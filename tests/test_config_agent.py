"""Tests for the Configuration Agent — stop conditions, triage, scoring."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from agent_team_v15.audit_agent import (
    AuditReport,
    Finding,
    FindingCategory,
    Severity,
)
from agent_team_v15.config_agent import (
    LoopDecision,
    LoopState,
    RunRecord,
    evaluate_stop_conditions,
    estimate_fix_cost,
    _check_circuit_breaker,
    _triage_findings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    severity: Severity = Severity.HIGH,
    category: FindingCategory = FindingCategory.CODE_FIX,
    effort: str = "small",
) -> Finding:
    """Create a minimal Finding for testing."""
    return Finding(
        id="F-TEST",
        feature="F-001",
        acceptance_criterion="test AC",
        severity=severity,
        category=category,
        title="Test finding",
        description="Test",
        prd_reference="F-001",
        current_behavior="wrong",
        expected_behavior="right",
        estimated_effort=effort,
    )


def _make_report(
    score: float = 80.0,
    passed: int = 80,
    total: int = 100,
    critical: int = 0,
    high: int = 0,
    medium: int = 0,
    findings: list[Finding] | None = None,
    regressions: list[str] | None = None,
) -> AuditReport:
    """Create a minimal AuditReport for testing."""
    if findings is None:
        findings = []
        for _ in range(critical):
            findings.append(_make_finding(Severity.CRITICAL))
        for _ in range(high):
            findings.append(_make_finding(Severity.HIGH))
        for _ in range(medium):
            findings.append(_make_finding(Severity.MEDIUM))

    return AuditReport(
        run_number=1,
        timestamp="2026-03-20T00:00:00Z",
        original_prd_path="prd.md",
        codebase_path="./output",
        total_acs=total,
        passed_acs=passed,
        failed_acs=total - passed,
        partial_acs=0,
        skipped_acs=0,
        score=score,
        findings=findings,
        regressions=regressions or [],
    )


def _make_state(
    runs: list[dict] | None = None,
    total_cost: float = 0.0,
    current_run: int = 0,
    max_budget: float = 300.0,
    max_iterations: int = 4,
) -> LoopState:
    """Create a LoopState with run history."""
    state = LoopState(
        original_prd_path="prd.md",
        codebase_path="./output",
        max_budget=max_budget,
        max_iterations=max_iterations,
        total_cost=total_cost,
        current_run=current_run,
    )
    if runs:
        for r in runs:
            state.runs.append(RunRecord(
                run_number=r.get("run_number", 1),
                run_type=r.get("run_type", "initial"),
                prd_path="prd.md",
                cost=r.get("cost", 60.0),
                score=r.get("score", 80.0),
                total_acs=r.get("total_acs", 100),
                passed_acs=r.get("passed_acs", 80),
                partial_acs=0,
                failed_acs=20,
                skipped_acs=0,
                critical_count=r.get("critical", 0),
                high_count=r.get("high", 0),
                medium_count=r.get("medium", 0),
                finding_count=r.get("findings", 0),
                regression_count=r.get("regressions", 0),
            ))
    return state


# ---------------------------------------------------------------------------
# Stop Condition: Convergence
# ---------------------------------------------------------------------------


class TestConvergence:
    """Tests for convergence stop condition."""

    def test_converged_below_threshold_zero_critical_high(self):
        state = _make_state(
            runs=[{"score": 92.0, "cost": 60.0}],
            total_cost=60.0,
            current_run=1,
        )
        report = _make_report(score=93.5, critical=0, high=0)
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "STOP"
        assert "CONVERG" in decision.reason

    def test_not_converged_above_threshold(self):
        state = _make_state(
            runs=[{"score": 80.0, "cost": 60.0}],
            total_cost=60.0,
            current_run=1,
        )
        report = _make_report(score=90.0, high=2)
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "CONTINUE"

    def test_not_converged_if_critical_remains(self):
        state = _make_state(
            runs=[{"score": 92.0, "cost": 60.0}],
            total_cost=60.0,
            current_run=1,
        )
        report = _make_report(score=93.0, critical=1, high=0)
        decision = evaluate_stop_conditions(state, report)
        # Should NOT converge because CRITICAL > 0
        assert decision.action != "STOP" or "CONVERG" not in decision.reason


# ---------------------------------------------------------------------------
# Stop Condition: Zero Actionable
# ---------------------------------------------------------------------------


class TestZeroActionable:
    """Tests for zero-actionable stop condition."""

    def test_stops_when_zero_actionable(self):
        # Use a high previous score with CRITICAL so convergence doesn't fire first
        state = _make_state(
            runs=[{"score": 80.0, "cost": 60.0, "critical": 1}],
            total_cost=60.0,
            current_run=1,
        )
        # Only LOW and REQUIRES_HUMAN findings (zero actionable)
        findings = [
            _make_finding(Severity.LOW),
            _make_finding(Severity.REQUIRES_HUMAN),
            _make_finding(Severity.ACCEPTABLE_DEVIATION),
        ]
        # Score jumped significantly (80→95) so convergence won't fire
        report = _make_report(score=95.0, findings=findings)
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "STOP"
        assert "COMPLETE" in decision.reason

    def test_continues_when_actionable_remain(self):
        state = _make_state(
            runs=[{"score": 85.0, "cost": 60.0}],
            total_cost=60.0,
            current_run=1,
        )
        findings = [_make_finding(Severity.HIGH)]
        report = _make_report(score=90.0, findings=findings)
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "CONTINUE"


# ---------------------------------------------------------------------------
# Stop Condition: Budget
# ---------------------------------------------------------------------------


class TestBudget:
    """Tests for budget stop condition."""

    def test_stops_when_budget_exceeded(self):
        state = _make_state(
            runs=[{"score": 80.0, "cost": 60.0}],
            total_cost=180.0,
            current_run=2,
            max_budget=180.0,
        )
        report = _make_report(score=90.0, high=3)
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "STOP"
        assert "BUDGET" in decision.reason

    def test_continues_under_budget(self):
        state = _make_state(
            runs=[{"score": 80.0, "cost": 60.0}],
            total_cost=120.0,
            current_run=2,
            max_budget=300.0,
        )
        report = _make_report(score=90.0, high=3)
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "CONTINUE"


# ---------------------------------------------------------------------------
# Stop Condition: Max Iterations
# ---------------------------------------------------------------------------


class TestMaxIterations:
    """Tests for max iterations stop condition."""

    def test_stops_at_max(self):
        state = _make_state(
            runs=[
                {"score": 80.0, "cost": 60.0},
                {"score": 88.0, "cost": 70.0},
                {"score": 92.0, "cost": 65.0},
                {"score": 93.0, "cost": 55.0},
            ],
            total_cost=250.0,
            current_run=4,
            max_iterations=4,
            max_budget=999.0,  # High budget so budget check doesn't fire first
        )
        report = _make_report(score=94.0, high=1)
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "STOP"
        assert "MAX ITERATIONS" in decision.reason

    def test_continues_before_max(self):
        state = _make_state(
            runs=[{"score": 80.0, "cost": 60.0}],
            total_cost=60.0,
            current_run=1,
            max_iterations=4,
        )
        report = _make_report(score=90.0, high=3)
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "CONTINUE"


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Tests for the three-level circuit breaker."""

    def test_level_0_no_issues(self):
        state = _make_state(
            runs=[{"score": 80.0}],
            current_run=1,
        )
        report = _make_report(score=90.0)
        level, reason = _check_circuit_breaker(state, report)
        assert level == 0

    def test_level_1_score_dropped(self):
        state = _make_state(
            runs=[{"score": 90.0}],
            current_run=1,
        )
        report = _make_report(score=88.0)
        level, reason = _check_circuit_breaker(state, report)
        assert level == 1
        assert "dropped" in reason.lower()

    def test_level_2_consecutive_drops(self):
        state = _make_state(
            runs=[
                {"score": 90.0},
                {"score": 88.0},
            ],
            current_run=2,
        )
        report = _make_report(score=86.0)
        level, reason = _check_circuit_breaker(state, report)
        assert level == 2

    def test_level_3_regression_spiral(self):
        state = _make_state(
            runs=[{"score": 80.0, "passed_acs": 80}],
            current_run=1,
        )
        report = _make_report(score=78.0, passed=78, regressions=["AC-1", "AC-2", "AC-3"])
        level, reason = _check_circuit_breaker(state, report)
        assert level == 3

    def test_level_2_stops_loop(self):
        state = _make_state(
            runs=[
                {"score": 90.0, "cost": 60.0},
                {"score": 88.0, "cost": 70.0},
            ],
            total_cost=130.0,
            current_run=2,
        )
        report = _make_report(score=86.0, high=2)
        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "STOP"
        assert "CIRCUIT BREAKER" in decision.reason


# ---------------------------------------------------------------------------
# Finding Triage
# ---------------------------------------------------------------------------


class TestFindingTriage:
    """Tests for _triage_findings()."""

    def test_critical_always_included(self):
        findings = [
            _make_finding(Severity.CRITICAL),
            _make_finding(Severity.LOW),
        ]
        fix, deferred = _triage_findings(findings, 50.0)
        assert len(fix) == 1
        assert fix[0].severity == Severity.CRITICAL
        assert len(deferred) == 1

    def test_respects_budget(self):
        findings = [_make_finding(Severity.HIGH, effort="large") for _ in range(20)]
        fix, deferred = _triage_findings(findings, 30.0)
        # Should cap based on budget
        assert len(fix) < 20

    def test_caps_at_max_findings(self):
        findings = [_make_finding(Severity.HIGH) for _ in range(20)]
        fix, deferred = _triage_findings(findings, 999.0)
        assert len(fix) <= 100

    def test_low_always_deferred(self):
        findings = [_make_finding(Severity.LOW)]
        fix, deferred = _triage_findings(findings, 999.0)
        assert len(fix) == 0
        assert len(deferred) == 1


# ---------------------------------------------------------------------------
# Cost Estimation
# ---------------------------------------------------------------------------


class TestCostEstimation:
    """Tests for estimate_fix_cost()."""

    def test_code_fix_small(self):
        cost = estimate_fix_cost([_make_finding(category=FindingCategory.CODE_FIX, effort="small")])
        assert cost == 3.0  # base 3.0 × mult 1.0

    def test_missing_feature_large(self):
        cost = estimate_fix_cost([_make_finding(category=FindingCategory.MISSING_FEATURE, effort="large")])
        assert cost == 20.0  # base 8.0 × mult 2.5

    def test_multiple_findings(self):
        findings = [
            _make_finding(category=FindingCategory.CODE_FIX, effort="small"),
            _make_finding(category=FindingCategory.SECURITY, effort="medium"),
        ]
        cost = estimate_fix_cost(findings)
        assert cost == 3.0 + 7.5  # 3×1.0 + 5×1.5


# ---------------------------------------------------------------------------
# LoopState Serialization
# ---------------------------------------------------------------------------


class TestLoopStateSerialization:
    """Tests for LoopState to_dict/from_dict/save/load."""

    def test_roundtrip(self):
        state = _make_state(
            runs=[{"score": 84.6, "cost": 62.0, "run_number": 1}],
            total_cost=62.0,
            current_run=1,
        )
        data = state.to_dict()
        json_str = json.dumps(data)
        restored = LoopState.from_dict(json.loads(json_str))

        assert restored.current_run == 1
        assert restored.total_cost == 62.0
        assert len(restored.runs) == 1
        assert restored.runs[0].score == 84.6

    def test_save_and_load(self, tmp_path):
        state = _make_state(
            runs=[{"score": 84.6, "cost": 62.0}],
            total_cost=62.0,
            current_run=1,
        )
        state.save(tmp_path)
        loaded = LoopState.load(tmp_path)
        assert loaded is not None
        assert loaded.current_run == 1
        assert loaded.total_cost == 62.0

    def test_load_missing_file(self, tmp_path):
        assert LoopState.load(tmp_path) is None
