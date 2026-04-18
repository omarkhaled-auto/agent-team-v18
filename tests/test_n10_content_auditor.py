"""N-10: Tests for forbidden_content_scanner.py.

Covers:
- Per-rule positive case (triggers each FC-001..FC-006)
- Per-rule negative case (clean content that does NOT trigger)
- Exclude path works (i18n files skip FC-005)
- merge_findings_into_report integration
- Flag OFF: scanner is not run (tested via scan_repository empty result)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.forbidden_content_scanner import (
    DEFAULT_RULES,
    ForbiddenContentRule,
    scan_repository,
    merge_findings_into_report,
)
from agent_team_v15.audit_models import AuditFinding


def _write_file(tmp_path: Path, rel_path: str, content: str) -> Path:
    """Helper to write a file at rel_path under tmp_path."""
    full = tmp_path / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


class TestFC001StubThrow:
    """FC-001: throw new Error('not implemented') / 'todo' / etc."""

    def test_positive_triggers(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/service.ts", "throw new Error('not implemented');")
        findings = scan_repository(tmp_path)
        fc001 = [f for f in findings if f.finding_id.startswith("FC-001")]
        assert len(fc001) >= 1

    def test_positive_todo_variant(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/handler.tsx", "throw new Error('todo');")
        findings = scan_repository(tmp_path)
        fc001 = [f for f in findings if f.finding_id.startswith("FC-001")]
        assert len(fc001) >= 1

    def test_negative_real_error(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/service.ts", "throw new Error('User not found');")
        findings = scan_repository(tmp_path)
        fc001 = [f for f in findings if f.finding_id.startswith("FC-001")]
        assert len(fc001) == 0


class TestFC002TodoComment:
    """FC-002: // TODO / FIXME / XXX line comments."""

    def test_positive_todo(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/app.ts", "// TODO: fix this later")
        findings = scan_repository(tmp_path)
        fc002 = [f for f in findings if f.finding_id.startswith("FC-002")]
        assert len(fc002) >= 1

    def test_positive_fixme(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/app.jsx", "// FIXME handle edge case")
        findings = scan_repository(tmp_path)
        fc002 = [f for f in findings if f.finding_id.startswith("FC-002")]
        assert len(fc002) >= 1

    def test_negative_clean_comment(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/app.ts", "// This function handles auth")
        findings = scan_repository(tmp_path)
        fc002 = [f for f in findings if f.finding_id.startswith("FC-002")]
        assert len(fc002) == 0


class TestFC003BlockTodo:
    """FC-003: Block-comment TODO/FIXME/XXX."""

    def test_positive_block_todo(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/util.tsx", "/* TODO: refactor this */")
        findings = scan_repository(tmp_path)
        fc003 = [f for f in findings if f.finding_id.startswith("FC-003")]
        assert len(fc003) >= 1

    def test_negative_clean_block(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/util.tsx", "/* This is a helper function */")
        findings = scan_repository(tmp_path)
        fc003 = [f for f in findings if f.finding_id.startswith("FC-003")]
        assert len(fc003) == 0


class TestFC004PlaceholderSecret:
    """FC-004: Placeholder secret literals."""

    def test_positive_change_me(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/config.ts", "const secret = 'CHANGE_ME';")
        findings = scan_repository(tmp_path)
        fc004 = [f for f in findings if f.finding_id.startswith("FC-004")]
        assert len(fc004) >= 1

    def test_positive_your_api_key(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/config.js", 'const key = "YOUR_API_KEY";')
        findings = scan_repository(tmp_path)
        fc004 = [f for f in findings if f.finding_id.startswith("FC-004")]
        assert len(fc004) >= 1

    def test_negative_real_value(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/config.ts", "const secret = 'abc123xyz';")
        findings = scan_repository(tmp_path)
        fc004 = [f for f in findings if f.finding_id.startswith("FC-004")]
        assert len(fc004) == 0


class TestFC005UntranslatedRtl:
    """FC-005: Untranslated Arabic/RTL literals."""

    def test_positive_arabic(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "apps/web/src/page.ts", 'const title = "\u0645\u0631\u062d\u0628\u0627";')
        findings = scan_repository(tmp_path)
        fc005 = [f for f in findings if f.finding_id.startswith("FC-005")]
        assert len(fc005) >= 1

    def test_negative_english(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "apps/web/src/page.ts", 'const title = "Hello";')
        findings = scan_repository(tmp_path)
        fc005 = [f for f in findings if f.finding_id.startswith("FC-005")]
        assert len(fc005) == 0

    def test_exclude_i18n_paths(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "apps/web/i18n/ar.ts", 'const title = "\u0645\u0631\u062d\u0628\u0627";')
        findings = scan_repository(tmp_path)
        fc005 = [f for f in findings if f.finding_id.startswith("FC-005")]
        assert len(fc005) == 0


class TestFC006EmptyFn:
    """FC-006: Empty function bodies."""

    def test_positive_empty_fn(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/handler.ts", "function handler() {}")
        findings = scan_repository(tmp_path)
        fc006 = [f for f in findings if f.finding_id.startswith("FC-006")]
        assert len(fc006) >= 1

    def test_negative_nonempty_fn(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/handler.ts", "function handler() { return 42; }")
        findings = scan_repository(tmp_path)
        fc006 = [f for f in findings if f.finding_id.startswith("FC-006")]
        assert len(fc006) == 0


class TestMergeFindingsIntoReport:
    """merge_findings_into_report mutates the report correctly."""

    def test_adds_findings_to_report(self) -> None:
        report = SimpleNamespace(
            findings=[],
            by_severity={},
            by_file={},
            by_requirement={},
            fix_candidates=[],
            auditors_deployed=[],
        )
        finding = AuditFinding(
            finding_id="FC-001-test-1",
            auditor="forbidden_content",
            requirement_id="GENERAL",
            verdict="FAIL",
            severity="HIGH",
            summary="Stub throw",
            evidence=["src/foo.ts:10 -- throw new Error('not implemented')"],
        )
        merge_findings_into_report(report, [finding])
        assert len(report.findings) == 1
        assert report.findings[0].finding_id == "FC-001-test-1"
        assert "forbidden_content" in report.auditors_deployed

    def test_updates_indices(self) -> None:
        report = SimpleNamespace(
            findings=[],
            by_severity={},
            by_file={},
            by_requirement={},
            fix_candidates=[],
            auditors_deployed=[],
        )
        finding = AuditFinding(
            finding_id="FC-002-test-1",
            auditor="forbidden_content",
            requirement_id="GENERAL",
            verdict="FAIL",
            severity="HIGH",
            summary="TODO comment",
            evidence=["src/app.ts:5 -- // TODO fix"],
        )
        merge_findings_into_report(report, [finding])
        assert 0 in report.by_severity.get("HIGH", [])
        assert 0 in report.by_requirement.get("GENERAL", [])
        assert 0 in report.fix_candidates

    def test_no_op_for_empty_findings(self) -> None:
        report = SimpleNamespace(
            findings=[],
            by_severity={},
            by_file={},
            by_requirement={},
            fix_candidates=[],
            auditors_deployed=[],
        )
        merge_findings_into_report(report, [])
        assert len(report.findings) == 0
        assert len(report.auditors_deployed) == 0

    def test_low_severity_not_in_fix_candidates(self) -> None:
        report = SimpleNamespace(
            findings=[],
            by_severity={},
            by_file={},
            by_requirement={},
            fix_candidates=[],
            auditors_deployed=[],
        )
        finding = AuditFinding(
            finding_id="FC-002-test-2",
            auditor="forbidden_content",
            requirement_id="GENERAL",
            verdict="FAIL",
            severity="LOW",
            summary="TODO",
            evidence=["src/test.ts:1"],
        )
        merge_findings_into_report(report, [finding])
        assert len(report.fix_candidates) == 0


class TestScannerFlagOff:
    """When the scanner flag is OFF, scan_repository returns empty on a clean repo."""

    def test_empty_directory_returns_no_findings(self, tmp_path: Path) -> None:
        findings = scan_repository(tmp_path)
        assert findings == []

    def test_non_matching_files_no_findings(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "readme.md", "# Hello world")
        findings = scan_repository(tmp_path)
        assert findings == []
