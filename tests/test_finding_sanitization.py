"""Tests for _clean_finding_text from audit_agent.py."""

from __future__ import annotations

from agent_team_v15.audit_agent import _clean_finding_text


def test_pipe_delimiters_removed():
    assert _clean_finding_text("| refreshAccessToken uses raw fetch |") == "refreshAccessToken uses raw fetch"


def test_bold_markers_removed():
    result = _clean_finding_text("**Category**: security issue detected")
    assert "**" not in result
    assert "Category" in result


def test_section_header_returns_empty():
    assert _clean_finding_text("### Findings") == ""


def test_ends_with_colon_returns_empty():
    assert _clean_finding_text("findings and check more areas:") == ""


def test_normal_text_unchanged():
    text = "Normal finding text about a real authentication issue"
    assert _clean_finding_text(text) == text


def test_multiline_collapsed():
    result = _clean_finding_text("  multi\n  line\n  text  ")
    assert result == "multi line text"


def test_empty_string_returns_empty():
    assert _clean_finding_text("") == ""


def test_none_returns_empty():
    assert _clean_finding_text(None) == ""


def test_bullet_prefix_removed():
    result = _clean_finding_text("- This is a longer finding item that should pass length check")
    assert not result.startswith("- ")
    assert "finding item" in result


def test_short_text_returns_empty():
    assert _clean_finding_text("short") == ""


def test_only_whitespace_returns_empty():
    assert _clean_finding_text("     ") == ""


def test_heading_with_content_cleaned():
    # Heading prefix is stripped, but remaining text too short => ""
    assert _clean_finding_text("## Ab") == ""


def test_multiple_bold_markers_stripped():
    result = _clean_finding_text("**Bold one** and **bold two** in finding text")
    assert "**" not in result
    assert "Bold one" in result
    assert "bold two" in result
