"""Tests for _assemble_gate_context budget management from audit_agent.py."""

from __future__ import annotations

from agent_team_v15.audit_agent import _assemble_gate_context, GATE_PROMPT_BUDGET


def test_small_context_fits_untruncated():
    result = _assemble_gate_context(
        base_prompt="base",
        findings_summary="findings summary text",
        codebase_summary="codebase summary text",
        prd_text="- AC-001: Some criterion\n- AC-002: Another criterion",
        integration_output="route table data",
        schema_output="schema output data",
    )
    assert "findings summary text" in result
    assert "AC-001" in result
    assert "route table data" in result


def test_total_never_exceeds_budget():
    big = "x" * 20_000
    result = _assemble_gate_context(
        base_prompt="base prompt",
        findings_summary=big,
        codebase_summary=big,
        prd_text=big,
        integration_output=big,
        schema_output=big,
    )
    # The budget covers content characters; section headers (e.g., "\n\n## Prior Findings\n")
    # are added on top. Allow ~200 chars of header overhead.
    header_overhead = 200
    assert len(result) <= GATE_PROMPT_BUDGET + header_overhead


def test_priority_order_findings_present():
    """Findings get a large share of budget even when all fields are large."""
    base = "b" * 100
    findings = "f" * 30_000
    result = _assemble_gate_context(
        base_prompt=base,
        findings_summary=findings,
        codebase_summary="codebase",
        prd_text="",
        integration_output="",
        schema_output="schema data that may be cut",
    )
    # Findings should get allocated space
    assert "f" * 100 in result


def test_ac_lines_extracted_from_prd():
    prd = "# Feature 1\n- AC-001: criterion one\n- AC-002: criterion two\nNon-AC line\n"
    result = _assemble_gate_context("base", "", "", prd_text=prd)
    assert "AC-001" in result
    assert "AC-002" in result
    # Non-AC lines are stripped by _extract_ac_lines
    assert "Non-AC line" not in result


def test_empty_fields_produce_base_only():
    result = _assemble_gate_context(
        base_prompt="base prompt only",
        findings_summary="",
        codebase_summary="",
    )
    assert result == "base prompt only"


def test_base_prompt_always_included():
    base = "IMPORTANT BASE PROMPT"
    big = "x" * 50_000
    result = _assemble_gate_context(
        base_prompt=base,
        findings_summary=big,
        codebase_summary=big,
        prd_text=big,
    )
    assert result.startswith(base)


def test_section_headers_present():
    result = _assemble_gate_context(
        base_prompt="base",
        findings_summary="some findings",
        codebase_summary="some codebase info",
        prd_text="- AC-001: criterion",
        integration_output="route data",
        schema_output="schema info",
    )
    assert "## Prior Findings" in result
    assert "## Acceptance Criteria from PRD" in result
    assert "## Frontend-Backend Route Mapping" in result
    assert "## Schema Validation Results" in result
    assert "## Codebase Structure" in result
