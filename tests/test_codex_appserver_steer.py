"""Tests for _CodexAppServerClient.turn_steer (Phase 0, Task 0.1)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent_team_v15.codex_appserver import _CodexAppServerClient
from agent_team_v15.codex_transport import CodexConfig


def test_client_exposes_turn_steer_method() -> None:
    assert hasattr(_CodexAppServerClient, "turn_steer"), (
        "_CodexAppServerClient must expose turn_steer() for Phase 0"
    )
    assert callable(getattr(_CodexAppServerClient, "turn_steer"))


def test_turn_steer_sends_correct_jsonrpc_payload(tmp_path) -> None:
    client = _CodexAppServerClient(
        cwd=str(tmp_path),
        config=CodexConfig(),
        codex_home=tmp_path,
    )

    captured: dict[str, Any] = {}

    async def fake_send_request(method: str, params: dict[str, Any]) -> dict[str, Any]:
        captured["method"] = method
        captured["params"] = params
        return {}

    client.send_request = fake_send_request  # type: ignore[assignment]

    asyncio.run(client.turn_steer("thread_abc", "turn_xyz", "Keep it brief"))

    assert captured["method"] == "turn/steer"
    assert captured["params"]["threadId"] == "thread_abc"
    assert captured["params"]["expectedTurnId"] == "turn_xyz"
    assert captured["params"]["input"] == [{"type": "text", "text": "Keep it brief"}]


def test_turn_steer_is_fail_open_on_transport_error(tmp_path) -> None:
    client = _CodexAppServerClient(
        cwd=str(tmp_path),
        config=CodexConfig(),
        codex_home=tmp_path,
    )

    async def boom(method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("transport offline")

    client.send_request = boom  # type: ignore[assignment]

    # Must NOT raise; fail-open is mandatory.
    asyncio.run(client.turn_steer("thread_abc", "turn_xyz", "hi"))
