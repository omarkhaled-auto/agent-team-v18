"""Claude Code PreToolUse hook — audit-session output path allowlist.

Phase 5.2 (R-#47) audit-team guardrail. Companion to:

* :mod:`agent_team_v15.wave_d_path_guard` — wave-letter-bound prefix
  list (``apps/web/**``).
* :mod:`agent_team_v15.audit_fix_path_guard` — finding-id-bound
  per-finding allowlist for audit-fix dispatches.

This guard is **audit-session-bound**: when ``AGENT_TEAM_AUDIT_WRITER=1``
is set, audit-team Claude (and its registered ``audit-*`` subagents)
may only ``Write`` / ``Edit`` / ``MultiEdit`` / ``NotebookEdit``:

* ``{AGENT_TEAM_AUDIT_OUTPUT_ROOT}/*_findings.json`` (covers both the
  canonical ``audit-<auditor>_findings.json`` shape and bare
  ``<auditor>_findings.json`` shape per plan §E.4.2)
* ``{AGENT_TEAM_AUDIT_OUTPUT_ROOT}/AUDIT_REPORT.json``
* ``{AGENT_TEAM_AUDIT_REQUIREMENTS_PATH}`` (exact-file edits)

Everything else is denied. ``Write`` to a project source file such as
``apps/api/src/main.ts`` is refused even though Phase 5.2 added
``Write`` to the ``audit-*`` agents' ``tools`` lists — those agents
need ``Write`` so they can persist findings inline rather than rely on
the parent/scorer copy-paste workaround surfaced by the 2026-04-28
smoke (BUILD_LOG lines 1281-1283, 1762-1764). The path guard is the
structural complement that bounds the scope of that ``Write``.

Mechanism (mirrors :mod:`audit_fix_path_guard`)
-----------------------------------------------

* The CLI pipes ``{"tool_name": ..., "tool_input": {...}, ...}`` to
  stdin.
* The hook prints the documented JSON envelope on stdout
  (``{"hookSpecificOutput": {"hookEventName": "PreToolUse",
  "permissionDecision": "deny|allow", ...}}``); allow is emitted as
  the empty object ``{}`` per the wave_d / audit_fix convention.
* Activation is gated on ``AGENT_TEAM_AUDIT_WRITER=1``: unset or any
  other value → deterministic no-op (allow). The audit dispatch in
  :func:`agent_team_v15.cli._run_milestone_audit` sets the env vars
  for the duration of the audit session via ``try`` / ``finally`` so
  Wave A/B/C/D, audit-fix dispatches, and other Claude sessions in
  the same run-dir leave the env unset and pass through untouched.

Asymmetry vs Wave D — fail CLOSED
---------------------------------

When the gate is active and the dispatch is malformed (missing
envelope vars, junk stdin, write to a path outside the allowlist),
the safe answer is to refuse the write. Audit findings are
recoverable; a write that mutates wave outputs while audit is
dispatched is not.

Path-comparison contract
------------------------

* Both the ``file_path`` and the allowed roots are resolved via
  ``Path.resolve(strict=False)`` BEFORE comparison. Symlinks,
  ``..`` segments, and sibling-prefix shapes (e.g.,
  ``audit-team-other/`` vs ``audit-team/``) cannot bypass via raw
  string-prefix tricks.
* The audit_output_root containment branch requires the resolved
  target to be a **direct child** of the resolved root
  (``resolved_target.parent == resolved_root``). This is tighter
  than ``Path.is_relative_to`` containment — nested shapes such as
  ``{audit_dir}/nested/AUDIT_REPORT.json`` are denied because plan
  §E.4.2 scopes writes to direct files
  ``{audit_dir}/AUDIT_REPORT.json`` and
  ``{audit_dir}/*_findings.json``, never to subtrees.
* Filename match uses ``Path.match`` against the literal patterns
  ``*_findings.json`` and ``AUDIT_REPORT.json``.
* The requirements-path comparison is exact-equality on the resolved
  ``Path`` (no glob, no prefix).

Hook-timeout overrun is treated as **allow** by Claude Code (per the
documented contract; v2.1.74 changelog notes the subprocess is killed
and the action proceeds). We protect against this by keeping the hook
tiny + fast — parse stdin, resolve a few paths, two membership tests.
It is implausible to exceed the configured 5-second timeout under any
realistic load.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .wave_d_path_guard import _emit_decision


_WRITE_TOOLS: frozenset[str] = frozenset(
    {"Write", "Edit", "MultiEdit", "NotebookEdit"}
)

# Filename whitelist for the audit_output_root direct-child branch.
# ``Path.match`` uses pathlib glob semantics; the rightmost segment is
# matched against the pattern. Plan §E.4.2 enumerates BOTH
# ``{audit_dir}/*_findings.json`` (any name ending in ``_findings.json``)
# and ``{audit_dir}/audit-*_findings.json`` (the canonical
# ``audit-<auditor>_findings.json`` shape) as allowed; ``*_findings.json``
# is the broader allowlist that subsumes the narrower ``audit-*`` one,
# so we use it directly. Direct files such as
# ``{audit_dir}/requirements_findings.json`` (plan example without the
# ``audit-`` prefix) are allowed.
_FINDINGS_FILENAME_PATTERN = "*_findings.json"
_REPORT_FILENAME = "AUDIT_REPORT.json"

# Phase 5.2 R-#47 follow-up — active guard decision log filename.
# Lives at ``<AGENT_TEAM_AUDIT_OUTPUT_ROOT>/audit_output_guard_decisions.jsonl``.
# JSONL append-mode so concurrent auditor sessions cannot stomp each
# other's entries. The 2026-04-28 Wave 1 closeout smoke surfaced a
# live-validation gap where the guard's enforcement could not be
# proven from the artifacts alone; this log records every decision
# the hook makes so smoke reviewers can cite the audit trail.
_DECISION_LOG_FILENAME = "audit_output_guard_decisions.jsonl"


def _append_decision_log(
    *,
    audit_output_root: str,
    decision: str,
    reason: str,
    tool_name: str,
    file_path: str,
) -> None:
    """Append a JSONL decision entry to the per-run audit-guard log.

    Phase 5.2 R-#47 follow-up — active live-evidence collection.
    Only invoked when ``AGENT_TEAM_AUDIT_WRITER=1`` AND
    ``AGENT_TEAM_AUDIT_OUTPUT_ROOT`` is populated; the no-op
    ``audit_writer != "1"`` path does NOT log (no-op dispatches don't
    produce evidence to record). The fail-closed branch where the
    env var is set but the root is empty also does NOT log here —
    there is no safe destination, so stderr is the fallback.

    Failures (filesystem permission, missing parent, etc.) are
    swallowed after a stderr breadcrumb so the guard's primary
    decision path always emits its envelope. The decision log is
    instrumentation, not enforcement.
    """

    try:
        log_path = Path(audit_output_root) / _DECISION_LOG_FILENAME
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "tool": tool_name,
            "file_path": file_path,
            "decision": decision,
            "reason": reason or None,
        }
        # Single ``open(..., "a")`` + ``write`` per call; POSIX
        # ``O_APPEND`` semantics make the write atomic for line-sized
        # payloads <= PIPE_BUF (4096 bytes on Linux). Decision entries
        # are well under that budget.
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False))
            handle.write("\n")
    except (OSError, ValueError) as exc:  # pragma: no cover — defensive
        sys.stderr.write(
            f"audit-output path-guard: decision-log append failed "
            f"({type(exc).__name__}: {exc}); decision still emitted\n"
        )


def _deny(
    reason: str,
    *,
    audit_output_root: str = "",
    tool_name: str = "",
    file_path: str = "",
) -> None:
    if audit_output_root:
        _append_decision_log(
            audit_output_root=audit_output_root,
            decision="deny",
            reason=reason,
            tool_name=tool_name,
            file_path=file_path,
        )
    _emit_decision(decision="deny", reason=reason)


def _allow(
    *,
    audit_output_root: str = "",
    tool_name: str = "",
    file_path: str = "",
) -> None:
    if audit_output_root:
        _append_decision_log(
            audit_output_root=audit_output_root,
            decision="allow",
            reason="",
            tool_name=tool_name,
            file_path=file_path,
        )
    _emit_decision(decision="allow")


def _resolve_against_cwd(file_path: str, cwd: str) -> Path | None:
    """Resolve ``file_path`` to an absolute path, anchoring relative
    paths against ``cwd`` when supplied. Returns ``None`` on resolution
    failure.

    ``Path.resolve(strict=False)`` normalises ``..`` and follows
    existing symlinks; non-existent path components are accepted as-is
    (the audit_dir / requirements_path may not exist on disk yet at
    the moment a write tool is invoked).
    """

    try:
        candidate = Path(file_path)
        if not candidate.is_absolute() and cwd:
            candidate = Path(cwd) / candidate
        return candidate.resolve(strict=False)
    except (OSError, ValueError):
        return None


def main() -> int:
    """Hook entry point — see module docstring for protocol."""

    audit_writer = (os.environ.get("AGENT_TEAM_AUDIT_WRITER") or "").strip()
    if audit_writer != "1":
        # Non-audit dispatch (Wave A/B/C/D, audit-fix, repairs, etc.)
        # — completely transparent. No decision-log entry: only active
        # audit dispatches produce evidence to record (per Phase 5.2
        # R-#47 follow-up reviewer guidance — log destination
        # ``audit_output_guard_decisions.jsonl`` lives under the
        # audit_output_root which is undefined in this branch).
        _allow()
        return 0

    audit_output_root = (
        os.environ.get("AGENT_TEAM_AUDIT_OUTPUT_ROOT") or ""
    ).strip()
    audit_requirements_path = (
        os.environ.get("AGENT_TEAM_AUDIT_REQUIREMENTS_PATH") or ""
    ).strip()
    if not audit_output_root:
        # Active gate but missing required envelope var → malformed
        # dispatch. Fail CLOSED. The decision log requires a known
        # destination; with no root, the deny + stderr breadcrumb is
        # the only safe evidence path (per reviewer 2026-04-29:
        # "If root is missing, fail closed and stderr is enough;
        # there is no safe log destination").
        sys.stderr.write(
            "audit-output path-guard: ACTIVE deny (env var "
            "AGENT_TEAM_AUDIT_WRITER=1 but AGENT_TEAM_AUDIT_OUTPUT_ROOT "
            "empty — no decision-log destination)\n"
        )
        _deny(
            "audit-output path-guard: AGENT_TEAM_AUDIT_WRITER=1 was "
            "set but AGENT_TEAM_AUDIT_OUTPUT_ROOT is empty; refusing "
            "the write rather than letting an unscoped audit dispatch "
            "through. Populate the env vars before audit dispatch."
        )
        return 0

    try:
        raw_stdin = sys.stdin.read()
        if not raw_stdin.strip():
            _deny(
                "audit-output path-guard: empty stdin payload while "
                "AGENT_TEAM_AUDIT_WRITER=1; cannot classify the write "
                "— refusing per fail-CLOSED contract.",
                audit_output_root=audit_output_root,
                tool_name="<unknown>",
                file_path="<empty-stdin>",
            )
            return 0
        payload = json.loads(raw_stdin)
    except (json.JSONDecodeError, OSError) as exc:
        _deny(
            "audit-output path-guard: malformed stdin payload ("
            + type(exc).__name__
            + "); refusing per fail-CLOSED contract.",
            audit_output_root=audit_output_root,
            tool_name="<unknown>",
            file_path=f"<stdin-parse-{type(exc).__name__}>",
        )
        return 0

    tool_name = str(payload.get("tool_name") or "").strip()
    if tool_name not in _WRITE_TOOLS:
        # Non-mutating tools (Read/Glob/Grep/Bash/Task) always pass —
        # the path-guard scope is write/edit only. Log so the smoke
        # decision-log records the read traffic the auditors do
        # legitimately (proves the hook actually saw the env-active
        # session — i.e., the live-validation evidence the 2026-04-28
        # smoke could not produce).
        _allow(
            audit_output_root=audit_output_root,
            tool_name=tool_name,
            file_path="<non-write-tool>",
        )
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or tool_input.get("path")
        or ""
    )
    if not isinstance(file_path, str) or not file_path.strip():
        _deny(
            "audit-output path-guard: write tool '"
            + tool_name
            + "' invoked with no file_path; refusing per fail-CLOSED "
            "contract.",
            audit_output_root=audit_output_root,
            tool_name=tool_name,
            file_path="<missing>",
        )
        return 0

    cwd = (
        payload.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.environ.get("AGENT_TEAM_PROJECT_DIR")
        or ""
    )
    resolved_target = _resolve_against_cwd(file_path, cwd)
    if resolved_target is None:
        _deny(
            "audit-output path-guard: could not resolve file_path '"
            + file_path
            + "'; refusing per fail-CLOSED contract.",
            audit_output_root=audit_output_root,
            tool_name=tool_name,
            file_path=file_path,
        )
        return 0

    resolved_str = str(resolved_target)

    # Allowed envelope #1 — exact-file edits to the requirements_path.
    if audit_requirements_path:
        try:
            resolved_req = Path(audit_requirements_path).resolve(strict=False)
        except (OSError, ValueError):
            resolved_req = None
        if resolved_req is not None and resolved_target == resolved_req:
            _allow(
                audit_output_root=audit_output_root,
                tool_name=tool_name,
                file_path=resolved_str,
            )
            return 0

    # Allowed envelope #2 — DIRECT children of audit_output_root only,
    # with a filename match against the audit-output whitelist. Plan
    # §E.4.2 scopes writes to ``{audit_dir}/AUDIT_REPORT.json`` and
    # ``{audit_dir}/*_findings.json`` (the broader pattern covers both
    # bare ``<auditor>_findings.json`` and canonical
    # ``audit-<auditor>_findings.json`` shapes) — direct files only,
    # never subtrees. Subtree containment via ``is_relative_to`` would
    # allow nested shapes (e.g., ``{audit_dir}/nested/AUDIT_REPORT.json``)
    # which create unconsumed audit outputs in stale locations and
    # broaden R-#47's scope beyond the contract. Require
    # ``resolved_target.parent == resolved_root`` for an exact-segment
    # match.
    try:
        resolved_root = Path(audit_output_root).resolve(strict=False)
    except (OSError, ValueError):
        resolved_root = None
    if resolved_root is not None and resolved_target.parent == resolved_root:
        target_name = resolved_target.name
        if (
            target_name == _REPORT_FILENAME
            or resolved_target.match(_FINDINGS_FILENAME_PATTERN)
        ):
            _allow(
                audit_output_root=audit_output_root,
                tool_name=tool_name,
                file_path=resolved_str,
            )
            return 0

    _deny(
        "audit-output path-guard: tool '"
        + tool_name
        + "' refused on out-of-scope path '"
        + resolved_str
        + "'. Audit-session writes are restricted to direct children "
        "of {AGENT_TEAM_AUDIT_OUTPUT_ROOT} matching either "
        "*_findings.json or AUDIT_REPORT.json, plus exact-file edits "
        "to {AGENT_TEAM_AUDIT_REQUIREMENTS_PATH}. If the audit team "
        "needs to mutate other files, raise the scope explicitly in "
        "plan §E.4.2 rather than expanding the env-var allowlist.",
        audit_output_root=audit_output_root,
        tool_name=tool_name,
        file_path=resolved_str,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
