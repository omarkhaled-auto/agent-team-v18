"""Phase 1 audit-fix-loop guardrails — synthetic fixtures.

Covers the six acceptance criteria (AC1-AC8) listed in
``docs/plans/2026-04-26-audit-fix-guardrails-phase1-3.md`` §D.

Fixture 1 — short-circuit-when-safety-nets-disabled (AC1; Phase 4.5
            renamed/extended — Risk #1's unconditional short-circuit
            survives as the degraded-config fallback when any safety
            net is off, validating the conditional lift in Phase 4.5)
Fixture 2 — CRITICAL-count exit (AC3)
Fixture 3 — anchor delete-untracked (AC2 + AC7)
Fixture 4 — denylist rejection (AC4)
Fixture 5 — audit-fail STATE.json mark (AC6 / Risk #15)
Fixture 6 — DEGRADED disambiguation (AC8 / Risk #16)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_team_v15 import wave_executor as wx
from agent_team_v15.audit_models import AuditScore
from agent_team_v15.audit_team import should_terminate_reaudit
from agent_team_v15.state import RunState


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_score(score: float, critical_count: int) -> AuditScore:
    """Build a minimal AuditScore for termination-condition tests."""

    return AuditScore(
        total_items=10,
        passed=8,
        failed=1,
        partial=1,
        critical_count=critical_count,
        high_count=0,
        medium_count=0,
        low_count=0,
        info_count=0,
        score=score,
        health="degraded",
        max_score=100,
    )


def _make_finding(
    finding_id: str,
    primary_file: str,
    severity: str = "HIGH",
) -> SimpleNamespace:
    """Create a duck-typed AuditFinding with the only fields the gate reads."""

    return SimpleNamespace(
        finding_id=finding_id,
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity=severity,
        summary=f"finding {finding_id}",
        evidence=[f"{primary_file}:1 -- synthetic"],
        remediation="",
        confidence=1.0,
        source="llm",
        primary_file=primary_file,
    )


# ---------------------------------------------------------------------------
# Fixture 1 — short-circuit-when-safety-nets-disabled (AC1)
#
# Phase 4.5 conditionally lifted Risk #1: when ALL safety nets are armed
# (Phase 1 anchor + Phase 2 lock + Phase 4.3 wave-aware audit + Phase 3
# hook PreToolUse deny), audit-fix runs on wave-fail as the recovery
# cascade. The pre-Phase-4.5 unconditional short-circuit survives as the
# degraded-config fallback: when ANY safety net is off, the legacy "skip
# audit-fix on wave-fail" behaviour fires. This fixture asserts THAT
# fallback contract by disabling one safety net (`milestone_anchor_enabled
# = False`) so the lift cannot activate even with all other knobs at
# their defaults.
# ---------------------------------------------------------------------------


def test_run_audit_fix_unified_short_circuits_when_safety_nets_disabled() -> None:
    """When wave_result.success is False AND any safety net is disabled,
    _run_audit_fix_unified MUST short-circuit with ``([], 0.0)`` and
    NEVER invoke ``execute_unified_fix_async``.

    Renamed/extended from the pre-Phase-4.5 fixture
    ``test_run_audit_fix_unified_skips_when_wave_failed`` per Phase 4.5
    plan §0.6 step 2: Risk #1's unconditional short-circuit is now the
    DEGRADED-CONFIG fallback. Phase 4.5's conditional lift is the
    primary path; this fixture locks the fallback so the M25-disaster
    prevention property survives operator misconfiguration.
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import fix_executor as fix_mod

    failed_wave = SimpleNamespace(success=False, error_wave="A", waves=[])
    report = SimpleNamespace(findings=[_make_finding("F1", "apps/web/x.tsx")], fix_candidates=[0])

    # Phase 4.5 — disable one safety net (milestone_anchor_enabled=False)
    # so the conditional lift cannot fire; the legacy short-circuit must
    # still trigger. The other knobs are set to their post-Phase-4.5
    # defaults so this test specifically validates the "any net off →
    # fallback fires" semantic.
    audit_cfg = SimpleNamespace(
        enabled=True,
        lift_risk_1_when_nets_armed=True,
        milestone_anchor_enabled=False,        # ← degraded
        test_surface_lock_enabled=True,
        audit_wave_awareness_enabled=True,
    )

    with patch.object(
        fix_mod, "execute_unified_fix_async", autospec=True
    ) as mock_dispatch:
        modified, cost = asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=SimpleNamespace(audit_team=audit_cfg),
                cwd=None,
                task_text="",
                depth="standard",
                wave_result=failed_wave,
            )
        )

    assert modified == []
    assert cost == 0.0
    mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# Fixture 2 — CRITICAL-count exit (AC3)
# ---------------------------------------------------------------------------


def test_critical_count_increase_forces_regression_exit() -> None:
    """When previous_score.critical_count=1 and current_score.critical_count=2,
    ``should_terminate_reaudit`` MUST return ``(True, "regression")`` rather
    than the existing logging.warning side effect.
    """

    previous = _make_score(score=80.0, critical_count=1)
    current = _make_score(score=80.0, critical_count=2)

    stop, reason = should_terminate_reaudit(
        current_score=current,
        previous_score=previous,
        cycle=2,
        max_cycles=3,
        healthy_threshold=90.0,
    )

    assert stop is True
    assert reason == "regression"


# ---------------------------------------------------------------------------
# Fixture 3 — anchor delete-untracked (AC2 + AC7)
# ---------------------------------------------------------------------------


def test_milestone_anchor_capture_and_restore_deletes_untracked(
    tmp_path: Path,
) -> None:
    """Capture an anchor, then mutate the run-dir (modify tracked + add
    untracked), then restore. The anchor MUST revert tracked changes AND
    delete the untracked file."""

    cwd = tmp_path
    a_path = cwd / "a.txt"
    a_path.write_text("original-a", encoding="utf-8")

    anchor_dir = wx._capture_milestone_anchor(str(cwd), "milestone-1")
    assert anchor_dir.is_dir()

    # Mutate AFTER anchor captured.
    a_path.write_text("MODIFIED", encoding="utf-8")
    b_path = cwd / "b.txt"
    b_path.write_text("untracked-leak", encoding="utf-8")
    sub_dir = cwd / "apps" / "web"
    sub_dir.mkdir(parents=True)
    leak_tsx = sub_dir / "leak.tsx"
    leak_tsx.write_text("// leak", encoding="utf-8")

    result = wx._restore_milestone_anchor(str(cwd), anchor_dir)

    assert a_path.read_text(encoding="utf-8") == "original-a"
    assert not b_path.exists(), "untracked b.txt MUST be deleted"
    assert not leak_tsx.exists(), "untracked apps/web/leak.tsx MUST be deleted"

    assert "a.txt" in result["reverted"]
    deleted_set = set(result["deleted"])
    assert "b.txt" in deleted_set
    assert "apps/web/leak.tsx" in deleted_set


# ---------------------------------------------------------------------------
# Fixture 4 — denylist rejection (AC4)
# ---------------------------------------------------------------------------


def test_denylisted_fix_proposals_are_rejected_pre_dispatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Findings whose primary_file matches the milestone-anchor immutable
    denylist must be filtered out before dispatch and logged with the
    canonical ``[FIX-DENYLIST] rejected ...`` format.
    """

    from agent_team_v15.fix_executor import filter_denylisted_findings

    keep = _make_finding("F-KEEP", "apps/web/page.tsx")
    drop_api = _make_finding("F-API", "packages/api-client/sdk.gen.ts")
    drop_prisma = _make_finding(
        "F-MIG", "prisma/migrations/20260426/migration.sql"
    )

    denylist = list(wx._MILESTONE_ANCHOR_IMMUTABLE_DENYLIST)

    with caplog.at_level(logging.WARNING, logger="agent_team_v15.fix_executor"):
        kept, rejected = filter_denylisted_findings(
            [keep, drop_api, drop_prisma], denylist
        )

    assert [f.finding_id for f in kept] == ["F-KEEP"]
    assert {f.finding_id for f in rejected} == {"F-API", "F-MIG"}

    log_lines = "\n".join(
        record.getMessage() for record in caplog.records
    )
    assert "[FIX-DENYLIST] rejected" in log_lines
    assert "F-API" in log_lines and "packages/api-client" in log_lines
    assert "F-MIG" in log_lines and "prisma/migrations" in log_lines


# ---------------------------------------------------------------------------
# Fixture 5 — audit-fail STATE.json mark (AC6 / Risk #15)
# ---------------------------------------------------------------------------


def test_audit_failure_marks_state_json_failed(tmp_path: Path) -> None:
    """When ``_handle_audit_failure_milestone_anchor`` runs for reason
    ``"regression"``, the milestone status persisted to STATE.json MUST be
    ``FAILED`` and ``failed_milestones`` MUST include the milestone id.
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15.state import load_state, save_state

    cwd = tmp_path
    agent_team_dir = cwd / ".agent-team"
    agent_team_dir.mkdir()

    (cwd / "ground.txt").write_text("zero", encoding="utf-8")
    anchor_dir = wx._capture_milestone_anchor(str(cwd), "milestone-1")

    state = RunState(
        run_id="rs-1",
        task="t",
        depth="standard",
        milestone_order=["milestone-1"],
        current_milestone="milestone-1",
    )
    state.milestone_progress["milestone-1"] = {"status": "IN_PROGRESS"}
    save_state(state, directory=str(agent_team_dir))

    cli_mod._handle_audit_failure_milestone_anchor(
        state=state,
        milestone_id="milestone-1",
        cwd=str(cwd),
        anchor_dir=anchor_dir,
        reason="regression",
        agent_team_dir=str(agent_team_dir),
    )

    persisted = load_state(directory=str(agent_team_dir))
    assert persisted is not None
    assert persisted.milestone_progress["milestone-1"]["status"] == "FAILED"
    assert "milestone-1" in persisted.failed_milestones
    assert persisted.current_milestone == ""


# ---------------------------------------------------------------------------
# Fixture 6 — DEGRADED disambiguation (AC8 / Risk #16)
# ---------------------------------------------------------------------------


def test_audit_failure_marks_failed_even_with_degraded_score(
    tmp_path: Path,
) -> None:
    """Audit-fail-driven anchor restore MUST mark the milestone ``FAILED``
    regardless of audit_score; the DEGRADED branch (cli.py:5838) is
    deliberately bypassed to preserve get_ready_milestones() halt semantics
    (Risk #16)."""

    from agent_team_v15 import cli as cli_mod

    cwd = tmp_path
    agent_team_dir = cwd / ".agent-team"
    agent_team_dir.mkdir()

    (cwd / "ground.txt").write_text("zero", encoding="utf-8")
    anchor_dir = wx._capture_milestone_anchor(str(cwd), "milestone-1")

    state = RunState(
        run_id="rs-2",
        task="t",
        depth="standard",
        milestone_order=["milestone-1"],
        current_milestone="milestone-1",
        audit_score=0.85,  # would otherwise yield DEGRADED at cli.py:5838
    )
    state.milestone_progress["milestone-1"] = {"status": "IN_PROGRESS"}

    cli_mod._handle_audit_failure_milestone_anchor(
        state=state,
        milestone_id="milestone-1",
        cwd=str(cwd),
        anchor_dir=anchor_dir,
        reason="regression",
        agent_team_dir=str(agent_team_dir),
    )

    assert state.milestone_progress["milestone-1"]["status"] == "FAILED"
    assert "milestone-1" not in state.completed_milestones
    assert "milestone-1" in state.failed_milestones
