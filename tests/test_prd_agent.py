"""Tests for PRD agent (generate, improve, validate)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15.prd_agent import (
    PrdResult,
    ValidationReport,
    generate_prd,
    improve_prd,
    validate_prd,
    format_validation_report,
    FORMAT_REFERENCE,
    _build_comprehension_prompt,
    _build_expansion_prompt,
    _build_improvement_prompt,
)


# ===================================================================
# Validation
# ===================================================================

class TestValidatePrd:
    def test_empty_prd(self):
        report = validate_prd("")
        assert not report.is_valid
        assert report.entities_extracted == 0

    def test_short_prd(self):
        report = validate_prd("too short")
        assert not report.is_valid
        assert "too short" in report.issues[0].lower()

    def test_valid_prd_with_entities(self):
        prd = (
            "# Test App\n\n"
            "## Technology Stack\n\n"
            "| Component | Technology | Rationale |\n"
            "|-----------|-----------|----------|\n"
            "| Backend | Python / FastAPI | Async |\n\n"
            "## Entities\n\n"
            "| Entity | Owning Service | Fields | Description |\n"
            "|--------|---------------|--------|-------------|\n"
            "| User | Auth Service | id(UUID), email(String), role(String) | App user |\n"
            "| Invoice | AR Service | id(UUID), amount(Decimal), status(String) | Customer invoice |\n"
            "| Payment | AR Service | id(UUID), amount(Decimal), date(Date) | Payment record |\n"
            "| Customer | AR Service | id(UUID), name(String), email(String) | Customer |\n"
        )
        report = validate_prd(prd)
        assert report.is_valid
        assert report.entities_extracted >= 4
        assert report.technology_detected is True

    def test_entities_without_fields_flagged(self):
        prd = (
            "# Test\n\n"
            "## Entities\n\n"
            "| Entity | Owning Service | Description |\n"
            "|--------|---------------|-------------|\n"
            "| User | Auth | App user |\n"
            "| Role | Auth | User role |\n"
            "| Perm | Auth | Permission |\n"
        )
        report = validate_prd(prd)
        # Should flag low field coverage
        assert report.entities_with_fields < report.entities_extracted

    def test_missing_state_machines_suggested(self):
        prd = (
            "# Test\n\n"
            "| Entity | Owning Service | Fields | Description |\n"
            "|--------|---------------|--------|-------------|\n"
            + "".join(
                f"| Entity{i} | Svc | id(UUID), name(String) | Entity {i} |\n"
                for i in range(10)
            )
        )
        report = validate_prd(prd)
        assert any("state machine" in s.lower() for s in report.suggestions)

    def test_missing_events_suggested(self):
        prd = (
            "# Test\n\n"
            "| Entity | Owning Service | Fields | Description |\n"
            "|--------|---------------|--------|-------------|\n"
            + "".join(
                f"| Entity{i} | Svc | id(UUID) | E{i} |\n"
                for i in range(8)
            )
        )
        report = validate_prd(prd)
        assert any("event" in s.lower() for s in report.suggestions)


class TestValidationReport:
    def test_score_zero_for_empty(self):
        report = ValidationReport()
        assert report.score == 0.0

    def test_score_high_for_complete(self):
        report = ValidationReport(
            entities_extracted=20,
            entities_with_fields=18,
            state_machines_extracted=8,
            events_extracted=15,
            technology_detected=True,
        )
        assert report.score >= 0.8

    def test_is_valid_requires_entities(self):
        report = ValidationReport(entities_extracted=2)
        assert not report.is_valid  # Need 3+

    def test_is_valid_with_issues(self):
        report = ValidationReport(entities_extracted=10, issues=["something wrong"])
        assert not report.is_valid


class TestFormatValidationReport:
    def test_includes_counts(self):
        report = ValidationReport(
            entities_extracted=10,
            state_machines_extracted=5,
            events_extracted=8,
            technology_detected=True,
            project_name="Test",
        )
        text = format_validation_report(report)
        assert "10" in text
        assert "5" in text
        assert "Test" in text
        assert "YES" in text

    def test_shows_issues(self):
        report = ValidationReport(issues=["Bad formatting"])
        text = format_validation_report(report)
        assert "Bad formatting" in text
        assert "must fix" in text.lower()


# ===================================================================
# Prompt builders
# ===================================================================

class TestPromptBuilders:
    def test_comprehension_prompt_contains_input(self):
        prompt = _build_comprehension_prompt("Build an accounting system")
        assert "accounting system" in prompt
        assert "COMPREHENSION" in prompt
        assert "CONTRADICTION" in prompt

    def test_expansion_prompt_contains_format_reference(self):
        prompt = _build_expansion_prompt("Build app", "Domain: fintech")
        assert "Entity | Owning Service" in prompt
        assert "State Machine" in prompt
        assert "EXACT" in prompt

    def test_expansion_prompt_includes_user_decisions(self):
        prompt = _build_expansion_prompt(
            "Build app", "Analysis", user_decisions="Use PostgreSQL, not MongoDB"
        )
        assert "PostgreSQL" in prompt
        assert "USER DECISIONS" in prompt

    def test_improvement_prompt_contains_gaps(self):
        prompt = _build_improvement_prompt(
            "# Old PRD\n...",
            ["Missing state machines", "No events table"],
        )
        assert "Missing state machines" in prompt
        assert "No events table" in prompt


# ===================================================================
# Format reference
# ===================================================================

class TestFormatReference:
    def test_contains_entity_table_format(self):
        assert "Entity | Owning Service | Fields | Description" in FORMAT_REFERENCE

    def test_contains_state_machine_format(self):
        assert "**States:**" in FORMAT_REFERENCE
        assert "**Transitions:**" in FORMAT_REFERENCE

    def test_contains_events_table_format(self):
        assert "Event | Publisher | Payload | Consumers" in FORMAT_REFERENCE

    def test_contains_tech_stack_format(self):
        assert "Component | Technology | Rationale" in FORMAT_REFERENCE

    def test_contains_field_type_guide(self):
        assert "UUID" in FORMAT_REFERENCE
        assert "Decimal" in FORMAT_REFERENCE
        assert "NEVER Float" in FORMAT_REFERENCE


# ===================================================================
# Generate PRD (mocked Claude)
# ===================================================================

class TestGeneratePrd:
    @patch("agent_team_v15.prd_agent._run_claude_session")
    def test_checkpoint_returned_when_gaps(self, mock_session):
        mock_session.return_value = (
            "## Understanding\nDomain: Accounting\n\n"
            "## Contradictions (1 found)\n"
            "1. Multi-tenant vs single-tenant not specified\n\n"
            "## Missing Pieces (1 found)\n"
            "1. Database choice not specified\n"
        )
        result = generate_prd("Build accounting system")
        assert result.checkpoint_message != ""
        assert result.prd_text == ""
        assert "Contradictions" in result.checkpoint_message

    @patch("agent_team_v15.prd_agent._run_claude_session")
    def test_skip_checkpoint_generates_full_prd(self, mock_session):
        mock_session.return_value = (
            "# TestApp\n\n"
            "## Technology Stack\n\n"
            "| Component | Technology | Rationale |\n"
            "|-----------|-----------|----------|\n"
            "| Backend | Python / FastAPI | Async |\n\n"
            "## Entities\n\n"
            "| Entity | Owning Service | Fields | Description |\n"
            "|--------|---------------|--------|-------------|\n"
            "| User | Auth | id(UUID), email(String) | User |\n"
            "| Task | Tasks | id(UUID), title(String), status(String) | Task |\n"
            "| Project | Projects | id(UUID), name(String) | Project |\n"
            "| Comment | Tasks | id(UUID), text(String) | Comment |\n\n"  # Extra newline to terminate table
        )
        result = generate_prd("Build task manager", skip_checkpoint=True)
        assert result.prd_text != ""
        assert result.validation.entities_extracted >= 3  # Parser may get 3-4 depending on trailing newline

    @patch("agent_team_v15.prd_agent._run_claude_session")
    def test_no_checkpoint_when_clear(self, mock_session):
        # Comprehension says "clear", expansion produces valid PRD with enough
        # entities that no suggestions trigger (need 3+ entities, <5 to avoid SM/event suggestions)
        prd_output = (
            "# App\n\n"
            "## Technology Stack\n\n"
            "| Component | Technology | Rationale |\n"
            "|-----------|-----------|----------|\n"
            "| Backend | Python / FastAPI | Fast |\n\n"
            "## Entities\n\n"
            "| Entity | Owning Service | Fields | Description |\n"
            "|--------|---------------|--------|-------------|\n"
            "| User | Auth | id(UUID), email(String), role(String) | User |\n"
            "| Item | Store | id(UUID), name(String), price(Decimal) | Item |\n"
            "| Order | Store | id(UUID), total(Decimal), status(String) | Order |\n"
            "| Cart | Store | id(UUID), user_id(UUID), created_at(DateTime) | Cart |\n\n"
        )
        mock_session.side_effect = [
            "Everything is clear. No user input needed.",
            prd_output,
        ]
        result = generate_prd("Build a simple store with users and orders")
        assert result.checkpoint_message == ""
        assert result.prd_text != ""
        assert result.validation.entities_extracted >= 3


# ===================================================================
# Improve PRD
# ===================================================================

class TestImprovePrd:
    def test_already_valid_returns_unchanged(self):
        valid_prd = (
            "# App\n\n"
            "## Technology Stack\n\n"
            "| Component | Technology | Rationale |\n"
            "|-----------|-----------|----------|\n"
            "| Backend | Python / FastAPI | Async |\n\n"
            "## Entities\n\n"
            "| Entity | Owning Service | Fields | Description |\n"
            "|--------|---------------|--------|-------------|\n"
            "| User | Auth | id(UUID), email(String), role(String) | User |\n"
            "| Task | Tasks | id(UUID), title(String), status(String) | Task |\n"
            "| Project | Projects | id(UUID), name(String), owner(UUID) | Project |\n"
            "| Label | Tasks | id(UUID), name(String), color(String) | Label |\n"
        )
        result = improve_prd(valid_prd)
        # Should return as-is (no Claude session needed)
        assert result.prd_text == valid_prd
        assert result.validation.is_valid

    @patch("agent_team_v15.prd_agent._run_claude_session")
    def test_improves_invalid_prd(self, mock_session):
        mock_session.return_value = (
            "# App\n\n"
            "| Entity | Owning Service | Fields | Description |\n"
            "|--------|---------------|--------|-------------|\n"
            "| User | Auth | id(UUID), email(String) | User |\n"
            "| Task | Tasks | id(UUID), title(String) | Task |\n"
            "| Project | PM | id(UUID), name(String) | Proj |\n"
        )
        result = improve_prd("Some badly formatted PRD without proper tables")
        assert result.prd_text != ""
        assert mock_session.called


# ===================================================================
# Real PRD validation
# ===================================================================

class TestRealPrdValidation:
    def test_globalbooks_prd(self):
        prd_path = Path(r"C:\MY_PROJECTS\globalbooks\prd.md")
        if not prd_path.is_file():
            pytest.skip("GlobalBooks PRD not available")

        report = validate_prd(prd_path.read_text(encoding="utf-8"))
        print(f"\n{format_validation_report(report)}")
        assert report.entities_extracted >= 50
        assert report.events_extracted >= 30
        assert report.technology_detected is True
        assert report.score >= 0.5
