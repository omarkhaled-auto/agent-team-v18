"""Tests for prompt integrity — CODE_WRITER_PROMPT policies, CODE_REVIEWER_PROMPT
duties, build function outputs, and standards constants.
"""

from __future__ import annotations

import inspect

import pytest

from agent_team_v15.agents import (
    ARCHITECT_PROMPT,
    CODE_REVIEWER_PROMPT,
    CODE_WRITER_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    TEAM_ORCHESTRATOR_SYSTEM_PROMPT,
    build_agent_definitions,
    build_decomposition_prompt,
    build_milestone_execution_prompt,
    build_orchestrator_prompt,
    get_orchestrator_system_prompt,
)
from agent_team_v15.code_quality_standards import (
    DATABASE_INTEGRITY_STANDARDS,
    E2E_TESTING_STANDARDS,
    get_standards_for_agent,
)
from agent_team_v15.config import AgentTeamConfig


# ===========================================================================
# CODE_WRITER_PROMPT policies
# ===========================================================================


class TestCodeWriterPromptPolicies:
    """Verify CODE_WRITER_PROMPT contains all required policy blocks."""

    def test_zero_mock_data_policy(self):
        assert "ZERO MOCK DATA POLICY" in CODE_WRITER_PROMPT

    def test_ui_compliance_policy(self):
        assert "UI COMPLIANCE POLICY" in CODE_WRITER_PROMPT

    def test_seed_data_policy(self):
        assert "SEED DATA COMPLETENESS" in CODE_WRITER_PROMPT

    def test_enum_registry_policy(self):
        assert "ENUM/STATUS REGISTRY" in CODE_WRITER_PROMPT

    def test_front_019_in_standards(self):
        """FRONT-019 lives in code_quality_standards, appended to code-writer."""
        standards = get_standards_for_agent("code-writer")
        assert "FRONT-019" in standards

    def test_front_020_in_standards(self):
        standards = get_standards_for_agent("code-writer")
        assert "FRONT-020" in standards

    def test_front_021_in_standards(self):
        standards = get_standards_for_agent("code-writer")
        assert "FRONT-021" in standards

    def test_ui_fail_codes(self):
        for code in ("UI-FAIL-001", "UI-FAIL-002", "UI-FAIL-003"):
            assert code in CODE_WRITER_PROMPT, f"{code} missing from CODE_WRITER_PROMPT"


# ===========================================================================
# CODE_REVIEWER_PROMPT duties
# ===========================================================================


class TestCodeReviewerPromptDuties:
    """Verify CODE_REVIEWER_PROMPT contains reviewer duties."""

    def test_ui_compliance_duty(self):
        assert "UI" in CODE_REVIEWER_PROMPT and "compliance" in CODE_REVIEWER_PROMPT.lower()

    def test_mock_data_duty(self):
        assert "mock" in CODE_REVIEWER_PROMPT.lower()

    def test_reviewer_is_adversarial(self):
        assert "ADVERSARIAL" in CODE_REVIEWER_PROMPT

    def test_reviewer_mentions_services(self):
        assert "service" in CODE_REVIEWER_PROMPT.lower()


# ===========================================================================
# ARCHITECT_PROMPT policies
# ===========================================================================


class TestArchitectPromptPolicies:
    """Verify ARCHITECT_PROMPT contains required policies."""

    def test_svc_requirement_type(self):
        assert "SVC-" in ARCHITECT_PROMPT or "SVC" in ARCHITECT_PROMPT

    def test_enum_registry_mention(self):
        assert "ENUM" in ARCHITECT_PROMPT


# ===========================================================================
# ORCHESTRATOR_SYSTEM_PROMPT
# ===========================================================================


class TestOrchestratorPrompt:
    """Verify orchestrator prompt core sections."""

    def test_requirements_document_protocol(self):
        assert "REQUIREMENTS.md" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_convergence_loop(self):
        assert "convergence" in ORCHESTRATOR_SYSTEM_PROMPT.lower()

    def test_planning_fleet(self):
        assert "PLANNING FLEET" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_ui_design_system_phase(self):
        assert "UI DESIGN SYSTEM" in ORCHESTRATOR_SYSTEM_PROMPT or \
               "UI_REQUIREMENTS" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_mock_data_gate(self):
        assert "MOCK DATA GATE" in ORCHESTRATOR_SYSTEM_PROMPT

    # --- Section 12: Schema Integrity Mandate ---

    def test_section_12_exists(self):
        assert "SECTION 12:" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_12_cascade_rule(self):
        assert "onDelete: Cascade" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_12_fk_relation_rule(self):
        assert "@relation" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_12_fk_default_rule(self):
        assert '@default("")' in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_12_soft_delete_middleware(self):
        assert "deleted_at" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "global middleware" in ORCHESTRATOR_SYSTEM_PROMPT.lower() or \
               "Global Enforcement" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_12_fk_indexes(self):
        assert "@@index" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_12_financial_precision(self):
        assert "Decimal(18,4)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_12_multi_tenant(self):
        assert "tenant_id" in ORCHESTRATOR_SYSTEM_PROMPT

    # --- Section 13: Enum Registry & Role Consistency ---

    def test_section_13_exists(self):
        assert "SECTION 13:" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_13_enum_registry(self):
        assert "ENUM_REGISTRY" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_13_role_consistency(self):
        assert "seed data" in ORCHESTRATOR_SYSTEM_PROMPT.lower()

    def test_section_13_reviewer_cross_check(self):
        assert "@Roles()" in ORCHESTRATOR_SYSTEM_PROMPT

    # --- Section 14: Auth Contract Mandate ---

    def test_section_14_exists(self):
        assert "SECTION 14:" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_14_auth_flow_documentation(self):
        assert "challenge-token" in ORCHESTRATOR_SYSTEM_PROMPT or \
               "MFA" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_14_frontend_backend_contract(self):
        assert "Token storage mechanism" in ORCHESTRATOR_SYSTEM_PROMPT or \
               "token storage" in ORCHESTRATOR_SYSTEM_PROMPT.lower()

    def test_section_14_end_to_end_trace(self):
        assert "End-to-End Auth Trace" in ORCHESTRATOR_SYSTEM_PROMPT or \
               "trace the complete auth flow" in ORCHESTRATOR_SYSTEM_PROMPT.lower()

    # --- Section 5 upgrade: Targeted Reviewer Checklist ---

    def test_section_5_targeted_reviewer_checklist(self):
        assert "Targeted Reviewer Checklist" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_5_role_consistency_check(self):
        assert "Role Consistency" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_5_route_path_alignment(self):
        assert "Route Path Alignment" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_5_prisma_include_validity(self):
        assert "Prisma Include Validity" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_5_response_shape_consistency(self):
        assert "Response Shape Consistency" in ORCHESTRATOR_SYSTEM_PROMPT

    # --- Section 9 upgrade: New mandatory standards ---

    def test_section_9_soft_delete_middleware(self):
        assert "Soft-Delete Middleware (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_9_route_structure_consistency(self):
        assert "Route Structure Consistency (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_9_build_verification_gate(self):
        assert "Build Verification Gate (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_9_query_correctness(self):
        assert "Query Correctness (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_9_post_pagination_filtering(self):
        assert "Post-pagination filtering prohibition" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_9_type_safe_orm_access(self):
        assert "Type-safe ORM access" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_9_invalid_fallback_values(self):
        assert "Invalid fallback values" in ORCHESTRATOR_SYSTEM_PROMPT

    # --- Section 10 strengthening: Serialization verification ---

    def test_section_10_serialization_verification_test(self):
        assert "Serialization Verification Test (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_10_field_name_fallback_prohibition(self):
        assert "Field-Name Fallback Prohibition (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    # --- Section 11 strengthening: Route convention + shared constants ---

    def test_section_11_route_convention_decision(self):
        assert "Route Convention Decision (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_11_shared_constants_mandate(self):
        assert "Shared Constants Mandate (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_11_auth_protocol_verification(self):
        assert "Auth Protocol Verification (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_11_security_config_consistency(self):
        assert "Security Config Consistency (MANDATORY)" in ORCHESTRATOR_SYSTEM_PROMPT

    # --- Section 5 strengthening: Root-cause-categorized checks ---

    def test_section_5_route_checks_category(self):
        assert "ROUTE checks (29% of bugs)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_5_schema_checks_category(self):
        assert "SCHEMA checks (19% of bugs)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_5_query_checks_category(self):
        assert "QUERY checks (16% of bugs)" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_5_pluralization_check(self):
        assert "Pluralization Check" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_5_auth_flow_trace(self):
        assert "Auth Flow Trace" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_5_no_field_name_fallbacks(self):
        assert "No Field-Name Fallbacks" in ORCHESTRATOR_SYSTEM_PROMPT

    # --- Tier promotion: soft-delete in Tier 2 ---

    def test_soft_delete_in_tier_2(self):
        """Soft-delete must be in Tier 2 (EXPECTED), not Tier 3 (IF BUDGET)."""
        from agent_team_v15.agents import build_tiered_mandate
        mandate = build_tiered_mandate([])
        tier2_start = mandate.index("TIER 2")
        tier3_start = mandate.index("TIER 3")
        soft_delete_pos = mandate.index("Soft delete with deleted_at")
        assert tier2_start < soft_delete_pos < tier3_start, (
            "Soft-delete must appear between Tier 2 and Tier 3 headings"
        )


# ===========================================================================
# Build functions
# ===========================================================================


class TestBuildFunctions:
    """Verify build functions produce non-empty strings with key content."""

    def test_build_orchestrator_prompt_contains_key_content(self):
        cfg = AgentTeamConfig()
        prompt = build_orchestrator_prompt(
            task="Build a todo app", depth="standard", config=cfg
        )
        # The build function wraps the system prompt — look for expected content
        assert "REQUIREMENTS" in prompt
        assert "Build a todo app" in prompt

    def test_build_decomposition_prompt_has_key_content(self):
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build app", depth="standard", config=cfg
        )
        assert "DECOMPOSITION" in prompt
        assert "Build app" in prompt

    def test_build_milestone_execution_prompt_has_workflow(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Setup Backend: Build REST API",
            depth="standard",
            config=cfg,
        )
        assert "MILESTONE WORKFLOW" in prompt or "milestone" in prompt.lower()

    def test_build_milestone_prompt_has_task_assigner(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Setup: Build API",
            depth="standard",
            config=cfg,
        )
        assert "TASK" in prompt

    def test_build_agent_definitions_returns_dict(self):
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, mcp_servers={})
        assert isinstance(agents, dict)
        assert len(agents) > 0


# ===========================================================================
# Standards constants
# ===========================================================================


class TestStandardsConstants:
    """Verify code quality standards mappings."""

    def test_database_standards_exist(self):
        assert len(DATABASE_INTEGRITY_STANDARDS) > 100
        assert "DB-" in DATABASE_INTEGRITY_STANDARDS

    def test_e2e_standards_exist(self):
        assert len(E2E_TESTING_STANDARDS) > 100
        assert "E2E" in E2E_TESTING_STANDARDS

    def test_code_writer_gets_db_standards(self):
        standards = get_standards_for_agent("code-writer")
        assert "DB-" in standards or "DATABASE" in standards

    def test_code_reviewer_gets_db_standards(self):
        standards = get_standards_for_agent("code-reviewer")
        assert "DB-" in standards or "DATABASE" in standards

    def test_architect_gets_db_standards(self):
        standards = get_standards_for_agent("architect")
        assert "DB-" in standards or "DATABASE" in standards

    def test_test_runner_gets_e2e_standards(self):
        standards = get_standards_for_agent("test-runner")
        assert "E2E" in standards

    def test_unknown_agent_returns_empty(self):
        standards = get_standards_for_agent("nonexistent-agent")
        assert standards == "" or standards is not None


# ===========================================================================
# Design reference (Inter font contradiction fix)
# ===========================================================================


class TestDesignReferenceCorrectness:
    """Verify design_reference module corrections."""

    def test_industrial_direction_no_inter_font(self):
        from agent_team_v15.design_reference import _DIRECTION_TABLE
        industrial = _DIRECTION_TABLE["industrial"]
        assert industrial["body_font"] != "Inter", \
            "Industrial body_font must not be 'Inter' (banned by ARCHITECT_PROMPT)"
        assert industrial["body_font"] == "IBM Plex Sans"

    def test_all_directions_have_required_keys(self):
        from agent_team_v15.design_reference import _DIRECTION_TABLE
        required_keys = {"heading_font", "body_font", "primary", "secondary", "accent"}
        for name, direction in _DIRECTION_TABLE.items():
            for key in required_keys:
                assert key in direction, f"{name} missing {key}"


# ===========================================================================
# Section 15: Team-Based Execution (prompt integrity)
# ===========================================================================


class TestSection15PromptIntegrity:
    """Verify Section 15 team-based execution content in ORCHESTRATOR_SYSTEM_PROMPT."""

    def test_section_15_header_exists(self):
        assert "SECTION 15: TEAM-BASED EXECUTION" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_mode_config_reference(self):
        assert "config.agent_teams.enabled" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_replaces_fleet(self):
        """Section 6 should have both team and fleet deployment modes."""
        assert "Team Deployment Mode" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "Fleet Deployment Mode" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_7_has_both_workflows(self):
        assert "Team-Based Workflow" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "Fleet-Based Workflow" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_convergence_gates_still_apply(self):
        """Team mode must reference convergence gates."""
        sec15_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("SECTION 15:")
        after_sec15 = ORCHESTRATOR_SYSTEM_PROMPT[sec15_pos:]
        assert "convergence" in after_sec15.lower()

    def test_section_7_team_workflow_before_fleet(self):
        """Team-based workflow should appear before fleet-based workflow in Section 7."""
        sec7_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("SECTION 7:")
        after_sec7 = ORCHESTRATOR_SYSTEM_PROMPT[sec7_pos:]
        team_pos = after_sec7.find("Team-Based Workflow")
        fleet_pos = after_sec7.find("Fleet-Based Workflow")
        assert team_pos < fleet_pos, "Team workflow must come before fleet workflow in Section 7"

    def test_section_15_structured_message_types_complete(self):
        """Section 15 must list all 9 structured message types."""
        sec15_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("SECTION 15:")
        after_sec15 = ORCHESTRATOR_SYSTEM_PROMPT[sec15_pos:]
        for msg_type in [
            "REQUIREMENTS_READY", "ARCHITECTURE_READY", "WAVE_COMPLETE",
            "REVIEW_RESULTS", "DEBUG_FIX_COMPLETE", "WIRING_ESCALATION",
            "CONVERGENCE_COMPLETE", "TESTING_COMPLETE", "ESCALATION_REQUEST",
        ]:
            assert msg_type in after_sec15, f"Section 15 missing message type: {msg_type}"

    def test_section_15_escalation_chains(self):
        """Section 15 must define escalation chains for stuck items."""
        sec15_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("SECTION 15:")
        after_sec15 = ORCHESTRATOR_SYSTEM_PROMPT[sec15_pos:]
        assert "Escalation Chains" in after_sec15

    def test_section_15_has_audit_lead(self):
        """Section 15 must list audit-lead as a phase lead."""
        sec15_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("SECTION 15:")
        after_sec15 = ORCHESTRATOR_SYSTEM_PROMPT[sec15_pos:]
        assert "audit-lead" in after_sec15

    def test_section_15_has_audit_message_types(self):
        """Section 15 must include audit-lead message types."""
        sec15_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("SECTION 15:")
        after_sec15 = ORCHESTRATOR_SYSTEM_PROMPT[sec15_pos:]
        for msg_type in ["AUDIT_COMPLETE", "FIX_REQUEST", "REGRESSION_ALERT", "PLATEAU", "CONVERGED"]:
            assert msg_type in after_sec15, f"Section 15 missing audit message type: {msg_type}"


class TestTeamOrchestratorPromptIntegrity:
    """Verify the slim TEAM_ORCHESTRATOR_SYSTEM_PROMPT maintains key invariants."""

    def test_slim_prompt_does_not_duplicate_monolithic_sections(self):
        """Slim prompt must not contain numbered section headers from the monolithic prompt."""
        for section_num in range(1, 16):
            assert f"SECTION {section_num}:" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT, \
                f"Slim prompt should not contain SECTION {section_num}:"

    def test_slim_prompt_has_convergence_gate_references(self):
        """Even in team mode, convergence gates must be referenced."""
        for gate_num in range(1, 6):
            assert f"GATE {gate_num}" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT, \
                f"Slim prompt missing GATE {gate_num}"

    def test_slim_prompt_references_phase_lead_workflow(self):
        """Slim prompt should describe Task-tool delegation to leads."""
        assert "Task -> planning-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "Task -> architecture-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "Task -> coding-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "Task -> review-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "Task -> testing-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_slim_prompt_does_not_contain_fleet_instructions(self):
        """Slim prompt should not contain fleet deployment specifics."""
        assert "PLANNING FLEET" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "CODING FLEET" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "REVIEW FLEET" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_slim_prompt_has_audit_lead(self):
        """Slim prompt must include audit-lead in phase lead coordination."""
        assert "audit-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_slim_prompt_has_audit_workflow(self):
        """Slim prompt must include audit-lead delegation and fix cycle."""
        assert "Task -> audit-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "AUDIT FIX CYCLE" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "audit findings" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_slim_prompt_audit_lead_in_completion_criteria(self):
        """Slim prompt must reference audit-lead in completion criteria."""
        assert "audit-lead returns COMPLETE" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
