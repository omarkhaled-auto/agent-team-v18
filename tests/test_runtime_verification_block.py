"""Tests for D-02 — runtime verification graceful-block.

Covers ``run_runtime_verification``'s new ``health`` / ``block_reason``
/ ``details`` fields. Before D-02 the function silently returned an
empty ``RuntimeReport`` whenever Docker or the compose file was
missing, and the markdown report read "runtime verification skipped"
— indistinguishable from an intentional opt-out. With D-02 the
behaviour splits:

- ``live_endpoint_check=False`` → ``health="skipped"`` (legacy).
- ``live_endpoint_check=True`` + infra missing → ``health="blocked"``
  with a structured ``block_reason``.
- ``live_endpoint_check=True`` + live app reachable → ``health="external_app"``
  (no Docker boot needed).

All subprocess and network calls are mocked — no real Docker or HTTP
traffic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15 import runtime_verification as rv
from agent_team_v15.runtime_verification import (
    RuntimeReport,
    run_runtime_verification,
    format_runtime_report,
    _probe_live_app,
)


# ---------------------------------------------------------------------------
# 1. Compose missing + live_endpoint_check=True → health=blocked
# ---------------------------------------------------------------------------


def test_compose_missing_live_check_opt_in_blocks(tmp_path: Path) -> None:
    """Opt-in to live endpoint verification + no compose + no live app
    → ``health="blocked"`` with ``block_reason="compose_file_missing"``.
    This is the build-j scenario: the pipeline must halt, not silently
    degrade."""
    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=None), \
         patch.object(rv, "_probe_live_app", return_value=False):
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=True,
            live_app_url="http://127.0.0.1:3001",
        )

    assert isinstance(report, RuntimeReport)
    assert report.health == "blocked"
    assert report.block_reason == "compose_file_missing"
    assert report.details["live_endpoint_check"] is True
    assert report.details["live_app_url_checked"] == "http://127.0.0.1:3001"
    assert report.details["live_app_reachable"] is False


# ---------------------------------------------------------------------------
# 2. Compose missing + live_endpoint_check=False → health=skipped
# ---------------------------------------------------------------------------


def test_compose_missing_live_check_opt_out_skips(tmp_path: Path) -> None:
    """Legacy opt-out path preserved — caller didn't request live endpoint
    verification so the lack of compose is a silent ``skipped`` (not a
    block)."""
    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=None):
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=False,
        )
    assert report.health == "skipped"
    assert report.block_reason == ""


# ---------------------------------------------------------------------------
# 3. Docker unavailable + opt-in → blocked with docker_unavailable reason
# ---------------------------------------------------------------------------


def test_docker_unavailable_opt_in_blocks_with_docker_reason(
    tmp_path: Path,
) -> None:
    with patch.object(rv, "check_docker_available", return_value=False), \
         patch.object(rv, "_probe_live_app", return_value=False):
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=True,
            live_app_url="http://127.0.0.1:3001",
        )
    assert report.health == "blocked"
    assert report.block_reason == "docker_unavailable"
    assert report.details["live_app_reachable"] is False


# ---------------------------------------------------------------------------
# 4. Compose missing + live app reachable → external_app (use live app)
# ---------------------------------------------------------------------------


def test_compose_missing_live_app_reachable_uses_external_app(
    tmp_path: Path,
) -> None:
    """Opt-in + no compose + live app responds → ``health="external_app"``.
    No block, no Docker boot needed."""
    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=None), \
         patch.object(rv, "_probe_live_app", return_value=True) as probe:
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=True,
            live_app_url="http://127.0.0.1:3001",
        )
    assert report.health == "external_app"
    assert report.block_reason == ""
    assert report.details["live_app_reachable"] is True
    probe.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Structured details payload on blocked runs
# ---------------------------------------------------------------------------


def test_blocked_report_has_structured_details(tmp_path: Path) -> None:
    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "find_compose_file", return_value=None), \
         patch.object(rv, "_probe_live_app", return_value=False):
        report = run_runtime_verification(
            project_root=tmp_path,
            live_endpoint_check=True,
            live_app_url="http://127.0.0.1:4321",
            compose_override="docker/compose.yml",
        )
    details = report.details
    assert details["compose_path_checked"] == "docker/compose.yml"
    assert details["live_app_url_checked"] == "http://127.0.0.1:4321"
    assert details["live_endpoint_check"] is True
    assert details["live_app_reachable"] is False
    assert details["project_root"] == str(tmp_path)


# ---------------------------------------------------------------------------
# 6. format_runtime_report surfaces BLOCKED distinct from SKIPPED
# ---------------------------------------------------------------------------


def test_format_report_blocked_header_names_reason() -> None:
    report = RuntimeReport()
    report.health = "blocked"
    report.block_reason = "compose_file_missing"
    report.details = {
        "compose_path_checked": "",
        "live_app_url_checked": "http://127.0.0.1:3001",
        "live_app_reachable": False,
        "live_endpoint_check": True,
    }
    md = format_runtime_report(report)
    assert "BLOCKED" in md
    assert "`compose_file_missing`" in md
    assert "http://127.0.0.1:3001" in md
    # The legacy "runtime verification skipped" wording must NOT appear —
    # blocked runs are a distinct status.
    assert "runtime verification skipped" not in md.lower()


def test_format_report_skipped_keeps_legacy_wording() -> None:
    report = RuntimeReport()
    report.health = "skipped"
    # docker_available stays False (legacy path) — skipped banner survives.
    md = format_runtime_report(report)
    assert "Docker not available" in md or "docker-compose file" in md
    assert "skipped" in md.lower()
    assert "BLOCKED" not in md


def test_format_report_external_app_header() -> None:
    report = RuntimeReport()
    report.health = "external_app"
    report.details = {"live_app_url_checked": "http://127.0.0.1:8080"}
    md = format_runtime_report(report)
    assert "External app used" in md
    assert "http://127.0.0.1:8080" in md


# ---------------------------------------------------------------------------
# 7. _probe_live_app — pure unit coverage of the new helper
# ---------------------------------------------------------------------------


def test_probe_live_app_empty_url_returns_false() -> None:
    assert _probe_live_app("") is False
    assert _probe_live_app("   ") is False


def test_probe_live_app_success_returns_true() -> None:
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    with patch("urllib.request.urlopen", return_value=_Resp()):
        assert _probe_live_app("http://127.0.0.1:3001/health") is True


def test_probe_live_app_connection_error_returns_false() -> None:
    import urllib.error

    def _raise(*args, **kwargs):
        raise urllib.error.URLError("Connection refused")

    with patch("urllib.request.urlopen", _raise):
        assert _probe_live_app("http://127.0.0.1:3001") is False


def test_probe_live_app_treats_4xx_as_listening() -> None:
    import urllib.error

    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:3001", 404, "Not Found", {}, None
        )

    with patch("urllib.request.urlopen", _raise):
        # 404 means the server IS listening; still counts as alive.
        assert _probe_live_app("http://127.0.0.1:3001") is True


def test_probe_live_app_5xx_not_treated_as_listening() -> None:
    import urllib.error

    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:3001", 503, "Unavailable", {}, None
        )

    with patch("urllib.request.urlopen", _raise):
        # 5xx suggests a broken server — conservative: not "reachable".
        assert _probe_live_app("http://127.0.0.1:3001") is False
