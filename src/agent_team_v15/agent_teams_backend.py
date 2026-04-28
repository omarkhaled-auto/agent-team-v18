"""Agent Teams execution backend abstraction layer.

Provides a unified ExecutionBackend protocol with two concrete
implementations:

- **CLIBackend** (Mode B): wraps existing subprocess-based orchestration.
- **AgentTeamsBackend** (Mode A): integrates with Claude Code Agent Teams
  for parallel task execution with peer messaging and self-claiming.

The ``create_execution_backend`` factory selects the correct backend
based on configuration, environment variables, and CLI availability,
with fail-fast behavior when Agent Teams is unavailable.

The ``detect_agent_teams_available`` helper performs a lightweight
availability check without constructing a full backend instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .async_subprocess_compat import create_subprocess_exec_compat

if TYPE_CHECKING:
    from .config import AgentTeamConfig
    from .scheduler import ExecutionWave

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ScheduledTask = Any  # Placeholder until scheduler integration is finalized

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaskResult:
    """Result of executing a single scheduled task."""

    task_id: str
    status: str  # "completed" | "failed" | "timeout"
    output: str
    error: str
    files_created: list[str]
    files_modified: list[str]
    duration_seconds: float = 0.0


@dataclass
class WaveResult:
    """Aggregated result of executing an entire wave of tasks."""

    wave_index: int
    task_results: list[TaskResult]
    all_succeeded: bool
    duration_seconds: float = 0.0


@dataclass
class TeamState:
    """Snapshot of the current execution backend state."""

    mode: str  # "agent_teams" | "cli"
    active: bool
    teammates: list[str]
    completed_tasks: list[str]
    failed_tasks: list[str]
    total_messages: int = 0


# ---------------------------------------------------------------------------
# ExecutionBackend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ExecutionBackend(Protocol):
    """Protocol that every execution backend must satisfy.

    Both CLIBackend and AgentTeamsBackend implement this interface so
    the orchestrator can treat them interchangeably.
    """

    async def initialize(self) -> TeamState:
        """Prepare the backend for task execution and return initial state."""
        ...

    async def execute_wave(self, wave: ExecutionWave) -> WaveResult:
        """Execute all tasks in *wave*, respecting parallelism limits."""
        ...

    async def execute_task(self, task: ScheduledTask) -> TaskResult:
        """Execute a single task and return its result."""
        ...

    async def send_context(self, context: str) -> bool:
        """Send contextual information to active teammates.

        Returns True if the context was delivered successfully.
        """
        ...

    async def shutdown(self) -> None:
        """Gracefully shut down the backend and release resources."""
        ...

    def supports_peer_messaging(self) -> bool:
        """Return whether this backend supports direct teammate messaging."""
        ...

    def supports_self_claiming(self) -> bool:
        """Return whether teammates can self-claim unassigned tasks."""
        ...


# ---------------------------------------------------------------------------
# CLIBackend (Mode B) -- subprocess-based execution
# ---------------------------------------------------------------------------


class CLIBackend:
    """Execution backend that wraps the existing subprocess orchestration.

    This is the default fallback backend.  Tasks are dispatched
    sequentially through the main orchestrator's subprocess mechanism.
    Peer messaging and self-claiming are not supported.
    """

    def __init__(self, config: AgentTeamConfig) -> None:
        self._config = config
        self._state = TeamState(
            mode="cli",
            active=False,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )

    # -- ExecutionBackend interface -----------------------------------------

    async def initialize(self) -> TeamState:
        """Initialize the CLI backend.

        Simply marks the state as active.  No external processes are
        started at this point -- the main orchestrator handles that.
        """
        self._state = TeamState(
            mode="cli",
            active=True,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )
        _logger.info("CLIBackend initialized (Mode B -- subprocess execution).")
        return self._state

    async def execute_wave(self, wave: ExecutionWave) -> WaveResult:
        """Execute all tasks in *wave* sequentially.

        In CLI mode each task is dispatched one at a time through the
        subprocess pipeline.  The method iterates over the wave's task
        IDs and produces a :class:`TaskResult` placeholder for each.
        """
        wave_start = time.monotonic()
        task_results: list[TaskResult] = []
        all_succeeded = True

        for task_id in wave.task_ids:
            task_start = time.monotonic()
            try:
                # In CLI mode the actual subprocess invocation is handled
                # by the main orchestrator.  Here we create a placeholder
                # result that the orchestrator fills in later.
                result = TaskResult(
                    task_id=task_id,
                    status="completed",
                    output="",
                    error="",
                    files_created=[],
                    files_modified=[],
                    duration_seconds=time.monotonic() - task_start,
                )
            except Exception as exc:
                _logger.error("CLIBackend: task %s failed: %s", task_id, exc)
                result = TaskResult(
                    task_id=task_id,
                    status="failed",
                    output="",
                    error=str(exc),
                    files_created=[],
                    files_modified=[],
                    duration_seconds=time.monotonic() - task_start,
                )
                all_succeeded = False
                self._state.failed_tasks.append(task_id)

            task_results.append(result)
            if result.status == "completed":
                self._state.completed_tasks.append(task_id)

        wave_duration = time.monotonic() - wave_start
        return WaveResult(
            wave_index=wave.wave_number,
            task_results=task_results,
            all_succeeded=all_succeeded,
            duration_seconds=wave_duration,
        )

    async def execute_task(self, task: ScheduledTask) -> TaskResult:
        """Create a placeholder TaskResult for a single task.

        In CLI mode the main orchestrator drives task execution; this
        method exists solely to satisfy the protocol.
        """
        task_id = getattr(task, "id", str(task))
        return TaskResult(
            task_id=task_id,
            status="completed",
            output="",
            error="",
            files_created=[],
            files_modified=[],
            duration_seconds=0.0,
        )

    async def send_context(self, context: str) -> bool:
        """No-op for CLI mode.  Always returns True."""
        return True

    async def shutdown(self) -> None:
        """Mark the CLI backend as inactive."""
        self._state.active = False
        _logger.info("CLIBackend shut down.")

    def supports_peer_messaging(self) -> bool:
        """CLI mode does not support peer messaging."""
        return False

    def supports_self_claiming(self) -> bool:
        """CLI mode does not support self-claiming."""
        return False


# ---------------------------------------------------------------------------
# AgentTeamsBackend (Mode A) -- Claude Code Agent Teams integration
# ---------------------------------------------------------------------------


class AgentTeamsBackend:
    """Execution backend using Claude Code Agent Teams for parallel work.

    This backend spawns Claude CLI teammate sub-processes that execute
    tasks in parallel.  Each teammate is a ``claude`` subprocess invoked
    with ``--print --output-format json`` so results can be parsed
    programmatically.

    Teammates communicate via a shared context directory: the lead
    writes context files that teammates read, and teammates write
    output files that the lead collects.

    The ``_active_teammates`` dict maps teammate names to their
    :class:`asyncio.subprocess.Process` handles for monitoring and
    cleanup.
    """

    # Sentinel used in output JSON when Claude does not report files
    _EMPTY_FILES: list[str] = []

    # Phase lead names (canonical, used as teammate names)
    PHASE_LEAD_NAMES: list[str] = [
        "wave-a-lead",    # Wave A - Claude architecture/schema
        "wave-d5-lead",   # Wave D5 - Claude frontend polish
        "wave-t-lead",    # Wave T - Claude test writing
        "wave-e-lead",    # Wave E - Claude verification/audit
    ]

    # Recognized inter-lead message types
    MESSAGE_TYPES: set[str] = {
        "REQUIREMENTS_READY",
        "ARCHITECTURE_READY",
        "WAVE_COMPLETE",
        "REVIEW_RESULTS",
        "DEBUG_FIX_COMPLETE",
        "WIRING_ESCALATION",
        "CONVERGENCE_COMPLETE",
        "TESTING_COMPLETE",
        "ESCALATION_REQUEST",
        "SYSTEM_STATE",
        "RESUME",
        "CODEX_WAVE_COMPLETE",  # orchestrator -> Claude lead: Codex turn finished
        "STEER_REQUEST",        # Claude lead -> orchestrator: steer active Codex turn
    }

    def __init__(self, config: AgentTeamConfig) -> None:
        self._config = config
        self._state = TeamState(
            mode="agent_teams",
            active=False,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )
        self._active_teammates: dict[str, Any] = {}  # name -> asyncio.subprocess.Process
        self._phase_leads: dict[str, Any] = {}       # lead name -> asyncio.subprocess.Process
        self._context_dir: Path | None = None  # shared context directory
        self._output_dir: Path | None = None   # teammate output directory
        self._claude_path: str = ""            # resolved path to claude CLI
        self._message_log: list[dict[str, str]] = []  # log of routed messages

    # -- Static helpers -----------------------------------------------------

    @staticmethod
    def _verify_claude_available() -> bool:
        """Check whether the ``claude`` CLI is installed and reachable.

        Returns True when ``claude --version`` exits with code 0.
        """
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def _resolve_claude_path() -> str:
        """Find the absolute path to the ``claude`` executable."""
        path = shutil.which("claude")
        return path if path else "claude"

    @staticmethod
    def _parse_claude_json_output(raw_output: str) -> dict[str, Any]:
        """Parse Claude CLI JSON output into a structured dict.

        Claude ``--output-format json`` emits one or more JSON objects
        (possibly as JSONL).  This method extracts the last complete
        JSON object which typically contains the final result.

        Returns a dict with keys: ``result``, ``cost_usd``,
        ``files_created``, ``files_modified``, ``error``.
        """
        parsed: dict[str, Any] = {
            "result": "",
            "cost_usd": 0.0,
            "files_created": [],
            "files_modified": [],
            "error": "",
        }

        if not raw_output.strip():
            return parsed

        # Try parsing as a single JSON object first
        try:
            data = json.loads(raw_output)
            return AgentTeamsBackend._extract_from_json(data, parsed)
        except json.JSONDecodeError:
            pass

        # Try JSONL: parse each line, keep the last valid object
        last_obj = None
        for line in raw_output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                last_obj = json.loads(line)
            except json.JSONDecodeError:
                continue

        if last_obj is not None:
            return AgentTeamsBackend._extract_from_json(last_obj, parsed)

        # Fallback: treat raw output as plain text result
        parsed["result"] = raw_output.strip()
        return parsed

    @staticmethod
    def _extract_from_json(
        data: Any, defaults: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract structured fields from a parsed JSON response."""
        result = dict(defaults)
        if not isinstance(data, dict):
            result["result"] = str(data)
            return result

        # Extract text result from various Claude output formats
        if "result" in data:
            result["result"] = str(data["result"])
        elif "content" in data:
            content = data["content"]
            if isinstance(content, str):
                result["result"] = content
            elif isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        texts.append(block)
                result["result"] = "\n".join(texts)
        elif "message" in data:
            result["result"] = str(data["message"])

        # Cost
        if "cost_usd" in data:
            try:
                result["cost_usd"] = float(data["cost_usd"])
            except (ValueError, TypeError):
                pass
        elif "total_cost_usd" in data:
            try:
                result["cost_usd"] = float(data["total_cost_usd"])
            except (ValueError, TypeError):
                pass

        # Files
        if "files_created" in data and isinstance(data["files_created"], list):
            result["files_created"] = [str(f) for f in data["files_created"]]
        if "files_modified" in data and isinstance(data["files_modified"], list):
            result["files_modified"] = [str(f) for f in data["files_modified"]]

        # Error
        if "error" in data:
            result["error"] = str(data["error"])
        elif "is_error" in data and data["is_error"]:
            result["error"] = result.get("result", "Unknown error")

        return result

    @staticmethod
    def _ensure_wave_d_path_guard_settings(cwd: str) -> None:
        """Write ``.claude/settings.json`` with the path-guard PreToolUse
        hooks (Wave D + audit-fix + audit-output).

        Idempotent: marker-keyed entries are rewritten to the current
        command in place (handles editable-install relocations). Other
        hook entries added by prior tooling are preserved verbatim.

        Three hook entries are managed by this writer:

        1. **Wave D path-guard** (``agent_team_v15_wave_d_path_guard``)
           — wave-letter-bound (``AGENT_TEAM_WAVE_LETTER``); restricts
           the Wave D dispatch to ``apps/web/**``. No-op for any wave
           other than ``D``.
        2. **Audit-fix path-guard** (``agent_team_v15_audit_fix_path_guard``)
           — finding-id-bound (``AGENT_TEAM_FINDING_ID``); restricts
           audit-fix dispatches to the per-finding allowlist supplied
           via ``AGENT_TEAM_ALLOWED_PATHS``. No-op when
           ``AGENT_TEAM_FINDING_ID`` is unset, so Wave A/B/C/D and
           non-fix audits / repairs pass through untouched.
        3. **Audit-output path-guard** (Phase 5.2 R-#47;
           ``agent_team_v15_audit_output_path_guard``) — audit-session-
           bound (``AGENT_TEAM_AUDIT_WRITER=1``); restricts auditor
           ``Write`` / ``Edit`` to ``{AGENT_TEAM_AUDIT_OUTPUT_ROOT}/
           audit-*_findings.json``, ``{AGENT_TEAM_AUDIT_OUTPUT_ROOT}/
           AUDIT_REPORT.json``, and ``{AGENT_TEAM_AUDIT_REQUIREMENTS_PATH}``.
           No-op when ``AGENT_TEAM_AUDIT_WRITER`` is unset, so the env-
           gate is mutually exclusive with the audit-fix gate (which
           fires on ``AGENT_TEAM_FINDING_ID``).

        Multi-matcher resolution: per Context7 ``/anthropics/claude-code``
        (lookup 2026-04-26), Claude Code resolves multiple matching
        hook outputs as ``deny > ask > allow``. v2.1.80 explicitly
        fixed an "allow bypasses deny" bug. So when several hooks
        fire on the same write the most-restrictive wins — the
        audit-fix and audit-output scopes cannot accidentally
        re-enable a Wave D denial, and vice versa.

        Hook timeouts are in SECONDS (Context7 ``/anthropics/claude-code``
        SKILL.md); 5 seconds is plenty for the audit-fix and audit-
        output guards (parse stdin, a couple of env reads, a path
        resolve + membership check).

        See ``wave_d_path_guard.py``, ``audit_fix_path_guard.py``,
        ``audit_output_path_guard.py``, and the Claude Code hook
        contract (https://github.com/anthropics/claude-code) for the
        JSON envelope shape.
        """
        if not cwd:
            return
        claude_dir = Path(cwd) / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_path = claude_dir / "settings.json"
        wave_d_marker = "agent_team_v15_wave_d_path_guard"
        audit_fix_marker = "agent_team_v15_audit_fix_path_guard"
        audit_output_marker = "agent_team_v15_audit_output_path_guard"
        managed_markers = {wave_d_marker, audit_fix_marker, audit_output_marker}
        existing: dict[str, Any] = {}
        if settings_path.is_file():
            try:
                existing = json.loads(settings_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}
        if not isinstance(existing, dict):
            existing = {}
        # The hook commands must be invoked through the same Python
        # interpreter that runs ``agent-team-v15`` so they pick up the
        # editable-installed package without relying on a venv being
        # active in the teammate subprocess. ``sys.executable`` is the
        # most portable reference.
        wave_d_command = (
            f'"{sys.executable}" -m agent_team_v15.wave_d_path_guard'
        )
        audit_fix_command = (
            f'"{sys.executable}" -m agent_team_v15.audit_fix_path_guard'
        )
        audit_output_command = (
            f'"{sys.executable}" -m agent_team_v15.audit_output_path_guard'
        )
        wave_d_entry: dict[str, Any] = {
            "matcher": "Write|Edit|MultiEdit|NotebookEdit",
            "hooks": [
                {
                    "type": "command",
                    "command": wave_d_command,
                    # Seconds (per Claude Code hook contract). Wave D's
                    # 10s budget is preserved verbatim from v18.0 to
                    # avoid surfacing a refactor-only behaviour change.
                    "timeout": 10,
                }
            ],
            wave_d_marker: True,
        }
        audit_fix_entry: dict[str, Any] = {
            "matcher": "Write|Edit|MultiEdit|NotebookEdit",
            "hooks": [
                {
                    "type": "command",
                    "command": audit_fix_command,
                    # 5 seconds is conservative-fast: hook timeout is a
                    # circuit breaker, not a budget. A path-allowlist
                    # check that hangs for >5s is broken; we'd rather
                    # the hook get killed than stall the fix loop.
                    "timeout": 5,
                }
            ],
            audit_fix_marker: True,
        }
        audit_output_entry: dict[str, Any] = {
            "matcher": "Write|Edit|MultiEdit|NotebookEdit",
            "hooks": [
                {
                    "type": "command",
                    "command": audit_output_command,
                    # 5 seconds — same circuit-breaker reasoning as the
                    # audit-fix entry above. The hook resolves a couple
                    # of paths and runs an exact-segment containment
                    # check; well under one second on any healthy host.
                    "timeout": 5,
                }
            ],
            audit_output_marker: True,
        }
        pre_tool_use = existing.get("PreToolUse")
        if not isinstance(pre_tool_use, list):
            pre_tool_use = []
        # Drop any prior managed entries so we always rewrite to the
        # current commands (handles editable-install relocations).
        # Non-managed entries (e.g., user-added hooks) are preserved
        # verbatim — only entries carrying one of our marker keys are
        # rewritten.
        pre_tool_use = [
            entry
            for entry in pre_tool_use
            if not (
                isinstance(entry, dict)
                and any(entry.get(marker) for marker in managed_markers)
            )
        ]
        pre_tool_use.append(wave_d_entry)
        pre_tool_use.append(audit_fix_entry)
        pre_tool_use.append(audit_output_entry)
        existing["PreToolUse"] = pre_tool_use
        settings_path.write_text(
            json.dumps(existing, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _wave_letter_from_task_id(task_id: str) -> str:
        """Extract the wave letter (e.g. ``D``) from a task id.

        Task ids are formatted ``wave-{LETTER}-{milestone}`` by the
        wave executor. Anything that doesn't match the convention
        returns the empty string, which the Wave D path guard treats
        as "non-D, allow everything".
        """
        if not task_id:
            return ""
        prefix = "wave-"
        text = str(task_id).strip()
        if not text.lower().startswith(prefix):
            return ""
        rest = text[len(prefix):]
        # Wave letters are single uppercase ASCII letters or one
        # letter followed by a digit (A5, T5, D5). Stop at the first
        # ``-`` which separates the letter from the milestone id.
        head, _sep, _tail = rest.partition("-")
        return head.strip().upper()

    def _build_teammate_env(self, *, task_id: str = "", cwd: str | Path | None = None) -> dict[str, str]:
        """Build the environment dict for teammate subprocesses.

        ``task_id`` and ``cwd`` are optional so existing callers (phase
        leads etc.) continue to work; when they are supplied the
        env carries Wave-letter context that the Claude Code
        ``PreToolUse`` Wave D path guard reads to decide whether the
        scope restriction is active for this dispatch.
        """
        env = os.environ.copy()
        env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
        if self._config.agent_teams.teammate_model:
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = self._config.agent_teams.teammate_model
        # Ensure context and output dirs are visible to teammates
        if self._context_dir:
            env["AGENT_TEAMS_CONTEXT_DIR"] = str(self._context_dir)
        if self._output_dir:
            env["AGENT_TEAMS_OUTPUT_DIR"] = str(self._output_dir)
        wave_letter = self._wave_letter_from_task_id(task_id)
        if wave_letter:
            env["AGENT_TEAM_WAVE_LETTER"] = wave_letter
        if cwd is not None:
            env["AGENT_TEAM_PROJECT_DIR"] = str(cwd)
        return env

    def _build_claude_cmd(
        self,
        task_id: str,
        prompt: str,
        *,
        output_file: Path | None = None,
        cwd: str | Path | None = None,
    ) -> list[str]:
        """Build the ``claude`` CLI command for a teammate task.

        Uses ``--print --output-format json`` for structured output.
        The prompt is sent on stdin by :meth:`_spawn_teammate` so full
        wave prompts do not hit the Windows command-line length limit.
        """
        cmd = [
            self._claude_path,
            "--print",
            "--output-format", "json",
        ]

        perm = self._config.agent_teams.teammate_permission_mode
        if perm:
            cmd.extend(["--permission-mode", perm])

        model = self._config.agent_teams.teammate_model
        if model:
            cmd.extend(["--model", model])

        if cwd is not None:
            cmd.extend(["--add-dir", str(cwd)])

        return cmd

    async def _spawn_teammate(
        self,
        task_id: str,
        prompt: str,
        timeout: float,
        *,
        cwd: str | Path | None = None,
    ) -> TaskResult:
        """Spawn a Claude CLI subprocess for a single task.

        Starts the process, waits for completion (or timeout), and
        parses the JSON output into a :class:`TaskResult`.
        """
        task_start = time.monotonic()
        teammate_name = f"teammate-{task_id}"
        output_file = self._output_dir / f"{task_id}.json" if self._output_dir else None

        cmd = self._build_claude_cmd(
            task_id,
            prompt,
            output_file=output_file,
            cwd=cwd,
        )
        env = self._build_teammate_env(task_id=task_id, cwd=cwd)
        subprocess_cwd = str(cwd) if cwd is not None else None

        # Wave D path-write sandbox: ensure the run-dir's
        # ``.claude/settings.json`` carries a ``PreToolUse`` hook that
        # routes Write/Edit/MultiEdit/NotebookEdit through the
        # ``wave_d_path_guard`` module. The hook is wave-aware via
        # the ``AGENT_TEAM_WAVE_LETTER`` env var the env builder just
        # set, so non-D dispatches (Wave A, audits, repairs) are a
        # no-op even though the settings.json applies workspace-wide.
        if subprocess_cwd:
            try:
                self._ensure_wave_d_path_guard_settings(subprocess_cwd)
            except Exception:  # pragma: no cover - defensive
                _logger.exception(
                    "AgentTeamsBackend: failed to write Wave D path-guard settings; continuing without sandbox"
                )

        _logger.info(
            "AgentTeamsBackend: spawning teammate %s for task %s (cwd=%s timeout=%.0fs)",
            teammate_name,
            task_id,
            subprocess_cwd or "<inherited>",
            timeout,
        )

        try:
            proc = await create_subprocess_exec_compat(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=subprocess_cwd,
            )
        except FileNotFoundError:
            duration = time.monotonic() - task_start
            _logger.error(
                "AgentTeamsBackend: claude CLI not found at %s", self._claude_path
            )
            return TaskResult(
                task_id=task_id,
                status="failed",
                output="",
                error=f"Claude CLI not found at '{self._claude_path}'",
                files_created=[],
                files_modified=[],
                duration_seconds=duration,
            )
        except OSError as exc:
            duration = time.monotonic() - task_start
            _logger.error(
                "AgentTeamsBackend: OS error spawning teammate for %s: %s",
                task_id,
                exc,
            )
            return TaskResult(
                task_id=task_id,
                status="failed",
                output="",
                error=f"OS error spawning process: {exc}",
                files_created=[],
                files_modified=[],
                duration_seconds=duration,
            )

        # Register as active teammate
        self._active_teammates[teammate_name] = proc
        self._state.teammates.append(teammate_name)

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            duration = time.monotonic() - task_start
            _logger.warning(
                "AgentTeamsBackend: task %s timed out after %.1fs — killing process",
                task_id,
                duration,
            )
            await self._kill_process(proc, teammate_name)
            return TaskResult(
                task_id=task_id,
                status="timeout",
                output="",
                error=f"Task timed out after {duration:.1f}s (limit: {timeout}s)",
                files_created=[],
                files_modified=[],
                duration_seconds=duration,
            )
        finally:
            # Remove from active teammates once done
            self._active_teammates.pop(teammate_name, None)

        duration = time.monotonic() - task_start
        stdout_str = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        if proc.returncode != 0:
            _logger.warning(
                "AgentTeamsBackend: task %s exited with code %d",
                task_id,
                proc.returncode,
            )
            # Still try to parse output — Claude may have produced partial results
            parsed = self._parse_claude_json_output(stdout_str)
            error_msg = parsed.get("error", "") or stderr_str or f"Exit code {proc.returncode}"
            return TaskResult(
                task_id=task_id,
                status="failed",
                output=parsed.get("result", ""),
                error=error_msg,
                files_created=parsed.get("files_created", []),
                files_modified=parsed.get("files_modified", []),
                duration_seconds=duration,
            )

        # Parse successful output
        parsed = self._parse_claude_json_output(stdout_str)

        # Also check the output file if it was written
        if output_file and output_file.is_file():
            try:
                file_data = json.loads(output_file.read_text(encoding="utf-8"))
                file_parsed = self._extract_from_json(
                    file_data,
                    {"result": "", "cost_usd": 0.0, "files_created": [], "files_modified": [], "error": ""},
                )
                # Merge: prefer file output for files lists
                if file_parsed["files_created"]:
                    parsed["files_created"] = file_parsed["files_created"]
                if file_parsed["files_modified"]:
                    parsed["files_modified"] = file_parsed["files_modified"]
                if not parsed["result"] and file_parsed["result"]:
                    parsed["result"] = file_parsed["result"]
            except (json.JSONDecodeError, OSError) as exc:
                _logger.debug("AgentTeamsBackend: could not read output file for %s: %s", task_id, exc)

        _logger.info(
            "AgentTeamsBackend: task %s completed in %.1fs",
            task_id,
            duration,
        )

        return TaskResult(
            task_id=task_id,
            status="completed",
            output=parsed.get("result", ""),
            error=parsed.get("error", ""),
            files_created=parsed.get("files_created", []),
            files_modified=parsed.get("files_modified", []),
            duration_seconds=duration,
        )

    async def _kill_process(
        self, proc: Any, teammate_name: str
    ) -> None:
        """Terminate a teammate subprocess, escalating to kill if needed."""
        if proc.returncode is not None:
            return  # Already exited

        _logger.debug("AgentTeamsBackend: terminating process for %s", teammate_name)
        try:
            proc.terminate()
        except ProcessLookupError:
            return  # Already gone

        # Wait briefly for graceful termination
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            _logger.warning(
                "AgentTeamsBackend: process for %s did not terminate — killing",
                teammate_name,
            )
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                _logger.error(
                    "AgentTeamsBackend: could not kill process for %s",
                    teammate_name,
                )

    def _is_teammate_alive(self, teammate_name: str) -> bool:
        """Check if a teammate's subprocess is still running."""
        proc = self._active_teammates.get(teammate_name)
        if proc is None:
            proc = self._phase_leads.get(teammate_name)
        if proc is None:
            return False
        return proc.returncode is None

    # -- Phase lead lifecycle -----------------------------------------------

    def _get_phase_lead_config(self, lead_name: str) -> Any:
        """Return the PhaseLeadConfig for a given lead name.

        Maps wave-aligned lead names (e.g., ``"wave-a-lead"``) to the
        corresponding config attribute (e.g., ``config.phase_leads.wave_a_lead``).
        """
        phase_leads_cfg = self._config.phase_leads
        name_map = {
            "wave-a-lead": phase_leads_cfg.wave_a_lead,
            "wave-d5-lead": phase_leads_cfg.wave_d5_lead,
            "wave-t-lead": phase_leads_cfg.wave_t_lead,
            "wave-e-lead": phase_leads_cfg.wave_e_lead,
        }
        return name_map.get(lead_name)

    def _build_phase_lead_cmd(
        self,
        lead_name: str,
        system_prompt: str,
    ) -> list[str]:
        """Build the ``claude`` CLI command to spawn a persistent phase lead.

        Phase leads are long-running interactive sessions (not one-shot
        ``-p`` calls).  They use ``--print --output-format json`` and
        receive their role via ``-p`` with a system prompt that encodes
        their responsibilities and communication protocol.
        """
        lead_cfg = self._get_phase_lead_config(lead_name)
        model = ""
        if lead_cfg and lead_cfg.model:
            model = lead_cfg.model
        elif self._config.agent_teams.phase_lead_model:
            model = self._config.agent_teams.phase_lead_model

        cmd = [
            self._claude_path,
            "--print",
            "--output-format", "json",
            "-p", system_prompt,
        ]

        perm = self._config.agent_teams.teammate_permission_mode
        if perm:
            cmd.extend(["--permission-mode", perm])

        if model:
            cmd.extend(["--model", model])

        return cmd

    async def spawn_phase_leads(
        self,
        prompts: dict[str, str] | None = None,
    ) -> dict[str, bool]:
        """Spawn persistent phase lead teammates.

        Parameters
        ----------
        prompts:
            Optional mapping of lead name -> system prompt.  If not
            provided, a minimal default prompt is used.

        Returns
        -------
        dict[str, bool]
            Mapping of lead name -> whether spawn succeeded.
        """
        if not self._state.active:
            _logger.warning("AgentTeamsBackend: cannot spawn phase leads — not initialized.")
            return {name: False for name in self.PHASE_LEAD_NAMES}

        phase_leads_cfg = self._config.phase_leads
        if not phase_leads_cfg.enabled:
            _logger.info("AgentTeamsBackend: phase leads disabled in config.")
            return {name: False for name in self.PHASE_LEAD_NAMES}

        results: dict[str, bool] = {}
        env = self._build_teammate_env()

        for lead_name in self.PHASE_LEAD_NAMES:
            lead_cfg = self._get_phase_lead_config(lead_name)
            if lead_cfg and not lead_cfg.enabled:
                _logger.info("AgentTeamsBackend: %s is disabled, skipping.", lead_name)
                results[lead_name] = False
                continue

            prompt = (prompts or {}).get(
                lead_name,
                f"You are {lead_name}. Await instructions from the orchestrator.",
            )
            cmd = self._build_phase_lead_cmd(lead_name, prompt)

            try:
                proc = await create_subprocess_exec_compat(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                self._phase_leads[lead_name] = proc
                self._state.teammates.append(lead_name)
                results[lead_name] = True
                _logger.info(
                    "AgentTeamsBackend: spawned phase lead %s (pid=%s)",
                    lead_name,
                    proc.pid,
                )
            except (FileNotFoundError, OSError) as exc:
                _logger.error(
                    "AgentTeamsBackend: failed to spawn %s: %s",
                    lead_name,
                    exc,
                )
                results[lead_name] = False

        return results

    async def respawn_phase_lead(
        self,
        lead_name: str,
        prompt: str | None = None,
    ) -> bool:
        """Respawn a failed or stalled phase lead.

        Kills the old process (if still running), then spawns a fresh
        one.  The new lead reads shared artifacts to reconstruct state.

        Returns True if respawn succeeded.
        """
        if lead_name not in self.PHASE_LEAD_NAMES:
            _logger.error("AgentTeamsBackend: unknown phase lead %s", lead_name)
            return False

        # Kill old process if it exists
        old_proc = self._phase_leads.pop(lead_name, None)
        if old_proc is not None:
            await self._kill_process(old_proc, lead_name)

        # Remove from teammates list if present
        if lead_name in self._state.teammates:
            self._state.teammates.remove(lead_name)

        # Re-spawn
        result = await self.spawn_phase_leads(
            prompts={lead_name: prompt or f"You are {lead_name}. Resume from shared artifacts."},
        )
        return result.get(lead_name, False)

    async def check_phase_lead_health(self) -> dict[str, str]:
        """Check the health status of all phase leads.

        Returns a dict mapping lead name -> status string:
        ``"running"``, ``"exited"``, ``"not_spawned"``.
        """
        statuses: dict[str, str] = {}
        for lead_name in self.PHASE_LEAD_NAMES:
            proc = self._phase_leads.get(lead_name)
            if proc is None:
                statuses[lead_name] = "not_spawned"
            elif proc.returncode is None:
                statuses[lead_name] = "running"
            else:
                statuses[lead_name] = "exited"
        return statuses

    async def route_message(
        self,
        to: str,
        message_type: str,
        body: str,
        from_lead: str = "orchestrator",
    ) -> bool:
        """Route a typed message to a phase lead via its context directory.

        Messages are written as files in the context directory with a
        structured format that the receiving lead can parse.

        Parameters
        ----------
        to:
            Recipient lead name, or ``"*"`` for broadcast.
        message_type:
            One of the recognized MESSAGE_TYPES.
        body:
            Message body content.
        from_lead:
            Sender name (for logging and message headers).

        Returns True if the message was delivered (written) successfully.
        """
        if not self._context_dir:
            _logger.warning("AgentTeamsBackend: no context dir — cannot route message.")
            return False

        if message_type not in self.MESSAGE_TYPES:
            _logger.warning(
                "AgentTeamsBackend: unrecognized message type %r (delivering anyway).",
                message_type,
            )

        timestamp = int(time.time() * 1000)
        message_content = (
            f"To: {to}\n"
            f"From: {from_lead}\n"
            f"Type: {message_type}\n"
            f"Timestamp: {timestamp}\n"
            f"---\n"
            f"{body}"
        )

        # Determine recipients
        if to == "*":
            recipients = list(self.PHASE_LEAD_NAMES)
        else:
            recipients = [to]

        delivered = False
        for recipient in recipients:
            msg_file = self._context_dir / f"msg_{timestamp}_{from_lead}_to_{recipient}.md"
            try:
                msg_file.write_text(message_content, encoding="utf-8")
                delivered = True
                _logger.debug(
                    "AgentTeamsBackend: routed %s from %s to %s",
                    message_type,
                    from_lead,
                    recipient,
                )
            except OSError as exc:
                _logger.warning(
                    "AgentTeamsBackend: failed to write message to %s: %s",
                    recipient,
                    exc,
                )

        if delivered:
            self._message_log.append({
                "from": from_lead,
                "to": to,
                "type": message_type,
                "timestamp": str(timestamp),
            })
            self._state.total_messages += 1

        return delivered

    def get_message_log(self) -> list[dict[str, str]]:
        """Return the message routing log for diagnostics."""
        return list(self._message_log)

    # -- ExecutionBackend interface -----------------------------------------

    async def initialize(self) -> TeamState:
        """Initialize Agent Teams: verify CLI, set environment variables,
        create working directories.

        Sets ``CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`` and optionally
        ``CLAUDE_CODE_SUBAGENT_MODEL`` when ``teammate_model`` is
        configured.

        Creates temporary directories for shared context and teammate
        output files.

        Raises
        ------
        RuntimeError
            If the ``claude`` CLI is not available.
        """
        if not self._verify_claude_available():
            raise RuntimeError(
                "Claude CLI is not available.  Cannot initialize Agent Teams backend.  "
                "Install Claude Code before running Claude-routed waves."
            )

        self._claude_path = self._resolve_claude_path()

        # Ensure the experimental feature flag is set
        os.environ["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

        # Optionally set the sub-agent model
        teammate_model = self._config.agent_teams.teammate_model
        if teammate_model:
            os.environ["CLAUDE_CODE_SUBAGENT_MODEL"] = teammate_model
            _logger.info(
                "AgentTeamsBackend: sub-agent model set to %s", teammate_model
            )

        # Create working directories for inter-agent communication
        base_tmp = Path(tempfile.mkdtemp(prefix="agent_teams_"))
        self._context_dir = base_tmp / "context"
        self._output_dir = base_tmp / "output"
        self._context_dir.mkdir(exist_ok=True)
        self._output_dir.mkdir(exist_ok=True)
        _logger.debug(
            "AgentTeamsBackend: working dirs created at %s", base_tmp
        )

        self._state = TeamState(
            mode="agent_teams",
            active=True,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )

        phase_leads_enabled = self._config.phase_leads.enabled
        _logger.info(
            "AgentTeamsBackend initialized (Mode A -- Agent Teams, "
            "max_teammates=%d, phase_leads=%s).",
            self._config.agent_teams.max_teammates,
            phase_leads_enabled,
        )
        return self._state

    async def execute_wave(self, wave: ExecutionWave) -> WaveResult:
        """Execute all tasks in *wave* as parallel Claude CLI subprocesses.

        Each task is spawned as a separate ``claude`` process.  The
        number of concurrent processes is capped at
        ``config.agent_teams.max_teammates``.  Tasks beyond the cap
        are queued and started as earlier tasks finish.

        Returns a :class:`WaveResult` with collected :class:`TaskResult`
        instances.
        """
        wave_start = time.monotonic()
        wave_timeout = self._config.agent_teams.wave_timeout_seconds
        task_timeout = self._config.agent_teams.task_timeout_seconds
        max_concurrent = self._config.agent_teams.max_teammates

        # Inject shared context into the task prompt
        context_snippet = ""
        if self._context_dir:
            context_files = sorted(self._context_dir.glob("*.md"))
            if context_files:
                pieces = []
                for cf in context_files[-5:]:  # last 5 context files
                    try:
                        pieces.append(cf.read_text(encoding="utf-8"))
                    except OSError:
                        pass
                if pieces:
                    context_snippet = (
                        "\n\n[SHARED CONTEXT FROM TEAM LEAD]\n"
                        + "\n---\n".join(pieces)
                        + "\n[END SHARED CONTEXT]\n\n"
                    )

        async def _run_single_task(task_id: str) -> TaskResult:
            """Build prompt and spawn teammate for one task."""
            prompt = f"Execute task {task_id}.{context_snippet}"
            # If the task has a description from the scheduler, it would be
            # included in the prompt by the orchestrator layer above.  Here
            # we provide the task_id as the minimum viable prompt.
            return await self._spawn_teammate(task_id, prompt, task_timeout)

        # Use a semaphore to limit concurrent teammates
        sem = asyncio.Semaphore(max_concurrent)

        async def _throttled_task(task_id: str) -> TaskResult:
            async with sem:
                return await _run_single_task(task_id)

        coros = [_throttled_task(tid) for tid in wave.task_ids]

        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(*coros, return_exceptions=True),
                timeout=wave_timeout,
            )
        except asyncio.TimeoutError:
            wave_duration = time.monotonic() - wave_start
            _logger.error(
                "AgentTeamsBackend: wave %d timed out after %.1fs (limit: %ds)",
                wave.wave_number,
                wave_duration,
                wave_timeout,
            )
            # Kill any remaining active teammate processes
            for name, proc in list(self._active_teammates.items()):
                await self._kill_process(proc, name)
            self._active_teammates.clear()

            task_results: list[TaskResult] = []
            for tid in wave.task_ids:
                task_results.append(
                    TaskResult(
                        task_id=tid,
                        status="timeout",
                        output="",
                        error=f"Wave timed out after {wave_duration:.1f}s",
                        files_created=[],
                        files_modified=[],
                        duration_seconds=wave_duration,
                    )
                )
            return WaveResult(
                wave_index=wave.wave_number,
                task_results=task_results,
                all_succeeded=False,
                duration_seconds=wave_duration,
            )

        # Process raw results (may contain exceptions from return_exceptions=True)
        task_results = []
        all_succeeded = True

        for i, raw in enumerate(raw_results):
            if isinstance(raw, TaskResult):
                task_results.append(raw)
                if raw.status == "completed":
                    self._state.completed_tasks.append(raw.task_id)
                else:
                    all_succeeded = False
                    self._state.failed_tasks.append(raw.task_id)
            elif isinstance(raw, Exception):
                task_id = wave.task_ids[i] if i < len(wave.task_ids) else f"unknown-{i}"
                _logger.error(
                    "AgentTeamsBackend: task %s raised %s: %s",
                    task_id,
                    type(raw).__name__,
                    raw,
                )
                task_results.append(
                    TaskResult(
                        task_id=task_id,
                        status="failed",
                        output="",
                        error=str(raw),
                        files_created=[],
                        files_modified=[],
                        duration_seconds=0.0,
                    )
                )
                all_succeeded = False
                self._state.failed_tasks.append(task_id)
            else:
                task_id = wave.task_ids[i] if i < len(wave.task_ids) else f"unknown-{i}"
                task_results.append(
                    TaskResult(
                        task_id=task_id,
                        status="failed",
                        output="",
                        error=f"Unexpected result type: {type(raw).__name__}",
                        files_created=[],
                        files_modified=[],
                        duration_seconds=0.0,
                    )
                )
                all_succeeded = False
                self._state.failed_tasks.append(task_id)

        wave_duration = time.monotonic() - wave_start
        self._state.total_messages += len(task_results)

        return WaveResult(
            wave_index=wave.wave_number,
            task_results=task_results,
            all_succeeded=all_succeeded,
            duration_seconds=wave_duration,
        )

    async def execute_prompt(
        self,
        *,
        prompt: str,
        cwd: str | Path,
        wave: str = "",
        milestone: Any | None = None,
        role: str = "wave_execution",
        progress_callback: Any | None = None,
    ) -> float:
        """Execute a full orchestrator wave prompt through Agent Teams.

        This is the production bridge used by PRD milestone waves. Unlike
        ``execute_wave()``, it receives the complete Wave A/B/D/T/E prompt
        already built by the orchestrator and runs it in the generated
        project cwd.
        """
        wave_letter = str(wave or "claude").upper()
        milestone_id = str(getattr(milestone, "id", "") or "unknown")
        task_id = f"wave-{wave_letter}-{milestone_id}"
        timeout = float(self._config.agent_teams.wave_timeout_seconds)

        if progress_callback is not None:
            progress_callback(
                message_type="agent_teams_session_started",
                tool_name="",
                event_kind="start",
            )

        result = await self._spawn_teammate(
            task_id,
            prompt,
            timeout,
            cwd=cwd,
        )
        self._persist_wave_output(
            cwd=cwd,
            wave_letter=wave_letter,
            milestone_id=milestone_id,
            output=result.output,
        )

        if result.status == "completed":
            self._state.completed_tasks.append(task_id)
        else:
            self._state.failed_tasks.append(task_id)
        self._state.total_messages += 1

        if progress_callback is not None:
            progress_callback(
                message_type="agent_teams_session_completed",
                tool_name="",
                event_kind=result.status,
            )

        if result.status != "completed":
            raise RuntimeError(
                f"Agent Teams {role} failed for {task_id}: {result.error or result.output}"
            )
        return 0.0

    def _persist_wave_output(
        self,
        *,
        cwd: str | Path,
        wave_letter: str,
        milestone_id: str,
        output: str,
    ) -> None:
        """Persist raw wave output needed by downstream deterministic gates."""

        if str(wave_letter or "").upper() != "T":
            return
        if not output:
            return
        safe_milestone = str(milestone_id or "unknown")
        try:
            milestone_dir = (
                Path(cwd)
                / ".agent-team"
                / "milestones"
                / safe_milestone
            )
            milestone_dir.mkdir(parents=True, exist_ok=True)
            (milestone_dir / "WAVE_T_OUTPUT.md").write_text(
                output,
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(
                "Failed to persist Wave T output for %s: %s",
                safe_milestone,
                exc,
            )

    async def execute_task(self, task: ScheduledTask) -> TaskResult:
        """Execute a single task by spawning a Claude CLI teammate.

        Extracts the task description from the task object (if
        available) and delegates to :meth:`_spawn_teammate`.
        """
        task_id = getattr(task, "id", str(task))
        description = getattr(task, "description", "")
        title = getattr(task, "title", "")
        task_timeout = self._config.agent_teams.task_timeout_seconds

        prompt_parts = [f"Execute task {task_id}."]
        if title:
            prompt_parts.append(f"Title: {title}")
        if description:
            prompt_parts.append(f"Description: {description}")

        prompt = "\n".join(prompt_parts)

        _logger.info(
            "AgentTeamsBackend: executing single task %s (timeout=%ds)",
            task_id,
            task_timeout,
        )

        result = await self._spawn_teammate(task_id, prompt, task_timeout)

        if result.status == "completed":
            self._state.completed_tasks.append(task_id)
        else:
            self._state.failed_tasks.append(task_id)

        return result

    async def send_context(self, context: str) -> bool:
        """Write context to the shared context directory.

        Active teammates can read context files from the shared
        directory.  Each context delivery is written as a timestamped
        Markdown file.

        Returns True if the context was written successfully, False
        otherwise.
        """
        if not self._state.active:
            _logger.warning(
                "AgentTeamsBackend: cannot send context -- backend is not active."
            )
            return False

        if not self._active_teammates:
            _logger.debug(
                "AgentTeamsBackend: no active teammates to receive context."
            )
            return False

        # Write context to shared directory if available
        if self._context_dir:
            timestamp = int(time.time() * 1000)
            context_file = self._context_dir / f"context_{timestamp}.md"
            try:
                context_file.write_text(context, encoding="utf-8")
                _logger.debug(
                    "AgentTeamsBackend: wrote context file %s (%d chars)",
                    context_file.name,
                    len(context),
                )
            except OSError as exc:
                _logger.warning(
                    "AgentTeamsBackend: failed to write context file: %s", exc
                )

        # Count active teammates that could receive the context
        delivered = 0
        for name, proc in self._active_teammates.items():
            returncode = getattr(proc, "returncode", None)
            if returncode is None:
                delivered += 1  # Process still running
            else:
                delivered += 1  # Count mocks / non-process handles too

        self._state.total_messages += delivered
        return delivered > 0

    async def shutdown(self) -> None:
        """Terminate all active teammate processes and clean up.

        Sends SIGTERM to each active subprocess, waits briefly for
        graceful exit, then escalates to SIGKILL if needed.  Removes
        temporary working directories.
        """
        if not self._state.active:
            _logger.debug("AgentTeamsBackend: already inactive, nothing to shut down.")
            return

        total_procs = len(self._active_teammates) + len(self._phase_leads)
        _logger.info(
            "AgentTeamsBackend: shutting down %d active processes "
            "(%d teammates, %d phase leads).",
            total_procs,
            len(self._active_teammates),
            len(self._phase_leads),
        )

        # Terminate all processes (task teammates + phase leads) in parallel
        kill_coros = []
        for name, proc in list(self._active_teammates.items()):
            kill_coros.append(self._kill_process(proc, name))
        for name, proc in list(self._phase_leads.items()):
            kill_coros.append(self._kill_process(proc, name))

        if kill_coros:
            await asyncio.gather(*kill_coros, return_exceptions=True)

        self._active_teammates.clear()
        self._phase_leads.clear()
        self._message_log.clear()
        self._state.teammates.clear()

        # Clean up temporary directories (best-effort)
        for d in (self._context_dir, self._output_dir):
            if d and d.exists():
                try:
                    shutil.rmtree(d.parent, ignore_errors=True)
                except OSError as exc:
                    _logger.debug("AgentTeamsBackend: cleanup error: %s", exc)
                break  # Both are under the same parent

        self._context_dir = None
        self._output_dir = None
        self._state.active = False
        _logger.info("AgentTeamsBackend shut down.")

    def supports_peer_messaging(self) -> bool:
        """Agent Teams natively supports peer-to-peer messaging."""
        return True

    def supports_self_claiming(self) -> bool:
        """Agent Teams supports teammate self-claiming of unassigned tasks."""
        return True


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_execution_backend(config: AgentTeamConfig, depth: str = "") -> ExecutionBackend:
    """Select and instantiate the appropriate execution backend.

    Decision tree (evaluated in order):

    1. ``agent_teams.enabled`` is False --> :class:`CLIBackend`.
    2. Enabled --> set ``CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`` in the
       current process before probing.
    3. Enabled but ``claude`` CLI is not reachable --> raise
       :class:`RuntimeError`.
    4. Enabled but requested display mode is unsupported --> raise
       :class:`RuntimeError`.
    5. All conditions met --> :class:`AgentTeamsBackend`.

    Parameters
    ----------
    config:
        The fully-loaded :class:`AgentTeamConfig`.
    depth:
        The resolved pipeline depth string (e.g. ``"standard"``,
        ``"exhaustive"``). Passed through from the CLI so the strict
        gate can fire only at exhaustive depth. Empty-string default
        preserves legacy behavior for callers without depth context.

    Returns
    -------
    ExecutionBackend
        A ready-to-initialize backend instance.

    Raises
    ------
    RuntimeError
        When Agent Teams is enabled but the CLI or requested display mode is
        unavailable.
    """
    at_cfg = config.agent_teams
    _logger.info(
        "select_backend: agent_teams.enabled=%s, env_flag=%s, depth=%s",
        at_cfg.enabled,
        os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", ""),
        depth,
    )

    # Branch 1: Agent Teams disabled
    if not at_cfg.enabled:
        _logger.info("Agent Teams disabled in config -- using CLIBackend.")
        return CLIBackend(config)

    env_flag = os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "")
    if env_flag != "1":
        _logger.info(
            "agent_teams.enabled=true; setting CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 "
            "for this process (previous value=%r).",
            env_flag,
        )
        os.environ["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

    # Branch 3 & 4: Check CLI availability
    cli_available = AgentTeamsBackend._verify_claude_available()
    if not cli_available:
        raise RuntimeError(
            "Agent Teams is enabled and CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 "
            "but the claude CLI is not installed or not on PATH. "
            "Install Claude Code before running Claude-routed waves."
        )

    # Branch 5: Platform / display-mode compatibility
    if not detect_agent_teams_available(display_mode=at_cfg.teammate_display_mode):
        # The env var and CLI are fine (checked above), so this means
        # the current platform doesn't support the requested display mode.
        raise RuntimeError(
            f"Agent Teams display mode '{at_cfg.teammate_display_mode}' "
            "is not supported on this platform. Change "
            "agent_teams.teammate_display_mode to 'in-process'."
        )

    # Branch 6: All conditions met
    _logger.info(
        "Agent Teams enabled -- using AgentTeamsBackend (max_teammates=%d).",
        at_cfg.max_teammates,
    )
    _logger.info("select_backend: returning AgentTeamsBackend")
    return AgentTeamsBackend(config)


# ---------------------------------------------------------------------------
# Phase 4.5 — audit-fix path-guard precondition check
# ---------------------------------------------------------------------------


def audit_fix_path_guard_settings_present(cwd: str | Path | None) -> bool:
    """Return True iff ``.claude/settings.json`` registers the audit-fix
    path-guard PreToolUse hook (Phase 3 marker
    ``agent_team_v15_audit_fix_path_guard``).

    Phase 4.5 reads this as one of the four safety nets gating the
    conditional Risk #1 lift. The hook enforces per-finding write scope
    via ``deny|ask|allow`` precedence (Context7 ``/anthropics/claude-code``
    confirms ``deny > ask > allow``); without it Phase 4.5's lift
    cannot enforce dispatch scope, so the legacy short-circuit remains
    in force.

    The check is a presence test only — operators may have edited the
    timeout / command path, but as long as a PreToolUse entry carries
    the canonical marker the hook is considered installed. Falls back
    to ``False`` on missing file / unreadable JSON / non-dict
    settings.
    """

    if not cwd:
        return False
    settings_path = Path(cwd) / ".claude" / "settings.json"
    if not settings_path.is_file():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    pre_tool_use = data.get("PreToolUse")
    if not isinstance(pre_tool_use, list):
        return False
    marker = "agent_team_v15_audit_fix_path_guard"
    for entry in pre_tool_use:
        if isinstance(entry, dict) and entry.get(marker) is True:
            return True
    return False


# ---------------------------------------------------------------------------
# Availability detection
# ---------------------------------------------------------------------------


def detect_agent_teams_available(display_mode: str = "in-process") -> bool:
    """Lightweight check for Agent Teams availability.

    Returns True when **all** of the following conditions hold:

    1. The ``CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`` env var is ``"1"``.
    2. The ``claude`` CLI is installed and responds to ``--version``.
    3. The current platform supports the required display mode.  On
       Windows Terminal, split-pane display is not available so Agent
       Teams is reported as unavailable when split or tmux panes would
       be required.  The ``"in-process"`` display mode works in any
       terminal.

    Parameters
    ----------
    display_mode:
        The display mode to check compatibility for.  One of
        ``"in-process"``, ``"split"``, or ``"tmux"``.  Defaults to
        ``"in-process"`` which is compatible with all terminals.

    This function does **not** raise exceptions -- it always returns a
    boolean.
    """
    # Condition 1: env var
    env_flag = os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "")
    if env_flag != "1":
        return False

    # Condition 2: CLI availability
    if not AgentTeamsBackend._verify_claude_available():
        return False

    # Condition 3: platform-specific display compatibility
    # On Windows, the "split"/"tmux" display modes require a terminal
    # multiplexer which is typically unavailable in Windows Terminal.
    # The "in-process" mode works everywhere.
    if platform.system() == "Windows":
        wt_session = os.environ.get("WT_SESSION", "")
        if wt_session and display_mode in ("split", "tmux"):
            _logger.debug(
                "detect_agent_teams_available: Windows Terminal detected "
                "(WT_SESSION=%s). Split-pane display mode '%s' not supported.",
                wt_session,
                display_mode,
            )
            return False

    return True
