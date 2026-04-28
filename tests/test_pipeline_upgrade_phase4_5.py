"""Phase 4.5 pipeline-upgrade — synthetic + replay fixtures.

Covers the seven acceptance criteria (AC1-AC7) listed in
``docs/plans/2026-04-26-pipeline-upgrade-phase4.md`` §H + §0.6:

* AC1: When safety nets disabled, ``_run_audit_fix_unified`` short-circuits.
* AC2: When safety nets armed, audit-fix runs on wave-fail.
* AC3: Audit-fix dispatch skips features whose findings are DEFERRED
       (Phase 4.3 wave-awareness gate threaded by Phase 4.5).
* AC4: Re-self-verify after the audit loop terminates non-FAILED.
* AC5: Re-self-verify failure → anchor restore + FAILED with
       ``failure_reason="audit_fix_did_not_recover_build"``.
* AC6: Re-self-verify success → milestone FAILED→COMPLETE +
       ``failure_reason="wave_fail_recovered"``.
* AC7: Replay smoke 2026-04-26 — only the 3 Codex bug features are
       eligible for dispatch; the 4 frontend chassis features are
       DEFERRED to Wave D.

Plus defensive paths: kill-switch flip, hook-marker absent, Phase 4.4
bypass interaction.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15.audit_models import AuditScore


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_audit_fix_path_guard_settings(cwd: Path) -> Path:
    """Materialise the Phase 3 audit-fix path-guard hook marker."""

    settings_dir = cwd / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path = settings_dir / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "PreToolUse": [
                    {
                        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python -m agent_team_v15.audit_fix_path_guard",
                                "timeout": 5,
                            }
                        ],
                        "agent_team_v15_audit_fix_path_guard": True,
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return settings_path


def _make_armed_audit_cfg(**overrides: object) -> SimpleNamespace:
    """Build a SimpleNamespace AuditTeamConfig with all four safety nets armed."""

    base = {
        "enabled": True,
        "lift_risk_1_when_nets_armed": True,
        "milestone_anchor_enabled": True,
        "test_surface_lock_enabled": True,
        "audit_wave_awareness_enabled": True,
        "failed_milestone_audit_on_wave_fail_enabled": False,
        "max_reaudit_cycles": 2,
        "fix_severity_threshold": "MEDIUM",
        "score_healthy_threshold": 90.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_finding(finding_id: str, primary_file: str) -> SimpleNamespace:
    return SimpleNamespace(
        finding_id=finding_id,
        auditor="test",
        requirement_id="REQ-001",
        verdict="FAIL",
        severity="HIGH",
        summary=f"finding {finding_id}",
        evidence=[f"{primary_file}:1 -- synthetic"],
        remediation="",
        confidence=1.0,
        source="llm",
        primary_file=primary_file,
    )


# ---------------------------------------------------------------------------
# AC1 — short-circuit when any safety net disabled (the degraded-config
# fallback). Already locked in tests/test_audit_fix_guardrails_phase1.py
# but re-validated here under Phase 4.5's vocabulary for the four
# discrete net-off cases.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "off_net",
    [
        "milestone_anchor_enabled",
        "test_surface_lock_enabled",
        "audit_wave_awareness_enabled",
        "lift_risk_1_when_nets_armed",
    ],
)
def test_run_audit_fix_unified_short_circuits_when_safety_nets_disabled(
    tmp_path: Path,
    off_net: str,
) -> None:
    """Each of the four config-driven safety nets, when disabled in
    isolation, MUST cause ``_run_audit_fix_unified`` to short-circuit on
    wave-fail (preserves Phase 1 Risk #1 fallback contract). The hook
    marker is intentionally INSTALLED so the only degraded net is the
    one parametrised.
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import fix_executor as fix_mod

    _write_audit_fix_path_guard_settings(tmp_path)
    overrides = {off_net: False}
    audit_cfg = _make_armed_audit_cfg(**overrides)
    failed_wave = SimpleNamespace(success=False, error_wave="B", waves=[])
    report = SimpleNamespace(
        findings=[_make_finding("F1", "apps/api/src/main.ts")],
        fix_candidates=[0],
    )

    with patch.object(
        fix_mod, "execute_unified_fix_async", autospec=True
    ) as mock_dispatch:
        modified, cost = asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=SimpleNamespace(audit_team=audit_cfg),
                cwd=str(tmp_path),
                task_text="",
                depth="standard",
                wave_result=failed_wave,
            )
        )

    assert modified == []
    assert cost == 0.0
    mock_dispatch.assert_not_called()


def test_run_audit_fix_unified_short_circuits_when_hook_settings_absent(
    tmp_path: Path,
) -> None:
    """Phase 3 hook is the fourth safety net. With ALL config knobs ON
    but the marker missing from ``.claude/settings.json``, the lift
    cannot fire; the legacy short-circuit must fall through.
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import fix_executor as fix_mod

    # Deliberately do NOT write .claude/settings.json — fourth net off.
    audit_cfg = _make_armed_audit_cfg()
    failed_wave = SimpleNamespace(success=False, error_wave="D", waves=[])
    report = SimpleNamespace(
        findings=[_make_finding("F1", "apps/web/src/middleware.ts")],
        fix_candidates=[0],
    )

    with patch.object(
        fix_mod, "execute_unified_fix_async", autospec=True
    ) as mock_dispatch:
        modified, cost = asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=SimpleNamespace(audit_team=audit_cfg),
                cwd=str(tmp_path),
                task_text="",
                depth="standard",
                wave_result=failed_wave,
            )
        )

    assert modified == []
    assert cost == 0.0
    mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# AC2 — audit-fix runs on wave-fail when ALL safety nets armed.
# ---------------------------------------------------------------------------


def test_run_audit_fix_unified_runs_on_wave_fail_when_safety_nets_armed(
    tmp_path: Path,
) -> None:
    """When every safety net is armed AND the lift kill switch is True,
    the wave-fail short-circuit must NOT fire — the function falls
    through to ``execute_unified_fix_async``.
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import fix_executor as fix_mod

    _write_audit_fix_path_guard_settings(tmp_path)
    audit_cfg = _make_armed_audit_cfg()
    failed_wave = SimpleNamespace(success=False, error_wave="B", waves=[])
    report = SimpleNamespace(
        findings=[_make_finding("F1", "apps/api/src/main.ts")],
        fix_candidates=[0],
    )

    async def _fake_execute_unified_fix_async(*args: object, **kwargs: object) -> float:
        return 0.0

    # ``_run_audit_fix_unified`` resolves the original PRD path BEFORE
    # invoking ``execute_unified_fix_async``; on tmp_path it will fail
    # to find the PRD. Stub the resolver and the fix dispatcher so the
    # gate's fall-through is what we observe — no env-side errors.
    with patch.object(
        fix_mod, "execute_unified_fix_async", side_effect=_fake_execute_unified_fix_async
    ) as mock_dispatch, patch.object(
        cli_mod, "_resolve_original_prd_path_for_test", create=True, return_value=tmp_path / "PRD.md",
    ):
        # Provide a minimal PRD on disk so any real resolver succeeds.
        (tmp_path / "PRD.md").write_text("# stub", encoding="utf-8")
        modified, cost = asyncio.run(
            cli_mod._run_audit_fix_unified(
                report=report,
                config=SimpleNamespace(
                    audit_team=audit_cfg,
                    v18=SimpleNamespace(codex_fix_routing_enabled=False),
                ),
                cwd=str(tmp_path),
                task_text="",
                depth="standard",
                wave_result=failed_wave,
            )
        )

    # Dispatch IS invoked (lift active + nets armed). The dispatcher
    # was stubbed to a no-op so cost is 0.0; the load-bearing assertion
    # is that the short-circuit DID NOT fire.
    assert mock_dispatch.called, (
        "Phase 4.5 lift should fall through to execute_unified_fix_async "
        "when every safety net is armed; observed short-circuit instead."
    )
    assert isinstance(modified, list)
    assert isinstance(cost, float)


# ---------------------------------------------------------------------------
# AC2.b — _phase_4_5_safety_nets_armed helper is the single resolver.
# ---------------------------------------------------------------------------


def test_phase_4_5_safety_nets_armed_returns_true_when_all_present(
    tmp_path: Path,
) -> None:
    """All four safety nets armed → True."""

    from agent_team_v15 import cli as cli_mod

    _write_audit_fix_path_guard_settings(tmp_path)
    audit_cfg = _make_armed_audit_cfg()
    config = SimpleNamespace(audit_team=audit_cfg)

    assert cli_mod._phase_4_5_safety_nets_armed(config, str(tmp_path)) is True


@pytest.mark.parametrize(
    "knob",
    [
        "milestone_anchor_enabled",
        "test_surface_lock_enabled",
        "audit_wave_awareness_enabled",
    ],
)
def test_phase_4_5_safety_nets_armed_returns_false_when_config_knob_off(
    tmp_path: Path, knob: str,
) -> None:
    """Disabling any config knob (other than lift_risk_1_when_nets_armed,
    which is read by the caller) flips the helper to False.
    """

    from agent_team_v15 import cli as cli_mod

    _write_audit_fix_path_guard_settings(tmp_path)
    audit_cfg = _make_armed_audit_cfg(**{knob: False})
    config = SimpleNamespace(audit_team=audit_cfg)

    assert cli_mod._phase_4_5_safety_nets_armed(config, str(tmp_path)) is False


def test_phase_4_5_safety_nets_armed_returns_false_when_no_settings_json(
    tmp_path: Path,
) -> None:
    """Missing ``.claude/settings.json`` → fourth net off → helper False."""

    from agent_team_v15 import cli as cli_mod

    audit_cfg = _make_armed_audit_cfg()
    config = SimpleNamespace(audit_team=audit_cfg)

    assert cli_mod._phase_4_5_safety_nets_armed(config, str(tmp_path)) is False


def test_phase_4_5_safety_nets_armed_handles_missing_audit_team(
    tmp_path: Path,
) -> None:
    """Defensive path: config without ``audit_team`` attribute returns False."""

    from agent_team_v15 import cli as cli_mod

    config = SimpleNamespace()  # No audit_team
    assert cli_mod._phase_4_5_safety_nets_armed(config, str(tmp_path)) is False


# ---------------------------------------------------------------------------
# audit_fix_path_guard_settings_present — module helper contract.
# ---------------------------------------------------------------------------


def test_audit_fix_path_guard_settings_present_true_with_marker(
    tmp_path: Path,
) -> None:
    """Marker present → True."""

    from agent_team_v15.agent_teams_backend import (
        audit_fix_path_guard_settings_present,
    )

    _write_audit_fix_path_guard_settings(tmp_path)
    assert audit_fix_path_guard_settings_present(str(tmp_path)) is True


def test_audit_fix_path_guard_settings_present_false_without_marker(
    tmp_path: Path,
) -> None:
    """Settings file with PreToolUse but missing marker → False."""

    from agent_team_v15.agent_teams_backend import (
        audit_fix_path_guard_settings_present,
    )

    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "echo"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert audit_fix_path_guard_settings_present(str(tmp_path)) is False


def test_audit_fix_path_guard_settings_present_false_when_settings_missing(
    tmp_path: Path,
) -> None:
    """No ``.claude/settings.json`` at all → False."""

    from agent_team_v15.agent_teams_backend import (
        audit_fix_path_guard_settings_present,
    )

    assert audit_fix_path_guard_settings_present(str(tmp_path)) is False


def test_audit_fix_path_guard_settings_present_false_for_none_cwd() -> None:
    """``None``/empty cwd → False (defensive)."""

    from agent_team_v15.agent_teams_backend import (
        audit_fix_path_guard_settings_present,
    )

    assert audit_fix_path_guard_settings_present(None) is False
    assert audit_fix_path_guard_settings_present("") is False


# ---------------------------------------------------------------------------
# AC3 — Phase 4.3 DEFERRED gate threaded by Phase 4.5: features whose
# findings all belong to a non-executed wave get
# ``skip_reason="owner_wave_deferred"`` from ``_classify_fix_features``
# when ``run_state`` is supplied.
# ---------------------------------------------------------------------------


def test_audit_fix_dispatch_skips_features_whose_findings_are_deferred(
    tmp_path: Path,
) -> None:
    """When ``run_state`` is threaded through ``_classify_fix_features``
    (Phase 4.5's primary Phase-4.3 carry-over wiring), a feature whose
    every file maps to a wave that has NOT executed gains
    ``skip_reason="owner_wave_deferred"``. ``_run_patch_fixes`` (Phase
    4.3-wired) short-circuits on the tag without invoking the SDK.
    """

    from agent_team_v15 import fix_executor as fix_mod
    from agent_team_v15.state import RunState

    # Wave A executed; Wave D never executed.
    state = RunState()
    state.wave_progress = {
        "milestone-1": {"completed_waves": ["A"], "failed_wave": "B"}
    }

    fix_prd_text = (
        "## Features\n\n"
        "### F-FIX-001: D-frontend-chassis\n"
        "[SEVERITY: CRITICAL]\n"
        "[EXECUTION_MODE: patch]\n\n"
        "Apply locale-aware middleware fixes.\n\n"
        "#### Files to Modify\n"
        "- `apps/web/src/middleware.ts`\n\n"
        "#### Files to Create\n"
        "- `apps/web/src/i18n/index.ts`\n\n"
        "#### Acceptance Criteria\n"
        "- AC-FIX-001: routes localised\n\n"
        "### F-FIX-002: B-backend-real-codex-bug\n"
        "[SEVERITY: HIGH]\n"
        "[EXECUTION_MODE: patch]\n\n"
        "Fix duplicate prisma client.\n\n"
        "#### Files to Modify\n"
        "- `apps/api/src/main.ts`\n\n"
        "#### Acceptance Criteria\n"
        "- AC-FIX-002: prisma single-instance\n"
    )

    features = fix_mod._classify_fix_features(
        fix_prd_text, tmp_path, run_state=state,
    )

    deferred = [f for f in features if f.get("skip_reason") == "owner_wave_deferred"]
    actionable = [f for f in features if f.get("skip_reason") != "owner_wave_deferred"]

    assert len(deferred) == 1, (
        f"Phase 4.3 wave-awareness must defer the apps/web feature; "
        f"got deferred={[f.get('name') for f in deferred]}"
    )
    assert deferred[0].get("deferred_to_wave") == "D"
    assert any(
        "apps/api" in str(p)
        for f in actionable
        for p in (f.get("files_to_modify", []) + f.get("files_to_create", []))
    ), "Wave B feature with apps/api files must remain actionable."


# ---------------------------------------------------------------------------
# AC4 + AC6 — re-self-verify after audit-fix terminates non-FAILED;
# success path mutates state to COMPLETE + ``wave_fail_recovered``.
# ---------------------------------------------------------------------------


def test_re_self_verify_success_marks_milestone_complete_and_recovered(
    tmp_path: Path,
) -> None:
    """After ``_run_audit_loop`` terminates without firing the anchor
    restore AND ``wave_result`` was originally failed, the Phase 4.5
    epilogue must call the per-wave self-verify. On pass: state updates
    to COMPLETE with ``failure_reason="wave_fail_recovered"``.
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15.state import RunState

    _write_audit_fix_path_guard_settings(tmp_path)
    state = RunState()
    state.milestone_progress = {
        "milestone-1": {"status": "FAILED", "failure_reason": "wave_b_failed"}
    }

    # Mock the audit-loop's internal dependencies so it terminates
    # cleanly on the FIRST cycle without firing the anchor restore.
    score = AuditScore(
        total_items=10, passed=10, failed=0, partial=0,
        critical_count=0, high_count=0, medium_count=0, low_count=0, info_count=0,
        score=95.0, health="passed", max_score=100,
    )
    healthy_report = SimpleNamespace(
        cycle=1,
        findings=[],
        score=score,
        to_json=lambda: '{"score":{"score":95,"health":"passed"}}',
    )
    failed_wave = SimpleNamespace(success=False, error_wave="B", waves=[])

    audit_cfg = _make_armed_audit_cfg(max_reaudit_cycles=1)
    config = SimpleNamespace(
        audit_team=audit_cfg,
        v18=SimpleNamespace(
            audit_fix_iteration_enabled=False,
            codex_fix_routing_enabled=False,
        ),
        tracking_documents=SimpleNamespace(fix_cycle_log=False),
        convergence=SimpleNamespace(requirements_dir=".agent-team"),
    )

    audit_dir = tmp_path / ".agent-team" / "milestone-1"
    audit_dir.mkdir(parents=True, exist_ok=True)
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    anchor_dir = agent_team_dir / "milestones" / "milestone-1" / "_anchor"
    anchor_dir.mkdir(parents=True, exist_ok=True)

    # Wave B re-self-verify result: PASS.
    fake_b_result = SimpleNamespace(
        passed=True,
        violations=[],
        build_failures=[],
        error_summary="",
        retry_prompt_suffix="",
        env_unavailable=False,
    )

    async def _fake_run_milestone_audit(*args: object, **kwargs: object):
        return healthy_report, 0.0

    with patch.object(
        cli_mod, "_run_milestone_audit", side_effect=_fake_run_milestone_audit
    ), patch(
        "agent_team_v15.wave_b_self_verify.run_wave_b_acceptance_test",
        return_value=fake_b_result,
    ) as mock_b:
        result_report, cost = asyncio.run(
            cli_mod._run_audit_loop(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=config,
                depth="standard",
                task_text="",
                requirements_path=str(audit_dir / "REQUIREMENTS.md"),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
                state=state,
                agent_team_dir=str(agent_team_dir),
                milestone_anchor_dir=anchor_dir,
                wave_result=failed_wave,
            )
        )

    assert mock_b.called, "Phase 4.5 epilogue must invoke run_wave_b_acceptance_test"
    assert state.milestone_progress["milestone-1"]["status"] == "COMPLETE"
    assert state.milestone_progress["milestone-1"]["failure_reason"] == "wave_fail_recovered"


# ---------------------------------------------------------------------------
# AC5 — re-self-verify failure → anchor restore + FAILED with
# ``failure_reason="audit_fix_did_not_recover_build"``.
# ---------------------------------------------------------------------------


def test_re_self_verify_failure_triggers_anchor_restore_and_marks_failed(
    tmp_path: Path,
) -> None:
    """When the Phase 4.5 epilogue's re-self-verify FAILS, the anchor
    must be restored AND the milestone re-marked FAILED with
    ``failure_reason="audit_fix_did_not_recover_build"``.
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15 import wave_executor as wave_executor_mod
    from agent_team_v15.state import RunState

    _write_audit_fix_path_guard_settings(tmp_path)

    # Capture an actual anchor so the restore call has something to do.
    a_path = tmp_path / "a.txt"
    a_path.write_text("original-a", encoding="utf-8")
    anchor_dir = wave_executor_mod._capture_milestone_anchor(str(tmp_path), "milestone-1")
    a_path.write_text("MUTATED", encoding="utf-8")  # post-anchor mutation

    state = RunState()
    state.milestone_progress = {
        "milestone-1": {"status": "FAILED", "failure_reason": "wave_b_failed"}
    }

    score = AuditScore(
        total_items=10, passed=10, failed=0, partial=0,
        critical_count=0, high_count=0, medium_count=0, low_count=0, info_count=0,
        score=95.0, health="passed", max_score=100,
    )
    healthy_report = SimpleNamespace(
        cycle=1, findings=[], score=score,
        to_json=lambda: '{"score":{"score":95,"health":"passed"}}',
    )
    failed_wave = SimpleNamespace(success=False, error_wave="B", waves=[])

    audit_cfg = _make_armed_audit_cfg(max_reaudit_cycles=1)
    config = SimpleNamespace(
        audit_team=audit_cfg,
        v18=SimpleNamespace(
            audit_fix_iteration_enabled=False,
            codex_fix_routing_enabled=False,
        ),
        tracking_documents=SimpleNamespace(fix_cycle_log=False),
        convergence=SimpleNamespace(requirements_dir=".agent-team"),
    )

    audit_dir = tmp_path / ".agent-team" / "milestone-1"
    audit_dir.mkdir(parents=True, exist_ok=True)
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)

    # Wave B re-self-verify result: FAIL.
    fake_b_result = SimpleNamespace(
        passed=False,
        violations=[],
        build_failures=["docker build api"],
        error_summary="api build still fails",
        retry_prompt_suffix="<previous_attempt_failed>...</previous_attempt_failed>",
        env_unavailable=False,
    )

    async def _fake_run_milestone_audit(*args: object, **kwargs: object):
        return healthy_report, 0.0

    with patch.object(
        cli_mod, "_run_milestone_audit", side_effect=_fake_run_milestone_audit
    ), patch(
        "agent_team_v15.wave_b_self_verify.run_wave_b_acceptance_test",
        return_value=fake_b_result,
    ):
        asyncio.run(
            cli_mod._run_audit_loop(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=config,
                depth="standard",
                task_text="",
                requirements_path=str(audit_dir / "REQUIREMENTS.md"),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
                state=state,
                agent_team_dir=str(agent_team_dir),
                milestone_anchor_dir=anchor_dir,
                wave_result=failed_wave,
            )
        )

    assert state.milestone_progress["milestone-1"]["status"] == "FAILED"
    assert (
        state.milestone_progress["milestone-1"]["failure_reason"]
        == "audit_fix_did_not_recover_build"
    )
    # Anchor restore reverted the post-anchor mutation:
    assert a_path.read_text(encoding="utf-8") == "original-a", (
        "Anchor restore must revert the mutated file back to its IN_PROGRESS-entry value"
    )


# ---------------------------------------------------------------------------
# AC4.b — anchor-restore-fired suppresses re-self-verify epilogue.
# ---------------------------------------------------------------------------


def test_re_self_verify_skipped_when_anchor_restore_fired_during_loop(
    tmp_path: Path,
) -> None:
    """If the audit-loop's regression branch already fired the anchor
    restore, the Phase 4.5 epilogue MUST NOT re-self-verify (the
    run-dir is already rolled back; running the wave's self-verify
    on the rolled-back tree would trivially fail and waste budget).
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15.state import RunState
    from agent_team_v15 import wave_executor as wave_executor_mod

    _write_audit_fix_path_guard_settings(tmp_path)

    # Capture a real anchor so the restore call inside the regression
    # branch can succeed and set the suppress flag.
    (tmp_path / "marker.txt").write_text("anchor-content", encoding="utf-8")
    anchor_dir = wave_executor_mod._capture_milestone_anchor(str(tmp_path), "milestone-1")

    state = RunState()
    state.milestone_progress = {
        "milestone-1": {"status": "FAILED", "failure_reason": "wave_b_failed"}
    }

    # Two cycles: cycle-1 produces report_a (critical=1); cycle-2 produces
    # report_b (critical=2 — INCREASE). ``should_terminate_reaudit``
    # returns "regression" on critical_count increase, which triggers
    # ``_handle_audit_failure_milestone_anchor`` → sets the anchor-
    # restore-fired flag → suppresses the Phase 4.5 epilogue. Score
    # stays equal-ish so the legacy score-rollback at line 8183 doesn't
    # fire first.
    score_a = AuditScore(
        total_items=10, passed=8, failed=2, partial=0,
        critical_count=1, high_count=2, medium_count=0, low_count=0, info_count=0,
        score=80.0, health="degraded", max_score=100,
    )
    score_b = AuditScore(
        total_items=10, passed=8, failed=2, partial=0,
        critical_count=2, high_count=2, medium_count=0, low_count=0, info_count=0,
        score=80.0, health="degraded", max_score=100,
    )
    report_a = SimpleNamespace(
        cycle=1, findings=[_make_finding("F1", "apps/api/src/main.ts")],
        score=score_a,
        to_json=lambda: '{"score":{"score":80}}',
    )
    report_b = SimpleNamespace(
        cycle=2, findings=[_make_finding("F1", "apps/api/src/main.ts")],
        score=score_b,
        to_json=lambda: '{"score":{"score":80}}',
    )

    failed_wave = SimpleNamespace(success=False, error_wave="B", waves=[])
    audit_cfg = _make_armed_audit_cfg(max_reaudit_cycles=3)
    config = SimpleNamespace(
        audit_team=audit_cfg,
        v18=SimpleNamespace(
            audit_fix_iteration_enabled=False,
            codex_fix_routing_enabled=False,
        ),
        tracking_documents=SimpleNamespace(fix_cycle_log=False),
        convergence=SimpleNamespace(requirements_dir=".agent-team"),
    )

    audit_dir = tmp_path / ".agent-team" / "milestone-1"
    audit_dir.mkdir(parents=True, exist_ok=True)
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)

    audit_calls: list[None] = []

    async def _fake_run_milestone_audit(*args: object, **kwargs: object):
        audit_calls.append(None)
        return (report_a, 0.0) if len(audit_calls) == 1 else (report_b, 0.0)

    async def _fake_run_audit_fix_unified(*args: object, **kwargs: object):
        return [], 0.0

    re_self_verify_called = MagicMock()

    with patch.object(
        cli_mod, "_run_milestone_audit", side_effect=_fake_run_milestone_audit
    ), patch.object(
        cli_mod, "_run_audit_fix_unified", side_effect=_fake_run_audit_fix_unified
    ), patch(
        "agent_team_v15.wave_b_self_verify.run_wave_b_acceptance_test",
        side_effect=re_self_verify_called,
    ):
        asyncio.run(
            cli_mod._run_audit_loop(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=config,
                depth="standard",
                task_text="",
                requirements_path=str(audit_dir / "REQUIREMENTS.md"),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
                state=state,
                agent_team_dir=str(agent_team_dir),
                milestone_anchor_dir=anchor_dir,
                wave_result=failed_wave,
            )
        )

    assert not re_self_verify_called.called, (
        "Phase 4.5 epilogue must skip re-self-verify when the audit-loop's "
        "anchor-restore branch already fired."
    )
    # Anchor-restore branch sets failure_reason via reason="regression"
    assert state.milestone_progress["milestone-1"]["status"] == "FAILED"


# ---------------------------------------------------------------------------
# AC2 / AC6 cross-check — wave-fail with lift active correctly persists
# ``wave_fail_recovery_attempt`` BEFORE the audit-loop runs.
# ---------------------------------------------------------------------------


def test_failed_milestone_audit_writes_wave_fail_recovery_attempt_when_lift_active(
    tmp_path: Path,
) -> None:
    """``_run_failed_milestone_audit_if_enabled`` should mutate STATE
    to ``failure_reason="wave_fail_recovery_attempt"`` BEFORE invoking
    the audit-loop when the Phase 4.5 lift activates. This is the
    operator signal "audit-fix recovery is in progress" — distinct from
    the Phase 4.4 ``wave_<X>_failed`` mainline write.
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15.state import RunState

    _write_audit_fix_path_guard_settings(tmp_path)

    state = RunState()
    state.milestone_progress = {
        "milestone-1": {"status": "FAILED", "failure_reason": "wave_b_failed"}
    }
    failed_wave = SimpleNamespace(success=False, error_wave="B", waves=[])

    audit_cfg = _make_armed_audit_cfg()
    config = SimpleNamespace(
        audit_team=audit_cfg,
        v18=SimpleNamespace(
            reaudit_trigger_fix_enabled=True,
            codex_fix_routing_enabled=False,
            audit_fix_iteration_enabled=False,
        ),
        tracking_documents=SimpleNamespace(fix_cycle_log=False),
        convergence=SimpleNamespace(requirements_dir=".agent-team"),
    )

    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    audit_dir = agent_team_dir / "milestone-1"
    audit_dir.mkdir(parents=True, exist_ok=True)
    anchor_dir = agent_team_dir / "milestones" / "milestone-1" / "_anchor"
    anchor_dir.mkdir(parents=True, exist_ok=True)

    captured_failure_reason_at_loop_entry: list[str] = []

    async def _fake_audit_loop(*args: object, **kwargs: object):
        captured_failure_reason_at_loop_entry.append(
            str(state.milestone_progress["milestone-1"].get("failure_reason", ""))
        )
        return None, 0.0

    with patch.object(cli_mod, "_run_audit_loop", side_effect=_fake_audit_loop):
        asyncio.run(
            cli_mod._run_failed_milestone_audit_if_enabled(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=config,
                depth="standard",
                task_text="",
                requirements_path=str(audit_dir / "REQUIREMENTS.md"),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
                wave_result=failed_wave,
                state=state,
                agent_team_dir=str(agent_team_dir),
                milestone_anchor_dir=anchor_dir,
            )
        )

    assert captured_failure_reason_at_loop_entry == ["wave_fail_recovery_attempt"], (
        "Phase 4.5 lift must persist 'wave_fail_recovery_attempt' "
        "BEFORE invoking the audit-loop; observed "
        f"{captured_failure_reason_at_loop_entry!r}."
    )


# ---------------------------------------------------------------------------
# Phase 4.4 vs Phase 4.5 interaction — bypass suppressed by lift.
# ---------------------------------------------------------------------------


def test_phase_4_4_forensics_bypass_suppressed_when_phase_4_5_lift_active(
    tmp_path: Path,
) -> None:
    """When the Phase 4.5 lift is active, the Phase 4.4 forensics-only
    bypass MUST NOT fire. Instead the audit-loop dispatches as the
    recovery path. This reconciles the two phases: 4.4 is the default
    wave-fail post-mortem; 4.5 is the recovery option that supersedes
    it when nets are armed.
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15.state import RunState

    _write_audit_fix_path_guard_settings(tmp_path)

    state = RunState()
    failed_wave = SimpleNamespace(success=False, error_wave="B", waves=[])

    audit_cfg = _make_armed_audit_cfg()
    config = SimpleNamespace(
        audit_team=audit_cfg,
        v18=SimpleNamespace(
            reaudit_trigger_fix_enabled=True,
            codex_fix_routing_enabled=False,
            audit_fix_iteration_enabled=False,
        ),
        tracking_documents=SimpleNamespace(fix_cycle_log=False),
        convergence=SimpleNamespace(requirements_dir=".agent-team"),
    )

    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    audit_dir = agent_team_dir / "milestone-1"
    audit_dir.mkdir(parents=True, exist_ok=True)

    audit_loop_invoked: list[None] = []

    async def _fake_audit_loop(*args: object, **kwargs: object):
        audit_loop_invoked.append(None)
        return None, 0.0

    with patch.object(cli_mod, "_run_audit_loop", side_effect=_fake_audit_loop):
        asyncio.run(
            cli_mod._run_failed_milestone_audit_if_enabled(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=config,
                depth="standard",
                task_text="",
                requirements_path=str(audit_dir / "REQUIREMENTS.md"),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
                wave_result=failed_wave,
                state=state,
                agent_team_dir=str(agent_team_dir),
                milestone_anchor_dir=agent_team_dir / "milestones" / "milestone-1" / "_anchor",
            )
        )

    forensics_path = agent_team_dir / "WAVE_FAILURE_FORENSICS.json"
    assert audit_loop_invoked, (
        "Phase 4.5 lift must invoke the audit-loop; observed bypass instead."
    )
    assert not forensics_path.is_file(), (
        "Phase 4.4 forensics-only bypass must be suppressed when Phase 4.5 lift is active "
        f"(found {forensics_path})."
    )


def test_phase_4_4_bypass_still_fires_when_phase_4_5_lift_disabled(
    tmp_path: Path,
) -> None:
    """When ``lift_risk_1_when_nets_armed=False``, Phase 4.4 forensics-only
    bypass MUST fire (legacy Phase 4.4 path preserved for operators who
    haven't opted into the recovery cascade).
    """

    from agent_team_v15 import cli as cli_mod
    from agent_team_v15.state import RunState

    _write_audit_fix_path_guard_settings(tmp_path)

    state = RunState()
    failed_wave = SimpleNamespace(
        success=False, error_wave="B", waves=[],
        files_created=[], files_modified=[],
        findings=[],
    )

    audit_cfg = _make_armed_audit_cfg(lift_risk_1_when_nets_armed=False)
    config = SimpleNamespace(
        audit_team=audit_cfg,
        v18=SimpleNamespace(
            reaudit_trigger_fix_enabled=True,
            codex_fix_routing_enabled=False,
            audit_fix_iteration_enabled=False,
        ),
        tracking_documents=SimpleNamespace(fix_cycle_log=False),
        convergence=SimpleNamespace(requirements_dir=".agent-team"),
    )

    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    audit_dir = agent_team_dir / "milestone-1"
    audit_dir.mkdir(parents=True, exist_ok=True)

    audit_loop_invoked: list[None] = []

    async def _fake_audit_loop(*args: object, **kwargs: object):
        audit_loop_invoked.append(None)
        return None, 0.0

    with patch.object(cli_mod, "_run_audit_loop", side_effect=_fake_audit_loop):
        asyncio.run(
            cli_mod._run_failed_milestone_audit_if_enabled(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=config,
                depth="standard",
                task_text="",
                requirements_path=str(audit_dir / "REQUIREMENTS.md"),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
                wave_result=failed_wave,
                state=state,
                agent_team_dir=str(agent_team_dir),
                milestone_anchor_dir=agent_team_dir / "milestones" / "milestone-1" / "_anchor",
            )
        )

    forensics_path = agent_team_dir / "WAVE_FAILURE_FORENSICS.json"
    assert not audit_loop_invoked, (
        "Phase 4.4 bypass must short-circuit before invoking audit-loop "
        "when Phase 4.5 lift is disabled."
    )
    assert forensics_path.is_file(), (
        "Phase 4.4 forensics-only bypass must produce WAVE_FAILURE_FORENSICS.json "
        "when Phase 4.5 lift is disabled."
    )


# ---------------------------------------------------------------------------
# AC7 — replay smoke 2026-04-26: only Wave B real-Codex-bug features
# would be eligible; the Wave D / Wave C features get DEFERRED.
# ---------------------------------------------------------------------------


_SMOKE_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "smoke_2026_04_26"


def test_replay_smoke_2026_04_26_audit_fix_dispatches_only_real_codex_features() -> None:
    """Load the frozen smoke ``AUDIT_REPORT.json`` (46 findings) and the
    ``STATE.json`` ``wave_progress`` (Wave A completed, Wave B failed,
    Wave C/D never executed). Phase 4.3 ``compute_finding_status``
    must classify findings whose ``owner_wave`` is C/D as DEFERRED;
    only Wave B (executed-but-failed) findings remain actionable for
    Phase 4.5 audit-fix dispatch.
    """

    from agent_team_v15.audit_models import AuditFinding
    from agent_team_v15.state import RunState
    from agent_team_v15.wave_ownership import (
        DEFERRED_STATUS,
        compute_finding_status,
    )

    audit_path = _SMOKE_FIXTURE_DIR / "AUDIT_REPORT.json"
    state_path = _SMOKE_FIXTURE_DIR / "STATE.json"
    assert audit_path.is_file()
    assert state_path.is_file()

    audit_data = json.loads(audit_path.read_text(encoding="utf-8"))
    findings_data = audit_data.get("findings") or []
    findings = [AuditFinding.from_dict(d) for d in findings_data]

    state_data = json.loads(state_path.read_text(encoding="utf-8"))
    state = RunState()
    state.wave_progress = state_data.get("wave_progress", {}) or {}

    statuses_by_wave: dict[str, list[str]] = {}
    for f in findings:
        statuses_by_wave.setdefault(f.owner_wave, []).append(
            compute_finding_status(f, state)
        )

    # 4 Wave-D critical findings (frontend chassis) — all DEFERRED.
    d_deferred = sum(
        1 for status in statuses_by_wave.get("D", []) if status == DEFERRED_STATUS
    )
    assert d_deferred >= 4, (
        f"Expected ≥4 Wave-D findings classified DEFERRED in the smoke replay; "
        f"got {d_deferred}."
    )

    # Wave-C (packages/api-client) findings — DEFERRED.
    c_deferred = sum(
        1 for status in statuses_by_wave.get("C", []) if status == DEFERRED_STATUS
    )
    assert c_deferred >= 1, (
        f"Expected ≥1 Wave-C finding classified DEFERRED; got {c_deferred}."
    )

    # Wave-B findings — actionable (B ran-and-failed; not DEFERRED).
    b_actionable = sum(
        1 for status in statuses_by_wave.get("B", []) if status != DEFERRED_STATUS
    )
    assert b_actionable >= 3, (
        f"Expected ≥3 actionable Wave-B findings (real Codex bugs); "
        f"got {b_actionable}."
    )

    # No Wave-B findings should be DEFERRED — Wave B did execute (and failed).
    b_deferred = sum(
        1 for status in statuses_by_wave.get("B", []) if status == DEFERRED_STATUS
    )
    assert b_deferred == 0, (
        f"Wave-B findings must NOT be DEFERRED (B executed); got {b_deferred}."
    )


# ---------------------------------------------------------------------------
# Config default sanity.
# ---------------------------------------------------------------------------


def test_audit_team_config_default_lift_risk_1_when_nets_armed_is_true() -> None:
    """Default for the kill switch is True (Phase 4.5 active by
    default; flip to False to restore Phase 1 Risk #1 unconditional
    short-circuit).
    """

    from agent_team_v15.config import AuditTeamConfig

    cfg = AuditTeamConfig()
    assert cfg.lift_risk_1_when_nets_armed is True


def test_v18_config_default_reaudit_trigger_fix_enabled_is_true() -> None:
    """Risk #32 closure: the upstream gate inside
    ``_run_failed_milestone_audit_if_enabled`` (cli.py:8106) that
    short-circuits Phase 4.4 forensics + Phase 4.5 cascade + Phase 4.6
    capture-on-recovery is now ON by default. The lift only fires when
    the four safety nets are armed (Phase 4.5 contract); the v18 gate
    being True simply lets the helper enter to evaluate the lift.

    Smoke m1-hardening-smoke-20260427-213258 surfaced this gate as the
    reason stage 2-3 of the cascade never engaged on stock smokes
    (smoke_2026-04-27_landing.md Risk #32). Flipping the default to
    True makes the cascade the production default; explicit False
    remains the rollback path.
    """

    from agent_team_v15.config import V18Config

    cfg = V18Config()
    assert cfg.reaudit_trigger_fix_enabled is True
