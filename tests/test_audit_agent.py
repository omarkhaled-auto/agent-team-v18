"""Tests for the Audit Agent — AC extraction, static checks, findings."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_team_v15.audit_agent import (
    AcceptanceCriterion,
    AuditReport,
    CheckResult,
    CheckType,
    Finding,
    FindingCategory,
    Severity,
    extract_acceptance_criteria,
    run_audit,
    _categorize_check_type,
    _extract_search_terms,
    _find_block_start,
    _find_block_end,
    _merge_ranges,
    _results_to_findings,
    _parse_claude_check_response,
    _grep_check,
    _run_static_check,
    _discover_source_files,
    _build_codebase_summary,
)


# ---------------------------------------------------------------------------
# Sample PRD text for testing
# ---------------------------------------------------------------------------

SAMPLE_PRD = """# Project: EVS Customer Portal

## Product Overview
A customer portal for EVS.

## Technology Stack
| Layer | Technology |
|-------|-----------|
| Backend | Node.js + Express |
| Database | PostgreSQL + Prisma |
| Frontend | React + Next.js |
| Auth | JWT + bcrypt |

## Feature F-001: User Signup

### Acceptance Criteria
- [ ] AC-1: GIVEN a new email not in the portal DB, WHEN the customer completes signup with valid email and phone, THEN the account is created and a magic link is sent.
- [ ] AC-2: GIVEN the signup phone number matches an existing Odoo res.partner, WHEN signup completes, THEN the portal account is linked to the Odoo record.
- [ ] AC-3: GIVEN an email already registered, WHEN signup is attempted, THEN the system returns an error message indicating the email is taken.

## Feature F-002: Authentication

### Acceptance Criteria
- [ ] AC-4: GIVEN a valid magic link, WHEN the user clicks it within 15 minutes, THEN they are logged in with a JWT in an httpOnly cookie.
- [ ] AC-5: GIVEN an expired magic link, WHEN the user clicks it, THEN they see an error and can request a new one.
- [ ] AC-6: GIVEN page load time, WHEN the dashboard loads, THEN it should complete in under 2 seconds.

## Feature F-003: Dashboard

### Acceptance Criteria
- [ ] AC-7: GIVEN a logged-in user, WHEN they visit the dashboard, THEN they see their account summary and recent invoices.
**AC-8:** GIVEN invoice data from Odoo, WHEN displayed on the dashboard, THEN amounts match the Odoo source exactly.
"""

SAMPLE_PRD_ALT_FORMAT = """# Test App

## Acceptance Criteria
AC 1: System must validate email format on signup
AC 2: System must hash passwords with bcrypt
AC 3: Dashboard loads in under 3 seconds

## Features
### Feature F-001
Acceptance Criterion 1: User can create an account
Acceptance Criterion 2: User receives confirmation email
"""


# ---------------------------------------------------------------------------
# AC Extraction
# ---------------------------------------------------------------------------


class TestExtractAcceptanceCriteria:
    """Tests for extract_acceptance_criteria()."""

    def test_extracts_checkbox_format(self):
        acs = extract_acceptance_criteria(SAMPLE_PRD)
        ids = [ac.id for ac in acs]
        assert "AC-1" in ids
        assert "AC-2" in ids
        assert "AC-3" in ids
        assert "AC-4" in ids
        assert "AC-5" in ids

    def test_extracts_bold_format(self):
        acs = extract_acceptance_criteria(SAMPLE_PRD)
        ids = [ac.id for ac in acs]
        assert "AC-8" in ids

    def test_associates_features(self):
        acs = extract_acceptance_criteria(SAMPLE_PRD)
        ac_map = {ac.id: ac for ac in acs}
        assert ac_map["AC-1"].feature == "F-001"
        assert ac_map["AC-4"].feature == "F-002"
        assert ac_map["AC-7"].feature == "F-003"

    def test_categorizes_check_types(self):
        acs = extract_acceptance_criteria(SAMPLE_PRD)
        ac_map = {ac.id: ac for ac in acs}
        # AC-4 mentions httpOnly → STATIC
        assert ac_map["AC-4"].check_type == CheckType.STATIC
        # AC-6 mentions seconds → RUNTIME
        assert ac_map["AC-6"].check_type == CheckType.RUNTIME
        # AC-2 mentions Odoo → EXTERNAL
        assert ac_map["AC-2"].check_type == CheckType.EXTERNAL
        # AC-1 is behavioral (no static/runtime/external keywords)
        assert ac_map["AC-1"].check_type == CheckType.BEHAVIORAL

    def test_empty_input(self):
        assert extract_acceptance_criteria("") == []
        assert extract_acceptance_criteria("too short") == []

    def test_no_duplicates(self):
        acs = extract_acceptance_criteria(SAMPLE_PRD)
        ids = [ac.id for ac in acs]
        assert len(ids) == len(set(ids))

    def test_sorted_by_ac_number(self):
        acs = extract_acceptance_criteria(SAMPLE_PRD)
        numbers = [int(ac.id.split("-")[1]) for ac in acs]
        assert numbers == sorted(numbers)

    def test_alternative_format_plain_text(self):
        acs = extract_acceptance_criteria(SAMPLE_PRD_ALT_FORMAT)
        # Should find at least some ACs
        assert len(acs) >= 2

    def test_section_context_populated(self):
        acs = extract_acceptance_criteria(SAMPLE_PRD)
        for ac in acs:
            # Each AC should have some section context
            assert isinstance(ac.section_context, str)


# ---------------------------------------------------------------------------
# Check type categorization
# ---------------------------------------------------------------------------


class TestCategorizeCheckType:
    """Tests for _categorize_check_type()."""

    def test_static_httponly(self):
        assert _categorize_check_type("uses httpOnly cookie") == CheckType.STATIC

    def test_static_bcrypt(self):
        assert _categorize_check_type("passwords hashed with bcrypt") == CheckType.STATIC

    def test_static_jwt(self):
        assert _categorize_check_type("JWT token in header") == CheckType.STATIC

    def test_runtime_seconds(self):
        assert _categorize_check_type("loads in under 2 seconds") == CheckType.RUNTIME

    def test_runtime_latency(self):
        assert _categorize_check_type("API latency below 100ms") == CheckType.RUNTIME

    def test_external_odoo(self):
        assert _categorize_check_type("syncs with Odoo partner") == CheckType.EXTERNAL

    def test_external_stripe(self):
        assert _categorize_check_type("Stripe webhook received") == CheckType.EXTERNAL

    def test_behavioral_default(self):
        assert _categorize_check_type("user can create an account") == CheckType.BEHAVIORAL

    def test_external_takes_priority_over_static(self):
        # "stripe" + "https" → external wins (checked first)
        assert _categorize_check_type("stripe webhook via https") == CheckType.EXTERNAL


# ---------------------------------------------------------------------------
# Search term extraction
# ---------------------------------------------------------------------------


class TestExtractSearchTerms:
    """Tests for _extract_search_terms()."""

    def test_extracts_quoted_strings(self):
        terms = _extract_search_terms('field "httpOnly" in cookie')
        assert "httpOnly" in terms

    def test_extracts_camel_case(self):
        terms = _extract_search_terms("the createUser function")
        assert "createUser" in terms

    def test_extracts_snake_case(self):
        terms = _extract_search_terms("the create_user method")
        assert "create_user" in terms

    def test_extracts_pascal_case(self):
        terms = _extract_search_terms("InvoiceLineItem entity")
        assert "InvoiceLineItem" in terms

    def test_caps_at_10(self):
        long_text = " ".join(f'"term{i}"' for i in range(20))
        terms = _extract_search_terms(long_text)
        assert len(terms) <= 10


# ---------------------------------------------------------------------------
# Block finding
# ---------------------------------------------------------------------------


class TestBlockFinding:
    """Tests for _find_block_start and _find_block_end."""

    def test_finds_function_start(self):
        lines = [
            "import os",
            "",
            "function authenticate(req, res) {",
            "  token = req.headers.auth;",
            "  if (!token) return res.status(401);",
            "  // verify token",
            "}",
        ]
        # _find_block_start walks from index backwards looking for function/class def
        start = _find_block_start(lines, 4)
        assert start == 2  # function line

    def test_finds_block_end(self):
        lines = [
            "function foo() {",
            "  const x = 1;",
            "  return x;",
            "}",
            "",
        ]
        assert _find_block_end(lines, 0) == 3  # closing brace

    def test_merge_ranges(self):
        ranges = [(0, 5), (3, 8), (15, 20)]
        merged = _merge_ranges(ranges)
        assert merged == [(0, 8), (15, 20)]

    def test_merge_empty(self):
        assert _merge_ranges([]) == []


# ---------------------------------------------------------------------------
# Claude response parsing
# ---------------------------------------------------------------------------


class TestParseClaude:
    """Tests for _parse_claude_check_response()."""

    def test_parses_json_pass(self):
        text = '{"verdict": "PASS", "evidence": "Found httpOnly in auth.ts", "file": "auth.ts", "line": 42}'
        r = _parse_claude_check_response(text, "AC-1")
        assert r.verdict == "PASS"
        assert r.ac_id == "AC-1"
        assert "httpOnly" in r.evidence

    def test_parses_json_fail(self):
        text = '{"verdict": "FAIL", "evidence": "No auth middleware found"}'
        r = _parse_claude_check_response(text, "AC-2")
        assert r.verdict == "FAIL"

    def test_parses_with_markdown_fences(self):
        text = '```json\n{"verdict": "PARTIAL", "evidence": "Partially implemented"}\n```'
        r = _parse_claude_check_response(text, "AC-3")
        assert r.verdict == "PARTIAL"

    def test_falls_back_to_text_extraction(self):
        text = "The code does PASS this criterion because..."
        r = _parse_claude_check_response(text, "AC-4")
        assert r.verdict == "PASS"

    def test_defaults_to_fail(self):
        text = "I cannot determine the result"
        r = _parse_claude_check_response(text, "AC-5")
        assert r.verdict == "FAIL"


# ---------------------------------------------------------------------------
# Static checks
# ---------------------------------------------------------------------------


class TestStaticChecks:
    """Tests for static check infrastructure."""

    def test_grep_check_finds_keyword(self, tmp_path):
        # Create a source file
        src = tmp_path / "auth.ts"
        src.write_text("const cookie = { httpOnly: true };", encoding="utf-8")

        ac = AcceptanceCriterion(
            id="AC-4", feature="F-002", text="JWT in httpOnly cookie",
            check_type=CheckType.STATIC,
        )
        result = _grep_check(ac, tmp_path, [src], keywords=["httpOnly"])
        assert result.verdict == "PASS"
        assert "auth.ts" in result.file_path

    def test_grep_check_fails_when_missing(self, tmp_path):
        src = tmp_path / "auth.ts"
        src.write_text("const cookie = { secure: true };", encoding="utf-8")

        ac = AcceptanceCriterion(
            id="AC-4", feature="F-002", text="JWT in httpOnly cookie",
            check_type=CheckType.STATIC,
        )
        result = _grep_check(ac, tmp_path, [src], keywords=["httpOnly"])
        assert result.verdict == "FAIL"

    def test_discover_source_files(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("export default {}", encoding="utf-8")
        (tmp_path / "src" / "utils.py").write_text("pass", encoding="utf-8")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg.js").write_text("", encoding="utf-8")

        files = _discover_source_files(tmp_path)
        names = [f.name for f in files]
        assert "app.ts" in names
        assert "utils.py" in names
        assert "pkg.js" not in names  # Excluded dir

    def test_codebase_summary(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("x", encoding="utf-8")
        files = _discover_source_files(tmp_path)
        summary = _build_codebase_summary(tmp_path, files)
        assert "1" in summary  # 1 file
        assert "src" in summary


# ---------------------------------------------------------------------------
# Finding construction
# ---------------------------------------------------------------------------


class TestResultsToFindings:
    """Tests for _results_to_findings()."""

    def test_pass_creates_no_finding(self):
        acs = [AcceptanceCriterion(id="AC-1", feature="F-001", text="test")]
        results = [CheckResult(ac_id="AC-1", verdict="PASS", evidence="ok")]
        findings = _results_to_findings(results, acs)
        assert len(findings) == 0

    def test_fail_creates_finding(self):
        acs = [AcceptanceCriterion(id="AC-1", feature="F-001", text="implement login")]
        results = [CheckResult(ac_id="AC-1", verdict="FAIL", evidence="not found")]
        findings = _results_to_findings(results, acs)
        assert len(findings) == 1
        assert findings[0].severity == Severity.HIGH

    def test_partial_creates_medium_finding(self):
        acs = [AcceptanceCriterion(id="AC-1", feature="F-001", text="implement login")]
        results = [CheckResult(ac_id="AC-1", verdict="PARTIAL", evidence="partially done")]
        findings = _results_to_findings(results, acs)
        assert len(findings) == 1
        assert findings[0].severity == Severity.MEDIUM

    def test_skip_creates_requires_human(self):
        acs = [AcceptanceCriterion(id="AC-1", feature="F-001", text="loads in 2 seconds")]
        results = [CheckResult(ac_id="AC-1", verdict="SKIP", evidence="needs runtime")]
        findings = _results_to_findings(results, acs)
        assert len(findings) == 1
        assert findings[0].severity == Severity.REQUIRES_HUMAN

    def test_security_keyword_sets_category(self):
        acs = [AcceptanceCriterion(id="AC-1", feature="F-001", text="auth security check")]
        results = [CheckResult(ac_id="AC-1", verdict="FAIL", evidence="missing")]
        findings = _results_to_findings(results, acs)
        assert findings[0].category == FindingCategory.SECURITY

    def test_no_code_found_is_missing_feature(self):
        acs = [AcceptanceCriterion(id="AC-1", feature="F-001", text="implement widget")]
        results = [CheckResult(ac_id="AC-1", verdict="FAIL", evidence="No relevant code found for this")]
        findings = _results_to_findings(results, acs)
        assert findings[0].category == FindingCategory.MISSING_FEATURE


# ---------------------------------------------------------------------------
# AuditReport serialization
# ---------------------------------------------------------------------------


class TestAuditReportSerialization:
    """Tests for AuditReport to_dict/from_dict."""

    def test_roundtrip(self):
        report = AuditReport(
            run_number=1,
            timestamp="2026-03-20T00:00:00Z",
            original_prd_path="/path/to/prd.md",
            codebase_path="/path/to/code",
            total_acs=10,
            passed_acs=7,
            failed_acs=2,
            partial_acs=1,
            skipped_acs=0,
            score=75.0,
            findings=[
                Finding(
                    id="F-AC-1", feature="F-001", acceptance_criterion="test",
                    severity=Severity.HIGH, category=FindingCategory.CODE_FIX,
                    title="Test finding", description="Desc",
                    prd_reference="F-001", current_behavior="wrong",
                    expected_behavior="right",
                )
            ],
            previously_passing=["AC-1", "AC-2"],
            regressions=["AC-3"],
            audit_cost=0.15,
        )
        data = report.to_dict()
        json_str = json.dumps(data)
        restored = AuditReport.from_dict(json.loads(json_str))

        assert restored.run_number == 1
        assert restored.score == 75.0
        assert len(restored.findings) == 1
        assert restored.findings[0].severity == Severity.HIGH
        assert restored.previously_passing == ["AC-1", "AC-2"]
        assert restored.regressions == ["AC-3"]
        assert restored.audit_cost == 0.15

    def test_properties(self):
        report = AuditReport(
            run_number=1, timestamp="", original_prd_path="", codebase_path="",
            total_acs=10, passed_acs=5, failed_acs=3, partial_acs=2,
            skipped_acs=0, score=60.0,
            findings=[
                Finding(id="1", feature="", acceptance_criterion="", severity=Severity.CRITICAL,
                        category=FindingCategory.SECURITY, title="", description="",
                        prd_reference="", current_behavior="", expected_behavior=""),
                Finding(id="2", feature="", acceptance_criterion="", severity=Severity.HIGH,
                        category=FindingCategory.CODE_FIX, title="", description="",
                        prd_reference="", current_behavior="", expected_behavior=""),
                Finding(id="3", feature="", acceptance_criterion="", severity=Severity.MEDIUM,
                        category=FindingCategory.CODE_FIX, title="", description="",
                        prd_reference="", current_behavior="", expected_behavior=""),
                Finding(id="4", feature="", acceptance_criterion="", severity=Severity.LOW,
                        category=FindingCategory.CODE_FIX, title="", description="",
                        prd_reference="", current_behavior="", expected_behavior=""),
            ],
        )
        assert report.critical_count == 1
        assert report.high_count == 1
        assert report.actionable_count == 3  # CRITICAL + HIGH + MEDIUM


# ---------------------------------------------------------------------------
# Integration: run_audit with mock Claude
# ---------------------------------------------------------------------------


class TestRunAuditIntegration:
    """Integration test for run_audit with mocked Claude calls."""

    def test_audit_with_sample_codebase(self, tmp_path):
        """Run audit on a small codebase with mocked behavioral checks."""
        # Create PRD
        prd_path = tmp_path / "prd.md"
        prd_path.write_text(SAMPLE_PRD, encoding="utf-8")

        # Create codebase
        src_dir = tmp_path / "output" / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "auth.ts").write_text(
            "import jwt from 'jsonwebtoken';\n"
            "const options = { httpOnly: true, secure: true };\n"
            "function login(req, res) { /* auth logic */ }\n",
            encoding="utf-8",
        )
        (src_dir / "signup.ts").write_text(
            "function createUser(email, phone) {\n"
            "  // validate email\n"
            "  if (existingUser(email)) throw new Error('Email taken');\n"
            "}\n",
            encoding="utf-8",
        )

        # Mock anthropic to avoid real API calls
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"verdict": "PASS", "evidence": "Found"}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        mock_anthropic_mod = MagicMock()
        mock_anthropic_mod.Anthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic_mod}):
            report = run_audit(
                original_prd_path=prd_path,
                codebase_path=tmp_path / "output",
                run_number=1,
            )

        assert report.total_acs > 0
        assert report.score >= 0
        assert isinstance(report.findings, list)
        assert report.run_number == 1
