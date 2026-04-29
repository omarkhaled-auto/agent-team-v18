"""Phase 5.5 §M.M10 — `agent-team-v15 rescan-quality-debt` migration command.

Re-evaluates each completed milestone in an existing run-directory against
the post-Phase-5 Quality Contract. Populates the Phase 5.3 quality-debt
fields on STATE.json from the on-disk AUDIT_REPORT.json so dashboards /
downstream consumers can see retroactive degradation that landed before
Phase 5.5 shipped.

Migration window: handles BOTH the post-Phase-5.2 canonical
``<run-dir>/.agent-team/milestones/<id>/.agent-team/AUDIT_REPORT.json``
AND the pre-Phase-5.2 nested
``<run-dir>/.agent-team/<id>/.agent-team/AUDIT_REPORT.json`` shapes.

Layer-2 state-invariant validators run in WARN-ONLY mode for this command
so pre-Phase-5 hollow-recovery STATE.json shapes can be REPORTED without
bricking the migration. Operators see the violations in the operator
report.

Operator-overridable: ``--rescan-overwrite-status`` rewrites status
``COMPLETE -> DEGRADED`` retroactively for milestones that fail the
Quality Contract; this is a breaking change to the STATE.json status
enum and downstream tooling consumers (CI/CD, dashboards). Operator
opts in explicitly.

Output: ``QUALITY_DEBT_RESCAN.md`` operator-readable report at
``<run-dir>/.agent-team/QUALITY_DEBT_RESCAN.md``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _resolve_audit_report_path(run_dir: Path, milestone_id: str) -> Optional[Path]:
    """Return the AUDIT_REPORT.json path on disk for ``milestone_id``.

    Tries canonical (post-Phase-5.2) layout first, then nested
    (pre-Phase-5.2) layout. Returns None when neither exists.
    """

    canonical = (
        run_dir / ".agent-team" / "milestones" / milestone_id / ".agent-team" / "AUDIT_REPORT.json"
    )
    if canonical.is_file():
        return canonical
    nested = run_dir / ".agent-team" / milestone_id / ".agent-team" / "AUDIT_REPORT.json"
    if nested.is_file():
        return nested
    return None


def _build_minimal_run_state(state_dict: dict) -> Any:
    """Build a duck-typed RunState-like object for compute_finding_status.

    The actual ``state.RunState`` dataclass requires more fields than the
    rescan command needs to load — we only need ``executed_waves`` and
    ``milestone_progress`` keys, which are present on disk. Constructing
    a SimpleNamespace mirrors the Phase 4.3 wave-ownership read pattern.
    """

    from types import SimpleNamespace
    return SimpleNamespace(
        executed_waves=state_dict.get("executed_waves", []),
        milestone_progress=state_dict.get("milestone_progress", {}),
        completed_milestones=state_dict.get("completed_milestones", []),
        failed_milestones=state_dict.get("failed_milestones", []),
    )


def _evaluate_milestone(
    audit_report_path: Path,
    state_dict: dict,
    legacy_permissive_audit: bool,
) -> tuple[str, str, int, str]:
    """Evaluate the Quality Contract for a single milestone.

    Returns the same tuple shape as
    :func:`agent_team_v15.quality_contract._evaluate_quality_contract`.
    """

    from .audit_models import AuditReport
    from .quality_contract import _evaluate_quality_contract
    from types import SimpleNamespace

    try:
        audit_report = AuditReport.from_json(
            audit_report_path.read_text(encoding="utf-8")
        )
    except Exception:
        return ("COMPLETE", "unknown", 0, "")

    run_state = _build_minimal_run_state(state_dict)
    config = SimpleNamespace(v18=SimpleNamespace(legacy_permissive_audit=legacy_permissive_audit))

    return _evaluate_quality_contract(audit_report, run_state, config)


def _format_report(
    run_dir: Path,
    findings: list[dict],
    rescan_overwrite_status: bool,
    legacy_permissive_audit: bool,
    invariant_violations: list[str],
) -> str:
    """Render QUALITY_DEBT_RESCAN.md operator report."""

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Phase 5.5 §M.M10 — Quality Debt Rescan Report",
        "",
        f"**Run-directory:** `{run_dir.as_posix()}`",
        f"**Rescan-time (UTC):** {timestamp}",
        f"**--rescan-overwrite-status:** {'YES' if rescan_overwrite_status else 'no (read-only)'}",
        f"**--legacy-permissive-audit:** {'YES' if legacy_permissive_audit else 'no'}",
        "",
        "## Per-milestone retroactive verdict",
        "",
        "| Milestone | Original status | Contract verdict | audit_status | unresolved | severity | findings_path |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in findings:
        lines.append(
            f"| {entry['milestone_id']} | {entry['original_status']} | "
            f"{entry['contract_verdict']} | {entry['audit_status']} | "
            f"{entry['unresolved_count']} | {entry['debt_severity'] or '—'} | "
            f"`{entry['audit_findings_path'] or 'absent'}` |"
        )
    lines.extend(["", "## Layer-2 state-invariant violations (warn-only)"])
    if invariant_violations:
        lines.append("")
        for v in invariant_violations:
            lines.append(f"- {v}")
    else:
        lines.extend(["", "_(none — all completed milestones consistent with Phase 5 Quality Contract)_"])
    lines.extend([
        "",
        "## Notes",
        "",
        "- Phase 5.3 fields populated on STATE.json: `audit_status`, "
        "`unresolved_findings_count`, `audit_debt_severity`, `audit_findings_path`.",
        "- `--rescan-overwrite-status` (off by default) rewrites status `COMPLETE -> DEGRADED` "
        "retroactively. Off mode: status stays `COMPLETE` for stability; quality-debt fields "
        "still populate so consumers see the gap.",
        "- Layer-2 invariants run warn-only here so pre-Phase-5 hollow-recovery shapes "
        "do not brick the migration. Address the violations on the next live run.",
    ])
    return "\n".join(lines) + "\n"


def rescan_quality_debt(
    *,
    cwd: str,
    rescan_overwrite_status: bool = False,
    legacy_permissive_audit: bool = False,
) -> int:
    """Phase 5.5 §M.M10 entry point.

    Returns process exit code: 0 on success, 1 on STATE.json absent.
    """

    run_dir = Path(cwd)
    state_path = run_dir / ".agent-team" / "STATE.json"
    if not state_path.is_file():
        print(f"[rescan-quality-debt] STATE.json not found at {state_path}", file=sys.stderr)
        return 1

    try:
        state_dict = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[rescan-quality-debt] STATE.json parse failure: {exc}", file=sys.stderr)
        return 1

    progress = state_dict.get("milestone_progress", {}) or {}
    completed_ids = [
        ms_id for ms_id, entry in progress.items()
        if isinstance(entry, dict)
        and entry.get("status") in ("COMPLETE", "DEGRADED")
    ]

    findings_for_report: list[dict] = []
    for ms_id in completed_ids:
        ar_path = _resolve_audit_report_path(run_dir, ms_id)
        if ar_path is None:
            findings_for_report.append({
                "milestone_id": ms_id,
                "original_status": progress[ms_id].get("status", ""),
                "contract_verdict": "—",
                "audit_status": "no_audit_report",
                "unresolved_count": 0,
                "debt_severity": "",
                "audit_findings_path": "",
            })
            continue

        verdict, audit_status, unresolved, severity = _evaluate_milestone(
            ar_path, state_dict, legacy_permissive_audit,
        )
        # Update Phase 5.3 fields on the in-memory state dict.
        entry = dict(progress[ms_id])
        original_status = entry.get("status", "")
        entry["audit_status"] = audit_status
        if unresolved > 0:
            entry["unresolved_findings_count"] = unresolved
        entry["audit_debt_severity"] = severity
        entry["audit_findings_path"] = str(ar_path.resolve())
        if rescan_overwrite_status and original_status == "COMPLETE" and verdict == "DEGRADED":
            entry["status"] = "DEGRADED"
        progress[ms_id] = entry

        findings_for_report.append({
            "milestone_id": ms_id,
            "original_status": original_status,
            "contract_verdict": verdict,
            "audit_status": audit_status,
            "unresolved_count": unresolved,
            "debt_severity": severity,
            "audit_findings_path": str(ar_path.resolve()),
        })

    # Persist updated STATE.json.
    state_dict["milestone_progress"] = progress
    state_path.write_text(
        json.dumps(state_dict, indent=2, sort_keys=False, ensure_ascii=False),
        encoding="utf-8",
    )

    # Layer-2 warn-only: collect violations across all milestones.
    invariant_violations: list[str] = []
    try:
        from .state_invariants import validate_terminal_quality_invariants
        run_state = _build_minimal_run_state(state_dict)
        for ms_id in completed_ids:
            v = validate_terminal_quality_invariants(
                run_state, cwd=run_dir, milestone_id=ms_id, warn_only=True,
            )
            invariant_violations.extend(v)
    except Exception as exc:  # pragma: no cover — defensive
        invariant_violations.append(f"validator-internal-error: {exc}")

    report_path = run_dir / ".agent-team" / "QUALITY_DEBT_RESCAN.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _format_report(
            run_dir,
            findings_for_report,
            rescan_overwrite_status,
            legacy_permissive_audit,
            invariant_violations,
        ),
        encoding="utf-8",
    )
    print(f"[rescan-quality-debt] {len(findings_for_report)} milestone(s) rescanned. "
          f"Report: {report_path}")
    return 0


__all__ = ("rescan_quality_debt",)
