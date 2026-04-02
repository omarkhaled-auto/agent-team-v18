"""Audit-team orchestration logic.

Replaces the single code-reviewer with a 6-agent parallel audit system:
  1. Requirements Auditor  (REQ-xxx, DESIGN-xxx, SEED-xxx, ENUM-xxx)
  2. Technical Auditor     (TECH-xxx, SDL-xxx, anti-patterns)
  3. Interface Auditor     (WIRE-xxx, SVC-xxx, API-xxx, orphans)
  4. Test Auditor          (TEST-xxx, test quality, coverage)
  5. MCP/Library Auditor   (library API correctness via Context7)
  6. PRD Fidelity Auditor  (DROPPED, DISTORTED, ORPHANED requirements)

Plus a Scorer agent that deduplicates, scores, and writes the report.

This module provides the pure logic functions used by the orchestrator
(cli.py) to dispatch auditors, compute scores, and manage the fix/re-audit
loop. It does NOT import cli.py or create Claude sessions directly.
"""

from __future__ import annotations

from .audit_models import (
    AUDITOR_NAMES,
    AUDITOR_PREFIXES,
    AuditFinding,
    AuditReport,
    AuditScore,
    FixTask,
    build_report,
    compute_reaudit_scope,
    deduplicate_findings,
    detect_fix_conflicts,
    group_findings_into_fix_tasks,
)
from .audit_prompts import AUDIT_PROMPTS, get_auditor_prompt


# ---------------------------------------------------------------------------
# Auditor selection by depth
# ---------------------------------------------------------------------------

# Maps depth level to the set of auditors that should run
DEPTH_AUDITOR_MAP: dict[str, list[str]] = {
    "quick": [],  # audit-team disabled at quick depth
    "standard": ["requirements", "technical", "interface"],
    "thorough": list(AUDITOR_NAMES),  # all 6 (prd_fidelity skipped if no PRD)
    "exhaustive": list(AUDITOR_NAMES),  # all 6 (prd_fidelity skipped if no PRD)
    "enterprise": list(AUDITOR_NAMES),  # all 6 — enterprise is superset of exhaustive
}


def get_auditors_for_depth(depth: str) -> list[str]:
    """Return the list of auditor names to deploy for the given depth."""
    return list(DEPTH_AUDITOR_MAP.get(depth, DEPTH_AUDITOR_MAP["standard"]))


# ---------------------------------------------------------------------------
# Overlapping scan detection
# ---------------------------------------------------------------------------

# Post-orchestration scans that are covered by specific auditors
_SCAN_AUDITOR_OVERLAP: dict[str, str] = {
    "mock_data_scan": "interface",       # SVC-xxx mock data check
    # NOTE: ui_compliance_scan is intentionally NOT mapped here.
    # The requirements auditor checks DESIGN-xxx requirements but does NOT
    # replicate the regex-based SLOP-001..015 pattern scanning that
    # ui_compliance_scan performs. Skipping it would lose anti-pattern coverage.
    "api_contract_scan": "interface",    # API-001 through API-004
    "silent_data_loss_scan": "technical",  # SDL-001/002/003
    "endpoint_xref_scan": "interface",   # XREF-001/002
}


def should_skip_scan(scan_name: str, auditors_deployed: list[str]) -> bool:
    """Return True if the given post-orchestration scan can be skipped.

    A scan is skippable when the audit-team deployed an auditor that
    covers the same verification scope.
    """
    covering_auditor = _SCAN_AUDITOR_OVERLAP.get(scan_name)
    if not covering_auditor:
        return False
    return covering_auditor in auditors_deployed


# ---------------------------------------------------------------------------
# Re-audit termination logic
# ---------------------------------------------------------------------------

def should_terminate_reaudit(
    current_score: AuditScore,
    previous_score: AuditScore | None,
    cycle: int,
    max_cycles: int = 3,
    healthy_threshold: float = 90.0,
) -> tuple[bool, str]:
    """Determine whether to stop the re-audit loop.

    Returns (should_stop, reason) tuple.
    """
    # Condition 1: Score meets healthy threshold with no criticals
    if current_score.score >= healthy_threshold and current_score.critical_count == 0:
        return True, "healthy"

    # Condition 2: Max cycles reached
    if cycle >= max_cycles:
        return True, "max_cycles"

    # Condition 3: Score regressed by >10 points (something broke)
    # Must be checked BEFORE no_improvement because no_improvement also catches drops.
    if previous_score is not None:
        if current_score.score < previous_score.score - 10:
            return True, "regression"

    # Condition 4: No improvement from previous cycle
    if previous_score is not None:
        if current_score.score <= previous_score.score and current_score.critical_count >= previous_score.critical_count:
            return True, "no_improvement"

    # Condition 5: New CRITICAL findings appeared (regression indicator)
    if previous_score is not None:
        if current_score.critical_count > previous_score.critical_count:
            import logging
            logging.getLogger(__name__).warning(
                "New CRITICAL findings appeared: %d -> %d",
                previous_score.critical_count,
                current_score.critical_count,
            )

    return False, ""


# ---------------------------------------------------------------------------
# Convergence tracking
# ---------------------------------------------------------------------------

def detect_convergence_plateau(
    metrics_history: list,
    window: int = 3,
) -> tuple[bool, str]:
    """Detect if the audit-fix loop has plateaued.

    A plateau is detected when the last *window* cycles show no
    meaningful score improvement (< 2 points total) and no net
    reduction in findings.

    Args:
        metrics_history: List of AuditCycleMetrics (or dicts with
            'score' and 'total_findings' keys).
        window: Number of recent cycles to consider.

    Returns:
        (is_plateau, reason) tuple.
    """
    if len(metrics_history) < window:
        return False, ""

    recent = metrics_history[-window:]

    # Check score movement
    scores = [m.score if hasattr(m, "score") else m["score"] for m in recent]
    score_delta = scores[-1] - scores[0]

    # Check finding count movement
    counts = [
        m.total_findings if hasattr(m, "total_findings") else m["total_findings"]
        for m in recent
    ]
    findings_delta = counts[-1] - counts[0]

    # Plateau: score improved < 2 points AND findings not decreasing
    if score_delta < 2.0 and findings_delta >= 0:
        return True, (
            f"Plateau detected over {window} cycles: "
            f"score {scores[0]:.1f} -> {scores[-1]:.1f} (+{score_delta:.1f}), "
            f"findings {counts[0]} -> {counts[-1]}"
        )

    # Oscillation: score going up and down with no net trend
    if len(scores) >= 3:
        ups = sum(1 for i in range(1, len(scores)) if scores[i] > scores[i - 1])
        downs = sum(1 for i in range(1, len(scores)) if scores[i] < scores[i - 1])
        if ups > 0 and downs > 0 and abs(score_delta) < 3.0:
            return True, (
                f"Oscillation detected over {window} cycles: "
                f"score {scores[0]:.1f} -> {scores[-1]:.1f} "
                f"({ups} ups, {downs} downs, net {score_delta:+.1f})"
            )

    return False, ""


def detect_regressions(
    current_findings: list,
    previous_findings: list,
) -> list[str]:
    """Detect findings that were fixed but reappeared.

    Compares current and previous finding lists by finding_id (for
    AuditFinding objects) or 'id' (for Finding dicts/objects).

    Returns list of regressed finding IDs.
    """
    def _get_id(f):
        if hasattr(f, "finding_id"):
            return f.finding_id
        if hasattr(f, "id"):
            return f.id
        if isinstance(f, dict):
            return f.get("finding_id", f.get("id", ""))
        return ""

    current_ids = {_get_id(f) for f in current_findings}
    previous_ids = {_get_id(f) for f in previous_findings}

    # Regressed = was not in current (fixed) in prev cycle, but now reappeared
    # Actually, regression means: something that PASSED before now FAILS.
    # We approximate: IDs in current that also existed in previous (same bug persisting).
    # True regressions are new failures on previously-passing items.
    # For finding-level regression: IDs that appear in both (not fixed).
    persistent = sorted(current_ids & previous_ids)
    return persistent


def compute_escalation_recommendation(
    metrics_history: list,
    max_cycles: int = 5,
) -> str | None:
    """Recommend an escalation action based on convergence analysis.

    Returns a recommendation string, or None if no escalation needed.
    """
    if not metrics_history:
        return None

    latest = metrics_history[-1]
    latest_score = latest.score if hasattr(latest, "score") else latest["score"]

    # Check for plateau
    is_plateau, reason = detect_convergence_plateau(metrics_history)

    if is_plateau and latest_score < 50.0:
        return (
            f"ESCALATE: {reason}. Score is critically low ({latest_score:.1f}%). "
            "Recommend manual review of deterministic findings and architectural changes."
        )

    if is_plateau and latest_score < 80.0:
        return (
            f"ESCALATE: {reason}. Score stalled at {latest_score:.1f}%. "
            "Consider focusing on deterministic findings only for next fix cycle."
        )

    if is_plateau:
        return (
            f"INFO: {reason}. Score is {latest_score:.1f}% — "
            "close to healthy, but fix loop may not improve further."
        )

    # Check for repeated regressions
    if len(metrics_history) >= 2:
        latest_m = metrics_history[-1]
        regressed = (
            latest_m.regressed_finding_ids
            if hasattr(latest_m, "regressed_finding_ids")
            else latest_m.get("regressed_finding_ids", [])
        )
        if len(regressed) >= 3:
            return (
                f"ESCALATE: {len(regressed)} regressions detected in cycle "
                f"{latest_m.cycle if hasattr(latest_m, 'cycle') else latest_m.get('cycle')}. "
                "Fix loop is introducing bugs. Consider narrower fix scope."
            )

    return None


# ---------------------------------------------------------------------------
# Auditor agent definition builders
# ---------------------------------------------------------------------------

def build_auditor_agent_definitions(
    auditors: list[str],
    task_text: str | None = None,
    requirements_path: str | None = None,
    prd_path: str | None = None,
) -> dict[str, dict]:
    """Build agent definitions for the specified auditors.

    Returns a dict of agent_name -> agent_definition suitable for
    injection into build_agent_definitions() or direct use.

    If *prd_path* is ``None``, the ``prd_fidelity`` auditor is silently
    skipped (it requires a PRD to cross-reference).
    """
    agents: dict[str, dict] = {}

    for auditor_name in auditors:
        if auditor_name not in AUDIT_PROMPTS:
            continue
        # Skip prd_fidelity when no PRD is available
        if auditor_name == "prd_fidelity" and not prd_path:
            continue
        prompt = get_auditor_prompt(
            auditor_name,
            requirements_path=requirements_path,
            prd_path=prd_path,
        )
        if task_text and auditor_name == "requirements":
            prompt = f"[ORIGINAL USER REQUEST]\n{task_text}\n\n" + prompt

        # Agent name uses hyphens (SDK convention)
        agent_key = f"audit-{auditor_name.replace('_', '-')}"
        agents[agent_key] = {
            "description": f"Audit-team {auditor_name} auditor",
            "prompt": prompt,
            "tools": ["Read", "Glob", "Grep", "Bash"] if auditor_name == "test" else ["Read", "Glob", "Grep"],
            "model": "opus",
        }

    # Scorer agent
    scorer_prompt = get_auditor_prompt("scorer", requirements_path=requirements_path)
    agents["audit-scorer"] = {
        "description": "Audit-team scorer — deduplicates, scores, writes report",
        "prompt": scorer_prompt,
        "tools": ["Read", "Write", "Edit", "Glob", "Grep"],
        "model": "opus",
    }

    return agents


# ---------------------------------------------------------------------------
# Public API summary (used by cli.py integration)
# ---------------------------------------------------------------------------

__all__ = [
    "AUDITOR_NAMES",
    "AUDITOR_PREFIXES",
    "AUDIT_PROMPTS",
    "AuditFinding",
    "AuditReport",
    "AuditScore",
    "FixTask",
    "build_auditor_agent_definitions",
    "build_report",
    "compute_convergence_plateau",
    "compute_escalation_recommendation",
    "compute_reaudit_scope",
    "deduplicate_findings",
    "detect_convergence_plateau",
    "detect_fix_conflicts",
    "detect_regressions",
    "get_auditor_prompt",
    "get_auditors_for_depth",
    "group_findings_into_fix_tasks",
    "should_skip_scan",
    "should_terminate_reaudit",
]
