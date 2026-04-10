"""Tests for systemic pattern consolidation in _build_features_section.

Verifies that when all findings in a feature group share the same scanner
pattern (same ID prefix) and there are >3 instances, a single strategic AC
is emitted instead of N individual ones.
"""

from __future__ import annotations

from agent_team_v15.audit_agent import Finding, FindingCategory, Severity
from agent_team_v15.fix_prd_agent import _build_features_section


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    *,
    finding_id: str = "WC-001",
    file_path: str = "apps/web/page.tsx",
    fix_suggestion: str = "Add middleware in main.ts",
    acceptance_criterion: str = "Use camelCase in requests",
    title: str = "snake_case field mismatch",
    description: str = "Frontend sends snake_case, DTO expects camelCase",
    current_behavior: str = "",
    expected_behavior: str = "",
    feature: str = "WIRING",
) -> Finding:
    return Finding(
        id=finding_id,
        feature=feature,
        acceptance_criterion=acceptance_criterion,
        severity=Severity.CRITICAL,
        category=FindingCategory.CODE_FIX,
        title=title,
        description=description,
        prd_reference=acceptance_criterion,
        current_behavior=current_behavior,
        expected_behavior=expected_behavior,
        file_path=file_path,
        fix_suggestion=fix_suggestion,
    )


def _make_feature_dict(findings: list[Finding], name: str = "Request Body Casing Fixes") -> dict:
    return {
        "name": name,
        "findings": findings,
        "category": FindingCategory.CODE_FIX,
        "severity": Severity.CRITICAL,
    }


def _ac_lines(result: str) -> list[str]:
    """Extract AC lines from rendered section."""
    return [line.strip() for line in result.split("\n") if line.strip().startswith("- AC-FIX-")]


# ---------------------------------------------------------------------------
# Systemic consolidation — >3 findings with same ID prefix
# ---------------------------------------------------------------------------


def test_systemic_pattern_produces_one_ac():
    """71 findings with same ID prefix → one strategic AC, not 71."""
    findings = [
        _make_finding(finding_id=f"WC-{i:03d}", file_path=f"apps/web/page{i}.tsx")
        for i in range(1, 72)
    ]
    result = _build_features_section([_make_feature_dict(findings)])
    acs = _ac_lines(result)
    assert len(acs) == 1, f"Expected 1 AC, got {len(acs)}: {acs}"


def test_systemic_ac_contains_fix_suggestion():
    """Systemic AC text is the strategic fix_suggestion."""
    findings = [
        _make_finding(
            finding_id=f"WC-{i:03d}",
            file_path=f"apps/web/page{i}.tsx",
            fix_suggestion="Add a global request body transformer middleware in main.ts",
        )
        for i in range(1, 10)
    ]
    result = _build_features_section([_make_feature_dict(findings)])
    assert "middleware" in result.lower()
    assert "main.ts" in result


def test_systemic_pattern_shows_instance_count():
    """Systemic AC includes 'N instances across M files'."""
    findings = [
        _make_finding(finding_id=f"WC-{i:03d}", file_path=f"page{i}.tsx")
        for i in range(1, 11)
    ]
    result = _build_features_section([_make_feature_dict(findings)])
    assert "10 instances" in result


def test_systemic_pattern_shows_file_list():
    """Systemic AC lists affected files."""
    findings = [
        _make_finding(finding_id=f"WC-{i:03d}", file_path=f"page{i}.tsx")
        for i in range(1, 6)
    ]
    result = _build_features_section([_make_feature_dict(findings)])
    assert "Affected files:" in result
    assert "page1.tsx" in result


def test_systemic_pattern_truncates_file_list_at_five():
    """When >5 files, shows first 5 + '+ N more'."""
    findings = [
        _make_finding(finding_id=f"WC-{i:03d}", file_path=f"page{i:02d}.tsx")
        for i in range(1, 12)
    ]
    result = _build_features_section([_make_feature_dict(findings)])
    assert "more)" in result  # e.g. "(+ 6 more)"


def test_systemic_threshold_is_four():
    """Exactly 4 findings → systemic (>3). Exactly 3 → not systemic."""
    findings_4 = [_make_finding(finding_id=f"WC-{i:03d}") for i in range(1, 5)]
    findings_3 = [_make_finding(finding_id=f"WC-{i:03d}") for i in range(1, 4)]

    result_4 = _build_features_section([_make_feature_dict(findings_4)])
    result_3 = _build_features_section([_make_feature_dict(findings_3)])

    assert len(_ac_lines(result_4)) == 1, "4 findings should consolidate"
    assert len(_ac_lines(result_3)) == 3, "3 findings should stay individual"


# ---------------------------------------------------------------------------
# Non-systemic paths — individual ACs preserved
# ---------------------------------------------------------------------------


def test_non_systemic_keeps_individual_acs():
    """3 or fewer findings → individual ACs (no consolidation)."""
    findings = [_make_finding(finding_id=f"WC-{i:03d}") for i in range(1, 4)]
    result = _build_features_section([_make_feature_dict(findings)])
    assert len(_ac_lines(result)) == 3


def test_mixed_id_prefixes_keeps_individual_acs():
    """Findings with different ID prefixes → individual ACs even if >3."""
    findings = (
        [_make_finding(finding_id=f"WC-{i:03d}") for i in range(1, 4)]
        + [_make_finding(finding_id="SCH-001")]
    )
    result = _build_features_section([_make_feature_dict(findings)])
    # Mixed prefixes → not systemic → 4 individual ACs
    assert len(_ac_lines(result)) == 4


def test_single_finding_not_systemic():
    """A single finding always produces one individual AC."""
    findings = [_make_finding(finding_id="WC-001")]
    result = _build_features_section([_make_feature_dict(findings)])
    acs = _ac_lines(result)
    assert len(acs) == 1
    # Individual path: AC should use acceptance_criterion, not scope note
    assert "Scope:" not in result


# ---------------------------------------------------------------------------
# Fallback for empty fix_suggestion
# ---------------------------------------------------------------------------


def test_systemic_falls_back_to_acceptance_criterion():
    """When fix_suggestion is empty, uses acceptance_criterion instead."""
    findings = [
        _make_finding(
            finding_id=f"WC-{i:03d}",
            fix_suggestion="",
            acceptance_criterion="Frontend must use camelCase matching DTO field names",
        )
        for i in range(1, 8)
    ]
    result = _build_features_section([_make_feature_dict(findings)])
    acs = _ac_lines(result)
    assert len(acs) == 1
    assert "camelCase" in result


def test_systemic_falls_back_to_default_when_all_empty():
    """When both fix_suggestion and acceptance_criterion are empty → default text."""
    findings = [
        _make_finding(finding_id=f"WC-{i:03d}", fix_suggestion="", acceptance_criterion="")
        for i in range(1, 6)
    ]
    result = _build_features_section([_make_feature_dict(findings)])
    acs = _ac_lines(result)
    assert len(acs) == 1
    assert "Fix all instances" in result


# ---------------------------------------------------------------------------
# Multiple feature groups
# ---------------------------------------------------------------------------


def test_first_group_systemic_second_not():
    """When two feature groups exist, each is evaluated independently."""
    systemic_findings = [_make_finding(finding_id=f"WC-{i:03d}") for i in range(1, 8)]
    individual_findings = [_make_finding(finding_id=f"SCH-{i:03d}") for i in range(1, 3)]

    features = [
        _make_feature_dict(systemic_findings, name="Wiring Fixes"),
        _make_feature_dict(individual_findings, name="Schema Fixes"),
    ]
    result = _build_features_section(features)
    acs = _ac_lines(result)
    # Feature 1: 1 strategic AC; Feature 2: 2 individual ACs → total 3
    assert len(acs) == 3
