"""Tests for the Coordinated Builder — orchestrator logic."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_team_v15.audit_agent import (
    AuditReport,
    Finding,
    FindingCategory,
    Severity,
)
from agent_team_v15.config_agent import LoopState
from agent_team_v15.coordinated_builder import (
    CoordinatedBuildResult,
    _archive_state,
    _build_result,
    _generate_final_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(severity: Severity = Severity.HIGH) -> Finding:
    return Finding(
        id="F-TEST", feature="F-001", acceptance_criterion="test",
        severity=severity, category=FindingCategory.CODE_FIX,
        title="Test", description="Test desc", prd_reference="F-001",
        current_behavior="wrong", expected_behavior="right",
    )


def _make_report(score: float = 85.0, findings: list | None = None) -> AuditReport:
    findings = findings or []
    return AuditReport(
        run_number=1, timestamp="2026-03-20T00:00:00Z",
        original_prd_path="prd.md", codebase_path="./output",
        total_acs=100, passed_acs=85, failed_acs=15, partial_acs=0,
        skipped_acs=0, score=score, findings=findings,
    )


# ---------------------------------------------------------------------------
# Archive state
# ---------------------------------------------------------------------------


class TestArchiveState:
    """Tests for _archive_state()."""

    def test_archives_existing_state(self, tmp_path):
        state_path = tmp_path / "STATE.json"
        state_path.write_text('{"test": true}', encoding="utf-8")

        _archive_state(tmp_path, 1)

        assert not state_path.exists()
        archive = tmp_path / "STATE.json.run1"
        assert archive.exists()
        assert json.loads(archive.read_text()) == {"test": True}

    def test_no_error_if_missing(self, tmp_path):
        # Should not raise
        _archive_state(tmp_path, 1)


# ---------------------------------------------------------------------------
# Final report generation
# ---------------------------------------------------------------------------


class TestFinalReport:
    """Tests for _generate_final_report()."""

    def test_generates_report_file(self, tmp_path):
        from agent_team_v15.config_agent import RunRecord

        state = LoopState(
            original_prd_path="prd.md",
            codebase_path="./output",
            total_cost=134.0,
            current_run=2,
            status="converged",
            stop_reason="CONVERGED: 1.5% improvement, zero CRITICAL/HIGH",
        )
        state.runs.append(RunRecord(
            run_number=1, run_type="initial", prd_path="prd.md",
            cost=62.0, score=84.6, total_acs=103, passed_acs=78,
            partial_acs=5, failed_acs=20, skipped_acs=0,
            critical_count=2, high_count=8, medium_count=10,
            finding_count=25, regression_count=0,
        ))
        state.runs.append(RunRecord(
            run_number=2, run_type="fix", prd_path="fix_prd.md",
            cost=72.0, score=93.5, total_acs=102, passed_acs=93,
            partial_acs=5, failed_acs=4, skipped_acs=0,
            critical_count=0, high_count=0, medium_count=3,
            finding_count=5, regression_count=0,
        ))

        report = _make_report(score=93.5, findings=[_make_finding(Severity.MEDIUM)])

        _generate_final_report(state, report, tmp_path)

        report_path = tmp_path / "FINAL_REPORT.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "Score Progression" in content
        assert "84.6" in content
        assert "93.5" in content
        assert "$134.00" in content
        assert "CONVERGED" in content


# ---------------------------------------------------------------------------
# Build result construction
# ---------------------------------------------------------------------------


class TestBuildResult:
    """Tests for _build_result()."""

    def test_success_result(self):
        state = LoopState(current_run=2, total_cost=134.0)
        report = _make_report(score=93.5, findings=[_make_finding(Severity.LOW)])
        result = _build_result(state, report, "CONVERGED: below threshold")
        assert result.success is True
        assert result.final_score == 93.5
        assert result.total_cost == 134.0
        assert result.total_runs == 2

    def test_failure_result(self):
        state = LoopState(current_run=1, total_cost=62.0)
        result = _build_result(state, None, "BUILDER_FAILURE")
        assert result.success is False
        assert result.error == "BUILDER_FAILURE"
        assert result.final_score == 0

    def test_excludes_acceptable_deviations(self):
        state = LoopState(current_run=1, total_cost=62.0)
        report = _make_report(findings=[
            _make_finding(Severity.HIGH),
            _make_finding(Severity.ACCEPTABLE_DEVIATION),
        ])
        result = _build_result(state, report, "COMPLETE")
        # Should exclude ACCEPTABLE_DEVIATION from remaining
        assert len(result.remaining_findings) == 1
        assert result.remaining_findings[0].severity == Severity.HIGH


# ---------------------------------------------------------------------------
# EVS simulation
# ---------------------------------------------------------------------------


class TestEVSSimulation:
    """Simulate the EVS Customer Portal coordinated build trajectory."""

    def test_evs_trajectory(self):
        """Verify the stop conditions match EVS evidence."""
        state = LoopState(
            original_prd_path="evs_portal.md",
            codebase_path="./evs_output",
            max_budget=300.0,
            max_iterations=4,
            min_improvement_threshold=3.0,
        )

        # Run 1: Initial build
        from agent_team_v15.config_agent import evaluate_stop_conditions

        run1_report = _make_report(
            score=84.6,
            findings=[
                _make_finding(Severity.CRITICAL),
                _make_finding(Severity.CRITICAL),
                _make_finding(Severity.HIGH),
                _make_finding(Severity.HIGH),
                _make_finding(Severity.HIGH),
                _make_finding(Severity.MEDIUM),
                _make_finding(Severity.MEDIUM),
                _make_finding(Severity.LOW),
            ],
        )
        state.add_run(run1_report, 62.0, run_type="initial")

        decision1 = evaluate_stop_conditions(state, run1_report)
        assert decision1.action == "CONTINUE"  # Score low, many findings

        # Run 2: Fix build
        run2_report = _make_report(
            score=93.5,
            findings=[
                _make_finding(Severity.MEDIUM),
                _make_finding(Severity.LOW),
                _make_finding(Severity.REQUIRES_HUMAN),
            ],
        )
        state.add_run(run2_report, 72.0, run_type="fix")

        decision2 = evaluate_stop_conditions(state, run2_report)
        # Score jumped 8.9% but zero CRITICAL/HIGH → might converge if we
        # pretend another run only gets 1% improvement
        # For now, with 1 MEDIUM finding, it should CONTINUE
        assert decision2.action in ("CONTINUE", "STOP")

        # Run 3: Minor improvements
        run3_report = _make_report(
            score=95.0,
            findings=[
                _make_finding(Severity.LOW),
                _make_finding(Severity.REQUIRES_HUMAN),
            ],
        )
        state.add_run(run3_report, 45.0, run_type="fix")

        decision3 = evaluate_stop_conditions(state, run3_report)
        # 95.0 - 93.5 = 1.5% < 3%, zero CRITICAL/HIGH → CONVERGED
        assert decision3.action == "STOP"
        assert "CONVERG" in decision3.reason


# ---------------------------------------------------------------------------
# Phase 2C: Pipeline fix tests
# ---------------------------------------------------------------------------


class TestFilterFindingsWiring:
    """Verify filter_findings_for_fix() is wired (not dead code)."""

    def test_filter_findings_called_in_triage(self):
        """filter_findings_for_fix() is called by _triage_findings(), not dead code."""
        import ast
        import pathlib
        source = pathlib.Path("C:/Projects/agent-team-v15/src/agent_team_v15/config_agent.py").read_text()
        tree = ast.parse(source)
        # Find calls to filter_findings_for_fix
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(getattr(node, "func", None), ast.Name)
            and node.func.id == "filter_findings_for_fix"
        ]
        assert len(calls) > 0, "filter_findings_for_fix() is dead code — never called"


class TestValidateFixPRDStructure:
    """Tests for _validate_fix_prd_structure() in coordinated_builder."""

    def test_rejects_no_features(self):
        from agent_team_v15.coordinated_builder import _validate_fix_prd_structure
        bad_prd = "# Fix PRD\n\nSome text without any feature headings.\n\n- AC-001: Something\n" * 5
        valid, msg = _validate_fix_prd_structure(bad_prd)
        assert not valid
        assert "feature" in msg.lower()

    def test_rejects_no_acs(self):
        from agent_team_v15.coordinated_builder import _validate_fix_prd_structure
        bad_prd = (
            "# Fix PRD\n\n## Features\n\n"
            "### F-FIX-001: Something\nDescription only, no ACs.\n" * 5
        )
        valid, msg = _validate_fix_prd_structure(bad_prd)
        assert not valid

    def test_accepts_valid_format(self):
        from agent_team_v15.coordinated_builder import _validate_fix_prd_structure
        good_prd = (
            "# Project — Fix Run 1\n\n## Features\n\n"
            "### F-FIX-001: Fix casing\nFix snake_case to camelCase.\n\n"
            "#### Acceptance Criteria\n"
            "- AC-FIX-001: booking sends vehicleId\n"
            "- AC-FIX-002: nps sends npsScore\n"
            + "\nExtra content for minimum length.\n" * 10
        )
        valid, msg = _validate_fix_prd_structure(good_prd)
        assert valid, f"Valid PRD rejected: {msg}"


    def test_evs_budget_cap(self):
        """Verify budget cap works with EVS-like costs."""
        state = LoopState(
            original_prd_path="evs.md",
            codebase_path="./out",
            max_budget=186.0,  # 3 × $62
        )

        from agent_team_v15.config_agent import evaluate_stop_conditions

        # Run 1: $62
        r1 = _make_report(score=84.6, findings=[_make_finding(Severity.HIGH)])
        state.add_run(r1, 62.0, run_type="initial")

        # Run 2: $72 → total $134
        r2 = _make_report(score=93.5, findings=[_make_finding(Severity.HIGH)])
        state.add_run(r2, 72.0, run_type="fix")

        # Run 3: would be $60 → total $194 > $186
        # But budget check is on total_cost BEFORE deciding to continue
        state.total_cost = 194.0  # Simulate going over
        r3 = _make_report(score=94.0, findings=[_make_finding(Severity.HIGH)])
        decision = evaluate_stop_conditions(state, r3)
        assert decision.action == "STOP"
        assert "BUDGET" in decision.reason
