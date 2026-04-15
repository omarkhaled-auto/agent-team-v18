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
