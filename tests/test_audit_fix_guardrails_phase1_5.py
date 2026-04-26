"""Phase 1.5 audit-fix-loop guardrail fixtures.

Goal: route Phase 2's :class:`CrossMilestoneLockViolation` through to
Phase 1's :func:`_handle_audit_failure_milestone_anchor` so the
milestone-anchor restore fires immediately when the cross-milestone
lock catches a regression — instead of waiting for
``should_terminate_reaudit`` to flip on the next cycle.

Closes the open follow-up flagged in ``phase_2_landing.md``:

> Wire CrossMilestoneLockViolation → anchor restore. Phase 2 raises
> but the audit-fix loop doesn't yet catch and rollback. Phase 1's
> ``_handle_audit_failure_milestone_anchor`` is the right sink;
> routing the violation to it is a small ``cli.py`` change near the
> ``_run_audit_fix_unified`` boundary.

Two surfaces covered:

* ``_run_audit_fix_unified`` no longer swallows
  :class:`CrossMilestoneLockViolation` (the original bare
  ``except Exception`` was eating the signal). The lock violation now
  propagates to the caller.
* ``_run_audit_loop`` catches the violation around the
  ``_run_audit_fix_unified`` call. With anchor context (state +
  agent_team_dir + milestone_anchor_dir), it triggers the Phase 1
  helper. Without anchor context (legacy callers), it falls through
  to the legacy ``best_snapshot`` rollback. Either way, the cycle
  loop breaks immediately.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15 import cli as cli_mod
from agent_team_v15.fix_executor import CrossMilestoneLockViolation


# ---------------------------------------------------------------------------
# Surface 1 — _run_audit_fix_unified must re-raise CrossMilestoneLockViolation
# rather than swallow it.
# ---------------------------------------------------------------------------


def test_run_audit_fix_unified_re_raises_cross_milestone_lock_violation() -> None:
    """The bare ``except Exception`` at the audit-fix boundary used to
    swallow the lock violation, leaving the audit-fix loop to discover
    the regression only when ``should_terminate_reaudit`` next fired.
    Phase 1.5 requires the violation to propagate so the outer loop
    can trigger the anchor restore immediately.
    """
    from agent_team_v15 import fix_executor as fix_mod

    finding = SimpleNamespace(
        finding_id="F-LOCK-001",
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity="HIGH",
        summary="lock violation propagation",
        evidence=["apps/web/login.tsx:1 -- synthetic"],
        remediation="",
        confidence=1.0,
        source="llm",
        primary_file="apps/web/login.tsx",
        sibling_test_files=[],
    )
    report = SimpleNamespace(findings=[finding], fix_candidates=[0])
    config = SimpleNamespace(audit_team=SimpleNamespace(enabled=True))

    violation = CrossMilestoneLockViolation(
        finding_id="F-LOCK-001",
        regressed_acs=["AC-M1-001"],
        regressed_tests=["e2e/tests/checkout.spec.ts"],
        finding_surface=["e2e/tests/login.spec.ts"],
    )

    async def _raise_violation(*args, **kwargs):
        raise violation

    with patch.object(
        fix_mod, "execute_unified_fix_async", side_effect=_raise_violation
    ):
        with pytest.raises(CrossMilestoneLockViolation) as excinfo:
            asyncio.run(
                cli_mod._run_audit_fix_unified(
                    report=report,
                    config=config,
                    cwd=None,
                    task_text="",
                    depth="standard",
                )
            )

    assert excinfo.value.finding_id == "F-LOCK-001"
    assert excinfo.value.regressed_acs == ["AC-M1-001"]


def test_run_audit_fix_unified_still_swallows_other_exceptions() -> None:
    """Backward-compat: non-lock failures (RuntimeError, network errors,
    SDK timeouts) continue to be logged + swallowed so the audit-fix
    loop keeps moving. Only the load-bearing lock signal escapes.
    """
    from agent_team_v15 import fix_executor as fix_mod

    finding = SimpleNamespace(
        finding_id="F-001",
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity="HIGH",
        summary="non-lock failure",
        evidence=["apps/web/x.tsx:1 -- synthetic"],
        remediation="",
        confidence=1.0,
        source="llm",
        primary_file="apps/web/x.tsx",
        sibling_test_files=[],
    )
    report = SimpleNamespace(findings=[finding], fix_candidates=[0])
    config = SimpleNamespace(audit_team=SimpleNamespace(enabled=True))

    async def _raise_other(*args, **kwargs):
        raise RuntimeError("dispatch timed out")

    with patch.object(
        fix_mod, "execute_unified_fix_async", side_effect=_raise_other
    ):
        modified, cost = asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=config,
                cwd=None,
                task_text="",
                depth="standard",
            )
        )

    assert modified == []
    assert cost == 0.0


# ---------------------------------------------------------------------------
# Surface 2 — _run_audit_loop catches the violation and routes to the
# Phase 1 anchor-restore helper when context is available.
# ---------------------------------------------------------------------------


def _make_audit_team_config() -> SimpleNamespace:
    """Build a minimum AuditTeamConfig the loop reads from."""
    return SimpleNamespace(
        enabled=True,
        max_reaudit_cycles=3,
        score_healthy_threshold=90.0,
        fix_severity_threshold="HIGH",
        milestone_anchor_enabled=True,
        test_surface_lock_enabled=True,
    )


def _make_loop_config() -> SimpleNamespace:
    """Build the duck-typed config the audit loop reads.

    Mirrors the AgentTeamConfig surface that ``_run_audit_loop``
    touches: audit_team, v18 (audit_fix_iteration_enabled,
    evidence_mode), tracking_documents (fix_cycle_log), convergence.
    """
    return SimpleNamespace(
        audit_team=_make_audit_team_config(),
        v18=SimpleNamespace(
            audit_fix_iteration_enabled=False,
            evidence_mode="disabled",
        ),
        tracking_documents=SimpleNamespace(fix_cycle_log=False),
        convergence=SimpleNamespace(
            requirements_dir=".agent-team",
            master_plan_file="MASTER_PLAN.md",
            escalation_threshold=3,
            max_escalation_depth=2,
            max_cycles=3,
        ),
    )


def _make_run_state() -> object:
    """Construct a real RunState so update_milestone_progress works."""
    from agent_team_v15.state import RunState

    state = RunState()
    state.milestone_progress["milestone-1"] = SimpleNamespace(
        status="IN_PROGRESS",
        started_at="2026-04-26T00:00:00",
        completed_at="",
    )
    return state


def test_run_audit_loop_catches_lock_violation_and_calls_anchor_helper(
    tmp_path: Path,
) -> None:
    """When CrossMilestoneLockViolation propagates from
    ``_run_audit_fix_unified``, the loop must catch it, call the Phase 1
    helper to restore the anchor + mark FAILED, and break the cycle.
    """
    from agent_team_v15 import audit_models as audit_models_mod

    audit_dir = tmp_path / ".agent-team" / "audits" / "milestone-1"
    audit_dir.mkdir(parents=True)
    agent_team_dir = tmp_path / ".agent-team"
    anchor_dir = agent_team_dir / "milestones" / "milestone-1" / "_anchor"
    anchor_dir.mkdir(parents=True)

    config = _make_loop_config()

    state = _make_run_state()
    violation = CrossMilestoneLockViolation(
        finding_id="F-LOCK-002",
        regressed_acs=["AC-M1-007"],
        regressed_tests=["e2e/tests/checkout.spec.ts"],
        finding_surface=["e2e/tests/login.spec.ts"],
    )

    # Mock dependencies the loop reads:
    #  - _run_audit_fix_unified raises the violation on cycle 2.
    #  - _run_milestone_audit returns a healthy report on cycle 1 so
    #    the loop enters cycle 2 and reaches the audit-fix dispatch.
    cycle_1_report = SimpleNamespace(
        cycle=1,
        score=SimpleNamespace(score=70.0, health="degraded"),
        findings=[
            SimpleNamespace(
                file_path="apps/web/login.tsx",
                severity="HIGH",
                auditor="test",
                requirement_id="REQ-001",
                summary="cycle 1 finding",
            )
        ],
        to_json=lambda: "{}",
    )

    async def _fake_audit(**kwargs):
        return cycle_1_report, 0.0

    async def _fake_fix_unified(*args, **kwargs):
        raise violation

    handler_calls: list[dict] = []

    def _fake_handler(**kwargs):
        handler_calls.append(kwargs)
        return {"reverted": ["apps/web/login.tsx"], "deleted": [], "restored": []}

    with patch.object(cli_mod, "_run_milestone_audit", side_effect=_fake_audit), \
         patch.object(cli_mod, "_run_audit_fix_unified", side_effect=_fake_fix_unified), \
         patch.object(
             cli_mod,
             "_handle_audit_failure_milestone_anchor",
             side_effect=_fake_handler,
         ):
        report_obj, cost = asyncio.run(
            cli_mod._run_audit_loop(
                milestone_id="milestone-1",
                milestone_template=None,
                config=config,
                depth="standard",
                task_text="",
                requirements_path=str(tmp_path / "REQUIREMENTS.md"),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
                state=state,
                agent_team_dir=str(agent_team_dir),
                milestone_anchor_dir=str(anchor_dir),
            )
        )

    # Helper invoked exactly once with the expected context.
    assert len(handler_calls) == 1, (
        "Expected _handle_audit_failure_milestone_anchor to fire exactly "
        f"once on lock violation; got {len(handler_calls)} calls"
    )
    call_kwargs = handler_calls[0]
    assert call_kwargs["milestone_id"] == "milestone-1"
    assert call_kwargs["state"] is state
    assert call_kwargs["agent_team_dir"] == str(agent_team_dir)
    assert call_kwargs["cwd"] == str(tmp_path)
    assert str(call_kwargs["anchor_dir"]) == str(anchor_dir)
    # Reason value names the trigger so future maintainers can grep.
    assert "lock" in call_kwargs["reason"].lower() or call_kwargs["reason"] == "cross_milestone_lock_violation"


def test_run_audit_loop_falls_back_to_snapshot_when_anchor_context_missing(
    tmp_path: Path,
) -> None:
    """Legacy callers (cli.py:2281, 7437, 12707 per phase_1_landing.md)
    don't pass state/anchor kwargs. The lock violation must still
    trigger A rollback — just the legacy in-memory snapshot one — and
    the cycle loop must break.
    """
    audit_dir = tmp_path / ".agent-team" / "audits" / "milestone-2"
    audit_dir.mkdir(parents=True)

    config = _make_loop_config()

    violation = CrossMilestoneLockViolation(
        finding_id="F-LOCK-003",
        regressed_acs=[],
        regressed_tests=["e2e/tests/foo.spec.ts"],
        finding_surface=["e2e/tests/bar.spec.ts"],
    )

    cycle_1_report = SimpleNamespace(
        cycle=1,
        score=SimpleNamespace(score=70.0, health="degraded"),
        findings=[
            SimpleNamespace(
                file_path="apps/web/x.tsx",
                severity="HIGH",
                auditor="test",
                requirement_id="REQ-001",
                summary="legacy",
            )
        ],
        to_json=lambda: "{}",
    )

    async def _fake_audit(**kwargs):
        return cycle_1_report, 0.0

    async def _fake_fix_unified(*args, **kwargs):
        raise violation

    helper_calls: list[dict] = []

    def _fake_handler(**kwargs):
        helper_calls.append(kwargs)
        return {"reverted": [], "deleted": [], "restored": []}

    with patch.object(cli_mod, "_run_milestone_audit", side_effect=_fake_audit), \
         patch.object(cli_mod, "_run_audit_fix_unified", side_effect=_fake_fix_unified), \
         patch.object(
             cli_mod,
             "_handle_audit_failure_milestone_anchor",
             side_effect=_fake_handler,
         ):
        report_obj, cost = asyncio.run(
            cli_mod._run_audit_loop(
                milestone_id=None,
                milestone_template=None,
                config=config,
                depth="standard",
                task_text="",
                requirements_path=str(tmp_path / "REQUIREMENTS.md"),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
                # Anchor context deliberately omitted (legacy caller).
            )
        )

    # Anchor helper must NOT fire when the legacy caller didn't supply
    # the kwargs — falling back to best_snapshot is the documented
    # behavior.
    assert helper_calls == [], (
        "_handle_audit_failure_milestone_anchor must not fire when "
        "anchor context is missing — the legacy snapshot rollback owns "
        "this code path"
    )


def test_run_audit_loop_breaks_cycle_on_lock_violation(tmp_path: Path) -> None:
    """The lock violation is irrecoverable for this milestone. The
    loop must break IMMEDIATELY rather than running another audit
    cycle, otherwise the audit_score from the next cycle could mask
    the divergence.
    """
    audit_dir = tmp_path / ".agent-team" / "audits" / "milestone-3"
    audit_dir.mkdir(parents=True)
    agent_team_dir = tmp_path / ".agent-team"
    anchor_dir = agent_team_dir / "milestones" / "milestone-3" / "_anchor"
    anchor_dir.mkdir(parents=True)

    config = _make_loop_config()
    # Higher max_cycles so an extra iteration would be visible.
    config.audit_team.max_reaudit_cycles = 5
    state = _make_run_state()

    cycle_count = {"audit": 0, "fix": 0}

    async def _fake_audit(**kwargs):
        cycle_count["audit"] += 1
        return SimpleNamespace(
            cycle=cycle_count["audit"],
            score=SimpleNamespace(score=70.0, health="degraded"),
            findings=[
                SimpleNamespace(
                    file_path="apps/web/x.tsx",
                    severity="HIGH",
                    auditor="test",
                    requirement_id="REQ-001",
                    summary="x",
                )
            ],
            to_json=lambda: "{}",
        ), 0.0

    async def _fake_fix_unified(*args, **kwargs):
        cycle_count["fix"] += 1
        raise CrossMilestoneLockViolation(
            finding_id="F-LOCK-004",
            regressed_acs=[],
            regressed_tests=["e2e/tests/break.spec.ts"],
            finding_surface=["e2e/tests/scope.spec.ts"],
        )

    def _fake_handler(**kwargs):
        return {"reverted": [], "deleted": [], "restored": []}

    with patch.object(cli_mod, "_run_milestone_audit", side_effect=_fake_audit), \
         patch.object(cli_mod, "_run_audit_fix_unified", side_effect=_fake_fix_unified), \
         patch.object(
             cli_mod,
             "_handle_audit_failure_milestone_anchor",
             side_effect=_fake_handler,
         ):
        asyncio.run(
            cli_mod._run_audit_loop(
                milestone_id="milestone-3",
                milestone_template=None,
                config=config,
                depth="standard",
                task_text="",
                requirements_path=str(tmp_path / "REQUIREMENTS.md"),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
                state=state,
                agent_team_dir=str(agent_team_dir),
                milestone_anchor_dir=str(anchor_dir),
            )
        )

    # Cycle 1: audit runs (cycle_count["audit"]=1). Cycle 2: audit-fix
    # raises the lock violation (cycle_count["fix"]=1). Loop should
    # break — no further audit cycles.
    assert cycle_count["fix"] == 1
    assert cycle_count["audit"] <= 2, (
        f"Expected loop to break after lock violation; saw "
        f"{cycle_count['audit']} audit cycles run"
    )
