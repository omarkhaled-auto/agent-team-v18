"""Phase 4.4 of the pipeline upgrade — failure_reason on wave-fail + deterministic forensics.

Plan: ``docs/plans/2026-04-26-pipeline-upgrade-phase4.md`` §G (Phase 4.4).

Phase 4.4 closes two risks surfaced by the 2026-04-26 M1 hardening smoke:

* **Risk #18** — ``failure_reason`` not persisted on wave-fail. Phase 1.6
  added the field on ``RunState.milestone_progress`` but only wired it
  via ``_handle_audit_failure_milestone_anchor`` (audit-fail). The
  wave-fail FAILED-mark site at ``cli.py`` left
  ``milestone_progress[id] = {"status": "FAILED"}`` with no reason,
  making post-hoc forensics blind to which path caused the failure.
* **Risk #19** — ``_run_failed_milestone_audit_if_enabled`` would fire
  the LLM forensics audit on milestone-FAILED regardless of the failure
  mode. On wave-fail, the audited code is known-broken; findings reduce
  to "stuff is broken" and the dispatch burns ~$5-8 producing
  foregone-conclusion forensics.

Phase 4.4 ships:

1. ``failure_reason="wave_<X>_failed"`` wiring at the wave-fail
   FAILED-mark site, symmetric to Phase 1.6's audit-fail wiring.
2. ``wave_failure_forensics`` — a NEW module that composes a
   deterministic ``WaveFailureForensics`` dataclass from already-captured
   signal (Phase 4.1's per-service self-verify error + Phase 4.2's
   structured retry feedback + Phase 4.3's owner_wave-tagged findings)
   and writes ``.agent-team/WAVE_FAILURE_FORENSICS.json``.
3. ``_run_failed_milestone_audit_if_enabled`` — gains an optional
   ``wave_result`` kwarg; when supplied and ``success=False`` AND the
   new ``failed_milestone_audit_on_wave_fail_enabled`` kill switch is at
   its default OFF, writes the forensics JSON and returns early
   (skipping the LLM audit).
4. ``AuditTeamConfig.failed_milestone_audit_on_wave_fail_enabled`` —
   default ``False`` (skip LLM audit on wave-fail). Flip to ``True`` to
   restore the always-fire-LLM behaviour (e.g. when Phase 4.5 lifts
   Risk #1 and audit-fix becomes the recovery path).

Each fixture below targets one acceptance criterion from §G AC1..AC5,
plus three defensive fixtures (Phase 4.3 owner_wave aggregation, the
empty-WAVE-FINDINGS fallback, and the no-codex-protocol-log defensive
path).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "smoke_2026_04_26"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeWaveFinding:
    """Minimal stand-in for ``wave_executor.WaveFinding``."""

    code: str
    severity: str = "HIGH"
    file: str = ""
    line: int = 0
    message: str = ""


@dataclass
class _FakeWaveResult:
    """Minimal stand-in for ``wave_executor.WaveResult``."""

    wave: str = ""
    success: bool = True
    error_message: str = ""
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    findings: list[_FakeWaveFinding] = field(default_factory=list)
    last_retry_prompt_suffix: str = ""


@dataclass
class _FakeMilestoneWaveResult:
    """Minimal stand-in for ``wave_executor.MilestoneWaveResult``."""

    milestone_id: str = ""
    template: str = "full_stack"
    waves: list[_FakeWaveResult] = field(default_factory=list)
    total_cost: float = 0.0
    success: bool = True
    error_wave: str = ""


def _build_wave_b_failed_milestone_result() -> _FakeMilestoneWaveResult:
    """Mirror the 2026-04-26 smoke shape: Wave B failed after 3 attempts."""
    wave_b = _FakeWaveResult(
        wave="B",
        success=False,
        error_message=(
            "Wave B self-verify failed after 3 attempt(s): "
            "0 violation(s), 1 build failure(s)."
        ),
        files_created=["apps/api/src/main.ts", "apps/api/src/app.module.ts"],
        files_modified=["package.json", "docker-compose.yml"],
        findings=[
            _FakeWaveFinding(
                code="WAVE-B-SELF-VERIFY",
                severity="HIGH",
                file="api",
                line=0,
                message=(
                    "retry=0 violations=0 build_failures=1: "
                    "Docker build failures (per service):\n"
                    "- service=api duration_s=26.83\n"
                    "target api: failed to solve: process "
                    "\"/bin/sh -c pnpm --filter api build\" did not "
                    "complete successfully: exit code: 1"
                ),
            ),
            _FakeWaveFinding(
                code="WAVE-B-SELF-VERIFY",
                severity="HIGH",
                file="api",
                line=0,
                message=(
                    "retry=1 violations=0 build_failures=1: "
                    "Docker build failures (per service):\n"
                    "- service=api duration_s=29.05\n"
                    "target api: failed to solve: process "
                    "\"/bin/sh -c pnpm --filter api build\" did not "
                    "complete successfully: exit code: 1"
                ),
            ),
            _FakeWaveFinding(
                code="WAVE-B-SELF-VERIFY",
                severity="HIGH",
                file="web",
                line=0,
                message=(
                    "retry=2 violations=0 build_failures=1: "
                    "Docker build failures (per service):\n"
                    "- service=web duration_s=36.49\n"
                    "target web: failed to solve: process "
                    "\"/bin/sh -c pnpm --filter web build\" did not "
                    "complete successfully: exit code: 1"
                ),
            ),
        ],
        last_retry_prompt_suffix=(
            "<previous_attempt_failed>\n"
            "Wave B retry=2: docker compose build web failed.\n"
            "service=web stderr (truncated): target web: failed to solve: "
            "process \"/bin/sh -c pnpm --filter web build\" did not complete "
            "successfully: exit code: 1\n"
            "</previous_attempt_failed>"
        ),
    )
    return _FakeMilestoneWaveResult(
        milestone_id="milestone-1",
        template="full_stack",
        waves=[wave_b],
        total_cost=0.969036,
        success=False,
        error_wave="B",
    )


def _build_audit_team_config(*, on_wave_fail_enabled: bool = False) -> Any:
    """Return an ``AuditTeamConfig`` shape for the helper-gating fixtures."""
    from agent_team_v15.config import AuditTeamConfig

    cfg = AuditTeamConfig()
    cfg.enabled = True
    cfg.failed_milestone_audit_on_wave_fail_enabled = on_wave_fail_enabled
    return cfg


def _build_full_config_with_v18(*, on_wave_fail_enabled: bool = False) -> Any:
    """Build a full ``AgentTeamConfig`` with v18.reaudit_trigger_fix_enabled=True.

    Required so the wave-fail bypass branch is reachable inside
    ``_run_failed_milestone_audit_if_enabled`` (the helper short-circuits
    on the v18 gate before checking wave_result).
    """
    from agent_team_v15.config import AgentTeamConfig

    cfg = AgentTeamConfig()
    cfg.audit_team.enabled = True
    cfg.audit_team.failed_milestone_audit_on_wave_fail_enabled = (
        on_wave_fail_enabled
    )
    cfg.v18.reaudit_trigger_fix_enabled = True
    return cfg


# ---------------------------------------------------------------------------
# AC1 — Wave-fail FAILED-mark site passes failure_reason="wave_<X>_failed"
# ---------------------------------------------------------------------------


def test_update_milestone_progress_wave_fail_writes_failure_reason() -> None:
    """Phase 4.4 AC1 — the persistence contract for wave-letter-specific reasons.

    Phase 1.6 already locks the keyword-only ``failure_reason`` kwarg on
    ``update_milestone_progress``. Phase 4.4 reuses it without altering
    the signature; the wave-letter-specific reason is emitted by the
    cli.py wave-fail FAILED-mark site (not by this helper). This fixture
    locks the persistence layer so any drift in Phase 1.6's contract
    surfaces here too.
    """
    from agent_team_v15.state import RunState, update_milestone_progress

    state = RunState()
    update_milestone_progress(
        state, "milestone-1", "FAILED", failure_reason="wave_b_failed",
    )
    entry = state.milestone_progress["milestone-1"]
    assert entry["status"] == "FAILED"
    assert entry.get("failure_reason") == "wave_b_failed"
    assert "milestone-1" in state.failed_milestones


# ---------------------------------------------------------------------------
# AC2 — _run_failed_milestone_audit_if_enabled gates on wave_result.success
# ---------------------------------------------------------------------------


def test_run_failed_milestone_audit_if_enabled_skipped_on_wave_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.4 AC2 — wave-fail bypass writes forensics + skips LLM audit.

    With ``wave_result.success=False`` and the kill switch at its
    default OFF, the helper must NOT invoke ``_run_audit_loop`` (the
    LLM-driven audit dispatch). It must instead write
    ``WAVE_FAILURE_FORENSICS.json`` to the run-dir's ``.agent-team/``
    and return ``0.0`` cost.
    """
    from agent_team_v15 import cli as cli_mod

    audit_loop_called = {"count": 0}

    async def _fake_audit_loop(*args: Any, **kwargs: Any) -> tuple[None, float]:
        audit_loop_called["count"] += 1
        return None, 5.0

    monkeypatch.setattr(cli_mod, "_run_audit_loop", _fake_audit_loop)

    cwd = tmp_path / "run-dir"
    (cwd / ".agent-team").mkdir(parents=True)
    audit_dir = cwd / ".requirements" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    config = _build_full_config_with_v18(on_wave_fail_enabled=False)
    wave_result = _build_wave_b_failed_milestone_result()

    cost = asyncio.run(cli_mod._run_failed_milestone_audit_if_enabled(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="exhaustive",
        task_text="",
        requirements_path=str(audit_dir / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(cwd),
        wave_result=wave_result,
    ))

    assert cost == 0.0
    assert audit_loop_called["count"] == 0, "LLM audit must not fire on wave-fail"
    forensics_path = cwd / ".agent-team" / "WAVE_FAILURE_FORENSICS.json"
    assert forensics_path.is_file(), "WAVE_FAILURE_FORENSICS.json must be written"
    blob = json.loads(forensics_path.read_text(encoding="utf-8"))
    assert blob["failed_wave_letter"] == "B"
    assert blob["retry_count"] == 3
    assert blob["failure_reason"] == "wave_b_failed"


def test_run_failed_milestone_audit_if_enabled_still_fires_on_convergence_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.4 AC4 — convergence-fail path preserved.

    When ``wave_result.success=True`` (waves passed; convergence failed
    elsewhere — e.g., audit found regressions), the LLM audit dispatch
    fires as before and no WAVE_FAILURE_FORENSICS.json is written.
    """
    from agent_team_v15 import cli as cli_mod

    audit_loop_called = {"count": 0}

    async def _fake_audit_loop(*args: Any, **kwargs: Any) -> tuple[None, float]:
        audit_loop_called["count"] += 1
        return None, 4.2

    monkeypatch.setattr(cli_mod, "_run_audit_loop", _fake_audit_loop)

    cwd = tmp_path / "run-dir"
    (cwd / ".agent-team").mkdir(parents=True)
    audit_dir = cwd / ".requirements" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    config = _build_full_config_with_v18(on_wave_fail_enabled=False)
    convergence_pass_result = _FakeMilestoneWaveResult(
        milestone_id="milestone-1",
        template="full_stack",
        waves=[_FakeWaveResult(wave="B", success=True)],
        success=True,
        error_wave="",
    )

    cost = asyncio.run(cli_mod._run_failed_milestone_audit_if_enabled(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="exhaustive",
        task_text="",
        requirements_path=str(audit_dir / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(cwd),
        wave_result=convergence_pass_result,
    ))

    assert cost == 4.2
    assert audit_loop_called["count"] == 1, "LLM audit must fire on convergence-fail"
    forensics_path = cwd / ".agent-team" / "WAVE_FAILURE_FORENSICS.json"
    assert not forensics_path.exists(), (
        "Forensics must NOT be written on convergence-fail"
    )


def test_run_failed_milestone_audit_if_enabled_fires_on_wave_fail_when_kill_switch_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.4 AC2 rollback contract — flag flip restores legacy behaviour.

    When ``failed_milestone_audit_on_wave_fail_enabled=True``, the gate
    deactivates and the LLM audit dispatch fires on wave-fail. This is
    the rollback path documented in plan §G; Phase 4.5 may flip this on
    when audit-fix is wired as the wave-fail recovery path.
    """
    from agent_team_v15 import cli as cli_mod

    audit_loop_called = {"count": 0}

    async def _fake_audit_loop(*args: Any, **kwargs: Any) -> tuple[None, float]:
        audit_loop_called["count"] += 1
        return None, 7.7

    monkeypatch.setattr(cli_mod, "_run_audit_loop", _fake_audit_loop)

    cwd = tmp_path / "run-dir"
    (cwd / ".agent-team").mkdir(parents=True)
    audit_dir = cwd / ".requirements" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    config = _build_full_config_with_v18(on_wave_fail_enabled=True)
    wave_result = _build_wave_b_failed_milestone_result()

    cost = asyncio.run(cli_mod._run_failed_milestone_audit_if_enabled(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="exhaustive",
        task_text="",
        requirements_path=str(audit_dir / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(cwd),
        wave_result=wave_result,
    ))

    assert cost == 7.7
    assert audit_loop_called["count"] == 1


# ---------------------------------------------------------------------------
# AC3 — WaveFailureForensics schema covers Phase 4.1 + 4.2 + 4.3 outputs
# ---------------------------------------------------------------------------


def test_wave_failure_forensics_json_schema(tmp_path: Path) -> None:
    """Phase 4.4 AC3 — schema lock for downstream consumers.

    Locks every field on the ``WaveFailureForensics`` dataclass so a
    refactor that changes the JSON shape surfaces in this fixture (and
    not in a downstream consumer that silently breaks).
    """
    from agent_team_v15.wave_failure_forensics import (
        WaveFailureForensics,
        build_wave_failure_forensics,
        write_wave_failure_forensics,
    )

    wave_result = _build_wave_b_failed_milestone_result()
    forensics = build_wave_failure_forensics(
        wave_result=wave_result,
        run_state=None,
        wave_findings_path=None,
        codex_protocol_path=None,
        docker_compose_ps="api  Up\nweb  Restarting",
        failure_reason="wave_b_failed",
    )
    assert isinstance(forensics, WaveFailureForensics)
    assert forensics.failed_wave_letter == "B"
    assert forensics.retry_count == 3
    assert forensics.failure_reason == "wave_b_failed"
    assert forensics.timestamp  # ISO-8601 string set
    assert forensics.docker_compose_ps == "api  Up\nweb  Restarting"
    assert forensics.files_modified == [
        "apps/api/src/main.ts",
        "apps/api/src/app.module.ts",
        "package.json",
        "docker-compose.yml",
    ]
    # Phase 4.1 wired self_verify_error.file → service-name attribution.
    assert forensics.self_verify_error.get("file") == "web"
    assert "service=web" in forensics.self_verify_error.get("message", "")
    # Phase 4.2 wired structured_retry_feedback.payload → last retry suffix.
    payload = forensics.structured_retry_feedback.get("payload", "")
    assert "<previous_attempt_failed>" in payload
    assert forensics.structured_retry_feedback.get("wave_letter") == "B"
    assert forensics.structured_retry_feedback.get("retry_index") == 2

    out = write_wave_failure_forensics(
        forensics, agent_team_dir=tmp_path,
    )
    assert out == tmp_path / "WAVE_FAILURE_FORENSICS.json"
    assert out.is_file()
    blob = json.loads(out.read_text(encoding="utf-8"))
    expected_keys = {
        "failed_wave_letter",
        "retry_count",
        "self_verify_error",
        "structured_retry_feedback",
        "files_modified",
        "codex_protocol_log_tail",
        "docker_compose_ps",
        "owner_wave_findings_count_per_wave",
        "failure_reason",
        "timestamp",
    }
    assert set(blob.keys()) == expected_keys
    # JSON is sorted-keys + indented for forensics readability
    assert "\n" in out.read_text(encoding="utf-8")
    assert '"failed_wave_letter":' in out.read_text(encoding="utf-8")


def test_wave_failure_forensics_includes_phase4_3_owner_wave_attribution() -> None:
    """Phase 4.4 AC3 — Phase 4.3 owner_wave attribution feeds the forensics.

    When the caller supplies ``audit_findings`` (Phase 4.3-tagged with
    ``owner_wave``), ``owner_wave_findings_count_per_wave`` aggregates
    by counting findings per owner wave letter. Used post-hoc by
    operators to see how the failed wave's blast radius distributes
    across the milestone's wave-set.
    """
    from agent_team_v15.audit_models import AuditFinding
    from agent_team_v15.wave_failure_forensics import build_wave_failure_forensics

    # ``AuditFinding`` carries paths via ``evidence`` rather than a
    # dedicated field; round-trip through ``from_dict`` so the Phase 4.3
    # ``owner_wave`` derivation runs through the canonical path.
    findings = [
        AuditFinding.from_dict({
            "file_path": "apps/web/src/middleware.ts", "owner_wave": "D",
        }),
        AuditFinding.from_dict({
            "file_path": "apps/web/src/app/layout.tsx", "owner_wave": "D",
        }),
        AuditFinding.from_dict({
            "file_path": "apps/web/src/i18n/index.ts", "owner_wave": "D",
        }),
        AuditFinding.from_dict({
            "file_path": "packages/api-client", "owner_wave": "C",
        }),
        AuditFinding.from_dict({
            "file_path": "prisma/schema.prisma", "owner_wave": "B",
        }),
        AuditFinding.from_dict({
            "file_path": "apps/api/Dockerfile", "owner_wave": "B",
        }),
        AuditFinding.from_dict({
            "file_path": "package.json", "owner_wave": "wave-agnostic",
        }),
    ]
    wave_result = _build_wave_b_failed_milestone_result()
    forensics = build_wave_failure_forensics(
        wave_result=wave_result,
        run_state=None,
        audit_findings=findings,
        wave_findings_path=None,
        codex_protocol_path=None,
        docker_compose_ps=None,
        failure_reason="wave_b_failed",
    )
    assert forensics.owner_wave_findings_count_per_wave == {
        "B": 2,
        "C": 1,
        "D": 3,
        "wave-agnostic": 1,
    }


def test_wave_failure_forensics_falls_back_to_wave_findings_when_no_audit(
    tmp_path: Path,
) -> None:
    """Phase 4.4 AC3 fallback — use WAVE_FINDINGS.json before audit fires.

    On wave-fail in the hot path, no AUDIT_REPORT.json exists yet (the
    audit phase fires post-success). The forensics fallback aggregates
    finding counts from WAVE_FINDINGS.json (already on disk), keyed by
    the per-finding ``wave`` field. Closes the data gap so operators
    see *some* wave-attribution distribution even on the fastest
    wave-fail.
    """
    from agent_team_v15.wave_failure_forensics import build_wave_failure_forensics

    wave_findings_path = tmp_path / "WAVE_FINDINGS.json"
    wave_findings_path.write_text(
        json.dumps({
            "milestone_id": "milestone-1",
            "findings": [
                {"wave": "A", "code": "STACK-IMPORT-002", "severity": "HIGH"},
                {"wave": "B", "code": "WAVE-B-SELF-VERIFY", "file": "api"},
                {"wave": "B", "code": "WAVE-B-SELF-VERIFY", "file": "api"},
                {"wave": "B", "code": "WAVE-B-SELF-VERIFY", "file": "web"},
            ],
        }),
        encoding="utf-8",
    )
    wave_result = _build_wave_b_failed_milestone_result()
    forensics = build_wave_failure_forensics(
        wave_result=wave_result,
        run_state=None,
        audit_findings=None,
        wave_findings_path=wave_findings_path,
        codex_protocol_path=None,
        docker_compose_ps=None,
        failure_reason="wave_b_failed",
    )
    assert forensics.owner_wave_findings_count_per_wave == {"A": 1, "B": 3}


# ---------------------------------------------------------------------------
# AC4-adjacent — defensive paths
# ---------------------------------------------------------------------------


def test_wave_failure_forensics_handles_missing_codex_protocol_log(
    tmp_path: Path,
) -> None:
    """Defensive: missing log path leaves the field empty without crashing.

    Codex protocol capture is opt-in (``v18.codex_protocol_capture_enabled``).
    On smokes that don't enable capture, the path doesn't exist; the
    forensics builder must return cleanly with ``codex_protocol_log_tail=""``.
    """
    from agent_team_v15.wave_failure_forensics import build_wave_failure_forensics

    wave_result = _build_wave_b_failed_milestone_result()
    forensics = build_wave_failure_forensics(
        wave_result=wave_result,
        run_state=None,
        wave_findings_path=None,
        codex_protocol_path=tmp_path / "does-not-exist.log",
        docker_compose_ps=None,
        failure_reason="wave_b_failed",
    )
    assert forensics.codex_protocol_log_tail == ""


def test_wave_failure_forensics_truncates_codex_protocol_log_to_tail(
    tmp_path: Path,
) -> None:
    """Defensive: large protocol logs are tailed to a bounded size.

    Smoke logs can be 4MB+; the forensics file should stay forensics-sized
    not log-sized.
    """
    from agent_team_v15.wave_failure_forensics import build_wave_failure_forensics

    log_path = tmp_path / "milestone-1-wave-B-protocol.log"
    head_marker = "HEAD-MARKER-" + ("X" * 100)
    tail_marker = "TAIL-MARKER-" + ("Y" * 100)
    middle = "M" * (50 * 1024)  # 50KB filler
    log_path.write_text(head_marker + middle + tail_marker, encoding="utf-8")

    wave_result = _build_wave_b_failed_milestone_result()
    forensics = build_wave_failure_forensics(
        wave_result=wave_result,
        run_state=None,
        wave_findings_path=None,
        codex_protocol_path=log_path,
        codex_log_tail_bytes=1024,
        docker_compose_ps=None,
        failure_reason="wave_b_failed",
    )
    assert "TAIL-MARKER" in forensics.codex_protocol_log_tail
    assert "HEAD-MARKER" not in forensics.codex_protocol_log_tail
    assert len(forensics.codex_protocol_log_tail.encode("utf-8")) <= 1024


# ---------------------------------------------------------------------------
# AC5 — Replay smoke: 2026-04-26 simulation reproduces expected forensics
# ---------------------------------------------------------------------------


def test_replay_smoke_2026_04_26_skips_audit_pass_on_wave_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4.4 AC5 — replay against the frozen smoke evidence.

    Recreates the 2026-04-26 M1 smoke shape (Wave B failed after 3
    retries) using the frozen ``WAVE_FINDINGS.json`` and asserts that
    Phase 4.4's gate would have skipped the LLM audit dispatch (the
    ~$5-8 / 1100s+ Agent dispatch cost cited in the smoke landing
    memo). Forensics file content matches Phase 4.1 per-service
    attribution + WAVE_FINDINGS-fallback owner_wave aggregation.
    """
    from agent_team_v15 import cli as cli_mod

    audit_loop_called = {"count": 0, "cost": 6.5}

    async def _fake_audit_loop(*args: Any, **kwargs: Any) -> tuple[None, float]:
        audit_loop_called["count"] += 1
        return None, audit_loop_called["cost"]

    monkeypatch.setattr(cli_mod, "_run_audit_loop", _fake_audit_loop)

    # Stage the smoke evidence into a fresh run-dir layout.
    cwd = tmp_path / "smoke-replay"
    agent_team_dir = cwd / ".agent-team"
    milestone_dir = cwd / ".requirements" / "milestones" / "milestone-1"
    milestone_audit_dir = milestone_dir / ".agent-team"
    agent_team_dir.mkdir(parents=True)
    milestone_audit_dir.mkdir(parents=True)
    (agent_team_dir / "WAVE_FINDINGS.json").write_text(
        (FIXTURE_ROOT / "WAVE_FINDINGS.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    config = _build_full_config_with_v18(on_wave_fail_enabled=False)
    wave_result = _build_wave_b_failed_milestone_result()

    cost = asyncio.run(cli_mod._run_failed_milestone_audit_if_enabled(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="exhaustive",
        task_text="",
        requirements_path=str(milestone_audit_dir / "REQUIREMENTS.md"),
        audit_dir=str(milestone_audit_dir),
        cwd=str(cwd),
        wave_result=wave_result,
    ))

    # ~$5-8 saved on simulated wave-fail
    assert cost == 0.0
    assert audit_loop_called["count"] == 0
    forensics_path = agent_team_dir / "WAVE_FAILURE_FORENSICS.json"
    assert forensics_path.is_file()
    blob = json.loads(forensics_path.read_text(encoding="utf-8"))
    assert blob["failed_wave_letter"] == "B"
    assert blob["retry_count"] == 3
    # Phase 4.1's per-service attribution: retry=2 failed on service=web.
    assert blob["self_verify_error"]["file"] == "web"
    assert "service=web" in blob["self_verify_error"]["message"]
    # Phase 4.3 fallback: WAVE_FINDINGS.json carries wave-letter attribution
    # for the per-attempt self-verify entries (1 from Wave A + 3 from Wave B).
    assert blob["owner_wave_findings_count_per_wave"] == {"A": 1, "B": 3}
    assert blob["failure_reason"] == "wave_b_failed"


# ---------------------------------------------------------------------------
# Cross-phase invariant — Phase 4.4 config flag default matches plan §G
# ---------------------------------------------------------------------------


def test_audit_team_config_default_failed_milestone_audit_on_wave_fail_is_false() -> None:
    """Phase 4.4 default — the kill switch is OFF (Phase 4.4 forensics path)."""
    from agent_team_v15.config import AuditTeamConfig

    cfg = AuditTeamConfig()
    assert cfg.failed_milestone_audit_on_wave_fail_enabled is False
