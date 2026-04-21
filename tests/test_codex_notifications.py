"""Tests for Codex notification parsing + watchdog storage (Phase 0, Task 0.2)."""

from __future__ import annotations

import pytest

from agent_team_v15.codex_appserver import (
    CodexNotificationEvent,
    _OrphanWatchdog,
    _TokenAccumulator,
    _process_streaming_event,
    parse_codex_notification,
)


def test_parse_turn_plan_updated() -> None:
    raw = {
        "method": "turn/plan/updated",
        "params": {
            "turnId": "turn_123",
            "explanation": "Refactor plan",
            "plan": [
                {"step": "analyze", "status": "completed"},
                {"step": "implement", "status": "inProgress"},
            ],
        },
    }
    event = parse_codex_notification(raw)
    assert event is not None
    assert isinstance(event, CodexNotificationEvent)
    assert event.event_type == "turn/plan/updated"
    assert event.turn_id == "turn_123"
    assert event.payload["plan"][0]["status"] == "completed"


def test_parse_turn_diff_updated() -> None:
    raw = {
        "method": "turn/diff/updated",
        "params": {
            "threadId": "thread_abc",
            "turnId": "turn_123",
            "diff": "--- a/x\n+++ b/x\n@@\n-old\n+new",
        },
    }
    event = parse_codex_notification(raw)
    assert event is not None
    assert event.event_type == "turn/diff/updated"
    assert event.thread_id == "thread_abc"
    assert event.turn_id == "turn_123"
    assert "new" in event.payload["diff"]


def test_parse_unknown_notification_returns_none() -> None:
    assert parse_codex_notification({"method": "item/started", "params": {}}) is None
    assert parse_codex_notification({}) is None
    assert parse_codex_notification({"method": "turn/plan/updated"}) is None  # missing params


def test_process_streaming_event_stores_plan_on_watchdog() -> None:
    watchdog = _OrphanWatchdog()
    tokens = _TokenAccumulator()
    event = {
        "method": "turn/plan/updated",
        "params": {
            "turnId": "turn_123",
            "plan": [{"step": "analyze", "status": "completed"}],
        },
    }

    _process_streaming_event(event, watchdog, tokens, progress_callback=None)

    assert watchdog.codex_last_plan == [{"step": "analyze", "status": "completed"}]


def test_process_streaming_event_stores_diff_on_watchdog() -> None:
    watchdog = _OrphanWatchdog()
    tokens = _TokenAccumulator()
    event = {
        "method": "turn/diff/updated",
        "params": {
            "threadId": "thread_abc",
            "turnId": "turn_123",
            "diff": "--- a/x\n+++ b/x\n",
        },
    }

    _process_streaming_event(event, watchdog, tokens, progress_callback=None)

    assert watchdog.codex_latest_diff == "--- a/x\n+++ b/x\n"


def test_orphan_watchdog_defaults_have_plan_and_diff_fields() -> None:
    watchdog = _OrphanWatchdog()
    assert watchdog.codex_last_plan == []
    assert watchdog.codex_latest_diff == ""
