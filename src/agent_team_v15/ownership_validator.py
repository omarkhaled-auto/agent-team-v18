"""Ownership map validation for enterprise-mode builds.

Validates OWNERSHIP_MAP.json for structural correctness: file glob overlaps,
unassigned requirements, empty domains, circular wave dependencies,
scaffolding collisions, and non-existent requirement references.

All checks are stdlib-only and designed to run as part of the
post-orchestration verification pipeline.

Typical usage::

    from pathlib import Path
    from agent_team_v15.ownership_validator import run_ownership_gate

    passed, findings = run_ownership_gate(Path("/path/to/project"))
    for f in findings:
        print(f"[{f.check}] {f.severity}: {f.message} (domain: {f.domain})")
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OwnershipFinding:
    """A single ownership map validation finding."""

    check: str       # "OWN-001" through "OWN-007"
    severity: str    # "critical", "high", "medium"
    message: str
    domain: str      # Which domain is affected
    suggestion: str



# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def _check_file_glob_overlap(
    domains: dict[str, dict],
) -> list[OwnershipFinding]:
    """OWN-001: Detect file glob patterns claimed by multiple domains."""
    findings: list[OwnershipFinding] = []
    glob_to_domains: dict[str, list[str]] = {}

    for domain_name, domain_def in domains.items():
        for pattern in domain_def.get("files", []):
            glob_to_domains.setdefault(pattern, []).append(domain_name)

    for pattern, owners in glob_to_domains.items():
        if len(owners) > 1:
            findings.append(OwnershipFinding(
                check="OWN-001",
                severity="critical",
                message=f"File glob '{pattern}' claimed by multiple domains: {', '.join(owners)}",
                domain=owners[0],
                suggestion=f"Assign '{pattern}' to exactly one domain or split into non-overlapping patterns.",
            ))

    return findings


def _check_unassigned_requirements(
    domains: dict[str, dict],
    requirement_ids: set[str],
) -> list[OwnershipFinding]:
    """OWN-002: Ensure every requirement is assigned to at least one domain."""
    findings: list[OwnershipFinding] = []
    assigned: set[str] = set()

    for domain_def in domains.values():
        for req_id in domain_def.get("requirements", []):
            assigned.add(req_id)

    for req_id in sorted(requirement_ids - assigned):
        findings.append(OwnershipFinding(
            check="OWN-002",
            severity="critical",
            message=f"Requirement {req_id} is not assigned to any domain.",
            domain="(none)",
            suggestion=f"Add {req_id} to the requirements list of the appropriate domain.",
        ))

    return findings


def _check_empty_files(domains: dict[str, dict]) -> list[OwnershipFinding]:
    """OWN-003: Flag domains with no files."""
    findings: list[OwnershipFinding] = []
    for domain_name, domain_def in domains.items():
        if not domain_def.get("files"):
            findings.append(OwnershipFinding(
                check="OWN-003",
                severity="high",
                message=f"Domain '{domain_name}' has no files assigned.",
                domain=domain_name,
                suggestion="Add file glob patterns to this domain or remove it.",
            ))
    return findings


def _check_empty_requirements(domains: dict[str, dict]) -> list[OwnershipFinding]:
    """OWN-004: Flag domains with no requirements."""
    findings: list[OwnershipFinding] = []
    for domain_name, domain_def in domains.items():
        if not domain_def.get("requirements"):
            findings.append(OwnershipFinding(
                check="OWN-004",
                severity="high",
                message=f"Domain '{domain_name}' has no requirements assigned.",
                domain=domain_name,
                suggestion="Add requirements to this domain or remove it.",
            ))
    return findings


def _check_circular_dependencies(
    domains: dict[str, dict],
) -> list[OwnershipFinding]:
    """OWN-005: Detect circular wave dependencies via DFS topological sort."""
    findings: list[OwnershipFinding] = []

    # Build adjacency list
    graph: dict[str, list[str]] = {}
    for domain_name, domain_def in domains.items():
        graph[domain_name] = list(domain_def.get("dependencies", []))

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in graph}

    def _dfs(node: str, path: list[str]) -> list[str] | None:
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in color:
                continue  # dependency on unknown domain — skip
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                return path[cycle_start:] + [neighbor]
            if color[neighbor] == WHITE:
                result = _dfs(neighbor, path)
                if result is not None:
                    return result
        path.pop()
        color[node] = BLACK
        return None

    for node in graph:
        if color[node] == WHITE:
            cycle = _dfs(node, [])
            if cycle is not None:
                cycle_str = " -> ".join(cycle)
                findings.append(OwnershipFinding(
                    check="OWN-005",
                    severity="critical",
                    message=f"Circular wave dependency detected: {cycle_str}",
                    domain=cycle[0],
                    suggestion="Remove or reorder dependencies to eliminate the cycle.",
                ))
                break  # Report first cycle only

    return findings


def _check_scaffolding_collision(
    domains: dict[str, dict],
    shared_scaffolding: list[str],
) -> list[OwnershipFinding]:
    """OWN-006: Flag domain files that overlap with shared scaffolding."""
    findings: list[OwnershipFinding] = []
    scaffolding_set = set(shared_scaffolding)

    for domain_name, domain_def in domains.items():
        for file_pattern in domain_def.get("files", []):
            if file_pattern in scaffolding_set:
                findings.append(OwnershipFinding(
                    check="OWN-006",
                    severity="high",
                    message=f"File '{file_pattern}' in domain '{domain_name}' is also in shared_scaffolding.",
                    domain=domain_name,
                    suggestion=f"Remove '{file_pattern}' from either the domain files or shared_scaffolding.",
                ))

    return findings


def _check_nonexistent_requirements(
    domains: dict[str, dict],
    requirement_ids: set[str],
) -> list[OwnershipFinding]:
    """OWN-007: Flag domain requirements that don't exist in the requirement list."""
    findings: list[OwnershipFinding] = []
    for domain_name, domain_def in domains.items():
        for req_id in domain_def.get("requirements", []):
            if req_id not in requirement_ids:
                findings.append(OwnershipFinding(
                    check="OWN-007",
                    severity="medium",
                    message=f"Domain '{domain_name}' references non-existent requirement {req_id}.",
                    domain=domain_name,
                    suggestion=f"Remove {req_id} from domain requirements or add it to REQUIREMENTS.md.",
                ))
    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_ownership_map(
    ownership_map: dict,
    requirement_ids: set[str] | None = None,
) -> list[OwnershipFinding]:
    """Run all ownership validation checks on a parsed ownership map.

    Args:
        ownership_map: Parsed OWNERSHIP_MAP.json dict.
        requirement_ids: Optional set of known REQ-xxx IDs from REQUIREMENTS.md.

    Returns:
        List of findings (may be empty if map is valid).
    """
    domains: dict[str, dict] = ownership_map.get("domains", {})
    shared_scaffolding: list[str] = ownership_map.get("shared_scaffolding", [])

    findings: list[OwnershipFinding] = []

    # OWN-001: File glob overlap
    findings.extend(_check_file_glob_overlap(domains))

    # OWN-002: Unassigned requirements
    if requirement_ids is not None:
        findings.extend(_check_unassigned_requirements(domains, requirement_ids))

    # OWN-003: Domain has no files
    findings.extend(_check_empty_files(domains))

    # OWN-004: Domain has no requirements
    findings.extend(_check_empty_requirements(domains))

    # OWN-005: Circular wave dependency
    findings.extend(_check_circular_dependencies(domains))

    # OWN-006: Scaffolding in domain files
    findings.extend(_check_scaffolding_collision(domains, shared_scaffolding))

    # OWN-007: Non-existent requirement reference
    if requirement_ids is not None:
        findings.extend(_check_nonexistent_requirements(domains, requirement_ids))

    return findings


def run_ownership_gate(
    project_path: Path,
) -> tuple[bool, list[OwnershipFinding]]:
    """Run ownership validation gate on a project directory.

    Loads ``.agent-team/OWNERSHIP_MAP.json`` and validates it.

    Args:
        project_path: Root directory of the project.

    Returns:
        Tuple of (passed, findings). ``passed`` is True if no critical
        findings exist. If no OWNERSHIP_MAP.json is found, returns
        ``(True, [])`` — the project is not in enterprise mode.
    """
    ownership_file = project_path / ".agent-team" / "OWNERSHIP_MAP.json"
    if not ownership_file.exists():
        return (True, [])

    try:
        ownership_map = json.loads(ownership_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        _logger.warning("Failed to parse OWNERSHIP_MAP.json: %s", exc)
        return (False, [OwnershipFinding(
            check="OWN-000",
            severity="critical",
            message=f"Failed to parse OWNERSHIP_MAP.json: {exc}",
            domain="(parse-error)",
            suggestion="Fix the JSON syntax in OWNERSHIP_MAP.json.",
        )])

    # Extract requirement IDs from REQUIREMENTS.md if it exists
    requirement_ids: set[str] | None = None
    req_file = project_path / "REQUIREMENTS.md"
    if req_file.exists():
        try:
            req_text = req_file.read_text(encoding="utf-8")
            requirement_ids = set(re.findall(r"REQ-\d+", req_text))
        except (OSError, UnicodeDecodeError):
            pass  # Non-fatal — skip requirement cross-check

    findings = validate_ownership_map(ownership_map, requirement_ids)
    has_critical = any(f.severity == "critical" for f in findings)

    return (not has_critical, findings)
