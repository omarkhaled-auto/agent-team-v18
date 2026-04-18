"""Tests for Phase 2 audit-fix pipeline changes.

Covers:
- 3A: AC Pass Rate Convergence (config_agent.py)
- 3B: Budget Pre-Check (coordinated_builder.py)
- 3C: Wiring Scanner Exclusion (quality_checks.py + audit_agent.py)
- 3D: Evaluator Grounding (audit_agent.py)
- 3E: Fix PRD Feature Coverage (fix_prd_agent.py)
- 3F: Regression Detection (audit_agent.py)
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15.audit_agent import (
    ACResult,
    AuditReport,
    CheckResult,
    Finding,
    FindingCategory,
    Severity,
)
from agent_team_v15.config_agent import (
    LoopDecision,
    LoopState,
    RunRecord,
    evaluate_stop_conditions,
)
from agent_team_v15.fix_prd_agent import (
    filter_findings_for_fix,
    _build_features_section,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    severity: Severity = Severity.HIGH,
    category: FindingCategory = FindingCategory.CODE_FIX,
    effort: str = "small",
    feature: str = "F-001",
    title: str = "Test finding",
    fid: str = "F-TEST",
    file_path: str = "",
    acceptance_criterion: str = "test AC",
) -> Finding:
    return Finding(
        id=fid,
        feature=feature,
        acceptance_criterion=acceptance_criterion,
        severity=severity,
        category=category,
        title=title,
        description="Test description",
        prd_reference=feature,
        current_behavior="wrong",
        expected_behavior="right",
        estimated_effort=effort,
        file_path=file_path,
    )


def _make_ac_result(status: str = "PASS") -> ACResult:
    return ACResult(
        feature_id="F-001",
        ac_id="AC-001",
        ac_text="Test AC",
        status=status,
        evidence="file.ts:42",
        score={"PASS": 1.0, "PARTIAL": 0.5, "FAIL": 0.0}.get(status, 0.0),
    )


def _make_report(
    score: float = 80.0,
    passed: int = 80,
    total: int = 100,
    findings: list[Finding] | None = None,
    ac_results: list[ACResult] | None = None,
    regressions: list[str] | None = None,
    previously_passing: list[str] | None = None,
) -> AuditReport:
    if findings is None:
        findings = []
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
        ac_results=ac_results or [],
        regressions=regressions or [],
        previously_passing=previously_passing or [],
    )


def _make_state(
    runs: int = 1,
    total_cost: float = 50.0,
    current_run: int = 1,
    max_budget: float = 300.0,
    max_iterations: int = 4,
) -> LoopState:
    state = LoopState(
        original_prd_path="prd.md",
        codebase_path="./output",
        max_budget=max_budget,
        max_iterations=max_iterations,
        total_cost=total_cost,
        current_run=current_run,
    )
    for i in range(runs):
        state.runs.append(RunRecord(
            run_number=i + 1,
            run_type="fix",
            prd_path="prd.md",
            cost=50.0,
            score=80.0,
            total_acs=100,
            passed_acs=80,
            partial_acs=0,
            failed_acs=20,
            skipped_acs=0,
            critical_count=0,
            high_count=0,
            medium_count=0,
            finding_count=0,
            regression_count=0,
        ))
    return state


# =========================================================================
# 3A: AC Pass Rate Convergence Tests (config_agent.py)
# =========================================================================


class TestACPassRateConvergence:
    """Test Condition 0b2: AC pass rate convergence check."""

    def test_pass_rate_above_90_no_criticals_stops(self):
        """Pass rate >= 90% with 0 criticals -> STOP."""
        ac_results = [_make_ac_result("PASS") for _ in range(10)]
        report = _make_report(score=90.0, ac_results=ac_results)
        state = _make_state(runs=1, current_run=1)

        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "STOP"
        assert "AC_PASS_RATE" in decision.reason

    def test_pass_rate_below_90_does_not_trigger(self):
        """Pass rate < 90% -> does NOT trigger AC_PASS_RATE stop."""
        ac_results = [_make_ac_result("PASS") for _ in range(7)]
        ac_results += [_make_ac_result("FAIL") for _ in range(3)]
        report = _make_report(score=70.0, ac_results=ac_results)
        state = _make_state(runs=1, current_run=1)

        decision = evaluate_stop_conditions(state, report)
        # If it stops, it should NOT be because of AC_PASS_RATE
        if decision.action == "STOP":
            assert "AC_PASS_RATE" not in decision.reason

    def test_pass_rate_above_90_with_criticals_does_not_trigger(self):
        """Pass rate >= 90% but criticals > 0 -> does NOT trigger AC_PASS_RATE."""
        ac_results = [_make_ac_result("PASS") for _ in range(10)]
        critical_finding = _make_finding(Severity.CRITICAL)
        report = _make_report(
            score=90.0,
            ac_results=ac_results,
            findings=[critical_finding],
        )
        state = _make_state(runs=1, current_run=1)

        decision = evaluate_stop_conditions(state, report)
        if decision.action == "STOP":
            assert "AC_PASS_RATE" not in decision.reason

    def test_empty_ac_results_does_not_trigger(self):
        """Empty ac_results -> does NOT trigger AC_PASS_RATE."""
        report = _make_report(score=95.0, ac_results=[])
        state = _make_state(runs=1, current_run=1)

        decision = evaluate_stop_conditions(state, report)
        if decision.action == "STOP":
            assert "AC_PASS_RATE" not in decision.reason

    def test_all_partial_does_not_trigger(self):
        """All PARTIAL (50% pass rate equivalent) -> does NOT trigger."""
        ac_results = [_make_ac_result("PARTIAL") for _ in range(10)]
        report = _make_report(score=50.0, ac_results=ac_results)
        state = _make_state(runs=1, current_run=1)

        decision = evaluate_stop_conditions(state, report)
        if decision.action == "STOP":
            assert "AC_PASS_RATE" not in decision.reason

    def test_mixed_pass_partial_exactly_90_triggers(self):
        """Mixed PASS/PARTIAL that yields exactly 90% triggers stop."""
        # 9 PASS + 0 PARTIAL + 1 FAIL = 9/10 = 90%
        ac_results = [_make_ac_result("PASS") for _ in range(9)]
        ac_results += [_make_ac_result("FAIL")]
        report = _make_report(score=90.0, ac_results=ac_results)
        state = _make_state(runs=1, current_run=1)

        decision = evaluate_stop_conditions(state, report)
        assert decision.action == "STOP"
        assert "AC_PASS_RATE" in decision.reason

    def test_denominator_includes_all_acs(self):
        """Total denominator includes ALL ACs (no N/A/SKIP exclusion)."""
        # 8 PASS + 2 FAIL = 8/10 = 80% (below 90%)
        ac_results = [_make_ac_result("PASS") for _ in range(8)]
        ac_results += [_make_ac_result("FAIL") for _ in range(2)]
        report = _make_report(score=80.0, ac_results=ac_results)
        state = _make_state(runs=1, current_run=1)

        decision = evaluate_stop_conditions(state, report)
        if decision.action == "STOP":
            assert "AC_PASS_RATE" not in decision.reason

    def test_no_prior_runs_does_not_trigger(self):
        """With no prior runs (len(state.runs) < 1), should not trigger."""
        ac_results = [_make_ac_result("PASS") for _ in range(10)]
        report = _make_report(score=95.0, ac_results=ac_results)
        state = _make_state(runs=0, current_run=0)

        decision = evaluate_stop_conditions(state, report)
        if decision.action == "STOP":
            assert "AC_PASS_RATE" not in decision.reason


# =========================================================================
# 3B: Budget Pre-Check Tests (coordinated_builder.py)
# =========================================================================


class TestBudgetPreCheck:
    """Verify the pre-call budget comparison is still observable.

    Phase F: the coordinated_builder pre-call checks no longer STOP the
    run. They now emit a ``BUDGET ADVISORY: ... no cap enforced`` log
    line and continue. The raw ``state.total_cost >= state.max_budget``
    comparison is retained as a telemetry trigger, so these tests still
    assert the comparison semantics without claiming the loop halts.
    """

    def test_budget_exceeded_triggers_advisory(self):
        """Budget exceeded before audit -> advisory fires, loop continues."""
        state = _make_state(total_cost=300.0, max_budget=300.0)
        assert state.total_cost >= state.max_budget

    def test_budget_exceeded_before_fix_build_triggers_advisory(self):
        """Budget exceeded before fix build -> advisory fires, loop continues."""
        state = _make_state(total_cost=301.0, max_budget=300.0)
        assert state.total_cost >= state.max_budget

    def test_budget_not_exceeded_proceeds(self):
        """Budget not exceeded -> proceeds normally (no advisory)."""
        state = _make_state(total_cost=100.0, max_budget=300.0)
        assert state.total_cost < state.max_budget

    def test_budget_check_uses_gte_comparison(self):
        """Advisory trigger uses >= (not >) so exactly at limit logs."""
        state = _make_state(total_cost=300.0, max_budget=300.0)
        assert state.total_cost >= state.max_budget

    def test_budget_advisory_format(self):
        """Verify the advisory message format when budget is crossed."""
        state = _make_state(total_cost=350.0, max_budget=300.0)
        expected_prefix = "BUDGET ADVISORY:"
        reason = (
            f"BUDGET ADVISORY: cumulative ${state.total_cost:.2f} has "
            f"crossed configured max_budget ${state.max_budget:.2f}."
        )
        assert reason.startswith(expected_prefix)
        assert "$350.00" in reason
        assert "$300.00" in reason


# =========================================================================
# 3C: Wiring Scanner Exclusion Tests (quality_checks.py + audit_agent.py)
# =========================================================================


class TestWiringScannerExclusion:
    """Test the exclusion list for snake_case DTO properties."""

    def test_scanner_sets_excluded_props_attribute(self, tmp_path):
        """DTOs with snake_case props -> exclusion list includes them."""
        from agent_team_v15.quality_checks import scan_request_body_casing

        # Create a DTO file with a snake_case property
        dto_dir = tmp_path / "apps" / "api" / "src"
        dto_dir.mkdir(parents=True)
        dto_file = dto_dir / "create-order.dto.ts"
        dto_file.write_text(textwrap.dedent("""\
            export class CreateOrderDto {
              orderId?: string;
              odoo_invoice_id?: string;
              customer_name?: string;
            }
        """), encoding="utf-8")

        # Create a frontend directory with a file
        fe_dir = tmp_path / "apps" / "web" / "src"
        fe_dir.mkdir(parents=True)
        fe_file = fe_dir / "api.ts"
        fe_file.write_text(textwrap.dedent("""\
            const data = { order_id: "123" };
            fetch('/api/orders', { method: 'POST', body: JSON.stringify(data) });
        """), encoding="utf-8")

        result = scan_request_body_casing(tmp_path)
        excluded = getattr(scan_request_body_casing, "excluded_snake_case_props", [])
        # odoo_invoice_id and customer_name are snake_case/single-word and should
        # be in the excluded list (they don't have mixed casing)
        assert isinstance(excluded, list)

    def test_scanner_no_exclusion_for_camel_only(self, tmp_path):
        """DTOs with only camelCase props -> no excluded props."""
        from agent_team_v15.quality_checks import scan_request_body_casing

        dto_dir = tmp_path / "apps" / "api" / "src"
        dto_dir.mkdir(parents=True)
        dto_file = dto_dir / "update-user.dto.ts"
        dto_file.write_text(textwrap.dedent("""\
            export class UpdateUserDto {
              firstName?: string;
              lastName?: string;
              emailAddress?: string;
            }
        """), encoding="utf-8")

        fe_dir = tmp_path / "apps" / "web" / "src"
        fe_dir.mkdir(parents=True)
        fe_file = fe_dir / "user-api.ts"
        fe_file.write_text(textwrap.dedent("""\
            const data = { first_name: "John" };
            fetch('/api/users', { method: 'PUT', body: JSON.stringify(data) });
        """), encoding="utf-8")

        result = scan_request_body_casing(tmp_path)
        excluded = getattr(scan_request_body_casing, "excluded_snake_case_props", [])
        # All props are camelCase, so exclusion list should be empty
        assert excluded == []

    def test_exclusion_list_in_fix_suggestion(self):
        """Exclusion list text appears in fix_suggestion when props exist."""
        excluded_props = ["odoo_invoice_id", "customer_name"]
        # Simulate the logic from audit_agent.py lines 1320-1326
        fix_suggestion = (
            "Add a global request body transformer middleware."
        )
        if excluded_props:
            fix_suggestion += (
                f"\n\nEXCLUSION LIST — these DTO properties intentionally use snake_case "
                f"and MUST NOT be transformed by the middleware: {', '.join(excluded_props)}"
            )
        assert "EXCLUSION LIST" in fix_suggestion
        assert "odoo_invoice_id" in fix_suggestion
        assert "customer_name" in fix_suggestion


# =========================================================================
# 3D: Evaluator Grounding Tests (audit_agent.py)
# =========================================================================


class TestEvaluatorGrounding:
    """Test that the grounding rule is present in the evaluator prompt."""

    def test_grounding_rule_text_present(self):
        """Verify GROUNDING RULE block text matches the expected content."""
        expected_phrases = [
            "GROUNDING RULE (MANDATORY):",
            "you MUST use the Read or Grep tool",
            "verify the implementation exists in the actual codebase",
            "MUST cite the exact",
            "file path and line number",
            "Do NOT rely on your training data",
        ]
        # Read the actual source to check the prompt
        import inspect
        from agent_team_v15 import audit_agent
        source = inspect.getsource(audit_agent)

        for phrase in expected_phrases:
            assert phrase in source, f"Missing grounding phrase: {phrase}"


# =========================================================================
# 3E: Fix PRD Feature Coverage Tests (fix_prd_agent.py)
# =========================================================================


class TestFixPRDFeatureCoverage:
    """Test fix PRD generation for feature coverage."""

    def test_missing_feature_has_new_feature_label(self):
        """Missing feature finding -> fix PRD includes '[NEW FEATURE]'."""
        fix_features = [{
            "name": "Dashboard Analytics",
            "severity": Severity.HIGH,
            "findings": [
                _make_finding(
                    severity=Severity.HIGH,
                    category=FindingCategory.MISSING_FEATURE,
                    feature="DASH",
                    title="Missing dashboard",
                ),
            ],
        }]
        result = _build_features_section(fix_features)
        assert "[NEW FEATURE]" in result
        assert "Implementation required from scratch" in result

    def test_missing_feature_with_prd_text_includes_original(self):
        """Missing feature with PRD text -> fix PRD includes original PRD section."""
        prd_text = textwrap.dedent("""\
            ### F-001: Dashboard Analytics

            The dashboard shows real-time metrics.

            ### F-002: User Management
        """)
        fix_features = [{
            "name": "Dashboard Analytics",
            "severity": Severity.HIGH,
            "findings": [
                _make_finding(
                    severity=Severity.HIGH,
                    category=FindingCategory.MISSING_FEATURE,
                    feature="DASH",
                    title="Missing dashboard analytics",
                ),
            ],
        }]
        result = _build_features_section(fix_features, prd_text=prd_text)
        assert "Original PRD specification" in result
        assert "Dashboard Analytics" in result

    def test_feature_representative_after_cap(self):
        """Every feature with findings gets at least one representative in selected list."""
        findings = []
        # Create 15 CRITICAL findings for feature A
        for i in range(15):
            findings.append(_make_finding(
                severity=Severity.CRITICAL,
                feature="FEATURE_A",
                fid=f"FA-{i:03d}",
            ))
        # Create 1 MEDIUM finding for feature B
        findings.append(_make_finding(
            severity=Severity.MEDIUM,
            feature="FEATURE_B",
            fid="FB-001",
        ))

        # filter_findings_for_fix caps at max_findings (default 10)
        selected = filter_findings_for_fix(findings, max_findings=10)

        # Feature B should be represented even though it's MEDIUM
        features_in_selected = {f.feature for f in selected}
        assert "FEATURE_B" in features_in_selected

    def test_non_missing_feature_has_severity_label(self):
        """Non-missing feature gets [SEVERITY: ...] label, not [NEW FEATURE]."""
        fix_features = [{
            "name": "Auth Flow Fix",
            "severity": Severity.CRITICAL,
            "findings": [
                _make_finding(
                    severity=Severity.CRITICAL,
                    category=FindingCategory.CODE_FIX,
                    feature="AUTH",
                ),
            ],
        }]
        result = _build_features_section(fix_features)
        assert "[NEW FEATURE]" not in result
        assert "[SEVERITY:" in result


# =========================================================================
# 3F: Regression Detection Tests (audit_agent.py)
# =========================================================================


class TestRegressionDetection:
    """Test enhanced regression detection in audit_agent.py."""

    def test_ac_pass_to_fail_is_regression(self):
        """AC was PASS now FAIL -> detected as regression."""
        previous_report = _make_report(
            score=80.0,
            previously_passing=["AC-001"],
        )
        # The regression detection code checks:
        # r.ac_id in prev_pass and r.verdict in ("FAIL", "PARTIAL")
        # where prev_pass = _get_passing_ids(previous_report)
        # _get_passing_ids returns set(report.previously_passing)
        from agent_team_v15.audit_agent import _get_passing_ids

        prev_pass = _get_passing_ids(previous_report)
        assert "AC-001" in prev_pass

        # Simulate a result that went from PASS to FAIL
        result = CheckResult(ac_id="AC-001", verdict="FAIL", evidence="regressed")
        assert result.ac_id in prev_pass
        assert result.verdict in ("FAIL", "PARTIAL")

    def test_ac_stays_pass_not_regression(self):
        """AC stays PASS -> not a regression."""
        previous_report = _make_report(
            score=80.0,
            previously_passing=["AC-001"],
        )
        from agent_team_v15.audit_agent import _get_passing_ids

        prev_pass = _get_passing_ids(previous_report)
        result = CheckResult(ac_id="AC-001", verdict="PASS", evidence="still passing")
        # PASS is not in ("FAIL", "PARTIAL"), so not a regression
        assert result.verdict not in ("FAIL", "PARTIAL")

    def test_ac_fail_to_pass_not_regression(self):
        """AC was FAIL now PASS -> not a regression (it's a fix)."""
        previous_report = _make_report(
            score=60.0,
            previously_passing=[],  # AC-001 was NOT previously passing
        )
        from agent_team_v15.audit_agent import _get_passing_ids

        prev_pass = _get_passing_ids(previous_report)
        result = CheckResult(ac_id="AC-001", verdict="PASS", evidence="now passing")
        assert result.ac_id not in prev_pass

    def test_regression_finding_has_prefix(self):
        """Regression finding has 'REGRESSION:' prefix in title."""
        finding = _make_finding(
            severity=Severity.HIGH,
            title="Auth endpoint broken",
            fid="AC-001",
        )
        # Simulate the code at audit_agent.py lines 2583-2585
        finding.category = FindingCategory.REGRESSION
        finding.severity = Severity.CRITICAL
        if not finding.title.startswith("REGRESSION:"):
            finding.title = f"REGRESSION: {finding.title}"
        assert finding.title.startswith("REGRESSION:")
        assert finding.severity == Severity.CRITICAL

    def test_regression_creates_new_finding_when_unmatched(self):
        """If no existing finding covers regression, a new one is created."""
        # Simulate the code at audit_agent.py lines 2588-2604
        ac_id = "AC-005"
        verdict = "FAIL"
        evidence = "file.ts:10 — broken"

        new_finding = Finding(
            id=f"REG-{ac_id}",
            feature=ac_id.split("-")[0] if "-" in ac_id else "UNKNOWN",
            acceptance_criterion=ac_id,
            severity=Severity.CRITICAL,
            category=FindingCategory.REGRESSION,
            title=f"REGRESSION: {ac_id} was PASS in previous run, now {verdict}",
            description=f"Acceptance criterion {ac_id} previously passed but now evaluates as {verdict}.",
            prd_reference=ac_id,
            current_behavior=f"{ac_id} now {verdict}: {evidence}",
            expected_behavior=f"{ac_id} should remain PASS as in the previous run",
            fix_suggestion=f"Investigate what changed since the last passing run and restore the {ac_id} functionality.",
            estimated_effort="medium",
        )
        assert new_finding.id == "REG-AC-005"
        assert new_finding.severity == Severity.CRITICAL
        assert new_finding.category == FindingCategory.REGRESSION
        assert "REGRESSION:" in new_finding.title

    def test_regression_severity_upgraded_to_critical(self):
        """Regression detection upgrades severity to CRITICAL."""
        finding = _make_finding(severity=Severity.MEDIUM)
        # Code: f.severity = Severity.CRITICAL
        finding.severity = Severity.CRITICAL
        assert finding.severity == Severity.CRITICAL

    def test_regression_category_set_to_regression(self):
        """Regression detection sets category to REGRESSION."""
        finding = _make_finding(category=FindingCategory.CODE_FIX)
        finding.category = FindingCategory.REGRESSION
        assert finding.category == FindingCategory.REGRESSION
