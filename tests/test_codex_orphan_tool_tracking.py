"""TDD for codex orphan tool tracking (Bug Wave-B post-completion idle).

Background: build-g-pr2-phaseB-20260414/.agent-team/hang_reports/wave-B-*.json
showed Wave B receiving 4-6 `item.started` events for `command_execution` tools
but only 0-4 matching `item.completed` events before the watchdog fired at 1821s
of idle. The orphan tool starts (likely npm install / prisma generate / docker
build subprocesses that wedge without flushing stdout) are the structural cause
of Wave B burning the entire wave budget on no useful work.

This test suite drives the diagnostic improvement: the codex transport layer
must extract `tool_id` and event kind (start/complete) from JSONL events; the
wave watchdog state must track pending tool starts; the hang report must
include the pending tools so post-mortems can name the wedged shell.

No behavior change to the watchdog firing time — that's a follow-up (opt-in
fail-fast). This PR ships diagnostics only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15 import codex_transport, wave_executor


# ---------------------------------------------------------------------------
# codex_transport._progress_from_event — extract tool_id and kind
# ---------------------------------------------------------------------------

class TestProgressFromEvent:
    def test_item_started_extracts_tool_id_and_kind(self) -> None:
        event = {
            "type": "item.started",
            "item": {"id": "tool_abc", "type": "command_execution", "name": "shell"},
        }
        message_type, tool_name, tool_id, kind = codex_transport._progress_from_event(event)
        assert message_type == "item.started"
        assert tool_id == "tool_abc"
        assert kind == "start"
        # tool_name should still be derived (existing behavior preserved)
        assert tool_name in {"shell", "command_execution"}

    def test_item_completed_extracts_tool_id_and_kind(self) -> None:
        event = {
            "type": "item.completed",
            "item": {"id": "tool_abc", "type": "command_execution"},
        }
        message_type, tool_name, tool_id, kind = codex_transport._progress_from_event(event)
        assert message_type == "item.completed"
        assert tool_id == "tool_abc"
        assert kind == "complete"

    def test_other_event_returns_empty_tool_id_and_other_kind(self) -> None:
        event = {"type": "thread.started"}
        message_type, tool_name, tool_id, kind = codex_transport._progress_from_event(event)
        assert message_type == "thread.started"
        assert tool_id == ""
        assert kind == "other"

    def test_event_without_item_id_returns_empty_tool_id(self) -> None:
        event = {"type": "item.started", "item": {"type": "shell"}}
        _, _, tool_id, kind = codex_transport._progress_from_event(event)
        assert tool_id == ""
        assert kind == "start"


# ---------------------------------------------------------------------------
# _WaveWatchdogState — track pending tool starts
# ---------------------------------------------------------------------------

class TestWaveWatchdogPendingTools:
    def test_record_progress_adds_pending_on_start(self) -> None:
        state = wave_executor._WaveWatchdogState()
        state.record_progress(
            message_type="item.started",
            tool_name="commandExecution",
            tool_id="tool_1",
            event_kind="start",
        )
        assert "tool_1" in state.pending_tool_starts
        assert state.pending_tool_starts["tool_1"]["tool_name"] == "commandExecution"

    def test_record_progress_resolves_pending_on_complete(self) -> None:
        state = wave_executor._WaveWatchdogState()
        state.record_progress(
            message_type="item.started", tool_name="commandExecution",
            tool_id="tool_1", event_kind="start",
        )
        assert "tool_1" in state.pending_tool_starts
        state.record_progress(
            message_type="item.completed", tool_name="commandExecution",
            tool_id="tool_1", event_kind="complete",
        )
        assert "tool_1" not in state.pending_tool_starts

    def test_record_progress_orphan_count_for_partial_completion(self) -> None:
        state = wave_executor._WaveWatchdogState()
        for tid in ("t1", "t2", "t3"):
            state.record_progress(
                message_type="item.started", tool_name="commandExecution",
                tool_id=tid, event_kind="start",
            )
        state.record_progress(
            message_type="item.completed", tool_name="commandExecution",
            tool_id="t1", event_kind="complete",
        )
        assert set(state.pending_tool_starts.keys()) == {"t2", "t3"}

    def test_record_progress_without_tool_id_is_backward_compatible(self) -> None:
        """Existing claude-only callers don't pass tool_id — must still work."""
        state = wave_executor._WaveWatchdogState()
        state.record_progress(message_type="assistant_message", tool_name="")
        assert state.last_message_type == "assistant_message"
        assert state.pending_tool_starts == {}


# ---------------------------------------------------------------------------
# Hang report includes pending tool starts
# ---------------------------------------------------------------------------

class TestHangReportPendingTools:
    def test_hang_report_includes_pending_tool_starts(self, tmp_path: Path) -> None:
        state = wave_executor._WaveWatchdogState()
        state.record_progress(
            message_type="item.started", tool_name="commandExecution",
            tool_id="tool_npm_install", event_kind="start",
        )
        state.record_progress(
            message_type="item.started", tool_name="commandExecution",
            tool_id="tool_prisma", event_kind="start",
        )
        state.record_progress(
            message_type="item.completed", tool_name="commandExecution",
            tool_id="tool_npm_install", event_kind="complete",
        )

        timeout = wave_executor.WaveWatchdogTimeoutError(
            wave="B", state=state, timeout_seconds=1800,
        )
        path_str = wave_executor._write_hang_report(
            cwd=str(tmp_path), milestone_id="m1", wave="B", timeout=timeout,
        )
        report = json.loads(Path(path_str).read_text(encoding="utf-8"))

        assert "pending_tool_starts" in report
        pending = report["pending_tool_starts"]
        assert isinstance(pending, list)
        assert len(pending) == 1
        assert pending[0]["tool_id"] == "tool_prisma"
        assert pending[0]["tool_name"] == "commandExecution"
        assert "started_at" in pending[0]

    def test_hang_report_includes_empty_pending_list_when_no_orphans(
        self, tmp_path: Path
    ) -> None:
        state = wave_executor._WaveWatchdogState()
        state.record_progress(message_type="assistant_message", tool_name="")
        timeout = wave_executor.WaveWatchdogTimeoutError(
            wave="A", state=state, timeout_seconds=1800,
        )
        path_str = wave_executor._write_hang_report(
            cwd=str(tmp_path), milestone_id="m1", wave="A", timeout=timeout,
        )
        report = json.loads(Path(path_str).read_text(encoding="utf-8"))
        assert report.get("pending_tool_starts") == []


# ---------------------------------------------------------------------------
# Smoke: _drain_stream forwards tool_id through _emit_progress
# ---------------------------------------------------------------------------

class TestDrainStreamForwardsToolId:
    @pytest.mark.asyncio
    async def test_drain_stream_calls_callback_with_tool_id_and_kind(self) -> None:
        import asyncio

        captured: list[dict[str, str]] = []

        async def progress_callback(**kwargs: object) -> None:
            captured.append({k: str(v) for k, v in kwargs.items()})

        events = [
            b'{"type":"item.started","item":{"id":"t1","type":"command_execution"}}\n',
            b'{"type":"item.completed","item":{"id":"t1","type":"command_execution"}}\n',
        ]
        reader = asyncio.StreamReader()
        for ev in events:
            reader.feed_data(ev)
        reader.feed_eof()

        chunks: list[str] = []
        await codex_transport._drain_stream(
            reader, chunks, progress_callback=progress_callback,
        )

        assert len(captured) == 2
        assert captured[0]["message_type"] == "item.started"
        assert captured[0]["tool_id"] == "t1"
        assert captured[0]["event_kind"] == "start"
        assert captured[1]["event_kind"] == "complete"
