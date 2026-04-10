"""Wiring verification tests — ensure perfection plan functions are CALLED from production code.

These tests verify that the quality gate functions are not just defined and tested
in isolation, but are actually imported and called from production code paths
(cli.py, coordinated_builder.py, config_agent.py).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# Root of the source package
_SRC = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15"


# ---------------------------------------------------------------------------
# Helper: parse AST and find function calls
# ---------------------------------------------------------------------------

def _find_calls_in_file(filepath: Path, target_func: str) -> list[int]:
    """Return line numbers where target_func is called in filepath."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Direct call: func_name(...)
            if isinstance(node.func, ast.Name) and node.func.id == target_func:
                lines.append(node.lineno)
            # Attribute call: module.func_name(...)
            elif isinstance(node.func, ast.Attribute) and node.func.attr == target_func:
                lines.append(node.lineno)
    return lines


# ---------------------------------------------------------------------------
# TIER 1: Wiring verification — all 6 orphaned functions are now called
# ---------------------------------------------------------------------------


class TestOrphanedFunctionsAreWired:
    """Verify all 6 previously-orphaned functions are called from production code."""

    def test_check_implementation_depth_called_from_cli(self):
        calls = _find_calls_in_file(_SRC / "cli.py", "check_implementation_depth")
        assert len(calls) >= 1, "check_implementation_depth must be called in cli.py"

    def test_check_implementation_depth_called_from_coordinated_builder(self):
        calls = _find_calls_in_file(_SRC / "coordinated_builder.py", "check_implementation_depth")
        assert len(calls) >= 1, "check_implementation_depth must be called in coordinated_builder.py"

    def test_verify_endpoint_contracts_called_from_cli(self):
        calls = _find_calls_in_file(_SRC / "cli.py", "verify_endpoint_contracts")
        assert len(calls) >= 1, "verify_endpoint_contracts must be called in cli.py"

    def test_verify_endpoint_contracts_called_from_coordinated_builder(self):
        calls = _find_calls_in_file(_SRC / "coordinated_builder.py", "verify_endpoint_contracts")
        assert len(calls) >= 1, "verify_endpoint_contracts must be called in coordinated_builder.py"

    def test_compute_weighted_score_called_from_config_agent(self):
        calls = _find_calls_in_file(_SRC / "config_agent.py", "compute_weighted_score")
        assert len(calls) >= 1, "compute_weighted_score must be called in config_agent.py"

    def test_check_agent_deployment_called_from_cli(self):
        calls = _find_calls_in_file(_SRC / "cli.py", "check_agent_deployment")
        assert len(calls) >= 1, "check_agent_deployment must be called in cli.py"

    def test_check_agent_deployment_called_from_coordinated_builder(self):
        calls = _find_calls_in_file(_SRC / "coordinated_builder.py", "check_agent_deployment")
        assert len(calls) >= 1, "check_agent_deployment must be called in coordinated_builder.py"

    def test_verify_review_integrity_called_from_cli(self):
        calls = _find_calls_in_file(_SRC / "cli.py", "verify_review_integrity")
        assert len(calls) >= 1, "verify_review_integrity must be called in cli.py"

    def test_verify_review_integrity_called_from_coordinated_builder(self):
        calls = _find_calls_in_file(_SRC / "coordinated_builder.py", "verify_review_integrity")
        assert len(calls) >= 1, "verify_review_integrity must be called in coordinated_builder.py"

    def test_compute_quality_score_called_from_coordinated_builder(self):
        calls = _find_calls_in_file(_SRC / "coordinated_builder.py", "compute_quality_score")
        assert len(calls) >= 1, "compute_quality_score must be called in coordinated_builder.py"


class TestAuditBypassFixed:
    """Verify coordinated builder uses run_full_audit, not run_audit."""

    def test_coordinated_builder_imports_run_full_audit(self):
        source = (_SRC / "coordinated_builder.py").read_text(encoding="utf-8")
        assert "run_full_audit" in source, "coordinated_builder must import run_full_audit"
        # Old import must be gone
        old_import = "from agent_team_v15.audit_agent import AuditReport, Finding, Severity, run_audit\n"
        assert old_import not in source, "Old run_audit import must be replaced"

    def test_coordinated_builder_calls_run_full_audit(self):
        calls = _find_calls_in_file(_SRC / "coordinated_builder.py", "run_full_audit")
        assert len(calls) >= 2, "run_full_audit must be called at least twice (primary + retry)"


# ---------------------------------------------------------------------------
# TIER 2: Prompt content verification
# ---------------------------------------------------------------------------


class TestPromptContentWired:
    """Verify prompt additions are present."""

    def test_coding_lead_has_agent_minimums(self):
        from agent_team_v15.agents import CODING_LEAD_PROMPT
        assert "MINIMUM" in CODING_LEAD_PROMPT
        assert "Agent Deployment Rules" in CODING_LEAD_PROMPT

    def test_coding_lead_has_contract_blocking(self):
        from agent_team_v15.agents import CODING_LEAD_PROMPT
        assert "ENDPOINT_CONTRACTS" in CODING_LEAD_PROMPT

    def test_coding_lead_has_test_colocation(self):
        from agent_team_v15.agents import CODING_LEAD_PROMPT
        assert "Test Co-Location" in CODING_LEAD_PROMPT

    def test_review_lead_has_reviewer_minimums(self):
        from agent_team_v15.agents import REVIEW_LEAD_PROMPT
        assert "MINIMUM" in REVIEW_LEAD_PROMPT
        assert "Reviewer Deployment Rules" in REVIEW_LEAD_PROMPT

    def test_orchestrator_has_gate_7(self):
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        assert "GATE 7" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_orchestrator_has_contract_protocol(self):
        from agent_team_v15.agents import TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "CONTRACT-FIRST" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_orchestrator_has_gate_7(self):
        from agent_team_v15.agents import TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "GATE 7" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_orchestrator_has_test_colocation(self):
        from agent_team_v15.agents import TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "TEST CO-LOCATION" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# TIER 2: Config verification
# ---------------------------------------------------------------------------


class TestEnterpriseConfigOverrides:
    """Verify all enterprise config overrides match plan values."""

    def test_enterprise_has_all_overrides(self):
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
        config = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", config)

        assert config.verification.min_test_count >= 10
        assert config.convergence.escalation_threshold >= 6
        assert config.audit_team.score_healthy_threshold >= 95.0
        assert config.audit_team.score_degraded_threshold >= 85.0
        assert config.audit_team.fix_severity_threshold == "LOW"

    def test_enterprise_thought_budgets_match_plan(self):
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
        config = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", config)

        expected = {1: 20, 2: 25, 3: 25, 4: 20, 5: 20}
        assert config.orchestrator_st.thought_budgets == expected


# ---------------------------------------------------------------------------
# TIER 3: Gate hardening verification
# ---------------------------------------------------------------------------


class TestDepthCheckGlobFixes:
    """Verify spec file exclusion and node_modules exclusion."""

    def test_depth_check_excludes_spec_files(self, tmp_path: Path):
        """Spec files must NOT be flagged by DEPTH-001."""
        from agent_team_v15.quality_checks import check_implementation_depth

        src = tmp_path / "src"
        src.mkdir()
        (src / "auth.service.ts").write_text("export class AuthService { async login() { try { } catch(e) {} } }")
        (src / "auth.service.spec.ts").write_text("describe('AuthService', () => { it('works', () => {}) });")

        violations = check_implementation_depth(tmp_path)
        depth001 = [v for v in violations if "DEPTH-001" in v]
        assert len(depth001) == 0, f"Spec files should not trigger DEPTH-001: {depth001}"

    def test_depth_check_skips_node_modules(self, tmp_path: Path):
        """Files in node_modules must not be checked."""
        from agent_team_v15.quality_checks import check_implementation_depth

        src = tmp_path / "src" / "node_modules" / "some-lib"
        src.mkdir(parents=True)
        (src / "lib.service.ts").write_text("// third party")

        violations = check_implementation_depth(tmp_path)
        assert len(violations) == 0

    def test_depth_check_nextjs_loading_file(self, tmp_path: Path):
        """Next.js sibling loading.tsx should satisfy DEPTH-003."""
        from agent_team_v15.quality_checks import check_implementation_depth

        src = tmp_path / "src" / "app" / "dashboard"
        src.mkdir(parents=True)
        (src / "page.tsx").write_text("export default function Dashboard() { return <div>hi</div> }")
        (src / "loading.tsx").write_text("export default function Loading() { return <div>...</div> }")

        violations = check_implementation_depth(tmp_path)
        depth003 = [v for v in violations if "DEPTH-003" in v]
        assert len(depth003) == 0, f"Sibling loading.tsx should satisfy DEPTH-003: {depth003}"


class TestImpactSortPreservesSeverity:
    """Verify CRITICAL is always before MEDIUM regardless of impact category."""

    def test_critical_security_before_medium_wiring(self):
        from agent_team_v15.audit_agent import Finding, Severity, FindingCategory
        from agent_team_v15.fix_prd_agent import filter_findings_for_fix

        findings = [
            Finding(
                id="F-001",
                feature="F-001",
                acceptance_criterion="AC-001",
                title="medium wiring integration issue",
                description="field name mismatch in endpoint integration contract",
                severity=Severity.MEDIUM,
                category=FindingCategory.CODE_FIX,
                prd_reference="Section 1",
                current_behavior="wrong field",
                expected_behavior="correct field",
            ),
            Finding(
                id="F-002",
                feature="F-002",
                acceptance_criterion="AC-002",
                title="critical security vulnerability",
                description="SQL injection in auth login query",
                severity=Severity.CRITICAL,
                category=FindingCategory.SECURITY,
                prd_reference="Section 2",
                current_behavior="unescaped input",
                expected_behavior="parameterized query",
            ),
        ]

        sorted_findings = filter_findings_for_fix(findings, max_findings=10)
        assert len(sorted_findings) >= 2
        # CRITICAL must come first regardless of impact category
        assert sorted_findings[0].severity == Severity.CRITICAL, \
            f"CRITICAL must sort before MEDIUM, got: {[f.severity for f in sorted_findings]}"


class TestContractPathNormalization:
    """Verify parameterized routes don't produce // in normalized paths."""

    def test_no_false_negative_for_parameterized_routes(self, tmp_path: Path):
        from agent_team_v15.quality_checks import verify_endpoint_contracts

        agent_team = tmp_path / ".agent-team"
        agent_team.mkdir()
        (agent_team / "ENDPOINT_CONTRACTS.md").write_text(
            "### GET /api/v1/users/:id\nReturns user by ID\n"
        )
        src = tmp_path / "src"
        src.mkdir()
        (src / "page.tsx").write_text(
            'const res = fetch(`/api/v1/users/${id}`)'
        )

        violations = verify_endpoint_contracts(tmp_path)
        uncontracted = [v for v in violations if "UNCONTRACTED" in v]
        assert len(uncontracted) == 0, f"Parameterized route should match: {uncontracted}"


class TestExportBugFixed:
    """Verify audit_team __all__ doesn't export non-existent function."""

    def test_no_compute_convergence_plateau_in_all(self):
        from agent_team_v15 import audit_team
        all_exports = getattr(audit_team, "__all__", [])
        assert "compute_convergence_plateau" not in all_exports, \
            "__all__ must not export non-existent compute_convergence_plateau"
        assert "detect_convergence_plateau" in all_exports
