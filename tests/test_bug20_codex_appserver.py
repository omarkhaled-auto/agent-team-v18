"""Protocol-focused tests for Bug #20: Codex app-server transport."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest


class _MockStdin:
    def __init__(self, owner: "_MockProcess") -> None:
        self._owner = owner
        self.writes: list[bytes] = []
        self._closed = False

    def write(self, data: bytes) -> None:
        chunk = bytes(data)
        self.writes.append(chunk)
        self._owner.consume_stdin(chunk)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self._closed = True
        self._owner.finish(0)

    async def wait_closed(self) -> None:
        return None


class _MockProcess:
    def __init__(self, on_request) -> None:
        self.on_request = on_request
        self.stdin = _MockStdin(self)
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode: int | None = None
        self.pid = 4242
        self.requests: list[dict[str, Any]] = []
        self._stdin_buffer = bytearray()
        self._waiter = asyncio.get_running_loop().create_future()

    def consume_stdin(self, data: bytes) -> None:
        self._stdin_buffer.extend(data)
        while b"\n" in self._stdin_buffer:
            line, _, remainder = self._stdin_buffer.partition(b"\n")
            self._stdin_buffer = bytearray(remainder)
            if not line.strip():
                continue
            request = json.loads(line.decode("utf-8"))
            self.requests.append(request)
            responses = self.on_request(request)
            if responses is None:
                continue
            if not isinstance(responses, list):
                responses = [responses]
            for response in responses:
                if isinstance(response, tuple) and response[0] == "stderr":
                    self.feed_stderr(response[1])
                    continue
                if isinstance(response, tuple) and response[0] == "finish":
                    self.finish(response[1])
                    continue
                self.feed_stdout(response)

    def feed_stdout(self, message: dict[str, Any] | bytes) -> None:
        if isinstance(message, bytes):
            payload = message
        else:
            payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        self.stdout.feed_data(payload)

    def feed_stderr(self, text: str) -> None:
        payload = text if text.endswith("\n") else text + "\n"
        self.stderr.feed_data(payload.encode("utf-8"))

    def finish(self, returncode: int) -> None:
        if self.returncode is not None:
            return
        self.returncode = returncode
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        if not self._waiter.done():
            self._waiter.set_result(returncode)

    async def wait(self) -> int:
        return await self._waiter

    def kill(self) -> None:
        self.finish(-9)

    def terminate(self) -> None:
        self.finish(-15)


def _exact_request_bytes(request_id: int, method: str, params: dict[str, Any]) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        },
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


@pytest.mark.asyncio
async def test_transport_serializes_newline_delimited_jsonrpc(monkeypatch, tmp_path: Path) -> None:
    from agent_team_v15 import codex_appserver as mod

    mock_proc = _MockProcess(
        lambda request: {"id": request["id"], "result": {"ok": True}}
    )

    async def _spawn(*, cwd: str, env: dict[str, str]):
        assert cwd == str(tmp_path)
        assert env["CODEX_HOME"] == str(tmp_path / "codex-home")
        return mock_proc

    monkeypatch.setattr(mod, "_spawn_appserver_process", _spawn)

    transport = mod._CodexJSONRPCTransport(cwd=str(tmp_path), codex_home=tmp_path / "codex-home")
    await transport.start()
    result = await transport.send_request("initialize", {"clientInfo": {"name": "probe"}, "capabilities": {}})
    await transport.close()

    assert result == {"ok": True}
    assert mock_proc.stdin.writes[0] == _exact_request_bytes(
        1,
        "initialize",
        {"clientInfo": {"name": "probe"}, "capabilities": {}},
    )


@pytest.mark.asyncio
async def test_transport_raises_jsonrpc_error_response(monkeypatch, tmp_path: Path) -> None:
    from agent_team_v15 import codex_appserver as mod

    mock_proc = _MockProcess(
        lambda request: {
            "id": request["id"],
            "error": {
                "code": -32600,
                "message": "Invalid request: missing field `threadId`",
            },
        }
    )

    async def _spawn(*, cwd: str, env: dict[str, str]):
        del cwd, env
        return mock_proc

    monkeypatch.setattr(mod, "_spawn_appserver_process", _spawn)

    transport = mod._CodexJSONRPCTransport(cwd=str(tmp_path), codex_home=tmp_path)
    await transport.start()
    with pytest.raises(mod._CodexAppServerRequestError) as exc_info:
        await transport.send_request("thread/archive", {})
    await transport.close()

    assert exc_info.value.code == -32600
    assert "missing field `threadId`" in str(exc_info.value)


@pytest.mark.asyncio
async def test_transport_surfaces_subprocess_death_mid_request(monkeypatch, tmp_path: Path) -> None:
    from agent_team_v15 import codex_appserver as mod

    mock_proc = _MockProcess(lambda request: None)

    async def _spawn(*, cwd: str, env: dict[str, str]):
        del cwd, env
        return mock_proc

    monkeypatch.setattr(mod, "_spawn_appserver_process", _spawn)

    transport = mod._CodexJSONRPCTransport(cwd=str(tmp_path), codex_home=tmp_path)
    await transport.start()

    pending = asyncio.create_task(transport.send_request("thread/start", {}))
    await asyncio.sleep(0)
    mock_proc.feed_stderr("app-server crashed")
    mock_proc.finish(23)

    with pytest.raises(mod._CodexAppServerError) as exc_info:
        await pending
    await transport.close()

    message = str(exc_info.value)
    assert "closed before completing the request" in message
    assert "exit=23" in message


@pytest.mark.asyncio
async def test_client_inherits_auth_from_environment_without_rpc_handshake(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    captured: dict[str, Any] = {}
    mock_proc = _MockProcess(
        lambda request: {
            "id": request["id"],
            "result": {
                "userAgent": "probe/0.121.0",
                "codexHome": str(tmp_path / "codex-home"),
                "platformFamily": "windows",
                "platformOs": "windows",
            },
        }
    )

    async def _spawn(*, cwd: str, env: dict[str, str]):
        captured["cwd"] = cwd
        captured["env"] = dict(env)
        return mock_proc

    monkeypatch.setattr(mod, "_spawn_appserver_process", _spawn)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    client = mod._CodexAppServerClient(
        cwd=str(tmp_path),
        config=mod.CodexConfig(),
        codex_home=tmp_path / "codex-home",
    )
    await client.start()
    init_result = await client.initialize()
    await client.close()

    initialize_request = mock_proc.requests[0]
    assert captured["env"]["CODEX_HOME"] == str(tmp_path / "codex-home")
    assert captured["env"]["OPENAI_API_KEY"] == "sk-test"
    assert set(initialize_request["params"]) == {"clientInfo", "capabilities"}
    assert init_result["codexHome"] == str(tmp_path / "codex-home")


@pytest.mark.asyncio
async def test_execute_codex_handles_real_protocol_shapes(monkeypatch, tmp_path: Path) -> None:
    from agent_team_v15 import codex_appserver as mod

    def _on_request(request: dict[str, Any]) -> list[dict[str, Any] | tuple[str, Any]]:
        method = request["method"]
        request_id = request["id"]
        if method == "initialize":
            return [
                {
                    "id": request_id,
                    "result": {
                        "userAgent": "probe/0.121.0",
                        "codexHome": str(tmp_path),
                        "platformFamily": "windows",
                        "platformOs": "windows",
                    },
                }
            ]
        if method == "thread/start":
            return [
                {
                    "id": request_id,
                    "result": {
                        "thread": {"id": "thr_1"},
                        "model": "gpt-5.4",
                        "modelProvider": "openai",
                        "cwd": str(tmp_path),
                        "approvalPolicy": "never",
                        "approvalsReviewer": "user",
                        "sandbox": {"type": "workspaceWrite"},
                    },
                }
            ]
        if method == "turn/start":
            return [
                {"method": "thread/started", "params": {"thread": {"id": "thr_1"}}},
                {
                    "id": request_id,
                    "result": {
                        "turn": {
                            "id": "turn_1",
                            "items": [],
                            "status": "inProgress",
                            "error": None,
                            "startedAt": None,
                            "completedAt": None,
                            "durationMs": None,
                        }
                    },
                },
                {
                    "method": "turn/started",
                    "params": {
                        "threadId": "thr_1",
                        "turn": {"id": "turn_1", "items": [], "status": "inProgress"},
                    },
                },
                {
                    "method": "item/started",
                    "params": {
                        "item": {
                            "type": "agentMessage",
                            "id": "msg_1",
                            "text": "",
                            "phase": "final_answer",
                        },
                        "threadId": "thr_1",
                        "turnId": "turn_1",
                    },
                },
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "thr_1",
                        "turnId": "turn_1",
                        "itemId": "msg_1",
                        "delta": "OK",
                    },
                },
                {
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "type": "agentMessage",
                            "id": "msg_1",
                            "text": "OK",
                            "phase": "final_answer",
                        },
                        "threadId": "thr_1",
                        "turnId": "turn_1",
                    },
                },
                {
                    "method": "thread/tokenUsage/updated",
                    "params": {
                        "threadId": "thr_1",
                        "turnId": "turn_1",
                        "tokenUsage": {
                            "total": {
                                "totalTokens": 106,
                                "inputTokens": 100,
                                "cachedInputTokens": 20,
                                "outputTokens": 5,
                                "reasoningOutputTokens": 1,
                            },
                            "last": {
                                "totalTokens": 106,
                                "inputTokens": 100,
                                "cachedInputTokens": 20,
                                "outputTokens": 5,
                                "reasoningOutputTokens": 1,
                            },
                            "modelContextWindow": 258400,
                        },
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thr_1",
                        "turn": {
                            "id": "turn_1",
                            "items": [],
                            "status": "completed",
                            "error": None,
                            "startedAt": 1,
                            "completedAt": 2,
                            "durationMs": 1000,
                        },
                    },
                },
            ]
        if method == "thread/archive":
            return [
                {
                    "method": "thread/status/changed",
                    "params": {"threadId": "thr_1", "status": {"type": "notLoaded"}},
                },
                {"id": request_id, "result": {}},
                ("finish", 0),
            ]
        raise AssertionError(f"Unexpected method: {method}")

    mock_proc = _MockProcess(_on_request)

    async def _spawn(*, cwd: str, env: dict[str, str]):
        assert cwd == str(tmp_path)
        assert env["CODEX_HOME"] == str(tmp_path)
        return mock_proc

    progress_events: list[tuple[str, str, str]] = []

    def _progress_callback(*, message_type: str = "", tool_name: str = "", event_kind: str = "", **_: object) -> None:
        progress_events.append((message_type, tool_name, event_kind))

    monkeypatch.setattr(mod, "_spawn_appserver_process", _spawn)
    monkeypatch.setattr(mod, "log_codex_cli_version", lambda *_a, **_kw: None)

    result = await mod.execute_codex(
        "Reply with exactly OK and nothing else.",
        str(tmp_path),
        mod.CodexConfig(max_retries=0, reasoning_effort="low"),
        tmp_path,
        progress_callback=_progress_callback,
    )

    assert result.success is True
    assert result.final_message == "OK"
    assert result.input_tokens == 100
    assert result.output_tokens == 5
    assert result.reasoning_tokens == 1
    assert result.cached_input_tokens == 20
    assert result.cost_usd == 0.00021
    assert [request["method"] for request in mock_proc.requests] == [
        "initialize",
        "thread/start",
        "turn/start",
        "thread/archive",
    ]
    assert ("item/started", "agentMessage", "start") in progress_events
    assert ("item/completed", "agentMessage", "complete") in progress_events
