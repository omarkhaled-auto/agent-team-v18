"""Claude Code PreToolUse hook — audit-fix per-finding path-write
allowlist.

Phase 3 audit-fix-loop guardrail. Companion to
:mod:`agent_team_v15.wave_d_path_guard` — same canonical envelope,
different scope semantics:

* **Wave D guard** (existing) restricts a wave-letter-bound dispatch
  to a static prefix list (``apps/web/**``).
* **Audit-fix guard** (this module) restricts each audit-fix dispatch
  to the per-finding allowlist passed via env vars
  (``AGENT_TEAM_FINDING_ID`` + ``AGENT_TEAM_ALLOWED_PATHS``).

Together with the Phase 1 milestone-anchor (recoverable rollback) and
the Phase 2 cross-milestone test-surface lock (loud cross-fix
regressions), this hook is the third layer of M25-disaster prevention:
a fix targeting one acceptance criterion physically cannot author a
write outside its declared scope.

Mechanism
---------

* The CLI pipes a JSON payload to stdin: ``{"tool_name": "...",
  "tool_input": {...}, ...}`` (same as Wave D).
* The hook prints a JSON envelope on stdout following the documented
  contract:
  ``{"hookSpecificOutput": {"hookEventName": "PreToolUse",
  "permissionDecision": "deny",
  "permissionDecisionReason": "..."}}`` to block, or ``{}`` to allow.
* Activation is gated on ``AGENT_TEAM_FINDING_ID``: if unset/empty the
  hook is a deterministic no-op (allow). The audit-fix dispatch flow
  in :mod:`agent_team_v15.cli` sets the env var per-feature; all other
  Claude dispatches in the same run-dir (Wave A/B/C/D, audits,
  repairs) leave it unset and pass through untouched.

Asymmetry vs Wave D — fail CLOSED
---------------------------------

Wave D path-guard fails OPEN on parse error (allow) because the
post-wave checkpoint diff is the second-line defence and the M25
disaster scenario lives downstream of audit-fix, not Wave D.

Audit-fix path-guard fails CLOSED (deny) because:

* Audit-fix is the higher-risk surface — the M25 disaster IS an
  audit-fix loop corrupting prior-milestone surface area.
* When a malformed dispatch reaches this hook (missing finding id,
  empty allowlist, junk stdin) the safe answer is to refuse the
  write; an aborted fix attempt is recoverable, a destructive
  out-of-scope edit is not.

Hook-timeout overrun is treated as **allow** by Claude Code (per the
documented contract; v2.1.74 changelog notes the subprocess is killed
and the action proceeds rather than blocking). We protect against this
by keeping the hook tiny + fast (parse stdin, two env reads, a path
lookup) — it is implausible to exceed the configured 5-second timeout
under any realistic load.
"""

from __future__ import annotations

import json
import os
import sys

from .wave_d_path_guard import (
    _decide_from_allowlist,
    _emit_decision,
    _normalize_relative,
)


_WRITE_TOOLS: frozenset[str] = frozenset(
    {"Write", "Edit", "MultiEdit", "NotebookEdit"}
)


def _parse_allowed_paths(raw: str) -> list[str]:
    """Parse the ``AGENT_TEAM_ALLOWED_PATHS`` env var.

    The format is a colon-separated list of forward-slash relative
    paths. Empty entries are dropped. Backslashes are normalised to
    forward slashes so callers can pass POSIX or native shapes
    interchangeably.

    Returns the parsed list with whitespace-stripped, non-empty
    entries.
    """
    if not raw:
        return []
    parsed: list[str] = []
    for chunk in raw.split(":"):
        normalized = chunk.replace("\\", "/").strip().lstrip("/")
        if normalized:
            parsed.append(normalized)
    return parsed


def _deny(reason: str) -> None:
    _emit_decision(decision="deny", reason=reason)


def main() -> int:
    """Hook entry point — see module docstring for protocol."""

    finding_id = (os.environ.get("AGENT_TEAM_FINDING_ID") or "").strip()
    if not finding_id:
        # Non-audit-fix dispatch — completely transparent.
        _emit_decision(decision="allow")
        return 0

    raw_paths = os.environ.get("AGENT_TEAM_ALLOWED_PATHS") or ""
    allowed_files = _parse_allowed_paths(raw_paths)
    if not allowed_files:
        # Active gate (FINDING_ID set) but no allowlist → malformed
        # dispatch. Fail CLOSED.
        _deny(
            "audit-fix path-guard: AGENT_TEAM_FINDING_ID="
            + finding_id
            + " was set but AGENT_TEAM_ALLOWED_PATHS is empty; refusing "
            "the write rather than letting an unscoped fix attempt "
            "through. If this is a legitimate dispatch, populate the "
            "allowlist before invocation."
        )
        return 0

    try:
        raw_stdin = sys.stdin.read()
        if not raw_stdin.strip():
            _deny(
                "audit-fix path-guard: empty stdin payload for finding="
                + finding_id
                + "; cannot classify the write — refusing per fail-CLOSED "
                "contract."
            )
            return 0
        payload = json.loads(raw_stdin)
    except (json.JSONDecodeError, OSError) as exc:
        _deny(
            "audit-fix path-guard: malformed stdin payload for finding="
            + finding_id
            + " ("
            + type(exc).__name__
            + "); refusing per fail-CLOSED contract."
        )
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
        # Write-class tool with no path is malformed — fail CLOSED.
        _deny(
            "audit-fix path-guard: write tool '"
            + tool_name
            + "' invoked with no file_path for finding="
            + finding_id
            + "; refusing per fail-CLOSED contract."
        )
        return 0

    cwd = (
        payload.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.environ.get("AGENT_TEAM_PROJECT_DIR")
        or ""
    )
    rel = _normalize_relative(file_path, cwd)
    # Each entry in the allowlist is treated as an exact-file
    # permission. Phase 3 deliberately does NOT support directory-glob
    # entries — the per-finding scope is the finding's primary_file
    # plus its sibling test files, both fully-qualified relative paths.
    allowed_files = [path for path in allowed_files]
    if _decide_from_allowlist(rel, allowed_prefixes=(), allowed_files=frozenset(allowed_files)):
        _emit_decision(decision="allow")
        return 0

    _deny(
        "audit-fix path-guard: tool '"
        + tool_name
        + "' refused on out-of-scope path '"
        + (rel or file_path)
        + "' for finding="
        + finding_id
        + ". Allowlist (colon-separated): "
        + raw_paths
        + ". If the milestone requires touching this path, raise the "
        "scope explicitly in the audit finding's evidence rather than "
        "expanding the allowlist mid-dispatch."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
