"""Tests for AC batch parsing helpers from audit_agent.py."""

from __future__ import annotations

import json

from agent_team_v15.audit_agent import (
    AcceptanceCriterion,
    CheckResult,
    _parse_batch_ac_results,
    _parse_batch_ac_findings,
)


# ---------------------------------------------------------------------------
# _parse_batch_ac_results
# ---------------------------------------------------------------------------


def test_batch_ac_results_from_valid_json():
    batch = [
        AcceptanceCriterion(id="AC-1", feature="F-001", text="Test 1"),
        AcceptanceCriterion(id="AC-2", feature="F-001", text="Test 2"),
    ]
    response = '''```findings
[
  {"ac_id": "AC-1", "status": "PASS", "evidence": "Found in auth.ts:42"},
  {"ac_id": "AC-2", "status": "FAIL", "evidence": "Not implemented"}
]
```'''
    results = _parse_batch_ac_results(response, batch)
    result_map = {r.ac_id: r for r in results}
    assert result_map["AC-1"].verdict == "PASS"
    assert result_map["AC-2"].verdict == "FAIL"


def test_batch_ac_results_missing_acs_get_partial():
    batch = [
        AcceptanceCriterion(id="AC-1", feature="F-001", text="Test 1"),
        AcceptanceCriterion(id="AC-2", feature="F-001", text="Test 2"),
        AcceptanceCriterion(id="AC-3", feature="F-001", text="Test 3"),
    ]
    response = '''```findings
[
  {"ac_id": "AC-1", "status": "PASS", "evidence": "Found"}
]
```'''
    results = _parse_batch_ac_results(response, batch)
    result_map = {r.ac_id: r for r in results}
    assert result_map["AC-1"].verdict == "PASS"
    assert result_map["AC-2"].verdict == "PARTIAL"
    assert result_map["AC-3"].verdict == "PARTIAL"


def test_batch_ac_results_invalid_status_defaults_partial():
    batch = [AcceptanceCriterion(id="AC-1", feature="F-001", text="Test 1")]
    response = '''```findings
[{"ac_id": "AC-1", "status": "MAYBE", "evidence": "unclear"}]
```'''
    results = _parse_batch_ac_results(response, batch)
    assert results[0].verdict == "PARTIAL"


def test_batch_ac_results_no_json_fence():
    batch = [
        AcceptanceCriterion(id="AC-1", feature="F-001", text="Test 1"),
    ]
    response = "No JSON content here, just prose."
    results = _parse_batch_ac_results(response, batch)
    # Every AC should get a PARTIAL default
    assert len(results) >= 1
    assert results[0].verdict == "PARTIAL"


def test_batch_ac_results_empty_batch():
    results = _parse_batch_ac_results("some response", [])
    assert results == []


def test_batch_ac_results_nested_findings_key():
    """JSON is a dict with 'findings' key instead of a top-level list."""
    batch = [AcceptanceCriterion(id="AC-1", feature="F-001", text="Test 1")]
    response = '''```findings
{"findings": [{"ac_id": "AC-1", "status": "PASS", "evidence": "ok"}]}
```'''
    results = _parse_batch_ac_results(response, batch)
    result_map = {r.ac_id: r for r in results}
    assert result_map["AC-1"].verdict == "PASS"


# ---------------------------------------------------------------------------
# _parse_batch_ac_findings
# ---------------------------------------------------------------------------


def test_batch_ac_findings_from_valid_json():
    response = '''```findings
[
  {"ac_id": "AC-1", "status": "FAIL", "description": "Missing auth guard", "evidence": "No guard on route"},
  {"ac_id": "AC-2", "status": "PASS", "description": "Correct", "evidence": "Found"}
]
```'''
    findings = _parse_batch_ac_findings(response)
    assert len(findings) == 2
    fail_finding = [f for f in findings if f.id == "AC-1"][0]
    assert fail_finding.severity.value == "high"


def test_batch_ac_findings_pass_gets_low_severity():
    response = '''```findings
[{"ac_id": "AC-5", "status": "PASS", "evidence": "All good"}]
```'''
    findings = _parse_batch_ac_findings(response)
    assert len(findings) == 1
    assert findings[0].severity.value == "low"


def test_batch_ac_findings_no_json_falls_back():
    response = "[HIGH] Some important finding that is long enough to be detected"
    findings = _parse_batch_ac_findings(response)
    assert isinstance(findings, list)


def test_batch_ac_findings_malformed_json():
    response = "```findings\n{broken\n```\n[CRITICAL] Important failure message that should be parsed"
    findings = _parse_batch_ac_findings(response)
    assert isinstance(findings, list)
