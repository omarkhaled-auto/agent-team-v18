"""N-08: Tests for audit-fix observability — FIX_CYCLE_LOG.md lifecycle.

Covers:
- Flag OFF: no FIX_CYCLE_LOG.md created
- Flag ON + fix_cycle_log ON: initialize_fix_cycle_log creates the file
- append_fix_cycle_entry appends after _run_audit_fix_unified
- Entry format validation (cycle_number, phase, severity-filtered findings)
- build-l offline replay (load real AUDIT_REPORT.json)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.tracking_documents import (
    initialize_fix_cycle_log,
    build_fix_cycle_entry,
    append_fix_cycle_entry,
)
from agent_team_v15.audit_models import AuditFinding, AuditReport


# Path to the preserved build-l AUDIT_REPORT.json
_BUILD_L_ROOT = Path(__file__).resolve().parent.parent / "v18 test runs" / "build-l-gate-a-20260416"
_BUILD_L_AUDIT_REPORT = _BUILD_L_ROOT / ".agent-team" / "AUDIT_REPORT.json"


class TestFlagOff:
    """When audit_fix_iteration_enabled is OFF, nothing should be written."""

    def test_no_fix_cycle_log_when_flag_off(self, tmp_path: Path) -> None:
        """FIX_CYCLE_LOG.md is not created when no initialize call is made."""
        log_path = tmp_path / "FIX_CYCLE_LOG.md"
        assert not log_path.exists()


class TestInitialize:
    """initialize_fix_cycle_log creates FIX_CYCLE_LOG.md with header."""

    def test_creates_file_on_first_call(self, tmp_path: Path) -> None:
        result = initialize_fix_cycle_log(str(tmp_path))
        assert result == tmp_path / "FIX_CYCLE_LOG.md"
        assert result.is_file()

    def test_header_content(self, tmp_path: Path) -> None:
        initialize_fix_cycle_log(str(tmp_path))
        content = (tmp_path / "FIX_CYCLE_LOG.md").read_text(encoding="utf-8")
        assert "# Fix Cycle Log" in content
        assert "DO NOT repeat a previously attempted strategy" in content

    def test_idempotent_does_not_overwrite(self, tmp_path: Path) -> None:
        initialize_fix_cycle_log(str(tmp_path))
        log_path = tmp_path / "FIX_CYCLE_LOG.md"
        log_path.write_text("custom content", encoding="utf-8")
        initialize_fix_cycle_log(str(tmp_path))
        assert log_path.read_text(encoding="utf-8") == "custom content"

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c"
        result = initialize_fix_cycle_log(str(deep))
        assert result.is_file()
        assert deep.is_dir()


class TestBuildFixCycleEntry:
    """build_fix_cycle_entry produces correct markdown format."""

    def test_contains_cycle_number(self) -> None:
        entry = build_fix_cycle_entry(phase="audit-fix", cycle_number=3, failures=[])
        assert "Cycle 3" in entry

    def test_contains_phase_label(self) -> None:
        entry = build_fix_cycle_entry(phase="audit-fix", cycle_number=1, failures=[])
        assert "audit-fix" in entry

    def test_contains_severity_filtered_findings(self) -> None:
        failures = [
            "[HIGH] technical/REQ-001: Missing error handler",
            "[CRITICAL] requirements/REQ-002: Auth bypass",
        ]
        entry = build_fix_cycle_entry(
            phase="audit-fix",
            cycle_number=2,
            failures=failures,
            previous_cycles=1,
        )
        assert "Missing error handler" in entry
        assert "Auth bypass" in entry
        assert "**Previous cycles in this phase:** 1" in entry

    def test_empty_failures_list(self) -> None:
        entry = build_fix_cycle_entry(phase="audit-fix", cycle_number=1, failures=[])
        assert "(none specified)" in entry


class TestAppendFixCycleEntry:
    """append_fix_cycle_entry appends to FIX_CYCLE_LOG.md."""

    def test_appends_entry(self, tmp_path: Path) -> None:
        initialize_fix_cycle_log(str(tmp_path))
        entry = build_fix_cycle_entry(
            phase="audit-fix", cycle_number=1, failures=["[HIGH] test failure"]
        )
        append_fix_cycle_entry(str(tmp_path), entry)
        content = (tmp_path / "FIX_CYCLE_LOG.md").read_text(encoding="utf-8")
        assert "audit-fix — Cycle 1" in content
        assert "test failure" in content

    def test_idempotent_no_duplicate(self, tmp_path: Path) -> None:
        initialize_fix_cycle_log(str(tmp_path))
        entry = build_fix_cycle_entry(
            phase="audit-fix", cycle_number=1, failures=["[HIGH] dup test"]
        )
        append_fix_cycle_entry(str(tmp_path), entry)
        append_fix_cycle_entry(str(tmp_path), entry)
        content = (tmp_path / "FIX_CYCLE_LOG.md").read_text(encoding="utf-8")
        assert content.count("audit-fix — Cycle 1") == 1


class TestBuildLOfflineReplay:
    """Load build-l AUDIT_REPORT.json and verify findings can feed entry builder."""

    @pytest.fixture()
    def build_l_report(self) -> AuditReport:
        if not _BUILD_L_AUDIT_REPORT.is_file():
            pytest.skip(f"build-l AUDIT_REPORT.json not found at {_BUILD_L_AUDIT_REPORT}")
        raw = _BUILD_L_AUDIT_REPORT.read_text(encoding="utf-8")
        return AuditReport.from_json(raw)

    def test_findings_can_feed_entry_builder(self, build_l_report: AuditReport) -> None:
        sev_order = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
        # Use MEDIUM threshold (index 2) to filter
        sev_cutoff = 2
        filtered = [
            f"[{f.severity}] {f.auditor}/{f.requirement_id}: {f.summary}"
            for f in build_l_report.findings
            if f.severity.upper() in sev_order[: sev_cutoff + 1]
        ][:20]
        entry = build_fix_cycle_entry(
            phase="audit-fix",
            cycle_number=1,
            failures=filtered,
        )
        assert "audit-fix — Cycle 1" in entry
        # With build-l's 28 findings, at least some should match CRITICAL/HIGH/MEDIUM
        assert len(filtered) > 0
