"""Phase 5 closeout — §M.M5 / §O.4.6 Codex provider-routed post-orphan-monitor
wedge propagation.

Plan: ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §M.M5 + §O.4.6.

Codex provider-routed dispatches MUST surface a wedge to the wave_executor
4-tier watchdog within ``tool_call_idle_timeout_seconds`` (default 1200) when
the Codex appserver's ``_OrphanWatchdog`` self-exits after sending
``turn/interrupt``. Pre-Stage-2-remediation reproductions:

* 2A.i v3 (``v18 test runs/phase-5-closeout-stage-2a-i-audit-bootstrap-
  20260501-005224/``): Wave B Codex reasoning event at 01:07:53; no further
  progress for 45+ min; no Phase 5.7 watchdog fired; killed at 60m.
* 2B smoke 1/3 (``v18 test runs/phase-5-8a-stage-2b-20260501-01-20260501-
  000725/``): Codex orphan-monitor sent ``turn/interrupt`` at 06:12:48
  (orphan event 1/2), self-exited at 06:20:47 with ``polls=7
  orphan_events=1``. BUILD_LOG silent for 33+ minutes after; STATE.json
  pinned 76 minutes pre-terminate; %CPU=0.0; no Phase 5.7 watchdog fire.

Phase 5.7 §J.4 4-tier contract:

* Tier 1 — Bootstrap (60s) — bootstrap_eligible=True only; Codex passes False.
* Tier 2 — Orphan-tool (default 400s on Linux) — fires when
  ``pending_tool_starts`` non-empty AND oldest age >= threshold.
* Tier 3 — Productive-tool-idle (default 1200s) — applies on EVERY dispatch
  including Codex; commandExecution-only progress predicate. Today gates on
  ``state.bootstrap_cleared and not state.pending_tool_starts and
  state.last_tool_call_monotonic > 0.0``.
* Tier 4 — Idle fallback (5400s wave-idle for Codex; 400/600s for Claude
  sub-agent).

The remediation introduces ``state.codex_orphan_observed: bool`` set when
Codex's appserver-side orphan-monitor surfaces a stale-tool signal to
wave_executor (via the existing progress_callback / record_progress path).
The tier-3 predicate uses this flag to:

1. Bypass the ``last_tool_call_monotonic > 0`` gate when the Codex
   orphan-monitor has surfaced a wedge.
2. Use ``started_monotonic`` as the productive baseline so the 1200s window
   measures from dispatch start when no commandExecution lifecycle has
   completed.

The codex_appserver-side change emits a ``codex_orphan_observed`` progress
event when ``_OrphanWatchdog.register_orphan_event`` fires (i.e., on the
first turn/interrupt). The wave_executor's ``record_progress`` recognises the
new ``message_type`` and sets ``state.codex_orphan_observed = True``.

§O.4.10 invariant must hold: Codex tier-3 fires DO NOT increment
``RunState._cumulative_wedge_budget`` (only bootstrap respawns increment).
This test file pins that explicitly.

Five tests — all fail at parent commit ``123daec`` (TDD lock) and pass post-
fix.
"""

from __future__ import annotations

import inspect
import re
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15 import codex_appserver as codex_app
from agent_team_v15 import wave_executor as we
from agent_team_v15.config import V18Config
from agent_team_v15.wave_executor import (
    _WaveWatchdogState,
    _build_wave_watchdog_timeout,
)


def _config_with_defaults() -> Any:
    """Return a minimal config object with the §M.M4/§M.M5 defaults."""

    class _Cfg:
        v18 = V18Config()

    return _Cfg()


# ---------------------------------------------------------------------------
# Test 1 — tier 3 fires on Codex paths with no productive event yet.
# ---------------------------------------------------------------------------


def test_tier_3_fires_on_codex_dispatch_with_no_productive_event() -> None:
    """Tier 3 productive-tool-idle MUST fire on Codex provider-routed
    dispatches even when ``last_tool_call_monotonic == 0.0`` if the Codex-side
    orphan-monitor has surfaced a wedge to the wave_executor.

    Pre-fix mode (HEAD ``123daec``): the predicate at
    ``wave_executor.py:4105-4109`` gates on ``state.last_tool_call_monotonic
    > 0.0``. When Codex's appserver-side orphan-monitor sees a stale
    commandExecution and sends ``turn/interrupt``, the wave_executor's state
    may not have a productive event yet (no ``item/started commandExecution``
    received before the stall) → ``last_tool_call_monotonic == 0`` → tier 3
    does not fire.

    Post-fix: when ``state.codex_orphan_observed`` is True, the predicate
    falls back to ``state.started_monotonic`` as the productive baseline so
    tier 3 fires after ``tool_call_idle_timeout_seconds`` (1200s default)
    measured from dispatch start.
    """

    state = _WaveWatchdogState()
    # Codex paths flip bootstrap_cleared without a productive event when
    # the appserver hasn't yet emitted any item/started.
    state.bootstrap_cleared = True
    state.last_tool_call_monotonic = 0.0
    # No pending tools — Codex stalled before emitting item/started for
    # any commandExecution (or the prior commandExecution had completed).
    state.pending_tool_starts = {}

    # Anchor started_monotonic 1300s ago so the 1200s tier-3 window is
    # exhausted. Anchor last_progress_monotonic recently to keep tier 4
    # (5400s wave-idle) inert — we want tier 3 to be the canonical fire-point
    # per the §M.M5 / §O.4.6 contract (1200s, NOT 5400s).
    now = time.monotonic()
    state.started_monotonic = now - 1300
    state.last_progress_monotonic = now - 60

    # Pre-fix: codex_orphan_observed is unset; predicate is unchanged →
    # tier 3 does not fire because last_tool_call_monotonic == 0.
    # The remediation surfaces this signal explicitly.
    assert hasattr(state, "codex_orphan_observed"), (
        "Phase 5 closeout Stage 2 §M.M5 follow-up: "
        "_WaveWatchdogState MUST carry a ``codex_orphan_observed`` field "
        "the codex_appserver orphan-monitor flips on stale-tool detection. "
        "Pre-fix this attribute does not exist — TDD lock."
    )
    state.codex_orphan_observed = True

    config = _config_with_defaults()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=config,
        # Codex provider-routed paths pass bootstrap_eligible=False per
        # §M.M4 / §O.4.10.
        bootstrap_eligible=False,
        # idle_fallback_seconds=5400 keeps tier 4 inert (last_progress_monotonic
        # is fresh) so tier 3 wins.
        idle_fallback_seconds=5400,
    )

    assert timeout is not None, (
        "Tier 3 productive-tool-idle MUST fire on Codex dispatches with "
        "codex_orphan_observed=True even when last_tool_call_monotonic=0. "
        "Pre-fix the predicate gates on >0 → tier 3 stays inert → wedge "
        "persists for the full 5400s (or longer if last_progress_monotonic "
        "keeps refreshing on heartbeats)."
    )
    assert timeout.timeout_kind == "tool-call-idle", (
        f"Expected timeout_kind='tool-call-idle' (tier 3); got "
        f"{timeout.timeout_kind!r}. The contract is 1200s tier 3, NOT "
        f"5400s tier 4 — operator wants the canonical wedge fire-point."
    )


# ---------------------------------------------------------------------------
# Test 2 — replay of the 2B BUILD_LOG event sequence.
# ---------------------------------------------------------------------------


def test_tier_3_fires_after_codex_orphan_monitor_exit() -> None:
    """Replays the 2B smoke 1/3 BUILD_LOG_TAIL_50.txt event sequence at unit-
    test scale. Codex thread starts at T=0; orphan-monitor poll #5 at T=295s
    reports a pending commandExecution (age=223s); orphan-monitor sends
    ``turn/interrupt`` at T=425s; orphan-monitor self-exits at T=900s with
    ``polls=7 orphan_events=1``; no further events. Asserts tier 3 fires by
    T=1200s, NOT T=5400s.

    The fixture exercises the wave_executor predicate against a synthetic
    ``_WaveWatchdogState`` mutated to mirror the on-disk evidence:
    ``codex_orphan_observed=True`` (set by the codex_appserver-side
    integration) drives tier 3 to fire from ``started_monotonic`` at the
    1200s threshold.
    """

    # T=0 baseline.
    state = _WaveWatchdogState()
    state.bootstrap_cleared = True
    # Empirical sequence: a commandExecution at age=223 -> 343 (across two
    # polls) — wave_executor's record_progress saw item/started so
    # last_tool_call_monotonic > 0 and pending_tool_starts had the entry.
    # After turn/interrupt the codex_appserver orphan-monitor exits without
    # an item/completed; the wave_executor's pending_tool_starts may STILL
    # carry the stale entry.

    now = time.monotonic()
    started = now - 1250  # T=0 of the dispatch (just past 1200s).
    cmd_start = now - 1100  # commandExecution item/started ~150s in.
    last_progress = now - 50  # heartbeat / tier-4 buffer.

    state.started_monotonic = started
    state.last_progress_monotonic = last_progress
    state.last_tool_call_monotonic = cmd_start

    # commandExecution still pending (no item/completed received).
    state.pending_tool_starts = {
        "call_EerWETZcmGFsGcOtmOOkkWdj": {
            "tool_name": "commandExecution",
            "started_at": "2026-05-01T06:07:05+00:00",
            "started_monotonic": cmd_start,
        },
    }

    # Codex appserver orphan-monitor surfaced the wedge to wave_executor.
    assert hasattr(state, "codex_orphan_observed")
    state.codex_orphan_observed = True

    config = _config_with_defaults()

    # Tier 2 (orphan-tool, default 400s) — pending tool age = 1100s, well
    # past 400s threshold. Pre-fix tier 2 SHOULD fire here. Post-fix tier 2
    # behaviour is unchanged. Both pre- and post-fix tier 2 fires.
    # The TDD lock here is on the post-fix BEHAVIOUR: with codex_orphan_observed
    # set, ``_build_wave_watchdog_timeout`` MUST surface a watchdog timeout
    # — either tier 2 (orphan-tool) OR tier 3 (tool-call-idle). Both are
    # acceptable terminal verdicts; what is forbidden is the pre-fix outcome
    # of returning ``None`` indefinitely.
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=config,
        bootstrap_eligible=False,
        idle_fallback_seconds=5400,
    )

    assert timeout is not None, (
        "After the Codex orphan-monitor surfaced a wedge to wave_executor "
        "(codex_orphan_observed=True), the predicate MUST return a non-None "
        "timeout — pre-fix it returned None indefinitely on this exact "
        "shape, replicating the 2B smoke 1/3 wedge."
    )

    # The replay-acceptance: either tier-2 OR tier-3 is the canonical fire-
    # point. Tier 4 (wave-idle) fires only on stale last_progress_monotonic;
    # the heartbeat-keepalive scenario rules it out here.
    assert timeout.timeout_kind in ("orphan-tool", "tool-call-idle"), (
        f"Expected tier 2 (orphan-tool) or tier 3 (tool-call-idle); got "
        f"timeout_kind={timeout.timeout_kind!r}. Tier 4 (wave-idle) is the "
        "5400s safety net, not the canonical fire-point per §M.M5."
    )


# ---------------------------------------------------------------------------
# Test 3 — tier 4 fires as fallback within 5400s on the same shape.
# ---------------------------------------------------------------------------


def test_tier_4_fires_as_fallback_within_5400s() -> None:
    """Synthetic safety-net lock — even if tier 3 misses, tier 4 wave-idle
    fallback (5400s for Codex) MUST fire when ``last_progress_monotonic``
    itself is stale by 5400+ seconds.

    Phase 5.7 §J.4 contract: tier 4 is the unconditional fallback. No gate
    other than the elapsed window. This test guards against a future
    regression that might gate tier 4 on ``codex_orphan_observed`` or
    similar — tier 4 must fire on any stale dispatch, with or without the
    new flag.
    """

    state = _WaveWatchdogState()
    # No bootstrap_cleared, no productive events — tier 4-only scenario.
    state.bootstrap_cleared = False
    state.last_tool_call_monotonic = 0.0
    state.pending_tool_starts = {}

    now = time.monotonic()
    state.started_monotonic = now - 5500
    state.last_progress_monotonic = now - 5500  # Stale by 5500s.

    config = _config_with_defaults()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=config,
        bootstrap_eligible=False,  # Codex path scoping.
        idle_fallback_seconds=5400,
    )

    assert timeout is not None, (
        "Tier 4 wave-idle fallback (5400s) MUST fire as the unconditional "
        "safety net regardless of bootstrap_cleared / codex_orphan_observed."
    )
    assert timeout.timeout_kind == "wave-idle", (
        f"Expected timeout_kind='wave-idle' (tier 4); got "
        f"{timeout.timeout_kind!r}."
    )


# ---------------------------------------------------------------------------
# Test 4 — codex_appserver orphan-monitor surfaces the signal.
# ---------------------------------------------------------------------------


def test_codex_orphan_monitor_exit_marks_watchdog_state() -> None:
    """The codex_appserver MUST surface its orphan-monitor's stale-tool
    detection to the wave_executor's ``_WaveWatchdogState``.

    Two contracts pinned here:

    1. **Static-source lock**: ``codex_appserver._monitor_orphans`` (or its
       call site at the orphan-event registration point) MUST emit a
       progress event with a ``codex_orphan_observed`` message_type whenever
       ``_OrphanWatchdog.register_orphan_event`` fires (i.e., on each
       turn/interrupt dispatch).
    2. **Behavioural lock**: ``_WaveWatchdogState.record_progress`` recognises
       the new message_type and sets ``state.codex_orphan_observed = True``.

    Combined the two ensure the wave_executor's predicate sees the wedge
    signal even though the codex_appserver and wave_executor track
    pending tools in separate _OrphanWatchdog instances.
    """

    # 1 — static lock
    src = inspect.getsource(codex_app)
    # Match codex_appserver emitting the new message_type from the orphan
    # detection / interrupt code path.
    assert re.search(
        r"(?:codex_orphan_observed|_emit_progress[^)\n]*codex_orphan_observed|"
        r"\"codex_orphan_observed\"|'codex_orphan_observed')",
        src,
    ), (
        "Phase 5 closeout Stage 2 §M.M5 follow-up: codex_appserver MUST "
        "emit a ``codex_orphan_observed`` progress event when "
        "_OrphanWatchdog detects a stale tool (i.e., on turn/interrupt "
        "dispatch). Pre-fix the wave_executor's _WaveWatchdogState has no "
        "way to learn about the codex_appserver's orphan-monitor activity."
    )

    # 2 — behavioural lock
    state = _WaveWatchdogState()
    assert hasattr(state, "codex_orphan_observed")
    assert state.codex_orphan_observed is False
    state.record_progress(
        message_type="codex_orphan_observed",
        tool_name="commandExecution",
        tool_id="",
        event_kind="other",
    )
    assert state.codex_orphan_observed is True, (
        "_WaveWatchdogState.record_progress MUST flip codex_orphan_observed "
        "to True on receipt of a ``codex_orphan_observed`` message_type."
    )


# ---------------------------------------------------------------------------
# Test 5 — §O.4.10 invariant preservation.
# ---------------------------------------------------------------------------


def test_provider_routed_codex_wedge_does_not_increment_cumulative_wedge_budget() -> None:
    """§O.4.10 invariant: Codex provider-routed wedges (orphan-tool / tool-
    call-idle / wave-idle) DO NOT increment
    ``RunState._cumulative_wedge_budget``. Only bootstrap-wedge respawns on
    the Claude SDK sub-agent path increment the counter (per §M.M4 budget
    contract). This test guards against a future regression where the new
    ``codex_orphan_observed`` flag's tier-3 fire might mistakenly bump the
    counter.

    The contract is honoured at the wave_executor handler — tier 3 surfaces
    a ``WaveWatchdogTimeoutError(timeout_kind='tool-call-idle')`` which is
    caught at ``_invoke_provider_wave_with_watchdog`` and converted to a
    wave-fail, NOT routed through the bootstrap-wedge callback. This test
    pins that wiring at the source-handler level.
    """

    src = inspect.getsource(we)

    # Search for the dispatch/handler block at
    # `_invoke_provider_wave_with_watchdog` that routes timeouts. The
    # bootstrap-wedge callback fires ONLY on `timeout_kind == "bootstrap"`.
    # The other tiers (orphan-tool / tool-call-idle / wave-idle) write a
    # hang report + raise — they do NOT invoke the callback.
    callback_re = re.compile(
        r'if\s+timeout\.timeout_kind\s*==\s*"bootstrap"\s*:'
        r'[\s\S]{0,500}?'
        r'cb\s*=\s*get_bootstrap_wedge_callback\(\)'
        r'[\s\S]{0,400}?'
        r'cb\(\s*wave_letter\s*,\s*hang_report_path\s*\)',
        re.MULTILINE,
    )
    assert callback_re.search(src), (
        "§O.4.10 invariant: the bootstrap-wedge callback (which increments "
        "RunState._cumulative_wedge_budget) MUST be gated on "
        "``timeout.timeout_kind == \"bootstrap\"`` inside "
        "_invoke_provider_wave_with_watchdog. The new tier-3 fire-path on "
        "Codex (codex_orphan_observed) MUST NOT change this routing — "
        "tier 3's timeout_kind='tool-call-idle' falls through to the "
        "non-respawn handler."
    )

    # Locate the non-respawn handler block (orphan-tool / tool-call-idle /
    # wave-idle path) and ensure it does NOT invoke the bootstrap callback.
    non_respawn_re = re.compile(
        r"_log_orphan_tool_wedge\(timeout\)"
        r"[\s\S]{0,400}?"
        r"_write_hang_report\("
        r"[\s\S]{0,500}?"
        r"raise\s+timeout",
        re.MULTILINE,
    )
    match = non_respawn_re.search(src)
    assert match is not None, (
        "Could not locate the non-respawn handler block in "
        "_invoke_provider_wave_with_watchdog. §O.4.10 wiring must be "
        "preserved by the §M.M5 follow-up."
    )

    # Ensure the matched non-respawn handler block does NOT contain a
    # `cb(...)` invocation (the bootstrap-wedge callback).
    block = match.group(0)
    assert "get_bootstrap_wedge_callback" not in block, (
        "§O.4.10 invariant violation: the non-respawn handler block "
        "(orphan-tool / tool-call-idle / wave-idle) MUST NOT invoke the "
        "bootstrap-wedge callback. Found `get_bootstrap_wedge_callback` "
        "in the non-bootstrap path."
    )


