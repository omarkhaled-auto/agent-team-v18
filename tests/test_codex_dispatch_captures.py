"""Observability captures for provider-routed Codex app-server dispatches."""

from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path
from typing import Any

import pytest


class _MockStdin:
    def __init__(self, owner: "_MockProcess") -> None:
        self._owner = owner
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        chunk = bytes(data)
        self.writes.append(chunk)
        self._owner.consume_stdin(chunk)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
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
            responses = self.on_request(request)
            if not isinstance(responses, list):
                responses = [responses]
            for response in responses:
                if isinstance(response, tuple) and response[0] == "finish":
                    self.finish(response[1])
                    continue
                self.feed_stdout(response)

    def feed_stdout(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        self.stdout.feed_data(payload)

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


class _FakeCheckpoint:
    def __init__(self, file_manifest: dict[str, str] | None = None) -> None:
        self.file_manifest = file_manifest or {}


class _FakeDiff:
    def __init__(
        self,
        *,
        created: list[str] | None = None,
        modified: list[str] | None = None,
        deleted: list[str] | None = None,
    ) -> None:
        self.created = created or []
        self.modified = modified or []
        self.deleted = deleted or []


def _provider_config(capture_enabled: bool) -> Any:
    return types.SimpleNamespace(
        v18=types.SimpleNamespace(codex_capture_enabled=capture_enabled),
        orchestrator=types.SimpleNamespace(model="claude-sonnet-4-6"),
    )


def _capture_paths(root: Path) -> tuple[Path, Path, Path]:
    capture_dir = root / ".agent-team" / "codex-captures"
    return (
        capture_dir / "milestone-1-wave-B-prompt.txt",
        capture_dir / "milestone-1-wave-B-protocol.log",
        capture_dir / "milestone-1-wave-B-response.json",
    )


def _diagnostic_path(root: Path) -> Path:
    return (
        root
        / ".agent-team"
        / "codex-captures"
        / "milestone-1-wave-B-terminal-diagnostic.json"
    )


def _mock_appserver_process(tmp_path: Path) -> _MockProcess:
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
                            "type": "commandExecution",
                            "id": "cmd_1",
                            "command": "pwd",
                            "status": "inProgress",
                        }
                    },
                },
                {
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "type": "commandExecution",
                            "id": "cmd_1",
                            "command": "pwd",
                            "status": "completed",
                            "stdout": str(tmp_path),
                        }
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
                        }
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
                        }
                    },
                },
                {
                    "method": "thread/tokenUsage/updated",
                    "params": {
                        "threadId": "thr_1",
                        "turnId": "turn_1",
                        "tokenUsage": {
                            "total": {
                                "inputTokens": 100,
                                "cachedInputTokens": 20,
                                "outputTokens": 5,
                                "reasoningOutputTokens": 1,
                            }
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

    return _MockProcess(_on_request)


@pytest.mark.asyncio
async def test_provider_routed_codex_dispatch_writes_capture_files(monkeypatch, tmp_path: Path) -> None:
    from agent_team_v15 import codex_appserver as appserver
    from agent_team_v15.codex_prompts import CODEX_WAVE_B_PREAMBLE
    from agent_team_v15.codex_transport import CodexConfig
    from agent_team_v15.provider_router import WaveProviderMap, execute_wave_with_provider

    mock_proc = _mock_appserver_process(tmp_path)

    async def _spawn(*, cwd: str, env: dict[str, str]) -> _MockProcess:
        assert cwd == str(tmp_path)
        assert env["CODEX_HOME"] == str(tmp_path)
        return mock_proc

    monkeypatch.setattr(appserver, "_spawn_appserver_process", _spawn)
    monkeypatch.setattr(appserver, "log_codex_cli_version", lambda *_a, **_kw: None)

    result = await execute_wave_with_provider(
        wave_letter="B",
        prompt="Wire the backend.",
        cwd=str(tmp_path),
        config=_provider_config(capture_enabled=True),
        provider_map=WaveProviderMap(),
        claude_callback=lambda **kw: 0,
        claude_callback_kwargs={
            "milestone": types.SimpleNamespace(id="milestone-1", title="Test"),
        },
        codex_transport_module=appserver,
        codex_config=CodexConfig(max_retries=0, reasoning_effort="low"),
        codex_home=tmp_path,
        checkpoint_create=lambda label, cwd: _FakeCheckpoint(file_manifest={"keep.txt": "hash"}),
        checkpoint_diff=lambda pre, post: _FakeDiff(modified=["keep.txt"]),
    )

    prompt_path, protocol_path, response_path = _capture_paths(tmp_path)

    assert result["provider"] == "codex"
    assert prompt_path.is_file()
    assert protocol_path.is_file()
    assert response_path.is_file()

    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "# Milestone: milestone-1" in prompt_text
    assert "# Wave: B" in prompt_text
    assert "# Model: gpt-5.4" in prompt_text
    assert "# Reasoning-effort: low" in prompt_text
    assert CODEX_WAVE_B_PREAMBLE in prompt_text
    assert "Wire the backend." in prompt_text

    protocol_lines = [line for line in protocol_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(" OUT " in line and '"method":"initialize"' in line for line in protocol_lines)
    assert any(" OUT " in line and '"method":"thread/start"' in line for line in protocol_lines)
    assert any(" IN " in line and '"method":"turn/completed"' in line for line in protocol_lines)

    response_payload = json.loads(response_path.read_text(encoding="utf-8"))
    assert response_payload["metadata"]["milestone_id"] == "milestone-1"
    assert response_payload["metadata"]["wave_letter"] == "B"
    assert response_payload["final_agent_message"] == "OK"
    assert response_payload["cumulative_tool_summary"]["total_tool_calls"] == 1
    assert response_payload["cumulative_tool_summary"]["shell_tool_invocations"] == 1
    assert response_payload["cumulative_tool_summary"]["write_tool_invocations"] == 0
    assert response_payload["tool_calls"][0]["tool_name"] == "commandExecution"


@pytest.mark.asyncio
async def test_eof_before_turn_completed_writes_terminal_diagnostic_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from agent_team_v15 import codex_appserver as appserver
    from agent_team_v15.codex_appserver import CodexTerminalTurnError
    from agent_team_v15.codex_captures import CodexCaptureMetadata
    from agent_team_v15.codex_transport import CodexConfig

    class _FakeClient:
        cwd = str(tmp_path)
        returncode = -15
        process_pid = 9876

        async def start(self) -> None:
            return None

        async def initialize(self) -> dict[str, Any]:
            return {"userAgent": "test", "codexHome": str(tmp_path)}

        async def thread_start(self) -> dict[str, Any]:
            return {"thread": {"id": "thread-target"}}

        async def turn_start(self, thread_id: str, prompt: str) -> dict[str, Any]:
            assert thread_id == "thread-target"
            assert prompt == "Probe prompt."
            return {"turn": {"id": "turn-target"}}

        async def thread_archive(self, thread_id: str) -> dict[str, Any]:
            assert thread_id == "thread-target"
            return {}

        async def close(self) -> None:
            return None

        def stderr_excerpt(self, limit: int = 300) -> str:
            del limit
            return "stderr tail"

    async def _fake_wait_for_turn_completion(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args
        capture_session = kwargs["capture_session"]
        assert capture_session.protocol_logger is not None
        capture_session.protocol_logger.log_in(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "item/commandExecution/outputDelta",
                    "params": {
                        "threadId": "thread-target",
                        "turnId": "turn-target",
                        "itemId": "call-big",
                        "delta": "x" * (300 * 1024),
                    },
                },
                separators=(",", ":"),
            )
        )
        raise CodexTerminalTurnError(
            "app-server stdout EOF — subprocess exited",
            thread_id="thread-target",
            turn_id="turn-target",
        )

    monkeypatch.setattr(appserver, "_CodexAppServerClient", lambda **_kwargs: _FakeClient())
    monkeypatch.setattr(appserver, "_wait_for_turn_completion", _fake_wait_for_turn_completion)
    monkeypatch.setattr(appserver, "log_codex_cli_version", lambda *_a, **_kw: None)

    with pytest.raises(CodexTerminalTurnError):
        await appserver.execute_codex(
            "Probe prompt.",
            str(tmp_path),
            CodexConfig(max_retries=0, reasoning_effort="low"),
            tmp_path,
            capture_enabled=True,
            capture_metadata=CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B"),
            wave_letter="B",
        )

    diagnostic_path = _diagnostic_path(tmp_path)
    assert diagnostic_path.is_file()
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))

    assert diagnostic["classification"] == "transport_stdout_eof_before_turn_completed"
    assert diagnostic["thread_id"] == "thread-target"
    assert diagnostic["turn_id"] == "turn-target"
    assert diagnostic["wave"] == "B"
    assert diagnostic["milestone_id"] == "milestone-1"
    assert diagnostic["codex_process_pid"] == 9876
    assert diagnostic["returncode"] == -15
    assert diagnostic["returncode_signal"]["signal_name"] == "SIGTERM"
    assert diagnostic["eof_before_turn_completed"] is True
    assert diagnostic["turn_completed_observed"] is False
    assert diagnostic["cleanup_thread_archive_after_failure"] is True
    assert diagnostic["orphan_monitor"]["orphan_events"] == 0
    assert diagnostic["paths"]["protocol_log_path"].endswith("milestone-1-wave-B-protocol.log")
    assert diagnostic["paths"]["response_json_path"].endswith("milestone-1-wave-B-response.json")
    assert diagnostic["paths"]["diagnostic_path"].endswith(
        "milestone-1-wave-B-terminal-diagnostic.json"
    )
    assert diagnostic["protocol"]["method_counts"]["item/commandExecution/outputDelta"] == 1
    assert diagnostic["protocol"]["command_output_delta_bytes_by_item_id"]["call-big"] == 300 * 1024
    assert diagnostic["protocol"]["largest_output_delta_item_id"] == "call-big"
    assert diagnostic["protocol"]["oversized_output_observed"] is True
    assert diagnostic["stderr_tail"] == "stderr tail"

    response_payload = json.loads(_capture_paths(tmp_path)[2].read_text(encoding="utf-8"))
    metadata = response_payload["metadata"]
    assert metadata["codex_terminal_diagnostic_path"] == str(diagnostic_path)
    assert metadata["codex_terminal_diagnostic_classification"] == (
        "transport_stdout_eof_before_turn_completed"
    )


@pytest.mark.asyncio
async def test_eof_without_capture_session_writes_minimal_terminal_diagnostic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from agent_team_v15 import codex_appserver as appserver
    from agent_team_v15.codex_appserver import CodexTerminalTurnError
    from agent_team_v15.codex_transport import CodexConfig

    class _FakeClient:
        cwd = str(tmp_path)
        returncode = 0
        process_pid = 1234

        async def start(self) -> None:
            return None

        async def initialize(self) -> dict[str, Any]:
            return {"userAgent": "test", "codexHome": str(tmp_path)}

        async def thread_start(self) -> dict[str, Any]:
            return {"thread": {"id": "thread-target"}}

        async def turn_start(self, thread_id: str, prompt: str) -> dict[str, Any]:
            del thread_id, prompt
            return {"turn": {"id": "turn-target"}}

        async def thread_archive(self, thread_id: str) -> dict[str, Any]:
            del thread_id
            return {}

        async def close(self) -> None:
            return None

        def stderr_excerpt(self, limit: int = 300) -> str:
            del limit
            return ""

    async def _fake_wait_for_turn_completion(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise CodexTerminalTurnError(
            "app-server stdout EOF — subprocess exited",
            thread_id="thread-target",
            turn_id="turn-target",
        )

    monkeypatch.setattr(appserver, "_CodexAppServerClient", lambda **_kwargs: _FakeClient())
    monkeypatch.setattr(appserver, "_wait_for_turn_completion", _fake_wait_for_turn_completion)
    monkeypatch.setattr(appserver, "log_codex_cli_version", lambda *_a, **_kw: None)

    with pytest.raises(CodexTerminalTurnError):
        await appserver.execute_codex(
            "Probe prompt.",
            str(tmp_path),
            CodexConfig(max_retries=0, reasoning_effort="low"),
            tmp_path,
            capture_enabled=False,
            wave_letter="B",
        )

    # B12 — appserver self-default now writes a forensic orphan-<ts> stem
    # (the legacy "auto"-prefix collided whenever two orphan recoveries
    # raced). Glob the milestone-id-agnostic suffix to find the artifact.
    capture_dir = tmp_path / ".agent-team" / "codex-captures"
    candidates = list(capture_dir.glob("orphan-*-wave-B-terminal-diagnostic.json"))
    assert len(candidates) == 1, (
        f"expected exactly one orphan-prefixed diagnostic; got {candidates}"
    )
    diagnostic_path = candidates[0]
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic["classification"] == "transport_stdout_eof_before_turn_completed"
    assert diagnostic["milestone_id"].startswith("orphan-")
    assert diagnostic["wave"] == "B"
    assert diagnostic["thread_id"] == "thread-target"
    assert diagnostic["turn_id"] == "turn-target"
    assert diagnostic["protocol"]["method_counts"] == {}


def test_cleanup_thread_archive_after_terminal_failure_is_not_natural_completion(tmp_path: Path) -> None:
    from agent_team_v15.codex_appserver import CodexTerminalTurnError
    from agent_team_v15.codex_captures import CodexCaptureMetadata, CodexCaptureSession

    session = CodexCaptureSession(
        metadata=CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B"),
        cwd=str(tmp_path),
        model="gpt-5.4",
        reasoning_effort="low",
        spawn_cwd=str(tmp_path),
        subprocess_argv=["codex", "app-server", "--listen", "stdio://"],
    )
    try:
        assert session.protocol_logger is not None
        session.protocol_logger.log_out(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "thread/archive",
                    "params": {"threadId": "thread-target"},
                },
                separators=(",", ":"),
            )
        )
        session.write_terminal_diagnostic(
            exception=CodexTerminalTurnError(
                "app-server stdout EOF — subprocess exited",
                thread_id="thread-target",
                turn_id="turn-target",
            ),
            thread_id="thread-target",
            turn_id="turn-target",
            codex_process_pid=9876,
            returncode=None,
            stderr_tail="",
            watchdog=None,
            cleanup_thread_archive_after_failure=True,
        )
    finally:
        session.close()

    diagnostic = json.loads(_diagnostic_path(tmp_path).read_text(encoding="utf-8"))
    assert diagnostic["classification"] == "transport_stdout_eof_before_turn_completed"
    assert diagnostic["turn_completed_observed"] is False
    assert diagnostic["cleanup_thread_archive_after_failure"] is True
    assert diagnostic["target_thread_archive_before_turn_completed"] is False
    assert diagnostic["protocol"]["method_counts"]["thread/archive"] == 1


def test_target_thread_archive_before_turn_completed_is_classified(tmp_path: Path) -> None:
    from agent_team_v15.codex_appserver import CodexTerminalTurnError
    from agent_team_v15.codex_captures import CodexCaptureMetadata, CodexCaptureSession

    session = CodexCaptureSession(
        metadata=CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B"),
        cwd=str(tmp_path),
        model="gpt-5.4",
        reasoning_effort="low",
        spawn_cwd=str(tmp_path),
        subprocess_argv=["codex", "app-server", "--listen", "stdio://"],
    )
    try:
        assert session.protocol_logger is not None
        session.protocol_logger.log_in(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "thread/archive",
                    "params": {"threadId": "thread-target"},
                },
                separators=(",", ":"),
            )
        )
        session.write_terminal_diagnostic(
            exception=CodexTerminalTurnError(
                "thread/archive received before turn/completed",
                thread_id="thread-target",
                turn_id="turn-target",
            ),
            thread_id="thread-target",
            turn_id="turn-target",
            codex_process_pid=9876,
            returncode=0,
            stderr_tail="",
            watchdog=None,
            cleanup_thread_archive_after_failure=False,
        )
    finally:
        session.close()

    diagnostic = json.loads(_diagnostic_path(tmp_path).read_text(encoding="utf-8"))
    assert diagnostic["classification"] == "target_thread_archive_before_turn_completed"
    assert diagnostic["target_thread_archive_before_turn_completed"] is True
    assert diagnostic["cleanup_thread_archive_after_failure"] is False
    assert diagnostic["eof_before_turn_completed"] is False


def test_large_output_delta_is_counted_without_mutating_stream_event(tmp_path: Path) -> None:
    from agent_team_v15.codex_appserver import (
        _MessageAccumulator,
        _OrphanWatchdog,
        _TokenAccumulator,
        _process_streaming_event,
    )
    from agent_team_v15.codex_captures import CodexCaptureMetadata, CodexCaptureSession

    delta = "Z" * (300 * 1024)
    event = {
        "jsonrpc": "2.0",
        "method": "item/commandExecution/outputDelta",
        "params": {
            "threadId": "thread-target",
            "turnId": "turn-target",
            "itemId": "call-big",
            "delta": delta,
        },
    }
    event_before = json.loads(json.dumps(event))
    progress_events: list[dict[str, Any]] = []

    def _progress_callback(**kwargs: Any) -> None:
        progress_events.append(dict(kwargs))

    session = CodexCaptureSession(
        metadata=CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B"),
        cwd=str(tmp_path),
        model="gpt-5.4",
        reasoning_effort="low",
        spawn_cwd=str(tmp_path),
        subprocess_argv=["codex", "app-server", "--listen", "stdio://"],
    )
    try:
        assert session.protocol_logger is not None
        session.protocol_logger.log_in(json.dumps(event, separators=(",", ":")))
        _process_streaming_event(
            event,
            _OrphanWatchdog(timeout_seconds=300),
            _TokenAccumulator(),
            _progress_callback,
            _MessageAccumulator(),
            session,
        )
        session.write_terminal_diagnostic(
            exception=None,
            thread_id="thread-target",
            turn_id="turn-target",
            codex_process_pid=None,
            returncode=None,
            stderr_tail="",
            watchdog=None,
            cleanup_thread_archive_after_failure=False,
        )
    finally:
        session.close()

    assert event == event_before
    diagnostic = json.loads(_diagnostic_path(tmp_path).read_text(encoding="utf-8"))
    assert diagnostic["protocol"]["command_output_delta_bytes_by_item_id"]["call-big"] == len(
        delta.encode("utf-8")
    )
    assert diagnostic["protocol"]["oversized_output_observed"] is True
    assert diagnostic["protocol"]["largest_output_delta_item_id"] == "call-big"
    assert progress_events == []


def test_normal_turn_completed_capture_has_no_terminal_diagnostic(tmp_path: Path) -> None:
    from agent_team_v15.codex_captures import CodexCaptureMetadata, CodexCaptureSession

    session = CodexCaptureSession(
        metadata=CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B"),
        cwd=str(tmp_path),
        model="gpt-5.4",
        reasoning_effort="low",
        spawn_cwd=str(tmp_path),
        subprocess_argv=["codex", "app-server", "--listen", "stdio://"],
    )
    try:
        assert session.protocol_logger is not None
        session.protocol_logger.log_in(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-target",
                        "turn": {"id": "turn-target", "status": "completed"},
                    },
                },
                separators=(",", ":"),
            )
        )
        session.finalize(codex_result=types.SimpleNamespace(success=True, model="gpt-5.4"))
    finally:
        session.close()

    response_payload = json.loads(_capture_paths(tmp_path)[2].read_text(encoding="utf-8"))
    assert response_payload["metadata"]["codex_terminal_diagnostic_path"] == ""
    assert response_payload["metadata"]["codex_terminal_diagnostic_classification"] == ""
    assert not _diagnostic_path(tmp_path).exists()


@pytest.mark.asyncio
async def test_provider_routed_codex_dispatch_skips_capture_when_flag_off(monkeypatch, tmp_path: Path) -> None:
    from agent_team_v15 import codex_appserver as appserver
    from agent_team_v15.codex_transport import CodexConfig
    from agent_team_v15.provider_router import WaveProviderMap, execute_wave_with_provider

    mock_proc = _mock_appserver_process(tmp_path)

    async def _spawn(*, cwd: str, env: dict[str, str]) -> _MockProcess:
        del cwd, env
        return mock_proc

    monkeypatch.setattr(appserver, "_spawn_appserver_process", _spawn)
    monkeypatch.setattr(appserver, "log_codex_cli_version", lambda *_a, **_kw: None)

    result = await execute_wave_with_provider(
        wave_letter="B",
        prompt="Wire the backend.",
        cwd=str(tmp_path),
        config=_provider_config(capture_enabled=False),
        provider_map=WaveProviderMap(),
        claude_callback=lambda **kw: 0,
        claude_callback_kwargs={
            "milestone": types.SimpleNamespace(id="milestone-1", title="Test"),
        },
        codex_transport_module=appserver,
        codex_config=CodexConfig(max_retries=0, reasoning_effort="low"),
        codex_home=tmp_path,
        checkpoint_create=lambda label, cwd: _FakeCheckpoint(file_manifest={"keep.txt": "hash"}),
        checkpoint_diff=lambda pre, post: _FakeDiff(modified=["keep.txt"]),
    )

    assert result["provider"] == "codex"
    assert not (tmp_path / ".agent-team" / "codex-captures").exists()


def test_response_accumulator_counts_write_like_items_and_truncates_output() -> None:
    from agent_team_v15.codex_captures import ResponseCaptureAccumulator

    accumulator = ResponseCaptureAccumulator()
    accumulator.observe_event(
        {
            "method": "item/started",
            "params": {
                "item": {
                    "type": "fileChange",
                    "id": "fc_1",
                    "path": "src/app.ts",
                    "status": "inProgress",
                }
            },
        }
    )
    accumulator.observe_event(
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "type": "fileChange",
                    "id": "fc_1",
                    "path": "src/app.ts",
                    "status": "completed",
                    "diff": "x" * 2048,
                }
            },
        }
    )

    summary = accumulator.summary()
    tool_call = accumulator.tool_calls_payload()[0]

    assert summary["total_tool_calls"] == 1
    assert summary["write_tool_invocations"] == 1
    assert summary["read_tool_invocations"] == 0
    assert "<truncated from " in str(tool_call["output_summary"])


def test_protocol_capture_logger_rotates(tmp_path: Path) -> None:
    from agent_team_v15.codex_captures import ProtocolCaptureLogger

    log_path = tmp_path / "protocol.log"
    protocol_logger = ProtocolCaptureLogger(log_path, max_bytes=160, backup_count=2)
    try:
        for _ in range(12):
            protocol_logger.log_out('{"jsonrpc":"2.0","method":"turn/start","params":{"text":"' + ("x" * 80) + '"}}')
    finally:
        protocol_logger.close()

    assert log_path.is_file()
    assert Path(str(log_path) + ".1").is_file()


def test_prompt_capture_failure_does_not_block_protocol_and_response_capture(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from agent_team_v15.codex_captures import CodexCaptureMetadata, CodexCaptureSession

    original_write_text = Path.write_text

    def _patched_write_text(self: Path, *args, **kwargs):
        if self.name.endswith("-prompt.txt"):
            raise OSError("prompt write blocked")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _patched_write_text)

    session = CodexCaptureSession(
        metadata=CodexCaptureMetadata(milestone_id="milestone-1", wave_letter="B"),
        cwd=str(tmp_path),
        model="gpt-5.4",
        reasoning_effort="low",
        spawn_cwd=str(tmp_path),
        subprocess_argv=["codex", "app-server", "--listen", "stdio://"],
    )
    try:
        session.capture_prompt("Prompt body")
        assert session.protocol_logger is not None
        session.protocol_logger.log_out(b'{"jsonrpc":"2.0","method":"initialize"}\n')
        session.observe_event(
            {
                "method": "item/started",
                "params": {
                    "item": {
                        "type": "commandExecution",
                        "id": "cmd_1",
                        "command": "pwd",
                        "status": "inProgress",
                    }
                },
            }
        )
        session.observe_event(
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "commandExecution",
                        "id": "cmd_1",
                        "command": "pwd",
                        "status": "completed",
                    }
                },
            }
        )
        session.finalize(
            codex_result=types.SimpleNamespace(
                success=True,
                model="gpt-5.4",
                input_tokens=1,
                output_tokens=1,
                reasoning_tokens=0,
                cached_input_tokens=0,
                retry_count=0,
                exit_code=0,
                error="",
            )
        )
    finally:
        session.close()

    prompt_path, protocol_path, response_path = _capture_paths(tmp_path)
    assert not prompt_path.exists()
    assert protocol_path.is_file()
    assert response_path.is_file()


def test_codex_config_has_protocol_capture_enabled_default_false() -> None:
    """Transport-level default capture flag is opt-in."""
    from agent_team_v15.codex_transport import CodexConfig

    cfg = CodexConfig()
    assert cfg.protocol_capture_enabled is False


@pytest.mark.asyncio
async def test_execute_codex_auto_synthesizes_capture_metadata_when_flag_on(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """With ``protocol_capture_enabled=True`` and no metadata passed in,
    ``execute_codex`` synthesizes ``CodexCaptureMetadata`` so captures
    land without the caller threading metadata through."""
    from agent_team_v15 import codex_appserver as appserver
    from agent_team_v15.codex_captures import CodexCaptureMetadata
    from agent_team_v15.codex_transport import CodexConfig

    mock_proc = _mock_appserver_process(tmp_path)

    async def _spawn(*, cwd: str, env: dict[str, str]) -> _MockProcess:
        del cwd, env
        return mock_proc

    monkeypatch.setattr(appserver, "_spawn_appserver_process", _spawn)
    monkeypatch.setattr(appserver, "log_codex_cli_version", lambda *_a, **_kw: None)

    seen: dict[str, Any] = {}
    real_session_cls = appserver.CodexCaptureSession

    class _SpyCaptureSession(real_session_cls):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen["metadata"] = kwargs.get("metadata")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(appserver, "CodexCaptureSession", _SpyCaptureSession)

    await appserver.execute_codex(
        "Probe prompt.",
        str(tmp_path),
        CodexConfig(max_retries=0, reasoning_effort="low", protocol_capture_enabled=True),
        tmp_path,
        wave_letter="b",
    )

    # B12 — auto-synthesized capture metadata now uses a forensic orphan-<ts>
    # stem (the legacy "auto" literal silently overwrote concurrent recoveries).
    assert isinstance(seen.get("metadata"), CodexCaptureMetadata)
    assert seen["metadata"].milestone_id.startswith("orphan-")
    assert seen["metadata"].wave_letter == "B"

    capture_dir = tmp_path / ".agent-team" / "codex-captures"
    assert capture_dir.is_dir()
    prompt_files = list(capture_dir.glob("orphan-*-wave-B*-prompt.txt"))
    assert prompt_files, "auto-synthesized capture must write a prompt file"


@pytest.mark.asyncio
async def test_execute_codex_respects_explicit_metadata_when_flag_on(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Caller-supplied metadata wins over auto-synthesis even if the flag is on."""
    from agent_team_v15 import codex_appserver as appserver
    from agent_team_v15.codex_captures import CodexCaptureMetadata
    from agent_team_v15.codex_transport import CodexConfig

    mock_proc = _mock_appserver_process(tmp_path)

    async def _spawn(*, cwd: str, env: dict[str, str]) -> _MockProcess:
        del cwd, env
        return mock_proc

    monkeypatch.setattr(appserver, "_spawn_appserver_process", _spawn)
    monkeypatch.setattr(appserver, "log_codex_cli_version", lambda *_a, **_kw: None)

    explicit = CodexCaptureMetadata(milestone_id="milestone-99", wave_letter="D")
    seen: dict[str, Any] = {}
    real_session_cls = appserver.CodexCaptureSession

    class _SpyCaptureSession(real_session_cls):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen["metadata"] = kwargs.get("metadata")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(appserver, "CodexCaptureSession", _SpyCaptureSession)

    await appserver.execute_codex(
        "Probe prompt.",
        str(tmp_path),
        CodexConfig(max_retries=0, reasoning_effort="low", protocol_capture_enabled=True),
        tmp_path,
        capture_enabled=True,
        capture_metadata=explicit,
        wave_letter="b",
    )

    assert seen.get("metadata") is explicit


@pytest.mark.asyncio
async def test_execute_codex_skips_capture_when_flag_off_and_no_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Flag off + no metadata = no capture session (byte-identical to pre-flag behavior)."""
    from agent_team_v15 import codex_appserver as appserver
    from agent_team_v15.codex_transport import CodexConfig

    mock_proc = _mock_appserver_process(tmp_path)

    async def _spawn(*, cwd: str, env: dict[str, str]) -> _MockProcess:
        del cwd, env
        return mock_proc

    monkeypatch.setattr(appserver, "_spawn_appserver_process", _spawn)
    monkeypatch.setattr(appserver, "log_codex_cli_version", lambda *_a, **_kw: None)

    calls: list[Any] = []
    real_session_cls = appserver.CodexCaptureSession

    class _SpyCaptureSession(real_session_cls):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append(kwargs.get("metadata"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(appserver, "CodexCaptureSession", _SpyCaptureSession)

    await appserver.execute_codex(
        "Probe prompt.",
        str(tmp_path),
        CodexConfig(max_retries=0, reasoning_effort="low", protocol_capture_enabled=False),
        tmp_path,
        wave_letter="b",
    )

    assert calls == []
    assert not (tmp_path / ".agent-team" / "codex-captures").exists()
