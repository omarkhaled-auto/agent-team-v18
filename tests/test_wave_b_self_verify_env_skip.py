"""Tests for Wave B self-verify's env_unavailable skip path.

Context
-------
When the Docker daemon is unreachable (Docker Desktop crashed, WSL backend
degraded, etc.), ``docker_build`` would normally return build failures that
look identical to a broken Dockerfile. The wave_executor retry loop would
then re-dispatch Wave B to Codex with error context, burning a Codex turn
on a problem Codex can't fix (it's environmental).

In R1B1-server-req-fix (2026-04-22) this exact scenario played out: Docker
daemon was returning 500s at ``/_ping``, self-verify reported build failure,
wave_executor re-dispatched Wave B, and the re-dispatched turn wedged on
``todo_list item_1`` for 620s (the orphan-tool watchdog fired).

Fix
---
``run_wave_b_acceptance_test`` now checks ``check_docker_available()`` BEFORE
attempting docker_build. If the daemon is down, it returns
``WaveBVerifyResult(passed=False, env_unavailable=True, ...)``. The caller
(wave_executor.py self-verify retry loop) detects ``env_unavailable`` and
breaks out with a WAVE-B-SELF-VERIFY-SKIPPED-ENV finding, WITHOUT retrying.

These tests pin both layers:

1. ``run_wave_b_acceptance_test`` returns env_unavailable=True when
   ``check_docker_available`` returns False (daemon down).
2. When daemon is up, the normal acceptance path runs.
3. ``WaveBVerifyResult.env_unavailable`` default is False (back-compat).
4. The skip path reports no violations/build_failures (honest zero).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15 import wave_b_self_verify as mod
from agent_team_v15.wave_b_self_verify import WaveBVerifyResult, run_wave_b_acceptance_test


def _write_min_compose(tmp_path: Path) -> None:
    """Write a compose file so the ``compose_file is None`` early-return
    doesn't short-circuit the daemon check."""
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: .\n",
        encoding="utf-8",
    )


def test_env_unavailable_default_is_false() -> None:
    """Back-compat: existing callers unaware of env_unavailable see False."""
    result = WaveBVerifyResult(passed=True)
    assert result.env_unavailable is False


def test_skip_when_docker_daemon_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When check_docker_available() returns False, self-verify MUST return
    env_unavailable=True and MUST NOT invoke docker_build (which would fail
    in a way indistinguishable from a Dockerfile bug)."""
    _write_min_compose(tmp_path)

    def _daemon_down() -> bool:
        return False

    docker_build_called = {"count": 0}

    def _docker_build_should_not_run(*args, **kwargs):
        docker_build_called["count"] += 1
        raise AssertionError("docker_build must not run when daemon is unreachable")

    monkeypatch.setattr(mod, "check_docker_available", _daemon_down)
    monkeypatch.setattr(mod, "docker_build", _docker_build_should_not_run)

    result = run_wave_b_acceptance_test(tmp_path, autorepair=True, timeout_seconds=60)

    assert result.env_unavailable is True
    assert result.passed is False
    assert "unreachable" in result.error_summary.lower()
    assert result.violations == []
    assert result.build_failures == []
    assert docker_build_called["count"] == 0


def test_normal_path_runs_when_docker_daemon_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When daemon is up, the acceptance test proceeds with docker_build."""
    _write_min_compose(tmp_path)

    monkeypatch.setattr(mod, "check_docker_available", lambda: True)

    monkeypatch.setattr(
        mod,
        "validate_compose_build_context",
        lambda compose_file, autorepair, project_root: [],
    )

    build_calls = {"count": 0}

    def _fake_docker_build(cwd, compose_file, timeout, *, services=None):
        build_calls["count"] += 1
        return []

    monkeypatch.setattr(mod, "docker_build", _fake_docker_build)

    result = run_wave_b_acceptance_test(tmp_path, autorepair=True, timeout_seconds=60)

    assert result.env_unavailable is False
    assert result.passed is True
    assert build_calls["count"] == 1


def test_compose_absent_still_passes_without_daemon_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no compose file exists, we skip early (no-docker milestone) and
    don't even need to probe the daemon. Behaviour unchanged from pre-fix."""
    daemon_probe_called = {"count": 0}

    def _probe() -> bool:
        daemon_probe_called["count"] += 1
        return True

    monkeypatch.setattr(mod, "check_docker_available", _probe)

    result = run_wave_b_acceptance_test(tmp_path, autorepair=True, timeout_seconds=60)

    assert result.passed is True
    assert result.env_unavailable is False
    assert daemon_probe_called["count"] == 0


def test_skip_has_no_retry_prompt_suffix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """env_unavailable skip path must not produce a retry_prompt_suffix —
    otherwise a caller that ignores env_unavailable might still feed a
    prompt back to Codex and trigger the exact wedge this fix prevents."""
    _write_min_compose(tmp_path)
    monkeypatch.setattr(mod, "check_docker_available", lambda: False)
    monkeypatch.setattr(
        mod,
        "docker_build",
        lambda *a, **k: pytest.fail("docker_build must not run"),
    )

    result = run_wave_b_acceptance_test(tmp_path, autorepair=True, timeout_seconds=60)

    assert result.env_unavailable is True
    assert result.retry_prompt_suffix == ""
