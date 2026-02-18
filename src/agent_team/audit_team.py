"""Audit-team orchestration logic.

Replaces the single code-reviewer with a 5-agent parallel audit system:
  1. Requirements Auditor  (REQ-xxx, DESIGN-xxx, SEED-xxx, ENUM-xxx)
  2. Technical Auditor     (TECH-xxx, SDL-xxx, anti-patterns)
  3. Interface Auditor     (WIRE-xxx, SVC-xxx, API-xxx, orphans)
  4. Test Auditor          (TEST-xxx, test quality, coverage)
  5. MCP/Library Auditor   (library API correctness via Context7)

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
    "thorough": list(AUDITOR_NAMES),  # all 5
    "exhaustive": list(AUDITOR_NAMES),  # all 5
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
# Auditor agent definition builders
# ---------------------------------------------------------------------------

def build_auditor_agent_definitions(
    auditors: list[str],
    task_text: str | None = None,
    requirements_path: str | None = None,
) -> dict[str, dict]:
    """Build agent definitions for the specified auditors.

    Returns a dict of agent_name -> agent_definition suitable for
    injection into build_agent_definitions() or direct use.
    """
    agents: dict[str, dict] = {}

    for auditor_name in auditors:
        if auditor_name not in AUDIT_PROMPTS:
            continue
        prompt = get_auditor_prompt(auditor_name, requirements_path=requirements_path)
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
    "compute_reaudit_scope",
    "deduplicate_findings",
    "detect_fix_conflicts",
    "get_auditor_prompt",
    "get_auditors_for_depth",
    "group_findings_into_fix_tasks",
    "should_skip_scan",
    "should_terminate_reaudit",
]
