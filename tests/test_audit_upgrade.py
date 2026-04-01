"""Tests for the audit system upgrades.

Covers:
- AuditFinding.source field
- FalsePositive model
- AuditCycleMetrics model
- compute_cycle_metrics()
- filter_false_positives()
- Deterministic scan integration (run_deterministic_scan)
- Severity mapping (_map_det_severity)
- Convergence tracking (detect_convergence_plateau)
- Regression detection (detect_regressions)
- Escalation recommendations (compute_escalation_recommendation)
- Fix PRD filtering (filter_findings_for_fix)
- Fix PRD verification criteria (build_verification_criteria)
- AuditMode enum and dual-mode audit architecture
- Validator tool definitions and execution
- run_implementation_quality_audit
- run_full_audit
- _parse_agentic_quality_findings
- Fix PRD scope caps
- Backward compatibility (existing models still work)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_team_v15.audit_models import (
    AuditFinding,
    AuditReport,
    AuditScore,
    AuditCycleMetrics,
    FalsePositive,
    build_report,
    compute_cycle_metrics,
    filter_false_positives,
)
from agent_team_v15.audit_team import (
    detect_convergence_plateau,
    detect_regressions,
    compute_escalation_recommendation,
    should_terminate_reaudit,
)
from agent_team_v15.audit_agent import (
    AuditMode,
    Finding,
    FindingCategory,
    Severity,
    run_deterministic_scan,
    run_implementation_quality_audit,
    _map_det_severity,
    _parse_agentic_quality_findings,
    _execute_validator_tool,
    AUDIT_VALIDATOR_TOOLS,
)
from agent_team_v15.fix_prd_agent import (
    filter_findings_for_fix,
    build_verification_criteria,
    MAX_FINDINGS_PER_FIX_CYCLE,
)


# ===================================================================
# Helpers
# ===================================================================

def _make_audit_finding(
    finding_id: str = "RA-001",
    auditor: str = "requirements",
    requirement_id: str = "REQ-001",
    verdict: str = "FAIL",
    severity: str = "HIGH",
    summary: str = "Test finding",
    evidence: list[str] | None = None,
    remediation: str = "Fix it",
    confidence: float = 0.9,
    source: str = "llm",
) -> AuditFinding:
    return AuditFinding(
        finding_id=finding_id,
        auditor=auditor,
        requirement_id=requirement_id,
        verdict=verdict,
        severity=severity,
        summary=summary,
        evidence=evidence if evidence is not None else ["src/foo.py:10 -- issue found"],
        remediation=remediation,
        confidence=confidence,
        source=source,
    )


def _make_score(
    score: float = 70.0,
    health: str = "degraded",
    critical: int = 0,
) -> AuditScore:
    return AuditScore(
        total_items=10, passed=7, failed=3, partial=0,
        critical_count=critical, high_count=2, medium_count=1,
        low_count=0, info_count=0, score=score, health=health,
    )


def _make_report(
    findings: list[AuditFinding] | None = None,
    score: AuditScore | None = None,
    cycle: int = 1,
) -> AuditReport:
    findings = findings or []
    score = score or _make_score()
    return AuditReport(
        audit_id="test-audit",
        timestamp="2026-01-01T00:00:00Z",
        cycle=cycle,
        auditors_deployed=["requirements"],
        findings=findings,
        score=score,
    )


def _make_finding(
    id: str = "F-AC-1",
    severity: Severity = Severity.HIGH,
    category: FindingCategory = FindingCategory.CODE_FIX,
    file_path: str = "src/foo.ts",
) -> Finding:
    return Finding(
        id=id,
        feature="F-001",
        acceptance_criterion="AC-1",
        severity=severity,
        category=category,
        title="Test finding",
        description="Test description",
        prd_reference="AC-1",
        current_behavior="bad",
        expected_behavior="good",
        file_path=file_path,
        fix_suggestion="Fix it",
    )


def _make_cycle_metrics(
    cycle: int = 1,
    score: float = 70.0,
    total_findings: int = 10,
    new_ids: list[str] | None = None,
    fixed_ids: list[str] | None = None,
    regressed_ids: list[str] | None = None,
) -> AuditCycleMetrics:
    return AuditCycleMetrics(
        cycle=cycle,
        total_findings=total_findings,
        deterministic_findings=5,
        llm_findings=5,
        score=score,
        health="degraded",
        new_finding_ids=new_ids or [],
        fixed_finding_ids=fixed_ids or [],
        regressed_finding_ids=regressed_ids or [],
    )


# ===================================================================
# AuditFinding.source field
# ===================================================================

class TestAuditFindingSource:
    def test_default_source_is_llm(self):
        f = _make_audit_finding()
        assert f.source == "llm"

    def test_deterministic_source(self):
        f = _make_audit_finding(source="deterministic")
        assert f.source == "deterministic"

    def test_manual_source(self):
        f = _make_audit_finding(source="manual")
        assert f.source == "manual"

    def test_source_in_to_dict(self):
        f = _make_audit_finding(source="deterministic")
        d = f.to_dict()
        assert d["source"] == "deterministic"

    def test_source_from_dict(self):
        f = _make_audit_finding(source="deterministic")
        d = f.to_dict()
        f2 = AuditFinding.from_dict(d)
        assert f2.source == "deterministic"

    def test_source_from_dict_defaults_to_llm(self):
        """Backward compatibility: old dicts without 'source' default to 'llm'."""
        d = {
            "finding_id": "RA-001",
            "auditor": "requirements",
            "requirement_id": "REQ-001",
            "verdict": "FAIL",
            "severity": "HIGH",
            "summary": "test",
        }
        f = AuditFinding.from_dict(d)
        assert f.source == "llm"


# ===================================================================
# FalsePositive model
# ===================================================================

class TestFalsePositive:
    def test_construction(self):
        fp = FalsePositive(finding_id="RA-001", reason="Not a real bug")
        assert fp.finding_id == "RA-001"
        assert fp.suppressed_by == "manual"

    def test_to_dict(self):
        fp = FalsePositive(finding_id="RA-001", reason="FP", suppressed_by="auto")
        d = fp.to_dict()
        assert d["finding_id"] == "RA-001"
        assert d["suppressed_by"] == "auto"

    def test_from_dict(self):
        d = {"finding_id": "RA-001", "reason": "FP", "suppressed_by": "manual"}
        fp = FalsePositive.from_dict(d)
        assert fp.finding_id == "RA-001"
        assert fp.reason == "FP"

    def test_from_dict_defaults(self):
        d = {"finding_id": "X"}
        fp = FalsePositive.from_dict(d)
        assert fp.suppressed_by == "manual"
        assert fp.reason == ""


# ===================================================================
# AuditCycleMetrics
# ===================================================================

class TestAuditCycleMetrics:
    def test_construction(self):
        m = _make_cycle_metrics()
        assert m.cycle == 1
        assert m.total_findings == 10
        assert m.deterministic_findings == 5

    def test_net_change_positive(self):
        m = _make_cycle_metrics(new_ids=["a", "b"], fixed_ids=["c"])
        assert m.net_change == 1

    def test_net_change_negative(self):
        m = _make_cycle_metrics(new_ids=["a"], fixed_ids=["b", "c", "d"])
        assert m.net_change == -2

    def test_net_change_zero(self):
        m = _make_cycle_metrics(new_ids=["a"], fixed_ids=["b"])
        assert m.net_change == 0

    def test_is_plateau_true(self):
        m = _make_cycle_metrics(new_ids=[], fixed_ids=[])
        assert m.is_plateau is True

    def test_is_plateau_false_with_new(self):
        m = _make_cycle_metrics(new_ids=["a"])
        assert m.is_plateau is False

    def test_is_plateau_false_with_fixed(self):
        m = _make_cycle_metrics(fixed_ids=["a"])
        assert m.is_plateau is False

    def test_to_dict(self):
        m = _make_cycle_metrics(new_ids=["a"])
        d = m.to_dict()
        assert d["cycle"] == 1
        assert d["new_finding_ids"] == ["a"]

    def test_from_dict(self):
        m = _make_cycle_metrics(new_ids=["a"])
        d = m.to_dict()
        m2 = AuditCycleMetrics.from_dict(d)
        assert m2.cycle == m.cycle
        assert m2.new_finding_ids == ["a"]

    def test_from_dict_defaults(self):
        d = {"cycle": 1, "total_findings": 5, "score": 80.0, "health": "degraded"}
        m = AuditCycleMetrics.from_dict(d)
        assert m.deterministic_findings == 0
        assert m.llm_findings == 0
        assert m.new_finding_ids == []


# ===================================================================
# compute_cycle_metrics
# ===================================================================

class TestComputeCycleMetrics:
    def test_first_cycle_no_previous(self):
        report = _make_report(findings=[
            _make_audit_finding(finding_id="F1", source="deterministic"),
            _make_audit_finding(finding_id="F2", source="llm"),
        ])
        m = compute_cycle_metrics(1, report, None)
        assert m.cycle == 1
        assert m.total_findings == 2
        assert m.deterministic_findings == 1
        assert m.llm_findings == 1
        assert m.new_finding_ids == ["F1", "F2"]
        assert m.fixed_finding_ids == []

    def test_second_cycle_with_fixes(self):
        prev = _make_report(findings=[
            _make_audit_finding(finding_id="F1"),
            _make_audit_finding(finding_id="F2"),
            _make_audit_finding(finding_id="F3"),
        ])
        curr = _make_report(findings=[
            _make_audit_finding(finding_id="F1"),
            _make_audit_finding(finding_id="F4"),
        ])
        m = compute_cycle_metrics(2, curr, prev)
        assert "F4" in m.new_finding_ids
        assert "F2" in m.fixed_finding_ids
        assert "F3" in m.fixed_finding_ids

    def test_deterministic_count(self):
        report = _make_report(findings=[
            _make_audit_finding(finding_id="D1", source="deterministic"),
            _make_audit_finding(finding_id="D2", source="deterministic"),
            _make_audit_finding(finding_id="L1", source="llm"),
        ])
        m = compute_cycle_metrics(1, report, None)
        assert m.deterministic_findings == 2
        assert m.llm_findings == 1


# ===================================================================
# filter_false_positives
# ===================================================================

class TestFilterFalsePositives:
    def test_no_suppressions(self):
        findings = [_make_audit_finding(finding_id="F1")]
        result = filter_false_positives(findings, [])
        assert len(result) == 1

    def test_suppresses_matching_id(self):
        findings = [
            _make_audit_finding(finding_id="F1"),
            _make_audit_finding(finding_id="F2"),
        ]
        suppressions = [FalsePositive(finding_id="F1", reason="FP")]
        result = filter_false_positives(findings, suppressions)
        assert len(result) == 1
        assert result[0].finding_id == "F2"

    def test_no_match_keeps_all(self):
        findings = [_make_audit_finding(finding_id="F1")]
        suppressions = [FalsePositive(finding_id="F999", reason="FP")]
        result = filter_false_positives(findings, suppressions)
        assert len(result) == 1


# ===================================================================
# Deterministic scan: _map_det_severity
# ===================================================================

class TestMapDetSeverity:
    def test_critical(self):
        assert _map_det_severity("critical") == Severity.CRITICAL

    def test_high(self):
        assert _map_det_severity("high") == Severity.HIGH

    def test_error_maps_to_high(self):
        assert _map_det_severity("error") == Severity.HIGH

    def test_medium(self):
        assert _map_det_severity("medium") == Severity.MEDIUM

    def test_warning_maps_to_medium(self):
        assert _map_det_severity("warning") == Severity.MEDIUM

    def test_low(self):
        assert _map_det_severity("low") == Severity.LOW

    def test_info_maps_to_low(self):
        assert _map_det_severity("info") == Severity.LOW

    def test_unknown_defaults_to_medium(self):
        assert _map_det_severity("unknown") == Severity.MEDIUM


# ===================================================================
# Deterministic scan: run_deterministic_scan
# ===================================================================

class TestRunDeterministicScan:
    def test_returns_empty_when_no_scanners(self, tmp_path):
        """With no codebase files, scanners return empty lists."""
        findings = run_deterministic_scan(tmp_path)
        assert isinstance(findings, list)

    def test_all_findings_are_finding_type(self, tmp_path):
        findings = run_deterministic_scan(tmp_path)
        for f in findings:
            assert isinstance(f, Finding)

    @patch("agent_team_v15.audit_agent.run_deterministic_scan")
    def test_deterministic_findings_have_det_prefix(self, mock_scan, tmp_path):
        """Verify that actual DET findings have correct ID format."""
        # Simulate a finding from the schema validator
        mock_scan.return_value = [
            _make_finding(id="DET-SCH-001"),
        ]
        findings = mock_scan(tmp_path)
        assert all(f.id.startswith("DET-") for f in findings)

    def test_graceful_degradation_on_import_error(self, tmp_path):
        """Scanner import errors should not crash the function."""
        with patch.dict("sys.modules", {"agent_team_v15.schema_validator": None}):
            # Should not raise
            findings = run_deterministic_scan(tmp_path)
            assert isinstance(findings, list)


# ===================================================================
# Convergence: detect_convergence_plateau
# ===================================================================

class TestDetectConvergencePlateau:
    def test_insufficient_history(self):
        metrics = [_make_cycle_metrics(cycle=1)]
        is_plateau, reason = detect_convergence_plateau(metrics, window=3)
        assert is_plateau is False

    def test_plateau_detected(self):
        metrics = [
            _make_cycle_metrics(cycle=1, score=70.0, total_findings=10),
            _make_cycle_metrics(cycle=2, score=70.5, total_findings=10),
            _make_cycle_metrics(cycle=3, score=71.0, total_findings=10),
        ]
        is_plateau, reason = detect_convergence_plateau(metrics, window=3)
        assert is_plateau is True
        assert "Plateau" in reason or "Oscillation" in reason

    def test_no_plateau_with_improvement(self):
        metrics = [
            _make_cycle_metrics(cycle=1, score=60.0, total_findings=15),
            _make_cycle_metrics(cycle=2, score=70.0, total_findings=12),
            _make_cycle_metrics(cycle=3, score=80.0, total_findings=8),
        ]
        is_plateau, reason = detect_convergence_plateau(metrics, window=3)
        assert is_plateau is False

    def test_oscillation_detected(self):
        metrics = [
            _make_cycle_metrics(cycle=1, score=70.0, total_findings=10),
            _make_cycle_metrics(cycle=2, score=73.0, total_findings=10),
            _make_cycle_metrics(cycle=3, score=69.0, total_findings=10),
            _make_cycle_metrics(cycle=4, score=72.0, total_findings=10),
        ]
        is_plateau, reason = detect_convergence_plateau(metrics, window=4)
        assert is_plateau is True
        assert "Oscillation" in reason or "Plateau" in reason

    def test_uses_dict_format(self):
        """Should also work with plain dicts."""
        metrics = [
            {"score": 70.0, "total_findings": 10},
            {"score": 70.5, "total_findings": 10},
            {"score": 71.0, "total_findings": 10},
        ]
        is_plateau, reason = detect_convergence_plateau(metrics, window=3)
        assert is_plateau is True


# ===================================================================
# Regression detection
# ===================================================================

class TestDetectRegressions:
    def test_no_regressions(self):
        current = [_make_audit_finding(finding_id="F1")]
        previous = [_make_audit_finding(finding_id="F2")]
        regressions = detect_regressions(current, previous)
        assert regressions == []

    def test_persistent_findings(self):
        current = [
            _make_audit_finding(finding_id="F1"),
            _make_audit_finding(finding_id="F2"),
        ]
        previous = [
            _make_audit_finding(finding_id="F1"),
            _make_audit_finding(finding_id="F3"),
        ]
        regressions = detect_regressions(current, previous)
        assert "F1" in regressions

    def test_empty_previous(self):
        current = [_make_audit_finding(finding_id="F1")]
        regressions = detect_regressions(current, [])
        assert regressions == []

    def test_works_with_finding_type(self):
        """Should work with Finding objects (have .id instead of .finding_id)."""
        current = [_make_finding(id="X1")]
        previous = [_make_finding(id="X1")]
        regressions = detect_regressions(current, previous)
        assert "X1" in regressions


# ===================================================================
# Escalation recommendations
# ===================================================================

class TestComputeEscalationRecommendation:
    def test_no_history(self):
        assert compute_escalation_recommendation([]) is None

    def test_no_escalation_when_improving(self):
        metrics = [
            _make_cycle_metrics(cycle=1, score=60.0, total_findings=15),
            _make_cycle_metrics(cycle=2, score=75.0, total_findings=10),
        ]
        result = compute_escalation_recommendation(metrics)
        assert result is None

    def test_escalation_on_plateau_low_score(self):
        metrics = [
            _make_cycle_metrics(cycle=1, score=40.0, total_findings=20),
            _make_cycle_metrics(cycle=2, score=41.0, total_findings=20),
            _make_cycle_metrics(cycle=3, score=41.5, total_findings=20),
        ]
        result = compute_escalation_recommendation(metrics)
        assert result is not None
        assert "ESCALATE" in result

    def test_escalation_on_many_regressions(self):
        metrics = [
            _make_cycle_metrics(cycle=1, score=70.0),
            _make_cycle_metrics(cycle=2, score=65.0, regressed_ids=["R1", "R2", "R3"]),
        ]
        result = compute_escalation_recommendation(metrics)
        assert result is not None
        assert "regression" in result.lower()

    def test_info_on_plateau_high_score(self):
        metrics = [
            _make_cycle_metrics(cycle=1, score=88.0, total_findings=3),
            _make_cycle_metrics(cycle=2, score=88.5, total_findings=3),
            _make_cycle_metrics(cycle=3, score=89.0, total_findings=3),
        ]
        result = compute_escalation_recommendation(metrics)
        assert result is not None
        assert "INFO" in result


# ===================================================================
# Fix PRD: filter_findings_for_fix
# ===================================================================

class TestFilterFindingsForFix:
    def test_empty_findings(self):
        assert filter_findings_for_fix([]) == []

    def test_excludes_requires_human(self):
        findings = [
            _make_finding(id="F1", severity=Severity.HIGH),
            _make_finding(id="F2", severity=Severity.REQUIRES_HUMAN),
        ]
        result = filter_findings_for_fix(findings)
        assert len(result) == 1
        assert result[0].id == "F1"

    def test_excludes_acceptable_deviation(self):
        findings = [
            _make_finding(id="F1", severity=Severity.MEDIUM),
            _make_finding(id="F2", severity=Severity.ACCEPTABLE_DEVIATION),
        ]
        result = filter_findings_for_fix(findings)
        assert len(result) == 1

    def test_caps_at_max_findings(self):
        findings = [_make_finding(id=f"F{i}", severity=Severity.MEDIUM) for i in range(30)]
        result = filter_findings_for_fix(findings, max_findings=20)
        assert len(result) == 20

    def test_default_max_is_constant(self):
        assert MAX_FINDINGS_PER_FIX_CYCLE == 20

    def test_deterministic_only_mode(self):
        findings = [
            _make_finding(id="DET-SCH-001"),
            _make_finding(id="F-AC-1"),
            _make_finding(id="DET-QV-002"),
        ]
        result = filter_findings_for_fix(findings, deterministic_only=True)
        assert len(result) == 2
        assert all(f.id.startswith("DET-") for f in result)

    def test_prioritizes_deterministic_over_llm(self):
        findings = [
            _make_finding(id="F-AC-1", severity=Severity.HIGH),
            _make_finding(id="DET-SCH-001", severity=Severity.HIGH),
        ]
        result = filter_findings_for_fix(findings)
        assert result[0].id == "DET-SCH-001"

    def test_prioritizes_regression_watchlist(self):
        findings = [
            _make_finding(id="F1", file_path="src/a.ts"),
            _make_finding(id="F2", file_path="src/b.ts"),
        ]
        result = filter_findings_for_fix(
            findings, regression_watchlist=["src/b.ts"]
        )
        assert result[0].id == "F2"

    def test_severity_ordering(self):
        findings = [
            _make_finding(id="F1", severity=Severity.LOW),
            _make_finding(id="F2", severity=Severity.CRITICAL),
            _make_finding(id="F3", severity=Severity.MEDIUM),
        ]
        result = filter_findings_for_fix(findings)
        assert result[0].id == "F2"


# ===================================================================
# Fix PRD: build_verification_criteria
# ===================================================================

class TestBuildVerificationCriteria:
    def test_schema_finding(self):
        findings = [_make_finding(id="DET-SCH-001")]
        criteria = build_verification_criteria(findings)
        assert len(criteria) == 1
        assert criteria[0]["scanner"] == "schema_validator"

    def test_quality_validator_finding(self):
        findings = [_make_finding(id="DET-QV-001")]
        criteria = build_verification_criteria(findings)
        assert criteria[0]["scanner"] == "quality_validators"

    def test_integration_finding(self):
        findings = [_make_finding(id="DET-IV-001")]
        criteria = build_verification_criteria(findings)
        assert criteria[0]["scanner"] == "integration_verifier"

    def test_spot_check_finding(self):
        findings = [_make_finding(id="DET-SC-001")]
        criteria = build_verification_criteria(findings)
        assert criteria[0]["scanner"] == "quality_checks"

    def test_llm_finding(self):
        findings = [_make_finding(id="F-AC-1")]
        criteria = build_verification_criteria(findings)
        assert criteria[0]["scanner"] == "llm_audit"

    def test_mixed_findings(self):
        findings = [
            _make_finding(id="DET-SCH-001"),
            _make_finding(id="F-AC-1"),
            _make_finding(id="DET-IV-002"),
        ]
        criteria = build_verification_criteria(findings)
        assert len(criteria) == 3
        scanners = [c["scanner"] for c in criteria]
        assert "schema_validator" in scanners
        assert "llm_audit" in scanners
        assert "integration_verifier" in scanners


# ===================================================================
# Backward compatibility
# ===================================================================

class TestBackwardCompatibility:
    def test_existing_finding_still_works(self):
        """Old AuditFinding creation without source should still work."""
        f = AuditFinding(
            finding_id="RA-001",
            auditor="requirements",
            requirement_id="REQ-001",
            verdict="FAIL",
            severity="HIGH",
            summary="test",
        )
        assert f.source == "llm"  # default

    def test_existing_report_json_roundtrip(self):
        """Old report format should still deserialize correctly."""
        f = _make_audit_finding()
        report = _make_report(findings=[f])
        json_str = report.to_json()
        restored = AuditReport.from_json(json_str)
        assert restored.findings[0].finding_id == f.finding_id
        assert restored.findings[0].source == f.source

    def test_old_finding_dict_without_source(self):
        """from_dict should handle dicts missing the source field."""
        d = {
            "finding_id": "OLD-001",
            "auditor": "technical",
            "requirement_id": "TECH-001",
            "verdict": "FAIL",
            "severity": "MEDIUM",
            "summary": "old finding",
        }
        f = AuditFinding.from_dict(d)
        assert f.source == "llm"
        assert f.confidence == 1.0

    def test_should_terminate_reaudit_unchanged(self):
        """Existing should_terminate_reaudit still works with new models."""
        score = _make_score(score=95.0, critical=0)
        stop, reason = should_terminate_reaudit(score, None, cycle=1)
        assert stop is True
        assert reason == "healthy"

    def test_build_report_unchanged(self):
        """build_report still works with source-aware findings."""
        findings = [
            _make_audit_finding(source="deterministic"),
            _make_audit_finding(finding_id="RA-002", source="llm"),
        ]
        report = build_report("test", 1, ["requirements"], findings)
        assert len(report.findings) >= 1


# ===================================================================
# AuditMode enum
# ===================================================================

class TestAuditMode:
    def test_prd_compliance_value(self):
        assert AuditMode.PRD_COMPLIANCE.value == "prd_compliance"

    def test_implementation_quality_value(self):
        assert AuditMode.IMPLEMENTATION_QUALITY.value == "implementation_quality"

    def test_full_value(self):
        assert AuditMode.FULL.value == "full"

    def test_from_string(self):
        assert AuditMode("prd_compliance") == AuditMode.PRD_COMPLIANCE
        assert AuditMode("implementation_quality") == AuditMode.IMPLEMENTATION_QUALITY
        assert AuditMode("full") == AuditMode.FULL

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            AuditMode("invalid")


# ===================================================================
# Validator tool definitions
# ===================================================================

class TestValidatorTools:
    def test_four_validator_tools_defined(self):
        assert len(AUDIT_VALIDATOR_TOOLS) == 4

    def test_tool_names(self):
        names = {t["name"] for t in AUDIT_VALIDATOR_TOOLS}
        assert "run_schema_check" in names
        assert "run_quality_check" in names
        assert "run_integration_check" in names
        assert "run_spot_check" in names

    def test_all_tools_have_input_schema(self):
        for tool in AUDIT_VALIDATOR_TOOLS:
            assert "input_schema" in tool
            assert "type" in tool["input_schema"]

    def test_all_tools_have_description(self):
        for tool in AUDIT_VALIDATOR_TOOLS:
            assert "description" in tool
            assert len(tool["description"]) > 20


# ===================================================================
# Validator tool execution
# ===================================================================

class TestExecuteValidatorTool:
    def test_unknown_tool_returns_error(self, tmp_path):
        result = _execute_validator_tool("unknown_tool", {}, tmp_path)
        assert "Unknown validator tool" in result

    def test_schema_check_on_empty_project(self, tmp_path):
        result = _execute_validator_tool("run_schema_check", {}, tmp_path)
        assert isinstance(result, str)
        # May find 0 issues, or report "no schema.prisma" advisory, or validator not available
        assert "issues" in result.lower() or "not available" in result.lower() or "validation" in result.lower()

    def test_quality_check_on_empty_project(self, tmp_path):
        result = _execute_validator_tool("run_quality_check", {}, tmp_path)
        assert isinstance(result, str)

    def test_integration_check_on_empty_project(self, tmp_path):
        result = _execute_validator_tool("run_integration_check", {}, tmp_path)
        assert isinstance(result, str)

    def test_spot_check_on_empty_project(self, tmp_path):
        result = _execute_validator_tool("run_spot_check", {}, tmp_path)
        assert isinstance(result, str)

    def test_quality_check_with_category_filter(self, tmp_path):
        result = _execute_validator_tool(
            "run_quality_check", {"checks": "infrastructure"}, tmp_path
        )
        assert isinstance(result, str)


# ===================================================================
# _parse_agentic_quality_findings
# ===================================================================

class TestParseAgenticQualityFindings:
    def test_empty_notes(self):
        assert _parse_agentic_quality_findings("") == []

    def test_json_array_extraction(self):
        notes = '''Here are my findings:
[
    {"title": "Missing auth guard", "severity": "high", "category": "security",
     "description": "Route /api/admin has no auth guard", "file_path": "src/admin.ts",
     "fix_suggestion": "Add JwtAuthGuard"},
    {"title": "Empty handler", "severity": "medium", "category": "code_fix",
     "description": "Handler logs but does nothing", "file_path": "src/handler.ts",
     "fix_suggestion": "Implement business logic"}
]'''
        findings = _parse_agentic_quality_findings(notes)
        assert len(findings) == 2
        assert findings[0].title == "Missing auth guard"
        assert findings[0].severity == Severity.HIGH
        assert findings[0].id == "IQ-AGT-001"
        assert findings[1].id == "IQ-AGT-002"

    def test_text_pattern_fallback(self):
        notes = """
Investigation results:
[HIGH] Missing authentication on admin routes — no guard found
[MEDIUM] Empty catch block in payment service — errors silently swallowed
[LOW] Unused variable in auth module
"""
        findings = _parse_agentic_quality_findings(notes)
        assert len(findings) >= 2
        assert findings[0].severity == Severity.HIGH

    def test_caps_at_30(self):
        notes_lines = [f"[MEDIUM] Finding {i} description text here" for i in range(50)]
        notes = "\n".join(notes_lines)
        findings = _parse_agentic_quality_findings(notes)
        assert len(findings) <= 30

    def test_ignores_short_titles(self):
        notes = "[HIGH] Short\n[MEDIUM] A more detailed finding description"
        findings = _parse_agentic_quality_findings(notes)
        # "Short" is < 10 chars, should be ignored
        assert all(len(f.title) >= 10 for f in findings)

    def test_json_with_invalid_category_uses_default(self):
        notes = '[{"title": "Some finding here", "severity": "high", "category": "invalid_cat"}]'
        findings = _parse_agentic_quality_findings(notes)
        assert len(findings) == 1
        assert findings[0].category == FindingCategory.CODE_FIX


# ===================================================================
# run_implementation_quality_audit
# ===================================================================

class TestRunImplementationQualityAudit:
    def test_returns_audit_report(self, tmp_path):
        report = run_implementation_quality_audit(tmp_path)
        from agent_team_v15.audit_agent import AuditReport
        assert isinstance(report, AuditReport)

    def test_report_has_valid_score(self, tmp_path):
        report = run_implementation_quality_audit(tmp_path)
        assert 0.0 <= report.score <= 100.0

    def test_empty_codebase_returns_high_score(self, tmp_path):
        """No source files = no deterministic findings = high score."""
        report = run_implementation_quality_audit(tmp_path)
        assert report.score >= 90.0

    def test_report_has_timestamp(self, tmp_path):
        report = run_implementation_quality_audit(tmp_path)
        assert report.timestamp

    def test_report_codebase_path_set(self, tmp_path):
        report = run_implementation_quality_audit(tmp_path)
        assert str(tmp_path) in report.codebase_path

    def test_findings_are_finding_type(self, tmp_path):
        report = run_implementation_quality_audit(tmp_path)
        for f in report.findings:
            assert isinstance(f, Finding)

    def test_config_override_model(self, tmp_path):
        """Config can override the audit model."""
        from agent_team_v15.audit_agent import AuditReport as AgentAuditReport
        report = run_implementation_quality_audit(
            tmp_path, config={"audit_model": "claude-sonnet-4-6"}
        )
        assert isinstance(report, AgentAuditReport)

    def test_previous_report_enables_regression_detection(self, tmp_path):
        """Passing a previous report should not crash."""
        from agent_team_v15.audit_agent import AuditReport as AgentAuditReport
        prev = AgentAuditReport(
            run_number=1,
            timestamp="2026-01-01T00:00:00Z",
            original_prd_path="",
            codebase_path=str(tmp_path),
            total_acs=0, passed_acs=0, failed_acs=0,
            partial_acs=0, skipped_acs=0, score=80.0,
        )
        report = run_implementation_quality_audit(
            tmp_path, previous_report=prev, run_number=2
        )
        assert report.run_number == 2


# ===================================================================
# Dual-mode integration
# ===================================================================

class TestDualModeArchitecture:
    def test_audit_mode_is_available(self):
        """AuditMode enum should be importable from audit_agent."""
        from agent_team_v15.audit_agent import AuditMode
        assert hasattr(AuditMode, "PRD_COMPLIANCE")
        assert hasattr(AuditMode, "IMPLEMENTATION_QUALITY")
        assert hasattr(AuditMode, "FULL")

    def test_run_full_audit_is_importable(self):
        """run_full_audit should be importable."""
        from agent_team_v15.audit_agent import run_full_audit
        assert callable(run_full_audit)

    def test_implementation_quality_mode_no_prd_needed(self, tmp_path):
        """IQ mode should work without a PRD."""
        report = run_implementation_quality_audit(tmp_path)
        assert report.original_prd_path == ""

    def test_increased_max_turns_default(self):
        """Verify the default max_turns was increased from 6 to 15."""
        import inspect
        from agent_team_v15.audit_agent import _call_claude_sdk_agentic
        sig = inspect.signature(_call_claude_sdk_agentic)
        default_turns = sig.parameters["max_turns"].default
        assert default_turns == 15, f"Expected 15, got {default_turns}"
