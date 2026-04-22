"""Tests for Codex app-server server-to-client JSON-RPC request handling.

Context
-------
The Codex app-server can send JSON-RPC requests (not notifications) to the
client — specifically ``applyPatchApproval`` and ``execCommandApproval`` —
expecting a reply of ``{"decision": "allow" | "deny"}``. See
``docs/codex_mcp_interface.md`` in the OpenAI codex repo for the protocol.

Pre-fix the transport treated every message with a ``method`` field as a
notification and never replied, which made the app-server wait indefinitely
for the decision. This surfaced in R1B1-post-remediation as a Wave B
``todo_list`` wedge — the orphan-tool watchdog fired after 600s and Wave B
fell back to Claude (see ``.smoke-logs/run.log`` lines 321-331 of the
preserved run for the empirical repro).

These tests cover the four paths of the fix:

1. ``applyPatchApproval`` request → transport replies with
   ``{"decision": "allow"}``.
2. ``execCommandApproval`` request → transport replies with
   ``{"decision": "allow"}``.
3. An unknown server-initiated method → transport replies with JSON-RPC
   ``-32601 Method not found``.
4. A true notification (``method`` field, no ``id``) still reaches
   ``next_notification()`` instead of being silently dropped.
"""
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
    """Mock subprocess whose stdout can be fed server messages on demand."""

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


def _ignore_requests(_request: dict[str, Any]) -> list:
    return []


async def _wait_for_stdin_write(
    mock_proc: _MockProcess,
    *,
    min_writes: int,
    timeout: float = 2.0,
) -> None:
    """Poll until at least ``min_writes`` lines have been written to stdin."""
    deadline = asyncio.get_running_loop().time() + timeout
    while len(mock_proc.stdin.writes) < min_writes:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(
                f"timeout waiting for {min_writes} stdin writes; "
                f"got {len(mock_proc.stdin.writes)}"
            )
        await asyncio.sleep(0.01)


async def _start_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    on_request,
):
    from agent_team_v15 import codex_appserver as mod

    mock_proc = _MockProcess(on_request)

    async def _spawn(*, cwd: str, env: dict[str, str]):
        return mock_proc

    monkeypatch.setattr(mod, "_spawn_appserver_process", _spawn)

    transport = mod._CodexJSONRPCTransport(
        cwd=str(tmp_path),
        codex_home=tmp_path / "codex-home",
    )
    await transport.start()
    return transport, mock_proc


@pytest.mark.asyncio
async def test_transport_auto_approves_apply_patch_approval_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Server sends applyPatchApproval → transport replies {decision: allow}."""
    transport, mock_proc = await _start_transport(monkeypatch, tmp_path, _ignore_requests)

    try:
        mock_proc.feed_stdout({
            "jsonrpc": "2.0",
            "id": 42,
            "method": "applyPatchApproval",
            "params": {
                "conversationId": "conv_1",
                "callId": "call_1",
                "fileChanges": [{"path": "foo.txt", "kind": "add"}],
                "reason": "sensitive file write",
            },
        })

        await _wait_for_stdin_write(mock_proc, min_writes=1)

        reply = json.loads(mock_proc.stdin.writes[0].decode("utf-8"))
        assert reply["jsonrpc"] == "2.0"
        assert reply["id"] == 42
        assert reply["result"] == {"decision": "allow"}
        assert "error" not in reply
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_transport_auto_approves_exec_command_approval_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Server sends execCommandApproval → transport replies {decision: allow}."""
    transport, mock_proc = await _start_transport(monkeypatch, tmp_path, _ignore_requests)

    try:
        mock_proc.feed_stdout({
            "jsonrpc": "2.0",
            "id": 99,
            "method": "execCommandApproval",
            "params": {
                "conversationId": "conv_1",
                "callId": "call_2",
                "approvalId": "approval_xyz",
                "command": "rm -rf /tmp/not-real",
                "cwd": str(tmp_path),
                "reason": "destructive",
            },
        })

        await _wait_for_stdin_write(mock_proc, min_writes=1)

        reply = json.loads(mock_proc.stdin.writes[0].decode("utf-8"))
        assert reply["jsonrpc"] == "2.0"
        assert reply["id"] == 99
        assert reply["result"] == {"decision": "allow"}
        assert "error" not in reply
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_transport_rejects_unknown_server_request_with_method_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unknown server-to-client method → JSON-RPC -32601 Method not found."""
    transport, mock_proc = await _start_transport(monkeypatch, tmp_path, _ignore_requests)

    try:
        mock_proc.feed_stdout({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "someUnknownElicitation",
            "params": {"unexpected": True},
        })

        await _wait_for_stdin_write(mock_proc, min_writes=1)

        reply = json.loads(mock_proc.stdin.writes[0].decode("utf-8"))
        assert reply["jsonrpc"] == "2.0"
        assert reply["id"] == 7
        assert "result" not in reply
        assert reply["error"]["code"] == -32601
        assert "someUnknownElicitation" in reply["error"]["message"]
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_transport_notification_without_id_still_queued(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A true notification (method, no id) must reach next_notification()
    and must NOT provoke a response on stdin."""
    transport, mock_proc = await _start_transport(monkeypatch, tmp_path, _ignore_requests)

    try:
        mock_proc.feed_stdout({
            "jsonrpc": "2.0",
            "method": "turn/plan/updated",
            "params": {
                "turnId": "turn_42",
                "plan": [{"step": "s1", "status": "completed"}],
            },
        })

        notif = await asyncio.wait_for(transport.next_notification(), timeout=2.0)
        assert notif["method"] == "turn/plan/updated"
        assert notif["params"]["turnId"] == "turn_42"

        # Give the loop a tick; the transport MUST NOT have written any
        # response for a notification (it has no id to respond to).
        await asyncio.sleep(0.05)
        assert mock_proc.stdin.writes == []
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_transport_handles_request_and_notification_interleaved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Interleaved approval-request + notification stream: the request gets a
    response, the notification reaches the queue, and a later
    ``send_request`` still correlates to its response."""
    from agent_team_v15 import codex_appserver as mod

    def _on_request(request: dict[str, Any]) -> list:
        # Only respond to client-initiated probe; ignore auto-approval replies.
        if request.get("method") == "probe":
            return [{"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}}]
        return []

    transport, mock_proc = await _start_transport(monkeypatch, tmp_path, _on_request)

    try:
        # Server pushes approval request + notification ahead of the client.
        mock_proc.feed_stdout({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "applyPatchApproval",
            "params": {
                "conversationId": "conv_x",
                "callId": "call_z",
                "fileChanges": [],
            },
        })
        mock_proc.feed_stdout({
            "jsonrpc": "2.0",
            "method": "turn/diff/updated",
            "params": {"turnId": "t_x", "diff": "--- a\n+++ b\n"},
        })

        # Client-initiated probe — must still round-trip.
        probe_result = await asyncio.wait_for(
            transport.send_request("probe", {"hello": True}),
            timeout=2.0,
        )
        assert probe_result == {"ok": True}

        # Notification made it to the queue.
        notif = await asyncio.wait_for(transport.next_notification(), timeout=2.0)
        assert notif["method"] == "turn/diff/updated"

        # Exactly two writes on stdin: the auto-approve reply AND the probe
        # request (order: server-request reply first, then client request).
        await _wait_for_stdin_write(mock_proc, min_writes=2)
        payloads = [json.loads(w.decode("utf-8")) for w in mock_proc.stdin.writes]
        by_id = {p["id"]: p for p in payloads}
        assert by_id[5]["result"] == {"decision": "allow"}
        assert by_id[5].get("error") is None
        probe_req = next(p for p in payloads if p.get("method") == "probe")
        assert probe_req["params"] == {"hello": True}
    finally:
        await transport.close()
