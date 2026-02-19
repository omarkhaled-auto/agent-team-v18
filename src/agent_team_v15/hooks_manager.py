"""Claude Code hooks configuration generation for Agent Teams.

Generates ``.claude/settings.local.json`` with hook definitions and
companion shell scripts that enforce quality gates, idle-task checks,
and file-change tracking during agent-team orchestration sessions.

Hook types supported:
* **agent** -- delegates to Claude with a custom prompt.
* **command** -- runs a shell script (optionally async, with matchers).

The public entry points are :func:`generate_hooks_config` (build the
in-memory config) and :func:`write_hooks_to_project` (persist it to
disk).
"""

from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import AgentTeamConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class HookConfig:
    """In-memory representation of a full hooks configuration."""

    hooks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    """Maps event names (e.g. ``"Stop"``) to lists of hook dicts."""

    scripts: dict[str, str] = field(default_factory=dict)
    """Maps script filenames (relative to ``.claude/hooks/``) to content."""


@dataclass
class HookInput:
    """Typed representation of the JSON blob Claude Code passes to hooks.

    Not every field is populated for every event -- callers should treat
    absent/empty strings as *not applicable*.
    """

    session_id: str = ""
    transcript_path: str = ""
    cwd: str = ""
    permission_mode: str = ""
    hook_event_name: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)

    # Event-specific optional fields
    task_id: str = ""
    task_subject: str = ""
    task_description: str = ""
    teammate_name: str = ""
    team_name: str = ""


# ---------------------------------------------------------------------------
# Individual hook generators
# ---------------------------------------------------------------------------


def generate_task_completed_hook() -> dict[str, Any]:
    """Return an *agent*-type hook dict for the ``TaskCompleted`` event.

    The agent is instructed to read REQUIREMENTS.md and verify that every
    item marked ``[x]`` is genuinely implemented in the codebase.
    """
    return {
        "hooks": [{
            "type": "agent",
            "prompt": (
                "Read REQUIREMENTS.md and verify that all items marked [x] are "
                "actually implemented in the codebase. For each checked item, "
                "confirm the corresponding code exists. If any item is marked "
                "complete but the implementation is missing or incomplete, "
                "report the discrepancy and uncheck the item."
            ),
            "timeout": 120,
        }],
    }


def generate_teammate_idle_hook() -> tuple[dict[str, Any], str]:
    """Return a *command*-type hook dict **and** its script for ``TeammateIdle``.

    The script invokes ``claude -p`` to inspect the task list and exits
    with code **2** (block the transition) when unblocked pending tasks
    still exist, or **0** when all tasks are done or blocked.
    """
    hook_dict: dict[str, Any] = {
        "type": "command",
        "command": ".claude/hooks/teammate-idle-check.sh",
        "timeout": 30,
    }

    script_content = textwrap.dedent("""\
        #!/usr/bin/env bash
        set -euo pipefail

        # Ask Claude to inspect the task list for pending unblocked tasks.
        result=$(claude -p "Check TaskList for any pending tasks that are NOT blocked. Reply ONLY with 'PENDING' if unblocked pending tasks exist, or 'DONE' if all tasks are completed or blocked." 2>/dev/null || true)

        if echo "$result" | grep -qi "PENDING"; then
            echo "There are still pending unblocked tasks. Resuming work." >&2
            exit 2
        fi

        # All tasks are done or blocked -- allow idle transition.
        exit 0
    """)

    return {"hooks": [hook_dict]}, script_content


def generate_stop_hook(
    requirements_path: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Return a *command*-type hook dict **and** its script for ``Stop``.

    The script reads the HookInput JSON from stdin, extracts ``cwd``,
    then checks the REQUIREMENTS.md completion ratio.  If fewer than 80 %
    of requirement items are checked, the hook exits **2** (block stop)
    with a descriptive message on stderr.
    """
    hook_dict: dict[str, Any] = {
        "type": "command",
        "command": ".claude/hooks/quality-gate.sh",
        "timeout": 30,
    }

    script_content = textwrap.dedent("""\
        #!/usr/bin/env bash
        set -euo pipefail

        # Read HookInput JSON from stdin and extract the working directory.
        CWD=$(python3 -c "import sys,json; print(json.load(sys.stdin)['cwd'])")

        REQ_FILE="$CWD/REQUIREMENTS.md"

        if [ ! -f "$REQ_FILE" ]; then
            # No requirements file -- nothing to enforce.
            exit 0
        fi

        DONE=$(grep -c '\\[x\\]' "$REQ_FILE" || true)
        TODO=$(grep -c '\\[ \\]' "$REQ_FILE" || true)
        TOTAL=$((DONE + TODO))

        if [ "$TOTAL" -eq 0 ]; then
            # No checkbox items found -- pass through.
            exit 0
        fi

        # Calculate completion ratio (integer math: multiply first).
        RATIO_OK=$(python3 -c "print(1 if $DONE / $TOTAL >= 0.8 else 0)")

        if [ "$RATIO_OK" -eq 0 ]; then
            echo "Quality gate FAILED: only $DONE/$TOTAL requirements completed ($(python3 -c "print(f'{$DONE/$TOTAL:.0%}')")) -- need at least 80%." >&2
            exit 2
        fi

        exit 0
    """)

    return {"hooks": [hook_dict]}, script_content


def generate_post_tool_use_hook() -> tuple[dict[str, Any], str]:
    """Return an async *command*-type hook dict **and** its script for ``PostToolUse``.

    Only fires for ``Write`` or ``Edit`` tool invocations (via the
    ``matcher`` pattern).  The script logs the tool name and file
    information to ``.claude/hooks/file-changes.log``.
    """
    hook_dict: dict[str, Any] = {
        "type": "command",
        "command": ".claude/hooks/track-file-change.sh",
        "timeout": 30,
        "async": True,
    }

    script_content = textwrap.dedent("""\
        #!/usr/bin/env bash
        set -euo pipefail

        # Read HookInput JSON from stdin.
        INPUT=$(cat)

        TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name','unknown'))")
        FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; ti=json.load(sys.stdin).get('tool_input',{}); print(ti.get('file_path', ti.get('path','unknown')))")
        CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd','.'))")

        LOG_DIR="$CWD/.claude/hooks"
        mkdir -p "$LOG_DIR"

        TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        echo "$TIMESTAMP | tool=$TOOL_NAME | file=$FILE_PATH" >> "$LOG_DIR/file-changes.log"
    """)

    return {"matcher": "Write|Edit", "hooks": [hook_dict]}, script_content


# ---------------------------------------------------------------------------
# Main assembly
# ---------------------------------------------------------------------------


def generate_hooks_config(
    config: AgentTeamConfig,
    project_dir: Path,
    requirements_path: Path | None = None,
) -> HookConfig:
    """Assemble a complete :class:`HookConfig` from all individual generators.

    Parameters
    ----------
    config:
        The full agent-team configuration (used for future per-hook
        enable/disable flags).
    project_dir:
        Root of the project being orchestrated.
    requirements_path:
        Optional explicit path to REQUIREMENTS.md (forwarded to the
        stop-hook generator).
    """
    hook_config = HookConfig()

    # --- TaskCompleted (agent hook -- no script) ---
    task_completed = generate_task_completed_hook()
    hook_config.hooks.setdefault("TaskCompleted", []).append(task_completed)

    # --- TeammateIdle ---
    idle_hook, idle_script = generate_teammate_idle_hook()
    hook_config.hooks.setdefault("TeammateIdle", []).append(idle_hook)
    hook_config.scripts["teammate-idle-check.sh"] = idle_script

    # --- Stop (quality gate) ---
    stop_hook, stop_script = generate_stop_hook(requirements_path)
    hook_config.hooks.setdefault("Stop", []).append(stop_hook)
    hook_config.scripts["quality-gate.sh"] = stop_script

    # --- PostToolUse (file-change tracker) ---
    post_hook, post_script = generate_post_tool_use_hook()
    hook_config.hooks.setdefault("PostToolUse", []).append(post_hook)
    hook_config.scripts["track-file-change.sh"] = post_script

    logger.debug(
        "Generated hooks config: %d events, %d scripts",
        len(hook_config.hooks),
        len(hook_config.scripts),
    )
    return hook_config


# ---------------------------------------------------------------------------
# Disk persistence
# ---------------------------------------------------------------------------


def write_hooks_to_project(hook_config: HookConfig, project_dir: Path) -> Path:
    """Persist *hook_config* into the project's ``.claude/`` directory tree.

    * Creates ``.claude/`` and ``.claude/hooks/`` if needed.
    * Writes (or **merges** into) ``.claude/settings.local.json``.
    * Writes each script to ``.claude/hooks/<filename>``.
    * Attempts ``chmod 0o755`` on scripts (gracefully ignored on Windows).

    Returns the path to ``settings.local.json``.
    """
    claude_dir = project_dir / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    settings_path = claude_dir / "settings.local.json"

    # ---- Merge with existing settings (if any) ----
    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Could not parse existing %s -- overwriting: %s",
                settings_path,
                exc,
            )
            existing = {}

    existing["hooks"] = hook_config.hooks
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Wrote hooks configuration to %s", settings_path)

    # ---- Write companion scripts ----
    for filename, content in hook_config.scripts.items():
        script_path = hooks_dir / filename
        script_path.write_text(content, encoding="utf-8")
        try:
            script_path.chmod(0o755)
        except OSError:
            # Windows does not support POSIX permission bits.
            pass
        logger.debug("Wrote hook script %s", script_path)

    return settings_path
