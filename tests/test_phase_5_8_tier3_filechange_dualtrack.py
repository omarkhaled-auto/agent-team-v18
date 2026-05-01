"""Phase 5 closeout Stage 2 §M.M5 / §O.4.6 follow-up #2 — tier-3 fileChange
dual-track gate.

Operator-found near-miss on Rerun 3 smoke 1/3
(``v18 test runs/phase-5-8a-stage-2b-rerun3-20260501-01-…``):

* Last Codex ``item/completed commandExecution``: 2026-05-01T09:32:41.694Z
* Last Codex ``item/completed fileChange``: 2026-05-01T09:33:41.925Z
* Codex natural turn end (``thread/archive``): 2026-05-01T09:52:45.803Z
* Tier-3 productive-tool-idle threshold from last commandExecution: 09:52:41.694Z

→ Tier 3 was poised to fire ~4 seconds before Codex naturally finished, even
though Codex was actively emitting ``item/completed fileChange`` events and
modifying 22 files between 13:30 and 13:33 (and continued reasoning +
agentMessage deltas through 13:52:45). False-positive averted by 30s
poll-cadence luck.

Root cause — ``_is_productive_tool_event`` (wave_executor.py:480-523)
classifies productive ONLY as Codex ``commandExecution`` lifecycle. Codex
``item/completed fileChange`` (file mutation) is treated as non-productive
even though it represents real forward progress. Tier 3's
``last_tool_call_monotonic + 1200s`` baseline therefore freezes at the last
commandExecution time, ignoring the fileChange activity.

Operator's Option 2 fix (preserving §O.4.6 hang-report semantics):

* Add ``_WaveWatchdogState.last_file_mutation_monotonic: float = 0.0``,
  refreshed by ``record_progress`` on
  ``item/completed`` + ``tool_name="fileChange"`` + ``event_kind="complete"``.
* Tier-3 predicate uses
  ``baseline = max(last_tool_call_monotonic, last_file_mutation_monotonic)``
  when either is set. fileChange is a TIER-3 GATE input, NOT a
  ``last_productive_tool_name`` column input — the §O.4.6 hang-report
  shape (``last_productive_tool_name="commandExecution"``,
  ``tool_call_event_count`` only on commandExecution lifecycle) is
  preserved.

Six tests:

1. ``test_filechange_completed_refreshes_last_file_mutation_monotonic`` —
   record_progress sets ``last_file_mutation_monotonic`` on a real
   ``item/completed fileChange`` event; the productive-event fields stay
   untouched.
2. ``test_filechange_does_not_refresh_last_productive_tool_name`` —
   pin §O.4.6 hang-report semantics: fileChange events do NOT bump
   ``last_productive_tool_name`` or ``tool_call_event_count``.
3. ``test_tier_3_does_not_fire_when_recent_filechange_within_window`` —
   the empirical near-miss: last commandExecution >1200s ago, last
   fileChange recent → tier 3 stays inert.
4. ``test_tier_3_fires_when_both_cmdexec_and_filechange_quiet_past_window``
   — both signals quiet for >1200s → tier 3 fires (the legitimate
   wedge case).
5. ``test_tier_3_uses_max_of_cmdexec_and_filechange_baselines`` —
   verifies the baseline is the LATEST of the two timestamps, not
   either one alone.
6. ``test_opaque_team_mode_still_skips_tier_3_with_no_filechange`` —
   ``_mark_bootstrap_cleared_on_watchdog_state`` opaque-team-mode
   exemption preserved: bootstrap_cleared=True without any productive
   or fileChange event → tier 3 stays inert (last_tool_call=0,
   last_file_mutation=0, codex_orphan_observed=False).

Plus 1 additional regression-check that the existing §O.4.6 closure
behaviour (``codex_orphan_observed`` baseline fallback to
``started_monotonic``) remains unaffected:

7. ``test_tier_3_codex_orphan_observed_baseline_falls_back_to_started_monotonic``
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from agent_team_v15 import wave_executor as we
from agent_team_v15.config import V18Config
from agent_team_v15.wave_executor import (
    _WaveWatchdogState,
    _build_wave_watchdog_timeout,
)


def _config_with_defaults() -> Any:
    class _Cfg:
        v18 = V18Config()

    return _Cfg()


# ---------------------------------------------------------------------------
# 1 — record_progress refreshes last_file_mutation_monotonic on
#     item/completed fileChange (Codex form).
# ---------------------------------------------------------------------------


def test_filechange_completed_refreshes_last_file_mutation_monotonic() -> None:
    """``record_progress`` MUST set ``state.last_file_mutation_monotonic`` to
    ``time.monotonic()`` when receiving a real Codex
    ``item/completed fileChange`` event.

    The pre-fix shape — last_file_mutation_monotonic stays 0.0 on these
    events — is the empirical defect that drove the Rerun 3 smoke 1/3
    near-miss.
    """

    state = _WaveWatchdogState()
    assert state.last_file_mutation_monotonic == 0.0

    # Real Codex item/completed fileChange shape (mirrored from
    # protocol-capture log line: thread.../turn.../fileChange item).
    state.record_progress(
        message_type="item/completed",
        tool_name="fileChange",
        tool_id="call_TestFileChange_1",
        event_kind="complete",
    )

    assert state.last_file_mutation_monotonic > 0.0, (
        "Phase 5 closeout Stage 2 §O.4.6 follow-up #2: fileChange complete "
        "event MUST refresh last_file_mutation_monotonic. Pre-fix value "
        "would be 0.0."
    )


# ---------------------------------------------------------------------------
# 2 — fileChange does NOT refresh last_productive_tool_name (preserves
#     §O.4.6 hang-report column).
# ---------------------------------------------------------------------------


def test_filechange_does_not_refresh_last_productive_tool_name() -> None:
    """The §O.4.6 hang-report column shape (operator-locked):

    * ``last_productive_tool_name == "commandExecution"`` on tier-3 fires
    * ``tool_call_event_count`` increments ONLY on commandExecution
      lifecycle.

    fileChange is a tier-3 GATE input, NOT a column input. This test
    pins that fileChange events do NOT corrupt the column shape — the
    closure evidence at run-dir
    ``phase-5-closeout-stage-2a-iv-rerun-o46-b1-20260501-103942/`` stays
    valid through this fix.
    """

    state = _WaveWatchdogState()

    # Receive a fileChange event ONLY (no prior commandExecution).
    state.record_progress(
        message_type="item/completed",
        tool_name="fileChange",
        tool_id="call_TestFileChange_2",
        event_kind="complete",
    )

    assert state.last_productive_tool_name == "", (
        "fileChange MUST NOT set last_productive_tool_name; only "
        "commandExecution lifecycle does. Got: "
        f"{state.last_productive_tool_name!r}."
    )
    assert state.tool_call_event_count == 0, (
        "fileChange MUST NOT increment tool_call_event_count; only "
        "commandExecution lifecycle does. Got: "
        f"{state.tool_call_event_count}."
    )
    # last_tool_call_monotonic should ALSO be untouched by fileChange.
    assert state.last_tool_call_monotonic == 0.0, (
        "fileChange MUST NOT refresh last_tool_call_monotonic; only "
        "commandExecution lifecycle does. Got: "
        f"{state.last_tool_call_monotonic}."
    )
    # bootstrap_cleared should NOT flip on fileChange alone (only
    # commandExecution lifecycle clears bootstrap).
    assert state.bootstrap_cleared is False, (
        "fileChange MUST NOT flip bootstrap_cleared; only commandExecution "
        "lifecycle does (the existing _is_productive_tool_event path)."
    )


# ---------------------------------------------------------------------------
# 3 — tier 3 STAYS INERT when last commandExecution is >1200s ago but
#     fileChange is recent (the near-miss scenario).
# ---------------------------------------------------------------------------


def test_tier_3_does_not_fire_when_recent_filechange_within_window() -> None:
    """Locks the empirical near-miss fix: long Codex turn that ran early
    commandExecutions then pivoted to >1200s of fileChange-only events
    MUST NOT trigger tier-3 productive-tool-idle.

    Pre-fix mode (Rerun 3 smoke 1/3 timing):
    * last_tool_call_monotonic = T-1300s (commandExecution >1200s ago)
    * last_file_mutation_monotonic = T-100s (fileChange recent)
    * pre-fix predicate: baseline = last_tool_call_monotonic; elapsed =
      1300s >= 1200s → tier 3 fires (FALSE POSITIVE — Codex was making
      real fileChange progress).

    Post-fix:
    * baseline = max(last_tool_call_monotonic, last_file_mutation_monotonic)
      = T-100s; elapsed = 100s < 1200s → tier 3 stays inert.
    """

    state = _WaveWatchdogState()
    state.bootstrap_cleared = True
    state.pending_tool_starts = {}

    now = time.monotonic()
    state.started_monotonic = now - 1400
    state.last_progress_monotonic = now - 50
    # Last commandExecution was 1300s ago — past the 1200s tier-3 threshold.
    state.last_tool_call_monotonic = now - 1300
    state.last_productive_tool_name = "commandExecution"
    state.tool_call_event_count = 5
    # fileChange was 100s ago — well within the 1200s window. Codex IS
    # actively progressing.
    state.last_file_mutation_monotonic = now - 100

    config = _config_with_defaults()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=config,
        bootstrap_eligible=False,  # Codex provider-routed.
        idle_fallback_seconds=5400,
    )

    assert timeout is None or timeout.timeout_kind != "tool-call-idle", (
        "Phase 5 closeout Stage 2 §O.4.6 follow-up #2 contract violation: "
        "tier 3 MUST NOT fire when last fileChange is within the 1200s "
        "window, even if last commandExecution is older than 1200s. "
        f"Got: {timeout!r}."
    )


# ---------------------------------------------------------------------------
# 4 — tier 3 FIRES when both signals quiet for >1200s (legitimate wedge).
# ---------------------------------------------------------------------------


def test_tier_3_fires_when_both_cmdexec_and_filechange_quiet_past_window() -> None:
    """Locks the legitimate-wedge case: both commandExecution AND
    fileChange channels have been quiet for >1200s → Codex truly hung.
    Tier 3 fires.
    """

    state = _WaveWatchdogState()
    state.bootstrap_cleared = True
    state.pending_tool_starts = {}

    now = time.monotonic()
    state.started_monotonic = now - 1400
    state.last_progress_monotonic = now - 50  # heartbeat keeps tier-4 inert
    state.last_tool_call_monotonic = now - 1300
    state.last_productive_tool_name = "commandExecution"
    state.tool_call_event_count = 3
    # Both signals quiet for >1200s.
    state.last_file_mutation_monotonic = now - 1300

    config = _config_with_defaults()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=config,
        bootstrap_eligible=False,
        idle_fallback_seconds=5400,
    )

    assert timeout is not None, (
        "Tier 3 MUST fire when both commandExecution AND fileChange "
        "have been quiet for >=1200s — the legitimate-wedge case."
    )
    assert timeout.timeout_kind == "tool-call-idle", (
        f"Expected timeout_kind='tool-call-idle' (tier 3); got "
        f"{timeout.timeout_kind!r}."
    )


# ---------------------------------------------------------------------------
# 5 — baseline is max(last_tool_call_monotonic, last_file_mutation_monotonic).
# ---------------------------------------------------------------------------


def test_tier_3_uses_max_of_cmdexec_and_filechange_baselines() -> None:
    """Locks the dual-track baseline shape: the predicate measures from
    the LATEST of the two channels, so the most-recent forward-progress
    signal always extends the tier-3 window.

    Three cases verified:
    * cmdexec recent (50s), fileChange older (1300s) → predicate sees
      50s elapsed → no fire.
    * cmdexec older (1300s), fileChange recent (50s) → predicate sees
      50s elapsed → no fire (the empirical near-miss case).
    * Both fresh (100s, 200s) → predicate sees 100s elapsed → no fire.
    """

    config = _config_with_defaults()

    def _build(cmdexec_age_s: float, filechange_age_s: float) -> Any:
        state = _WaveWatchdogState()
        state.bootstrap_cleared = True
        state.pending_tool_starts = {}
        now = time.monotonic()
        state.started_monotonic = now - 1400
        state.last_progress_monotonic = now - 30
        state.last_tool_call_monotonic = now - cmdexec_age_s
        state.last_productive_tool_name = "commandExecution"
        state.tool_call_event_count = 2
        state.last_file_mutation_monotonic = now - filechange_age_s
        return state

    cases = [
        (50.0, 1300.0),    # cmdexec recent
        (1300.0, 50.0),    # fileChange recent (the near-miss case)
        (100.0, 200.0),    # both fresh
    ]

    for cmdexec_age, filechange_age in cases:
        state = _build(cmdexec_age, filechange_age)
        timeout = _build_wave_watchdog_timeout(
            wave_letter="B",
            state=state,
            config=config,
            bootstrap_eligible=False,
            idle_fallback_seconds=5400,
        )
        assert timeout is None or timeout.timeout_kind != "tool-call-idle", (
            f"Tier 3 fired on (cmdexec_age={cmdexec_age}, "
            f"filechange_age={filechange_age}); the LATEST signal age is "
            f"min({cmdexec_age}, {filechange_age}) = {min(cmdexec_age, filechange_age)}s, "
            f"which is below the 1200s threshold. Predicate must use "
            f"max(last_tool_call_monotonic, last_file_mutation_monotonic) "
            f"as the baseline. Got: {timeout!r}."
        )


# ---------------------------------------------------------------------------
# 6 — opaque-team-mode tier-3 exemption preserved.
# ---------------------------------------------------------------------------


def test_opaque_team_mode_still_skips_tier_3_with_no_filechange() -> None:
    """The opaque-team-mode exemption (claude --print --output-format json
    subprocesses) is preserved by the dual-track fix.

    Opaque paths flip ``bootstrap_cleared=True`` via
    ``cli._mark_bootstrap_cleared_on_watchdog_state`` but never receive
    productive tool events (no Codex commandExecution, no Claude
    tool_use, no Codex fileChange). The pre-fix predicate gated on
    ``last_tool_call_monotonic > 0.0`` to skip tier 3 in this case.
    The post-fix predicate gates on
    ``last_tool_call_monotonic > 0.0 OR last_file_mutation_monotonic > 0.0
    OR codex_orphan_observed`` — opaque paths satisfy NONE of these,
    so tier 3 STILL stays inert.
    """

    state = _WaveWatchdogState()
    state.bootstrap_cleared = True  # opaque exemption flipped this
    state.pending_tool_starts = {}
    state.last_tool_call_monotonic = 0.0  # no productive event
    state.last_file_mutation_monotonic = 0.0  # no fileChange
    state.codex_orphan_observed = False  # not a Codex path

    now = time.monotonic()
    state.started_monotonic = now - 1400  # well past 1200s threshold
    state.last_progress_monotonic = now - 50

    config = _config_with_defaults()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=config,
        bootstrap_eligible=False,
        idle_fallback_seconds=5400,
    )

    assert timeout is None or timeout.timeout_kind != "tool-call-idle", (
        "Opaque-team-mode exemption regressed: tier 3 fired when "
        "last_tool_call_monotonic=0, last_file_mutation_monotonic=0, "
        "codex_orphan_observed=False. The predicate's productive-baseline "
        "gate must keep tier 3 inert in this case."
    )


# ---------------------------------------------------------------------------
# 7 — codex_orphan_observed baseline still falls back to started_monotonic.
# ---------------------------------------------------------------------------


def test_tier_3_codex_orphan_observed_baseline_falls_back_to_started_monotonic() -> None:
    """Regression check on the §M.M5 follow-up #1 contract (closed at
    ``fcb0e97`` via Rerun 2 B1):

    When ``codex_orphan_observed=True`` AND ``last_tool_call_monotonic=0``
    AND ``last_file_mutation_monotonic=0``, the predicate baseline MUST
    fall back to ``state.started_monotonic`` so tier 3 fires within
    1200s of dispatch start. The dual-track fix MUST NOT regress this
    fallback.
    """

    state = _WaveWatchdogState()
    state.bootstrap_cleared = True
    state.pending_tool_starts = {}
    state.last_tool_call_monotonic = 0.0
    state.last_file_mutation_monotonic = 0.0
    state.codex_orphan_observed = True

    now = time.monotonic()
    state.started_monotonic = now - 1300  # 100s past 1200s threshold
    state.last_progress_monotonic = now - 50

    config = _config_with_defaults()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=config,
        bootstrap_eligible=False,
        idle_fallback_seconds=5400,
    )

    assert timeout is not None, (
        "§M.M5 follow-up #1 regression: tier 3 MUST fire when "
        "codex_orphan_observed=True and started_monotonic > 1200s ago, "
        "even with last_tool_call_monotonic=0 AND "
        "last_file_mutation_monotonic=0."
    )
    assert timeout.timeout_kind == "tool-call-idle", (
        f"Expected timeout_kind='tool-call-idle'; got {timeout.timeout_kind!r}."
    )
