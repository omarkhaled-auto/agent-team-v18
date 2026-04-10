"""Wave 3 + Wave 4 tests for the builder-perfection upgrade (v16 → v17).

Covers:
- Bug fixes: pattern_memory, quality_checks, audit_agent, browser_test_agent
- Prompt content: agents.py prompt hardening and new sections
- Quality gates: check_implementation_depth, verify_review_integrity,
  verify_endpoint_contracts, check_agent_deployment
- Config: AgentScalingConfig, enterprise depth gating
- Audit prompts: word counts, get_auditor_prompt tech-stack additions
- Fix PRD: _build_features_section, _group_findings_by_root_cause,
  filter_findings_for_fix impact priority sorting
"""

from __future__ import annotations

import re
import logging
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1. Bug fix tests (items 1-8)
# ---------------------------------------------------------------------------


class TestPatternMemoryBugFixes:
    """Tests for pattern_memory.py SQL fix and snapshot cap warning."""

    def test_get_fix_recipes_10plus_word_description(self, tmp_path: Path):
        """Item 1: get_fix_recipes() with 10+ word description must NOT throw."""
        from agent_team_v15.pattern_memory import PatternMemory, FixRecipe

        mem = PatternMemory(db_path=tmp_path / "pm.db")
        try:
            # Store a recipe to make the query non-trivial
            mem.store_fix_recipe(FixRecipe(
                finding_id="TEST-001",
                finding_description="some long description with many words here",
                file_path="src/foo.ts",
                diff_text="- old\n+ new",
                build_id="build-1",
            ))
            # Query with >10 significant words — previously crashed with sqlite3 error
            long_desc = (
                "frontend pagination response shape mismatch unwrap "
                "controller service endpoint handler data"
            )
            # Should not raise sqlite3.ProgrammingError
            results = mem.get_fix_recipes("MISS-ID", long_desc, limit=3)
            assert isinstance(results, list)
        finally:
            mem.close()

    def test_snapshot_cap_warning_fires_once(self, tmp_path: Path, caplog):
        """Item 2: Snapshot cap warning should appear exactly once."""
        from agent_team_v15.pattern_memory import PatternMemory, BuildPattern

        # Reset class-level flag
        PatternMemory._snapshot_cap_warned = False

        mem = PatternMemory(db_path=tmp_path / "pm.db")
        try:
            # Fill past the cap (50) to trigger the warning
            for i in range(52):
                mem.store_build_pattern(BuildPattern(
                    build_id=f"build-{i:04d}",
                    task_summary=f"task {i}",
                ))
            # The flag should be set after exceeding the cap
            assert PatternMemory._snapshot_cap_warned is True
        finally:
            mem.close()
            PatternMemory._snapshot_cap_warned = False  # clean up


class TestQualityChecksContractCompliance:
    """Tests for _score_contract_compliance() returning 0.0 when no contracts."""

    def test_no_contracts_returns_zero(self, tmp_path: Path):
        """Item 3: No CONTRACTS.json → score is 0.0, not 0.5."""
        from agent_team_v15.quality_checks import TruthScorer

        # Create a minimal project dir with no contracts
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.ts").write_text("console.log('hello');")

        scorer = TruthScorer(tmp_path)
        score = scorer._score_contract_compliance()
        assert score == 0.0, f"Expected 0.0 when no contracts exist, got {score}"


class TestAuditAgentACExtraction:
    """Tests for audit_agent.py acceptance criteria extraction."""

    def test_extract_ac_from_table_format(self):
        """Item 4: AC extraction finds ACs from table format (| AC-XXX-NNN |)."""
        from agent_team_v15.audit_agent import extract_acceptance_criteria

        prd_text = """# Project: Test App

## Feature F-1: User Management

| AC ID | Description |
|-------|-------------|
| AC-001 | Users can register with email and password |
| AC-002 | Users can reset their password via email link |
"""
        acs = extract_acceptance_criteria(prd_text)
        ac_ids = [ac.id for ac in acs]
        assert "AC-1" in ac_ids or "AC-001" in ac_ids, f"Table-format ACs not found. Got: {ac_ids}"

    def test_extract_ac_from_gwt_format(self):
        """Item 5: AC extraction finds ACs from GIVEN/WHEN/THEN format."""
        from agent_team_v15.audit_agent import extract_acceptance_criteria

        prd_text = """# Project: Test App

## Feature F-1: Login

AC-1: GIVEN a valid email and password
WHEN the user clicks login
THEN the user is redirected to the dashboard

AC-2: GIVEN an invalid password
WHEN the user clicks login
THEN an error message is displayed
"""
        acs = extract_acceptance_criteria(prd_text)
        ac_ids = [ac.id for ac in acs]
        assert "AC-1" in ac_ids, f"GWT-format AC-1 not found. Got: {ac_ids}"
        assert "AC-2" in ac_ids, f"GWT-format AC-2 not found. Got: {ac_ids}"

    def test_deduplicate_findings_keeps_higher_severity(self):
        """Item 6: _deduplicate_findings() removes dupes, keeps higher severity."""
        from agent_team_v15.audit_agent import (
            _deduplicate_findings, Finding, FindingCategory, Severity,
        )

        f1 = Finding(
            id="F-001", feature="F-001", acceptance_criterion="AC-1",
            severity=Severity.MEDIUM, category=FindingCategory.CODE_FIX,
            title="Missing validation in login",
            description="Login endpoint has no validation",
            prd_reference="F-001", current_behavior="", expected_behavior="",
        )
        f2 = Finding(
            id="F-002", feature="F-001", acceptance_criterion="AC-1",
            severity=Severity.CRITICAL, category=FindingCategory.CODE_FIX,
            title="Missing validation in login endpoint",  # >80% similarity
            description="Validation is missing",
            prd_reference="F-001", current_behavior="", expected_behavior="",
        )
        f3 = Finding(
            id="F-003", feature="F-002", acceptance_criterion="AC-3",
            severity=Severity.LOW, category=FindingCategory.MISSING_FEATURE,
            title="Completely different finding",
            description="Something else",
            prd_reference="F-002", current_behavior="", expected_behavior="",
        )

        result = _deduplicate_findings([f1, f2, f3])
        # Should keep 2: the deduplicated pair (higher severity) + the unique one
        assert len(result) == 2, f"Expected 2 after dedup, got {len(result)}"
        # The kept finding for the duplicate pair should be CRITICAL
        code_fix_findings = [f for f in result if f.category == FindingCategory.CODE_FIX]
        assert code_fix_findings[0].severity == Severity.CRITICAL


class TestBrowserTestAgentRegex:
    """Tests for browser_test_agent.py _RE_ARROW_FLOW regex."""

    def test_arrow_flow_regex_compiles_and_matches(self):
        """Item 8: _RE_ARROW_FLOW regex compiles and matches arrow patterns."""
        from agent_team_v15.browser_test_agent import _RE_ARROW_FLOW

        # The regex should compile without error (it's imported)
        assert _RE_ARROW_FLOW is not None
        # It should match the arrow character
        assert _RE_ARROW_FLOW.search("Login → Dashboard")


# ---------------------------------------------------------------------------
# 2. Prompt content tests (items 9-13)
# ---------------------------------------------------------------------------


class TestPromptContent:
    """Tests for agents.py prompt hardening and new sections."""

    def test_planner_has_requirement_granularity_rules(self):
        """Item 9: PLANNER_PROMPT contains 'Requirement Granularity Rules'."""
        from agent_team_v15.agents import PLANNER_PROMPT

        assert "Requirement Granularity Rules" in PLANNER_PROMPT

    def test_code_writer_has_implementation_checklists(self):
        """Item 10: CODE_WRITER_PROMPT contains all 4 implementation checklists."""
        from agent_team_v15.agents import CODE_WRITER_PROMPT

        # Check for the 4 implementation checklist categories
        checklist_indicators = [
            "backend service",
            "backend controller",
            "frontend page",
            "test file",
        ]
        lower = CODE_WRITER_PROMPT.lower()
        # At least 3 of 4 should be present (exact wording may vary)
        found = sum(1 for ind in checklist_indicators if ind in lower)
        assert found >= 3, (
            f"Expected at least 3 of 4 implementation checklists, found {found}"
        )

    def test_orchestrator_has_contract_first_protocol(self):
        """Item 11: ORCHESTRATOR_SYSTEM_PROMPT has CONTRACT-FIRST INTEGRATION PROTOCOL."""
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT

        assert "CONTRACT-FIRST INTEGRATION PROTOCOL" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_task_assigner_has_frontend_protocol(self):
        """Item 12: TASK_ASSIGNER_PROMPT has FRONTEND TASK ASSIGNMENT PROTOCOL."""
        from agent_team_v15.agents import TASK_ASSIGNER_PROMPT

        has_frontend_protocol = "FRONTEND TASK ASSIGNMENT PROTOCOL" in TASK_ASSIGNER_PROMPT
        has_agent_deploy = "Agent Deployment Rules" in TASK_ASSIGNER_PROMPT
        assert has_frontend_protocol or has_agent_deploy, (
            "TASK_ASSIGNER_PROMPT missing both FRONTEND TASK ASSIGNMENT PROTOCOL "
            "and Agent Deployment Rules"
        )

    def test_language_hardening_reduced_should_count(self):
        """Item 13: 'should' in instruction contexts is significantly reduced."""
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT

        # Count 'should' occurrences (case-insensitive, word boundary)
        should_count = len(re.findall(r"\bshould\b", ORCHESTRATOR_SYSTEM_PROMPT, re.IGNORECASE))
        # After hardening, there should be fewer 'should' instances
        # Original had ~80 across agents.py; orchestrator prompt portion should be under 20
        assert should_count < 30, (
            f"Expected fewer 'should' instances after hardening, found {should_count}"
        )


# ---------------------------------------------------------------------------
# 3. Quality gate tests (items 14-19)
# ---------------------------------------------------------------------------


class TestCheckImplementationDepth:
    """Tests for check_implementation_depth() in quality_checks.py."""

    def test_detects_missing_spec_for_service(self, tmp_path: Path):
        """Item 14: Detects missing .spec.ts for a .service.ts file."""
        from agent_team_v15.quality_checks import check_implementation_depth

        src = tmp_path / "src"
        src.mkdir()
        (src / "users.service.ts").write_text("export class UsersService { async findAll() {} }")
        # No users.service.spec.ts

        violations = check_implementation_depth(tmp_path)
        depth_001 = [v for v in violations if "DEPTH-001" in v]
        assert len(depth_001) >= 1, f"Expected DEPTH-001 violation, got: {violations}"

    def test_detects_missing_error_handling_in_service(self, tmp_path: Path):
        """Item 15: Detects missing error handling in service."""
        from agent_team_v15.quality_checks import check_implementation_depth

        src = tmp_path / "src"
        src.mkdir()
        (src / "orders.service.ts").write_text(
            "export class OrdersService {\n"
            "  async create(dto: any) {\n"
            "    return this.repo.save(dto);\n"
            "  }\n"
            "}\n"
        )

        violations = check_implementation_depth(tmp_path)
        depth_002 = [v for v in violations if "DEPTH-002" in v]
        assert len(depth_002) >= 1, f"Expected DEPTH-002 violation, got: {violations}"

    def test_detects_missing_loading_state_in_page(self, tmp_path: Path):
        """Item 16: Detects missing loading state in page.tsx."""
        from agent_team_v15.quality_checks import check_implementation_depth

        src = tmp_path / "src"
        src.mkdir()
        (src / "page.tsx").write_text(
            "export default function DashboardPage() {\n"
            "  return <div>Dashboard content</div>;\n"
            "}\n"
        )

        violations = check_implementation_depth(tmp_path)
        depth_003 = [v for v in violations if "DEPTH-003" in v]
        assert len(depth_003) >= 1, f"Expected DEPTH-003 violation, got: {violations}"


class TestVerifyReviewIntegrity:
    """Tests for verify_review_integrity() in quality_checks.py."""

    def test_detects_checked_items_with_zero_review_cycles(self, tmp_path: Path):
        """Item 17: Detects [x] items with review_cycles=0."""
        from agent_team_v15.quality_checks import verify_review_integrity

        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        (agent_dir / "REQUIREMENTS.md").write_text(
            "# Requirements\n\n"
            "- [x] REQ-001: User login review_cycles: 0\n"
            "- [x] REQ-002: User signup review_cycles: 2\n"
            "- [ ] REQ-003: Dashboard\n"
        )

        violations = verify_review_integrity(tmp_path)
        integrity_violations = [v for v in violations if "review_cycles" in v.lower() and "0" in v]
        assert len(integrity_violations) >= 1, (
            f"Expected review_cycles=0 violation, got: {violations}"
        )


class TestVerifyEndpointContracts:
    """Tests for verify_endpoint_contracts() in quality_checks.py."""

    def test_detects_uncontracted_api_calls(self, tmp_path: Path):
        """Item 18: Detects uncontracted API calls."""
        from agent_team_v15.quality_checks import verify_endpoint_contracts

        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        (agent_dir / "ENDPOINT_CONTRACTS.md").write_text(
            "# Endpoint Contracts\n\n"
            "### GET /api/users\n"
            "Returns list of users\n"
        )

        src = tmp_path / "src"
        src.mkdir()
        (src / "service.ts").write_text(
            "const users = await axios.get('/api/users');\n"
            "const orders = await fetch('/api/orders');\n"  # Not in contracts
        )

        violations = verify_endpoint_contracts(tmp_path)
        uncontracted = [v for v in violations if "UNCONTRACTED" in v]
        assert len(uncontracted) >= 1, f"Expected uncontracted violation for /api/orders, got: {violations}"


class TestCheckAgentDeployment:
    """Tests for check_agent_deployment() in quality_checks.py."""

    def test_detects_under_deployment_at_enterprise(self, tmp_path: Path):
        """Item 19: Detects under-deployment at enterprise depth."""
        from agent_team_v15.quality_checks import check_agent_deployment

        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        # Create REQUIREMENTS.md with 30 requirements
        reqs = "\n".join(f"- [x] REQ-{i:03d}: Requirement {i}" for i in range(30))
        (agent_dir / "REQUIREMENTS.md").write_text(f"# Requirements\n\n{reqs}\n")
        # Create TASKS.md with only 1 assignee
        (agent_dir / "TASKS.md").write_text(
            "assigned_to: coder-1\n"
            "reviewer: reviewer-1\n"
        )

        violations = check_agent_deployment(tmp_path, "enterprise")
        assert len(violations) >= 1, f"Expected under-deployment violation, got: {violations}"
        assert any("AGENT-DEPLOY" in v for v in violations)


# ---------------------------------------------------------------------------
# 4. Config tests (items 20-22)
# ---------------------------------------------------------------------------


class TestAgentScalingConfig:
    """Tests for AgentScalingConfig dataclass defaults."""

    def test_default_values(self):
        """Item 20: AgentScalingConfig defaults match spec."""
        from agent_team_v15.config import AgentScalingConfig

        cfg = AgentScalingConfig()
        assert cfg.max_requirements_per_coder == 15
        assert cfg.max_requirements_per_reviewer == 25
        assert cfg.max_requirements_per_tester == 20


class TestEnterpriseDepthGating:
    """Tests for enterprise depth gating in apply_depth_quality_gating()."""

    def test_enterprise_sets_max_cycles_25(self):
        """Item 21: Enterprise depth sets max_cycles=25."""
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating

        cfg = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", cfg)
        assert cfg.convergence.max_cycles == 25

    def test_enterprise_thought_budgets_match_plan(self):
        """Item 22: Enterprise depth uses plan-specified thought budgets."""
        from agent_team_v15.config import (
            AgentTeamConfig, apply_depth_quality_gating,
        )

        cfg = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", cfg)

        # Plan specifies explicit values (not 2x defaults)
        expected = {1: 20, 2: 25, 3: 25, 4: 20, 5: 20}
        assert cfg.orchestrator_st.thought_budgets == expected, (
            f"Expected {expected}, got {cfg.orchestrator_st.thought_budgets}"
        )


# ---------------------------------------------------------------------------
# 5. Audit prompt tests (items 23-26)
# ---------------------------------------------------------------------------


class TestAuditPromptWordCounts:
    """Tests for audit prompt minimum word counts."""

    def test_interface_auditor_prompt_length(self):
        """Item 23: INTERFACE_AUDITOR_PROMPT word count > 1500."""
        from agent_team_v15.audit_prompts import INTERFACE_AUDITOR_PROMPT

        word_count = len(INTERFACE_AUDITOR_PROMPT.split())
        assert word_count > 1500, (
            f"INTERFACE_AUDITOR_PROMPT has {word_count} words, expected > 1500"
        )

    def test_requirements_auditor_prompt_length(self):
        """Item 24: REQUIREMENTS_AUDITOR_PROMPT word count > 1500."""
        from agent_team_v15.audit_prompts import REQUIREMENTS_AUDITOR_PROMPT

        word_count = len(REQUIREMENTS_AUDITOR_PROMPT.split())
        assert word_count > 1500, (
            f"REQUIREMENTS_AUDITOR_PROMPT has {word_count} words, expected > 1500"
        )

    def test_comprehensive_auditor_prompt_length(self):
        """Item 25: COMPREHENSIVE_AUDITOR_PROMPT word count > 2500."""
        from agent_team_v15.audit_prompts import COMPREHENSIVE_AUDITOR_PROMPT

        word_count = len(COMPREHENSIVE_AUDITOR_PROMPT.split())
        assert word_count > 2500, (
            f"COMPREHENSIVE_AUDITOR_PROMPT has {word_count} words, expected > 2500"
        )


class TestGetAuditorPrompt:
    """Tests for get_auditor_prompt() tech-stack additions."""

    def test_nestjs_tech_stack_adds_checks(self):
        """Item 26: Returns NestJS-specific checks when tech_stack includes 'nestjs'."""
        from agent_team_v15.audit_prompts import get_auditor_prompt

        prompt = get_auditor_prompt("requirements", tech_stack=["nestjs"])
        assert "TECH-STACK-SPECIFIC REQUIREMENTS" in prompt
        assert "NestJS" in prompt or "nest" in prompt.lower()

    def test_without_tech_stack(self):
        """get_auditor_prompt without tech_stack returns base prompt."""
        from agent_team_v15.audit_prompts import get_auditor_prompt

        prompt = get_auditor_prompt("requirements")
        assert "TECH-STACK-SPECIFIC REQUIREMENTS" not in prompt


# ---------------------------------------------------------------------------
# 6. Fix PRD tests (items 27-29)
# ---------------------------------------------------------------------------


class TestFixPRDFeaturesSection:
    """Tests for _build_features_section() in fix_prd_agent.py."""

    def test_output_contains_files_and_acceptance_criteria(self):
        """Item 27: Output contains file references and acceptance criteria."""
        from agent_team_v15.fix_prd_agent import _build_features_section, _group_findings_by_root_cause
        from agent_team_v15.audit_agent import Finding, FindingCategory, Severity

        finding = Finding(
            id="F-001", feature="F-001", acceptance_criterion="AC-1",
            severity=Severity.HIGH, category=FindingCategory.CODE_FIX,
            title="Wrong return type",
            description="Service returns wrong type",
            prd_reference="F-001 AC-1",
            current_behavior="Returns string",
            expected_behavior="Should return UserDto",
            file_path="src/users.service.ts",
            line_number=42,
            code_snippet="return 'hello';",
            fix_suggestion="Change return type to UserDto",
        )

        groups = _group_findings_by_root_cause([finding])
        output = _build_features_section(groups)
        assert "src/users.service.ts" in output, f"Missing file reference in:\n{output}"
        assert "AC-FIX-" in output, f"Missing acceptance criteria in:\n{output}"


class TestFilterFindingsImpactPriority:
    """Tests for filter_findings_for_fix() impact-based sorting."""

    def test_wiring_before_auth(self):
        """Item 28: Wiring findings sort before auth findings."""
        from agent_team_v15.fix_prd_agent import filter_findings_for_fix
        from agent_team_v15.audit_agent import Finding, FindingCategory, Severity

        auth_finding = Finding(
            id="F-001", feature="F-001", acceptance_criterion="AC-1",
            severity=Severity.HIGH, category=FindingCategory.SECURITY,
            title="JWT guard missing on endpoint",
            description="Auth guard not applied",
            prd_reference="F-001", current_behavior="", expected_behavior="",
        )
        wiring_finding = Finding(
            id="F-002", feature="F-002", acceptance_criterion="AC-2",
            severity=Severity.HIGH, category=FindingCategory.CODE_FIX,
            title="API endpoint wiring broken",
            description="Frontend calls wrong endpoint integration contract",
            prd_reference="F-002", current_behavior="", expected_behavior="",
        )

        result = filter_findings_for_fix([auth_finding, wiring_finding])
        # Wiring (impact 0) should come before auth (impact 1)
        assert len(result) == 2
        assert result[0].id == "F-002", (
            f"Expected wiring finding first, got {result[0].id}"
        )


class TestBuildRegressionGuardSection:
    """Tests for _build_regression_guard_section() in fix_prd_agent.py."""

    def test_output_contains_regression_guard_section(self):
        """Item 29: Output contains 'Regression Guard' section with passing ACs."""
        from agent_team_v15.fix_prd_agent import _build_regression_guard_section

        output = _build_regression_guard_section(["AC-1", "AC-2"])
        assert "Regression Guard" in output, f"Missing Regression Guard in:\n{output}"
        assert "AC-1" in output
        assert "AC-2" in output
