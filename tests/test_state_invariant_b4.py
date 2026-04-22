"""Tests for B4: STATE.json invariant append-without-flip fix.

R1B1 root cause: ``RunState.finalize()`` stamped ``summary["success"]=True`` at
milestone-1 wave-A COMPLETE (before any failures). A later gate-FAILED code
path in ``cli.py`` called ``update_milestone_progress(FAILED)`` which appended
to ``failed_milestones`` but did NOT re-run finalize; the next ``save_state``
then raised ``StateInvariantError`` because the cached True survived.

B4 structural fix (two parts):

1. ``update_milestone_progress`` becomes the single resolver of
   ``summary["success"]`` — any mutation of ``failed_milestones`` atomically
   reconciles the cached rollup. Single chokepoint.

2. ``save_state`` coerces any cached ``success=True`` to ``False`` at write
   time when the invariant ``(not interrupted) and len(failed_milestones)==0``
   is False. Self-healing for the pre-finalize edge where summary is still
   ``{}`` and the atomic flip in (1) can't fire.

The invariant raise in ``save_state`` remains as a backstop for genuinely
contradictory states that escape both the single-resolver and the coercion.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_team_v15.state import (
    RunState,
    StateInvariantError,
    load_state,
    save_state,
    update_milestone_progress,
)


# ---------------------------------------------------------------------------
# Part 1: single-resolver reconciliation in update_milestone_progress
# ---------------------------------------------------------------------------


class TestUpdateMilestoneProgressReconciles:
    def test_append_failed_flips_cached_success(self):
        """After finalize() stamps success=True, appending a FAILED milestone
        via update_milestone_progress must flip summary.success to False in
        the same call — without requiring a re-run of finalize."""
        state = RunState(task="x")
        state.finalize()  # no failures yet → success=True
        assert state.summary["success"] is True

        update_milestone_progress(state, "milestone-1", "FAILED")

        assert state.failed_milestones == ["milestone-1"]
        assert state.summary["success"] is False

    def test_complete_retry_after_failure_flips_success_back(self):
        """When a previously FAILED milestone is retried to COMPLETE and it
        was the only failure, update_milestone_progress removes it from
        failed_milestones AND must reconcile summary.success back to True."""
        state = RunState(task="x")
        state.finalize()
        update_milestone_progress(state, "milestone-1", "FAILED")
        assert state.summary["success"] is False

        update_milestone_progress(state, "milestone-1", "COMPLETE")

        assert state.failed_milestones == []
        assert state.summary["success"] is True

    def test_complete_with_other_failures_keeps_success_false(self):
        """Completing one milestone while another is still FAILED must
        not flip success to True — invariant formula handles this."""
        state = RunState(task="x")
        state.finalize()
        update_milestone_progress(state, "milestone-1", "FAILED")
        update_milestone_progress(state, "milestone-2", "IN_PROGRESS")
        update_milestone_progress(state, "milestone-2", "COMPLETE")

        assert state.failed_milestones == ["milestone-1"]
        assert state.summary["success"] is False

    def test_no_summary_key_pre_finalize_is_noop(self):
        """Before the first finalize(), summary is {} — update_milestone_progress
        must NOT create the success key (that's finalize's job). Keeps the
        change minimal; save-time coercion (Part 2) covers the pre-finalize
        edge anyway."""
        state = RunState(task="x")
        assert state.summary == {}

        update_milestone_progress(state, "milestone-1", "FAILED")

        assert "success" not in state.summary
        assert state.failed_milestones == ["milestone-1"]

    def test_interrupted_true_flips_success_false(self):
        """Invariant covers interrupted too: if interrupted is True, success
        must be False even with empty failed_milestones."""
        state = RunState(task="x")
        state.finalize()
        assert state.summary["success"] is True

        state.interrupted = True
        # Any milestone update triggers reconciliation — even IN_PROGRESS
        # would be a no-op for the success field. Use COMPLETE to exercise
        # the "all-green but interrupted" case.
        update_milestone_progress(state, "milestone-1", "COMPLETE")

        assert state.summary["success"] is False


# ---------------------------------------------------------------------------
# Part 2: save_state coerces stale success=True
# ---------------------------------------------------------------------------


class TestSaveStateCoerces:
    def test_coerces_stale_cached_success_true_with_failed_milestone(self, tmp_path):
        """The R1B1 pattern at save-time: state carries summary.success=True
        (e.g. from a prior finalize) but failed_milestones is non-empty. The
        old code raised StateInvariantError here. B4 coerces to False and
        writes a consistent STATE.json."""
        state = RunState(task="x")
        # Simulate a stale cached True — this is what round-trips to disk
        # when a prior finalize at wave-A COMPLETE stamps success=True.
        state.summary = {"success": True}
        state.failed_milestones = ["milestone-1"]

        save_state(state, str(tmp_path))  # must NOT raise

        data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert data["summary"]["success"] is False
        assert data["failed_milestones"] == ["milestone-1"]

    def test_coerces_stale_success_true_when_interrupted(self, tmp_path):
        """Same coercion covers the interrupted=True + cached success=True
        case, even with empty failed_milestones."""
        state = RunState(task="x", interrupted=True)
        state.summary = {"success": True}

        save_state(state, str(tmp_path))

        data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert data["summary"]["success"] is False
        assert data["interrupted"] is True

    def test_clean_run_preserves_success_true(self, tmp_path):
        """Sanity: a genuinely clean state (not interrupted, no failures)
        with finalize-stamped success=True must NOT be coerced — otherwise
        every successful run would report failure."""
        state = RunState(task="x")
        state.finalize()
        assert state.summary["success"] is True

        save_state(state, str(tmp_path))

        data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert data["summary"]["success"] is True
        assert data["failed_milestones"] == []
        assert data["interrupted"] is False

    def test_pre_finalize_empty_summary_computes_invariant(self, tmp_path):
        """Pre-finalize edge: summary is {} and failed_milestones is
        non-empty. File 1's update_milestone_progress gate no-ops because
        "success" isn't in summary yet. File 2's coercion must compute the
        invariant from scratch and write False."""
        state = RunState(task="x")
        # Before any finalize; append directly to simulate the edge.
        state.failed_milestones = ["milestone-1"]
        assert state.summary == {}

        save_state(state, str(tmp_path))

        data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert data["summary"]["success"] is False


# ---------------------------------------------------------------------------
# Part 3: integration — the full R1B1 sequence
# ---------------------------------------------------------------------------


class TestR1B1Scenario:
    def test_wave_a_complete_then_gate_failed_no_raise(self, tmp_path):
        """Reproduces the R1B1 sequence end-to-end:

        1. At wave-A COMPLETE, finalize() stamps summary.success=True while
           failed_milestones is still empty.
        2. A post-milestone gate marks the milestone FAILED via
           update_milestone_progress(FAILED).
        3. save_state runs — before B4 this raised StateInvariantError.
           After B4, it must write a consistent STATE.json with
           success=False and failed_milestones=["milestone-1"].
        """
        # Step 1: wave-A COMPLETE, finalize runs
        state = RunState(task="x")
        state.finalize()  # success=True, failed=[]
        save_state(state, str(tmp_path))
        mid_disk = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert mid_disk["summary"]["success"] is True

        # Step 2: later gate fails the milestone (the single-resolver path)
        update_milestone_progress(state, "milestone-1", "FAILED")

        # Step 3: the save-site that used to raise now writes cleanly
        save_state(state, str(tmp_path))  # must NOT raise

        data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert data["summary"]["success"] is False
        assert data["failed_milestones"] == ["milestone-1"]

    def test_round_trip_through_load_state(self, tmp_path):
        """load_state → mutate via update_milestone_progress → save_state
        must produce a consistent file, exercising the disk round-trip
        that load_state introduces when a later save-site reads state back."""
        # Prime disk with a wave-A-COMPLETE-like state.
        primed = RunState(task="x")
        primed.finalize()
        save_state(primed, str(tmp_path))

        # Later code path reloads state (wave_executor._load_run_state_for_wave_execution
        # pattern), mutates failed_milestones, writes back.
        reloaded = load_state(str(tmp_path))
        assert reloaded is not None
        assert reloaded.summary["success"] is True  # True round-tripped

        update_milestone_progress(reloaded, "milestone-1", "FAILED")
        assert reloaded.summary["success"] is False

        save_state(reloaded, str(tmp_path))

        data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert data["summary"]["success"] is False
        assert data["failed_milestones"] == ["milestone-1"]


# ---------------------------------------------------------------------------
# Part 4: invariant-raise backstop still fires on genuinely bad state
# ---------------------------------------------------------------------------


class TestInvariantBackstopStillFires:
    def test_explicit_false_with_clean_state_raises(self, tmp_path):
        """After B4, coercion only flips cached True → False. A caller that
        forces summary.success=False while the invariant says True is STILL
        inconsistent and must raise — the backstop protects against the
        opposite class of upstream lie (e.g. a reporting bug suppressing
        real successes)."""
        state = RunState(task="x")
        state.summary = {"success": False}
        # invariant: not interrupted AND len(failed_milestones)==0 = True
        # cached: False → still False after coercion (coercion only
        # downgrades True→False, not the other direction)
        try:
            save_state(state, str(tmp_path))
        except StateInvariantError:
            return
        raise AssertionError(
            "Expected StateInvariantError for explicit False on clean state"
        )
