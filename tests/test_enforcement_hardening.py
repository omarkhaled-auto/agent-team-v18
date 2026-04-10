"""Tests for enforcement hardening functions (deep optimization)."""
from __future__ import annotations

import pytest
from pathlib import Path

from agent_team_v15.quality_checks import (
    CATEGORY_WEIGHTS,
    check_test_colocation_quality,
    compute_weighted_score,
    detect_pagination_wrapper_mismatch,
    verify_contracts_exist,
    verify_milestone_sequencing,
    verify_requirement_granularity,
)
from agent_team_v15.config_agent import (
    _map_finding_to_scoring_category,
    evaluate_stop_conditions,
)
from agent_team_v15.audit_agent import (
    AuditReport,
    Finding,
    FindingCategory,
    Severity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    severity: Severity = Severity.HIGH,
    category: FindingCategory = FindingCategory.CODE_FIX,
    title: str = "Test finding",
    description: str = "Test",
    finding_id: str = "F-TEST",
) -> Finding:
    return Finding(
        id=finding_id,
        feature="F-001",
        acceptance_criterion="test AC",
        severity=severity,
        category=category,
        title=title,
        description=description,
        prd_reference="F-001",
        current_behavior="wrong",
        expected_behavior="right",
    )


# ---------------------------------------------------------------------------
# verify_milestone_sequencing
# ---------------------------------------------------------------------------


class TestMilestoneSequencing:
    def test_backend_milestone_passes(self, tmp_path):
        violations = verify_milestone_sequencing("Backend API Development", tmp_path)
        assert len(violations) == 0

    def test_frontend_blocked_without_contracts(self, tmp_path):
        violations = verify_milestone_sequencing("Frontend Dashboard", tmp_path)
        assert len(violations) == 1
        assert "SEQUENCE-001" in violations[0]

    def test_frontend_allowed_with_contracts(self, tmp_path):
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        (agent_dir / "ENDPOINT_CONTRACTS.md").write_text("# Contracts\n" * 100)
        violations = verify_milestone_sequencing("Frontend Dashboard", tmp_path)
        assert len(violations) == 0

    def test_fullstack_not_flagged(self, tmp_path):
        # "Infrastructure" has no frontend keywords
        violations = verify_milestone_sequencing("Infrastructure Setup", tmp_path)
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# verify_contracts_exist
# ---------------------------------------------------------------------------


class TestContractsExist:
    def test_missing_contracts(self, tmp_path):
        violations = verify_contracts_exist(tmp_path)
        assert len(violations) == 1
        assert "CONTRACT-MISSING" in violations[0]

    def test_thin_contracts(self, tmp_path):
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        (agent_dir / "ENDPOINT_CONTRACTS.md").write_text("# Short")
        violations = verify_contracts_exist(tmp_path)
        assert len(violations) == 1
        assert "CONTRACT-THIN" in violations[0]

    def test_valid_contracts(self, tmp_path):
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        (agent_dir / "ENDPOINT_CONTRACTS.md").write_text("# Contracts\n" * 200)
        violations = verify_contracts_exist(tmp_path)
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# detect_pagination_wrapper_mismatch
# ---------------------------------------------------------------------------


class TestPaginationWrapperMismatch:
    def test_no_src_dir(self, tmp_path):
        violations = detect_pagination_wrapper_mismatch(tmp_path)
        assert len(violations) == 0

    def test_no_backend_wrapper(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "test.controller.ts").write_text("export class TestController {}")
        violations = detect_pagination_wrapper_mismatch(tmp_path)
        assert len(violations) == 0

    def test_detects_mismatch(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        ctrl = src / "repairs.controller.ts"
        ctrl.write_text(
            "export class RepairsController {\n"
            "  return { data: repairs, meta: { totalPages: 5 } };\n"
            "}\n"
        )
        app_dir = src / "app" / "repairs"
        app_dir.mkdir(parents=True)
        page = app_dir / "page.tsx"
        page.write_text(
            "export default function RepairsPage() {\n"
            "  const repairs = use(fetchRepairs());\n"
            "  return <div>{repairs.map(r => <p>{r.name}</p>)}</div>;\n"
            "}\n"
        )
        violations = detect_pagination_wrapper_mismatch(tmp_path)
        assert len(violations) == 1
        assert "WRAPPER-001" in violations[0]

    def test_no_mismatch_when_unwrapped(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        ctrl = src / "repairs.controller.ts"
        ctrl.write_text(
            "return { data: repairs, meta: { totalPages: 5 } };\n"
        )
        app_dir = src / "app" / "repairs"
        app_dir.mkdir(parents=True)
        page = app_dir / "page.tsx"
        page.write_text(
            "const response = use(fetchRepairs());\n"
            "const repairs = response.data;\n"
        )
        violations = detect_pagination_wrapper_mismatch(tmp_path)
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# verify_requirement_granularity
# ---------------------------------------------------------------------------


class TestRequirementGranularity:
    def test_no_requirements_file(self, tmp_path):
        violations = verify_requirement_granularity(tmp_path)
        assert len(violations) == 0

    def test_coarse_requirements(self, tmp_path):
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        content = (
            "## Milestone 1\n"
            "- [ ] REQ-001: Build everything\n"
            "- [ ] REQ-002: Test everything\n"
        )
        (agent_dir / "REQUIREMENTS.md").write_text(content)
        violations = verify_requirement_granularity(tmp_path)
        assert any("ATOMIC-001" in v for v in violations)

    def test_fine_requirements(self, tmp_path):
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        reqs = "\n".join(f"- [ ] REQ-{i:03d}: Specific task {i}" for i in range(10))
        content = f"## Milestone 1\n{reqs}\n"
        (agent_dir / "REQUIREMENTS.md").write_text(content)
        violations = verify_requirement_granularity(tmp_path)
        assert not any("ATOMIC-001" in v for v in violations)

    def test_multi_file_requirement(self, tmp_path):
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        content = (
            "## Milestone 1\n"
            "- [ ] REQ-001: Do stuff in a.ts b.ts c.ts d.ts e.ts\n"
        )
        (agent_dir / "REQUIREMENTS.md").write_text(content)
        violations = verify_requirement_granularity(tmp_path)
        assert any("ATOMIC-002" in v for v in violations)


# ---------------------------------------------------------------------------
# check_test_colocation_quality
# ---------------------------------------------------------------------------


class TestColocationQuality:
    def test_no_src_dir(self, tmp_path):
        violations = check_test_colocation_quality(tmp_path)
        assert len(violations) == 0

    def test_empty_spec_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "auth.service.spec.ts").write_text("")
        violations = check_test_colocation_quality(tmp_path)
        assert any("DEPTH-005" in v for v in violations)

    def test_stub_spec_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "auth.service.spec.ts").write_text(
            "import { AuthService } from './auth.service';\n"
            "describe('AuthService', () => {\n"
            "  it('should be defined', () => { expect(true).toBe(true); });\n"
            "});\n"
        )
        violations = check_test_colocation_quality(tmp_path)
        assert any("DEPTH-006" in v for v in violations)

    def test_good_spec_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "auth.service.spec.ts").write_text(
            "describe('AuthService', () => {\n"
            "  it('should login', () => { expect(result).toBeDefined(); });\n"
            "  it('should logout', () => { expect(result).toBeNull(); });\n"
            "  it('should refresh', () => { expect(token).toBeTruthy(); });\n"
            "});\n"
        )
        violations = check_test_colocation_quality(tmp_path)
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# _map_finding_to_scoring_category
# ---------------------------------------------------------------------------


class TestFindingCategoryMapping:
    def test_security_direct_mapping(self):
        f = _make_finding(category=FindingCategory.SECURITY, title="SQL injection")
        assert _map_finding_to_scoring_category(f) == "security_auth"

    def test_performance_direct_mapping(self):
        f = _make_finding(category=FindingCategory.PERFORMANCE, title="Slow query")
        assert _map_finding_to_scoring_category(f) == "backend_architecture"

    def test_ux_direct_mapping(self):
        f = _make_finding(category=FindingCategory.UX, title="Bad layout")
        assert _map_finding_to_scoring_category(f) == "frontend_quality"

    def test_wiring_keyword_mapping(self):
        f = _make_finding(
            title="Endpoint mismatch in API wiring",
            description="Frontend calls wrong endpoint",
        )
        assert _map_finding_to_scoring_category(f) == "frontend_backend_wiring"

    def test_database_keyword_mapping(self):
        f = _make_finding(
            title="Missing database migration",
            description="Entity schema not migrated",
        )
        assert _map_finding_to_scoring_category(f) == "entity_database"

    def test_auth_keyword_mapping(self):
        f = _make_finding(
            title="Missing JWT auth guard",
            description="Endpoint lacks auth check",
        )
        assert _map_finding_to_scoring_category(f) == "security_auth"

    def test_fallback_to_prd_compliance(self):
        f = _make_finding(title="Generic issue", description="Something wrong")
        assert _map_finding_to_scoring_category(f) == "prd_ac_compliance"


# ---------------------------------------------------------------------------
# Weighted score with correct mapping
# ---------------------------------------------------------------------------


class TestWeightedScoreMapping:
    def test_all_categories_at_100_gives_1000(self):
        scores = {k: 100.0 for k in CATEGORY_WEIGHTS}
        assert compute_weighted_score(scores) == 1000

    def test_all_categories_at_0_gives_0(self):
        scores = {k: 0.0 for k in CATEGORY_WEIGHTS}
        assert compute_weighted_score(scores) == 0

    def test_missing_categories_treated_as_0(self):
        scores = {"frontend_backend_wiring": 100.0}
        assert compute_weighted_score(scores) == 200  # only wiring's weight

    def test_weighted_score_stop_condition_fires(self):
        """Weighted score >= 850 with 0 critical/high → STOP."""
        from agent_team_v15.config_agent import LoopState
        state = LoopState(
            original_prd_path="prd.md",
            codebase_path="./out",
        )
        # Add a prior run so the condition activates
        state.runs = [type("R", (), {
            "run_number": 1, "score": 70.0, "cost": 50.0,
            "passed_acs": 70, "total_acs": 100, "critical_count": 0,
            "high_count": 0, "partial_acs": 0, "failed_acs": 30,
            "skipped_acs": 0, "regression_count": 0,
        })()]
        state.current_run = 1
        state.total_cost = 50.0
        # Create findings that are MEDIUM severity (actionable) but score >= 850
        findings = [
            _make_finding(
                severity=Severity.MEDIUM,
                title="Minor frontend loading state missing",
                description="Page missing loading indicator",
                finding_id=f"F-{i}",
            )
            for i in range(3)
        ]
        report = AuditReport(
            run_number=2,
            timestamp="2026-04-04T00:00:00Z",
            original_prd_path="prd.md",
            codebase_path="./out",
            total_acs=100,
            passed_acs=95,
            failed_acs=5,
            partial_acs=0,
            skipped_acs=0,
            score=95.0,
            findings=findings,
        )
        decision = evaluate_stop_conditions(state, report)
        # With 3 MEDIUM findings (deduction 8 each = 24 from one category),
        # total weighted score should be high. But there are no HIGH/CRITICAL,
        # so the weighted score stop SHOULD fire.
        # However, the condition also requires high_count == 0, which is true.
        assert decision.action == "STOP"
        assert "WEIGHTED SCORE" in decision.reason
