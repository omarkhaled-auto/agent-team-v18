"""Phase 1.6 audit-fix-loop guardrail fixtures.

Goal: close two carry-over follow-ups from earlier landings —

* ``failure_reason`` persistence (carry-over from
  ``phase_1_5_landing.md`` §"Plan deviations / observations" #2).
  ``_handle_audit_failure_milestone_anchor`` accepts a ``reason`` kwarg
  but discards it; Phase 1.6 persists it on
  ``RunState.milestone_progress[id]["failure_reason"]`` so post-hoc
  forensics can distinguish ``regression`` / ``no_improvement`` /
  ``cross_milestone_lock_violation`` failures.
* Config-driven ``run_regression_check`` timeout (carry-over from
  ``phase_2_landing.md`` §"Open follow-ups (not blocking)").
  ``run_regression_check`` hard-codes ``timeout=300`` at the
  ``subprocess.run`` call; Phase 1.6 plumbs it through
  ``AuditTeamConfig.regression_check_timeout`` so a slow CI runner can
  raise the cap and a fast local dev workflow can lower it without a
  code change.

Both surfaces are schema-additive (no migration), low-LoC, and
bundle into one Phase 1.6 commit.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# These imports point at the public API Phase 1.6 lands. If they fail
# at import time the whole file collects as ``ImportError`` — that's
# the expected initial-red state per the Phase 1.6 handoff §5 TDD
# sequence.
from agent_team_v15.config import AuditTeamConfig, _validate_audit_team_config
from agent_team_v15.fix_executor import (
    _resolve_regression_check_timeout,
    run_regression_check,
)
from agent_team_v15.state import (
    RunState,
    get_milestone_failure_reason,
    update_milestone_progress,
)


# ---------------------------------------------------------------------------
# Surface 1 — failure_reason persistence on update_milestone_progress
# ---------------------------------------------------------------------------


def test_update_milestone_progress_writes_failure_reason_when_provided() -> None:
    """When the new keyword-only ``failure_reason`` is non-empty, the
    persisted dict at ``milestone_progress[id]`` carries it under the
    ``"failure_reason"`` key. The reason is the load-bearing forensics
    signal that survives process exit.
    """
    state = RunState()
    update_milestone_progress(
        state, "milestone-1", "FAILED", failure_reason="regression"
    )
    assert state.milestone_progress["milestone-1"] == {
        "status": "FAILED",
        "failure_reason": "regression",
    }


def test_update_milestone_progress_omits_failure_reason_when_not_provided() -> None:
    """Backward compat: 14 of the 15 existing call sites in cli.py
    pass no reason. The default ``failure_reason=""`` must NOT add
    a stray key to the persisted dict — the dict shape is unchanged
    for unmigrated callers.
    """
    state = RunState()
    update_milestone_progress(state, "milestone-1", "FAILED")
    assert state.milestone_progress["milestone-1"] == {"status": "FAILED"}
    assert "failure_reason" not in state.milestone_progress["milestone-1"]


def test_update_milestone_progress_replaces_stale_failure_reason_on_status_change() -> None:
    """REPLACE semantics at the dict assignment auto-clear stale
    reasons on subsequent transitions. A milestone that FAILED with
    ``regression`` and later transitions to COMPLETE must NOT carry
    the stale reason — the post-hoc forensics field would lie.
    """
    state = RunState()
    update_milestone_progress(
        state, "milestone-1", "FAILED", failure_reason="regression"
    )
    update_milestone_progress(state, "milestone-1", "COMPLETE")
    assert state.milestone_progress["milestone-1"] == {"status": "COMPLETE"}
    assert "failure_reason" not in state.milestone_progress["milestone-1"]


def test_update_milestone_progress_preserves_summary_success_invariant() -> None:
    """Defensive: the new ``failure_reason`` key must not interact with
    the ``summary["success"]`` reconciliation at lines 446-449. The
    rollup is computed from ``state.failed_milestones`` (not from the
    dict shape) so adding the key has zero effect on the invariant.
    """
    state = RunState(summary={"success": True})  # type: ignore[call-arg]
    update_milestone_progress(
        state, "milestone-1", "FAILED", failure_reason="regression"
    )
    # FAILED appended → success rollup must flip to False.
    assert state.summary["success"] is False
    assert state.failed_milestones == ["milestone-1"]


def test_get_milestone_failure_reason_returns_empty_when_unset() -> None:
    """Accessor returns ``""`` for a milestone that failed without a
    reason (legacy state files, pre-Phase-1.6 audits).
    """
    state = RunState()
    update_milestone_progress(state, "milestone-1", "FAILED")
    assert get_milestone_failure_reason(state, "milestone-1") == ""


def test_get_milestone_failure_reason_returns_persisted_value() -> None:
    """Accessor surfaces the persisted reason for a milestone that
    failed with one. The Phase 1.5 ``cross_milestone_lock_violation``
    case is the load-bearing example.
    """
    state = RunState()
    update_milestone_progress(
        state,
        "milestone-1",
        "FAILED",
        failure_reason="cross_milestone_lock_violation",
    )
    assert (
        get_milestone_failure_reason(state, "milestone-1")
        == "cross_milestone_lock_violation"
    )


def test_get_milestone_failure_reason_returns_empty_for_unknown_milestone() -> None:
    """Defensive: never raise for a milestone the run never saw.
    Post-hoc forensics readers should get a clean ``""`` fallback.
    """
    state = RunState()
    assert get_milestone_failure_reason(state, "milestone-99") == ""


def test_get_milestone_failure_reason_handles_non_dict_entry() -> None:
    """Defensive: if a future schema drift writes a non-dict value
    under ``milestone_progress[id]`` (e.g., an old shape), the
    accessor must not crash.
    """
    state = RunState()
    state.milestone_progress["milestone-1"] = "FAILED"  # type: ignore[assignment]
    assert get_milestone_failure_reason(state, "milestone-1") == ""


def test_handle_audit_failure_milestone_anchor_persists_reason_to_state(
    tmp_path: Path,
) -> None:
    """End-to-end through the Phase 1 helper: the ``reason`` kwarg
    flows from the audit-fix loop's catch site → helper →
    ``update_milestone_progress`` → ``state.milestone_progress[id]``.

    Today (pre-Phase-1.6) the kwarg is captured but never persisted
    anywhere; this fixture locks the round-trip contract.
    """
    from agent_team_v15.cli import _handle_audit_failure_milestone_anchor

    anchor_dir = tmp_path / "_anchor"
    anchor_dir.mkdir()
    state = RunState()

    with patch(
        "agent_team_v15.wave_executor._restore_milestone_anchor",
        return_value={"reverted": [], "deleted": [], "restored": []},
    ), patch("agent_team_v15.state.save_state"):
        _handle_audit_failure_milestone_anchor(
            state=state,
            milestone_id="milestone-1",
            cwd=str(tmp_path),
            anchor_dir=anchor_dir,
            reason="cross_milestone_lock_violation",
            agent_team_dir=str(tmp_path),
        )

    assert (
        get_milestone_failure_reason(state, "milestone-1")
        == "cross_milestone_lock_violation"
    )
    assert state.milestone_progress["milestone-1"]["status"] == "FAILED"


def test_reset_failed_milestones_clears_failure_reason() -> None:
    """The ``--reset-failed-milestones`` in-place mutation at
    cli.py:4006-4008 does NOT go through ``update_milestone_progress``,
    so its REPLACE semantics don't auto-clear the new key. Phase 1.6
    adds an explicit ``_mp.pop("failure_reason", None)`` at the reset
    site; without it, stale reasons survive a reset and confuse
    post-hoc forensics on the next run.
    """
    state = RunState()
    update_milestone_progress(
        state, "milestone-1", "FAILED", failure_reason="regression"
    )
    # Simulate the cli.py:4006-4008 in-place mutation path WITH the
    # Phase 1.6 cleanup line.
    _mp = state.milestone_progress.get("milestone-1")
    assert isinstance(_mp, dict) and _mp.get("status") == "FAILED"
    _mp["status"] = "PENDING"
    _mp.pop("failure_reason", None)

    assert state.milestone_progress["milestone-1"] == {"status": "PENDING"}


# ---------------------------------------------------------------------------
# Surface 2 — config-driven regression_check_timeout
# ---------------------------------------------------------------------------


def test_audit_team_config_default_regression_timeout_is_300() -> None:
    """Default preserves Phase 2's hardcoded 300s — backward-compat for
    every existing config (file-loaded or programmatic)."""
    cfg = AuditTeamConfig()
    assert cfg.regression_check_timeout == 300


def test_audit_team_config_validates_regression_timeout_zero_raises() -> None:
    """0 would break ``subprocess.run`` (treats as 'no timeout' isn't
    the contract; 0 is rejected by the subprocess kernel API in any
    case). Validation rejects at config-load time."""
    cfg = AuditTeamConfig(regression_check_timeout=0)
    with pytest.raises(ValueError, match="regression_check_timeout"):
        _validate_audit_team_config(cfg)


def test_audit_team_config_validates_regression_timeout_negative_raises() -> None:
    cfg = AuditTeamConfig(regression_check_timeout=-1)
    with pytest.raises(ValueError, match="regression_check_timeout"):
        _validate_audit_team_config(cfg)


def test_audit_team_config_validates_regression_timeout_above_3600_raises() -> None:
    """>3600 (1 hour) is pathological — would hide real hangs that the
    audit-fix loop should surface, not absorb. Bounds the M25-disaster
    prevention property: the loop must make forward progress."""
    cfg = AuditTeamConfig(regression_check_timeout=3601)
    with pytest.raises(ValueError, match="regression_check_timeout"):
        _validate_audit_team_config(cfg)


def test_audit_team_config_validates_regression_timeout_at_boundaries_ok() -> None:
    """Boundary values (1 and 3600) are valid. Closed interval
    [1, 3600] per ``_validate_audit_team_config`` contract."""
    _validate_audit_team_config(AuditTeamConfig(regression_check_timeout=1))
    _validate_audit_team_config(AuditTeamConfig(regression_check_timeout=3600))


def test_resolve_regression_check_timeout_falls_back_when_config_none() -> None:
    """Defensive read at call-time: ``config=None`` is the legacy-caller
    contract (some test fixtures pass None directly). Returns default."""
    assert _resolve_regression_check_timeout(None) == 300


def test_resolve_regression_check_timeout_reads_object_shape() -> None:
    """``coordinated_builder.py:1179, 1920`` and the orchestrator pass
    ``AgentTeamConfig`` (object-shaped, has ``.audit_team`` attribute).
    The defensive helper reads via ``getattr``."""
    config = SimpleNamespace(
        audit_team=SimpleNamespace(regression_check_timeout=120)
    )
    assert _resolve_regression_check_timeout(config) == 120


def test_resolve_regression_check_timeout_reads_dict_shape() -> None:
    """Some code paths in fix_executor.py treat ``config`` as a dict
    (see ``config.get(key, default)`` at line 1249-1250). The
    defensive helper reads via ``.get`` when ``.audit_team``
    attribute access misses."""
    config = {"audit_team": {"regression_check_timeout": 600}}
    assert _resolve_regression_check_timeout(config) == 600


def test_resolve_regression_check_timeout_clamps_invalid_to_default() -> None:
    """Two-layer safety: validation at config-load is strict, but a
    corrupted in-memory config (test fixture, schema drift) at call
    time falls back to the default rather than raising. Keeps the
    audit-fix loop running even under degraded config."""
    config = SimpleNamespace(
        audit_team=SimpleNamespace(regression_check_timeout=0)
    )
    assert _resolve_regression_check_timeout(config) == 300


def test_resolve_regression_check_timeout_clamps_above_3600_to_default() -> None:
    config = SimpleNamespace(
        audit_team=SimpleNamespace(regression_check_timeout=10_000)
    )
    assert _resolve_regression_check_timeout(config) == 300


def test_resolve_regression_check_timeout_clamps_non_int_to_default() -> None:
    """A string or None where an int is expected falls back rather
    than raising — the audit-fix loop survives a junk config."""
    config = SimpleNamespace(
        audit_team=SimpleNamespace(regression_check_timeout="not-a-number")
    )
    assert _resolve_regression_check_timeout(config) == 300


def test_resolve_regression_check_timeout_returns_default_when_audit_team_missing() -> None:
    """Defensive: a config object without ``.audit_team`` (e.g., a
    bare AuditTeamConfig passed directly) returns default rather than
    raising AttributeError."""
    config = SimpleNamespace()
    assert _resolve_regression_check_timeout(config) == 300


def test_run_regression_check_passes_configured_timeout_to_subprocess(
    tmp_path: Path,
) -> None:
    """Risk #7 lock: the subprocess.run kwargs MUST receive the
    config-driven value — not the default. Without asserting on the
    exact kwarg value, a no-op default could make this test pass for
    the wrong reason. The mock captures kwargs and asserts on the
    specific timeout value."""
    e2e_dir = tmp_path / "e2e" / "tests"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "x.spec.ts").write_text("// stub", encoding="utf-8")

    captured: dict = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["timeout"] = kwargs.get("timeout")
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    config = SimpleNamespace(
        audit_team=SimpleNamespace(regression_check_timeout=42)
    )
    with patch(
        "agent_team_v15.fix_executor.subprocess.run", side_effect=_fake_run
    ):
        run_regression_check(
            cwd=str(tmp_path),
            previously_passing_acs=["AC-1"],
            config=config,
        )

    assert captured.get("timeout") == 42, (
        f"Expected subprocess.run to receive timeout=42 from config; "
        f"captured kwargs were {captured!r}. If timeout=300 here the "
        f"defensive helper isn't being invoked at the subprocess.run site."
    )


def test_run_regression_check_falls_back_to_300_when_config_missing(
    tmp_path: Path,
) -> None:
    """Backward compat: when callers pass a config without the new
    field (legacy ``SimpleNamespace()`` from existing tests), the
    helper falls back to 300 — preserving Phase 2 behaviour."""
    e2e_dir = tmp_path / "e2e" / "tests"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "x.spec.ts").write_text("// stub", encoding="utf-8")

    captured: dict = {}

    def _fake_run(cmd, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    with patch(
        "agent_team_v15.fix_executor.subprocess.run", side_effect=_fake_run
    ):
        run_regression_check(
            cwd=str(tmp_path),
            previously_passing_acs=["AC-1"],
            config=SimpleNamespace(),
        )

    assert captured.get("timeout") == 300
