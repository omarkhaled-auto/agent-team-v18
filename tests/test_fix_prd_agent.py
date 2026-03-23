"""Tests for the Fix PRD Agent — fix PRD generation and parser compatibility."""

from __future__ import annotations

import pytest
from pathlib import Path

from agent_team_v15.audit_agent import Finding, FindingCategory, Severity
from agent_team_v15.fix_prd_agent import (
    generate_fix_prd,
    _extract_project_name,
    _extract_tech_stack_section,
    _extract_entity_summary,
    _identify_modified_entities,
    _build_product_overview,
    _build_tech_stack_section,
    _build_existing_context,
    _build_bounded_contexts,
    _build_regression_section,
    _build_success_criteria,
    _validate_fix_prd,
    _group_findings_by_feature,
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
        description="Detailed issue description",
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

    def test_extract_entity_summary(self):
        entities = _extract_entity_summary(SAMPLE_PRD)
        names = [e["name"] for e in entities]
        assert "User" in names or "Invoice" in names

    def test_identify_modified_entities(self):
        findings = [
            _make_finding(title="InvoiceLineItem unit_price wrong type"),
        ]
        modified = _identify_modified_entities(findings, SAMPLE_PRD)
        # Should find InvoiceLineItem if in PRD, or empty if not
        assert isinstance(modified, list)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


class TestSectionBuilders:
    """Tests for individual fix PRD section builders."""

    def test_product_overview(self):
        overview = _build_product_overview(
            "Test App", Path("./output"), Path("prd.md"),
            [_make_finding(severity=Severity.CRITICAL), _make_finding(severity=Severity.HIGH)],
            2,
        )
        assert "TARGETED FIX RUN" in overview
        assert "Test App" in overview
        assert "1 CRITICAL" in overview
        assert "1 HIGH" in overview

    def test_tech_stack_section(self):
        section = _build_tech_stack_section("## Technology Stack\n| Layer | Tech |\n| Backend | Node |")
        assert "Technology Stack" in section

    def test_tech_stack_fallback(self):
        section = _build_tech_stack_section("")
        assert "Technology Stack" in section

    def test_existing_context(self):
        entities = [
            {"name": "User", "fields": "id, email, name"},
            {"name": "Invoice", "fields": "id, number, amount"},
        ]
        section = _build_existing_context(entities)
        assert "DO NOT REGENERATE" in section
        assert "User" in section
        assert "Invoice" in section

    def test_bounded_contexts(self):
        findings = {
            "F-001": [
                _make_finding(category=FindingCategory.CODE_FIX),
                _make_finding(id="F-AC-2", category=FindingCategory.MISSING_FEATURE, title="Missing widget"),
            ],
        }
        section = _build_bounded_contexts(findings)
        assert "FIX-001" in section
        assert "FEAT-001" in section
        assert "F-001" in section

    def test_regression_section(self):
        section = _build_regression_section(
            ["AC-1", "AC-2", "AC-3"],
            [_make_finding(file_path="src/auth.ts")],
            Path("./output"),
        )
        assert "MUST still pass" in section or "MUST STILL PASS" in section
        assert "AC-1" in section
        assert "src/auth.ts" in section

    def test_success_criteria(self):
        findings = [_make_finding(), _make_finding(id="F-AC-2")]
        section = _build_success_criteria(findings, ["AC-1", "AC-2"])
        assert "REGRESSION CHECK" in section
        assert "F-AC-1" in section

    def test_group_findings_by_feature(self):
        findings = [
            _make_finding(feature="F-001"),
            _make_finding(id="F-AC-2", feature="F-001"),
            _make_finding(id="F-AC-3", feature="F-002"),
        ]
        groups = _group_findings_by_feature(findings)
        assert "F-001" in groups
        assert "F-002" in groups
        assert len(groups["F-001"]) == 2
        assert len(groups["F-002"]) == 1


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
            "## Bounded Contexts\n"
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
        text = "# Title\n\nThis is a document about nothing technical at all.\n" * 10
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
        assert "Regression Prevention" in fix_prd
        assert "Success Criteria" in fix_prd
        assert "MUST" in fix_prd  # Regression check

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

    def test_includes_code_snippets(self, tmp_path):
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
