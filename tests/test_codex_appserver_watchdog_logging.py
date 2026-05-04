"""Diagnostic-logging tests for the Codex app-server orphan watchdog.

Rationale
---------
In R1B1-server-req-fix (2026-04-22) the wave-executor's 600s wedge watchdog
fired on ``todo_list item_1`` but the transport's own 300s ``_monitor_orphans``
apparently did nothing — ``grep "Orphan tool detected"`` returned zero hits.
Without diagnostic logs we can't tell whether the transport watchdog:

  (a) saw zero pending items the whole turn (no ``record_start`` happened),
  (b) saw items but they never aged past 300s (strange — turn was silent
      for 620s), or
  (c) was cancelled / never started.

These tests pin the new diagnostic logging so future wedges are debuggable
from the run.log alone:

  * ``_OrphanWatchdog.snapshot_pending()`` returns the pending-items view
  * ``record_start`` / ``record_complete`` emit DEBUG lines
  * ``_monitor_orphans`` emits an INFO "started" line
  * When an orphan is detected, the WARNING includes the full pending list
  * Periodic pending snapshots emit at INFO every N polls
"""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from agent_team_v15 import codex_appserver as mod


class _FakeClient:
    """Minimal client stub — ``_send_turn_interrupt`` calls
    ``client.send_request`` or ``client.turn_interrupt``."""

    def __init__(self) -> None:
        self.interrupts: list[tuple[str, str]] = []

    async def turn_interrupt(self, thread_id: str, turn_id: str) -> None:
        self.interrupts.append((thread_id, turn_id))


def test_snapshot_pending_lists_items_with_ages() -> None:
    wd = mod._OrphanWatchdog(timeout_seconds=300.0)
    wd.record_start("item_1", "commandExecution", command_summary="pnpm test")
    wd.record_start("item_2", "commandExecution", command_summary="pnpm install")

    snap = wd.snapshot_pending()

    ids = {s[0] for s in snap}
    tools = {s[1] for s in snap}
    assert ids == {"item_1", "item_2"}
    assert tools == {"commandExecution"}
    for _, _, age in snap:
        assert age >= 0.0


def test_snapshot_pending_empty_when_all_completed() -> None:
    wd = mod._OrphanWatchdog(timeout_seconds=300.0)
    wd.record_start("item_1", "todo_list")
    wd.record_complete("item_1")

    assert wd.snapshot_pending() == []


def test_record_start_logs_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    wd = mod._OrphanWatchdog(timeout_seconds=300.0)
    with caplog.at_level(logging.DEBUG, logger="agent_team_v15.codex_appserver"):
        wd.record_start("item_1", "todo_list")

    records = [r for r in caplog.records if "ORPHAN-WATCHDOG" in r.getMessage()]
    assert any("record_start" in r.getMessage() for r in records)
    assert any("item_1" in r.getMessage() for r in records)
    assert any("todo_list" in r.getMessage() for r in records)


def test_record_complete_logs_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    wd = mod._OrphanWatchdog(timeout_seconds=300.0)
    wd.record_start("item_1", "todo_list")
    with caplog.at_level(logging.DEBUG, logger="agent_team_v15.codex_appserver"):
        wd.record_complete("item_1")

    records = [r for r in caplog.records if "ORPHAN-WATCHDOG" in r.getMessage()]
    assert any("record_complete" in r.getMessage() for r in records)


@pytest.mark.asyncio
async def test_monitor_emits_startup_log(caplog: pytest.LogCaptureFixture) -> None:
    """Transport monitor must emit an INFO startup line so the run.log can
    prove the monitor is running (distinguishing "never started" from
    "started but quiet")."""
    wd = mod._OrphanWatchdog(timeout_seconds=300.0)
    client = _FakeClient()

    with caplog.at_level(logging.INFO, logger="agent_team_v15.codex_appserver"):
        task = asyncio.create_task(
            mod._monitor_orphans(
                client,
                "thr_x",
                "turn_x",
                wd,
                check_interval_seconds=0.05,
            )
        )
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises((asyncio.CancelledError, BaseException)):
            await task

    messages = [r.getMessage() for r in caplog.records]
    assert any("[ORPHAN-MONITOR] started" in m and "thr_x" in m and "turn_x" in m for m in messages)
    assert any("[ORPHAN-MONITOR] exited" in m for m in messages) or \
           any("[ORPHAN-MONITOR] cancelled" in m for m in messages)


@pytest.mark.asyncio
async def test_monitor_logs_pending_snapshot_on_orphan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When orphan fires, the WARNING must include the pending list so we
    can see every item in-flight at wedge time (not just the single oldest)."""
    wd = mod._OrphanWatchdog(timeout_seconds=0.01)
    wd.record_start("item_1", "commandExecution", command_summary="pnpm test")
    wd.record_start("item_2", "commandExecution", command_summary="pnpm install")
    # Force age past the 0.01s timeout.
    await asyncio.sleep(0.05)

    client = _FakeClient()

    with caplog.at_level(logging.WARNING, logger="agent_team_v15.codex_appserver"):
        task = asyncio.create_task(
            mod._monitor_orphans(
                client,
                "thr_y",
                "turn_y",
                wd,
                check_interval_seconds=0.01,
            )
        )
        result = await asyncio.wait_for(task, timeout=1.0)
    assert result is True

    warn_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    orphan_lines = [m for m in warn_messages if "Orphan tool detected" in m]
    assert orphan_lines, f"expected orphan detected line; got {warn_messages}"
    combined = " | ".join(orphan_lines)
    # Either item could be the "oldest" to fire first; both must appear in
    # the snapshot.
    assert "item_1" in combined
    assert "item_2" in combined
    # Interrupt must have been sent.
    assert client.interrupts == [("thr_y", "turn_y")]


@pytest.mark.asyncio
async def test_monitor_emits_periodic_snapshot_when_no_orphan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When check_orphans returns no-orphan, every N=5 polls the monitor
    should still emit an INFO snapshot so prolonged quiet periods remain
    visible in the log."""
    wd = mod._OrphanWatchdog(timeout_seconds=300.0)  # Far above any real age.
    wd.record_start("item_1", "commandExecution", command_summary="pnpm install")

    client = _FakeClient()

    with caplog.at_level(logging.INFO, logger="agent_team_v15.codex_appserver"):
        task = asyncio.create_task(
            mod._monitor_orphans(
                client,
                "thr_z",
                "turn_z",
                wd,
                check_interval_seconds=0.01,
            )
        )
        # Let the monitor run through at least 6 polls → snapshot fires at
        # poll=5.
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises((asyncio.CancelledError, BaseException)):
            await task

    messages = [r.getMessage() for r in caplog.records]
    snapshot_lines = [m for m in messages if "[ORPHAN-MONITOR] poll=" in m]
    assert snapshot_lines, f"expected a periodic snapshot; got {messages}"
    assert any("item_1" in m for m in snapshot_lines)
    assert any("commandExecution" in m for m in snapshot_lines)
    # No orphan should have been raised because timeout is 300s.
    assert client.interrupts == []
