"""Codex App-Server transport via stdio JSON-RPC."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Optional

from .codex_cli import log_codex_cli_version, prefix_codex_error_code, resolve_codex_binary
from .codex_transport import CodexConfig, CodexResult, cleanup_codex_home, create_codex_home

logger = logging.getLogger(__name__)

_PROCESS_TERMINATION_TIMEOUT_SECONDS = 2.0
_CLIENT_INFO = {
    "name": "agent-team-v15",
    "title": "agent-team-v15",
    "version": "15.0.0",
}


class CodexOrphanToolError(Exception):
    """Raised when orphan tool detection fires past the retry budget."""

    def __init__(
        self,
        tool_name: str = "",
        tool_id: str = "",
        age_seconds: float = 0.0,
        orphan_count: int = 0,
        message: str = "",
    ) -> None:
        self.tool_name = tool_name
        self.tool_id = tool_id
        self.age_seconds = age_seconds
        self.orphan_count = orphan_count
        super().__init__(message or f"Orphan tool '{tool_name}' (age={age_seconds:.0f}s, count={orphan_count})")


class _CodexAppServerError(RuntimeError):
    """Base transport/protocol error."""


class _CodexAppServerRequestError(_CodexAppServerError):
    """JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = int(code)
        self.data = data
        super().__init__(f"JSON-RPC error {self.code}: {message}")


def is_codex_available() -> bool:
    """Return *True* if the ``codex`` binary is on PATH."""
    return shutil.which("codex") is not None


async def _emit_progress(
    progress_callback: Callable[..., Any] | None,
    *,
    message_type: str,
    tool_name: str = "",
    tool_id: str = "",
    event_kind: str = "other",
) -> None:
    """Best-effort progress callback runner."""
    if progress_callback is None:
        return
    try:
        maybe_awaitable = progress_callback(
            message_type=message_type,
            tool_name=tool_name,
            tool_id=tool_id,
            event_kind=event_kind,
        )
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
    except TypeError:
        try:
            maybe_awaitable = progress_callback(
                message_type=message_type,
                tool_name=tool_name,
            )
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        except Exception as exc:  # pragma: no cover - defensive logging only
            logger.debug("App-server progress callback failed: %s", exc)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("App-server progress callback failed: %s", exc)


class _OrphanWatchdog:
    """Track pending tool starts and detect orphans past a threshold."""

    def __init__(self, timeout_seconds: float = 300.0, max_orphan_events: int = 2) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_orphan_events = max_orphan_events
        self._lock = threading.Lock()
        self.pending_tool_starts: dict[str, dict[str, Any]] = {}
        self.orphan_event_count: int = 0
        self.last_orphan_tool_name: str = ""
        self.last_orphan_tool_id: str = ""
        self.last_orphan_age: float = 0.0
        self._registered_orphans: set[str] = set()

    def record_start(self, item_id: str, tool_name: str) -> None:
        with self._lock:
            self.pending_tool_starts[item_id] = {
                "tool_name": tool_name,
                "started_monotonic": time.monotonic(),
            }

    def record_complete(self, item_id: str) -> None:
        with self._lock:
            self.pending_tool_starts.pop(item_id, None)

    def check_orphans(self) -> tuple[bool, str, str, float]:
        now = time.monotonic()
        with self._lock:
            for item_id, info in self.pending_tool_starts.items():
                if item_id in self._registered_orphans:
                    continue
                age = now - info["started_monotonic"]
                if age > self.timeout_seconds:
                    return True, info["tool_name"], item_id, age
        return False, "", "", 0.0

    def register_orphan_event(self, tool_name: str, tool_id: str, age: float) -> None:
        with self._lock:
            if tool_id and tool_id in self._registered_orphans:
                return
            if tool_id:
                self._registered_orphans.add(tool_id)
            self.orphan_event_count += 1
            self.last_orphan_tool_name = tool_name
            self.last_orphan_tool_id = tool_id
            self.last_orphan_age = age

    @property
    def budget_exhausted(self) -> bool:
        return self.orphan_event_count >= self.max_orphan_events


class _TokenAccumulator:
    """Accumulate token usage from ``thread/tokenUsage/updated`` notifications."""

    def __init__(self) -> None:
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.reasoning_tokens: int = 0
        self.cached_input_tokens: int = 0

    def update(self, usage: dict[str, Any]) -> None:
        token_usage = usage.get("tokenUsage") if isinstance(usage, dict) else None
        if isinstance(token_usage, dict):
            usage = token_usage.get("total") or token_usage.get("last") or {}

        self.input_tokens = int(usage.get("inputTokens", usage.get("input_tokens", 0)) or 0)
        self.output_tokens = int(usage.get("outputTokens", usage.get("output_tokens", 0)) or 0)
        self.reasoning_tokens = int(
            usage.get(
                "reasoningOutputTokens",
                usage.get("reasoningTokens", usage.get("reasoning_tokens", 0)),
            )
            or 0
        )
        self.cached_input_tokens = int(
            usage.get("cachedInputTokens", usage.get("cached_input_tokens", 0)) or 0
        )

    def apply_to(self, result: CodexResult, config: CodexConfig) -> None:
        result.input_tokens = self.input_tokens
        result.output_tokens = self.output_tokens
        result.reasoning_tokens = self.reasoning_tokens
        result.cached_input_tokens = self.cached_input_tokens

        model_pricing = config.pricing.get(config.model)
        if not model_pricing:
            logger.warning("No pricing data for model %s - cost will be $0", config.model)
            result.cost_usd = 0.0
            return

        input_price = model_pricing.get("input", 0.0)
        cached_price = model_pricing.get("cached_input", 0.0)
        output_price = model_pricing.get("output", 0.0)
        uncached_input = max(self.input_tokens - self.cached_input_tokens, 0)
        result.cost_usd = round(
            (uncached_input * input_price / 1_000_000)
            + (self.cached_input_tokens * cached_price / 1_000_000)
            + (self.output_tokens * output_price / 1_000_000),
            6,
        )


class _MessageAccumulator:
    """Collect final assistant text from streaming notifications."""

    def __init__(self) -> None:
        self._buffers: dict[str, str] = {}
        self._completed: list[str] = []
        self._final_answer: str = ""

    def observe(self, event: dict[str, Any]) -> None:
        method = str(event.get("method", ""))
        params = event.get("params", {})
        if not isinstance(params, dict):
            return

        if method == "item/agentMessage/delta":
            item_id = str(params.get("itemId", "") or "")
            delta = str(params.get("delta", "") or "")
            if item_id and delta:
                self._buffers[item_id] = self._buffers.get(item_id, "") + delta
            return

        if method != "item/completed":
            return

        item = params.get("item", {})
        if not isinstance(item, dict) or str(item.get("type", "")) != "agentMessage":
            return

        item_id = str(item.get("id", "") or "")
        text = str(item.get("text", "") or self._buffers.get(item_id, "") or "")
        if not text:
            return
        if item.get("phase") == "final_answer":
            self._final_answer = text
        self._completed.append(text)

    def final_message(self) -> str:
        if self._final_answer:
            return self._final_answer
        if self._completed:
            return self._completed[-1]
        return ""


def _serialize_jsonrpc_request(request_id: int, method: str, params: dict[str, Any]) -> bytes:
    """Serialize one newline-delimited JSON-RPC request."""
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"


def _parse_jsonrpc_line(line: bytes) -> dict[str, Any]:
    """Parse one newline-delimited JSON message."""
    stripped = line.strip()
    if not stripped:
        raise _CodexAppServerError("Received blank line from codex app-server")
    try:
        parsed = json.loads(stripped.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise _CodexAppServerError(f"Invalid JSON from codex app-server: {exc}") from exc
    if not isinstance(parsed, dict):
        raise _CodexAppServerError("Expected JSON object from codex app-server")
    return parsed


def _build_transport_env(codex_home: Path) -> dict[str, str]:
    """Build the environment for the app-server subprocess."""
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    env["CODEX_QUIET_MODE"] = "1"
    return env


async def _spawn_appserver_process(*, cwd: str, env: dict[str, str]) -> asyncio.subprocess.Process:
    """Spawn ``codex app-server --listen stdio://``."""
    codex_bin = resolve_codex_binary()
    cmd = [codex_bin, "app-server", "--listen", "stdio://"]
    use_shell = sys.platform == "win32" and codex_bin.lower().endswith((".cmd", ".bat"))

    if use_shell:
        return await asyncio.create_subprocess_shell(
            subprocess.list2cmdline(cmd),
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    return await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )


async def _kill_process_tree_windows(
    pid: int,
    *,
    timeout_seconds: float | None = None,
) -> None:
    """Best-effort Windows tree kill for shell-wrapped Codex processes."""
    if timeout_seconds is None:
        timeout_seconds = _PROCESS_TERMINATION_TIMEOUT_SECONDS
    try:
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/F",
            "/T",
            "/PID",
            str(pid),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("taskkill launch failed for PID %s: %s", pid, exc)
        return

    try:
        await asyncio.wait_for(killer.communicate(), timeout=timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.debug("taskkill wait failed for PID %s: %s", pid, exc)


async def _terminate_subprocess(
    proc: asyncio.subprocess.Process | None,
    *,
    timeout_seconds: float | None = None,
) -> None:
    """Best-effort termination that must not block teardown forever."""
    if proc is None:
        return
    if timeout_seconds is None:
        timeout_seconds = _PROCESS_TERMINATION_TIMEOUT_SECONDS

    pid = getattr(proc, "pid", None)
    with suppress(Exception):
        proc.kill()

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        return
    except Exception as exc:  # noqa: BLE001
        logger.debug("Initial subprocess wait failed for PID %s: %s", pid, exc)

    if sys.platform == "win32" and pid is not None:
        await _kill_process_tree_windows(int(pid), timeout_seconds=timeout_seconds)
        with suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)


class _CodexJSONRPCTransport:
    """Own the app-server subprocess and multiplex JSON-RPC over stdio."""

    def __init__(self, *, cwd: str, codex_home: Path) -> None:
        self.cwd = cwd
        self.codex_home = codex_home
        self.process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._request_id = 0
        self._closing = False
        self._stderr_lines: deque[str] = deque(maxlen=40)

    @property
    def returncode(self) -> int | None:
        return None if self.process is None else self.process.returncode

    def stderr_excerpt(self, limit: int = 300) -> str:
        collapsed = " ".join(line.strip() for line in self._stderr_lines if line.strip())
        return collapsed[:limit]

    async def start(self) -> None:
        if self.process is not None:
            return
        env = _build_transport_env(self.codex_home)
        self.process = await _spawn_appserver_process(cwd=self.cwd, env=env)
        self._stdout_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        close_error = self._closed_error()
        self._fail_pending(close_error)

        if self.process is not None and self.process.stdin is not None:
            with suppress(Exception):
                self.process.stdin.close()
            wait_closed = getattr(self.process.stdin, "wait_closed", None)
            if callable(wait_closed):
                with suppress(Exception):
                    await wait_closed()

        if self.process is not None:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=_PROCESS_TERMINATION_TIMEOUT_SECONDS)
            except Exception:
                await _terminate_subprocess(self.process)

        tasks = [task for task in (self._stdout_task, self._stderr_task) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def send_request(self, method: str, params: dict[str, Any]) -> Any:
        if self.process is None:
            raise _CodexAppServerError("Transport has not been started")

        self._request_id += 1
        request_id = self._request_id
        payload = _serialize_jsonrpc_request(request_id, method, params)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future

        try:
            async with self._write_lock:
                if self.process.stdin is None:
                    raise _CodexAppServerError("codex app-server stdin is unavailable")
                self.process.stdin.write(payload)
                await self.process.stdin.drain()
        except Exception:
            self._pending.pop(request_id, None)
            raise

        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def next_notification(self) -> dict[str, Any]:
        return await self._notifications.get()

    async def _read_stdout(self) -> None:
        if self.process is None or self.process.stdout is None:
            return

        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                message = _parse_jsonrpc_line(line)
                if "method" in message:
                    await self._notifications.put(message)
                    continue
                if "id" not in message:
                    logger.debug("Ignoring app-server message without method/id: %s", message)
                    continue

                future = self._pending.get(int(message["id"]))
                if future is None or future.done():
                    continue

                if "error" in message:
                    error = message.get("error", {})
                    future.set_exception(
                        _CodexAppServerRequestError(
                            error.get("code", -32000),
                            str(error.get("message", "unknown JSON-RPC error")),
                            error.get("data"),
                        )
                    )
                else:
                    future.set_result(message.get("result"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("App-server stdout reader failed: %s", exc)
            self._fail_pending(exc)
        finally:
            if not self._closing:
                self._fail_pending(self._closed_error())

    async def _read_stderr(self) -> None:
        if self.process is None or self.process.stderr is None:
            return

        try:
            while True:
                line = await self.process.stderr.readline()
                if not line:
                    return
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    self._stderr_lines.append(decoded)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("App-server stderr reader failed: %s", exc)

    def _closed_error(self) -> _CodexAppServerError:
        parts = ["codex app-server closed before completing the request"]
        if self.process is not None and self.process.returncode not in (None, 0):
            parts.append(f"(exit={self.process.returncode})")
        stderr = self.stderr_excerpt()
        if stderr:
            parts.append(f"stderr: {stderr}")
        return _CodexAppServerError(" ".join(parts))

    def _fail_pending(self, exc: BaseException) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(exc)


class _CodexAppServerClient:
    """Method-level JSON-RPC client for the subset v18 uses."""

    def __init__(self, *, cwd: str, config: CodexConfig, codex_home: Path) -> None:
        self.cwd = cwd
        self.config = config
        self.codex_home = codex_home
        self.transport = _CodexJSONRPCTransport(cwd=cwd, codex_home=codex_home)

    @property
    def returncode(self) -> int | None:
        return self.transport.returncode

    def stderr_excerpt(self, limit: int = 300) -> str:
        return self.transport.stderr_excerpt(limit=limit)

    async def start(self) -> None:
        await self.transport.start()

    async def close(self) -> None:
        await self.transport.close()

    async def send_request(self, method: str, params: dict[str, Any]) -> Any:
        return await self.transport.send_request(method, params)

    async def initialize(self) -> dict[str, Any]:
        return await self.send_request(
            "initialize",
            {
                "clientInfo": dict(_CLIENT_INFO),
                "capabilities": {"experimentalApi": True},
            },
        )

    async def thread_start(self) -> dict[str, Any]:
        params = {
            "cwd": self.cwd,
            "model": self.config.model,
            "approvalPolicy": "never",
            "personality": "pragmatic",
        }
        return await self.send_request("thread/start", params)

    async def turn_start(self, thread_id: str, prompt: str) -> dict[str, Any]:
        params = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "cwd": self.cwd,
            "effort": self.config.reasoning_effort,
        }
        return await self.send_request("turn/start", params)

    async def turn_interrupt(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        return await self.send_request(
            "turn/interrupt",
            {"threadId": thread_id, "turnId": turn_id},
        )

    async def thread_archive(self, thread_id: str) -> dict[str, Any]:
        return await self.send_request("thread/archive", {"threadId": thread_id})

    async def next_notification(self) -> dict[str, Any]:
        return await self.transport.next_notification()


async def _send_turn_interrupt(client: Any, thread_id: str, turn_id: str) -> bool:
    """Send ``turn/interrupt`` over JSON-RPC."""
    if not thread_id or not turn_id:
        return False

    try:
        fn = getattr(client, "turn_interrupt", None)
        if callable(fn):
            result = fn(thread_id, turn_id)
        else:
            send_request = getattr(client, "send_request", None)
            if not callable(send_request):
                raise AttributeError("client exposes neither turn_interrupt nor send_request")
            result = send_request(
                "turn/interrupt",
                {"threadId": thread_id, "turnId": turn_id},
            )
        if inspect.isawaitable(result):
            await result
        return True
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.error("turn/interrupt dispatch failed: %s", exc)
        return False


async def _monitor_orphans(
    client: Any,
    thread_id: str,
    turn_id: str,
    watchdog: _OrphanWatchdog,
    *,
    check_interval_seconds: float,
) -> bool:
    """Poll the watchdog and send ``turn/interrupt`` on first orphan."""
    interval = max(check_interval_seconds, 1.0)
    while True:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        is_orphan, tool_name, tool_id, age = watchdog.check_orphans()
        if not is_orphan:
            continue
        watchdog.register_orphan_event(tool_name, tool_id, age)
        logger.warning(
            "Orphan tool detected: name=%s id=%s age=%.0fs (event %d/%d) - sending turn/interrupt",
            tool_name,
            tool_id,
            age,
            watchdog.orphan_event_count,
            watchdog.max_orphan_events,
        )
        await _send_turn_interrupt(client, thread_id, turn_id)
        return True


def _item_field(item: Any, field: str, default: str = "") -> str:
    if isinstance(item, dict):
        return str(item.get(field, default) or default)
    return str(getattr(item, field, default) or default)


def _fire_progress_sync(
    callback: Callable[..., Any],
    message_type: str,
    tool_name: str,
    tool_id: str,
    event_kind: str,
) -> None:
    """Fire progress callback synchronously."""
    try:
        result = callback(
            message_type=message_type,
            tool_name=tool_name,
            tool_id=tool_id,
            event_kind=event_kind,
        )
        if inspect.isawaitable(result):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(result)
            except RuntimeError:
                pass
    except TypeError:
        try:
            callback(message_type=message_type, tool_name=tool_name)
        except Exception:
            pass
    except Exception:
        pass


def _process_streaming_event(
    event: Any,
    watchdog: _OrphanWatchdog,
    tokens: _TokenAccumulator,
    progress_callback: Callable[..., Any] | None,
    messages: _MessageAccumulator | None = None,
) -> None:
    """Process one app-server notification."""
    method = ""
    params: dict[str, Any] = {}

    if isinstance(event, dict):
        method = str(event.get("method", ""))
        raw_params = event.get("params", {})
        if isinstance(raw_params, dict):
            params = raw_params
    elif hasattr(event, "method"):
        method = str(getattr(event, "method", ""))
        raw_params = getattr(event, "params", {}) or {}
        if isinstance(raw_params, dict):
            params = raw_params

    if not method:
        return

    if messages is not None:
        messages.observe({"method": method, "params": params})

    if method == "item/started":
        item = params.get("item", {})
        item_id = _item_field(item, "id")
        tool_name = _item_field(item, "name") or _item_field(item, "tool") or _item_field(item, "type")
        if item_id:
            watchdog.record_start(item_id, tool_name)
        if progress_callback is not None:
            _fire_progress_sync(progress_callback, "item/started", tool_name, item_id, "start")
        return

    if method == "item/completed":
        item = params.get("item", {})
        item_id = _item_field(item, "id")
        tool_name = _item_field(item, "name") or _item_field(item, "tool") or _item_field(item, "type")
        if item_id:
            watchdog.record_complete(item_id)
        if progress_callback is not None:
            _fire_progress_sync(progress_callback, "item/completed", tool_name, item_id, "complete")
        return

    if method == "item/agentMessage/delta":
        if progress_callback is not None:
            item_id = str(params.get("itemId", "") or "")
            _fire_progress_sync(progress_callback, "item/agentMessage/delta", "agentMessage", item_id, "other")
        return

    if method == "thread/tokenUsage/updated":
        tokens.update(params)
        return

    if method == "model/rerouted":
        logger.info(
            "Model rerouted: %s -> %s",
            params.get("fromModel", ""),
            params.get("toModel", ""),
        )


def _format_turn_error(error: Any) -> str:
    if isinstance(error, dict):
        message = str(error.get("message", "") or "")
        details = str(error.get("additionalDetails", "") or "")
        if message and details:
            return f"{message} ({details})"
        return message or details
    if error is None:
        return ""
    return str(error)


def _format_protocol_error(exc: Exception) -> str:
    message = str(exc)
    return prefix_codex_error_code(message)


def _accumulate_attempt_totals(total: CodexResult, attempt: CodexResult) -> None:
    total.input_tokens += attempt.input_tokens
    total.output_tokens += attempt.output_tokens
    total.reasoning_tokens += attempt.reasoning_tokens
    total.cached_input_tokens += attempt.cached_input_tokens
    total.cost_usd = round(total.cost_usd + attempt.cost_usd, 6)
    total.exit_code = attempt.exit_code
    if attempt.final_message:
        total.final_message = attempt.final_message
    if attempt.error:
        total.error = attempt.error


async def _wait_for_turn_completion(
    client: _CodexAppServerClient,
    *,
    thread_id: str,
    turn_id: str,
    watchdog: _OrphanWatchdog,
    tokens: _TokenAccumulator,
    progress_callback: Callable[..., Any] | None,
    messages: _MessageAccumulator,
) -> dict[str, Any]:
    """Drain notifications until the target turn finishes."""
    while True:
        message = await client.next_notification()
        _process_streaming_event(message, watchdog, tokens, progress_callback, messages)

        if message.get("method") == "error":
            logger.warning(
                "App-server error notification: %s",
                _format_turn_error(message.get("params", {}).get("error")),
            )
            continue

        if message.get("method") != "turn/completed":
            continue

        params = message.get("params", {})
        if not isinstance(params, dict) or params.get("threadId") != thread_id:
            continue
        turn = params.get("turn", {})
        if isinstance(turn, dict) and turn.get("id") == turn_id:
            return turn


def _app_server_error_message(client: _CodexAppServerClient, exc: Exception) -> str:
    base = _format_protocol_error(exc)
    stderr = client.stderr_excerpt()
    if stderr and stderr not in base:
        return f"{base}; stderr: {stderr}"
    return base


async def _execute_once(
    prompt: str,
    cwd: str,
    config: CodexConfig,
    codex_home: Path,
    *,
    orphan_timeout_seconds: float = 300.0,
    orphan_max_events: int = 2,
    orphan_check_interval_seconds: float = 60.0,
    progress_callback: Callable[..., Any] | None = None,
) -> CodexResult:
    """Run one app-server session and parse the turn result."""
    result = CodexResult(model=config.model)
    start = time.monotonic()
    tokens = _TokenAccumulator()
    watchdog = _OrphanWatchdog(
        timeout_seconds=orphan_timeout_seconds,
        max_orphan_events=orphan_max_events,
    )
    messages = _MessageAccumulator()
    client = _CodexAppServerClient(cwd=cwd, config=config, codex_home=codex_home)
    thread_id = ""
    current_prompt = prompt

    try:
        await client.start()
        init_result = await client.initialize()
        logger.info(
            "App-server initialized: userAgent=%s codexHome=%s",
            init_result.get("userAgent", "unknown"),
            init_result.get("codexHome", "unknown"),
        )

        thread_result = await client.thread_start()
        thread = thread_result.get("thread", {})
        thread_id = str(thread.get("id", "") or "")
        logger.info("Thread started: id=%s", thread_id)

        while True:
            turn_result = await client.turn_start(thread_id, current_prompt)
            turn = turn_result.get("turn", {})
            turn_id = str(turn.get("id", "") or "")
            logger.info("Turn started: id=%s", turn_id)

            await _emit_progress(
                progress_callback,
                message_type="turn/started",
                event_kind="other",
            )

            monitor_task = asyncio.create_task(
                _monitor_orphans(
                    client,
                    thread_id,
                    turn_id,
                    watchdog,
                    check_interval_seconds=orphan_check_interval_seconds,
                )
            )
            try:
                completed_turn = await _wait_for_turn_completion(
                    client,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    watchdog=watchdog,
                    tokens=tokens,
                    progress_callback=progress_callback,
                    messages=messages,
                )
            finally:
                monitor_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await monitor_task

            turn_status = str(completed_turn.get("status", "") or "")
            turn_error = _format_turn_error(completed_turn.get("error"))

            if turn_status == "completed":
                result.success = True
                result.final_message = messages.final_message()
                break

            if turn_status == "interrupted":
                if watchdog.budget_exhausted:
                    raise CodexOrphanToolError(
                        tool_name=watchdog.last_orphan_tool_name,
                        tool_id=watchdog.last_orphan_tool_id,
                        age_seconds=watchdog.last_orphan_age,
                        orphan_count=watchdog.orphan_event_count,
                    )

                current_prompt = (
                    f"The previous turn's tool (tool_name={watchdog.last_orphan_tool_name}) "
                    f"stalled for >{watchdog.last_orphan_age:.0f}s. Do not run that tool again; "
                    "continue the remaining work using alternative approaches."
                )
                logger.info(
                    "Orphan recovery: sending corrective prompt for tool '%s' (attempt %d/%d)",
                    watchdog.last_orphan_tool_name,
                    watchdog.orphan_event_count,
                    watchdog.max_orphan_events,
                )
                continue

            result.success = False
            if turn_status == "failed":
                result.error = prefix_codex_error_code(turn_error or "turn/completed status=failed")
            else:
                result.error = prefix_codex_error_code(f"Unexpected turn status: {turn_status or 'unknown'}")
            break

    except CodexOrphanToolError:
        result.duration_seconds = round(time.monotonic() - start, 2)
        result.exit_code = client.returncode or 0
        tokens.apply_to(result, config)
        raise
    except asyncio.TimeoutError:
        result.success = False
        result.error = f"Timed out after {config.timeout_seconds}s"
    except _CodexAppServerRequestError as exc:
        result.success = False
        result.error = _app_server_error_message(client, exc)
    except _CodexAppServerError as exc:
        result.success = False
        result.error = _app_server_error_message(client, exc)
    except FileNotFoundError:
        result.success = False
        result.error = "codex binary not found - is codex-cli installed?"
    except Exception as exc:  # noqa: BLE001
        result.success = False
        result.error = _app_server_error_message(client, exc)
        logger.exception("App-server transport failed")
    finally:
        if thread_id:
            with suppress(Exception):
                await client.thread_archive(thread_id)
        await client.close()

    result.duration_seconds = round(time.monotonic() - start, 2)
    result.exit_code = client.returncode or 0
    tokens.apply_to(result, config)

    logger.info(
        "App-server turn %s tokens_in=%d tokens_out=%d cost=$%.4f %.1fs",
        "OK" if result.success else "FAILED",
        result.input_tokens,
        result.output_tokens,
        result.cost_usd,
        result.duration_seconds,
    )
    return result


async def execute_codex(
    prompt: str,
    cwd: str,
    config: Optional[CodexConfig] = None,
    codex_home: Optional[Path] = None,
    *,
    progress_callback: Callable[..., Any] | None = None,
    orphan_timeout_seconds: float = 300.0,
    orphan_max_events: int = 2,
) -> CodexResult:
    """Execute a codex prompt via ``codex app-server --listen stdio://``."""
    if config is None:
        config = CodexConfig()

    log_codex_cli_version(logger)

    owns_home = codex_home is None
    if owns_home:
        codex_home = create_codex_home(config)

    attempts = 1 + max(int(config.max_retries), 0)
    aggregate = CodexResult(model=config.model)
    last_result = CodexResult(model=config.model)
    overall_start = time.monotonic()

    try:
        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(
                    _execute_once(
                        prompt,
                        cwd,
                        config,
                        codex_home,
                        orphan_timeout_seconds=orphan_timeout_seconds,
                        orphan_max_events=orphan_max_events,
                        progress_callback=progress_callback,
                    ),
                    timeout=config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                result = CodexResult(model=config.model)
                result.success = False
                result.error = f"Timed out after {config.timeout_seconds}s"

            result.retry_count = attempt
            _accumulate_attempt_totals(aggregate, result)
            aggregate.retry_count = attempt

            if result.success:
                aggregate.success = True
                aggregate.error = ""
                aggregate.duration_seconds = round(time.monotonic() - overall_start, 2)
                return aggregate

            last_result = result
            if attempt < attempts - 1:
                wait = 2 ** attempt
                logger.warning(
                    "App-server attempt %d/%d failed (%s) - retrying in %ds",
                    attempt + 1,
                    attempts,
                    result.error,
                    wait,
                )
                await asyncio.sleep(wait)
    finally:
        if owns_home and codex_home is not None:
            cleanup_codex_home(codex_home)

    aggregate.success = False
    aggregate.duration_seconds = round(time.monotonic() - overall_start, 2)
    aggregate.error = last_result.error
    aggregate.exit_code = last_result.exit_code
    return aggregate
