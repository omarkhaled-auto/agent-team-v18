"""Codex Transport — async subprocess wrapper for ``codex exec``.

Manages the full lifecycle of a single codex-cli invocation:
temp CODEX_HOME creation, config.toml generation, stdin prompt delivery,
JSONL result parsing, token/cost accounting, and cleanup.

Designed for use by the wave executor as a drop-in execution backend.

Validated against codex-cli 0.66.0.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from .codex_cli import log_codex_cli_version, prefix_codex_error_code, resolve_codex_binary

logger = logging.getLogger(__name__)
_PROCESS_TERMINATION_TIMEOUT_SECONDS = 2.0


# ---------------------------------------------------------------------------
# Configuration & result data classes
# ---------------------------------------------------------------------------

@dataclass
class CodexConfig:
    """Runtime configuration for a codex exec invocation."""

    model: str = "gpt-5.4"
    timeout_seconds: int = 5400
    max_retries: int = 1
    reasoning_effort: str = "high"
    context7_enabled: bool = True
    context7_package: str = "@upstash/context7-mcp"
    # Pricing per 1 M tokens — caller can override for new models.
    # gpt-5.1-codex-max was migrated to gpt-5.4; both kept for backward compat.
    pricing: dict = field(default_factory=lambda: {
        "gpt-5.4": {
            "input": 2.00,
            "cached_input": 0.50,
            "output": 8.00,
        },
        "gpt-5.1-codex-max": {
            "input": 2.00,
            "cached_input": 0.50,
            "output": 8.00,
        },
    })


@dataclass
class CodexResult:
    """Outcome of one ``codex exec`` run."""

    success: bool = False
    exit_code: int = -1
    duration_seconds: float = 0.0
    # Token counters — populated from JSONL ``usage`` objects.
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    # File lists are set by the *caller* via manifest diff, not by us.
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    final_message: str = ""
    error: str = ""
    retry_count: int = 0


# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

def is_codex_available() -> bool:
    """Return *True* if the ``codex`` binary is on PATH."""
    return shutil.which("codex") is not None


def check_prerequisites() -> list[str]:
    """Validate that codex-cli and its dependencies are ready.

    Returns a list of human-readable issues.  Empty list means all clear.
    """
    issues: list[str] = []

    # 1. codex binary
    if not is_codex_available():
        issues.append("codex CLI not found on PATH (install via npm i -g @openai/codex)")

    # 2. Node.js >= 18
    try:
        node_out = subprocess.check_output(
            ["node", "--version"], text=True, timeout=10,
        ).strip()
        # e.g. "v20.11.0" -> 20
        major = int(node_out.lstrip("v").split(".")[0])
        if major < 18:
            issues.append(f"Node.js >= 18 required (found {node_out})")
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        issues.append("Node.js not found or version unreadable (>= 18 required)")

    return issues


# ---------------------------------------------------------------------------
# CODEX_HOME management
# ---------------------------------------------------------------------------

def create_codex_home(config: CodexConfig) -> Path:
    """Create a temporary CODEX_HOME directory with a ``config.toml``.

    Copies the user's existing ChatGPT login credentials from ``~/.codex/``
    into the temp home so codex CLI auth (preferred) works without needing
    OPENAI_API_KEY.  If no login exists, codex will fall back to
    OPENAI_API_KEY at runtime if it's set in the environment.

    The caller is responsible for calling :func:`cleanup_codex_home` when done.
    """
    def _make_home_dir() -> Path:
        root = Path.home() / ".codex" / "memories" / "tmp"
        root.mkdir(parents=True, exist_ok=True)
        for _ in range(8):
            candidate = root / f"codex_home_{uuid4().hex}"
            try:
                candidate.mkdir()
                return candidate
            except FileExistsError:
                continue
        raise RuntimeError("Unable to allocate a temporary CODEX_HOME directory")

    home = _make_home_dir()

    # Copy from user's ~/.codex/ — auth, identity, and config.toml verbatim
    # so the temp home inherits trust levels, sandbox settings, MCP servers,
    # and any feature flags the user has configured.  Without this, codex
    # executes but can't write files (no trust + restricted sandbox).
    # Model and reasoning effort are overridden via codex CLI -c flags at
    # invocation time (see execute_codex), so the inherited config.toml is
    # left untouched here.
    user_codex = Path.home() / ".codex"
    for src_name in ("auth.json", "installation_id", "config.toml"):
        src = user_codex / src_name
        if src.is_file():
            try:
                shutil.copy2(src, home / src_name)
                logger.debug("Copied %s into temp CODEX_HOME", src_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not copy %s into CODEX_HOME: %s", src_name, exc)

    # If user had no config.toml, create a minimal one with our overrides.
    if not (home / "config.toml").is_file():
        lines: list[str] = [
            f'model = "{config.model}"',
            f'model_reasoning_effort = "{config.reasoning_effort}"',
        ]
        if config.context7_enabled:
            lines.append("")
            lines.append("[mcp_servers.context7]")
            lines.append('command = "npx"')
            lines.append(f'args = ["-y", "{config.context7_package}"]')
        try:
            (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            shutil.rmtree(home, ignore_errors=True)
            raise
    logger.debug("Created CODEX_HOME at %s", home)
    return home


def cleanup_codex_home(codex_home: Path) -> None:
    """Remove a temporary CODEX_HOME directory, ignoring errors."""
    if not codex_home.exists():
        return
    try:
        shutil.rmtree(codex_home)
        if codex_home.exists():
            logger.debug("CODEX_HOME still exists after cleanup attempt: %s", codex_home)
        else:
            logger.debug("Cleaned up CODEX_HOME at %s", codex_home)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to remove CODEX_HOME %s (non-fatal): %s", codex_home, exc)


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _parse_jsonl(output: str) -> list[dict]:
    """Parse newline-delimited JSON from codex stdout.

    Non-JSON lines (e.g. progress spinners) are silently skipped.
    """
    events: list[dict] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            logger.debug("Skipped non-JSON line: %.120s", line)
    return events


def _extract_token_usage(result: CodexResult, events: list[dict]) -> None:
    """Sum token usage across all JSONL events that carry a ``usage`` dict."""
    for ev in events:
        usage = ev.get("usage")
        if not isinstance(usage, dict):
            continue
        result.input_tokens += int(usage.get("input_tokens", 0))
        result.output_tokens += int(usage.get("output_tokens", 0))
        result.reasoning_tokens += int(usage.get("reasoning_tokens", 0))
        result.cached_input_tokens += int(usage.get("cached_input_tokens", 0))


def _compute_cost(result: CodexResult, config: CodexConfig) -> float:
    """Compute estimated cost in USD from token counts and pricing table.

    Separates uncached from cached input tokens to avoid double-counting.
    """
    model_pricing = config.pricing.get(config.model)
    if not model_pricing:
        logger.warning("No pricing data for model %s — cost will be $0", config.model)
        return 0.0

    input_price = model_pricing.get("input", 0.0)
    cached_price = model_pricing.get("cached_input", 0.0)
    output_price = model_pricing.get("output", 0.0)

    # input_tokens from the API typically includes cached — separate them.
    uncached_input = max(result.input_tokens - result.cached_input_tokens, 0)

    cost = (
        (uncached_input * input_price / 1_000_000)
        + (result.cached_input_tokens * cached_price / 1_000_000)
        + (result.output_tokens * output_price / 1_000_000)
    )
    return round(cost, 6)


def _extract_final_message(result: CodexResult, events: list[dict]) -> None:
    """Pull the last substantive text from the JSONL event stream.

    Looks for ``item.completed`` events containing an ``agent_message``,
    then falls back to any event with a ``text`` or ``message`` field that
    is long enough to be meaningful.
    """
    # Walk in reverse — latest events are most relevant.
    for ev in reversed(events):
        # Primary: item.completed → agent_message
        if ev.get("type") == "item.completed":
            item = ev.get("item", {})
            msg = item.get("agent_message") or item.get("text", "")
            if isinstance(msg, str) and len(msg) > 20:
                result.final_message = msg
                return
            # Check content array inside the item
            for content in item.get("content", []):
                if isinstance(content, dict):
                    text = content.get("text", "")
                    if isinstance(text, str) and len(text) > 20:
                        result.final_message = text
                        return

    # Fallback: any event with a meaningful text/message field.
    for ev in reversed(events):
        for key in ("text", "message"):
            val = ev.get(key)
            if isinstance(val, str) and len(val) > 40:
                result.final_message = val
                return


def _summarize_stderr(stderr_text: str, limit: int = 300) -> str:
    """Collapse stderr into a single bounded line for fallback diagnostics."""
    collapsed = " ".join(stderr_text.split())
    return collapsed[:limit]


async def _emit_progress(
    progress_callback: Callable[..., Any] | None,
    *,
    message_type: str,
    tool_name: str = "",
    tool_id: str = "",
    event_kind: str = "other",
) -> None:
    """Best-effort progress callback runner used by streamed Codex execution.

    tool_id and event_kind are forwarded so downstream watchdog state can pair
    item.started / item.completed events for orphan detection.
    """
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
        # Older callbacks (claude-only paths) accept only message_type+tool_name.
        try:
            maybe_awaitable = progress_callback(
                message_type=message_type,
                tool_name=tool_name,
            )
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        except Exception as exc:  # pragma: no cover - defensive logging only
            logger.debug("Codex progress callback failed: %s", exc)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("Codex progress callback failed: %s", exc)


def _progress_from_event(event: dict[str, Any]) -> tuple[str, str, str, str]:
    """Extract message_type, tool_name, tool_id, and event_kind from one event.

    event_kind is one of: "start" (item.started), "complete" (item.completed),
    or "other". tool_id is the codex item id when present (used to pair starts
    with completes for orphan-tool detection).
    """
    message_type = str(event.get("type") or "codex_event")
    tool_name = ""
    tool_id = ""
    event_kind = "other"
    if message_type == "item.started":
        event_kind = "start"
    elif message_type == "item.completed":
        event_kind = "complete"

    item = event.get("item")
    if isinstance(item, dict):
        tool_name = str(
            item.get("name")
            or item.get("tool_name")
            or item.get("type")
            or ""
        )
        tool_id = str(item.get("id") or "")

    if not tool_name:
        tool_name = str(event.get("tool_name") or event.get("name") or "")

    return message_type, tool_name, tool_id, event_kind


async def _drain_stream(
    reader: asyncio.StreamReader | None,
    chunks: list[str],
    *,
    progress_callback: Callable[..., Any] | None = None,
) -> None:
    """Read a subprocess stream line-by-line, preserving output order."""
    if reader is None:
        return

    while True:
        line = await reader.readline()
        if not line:
            return
        decoded = line.decode("utf-8", errors="replace")
        chunks.append(decoded)

        stripped = decoded.strip()
        if not stripped or progress_callback is None:
            continue

        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            await _emit_progress(progress_callback, message_type="codex_stdout", tool_name="")
            continue

        if isinstance(event, dict):
            message_type, tool_name, tool_id, event_kind = _progress_from_event(event)
            await _emit_progress(
                progress_callback,
                message_type=message_type,
                tool_name=tool_name,
                tool_id=tool_id,
                event_kind=event_kind,
            )


async def _communicate_with_progress(
    proc: asyncio.subprocess.Process,
    prompt_bytes: bytes,
    *,
    progress_callback: Callable[..., Any],
) -> tuple[str, str]:
    """Stream Codex stdout/stderr while forwarding JSONL progress events."""
    if proc.stdin is not None:
        proc.stdin.write(prompt_bytes)
        await proc.stdin.drain()
        proc.stdin.close()
        wait_closed = getattr(proc.stdin, "wait_closed", None)
        if callable(wait_closed):
            with contextlib.suppress(Exception):
                await wait_closed()

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_task = asyncio.create_task(
        _drain_stream(proc.stdout, stdout_chunks, progress_callback=progress_callback)
    )
    stderr_task = asyncio.create_task(_drain_stream(proc.stderr, stderr_chunks))
    pending_exc: BaseException | None = None
    try:
        await proc.wait()
    except BaseException as exc:  # includes cancellation
        pending_exc = exc
    finally:
        if pending_exc is not None:
            stdout_task.cancel()
            stderr_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    if pending_exc is not None:
        raise pending_exc

    return "".join(stdout_chunks), "".join(stderr_chunks)


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
    """Best-effort termination that must not block watchdog teardown forever."""
    if proc is None:
        return
    if timeout_seconds is None:
        timeout_seconds = _PROCESS_TERMINATION_TIMEOUT_SECONDS

    pid = getattr(proc, "pid", None)
    with contextlib.suppress(Exception):
        proc.kill()

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        return
    except Exception as exc:  # noqa: BLE001
        logger.debug("Initial subprocess wait failed for PID %s: %s", pid, exc)

    if sys.platform == "win32" and pid is not None:
        await _kill_process_tree_windows(int(pid), timeout_seconds=timeout_seconds)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)


def _accumulate_attempt_totals(total: CodexResult, attempt: CodexResult) -> None:
    """Fold one attempt's usage/cost into the aggregate result."""
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


def _check_success(events: list[dict]) -> tuple[bool, str]:
    """Determine success or failure from JSONL events.

    Exit code is unreliable (always 0).  We scan for:
    - ``turn.completed`` → success
    - ``turn.failed``    → failure with error message

    Returns (success_bool, error_string).
    """
    has_completed = False
    failure_message = ""

    for ev in events:
        ev_type = ev.get("type", "")
        if ev_type == "turn.completed":
            has_completed = True
        elif ev_type == "turn.failed":
            err = ev.get("error", {})
            if isinstance(err, dict):
                failure_message = err.get("message", "turn.failed (no message)")
            elif isinstance(err, str):
                failure_message = err
            else:
                failure_message = "turn.failed (unknown error shape)"
            return False, failure_message

    if has_completed:
        return True, ""

    return False, "No completion event found in JSONL output"


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------

async def _execute_once(
    prompt: str,
    cwd: str,
    config: CodexConfig,
    codex_home: Path,
    *,
    progress_callback: Callable[..., Any] | None = None,
) -> CodexResult:
    """Run a single ``codex exec`` invocation and parse results."""
    result = CodexResult(model=config.model)
    start = time.monotonic()
    proc: asyncio.subprocess.Process | None = None

    # Resolve the codex binary path — on Windows, shutil.which returns
    # a .CMD wrapper that create_subprocess_exec cannot run directly.
    codex_bin = resolve_codex_binary()
    cmd = [
        codex_bin, "exec",
        "--json",
        "--full-auto",
        "--skip-git-repo-check",
        "--cd", cwd,
        "-m", config.model,
        # Override reasoning effort regardless of inherited config.toml.
        "-c", f"model_reasoning_effort={config.reasoning_effort}",
        "-",
    ]

    env = os.environ.copy()
    # On Windows, .CMD files need shell=True or COMSPEC; use COMSPEC approach
    use_shell = sys.platform == "win32" and codex_bin.lower().endswith((".cmd", ".bat"))
    env["CODEX_HOME"] = str(codex_home)
    env["CODEX_QUIET_MODE"] = "1"

    logger.info(
        "Running codex exec  model=%s  cwd=%s  timeout=%ds",
        config.model, cwd, config.timeout_seconds,
    )

    try:
        if use_shell:
            # Windows .CMD wrappers require shell execution
            import subprocess as _sp
            proc = await asyncio.create_subprocess_shell(
                _sp.list2cmdline(cmd),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

        if progress_callback is None:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=config.timeout_seconds,
            )
            stdout_text = stdout_bytes.decode("utf-8", errors="replace")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        else:
            stdout_text, stderr_text = await asyncio.wait_for(
                _communicate_with_progress(
                    proc,
                    prompt.encode("utf-8"),
                    progress_callback=progress_callback,
                ),
                timeout=config.timeout_seconds,
            )

        result.exit_code = proc.returncode or 0
        result.duration_seconds = round(time.monotonic() - start, 2)

        if stderr_text.strip():
            logger.debug("codex stderr (first 500 chars): %.500s", stderr_text)

    except asyncio.TimeoutError:
        result.duration_seconds = round(time.monotonic() - start, 2)
        result.error = f"Timed out after {config.timeout_seconds}s"
        logger.error("codex exec timed out after %ds", config.timeout_seconds)
        await _terminate_subprocess(proc)
        return result
    except asyncio.CancelledError:
        result.duration_seconds = round(time.monotonic() - start, 2)
        await _terminate_subprocess(proc)
        raise

    except FileNotFoundError:
        result.duration_seconds = round(time.monotonic() - start, 2)
        result.error = "codex binary not found — is codex-cli installed?"
        logger.error("FileNotFoundError: codex binary missing from PATH")
        return result

    except Exception as exc:  # noqa: BLE001
        result.duration_seconds = round(time.monotonic() - start, 2)
        result.error = f"Subprocess error: {exc}"
        logger.exception("Unexpected error running codex exec")
        return result

    # --- Parse JSONL output ---
    events = _parse_jsonl(stdout_text)
    logger.debug("Parsed %d JSONL events from codex stdout", len(events))

    # Token usage
    _extract_token_usage(result, events)
    result.cost_usd = _compute_cost(result, config)

    # Final message
    _extract_final_message(result, events)

    # Success determination (exit code is unreliable!)
    success, error_msg = _check_success(events)
    result.success = success
    if not success:
        stderr_excerpt = _summarize_stderr(stderr_text)
        if error_msg == "No completion event found in JSONL output" and stderr_excerpt:
            result.error = prefix_codex_error_code(f"{error_msg}; stderr: {stderr_excerpt}")
        else:
            result.error = prefix_codex_error_code(error_msg)

    logger.info(
        "codex exec %s  tokens_in=%d  tokens_out=%d  cost=$%.4f  %.1fs",
        "OK" if success else "FAILED",
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
) -> CodexResult:
    """Execute a codex prompt with automatic retry on transient failures.

    Parameters
    ----------
    prompt:
        The full prompt text to send via stdin.
    cwd:
        Working directory for the codex process (``--cd`` flag).
    config:
        Execution configuration.  Defaults to :class:`CodexConfig` defaults.
    codex_home:
        Pre-created CODEX_HOME path.  If *None*, a temporary one is created
        and cleaned up automatically.

    Returns an aggregate :class:`CodexResult` spanning all attempts. On
    success the token/cost totals include prior failed attempts; on
    exhaustion the error/exit code come from the final attempt.
    """
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
            result = await _execute_once(
                prompt,
                cwd,
                config,
                codex_home,
                progress_callback=progress_callback,
            )
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
                wait = 2 ** attempt  # 1s, 2s, 4s, ...
                logger.warning(
                    "Attempt %d/%d failed (%s) — retrying in %ds",
                    attempt + 1, attempts, result.error, wait,
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
