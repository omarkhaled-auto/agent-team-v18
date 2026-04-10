"""Tests for Truth Scoring + Auto-Rollback (Feature #2)."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from agent_team_v15.quality_checks import (
    TruthScore,
    TruthScoreGate,
    TruthScorer,
)
from agent_team_v15.audit_agent import AuditReport, Finding, FindingCategory, Severity
from agent_team_v15.config_agent import LoopState, RunRecord, evaluate_stop_conditions


# --- TruthScore dataclass tests ---

class TestTruthScore:
    def test_pass_gate_above_095(self):
        dims = {k: 1.0 for k in TruthScorer.DIMENSION_WEIGHTS}
        score = TruthScore.from_dimensions(dims)
        assert score.gate == TruthScoreGate.PASS
        assert score.passed is True
        assert score.overall == 1.0

    def test_retry_gate_between_080_095(self):
        dims = {k: 0.9 for k in TruthScorer.DIMENSION_WEIGHTS}
        score = TruthScore.from_dimensions(dims)
        assert score.gate == TruthScoreGate.RETRY
        assert score.passed is False

    def test_escalate_gate_below_080(self):
        dims = {k: 0.5 for k in TruthScorer.DIMENSION_WEIGHTS}
        score = TruthScore.from_dimensions(dims)
        assert score.gate == TruthScoreGate.ESCALATE
        assert score.passed is False
        assert score.overall < 0.80

    def test_weighted_average(self):
        dims = {
            "requirement_coverage": 1.0,  # weight 0.25
            "contract_compliance": 1.0,   # weight 0.20
            "error_handling": 1.0,        # weight 0.15
            "type_safety": 1.0,           # weight 0.15
            "test_presence": 0.0,         # weight 0.15
            "security_patterns": 0.0,     # weight 0.10
        }
        score = TruthScore.from_dimensions(dims)
        # Expected: (0.25 + 0.20 + 0.15 + 0.15 + 0 + 0) / 1.0 = 0.75
        assert 0.74 <= score.overall <= 0.76


# --- TruthScorer integration tests ---

class TestTruthScorer:
    def test_scores_empty_project(self, tmp_path):
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        assert 0.0 <= score.overall <= 1.0

    def test_scores_project_with_source_files(self, tmp_path):
        # Create minimal source file
        src = tmp_path / "app.ts"
        src.write_text(
            "import { Controller, Get } from '@nestjs/common';\n"
            "@Controller('users')\n"
            "export class UserController {\n"
            "  @Get()\n"
            "  findAll() { return []; }\n"
            "}\n"
        )
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        assert score.overall > 0.0
        assert "requirement_coverage" in score.dimensions

    def test_type_safety_penalizes_any(self, tmp_path):
        src = tmp_path / "bad.ts"
        src.write_text("const x: any = 5;\nconst y: any = 'hello';\n")
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        assert score.dimensions["type_safety"] < 1.0

    def test_test_presence_scores(self, tmp_path):
        (tmp_path / "app.ts").write_text("export class App {}")
        (tmp_path / "app.test.ts").write_text("test('works', () => {})")
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        assert score.dimensions["test_presence"] > 0.0


# --- Regression detection tests ---

class TestRegressionDetection:
    def _make_report(self, passing_acs: list[str], regressions: list[str] | None = None) -> AuditReport:
        return AuditReport(
            run_number=1, timestamp="2026-04-01T00:00:00Z",
            original_prd_path="prd.md", codebase_path="./output",
            total_acs=10, passed_acs=len(passing_acs), failed_acs=10-len(passing_acs),
            partial_acs=0, skipped_acs=0, score=len(passing_acs)*10.0,
            previously_passing=passing_acs,
            regressions=regressions or [],
        )

    def test_detects_regression(self):
        from agent_team_v15.coordinated_builder import _check_regressions
        prev = self._make_report(["AC-1", "AC-2", "AC-3"])
        curr = self._make_report(["AC-1", "AC-3"])  # AC-2 regressed
        regressions = _check_regressions(curr, prev)
        assert "AC-2" in regressions

    def test_no_regression_on_first_run(self):
        from agent_team_v15.coordinated_builder import _check_regressions
        curr = self._make_report(["AC-1"])
        regressions = _check_regressions(curr, None)
        assert regressions == []


# --- Stop condition: REGRESSION_LIMIT ---

class TestRegressionLimitStop:
    def _make_state(self, regression_count: int, max_regressions: int = 5) -> LoopState:
        state = LoopState(
            original_prd_path="prd.md",
            codebase_path="./output",
            max_budget=300.0,
            max_iterations=10,
            total_cost=60.0,
            current_run=2,
            regression_count=regression_count,
            max_regressions=max_regressions,
        )
        state.runs.append(RunRecord(
            run_number=1, run_type="initial", prd_path="prd.md",
            cost=60.0, score=80.0, total_acs=100, passed_acs=80,
            partial_acs=0, failed_acs=20, skipped_acs=0,
            critical_count=0, high_count=2, medium_count=5,
            finding_count=10, regression_count=0,
        ))
        return state

    def _make_report(self) -> AuditReport:
        return AuditReport(
            run_number=2, timestamp="2026-04-01T00:00:00Z",
            original_prd_path="prd.md", codebase_path="./output",
            total_acs=100, passed_acs=82, failed_acs=18,
            partial_acs=0, skipped_acs=0, score=82.0,
            findings=[Finding(
                id="F-1", feature="F-001", acceptance_criterion="test",
                severity=Severity.HIGH, category=FindingCategory.CODE_FIX,
                title="Test", description="desc", prd_reference="F-001",
                current_behavior="wrong", expected_behavior="right",
            )],
        )

    def test_stops_on_regression_limit(self):
        state = self._make_state(regression_count=5)
        report = self._make_report()
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "STOP"
        assert "REGRESSION_LIMIT" in decision.reason

    def test_continues_below_limit(self):
        state = self._make_state(regression_count=3)
        report = self._make_report()
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "CONTINUE"


# --- State backward compatibility ---

class TestStateBackwardCompat:
    def test_loop_state_defaults(self):
        state = LoopState()
        assert state.regression_count == 0
        assert state.truth_score_threshold == 0.95
        assert state.max_regressions == 5

    def test_loop_state_serialization_roundtrip(self):
        state = LoopState(
            regression_count=3,
            truth_score_threshold=0.90,
            max_regressions=10,
        )
        data = state.to_dict()
        restored = LoopState.from_dict(data)
        assert restored.regression_count == 3
        assert restored.truth_score_threshold == 0.90
        assert restored.max_regressions == 10

    def test_old_state_file_loads(self):
        """Simulate loading a state file from before Feature #2."""
        old_data = {
            "schema_version": 1,
            "original_prd_path": "prd.md",
            "codebase_path": "./output",
            "config": {"max_budget": 300.0, "max_iterations": 4},
            "runs": [],
            "total_cost": 0.0,
            "current_run": 0,
            "status": "running",
            "stop_reason": "",
            # No regression_count, truth_score_threshold, max_regressions
        }
        state = LoopState.from_dict(old_data)
        assert state.regression_count == 0
        assert state.truth_score_threshold == 0.95
        assert state.max_regressions == 5
