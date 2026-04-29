"""Phase 5.5 §M.M13 — `agent-team-v15 confirm-findings` interactive review + suppression registry.

Operator walks each AUDIT_REPORT.json finding and marks it
``confirmed`` (true positive) or ``rejected`` (false positive — auditor
noise). Rejections write to ``.agent-team/audit_suppressions.json``,
the persisted suppression registry. The Quality Contract resolver
honours rejected findings only after the registry validates the entry.

Suppression registry schema (per §M.M13):

.. code-block:: json

    {
      "suppressions": [
        {
          "finding_code": "string",
          "milestone_id": "string",
          "confirmation_status": "rejected",
          "operator": "string",
          "reason": "string",
          "created_at": "ISO-8601",
          "expires_at": "ISO-8601 | null",
          "auditor_prompt_hash": "string",
          "auditor_version": "string"
        }
      ]
    }

CRITICAL findings cannot be suppressed without the
``--emergency-suppress-critical`` flag — the flag logs a red warning and
writes ``emergency_critical_suppression=true`` to STATE.json so the
suppression is auditable.
"""

from __future__ import annotations

import getpass
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_SUPPRESSIONS_FILENAME = "audit_suppressions.json"
_NON_INTERACTIVE_DEFAULT_DECISION = "skip"


def _suppressions_path(cwd: Path) -> Path:
    return cwd / ".agent-team" / _SUPPRESSIONS_FILENAME


def load_suppression_registry(cwd: Path) -> dict[str, Any]:
    """Load ``.agent-team/audit_suppressions.json``; return empty registry when absent."""

    p = _suppressions_path(Path(cwd))
    if not p.is_file():
        return {"suppressions": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # Malformed registry — return empty rather than fail, but warn.
        print(
            f"[confirm-findings] WARNING: malformed {p}; treating as empty.",
            file=sys.stderr,
        )
        return {"suppressions": []}


def save_suppression_registry(cwd: Path, registry: dict[str, Any]) -> None:
    """Persist the suppression registry atomically."""

    p = _suppressions_path(Path(cwd))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(registry, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def is_finding_suppressed(
    registry: dict[str, Any],
    finding_code: str,
    milestone_id: str,
) -> bool:
    """True iff ``finding_code`` for ``milestone_id`` has a non-expired rejection in the registry.

    NOTE — this is a SHALLOW search used by the ``confirm-findings`` cli to
    detect "already suppressed" entries during interactive review. The
    Quality Contract resolver MUST use :func:`is_finding_suppression_valid`
    instead, which enforces the full §M.M13 evidence schema + CRITICAL
    emergency-state gate. Calling ``is_finding_suppressed`` from the
    resolver opens the disk-edit loophole (a minimal one-field registry
    row would bypass the contract).
    """

    now = datetime.now(timezone.utc)
    for s in registry.get("suppressions", []) or ():
        if not isinstance(s, dict):
            continue
        if s.get("finding_code") != finding_code:
            continue
        if s.get("milestone_id") and s["milestone_id"] != milestone_id:
            continue
        if s.get("confirmation_status") != "rejected":
            continue
        expires = s.get("expires_at")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if exp_dt < now:
                    continue
            except Exception:
                pass
        return True
    return False


# Phase 5.5 §M.M13 — required evidence fields on every suppression entry.
# Plan line 1629: "A suppression requires: finding code, confirmation_status='rejected'
# evidence, operator, reason, created_at, expires_at, and the exact auditor
# prompt/version that produced the false positive."
# expires_at is the only field that may be null (no expiration); all others
# must be present AND non-empty strings.
_SUPPRESSION_REQUIRED_NON_EMPTY = (
    "finding_code",
    "milestone_id",
    "operator",
    "reason",
    "created_at",
    "auditor_prompt_hash",
    "auditor_version",
)


def _state_emergency_critical_suppression(cwd: "Path | str | None") -> bool:
    """Read ``emergency_critical_suppression`` flag from STATE.json on disk.

    The flag is set by ``confirm-findings --emergency-suppress-critical``
    via :func:`_set_emergency_critical_flag`. The Quality Contract reads
    it from disk (it is not a first-class ``RunState`` field) so the
    in-memory ``state`` object passed to the resolver doesn't need a
    schema migration.
    """

    if not cwd:
        return False
    sp = Path(cwd) / ".agent-team" / "STATE.json"
    if not sp.is_file():
        return False
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(data.get("emergency_critical_suppression", False))


def is_finding_suppression_valid(
    registry: dict[str, Any],
    *,
    finding: Any,
    milestone_id: str,
    cwd: "Path | str | None" = None,
) -> bool:
    """Phase 5.5 §M.M13 — STRICT validation for Quality Contract suppression.

    Returns True only when ALL of:

    1. A registry entry matches ``finding.finding_id`` + ``milestone_id``
       (per-milestone scoped — same code in a different milestone is
       NOT auto-applied).
    2. ``confirmation_status == "rejected"``.
    3. Every required §M.M13 evidence field is present AND non-empty:
       ``finding_code``, ``milestone_id``, ``operator``, ``reason``,
       ``created_at``, ``auditor_prompt_hash``, ``auditor_version``.
       ``expires_at`` may be ``null`` (permanent suppression) but if
       present must parse and not be in the past.
    4. For CRITICAL findings, ``emergency_critical_suppression`` on
       STATE.json is True (set by ``confirm-findings --emergency-suppress-critical``).

    Falls closed on every unknown / missing condition. The Quality Contract
    resolver (``_evaluate_quality_contract``) calls this; the
    ``confirm-findings`` cli's interactive review uses the shallow
    :func:`is_finding_suppressed` instead.
    """

    finding_code = str(getattr(finding, "finding_id", "") or "")
    if not finding_code:
        return False

    severity = str(getattr(finding, "severity", "") or "").upper()

    now = datetime.now(timezone.utc)
    for entry in registry.get("suppressions", []) or ():
        if not isinstance(entry, dict):
            continue
        if entry.get("finding_code") != finding_code:
            continue
        if str(entry.get("milestone_id", "") or "") != milestone_id:
            continue
        if entry.get("confirmation_status") != "rejected":
            continue
        # Schema: every required field present + non-empty.
        schema_ok = True
        for k in _SUPPRESSION_REQUIRED_NON_EMPTY:
            v = entry.get(k)
            if not (isinstance(v, str) and v.strip()):
                schema_ok = False
                break
        if not schema_ok:
            continue
        # expires_at: may be None (permanent); else must parse + future.
        expires = entry.get("expires_at", None)
        if expires is not None:
            if not isinstance(expires, str):
                continue
            try:
                exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if exp_dt < now:
                continue
        # CRITICAL severity gate: STATE.json must carry the emergency flag.
        if severity == "CRITICAL" and not _state_emergency_critical_suppression(cwd):
            continue
        return True
    return False


def _record_suppression(
    registry: dict[str, Any],
    *,
    finding_code: str,
    milestone_id: str,
    operator: str,
    reason: str,
    expires_at: Optional[str] = None,
    auditor_prompt_hash: str = "",
    auditor_version: str = "",
) -> None:
    """Append a new rejection record to the registry."""

    registry.setdefault("suppressions", []).append({
        "finding_code": finding_code,
        "milestone_id": milestone_id,
        "confirmation_status": "rejected",
        "operator": operator or "unknown",
        "reason": reason or "",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires_at,
        "auditor_prompt_hash": auditor_prompt_hash,
        "auditor_version": auditor_version,
    })


def _set_emergency_critical_flag(cwd: Path) -> None:
    """Persist ``emergency_critical_suppression=true`` on STATE.json."""

    sp = cwd / ".agent-team" / "STATE.json"
    if not sp.is_file():
        return
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        data["emergency_critical_suppression"] = True
        sp.write_text(
            json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # pragma: no cover — defensive
        pass


def _enumerate_milestone_audit_reports(
    cwd: Path, milestone_filter: str = "",
) -> list[tuple[str, Path]]:
    """Return ``[(milestone_id, audit_report_path)]`` for every milestone with a report on disk."""

    out: list[tuple[str, Path]] = []
    canonical_root = cwd / ".agent-team" / "milestones"
    if canonical_root.is_dir():
        for ms_dir in canonical_root.iterdir():
            if not ms_dir.is_dir():
                continue
            ar = ms_dir / ".agent-team" / "AUDIT_REPORT.json"
            if ar.is_file():
                if milestone_filter and ms_dir.name != milestone_filter:
                    continue
                out.append((ms_dir.name, ar))
    # Pre-Phase-5.2 nested layout fallback.
    nested_root = cwd / ".agent-team"
    if nested_root.is_dir():
        for child in nested_root.iterdir():
            if not child.is_dir():
                continue
            if child.name in ("milestones", "anchors"):
                continue
            ar = child / ".agent-team" / "AUDIT_REPORT.json"
            if ar.is_file() and not any(ms_id == child.name for ms_id, _ in out):
                if milestone_filter and child.name != milestone_filter:
                    continue
                out.append((child.name, ar))
    return out


def confirm_findings(
    *,
    cwd: str,
    milestone_id: str = "",
    emergency_suppress_critical: bool = False,
    non_interactive: bool = False,
) -> int:
    """Phase 5.5 §M.M13 entry point.

    Returns process exit code: 0 on success, 1 on cwd issue.
    """

    cwd_path = Path(cwd)
    if not (cwd_path / ".agent-team").is_dir():
        print(f"[confirm-findings] {cwd_path}/.agent-team not found.", file=sys.stderr)
        return 1

    audit_reports = _enumerate_milestone_audit_reports(cwd_path, milestone_filter=milestone_id)
    if not audit_reports:
        print("[confirm-findings] no AUDIT_REPORT.json files found on disk.")
        return 0

    registry = load_suppression_registry(cwd_path)
    operator = getpass.getuser() if not non_interactive else "ci"

    summary = {"reviewed": 0, "confirmed": 0, "rejected": 0, "skipped": 0}

    for ms_id, ar_path in audit_reports:
        try:
            data = json.loads(ar_path.read_text(encoding="utf-8"))
        except Exception:
            print(f"[confirm-findings] {ar_path} parse error; skipping.", file=sys.stderr)
            continue
        findings = data.get("findings", []) or []
        if not findings:
            continue
        print(f"\n=== Milestone {ms_id} — {len(findings)} finding(s) ===")
        for f in findings:
            if not isinstance(f, dict):
                continue
            code = str(f.get("finding_id") or f.get("id") or "")
            severity = str(f.get("severity") or "MEDIUM").upper()
            verdict = str(f.get("verdict") or "FAIL").upper()
            current_status = str(f.get("confirmation_status") or "unconfirmed")
            summary_text = str(f.get("summary") or f.get("title") or "")[:160]

            already_suppressed = is_finding_suppressed(registry, code, ms_id)
            print(
                f"  [{severity}/{verdict}] {code} — current: {current_status} "
                f"{'(suppressed)' if already_suppressed else ''}\n    {summary_text}"
            )
            if non_interactive:
                summary["skipped"] += 1
                summary["reviewed"] += 1
                continue

            try:
                decision = input("    decision [c]onfirm / [r]eject / [s]kip: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n[confirm-findings] interrupted; saving registry.")
                save_suppression_registry(cwd_path, registry)
                return 0
            summary["reviewed"] += 1
            if decision == "c":
                summary["confirmed"] += 1
                # Confirmation does NOT modify the suppression registry;
                # it just marks the finding's confirmation_status. Phase
                # 5.5's resolver will count the finding regardless.
                # Persist to AUDIT_REPORT.json directly:
                f["confirmation_status"] = "confirmed"
            elif decision == "r":
                if severity == "CRITICAL" and not emergency_suppress_critical:
                    print(
                        "    ! CRITICAL findings cannot be suppressed without "
                        "--emergency-suppress-critical. Skipping."
                    )
                    summary["skipped"] += 1
                    continue
                if severity == "CRITICAL":
                    print(
                        "    *** EMERGENCY CRITICAL SUPPRESSION — writing "
                        "emergency_critical_suppression=true to STATE.json ***"
                    )
                    _set_emergency_critical_flag(cwd_path)
                try:
                    reason = input("    reason (one line): ").strip()
                except (EOFError, KeyboardInterrupt):
                    reason = ""
                _record_suppression(
                    registry,
                    finding_code=code,
                    milestone_id=ms_id,
                    operator=operator,
                    reason=reason,
                    auditor_prompt_hash=str(f.get("auditor") or ""),
                    auditor_version=str(data.get("audit_id") or ""),
                )
                f["confirmation_status"] = "rejected"
                summary["rejected"] += 1
            else:
                summary["skipped"] += 1

        # Persist the AUDIT_REPORT.json with updated confirmation_status fields.
        try:
            ar_path.write_text(
                json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:  # pragma: no cover — defensive
            print(f"[confirm-findings] {ar_path} write failed; continuing.", file=sys.stderr)

    save_suppression_registry(cwd_path, registry)
    print(
        f"\n[confirm-findings] reviewed={summary['reviewed']} "
        f"confirmed={summary['confirmed']} rejected={summary['rejected']} "
        f"skipped={summary['skipped']}; registry: {_suppressions_path(cwd_path)}"
    )
    return 0


__all__ = (
    "confirm_findings",
    "load_suppression_registry",
    "save_suppression_registry",
    "is_finding_suppressed",
    "is_finding_suppression_valid",
)
