"""Tests for _build_ac_from_finding from fix_prd_agent.py."""

from __future__ import annotations

from agent_team_v15.audit_agent import Finding, FindingCategory, Severity
from agent_team_v15.fix_prd_agent import _build_ac_from_finding


def _make_finding(**overrides) -> Finding:
    """Create a Finding with default values, overridden by kwargs."""
    defaults = dict(
        id="F-001",
        feature="F-001",
        acceptance_criterion="",
        severity=Severity.HIGH,
        category=FindingCategory.CODE_FIX,
        title="Default title for this finding item",
        description="Default description text",
        prd_reference="F-001",
        current_behavior="",
        expected_behavior="",
        file_path="",
        line_number=0,
    )
    defaults.update(overrides)
    return Finding(**defaults)


def test_good_acceptance_criterion_returned():
    f = _make_finding(
        acceptance_criterion="Session must expire after 30 days of inactivity"
    )
    result = _build_ac_from_finding(f)
    assert "Session must expire" in result


def test_short_ac_falls_through_to_synthesis():
    f = _make_finding(
        acceptance_criterion="ok",
        expected_behavior="Token refreshes automatically",
        current_behavior="Token expires silently",
    )
    result = _build_ac_from_finding(f)
    # Should synthesize from expected/current behavior since AC is too short
    assert "Token refreshes" in result or "Expected" in result


def test_synthesizes_from_file_path_and_behaviors():
    f = _make_finding(
        acceptance_criterion="",
        file_path="auth.service.ts",
        expected_behavior="JWT validates correctly on each request",
        current_behavior="JWT fails on token refresh",
    )
    result = _build_ac_from_finding(f)
    assert "auth.service.ts" in result


def test_garbled_title_returns_cleaned():
    f = _make_finding(
        acceptance_criterion="",
        file_path="",
        expected_behavior="",
        current_behavior="",
        title="| table cell with markdown artifacts here |",
    )
    result = _build_ac_from_finding(f)
    assert "|" not in result


def test_all_empty_fields_returns_default():
    f = _make_finding(
        acceptance_criterion="",
        file_path="",
        expected_behavior="",
        current_behavior="",
        title="",
        description="",
    )
    assert _build_ac_from_finding(f) == "Fix identified issue"


def test_long_ac_with_markdown_gets_cleaned():
    f = _make_finding(
        acceptance_criterion="**The session** must handle | timeout | properly for all users"
    )
    result = _build_ac_from_finding(f)
    assert "**" not in result
    assert "session" in result.lower()


def test_synthesis_joins_parts_with_period():
    f = _make_finding(
        file_path="controllers/booking.controller.ts",
        expected_behavior="Booking returns confirmation code properly",
        current_behavior="Booking returns null and crashes",
    )
    result = _build_ac_from_finding(f)
    assert "booking.controller.ts" in result
    assert ". " in result  # Parts joined with period-space
