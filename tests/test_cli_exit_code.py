"""Regression tests for CLI exit-code derived from RunState.summary.success.

Guards against the build-l root cause: a smoke run that logged
``summary.success=True`` alongside ``failed_milestones=['milestone-1']``
while the orchestrator process exited 0 (success).

Two layers under test:
  * ``state.RunState.finalize()`` must set ``summary['success']`` to the
    conjunction of ``not interrupted`` and ``len(failed_milestones) == 0``.
  * ``cli._exit_code_for_state()`` must map ``summary.success`` to a
    non-zero process exit code when the rollup says the run failed.
"""

from __future__ import annotations

from agent_team_v15.cli import _exit_code_for_state
from agent_team_v15.state import RunState


# --- finalize() invariants --------------------------------------------------


def test_finalize_sets_success_false_when_failed_milestones():
    state = RunState()
    state.failed_milestones = ["milestone-1"]
    state.interrupted = False

    state.finalize()

    assert state.summary["success"] is False


def test_finalize_sets_success_true_when_clean():
    state = RunState()

    state.finalize()

    assert state.summary["success"] is True


def test_finalize_sets_success_false_when_interrupted():
    state = RunState()
    state.interrupted = True

    state.finalize()

    assert state.summary["success"] is False


# --- _exit_code_for_state() helper -----------------------------------------


def test_exit_code_zero_when_state_is_none():
    assert _exit_code_for_state(None) == 0


def test_exit_code_zero_when_summary_missing_success_key():
    # Back-compat: legacy code paths that never populate summary must not
    # newly fail. The helper defaults success=True when unset.
    state = RunState()
    assert state.summary == {}
    assert _exit_code_for_state(state) == 0


def test_exit_code_one_when_finalize_derives_failure():
    state = RunState()
    state.failed_milestones = ["milestone-1"]
    state.finalize()

    assert _exit_code_for_state(state) == 1


def test_exit_code_zero_when_finalize_derives_success():
    state = RunState()
    state.finalize()

    assert _exit_code_for_state(state) == 0


def test_exit_code_one_when_summary_explicit_false():
    # Even without calling finalize(), an explicit summary.success=False
    # from any upstream writer must propagate to exit code 1.
    state = RunState()
    state.summary = {"success": False}

    assert _exit_code_for_state(state) == 1


def test_exit_code_zero_when_summary_non_dict():
    # Defensive: if a caller replaced summary with an unexpected type, fall
    # back to the back-compat success-default rather than asserting.
    state = RunState()
    state.summary = "not-a-dict"  # type: ignore[assignment]

    assert _exit_code_for_state(state) == 0


# --- belt-and-suspenders: consult RunState attrs directly -------------------
#
# Guards the gap that PR #48 flagged and issue #67 tracks: if ``finalize()``
# AND the subsequent ``save_state()`` both throw, ``summary`` is stale while
# ``failed_milestones`` / ``interrupted`` on the in-memory RunState are still
# authoritative. ``_exit_code_for_state`` must short-circuit on those attrs
# before falling through to ``summary.success``.


def test_exit_code_one_when_failed_milestones_nonempty_despite_summary_true():
    # Stale summary from an earlier finalize() at wave-A COMPLETE, then a
    # later gate appended to failed_milestones without re-running finalize.
    state = RunState()
    state.failed_milestones = ["milestone-1"]
    state.summary = {"success": True}

    assert _exit_code_for_state(state) == 1


def test_exit_code_one_when_interrupted_despite_summary_true():
    state = RunState()
    state.interrupted = True
    state.summary = {"success": True}

    assert _exit_code_for_state(state) == 1


def test_exit_code_one_when_failed_milestones_nonempty_and_summary_missing():
    # The exact build-l scenario: finalize() threw before populating summary,
    # save_state() also threw, but failed_milestones on the RunState attr is
    # authoritative. B4's save-time coercion never ran. Belt-and-suspenders.
    state = RunState()
    state.failed_milestones = ["milestone-1"]
    assert state.summary == {}

    assert _exit_code_for_state(state) == 1


def test_exit_code_one_when_failed_milestones_nonempty_and_summary_non_dict():
    state = RunState()
    state.failed_milestones = ["milestone-1"]
    state.summary = "bogus"  # type: ignore[assignment]

    assert _exit_code_for_state(state) == 1


def test_exit_code_zero_when_attrs_missing():
    # Defensive: a bare object without RunState attrs (legacy / mock state
    # shapes) must not crash — fall through to the summary fallback, which
    # itself defaults to 0 when summary is absent. Matches the None-state
    # back-compat default.
    class _Bare:
        pass

    assert _exit_code_for_state(_Bare()) == 0
