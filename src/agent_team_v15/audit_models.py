"""Data models for the audit-team review system.

Provides structured finding, scoring, and reporting data classes used
by the 6 specialized auditors, the scorer agent, and the fix dispatch
algorithm.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Severity and verdict constants
# ---------------------------------------------------------------------------

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
VERDICTS = ("PASS", "FAIL", "PARTIAL")
AUDITOR_NAMES = ("requirements", "technical", "interface", "test", "mcp_library", "prd_fidelity")
AUDITOR_PREFIXES = {
    "requirements": "RA",
    "technical": "TA",
    "interface": "IA",
    "test": "XA",
    "mcp_library": "MA",
    "prd_fidelity": "PA",
}

# Severity weights for fix dispatch priority ordering
_SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}

# Maximum findings to keep after dedup — prevents overwhelming the fix dispatcher
_MAX_FINDINGS = 50


# ---------------------------------------------------------------------------
# AuditFinding
# ---------------------------------------------------------------------------

@dataclass
class AuditFinding:
    """A single audit finding from any auditor."""

    finding_id: str
    auditor: str
    requirement_id: str
    verdict: str
    severity: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    remediation: str = ""
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "auditor": self.auditor,
            "requirement_id": self.requirement_id,
            "verdict": self.verdict,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AuditFinding:
        return cls(
            finding_id=data["finding_id"],
            auditor=data["auditor"],
            requirement_id=data["requirement_id"],
            verdict=data["verdict"],
            severity=data["severity"],
            summary=data["summary"],
            evidence=data.get("evidence", []),
            remediation=data.get("remediation", ""),
            confidence=data.get("confidence", 1.0),
        )

    @property
    def primary_file(self) -> str:
        """Extract the primary file path from the first evidence entry."""
        if not self.evidence:
            return ""
        filepath, _, _ = parse_evidence_entry(self.evidence[0])
        return filepath


# ---------------------------------------------------------------------------
# AuditScore
# ---------------------------------------------------------------------------

@dataclass
class AuditScore:
    """Computed score for an audit run."""

    total_items: int
    passed: int
    failed: int
    partial: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    info_count: int
    score: float
    health: str

    @staticmethod
    def compute(
        findings: list[AuditFinding],
        healthy_threshold: float = 90.0,
        degraded_threshold: float = 70.0,
    ) -> AuditScore:
        """Compute score from a list of findings."""
        req_verdicts: dict[str, str] = {}
        severity_counts = {s: 0 for s in SEVERITIES}

        for f in findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
            if f.requirement_id == "GENERAL":
                continue
            # Register requirement if not yet seen (default to its verdict)
            if f.requirement_id not in req_verdicts:
                req_verdicts[f.requirement_id] = f.verdict
            elif f.verdict == "FAIL":
                req_verdicts[f.requirement_id] = "FAIL"
            elif f.verdict == "PARTIAL" and req_verdicts[f.requirement_id] != "FAIL":
                req_verdicts[f.requirement_id] = "PARTIAL"

        total = len(req_verdicts)
        passed = sum(1 for v in req_verdicts.values() if v == "PASS")
        failed = sum(1 for v in req_verdicts.values() if v == "FAIL")
        partial = sum(1 for v in req_verdicts.values() if v == "PARTIAL")

        score = (passed * 100 + partial * 50) / max(total, 1)

        critical = severity_counts.get("CRITICAL", 0)
        if score >= healthy_threshold and critical == 0:
            health = "healthy"
        elif score >= degraded_threshold and critical == 0:
            health = "degraded"
        else:
            health = "failed"

        return AuditScore(
            total_items=total,
            passed=passed,
            failed=failed,
            partial=partial,
            critical_count=critical,
            high_count=severity_counts.get("HIGH", 0),
            medium_count=severity_counts.get("MEDIUM", 0),
            low_count=severity_counts.get("LOW", 0),
            info_count=severity_counts.get("INFO", 0),
            score=round(score, 1),
            health=health,
        )

    def to_dict(self) -> dict:
        return {
            "total_items": self.total_items,
            "passed": self.passed,
            "failed": self.failed,
            "partial": self.partial,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "info_count": self.info_count,
            "score": self.score,
            "health": self.health,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AuditScore:
        return cls(
            total_items=data["total_items"],
            passed=data["passed"],
            failed=data["failed"],
            partial=data["partial"],
            critical_count=data["critical_count"],
            high_count=data["high_count"],
            medium_count=data["medium_count"],
            low_count=data["low_count"],
            info_count=data["info_count"],
            score=data["score"],
            health=data["health"],
        )


# ---------------------------------------------------------------------------
# AuditReport
# ---------------------------------------------------------------------------

@dataclass
class AuditReport:
    """Complete audit report produced by the scorer agent."""

    audit_id: str
    timestamp: str
    cycle: int
    auditors_deployed: list[str]
    findings: list[AuditFinding]
    score: AuditScore
    by_severity: dict[str, list[int]] = field(default_factory=dict)
    by_file: dict[str, list[int]] = field(default_factory=dict)
    by_requirement: dict[str, list[int]] = field(default_factory=dict)
    fix_candidates: list[int] = field(default_factory=list)

    def to_json(self) -> str:
        """Serialize to JSON for persistence."""
        return json.dumps({
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "cycle": self.cycle,
            "auditors_deployed": self.auditors_deployed,
            "findings": [f.to_dict() for f in self.findings],
            "score": self.score.to_dict(),
            "by_severity": self.by_severity,
            "by_file": self.by_file,
            "by_requirement": self.by_requirement,
            "fix_candidates": self.fix_candidates,
        }, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> AuditReport:
        """Deserialize from JSON."""
        data = json.loads(json_str)
        findings = [AuditFinding.from_dict(f) for f in data["findings"]]
        return cls(
            audit_id=data["audit_id"],
            timestamp=data["timestamp"],
            cycle=data.get("cycle", 1),
            auditors_deployed=data["auditors_deployed"],
            findings=findings,
            score=AuditScore.from_dict(data["score"]),
            by_severity=data.get("by_severity", {}),
            by_file=data.get("by_file", {}),
            by_requirement=data.get("by_requirement", {}),
            fix_candidates=data.get("fix_candidates", []),
        )


# ---------------------------------------------------------------------------
# FixTask
# ---------------------------------------------------------------------------

@dataclass
class FixTask:
    """A grouped fix task for debugger dispatch."""

    target_files: list[str]
    findings: list[AuditFinding]
    priority: str  # highest severity among findings

    @property
    def priority_order(self) -> int:
        """Numeric priority for sorting (lower = higher priority)."""
        return _SEVERITY_ORDER.get(self.priority, 99)

    def to_dict(self) -> dict:
        return {
            "target_files": self.target_files,
            "findings": [f.to_dict() for f in self.findings],
            "priority": self.priority,
        }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def parse_evidence_entry(entry: str) -> tuple[str, int | None, str]:
    """Parse a single evidence string into (file_path, line_number, description).

    Handles formats:
      - "src/file.ts:42 -- description"          (standard)
      - "C:\\Users\\path\\file.ts:42 -- desc"     (Windows absolute)
      - "src/file.ts -- no line number"           (missing line)
      - multiline entries (uses first line only)
    """
    # Use first line only for multiline evidence
    line = entry.split("\n")[0].strip()
    if not line:
        return ("", None, "")

    # Split on " -- " to separate file:line from description
    desc = ""
    if " -- " in line:
        file_part, desc = line.split(" -- ", 1)
    else:
        file_part = line

    file_part = file_part.strip()

    # Detect Windows absolute path (e.g., C:\Users\...) — drive letter at position 0-1
    colon_idx = file_part.find(":")
    if colon_idx == 1 and len(file_part) > 2 and file_part[2] in ("/", "\\"):
        # Windows path — look for next colon (line number separator)
        next_colon = file_part.find(":", 2)
        if next_colon != -1:
            filepath = file_part[:next_colon]
            line_str = file_part[next_colon + 1:].strip()
            try:
                return (filepath, int(line_str), desc)
            except ValueError:
                return (filepath, None, desc)
        return (file_part, None, desc)

    # Standard path — first colon is the line number separator
    if colon_idx != -1:
        filepath = file_part[:colon_idx]
        line_str = file_part[colon_idx + 1:].strip()
        try:
            return (filepath, int(line_str), desc)
        except ValueError:
            return (filepath, None, desc)

    # No colon at all — just a filepath (or partial)
    return (file_part.split(" ")[0], None, desc)


def deduplicate_findings(findings: list[AuditFinding]) -> list[AuditFinding]:
    """Deduplicate findings per the scorer rules.

    1. Same requirement_id + same verdict: keep higher confidence
    2. Same file:line across auditors: merge evidence
    3. Never deduplicate across different requirement_ids
    """
    # Group by requirement_id
    by_req: dict[str, list[AuditFinding]] = {}
    for f in findings:
        by_req.setdefault(f.requirement_id, []).append(f)

    result: list[AuditFinding] = []
    for req_id, group in by_req.items():
        if req_id == "GENERAL":
            # Keep all GENERAL findings (they may be from different auditors about different things)
            result.extend(group)
            continue

        # Within each requirement, deduplicate by verdict
        by_verdict: dict[str, list[AuditFinding]] = {}
        for f in group:
            by_verdict.setdefault(f.verdict, []).append(f)

        for verdict, vgroup in by_verdict.items():
            if len(vgroup) == 1:
                result.append(vgroup[0])
            else:
                # Keep the one with highest confidence, merge evidence
                best = max(vgroup, key=lambda x: x.confidence)
                merged_evidence = list(best.evidence)
                for other in vgroup:
                    if other is not best:
                        for ev in other.evidence:
                            if ev not in merged_evidence:
                                merged_evidence.append(ev)
                best_copy = AuditFinding(
                    finding_id=best.finding_id,
                    auditor=best.auditor,
                    requirement_id=best.requirement_id,
                    verdict=best.verdict,
                    severity=best.severity,
                    summary=best.summary,
                    evidence=merged_evidence,
                    remediation=best.remediation,
                    confidence=best.confidence,
                )
                result.append(best_copy)

    # --- Second pass: file:line-level dedup across auditors ---
    # If multiple findings reference the same file:line with the same severity,
    # same verdict, AND the same requirement_id, merge them.
    # Never merge across requirement_ids or different verdicts.
    file_line_groups: dict[tuple[str, int | None, str, str, str], list[int]] = {}
    for idx, f in enumerate(result):
        # GENERAL findings are never deduplicated (may be from different auditors about different things)
        if f.requirement_id == "GENERAL":
            continue
        filepath, line_no, _ = parse_evidence_entry(f.evidence[0]) if f.evidence else ("", None, "")
        if filepath and line_no is not None:
            key = (filepath, line_no, f.severity, f.requirement_id, f.verdict)
            file_line_groups.setdefault(key, []).append(idx)

    indices_to_remove: set[int] = set()
    for key, indices in file_line_groups.items():
        if len(indices) < 2:
            continue
        # Keep the one with highest confidence, merge evidence
        best_idx = max(indices, key=lambda i: result[i].confidence)
        merged_evidence = list(result[best_idx].evidence)
        for other_idx in indices:
            if other_idx != best_idx:
                indices_to_remove.add(other_idx)
                for ev in result[other_idx].evidence:
                    if ev not in merged_evidence:
                        merged_evidence.append(ev)
        result[best_idx] = AuditFinding(
            finding_id=result[best_idx].finding_id,
            auditor=result[best_idx].auditor,
            requirement_id=result[best_idx].requirement_id,
            verdict=result[best_idx].verdict,
            severity=result[best_idx].severity,
            summary=result[best_idx].summary,
            evidence=merged_evidence,
            remediation=result[best_idx].remediation,
            confidence=result[best_idx].confidence,
        )

    if indices_to_remove:
        result = [f for i, f in enumerate(result) if i not in indices_to_remove]

    return result


def build_report(
    audit_id: str,
    cycle: int,
    auditors_deployed: list[str],
    findings: list[AuditFinding],
    healthy_threshold: float = 90.0,
    degraded_threshold: float = 70.0,
) -> AuditReport:
    """Build a complete AuditReport from findings.

    Deduplicates findings, computes score, and builds grouped indices.
    """
    deduped = deduplicate_findings(findings)
    # Cap findings to prevent overwhelming fix dispatch
    if len(deduped) > _MAX_FINDINGS:
        import logging
        logging.getLogger(__name__).warning(
            "Findings capped: %d -> %d (sorted by severity)",
            len(deduped), _MAX_FINDINGS,
        )
        deduped.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 99))
        deduped = deduped[:_MAX_FINDINGS]
    score = AuditScore.compute(deduped, healthy_threshold, degraded_threshold)

    by_severity: dict[str, list[int]] = {}
    by_file: dict[str, list[int]] = {}
    by_requirement: dict[str, list[int]] = {}
    fix_candidates: list[int] = []

    fix_severities = {"CRITICAL", "HIGH", "MEDIUM"}

    for i, f in enumerate(deduped):
        by_severity.setdefault(f.severity, []).append(i)
        pf = f.primary_file
        if pf:
            by_file.setdefault(pf, []).append(i)
        by_requirement.setdefault(f.requirement_id, []).append(i)
        if f.severity in fix_severities and f.verdict in ("FAIL", "PARTIAL"):
            fix_candidates.append(i)

    return AuditReport(
        audit_id=audit_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        cycle=cycle,
        auditors_deployed=auditors_deployed,
        findings=deduped,
        score=score,
        by_severity=by_severity,
        by_file=by_file,
        by_requirement=by_requirement,
        fix_candidates=fix_candidates,
    )


def group_findings_into_fix_tasks(
    report: AuditReport,
    max_findings_per_task: int = 5,
) -> list[FixTask]:
    """Group fix candidates into FixTasks by primary file.

    Each FixTask targets a single file group. If a file has more than
    *max_findings_per_task* findings, it is split into multiple tasks
    ordered by severity.
    """
    if not report.fix_candidates:
        return []

    # Group candidate findings by primary file
    file_groups: dict[str, list[AuditFinding]] = {}
    for idx in report.fix_candidates:
        f = report.findings[idx]
        pf = f.primary_file or "__unknown__"
        file_groups.setdefault(pf, []).append(f)

    tasks: list[FixTask] = []
    for filepath, group in file_groups.items():
        # Sort by severity (CRITICAL first)
        group.sort(key=lambda x: _SEVERITY_ORDER.get(x.severity, 99))

        # Split into chunks of max_findings_per_task
        for chunk_start in range(0, len(group), max_findings_per_task):
            chunk = group[chunk_start:chunk_start + max_findings_per_task]
            target_files = [filepath]
            # Add related files from evidence
            for f in chunk:
                for ev in f.evidence:
                    ev_file, _, _ = parse_evidence_entry(ev)
                    if ev_file and ev_file not in target_files:
                        target_files.append(ev_file)
            priority = chunk[0].severity  # highest severity in chunk
            tasks.append(FixTask(
                target_files=target_files,
                findings=chunk,
                priority=priority,
            ))

    # Sort tasks by priority
    tasks.sort(key=lambda t: t.priority_order)
    return tasks


def compute_reaudit_scope(
    modified_files: list[str],
    original_findings: list[AuditFinding],
) -> list[str]:
    """Determine which auditors need to re-run based on modified files.

    Maps modified files back to the original findings that targeted them,
    then returns the set of auditor names that need to re-run.
    The test auditor always re-runs.
    """
    affected_auditors: set[str] = set()

    for f in original_findings:
        if f.verdict == "PASS":
            continue
        pf = f.primary_file
        if pf and pf in modified_files:
            affected_auditors.add(f.auditor)

    # Test auditor always re-runs after fixes
    affected_auditors.add("test")

    return sorted(affected_auditors)


def detect_fix_conflicts(tasks: list[FixTask]) -> list[tuple[int, int]]:
    """Detect conflicting fix tasks that share target files.

    Returns pairs of task indices that must be serialized (not run in parallel).
    Uses a reverse index for O(n*m) performance instead of O(n^2).
    """
    # Build reverse index: file -> set of task indices
    file_to_tasks: dict[str, list[int]] = {}
    for i, task in enumerate(tasks):
        for f in task.target_files:
            file_to_tasks.setdefault(f, []).append(i)

    # Conflicts = any file shared by 2+ tasks
    conflict_set: set[tuple[int, int]] = set()
    for indices in file_to_tasks.values():
        if len(indices) < 2:
            continue
        for a_idx in range(len(indices)):
            for b_idx in range(a_idx + 1, len(indices)):
                pair = (indices[a_idx], indices[b_idx])
                conflict_set.add(pair)

    return sorted(conflict_set)
