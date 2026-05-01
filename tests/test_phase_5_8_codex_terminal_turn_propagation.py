"""Phase 5 closeout Stage 2 §M.M5 follow-up #3 — Codex terminal-turn
propagation.

Operator-found Stage 2 wedge gap on Rerun 3 fresh smoke 1 milestone-1 Wave B
(run-dir
``v18 test runs/phase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516/``):

* Codex emitted ``item/started commandExecution`` (no matching
  ``item/completed``)
* Orphan-monitor sent ``turn/interrupt`` and emitted
  ``codex_orphan_observed`` (A1b signal flowed correctly to wave_executor)
* Codex emitted ``thread/archive`` and stopped emitting events
* No further ``item/completed`` ever arrived; protocol log ends at
  ``thread/archive``
* wave_executor heartbeat continues firing (task alive)
* No ``orphan-tool`` / ``tool-call-idle`` hang report produced
* No EXIT_CODE.txt; smoke effectively wedged until 5400s tier-4 fallback

Root cause — ``_wait_for_turn_completion`` (codex_appserver.py:1610) only
breaks the drain loop on ``method == "turn/completed"``; ``thread/archive``
just ``continue``\\s. With no further messages possible, ``await
client.next_notification()`` blocks indefinitely on an empty queue. The
wave_executor's ``_invoke_provider_wave_with_watchdog`` poll loop runs but
``task in done`` never fires (task stuck on the blocking await), so the
predicate never gets to fire because ``task.cancel()`` is gated on
``timeout is not None`` AFTER the predicate runs.

Operator-approved 3-pronged fix:

1. **codex_appserver-side**: typed ``CodexTerminalTurnError`` raised by
   ``_wait_for_turn_completion`` on:
   - ``thread/archive`` notification for the target thread before
     ``turn/completed``;
   - transport stdout EOF (``_read_stdout`` finally pushes an EOF
     sentinel into ``_notifications``; ``next_notification`` recognises
     the sentinel and raises).
2. **codex_appserver-side**: ``execute_codex`` finally bounds the
   cleanup ``client.thread_archive`` call with ``asyncio.wait_for``
   (10s) so cleanup itself can never become the next indefinite hang.
3. **wave_executor-side**:
   ``_invoke_provider_wave_with_watchdog`` catches
   ``CodexTerminalTurnError`` from ``task.result()`` and synthesises a
   ``WaveWatchdogTimeoutError`` via
   ``_synthesize_watchdog_timeout_from_state`` — preferring
   ``orphan-tool`` when ``state.pending_tool_starts`` proves a stale
   tool, then ``tool-call-idle`` (dual-track baseline) when productive
   signals are quiet, else propagating the original exception (no
   fabricated evidence).

Tests cover:

A) **codex_appserver source-level**:
   - ``test_thread_archive_for_target_thread_raises_terminal_turn_error``
   - ``test_thread_archive_for_other_thread_does_not_raise``
   - ``test_stdout_eof_pushes_sentinel_and_next_notification_raises``
   - ``test_normal_turn_completed_returns_normally`` (negative
     regression)
   - ``test_codex_terminal_turn_error_distinct_from_orphan_tool_error``
     (type lock)

B) **wave_executor synthesizer**:
   - ``test_synthesize_orphan_tool_when_pending_non_empty_and_aged``
   - ``test_synthesize_tool_call_idle_when_pending_empty_and_baseline_old``
   - ``test_synthesize_returns_none_when_state_does_not_prove_wedge``
   - ``test_synthesize_uses_dual_track_baseline``

C) **integration — exact live shape from Rerun 3 fresh**:
   - ``test_post_orphan_thread_archive_translates_to_orphan_tool_hang_report``
     — drives the full ``CodexTerminalTurnError`` → wave_executor
     translation with a state that mirrors the live wedge: pending
     non-empty (commandExecution), age >= 400s, codex_orphan_observed
     True, no fileChange. Asserts hang report ``timeout_kind=
     "orphan-tool"`` is written, no bootstrap counter increment
     (§O.4.10 invariant), and ``WaveWatchdogTimeoutError`` propagates.

D) **negative regression on §O.4.6 hang-report fields**:
   - ``test_synthesize_preserves_last_productive_tool_name_and_event_count``
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_team_v15 import wave_executor as we
from agent_team_v15.codex_appserver import (
    CodexOrphanToolError,
    CodexTerminalTurnError,
    _EOF_SENTINEL,
)
from agent_team_v15.config import V18Config
from agent_team_v15.wave_executor import (
    WaveWatchdogTimeoutError,
    _WaveWatchdogState,
    _synthesize_watchdog_timeout_from_state,
)


def _config_with_defaults() -> Any:
    class _Cfg:
        v18 = V18Config()
    return _Cfg()


# ---------------------------------------------------------------------------
# A — codex_appserver source-level tests
# ---------------------------------------------------------------------------


def test_codex_terminal_turn_error_distinct_from_orphan_tool_error() -> None:
    """Type lock — ``CodexTerminalTurnError`` is NOT the same class as
    ``CodexOrphanToolError``. They surface different failure modes:

    * ``CodexOrphanToolError`` — per-tool budget exhaustion (orphan
      events >= max_orphan_events).
    * ``CodexTerminalTurnError`` — per-session abnormal termination
      (thread/archive or stdout EOF before turn/completed).
    """

    err = CodexTerminalTurnError("test", thread_id="t1", turn_id="u1")
    assert isinstance(err, Exception)
    assert not isinstance(err, CodexOrphanToolError)
    assert err.thread_id == "t1"
    assert err.turn_id == "u1"
    assert "without turn/completed" in str(err)


def test_thread_archive_for_target_thread_raises_terminal_turn_error() -> None:
    """``_wait_for_turn_completion`` MUST raise
    :class:`CodexTerminalTurnError` when ``thread/archive`` arrives for
    the target thread before ``turn/completed``.

    The empirical Rerun 3 wedge shape: orphan-monitor sent
    turn/interrupt, then appserver emitted thread/archive, then no more
    messages. Pre-fix: drain loop ``continue``\\d on thread/archive,
    next_notification blocks forever. Post-fix: raises.
    """

    from agent_team_v15.codex_appserver import _wait_for_turn_completion, _MessageAccumulator, _OrphanWatchdog, _TokenAccumulator

    # Mock the client to feed a thread/archive notification.
    client = MagicMock()
    client.next_notification = AsyncMock(return_value={
        "method": "thread/archive",
        "params": {"threadId": "thread-target"},
    })

    watchdog = _OrphanWatchdog(timeout_seconds=300.0)
    tokens = _TokenAccumulator()
    messages = _MessageAccumulator()

    async def run() -> None:
        await _wait_for_turn_completion(
            client,
            thread_id="thread-target",
            turn_id="turn-target",
            watchdog=watchdog,
            tokens=tokens,
            progress_callback=None,
            messages=messages,
        )

    with pytest.raises(CodexTerminalTurnError) as excinfo:
        asyncio.run(run())
    assert excinfo.value.thread_id == "thread-target"
    assert excinfo.value.turn_id == "turn-target"
    assert "thread/archive" in excinfo.value.reason


def test_thread_archive_for_other_thread_does_not_raise() -> None:
    """``thread/archive`` for an UNRELATED thread MUST NOT raise — the
    drain loop must ``continue`` and keep waiting for the target turn.

    Defensive: the appserver MAY archive an unrelated thread (e.g.,
    a previous turn's residual cleanup) without affecting the active
    target turn's drain. Without this carve-out, the fix would
    spuriously kill healthy active turns.
    """

    from agent_team_v15.codex_appserver import _wait_for_turn_completion, _MessageAccumulator, _OrphanWatchdog, _TokenAccumulator

    target_completed = {
        "method": "turn/completed",
        "params": {
            "threadId": "thread-target",
            "turn": {"id": "turn-target", "status": "completed"},
        },
    }
    notifications = [
        {
            "method": "thread/archive",
            "params": {"threadId": "thread-other-unrelated"},
        },
        target_completed,
    ]
    notifications_iter = iter(notifications)

    client = MagicMock()
    client.next_notification = AsyncMock(
        side_effect=lambda: notifications_iter.__next__(),
    )

    watchdog = _OrphanWatchdog(timeout_seconds=300.0)
    tokens = _TokenAccumulator()
    messages = _MessageAccumulator()

    async def run() -> dict:
        return await _wait_for_turn_completion(
            client,
            thread_id="thread-target",
            turn_id="turn-target",
            watchdog=watchdog,
            tokens=tokens,
            progress_callback=None,
            messages=messages,
        )

    result = asyncio.run(run())
    assert result["id"] == "turn-target"


def test_stdout_eof_pushes_sentinel_and_next_notification_raises() -> None:
    """The transport's ``next_notification`` MUST raise
    :class:`CodexTerminalTurnError` when it consumes the EOF sentinel
    pushed by ``_read_stdout``'s ``finally`` on subprocess EOF.

    Without this, a consumer awaiting on ``_notifications.get()`` after
    the subprocess has exited would block forever on an empty queue.
    """

    from agent_team_v15.codex_appserver import _CodexJSONRPCTransport

    # Build a transport WITHOUT starting the subprocess — we just need
    # the queue and the next_notification method.
    transport = _CodexJSONRPCTransport.__new__(_CodexJSONRPCTransport)
    transport._notifications = asyncio.Queue()

    # Push the EOF sentinel directly (mimicking _read_stdout's finally).
    transport._notifications.put_nowait(_EOF_SENTINEL)

    async def run() -> dict:
        return await transport.next_notification()

    with pytest.raises(CodexTerminalTurnError) as excinfo:
        asyncio.run(run())
    assert "EOF" in excinfo.value.reason


def test_eof_sentinel_constant_shape() -> None:
    """Lock the EOF sentinel's shape so producers and consumers agree."""

    assert isinstance(_EOF_SENTINEL, dict)
    assert _EOF_SENTINEL.get("_codex_appserver_eof") is True


def test_normal_next_notification_returns_message_unchanged() -> None:
    """Negative regression — ``next_notification`` returns regular
    notifications unmodified (no false-positive EOF detection on
    well-formed messages)."""

    from agent_team_v15.codex_appserver import _CodexJSONRPCTransport

    transport = _CodexJSONRPCTransport.__new__(_CodexJSONRPCTransport)
    transport._notifications = asyncio.Queue()

    msg = {"method": "item/completed", "params": {"item": {"id": "x"}}}
    transport._notifications.put_nowait(msg)

    async def run() -> dict:
        return await transport.next_notification()

    result = asyncio.run(run())
    assert result == msg


# ---------------------------------------------------------------------------
# B — wave_executor synthesizer tests
# ---------------------------------------------------------------------------


def test_synthesize_orphan_tool_when_pending_non_empty_and_aged() -> None:
    """When the live state has a stale ``commandExecution`` in
    ``pending_tool_starts`` (age >= orphan_seconds), the synthesizer
    MUST return a ``WaveWatchdogTimeoutError(timeout_kind="orphan-tool")``
    with the correct ``orphan_tool_id`` / ``orphan_tool_name``.

    This mirrors the empirical Rerun 3 fresh wedge: item/started
    commandExecution had no matching item/completed at the time of
    thread/archive.
    """

    state = _WaveWatchdogState()
    state.bootstrap_cleared = True

    now = time.monotonic()
    cmdexec_started = now - 1700  # well past 400s threshold
    state.pending_tool_starts = {
        "call_TestOrphan_1": {
            "tool_name": "commandExecution",
            "started_at": "synthetic",
            "started_monotonic": cmdexec_started,
        },
    }
    state.last_tool_call_monotonic = cmdexec_started
    state.last_productive_tool_name = "commandExecution"
    state.tool_call_event_count = 1

    config = _config_with_defaults()
    timeout = _synthesize_watchdog_timeout_from_state(
        state=state,
        wave_letter="B",
        config=config,
    )

    assert timeout is not None
    assert timeout.timeout_kind == "orphan-tool"
    assert timeout.orphan_tool_id == "call_TestOrphan_1"
    assert timeout.orphan_tool_name == "commandExecution"


def test_synthesize_tool_call_idle_when_pending_empty_and_baseline_old() -> None:
    """When ``pending_tool_starts`` is empty AND the productive
    baseline (``max(last_tool_call_monotonic,
    last_file_mutation_monotonic)``) is >= 1200s old, the synthesiser
    MUST return ``timeout_kind="tool-call-idle"``."""

    state = _WaveWatchdogState()
    state.bootstrap_cleared = True
    state.pending_tool_starts = {}

    now = time.monotonic()
    state.last_tool_call_monotonic = now - 1300  # past 1200s threshold
    state.last_productive_tool_name = "commandExecution"
    state.tool_call_event_count = 2
    state.last_file_mutation_monotonic = 0.0

    config = _config_with_defaults()
    timeout = _synthesize_watchdog_timeout_from_state(
        state=state,
        wave_letter="B",
        config=config,
    )

    assert timeout is not None
    assert timeout.timeout_kind == "tool-call-idle"


def test_synthesize_returns_none_when_state_does_not_prove_wedge() -> None:
    """When state is too fresh OR has no productive baseline, the
    synthesiser MUST return ``None`` so the caller propagates the
    original exception (no fabricated evidence).

    Three sub-cases verified:
    * Pending non-empty but age below threshold → None
    * Pending empty + last_tool_call recent → None
    * Pending empty + no productive baseline AT ALL → None
    """

    config = _config_with_defaults()
    now = time.monotonic()

    # Sub-case 1: pending non-empty but young
    state1 = _WaveWatchdogState()
    state1.bootstrap_cleared = True
    state1.pending_tool_starts = {
        "x": {
            "tool_name": "commandExecution",
            "started_at": "x",
            "started_monotonic": now - 100,  # 100s — below 400s
        },
    }
    state1.last_tool_call_monotonic = now - 100
    assert _synthesize_watchdog_timeout_from_state(
        state=state1, wave_letter="B", config=config,
    ) is None

    # Sub-case 2: pending empty, last_tool_call recent
    state2 = _WaveWatchdogState()
    state2.bootstrap_cleared = True
    state2.pending_tool_starts = {}
    state2.last_tool_call_monotonic = now - 100  # below 1200s
    assert _synthesize_watchdog_timeout_from_state(
        state=state2, wave_letter="B", config=config,
    ) is None

    # Sub-case 3: no productive baseline at all (started_monotonic
    # alone, no codex_orphan_observed) — should return None per the
    # gate ``productive_baseline_present``.
    state3 = _WaveWatchdogState()
    state3.bootstrap_cleared = True
    state3.pending_tool_starts = {}
    state3.last_tool_call_monotonic = 0.0
    state3.last_file_mutation_monotonic = 0.0
    state3.codex_orphan_observed = False
    state3.started_monotonic = now - 1300
    assert _synthesize_watchdog_timeout_from_state(
        state=state3, wave_letter="B", config=config,
    ) is None


def test_synthesize_uses_dual_track_baseline() -> None:
    """The synthesiser's tier-3 baseline MUST be
    ``max(last_tool_call_monotonic, last_file_mutation_monotonic)``,
    matching the dual-track contract from ``6b790ce``.

    If last_tool_call is old (1300s) but last_file_mutation is recent
    (50s), the synthesiser MUST NOT fire (baseline = 50s < 1200s)."""

    state = _WaveWatchdogState()
    state.bootstrap_cleared = True
    state.pending_tool_starts = {}

    now = time.monotonic()
    state.last_tool_call_monotonic = now - 1300  # would fire tier-3 alone
    state.last_file_mutation_monotonic = now - 50  # recent — extends window
    state.last_productive_tool_name = "commandExecution"

    config = _config_with_defaults()
    timeout = _synthesize_watchdog_timeout_from_state(
        state=state, wave_letter="B", config=config,
    )
    assert timeout is None, (
        "dual-track baseline regression: synthesiser fired on stale "
        "last_tool_call when last_file_mutation was recent. Baseline "
        "MUST take the LATEST of the two timestamps."
    )


def test_synthesize_codex_orphan_observed_baseline_falls_back_to_started_monotonic() -> None:
    """Regression check on the §M.M5 follow-up #1 contract: when
    ``codex_orphan_observed=True`` AND both productive timestamps are
    0, the synthesiser MUST use ``started_monotonic`` as fallback
    baseline. Mirrors :func:`_build_wave_watchdog_timeout` behaviour."""

    state = _WaveWatchdogState()
    state.bootstrap_cleared = True
    state.pending_tool_starts = {}
    state.last_tool_call_monotonic = 0.0
    state.last_file_mutation_monotonic = 0.0
    state.codex_orphan_observed = True

    now = time.monotonic()
    state.started_monotonic = now - 1300

    config = _config_with_defaults()
    timeout = _synthesize_watchdog_timeout_from_state(
        state=state, wave_letter="B", config=config,
    )
    assert timeout is not None
    assert timeout.timeout_kind == "tool-call-idle"


# ---------------------------------------------------------------------------
# C — Integration: exact live shape from Rerun 3 fresh smoke 1
# ---------------------------------------------------------------------------


def test_post_orphan_thread_archive_translates_to_orphan_tool_hang_report(tmp_path) -> None:
    """Replays the exact live wedge shape from Rerun 3 fresh smoke 1
    milestone-1 Wave B at the full ``_invoke_provider_wave_with_watchdog``
    + ``CodexTerminalTurnError`` integration level:

    Sequence:
    1. ``item/started commandExecution`` fires via progress_callback →
       state.pending_tool_starts populated, last_tool_call_monotonic
       set, bootstrap_cleared=True.
    2. (No matching ``item/completed``.)
    3. ``codex_orphan_observed`` fires via progress_callback →
       state.codex_orphan_observed=True.
    4. (No ``fileChange`` after that.)
    5. Mock execute_wave_with_provider raises ``CodexTerminalTurnError``
       (mimicking the live thread/archive raise).

    Asserts (operator-required):
    * Provider watchdog produces a hang report under
      ``<cwd>/.agent-team/hang_reports/wave-B-<ts>.json`` with
      ``timeout_kind="orphan-tool"`` (pending non-empty + aged) within
      the synth path.
    * Hang report fields: ``timeout_kind``, ``last_tool_call_at``,
      ``last_sdk_tool_name``, etc., per the §O.4.6 column shape.
    * ``WaveWatchdogTimeoutError`` propagates out of
      ``_invoke_provider_wave_with_watchdog`` — caller's
      ``except WaveWatchdogTimeoutError`` branch handles it (tested
      separately).
    * Bootstrap counter NOT incremented (§O.4.10 invariant).
    * Termination occurs WELL BEFORE 5400s tier-4 fallback.
    """

    from agent_team_v15.wave_executor import _invoke_provider_wave_with_watchdog
    from agent_team_v15 import wave_executor as we_mod

    # Build a fake provider_routing dict that orchestrates the live shape.
    cwd = str(tmp_path)
    (tmp_path / ".agent-team").mkdir(exist_ok=True)

    state_holder: dict = {"state": None}

    async def fake_execute_wave_with_provider(*, progress_callback, **kwargs):
        # Capture the state to verify post-conditions
        # (progress_callback is bound to state.record_progress).
        # Step 1: simulate item/started commandExecution
        progress_callback(
            message_type="item/started",
            tool_name="commandExecution",
            tool_id="call_LiveOrphan_1",
            event_kind="start",
        )
        # Cycle the event loop to allow the watchdog state to update.
        await asyncio.sleep(0)
        # Backdate started_monotonic by 1700s so the synth fires
        # tier-2 orphan-tool when CodexTerminalTurnError raises.
        # (Direct state mutation bypasses real wall-clock dependence.)
        # The progress_callback's __self__ is the _WaveWatchdogState.
        state = progress_callback.__self__
        state_holder["state"] = state
        if "call_LiveOrphan_1" in state.pending_tool_starts:
            state.pending_tool_starts["call_LiveOrphan_1"]["started_monotonic"] = (
                time.monotonic() - 1700
            )
        state.last_tool_call_monotonic = time.monotonic() - 1700
        # Step 3: codex_orphan_observed (tool_id present, event_kind=other)
        progress_callback(
            message_type="codex_orphan_observed",
            tool_name="commandExecution",
            tool_id="call_LiveOrphan_1",
            event_kind="other",
        )
        await asyncio.sleep(0)
        # Step 5: raise CodexTerminalTurnError (mimics
        # _wait_for_turn_completion raising on thread/archive).
        raise CodexTerminalTurnError(
            "thread/archive received before turn/completed",
            thread_id="thread-target",
            turn_id="turn-target",
        )

    # Patch execute_wave_with_provider in provider_router to our fake.
    import agent_team_v15.provider_router as provider_router_mod
    original_exec_wave = provider_router_mod.execute_wave_with_provider
    provider_router_mod.execute_wave_with_provider = fake_execute_wave_with_provider

    try:
        async def run_dispatch():
            return await _invoke_provider_wave_with_watchdog(
                execute_sdk_call=AsyncMock(return_value=0.0),
                prompt="test prompt",
                wave_letter="B",
                config=_config_with_defaults(),
                cwd=cwd,
                milestone=type("M", (), {"id": "milestone-1"})(),
                provider_routing={
                    "provider_map": {"B": "codex"},
                    "codex_transport": MagicMock(),
                    "codex_config": MagicMock(),
                    "codex_home": tmp_path,
                },
                bootstrap_eligible=False,  # Codex
            )

        with pytest.raises(WaveWatchdogTimeoutError) as excinfo:
            asyncio.run(run_dispatch())
        assert excinfo.value.timeout_kind == "orphan-tool"

        # Verify hang report was written.
        hang_dir = tmp_path / ".agent-team" / "hang_reports"
        hang_files = list(hang_dir.glob("wave-B-*.json"))
        assert len(hang_files) == 1, (
            f"Expected exactly 1 hang report under {hang_dir}; "
            f"got {hang_files!r}"
        )
        import json as _json
        report = _json.loads(hang_files[0].read_text())
        assert report["timeout_kind"] == "orphan-tool"
        assert report.get("orphan_tool_name") == "commandExecution"
        assert report["wave"] == "B"
        assert report["milestone_id"] == "milestone-1"

        # §O.4.10 invariant — Codex path must NOT increment cumulative
        # wedge counter on this synthetic wedge. The test environment
        # has no callback installed, so _get_cumulative_wedge_count
        # returns 0; the hang report records that.
        assert report.get("cumulative_wedges_so_far", 0) == 0

    finally:
        provider_router_mod.execute_wave_with_provider = original_exec_wave


def test_invoke_provider_propagates_terminal_turn_when_state_does_not_prove_wedge(
    tmp_path,
) -> None:
    """When ``CodexTerminalTurnError`` raises with a state that does NOT
    prove a wedge (e.g., immediately after sdk_call_started), the
    synthesiser returns None and the wave_executor MUST propagate the
    original exception unchanged.

    This guards against fabricated hang-report evidence for premature
    terminations that have legitimate other causes."""

    from agent_team_v15.wave_executor import _invoke_provider_wave_with_watchdog

    cwd = str(tmp_path)
    (tmp_path / ".agent-team").mkdir(exist_ok=True)

    async def fake_execute_wave_with_provider(*, progress_callback, **kwargs):
        # Only sdk_call_started fires (no productive event, no
        # codex_orphan_observed, no pending tools).
        # Then raise immediately.
        raise CodexTerminalTurnError(
            "premature termination",
            thread_id="t",
            turn_id="u",
        )

    import agent_team_v15.provider_router as provider_router_mod
    original_exec_wave = provider_router_mod.execute_wave_with_provider
    provider_router_mod.execute_wave_with_provider = fake_execute_wave_with_provider

    try:
        async def run_dispatch():
            return await _invoke_provider_wave_with_watchdog(
                execute_sdk_call=AsyncMock(return_value=0.0),
                prompt="test",
                wave_letter="B",
                config=_config_with_defaults(),
                cwd=cwd,
                milestone=type("M", (), {"id": "milestone-1"})(),
                provider_routing={
                    "provider_map": {"B": "codex"},
                    "codex_transport": MagicMock(),
                    "codex_config": MagicMock(),
                    "codex_home": tmp_path,
                },
                bootstrap_eligible=False,
            )

        with pytest.raises(CodexTerminalTurnError):
            asyncio.run(run_dispatch())

        # No hang report should be written when the state does not
        # prove a wedge.
        hang_dir = tmp_path / ".agent-team" / "hang_reports"
        hang_files = list(hang_dir.glob("wave-B-*.json")) if hang_dir.is_dir() else []
        assert len(hang_files) == 0, (
            f"Synthesiser fabricated hang report despite state not "
            f"proving a wedge: {hang_files!r}"
        )

    finally:
        provider_router_mod.execute_wave_with_provider = original_exec_wave


# ---------------------------------------------------------------------------
# D — Negative regression on §O.4.6 hang-report fields
# ---------------------------------------------------------------------------


def test_synthesize_preserves_last_productive_tool_name_and_event_count() -> None:
    """The synthesiser MUST NOT mutate or fabricate
    ``last_productive_tool_name`` or ``tool_call_event_count`` — these
    are operator-locked column-shape fields per the §O.4.6 hang-report
    closure (B1 rerun at run-dir
    ``phase-5-closeout-stage-2a-iv-rerun-o46-b1-20260501-103942/``).

    The synthesiser READS state but does not write back to it. This
    test confirms the post-call state is byte-identical to the pre-call
    state for those columns."""

    state = _WaveWatchdogState()
    state.bootstrap_cleared = True
    state.pending_tool_starts = {
        "x": {
            "tool_name": "commandExecution",
            "started_at": "synthetic",
            "started_monotonic": time.monotonic() - 1700,
        },
    }
    state.last_tool_call_monotonic = time.monotonic() - 1700
    state.last_productive_tool_name = "commandExecution"
    state.tool_call_event_count = 3

    pre_lptn = state.last_productive_tool_name
    pre_count = state.tool_call_event_count

    config = _config_with_defaults()
    _synthesize_watchdog_timeout_from_state(
        state=state, wave_letter="B", config=config,
    )

    assert state.last_productive_tool_name == pre_lptn
    assert state.tool_call_event_count == pre_count


# ---------------------------------------------------------------------------
# E — Propagation gap closures (operator-found at HEAD 347163e)
# ---------------------------------------------------------------------------
#
# Operator found that the prior commit (347163e) had two broad
# ``except Exception`` sites that swallowed CodexTerminalTurnError BEFORE
# it could reach wave_executor's synth path:
#
# 1. ``codex_appserver._execute_once`` (codex_appserver.py:1896 area)
# 2. ``provider_router._execute_codex_wave`` (provider_router.py:474 area)
#
# Both must early-re-raise CodexTerminalTurnError before the broad except.
# Otherwise the typed error becomes a generic failed CodexResult / a
# _codex_hard_failure return, and the wave_executor never sees it as an
# exception (so the synth helper never runs, and no canonical hang report
# is written).
#
# These tests fail at parent commit ``347163e`` (TDD pre-fix lock) and
# pass post-fix.


def test_execute_once_does_not_swallow_terminal_turn_error(tmp_path) -> None:
    """``_execute_once`` MUST re-raise ``CodexTerminalTurnError``
    instead of converting it to a failed ``CodexResult`` via the broad
    ``except Exception``.

    Pre-fix (347163e): the broad ``except Exception as exc`` at
    codex_appserver.py:1896 caught the error, set ``result.success=False``
    and ``result.error = _app_server_error_message(client, exc)``, and
    returned a ``CodexResult`` normally. The typed error never escaped
    ``_execute_once``.

    Post-fix: an explicit ``except CodexTerminalTurnError: raise`` BEFORE
    the broad except lets the typed error escape this layer cleanly.
    """

    from agent_team_v15.codex_appserver import (
        _execute_once,
        CodexConfig,
        _CodexAppServerClient,
    )

    config = CodexConfig()

    # Patch the inner pieces just enough that _execute_once reaches the
    # try-block's `_wait_for_turn_completion` call. We replace
    # ``_wait_for_turn_completion`` itself with a stub that raises
    # CodexTerminalTurnError so we can isolate the early-re-raise
    # behaviour at the _execute_once layer.
    from unittest.mock import patch as _patch

    async def fake_wait_for_turn_completion(*a, **k):
        raise CodexTerminalTurnError(
            "thread/archive received before turn/completed",
            thread_id="thread-target",
            turn_id="turn-target",
        )

    # Mock the client's start/initialize/thread_start/turn_start so we
    # can drive _execute_once to the wait_for_turn_completion call.
    async def fake_async_noop(*a, **k):
        return {}

    async def fake_thread_start(*a, **k):
        return {"thread": {"id": "thread-target"}}

    async def fake_turn_start(*a, **k):
        return {"turn": {"id": "turn-target"}}

    fake_client = MagicMock()
    fake_client.start = AsyncMock(side_effect=fake_async_noop)
    fake_client.initialize = AsyncMock(return_value={"userAgent": "test", "codexHome": str(tmp_path)})
    fake_client.thread_start = AsyncMock(side_effect=fake_thread_start)
    fake_client.turn_start = AsyncMock(side_effect=fake_turn_start)
    fake_client.thread_archive = AsyncMock(side_effect=fake_async_noop)
    fake_client.close = AsyncMock(side_effect=fake_async_noop)
    fake_client.returncode = 0
    fake_client.cwd = str(tmp_path)
    fake_client.stderr_excerpt = MagicMock(return_value="")

    with _patch(
        "agent_team_v15.codex_appserver._CodexAppServerClient",
        return_value=fake_client,
    ), _patch(
        "agent_team_v15.codex_appserver._wait_for_turn_completion",
        side_effect=fake_wait_for_turn_completion,
    ):
        async def run() -> None:
            await _execute_once(
                prompt="test prompt",
                cwd=str(tmp_path),
                config=config,
                codex_home=tmp_path,
            )

        with pytest.raises(CodexTerminalTurnError) as excinfo:
            asyncio.run(run())
        assert excinfo.value.thread_id == "thread-target"
        assert excinfo.value.turn_id == "turn-target"


def test_execute_codex_wave_does_not_convert_terminal_turn_to_hard_failure(tmp_path) -> None:
    """``provider_router._execute_codex_wave`` MUST re-raise
    ``CodexTerminalTurnError`` instead of catching it in the broad
    ``except Exception`` and returning a ``_codex_hard_failure`` dict.

    Pre-fix (347163e): the broad ``except Exception as exc`` at
    provider_router.py:474 caught the error, called
    ``rollback_from_snapshot`` and returned ``_codex_hard_failure(...)``
    — a successful return. The wave_executor's task in
    ``_invoke_provider_wave_with_watchdog`` then saw ``task.result()``
    return a dict (not raise), and the synth helper never ran. No
    canonical hang report.

    Post-fix: an explicit ``except _CodexTerminalTurnError: raise``
    BEFORE the broad except propagates the typed error to
    ``_invoke_provider_wave_with_watchdog``'s task-done branch, which
    calls the synth helper.
    """

    import agent_team_v15.provider_router as provider_router_mod
    from agent_team_v15.wave_executor import _create_checkpoint, _diff_checkpoints

    cwd = str(tmp_path)
    (tmp_path / ".agent-team").mkdir(exist_ok=True)
    # Need at least one file in cwd for the checkpoint manifest.
    (tmp_path / "marker.txt").write_text("synthetic", encoding="utf-8")

    # Mock execute_codex on the codex_transport_module to raise
    # CodexTerminalTurnError. This simulates the real path where
    # codex_appserver._execute_once raises (post fix #1).
    fake_codex_transport = MagicMock()

    async def fake_execute_codex(*a, **k):
        raise CodexTerminalTurnError(
            "stdout EOF — subprocess exited",
            thread_id="t",
            turn_id="u",
        )

    fake_codex_transport.execute_codex = fake_execute_codex
    fake_codex_transport.CodexConfig = MagicMock

    fake_codex_config = MagicMock()
    fake_codex_config.model = "gpt-test"

    async def run_dispatch():
        # Use the REAL ``_create_checkpoint`` and ``_diff_checkpoints``
        # so ``snapshot_for_rollback`` / ``rollback_from_snapshot`` see a
        # well-formed ``WaveCheckpoint`` (not a dict). This exercises
        # the ACTUAL provider_router rollback path that the broad
        # ``except Exception`` branch invokes — the operator's
        # required-test contract is that the rollback runs but the
        # CodexTerminalTurnError still propagates instead of being
        # converted to ``_codex_hard_failure``.
        return await provider_router_mod._execute_codex_wave(
            prompt="test",
            wave_letter="B",
            cwd=cwd,
            config=type("C", (), {"v18": MagicMock()})(),
            claude_callback=AsyncMock(return_value=0.0),
            claude_callback_kwargs={},
            codex_transport_module=fake_codex_transport,
            codex_config=fake_codex_config,
            codex_home=tmp_path,
            checkpoint_create=_create_checkpoint,
            checkpoint_diff=_diff_checkpoints,
        )

    with pytest.raises(CodexTerminalTurnError):
        asyncio.run(run_dispatch())


def test_full_invoke_provider_wave_with_real_provider_router_path(tmp_path) -> None:
    """Operator-required integration test: the full
    ``_invoke_provider_wave_with_watchdog`` path uses the REAL
    ``provider_router._execute_codex_wave`` (not a bypass patch of
    ``execute_wave_with_provider``), with only the lowest-level
    ``codex_transport_module.execute_codex`` mocked.

    This covers the ENTIRE propagation chain end-to-end:

    1. wave_executor's task spawns ``execute_wave_with_provider`` (real).
    2. ``execute_wave_with_provider`` calls ``_execute_codex_wave``
       (real).
    3. ``_execute_codex_wave`` calls ``codex_transport_module.execute_codex``
       (mocked — raises CodexTerminalTurnError).
    4. The error propagates through:
       - mock execute_codex → raise
       - real ``_execute_codex_wave`` (must re-raise — fix #2)
       - real ``execute_wave_with_provider`` (no broad except — passes
         through)
       - wave_executor's ``task`` becomes done with the exception
       - ``_invoke_provider_wave_with_watchdog``'s try/except around
         ``task.result()`` catches it
       - Synth helper builds ``WaveWatchdogTimeoutError(timeout_kind=
         "orphan-tool")`` from live state
       - Hang report written; synth raised

    Asserts:
    * ``WaveWatchdogTimeoutError`` raised with
      ``timeout_kind="orphan-tool"``.
    * Hang report on disk under
      ``<cwd>/.agent-team/hang_reports/wave-B-*.json`` with
      ``timeout_kind="orphan-tool"``.
    """

    from agent_team_v15.wave_executor import _invoke_provider_wave_with_watchdog
    from agent_team_v15.provider_router import WaveProviderMap

    cwd = str(tmp_path)
    (tmp_path / ".agent-team").mkdir(exist_ok=True)
    # Need at least one file in cwd for the checkpoint manifest used by
    # provider_router._execute_codex_wave's rollback path.
    (tmp_path / "marker.txt").write_text("synthetic", encoding="utf-8")

    # Mock ONLY the lowest-level execute_codex. The inner wrap simulates
    # the live wedge shape (item/started commandExecution + no
    # completion + codex_orphan_observed + thread/archive raise) by
    # driving progress events through the progress_callback BEFORE
    # raising.
    fake_codex_transport = MagicMock()

    async def fake_execute_codex(prompt, cwd_, config=None, codex_home=None,
                                 *, progress_callback=None, **k):
        if progress_callback is not None:
            # Simulate item/started commandExecution
            progress_callback(
                message_type="item/started",
                tool_name="commandExecution",
                tool_id="call_LiveOrphan_X",
                event_kind="start",
            )
            # Backdate so the synth fires tier-2 orphan-tool
            await asyncio.sleep(0)
            # Use the bound state's __self__ to backdate
            state_obj = getattr(progress_callback, "__self__", None)
            if state_obj is not None and "call_LiveOrphan_X" in state_obj.pending_tool_starts:
                state_obj.pending_tool_starts["call_LiveOrphan_X"]["started_monotonic"] = (
                    time.monotonic() - 1700
                )
                state_obj.last_tool_call_monotonic = time.monotonic() - 1700
            # Simulate codex_orphan_observed
            progress_callback(
                message_type="codex_orphan_observed",
                tool_name="commandExecution",
                tool_id="call_LiveOrphan_X",
                event_kind="other",
            )
            await asyncio.sleep(0)
        raise CodexTerminalTurnError(
            "thread/archive received before turn/completed",
            thread_id="t",
            turn_id="u",
        )

    fake_codex_transport.execute_codex = fake_execute_codex

    async def run_dispatch():
        return await _invoke_provider_wave_with_watchdog(
            execute_sdk_call=AsyncMock(return_value=0.0),
            prompt="test prompt",
            wave_letter="B",
            config=_config_with_defaults(),
            cwd=cwd,
            milestone=type("M", (), {"id": "milestone-1"})(),
            provider_routing={
                # ``execute_wave_with_provider`` requires a real
                # ``WaveProviderMap``, NOT a dict — its routing logic
                # calls ``provider_map.provider_for(wave_letter)``. Use
                # the real dataclass; default ``B="codex"`` matches
                # production routing.
                "provider_map": WaveProviderMap(),
                "codex_transport": fake_codex_transport,
                "codex_config": MagicMock(model="gpt-test"),
                "codex_home": tmp_path,
            },
            bootstrap_eligible=False,
        )

    with pytest.raises(WaveWatchdogTimeoutError) as excinfo:
        asyncio.run(run_dispatch())
    assert excinfo.value.timeout_kind == "orphan-tool", (
        f"Expected synth timeout_kind='orphan-tool'; got "
        f"{excinfo.value.timeout_kind!r}"
    )

    # Hang report must be on disk.
    hang_dir = tmp_path / ".agent-team" / "hang_reports"
    hang_files = list(hang_dir.glob("wave-B-*.json"))
    assert len(hang_files) == 1, (
        f"Expected exactly 1 hang report under {hang_dir}; got "
        f"{hang_files!r}"
    )
    import json as _json
    report = _json.loads(hang_files[0].read_text())
    assert report["timeout_kind"] == "orphan-tool"
    assert report.get("orphan_tool_name") == "commandExecution"


def test_normal_archive_cleanup_is_bounded() -> None:
    """Source-static lock — ``execute_codex``'s ``finally`` block
    MUST wrap the cleanup ``client.thread_archive`` call with
    ``asyncio.wait_for`` so cleanup itself can NEVER become the next
    indefinite hang.

    Pre-fix: ``await client.thread_archive(thread_id)`` could block
    forever if the appserver subprocess is alive but unresponsive.
    Post-fix: bounded with ``asyncio.wait_for(..., timeout=10.0)``.
    """

    import inspect
    import re
    from agent_team_v15 import codex_appserver as codex_app

    # The thread_archive cleanup is in ``_execute_once`` (the per-attempt
    # session loop called from ``execute_codex``). Check that function
    # body for the bounded wait_for.
    src = inspect.getsource(codex_app._execute_once)
    # The cleanup block must use asyncio.wait_for with a positive
    # timeout when calling client.thread_archive. Permissive separators
    # to handle the actual multi-line wrap in the source.
    pattern = re.compile(
        r"asyncio\.wait_for\([\s\S]*?client\.thread_archive\([\s\S]*?timeout\s*=\s*\d+(?:\.\d+)?",
    )
    assert pattern.search(src), (
        "Phase 5 closeout Stage 2 §M.M5 follow-up #3: execute_codex's "
        "finally block MUST bound client.thread_archive with "
        "asyncio.wait_for. Pre-fix the unbounded await could become "
        "the next indefinite hang. Search around codex_appserver.py "
        "execute_codex finally block for the missing wait_for."
    )
