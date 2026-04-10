"""Enterprise v2: Department model for distributed phase execution.

Departments replace single phase leads with TeamCreate groups where a
department head coordinates domain managers who dispatch workers. This
distributes context across multiple agent windows and enables true
parallel domain execution with lateral SendMessage communication.

Requires: enterprise_mode.enabled AND enterprise_mode.department_model AND departments.enabled
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Department definitions
# ---------------------------------------------------------------------------

CODING_DEPARTMENT_MEMBERS = [
    "coding-dept-head",
    "backend-manager",
    "frontend-manager",
    "infra-manager",
    "integration-manager",
]

REVIEW_DEPARTMENT_MEMBERS = [
    "review-dept-head",
    "backend-review-manager",
    "frontend-review-manager",
    "cross-cutting-reviewer",
]
# Note: "domain-reviewer" is intentionally NOT in this list — it is a
# spawn-only subagent template that review managers dispatch via Agent(),
# not a TeamCreate member.

# Map tech_stack keywords to manager agent names
TECH_STACK_MANAGER_MAP: dict[str, str] = {
    "nestjs": "backend-manager",
    "prisma": "backend-manager",
    "express": "backend-manager",
    "fastify": "backend-manager",
    "nextjs": "frontend-manager",
    "react": "frontend-manager",
    "vue": "frontend-manager",
    "angular": "frontend-manager",
    "docker": "infra-manager",
    "ci/cd": "infra-manager",
    "cicd": "infra-manager",
    "github-actions": "infra-manager",
    "jenkins": "infra-manager",
    "terraform": "infra-manager",
    "k8s": "infra-manager",
    "kubernetes": "infra-manager",
}


def resolve_manager_for_domain(domain: dict[str, Any]) -> str:
    """Determine which manager should handle a domain based on tech_stack."""
    tech = domain.get("tech_stack", "").lower()
    for keyword, manager in TECH_STACK_MANAGER_MAP.items():
        if keyword in tech:
            return manager
    # Fallback: backend-manager handles unknown stacks
    return "backend-manager"


def build_manager_assignments(
    ownership_map: dict[str, Any],
) -> dict[str, list[str]]:
    """Group domains by their assigned manager.

    Returns: {manager_name: [domain_name, ...]}
    """
    assignments: dict[str, list[str]] = {}
    for domain_name, domain_data in ownership_map.get("domains", {}).items():
        manager = resolve_manager_for_domain(domain_data)
        assignments.setdefault(manager, []).append(domain_name)
    return assignments


def should_manager_work_directly(domain_count: int) -> bool:
    """Smart sizing: manager works directly if <=2 domains (no worker spawning)."""
    return domain_count <= 2


def build_domain_assignment_message(
    wave_id: int,
    wave_name: str,
    domains: list[dict[str, Any]],
) -> str:
    """Build a DOMAIN_ASSIGNMENT message for a manager.

    Format matches the intra-department communication protocol.
    """
    return json.dumps({
        "type": "DOMAIN_ASSIGNMENT",
        "wave_id": wave_id,
        "wave_name": wave_name,
        "domains": domains,
    }, indent=2)


def build_domain_complete_message(
    wave_id: int,
    domain: str,
    status: str,
    files_written: list[str],
    issues: list[str],
) -> str:
    """Build a DOMAIN_COMPLETE message from a manager to dept-head."""
    return json.dumps({
        "type": "DOMAIN_COMPLETE",
        "wave_id": wave_id,
        "domain": domain,
        "status": status,
        "files_written": files_written,
        "issues": issues,
    }, indent=2)


def get_department_team_name(prefix: str, department: str) -> str:
    """Generate a TeamCreate team name for a department.

    Example: build-coding-dept, build-review-dept
    """
    return f"{prefix}-{department}-dept"


def get_wave_domains(
    ownership_map: dict[str, Any],
    wave_id: int,
) -> list[str]:
    """Get domain names for a specific wave from the ownership map."""
    for wave in ownership_map.get("waves", []):
        if wave.get("id") == wave_id:
            return wave.get("domains", [])
    return []


def compute_department_size(
    ownership_map: dict[str, Any],
    department: str,
    config_max_managers: int,
) -> int:
    """Compute how many managers are needed for a department.

    Based on unique tech_stack categories in the ownership map.
    """
    if department == "review":
        # Review always uses: backend-reviewer, frontend-reviewer, cross-cutting
        return min(3, config_max_managers)

    # Coding: count distinct manager types needed
    assignments = build_manager_assignments(ownership_map)
    # Always include integration-manager
    needed = len(assignments) + 1  # +1 for integration-manager
    return min(needed, config_max_managers)


def build_orchestrator_department_prompt(
    team_prefix: str,
    coding_enabled: bool,
    review_enabled: bool,
    skills_dir: Path | None = None,
) -> str:
    """Build the orchestrator prompt injection for department mode.

    This replaces the single-lead enterprise prompt injection when
    department_model is active.  When *skills_dir* is provided,
    accumulated department skills are injected into the prompt.
    """
    lines = [
        "[ENTERPRISE MODE — DEPARTMENT MODEL]",
        "This build uses the department model for distributed phase execution.",
        "Coding and Review phases are handled by DEPARTMENTS (TeamCreate groups),",
        "not single phase leads.",
        "",
    ]
    if coding_enabled:
        team_name = get_department_team_name(team_prefix, "coding")
        lines += [
            f"CODING DEPARTMENT: Team '{team_name}'",
            "  Members: coding-dept-head, backend-manager, frontend-manager, infra-manager, integration-manager",
            "  The coding-dept-head coordinates wave execution. You delegate to it via Task.",
            "  For EACH wave: Task(coding-dept-head, 'ENTERPRISE WAVE {wave_id}. Domains: ...')",
            "",
        ]
        # Inject accumulated coding department skills
        if skills_dir is not None:
            from .skills import load_skills_for_department
            coding_skills = load_skills_for_department(skills_dir, "coding")
            if coding_skills:
                lines += [
                    "  CODING DEPARTMENT SKILLS (learned from previous builds):",
                    *[f"  {sl}" for sl in coding_skills.splitlines()],
                    "",
                ]
    if review_enabled:
        team_name = get_department_team_name(team_prefix, "review")
        lines += [
            f"REVIEW DEPARTMENT: Team '{team_name}'",
            "  Members: review-dept-head, backend-review-manager, frontend-review-manager, cross-cutting-reviewer",
            "  The review-dept-head aggregates convergence. You delegate via Task.",
            "  Task(review-dept-head, 'ENTERPRISE REVIEW. Ownership map: ...')",
            "",
        ]
        # Inject accumulated review department skills
        if skills_dir is not None:
            from .skills import load_skills_for_department
            review_skills = load_skills_for_department(skills_dir, "review")
            if review_skills:
                lines += [
                    "  REVIEW DEPARTMENT SKILLS (learned from previous builds):",
                    *[f"  {sl}" for sl in review_skills.splitlines()],
                    "",
                ]
    lines += [
        "CROSS-DEPARTMENT FIX FLOW:",
        "  When review department returns PARTIAL with failing items:",
        "  1. Extract the fix list with domain ownership",
        "  2. Task(coding-dept-head, 'FIX_REQUIRED. Items: {fix_list}')",
        "  3. Re-run review department after fixes",
        "",
        "Planning, Architecture, Testing, and Audit remain as single phase leads.",
    ]
    return "\n".join(lines)


def load_ownership_map(cwd: Path) -> dict[str, Any] | None:
    """Load OWNERSHIP_MAP.json from the .agent-team directory."""
    path = cwd / ".agent-team" / "OWNERSHIP_MAP.json"
    if not path.exists():
        _logger.warning("OWNERSHIP_MAP.json not found at %s", path)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _logger.error("Failed to load OWNERSHIP_MAP.json: %s", exc)
        return None
