"""Claude Code PreToolUse hook — Wave D path-write sandbox.

Wave D is the frontend wave; its only legitimate write surface is
``apps/web/**``. The Wave D agent (Claude via Agent Teams) has been
empirically observed drifting onto root-level files (``tsconfig.base.json``)
and Wave C deliverables (``packages/api-client/*``) under prompt-only
restrictions. Prompt rules are advisory; this hook makes the boundary
deterministic.

Mechanism
---------

This module is invoked by Claude Code as a ``PreToolUse`` hook (per the
``Claude Code`` hook contract documented at
https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md
and verified via Context7 ``/anthropics/claude-code``):

* The CLI pipes a JSON payload to stdin: ``{"tool_name": "...",
  "tool_input": {...}, ...}``.
* The hook prints a JSON envelope on stdout:
  ``{"hookSpecificOutput": {"hookEventName": "PreToolUse",
  "permissionDecision": "deny", "permissionDecisionReason": "..."}}``
  to block, or exits 0 with empty stdout to allow.
* Wave-letter awareness comes from the ``AGENT_TEAM_WAVE_LETTER``
  environment variable that ``agent_teams_backend`` sets per-task. The
  hook is a no-op for any wave other than ``D``, so non-Wave-D Claude
  dispatches (Wave A, audits, repairs) are completely unaffected.

The hook fires only for write-class tools (``Write``, ``Edit``,
``MultiEdit``, ``NotebookEdit``) — Reads remain unrestricted so Wave D
can still consume ``packages/api-client/`` types without a deny.

Design intent
-------------

* Allow ``apps/web/**`` writes (frontend deliverable scope).
* Deny everything else when ``AGENT_TEAM_WAVE_LETTER == "D"``.
* Fail-open on parse errors / missing tool_input — never silently
  block a wave because of a parser bug. The post-wave checkpoint diff
  (``_apply_post_wave_scope_validation`` in ``wave_executor``) remains
  the second-line defense.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import PurePosixPath


_WRITE_TOOLS: frozenset[str] = frozenset(
    {"Write", "Edit", "MultiEdit", "NotebookEdit"}
)
_WAVE_D_ALLOWED_PREFIXES: tuple[str, ...] = (
    "apps/web/",
)
# Files at the workspace root or other directories that Wave D may
# legitimately touch despite living outside ``apps/web/``. Empty for
# now — the prompt-level scaffold-deliverables block already covers
# the legitimate exceptions through Wave B / scaffold ownership, not
# Wave D.
_WAVE_D_ALLOWED_FILES: frozenset[str] = frozenset()


def _normalize_relative(file_path: str, cwd: str) -> str:
    """Return ``file_path`` as a forward-slash path relative to ``cwd``.

    Falls back to the original path when relativisation fails (cross-
    drive paths on Windows, etc.); the caller treats unknown paths as
    out-of-scope which keeps the boundary safe.
    """
    if not file_path:
        return ""
    raw = file_path.replace("\\", "/").strip()
    if not raw:
        return ""
    cwd_norm = (cwd or "").replace("\\", "/").rstrip("/")
    if cwd_norm and raw.lower().startswith(cwd_norm.lower() + "/"):
        return raw[len(cwd_norm) + 1 :]
    if cwd_norm and raw.lower() == cwd_norm.lower():
        return ""
    # Already relative.
    return raw


def _is_under_allowed_prefix(rel_posix: str) -> bool:
    if not rel_posix:
        return False
    pure = PurePosixPath(rel_posix)
    if pure.is_absolute():
        # Absolute paths that fell through ``_normalize_relative``
        # (e.g., paths on a different drive) cannot be safely classified
        # as in-scope. Treat as out-of-scope.
        return False
    parts = pure.parts
    if not parts:
        return False
    # ``..`` traversal escapes scope by construction.
    if any(part == ".." for part in parts):
        return False
    normalized = "/".join(parts)
    if normalized in _WAVE_D_ALLOWED_FILES:
        return True
    return any(normalized.startswith(prefix) for prefix in _WAVE_D_ALLOWED_PREFIXES)


def _emit_decision(
    *,
    decision: str,
    reason: str = "",
) -> None:
    """Print the Claude Code PreToolUse hook envelope and exit cleanly.

    The envelope shape follows the documented contract:
    ``{"hookSpecificOutput": {"hookEventName": "PreToolUse",
    "permissionDecision": "...", "permissionDecisionReason": "..."}}``.
    Allow paths emit ``{}`` (empty object) which the CLI treats as a
    no-op and proceeds with the tool call.
    """
    if decision == "allow":
        sys.stdout.write("{}\n")
        sys.stdout.flush()
        sys.exit(0)
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    sys.stdout.flush()
    sys.exit(0)


def main() -> int:
    """Hook entry point — see module docstring for protocol."""

    wave_letter = (os.environ.get("AGENT_TEAM_WAVE_LETTER") or "").strip().upper()
    if wave_letter != "D":
        # Hook is wave-D-only; non-D dispatches are unaffected.
        _emit_decision(decision="allow")
        return 0

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            _emit_decision(decision="allow")
            return 0
        payload = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        # Fail-open on parse errors — second-line defense
        # (post-wave checkpoint diff) still catches real drift.
        _emit_decision(decision="allow")
        return 0

    tool_name = str(payload.get("tool_name") or "").strip()
    if tool_name not in _WRITE_TOOLS:
        _emit_decision(decision="allow")
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or tool_input.get("path")
        or ""
    )
    if not isinstance(file_path, str) or not file_path.strip():
        _emit_decision(decision="allow")
        return 0

    cwd = (
        payload.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.environ.get("AGENT_TEAM_PROJECT_DIR")
        or ""
    )
    rel = _normalize_relative(file_path, cwd)

    if _is_under_allowed_prefix(rel):
        _emit_decision(decision="allow")
        return 0

    reason = (
        "Wave D is the frontend specialist and may only write under "
        "apps/web/**. Refusing tool '"
        + tool_name
        + "' on out-of-scope path '"
        + (rel or file_path)
        + "'. If you believe the milestone requires touching a non-frontend "
        "file, write WAVE_D_CONTRACT_CONFLICT.md describing the required "
        "exception and stop."
    )
    _emit_decision(decision="deny", reason=reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
