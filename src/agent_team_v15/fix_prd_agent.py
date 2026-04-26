"""Fix PRD Agent — Generates structured fix PRDs from audit findings.

Takes structured findings from the audit agent and produces a fix PRD that
the builder LLM can read as bounded-context features with acceptance criteria.
Groups related findings by root cause and produces ``### F-FIX-NNN:`` features.

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

import re
from pathlib import Path
from typing import Any, Optional

from agent_team_v15.audit_agent import Finding, FindingCategory, Severity, _clean_finding_text
from agent_team_v15.registry_compiler import COMPILED_SHARED_SURFACES


# ---------------------------------------------------------------------------
# AC criterion builder (Fix 5)
# ---------------------------------------------------------------------------


def _build_ac_from_finding(f: Finding) -> str:
    """Build a clean, actionable AC from a finding."""
    # Try explicit acceptance criterion first
    ac = getattr(f, 'acceptance_criterion', None)
    if ac and len(str(ac).strip()) > 20:
        cleaned = _clean_finding_text(str(ac))
        if cleaned:
            return cleaned

    # Synthesize from structured fields
    parts: list[str] = []
    fp = getattr(f, 'file_path', None)
    eb = getattr(f, 'expected_behavior', None)
    cb = getattr(f, 'current_behavior', None)
    if fp:
        parts.append(f"In {fp}")
    if eb:
        parts.append(f"Expected: {_clean_finding_text(str(eb))}")
    if cb:
        parts.append(f"Actual: {_clean_finding_text(str(cb))}")
    if parts:
        return '. '.join(p for p in parts if p)

    # Fall back to clean title
    title = getattr(f, 'title', None)
    if title:
        cleaned = _clean_finding_text(str(title))
        if cleaned:
            return cleaned

    # Last resort: description
    desc = getattr(f, 'description', None)
    if desc:
        cleaned = _clean_finding_text(str(desc)[:200])
        if cleaned:
            return cleaned

    return "Fix identified issue"


# ---------------------------------------------------------------------------
# Fix PRD scoping and filtering
# ---------------------------------------------------------------------------

# Maximum number of findings per fix cycle to prevent scope creep
MAX_FINDINGS_PER_FIX_CYCLE = 20

# Maximum fix PRD size in characters to avoid LLM context overflow
MAX_FIX_PRD_CHARS = 50_000

# Maximum fix features (root-cause groups) in a single fix PRD
MAX_FIX_FEATURES = 20

# Severity priority for sorting (lower = higher priority)
_SEVERITY_PRIORITY = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.ACCEPTABLE_DEVIATION: 4,
    Severity.REQUIRES_HUMAN: 5,
}

# Impact-based keywords for categorizing findings (Phase 6.2 + 8.3)
_WIRING_KEYWORDS = ("wiring", "integration", "contract", "response_shape", "field_name", "endpoint", "api_call", "route")
_AUTH_KEYWORDS = ("auth", "security", "jwt", "guard", "token", "permission", "rbac", "cors")
_MISSING_KEYWORDS = ("missing", "unimplemented", "not_found", "stub", "todo", "placeholder")
_FULL_MODE_EXACT_FILES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    *COMPILED_SHARED_SURFACES,
}
_FULL_MODE_PATH_MARKERS = (
    "migration",
    "schema.prisma",
    ".entity.",
    "/entities/",
    "\\entities\\",
    ".dto.",
    ".controller.",
    "middleware",
    "interceptor",
    "guard",
    "/ports/",
    "\\ports\\",
    "adapter",
    "openapi",
    "asyncapi",
    ".agent-team/registries/",
)
_FULL_MODE_TEXT_MARKERS = (
    "new feature",
    "missing feature",
    "from scratch",
    "schema",
    "migration",
    "openapi",
    "asyncapi",
    "contract decorator",
    "generated client",
    "route auth",
    "lockfile",
    "translation registry",
    "nav registry",
    "adapter port",
)


def _get_impact_priority(finding: Finding) -> int:
    """Classify finding by impact priority. Lower = higher priority.

    0 = WIRING (frontend-backend integration issues)
    1 = AUTH (security and authentication issues)
    2 = MISSING (unimplemented features)
    3 = QUALITY (error handling, tests, other)
    """
    searchable = " ".join([
        finding.category.value if finding.category else "",
        finding.title.lower() if finding.title else "",
        finding.id.lower() if finding.id else "",
        finding.description.lower()[:200] if finding.description else "",
    ]).lower()

    # Check auth first when the category is SECURITY to avoid false wiring matches
    if finding.category == FindingCategory.SECURITY:
        return 1
    if any(kw in searchable for kw in _AUTH_KEYWORDS):
        return 1
    if any(kw in searchable for kw in _WIRING_KEYWORDS):
        return 0
    if finding.category == FindingCategory.MISSING_FEATURE:
        return 2
    if any(kw in searchable for kw in _MISSING_KEYWORDS):
        return 2
    return 3


def _normalize_file_path(path: str) -> str:
    return path.replace("\\", "/").strip().lower()


def classify_fix_feature_mode(feature: dict[str, Any]) -> str:
    """Classify a fix feature as full or patch using V18.1 blast-radius rules."""

    findings = [
        finding for finding in feature.get("findings", [])
        if isinstance(finding, Finding)
    ]
    files = {
        _normalize_file_path(path)
        for path in (
            list(feature.get("files_to_modify", []) or [])
            + list(feature.get("files_to_create", []) or [])
            + [getattr(finding, "file_path", "") for finding in findings]
        )
        if isinstance(path, str) and path.strip()
    }
    text_parts = [
        str(feature.get("name", "") or ""),
        str(feature.get("description", "") or ""),
    ]
    for finding in findings:
        text_parts.extend(
            [
                str(getattr(finding, "title", "") or ""),
                str(getattr(finding, "description", "") or ""),
                str(getattr(finding, "fix_suggestion", "") or ""),
                str(getattr(finding, "current_behavior", "") or ""),
                str(getattr(finding, "expected_behavior", "") or ""),
            ]
        )
    description = " ".join(text_parts).lower()

    if any(getattr(finding, "category", None) == FindingCategory.MISSING_FEATURE for finding in findings):
        return "full"
    if findings and any(not getattr(finding, "file_path", "") for finding in findings):
        return "full"
    if any(file_path in _FULL_MODE_EXACT_FILES for file_path in files):
        return "full"
    if any(marker in file_path for file_path in files for marker in _FULL_MODE_PATH_MARKERS):
        return "full"
    if any(marker in description for marker in _FULL_MODE_TEXT_MARKERS):
        return "full"
    return "patch"


def filter_findings_for_fix(
    findings: list[Finding],
    max_findings: int = MAX_FINDINGS_PER_FIX_CYCLE,
    confidence_threshold: float = 0.8,
    deterministic_only: bool = False,
    regression_watchlist: Optional[list[str]] = None,
) -> list[Finding]:
    """Filter and prioritize findings for a fix PRD.

    Filtering rules:
    1. Always include deterministic findings (source="deterministic")
    2. Include LLM findings only if confidence >= threshold
    3. Exclude REQUIRES_HUMAN and ACCEPTABLE_DEVIATION severities
    4. Prioritize: regressions > impact category > severity > deterministic
    5. Cap at max_findings to prevent scope creep

    Impact category ordering (Phase 6.2):
    - WIRING fixes first (integration, contract, response shape)
    - AUTH fixes second (security, JWT, guards)
    - MISSING features third (unimplemented, stubs)
    - Quality / tests / error handling last

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

        # For LLM findings, apply confidence threshold when available.
        # Finding currently has no 'confidence' field — all LLM findings pass through.
        # TODO: Wire confidence scoring when Finding dataclass gains a confidence attribute.
        if not is_det:
            conf = getattr(f, "confidence", None)
            if conf is not None and conf < confidence_threshold:
                continue

        actionable.append(f)

    # Step 2: Sort by severity FIRST, then impact within same severity, then deterministic boost
    def _sort_key(f: Finding) -> tuple[int, int, int, int]:
        # Boost regression findings (files in watchlist)
        is_regression = 0 if f.file_path in regression_files else 1
        # Severity is PRIMARY sort — CRITICAL always before HIGH, etc.
        sev_order = _SEVERITY_PRIORITY.get(f.severity, 99)
        # Impact-based priority WITHIN same severity (wiring > auth > missing > quality)
        impact = _get_impact_priority(f)
        # Boost deterministic findings within same severity+impact
        is_det = 0 if f.id.startswith("DET-") else 1
        return (is_regression, sev_order, impact, is_det)

    actionable.sort(key=_sort_key)

    # Step 3: Cap at max_findings
    selected = actionable[:max_findings]

    # Step 4: Ensure every feature with findings has at least one representative
    # This prevents MEDIUM-severity features (e.g., STATUS/DASH) from being
    # entirely dropped when CRITICAL/HIGH findings fill all slots.
    features_with_findings = {f.feature for f in selected}
    for f in actionable[max_findings:]:
        if f.feature not in features_with_findings:
            selected.append(f)
            features_with_findings.add(f.feature)

    return selected


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
    """Generate a structured fix PRD from audit findings.

    The fix PRD uses ``### F-FIX-NNN:`` headings that the builder LLM reads
    as bounded-context features.  Related findings are grouped by root cause
    so the builder sees coherent fix tasks rather than a flat finding list.

    Returns the fix PRD as a markdown string (capped at *MAX_FIX_PRD_CHARS*).
    """
    config = config or {}
    previously_passing_acs = previously_passing_acs or []

    prd_text = original_prd_path.read_text(encoding="utf-8", errors="replace")

    # Extract components from original PRD
    project_name = _extract_project_name(prd_text)
    tech_stack = _extract_tech_stack_section(prd_text)

    # Group findings by root cause into fix features
    fix_features = _group_findings_by_root_cause(findings)

    # Render with size guard — drop lowest-priority features until under limit
    fix_prd = _render_fix_prd(
        project_name, codebase_path, original_prd_path,
        tech_stack, fix_features, findings, run_number,
        previously_passing_acs,
    )

    while len(fix_prd) > MAX_FIX_PRD_CHARS and fix_features:
        fix_features.pop()  # Remove lowest priority (last) feature
        fix_prd = _render_fix_prd(
            project_name, codebase_path, original_prd_path,
            tech_stack, fix_features, findings, run_number,
            previously_passing_acs,
        )

    # Validate
    if not _validate_fix_prd(fix_prd):
        fix_prd = _ensure_parser_compatibility(fix_prd, tech_stack)

    return fix_prd


def _render_fix_prd(
    project_name: str,
    codebase_path: Path,
    original_prd_path: Path,
    tech_stack: str,
    fix_features: list[dict[str, Any]],
    all_findings: list[Finding],
    run_number: int,
    previously_passing_acs: list[str],
) -> str:
    """Render the full fix PRD markdown from grouped fix features."""
    # Flatten all findings covered by the current feature set
    covered_findings = []
    for feat in fix_features:
        covered_findings.extend(feat["findings"])

    critical = sum(1 for f in covered_findings if f.severity == Severity.CRITICAL)
    high = sum(1 for f in covered_findings if f.severity == Severity.HIGH)
    medium = sum(1 for f in covered_findings if f.severity == Severity.MEDIUM)

    sections: list[str] = []

    # --- Header + Overview ---
    sections.append(f"# {project_name} — Targeted Fix Run {run_number}")
    sections.append(f"""## Overview

Targeted modifications to the existing **{project_name}** codebase.
ALL existing functionality MUST be preserved. Only the features below should change.
The codebase at `{codebase_path}` is the working base — read existing files before modifying.

- **Original PRD:** `{original_prd_path}`
- **Findings addressed:** {len(covered_findings)} ({critical} CRITICAL, {high} HIGH, {medium} MEDIUM)""")

    # --- Tech Stack ---
    sections.append(_build_tech_stack_section(tech_stack))

    # --- Features ---
    # Read original PRD text for enriching new feature sections
    try:
        _prd_text = original_prd_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _prd_text = ""
    # Phase 3.5: pass codebase_path so the features section can fall
    # back to evidence/description synthesis when a feature's findings
    # carry no direct file_path. Closes the free-form-features-bypass-
    # the-audit-fix-hook gap (Phase 3 landing carry-over).
    sections.append(
        _build_features_section(fix_features, prd_text=_prd_text, project_root=codebase_path)
    )

    # --- Regression Guard ---
    # Derive failing ACs from findings so the fix prompt shows the FULL AC
    # surface (passing + failing). Claude should not regress a passing AC
    # while fixing a failing one, and should not break another failing AC
    # deeper than it already is.
    failing_ac_ids: list[str] = []
    seen_failing = set()
    for f in all_findings:
        ac_id = str(getattr(f, "acceptance_criterion", "") or "").strip()
        if not ac_id or ac_id in seen_failing or ac_id in previously_passing_acs:
            continue
        seen_failing.add(ac_id)
        failing_ac_ids.append(ac_id)
    sections.append(
        _build_regression_guard_section(previously_passing_acs, failing_ac_ids)
    )

    return "\n\n".join(sections)


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




# ---------------------------------------------------------------------------
# Finding enrichment
# ---------------------------------------------------------------------------


def _group_findings_by_root_cause(findings: list[Finding]) -> list[dict[str, Any]]:
    """Group related findings into fix features by root cause.

    Returns a priority-sorted list of feature dicts, each containing:
    - ``name``: human-readable group name
    - ``findings``: list of Finding objects in this group
    - ``category``: dominant FindingCategory
    - ``severity``: highest severity in the group
    """
    groups: dict[str, dict[str, Any]] = {}

    for f in findings:
        key = _root_cause_key(f)
        if key not in groups:
            groups[key] = {
                "name": _root_cause_name(key),
                "findings": [],
                "category": f.category,
                "severity": f.severity,
            }
        groups[key]["findings"].append(f)
        # Promote severity to the highest in the group
        if _SEVERITY_PRIORITY.get(f.severity, 99) < _SEVERITY_PRIORITY.get(groups[key]["severity"], 99):
            groups[key]["severity"] = f.severity

    # Sort: CRITICAL first, then HIGH, then MEDIUM; within same severity prefer WIRING
    def _sort_key(g: dict[str, Any]) -> tuple[int, int]:
        sev = _SEVERITY_PRIORITY.get(g["severity"], 99)
        cat_boost = 0 if g["category"] in (FindingCategory.CODE_FIX,) else 1
        return (sev, cat_boost)

    sorted_groups = sorted(groups.values(), key=_sort_key)
    return sorted_groups[:MAX_FIX_FEATURES]


def _root_cause_key(f: Finding) -> str:
    """Derive a root-cause grouping key from a finding."""
    desc_lower = (f.description or "").lower()
    title_lower = (f.title or "").lower()
    combined = desc_lower + " " + title_lower

    if f.category == FindingCategory.MISSING_FEATURE:
        return f"missing_{f.feature or 'general'}"
    if f.category == FindingCategory.SECURITY:
        return "auth_security"
    if any(kw in combined for kw in ("snake_case", "camelcase", "casing", "case mismatch")):
        return "request_body_casing"
    if any(kw in combined for kw in ("response shape", "unwrap", "pagination", "wrapper")):
        return "response_shape_mismatch"
    if any(kw in combined for kw in ("docker", "dockerfile", "compose")):
        return "docker_infrastructure"
    if any(kw in combined for kw in _WIRING_KEYWORDS):
        return f"wiring_{(f.file_path or 'unknown').split('/')[-1]}"
    # Fall back to feature + category
    feature = f.feature if f.feature and f.feature != "unknown" else "general"
    return f"{f.category.value}_{feature}"


def _root_cause_name(key: str) -> str:
    """Convert a root-cause key to a human-readable feature name."""
    names: dict[str, str] = {
        "request_body_casing": "Request Body Casing Fixes",
        "response_shape_mismatch": "Response Shape Corrections",
        "docker_infrastructure": "Docker Infrastructure Setup",
        "auth_security": "Authentication & Security Fixes",
    }
    if key in names:
        return names[key]
    return key.replace("_", " ").title()


# ---------------------------------------------------------------------------
# PRD section builders
# ---------------------------------------------------------------------------


def _build_features_section(
    fix_features: list[dict[str, Any]],
    prd_text: str = "",
    *,
    project_root: "Path | str | None" = None,
) -> str:
    """Build the ``## Features`` section with ``### F-FIX-NNN:`` headings.

    Each fix feature is a root-cause group containing one or more findings.
    The builder LLM reads these as bounded-context items.

    Phase 3.5 audit-fix-loop guardrail: when ``project_root`` is
    provided AND a feature's findings carry no direct ``file_path``,
    fall back to :func:`audit_models.synthesise_primary_file` to walk
    each finding's text fields for path-shaped tokens that exist on
    disk. The synthesised paths populate ``#### Files to Modify`` so
    every emitted feature carries scope binding for the per-feature
    audit-fix path-guard hook (Phase 3 §F AC1+AC4). Without
    ``project_root`` the function falls back to legacy direct-file_path
    behaviour (backward compat with all callers that don't yet plumb
    the codebase path).
    """
    lines: list[str] = ["## Features"]

    for idx, feat in enumerate(fix_features, 1):
        feat_findings = feat["findings"]
        execution_mode = classify_fix_feature_mode(feat)
        feat["execution_mode"] = execution_mode
        is_new_feature = all(
            f.category == FindingCategory.MISSING_FEATURE for f in feat_findings
        )
        label = f"F-FIX-{idx:03d}"
        lines.append(f"\n### {label}: {feat['name']}")

        # Description: summarise what needs to change
        # Detect partially missing features: findings with no file_path indicate
        # code that doesn't exist yet (e.g., backend exists but frontend missing)
        has_missing_files = any(not getattr(f, "file_path", "") for f in feat_findings)
        if is_new_feature:
            lines.append("[NEW FEATURE]")
            lines.append(f"[EXECUTION_MODE: {execution_mode}]")
            lines.append("")
            lines.append("**Implementation required from scratch.** Create all necessary files.")
        elif has_missing_files:
            lines.append(f"[SEVERITY: {feat['severity'].value.upper()}]")
            lines.append(f"[EXECUTION_MODE: {execution_mode}]")
            lines.append("")
            lines.append("**Some components for this feature are missing.** Create any files that do not yet exist.")
        else:
            lines.append(f"[SEVERITY: {feat['severity'].value.upper()}]")
            lines.append(f"[EXECUTION_MODE: {execution_mode}]")
        # Include original PRD specification for new or partially missing features
        if (is_new_feature or has_missing_files) and prd_text:
            feature_name = feat["name"]
            pattern = rf"###\s+F-\d{{3}}[^#]*?{re.escape(feature_name)}.*?(?=###|\Z)"
            match = re.search(pattern, prd_text, re.DOTALL | re.IGNORECASE)
            if match:
                lines.append("")
                lines.append("**Original PRD specification:**")
                lines.append(match.group(0).strip()[:2000])

        # Build description from constituent findings (Fix 4: clean text)
        desc_parts: list[str] = []
        for f in feat_findings[:5]:  # Cap description at 5 findings
            clean_title = _clean_finding_text(f.title) or f.title
            clean_desc = _clean_finding_text(f.description[:200]) or f.description[:200]
            desc_parts.append(f"- {clean_title}: {clean_desc}")
        lines.append("")
        lines.append("\n".join(desc_parts))

        # Constraints / important notes
        constraints: list[str] = []
        for f in feat_findings:
            if f.fix_suggestion:
                constraints.append(_clean_finding_text(f.fix_suggestion[:300]) or f.fix_suggestion[:300])
        if constraints:
            lines.append("")
            lines.append(f"**IMPORTANT:** {constraints[0]}")
            for c in constraints[1:3]:
                lines.append(f"- {c}")

        # Files to modify
        files_seen: set[str] = set()
        file_entries: list[str] = []
        for f in feat_findings:
            if f.file_path and f.file_path not in files_seen:
                files_seen.add(f.file_path)
                loc = f"`{f.file_path}`"
                if f.line_number > 0:
                    loc += f" (line {f.line_number})"
                file_entries.append(f"- {loc}")
        # Phase 3.5: fall back to evidence/description synthesis when no
        # finding in this feature carried a direct file_path AND we have
        # a project_root to validate paths against. Without synthesis,
        # the emitted feature has no ``#### Files to Modify`` section,
        # ``_parse_fix_features`` returns ``files_to_modify=[]``, and
        # ``_run_patch_fixes`` either skips (Phase 3.5 dispatch backstop)
        # or — pre-Phase 3.5 — proceeds without scope binding (the gap
        # this phase closes).
        if not file_entries and project_root is not None:
            from .audit_models import synthesise_primary_file

            synth_seen: set[str] = set()
            for f in feat_findings:
                for synth in synthesise_primary_file(f, project_root=project_root):
                    if synth in synth_seen:
                        continue
                    synth_seen.add(synth)
                    file_entries.append(f"- `{synth}`")
        if file_entries:
            lines.append("")
            lines.append("#### Files to Modify")
            lines.extend(file_entries)

        # Acceptance criteria (Fix 5: use _build_ac_from_finding)
        lines.append("")
        lines.append("#### Acceptance Criteria")

        # Systemic pattern detection: if a dominant check accounts for >50%
        # of findings AND has >3 instances → one strategic AC.
        from collections import Counter as _Counter
        _check_counts = _Counter(
            getattr(f, "check", None) or f.id.rsplit("-", 1)[0]
            for f in feat_findings
        )
        _dominant_check, _dominant_count = _check_counts.most_common(1)[0]
        _is_systemic = _dominant_count > 3 and (_dominant_count / len(feat_findings)) > 0.5

        if _is_systemic:
            dominant_findings = [
                f for f in feat_findings
                if (getattr(f, "check", None) or f.id.rsplit("-", 1)[0]) == _dominant_check
            ]
            first = dominant_findings[0]
            strategic = (
                _clean_finding_text(first.fix_suggestion or "")
                or _clean_finding_text(first.acceptance_criterion or "")
                or "Fix all instances of this pattern"
            )
            files_affected = sorted({f.file_path for f in feat_findings if f.file_path})
            lines.append(f"- AC-FIX-{idx:03d}-01: {strategic}")
            lines.append(f"  - Scope: {len(feat_findings)} instances across {len(files_affected)} files")
            file_list = ", ".join(files_affected[:5])
            if len(files_affected) > 5:
                file_list += f" (+ {len(files_affected) - 5} more)"
            lines.append(f"  - Affected files: {file_list}")

            # List minority findings as supplementary context
            minority_findings = [f for f in feat_findings if f not in dominant_findings]
            if minority_findings:
                lines.append(f"  - Additional related findings: {len(minority_findings)}")
                for mf in minority_findings[:3]:
                    clean_title = _clean_finding_text(mf.title)
                    if clean_title:
                        lines.append(f"    - {clean_title}")
        else:
            ac_idx = 0
            for f in feat_findings:
                ac_idx += 1
                criterion = _build_ac_from_finding(f)
                lines.append(f"- AC-FIX-{idx:03d}-{ac_idx:02d}: {criterion}")
                # Add expected-vs-current for context
                if f.current_behavior and f.expected_behavior:
                    lines.append(
                        f"  - Current: {_clean_finding_text(f.current_behavior[:150]) or f.current_behavior[:150]}"
                    )
                    lines.append(
                        f"  - Expected: {_clean_finding_text(f.expected_behavior[:150]) or f.expected_behavior[:150]}"
                    )

        lines.append("")

    return "\n".join(lines)


def _build_regression_guard_section(
    previously_passing_acs: list[str],
    failing_ac_ids: list[str] | None = None,
) -> str:
    """Build the Regression Guard section listing the full AC surface.

    Claude sees both PASSING ACs (regression guard) and FAILING ACs
    (do not regress further). The goal is to prevent a fix to one AC
    from breaking another, and to keep Claude aware of the total surface
    it must respect.
    """
    failing_ac_ids = failing_ac_ids or []
    lines = [
        "## Regression Guard",
        "",
        "The FULL milestone acceptance criteria surface — every passing AC",
        "MUST still pass after your fix, and no failing AC may regress further.",
        "",
    ]
    if previously_passing_acs or failing_ac_ids:
        for ac_id in previously_passing_acs:
            lines.append(f"- [PASSING] {ac_id} — must stay green after your fix")
        for ac_id in failing_ac_ids:
            lines.append(f"- [FAILING] {ac_id} — may be the target of your fix; at minimum do not regress further")
    else:
        lines.append("- (No previously passing ACs recorded)")
    return "\n".join(lines)


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




# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_fix_prd(prd_text: str) -> bool:
    """Validate that the fix PRD has the expected structure.

    Checks:
    - Has a project title (H1)
    - Has ``## Features`` section with at least one ``### F-FIX-`` heading
    - Has technology mentions
    - Is at least 200 chars
    """
    if len(prd_text) < 200:
        return False

    # Must have H1 title
    if not re.search(r"^#\s+", prd_text, re.MULTILINE):
        return False

    # Must have ## Features section
    if "## Features" not in prd_text:
        return False

    # Must have at least one F-FIX heading
    if not re.search(r"^###\s+F-FIX-\d{3}:", prd_text, re.MULTILINE):
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
    """Fix structural issues in the PRD text."""
    # Ensure H1 title exists
    if not re.search(r"^#\s+", prd_text, re.MULTILINE):
        prd_text = "# Fix Run Application\n\n" + prd_text

    # Ensure tech stack is present
    if "Technology Stack" not in prd_text and "Tech Stack" not in prd_text:
        if tech_stack:
            insert_pos = prd_text.find("## Features")
            if insert_pos > 0:
                prd_text = prd_text[:insert_pos] + tech_stack + "\n\n" + prd_text[insert_pos:]
            else:
                prd_text += "\n\n" + tech_stack

    return prd_text
