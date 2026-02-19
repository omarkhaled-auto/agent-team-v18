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
import logging
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
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

    This backend leverages the experimental Agent Teams feature where
    the team-lead spawns teammate sub-agents that can communicate via
    peer messaging and self-claim unassigned tasks.

    .. note::

       Agent Teams is an experimental feature behind the
       ``CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`` environment variable.
       All subprocess calls in this class are placeholders -- the actual
       Agent Teams SDK integration will replace them once the API
       stabilizes.
    """

    def __init__(self, config: AgentTeamConfig) -> None:
        self._config = config
        self._state = TeamState(
            mode="agent_teams",
            active=False,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )
        self._active_teammates: dict[str, Any] = {}  # name -> handle

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

    # -- ExecutionBackend interface -----------------------------------------

    async def initialize(self) -> TeamState:
        """Initialize Agent Teams: verify CLI, set environment variables.

        Sets ``CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`` and optionally
        ``CLAUDE_CODE_SUBAGENT_MODEL`` when ``teammate_model`` is
        configured.

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

        # Ensure the experimental feature flag is set
        os.environ["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

        # Optionally set the sub-agent model
        teammate_model = self._config.agent_teams.teammate_model
        if teammate_model:
            os.environ["CLAUDE_CODE_SUBAGENT_MODEL"] = teammate_model
            _logger.info(
                "AgentTeamsBackend: sub-agent model set to %s", teammate_model
            )

        self._state = TeamState(
            mode="agent_teams",
            active=True,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )
        _logger.info(
            "AgentTeamsBackend initialized (Mode A -- Agent Teams, "
            "max_teammates=%d).",
            self._config.agent_teams.max_teammates,
        )
        return self._state

    async def execute_wave(self, wave: ExecutionWave) -> WaveResult:
        """Execute all tasks in *wave* using Agent Teams parallelism.

        Flow:
        1. Create a coroutine for each task in the wave.
        2. Use ``asyncio.gather`` with ``return_exceptions=True`` to
           run them concurrently.
        3. Poll every 30 seconds until all tasks complete or the wave
           timeout is reached.
        4. Enforce per-task and per-wave timeouts from config.

        Returns a :class:`WaveResult` with collected :class:`TaskResult`
        instances.
        """
        wave_start = time.monotonic()
        wave_timeout = self._config.agent_teams.wave_timeout_seconds
        task_timeout = self._config.agent_teams.task_timeout_seconds

        async def _run_single_task(task_id: str) -> TaskResult:
            """Execute a single task within the Agent Teams framework."""
            task_start = time.monotonic()
            try:
                # TODO: Replace with actual Agent Teams SDK call.
                # The real implementation would:
                #   1. Create a teammate via the Agent Teams API
                #   2. Assign the task with its context
                #   3. Poll the teammate's status
                #   4. Collect the result when the teammate finishes

                _logger.info(
                    "AgentTeamsBackend: starting task %s (timeout=%ds)",
                    task_id,
                    task_timeout,
                )

                # Simulate polling loop -- in production this polls the
                # Agent Teams API for task completion.
                elapsed = 0.0
                poll_interval = 30  # seconds
                task_complete = False

                while not task_complete:
                    await asyncio.sleep(poll_interval)
                    elapsed = time.monotonic() - task_start

                    # TODO: Query Agent Teams API for task status
                    # status = await agent_teams_api.get_task_status(task_id)
                    # task_complete = status in ("completed", "failed")

                    # Placeholder: mark as complete after first poll
                    task_complete = True

                    if elapsed >= task_timeout:
                        _logger.warning(
                            "AgentTeamsBackend: task %s timed out after %.1fs",
                            task_id,
                            elapsed,
                        )
                        return TaskResult(
                            task_id=task_id,
                            status="timeout",
                            output="",
                            error=f"Task timed out after {elapsed:.1f}s (limit: {task_timeout}s)",
                            files_created=[],
                            files_modified=[],
                            duration_seconds=elapsed,
                        )

                duration = time.monotonic() - task_start

                # TODO: Extract actual output, files_created, files_modified
                # from Agent Teams API response.
                return TaskResult(
                    task_id=task_id,
                    status="completed",
                    output="",
                    error="",
                    files_created=[],
                    files_modified=[],
                    duration_seconds=duration,
                )

            except Exception as exc:
                duration = time.monotonic() - task_start
                _logger.error(
                    "AgentTeamsBackend: task %s failed with %s: %s",
                    task_id,
                    type(exc).__name__,
                    exc,
                )
                return TaskResult(
                    task_id=task_id,
                    status="failed",
                    output="",
                    error=str(exc),
                    files_created=[],
                    files_modified=[],
                    duration_seconds=duration,
                )

        # Launch all tasks concurrently via asyncio.gather
        coros = [_run_single_task(tid) for tid in wave.task_ids]

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
            # Build timeout results for any tasks that did not finish
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
                # asyncio.gather with return_exceptions=True yields exceptions
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
                # Unexpected type -- treat as failure
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
        """Execute a single task via Agent Teams and poll until complete.

        This is a convenience wrapper around :meth:`execute_wave` for
        one-off task execution outside the wave pipeline.
        """
        task_id = getattr(task, "id", str(task))
        task_start = time.monotonic()
        task_timeout = self._config.agent_teams.task_timeout_seconds

        try:
            # TODO: Replace with actual Agent Teams SDK call.
            # 1. Create/reuse a teammate
            # 2. Send the task description and context
            # 3. Poll for completion

            _logger.info(
                "AgentTeamsBackend: executing single task %s (timeout=%ds)",
                task_id,
                task_timeout,
            )

            elapsed = 0.0
            poll_interval = 30  # seconds
            task_complete = False

            while not task_complete:
                await asyncio.sleep(poll_interval)
                elapsed = time.monotonic() - task_start

                # TODO: Query Agent Teams API for task status
                task_complete = True  # Placeholder

                if elapsed >= task_timeout:
                    _logger.warning(
                        "AgentTeamsBackend: single task %s timed out after %.1fs",
                        task_id,
                        elapsed,
                    )
                    return TaskResult(
                        task_id=task_id,
                        status="timeout",
                        output="",
                        error=f"Task timed out after {elapsed:.1f}s (limit: {task_timeout}s)",
                        files_created=[],
                        files_modified=[],
                        duration_seconds=elapsed,
                    )

            duration = time.monotonic() - task_start

            # TODO: Extract actual outputs from Agent Teams API response
            result = TaskResult(
                task_id=task_id,
                status="completed",
                output="",
                error="",
                files_created=[],
                files_modified=[],
                duration_seconds=duration,
            )
            self._state.completed_tasks.append(task_id)
            return result

        except Exception as exc:
            duration = time.monotonic() - task_start
            _logger.error(
                "AgentTeamsBackend: single task %s failed: %s", task_id, exc
            )
            result = TaskResult(
                task_id=task_id,
                status="failed",
                output="",
                error=str(exc),
                files_created=[],
                files_modified=[],
                duration_seconds=duration,
            )
            self._state.failed_tasks.append(task_id)
            return result

    async def send_context(self, context: str) -> bool:
        """Send context string to all active teammates.

        Returns True if the context was delivered to at least one
        teammate, False otherwise.
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

        delivered = 0
        for name, handle in self._active_teammates.items():
            try:
                # TODO: Replace with actual Agent Teams SDK context delivery.
                # await agent_teams_api.send_message(handle, context)
                _logger.debug(
                    "AgentTeamsBackend: sent context to teammate %s (%d chars)",
                    name,
                    len(context),
                )
                delivered += 1
            except Exception as exc:
                _logger.warning(
                    "AgentTeamsBackend: failed to send context to %s: %s",
                    name,
                    exc,
                )

        self._state.total_messages += delivered
        return delivered > 0

    async def shutdown(self) -> None:
        """Send shutdown requests to all active teammates and deactivate.

        Each teammate receives a ``shutdown_request`` message.  The
        backend waits briefly for acknowledgments but does not block
        indefinitely.
        """
        if not self._state.active:
            _logger.debug("AgentTeamsBackend: already inactive, nothing to shut down.")
            return

        _logger.info(
            "AgentTeamsBackend: shutting down %d active teammates.",
            len(self._active_teammates),
        )

        for name, handle in list(self._active_teammates.items()):
            try:
                # TODO: Replace with actual Agent Teams SDK shutdown call.
                # await agent_teams_api.send_shutdown_request(handle)
                _logger.debug(
                    "AgentTeamsBackend: sent shutdown_request to %s", name
                )
            except Exception as exc:
                _logger.warning(
                    "AgentTeamsBackend: failed to shut down teammate %s: %s",
                    name,
                    exc,
                )

        self._active_teammates.clear()
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
