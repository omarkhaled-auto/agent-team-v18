"""Phase 5.4 — cycle-1 fix-dispatch refactor + ``audit_fix_rounds`` increment.

Closes R-#35 (cycle-1 fix-dispatch guard at cli.py:8477) AND fully closes
R-#37 (``audit_fix_rounds`` field is dead-data) by wiring the per-
milestone incrementer Phase 5.3 shipped the slot for.

Plan: ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §G + §M.M3
+ §M.M14 + Phase 5.3 landing memo team-lead correction (AC8 / AC9
contract additions).

Coverage:

* AC1 — cycle 1 dirty audit dispatches fix.
* AC2 — cycle 1 clean audit terminates without dispatch.
* AC3 — full 3-cycle run with max_reaudit_cycles=3 → audit_fix_rounds=2.
* AC4 — Phase 4.5 epilogue contract preserved (re-self-verify still
  fires when wave_result.success is False AND no anchor restore fired).
* AC5 — Phase 1.5 ``CrossMilestoneLockViolation`` handling unchanged.
* AC6 — deferred to live closeout smoke per Phase 5.4 smoke policy.
* AC7 — ``--milestone-cost-cap-usd`` aborts the audit-fix loop with
  ``failure_reason="cost_cap_reached"``; second-check after dispatch
  catches the case where dispatch alone pushes ``total_cost`` over the
  cap (team-lead correction 2026-04-29).
* AC8 — increment contract: cycle N → ``audit_fix_rounds == N`` until
  ``max_reaudit_cycles`` (last cycle is audit-only / no dispatch).
* AC9 — REPLACE-preserve contract: terminal finalize after cycle N
  must thread ``audit_fix_rounds=N`` through every call site that
  fires after audit-fix can have run.
* §M.M14 #1 — full workspace rollback when fix dispatch introduces a
  new compile-profile diagnostic identity (file, line, code,
  normalized message).
* §M.M14 #2 — partial-success preserved when no new diagnostic appears
  (count or score may shift, but identity-set is a subset).
* §M.M14 #3 — regression detected by identity, not count: one old
  identity disappears + one new identity appears (count steady) → still
  rolls back.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from agent_team_v15 import cli as cli_module
from agent_team_v15 import audit_fix_rollback as rollback_module
from agent_team_v15.audit_fix_rollback import (
    DiagnosticIdentity,
    PreDispatchState,
    RollbackOutcome,
    detect_and_rollback_regression,
    diagnostics_to_identities_for_test,
)
from agent_team_v15.config import AgentTeamConfig, AuditTeamConfig
from agent_team_v15.state import (
    RunState,
    save_state,
    update_milestone_progress,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic AuditReport / AuditScore + mock dispatch fixtures
# ---------------------------------------------------------------------------


@dataclass
class _MockFinding:
    """Minimal Finding-shape stand-in for the audit-loop's read patterns.

    Fields ``verdict`` + ``primary_file`` are read by
    ``compute_reaudit_scope``. ``file_path`` is read by the audit-loop's
    snapshot site. Keep both populated.
    """

    severity: str = "HIGH"
    auditor: str = "audit-test"
    requirement_id: str = "AC-1"
    summary: str = "synthetic finding"
    file_path: str = "src/foo.ts"
    verdict: str = "FAIL"

    @property
    def primary_file(self) -> str:
        return self.file_path


@dataclass
class _MockScore:
    """Minimal AuditScore stand-in."""

    score: float = 612.0
    max_score: float = 1000.0
    critical_count: int = 3
    high_count: int = 10
    medium_count: int = 9
    low_count: int = 6
    health: str = "failed"


@dataclass
class _MockReport:
    """Minimal AuditReport stand-in for the audit-loop."""

    score: _MockScore = field(default_factory=_MockScore)
    findings: list[_MockFinding] = field(default_factory=list)
    cycle: int = 1
    extras: dict[str, Any] = field(default_factory=lambda: {"verdict": "FAIL"})

    def to_json(self, run_state: Any = None) -> str:
        return json.dumps({"score": {"score": self.score.score}})


def _make_clean_report() -> _MockReport:
    """Cycle-1-healthy shape: 0 critical, score 95."""
    return _MockReport(
        score=_MockScore(
            score=95.0, max_score=100.0,
            critical_count=0, high_count=0, medium_count=0, low_count=0,
            health="healthy",
        ),
        findings=[],
        cycle=1,
        extras={"verdict": "PASS"},
    )


def _make_dirty_report(cycle: int = 1, score_value: float = 60.0) -> _MockReport:
    """Cycle-N-dirty shape: 3 critical, score 60%."""
    return _MockReport(
        score=_MockScore(
            score=score_value, max_score=100.0,
            critical_count=3, high_count=10, medium_count=9, low_count=6,
            health="failed",
        ),
        findings=[
            _MockFinding(severity="CRITICAL", file_path="src/foo.ts"),
            _MockFinding(severity="HIGH", file_path="src/bar.ts"),
            _MockFinding(severity="HIGH", file_path="src/baz.ts"),
        ],
        cycle=cycle,
        extras={"verdict": "FAIL"},
    )


def _make_config(
    *,
    max_cycles: int = 3,
    cost_cap_usd: float = 0.0,
    score_healthy_threshold: float = 90.0,
) -> AgentTeamConfig:
    """Construct a minimal AgentTeamConfig for the audit-loop."""
    cfg = AgentTeamConfig()
    cfg.audit_team = AuditTeamConfig(
        enabled=True,
        max_reaudit_cycles=max_cycles,
        score_healthy_threshold=score_healthy_threshold,
        milestone_cost_cap_usd=cost_cap_usd,
    )
    return cfg


def _mock_run_milestone_audit_factory(
    reports: list[_MockReport], audit_cost: float = 0.5,
) -> Callable[..., Any]:
    """Build an async stub that yields one report per cycle (dispatched in
    order) until ``reports`` is exhausted."""
    state = {"index": 0, "calls": []}

    async def _stub(**kwargs):
        state["calls"].append({k: kwargs.get(k) for k in ("cycle", "auditors_override")})
        idx = state["index"]
        state["index"] += 1
        if idx >= len(reports):
            return None, audit_cost
        return reports[idx], audit_cost

    _stub._calls = state["calls"]  # type: ignore[attr-defined]
    return _stub


def _mock_run_audit_fix_unified_factory(
    fix_cost: float = 1.0,
    modified_files: list[str] | None = None,
    raise_lock_violation: bool = False,
) -> Callable[..., Any]:
    """Build an async stub for ``_run_audit_fix_unified``."""
    files = modified_files if modified_files is not None else ["src/foo.ts"]
    state = {"calls": 0}

    async def _stub(*args, **kwargs):
        state["calls"] += 1
        if raise_lock_violation:
            from agent_team_v15.fix_executor import CrossMilestoneLockViolation
            raise CrossMilestoneLockViolation(
                finding_id="F-001",
                regressed_acs={"AC-2"},
                regressed_tests={"test_foo"},
                finding_surface={"src/foo.ts"},
            )
        return list(files), fix_cost

    _stub._call_count = lambda: state["calls"]  # type: ignore[attr-defined]
    return _stub


def _patch_audit_loop(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reports: list[_MockReport],
    fix_cost: float = 1.0,
    modified_files: list[str] | None = None,
    raise_lock_violation: bool = False,
    audit_cost: float = 0.5,
    skip_workspace_rollback: bool = True,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Wire mocks for the audit-loop. Returns (audit_stub, fix_stub)."""
    audit_stub = _mock_run_milestone_audit_factory(reports, audit_cost=audit_cost)
    fix_stub = _mock_run_audit_fix_unified_factory(
        fix_cost=fix_cost,
        modified_files=modified_files,
        raise_lock_violation=raise_lock_violation,
    )
    monkeypatch.setattr(cli_module, "_run_milestone_audit", audit_stub)
    monkeypatch.setattr(cli_module, "_run_audit_fix_unified", fix_stub)

    if skip_workspace_rollback:
        # Most ACs don't exercise §M.M14 — stub the rollback module so the
        # tests don't try to run ``npx tsc`` during synthetic loops.
        async def _no_capture(_workspace_dir):
            # Return a state object that ``_detect_and_rollback_regression``
            # treats as "no rollback needed" — a frozen state with empty
            # diagnostics + ``available=True`` so post comparison sees
            # post == pre and reports rollback_fired=False.
            from agent_team_v15.audit_fix_rollback import PreDispatchState
            from agent_team_v15.wave_executor import WaveCheckpoint
            return PreDispatchState(
                workspace_dir=_workspace_dir,
                pre_checkpoint=WaveCheckpoint(wave="t", timestamp="t"),
                pre_snapshot={},
                pre_diagnostics=frozenset(),
                pre_diagnostics_available=False,
            )

        async def _no_rollback(_state):
            return RollbackOutcome(
                rollback_fired=False,
                pre_diagnostics_available=False,
                post_diagnostics_available=False,
                restore_skipped_reason="diagnostics_unavailable",
            )

        monkeypatch.setattr(cli_module, "capture_pre_dispatch_state", _no_capture, raising=False)
        monkeypatch.setattr(cli_module, "detect_and_rollback_regression", _no_rollback, raising=False)
        # The audit-loop imports lazily from ``audit_fix_rollback`` inside
        # the function body, so also stub at the source module.
        monkeypatch.setattr(rollback_module, "capture_pre_dispatch_state", _no_capture)
        monkeypatch.setattr(rollback_module, "detect_and_rollback_regression", _no_rollback)

    return audit_stub, fix_stub


def _mk_workspace(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# AC1 — cycle-1 dirty audit dispatches fix (R-#35 lift)
# ---------------------------------------------------------------------------


def test_ac1_cycle_1_findings_dispatch_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle 1 audit returns 28 FAIL findings (3 CRITICAL, score 60%);
    ``should_terminate_reaudit`` returns False (not healthy);
    ``_run_audit_fix_unified`` IS called with cycle=1.

    Closes R-#35 — pre-Phase-5.4 the cycle 1 fix dispatch was guarded
    behind ``if cycle > 1 and current_report:``. Post-Phase-5.4 cycle 1
    dispatches when findings warrant.
    """
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    # Cycle 1 audit returns dirty + cycle 2 audit also dirty (then loop
    # hits max_cycles=2 → terminate). Plus an extra report so the audit
    # at top of cycle 2 has something.
    audit_stub, fix_stub = _patch_audit_loop(
        monkeypatch,
        reports=[_make_dirty_report(cycle=1), _make_dirty_report(cycle=2, score_value=70.0)],
    )

    state = RunState(run_id="ac1", task="ac1")
    config = _make_config(max_cycles=2, cost_cap_usd=0.0)

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="ac1",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
    ))

    # Cycle 1 dispatched (R-#35 lift fires). Cycle 2 audited only (max
    # cycles → terminate before dispatch in the post-Phase-5.4 layout).
    assert fix_stub._call_count() == 1, (
        f"AC1: expected 1 dispatch (cycle 1 only with max_cycles=2); "
        f"got {fix_stub._call_count()}"
    )
    # audit_fix_rounds bumped to 1 by the cycle-1 dispatch.
    progress = state.milestone_progress.get("milestone-1", {})
    assert progress.get("audit_fix_rounds", 0) == 1, (
        f"AC1: expected audit_fix_rounds=1 after cycle-1 dispatch; "
        f"progress={progress}"
    )


# ---------------------------------------------------------------------------
# AC2 — cycle-1 clean audit terminates without dispatch
# ---------------------------------------------------------------------------


def test_ac2_cycle_1_clean_audit_skips_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle 1 audit returns clean (score 95% computed, 0 critical);
    ``should_terminate_reaudit`` returns True (Cond 1 healthy);
    ``_run_audit_fix_unified`` is NOT called; ``audit_fix_rounds``
    stays absent (sentinel-skip preserved)."""
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    audit_stub, fix_stub = _patch_audit_loop(
        monkeypatch,
        reports=[_make_clean_report()],
    )

    state = RunState(run_id="ac2", task="ac2")
    config = _make_config(max_cycles=3, cost_cap_usd=0.0)

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="ac2",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
    ))

    assert fix_stub._call_count() == 0, (
        f"AC2: cycle-1 healthy must NOT dispatch; got {fix_stub._call_count()}"
    )
    progress = state.milestone_progress.get("milestone-1", {})
    # Sentinel-skip: when no dispatch fires, the key MUST NOT be written
    # (preserves Phase 1.6 / 4.4 / 4.5 byte-shape).
    assert "audit_fix_rounds" not in progress, (
        f"AC2: expected ``audit_fix_rounds`` ABSENT after no-dispatch path; "
        f"progress={progress}"
    )


# ---------------------------------------------------------------------------
# AC3 — full 3-cycle run with max_reaudit_cycles=3
# ---------------------------------------------------------------------------


def test_ac3_full_three_cycle_run_increments_to_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cycle 1 dispatch + cycle 2 re-audit + cycle 2 dispatch + cycle 3
    audit hits max_cycles``. ``audit_fix_rounds == 2`` post-loop.

    Locks the AC3 contract: dispatch fires at the END of cycles 1 + 2;
    cycle 3 audits and terminates via ``Cond 2: cycle >= max_cycles``
    BEFORE dispatching.
    """
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    # Three audits across three cycles. Each progressively dirtier so
    # ``should_terminate_reaudit`` doesn't fire Cond 1 healthy and
    # doesn't spuriously fire Cond 4 critical-rise (we keep critical
    # counts steady).
    audit_stub, fix_stub = _patch_audit_loop(
        monkeypatch,
        reports=[
            _make_dirty_report(cycle=1, score_value=60.0),
            _make_dirty_report(cycle=2, score_value=70.0),
            _make_dirty_report(cycle=3, score_value=80.0),
        ],
    )

    state = RunState(run_id="ac3", task="ac3")
    config = _make_config(max_cycles=3, cost_cap_usd=0.0)

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="ac3",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
    ))

    assert fix_stub._call_count() == 2, (
        f"AC3: expected 2 dispatches across 3 cycles (last cycle audits "
        f"+ terminates via max_cycles before dispatch); got "
        f"{fix_stub._call_count()}"
    )
    progress = state.milestone_progress.get("milestone-1", {})
    assert progress.get("audit_fix_rounds", 0) == 2, (
        f"AC3: expected audit_fix_rounds=2 after 2 dispatches; progress={progress}"
    )


# ---------------------------------------------------------------------------
# AC4 — Phase 4.5 epilogue contract preserved
# ---------------------------------------------------------------------------


def test_ac4_phase_4_5_epilogue_runs_after_audit_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the audit-loop terminates non-FAILED AND ``wave_result`` was
    originally failed, the Phase 4.5 epilogue re-runs the per-wave self-
    verify. Locks the AC4 contract: epilogue presence + cascade quality
    gate consume ``current_report``.
    """
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    milestone_anchor_dir = agent_team_dir / "milestones" / "milestone-1" / "_anchor"
    milestone_anchor_dir.mkdir(parents=True)
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    # Cycle 1 dirty → dispatch → cycle 2 clean → terminate.
    audit_stub, fix_stub = _patch_audit_loop(
        monkeypatch,
        reports=[_make_dirty_report(cycle=1), _make_clean_report()],
    )

    # Stub the Phase 4.5 self-verify and cascade gate. The epilogue's
    # ``run_wave_d_acceptance_test`` import is local to the epilogue
    # block; patch the module attribute on the wave_d_self_verify module.
    self_verify_calls: list[Path] = []

    def _fake_d_acceptance(workspace_arg, **kwargs):
        self_verify_calls.append(Path(workspace_arg))
        return SimpleNamespace(passed=True, error_summary="")

    from agent_team_v15 import wave_d_self_verify
    monkeypatch.setattr(
        wave_d_self_verify, "run_wave_d_acceptance_test", _fake_d_acceptance,
    )

    # Stub cascade_quality_gate_blocks_complete to return clean.
    from agent_team_v15 import audit_team
    monkeypatch.setattr(
        audit_team, "cascade_quality_gate_blocks_complete",
        lambda report: (False, ""),
    )

    state = RunState(run_id="ac4", task="ac4")
    config = _make_config(max_cycles=2, cost_cap_usd=0.0)
    wave_result = SimpleNamespace(success=False, error_wave="D")

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="ac4",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
        milestone_anchor_dir=str(milestone_anchor_dir),
        wave_result=wave_result,
    ))

    # Phase 4.5 epilogue fired (re-self-verify D ran).
    assert len(self_verify_calls) == 1, (
        f"AC4: expected Phase 4.5 epilogue to run wave_d acceptance once; "
        f"got {len(self_verify_calls)}"
    )
    # Cascade-COMPLETE branch fired (cascade gate clean) → milestone
    # COMPLETE with failure_reason=wave_fail_recovered AND audit_fix_rounds=1.
    progress = state.milestone_progress.get("milestone-1", {})
    assert progress.get("status") == "COMPLETE", (
        f"AC4: expected COMPLETE post-cascade; progress={progress}"
    )
    assert progress.get("failure_reason") == "wave_fail_recovered", (
        f"AC4: expected failure_reason=wave_fail_recovered; progress={progress}"
    )
    assert progress.get("audit_fix_rounds") == 1, (
        f"AC4: expected REPLACE-preserve threading at cascade-COMPLETE; "
        f"progress={progress}"
    )


def test_phase_4_5_terminal_transport_wave_fail_skips_audit_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminal app-server EOF is transport failure, not an app audit finding."""
    workspace = _mk_workspace(tmp_path, "transport")
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    async def _unexpected_audit_loop(**_kwargs):
        raise AssertionError("terminal transport failures must not dispatch audit-fix")

    monkeypatch.setattr(cli_module, "_phase_4_5_safety_nets_armed", lambda *_a, **_kw: True)
    monkeypatch.setattr(cli_module, "_run_audit_loop", _unexpected_audit_loop)

    state = RunState(run_id="transport-eof", task="transport-eof")
    state.milestone_order = ["milestone-1"]
    config = _make_config(max_cycles=2, cost_cap_usd=0.0)
    wave_result = SimpleNamespace(
        success=False,
        error_wave="B",
        error_message=(
            "Codex turn turn_1 ended without turn/completed: "
            "app-server stdout EOF — subprocess exited"
        ),
    )

    cost = asyncio.run(cli_module._run_failed_milestone_audit_if_enabled(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="transport-eof",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        wave_result=wave_result,
        state=state,
        agent_team_dir=str(agent_team_dir),
        milestone_anchor_dir=str(agent_team_dir / "milestones" / "milestone-1" / "_anchor"),
    ))

    assert cost == 0.0
    progress = state.milestone_progress.get("milestone-1", {})
    assert progress.get("status") == "FAILED"
    assert progress.get("failure_reason") == "transport_stdout_eof_before_turn_completed"


def test_phase_4_5_detector_recognizes_compile_repair_transport_eof() -> None:
    """Compile-repair EOF can arrive as a compile-failure message without stdout wording."""
    wave_result = SimpleNamespace(
        success=False,
        error_message=(
            "transport_stdout_eof_before_turn_completed: "
            "Compile failed after 2 attempt(s)"
        ),
    )
    assert (
        cli_module._phase_4_5_terminal_transport_failure_reason(wave_result)
        == "transport_stdout_eof_before_turn_completed"
    )

    wave_result.error_message = (
        "Wave B compile Codex repair ended with transport EOF before "
        "turn/completed; host compile recheck still failed"
    )
    assert (
        cli_module._phase_4_5_terminal_transport_failure_reason(wave_result)
        == "transport_stdout_eof_before_turn_completed"
    )


def test_phase_4_5_post_anchor_deleted_marks_degraded_tree(
    tmp_path: Path,
) -> None:
    """If anchor restore deletes files, persisted failure reason names the degraded tree."""
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir()
    state = RunState(run_id="degraded-tree", task="degraded-tree")
    state.milestone_order = ["milestone-1"]
    state.failed_milestones = ["milestone-1"]
    state.milestone_progress["milestone-1"] = {
        "status": "FAILED",
        "failure_reason": "audit_fix_did_not_recover_build",
        "audit_fix_rounds": 2,
        "audit_status": "failed",
    }

    marked = cli_module._phase_4_5_mark_post_anchor_degraded_tree(
        state=state,
        milestone_id="milestone-1",
        restore_result={
            "reverted": [],
            "deleted": ["apps/api/src/main.ts"],
            "restored": [],
        },
        agent_team_dir=str(agent_team_dir),
    )

    assert marked is True
    progress = state.milestone_progress["milestone-1"]
    assert progress["status"] == "FAILED"
    assert progress["failure_reason"] == "post_anchor_restore_degraded_tree"
    assert progress["audit_fix_rounds"] == 2
    assert progress["audit_status"] == "failed"


# ---------------------------------------------------------------------------
# AC5 — Phase 1.5 CrossMilestoneLockViolation handling unchanged
# ---------------------------------------------------------------------------


def test_ac5_cross_milestone_lock_violation_path_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``_run_audit_fix_unified`` raises
    ``CrossMilestoneLockViolation``, the audit-loop:
    1. Logs the violation.
    2. Calls ``_handle_audit_failure_milestone_anchor`` (when anchor
       context available) to restore + mark FAILED.
    3. Sets ``_phase_4_5_anchor_restore_fired`` so the epilogue is
       suppressed.
    4. Breaks the cycle loop.
    """
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    milestone_anchor_dir = agent_team_dir / "milestones" / "milestone-1" / "_anchor"
    milestone_anchor_dir.mkdir(parents=True)
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    audit_stub, fix_stub = _patch_audit_loop(
        monkeypatch,
        reports=[_make_dirty_report(cycle=1), _make_dirty_report(cycle=2)],
        raise_lock_violation=True,
    )

    # Stub the anchor-restore helper.
    handler_calls: list[dict] = []

    def _fake_handler(**kwargs):
        handler_calls.append(kwargs)
        return {"reverted": [], "deleted": [], "restored": []}

    monkeypatch.setattr(
        cli_module, "_handle_audit_failure_milestone_anchor", _fake_handler,
    )

    state = RunState(run_id="ac5", task="ac5")
    config = _make_config(max_cycles=2, cost_cap_usd=0.0)

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="ac5",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
        milestone_anchor_dir=str(milestone_anchor_dir),
        wave_result=SimpleNamespace(success=False, error_wave="D"),
    ))

    # Lock-violation path fired exactly once (cycle 1 dispatched →
    # raised → handler called → break).
    assert len(handler_calls) == 1, (
        f"AC5: expected 1 anchor-restore call from lock-violation path; "
        f"got {len(handler_calls)}"
    )
    assert handler_calls[0].get("reason") == "cross_milestone_lock_violation"


# ---------------------------------------------------------------------------
# AC7 — milestone cost cap aborts loop with failure_reason=cost_cap_reached
# ---------------------------------------------------------------------------


def test_ac7_cost_cap_pre_dispatch_check_aborts_with_failure_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``total_cost`` reaches the cap BEFORE the dispatch-cycle
    fires, the loop logs + persists ``failure_reason="cost_cap_reached"``
    + breaks. No dispatch fires."""
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    # Cycle 1 audit_cost = 5.0 → cap 3.0 → cap reached BEFORE dispatch.
    audit_stub, fix_stub = _patch_audit_loop(
        monkeypatch,
        reports=[_make_dirty_report(cycle=1)],
        audit_cost=5.0,
    )

    state = RunState(run_id="ac7-pre", task="ac7-pre")
    config = _make_config(max_cycles=3, cost_cap_usd=3.0)

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="ac7-pre",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
    ))

    assert fix_stub._call_count() == 0, (
        "AC7 (pre-dispatch): cost cap must abort BEFORE any dispatch fires"
    )
    progress = state.milestone_progress.get("milestone-1", {})
    assert progress.get("failure_reason") == "cost_cap_reached", (
        f"AC7 (pre-dispatch): expected failure_reason=cost_cap_reached; "
        f"progress={progress}"
    )


def test_ac7_cost_cap_post_dispatch_check_catches_overrun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cost cap second-check (team-lead correction): when the dispatch
    pushes ``total_cost`` past the cap, the loop must abort immediately
    after the dispatch — not let the next iteration burn another
    audit. Locks the §M.M3 "cumulative cost reaches the cap" semantic."""
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    # Cycle 1: audit_cost=1.0 (below cap 5.0), fix_cost=10.0 (way above).
    # Cap reached AFTER cycle 1 dispatch. Cycle 2 must NOT audit.
    audit_stub, fix_stub = _patch_audit_loop(
        monkeypatch,
        reports=[_make_dirty_report(cycle=1), _make_dirty_report(cycle=2)],
        audit_cost=1.0,
        fix_cost=10.0,
    )

    state = RunState(run_id="ac7-post", task="ac7-post")
    config = _make_config(max_cycles=3, cost_cap_usd=5.0)

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="ac7-post",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
    ))

    # Cycle 1 dispatched once; cycle 2's audit didn't fire.
    assert fix_stub._call_count() == 1, (
        f"AC7 (post-dispatch): expected exactly 1 dispatch (cycle 1); "
        f"got {fix_stub._call_count()}"
    )
    audit_calls = audit_stub._calls  # type: ignore[attr-defined]
    assert len(audit_calls) == 1, (
        f"AC7 (post-dispatch): cycle 2 audit MUST NOT fire when cap is "
        f"reached after cycle 1 dispatch; got {len(audit_calls)} audits"
    )
    progress = state.milestone_progress.get("milestone-1", {})
    assert progress.get("failure_reason") == "cost_cap_reached"
    # Increment still fires for the cycle-1 dispatch that DID happen.
    assert progress.get("audit_fix_rounds") == 1, (
        f"AC7 (post-dispatch): cycle 1 dispatch DID fire; "
        f"audit_fix_rounds must reflect that; progress={progress}"
    )


def test_ac7_cost_cap_zero_disables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``milestone_cost_cap_usd=0`` is the documented "disable"
    sentinel. The loop must NOT abort regardless of ``total_cost``."""
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    audit_stub, fix_stub = _patch_audit_loop(
        monkeypatch,
        reports=[_make_dirty_report(cycle=1), _make_dirty_report(cycle=2)],
        audit_cost=100.0,  # Huge cost — would trip any positive cap.
        fix_cost=100.0,
    )

    state = RunState(run_id="ac7-zero", task="ac7-zero")
    config = _make_config(max_cycles=2, cost_cap_usd=0.0)  # Disabled.

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="ac7-zero",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
    ))

    # Cycle 1 dispatched normally; loop terminated via max_cycles.
    assert fix_stub._call_count() == 1
    progress = state.milestone_progress.get("milestone-1", {})
    # No cost-cap signal because cap is 0 (disabled).
    assert progress.get("failure_reason", "") != "cost_cap_reached"


# ---------------------------------------------------------------------------
# AC8 — increment contract: cycle N → audit_fix_rounds == N within max_cycles
# ---------------------------------------------------------------------------


def test_ac8_cycle_n_increment_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Locks the per-cycle increment contract via the Phase 5.3 team-
    lead correction: cycle 1 dispatch → ``audit_fix_rounds == 1``;
    cycle 2 dispatch → ``audit_fix_rounds == 2``; cycle 3 audit-only
    (max_cycles) → stays at 2 (last cycle audits, doesn't dispatch).
    """
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    # Counter that captures the audit_fix_rounds value at every
    # save_state call. The audit-loop function-scope imports
    # ``from .state import save_state``, so monkey-patching
    # ``agent_team_v15.state.save_state`` (the source) intercepts
    # both the cycle-bump path and the cost-cap path.
    rounds_per_cycle: list[int] = []
    from agent_team_v15 import state as state_module
    real_save_state = state_module.save_state

    def _capturing_save_state(state_arg, **kwargs):
        real_save_state(state_arg, **kwargs)
        progress = state_arg.milestone_progress.get("milestone-1", {})
        rounds_per_cycle.append(progress.get("audit_fix_rounds", 0))

    monkeypatch.setattr(state_module, "save_state", _capturing_save_state)

    audit_stub, fix_stub = _patch_audit_loop(
        monkeypatch,
        reports=[
            _make_dirty_report(cycle=1, score_value=60.0),
            _make_dirty_report(cycle=2, score_value=70.0),
            _make_dirty_report(cycle=3, score_value=80.0),
        ],
    )

    state = RunState(run_id="ac8", task="ac8")
    config = _make_config(max_cycles=3, cost_cap_usd=0.0)

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="ac8",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
    ))

    # The save_state captures should include increments at 1 then 2.
    # (No cycle 3 dispatch.) Filter to non-zero entries to ignore any
    # other save_state calls (none expected in this synthetic, but
    # robust to refactor).
    increment_saves = [r for r in rounds_per_cycle if r > 0]
    assert increment_saves == [1, 2], (
        f"AC8: expected cycle-by-cycle increments [1, 2]; "
        f"got {increment_saves} (full series: {rounds_per_cycle})"
    )


# ---------------------------------------------------------------------------
# AC9 — REPLACE-preserve contract at terminal finalize sites
# ---------------------------------------------------------------------------


def test_ac9_replace_preserve_at_handle_audit_failure_milestone_anchor(
    tmp_path: Path,
) -> None:
    """``_handle_audit_failure_milestone_anchor`` MUST thread
    pre-existing ``audit_fix_rounds`` through its FAILED write so the
    REPLACE semantic doesn't clobber the count. Locks the AC9 contract
    at the canonical anchor-restore terminal site."""
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    anchor_dir = workspace / "_anchor"
    anchor_dir.mkdir()

    state = RunState(run_id="ac9-anchor", task="ac9-anchor")
    # Pre-set audit_fix_rounds=3 to mimic a milestone that ran through 3
    # dispatches before regression rolled it back.
    update_milestone_progress(
        state, "milestone-1", "IN_PROGRESS", audit_fix_rounds=3,
    )

    # Stub the wave_executor restore so we don't try to operate on disk.
    from agent_team_v15 import wave_executor

    def _fake_restore(_cwd, _anchor_dir):
        return {"reverted": [], "deleted": [], "restored": []}

    import unittest.mock as _mock
    with _mock.patch.object(wave_executor, "_restore_milestone_anchor", _fake_restore):
        cli_module._handle_audit_failure_milestone_anchor(
            state=state,
            milestone_id="milestone-1",
            cwd=str(workspace),
            anchor_dir=str(anchor_dir),
            reason="regression",
            agent_team_dir=str(agent_team_dir),
        )

    progress = state.milestone_progress["milestone-1"]
    assert progress["status"] == "FAILED"
    assert progress["failure_reason"] == "regression"
    assert progress["audit_fix_rounds"] == 3, (
        f"AC9: REPLACE-preserve violation — pre-existing audit_fix_rounds=3 "
        f"was clobbered. progress={progress}"
    )


def test_ac9_replace_preserve_when_zero_keeps_sentinel_skip(
    tmp_path: Path,
) -> None:
    """When ``audit_fix_rounds`` is 0 (or absent — sentinel) on a
    milestone hitting the anchor-restore terminal, the helper passes
    ``audit_fix_rounds=None`` so the kwarg is skipped and the inner
    dict matches the Phase 1.6 byte-shape (no audit_fix_rounds key)."""
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    anchor_dir = workspace / "_anchor"
    anchor_dir.mkdir()

    state = RunState(run_id="ac9-zero", task="ac9-zero")

    from agent_team_v15 import wave_executor
    import unittest.mock as _mock
    with _mock.patch.object(
        wave_executor, "_restore_milestone_anchor",
        lambda *a, **k: {"reverted": [], "deleted": [], "restored": []},
    ):
        cli_module._handle_audit_failure_milestone_anchor(
            state=state,
            milestone_id="milestone-1",
            cwd=str(workspace),
            anchor_dir=str(anchor_dir),
            reason="regression",
            agent_team_dir=str(agent_team_dir),
        )

    progress = state.milestone_progress["milestone-1"]
    assert progress == {"status": "FAILED", "failure_reason": "regression"}, (
        f"AC9: zero-rounds sentinel-skip violated — progress={progress}"
    )
    assert "audit_fix_rounds" not in progress


def test_anchor_restore_clears_milestone_wave_resume_state_and_artifacts(
    tmp_path: Path,
) -> None:
    """After audit-fix anchor restore, the milestone must resume from Wave A."""

    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    artifacts_dir = agent_team_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    anchor_dir = workspace / "_anchor"
    anchor_dir.mkdir()

    stale_a = artifacts_dir / "milestone-1-wave-A.json"
    stale_b = artifacts_dir / "milestone-1-wave-B.json"
    stale_c = artifacts_dir / "milestone-1-wave-C.json"
    other = artifacts_dir / "milestone-2-wave-A.json"
    for path in (stale_a, stale_b, stale_c, other):
        path.write_text("{}", encoding="utf-8")

    state = RunState(run_id="anchor-wave-reset", task="anchor-wave-reset")
    state.wave_progress["milestone-1"] = {
        "current_wave": "C",
        "completed_waves": ["A", "B"],
        "failed_wave": "C",
        "wave_artifacts": {
            "A": str(stale_a),
            "B": str(stale_b),
            "C": str(stale_c),
        },
    }

    from agent_team_v15 import wave_executor

    import unittest.mock as _mock
    with _mock.patch.object(
        wave_executor, "_restore_milestone_anchor",
        lambda *a, **k: {"reverted": [], "deleted": [], "restored": []},
    ):
        cli_module._handle_audit_failure_milestone_anchor(
            state=state,
            milestone_id="milestone-1",
            cwd=str(workspace),
            anchor_dir=str(anchor_dir),
            reason="audit_fix_did_not_recover_build",
            agent_team_dir=str(agent_team_dir),
        )

    persisted = json.loads((agent_team_dir / "STATE.json").read_text(encoding="utf-8"))
    assert "milestone-1" not in state.wave_progress
    assert "milestone-1" not in persisted["wave_progress"]
    assert wave_executor._get_resume_wave("milestone-1", "full_stack", str(workspace)) == "A"
    assert not stale_a.exists()
    assert not stale_b.exists()
    assert not stale_c.exists()
    assert other.is_file()


# ---------------------------------------------------------------------------
# §M.M14 fix-regression workspace rollback fixtures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_m14_diagnostic_identity_projection_includes_normalized_message(
) -> None:
    """``diagnostics_to_identities_for_test`` collapses whitespace runs
    and strips trailing punctuation. Two compile errors that differ only
    in whitespace OR trailing dots project to the same identity."""
    result_a = SimpleNamespace(errors=[
        {"file": "src/foo.ts", "line": 12, "code": "TS2304",
         "message": "Cannot find name 'foo'."},
    ])
    result_b = SimpleNamespace(errors=[
        {"file": "src/foo.ts", "line": 12, "code": "TS2304",
         "message": "Cannot   find name 'foo'"},  # different whitespace, no period
    ])
    assert (
        diagnostics_to_identities_for_test(result_a)
        == diagnostics_to_identities_for_test(result_b)
    )


@pytest.mark.asyncio
async def test_phase_5_4_cycle_1_fix_introduces_new_error_triggers_full_workspace_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§M.M14 #1: cycle 1 fix-Claude (mocked) edits one finding file AND
    creates one new file that introduces a new compile-profile diagnostic.
    Post-fix diagnostic identity diff detects the new diagnostic.
    Rollback restores edited files AND removes created files. Works on
    a workspace with NO ``.git`` (per team-lead correction)."""
    workspace = _mk_workspace(tmp_path)
    # Pre-existing file the fix-Claude session "edits".
    pre_file = workspace / "src" / "existing.ts"
    pre_file.parent.mkdir(parents=True)
    pre_file.write_text("export const A = 1;\n")
    # Workspace has NO .git directory — verifies the checkpoint walker
    # works without git state (per team-lead correction).
    assert not (workspace / ".git").exists()

    # Mock the diagnostic capture: pre returns 0 identities; post
    # returns 1 (the "new" one fix-Claude introduced).
    pre_call: list[bool] = []
    post_call: list[bool] = []

    async def _mock_run_diags(workspace_dir: Path):
        if not pre_call:
            pre_call.append(True)
            return frozenset(), True
        post_call.append(True)
        return (
            frozenset({
                ("src/created.ts", 5, "TS2304",
                 "Cannot find name 'unresolved'"),
            }),
            True,
        )

    monkeypatch.setattr(
        rollback_module, "_run_full_workspace_diagnostics", _mock_run_diags,
    )

    pre_state = await rollback_module.capture_pre_dispatch_state(workspace)

    # Simulate fix-Claude's mutation: edit existing.ts + create new file.
    pre_file.write_text("export const A = 999;  // edited\n")
    new_file = workspace / "src" / "created.ts"
    new_file.write_text("export const broken: string = 1;\n")

    outcome = await rollback_module.detect_and_rollback_regression(pre_state)

    assert outcome.rollback_fired
    assert len(outcome.new_diagnostic_identities) == 1
    # Restore happened — edited file reverted, created file removed.
    assert pre_file.read_text() == "export const A = 1;\n", (
        f"§M.M14 #1: edited file should be restored, got: {pre_file.read_text()!r}"
    )
    assert not new_file.exists(), (
        "§M.M14 #1: created file should be removed by rollback"
    )


@pytest.mark.asyncio
async def test_phase_5_4_cycle_1_fix_partial_success_preserved_when_no_new_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§M.M14 #2: fix-Claude addresses 2/3 findings cleanly; 1 still
    fails. No new compile-profile diagnostic identity appears (the
    existing one stays). Loop keeps the good patches and continues —
    no rollback fires."""
    workspace = _mk_workspace(tmp_path)
    pre_file = workspace / "src" / "existing.ts"
    pre_file.parent.mkdir(parents=True)
    pre_file.write_text("export const A = 1;\n")

    # Pre-state has 1 known diagnostic; post-state has the SAME 1 (the
    # "still failing" finding). No new identities → no rollback.
    pre_diags = frozenset({
        ("src/existing.ts", 1, "TS2322", "type mismatch"),
    })

    call_n = [0]

    async def _mock_run_diags(workspace_dir: Path):
        call_n[0] += 1
        return pre_diags, True  # Identical pre + post.

    monkeypatch.setattr(
        rollback_module, "_run_full_workspace_diagnostics", _mock_run_diags,
    )

    pre_state = await rollback_module.capture_pre_dispatch_state(workspace)
    # Simulate fix-Claude edit (won't be rolled back).
    pre_file.write_text("export const A = 2;  // partial fix\n")

    outcome = await rollback_module.detect_and_rollback_regression(pre_state)

    assert not outcome.rollback_fired
    assert outcome.new_diagnostic_identities == []
    # Edit preserved — fix-Claude's partial work survives.
    assert pre_file.read_text() == "export const A = 2;  // partial fix\n"


@pytest.mark.asyncio
async def test_phase_5_4_regression_identity_not_count_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§M.M14 #3: one OLD diagnostic disappears AND one NEW diagnostic
    appears, leaving the same count. Rollback STILL fires because
    diagnostic IDENTITY changed. Locks the count-only-comparison-is-
    insufficient contract."""
    workspace = _mk_workspace(tmp_path)
    pre_file = workspace / "src" / "existing.ts"
    pre_file.parent.mkdir(parents=True)
    pre_file.write_text("export const A = 1;\n")

    pre_diags = frozenset({
        ("src/existing.ts", 1, "TS2322", "type mismatch on A"),
    })
    # Same count (1), different identity. Old disappears (the fix
    # "fixed" line 1) BUT a new one appears at line 99 (fix-Claude
    # introduced a regression).
    post_diags = frozenset({
        ("src/existing.ts", 99, "TS2304", "cannot find name 'B'"),
    })

    call_n = [0]

    async def _mock_run_diags(workspace_dir: Path):
        call_n[0] += 1
        if call_n[0] == 1:
            return pre_diags, True
        return post_diags, True

    monkeypatch.setattr(
        rollback_module, "_run_full_workspace_diagnostics", _mock_run_diags,
    )

    pre_state = await rollback_module.capture_pre_dispatch_state(workspace)
    pre_file.write_text("export const A = 1;\nimport { B } from './nope';\n")

    outcome = await rollback_module.detect_and_rollback_regression(pre_state)

    # Rollback fired despite count being identical (1 → 1).
    assert outcome.rollback_fired, (
        "§M.M14 #3: rollback must fire on identity-change even when "
        "count is steady (count-only comparison is insufficient)"
    )
    assert len(outcome.new_diagnostic_identities) == 1
    new_id = outcome.new_diagnostic_identities[0]
    assert new_id == ("src/existing.ts", 99, "TS2304", "cannot find name 'B'")
    # Restore brought the file back to pre-state.
    assert pre_file.read_text() == "export const A = 1;\n"


@pytest.mark.asyncio
async def test_m_m14_unavailable_pre_or_post_falls_back_to_score_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the diagnostic capture is structurally impossible (no root
    ``tsconfig.json``, infra error, etc.), the rollback path stays
    quiet — ``rollback_fired=False`` with ``*_available`` flags
    surfaced for caller telemetry. Locks the no-rollback-on-incomplete-
    signal contract."""
    workspace = _mk_workspace(tmp_path)

    async def _no_diags(workspace_dir: Path):
        return frozenset(), False

    monkeypatch.setattr(
        rollback_module, "_run_full_workspace_diagnostics", _no_diags,
    )

    pre_state = await rollback_module.capture_pre_dispatch_state(workspace)
    outcome = await rollback_module.detect_and_rollback_regression(pre_state)

    assert not outcome.rollback_fired
    assert not outcome.pre_diagnostics_available
    assert not outcome.post_diagnostics_available
    assert outcome.restore_skipped_reason == "diagnostics_unavailable"


# ---------------------------------------------------------------------------
# Cost cap config wiring
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Reviewer-mandated patches (2026-04-29) — three blocking defects + tests
# ---------------------------------------------------------------------------


def test_reviewer_defect_1_cost_cap_overrun_still_runs_m_m14_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reviewer defect #1: post-dispatch cost cap MUST NOT bypass §M.M14
    rollback. When a fix dispatch both pushes ``total_cost`` over the
    cap AND introduces a new compile-profile diagnostic identity, the
    rollback runs FIRST (workspace is restored) — the cost-cap branch
    doesn't get to short-circuit before the workspace integrity check.
    """
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    # Simulate a fix-Claude-touched file under the workspace so the
    # checkpoint walker can see the difference. We'll write the
    # "edited" content during the fix-stub call.
    src_file = workspace / "src" / "existing.ts"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("export const A = 1;\n")

    # Mock pre/post diagnostics: pre empty, post has a new identity.
    diag_state = {"calls": 0}

    async def _mock_diags(workspace_dir: Path):
        diag_state["calls"] += 1
        if diag_state["calls"] == 1:
            return frozenset(), True
        return (
            frozenset({
                ("src/existing.ts", 5, "TS2304", "cannot find name 'broken'"),
            }),
            True,
        )

    monkeypatch.setattr(
        rollback_module, "_run_full_workspace_diagnostics", _mock_diags,
    )

    # Audit returns dirty cycle 1; fix dispatch costs $10 (way above
    # cap $5). Without the patch, post-dispatch cost-cap would break
    # before rollback. With the patch, rollback fires first.
    audit_stub = _mock_run_milestone_audit_factory(
        [_make_dirty_report(cycle=1)], audit_cost=1.0,
    )

    fix_call_count = {"n": 0}

    async def _fix_stub_that_edits_workspace(*args, **kwargs):
        fix_call_count["n"] += 1
        # Simulate fix-Claude editing the file — visible to the
        # checkpoint walker via byte-content delta.
        src_file.write_text("export const A = 999;  // edited\n")
        return ["src/existing.ts"], 10.0  # pushes total over $5 cap

    monkeypatch.setattr(cli_module, "_run_milestone_audit", audit_stub)
    monkeypatch.setattr(cli_module, "_run_audit_fix_unified", _fix_stub_that_edits_workspace)

    state = RunState(run_id="rev-d1", task="rev-d1")
    config = _make_config(max_cycles=2, cost_cap_usd=5.0)

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="rev-d1",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
    ))

    # Workspace restored — the fix's edit was rolled back.
    assert src_file.read_text() == "export const A = 1;\n", (
        "Reviewer defect #1: workspace must be restored before cost-cap "
        f"break. Got: {src_file.read_text()!r}"
    )
    # Dispatch fired exactly once.
    assert fix_call_count["n"] == 1


def test_reviewer_defect_2_rollback_still_increments_audit_fix_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reviewer defect #2: when §M.M14 rollback fires, the loop must
    still record that the fix dispatch happened. ``audit_fix_rounds``
    is "increment per audit-fix dispatch" (R-#37), and the dispatch
    DID run — telemetry can't go silent on the regression path.
    """
    workspace = _mk_workspace(tmp_path)
    agent_team_dir = workspace / ".agent-team"
    agent_team_dir.mkdir()
    audit_dir = agent_team_dir / "milestones" / "milestone-1" / ".agent-team"
    audit_dir.mkdir(parents=True)

    diag_calls = {"n": 0}

    async def _mock_diags(workspace_dir: Path):
        diag_calls["n"] += 1
        if diag_calls["n"] == 1:
            return frozenset(), True
        return (
            frozenset({
                ("src/foo.ts", 1, "TS2304", "regression"),
            }),
            True,
        )

    monkeypatch.setattr(
        rollback_module, "_run_full_workspace_diagnostics", _mock_diags,
    )

    audit_stub = _mock_run_milestone_audit_factory(
        [_make_dirty_report(cycle=1)], audit_cost=0.1,
    )
    fix_stub = _mock_run_audit_fix_unified_factory(fix_cost=0.1)
    monkeypatch.setattr(cli_module, "_run_milestone_audit", audit_stub)
    monkeypatch.setattr(cli_module, "_run_audit_fix_unified", fix_stub)

    state = RunState(run_id="rev-d2", task="rev-d2")
    config = _make_config(max_cycles=2, cost_cap_usd=0.0)

    asyncio.run(cli_module._run_audit_loop(
        milestone_id="milestone-1",
        milestone_template="full_stack",
        config=config,
        depth="standard",
        task_text="rev-d2",
        requirements_path=str(audit_dir.parent / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cwd=str(workspace),
        state=state,
        agent_team_dir=str(agent_team_dir),
    ))

    # Rollback fired → loop broke. But the dispatch DID run, so
    # ``audit_fix_rounds`` must be 1 — the increment fires before the
    # rollback-break path.
    progress = state.milestone_progress.get("milestone-1", {})
    assert progress.get("audit_fix_rounds") == 1, (
        f"Reviewer defect #2: audit_fix_rounds must increment when "
        f"rollback fires (the dispatch DID run). progress={progress}"
    )
    assert fix_stub._call_count() == 1


def test_reviewer_defect_3_rootless_monorepo_diagnostic_capture(
    tmp_path: Path,
) -> None:
    """Reviewer defect #3: ``_run_full_workspace_diagnostics`` MUST work
    on rootless TS monorepos. A workspace with ``apps/web/tsconfig.json``
    and no root ``tsconfig.json`` is a normal Nx / Turborepo / pnpm
    workspaces shape; the previous root-tsconfig-only gate silently
    disabled §M.M14 capture for every such project.

    Verifies the resolver path: ``_full_workspace_compile_profile`` (the
    Wave E/T resolver) discovers the sub-package tsconfigs and emits
    one ``--project <path>`` invocation per discovered config.
    """
    workspace = _mk_workspace(tmp_path)
    # Rootless monorepo shape:
    #   apps/web/tsconfig.json (frontend)
    #   apps/api/tsconfig.json (backend)
    # NO root tsconfig.json.
    web_dir = workspace / "apps" / "web"
    web_dir.mkdir(parents=True)
    (web_dir / "tsconfig.json").write_text('{"compilerOptions": {}}')
    api_dir = workspace / "apps" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "tsconfig.json").write_text('{"compilerOptions": {}}')
    assert not (workspace / "tsconfig.json").exists()

    profile = rollback_module._full_workspace_compile_profile(workspace)

    # Resolver discovered both sub-tsconfigs; profile has at least 2
    # commands (one per discovered tsconfig).
    assert profile.name != "noop", (
        f"Reviewer defect #3: rootless monorepo must NOT degrade to noop. "
        f"Got profile name {profile.name!r}"
    )
    assert len(profile.commands) >= 2, (
        f"Reviewer defect #3: expected ≥2 ``--project <path>`` commands "
        f"(one per sub-tsconfig); got {len(profile.commands)}"
    )

    # Verify the apps/web/tsconfig.json IS included in the discovered
    # profile (the regression case the reviewer flagged: §M.M14
    # silently missing frontend/generated diagnostics on rootless
    # monorepos).
    resolved_targets = []
    for cmd in profile.commands:
        if "--project" in cmd:
            idx = cmd.index("--project")
            if idx + 1 < len(cmd):
                resolved_targets.append(cmd[idx + 1])
    assert any("apps/web" in t for t in resolved_targets), (
        f"Reviewer defect #3: apps/web/tsconfig.json must be in the "
        f"diagnostic-capture profile. Resolved targets: {resolved_targets}"
    )
    assert any("apps/api" in t for t in resolved_targets)


def test_milestone_cost_cap_usd_yaml_parser_threading() -> None:
    """``audit_team.milestone_cost_cap_usd`` round-trips through YAML
    config parsing. Closes a §0.1 invariant 4 carry-over: every flag
    Phase 5 ships must be wired through the YAML parser at config.py."""
    from agent_team_v15.config import load_config
    from textwrap import dedent
    import tempfile

    yaml_text = dedent("""
        audit_team:
          enabled: true
          milestone_cost_cap_usd: 12.5
    """).strip()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False,
    ) as f:
        f.write(yaml_text)
        yaml_path = f.name

    try:
        config, _overrides = load_config(config_path=yaml_path)
        assert config.audit_team.milestone_cost_cap_usd == 12.5
    finally:
        Path(yaml_path).unlink(missing_ok=True)


def test_milestone_cost_cap_usd_negative_value_rejected() -> None:
    """Validation rejects negative caps — the config-time guard."""
    from agent_team_v15.config import _validate_audit_team_config
    cfg = AuditTeamConfig()
    cfg.milestone_cost_cap_usd = -1.0
    with pytest.raises(ValueError, match="milestone_cost_cap_usd must be >= 0"):
        _validate_audit_team_config(cfg)
