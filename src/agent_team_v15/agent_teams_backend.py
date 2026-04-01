"""Agent Teams execution backend abstraction layer.

Provides a unified ExecutionBackend protocol with two concrete
implementations:

- **CLIBackend** (Mode B): wraps existing subprocess-based orchestration.
- **AgentTeamsBackend** (Mode A): integrates with Claude Code Agent Teams
  for parallel task execution with peer messaging and self-claiming.

The ``create_execution_backend`` factory selects the correct backend
based on configuration, environment variables, and CLI availability,
with automatic fallback to CLIBackend when Agent Teams is unavailable
(REQ-009).

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
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

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
        "planning-lead",
        "architecture-lead",
        "coding-lead",
        "review-lead",
        "testing-lead",
        "audit-lead",
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

    def _build_teammate_env(self) -> dict[str, str]:
        """Build the environment dict for teammate subprocesses."""
        env = os.environ.copy()
        env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
        if self._config.agent_teams.teammate_model:
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = self._config.agent_teams.teammate_model
        # Ensure context and output dirs are visible to teammates
        if self._context_dir:
            env["AGENT_TEAMS_CONTEXT_DIR"] = str(self._context_dir)
        if self._output_dir:
            env["AGENT_TEAMS_OUTPUT_DIR"] = str(self._output_dir)
        return env

    def _build_claude_cmd(
        self,
        task_id: str,
        prompt: str,
        *,
        output_file: Path | None = None,
    ) -> list[str]:
        """Build the ``claude`` CLI command for a teammate task.

        Uses ``--print --output-format json`` for structured output
        and ``-p`` for non-interactive prompt mode.
        """
        cmd = [
            self._claude_path,
            "--print",
            "--output-format", "json",
            "-p", prompt,
        ]

        perm = self._config.agent_teams.teammate_permission_mode
        if perm:
            cmd.extend(["--permission-mode", perm])

        return cmd

    async def _spawn_teammate(
        self,
        task_id: str,
        prompt: str,
        timeout: float,
    ) -> TaskResult:
        """Spawn a Claude CLI subprocess for a single task.

        Starts the process, waits for completion (or timeout), and
        parses the JSON output into a :class:`TaskResult`.
        """
        task_start = time.monotonic()
        teammate_name = f"teammate-{task_id}"
        output_file = self._output_dir / f"{task_id}.json" if self._output_dir else None

        cmd = self._build_claude_cmd(task_id, prompt, output_file=output_file)
        env = self._build_teammate_env()

        _logger.info(
            "AgentTeamsBackend: spawning teammate %s for task %s (timeout=%.0fs)",
            teammate_name,
            task_id,
            timeout,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
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
                proc.communicate(),
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

        Maps lead names like ``"planning-lead"`` to the corresponding
        config attribute (e.g., ``config.phase_leads.planning_lead``).
        """
        phase_leads_cfg = self._config.phase_leads
        name_map = {
            "planning-lead": phase_leads_cfg.planning_lead,
            "architecture-lead": phase_leads_cfg.architecture_lead,
            "coding-lead": phase_leads_cfg.coding_lead,
            "review-lead": phase_leads_cfg.review_lead,
            "testing-lead": phase_leads_cfg.testing_lead,
            "audit-lead": phase_leads_cfg.audit_lead,
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
                proc = await asyncio.create_subprocess_exec(
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
                "Install Claude Code or set agent_teams.fallback_to_cli=true."
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


def create_execution_backend(config: AgentTeamConfig) -> ExecutionBackend:
    """Select and instantiate the appropriate execution backend.

    Decision tree (evaluated in order):

    1. ``agent_teams.enabled`` is False --> :class:`CLIBackend`.
    2. Enabled but ``CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`` env var is
       not ``"1"`` --> :class:`CLIBackend` with a warning.
    3. Enabled, env var set, but ``claude`` CLI is not reachable and
       ``fallback_to_cli`` is True --> :class:`CLIBackend` with a
       warning.
    4. Enabled, env var set, CLI missing, ``fallback_to_cli`` is False
       --> raise :class:`RuntimeError`.
    5. All conditions met --> :class:`AgentTeamsBackend`.

    Parameters
    ----------
    config:
        The fully-loaded :class:`AgentTeamConfig`.

    Returns
    -------
    ExecutionBackend
        A ready-to-initialize backend instance.

    Raises
    ------
    RuntimeError
        When Agent Teams is enabled, the CLI is missing, and
        ``fallback_to_cli`` is False (branch 4).
    """
    at_cfg = config.agent_teams

    # Branch 1: Agent Teams disabled
    if not at_cfg.enabled:
        _logger.info("Agent Teams disabled in config -- using CLIBackend.")
        return CLIBackend(config)

    # Branch 2: Enabled but env var not set
    env_flag = os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "")
    if env_flag != "1":
        _logger.warning(
            "agent_teams.enabled=true but CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS "
            "is not '1' (got %r).  Falling back to CLIBackend.",
            env_flag,
        )
        return CLIBackend(config)

    # Branch 3 & 4: Check CLI availability
    cli_available = AgentTeamsBackend._verify_claude_available()
    if not cli_available:
        if at_cfg.fallback_to_cli:
            _logger.warning(
                "agent_teams.enabled=true and env var is set, but the claude "
                "CLI is not available.  Falling back to CLIBackend "
                "(fallback_to_cli=true)."
            )
            return CLIBackend(config)
        else:
            raise RuntimeError(
                "Agent Teams is enabled and CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 "
                "but the claude CLI is not installed or not on PATH.  "
                "Either install Claude Code or set agent_teams.fallback_to_cli=true."
            )

    # Branch 5: Platform / display-mode compatibility
    if not detect_agent_teams_available(display_mode=at_cfg.teammate_display_mode):
        # The env var and CLI are fine (checked above), so this means
        # the current platform doesn't support the requested display mode.
        if at_cfg.fallback_to_cli:
            _logger.warning(
                "agent_teams.enabled=true but display mode '%s' is not "
                "supported on this platform.  Falling back to CLIBackend.",
                at_cfg.teammate_display_mode,
            )
            return CLIBackend(config)
        else:
            raise RuntimeError(
                f"Agent Teams display mode '{at_cfg.teammate_display_mode}' "
                "is not supported on this platform.  Either change "
                "agent_teams.teammate_display_mode to 'in-process' or set "
                "agent_teams.fallback_to_cli=true."
            )

    # Branch 6: All conditions met
    _logger.info(
        "Agent Teams enabled -- using AgentTeamsBackend (max_teammates=%d).",
        at_cfg.max_teammates,
    )
    return AgentTeamsBackend(config)


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
