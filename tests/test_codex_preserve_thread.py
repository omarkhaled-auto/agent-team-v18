"""Tests for preserving Codex app-server threads across calls."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest

from agent_team_v15.codex_appserver import _execute_once, execute_codex
from agent_team_v15.codex_transport import CodexConfig


class _FakeCodexAppServerClient:
    last_instance: "_FakeCodexAppServerClient | None" = None

    def __init__(self, **_: Any) -> None:
        self.archive_called = False
        self.close_called = False
        self.returncode = 0
        self.thread_id = "thr_preserve"
        self.turn_id = "turn_preserve"
        _FakeCodexAppServerClient.last_instance = self

    async def start(self) -> None:
        return None

    async def initialize(self) -> dict[str, Any]:
        return {"userAgent": "fake/0.0", "codexHome": ""}

    async def thread_start(self) -> dict[str, Any]:
        return {"thread": {"id": self.thread_id}, "cwd": ""}

    async def turn_start(self, thread_id: str, prompt: str) -> dict[str, Any]:
        assert thread_id == self.thread_id
        assert prompt
        return {"turn": {"id": self.turn_id}}

    async def next_notification(self) -> dict[str, Any]:
        return {
            "method": "turn/completed",
            "params": {
                "threadId": self.thread_id,
                "turn": {"id": self.turn_id, "status": "completed"},
            },
        }

    async def thread_archive(self, thread_id: str) -> dict[str, Any]:
        assert thread_id == self.thread_id
        self.archive_called = True
        return {}

    async def close(self) -> None:
        self.close_called = True


def test_execute_once_accepts_preserve_thread_param() -> None:
    sig = inspect.signature(_execute_once)
    assert "preserve_thread" in sig.parameters
    param = sig.parameters["preserve_thread"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is False


def test_execute_codex_accepts_preserve_thread_param() -> None:
    sig = inspect.signature(execute_codex)
    assert "preserve_thread" in sig.parameters
    param = sig.parameters["preserve_thread"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is False


def test_preserve_thread_false_calls_archive(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from agent_team_v15 import codex_appserver as mod

    _FakeCodexAppServerClient.last_instance = None
    monkeypatch.setattr(mod, "_CodexAppServerClient", _FakeCodexAppServerClient)

    result = asyncio.run(
        mod._execute_once(
            "finish",
            str(tmp_path),
            CodexConfig(),
            tmp_path,
            preserve_thread=False,
        )
    )

    client = _FakeCodexAppServerClient.last_instance
    assert client is not None
    assert result.success is True
    assert result.thread_id == "thr_preserve"
    assert client.archive_called is True
    assert client.close_called is True


def test_preserve_thread_true_skips_archive(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from agent_team_v15 import codex_appserver as mod

    _FakeCodexAppServerClient.last_instance = None
    monkeypatch.setattr(mod, "_CodexAppServerClient", _FakeCodexAppServerClient)

    result = asyncio.run(
        mod._execute_once(
            "finish",
            str(tmp_path),
            CodexConfig(),
            tmp_path,
            preserve_thread=True,
        )
    )

    client = _FakeCodexAppServerClient.last_instance
    assert client is not None
    assert result.success is True
    assert result.thread_id == "thr_preserve"
    assert client.archive_called is False
    assert client.close_called is True
