"""Phase 5 closeout — §O.4.8 cumulative-cap STATE.json final-state persistence.

Plan: ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §M.M4 + §O.4.8.

Locks the cumulative-wedge cap halt path so the final ``STATE.json`` carries
the canonical halt fields:

* ``milestone_progress[<id>].status == "FAILED"``
* ``milestone_progress[<id>].failure_reason == "sdk_pipe_environment_unstable"``
* ``_cumulative_wedge_budget >= caught_exc.count``
* ``EXIT_CODE.txt`` written with ``2``
* ``BUILD_LOG.txt`` carries the ``[BOOTSTRAP-WATCHDOG] Cumulative wedge cap``
  cap-reached line.

Pre-Stage-2-remediation reproduction (run-dir
``v18 test runs/phase-5-closeout-stage-2a-ii-cumcap-halt-audit-20260501-031850/``):
STATE.json ended with ``failure_reason="wave_fail_recovery_attempt"`` (Phase 4.5
transient — never overwritten) and ``_cumulative_wedge_budget=0`` (callback's
``state`` snapshot diverged from the global ``_current_state`` after
``_save_wave_state`` reassigned the global; callback writes never reached the
on-disk STATE.json). The forensics swallow at ``cli.py:5821`` (``except
Exception as forensics_exc``) caught the cap halt as a regular exception and
let the milestone loop ``continue`` past wedges 1–2; the third wedge inside
the post-loop integration audit reached the top-level handler at
``cli.py:15331`` but the gate ``if _phase57_ms_id`` rejected the resolver call
because ``state.current_milestone`` was ``""`` (Phase 4.5's preemptive FAILED
write at ``cli.py:9077`` cleared it). Even when the resolver path was reached
the call did not pass ``agent_team_dir``, so ``save_state`` never fired.

The post-fix contract:

* ``cli.py:5821`` — ``except BuildEnvironmentUnstableError: raise`` BEFORE the
  broad ``except Exception``; tier-2 orphan-tool wedges still get the
  ``(non-blocking)`` log + ``continue``.
* ``cli._handle_cumulative_wedge_cap_halt`` — extracted helper that:
  - resolves the target milestone-id from ``current_milestone`` first, then
    falls back to the most-recent ``failed_milestones[-1]`` entry;
  - syncs ``_current_state._cumulative_wedge_budget`` to ``caught_exc.count``
    when in-memory state lags the cap;
  - calls ``_finalize_milestone_with_quality_contract`` with
    ``override_status="FAILED"`` + ``override_failure_reason=
    "sdk_pipe_environment_unstable"`` + ``agent_team_dir=<run-dir>/.agent-team``
    so ``save_state`` flushes the canonical halt fields + budget to disk.
* ``cli.py:15331`` — top-level ``BaseException`` handler delegates to the
  helper and ``sys.exit(2)``.

Six tests:

1. ``test_cap_halt_routes_through_phase_5_5_resolver_with_canonical_reason``
2. ``test_cap_halt_preserves_cumulative_wedge_budget_to_n``
3. ``test_cap_halt_overrides_wave_fail_recovery_attempt_state``
4. ``test_audit_cycle_non_blocking_handler_re_raises_cap_halt`` (static-source)
5. ``test_exit_code_is_2_after_cap_halt`` (static-source on the helper-call
    epilogue)
6. ``test_build_log_carries_cap_reached_line_after_halt`` (static-source on
    the ``print_error`` template at ``cli.py:15340-15346``)

All six fail at parent commit ``123daec`` (TDD lock) and pass post-fix.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_team_v15 import cli as cli_mod
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.state import RunState, load_state, save_state
from agent_team_v15.wave_executor import BuildEnvironmentUnstableError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_post_phase_4_5_state(
    *,
    failed_milestone_ids: list[str],
    inflight_failure_reason: str = "wave_fail_recovery_attempt",
    cumulative_wedge_budget: int = 0,
) -> RunState:
    """Mimic the on-disk shape after Phase 4.5 lift fired.

    Phase 4.5 lift at ``cli.py:9075-9080`` calls
    ``update_milestone_progress(state, mid, "FAILED",
    failure_reason="wave_fail_recovery_attempt")`` — which clears
    ``state.current_milestone`` (per ``state.py:501-502``) and appends the
    milestone to ``failed_milestones``. The post-Phase-4.5 state shape is the
    pre-cap-halt baseline this remediation must finalize correctly.
    """

    state = RunState()
    state.current_milestone = ""  # Cleared by update_milestone_progress on FAILED.
    state.failed_milestones = list(failed_milestone_ids)
    for ms_id in failed_milestone_ids:
        state.milestone_progress[ms_id] = {
            "status": "FAILED",
            "failure_reason": inflight_failure_reason,
        }
    state._cumulative_wedge_budget = int(cumulative_wedge_budget)
    return state


@pytest.fixture
def _agent_team_dir(tmp_path: Path) -> Path:
    """Return a per-test ``<run-dir>/.agent-team/`` directory."""

    out = tmp_path / ".agent-team"
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture
def _restore_global_current_state():
    """Restore the cli module's ``_current_state`` global after each test."""

    saved = getattr(cli_mod, "_current_state", None)
    yield
    cli_mod._current_state = saved


# ---------------------------------------------------------------------------
# Behavioural tests (1, 2, 3) — the cap-halt finalization helper
# ---------------------------------------------------------------------------


def test_cap_halt_routes_through_phase_5_5_resolver_with_canonical_reason(
    tmp_path: Path,
    _agent_team_dir: Path,
    _restore_global_current_state: None,
) -> None:
    """STATE.json post-cap-halt MUST carry
    ``failure_reason="sdk_pipe_environment_unstable"`` even when
    ``state.current_milestone`` is empty.

    Pre-fix mode (HEAD ``123daec``): the cap-halt handler at
    ``cli.py:15351-15353`` reads ``state.current_milestone``; Phase 4.5's
    preemptive FAILED write cleared it, so ``_phase57_ms_id == ""`` and the
    gate ``if _phase57_ms_id`` skips the resolver call entirely. STATE.json
    retains ``failure_reason="wave_fail_recovery_attempt"``.

    Post-fix: a ``cli._handle_cumulative_wedge_cap_halt`` helper falls back to
    ``state.failed_milestones[-1]`` when ``current_milestone`` is empty, then
    routes through the Phase 5.5 single-resolver with
    ``override_status="FAILED"`` + ``override_failure_reason=
    "sdk_pipe_environment_unstable"`` + ``agent_team_dir=<run-dir>/.agent-team``
    so ``save_state`` persists the canonical reason to disk.
    """

    state = _make_post_phase_4_5_state(failed_milestone_ids=["milestone-1"])
    cli_mod._current_state = state
    save_state(state, directory=str(_agent_team_dir))

    config = AgentTeamConfig()
    exc = BuildEnvironmentUnstableError(count=3, cap=2)

    handler = getattr(cli_mod, "_handle_cumulative_wedge_cap_halt", None)
    assert handler is not None, (
        "Post-fix the cap-halt finalization helper MUST live on cli.py "
        "(extracted from the inline handler at cli.py:15331-15371). "
        "Pre-fix this attribute does not exist — TDD lock."
    )

    handler(caught_exc=exc, cwd=str(tmp_path), config=config)

    final = load_state(str(_agent_team_dir))
    assert final is not None
    entry = final.milestone_progress.get("milestone-1")
    assert isinstance(entry, dict), (
        "milestone-1 MUST exist in milestone_progress post-helper."
    )
    assert entry.get("status") == "FAILED", (
        f"milestone-1 status: expected FAILED, got {entry.get('status')!r}"
    )
    assert entry.get("failure_reason") == "sdk_pipe_environment_unstable", (
        "Phase 5.7 §M.M4 contract violation: milestone-1 failure_reason MUST "
        f"be 'sdk_pipe_environment_unstable' post-cap-halt; got "
        f"{entry.get('failure_reason')!r} (this is the precise pre-fix "
        f"defect — Phase 4.5 transient state never gets overwritten)."
    )


def test_cap_halt_preserves_cumulative_wedge_budget_to_n(
    tmp_path: Path,
    _agent_team_dir: Path,
    _restore_global_current_state: None,
) -> None:
    """STATE.json post-cap-halt MUST carry
    ``_cumulative_wedge_budget >= caught_exc.count`` so smoke reviewers can
    verify the cap was reached.

    Pre-fix mode (HEAD ``123daec``): the bootstrap-wedge callback's ``state``
    snapshot from ``cli.py:3860-3866`` diverges from the live
    ``_current_state`` global after ``_save_wave_state`` reassigns the global
    at ``cli.py:2052``. Callback writes go to the orphan snapshot and never
    reach the on-disk STATE.json. Empirically the 2A.ii reproduction wrote
    ``_cumulative_wedge_budget=0`` even though the cap halt fired at count=3.

    Post-fix: the cap-halt helper syncs the global state's budget to
    ``caught_exc.count`` BEFORE the resolver call so save_state flushes the
    cap count. Callback divergence is benign — the helper restores
    correctness on the way out.
    """

    state = _make_post_phase_4_5_state(
        failed_milestone_ids=["milestone-1"],
        cumulative_wedge_budget=0,  # Pre-cap-halt state: callback didn't land.
    )
    cli_mod._current_state = state
    save_state(state, directory=str(_agent_team_dir))

    config = AgentTeamConfig()
    exc = BuildEnvironmentUnstableError(count=3, cap=2)

    handler = getattr(cli_mod, "_handle_cumulative_wedge_cap_halt", None)
    assert handler is not None
    handler(caught_exc=exc, cwd=str(tmp_path), config=config)

    final = load_state(str(_agent_team_dir))
    assert final is not None
    assert int(final._cumulative_wedge_budget) >= 3, (
        "Phase 5.7 §M.M4 contract violation: STATE.json "
        "_cumulative_wedge_budget MUST be >= caught_exc.count (3) post-cap-"
        f"halt; got {final._cumulative_wedge_budget!r}. Pre-fix this is 0 "
        "because the callback's snapshot diverged from _current_state."
    )


def test_cap_halt_overrides_wave_fail_recovery_attempt_state(
    tmp_path: Path,
    _agent_team_dir: Path,
    _restore_global_current_state: None,
) -> None:
    """Cap halt's canonical ``sdk_pipe_environment_unstable`` MUST take
    precedence over Phase 4.5's transient ``wave_fail_recovery_attempt``.

    The Phase 5.5 single-resolver's failure_reason precedence
    (``quality_contract.py:598-607``) accepts ``override_failure_reason``
    verbatim on the override path — so the helper SUPPLYING the canonical
    reason is sufficient. This test guards against a future regression where
    the helper might pass ``failure_reason=`` (resolver-default) instead of
    ``override_failure_reason=`` (caller verbatim) — only the latter wins
    against the in-flight ``wave_fail_recovery_attempt``.
    """

    state = _make_post_phase_4_5_state(
        failed_milestone_ids=["milestone-1"],
        inflight_failure_reason="wave_fail_recovery_attempt",
    )
    cli_mod._current_state = state
    save_state(state, directory=str(_agent_team_dir))

    pre = state.milestone_progress["milestone-1"]
    assert pre.get("failure_reason") == "wave_fail_recovery_attempt", (
        "Pre-state setup: in-flight reason must be wave_fail_recovery_attempt."
    )

    config = AgentTeamConfig()
    exc = BuildEnvironmentUnstableError(count=2, cap=2)

    handler = getattr(cli_mod, "_handle_cumulative_wedge_cap_halt", None)
    assert handler is not None
    handler(caught_exc=exc, cwd=str(tmp_path), config=config)

    final = load_state(str(_agent_team_dir))
    assert final is not None
    entry = final.milestone_progress.get("milestone-1")
    assert isinstance(entry, dict)
    assert entry.get("failure_reason") == "sdk_pipe_environment_unstable", (
        "Cap halt MUST overwrite Phase 4.5's transient "
        "wave_fail_recovery_attempt with the canonical reason. Got "
        f"{entry.get('failure_reason')!r}."
    )


# ---------------------------------------------------------------------------
# Static-source tests (4, 5, 6) — the source contract locks
# ---------------------------------------------------------------------------


def test_audit_cycle_non_blocking_handler_re_raises_cap_halt() -> None:
    """Static-source lock — the forensics-swallow handler at
    ``cli.py:5821`` (``except Exception as forensics_exc:`` wrapping the
    ``_run_failed_milestone_audit_if_enabled`` dispatch) MUST early-re-raise
    ``BuildEnvironmentUnstableError`` BEFORE the broad-Exception block. Else
    the cap halt is logged ``(non-blocking)`` and the milestone loop
    ``continue``s past it — empirically observed in the 2A.ii reproduction
    where wedges 1–2 (cap=2) hit the swallow and only wedge 3 (post-loop
    integration audit) reached the top-level halt path.

    Tier-2 orphan-tool wedges in the audit-fix dispatch DO need the
    ``(non-blocking)`` semantics so a single transient hiccup doesn't kill
    the run. So the fix excludes BuildEnvironmentUnstableError specifically;
    everything else still falls into the broad-Exception logger.
    """

    src = inspect.getsource(cli_mod)

    # Look for the Phase 5.4 forensics handler shape: a dispatch of
    # ``_run_failed_milestone_audit_if_enabled`` followed by an except
    # block with ``BuildEnvironmentUnstableError: ... raise`` BEFORE the
    # broad ``except Exception as forensics_exc:``. Permissive separators
    # because the call is multi-line + the early-re-raise body carries
    # documentation comments.
    forensics_re = re.compile(
        r"_run_failed_milestone_audit_if_enabled\([\s\S]*?\)"
        r"[\s\S]*?"
        r"except\s+BuildEnvironmentUnstableError\s*:"
        r"[\s\S]*?\braise\b"
        r"[\s\S]*?"
        r"except\s+Exception\s+as\s+forensics_exc\s*:",
    )
    forensics_match = forensics_re.search(src)
    assert forensics_match is not None, (
        "Phase 5 closeout Stage 2 §O.4.8 contract: cli.py's failed-"
        "milestone forensics handler MUST early-re-raise "
        "BuildEnvironmentUnstableError before the broad ``except "
        "Exception as forensics_exc`` block. Pre-fix the cap halt is "
        "swallowed and logged ``(non-blocking)`` while the milestone loop "
        "``continue``s — this is the precise empirical regression. Search "
        "for the missing early-re-raise around cli.py:5821."
    )

    # The matched window must NOT extend past more than one
    # ``except Exception as forensics_exc:`` site. If the regex's lazy
    # ``[\s\S]*?`` jumped over an unrelated handler block to reach the
    # forensics handler, the byte-distance check guards against that.
    matched = forensics_match.group(0)
    assert matched.count("except BuildEnvironmentUnstableError") == 1, (
        "The matched forensics-handler window must contain exactly one "
        "BuildEnvironmentUnstableError early-re-raise — the dispatch's "
        "scoped guardrail. Found {0} matches.".format(
            matched.count("except BuildEnvironmentUnstableError"),
        )
    )


def test_exit_code_is_2_after_cap_halt() -> None:
    """Static-source lock — the top-level ``BaseException`` handler at
    ``cli.py:15331`` MUST end with ``sys.exit(2)`` after the helper call so
    EXIT_CODE.txt carries the canonical environmental-error exit code.

    This stays a static lock (rather than a behavioural drive) because
    ``cli_main``'s exit path is wrapped in a launcher script — driving it
    end-to-end requires harness orchestration that is out of scope for the
    focused-test sweep.
    """

    src = inspect.getsource(cli_mod)
    # The handler must reach sys.exit(2) on the BuildEnvironmentUnstableError
    # branch. Match against a window that requires the sequence:
    #   isinstance(_phase57_caught_exc, BuildEnvironmentUnstableError) ...
    #   sys.exit(2)
    # before the trailing ``raise`` (non-cap-halt fall-through).
    halt_re = re.compile(
        r"isinstance\(\s*_phase57_caught_exc\s*,\s*BuildEnvironmentUnstableError\s*\)"
        r"[\s\S]{0,2000}?sys\.exit\(\s*2\s*\)",
        re.MULTILINE,
    )
    assert halt_re.search(src), (
        "Phase 5.7 §M.M4 contract: the top-level BuildEnvironmentUnstableError "
        "branch MUST sys.exit(2) so EXIT_CODE.txt carries 2. The exit must "
        "fire AFTER the cap-halt finalization helper completes (or its "
        "exception is caught + logged). Search for the missing sys.exit(2) "
        "around cli.py:15371."
    )


def test_build_log_carries_cap_reached_line_after_halt() -> None:
    """Static-source lock — the ``[BOOTSTRAP-WATCHDOG] Cumulative wedge cap``
    line MUST be emitted via ``print_error`` (or equivalent) inside the
    top-level handler at ``cli.py:15340-15346`` so BUILD_LOG.txt carries the
    operator-visible halt message.

    This also pins the message format: ``({cap}) reached (count={count})`` so
    smoke reviewers can grep against a stable shape.
    """

    src = inspect.getsource(cli_mod)
    # The print_error template spans multiple f-string fragments because
    # the source uses implicit-concatenation across lines. Each fragment
    # is a separate string literal in the AST. Lock the literal substrings
    # in order with permissive separators between them.
    line_re = re.compile(
        r"\[BOOTSTRAP-WATCHDOG\]\s+Cumulative\s+wedge\s+cap\s*"
        r"[\s\S]*?\.cap[\s\S]*?\)\s*reached"
        r"[\s\S]*?count=[\s\S]*?\.count",
    )
    assert line_re.search(src), (
        "Phase 5.7 §M.M4 contract: cli.py's top-level cap-halt branch MUST "
        "emit the ``[BOOTSTRAP-WATCHDOG] Cumulative wedge cap (CAP) reached "
        "(count=N)`` line via print_error so BUILD_LOG.txt carries the "
        "halt fingerprint. Search around cli.py:15340-15346 for the missing "
        "or drifted message format."
    )
