from __future__ import annotations

import types

from agent_team_v15 import wave_executor


def _config(*, wave_idle_timeout_seconds: int = 1800, orphan_tool_idle_timeout_seconds: int = 600) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        v18=types.SimpleNamespace(
            wave_idle_timeout_seconds=wave_idle_timeout_seconds,
            orphan_tool_idle_timeout_seconds=orphan_tool_idle_timeout_seconds,
        )
    )


def _pending_state(tool_id: str = "item_1", tool_name: str = "command_execution") -> wave_executor._WaveWatchdogState:
    state = wave_executor._WaveWatchdogState()
    state.last_progress_monotonic = 0.0
    state.last_message_type = "item.started"
    state.last_tool_name = tool_name
    state.pending_tool_starts[tool_id] = {
        "tool_name": tool_name,
        "started_at": "2026-04-15T00:00:00+00:00",
        "started_monotonic": 0.0,
    }
    return state


def _idle_state() -> wave_executor._WaveWatchdogState:
    state = wave_executor._WaveWatchdogState()
    state.last_progress_monotonic = 0.0
    state.last_message_type = "assistant_message"
    state.last_tool_name = ""
    return state


class TestOrphanAwareFailFast:
    def test_pending_tool_starts_trip_orphan_budget(self, monkeypatch) -> None:
        state = _pending_state()
        monkeypatch.setattr(wave_executor.time, "monotonic", lambda: 600.0)

        timeout = wave_executor._build_wave_watchdog_timeout(
            wave_letter="B",
            state=state,
            config=_config(),
        )

        assert timeout is not None
        assert timeout.timeout_seconds == 600
        assert timeout.timeout_kind == "orphan-tool"
        assert "orphan-tool wedge" in str(timeout).lower()
        assert "command_execution" in str(timeout)
        assert "item_1" in str(timeout)

    def test_no_pending_tool_waits_full_wave_budget(self, monkeypatch) -> None:
        state = _idle_state()
        monkeypatch.setattr(wave_executor.time, "monotonic", lambda: 600.0)

        timeout = wave_executor._build_wave_watchdog_timeout(
            wave_letter="B",
            state=state,
            config=_config(),
        )

        assert timeout is None

    def test_regular_wave_idle_timeout_still_fires_at_1800(self, monkeypatch) -> None:
        state = _idle_state()
        monkeypatch.setattr(wave_executor.time, "monotonic", lambda: 1800.0)

        timeout = wave_executor._build_wave_watchdog_timeout(
            wave_letter="B",
            state=state,
            config=_config(),
        )

        assert timeout is not None
        assert timeout.timeout_seconds == 1800
        assert timeout.timeout_kind == "wave-idle"
        assert "idle timeout of 1800s" in str(timeout)
        assert "orphan-tool" not in str(timeout).lower()

    def test_cleared_orphan_returns_to_full_budget(self, monkeypatch) -> None:
        state = _pending_state()
        state.record_progress(
            message_type="item.completed",
            tool_name="command_execution",
            tool_id="item_1",
            event_kind="complete",
        )
        monkeypatch.setattr(wave_executor.time, "monotonic", lambda: 600.0)

        timeout = wave_executor._build_wave_watchdog_timeout(
            wave_letter="B",
            state=state,
            config=_config(),
        )

        assert timeout is None
        assert wave_executor._effective_wave_idle_timeout_seconds(_config(), state) == 1800

    def test_config_override_respects_orphan_tool_idle_timeout(self, monkeypatch) -> None:
        state = _pending_state(tool_id="item_99", tool_name="shell")
        monkeypatch.setattr(wave_executor.time, "monotonic", lambda: 120.0)

        timeout = wave_executor._build_wave_watchdog_timeout(
            wave_letter="D",
            state=state,
            config=_config(orphan_tool_idle_timeout_seconds=120),
        )

        assert timeout is not None
        assert timeout.timeout_seconds == 120
        assert timeout.timeout_kind == "orphan-tool"
        assert "item_99" in str(timeout)


class TestCodexOrphanObservedClearsPendingToolId:
    """rerun13 forensic — Defect A:

    Codex appserver's orphan-monitor emits a synthetic
    ``codex_orphan_observed`` progress event with the orphaned ``tool_id``
    BEFORE sending ``turn/interrupt``. Once that event lands, the SDK
    will never emit ``item/completed`` for the abandoned item; leaving it
    in ``state.pending_tool_starts`` causes tier-2 to re-fire the wedge
    on the very next watchdog tick — overriding the corrective prompt
    that is producing real output on the new turn.

    Fix contract: the synthetic event clears ONLY the matching
    ``tool_id`` from ``pending_tool_starts``; other live tools, the
    ``codex_orphan_observed`` flag, and tier-3 tool-call-idle behaviour
    must remain intact.
    """

    def test_codex_orphan_observed_clears_pending_tool_starts_for_tool_id(
        self, monkeypatch
    ) -> None:
        state = _pending_state(tool_id="rs_X", tool_name="reasoning")

        # Codex appserver emits the synthetic event for the orphaned id
        # AFTER 350s of no completion; ``event_kind`` is "other".
        state.record_progress(
            message_type="codex_orphan_observed",
            tool_name="reasoning",
            tool_id="rs_X",
            event_kind="other",
        )

        assert state.codex_orphan_observed is True
        assert "rs_X" not in state.pending_tool_starts, (
            "codex_orphan_observed for rs_X must clear that pending entry "
            "so the corrective prompt's new turn isn't pre-empted by tier-2"
        )

        # Even at age 410s (past the 400s threshold) tier-2 must NOT fire
        # because the orphan has been abandoned by the corrective path.
        monkeypatch.setattr(wave_executor.time, "monotonic", lambda: 410.0)
        timeout = wave_executor._build_wave_watchdog_timeout(
            wave_letter="B",
            state=state,
            config=_config(orphan_tool_idle_timeout_seconds=400),
        )
        assert timeout is None, (
            "tier-2 fired despite codex_orphan_observed clearing the entry; "
            "the corrective prompt would be killed prematurely (rerun13 bug)"
        )

    def test_codex_orphan_observed_does_not_drop_other_pending_tools(
        self, monkeypatch
    ) -> None:
        state = _pending_state(tool_id="rs_A", tool_name="reasoning")
        # Second pending tool (real, not orphaned).
        state.pending_tool_starts["rs_B"] = {
            "tool_name": "commandExecution",
            "started_at": "2026-04-15T00:00:00+00:00",
            "started_monotonic": 0.0,
        }

        state.record_progress(
            message_type="codex_orphan_observed",
            tool_name="reasoning",
            tool_id="rs_A",
            event_kind="other",
        )

        assert "rs_A" not in state.pending_tool_starts
        assert "rs_B" in state.pending_tool_starts, (
            "synthetic event must clear ONLY the named tool_id, not the dict"
        )

        # rs_B aged to 410s — tier-2 still fires on it.
        monkeypatch.setattr(wave_executor.time, "monotonic", lambda: 410.0)
        timeout = wave_executor._build_wave_watchdog_timeout(
            wave_letter="B",
            state=state,
            config=_config(orphan_tool_idle_timeout_seconds=400),
        )
        assert timeout is not None
        assert timeout.timeout_kind == "orphan-tool"
        assert "rs_B" in str(timeout)
        assert "rs_A" not in str(timeout)

    def test_codex_orphan_observed_without_tool_id_is_noop_for_pending_starts(
        self,
    ) -> None:
        state = _pending_state(tool_id="rs_X", tool_name="reasoning")

        # Defensive: no tool_id provided — flag still flips, pending dict
        # untouched (no entry to target).
        state.record_progress(
            message_type="codex_orphan_observed",
            tool_name="reasoning",
            tool_id="",
            event_kind="other",
        )

        assert state.codex_orphan_observed is True
        assert "rs_X" in state.pending_tool_starts, (
            "empty tool_id must not blanket-clear pending_tool_starts"
        )
