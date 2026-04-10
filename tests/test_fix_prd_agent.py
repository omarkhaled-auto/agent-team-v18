"""Tests for the Fix PRD Agent — fix PRD generation and structure."""

from __future__ import annotations

import pytest
from pathlib import Path

from agent_team_v15.audit_agent import Finding, FindingCategory, Severity
from agent_team_v15.fix_prd_agent import (
    generate_fix_prd,
    filter_findings_for_fix,
    _extract_project_name,
    _extract_tech_stack_section,
    _build_tech_stack_section,
    _build_features_section,
    _build_regression_guard_section,
    _validate_fix_prd,
    _group_findings_by_root_cause,
    _root_cause_key,
    MAX_FIX_PRD_CHARS,
)
from agent_team_v15.prd_parser import parse_prd


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_PRD = """# Project: EVS Customer Portal

## Product Overview
A customer portal for EVS with authentication, invoices, and dashboard.

## Technology Stack
| Layer | Technology |
|-------|-----------|
| Backend | Node.js + Express |
| Database | PostgreSQL + Prisma |
| Frontend | React + Next.js |
| Auth | JWT + bcrypt |

## Entities

### User
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| email | string | Unique email |
| name | string | Display name |
| role | enum | customer, admin |

### Invoice
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| number | string | Invoice number |
| amount | decimal | Total amount |
| status | enum | draft, sent, paid |

## Feature F-001: User Signup
- [ ] AC-1: GIVEN a new email, WHEN signup, THEN account created.

## Feature F-002: Dashboard
- [ ] AC-2: GIVEN logged in, WHEN visit dashboard, THEN see invoices.
"""


def _make_finding(
    id: str = "F-AC-1",
    feature: str = "F-001",
    severity: Severity = Severity.HIGH,
    category: FindingCategory = FindingCategory.CODE_FIX,
    title: str = "Missing validation",
    description: str = "Detailed issue description",
    file_path: str = "src/auth.ts",
    line_number: int = 42,
    code_snippet: str = "function login() { }",
) -> Finding:
    return Finding(
        id=id,
        feature=feature,
        acceptance_criterion="Test AC",
        severity=severity,
        category=category,
        title=title,
        description=description,
        prd_reference="F-001 → AC-1",
        current_behavior="wrong behavior",
        expected_behavior="correct behavior",
        file_path=file_path,
        line_number=line_number,
        code_snippet=code_snippet,
        fix_suggestion="Fix the validation logic",
        estimated_effort="small",
        test_requirement="Test that validation works",
    )


# ---------------------------------------------------------------------------
# PRD extraction
# ---------------------------------------------------------------------------


class TestPRDExtraction:
    """Tests for extracting data from the original PRD."""

    def test_extract_project_name(self):
        name = _extract_project_name(SAMPLE_PRD)
        assert "EVS Customer Portal" in name

    def test_extract_project_name_with_dash(self):
        name = _extract_project_name("# Project: My App — V2\nContent here")
        assert "My App" in name

    def test_extract_tech_stack(self):
        tech = _extract_tech_stack_section(SAMPLE_PRD)
        assert "Node.js" in tech
        assert "PostgreSQL" in tech
        assert "React" in tech


# ---------------------------------------------------------------------------
# Root-cause grouping
# ---------------------------------------------------------------------------


class TestRootCauseGrouping:
    """Tests for root-cause-based finding grouping."""

    def test_groups_by_root_cause(self):
        findings = [
            _make_finding(feature="F-001"),
            _make_finding(id="F-AC-2", feature="F-001"),
            _make_finding(id="F-AC-3", feature="F-002"),
        ]
        groups = _group_findings_by_root_cause(findings)
        assert len(groups) >= 1
        # All findings should be distributed across groups
        total = sum(len(g["findings"]) for g in groups)
        assert total == 3

    def test_groups_casing_findings_together(self):
        f1 = _make_finding(title="snake_case in request body", description="casing mismatch")
        f2 = _make_finding(id="F-AC-2", title="camelCase issue", description="case mismatch")
        groups = _group_findings_by_root_cause([f1, f2])
        # Both should end up in same "request_body_casing" group
        casing_groups = [g for g in groups if "casing" in g["name"].lower()]
        assert len(casing_groups) == 1
        assert len(casing_groups[0]["findings"]) == 2

    def test_groups_security_findings_together(self):
        f1 = _make_finding(category=FindingCategory.SECURITY, title="JWT leak")
        f2 = _make_finding(id="F-AC-2", category=FindingCategory.SECURITY, title="CORS issue")
        groups = _group_findings_by_root_cause([f1, f2])
        sec_groups = [g for g in groups if "auth" in g["name"].lower() or "security" in g["name"].lower()]
        assert len(sec_groups) == 1
        assert len(sec_groups[0]["findings"]) == 2

    def test_severity_promotion(self):
        f1 = _make_finding(severity=Severity.MEDIUM, title="wiring: endpoint missing")
        f2 = _make_finding(id="F-AC-2", severity=Severity.CRITICAL, title="wiring: endpoint crash")
        groups = _group_findings_by_root_cause([f1, f2])
        # The group should have the highest severity (CRITICAL)
        for g in groups:
            if len(g["findings"]) == 2:
                assert g["severity"] == Severity.CRITICAL

    def test_missing_feature_grouped_by_feature(self):
        f1 = _make_finding(category=FindingCategory.MISSING_FEATURE, feature="F-003", title="Missing export")
        key = _root_cause_key(f1)
        assert key == "missing_F-003"

    def test_max_features_cap(self):
        # Create 25 findings with different categories to produce many groups
        findings = []
        for i in range(25):
            findings.append(_make_finding(
                id=f"F-AC-{i}",
                feature=f"F-{i:03d}",
                title=f"Issue {i}",
            ))
        groups = _group_findings_by_root_cause(findings)
        assert len(groups) <= 20


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


class TestSectionBuilders:
    """Tests for individual fix PRD section builders."""

    def test_tech_stack_section(self):
        section = _build_tech_stack_section("## Technology Stack\n| Layer | Tech |\n| Backend | Node |")
        assert "Technology Stack" in section

    def test_tech_stack_fallback(self):
        section = _build_tech_stack_section("")
        assert "Technology Stack" in section

    def test_features_section_structure(self):
        groups = _group_findings_by_root_cause([
            _make_finding(category=FindingCategory.CODE_FIX),
            _make_finding(id="F-AC-2", category=FindingCategory.MISSING_FEATURE, title="Missing widget", feature="F-002"),
        ])
        section = _build_features_section(groups)
        assert "## Features" in section
        assert "### F-FIX-001:" in section
        # Should have acceptance criteria
        assert "AC-FIX-" in section

    def test_features_section_files_to_modify(self):
        groups = _group_findings_by_root_cause([
            _make_finding(file_path="src/auth.ts", line_number=42),
        ])
        section = _build_features_section(groups)
        assert "src/auth.ts" in section
        assert "line 42" in section

    def test_regression_guard_section(self):
        section = _build_regression_guard_section(["AC-1", "AC-2", "AC-3"])
        assert "MUST still pass" in section
        assert "AC-1" in section
        assert "AC-2" in section

    def test_regression_guard_empty(self):
        section = _build_regression_guard_section([])
        assert "No previously passing" in section


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Tests for fix PRD validation."""

    def test_valid_prd(self):
        text = (
            "# Project: Test Application Fix Run\n\n"
            "## Technology Stack\n"
            "| Layer | Tech |\n"
            "|-------|------|\n"
            "| Backend | Node.js Express |\n"
            "| Frontend | React Next.js |\n"
            "| Database | PostgreSQL Prisma |\n\n"
            "## Features\n\n"
            "### F-FIX-001: Some Fix\n"
            "Content here with enough length to pass the minimum character requirement for validation.\n"
        )
        assert _validate_fix_prd(text) is True

    def test_too_short(self):
        assert _validate_fix_prd("short") is False

    def test_no_heading(self):
        text = "No heading here\n" * 20
        text += "node.js express react"
        assert _validate_fix_prd(text) is False

    def test_no_tech_keywords(self):
        text = "# Title\n\n## Features\n\n### F-FIX-001: Foo\nThis is a document about nothing technical at all.\n" * 10
        assert _validate_fix_prd(text) is False

    def test_no_features_section(self):
        text = (
            "# Title\n\n"
            "## Technology Stack\nNode.js React\n" * 10
        )
        assert _validate_fix_prd(text) is False

    def test_no_f_fix_heading(self):
        text = (
            "# Title\n\n"
            "## Features\n\n"
            "Some content with node.js react\n" * 10
        )
        assert _validate_fix_prd(text) is False


# ---------------------------------------------------------------------------
# Full fix PRD generation
# ---------------------------------------------------------------------------


class TestGenerateFixPRD:
    """Integration tests for generate_fix_prd()."""

    def test_generates_valid_prd(self, tmp_path):
        prd_path = tmp_path / "prd.md"
        prd_path.write_text(SAMPLE_PRD, encoding="utf-8")
        codebase = tmp_path / "output"
        codebase.mkdir()

        findings = [
            _make_finding(),
            _make_finding(
                id="F-AC-3", feature="F-002",
                category=FindingCategory.MISSING_FEATURE,
                title="Missing dashboard chart",
                file_path="",
            ),
        ]

        fix_prd = generate_fix_prd(
            original_prd_path=prd_path,
            codebase_path=codebase,
            findings=findings,
            run_number=2,
            previously_passing_acs=["AC-1", "AC-2"],
        )

        assert "Fix Run 2" in fix_prd
        assert "Technology Stack" in fix_prd
        assert "## Features" in fix_prd
        assert "## Regression Guard" in fix_prd
        assert "MUST" in fix_prd
        assert "### F-FIX-" in fix_prd

    def test_parser_compatible(self, tmp_path):
        """The generated fix PRD should be parseable by parse_prd()."""
        prd_path = tmp_path / "prd.md"
        prd_path.write_text(SAMPLE_PRD, encoding="utf-8")
        codebase = tmp_path / "output"
        codebase.mkdir()

        findings = [_make_finding()]

        fix_prd = generate_fix_prd(
            original_prd_path=prd_path,
            codebase_path=codebase,
            findings=findings,
            run_number=2,
        )

        # Parser should not crash
        parsed = parse_prd(fix_prd)
        assert parsed.project_name != ""
        # Tech hints should be extracted
        assert len(parsed.technology_hints) > 0 or "node" in fix_prd.lower()

    def test_file_references_no_code_dump(self, tmp_path):
        """Fix PRD should reference files by path, not dump source code."""
        prd_path = tmp_path / "prd.md"
        prd_path.write_text(SAMPLE_PRD, encoding="utf-8")
        codebase = tmp_path / "output" / "src"
        codebase.mkdir(parents=True)
        (codebase / "auth.ts").write_text(
            "function login() {\n  // TODO\n}\n" * 5,
            encoding="utf-8",
        )

        findings = [_make_finding(file_path="src/auth.ts", line_number=1)]

        fix_prd = generate_fix_prd(
            original_prd_path=prd_path,
            codebase_path=tmp_path / "output",
            findings=findings,
            run_number=2,
        )

        assert "auth.ts" in fix_prd
        # Should NOT contain "CURRENT CODE (broken):" code dump
        assert "CURRENT CODE (broken)" not in fix_prd


# ---------------------------------------------------------------------------
# Phase 2B: Fix PRD format and structure tests
# ---------------------------------------------------------------------------


class TestFixPRDFormat:
    """Tests for fix PRD format requirements from Phase 2B."""

    def _generate(self, tmp_path, findings=None, run_number=2):
        """Helper to generate a fix PRD with default setup."""
        import re as re_mod
        prd_path = tmp_path / "prd.md"
        prd_path.write_text(SAMPLE_PRD, encoding="utf-8")
        codebase = tmp_path / "output"
        codebase.mkdir(exist_ok=True)
        if findings is None:
            findings = [_make_finding()]
        return generate_fix_prd(
            original_prd_path=prd_path,
            codebase_path=codebase,
            findings=findings,
            run_number=run_number,
        )

    def test_fix_prd_uses_feature_format(self, tmp_path):
        """Fix PRD contains ### F-FIX-NNN: headings."""
        import re as re_mod
        result = self._generate(tmp_path)
        assert re_mod.search(r"^### F-FIX-\d+:", result, re_mod.MULTILINE)

    def test_fix_prd_has_features_section(self, tmp_path):
        """Fix PRD contains ## Features section."""
        result = self._generate(tmp_path)
        assert "## Features" in result

    def test_fix_prd_has_acceptance_criteria(self, tmp_path):
        """Fix PRD contains - AC-FIX-NNN items."""
        import re as re_mod
        result = self._generate(tmp_path)
        assert re_mod.search(r"^- AC-FIX-\d+", result, re_mod.MULTILINE)

    def test_fix_prd_under_50kb(self, tmp_path):
        """Fix PRD is under 50,000 characters even with many findings."""
        findings = [
            _make_finding(
                id=f"F-AC-{i}",
                feature=f"F-{i:03d}",
                title=f"Issue {i}: detailed problem description",
                description=f"Finding {i} with a longer description for testing size limits",
            )
            for i in range(100)
        ]
        result = self._generate(tmp_path, findings=findings)
        assert len(result) <= 50_000

    def test_fix_prd_max_20_fix_features(self, tmp_path):
        """Fix PRD has at most 20 ### F-FIX-NNN: sections."""
        import re as re_mod
        findings = [
            _make_finding(
                id=f"F-AC-{i}",
                feature=f"F-{i:03d}",
                title=f"Unique issue {i}",
                description=f"Unique description {i}",
            )
            for i in range(100)
        ]
        result = self._generate(tmp_path, findings=findings)
        feature_count = len(re_mod.findall(r"^### F-FIX-\d+:", result, re_mod.MULTILINE))
        assert feature_count <= 20

    def test_fix_prd_no_source_code_dumps(self, tmp_path):
        """Fix PRD does not contain CURRENT CODE blocks."""
        result = self._generate(tmp_path)
        assert "CURRENT CODE (broken)" not in result
        assert "CURRENT CODE" not in result

    def test_fix_prd_snake_case_findings_grouped(self, tmp_path):
        """Multiple snake_case wiring findings become one fix feature, not N."""
        import re as re_mod
        findings = [
            _make_finding(
                id=f"F-AC-{i}",
                category=FindingCategory.CODE_FIX,
                title=f"snake_case in request body {i}",
                description=f"booking sends snake_case: casing mismatch {i}",
            )
            for i in range(5)
        ]
        result = self._generate(tmp_path, findings=findings)
        feature_count = len(re_mod.findall(r"^### F-FIX-\d+:", result, re_mod.MULTILINE))
        assert feature_count < 5  # Grouped, not 1:1

    def test_fix_prd_parseable_by_validate(self, tmp_path):
        """_validate_fix_prd() returns True for the generated fix PRD."""
        result = self._generate(tmp_path)
        assert _validate_fix_prd(result) is True


class TestFixPRDValidationDetailed:
    """Tests for _validate_fix_prd_structure in coordinated_builder."""

    def test_validate_rejects_no_features(self):
        """_validate_fix_prd_structure() returns False for PRD with no features."""
        from agent_team_v15.coordinated_builder import _validate_fix_prd_structure
        bad_prd = "# Fix PRD\n\nSome text without any feature headings.\n\n- AC-001: Something\n" * 5
        valid, msg = _validate_fix_prd_structure(bad_prd)
        assert not valid
        assert "feature" in msg.lower()

    def test_validate_rejects_no_acs(self):
        """_validate_fix_prd_structure() returns False for PRD with no AC items."""
        from agent_team_v15.coordinated_builder import _validate_fix_prd_structure
        bad_prd = (
            "# Fix PRD\n\n## Features\n\n"
            "### F-FIX-001: Something\nDescription only, no ACs.\n" * 5
        )
        valid, msg = _validate_fix_prd_structure(bad_prd)
        assert not valid

    def test_validate_accepts_valid_format(self):
        """_validate_fix_prd_structure() returns True for correctly formatted fix PRD."""
        from agent_team_v15.coordinated_builder import _validate_fix_prd_structure
        good_prd = """# Project — Fix Run 1

## Features

### F-FIX-001: Fix casing
Fix snake_case to camelCase.

#### Acceptance Criteria
- AC-FIX-001: booking sends vehicleId not vehicle_id
- AC-FIX-002: nps sends npsScore not nps_score
""" + "\nMore content to meet the 200 char minimum requirement for validation checks.\n" * 3
        valid, msg = _validate_fix_prd_structure(good_prd)
        assert valid, f"Valid PRD rejected: {msg}"

    def test_validate_rejects_oversized(self):
        """_validate_fix_prd_structure() rejects PRDs over 50KB."""
        from agent_team_v15.coordinated_builder import _validate_fix_prd_structure
        big_prd = (
            "# Title\n\n### F-FIX-001: Fix\n- AC-FIX-001: criterion\n"
            + "x" * 51_000
        )
        valid, msg = _validate_fix_prd_structure(big_prd)
        assert not valid
        assert "large" in msg.lower() or "50" in msg
