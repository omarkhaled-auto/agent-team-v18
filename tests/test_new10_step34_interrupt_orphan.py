"""Tests for NEW-10 Steps 3+4: client.interrupt() + orphan tool detection."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.wave_executor import _WaveWatchdogState
from agent_team_v15.orphan_detector import OrphanToolDetector, OrphanToolEvent


# ===========================================================================
# Step 3: _WaveWatchdogState client.interrupt() integration
# ===========================================================================


def test_watchdog_state_has_client_field():
    """_WaveWatchdogState must have a `client` attribute (defaults to None)."""
    state = _WaveWatchdogState()
    assert hasattr(state, "client")
    assert state.client is None


def test_watchdog_state_has_interrupt_count():
    """_WaveWatchdogState must have an `interrupt_count` field starting at 0."""
    state = _WaveWatchdogState()
    assert hasattr(state, "interrupt_count")
    assert state.interrupt_count == 0


@pytest.mark.asyncio
async def test_interrupt_oldest_orphan_returns_none_when_no_orphans():
    """With an empty pending_tool_starts dict, interrupt_oldest_orphan
    should return None without calling interrupt()."""
    state = _WaveWatchdogState()
    mock_client = AsyncMock()
    state.client = mock_client
    result = await state.interrupt_oldest_orphan(threshold_seconds=60)
    assert result is None
    mock_client.interrupt.assert_not_called()


@pytest.mark.asyncio
async def test_interrupt_oldest_orphan_returns_none_when_no_client():
    """With no client reference, interrupt_oldest_orphan should return None
    even if there are pending tools past threshold (safe no-op)."""
    state = _WaveWatchdogState()
    state.client = None
    # Add an old pending tool
    state.pending_tool_starts["tool-1"] = {
        "tool_name": "shell",
        "started_at": "2026-04-17T00:00:00Z",
        "started_monotonic": time.monotonic() - 9999,
    }
    result = await state.interrupt_oldest_orphan(threshold_seconds=60)
    assert result is None


@pytest.mark.asyncio
async def test_interrupt_oldest_orphan_fires_on_threshold():
    """When a pending tool exceeds the threshold, interrupt_oldest_orphan
    should call client.interrupt() and increment interrupt_count."""
    state = _WaveWatchdogState()
    mock_client = AsyncMock()
    mock_client.interrupt = AsyncMock(return_value=None)
    state.client = mock_client

    # Add a tool that started 120s ago
    state.pending_tool_starts["tool-abc"] = {
        "tool_name": "shell",
        "started_at": "2026-04-17T00:00:00Z",
        "started_monotonic": time.monotonic() - 120,
    }

    result = await state.interrupt_oldest_orphan(threshold_seconds=60)
    assert result is not None
    mock_client.interrupt.assert_awaited_once()
    assert state.interrupt_count == 1


@pytest.mark.asyncio
async def test_interrupt_oldest_orphan_returns_orphan_info():
    """The returned dict must contain tool_use_id, tool_name, and age_seconds."""
    state = _WaveWatchdogState()
    mock_client = AsyncMock()
    mock_client.interrupt = AsyncMock(return_value=None)
    state.client = mock_client

    state.pending_tool_starts["tool-xyz"] = {
        "tool_name": "write_file",
        "started_at": "2026-04-17T00:00:00Z",
        "started_monotonic": time.monotonic() - 200,
    }

    result = await state.interrupt_oldest_orphan(threshold_seconds=60)
    assert "tool_use_id" in result
    assert result["tool_use_id"] == "tool-xyz"
    assert result["tool_name"] == "write_file"
    assert "age_seconds" in result
    assert result["age_seconds"] > 100  # should be ~200


@pytest.mark.asyncio
async def test_watchdog_first_orphan_interrupts_second_escalates():
    """First orphan detection -> interrupt (count 0->1).
    Second orphan detection -> count goes to 2 (escalation threshold
    for containment timeout in the wave executor)."""
    state = _WaveWatchdogState()
    mock_client = AsyncMock()
    mock_client.interrupt = AsyncMock(return_value=None)
    state.client = mock_client

    # First orphan
    state.pending_tool_starts["tool-1"] = {
        "tool_name": "shell",
        "started_at": "2026-04-17T00:00:00Z",
        "started_monotonic": time.monotonic() - 300,
    }
    r1 = await state.interrupt_oldest_orphan(threshold_seconds=60)
    assert r1 is not None
    assert state.interrupt_count == 1

    # Second orphan (tool still pending or new one)
    state.pending_tool_starts["tool-2"] = {
        "tool_name": "npm_install",
        "started_at": "2026-04-17T00:01:00Z",
        "started_monotonic": time.monotonic() - 300,
    }
    r2 = await state.interrupt_oldest_orphan(threshold_seconds=60)
    assert r2 is not None
    assert state.interrupt_count == 2


def test_set_watchdog_client_injects_reference():
    """_set_watchdog_client should inject the client reference into the
    _WaveWatchdogState bound to the progress callback."""
    from agent_team_v15.cli import _set_watchdog_client

    state = _WaveWatchdogState()
    progress_cb = state.record_progress  # bound method

    mock_client = MagicMock()
    _set_watchdog_client(progress_cb, mock_client)
    assert state.client is mock_client


# ===========================================================================
# Step 4: OrphanToolDetector
# ===========================================================================


def test_orphan_detector_tracks_tool_use():
    """on_tool_use should add the tool to _pending_tools."""
    detector = OrphanToolDetector(timeout_seconds=60)
    detector.on_tool_use("tu-1", "shell")
    assert "tu-1" in detector._pending_tools
    assert detector._pending_tools["tu-1"]["tool_name"] == "shell"


def test_orphan_detector_clears_on_tool_result():
    """on_tool_result should remove the tool from _pending_tools."""
    detector = OrphanToolDetector(timeout_seconds=60)
    detector.on_tool_use("tu-1", "shell")
    assert "tu-1" in detector._pending_tools
    detector.on_tool_result("tu-1")
    assert "tu-1" not in detector._pending_tools


def test_orphan_detector_fires_on_timeout():
    """check_orphans should return an OrphanToolEvent when a tool exceeds timeout."""
    detector = OrphanToolDetector(timeout_seconds=10)

    with patch("agent_team_v15.orphan_detector.time") as mock_time:
        # Record tool use at t=1000
        mock_time.monotonic.return_value = 1000.0
        detector.on_tool_use("tu-1", "shell")

        # Check at t=1020 (20s > 10s timeout)
        mock_time.monotonic.return_value = 1020.0
        orphans = detector.check_orphans()

    assert len(orphans) == 1
    assert isinstance(orphans[0], OrphanToolEvent)
    assert orphans[0].tool_use_id == "tu-1"
    assert orphans[0].tool_name == "shell"
    assert orphans[0].age_seconds == pytest.approx(20.0, abs=1.0)


def test_orphan_detector_clear_resets_state():
    """clear() should empty all pending tool tracking."""
    detector = OrphanToolDetector(timeout_seconds=60)
    detector.on_tool_use("tu-1", "shell")
    detector.on_tool_use("tu-2", "read_file")
    assert len(detector._pending_tools) == 2
    detector.clear()
    assert len(detector._pending_tools) == 0
