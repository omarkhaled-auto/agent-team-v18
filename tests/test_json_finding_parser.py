"""Tests for _parse_structured_findings and _extract_score from audit_agent.py."""

from __future__ import annotations

from agent_team_v15.audit_agent import _parse_structured_findings, _extract_score


def test_valid_findings_fence_parsed():
    response = '''Analysis complete.
```findings
{"findings": [
  {"id": "F-001", "severity": "CRITICAL", "title": "Missing auth", "description": "auth.ts:42", "category": "security", "file_path": "auth.ts", "line_number": 42, "expected_behavior": "Token validated", "current_behavior": "No validation", "fix_action": "Add guard"},
  {"id": "F-002", "severity": "HIGH", "title": "Missing test", "description": "test.ts:10", "category": "prd_compliance", "file_path": "test.ts", "line_number": 10, "expected_behavior": "Tests exist", "current_behavior": "No tests", "fix_action": "Add tests"}
], "total_score": 750}
```'''
    findings = _parse_structured_findings(response)
    assert len(findings) == 2
    assert findings[0].id == "F-001"
    assert findings[1].id == "F-002"


def test_malformed_json_falls_back_to_prose_parser():
    response = "```findings\n{broken json\n```\n[CRITICAL] Some finding title that is long enough to matter"
    findings = _parse_structured_findings(response)
    assert isinstance(findings, list)


def test_no_findings_fence_falls_back():
    response = "[CRITICAL] Some finding without JSON fence that is long enough to parse"
    findings = _parse_structured_findings(response)
    assert isinstance(findings, list)


def test_extract_score_from_json():
    response = '```findings\n{"findings": [], "total_score": 802}\n```'
    assert _extract_score(response) == 802


def test_extract_score_regex_fallback():
    response = "COMPREHENSIVE_SCORE: 750\nSome text"
    assert _extract_score(response) == 750


def test_json_score_wins_over_regex():
    response = '```findings\n{"findings": [], "total_score": 802}\n```\nCOMPREHENSIVE_SCORE: 600'
    assert _extract_score(response) == 802


def test_no_score_returns_zero():
    response = "No score here at all"
    assert _extract_score(response) == 0


def test_extract_score_float():
    response = "COMPREHENSIVE_SCORE: 750.5\nSome text"
    assert _extract_score(response) == 750


def test_empty_findings_list_parsed():
    response = '```findings\n{"findings": [], "total_score": 1000}\n```'
    findings = _parse_structured_findings(response)
    # Falls back to prose parser because findings list is empty
    assert isinstance(findings, list)


def test_structured_finding_fields():
    response = '''```findings
{"findings": [
  {"id": "WR-001", "severity": "HIGH", "title": "Missing endpoint handler", "description": "No handler for /api/v1/invoices", "category": "wiring", "file_path": "routes/invoices.ts", "line_number": 15, "expected_behavior": "Endpoint returns data", "current_behavior": "404 error", "fix_action": "Add route handler"}
], "total_score": 500}
```'''
    findings = _parse_structured_findings(response)
    assert len(findings) == 1
    f = findings[0]
    assert f.id == "WR-001"
    assert f.file_path == "routes/invoices.ts"
    assert f.line_number == 15
