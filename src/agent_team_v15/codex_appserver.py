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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .async_subprocess_compat import (
    create_subprocess_exec_compat,
    create_subprocess_shell_compat,
    terminate_process_group,
)
from .codex_captures import CodexCaptureMetadata, CodexCaptureSession
from .codex_cli import log_codex_cli_version, prefix_codex_error_code, resolve_codex_binary
from .codex_transport import (
    CODEX_LOCKFILE_GUARD_PROFILE_NAME,
    CodexConfig,
    CodexResult,
    cleanup_codex_home,
    create_codex_home,
    _ensure_lockfile_write_guard_profile,
)
from .config import ObserverConfig

logger = logging.getLogger(__name__)

# Linux signal delivery is sub-millisecond and there's no WSL/Docker-Desktop
# IO boundary to cross, so the historical 2.0s grace is over-budgeted.
# Windows keeps the original value because taskkill /T can take noticeably
# longer to traverse the process tree on heavily-loaded shells.
_PROCESS_TERMINATION_TIMEOUT_SECONDS = 1.0 if sys.platform != "win32" else 2.0
_CODEX_RIPGREP_CONFIG_FILENAME = "ripgrep-config"
_CODEX_RIPGREP_CONFIG_TEXT = "--max-columns=20000\n--max-columns-preview\n"
_THREAD_START_SANDBOX_MODE_ALIASES = {
    "readOnly": "read-only",
    "read-only": "read-only",
    "workspaceWrite": "workspace-write",
    "workspace-write": "workspace-write",
    "dangerFullAccess": "danger-full-access",
    "danger-full-access": "danger-full-access",
}
_CLIENT_INFO = (
    ("name", "agent-team-v15"),
    ("title", "agent-team-v15"),
    ("version", "15.0.0"),
)
_CODEX_OBSERVER_RUN_ID = (
    os.environ.get("AGENT_TEAM_RUN_ID")
    or os.environ.get("AGENT_TEAM_BUILD_ID")
    or f"pid-{os.getpid()}-{int(time.time())}"
)


class CodexTerminalTurnError(Exception):
    """Phase 5 closeout Stage 2 §M.M5 follow-up #3 — codex_appserver session
    ended abnormally before the target ``turn/completed`` arrived.

    Raised by :func:`_wait_for_turn_completion` on:
      * ``thread/archive`` notification for the target thread before any
        ``turn/completed`` matched.
      * Transport stdout EOF (subprocess exited or pipe closed) — pushed
        as a sentinel by :meth:`_CodexAppServerTransport._read_stdout`'s
        ``finally`` block; :meth:`next_notification` recognises the
        sentinel and raises this error.

    Distinct from :class:`CodexOrphanToolError` (per-tool budget
    exhaustion); this is per-session abnormal termination.

    Empirically observed on Stage 2 Rerun 3 fresh smoke 1 milestone-1
    Wave B (run-dir
    ``v18 test runs/phase-5-8a-stage-2b-rerun3-fresh-20260501-01-…``):
    Codex's appserver emitted ``item/started commandExecution`` (no
    matching ``item/completed``), the orphan-monitor sent
    ``turn/interrupt`` and emitted ``codex_orphan_observed``, then
    ``thread/archive`` arrived. ``_wait_for_turn_completion`` only
    breaks on ``turn/completed`` — every other method ``continue``\\s
    the drain loop. With no further messages possible (thread archived,
    transport drained), ``await client.next_notification()`` blocks
    indefinitely. The wave_executor's poll loop runs forever without
    the task entering ``done`` state; tier-2/tier-3/tier-4 predicate
    fires never reach the wave-fail path because they require
    ``task.cancel()`` to actually return from the await.

    The wave_executor's :func:`_invoke_provider_wave_with_watchdog`
    translates this exception to a :class:`WaveWatchdogTimeoutError`
    with ``timeout_kind`` selected from the live watchdog state via
    :func:`_synthesize_watchdog_timeout_from_state` — preserving the
    canonical hang-report evidence path required by §O.4 row contracts.
    """

    def __init__(
        self,
        reason: str,
        *,
        thread_id: str = "",
        turn_id: str = "",
        repeated_eof: bool = False,
    ) -> None:
        self.reason = reason
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.repeated_eof = bool(repeated_eof)
        super().__init__(
            f"Codex turn {turn_id or '<unknown>'}@thread "
            f"{thread_id or '<unknown>'} ended without turn/completed: "
            f"{reason}"
        )


class CodexAppserverUnstableError(CodexTerminalTurnError):
    """Repeated transport stdout EOF after the provider retry budget exhausted."""

    repeated_eof: bool = True

    def __init__(
        self,
        reason: str,
        *,
        thread_id: str = "",
        turn_id: str = "",
        milestone_id: str = "",
    ) -> None:
        self.milestone_id = milestone_id
        super().__init__(
            reason,
            thread_id=thread_id,
            turn_id=turn_id,
            repeated_eof=True,
        )


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


class CodexAppserverPreflightError(RuntimeError):
    """Raised when the Codex app-server cannot complete a minimal turn."""


# Phase 5 closeout Stage 2 §M.M5 follow-up #3 — sentinel pushed into
# ``_notifications`` queue when the transport's stdout reader hits EOF.
# Consumers calling :meth:`_CodexAppServerTransport.next_notification`
# detect the sentinel and raise :class:`CodexTerminalTurnError` so the
# wave_executor can map it to a canonical hang-report path instead of
# blocking forever on an empty queue.
_EOF_SENTINEL: dict = {"_codex_appserver_eof": True}


class _CodexAppServerError(RuntimeError):
    """Base transport/protocol error."""


class _CodexAppServerRequestError(_CodexAppServerError):
    """JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = int(code)
        self.data = data
        super().__init__(f"JSON-RPC error {self.code}: {message}")


class CodexDispatchError(RuntimeError):
    """Raised when transport dispatch prerequisites are invalid."""


@dataclass
class CodexNotificationEvent:
    """Parsed Codex app-server streaming notification of interest."""

    event_type: str
    thread_id: str
    turn_id: str
    payload: dict[str, Any]


_CODEX_OBSERVED_NOTIFICATION_METHODS = frozenset(
    {"turn/plan/updated", "turn/diff/updated"}
)


def parse_codex_notification(event: dict[str, Any]) -> CodexNotificationEvent | None:
    """Parse a raw JSON-RPC notification into a CodexNotificationEvent.

    Returns ``None`` for notifications outside the observed set or for
    malformed payloads.
    """
    if not isinstance(event, dict):
        return None
    method = str(event.get("method", "") or "")
    if method not in _CODEX_OBSERVED_NOTIFICATION_METHODS:
        return None
    params = event.get("params")
    if not isinstance(params, dict):
        return None
    return CodexNotificationEvent(
        event_type=method,
        thread_id=str(params.get("threadId", "") or ""),
        turn_id=str(params.get("turnId", "") or ""),
        payload=params,
    )


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

    def __init__(
        self,
        timeout_seconds: float = 300.0,
        max_orphan_events: int = 2,
        *,
        observer_config: "ObserverConfig | None" = None,
        requirements_text: str = "",
        wave_letter: str = "",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_orphan_events = max_orphan_events
        self._lock = threading.Lock()
        self.pending_tool_starts: dict[str, dict[str, Any]] = {}
        self.orphan_event_count: int = 0
        self.last_orphan_tool_name: str = ""
        self.last_orphan_tool_id: str = ""
        self.last_orphan_age: float = 0.0
        self.last_orphan_command_summary: str = ""
        self._registered_orphans: set[str] = set()
        # Observer configuration (read by Phase 4 peek/steer path).
        self.observer_config = observer_config
        self.requirements_text: str = requirements_text
        self.wave_letter: str = wave_letter
        # Runtime state populated by the streaming notification handler
        # (correction #3/#4 - instance attrs, not constructor params).
        self.codex_last_plan: list[dict[str, Any]] = []
        self.codex_latest_diff: str = ""
        self._observer_seen_payloads: set[tuple[str, str]] = set()
        self._observer_seen_steer_messages: set[tuple[str, str]] = set()

    def record_start(
        self,
        item_id: str,
        tool_name: str,
        *,
        command_summary: str = "",
    ) -> None:
        with self._lock:
            if tool_name == "commandExecution":
                self.pending_tool_starts[item_id] = {
                    "tool_name": tool_name,
                    "command_summary": command_summary,
                    "started_monotonic": time.monotonic(),
                }
        logger.debug(
            "[ORPHAN-WATCHDOG] record_start item_id=%s tool=%s pending_count=%d",
            item_id,
            tool_name,
            len(self.pending_tool_starts),
        )

    def record_complete(self, item_id: str) -> None:
        with self._lock:
            popped = self.pending_tool_starts.pop(item_id, None)
        logger.debug(
            "[ORPHAN-WATCHDOG] record_complete item_id=%s tool=%s pending_count=%d",
            item_id,
            (popped or {}).get("tool_name", "?"),
            len(self.pending_tool_starts),
        )

    def check_orphans(self) -> tuple[bool, str, str, float, str]:
        now = time.monotonic()
        with self._lock:
            for item_id, info in self.pending_tool_starts.items():
                if item_id in self._registered_orphans:
                    continue
                age = now - info["started_monotonic"]
                if age > self.timeout_seconds:
                    return True, info["tool_name"], item_id, age, str(info.get("command_summary", "") or "")
        return False, "", "", 0.0, ""

    def snapshot_pending(self) -> list[tuple[str, str, float]]:
        """Snapshot every pending item as ``(item_id, tool_name, age_seconds)``.

        Diagnostic helper for the transport's ``_monitor_orphans`` periodic
        logging path. Returns a point-in-time list so a single log line can
        summarise the watchdog's view without holding the lock across IO.
        Items already registered as orphans are included (age keeps growing
        so operators can see how long the wedge has persisted after interrupt).
        """
        now = time.monotonic()
        with self._lock:
            return [
                (
                    str(item_id),
                    str(info.get("tool_name", "") or ""),
                    max(0.0, now - float(info.get("started_monotonic", now))),
                )
                for item_id, info in self.pending_tool_starts.items()
            ]

    def register_orphan_event(
        self,
        tool_name: str,
        tool_id: str,
        age: float,
        *,
        command_summary: str = "",
    ) -> None:
        with self._lock:
            if tool_id and tool_id in self._registered_orphans:
                return
            if tool_id:
                self._registered_orphans.add(tool_id)
            self.orphan_event_count += 1
            self.last_orphan_tool_name = tool_name
            self.last_orphan_tool_id = tool_id
            self.last_orphan_age = age
            self.last_orphan_command_summary = command_summary

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


def _serialize_jsonrpc_response(request_id: Any, result: Any) -> bytes:
    """Serialize one newline-delimited JSON-RPC success response."""
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"


def _serialize_jsonrpc_error(request_id: Any, code: int, message: str) -> bytes:
    """Serialize one newline-delimited JSON-RPC error response."""
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": int(code), "message": str(message)},
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"


# Codex CLI 0.128.0 app-server schema splits legacy approval requests from
# item-scoped approval requests. Because turn/start sets approvalPolicy="never",
# any approval prompt that still arrives must be answered or the turn wedges.
_LEGACY_APPROVED_SERVER_REQUEST_METHODS = frozenset({
    "applyPatchApproval",
    "execCommandApproval",
})

_ITEM_ACCEPT_SERVER_REQUEST_METHODS = frozenset({
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
})

_PERMISSION_APPROVAL_REQUEST_METHOD = "item/permissions/requestApproval"


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
    codex_home.mkdir(parents=True, exist_ok=True)
    ripgrep_config_path = codex_home / _CODEX_RIPGREP_CONFIG_FILENAME
    ripgrep_config_path.write_text(_CODEX_RIPGREP_CONFIG_TEXT, encoding="utf-8")

    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    env["CODEX_QUIET_MODE"] = "1"
    env["RIPGREP_CONFIG_PATH"] = str(ripgrep_config_path)
    env["RUST_BACKTRACE"] = "1"
    env["RUST_LOG"] = "info"
    return env


async def _spawn_appserver_process(
    *,
    cwd: str,
    env: dict[str, str],
) -> asyncio.subprocess.Process:
    """Spawn ``codex app-server --listen stdio://``.

    ``start_new_session=True`` puts Codex in its own POSIX process group so
    ``terminate_process_group`` can reap MCP grandchildren (npm exec
    @upstash/context7-mcp, npm exec @modelcontextprotocol/...) on teardown.
    Silently ignored on Windows (taskkill /T handles tree kill there).
    """
    cmd, use_shell = _build_appserver_command()
    if use_shell:
        return await create_subprocess_shell_compat(
            subprocess.list2cmdline(cmd),
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )

    return await create_subprocess_exec_compat(
        *cmd,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,
    )


def _build_appserver_command() -> tuple[list[str], bool]:
    """Return the argv and shell mode for ``codex app-server``."""
    codex_bin = resolve_codex_binary()
    cmd = [codex_bin, "app-server", "--listen", "stdio://"]
    use_shell = sys.platform == "win32" and codex_bin.lower().endswith((".cmd", ".bat"))
    return cmd, use_shell


def _cwd_propagation_check_enabled(config: CodexConfig | None) -> bool:
    return bool(getattr(config, "cwd_propagation_check_enabled", False))


def _resolve_dispatch_cwd(cwd: str, config: CodexConfig) -> str:
    if not _cwd_propagation_check_enabled(config):
        return cwd

    cwd_path = Path(cwd).resolve()
    if not cwd_path.exists():
        raise CodexDispatchError(f"cwd does not exist: {cwd_path}")
    if not cwd_path.is_dir():
        raise CodexDispatchError(f"cwd is not a directory: {cwd_path}")

    logger.info("Codex dispatch cwd (resolved): %s", cwd_path)
    return str(cwd_path)


def _thread_start_sandbox_mode(config: CodexConfig) -> str | None:
    if bool(getattr(config, "lockfile_write_guard_enabled", False)):
        return None
    if not bool(getattr(config, "sandbox_writable_enabled", False)):
        return None

    sandbox_mode = str(getattr(config, "sandbox_mode", "workspaceWrite") or "workspaceWrite").strip()
    wire_value = _THREAD_START_SANDBOX_MODE_ALIASES.get(sandbox_mode)
    if wire_value is None:
        allowed = ", ".join(sorted(_THREAD_START_SANDBOX_MODE_ALIASES))
        raise CodexDispatchError(
            f"Invalid codex_sandbox_mode: {sandbox_mode!r}. Must be one of: {allowed}"
        )
    return wire_value


def _thread_start_permissions(config: CodexConfig) -> dict[str, Any] | None:
    if not bool(getattr(config, "lockfile_write_guard_enabled", False)):
        return None
    return {
        "type": "profile",
        "id": CODEX_LOCKFILE_GUARD_PROFILE_NAME,
        "modifications": None,
    }


def _warn_if_cwd_mismatch(
    *,
    expected_cwd: str,
    thread_result: dict[str, Any],
    config: CodexConfig,
) -> None:
    if not _cwd_propagation_check_enabled(config):
        return

    observed_cwd = str(thread_result.get("cwd", "") or "").strip()
    if not observed_cwd:
        return

    try:
        observed_path = Path(observed_cwd).resolve()
        expected_path = Path(expected_cwd).resolve()
    except Exception:  # noqa: BLE001
        return

    if observed_path != expected_path:
        logger.warning(
            "CODEX-CWD-MISMATCH-001: orchestrator cwd %s != codex app-server cwd %s",
            expected_path,
            observed_path,
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
        killer = await create_subprocess_exec_compat(
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

    # On Linux, ``proc.kill()`` only signals the immediate child. Codex
    # spawns MCP grandchildren (npm exec @upstash/context7-mcp, npm exec
    # @modelcontextprotocol/...) which leak as orphans unless we tear
    # down the whole process group. ``start_new_session=True`` at spawn
    # time made the child a session leader; killpg cleans the rest.
    # Windows tree kill happens via taskkill below.
    if sys.platform != "win32" and pid is not None:
        await terminate_process_group(int(pid), timeout=timeout_seconds)

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        return
    except Exception as exc:  # noqa: BLE001
        logger.debug("Initial subprocess wait failed for PID %s: %s", pid, exc)

    if sys.platform == "win32" and pid is not None:
        await _kill_process_tree_windows(int(pid), timeout_seconds=timeout_seconds)
        with suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)


async def _perform_app_server_teardown(
    proc: asyncio.subprocess.Process | None,
    *,
    pid: int | None,
    use_shell: bool,
    timeout_seconds: float = 5.0,
) -> None:
    """Best-effort parent teardown for tracked app-server processes."""
    if proc is None:
        return
    if getattr(proc, "returncode", None) is not None:
        return

    if sys.platform == "win32":
        if use_shell and pid is not None:
            logger.info("[APP-SERVER-TEARDOWN] taskkill /T /F for tracked PID %s", pid)
            await _kill_process_tree_windows(int(pid), timeout_seconds=timeout_seconds)
            with suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
            return
        terminate = getattr(proc, "terminate", None)
        if callable(terminate):
            with suppress(Exception):
                terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
            return
        except Exception:
            pass
        await _terminate_subprocess(proc, timeout_seconds=timeout_seconds)
        return

    # Linux/POSIX: tear down the whole process group so MCP grandchildren
    # (npm @upstash/context7-mcp, @modelcontextprotocol/...) are reaped
    # alongside the codex parent. Mirrors taskkill /T on Windows.
    if pid is not None:
        logger.info("[APP-SERVER-TEARDOWN] killpg SIGTERM for tracked PID %s (process group)", pid)
        await terminate_process_group(int(pid), timeout=timeout_seconds)
    with suppress(Exception):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        return
    except Exception:
        pass
    with suppress(Exception):
        proc.kill()
    with suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)


class _CodexJSONRPCTransport:
    """Own the app-server subprocess and multiplex JSON-RPC over stdio."""

    def __init__(
        self,
        *,
        cwd: str,
        codex_home: Path,
        app_server_teardown_enabled: bool = False,
        protocol_logger: Any | None = None,
    ) -> None:
        self.cwd = cwd
        self.codex_home = codex_home
        self._app_server_teardown_enabled = bool(app_server_teardown_enabled)
        self._use_shell = False
        self._app_server_pid: int | None = None
        self.protocol_logger = protocol_logger
        self.process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._request_id = 0
        self._closing = False
        self._stderr_lines: deque[str] = deque(maxlen=200)

    @property
    def returncode(self) -> int | None:
        return None if self.process is None else self.process.returncode

    @property
    def process_pid(self) -> int | None:
        return self._app_server_pid or (None if self.process is None else getattr(self.process, "pid", None))

    def stderr_excerpt(self, limit: int = 300) -> str:
        collapsed = " ".join(line.strip() for line in self._stderr_lines if line.strip())
        return collapsed[:limit]

    async def start(self) -> None:
        if self.process is not None:
            return
        env = _build_transport_env(self.codex_home)
        _, self._use_shell = _build_appserver_command()
        self.process = await _spawn_appserver_process(cwd=self.cwd, env=env)
        self._app_server_pid = getattr(self.process, "pid", None)
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
            if self._app_server_teardown_enabled:
                try:
                    await _perform_app_server_teardown(
                        self.process,
                        pid=self._app_server_pid,
                        use_shell=self._use_shell,
                    )
                except Exception as exc:  # pragma: no cover - defensive logging only
                    logger.warning(
                        "[APP-SERVER-TEARDOWN] tracked teardown failed for PID %s: %s",
                        self._app_server_pid,
                        exc,
                    )
                    await _terminate_subprocess(self.process)
            else:
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=_PROCESS_TERMINATION_TIMEOUT_SECONDS)
                except Exception:
                    await _terminate_subprocess(self.process)

        stderr_task = self._stderr_task
        if stderr_task is not None and not stderr_task.done():
            try:
                await asyncio.wait_for(stderr_task, timeout=2.0)
            except asyncio.TimeoutError:
                stderr_task.cancel()

        stdout_task = self._stdout_task
        if stdout_task is not None and not stdout_task.done():
            stdout_task.cancel()

        tasks = [task for task in (stdout_task, stderr_task) if task is not None]
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
                if self.protocol_logger is not None:
                    self.protocol_logger.log_out(payload)
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
        msg = await self._notifications.get()
        # Phase 5 closeout Stage 2 §M.M5 follow-up #3 — recognise the EOF
        # sentinel pushed by ``_read_stdout``'s ``finally`` and convert
        # to a typed terminal-turn error so consumers (e.g.
        # ``_wait_for_turn_completion``) can break out of their drain
        # loops instead of blocking forever.
        if isinstance(msg, dict) and msg.get("_codex_appserver_eof") is True:
            raise CodexTerminalTurnError(
                "app-server stdout EOF — subprocess exited",
            )
        return msg

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        """Respond to a server-to-client JSON-RPC request.

        Codex app-server sends approval requests that expect typed decision
        replies. Our ``turn/start`` sets ``approvalPolicy="never"`` — a
        non-interactive policy — so we auto-approve every incoming approval
        request for consistency with that stated intent. Unknown
        server-initiated methods still receive JSON-RPC ``-32601 Method not
        found`` instead of being silently queued as notifications.
        """
        method = str(message.get("method", "") or "")
        request_id = message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        params = params or {}

        if method in _LEGACY_APPROVED_SERVER_REQUEST_METHODS:
            logger.info(
                "[APP-SERVER-REQ] auto-approved %s (callId=%s conversationId=%s)",
                method,
                params.get("callId", ""),
                params.get("conversationId", ""),
            )
            response = _serialize_jsonrpc_response(request_id, {"decision": "approved"})
        elif method in _ITEM_ACCEPT_SERVER_REQUEST_METHODS:
            logger.info(
                "[APP-SERVER-REQ] auto-accepted %s (threadId=%s turnId=%s itemId=%s)",
                method,
                params.get("threadId", ""),
                params.get("turnId", ""),
                params.get("itemId", ""),
            )
            response = _serialize_jsonrpc_response(request_id, {"decision": "accept"})
        elif method == _PERMISSION_APPROVAL_REQUEST_METHOD:
            permissions = params.get("permissions")
            if not isinstance(permissions, dict):
                permissions = {}
            logger.info(
                "[APP-SERVER-REQ] auto-granted permissions request "
                "(threadId=%s turnId=%s itemId=%s)",
                params.get("threadId", ""),
                params.get("turnId", ""),
                params.get("itemId", ""),
            )
            response = _serialize_jsonrpc_response(
                request_id,
                {
                    "scope": "session",
                    "permissions": permissions,
                },
            )
        else:
            logger.warning(
                "[APP-SERVER-REQ] Unknown server-to-client method %r (id=%s); "
                "responding method-not-found. If this method should be handled, "
                "add it to an approval method set or a dedicated "
                "handler.",
                method,
                request_id,
            )
            response = _serialize_jsonrpc_error(
                request_id,
                -32601,
                f"Method not found: {method}",
            )

        try:
            async with self._write_lock:
                if self.process is None or self.process.stdin is None:
                    logger.warning(
                        "[APP-SERVER-REQ] Cannot respond to %r (id=%s): stdin unavailable",
                        method,
                        request_id,
                    )
                    return
                if self.protocol_logger is not None:
                    self.protocol_logger.log_out(response)
                self.process.stdin.write(response)
                await self.process.stdin.drain()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "[APP-SERVER-REQ] Failed to write response to %r (id=%s): %s",
                method,
                request_id,
                exc,
            )

    async def _read_stdout(self) -> None:
        if self.process is None or self.process.stdout is None:
            return

        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                if self.protocol_logger is not None:
                    self.protocol_logger.log_in(line)
                message = _parse_jsonrpc_line(line)
                if "method" in message:
                    if "id" in message:
                        # JSON-RPC server-to-client request — respond
                        # immediately. Treating this path as a notification
                        # (the pre-fix behaviour) made the app-server wait
                        # forever for a reply that never came, wedging the
                        # turn (Codex 0.122 approval / Guardian flow).
                        await self._handle_server_request(message)
                    else:
                        # JSON-RPC notification — queue for consumers.
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
            # Phase 5 closeout Stage 2 §M.M5 follow-up #3 — push an EOF
            # sentinel so consumers awaiting ``next_notification`` can
            # detect the session end and raise ``CodexTerminalTurnError``
            # instead of blocking forever on a queue that will never
            # receive another message. ``_notifications`` is an
            # ``asyncio.Queue`` (no native close); the sentinel is a
            # marker dict that ``next_notification`` recognises.
            with suppress(Exception):
                self._notifications.put_nowait(_EOF_SENTINEL)

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

    def __init__(
        self,
        *,
        cwd: str,
        config: CodexConfig,
        codex_home: Path,
        protocol_logger: Any | None = None,
    ) -> None:
        self.cwd = cwd
        self.config = config
        self.codex_home = codex_home
        self.transport = _CodexJSONRPCTransport(
            cwd=cwd,
            codex_home=codex_home,
            app_server_teardown_enabled=bool(getattr(config, "app_server_teardown_enabled", False)),
            protocol_logger=protocol_logger,
        )

    @property
    def returncode(self) -> int | None:
        return self.transport.returncode

    @property
    def process_pid(self) -> int | None:
        return self.transport.process_pid

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
        # Per Codex app-server docs, ``model`` is optional on ``thread/start``
        # and Codex falls back to the user's ``~/.codex/config.toml`` default
        # when omitted. Omitting it here decouples the orchestrator from
        # the OpenAI model treadmill (gpt-5.1-codex-max → gpt-5.4 → gpt-5.5 →
        # …), so the user's installed Codex CLI picks the current model.
        # Callers that need to pin a specific model can do so via Codex's
        # config or by explicitly setting it in CodexConfig and re-adding it
        # to params here behind a feature flag.
        params = {
            "cwd": self.cwd,
            "approvalPolicy": "never",
            "personality": "pragmatic",
        }
        permissions = _thread_start_permissions(self.config)
        sandbox_mode = _thread_start_sandbox_mode(self.config)
        if permissions is not None:
            params["permissions"] = permissions
            logger.info(
                "Codex dispatch permissions profile override: %s (lockfile-write guard)",
                permissions["id"],
            )
        elif sandbox_mode is not None:
            params["sandbox"] = sandbox_mode
            logger.info("Codex dispatch sandbox override: %s (flag-enabled)", sandbox_mode)
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

    async def turn_steer(self, thread_id: str, turn_id: str, message: str) -> None:
        """Inject a mid-turn steering message into an in-flight turn.

        Fail-open: any transport error is logged and swallowed. The observer
        must never be able to break the wave by failing to steer.
        """
        if not thread_id or not turn_id or not message:
            return
        try:
            await self.send_request(
                "turn/steer",
                {
                    "threadId": thread_id,
                    "expectedTurnId": turn_id,
                    "input": [{"type": "text", "text": message}],
                },
            )
        except Exception as exc:  # noqa: BLE001 - fail-open by contract
            logger.warning("turn/steer dispatch failed (fail-open): %s", exc)

    async def thread_archive(self, thread_id: str) -> dict[str, Any]:
        return await self.send_request("thread/archive", {"threadId": thread_id})

    async def next_notification(self) -> dict[str, Any]:
        return await self.transport.next_notification()


async def turn_steer(
    client: _CodexAppServerClient,
    thread_id: str,
    turn_id: str,
    message: str,
) -> None:
    """Module-level turn/steer wrapper for observer integration tests."""
    await client.turn_steer(thread_id, turn_id, message)


def _write_codex_observer_log(
    cwd: str,
    *,
    wave_letter: str,
    source: str,
    message: str,
    log_only: bool,
    did_steer: bool,
) -> None:
    try:
        if not cwd:
            return
        log_path = Path(cwd) / ".agent-team" / "observer_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        would_steer = bool(message)
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": _CODEX_OBSERVER_RUN_ID,
            "wave": wave_letter,
            "file": "",
            "verdict": "issue" if would_steer else "ok",
            "confidence": 1.0 if would_steer else 0.0,
            "message": message,
            "source": source,
            "log_only": log_only,
            "would_interrupt": would_steer,
            "did_interrupt": did_steer,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except Exception as exc:  # noqa: BLE001 - observer logging is fail-open
        logger.warning("Codex observer log write failed (fail-open): %s", exc)


def _observer_payload_signature(payload: Any) -> str:
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return str(payload)


def _plan_items_to_lines(plan: list[Any]) -> list[str]:
    plan_lines: list[str] = []
    for plan_item in list(plan):
        if isinstance(plan_item, str):
            plan_lines.append(plan_item)
        elif isinstance(plan_item, dict):
            plan_lines.append(
                str(
                    plan_item.get("step")
                    or plan_item.get("text")
                    or plan_item.get("description")
                    or plan_item
                )
            )
        else:
            plan_lines.append(str(plan_item))
    return plan_lines


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
    progress_callback: Callable[..., Any] | None = None,
) -> bool:
    """Poll the watchdog and send ``turn/interrupt`` on first orphan.

    Emits diagnostic logs so wedge post-mortems can distinguish these three
    classes (see R1B1-server-req-fix 2026-04-22 where the transport watchdog
    seemingly never fired but the wave-executor's 600s wedge did):

    * transport watchdog fired interrupt → logs at WARNING
    * transport never saw any pending items → periodic INFO snapshot shows
      empty ``pending_tool_starts`` throughout the turn
    * transport saw pending items but they never aged past ``timeout_seconds``
      → periodic INFO snapshot shows items + their current age

    Phase 5 closeout Stage 2 §M.M5 / §O.4.6 follow-up — when the watchdog
    detects a stale tool, emits a ``codex_orphan_observed`` progress event
    BEFORE sending ``turn/interrupt``. The wave_executor's
    :class:`_WaveWatchdogState` recognises this message_type and flips
    ``codex_orphan_observed=True`` so its tier-3 productive-tool-idle
    predicate fires within ``tool_call_idle_timeout_seconds`` even when
    wave_executor's own ``record_progress`` never saw an
    ``item/started commandExecution`` event from this turn (the case
    empirically reproduced on the wedged 2B smoke 1/3 — Codex stalled
    pre-emit-of-commandExecution so wave_executor's pending_tool_starts
    stayed empty).
    """
    # Floor at 10ms rather than 1s — production callers pass 60s (far above
    # the floor) so this doesn't change their cadence, but it lets unit tests
    # exercise the snapshot + orphan paths without waiting whole seconds.
    interval = max(check_interval_seconds, 0.01)
    logger.info(
        "[ORPHAN-MONITOR] started thread=%s turn=%s timeout=%.0fs interval=%.2fs",
        thread_id,
        turn_id,
        watchdog.timeout_seconds,
        interval,
    )
    poll_count = 0
    # Log a pending-items snapshot every N polls so we have periodic visibility
    # without flooding. At default interval=60s this is one snapshot every
    # ~5 minutes — enough to reconstruct a wedge's progression post-mortem.
    snapshot_every = 5
    try:
        while True:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info(
                    "[ORPHAN-MONITOR] cancelled thread=%s turn=%s polls=%d",
                    thread_id,
                    turn_id,
                    poll_count,
                )
                raise
            poll_count += 1
            is_orphan, tool_name, tool_id, age, command_summary = watchdog.check_orphans()
            if not is_orphan:
                if poll_count % snapshot_every == 0:
                    pending = watchdog.snapshot_pending()
                    logger.info(
                        "[ORPHAN-MONITOR] poll=%d thread=%s turn=%s pending=%d timeout=%.0fs detail=%s",
                        poll_count,
                        thread_id,
                        turn_id,
                        len(pending),
                        watchdog.timeout_seconds,
                        [(iid, name, round(a, 1)) for iid, name, a in pending[:10]],
                    )
                continue
            watchdog.register_orphan_event(
                tool_name,
                tool_id,
                age,
                command_summary=command_summary,
            )
            pending = watchdog.snapshot_pending()
            logger.warning(
                "Orphan tool detected: name=%s id=%s age=%.0fs (event %d/%d) - "
                "sending turn/interrupt. pending_count=%d all_pending=%s",
                tool_name,
                tool_id,
                age,
                watchdog.orphan_event_count,
                watchdog.max_orphan_events,
                len(pending),
                [(iid, nm, round(a, 1)) for iid, nm, a in pending[:10]],
            )
            # Phase 5 closeout Stage 2 §M.M5 / §O.4.6 follow-up — surface
            # the stale-tool signal to the wave_executor's watchdog state
            # BEFORE sending turn/interrupt. The progress_callback chain
            # leads to ``_WaveWatchdogState.record_progress``, which flips
            # ``codex_orphan_observed=True``. If turn/interrupt fails to
            # produce an ``item/completed``, the wave_executor's tier-3
            # predicate uses this flag to fire within
            # ``tool_call_idle_timeout_seconds`` from ``started_monotonic``.
            await _emit_progress(
                progress_callback,
                message_type="codex_orphan_observed",
                tool_name=tool_name,
                tool_id=tool_id,
                event_kind="other",
            )
            await _send_turn_interrupt(client, thread_id, turn_id)
            return True
    finally:
        logger.info(
            "[ORPHAN-MONITOR] exited thread=%s turn=%s polls=%d orphan_events=%d",
            thread_id,
            turn_id,
            poll_count,
            watchdog.orphan_event_count,
        )


def _item_field(item: Any, field: str, default: str = "") -> str:
    if isinstance(item, dict):
        return str(item.get(field, default) or default)
    return str(getattr(item, field, default) or default)


def _summarize_command(command: str, *, max_chars: int = 80) -> str:
    collapsed = " ".join(str(command or "").split())
    if not collapsed:
        return ""
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 3].rstrip() + "..."


def _item_command_summary(item: Any) -> str:
    return _summarize_command(_item_field(item, "command"))


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
    capture_session: CodexCaptureSession | None = None,
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
    if capture_session is not None:
        capture_session.observe_event({"method": method, "params": params})

    if method == "item/started":
        item = params.get("item", {})
        item_id = _item_field(item, "id")
        tool_name = _item_field(item, "name") or _item_field(item, "tool") or _item_field(item, "type")
        command_summary = _item_command_summary(item)
        if item_id:
            watchdog.record_start(
                item_id,
                tool_name,
                command_summary=command_summary,
            )
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
        return

    if method == "turn/plan/updated":
        plan = params.get("plan")
        if isinstance(plan, list):
            watchdog.codex_last_plan = list(plan)
        return

    if method == "turn/diff/updated":
        diff = params.get("diff")
        if isinstance(diff, str):
            watchdog.codex_latest_diff = diff
        return


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
    capture_session: CodexCaptureSession | None = None,
) -> dict[str, Any]:
    """Drain notifications until the target turn finishes."""
    while True:
        try:
            message = await client.next_notification()
        except CodexTerminalTurnError as exc:
            # Phase 5 closeout Stage 2 Rerun 3 clean smoke 1 follow-up —
            # ``_CodexJSONRPCTransport.next_notification`` raises
            # ``CodexTerminalTurnError`` on the EOF sentinel without
            # caller context (transport has no thread/turn IDs at the
            # queue layer). Re-raise with the IDs from this scope so
            # ``dispatch_exception`` in ``response.json::metadata``
            # carries the canonical IDs the protocol log already
            # captured. Pre-fix evidence (run-dir
            # ``v18 test runs/phase-5-8a-stage-2b-rerun3-clean-20260501-205232-…``):
            # metadata reported ``Codex turn <unknown>@thread <unknown>
            # ended without turn/completed: app-server stdout EOF —
            # subprocess exited`` while the protocol log showed
            # ``threadId=019de55a-7665-…`` and
            # ``turnId=019de55a-7680-…`` for the same wave.
            # Defensive: only fill IDs when both are empty so the
            # ``thread/archive``-before-``turn/completed`` raise (which
            # already passes correct IDs from the message params) is
            # never overwritten by the caller's parameters.
            if not exc.thread_id and not exc.turn_id:
                raise CodexTerminalTurnError(
                    exc.reason,
                    thread_id=thread_id,
                    turn_id=turn_id,
                ) from exc
            raise
        _process_streaming_event(
            message,
            watchdog,
            tokens,
            progress_callback,
            messages,
            capture_session,
        )

        observer_cfg = getattr(watchdog, "observer_config", None)
        observer_enabled = bool(
            observer_cfg is not None
            and getattr(observer_cfg, "enabled", False)
            and getattr(observer_cfg, "codex_notification_observer_enabled", True)
        )
        method = message.get("method")
        # Phase 5: real rule-based plan/diff observer checks for Codex waves.
        # Fail-open - any exception (including ImportError) returns no steer.
        try:
            if observer_enabled:
                from agent_team_v15.codex_observer_checks import (
                    check_codex_diff,
                    check_codex_plan,
                )

            steer_msg = ""
            observer_source = ""
            params = message.get("params", {})
            if not isinstance(params, dict):
                params = {}
            if observer_enabled and method == "turn/diff/updated":
                diff = params.get("diff")
                signature = _observer_payload_signature(diff)
                payload_key = ("diff_event", signature)
                if (
                    isinstance(diff, str)
                    and diff
                    and payload_key not in watchdog._observer_seen_payloads
                    and getattr(observer_cfg, "codex_diff_check_enabled", True)
                ):
                    watchdog._observer_seen_payloads.add(payload_key)
                    steer_msg = check_codex_diff(
                        diff,
                        getattr(watchdog, "wave_letter", "") or "",
                    )
                    observer_source = "diff_event"
            elif observer_enabled and method == "turn/plan/updated":
                plan = params.get("plan")
                signature = _observer_payload_signature(plan)
                payload_key = ("plan_event", signature)
                if (
                    isinstance(plan, list)
                    and plan
                    and payload_key not in watchdog._observer_seen_payloads
                    and getattr(observer_cfg, "codex_plan_check_enabled", True)
                ):
                    watchdog._observer_seen_payloads.add(payload_key)
                    steer_msg = check_codex_plan(
                        _plan_items_to_lines(plan),
                        getattr(watchdog, "wave_letter", "") or "",
                    )
                    observer_source = "plan_event"

            did_steer = False
            duplicate_steer = False
            if steer_msg:
                steer_key = (observer_source, steer_msg)
                if steer_key in watchdog._observer_seen_steer_messages:
                    duplicate_steer = True
                else:
                    watchdog._observer_seen_steer_messages.add(steer_key)
            if (
                steer_msg
                and observer_enabled
                and not getattr(observer_cfg, "log_only", True)
                and not duplicate_steer
            ):
                await turn_steer(client, thread_id, turn_id, steer_msg)
                did_steer = True
                logger.info(
                    "Observer steered Codex Wave %s: %s",
                    getattr(watchdog, "wave_letter", "?"),
                    steer_msg[:120],
                )
            elif steer_msg and not duplicate_steer:
                logger.info(
                    "Observer (log_only) would steer Codex Wave %s: %s",
                    getattr(watchdog, "wave_letter", "?"),
                    steer_msg[:120],
                )
            if (
                observer_enabled
                and observer_source
                and not duplicate_steer
            ):
                _write_codex_observer_log(
                    str(getattr(client, "cwd", "") or ""),
                    wave_letter=getattr(watchdog, "wave_letter", "") or "",
                    source=observer_source,
                    message=steer_msg,
                    log_only=bool(getattr(observer_cfg, "log_only", True)),
                    did_steer=did_steer,
                )
        except Exception:
            logger.warning("Codex observer check failed (fail-open)", exc_info=True)

        if message.get("method") == "error":
            logger.warning(
                "App-server error notification: %s",
                _format_turn_error(message.get("params", {}).get("error")),
            )
            continue

        # Phase 5 closeout Stage 2 §M.M5 follow-up #3 — terminal protocol
        # signal: ``thread/archive`` for the target thread BEFORE any
        # ``turn/completed`` matched. Without this break-out the drain
        # loop blocks indefinitely on ``await client.next_notification()``
        # because no further messages will arrive (the appserver
        # archived the thread and the subprocess will eventually exit).
        # Empirically observed on Stage 2 Rerun 3 fresh smoke 1
        # milestone-1 Wave B — Codex's orphan-monitor sent
        # ``turn/interrupt``, then the appserver emitted
        # ``thread/archive`` and stopped emitting events. The
        # wave_executor's poll loop kept running but the dispatch task
        # was stuck on this blocking await. Raising
        # ``CodexTerminalTurnError`` lets wave_executor map the abnormal
        # termination to a canonical hang-report path.
        if message.get("method") == "thread/archive":
            params = message.get("params", {})
            archived_thread_id = ""
            if isinstance(params, dict):
                archived_thread_id = str(params.get("threadId", "") or "")
            # Match the target thread (or accept ``thread/archive`` with
            # no threadId — defensive). Any other thread's archive is
            # irrelevant to this turn's completion path; ``continue``.
            if not archived_thread_id or archived_thread_id == thread_id:
                raise CodexTerminalTurnError(
                    "thread/archive received before turn/completed",
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
            continue

        if message.get("method") != "turn/completed":
            continue

        params = message.get("params", {})
        if not isinstance(params, dict):
            continue
        observed_thread_id = params.get("threadId")
        if observed_thread_id is not None and observed_thread_id != thread_id:
            continue
        turn = params.get("turn", {})
        if isinstance(turn, dict) and turn.get("id") == turn_id:
            return turn


async def _preflight_codex_appserver(
    client: Any,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Run one bounded no-op turn before dispatching real work.

    The cache lives on the client instance, which is the concrete appserver
    session boundary in this transport.
    """

    state = str(getattr(client, "_codex_appserver_preflight_state", "") or "")
    if state == "passed":
        return dict(getattr(client, "_codex_appserver_preflight_initialize_result", {}) or {})
    if state == "failed":
        cached_error = getattr(client, "_codex_appserver_preflight_error", None)
        if isinstance(cached_error, CodexAppserverPreflightError):
            raise cached_error
        raise CodexAppserverPreflightError("cached Codex appserver preflight failure")

    try:
        bounded_timeout = min(max(float(timeout), 0.001), 30.0)
    except (TypeError, ValueError):
        bounded_timeout = 30.0

    async def _run_preflight() -> dict[str, Any]:
        try:
            init_result = await client.initialize()
        except Exception as exc:  # noqa: BLE001 - typed boundary for callers
            raise CodexAppserverPreflightError(f"initialize failed: {exc}") from exc

        try:
            thread_result = await client.thread_start()
            thread = thread_result.get("thread", {}) if isinstance(thread_result, dict) else {}
            thread_id = str(thread.get("id", "") or "")
            if not thread_id:
                raise CodexAppserverPreflightError("thread/start returned no thread id")

            turn_result = await client.turn_start(
                thread_id,
                "Reply with the literal string OK",
            )
            turn = turn_result.get("turn", {}) if isinstance(turn_result, dict) else {}
            turn_id = str(turn.get("id", "") or "")
            if not turn_id:
                raise CodexAppserverPreflightError("turn/start returned no turn id")

            while True:
                message = await client.next_notification()
                if not isinstance(message, dict):
                    continue
                if message.get("method") == "error":
                    error = message.get("params", {}).get("error") if isinstance(message.get("params"), dict) else None
                    raise CodexAppserverPreflightError(
                        f"error notification during preflight: {_format_turn_error(error)}"
                    )
                if message.get("method") != "turn/completed":
                    continue
                params = message.get("params", {})
                if not isinstance(params, dict):
                    continue
                observed_thread_id = params.get("threadId")
                if observed_thread_id is not None and observed_thread_id != thread_id:
                    continue
                completed_turn = params.get("turn", {})
                if not isinstance(completed_turn, dict) or completed_turn.get("id") != turn_id:
                    continue
                status = str(completed_turn.get("status", "") or "")
                if status != "completed":
                    raise CodexAppserverPreflightError(
                        f"turn/completed status={status or 'unknown'}"
                    )
                return init_result if isinstance(init_result, dict) else {}
        except CodexAppserverPreflightError:
            raise
        except Exception as exc:  # noqa: BLE001 - typed boundary for callers
            raise CodexAppserverPreflightError(f"turn preflight failed: {exc}") from exc

    try:
        result = await asyncio.wait_for(_run_preflight(), timeout=bounded_timeout)
    except asyncio.TimeoutError as exc:
        error = CodexAppserverPreflightError(
            f"preflight timed out after {bounded_timeout:.1f}s waiting for turn/completed"
        )
        setattr(client, "_codex_appserver_preflight_state", "failed")
        setattr(client, "_codex_appserver_preflight_error", error)
        raise error from exc
    except CodexAppserverPreflightError as exc:
        setattr(client, "_codex_appserver_preflight_state", "failed")
        setattr(client, "_codex_appserver_preflight_error", exc)
        raise

    setattr(client, "_codex_appserver_preflight_state", "passed")
    setattr(client, "_codex_appserver_preflight_initialize_result", dict(result))
    return dict(result)


def _app_server_error_message(client: _CodexAppServerClient, exc: Exception) -> str:
    base = _format_protocol_error(exc)
    stderr = client.stderr_excerpt()
    if stderr and stderr not in base:
        return f"{base}; stderr: {stderr}"
    return base


def _legacy_turn_interrupt_prompt(watchdog: _OrphanWatchdog) -> str:
    return (
        f"The previous turn's tool (tool_name={watchdog.last_orphan_tool_name}) "
        f"stalled for >{watchdog.last_orphan_age:.0f}s. Do not run that tool again; "
        "continue the remaining work using alternative approaches."
    )


def _build_turn_interrupt_prompt(watchdog: _OrphanWatchdog, config: CodexConfig) -> str:
    try:
        tool_name = watchdog.last_orphan_tool_name or "commandExecution"
        timeout_seconds = int(round(watchdog.timeout_seconds or watchdog.last_orphan_age or 0))
        command_summary = str(watchdog.last_orphan_command_summary or "").strip()
        if command_summary:
            return (
                f"The previous invocation of `{tool_name}` running command `{command_summary}` stalled "
                f"for >{timeout_seconds}s and was interrupted. You may continue using `{tool_name}` for "
                "other commands. Do NOT retry the stalled command; treat its effects as already applied "
                "(any files it created or modified are present on disk). Continue with the remaining "
                "work, including any validation, build, or test steps you would normally perform."
            )
        return (
            f"The previous invocation of `{tool_name}` stalled for >{timeout_seconds}s and was interrupted. "
            f"You may continue using `{tool_name}` for other commands. Do NOT retry that stalled "
            "invocation; treat its effects as already applied (any files it created or modified are "
            "present on disk). Continue with the remaining work, including any validation, build, or "
            "test steps you would normally perform."
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Refined interrupt prompt failed; falling back to legacy text: %s", exc)
        return _legacy_turn_interrupt_prompt(watchdog)


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
    capture_session: CodexCaptureSession | None = None,
    existing_thread_id: str = "",
    preserve_thread: bool = False,
    observer_config: "ObserverConfig | None" = None,
    requirements_text: str = "",
    wave_letter: str = "",
) -> CodexResult:
    """Run one app-server session and parse the turn result."""
    result = CodexResult(model=config.model)
    start = time.monotonic()
    tokens = _TokenAccumulator()
    watchdog = _OrphanWatchdog(
        timeout_seconds=orphan_timeout_seconds,
        max_orphan_events=orphan_max_events,
        observer_config=observer_config,
        requirements_text=requirements_text,
        wave_letter=wave_letter,
    )
    messages = _MessageAccumulator()
    client = _CodexAppServerClient(
        cwd=cwd,
        config=config,
        codex_home=codex_home,
        protocol_logger=None if capture_session is None else capture_session.protocol_logger,
    )
    thread_id = ""
    turn_id = ""
    current_prompt = prompt
    terminal_turn_error: CodexTerminalTurnError | None = None
    cleanup_thread_archive_after_failure = False

    try:
        try:
            await client.start()
        except Exception as exc:  # noqa: BLE001 - startup is part of preflight
            raise CodexAppserverPreflightError(f"startup failed: {exc}") from exc
        init_result = await _preflight_codex_appserver(client)
        logger.info(
            "App-server initialized: userAgent=%s codexHome=%s",
            init_result.get("userAgent", "unknown"),
            init_result.get("codexHome", "unknown"),
        )

        if existing_thread_id:
            thread_id = existing_thread_id
            logger.info("Thread reused: id=%s", thread_id)
        else:
            thread_result = await client.thread_start()
            thread = thread_result.get("thread", {})
            thread_id = str(thread.get("id", "") or "")
            _warn_if_cwd_mismatch(
                expected_cwd=cwd,
                thread_result=thread_result,
                config=config,
            )
            logger.info("Thread started: id=%s", thread_id)
        result.thread_id = thread_id

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
                    # Phase 5 closeout Stage 2 §M.M5 / §O.4.6 follow-up —
                    # thread progress_callback so the orphan-monitor can
                    # emit ``codex_orphan_observed`` to wave_executor when
                    # it detects a stale tool. See ``_monitor_orphans``
                    # docstring for the wave_executor-side wiring.
                    progress_callback=progress_callback,
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
                    capture_session=capture_session,
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

                if bool(getattr(config, "turn_interrupt_message_refined_enabled", False)):
                    current_prompt = _build_turn_interrupt_prompt(watchdog, config)
                else:
                    current_prompt = _legacy_turn_interrupt_prompt(watchdog)
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
    except CodexDispatchError:
        raise
    except CodexAppserverPreflightError:
        raise
    except CodexTerminalTurnError as exc:
        # Phase 5 closeout Stage 2 §M.M5 follow-up #3 — terminal-turn
        # propagation gap closed. Pre-fix the broad ``except Exception``
        # below would convert ``CodexTerminalTurnError`` (raised by
        # ``_wait_for_turn_completion`` on ``thread/archive`` or stdout
        # EOF before ``turn/completed``) into a failed
        # :class:`CodexResult` with ``success=False`` and a generic
        # error message. That swallowed the typed error before it could
        # reach the wave_executor's synth path
        # (:func:`_synthesize_watchdog_timeout_from_state`), losing the
        # canonical hang-report evidence and falling into the caller's
        # generic ``except Exception`` (no hang report).
        # The early re-raise lets the typed error escape this layer
        # cleanly. The ``finally`` block below still runs the bounded
        # ``thread_archive`` cleanup + ``client.close()``.
        terminal_turn_error = exc
        raise
    except FileNotFoundError:
        result.success = False
        result.error = "codex binary not found - is codex-cli installed?"
    except Exception as exc:  # noqa: BLE001
        result.success = False
        result.error = _app_server_error_message(client, exc)
        logger.exception("App-server transport failed")
    finally:
        if thread_id and not preserve_thread:
            cleanup_thread_archive_after_failure = terminal_turn_error is not None
            # Phase 5 closeout Stage 2 §M.M5 follow-up #3 — bound the
            # cleanup ``thread/archive`` call so it can NEVER become the
            # next indefinite hang. Pre-fix the ``await
            # client.thread_archive(thread_id)`` could block forever if
            # the appserver subprocess is alive but unresponsive (e.g.,
            # post-orphan-monitor wedge state). 10s is generous for a
            # responsive appserver; the ``with suppress(Exception)``
            # absorbs the ``asyncio.TimeoutError`` so cleanup failure
            # never masks the upstream wave-fail.
            with suppress(Exception):
                await asyncio.wait_for(
                    client.thread_archive(thread_id),
                    timeout=10.0,
                )
        await client.close()
        if terminal_turn_error is not None:
            diagnostic_session = capture_session
            owns_diagnostic_session = False
            try:
                if diagnostic_session is None:
                    # B12 — caller did not thread capture_metadata, so we
                    # synthesise a forensic stem (timestamp-based ms-precision
                    # so concurrent orphan recoveries don't collide) instead
                    # of the legacy literal "auto"/"unknown" defaults that
                    # silently overwrote diagnostic artifacts across wedges.
                    diagnostic_session = CodexCaptureSession(
                        metadata=CodexCaptureMetadata(
                            milestone_id=f"orphan-{int(time.time() * 1000)}",
                            wave_letter=str(wave_letter or "").strip().upper() or "ORPHAN",
                        ),
                        cwd=cwd,
                        model=str(config.model or ""),
                        reasoning_effort=str(config.reasoning_effort or ""),
                        spawn_cwd=cwd,
                        subprocess_argv=None,
                    )
                    owns_diagnostic_session = True
                diagnostic_path = diagnostic_session.write_terminal_diagnostic(
                    exception=terminal_turn_error,
                    thread_id=terminal_turn_error.thread_id or thread_id,
                    turn_id=terminal_turn_error.turn_id or turn_id,
                    codex_process_pid=getattr(client, "process_pid", None),
                    returncode=client.returncode,
                    stderr_tail=client.stderr_excerpt(limit=4096),
                    watchdog=watchdog,
                    cleanup_thread_archive_after_failure=cleanup_thread_archive_after_failure,
                )
                logger.error("Codex terminal-turn diagnostic written: %s", diagnostic_path)
            except Exception as diagnostic_exc:  # noqa: BLE001
                logger.warning(
                    "Codex terminal-turn diagnostic failed (non-fatal): %s",
                    diagnostic_exc,
                )
            finally:
                if owns_diagnostic_session and diagnostic_session is not None:
                    diagnostic_session.close()

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
    capture_enabled: bool = False,
    capture_metadata: CodexCaptureMetadata | None = None,
    existing_thread_id: str = "",
    preserve_thread: bool = False,
    observer_config: "ObserverConfig | None" = None,
    requirements_text: str = "",
    wave_letter: str = "",
) -> CodexResult:
    """Execute a codex prompt via ``codex app-server --listen stdio://``."""
    if config is None:
        config = CodexConfig()
    orphan_timeout_seconds = float(
        getattr(config, "orphan_timeout_seconds", orphan_timeout_seconds) or orphan_timeout_seconds
    )

    cwd = _resolve_dispatch_cwd(cwd, config)
    log_codex_cli_version(logger)

    owns_home = codex_home is None
    if owns_home:
        codex_home = create_codex_home(config, project_root=Path(cwd))
    elif bool(getattr(config, "lockfile_write_guard_enabled", False)):
        _ensure_lockfile_write_guard_profile(codex_home, project_root=Path(cwd))

    attempts = 1 + max(int(config.max_retries), 0)
    aggregate = CodexResult(model=config.model)
    last_result = CodexResult(model=config.model)
    overall_start = time.monotonic()
    capture_session: CodexCaptureSession | None = None
    capture_exception: BaseException | None = None

    if (
        getattr(config, "protocol_capture_enabled", False)
        and capture_metadata is None
    ):
        # B12 — orphan-prefix forensic stem replaces the legacy "auto"/"unknown"
        # literals when the caller did not thread capture_metadata. Two
        # concurrent orphan recoveries get distinct ms-precision stems.
        capture_metadata = CodexCaptureMetadata(
            milestone_id=f"orphan-{int(time.time() * 1000)}",
            wave_letter=str(wave_letter or "").strip().upper() or "ORPHAN",
        )
        capture_enabled = True

    if capture_enabled and capture_metadata is not None:
        subprocess_argv: list[str] | None = None
        try:
            subprocess_argv, _ = _build_appserver_command()
        except Exception:
            subprocess_argv = None
        capture_session = CodexCaptureSession(
            metadata=capture_metadata,
            cwd=cwd,
            model=str(config.model or ""),
            reasoning_effort=str(config.reasoning_effort or ""),
            spawn_cwd=cwd,
            subprocess_argv=subprocess_argv,
        )
        capture_session.capture_prompt(prompt)

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
                        capture_session=capture_session,
                        existing_thread_id=existing_thread_id,
                        preserve_thread=preserve_thread,
                        observer_config=observer_config,
                        requirements_text=requirements_text,
                        wave_letter=wave_letter,
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
                aggregate.thread_id = result.thread_id
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
    except BaseException as exc:
        capture_exception = exc
        raise
    finally:
        if capture_session is not None:
            capture_session.finalize(
                codex_result=aggregate if aggregate.success or aggregate.error else last_result,
                exception=capture_exception,
            )
            capture_session.close()
        if owns_home and codex_home is not None:
            cleanup_codex_home(codex_home)

    aggregate.success = False
    aggregate.duration_seconds = round(time.monotonic() - overall_start, 2)
    aggregate.error = last_result.error
    aggregate.exit_code = last_result.exit_code
    if not aggregate.thread_id:
        aggregate.thread_id = last_result.thread_id
    return aggregate
