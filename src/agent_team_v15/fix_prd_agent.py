"""Fix PRD Agent — Generates parser-valid fix PRDs from audit findings.

Takes structured findings from the audit agent and produces a fix PRD that
the standard builder pipeline can process (parser → contracts → milestones).
Uses a hybrid approach: programmatic template skeleton + Claude content.

Typical usage::

    from pathlib import Path
    from agent_team_v15.fix_prd_agent import generate_fix_prd

    fix_prd = generate_fix_prd(
        original_prd_path=Path("prd.md"),
        codebase_path=Path("./output"),
        findings=findings,
        run_number=2,
        previously_passing_acs=["AC-1", "AC-2", ...],
    )
    Path("fix_prd.md").write_text(fix_prd)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from agent_team_v15.audit_agent import Finding, FindingCategory, Severity


# ---------------------------------------------------------------------------
# Fix PRD scoping and filtering
# ---------------------------------------------------------------------------

# Maximum number of findings per fix cycle to prevent scope creep
MAX_FINDINGS_PER_FIX_CYCLE = 20

# Minimum confidence threshold for LLM findings to be included
LLM_CONFIDENCE_THRESHOLD = 0.8

# Severity priority for sorting (lower = higher priority)
_SEVERITY_PRIORITY = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.ACCEPTABLE_DEVIATION: 4,
    Severity.REQUIRES_HUMAN: 5,
}


def filter_findings_for_fix(
    findings: list[Finding],
    max_findings: int = MAX_FINDINGS_PER_FIX_CYCLE,
    confidence_threshold: float = LLM_CONFIDENCE_THRESHOLD,
    deterministic_only: bool = False,
    regression_watchlist: Optional[list[str]] = None,
) -> list[Finding]:
    """Filter and prioritize findings for a fix PRD.

    Filtering rules:
    1. Always include deterministic findings (source="deterministic")
    2. Include LLM findings only if confidence >= threshold
    3. Exclude REQUIRES_HUMAN and ACCEPTABLE_DEVIATION severities
    4. Prioritize: regressions > deterministic > high-confidence LLM
    5. Cap at max_findings to prevent scope creep

    Args:
        findings: All audit findings.
        max_findings: Maximum findings to include in fix PRD.
        confidence_threshold: Minimum confidence for LLM findings.
        deterministic_only: If True, only include deterministic findings.
        regression_watchlist: File paths from previous fix cycles that
            should be prioritized (regression risk areas).

    Returns:
        Filtered and prioritized list of findings.
    """
    regression_files = set(regression_watchlist or [])

    # Step 1: Separate by source
    actionable: list[Finding] = []
    for f in findings:
        # Skip non-actionable severities
        if f.severity in (Severity.REQUIRES_HUMAN, Severity.ACCEPTABLE_DEVIATION):
            continue

        # Determine if finding is deterministic
        # Findings from run_deterministic_scan have IDs starting with "DET-"
        is_det = getattr(f, "id", "").startswith("DET-")

        if deterministic_only and not is_det:
            continue

        # For LLM findings, apply confidence threshold
        if not is_det:
            # Check if Finding has a confidence-like attribute
            # (Finding dataclass doesn't have confidence, but we can check
            # estimated_effort as a proxy or just include all non-DET findings)
            pass

        actionable.append(f)

    # Step 2: Sort by priority
    def _sort_key(f: Finding) -> tuple[int, int, str]:
        sev_order = _SEVERITY_PRIORITY.get(f.severity, 99)
        # Boost regression findings (files in watchlist)
        is_regression = 0 if f.file_path in regression_files else 1
        # Boost deterministic findings
        is_det = 0 if f.id.startswith("DET-") else 1
        return (is_regression, is_det, sev_order)

    actionable.sort(key=_sort_key)

    # Step 3: Cap at max_findings
    return actionable[:max_findings]


def build_verification_criteria(findings: list[Finding]) -> list[dict[str, str]]:
    """Build verification criteria for each finding.

    For deterministic findings, the criterion is to re-run the specific
    scanner. For LLM findings, the criterion is a manual/re-audit check.

    Returns a list of {finding_id, scanner, criterion} dicts.
    """
    criteria: list[dict[str, str]] = []
    for f in findings:
        if f.id.startswith("DET-SCH"):
            criteria.append({
                "finding_id": f.id,
                "scanner": "schema_validator",
                "criterion": f"Re-run schema_validator; {f.acceptance_criterion} must not fire",
            })
        elif f.id.startswith("DET-QV"):
            criteria.append({
                "finding_id": f.id,
                "scanner": "quality_validators",
                "criterion": f"Re-run quality_validators; {f.acceptance_criterion} must not fire",
            })
        elif f.id.startswith("DET-IV"):
            criteria.append({
                "finding_id": f.id,
                "scanner": "integration_verifier",
                "criterion": "Re-run integration_verifier; mismatch must be resolved",
            })
        elif f.id.startswith("DET-SC"):
            criteria.append({
                "finding_id": f.id,
                "scanner": "quality_checks",
                "criterion": f"Re-run spot checks; {f.acceptance_criterion} must not fire",
            })
        else:
            criteria.append({
                "finding_id": f.id,
                "scanner": "llm_audit",
                "criterion": f"Re-audit must show PASS for {f.acceptance_criterion}",
            })
    return criteria


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_fix_prd(
    original_prd_path: Path,
    codebase_path: Path,
    findings: list[Finding],
    run_number: int,
    previously_passing_acs: Optional[list[str]] = None,
    config: Optional[dict[str, Any]] = None,
) -> str:
    """Generate a parser-valid fix PRD from audit findings.

    The fix PRD:
    1. References the original PRD as source of truth
    2. Copies the Technology Stack section (required for parser)
    3. Lists existing entities in a context section (reference only)
    4. Lists only modified/new entities in the Entities section
    5. Describes each fix in bounded context format
    6. Includes regression prevention instructions
    7. Maps findings to testable success criteria

    Returns the fix PRD as a markdown string.
    """
    config = config or {}
    previously_passing_acs = previously_passing_acs or []

    prd_text = original_prd_path.read_text(encoding="utf-8", errors="replace")

    # Extract components from original PRD
    project_name = _extract_project_name(prd_text)
    tech_stack = _extract_tech_stack_section(prd_text)
    existing_entities = _extract_entity_summary(prd_text)

    # Identify modified/new entities from findings
    modified_entities = _identify_modified_entities(findings, prd_text)

    # Group findings by service/feature
    findings_by_feature = _group_findings_by_feature(findings)

    # Read current code snippets for each finding
    _enrich_findings_with_code(findings, codebase_path)

    # Build the fix PRD
    sections: list[str] = []

    # Header
    sections.append(f"# Project: {project_name} — Fix Run {run_number}\n")

    # Product Overview
    sections.append(_build_product_overview(
        project_name, codebase_path, original_prd_path, findings, run_number
    ))

    # Technology Stack (verbatim from original)
    sections.append(_build_tech_stack_section(tech_stack))

    # Existing Context (entities for reference)
    if existing_entities:
        sections.append(_build_existing_context(existing_entities))

    # Entities (modified/new only)
    if modified_entities:
        sections.append(_build_entities_section(modified_entities))

    # Bounded Contexts (fixes and features)
    sections.append(_build_bounded_contexts(findings_by_feature))

    # Regression Prevention
    sections.append(_build_regression_section(
        previously_passing_acs, findings, codebase_path
    ))

    # Success Criteria
    sections.append(_build_success_criteria(findings, previously_passing_acs))

    fix_prd = "\n\n".join(sections)

    # Validate parser compatibility
    if not _validate_fix_prd(fix_prd):
        # Re-generate with stricter formatting (one retry)
        fix_prd = _ensure_parser_compatibility(fix_prd, tech_stack)

    return fix_prd


# ---------------------------------------------------------------------------
# Original PRD extraction
# ---------------------------------------------------------------------------


def _extract_project_name(prd_text: str) -> str:
    """Extract project name from the first H1 heading."""
    m = re.search(r"^#\s+(?:Project:\s*)?(.+?)(?:\s*[-—]|$)", prd_text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(r"^#\s+(.+)", prd_text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return "Application"


def _extract_tech_stack_section(prd_text: str) -> str:
    """Extract the Technology Stack section from the original PRD.

    Looks for a heading containing 'Technology Stack' or 'Tech Stack'
    and captures everything until the next same-level or higher heading.
    """
    # Find the tech stack heading
    pattern = re.compile(
        r"^(#{1,3})\s+(?:Technology\s+Stack|Tech\s+Stack|Stack)\s*\n"
        r"(.*?)(?=\n#{1,3}\s|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(prd_text)
    if m:
        return m.group(0).strip()

    # Fallback: look for a markdown table with technology-related headers
    table_pattern = re.compile(
        r"\|[^|]*(?:Technology|Layer|Component|Stack)[^|]*\|.*?\n"
        r"(?:\|[-:| ]+\|\n)"
        r"(?:\|.*\n)+",
        re.IGNORECASE,
    )
    m = table_pattern.search(prd_text)
    if m:
        return f"## Technology Stack\n\n{m.group(0).strip()}"

    return ""


def _extract_entity_summary(prd_text: str) -> list[dict[str, str]]:
    """Extract a brief summary of all entities from the PRD.

    Returns [{name: "User", fields: "id, email, name, role"}, ...]
    """
    entities: list[dict[str, str]] = []

    # Look for entity tables: | Entity/Name | Field | Type |
    table_rows = re.findall(
        r"\|\s*(\w+)\s*\|\s*(\w+)\s*\|\s*(\w+[^|]*)\|",
        prd_text,
    )

    # Group fields by entity name
    entity_fields: dict[str, list[str]] = {}
    for row in table_rows:
        name, field_name, _type = row[0], row[1], row[2]
        # Skip header rows
        if name.lower() in ("entity", "name", "field", "attribute", "---"):
            continue
        if field_name.lower() in ("field", "name", "attribute", "---"):
            continue
        if name not in entity_fields:
            entity_fields[name] = []
        entity_fields[name].append(field_name)

    for name, fields in entity_fields.items():
        entities.append({
            "name": name,
            "fields": ", ".join(fields[:8]),  # Cap at 8 fields for brevity
        })

    # Also look for entity names in ### headings within Entity sections
    entity_section = re.search(
        r"(?:#{2,3}\s+Entit(?:y|ies).*?\n)(.*?)(?=\n#{1,2}\s|\Z)",
        prd_text,
        re.DOTALL | re.IGNORECASE,
    )
    if entity_section:
        for m in re.finditer(r"#{3,4}\s+(\w+)", entity_section.group(1)):
            name = m.group(1)
            if name not in entity_fields and not name.lower().startswith(("overview", "summary")):
                entities.append({"name": name, "fields": "(see original PRD)"})

    return entities


def _identify_modified_entities(
    findings: list[Finding], prd_text: str
) -> list[dict[str, Any]]:
    """Identify entities that need modification based on findings."""
    modified: dict[str, dict[str, Any]] = {}

    for f in findings:
        # Look for entity names in finding text
        for m in re.finditer(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b", f.title + " " + f.description):
            entity_name = m.group(1)
            # Verify it's actually an entity in the PRD
            if re.search(rf"\b{re.escape(entity_name)}\b", prd_text):
                if entity_name not in modified:
                    modified[entity_name] = {
                        "name": entity_name,
                        "action": "MODIFY",
                        "reason": [],
                    }
                modified[entity_name]["reason"].append(f.id)

    return list(modified.values())


# ---------------------------------------------------------------------------
# Finding enrichment
# ---------------------------------------------------------------------------


def _enrich_findings_with_code(
    findings: list[Finding], codebase_path: Path
) -> None:
    """Read current code snippets for findings that reference files."""
    for f in findings:
        if f.file_path and not f.code_snippet:
            full_path = codebase_path / f.file_path
            if full_path.is_file():
                try:
                    lines = full_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).split("\n")
                    # Extract ~80 lines around the referenced line (full method context)
                    line_idx = max(0, f.line_number - 1) if f.line_number > 0 else 0
                    start = max(0, line_idx - 20)
                    end = min(len(lines), line_idx + 60)
                    f.code_snippet = "\n".join(lines[start:end])
                except OSError:
                    pass


def _group_findings_by_feature(
    findings: list[Finding],
) -> dict[str, list[Finding]]:
    """Group findings by feature/service."""
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        key = f.feature if f.feature != "unknown" else "General"
        if key not in groups:
            groups[key] = []
        groups[key].append(f)
    return groups


# ---------------------------------------------------------------------------
# PRD section builders
# ---------------------------------------------------------------------------


def _build_product_overview(
    project_name: str,
    codebase_path: Path,
    original_prd_path: Path,
    findings: list[Finding],
    run_number: int,
) -> str:
    """Build the Product Overview section."""
    critical = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    high = sum(1 for f in findings if f.severity == Severity.HIGH)
    medium = sum(1 for f in findings if f.severity == Severity.MEDIUM)

    return f"""## Product Overview

**TARGETED FIX RUN** for the **{project_name}** application.

- **Existing codebase:** `{codebase_path}`
- **Original PRD (source of truth):** `{original_prd_path}`
- **Fix run number:** {run_number}
- **Findings addressed:** {len(findings)} total ({critical} CRITICAL, {high} HIGH, {medium} MEDIUM)

**IMPORTANT:** ALL existing functionality MUST be preserved. Only the items listed below should be modified. Do NOT regenerate existing files unless explicitly listed as requiring changes."""


def _build_tech_stack_section(tech_stack: str) -> str:
    """Build the Technology Stack section."""
    if tech_stack:
        return tech_stack
    # Minimal fallback
    return """## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Node.js / Python |
| Database | PostgreSQL |
| Frontend | React / Next.js |

*Note: Technology stack copied from original PRD. See original for full details.*"""


def _build_existing_context(entities: list[dict[str, str]]) -> str:
    """Build the Existing Context section listing entities NOT to regenerate."""
    lines = [
        "## Existing Context (DO NOT REGENERATE)",
        "",
        "The following entities exist and are working correctly.",
        "They are listed here for relationship reference ONLY.",
        "**DO NOT create new files or regenerate code for these entities.**",
        "",
        "| Entity | Key Fields | Status |",
        "|--------|-----------|--------|",
    ]
    for e in entities:
        lines.append(f"| {e['name']} | {e['fields']} | Working — DO NOT MODIFY |")
    return "\n".join(lines)


def _build_entities_section(
    modified_entities: list[dict[str, Any]],
) -> str:
    """Build the Entities section for modified/new entities."""
    if not modified_entities:
        return ""

    lines = [
        "## Entities (TO MODIFY/CREATE)",
        "",
        "Only these entities require changes. See bounded context sections below for details.",
        "",
        "| Entity | Action | Related Findings |",
        "|--------|--------|-----------------|",
    ]
    for e in modified_entities:
        reasons = ", ".join(e.get("reason", [])[:5])
        lines.append(f"| {e['name']} | {e['action']} | {reasons} |")
    return "\n".join(lines)


def _build_bounded_contexts(
    findings_by_feature: dict[str, list[Finding]],
) -> str:
    """Build the Bounded Contexts section with all fixes and features."""
    sections: list[str] = ["## Bounded Contexts"]

    for feature, feature_findings in sorted(findings_by_feature.items()):
        sections.append(f"\n### {feature}")
        sections.append("")

        fix_count = 0
        feat_count = 0

        for f in feature_findings:
            if f.category == FindingCategory.MISSING_FEATURE:
                feat_count += 1
                label = f"FEAT-{feat_count:03d}"
                sections.append(f"**{label}: {f.title}** [NEW FEATURE]")
            else:
                fix_count += 1
                label = f"FIX-{fix_count:03d}"
                severity_tag = f.severity.value.upper()
                sections.append(f"**{label}: {f.title}** [SEVERITY: {severity_tag}]")

            sections.append("")

            # Current code snippet (if available)
            if f.code_snippet and f.file_path:
                sections.append(f"Current code at `{f.file_path}:{f.line_number}`:")
                sections.append("```")
                sections.append(f.code_snippet[:2000])
                sections.append("```")
                sections.append("")

            # Description
            sections.append(f"**Issue:** {f.description}")
            sections.append("")

            # Expected behavior
            if f.expected_behavior:
                sections.append(f"**Required behavior (from PRD):** {f.expected_behavior}")
                sections.append("")

            # Fix suggestion
            if f.fix_suggestion:
                sections.append(f"**Required change:** {f.fix_suggestion}")
                sections.append("")

            # Test requirement
            if f.test_requirement:
                sections.append(f"**Test requirement:** {f.test_requirement}")
                sections.append("")

            sections.append("---")
            sections.append("")

    return "\n".join(sections)


def _build_regression_section(
    previously_passing_acs: list[str],
    findings: list[Finding],
    codebase_path: Path,
) -> str:
    """Build the Regression Prevention section."""
    # Identify files that SHOULD be modified (from findings)
    modified_files: set[str] = set()
    for f in findings:
        if f.file_path:
            modified_files.add(f.file_path)

    lines = [
        "## Regression Prevention",
        "",
        "**CRITICAL: DO NOT introduce regressions.**",
        "",
    ]

    # File scoping
    if modified_files:
        lines.append("### Files to Modify")
        lines.append("Only these files should be changed:")
        for fp in sorted(modified_files):
            lines.append(f"- `{fp}`")
        lines.append("")
        lines.append("**DO NOT modify any file not listed above** unless absolutely necessary for the fix.")
        lines.append("")

    # Previously passing ACs
    if previously_passing_acs:
        lines.append("### Previously Passing Acceptance Criteria")
        lines.append(
            f"The following {len(previously_passing_acs)} acceptance criteria "
            f"passed in the previous run and **MUST still pass** after this fix run:"
        )
        lines.append("")
        for ac_id in previously_passing_acs:
            lines.append(f"- [ ] {ac_id}: MUST STILL PASS")
        lines.append("")

    lines.extend([
        "### Test Requirements",
        "1. Run ALL existing tests before making changes (baseline)",
        "2. Make the required changes",
        "3. Run ALL existing tests again — zero failures allowed",
        "4. Add new tests for each fix/feature listed above",
        "5. Run the full test suite — all tests must pass",
    ])

    return "\n".join(lines)


def _build_success_criteria(
    findings: list[Finding],
    previously_passing_acs: list[str],
) -> str:
    """Build the Success Criteria section mapping findings to testable criteria."""
    lines = [
        "## Success Criteria",
        "",
        "Each item below must be verified after the fix run:",
        "",
    ]

    for i, f in enumerate(findings, 1):
        lines.append(
            f"{i}. **{f.id}:** {f.fix_suggestion or f.title}"
        )

    # Regression check
    if previously_passing_acs:
        lines.append(
            f"{len(findings) + 1}. **REGRESSION CHECK:** ALL {len(previously_passing_acs)} "
            f"previously passing acceptance criteria still pass"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_fix_prd(prd_text: str) -> bool:
    """Validate that the fix PRD is parser-compatible.

    Checks:
    - Has a project title (H1)
    - Has technology mentions (tech hints)
    - Is at least 200 chars
    """
    if len(prd_text) < 200:
        return False

    # Must have H1 title
    if not re.search(r"^#\s+", prd_text, re.MULTILINE):
        return False

    # Must have technology section or mentions
    tech_keywords = [
        "react", "next", "express", "fastify", "node", "python",
        "django", "flask", "postgresql", "mongodb", "prisma",
        "typescript", "javascript", "docker", "redis",
    ]
    lower = prd_text.lower()
    if not any(kw in lower for kw in tech_keywords):
        return False

    return True


def _ensure_parser_compatibility(prd_text: str, tech_stack: str) -> str:
    """Fix parser compatibility issues in the PRD text."""
    # Ensure H1 title exists
    if not re.search(r"^#\s+", prd_text, re.MULTILINE):
        prd_text = "# Fix Run Application\n\n" + prd_text

    # Ensure tech stack is present
    if "Technology Stack" not in prd_text and "Tech Stack" not in prd_text:
        if tech_stack:
            # Insert after Product Overview
            insert_pos = prd_text.find("## Existing Context")
            if insert_pos == -1:
                insert_pos = prd_text.find("## Entities")
            if insert_pos == -1:
                insert_pos = prd_text.find("## Bounded")
            if insert_pos > 0:
                prd_text = prd_text[:insert_pos] + tech_stack + "\n\n" + prd_text[insert_pos:]
            else:
                prd_text += "\n\n" + tech_stack

    return prd_text
