"""Phase H1a Item 5 — endpoint_prober probe spec-oracle guard.

Flag-gated (``v18.probe_spec_oracle_enabled``) check at the TOP of
``_detect_app_url``. If the milestone REQUIREMENTS.md DoD port drifts
from the resolved code-side port, raise ``ProbeSpecDriftError`` at
~T+1s instead of letting the probe eat a 120s health-check timeout.

The guard:
* PASSes silently when DoD port == code port.
* Raises on drift (DoD=3080, code=4000 in smoke #11).
* WARNs and falls through when DoD port isn't parseable.
* Silently falls through when REQUIREMENTS.md is missing.
* Is a no-op when the config flag is off.
* Skips when milestone_id is None (can't find REQUIREMENTS.md).
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_team_v15.endpoint_prober import (
    ProbeSpecDriftError,
    _detect_app_url,
)


def _cfg(app_port: int = 0, oracle_on: bool = True) -> Any:
    v18 = SimpleNamespace(probe_spec_oracle_enabled=oracle_on)

    class C:
        class browser_testing:
            pass

    C.browser_testing.app_port = app_port
    C.v18 = v18
    return C


def _write_requirements(
    workspace: Path, milestone_id: str, body: str
) -> None:
    d = workspace / ".agent-team" / "milestones" / milestone_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "REQUIREMENTS.md").write_text(body, encoding="utf-8")


def _dod_block(port: int) -> str:
    return (
        "# M1\n\n## Definition of Done\n\n"
        f"- `GET http://localhost:{port}/api/health` returns ok.\n"
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_dod_and_code_port_match_proceeds(tmp_path: Path) -> None:
    _write_requirements(tmp_path, "milestone-1", _dod_block(4000))
    (tmp_path / ".env").write_text("PORT=4000\n", encoding="utf-8")

    url = _detect_app_url(tmp_path, _cfg(oracle_on=True), milestone_id="milestone-1")
    assert url == "http://localhost:4000"


# ---------------------------------------------------------------------------
# Drift — the smoke #11 case
# ---------------------------------------------------------------------------


def test_drift_between_dod_and_code_raises_fast(tmp_path: Path) -> None:
    """Smoke #11: DoD says 3080, .env PORT=4000. Spec-oracle must raise
    ProbeSpecDriftError immediately — no 120s health-check timeout."""

    _write_requirements(tmp_path, "milestone-1", _dod_block(3080))
    (tmp_path / ".env").write_text("PORT=4000\n", encoding="utf-8")

    with pytest.raises(ProbeSpecDriftError) as excinfo:
        _detect_app_url(
            tmp_path, _cfg(oracle_on=True), milestone_id="milestone-1"
        )
    err = excinfo.value
    assert err.dod_port == 3080
    assert err.code_port == 4000
    assert err.requirements_path.is_file()
    assert "PROBE-SPEC-DRIFT-001" in str(err)


# ---------------------------------------------------------------------------
# Degraded inputs
# ---------------------------------------------------------------------------


def test_dod_port_unparseable_warns_and_proceeds(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write_requirements(
        tmp_path,
        "milestone-1",
        "# M1\n\n## Definition of Done\n\n- Hits `GET /api/health`; no URL.\n",
    )
    (tmp_path / ".env").write_text("PORT=4000\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="agent_team_v15.endpoint_prober"):
        url = _detect_app_url(
            tmp_path, _cfg(oracle_on=True), milestone_id="milestone-1"
        )
    assert url == "http://localhost:4000"
    assert any(
        "DoD port not parseable" in rec.getMessage()
        or "spec-oracle" in rec.getMessage()
        for rec in caplog.records
    ), f"expected spec-oracle WARN; got: {[r.getMessage() for r in caplog.records]}"


def test_requirements_md_missing_proceeds(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PORT=4000\n", encoding="utf-8")
    url = _detect_app_url(
        tmp_path, _cfg(oracle_on=True), milestone_id="milestone-1"
    )
    assert url == "http://localhost:4000"


def test_milestone_id_none_skips_guard(tmp_path: Path) -> None:
    """No milestone_id → can't resolve REQUIREMENTS.md → guard no-op."""

    (tmp_path / ".env").write_text("PORT=4000\n", encoding="utf-8")
    url = _detect_app_url(tmp_path, _cfg(oracle_on=True), milestone_id=None)
    assert url == "http://localhost:4000"


# ---------------------------------------------------------------------------
# Flag off — legacy behaviour
# ---------------------------------------------------------------------------


def test_oracle_disabled_preserves_legacy_precedence(tmp_path: Path) -> None:
    """With the flag off, legacy silent-first-source-wins behaviour is
    preserved — no drift detection, no exception."""

    _write_requirements(tmp_path, "milestone-1", _dod_block(3080))
    (tmp_path / ".env").write_text("PORT=4000\n", encoding="utf-8")

    url = _detect_app_url(
        tmp_path, _cfg(oracle_on=False), milestone_id="milestone-1"
    )
    assert url == "http://localhost:4000"


def test_oracle_disabled_with_milestone_id_still_skips(tmp_path: Path) -> None:
    """Even if the caller passes milestone_id, the flag-off path must
    not consult REQUIREMENTS.md at all."""

    _write_requirements(tmp_path, "milestone-1", _dod_block(3080))
    (tmp_path / "apps" / "api" / "src").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "src" / "main.ts").write_text(
        "await app.listen(4000);\n", encoding="utf-8"
    )
    url = _detect_app_url(
        tmp_path, _cfg(oracle_on=False), milestone_id="milestone-1"
    )
    assert url == "http://localhost:4000"


# ---------------------------------------------------------------------------
# Crash-isolation regression (Finding 2 of PR #42 review)
# ---------------------------------------------------------------------------
#
# The initial h1a wiring let ProbeSpecDriftError propagate out of
# start_docker_for_probing into _run_wave_b_probing and up into the live
# executor path at wave_executor.py:4867. With the flag on, real drift
# would abort the executor instead of producing a normal failed Wave B
# result. start_docker_for_probing must convert the drift into a
# structured DockerContext with startup_error populated (so
# _run_wave_b_probing's existing `if not docker_ctx.api_healthy` handles
# it), not raise.


def test_start_docker_for_probing_converts_drift_to_structured_failure(
    tmp_path: Path,
) -> None:
    import asyncio

    from agent_team_v15.endpoint_prober import start_docker_for_probing

    _write_requirements(tmp_path, "milestone-1", _dod_block(3080))
    (tmp_path / ".env").write_text("PORT=4000\n", encoding="utf-8")

    ctx = asyncio.run(
        start_docker_for_probing(
            str(tmp_path),
            _cfg(oracle_on=True),
            milestone_id="milestone-1",
        )
    )
    # Must not raise. Must return a DockerContext with a structured
    # startup_error pointing at PROBE-SPEC-DRIFT-001 and api_healthy=False.
    assert ctx.api_healthy is False
    assert ctx.infra_missing is False, (
        "drift is a real failure signal, not an infra-skip — must block "
        "the wave, not fall through to 'external app' handling"
    )
    assert "PROBE-SPEC-DRIFT-001" in (ctx.startup_error or "")
    assert "3080" in (ctx.startup_error or "")
    assert "4000" in (ctx.startup_error or "")
