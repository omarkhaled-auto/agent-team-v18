"""Tests for agent_team.agents."""

from __future__ import annotations

from pathlib import Path

from agent_team_v15.agents import (
    ARCHITECT_PROMPT,
    ARCHITECTURE_LEAD_PROMPT,
    CODE_REVIEWER_PROMPT,
    CODE_WRITER_PROMPT,
    CODING_LEAD_PROMPT,
    CONTRACT_GENERATOR_PROMPT,
    DEBUGGER_PROMPT,
    INTEGRATION_AGENT_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    PLANNER_PROMPT,
    PLANNING_LEAD_PROMPT,
    RESEARCHER_PROMPT,
    REVIEW_LEAD_PROMPT,
    SECURITY_AUDITOR_PROMPT,
    SPEC_VALIDATOR_PROMPT,
    TASK_ASSIGNER_PROMPT,
    TEST_RUNNER_PROMPT,
    TESTING_LEAD_PROMPT,
    _ALL_OUT_BACKEND_MANDATES,
    _ALL_OUT_FRONTEND_MANDATES,
    _TEAM_COMMUNICATION_PROTOCOL,
    build_agent_definitions,
    build_decomposition_prompt,
    build_milestone_execution_prompt,
    build_orchestrator_prompt,
    detect_stack_from_text,
    get_orchestrator_system_prompt,
    get_stack_instructions,
    check_context_budget,
    TEAM_ORCHESTRATOR_SYSTEM_PROMPT,
    _is_accounting_prd,
)
from agent_team_v15.config import AgentConfig, AgentTeamConfig, AgentTeamsConfig, ConstraintEntry, PhaseLeadsConfig, SchedulerConfig, VerificationConfig


# ===================================================================
# Prompt constants
# ===================================================================

class TestPromptConstants:
    def test_orchestrator_prompt_non_empty(self):
        assert len(ORCHESTRATOR_SYSTEM_PROMPT) > 100

    def test_planner_prompt_non_empty(self):
        assert len(PLANNER_PROMPT) > 100

    def test_researcher_prompt_non_empty(self):
        assert len(RESEARCHER_PROMPT) > 100

    def test_architect_prompt_non_empty(self):
        assert len(ARCHITECT_PROMPT) > 100

    def test_code_writer_prompt_non_empty(self):
        assert len(CODE_WRITER_PROMPT) > 100

    def test_code_reviewer_prompt_non_empty(self):
        assert len(CODE_REVIEWER_PROMPT) > 100

    def test_test_runner_prompt_non_empty(self):
        assert len(TEST_RUNNER_PROMPT) > 100

    def test_security_auditor_prompt_non_empty(self):
        assert len(SECURITY_AUDITOR_PROMPT) > 100

    def test_debugger_prompt_non_empty(self):
        assert len(DEBUGGER_PROMPT) > 100

    def test_task_assigner_prompt_non_empty(self):
        assert len(TASK_ASSIGNER_PROMPT) > 100

    def test_orchestrator_dockerfile_standards_do_not_hardcode_ports(self):
        assert "EXPOSE 8080 for backend services" not in ORCHESTRATOR_SYSTEM_PROMPT
        assert "EXPOSE 80 for frontend" not in ORCHESTRATOR_SYSTEM_PROMPT
        assert "do not invent 8080/80" in ORCHESTRATOR_SYSTEM_PROMPT.lower()

    def test_orchestrator_has_convergence_placeholders(self):
        assert "$escalation_threshold" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "$max_escalation_depth" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_section_headers(self):
        assert "SECTION 1:" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "SECTION 2:" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "SECTION 3:" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_planner_references_requirements(self):
        assert "REQUIREMENTS.md" in PLANNER_PROMPT

    def test_researcher_references_context7(self):
        assert "Context7" in RESEARCHER_PROMPT

    def test_framework_idioms_unavailable_note_blocks_best_judgment(self):
        from agent_team_v15.cli import _framework_idioms_unavailable_note

        note = _framework_idioms_unavailable_note()
        assert "BLOCKED" in note
        assert "Context7" in note
        assert "Use your best judgment" not in note
        assert "best judgment" not in note.lower()

    def test_researcher_references_firecrawl(self):
        assert "firecrawl" in RESEARCHER_PROMPT.lower()

    def test_architect_references_wiring_map(self):
        assert "Wiring Map" in ARCHITECT_PROMPT

    def test_reviewer_is_adversarial(self):
        assert "ADVERSARIAL" in CODE_REVIEWER_PROMPT

    def test_task_assigner_references_dag(self):
        assert "DAG" in TASK_ASSIGNER_PROMPT

    def test_debugger_references_wire(self):
        assert "WIRE-xxx" in DEBUGGER_PROMPT

    def test_integration_agent_prompt_non_empty(self):
        assert len(INTEGRATION_AGENT_PROMPT) > 100

    def test_contract_generator_prompt_non_empty(self):
        assert len(CONTRACT_GENERATOR_PROMPT) > 100

    def test_orchestrator_has_section_0(self):
        assert "SECTION 0:" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_section_3c(self):
        assert "SECTION 3c:" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_section_3d(self):
        assert "SECTION 3d:" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_planner_has_codebase_map_awareness(self):
        assert "codebase map" in PLANNER_PROMPT.lower()

    def test_architect_has_contract_awareness(self):
        assert "contract" in ARCHITECT_PROMPT.lower()

    def test_task_assigner_has_scheduler_awareness(self):
        assert "scheduler" in TASK_ASSIGNER_PROMPT.lower()

    def test_code_writer_has_integration_declarations(self):
        assert "Integration Declarations" in CODE_WRITER_PROMPT

    def test_code_reviewer_has_verification_awareness(self):
        assert "VERIFICATION.md" in CODE_REVIEWER_PROMPT

    def test_orchestrator_has_contract_generator_step(self):
        assert "CONTRACT GENERATOR" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_convergence_gates(self):
        assert "GATE 1" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "GATE 2" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "GATE 3" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "GATE 4" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_section_8(self):
        assert "SECTION 8" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_constraint_enforcement(self):
        assert "CONSTRAINT ENFORCEMENT" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_intervention_awareness(self):
        assert "USER INTERVENTION" in ORCHESTRATOR_SYSTEM_PROMPT or "INTERVENTION" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_code_reviewer_has_review_authority(self):
        assert "ONLY" in CODE_REVIEWER_PROMPT
        assert "authorized" in CODE_REVIEWER_PROMPT

    def test_debugger_has_review_boundary(self):
        assert "CANNOT" in DEBUGGER_PROMPT
        assert "mark" in DEBUGGER_PROMPT.lower()


# ===================================================================
# build_agent_definitions()
# ===================================================================

class TestBuildAgentDefinitions:
    def test_returns_17_agents_default(self, default_config):
        """Default config includes 12 base agents plus 5 audit-team agents."""
        agents = build_agent_definitions(default_config, {})
        assert len(agents) == 17

    def test_returns_16_without_scheduler(self):
        """Disabling scheduler removes integration-agent: 16 agents."""
        cfg = AgentTeamConfig(scheduler=SchedulerConfig(enabled=False))
        agents = build_agent_definitions(cfg, {})
        assert len(agents) == 16
        assert "integration-agent" not in agents

    def test_returns_16_without_verification(self):
        """Disabling verification removes contract-generator: 16 agents."""
        cfg = AgentTeamConfig(verification=VerificationConfig(enabled=False))
        agents = build_agent_definitions(cfg, {})
        assert len(agents) == 16
        assert "contract-generator" not in agents

    def test_returns_17_agents_with_both(self, full_config_with_new_features):
        """All base features enabled returns 17 agents including audit-team agents."""
        agents = build_agent_definitions(full_config_with_new_features, {})
        assert len(agents) == 17
        assert "integration-agent" in agents
        assert "contract-generator" in agents
        assert "spec-validator" in agents

    def test_integration_agent_present_by_default(self, default_config):
        """Scheduler enabled by default → integration-agent present."""
        agents = build_agent_definitions(default_config, {})
        assert "integration-agent" in agents

    def test_contract_generator_present_by_default(self, default_config):
        """Verification enabled by default → contract-generator present."""
        agents = build_agent_definitions(default_config, {})
        assert "contract-generator" in agents

    def test_agent_names_are_hyphenated(self, default_config):
        agents = build_agent_definitions(default_config, {})
        expected = {
            "planner", "researcher", "architect", "task-assigner",
            "code-writer", "code-reviewer", "test-runner",
            "security-auditor", "debugger",
            "integration-agent", "contract-generator", "spec-validator",
            "audit-comprehensive", "audit-interface", "audit-requirements",
            "audit-scorer", "audit-technical",
        }
        assert set(agents.keys()) == expected

    def test_disabled_agent_excluded(self, config_with_disabled_agents):
        agents = build_agent_definitions(config_with_disabled_agents, {})
        assert "planner" not in agents
        assert "researcher" not in agents
        assert "debugger" not in agents

    def test_v1_agents_disabled_keeps_audit_team_and_spec_validator(self):
        """Audit-team agents and spec-validator remain when v1 agents are disabled."""
        cfg = AgentTeamConfig()
        for name in cfg.agents:
            cfg.agents[name] = AgentConfig(enabled=False)
        agents = build_agent_definitions(cfg, {})
        assert len(agents) == 6
        assert "spec-validator" in agents
        assert {
            "audit-comprehensive",
            "audit-interface",
            "audit-requirements",
            "audit-scorer",
            "audit-technical",
        }.issubset(agents)

    def test_researcher_no_mcp_tools_even_with_servers(self, default_config):
        """MCP tools are NOT in researcher — orchestrator calls them directly."""
        servers = {"firecrawl": {"type": "stdio"}, "context7": {"type": "stdio"}}
        agents = build_agent_definitions(default_config, servers)
        researcher_tools = agents["researcher"]["tools"]
        # MCP servers aren't propagated to sub-agents, so researcher
        # should NOT have firecrawl or context7 tool names.
        assert not any("firecrawl" in t for t in researcher_tools)
        assert not any("context7" in t for t in researcher_tools)

    def test_researcher_has_web_tools(self, default_config):
        """Researcher still has WebSearch and WebFetch for direct use."""
        agents = build_agent_definitions(default_config, {})
        researcher_tools = agents["researcher"]["tools"]
        assert "WebSearch" in researcher_tools
        assert "WebFetch" in researcher_tools

    def test_all_agents_use_opus(self, default_config):
        agents = build_agent_definitions(default_config, {})
        for name, defn in agents.items():
            assert defn["model"] == "opus", f"{name} model should be opus"

    def test_planner_tools(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "Read" in agents["planner"]["tools"]
        assert "Write" in agents["planner"]["tools"]
        assert "Bash" in agents["planner"]["tools"]

    def test_each_agent_has_description_and_prompt(self, default_config):
        agents = build_agent_definitions(default_config, {})
        for name, defn in agents.items():
            assert "description" in defn, f"{name} missing description"
            assert "prompt" in defn, f"{name} missing prompt"
            assert len(defn["description"]) > 0
            assert len(defn["prompt"]) > 0

    def test_each_agent_has_tools(self, default_config):
        agents = build_agent_definitions(default_config, {})
        for name, defn in agents.items():
            assert "tools" in defn, f"{name} missing tools"
            assert len(defn["tools"]) > 0


# ===================================================================
# build_orchestrator_prompt()
# ===================================================================

class TestAgentNamingConsistency:
    """Tests for Finding #17: config keys map to hyphenated SDK names."""

    def test_all_config_keys_produce_sdk_names(self):
        """Every default config agent key should produce an agent in the output."""
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {})
        # All 12 default agents should be present (scheduler+verification enabled by default)
        expected_sdk_names = {
            "planner", "researcher", "architect", "task-assigner",
            "code-writer", "code-reviewer", "test-runner",
            "security-auditor", "debugger",
            "integration-agent", "contract-generator", "spec-validator",
        }
        assert expected_sdk_names.issubset(set(agents.keys()))

    def test_underscore_to_hyphen_mapping(self):
        """Config keys with underscores produce hyphenated SDK names."""
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {})
        # Verify specific underscore->hyphen mappings
        assert "task-assigner" in agents  # from config key "task_assigner"
        assert "code-writer" in agents     # from config key "code_writer"
        assert "code-reviewer" in agents   # from config key "code_reviewer"
        assert "test-runner" in agents     # from config key "test_runner"
        assert "security-auditor" in agents  # from config key "security_auditor"

    def test_no_underscore_names_in_output(self):
        """SDK agent names should never contain underscores."""
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {})
        for name in agents.keys():
            assert "_" not in name, f"Agent name '{name}' contains underscore"


class TestPerAgentModelConfig:
    """Tests for Finding #4: per-agent model configuration."""

    def test_custom_model_propagates(self):
        """Config with planner.model = 'sonnet' should produce a planner with model 'sonnet'."""
        cfg = AgentTeamConfig()
        cfg.agents["planner"] = AgentConfig(model="sonnet")
        agents = build_agent_definitions(cfg, {})
        assert agents["planner"]["model"] == "sonnet"

    def test_default_model_is_opus(self):
        """Default config should produce agents with model 'opus'."""
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {})
        assert agents["planner"]["model"] == "opus"
        assert agents["code-writer"]["model"] == "opus"

    def test_each_agent_respects_own_model(self):
        """Each agent reads its own model config, not a global one."""
        cfg = AgentTeamConfig()
        cfg.agents["code_writer"] = AgentConfig(model="haiku")
        cfg.agents["researcher"] = AgentConfig(model="sonnet")
        agents = build_agent_definitions(cfg, {})
        assert agents["code-writer"]["model"] == "haiku"
        assert agents["researcher"]["model"] == "sonnet"
        assert agents["planner"]["model"] == "opus"  # unchanged


class TestBuildOrchestratorPrompt:
    def test_contains_depth_label(self, default_config):
        prompt = build_orchestrator_prompt("fix bug", "thorough", default_config)
        assert "[DEPTH: THOROUGH]" in prompt

    def test_contains_task_text(self, default_config):
        prompt = build_orchestrator_prompt("fix the login bug", "standard", default_config)
        assert "fix the login bug" in prompt

    def test_contains_agent_count(self, default_config):
        prompt = build_orchestrator_prompt("task", "standard", default_config, agent_count=5)
        assert "AGENT COUNT: 5" in prompt

    def test_contains_prd_path(self, default_config):
        prompt = build_orchestrator_prompt("task", "exhaustive", default_config, prd_path="/tmp/prd.md")
        assert "PRD MODE ACTIVE" in prompt
        assert "/tmp/prd.md" in prompt

    def test_contains_cwd(self, default_config):
        prompt = build_orchestrator_prompt("task", "standard", default_config, cwd="/project")
        assert "[PROJECT DIR: /project]" in prompt

    def test_contains_interview_doc(self, default_config, sample_interview_doc):
        prompt = build_orchestrator_prompt(
            "task", "standard", default_config,
            interview_doc=sample_interview_doc,
        )
        assert "INTERVIEW DOCUMENT" in prompt
        assert "Feature Brief: Login Page" in prompt

    def test_contains_design_reference_urls(self, default_config):
        urls = ["https://stripe.com", "https://linear.app"]
        prompt = build_orchestrator_prompt(
            "task", "standard", default_config,
            design_reference_urls=urls,
        )
        assert "DESIGN REFERENCE" in prompt
        assert "https://stripe.com" in prompt
        assert "https://linear.app" in prompt

    def test_contains_codebase_map_summary(self, default_config):
        summary = "## Codebase Map\n- 50 files\n- Python primary"
        prompt = build_orchestrator_prompt(
            "task", "standard", default_config,
            codebase_map_summary=summary,
        )
        assert "CODEBASE MAP" in prompt
        assert "50 files" in prompt

    def test_no_codebase_map_when_none(self, default_config):
        prompt = build_orchestrator_prompt("task", "standard", default_config)
        assert "CODEBASE MAP" not in prompt or "SECTION 0" not in prompt

    def test_fleet_scaling_section(self, default_config):
        prompt = build_orchestrator_prompt("task", "standard", default_config)
        assert "FLEET SCALING" in prompt
        assert "planning:" in prompt
        assert "research:" in prompt

    # --- COMPLEX interview → PRD mode tests ---

    def test_complex_interview_activates_prd_mode(self, default_config, sample_complex_interview_doc):
        """COMPLEX interview_scope + interview_doc → PRD MODE ACTIVE with INTERVIEW.md path."""
        prompt = build_orchestrator_prompt(
            "task", "exhaustive", default_config,
            interview_doc=sample_complex_interview_doc,
            interview_scope="COMPLEX",
        )
        assert "PRD MODE ACTIVE" in prompt
        assert "INTERVIEW.md" in prompt
        assert "already injected inline" in prompt

    def test_complex_interview_prd_instructions(self, default_config, sample_complex_interview_doc):
        """COMPLEX scope → PRD-specific instructions (analyzer fleet, MASTER_PLAN.md)."""
        prompt = build_orchestrator_prompt(
            "task", "exhaustive", default_config,
            interview_doc=sample_complex_interview_doc,
            interview_scope="COMPLEX",
        )
        assert "PRD ANALYZER FLEET" in prompt
        assert "MASTER_PLAN.md" in prompt
        assert "per-milestone REQUIREMENTS.md" in prompt
        # Should NOT contain standard planner instructions
        assert "PLANNING FLEET to create REQUIREMENTS.md" not in prompt

    def test_medium_interview_no_prd_mode(self, default_config, sample_interview_doc):
        """MEDIUM scope → no PRD mode activation."""
        prompt = build_orchestrator_prompt(
            "task", "standard", default_config,
            interview_doc=sample_interview_doc,
            interview_scope="MEDIUM",
        )
        assert "PRD MODE ACTIVE" not in prompt
        assert "PLANNING FLEET to create REQUIREMENTS.md" in prompt

    def test_prd_path_takes_precedence(self, default_config, sample_complex_interview_doc):
        """prd_path + COMPLEX → only prd_path PRD MODE marker, not interview-based one."""
        prompt = build_orchestrator_prompt(
            "task", "exhaustive", default_config,
            prd_path="/tmp/spec.md",
            interview_doc=sample_complex_interview_doc,
            interview_scope="COMPLEX",
        )
        # prd_path marker should be present
        assert "/tmp/spec.md" in prompt
        # Interview-based PRD MODE should NOT be present (guard: not prd_path)
        assert "already injected inline" not in prompt
        # PRD instructions should still activate (is_prd_mode is True from prd_path)
        assert "PRD ANALYZER FLEET" in prompt

    def test_no_scope_no_prd_mode(self, default_config, sample_interview_doc):
        """No interview_scope → no PRD mode even with interview_doc."""
        prompt = build_orchestrator_prompt(
            "task", "standard", default_config,
            interview_doc=sample_interview_doc,
        )
        assert "PRD MODE ACTIVE" not in prompt
        assert "PLANNING FLEET to create REQUIREMENTS.md" in prompt


# ===================================================================
# Template substitution (Finding #20)
# ===================================================================

class TestTemplateSubstitution:
    """Tests for Finding #20: template variable safety."""

    def test_template_variables_substituted(self):
        """Template variables in orchestrator prompt should be substituted correctly."""
        import string
        prompt = string.Template(ORCHESTRATOR_SYSTEM_PROMPT).safe_substitute(
            escalation_threshold="3",
            max_escalation_depth="2",
        )
        assert "$escalation_threshold" not in prompt
        assert "$max_escalation_depth" not in prompt
        assert "3" in prompt  # the substituted value
        assert "2" in prompt

    def test_safe_substitute_leaves_unknown_vars(self):
        """safe_substitute should not crash on unknown template variables."""
        import string
        prompt = string.Template(ORCHESTRATOR_SYSTEM_PROMPT).safe_substitute(
            escalation_threshold="5",
            # deliberately missing max_escalation_depth
        )
        # Should not raise, just leave $max_escalation_depth as-is
        assert "$max_escalation_depth" in prompt

    def test_no_curly_brace_template_vars(self):
        """Prompt should not contain {variable} style templates."""
        assert "{escalation_threshold}" not in ORCHESTRATOR_SYSTEM_PROMPT
        assert "{max_escalation_depth}" not in ORCHESTRATOR_SYSTEM_PROMPT


# ===================================================================
# Constraint injection
# ===================================================================

class TestConstraintInjection:
    """Tests for constraint injection into agent prompts."""

    def test_constraints_appear_in_agent_prompts(self, default_config):
        constraints = [ConstraintEntry("no library swaps", "prohibition", "task", 2)]
        agents = build_agent_definitions(default_config, {}, constraints=constraints)
        for name, defn in agents.items():
            assert "no library swaps" in defn["prompt"], f"{name} missing constraint"

    def test_none_constraints_no_change(self, default_config):
        agents_without = build_agent_definitions(default_config, {})
        agents_with_none = build_agent_definitions(default_config, {}, constraints=None)
        for name in agents_without:
            assert agents_without[name]["prompt"] == agents_with_none[name]["prompt"]

    def test_empty_constraints_no_change(self, default_config):
        agents_without = build_agent_definitions(default_config, {})
        agents_with_empty = build_agent_definitions(default_config, {}, constraints=[])
        for name in agents_without:
            assert agents_without[name]["prompt"] == agents_with_empty[name]["prompt"]

    def test_constraint_block_format(self):
        constraints = [ConstraintEntry("no changes", "prohibition", "task", 2)]
        agents = build_agent_definitions(AgentTeamConfig(), {}, constraints=constraints)
        # Check that the constraint block header is present
        for name, defn in agents.items():
            assert "USER CONSTRAINTS" in defn["prompt"]

    def test_constraints_in_orchestrator_prompt(self, default_config):
        constraints = [ConstraintEntry("only restyle SCSS", "scope", "task", 1)]
        prompt = build_orchestrator_prompt(
            "restyle the app", "thorough", default_config,
            constraints=constraints,
        )
        assert "only restyle SCSS" in prompt


# ===================================================================
# Convergence gates
# ===================================================================

class TestConvergenceGates:
    """Tests for convergence gate content in prompts."""

    def test_gate_1_review_authority(self):
        assert "REVIEW" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "GATE 1" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_gate_2_mandatory_re_review(self):
        assert "GATE 2" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "Re-Review" in ORCHESTRATOR_SYSTEM_PROMPT or "re-review" in ORCHESTRATOR_SYSTEM_PROMPT.lower()

    def test_gate_3_cycle_reporting(self):
        assert "GATE 3" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_gate_4_depth_thoroughness(self):
        assert "GATE 4" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_reviewer_exclusive_authority(self):
        assert "ONLY" in CODE_REVIEWER_PROMPT
        assert "[x]" in CODE_REVIEWER_PROMPT

    def test_debugger_cannot_mark(self):
        assert "CANNOT" in DEBUGGER_PROMPT
        assert "code-reviewer" in DEBUGGER_PROMPT.lower() or "reviewer" in DEBUGGER_PROMPT.lower()

    def test_orchestrator_has_show_fleet_composition_placeholder(self):
        assert "$show_fleet_composition" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_show_convergence_status_placeholder(self):
        assert "$show_convergence_status" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_max_cycles_placeholder(self):
        assert "$max_cycles" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_master_plan_file_placeholder(self):
        assert "$master_plan_file" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_max_budget_placeholder(self):
        assert "$max_budget_usd" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_section_6b(self):
        assert "SECTION 6b:" in ORCHESTRATOR_SYSTEM_PROMPT


# ===================================================================
# build_orchestrator_prompt depth handling
# ===================================================================

class TestBuildOrchestratorPromptDepthHandling:
    """Test that build_orchestrator_prompt handles both str and DepthDetection."""

    def test_string_depth_works(self, default_config):
        prompt = build_orchestrator_prompt("test", "thorough", default_config)
        assert "[DEPTH: THOROUGH]" in prompt

    def test_depth_detection_works(self, default_config):
        from agent_team_v15.config import DepthDetection
        det = DepthDetection("exhaustive", "keyword", ["exhaustive"], "test")
        prompt = build_orchestrator_prompt("test", det, default_config)
        assert "[DEPTH: EXHAUSTIVE]" in prompt

    def test_constraints_param_default_none(self, default_config):
        # Should work without constraints parameter
        prompt = build_orchestrator_prompt("test", "standard", default_config)
        assert "[DEPTH: STANDARD]" in prompt

    def test_orchestrator_prompt_has_resume_context_placeholder(self, default_config):
        """resume_context param is accepted without error."""
        prompt = build_orchestrator_prompt(
            "test", "standard", default_config,
            resume_context="[RESUME MODE -- test]",
        )
        assert "[RESUME MODE -- test]" in prompt

    def test_resume_context_injected_before_task(self, default_config):
        """resume_context should appear before [TASK] in the prompt."""
        ctx = "[RESUME MODE -- Continuing from an interrupted run]"
        prompt = build_orchestrator_prompt(
            "fix the bug", "standard", default_config,
            resume_context=ctx,
        )
        ctx_pos = prompt.index(ctx)
        task_pos = prompt.index("[TASK]")
        assert ctx_pos < task_pos


# ===================================================================
# build_orchestrator_prompt() — design reference cache & dedup
# ===================================================================

class TestDesignReferenceCacheAndDedup:
    def test_prompt_contains_cache_ttl(self, default_config):
        urls = ["https://stripe.com"]
        prompt = build_orchestrator_prompt(
            "task", "standard", default_config,
            design_reference_urls=urls,
        )
        assert "Cache TTL (maxAge): 7200000 milliseconds" in prompt

    def test_cache_ttl_in_milliseconds(self, default_config):
        default_config.design_reference.cache_ttl_seconds = 3600
        urls = ["https://stripe.com"]
        prompt = build_orchestrator_prompt(
            "task", "standard", default_config,
            design_reference_urls=urls,
        )
        assert "Cache TTL (maxAge): 3600000 milliseconds" in prompt

    def test_dedup_instruction_with_multiple_urls(self, default_config):
        urls = ["https://stripe.com", "https://linear.app"]
        prompt = build_orchestrator_prompt(
            "task", "standard", default_config,
            design_reference_urls=urls,
        )
        assert "URL ASSIGNMENT" in prompt
        assert "EXACTLY ONE researcher" in prompt

    def test_no_dedup_instruction_with_single_url(self, default_config):
        urls = ["https://stripe.com"]
        prompt = build_orchestrator_prompt(
            "task", "standard", default_config,
            design_reference_urls=urls,
        )
        assert "URL ASSIGNMENT" not in prompt


# ===================================================================
# UI Design Standards injection
# ===================================================================

class TestUIDesignStandardsInjection:
    """Tests for built-in UI design standards in orchestrator + agent prompts."""

    def test_always_contains_ui_standards(self, default_config):
        prompt = build_orchestrator_prompt("build a landing page", "standard", default_config)
        assert "UI DESIGN STANDARDS" in prompt
        assert "SLOP-001" in prompt
        assert "SLOP-015" in prompt

    def test_ui_standards_with_design_refs(self, default_config):
        urls = ["https://stripe.com"]
        prompt = build_orchestrator_prompt("task", "standard", default_config, design_reference_urls=urls)
        assert "UI DESIGN STANDARDS" in prompt
        assert "DESIGN REFERENCE" in prompt
        assert "OVERRIDES" in prompt

    def test_ui_standards_before_design_refs(self, default_config):
        urls = ["https://stripe.com"]
        prompt = build_orchestrator_prompt("task", "standard", default_config, design_reference_urls=urls)
        standards_pos = prompt.index("UI DESIGN STANDARDS")
        ref_pos = prompt.index("[DESIGN REFERENCE")
        assert standards_pos < ref_pos

    def test_custom_standards_file_used(self, default_config, tmp_path):
        custom = tmp_path / "my-standards.md"
        custom.write_text("MY CUSTOM DESIGN RULES", encoding="utf-8")
        default_config.design_reference.standards_file = str(custom)
        prompt = build_orchestrator_prompt("build UI", "standard", default_config)
        assert "MY CUSTOM DESIGN RULES" in prompt
        assert "SLOP-001" not in prompt

    def test_architect_has_design_system_architecture(self):
        assert "Design System Architecture" in ARCHITECT_PROMPT

    def test_code_writer_has_ui_quality_standards(self):
        assert "UI COMPLIANCE POLICY" in CODE_WRITER_PROMPT

    def test_code_reviewer_has_design_quality_review(self):
        assert "Design Quality Review" in CODE_REVIEWER_PROMPT

    def test_code_reviewer_has_anti_pattern_check(self):
        assert "SLOP-001" in CODE_REVIEWER_PROMPT


# ===================================================================
# Code Quality Standards injection
# ===================================================================

class TestCodeQualityInjection:
    """Tests that build_agent_definitions injects quality standards into the right agents."""

    def test_code_writer_has_frontend_standards(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "FRONT-001" in agents["code-writer"]["prompt"]
        assert "BACK-001" in agents["code-writer"]["prompt"]

    def test_code_reviewer_has_review_standards(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "REVIEW-001" in agents["code-reviewer"]["prompt"]

    def test_test_runner_has_testing_standards(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "TEST-001" in agents["test-runner"]["prompt"]

    def test_debugger_has_debugging_standards(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "DEBUG-001" in agents["debugger"]["prompt"]

    def test_architect_has_architecture_quality(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "ARCHITECTURE QUALITY" in agents["architect"]["prompt"]

    def test_planner_has_no_quality_standards(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "FRONT-001" not in agents["planner"]["prompt"]
        assert "BACK-001" not in agents["planner"]["prompt"]
        assert "REVIEW-001" not in agents["planner"]["prompt"]
        assert "TEST-001" not in agents["planner"]["prompt"]
        assert "DEBUG-001" not in agents["planner"]["prompt"]

    def test_researcher_has_no_quality_standards(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "FRONT-001" not in agents["researcher"]["prompt"]

    def test_task_assigner_has_no_quality_standards(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "FRONT-001" not in agents["task-assigner"]["prompt"]

    def test_security_auditor_has_no_quality_standards(self, default_config):
        agents = build_agent_definitions(default_config, {})
        assert "FRONT-001" not in agents["security-auditor"]["prompt"]
        assert "TEST-001" not in agents["security-auditor"]["prompt"]

    def test_quality_standards_after_constraints(self, default_config):
        """Quality standards appended after constraints."""
        constraints = [ConstraintEntry("Use Python 3.12", "requirement", "task", 1)]
        agents = build_agent_definitions(default_config, {}, constraints=constraints)
        prompt = agents["code-writer"]["prompt"]
        constraint_pos = prompt.index("Python 3.12")
        front_pos = prompt.index("FRONT-001")
        assert constraint_pos < front_pos

    def test_all_frontend_anti_patterns_in_code_writer(self, default_config):
        agents = build_agent_definitions(default_config, {})
        prompt = agents["code-writer"]["prompt"]
        for i in range(1, 16):
            code = f"FRONT-{i:03d}"
            assert code in prompt, f"Missing {code} in code-writer prompt"

    def test_all_backend_anti_patterns_in_code_writer(self, default_config):
        agents = build_agent_definitions(default_config, {})
        prompt = agents["code-writer"]["prompt"]
        for i in range(1, 16):
            code = f"BACK-{i:03d}"
            assert code in prompt, f"Missing {code} in code-writer prompt"

    def test_integration_agent_has_no_quality_standards(self):
        """integration-agent (scheduler-only) gets no quality standards."""
        from agent_team_v15.config import SchedulerConfig
        cfg = AgentTeamConfig(scheduler=SchedulerConfig(enabled=True))
        agents = build_agent_definitions(cfg, {})
        assert "integration-agent" in agents
        assert "FRONT-001" not in agents["integration-agent"]["prompt"]
        assert "REVIEW-001" not in agents["integration-agent"]["prompt"]

    def test_contract_generator_has_no_quality_standards(self):
        """contract-generator (verification-only) gets no quality standards."""
        from agent_team_v15.config import VerificationConfig
        cfg = AgentTeamConfig(verification=VerificationConfig(enabled=True))
        agents = build_agent_definitions(cfg, {})
        assert "contract-generator" in agents
        assert "FRONT-001" not in agents["contract-generator"]["prompt"]
        assert "TEST-001" not in agents["contract-generator"]["prompt"]

    def test_quality_standards_with_scheduler_enabled(self):
        """Quality standards still injected when scheduler is enabled."""
        from agent_team_v15.config import SchedulerConfig
        cfg = AgentTeamConfig(scheduler=SchedulerConfig(enabled=True))
        agents = build_agent_definitions(cfg, {})
        assert len(agents) == 17
        assert "FRONT-001" in agents["code-writer"]["prompt"]
        assert "REVIEW-001" in agents["code-reviewer"]["prompt"]

    def test_quality_standards_with_both_enabled(self):
        """Quality standards injected correctly with scheduler + verification."""
        from agent_team_v15.config import SchedulerConfig, VerificationConfig
        cfg = AgentTeamConfig(
            scheduler=SchedulerConfig(enabled=True),
            verification=VerificationConfig(enabled=True),
        )
        agents = build_agent_definitions(cfg, {})
        assert len(agents) == 17
        # Quality agents still get standards
        assert "FRONT-001" in agents["code-writer"]["prompt"]
        assert "DEBUG-001" in agents["debugger"]["prompt"]
        # Non-quality agents don't
        assert "FRONT-001" not in agents["integration-agent"]["prompt"]
        assert "FRONT-001" not in agents["contract-generator"]["prompt"]

    def test_all_disabled_no_crash_from_injection(self):
        """When v1 agents are disabled, injection loop still keeps audit/spec agents."""
        cfg = AgentTeamConfig()
        for name in cfg.agents:
            cfg.agents[name] = AgentConfig(enabled=False)
        agents = build_agent_definitions(cfg, {})
        assert len(agents) == 6
        assert "spec-validator" in agents

    def test_empty_constraints_plus_standards(self):
        """Empty constraints + standards: standards still injected, no constraints prefix."""
        agents = build_agent_definitions(AgentTeamConfig(), {}, constraints=[])
        prompt = agents["code-writer"]["prompt"]
        assert "FRONT-001" in prompt
        assert "USER CONSTRAINTS" not in prompt

    def test_custom_model_does_not_affect_standards(self):
        """Per-agent model config doesn't interfere with standards injection."""
        cfg = AgentTeamConfig()
        cfg.agents["code_writer"] = AgentConfig(model="sonnet")
        agents = build_agent_definitions(cfg, {})
        assert agents["code-writer"]["model"] == "sonnet"
        assert "FRONT-001" in agents["code-writer"]["prompt"]
        assert "BACK-001" in agents["code-writer"]["prompt"]


# ===================================================================
# Prompt strengthening
# ===================================================================

class TestPromptStrengthening:
    """Tests that agent prompt constants have their strengthening sections."""

    def test_architect_has_code_architecture_quality(self):
        assert "Code Architecture Quality" in ARCHITECT_PROMPT

    def test_code_writer_has_code_quality_standards(self):
        assert "Code Quality Standards" in CODE_WRITER_PROMPT

    def test_code_reviewer_has_code_quality_review(self):
        assert "Code Quality Review" in CODE_REVIEWER_PROMPT

    def test_test_runner_has_testing_quality_standards(self):
        assert "Testing Quality Standards" in TEST_RUNNER_PROMPT

    def test_debugger_has_debugging_methodology(self):
        assert "Debugging Methodology" in DEBUGGER_PROMPT


# ===================================================================
# SPEC_VALIDATOR_PROMPT
# ===================================================================

class TestSpecValidatorPrompt:
    def test_prompt_exists_and_non_empty(self):
        assert len(SPEC_VALIDATOR_PROMPT) > 100

    def test_contains_spec_fidelity(self):
        assert "SPEC FIDELITY" in SPEC_VALIDATOR_PROMPT

    def test_contains_original_user_request(self):
        assert "ORIGINAL USER REQUEST" in SPEC_VALIDATOR_PROMPT

    def test_contains_pass_fail(self):
        assert "PASS" in SPEC_VALIDATOR_PROMPT
        assert "FAIL" in SPEC_VALIDATOR_PROMPT

    def test_checks_missing_technologies(self):
        assert "Missing Technologies" in SPEC_VALIDATOR_PROMPT or "MISSING_TECH" in SPEC_VALIDATOR_PROMPT

    def test_checks_scope_reduction(self):
        assert "Scope Reduction" in SPEC_VALIDATOR_PROMPT or "SCOPE_REDUCTION" in SPEC_VALIDATOR_PROMPT

    def test_checks_missing_architecture(self):
        assert "Architecture" in SPEC_VALIDATOR_PROMPT or "ARCHITECTURE" in SPEC_VALIDATOR_PROMPT

    def test_spec_validator_in_agent_definitions(self):
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {})
        assert "spec-validator" in agents

    def test_spec_validator_read_only_tools(self):
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {})
        tools = agents["spec-validator"]["tools"]
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools
        assert "Write" not in tools
        assert "Edit" not in tools
        assert "Bash" not in tools

    def test_spec_validator_has_description(self):
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {})
        assert len(agents["spec-validator"]["description"]) > 0


# ===================================================================
# Reviewer anchoring to original request
# ===================================================================

class TestReviewerAnchoring:
    def test_reviewer_has_original_request_check(self):
        assert "ORIGINAL USER REQUEST" in CODE_REVIEWER_PROMPT

    def test_reviewer_has_step_1b(self):
        assert "1b." in CODE_REVIEWER_PROMPT

    def test_reviewer_flags_critical(self):
        assert "CRITICAL" in CODE_REVIEWER_PROMPT

    def test_orchestrator_passes_original_request_to_reviewers(self):
        assert "ORIGINAL USER REQUEST" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_build_orchestrator_prompt_has_original_request_section(self):
        cfg = AgentTeamConfig()
        prompt = build_orchestrator_prompt("build a REST API", "standard", cfg)
        assert "[ORIGINAL USER REQUEST]" in prompt
        assert "build a REST API" in prompt


# ===================================================================
# Planner guardrails + mandatory test wave
# ===================================================================

class TestPlannerGuardrails:
    def test_planner_has_technology_preservation(self):
        assert "MUST appear in REQUIREMENTS.md" in PLANNER_PROMPT

    def test_planner_has_monorepo_preservation(self):
        assert "monorepo" in PLANNER_PROMPT.lower()

    def test_planner_has_test_requirements(self):
        assert "Testing Requirements" in PLANNER_PROMPT

    def test_planner_prevents_architecture_simplification(self):
        assert "may NOT" in PLANNER_PROMPT or "may not" in PLANNER_PROMPT.lower()


class TestMandatoryTestWave:
    def test_orchestrator_has_mandatory_test_rule(self):
        assert "MANDATORY TEST RULE" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_mentions_test_keywords(self):
        assert "test suite" in ORCHESTRATOR_SYSTEM_PROMPT.lower() or "tests" in ORCHESTRATOR_SYSTEM_PROMPT.lower()

    def test_orchestrator_test_rule_is_blocking(self):
        assert "BLOCKING" in ORCHESTRATOR_SYSTEM_PROMPT


# ===================================================================
# Investigation protocol injection
# ===================================================================

class TestInvestigationInjection:
    """Tests that investigation protocol is injected into the right agents."""

    def test_protocol_injected_when_enabled(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "DEEP INVESTIGATION PROTOCOL" in agents["code-reviewer"]["prompt"]
        assert "DEEP INVESTIGATION PROTOCOL" in agents["security-auditor"]["prompt"]
        assert "DEEP INVESTIGATION PROTOCOL" in agents["debugger"]["prompt"]

    def test_protocol_not_injected_when_disabled(self):
        cfg = AgentTeamConfig()
        # Default: investigation.enabled = False
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "DEEP INVESTIGATION PROTOCOL" not in agents["code-reviewer"]["prompt"]
        assert "DEEP INVESTIGATION PROTOCOL" not in agents["debugger"]["prompt"]

    def test_protocol_not_injected_for_planner(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "DEEP INVESTIGATION PROTOCOL" not in agents["planner"]["prompt"]

    def test_protocol_not_injected_for_code_writer(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "DEEP INVESTIGATION PROTOCOL" not in agents["code-writer"]["prompt"]

    def test_bash_added_to_reviewer_with_gemini(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=True)
        assert "Bash" in agents["code-reviewer"]["tools"]

    def test_bash_not_added_to_reviewer_without_gemini(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "Bash" not in agents["code-reviewer"]["tools"]

    def test_bash_not_added_when_investigation_disabled(self):
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {}, gemini_available=True)
        assert "Bash" not in agents["code-reviewer"]["tools"]

    def test_gemini_section_in_reviewer_when_available(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=True)
        assert "Gemini CLI" in agents["code-reviewer"]["prompt"]

    def test_gemini_section_not_in_reviewer_without_gemini(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "Gemini CLI" not in agents["code-reviewer"]["prompt"]

    def test_protocol_all_three_agents_enabled(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=True)
        for name in ["code-reviewer", "security-auditor", "debugger"]:
            assert "DEEP INVESTIGATION PROTOCOL" in agents[name]["prompt"], (
                f"{name} should have investigation protocol"
            )

    def test_quality_standards_still_present_with_investigation(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=True)
        # Quality standards should still be injected
        assert "REVIEW-001" in agents["code-reviewer"]["prompt"]
        assert "DEBUG-001" in agents["debugger"]["prompt"]
        # Investigation protocol should also be present
        assert "DEEP INVESTIGATION PROTOCOL" in agents["code-reviewer"]["prompt"]
        assert "DEEP INVESTIGATION PROTOCOL" in agents["debugger"]["prompt"]


class TestSequentialThinkingInjection:
    """Tests that ST methodology is injected into the right agents."""

    def test_st_injected_when_investigation_and_st_enabled(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True, sequential_thinking=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "SEQUENTIAL THINKING METHODOLOGY" in agents["code-reviewer"]["prompt"]
        assert "SEQUENTIAL THINKING METHODOLOGY" in agents["security-auditor"]["prompt"]
        assert "SEQUENTIAL THINKING METHODOLOGY" in agents["debugger"]["prompt"]

    def test_st_not_injected_when_investigation_disabled(self):
        cfg = AgentTeamConfig()
        # Default: investigation.enabled = False
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "SEQUENTIAL THINKING METHODOLOGY" not in agents["code-reviewer"]["prompt"]

    def test_st_not_injected_when_st_disabled(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True, sequential_thinking=False)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "SEQUENTIAL THINKING METHODOLOGY" not in agents["code-reviewer"]["prompt"]
        # Investigation protocol should still be present
        assert "DEEP INVESTIGATION PROTOCOL" in agents["code-reviewer"]["prompt"]

    def test_st_not_injected_for_planner(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "SEQUENTIAL THINKING METHODOLOGY" not in agents["planner"]["prompt"]

    def test_st_not_injected_for_code_writer(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "SEQUENTIAL THINKING METHODOLOGY" not in agents["code-writer"]["prompt"]

    def test_st_appears_after_investigation_protocol(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        prompt = agents["code-reviewer"]["prompt"]
        ip_idx = prompt.index("DEEP INVESTIGATION PROTOCOL")
        st_idx = prompt.index("SEQUENTIAL THINKING METHODOLOGY")
        assert ip_idx < st_idx, "ST must appear after Investigation Protocol"

    def test_hypothesis_loop_present_by_default(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "Hypothesis-Verification Cycle" in agents["code-reviewer"]["prompt"]

    def test_hypothesis_loop_absent_when_disabled(self):
        from agent_team_v15.config import InvestigationConfig
        cfg = AgentTeamConfig()
        cfg.investigation = InvestigationConfig(enabled=True, enable_hypothesis_loop=False)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "Hypothesis-Verification Cycle" not in agents["code-reviewer"]["prompt"]
        # ST core should still be present
        assert "SEQUENTIAL THINKING METHODOLOGY" in agents["code-reviewer"]["prompt"]


# ===================================================================
# Quality Optimization: Production Readiness & Code Craft
# ===================================================================

class TestProductionReadinessDefaults:
    def test_planner_has_production_defaults(self):
        assert "PRODUCTION READINESS DEFAULTS" in PLANNER_PROMPT

    def test_planner_mentions_gitignore(self):
        assert ".gitignore" in PLANNER_PROMPT

    def test_planner_mentions_pagination(self):
        assert "pagination" in PLANNER_PROMPT.lower()

    def test_planner_mentions_nan(self):
        assert "NaN" in PLANNER_PROMPT

    def test_planner_mentions_transaction(self):
        assert "transaction" in PLANNER_PROMPT.lower()


class TestArchitectSharedUtilities:
    def test_architect_has_shared_utilities_map(self):
        assert "Shared Utilities Map" in ARCHITECT_PROMPT


class TestWriterQualitySections:
    def test_writer_has_validation_pattern(self):
        assert "Validation Middleware" in CODE_WRITER_PROMPT

    def test_writer_has_transaction_safety(self):
        assert "Transaction Safety" in CODE_WRITER_PROMPT

    def test_writer_has_param_validation(self):
        assert "Route Parameter Validation" in CODE_WRITER_PROMPT


class TestReviewerCraftReview:
    def test_reviewer_has_craft_review(self):
        assert "CODE CRAFT REVIEW" in CODE_REVIEWER_PROMPT

    def test_reviewer_has_all_craft_checks(self):
        craft_checks = [
            "CRAFT-DRY",
            "CRAFT-TYPES",
            "CRAFT-PARAMS",
            "CRAFT-TXN",
            "CRAFT-VALIDATION",
            "CRAFT-FK",
        ]
        for check in craft_checks:
            assert check in CODE_REVIEWER_PROMPT, f"Missing {check} in reviewer prompt"


class TestQualityConfigGating:
    """Verify config.quality flags control prompt content in build_agent_definitions."""

    def test_quick_depth_strips_production_defaults(self):
        from agent_team_v15.config import QualityConfig
        cfg = AgentTeamConfig()
        cfg.quality = QualityConfig(production_defaults=False)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "PRODUCTION READINESS DEFAULTS" not in agents["planner"]["prompt"]

    def test_standard_depth_keeps_production_defaults(self):
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "PRODUCTION READINESS DEFAULTS" in agents["planner"]["prompt"]

    def test_quick_depth_strips_craft_review(self):
        from agent_team_v15.config import QualityConfig
        cfg = AgentTeamConfig()
        cfg.quality = QualityConfig(craft_review=False)
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "CODE CRAFT REVIEW" not in agents["code-reviewer"]["prompt"]

    def test_standard_depth_keeps_craft_review(self):
        cfg = AgentTeamConfig()
        agents = build_agent_definitions(cfg, {}, gemini_available=False)
        assert "CODE CRAFT REVIEW" in agents["code-reviewer"]["prompt"]


# ===================================================================
# PRD Mode Prompt Builders - Design Reference URL Tests
# ===================================================================

class TestBuildDecompositionPromptDesignRefs:
    """Tests for design_reference_urls in build_decomposition_prompt."""

    def test_contains_design_reference_urls(self):
        """Decomposition prompt should include design reference URLs when provided."""
        cfg = AgentTeamConfig()
        urls = ["https://stripe.com", "https://linear.app"]
        prompt = build_decomposition_prompt(
            task="Build a dashboard",
            depth="standard",
            config=cfg,
            design_reference_urls=urls,
        )
        assert "DESIGN REFERENCE" in prompt
        assert "https://stripe.com" in prompt
        assert "https://linear.app" in prompt

    def test_no_design_reference_when_none(self):
        """Decomposition prompt should NOT include design reference section when None."""
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build a dashboard",
            depth="standard",
            config=cfg,
            design_reference_urls=None,
        )
        assert "DESIGN REFERENCE" not in prompt

    def test_design_reference_extraction_depth(self):
        """Decomposition prompt should include extraction depth config."""
        cfg = AgentTeamConfig()
        cfg.design_reference.depth = "full"
        urls = ["https://example.com"]
        prompt = build_decomposition_prompt(
            task="Build app",
            depth="standard",
            config=cfg,
            design_reference_urls=urls,
        )
        assert "Extraction depth: full" in prompt


class TestBuildMilestoneExecutionPromptDesignRefs:
    """Tests for design_reference_urls in build_milestone_execution_prompt."""

    def test_contains_design_reference_urls(self):
        """Milestone execution prompt should include design reference URLs when provided."""
        cfg = AgentTeamConfig()
        urls = ["https://stripe.com/docs", "https://tailwindcss.com"]
        prompt = build_milestone_execution_prompt(
            task="Build UI components",
            depth="standard",
            config=cfg,
            design_reference_urls=urls,
        )
        assert "DESIGN REFERENCE" in prompt
        assert "https://stripe.com/docs" in prompt
        assert "https://tailwindcss.com" in prompt

    def test_no_design_reference_when_none(self):
        """Milestone execution prompt should NOT include design reference section when None."""
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build UI",
            depth="standard",
            config=cfg,
            design_reference_urls=None,
        )
        assert "DESIGN REFERENCE" not in prompt

    def test_design_reference_includes_cache_ttl(self):
        """Milestone execution prompt should include cache TTL for Firecrawl."""
        cfg = AgentTeamConfig()
        cfg.design_reference.cache_ttl_seconds = 3600  # 1 hour
        urls = ["https://example.com"]
        prompt = build_milestone_execution_prompt(
            task="Build app",
            depth="standard",
            config=cfg,
            design_reference_urls=urls,
        )
        assert "Cache TTL (maxAge): 3600000 milliseconds" in prompt

    def test_design_reference_researcher_instruction(self):
        """Milestone execution prompt should instruct researcher assignment."""
        cfg = AgentTeamConfig()
        urls = ["https://example.com"]
        prompt = build_milestone_execution_prompt(
            task="Build app",
            depth="standard",
            config=cfg,
            design_reference_urls=urls,
        )
        assert "researcher" in prompt.lower()


# ===================================================================
# V16 Phase 1: Stub handler prohibition
# ===================================================================

class TestStubHandlerProhibition:
    """Verify SECTION 3a: STUB HANDLER PROHIBITION is in the system prompt."""

    def test_stub_prohibition_section_exists(self):
        assert "STUB HANDLER PROHIBITION" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_stub_prohibition_forbids_log_only(self):
        assert "log-only stub" in ORCHESTRATOR_SYSTEM_PROMPT.lower() or \
               "MUST NOT be a log-only stub" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_stub_prohibition_mentions_detection(self):
        assert "STUB-001" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_stub_prohibition_has_bad_example(self):
        assert "logger.info(\"Received invoice.created" in ORCHESTRATOR_SYSTEM_PROMPT or \
               "logger.info(" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_stub_prohibition_has_good_example(self):
        assert "create_journal_entry" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_stub_prohibition_before_task_assignment(self):
        stub_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("STUB HANDLER PROHIBITION")
        task_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("SECTION 3b: TASK ASSIGNMENT")
        assert stub_pos < task_pos, "Stub prohibition must come before task assignment"


# ===================================================================
# V16 Phase 1.4: Cross-service standards in system prompt
# ===================================================================

class TestCrossServiceStandards:
    """Verify SECTION 9: CROSS-SERVICE IMPLEMENTATION STANDARDS is present."""

    def test_section_9_exists(self):
        assert "SECTION 9: CROSS-SERVICE IMPLEMENTATION STANDARDS" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_error_response_format(self):
        assert "RESOURCE_NOT_FOUND" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "VALIDATION_ERROR" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_testing_requirements(self):
        assert "pytest + httpx" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "jest" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_state_machine_standard(self):
        assert "VALID_TRANSITIONS" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "409 Conflict" in ORCHESTRATOR_SYSTEM_PROMPT or "HTTP 409" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_business_logic_depth(self):
        assert "Service classes contain ALL business logic" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_security_requirements(self):
        assert "Rate limiting" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "CORS_ORIGINS" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_database_standards(self):
        assert "Alembic" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "synchronize: false" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_dockerfile_standards(self):
        assert "start-period=90s" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "127.0.0.1" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "urllib.request" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_handler_completeness_standard(self):
        assert "Input validation" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "tenant_id from JWT" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_standards_after_constraint_enforcement(self):
        standards_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("SECTION 9")
        constraint_pos = ORCHESTRATOR_SYSTEM_PROMPT.find("SECTION 8: CONSTRAINT")
        assert standards_pos > constraint_pos


# ===================================================================
# V16 Phase 1.7: All-out mandates injection
# ===================================================================

class TestAllOutMandates:
    """Verify all-out mandates exist as constants and inject into prompts."""

    def test_backend_mandates_non_empty(self):
        assert len(_ALL_OUT_BACKEND_MANDATES) > 1000

    def test_frontend_mandates_non_empty(self):
        assert len(_ALL_OUT_FRONTEND_MANDATES) > 500

    def test_backend_mandates_covers_bulk_ops(self):
        assert "bulk create" in _ALL_OUT_BACKEND_MANDATES.lower()

    def test_backend_mandates_covers_audit_trail(self):
        assert "audit_log" in _ALL_OUT_BACKEND_MANDATES

    def test_backend_mandates_covers_optimistic_locking(self):
        assert "optimistic locking" in _ALL_OUT_BACKEND_MANDATES.lower() or \
               "version" in _ALL_OUT_BACKEND_MANDATES

    def test_backend_mandates_covers_import_export(self):
        assert "export?format=csv" in _ALL_OUT_BACKEND_MANDATES

    def test_backend_mandates_covers_idempotency(self):
        assert "idempotency" in _ALL_OUT_BACKEND_MANDATES.lower()

    def test_backend_mandates_covers_20_test_files(self):
        assert "20 test files" in _ALL_OUT_BACKEND_MANDATES

    def test_frontend_mandates_covers_datatable(self):
        assert "DataTable" in _ALL_OUT_FRONTEND_MANDATES

    def test_frontend_mandates_covers_dashboard(self):
        assert "Dashboard" in _ALL_OUT_FRONTEND_MANDATES

    def test_frontend_mandates_covers_chart_js(self):
        assert "Chart.js" in _ALL_OUT_FRONTEND_MANDATES

    def test_frontend_mandates_covers_breadcrumbs(self):
        assert "Breadcrumb" in _ALL_OUT_FRONTEND_MANDATES

    def test_injected_at_exhaustive_depth(self):
        """Exhaustive depth injects tiered mandates for non-frontend milestones."""
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build accounting system",
            depth="exhaustive",
            config=cfg,
        )
        # v16+ uses tiered mandates instead of flat MANDATORY DELIVERABLES
        assert "IMPLEMENTATION PRIORITY" in prompt or "MANDATORY DELIVERABLES" in prompt
        assert "TIER 2" in prompt or "Bulk operations" in prompt

    def test_injected_at_thorough_depth(self):
        """Thorough depth injects tiered mandates."""
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build accounting system",
            depth="thorough",
            config=cfg,
        )
        # v16+ uses tiered mandates instead of flat MANDATORY DELIVERABLES
        assert "IMPLEMENTATION PRIORITY" in prompt or "MANDATORY DELIVERABLES" in prompt

    def test_not_injected_at_standard_depth(self):
        """Standard depth does NOT inject mandates."""
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build accounting system",
            depth="standard",
            config=cfg,
        )
        assert "MANDATORY DELIVERABLES — Maximum Implementation" not in prompt

    def test_not_injected_at_quick_depth(self):
        """Quick depth does NOT inject mandates."""
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build app",
            depth="quick",
            config=cfg,
        )
        assert "MANDATORY DELIVERABLES — Maximum Implementation" not in prompt

    def test_frontend_mandates_for_frontend_milestone(self):
        """Frontend-titled milestone at exhaustive gets frontend mandates."""
        from agent_team_v15.milestone_manager import MilestoneContext
        cfg = AgentTeamConfig()
        ms_ctx = MilestoneContext(
            milestone_id="milestone-16",
            title="Frontend GL Components",
            requirements_path=".agent-team/milestones/milestone-16/REQUIREMENTS.md",
            predecessor_summaries=[],
        )
        prompt = build_milestone_execution_prompt(
            task="Build accounting system",
            depth="exhaustive",
            config=cfg,
            milestone_context=ms_ctx,
        )
        assert "DataTable" in prompt or "Dashboard" in prompt


# ===================================================================
# V16 Phase 2.3: Domain model injection into decomposition prompt
# ===================================================================

class TestDomainModelInjection:
    """Verify domain_model_text is injected into decomposition prompt."""

    def test_domain_model_injected_when_provided(self):
        cfg = AgentTeamConfig()
        model_text = "### Entities (5 found)\n1. **Invoice**: id(UUID), amount(decimal)"
        prompt = build_decomposition_prompt(
            task="Build accounting system",
            depth="exhaustive",
            config=cfg,
            domain_model_text=model_text,
        )
        assert "PRD ANALYSIS" in prompt
        assert "Invoice" in prompt
        assert "CHECKLIST" in prompt

    def test_domain_model_not_injected_when_empty(self):
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build app",
            depth="standard",
            config=cfg,
            domain_model_text="",
        )
        assert "PRD ANALYSIS" not in prompt

    def test_domain_model_before_instructions(self):
        cfg = AgentTeamConfig()
        model_text = "### Entities (3 found)\n1. **User**: id, name"
        prompt = build_decomposition_prompt(
            task="Build app",
            depth="standard",
            config=cfg,
            prd_path="/fake/prd.md",
            domain_model_text=model_text,
        )
        model_pos = prompt.find("PRD ANALYSIS")
        instructions_pos = prompt.find("[INSTRUCTIONS]")
        assert model_pos < instructions_pos


# ===================================================================
# Scaling: Phase-structured milestone planning
# ===================================================================

class TestPhaseStructuredPlanning:
    """Verify decomposition prompt emits the V18.1 vertical-slice phasing.

    V18.1 Fix 3: the legacy 5-phase (A/B/C/D/E) structure has been retired as
    the planner output. The planner now emits vertical-slice milestones —
    each one a complete feature across all layers. These tests cover the
    equivalent invariants for the current (and only) planner.
    """

    def test_contains_vertical_slice_structure(self):
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build multi-service ERP", depth="exhaustive", config=cfg,
        )
        assert "VERTICAL SLICE MODE" in prompt
        assert "FOUNDATION MILESTONES" in prompt
        assert "FEATURE MILESTONES" in prompt
        assert "POLISH MILESTONES" in prompt

    def test_feature_milestones_include_all_layers(self):
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build ERP", depth="standard", config=cfg,
        )
        # Each vertical slice includes entities, backend, DTOs, and frontend
        assert "Database entities" in prompt
        assert "Backend service" in prompt
        assert "DTOs" in prompt
        assert "Frontend page" in prompt

    def test_milestone_sizing_instruction(self):
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build app", depth="standard", config=cfg,
        )
        # Phase 5.9 §L sizing rule: 3-10 ACs per feature milestone, target
        # 5-10. Maximum lowered from 13 → 10 (the validator gates above
        # this; auto-split runs when the planner emits above-cap milestones).
        assert "MILESTONE SIZING" in prompt
        assert "Target: 5-10 ACs" in prompt
        assert "Minimum: 3 ACs" in prompt
        assert "Maximum: 10 ACs per milestone" in prompt

    def test_milestone_format_required_fields(self):
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build app", depth="standard", config=cfg,
        )
        # V18.1 Fix 2: example block lists every required milestone field.
        for field in (
            "- ID:",
            "- Status:",
            "- Dependencies:",
            "- Template:",
            "- Parallel-Group:",
            "- Features:",
            "- AC-Refs:",
            "- Merge-Surfaces:",
            "- Stack-Target:",
        ):
            assert field in prompt, f"Expected milestone field {field!r} in prompt"

    def test_no_layered_milestones(self):
        """Vertical-slice mode explicitly forbids separate per-layer milestones."""
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build app", depth="standard", config=cfg,
        )
        assert 'DO NOT create separate "Backend"' in prompt


# ===================================================================
# Scaling: Smart context loading in milestone prompts
# ===================================================================

class TestSmartContextLoading:
    """Verify contracts, registry, and targeted files inject into milestone prompts."""

    def test_contracts_md_injected(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build GL", depth="standard", config=cfg,
            contracts_md_text="## GL API\nPOST /journal-entries\n",
        )
        assert "CONTRACTS.md" in prompt
        assert "POST /journal-entries" in prompt

    def test_contracts_md_not_injected_when_empty(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build GL", depth="standard", config=cfg,
            contracts_md_text="",
        )
        assert "CONTRACTS.md — Cross-Module" not in prompt

    def test_interface_registry_injected(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build AR", depth="standard", config=cfg,
            interface_registry_text="[INTERFACE REGISTRY]\n### gl\n  async create_journal(data)\n",
        )
        assert "INTERFACE REGISTRY" in prompt
        assert "create_journal" in prompt

    def test_targeted_files_injected(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Wire AR to GL", depth="standard", config=cfg,
            targeted_files_text="[TARGETED FILE CONTENTS]\n### gl/service.py\nasync def create_journal():\n",
        )
        assert "TARGETED FILE CONTENTS" in prompt
        assert "create_journal" in prompt

    def test_contracts_truncated_if_large(self):
        cfg = AgentTeamConfig()
        large_contracts = "x" * 50000  # 50K chars
        prompt = build_milestone_execution_prompt(
            task="Build", depth="standard", config=cfg,
            contracts_md_text=large_contracts,
        )
        assert "truncated" in prompt.lower()

    def test_all_three_present_together(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build accounting with GL journal entries chart of accounts",
            depth="exhaustive", config=cfg,
            contracts_md_text="## GL API\n",
            interface_registry_text="[INTERFACE REGISTRY]\n### auth\n",
            targeted_files_text="[TARGETED FILES]\n### auth/service.py\n",
            domain_model_text="### Entities (5)\n",
        )
        assert "CONTRACTS.md" in prompt
        assert "INTERFACE REGISTRY" in prompt
        assert "TARGETED FILES" in prompt
        assert "Entities (5)" in prompt

    def test_context_budget_still_passes(self):
        """All injections combined should stay within 25% budget."""
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build accounting with GL journal entries chart of accounts trial balance",
            depth="exhaustive", config=cfg,
            contracts_md_text="## GL API\nPOST /journal-entries\n" * 50,
            interface_registry_text="[INTERFACE REGISTRY]\n" + "  func(a, b) -> dict\n" * 100,
            targeted_files_text="[TARGETED]\n" + "def func(): pass\n" * 100,
            domain_model_text="### Entities\n" + "1. Entity: field1, field2\n" * 50,
        )
        assert check_context_budget(prompt, label="test", threshold=0.25)


# ===================================================================
# V16 Phase 2.4: Domain model injection into milestone prompts
# ===================================================================

class TestMilestoneDomainModelInjection:
    """Verify domain_model_text is injected into milestone execution prompts."""

    def test_domain_model_injected_into_milestone(self):
        cfg = AgentTeamConfig()
        model_text = "### Entities (5 found)\n1. **Invoice**: id(UUID)"
        prompt = build_milestone_execution_prompt(
            task="Build accounting",
            depth="standard",
            config=cfg,
            domain_model_text=model_text,
        )
        assert "PRD DOMAIN MODEL" in prompt
        assert "Invoice" in prompt

    def test_no_injection_when_empty(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build app",
            depth="standard",
            config=cfg,
            domain_model_text="",
        )
        assert "PRD DOMAIN MODEL" not in prompt

    def test_domain_model_before_milestone_workflow(self):
        cfg = AgentTeamConfig()
        model_text = "### Entities\n1. User"
        prompt = build_milestone_execution_prompt(
            task="Build app",
            depth="standard",
            config=cfg,
            domain_model_text=model_text,
        )
        model_pos = prompt.find("PRD DOMAIN MODEL")
        workflow_pos = prompt.find("MILESTONE WORKFLOW")
        assert model_pos < workflow_pos


# ===================================================================
# V16 Phase 2.5: Stack-specific framework instructions
# ===================================================================

class TestStackDetection:
    def test_detects_python_fastapi(self):
        stacks = detect_stack_from_text("Build with Python FastAPI and PostgreSQL")
        assert "python" in stacks

    def test_detects_nestjs(self):
        stacks = detect_stack_from_text("Backend using NestJS with TypeORM")
        assert "typescript" in stacks

    def test_detects_angular(self):
        stacks = detect_stack_from_text("Frontend in Angular 18 with PrimeNG")
        assert "angular" in stacks

    def test_detects_react(self):
        stacks = detect_stack_from_text("React frontend with Next.js")
        assert "react" in stacks

    def test_multiple_stacks(self):
        stacks = detect_stack_from_text("FastAPI backend API + Angular frontend")
        assert "python" in stacks
        assert "angular" in stacks

    def test_no_stacks(self):
        stacks = detect_stack_from_text("Build a simple calculator")
        assert stacks == []


class TestGetStackInstructions:
    def test_python_instructions(self):
        result = get_stack_instructions("Build API with FastAPI")
        assert "fastapi" in result.lower()
        assert "alembic" in result.lower()

    def test_python_instructions_do_not_invent_8080_default(self):
        result = get_stack_instructions("Build API with FastAPI")
        assert "listen on 8080" not in result.lower()
        assert "do not invent 8080" in result.lower()

    def test_typescript_instructions(self):
        result = get_stack_instructions("Backend with NestJS framework")
        assert "nestjs" in result.lower() or "typeorm" in result.lower()

    def test_typescript_instructions_do_not_invent_8080_default(self):
        result = get_stack_instructions("Backend with NestJS framework")
        assert "default 8080" not in result.lower()
        assert "do not invent 8080" in result.lower()

    def test_typescript_instructions_follow_prisma_research(self):
        result = get_stack_instructions(
            "Backend with NestJS framework",
            tech_research_content="Database stack: Prisma ORM with PostgreSQL.",
        )
        assert "database (prisma)" in result.lower()
        assert "database (typeorm)" not in result.lower()

    def test_prisma_instructions_require_config_file_not_package_json_prisma(self):
        result = get_stack_instructions(
            "Backend with NestJS framework",
            tech_research_content="Database stack: Prisma ORM with PostgreSQL.",
        )
        lowered = result.lower()

        assert "prisma.config.ts" in lowered
        assert "package.json#prisma" not in lowered

    def test_prisma_instructions_require_cli_as_dev_dependency(self):
        result = get_stack_instructions(
            "Backend with NestJS framework",
            tech_research_content="Database stack: Prisma ORM with PostgreSQL.",
        )
        lowered = result.lower()

        assert "`prisma` devdependency" in lowered or "prisma as a devdependency" in lowered
        assert "@prisma/client" in lowered

    def test_typescript_instructions_detect_monorepo_layout_from_research(self):
        result = get_stack_instructions(
            "Backend with NestJS framework",
            tech_research_content="Monorepo layout uses apps/api and apps/web workspaces.",
        )
        assert "monorepo layout" in result.lower()
        assert "apps/api/src/main.ts" in result

    def test_empty_for_no_stack(self):
        result = get_stack_instructions("do something generic")
        assert result == ""


class TestStackInstructionsInPrompt:
    def test_injected_into_milestone_prompt(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build accounting system with FastAPI backend",
            depth="standard",
            config=cfg,
        )
        assert "FRAMEWORK INSTRUCTIONS" in prompt
        assert "fastapi" in prompt.lower()

    def test_not_injected_for_generic_task(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Fix the bug in the login page",
            depth="standard",
            config=cfg,
        )
        assert "FRAMEWORK INSTRUCTIONS" not in prompt

    def test_prisma_research_removes_default_typeorm_guidance(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build NestJS backend",
            depth="standard",
            config=cfg,
            tech_research_content="Use Prisma ORM with PostgreSQL for persistence.",
        )
        assert "database (prisma)" in prompt.lower()
        assert "database (typeorm)" not in prompt.lower()


class TestDecompositionOutputLocation:
    def test_outputs_are_rooted_at_cwd_not_prd_directory(self, tmp_path: Path):
        cfg = AgentTeamConfig()
        cwd = tmp_path / "build-root"
        prd_dir = tmp_path / "input-docs"
        prompt = build_decomposition_prompt(
            task="Build a NestJS and Next.js app",
            depth="standard",
            config=cfg,
            prd_path=str(prd_dir / "product.md"),
            cwd=str(cwd),
        )

        expected_root = (cwd.resolve() / cfg.convergence.requirements_dir).as_posix()
        assert "[OUTPUT LOCATION - MANDATORY]" in prompt
        assert expected_root in prompt
        assert f"{expected_root}/MASTER_PLAN.md" in prompt
        assert f"The PRD directory ({prd_dir.resolve().as_posix()}) is INPUT ONLY." in prompt


# ===================================================================
# V16 Phase 3.5: Domain-specific integration mandates (accounting)
# ===================================================================

class TestAccountingDetection:
    def test_detects_accounting_prd(self):
        assert _is_accounting_prd("Build a general ledger with journal entries and chart of accounts") is True

    def test_detects_erp(self):
        assert _is_accounting_prd("ERP with AR, AP, GL, trial balance, and fiscal period management") is True

    def test_rejects_non_accounting(self):
        assert _is_accounting_prd("Build a task management app with kanban boards") is False

    def test_threshold_requires_3_keywords(self):
        # Only 2 keywords — not enough
        assert _is_accounting_prd("The system has a GL module") is False
        # 3 keywords — enough
        assert _is_accounting_prd("The GL has journal entries and a chart of accounts") is True


class TestAccountingMandateInjection:
    def test_injected_into_decomposition_for_accounting(self):
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build accounting system with GL, AR, AP, journal entries, chart of accounts",
            depth="exhaustive",
            config=cfg,
        )
        assert "ACCOUNTING SYSTEM INTEGRATION MANDATE" in prompt
        assert "Debit: Accounts Receivable" in prompt

    def test_not_injected_for_non_accounting(self):
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build a social media platform",
            depth="exhaustive",
            config=cfg,
        )
        assert "ACCOUNTING SYSTEM INTEGRATION MANDATE" not in prompt

    def test_injected_into_milestone_for_accounting(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build accounting with GL, journal entries, chart of accounts, trial balance",
            depth="standard",
            config=cfg,
        )
        assert "ACCOUNTING SYSTEM INTEGRATION MANDATE" in prompt

    def test_not_injected_into_milestone_for_non_accounting(self):
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build a blog platform",
            depth="standard",
            config=cfg,
        )
        assert "ACCOUNTING SYSTEM INTEGRATION MANDATE" not in prompt


# ===================================================================
# V16 Phase 3.7: Context window budget monitoring
# ===================================================================

class TestContextBudget:
    def test_small_prompt_within_budget(self):
        assert check_context_budget("Hello world", label="test") is True

    def test_large_prompt_over_budget(self):
        large = "x" * 300_000
        assert check_context_budget(large, label="test", threshold=0.25) is False

    def test_custom_threshold(self):
        medium = "x" * 10_000
        assert check_context_budget(medium, threshold=0.01) is False
        assert check_context_budget(medium, threshold=0.05) is True

    def test_decomposition_prompt_within_budget(self):
        """Real decomposition prompt should be well within 25% budget."""
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt(
            task="Build a large accounting system",
            depth="exhaustive",
            config=cfg,
        )
        assert check_context_budget(prompt, label="test") is True

    def test_milestone_prompt_within_budget(self):
        """Real milestone prompt should be well within 25% budget."""
        cfg = AgentTeamConfig()
        prompt = build_milestone_execution_prompt(
            task="Build GL service with journal entries, chart of accounts, trial balance",
            depth="exhaustive",
            config=cfg,
        )
        assert check_context_budget(prompt, label="test") is True


# ===================================================================
# Section 15: Team-Based Execution
# ===================================================================

class TestSection15TeamBasedExecution:
    """Tests for SECTION 15: TEAM-BASED EXECUTION in orchestrator prompt."""

    def test_section_15_exists(self):
        assert "SECTION 15:" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_team_create_mandatory(self):
        assert "TeamCreate" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_send_message_mandatory(self):
        assert "SendMessage" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_task_tracking(self):
        assert "TaskCreate" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "TaskUpdate" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_phase_leads(self):
        assert "wave-a-lead" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "wave-d5-lead" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "wave-t-lead" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "wave-e-lead" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_non_negotiable(self):
        assert "NON-NEGOTIABLE" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_team_workflow(self):
        assert "Team-Based Workflow" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_handoff_protocol(self):
        assert "Phase Handoff Protocol" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_structured_message_types(self):
        for msg_type in [
            "REQUIREMENTS_READY", "ARCHITECTURE_READY", "WAVE_COMPLETE",
            "REVIEW_RESULTS", "DEBUG_FIX_COMPLETE", "WIRING_ESCALATION",
            "CONVERGENCE_COMPLETE", "TESTING_COMPLETE", "ESCALATION_REQUEST",
            "AUDIT_COMPLETE", "FIX_REQUEST", "REGRESSION_ALERT", "PLATEAU", "CONVERGED",
        ]:
            assert msg_type in ORCHESTRATOR_SYSTEM_PROMPT, f"Missing message type: {msg_type}"

    def test_section_15_escalation_chains(self):
        assert "Escalation Chains" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_shared_task_tracking(self):
        assert "Shared Task Tracking" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_6_team_deployment_mode(self):
        assert "Team Deployment Mode" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_7_team_workflow(self):
        assert "Team-Based Workflow" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "Fleet-Based Workflow" in ORCHESTRATOR_SYSTEM_PROMPT


# ===================================================================
# Phase lead prompt templates
# ===================================================================

class TestPhaseLeadPrompts:
    """Tests for phase lead prompt templates."""

    def test_planning_lead_prompt_non_empty(self):
        assert len(PLANNING_LEAD_PROMPT) > 100

    def test_architecture_lead_prompt_non_empty(self):
        assert len(ARCHITECTURE_LEAD_PROMPT) > 100

    def test_coding_lead_prompt_non_empty(self):
        assert len(CODING_LEAD_PROMPT) > 100

    def test_review_lead_prompt_non_empty(self):
        assert len(REVIEW_LEAD_PROMPT) > 100

    def test_testing_lead_prompt_non_empty(self):
        assert len(TESTING_LEAD_PROMPT) > 100

    def test_planning_lead_has_send_message_targets(self):
        assert "REQUIREMENTS.md" in PLANNING_LEAD_PROMPT

    def test_architecture_lead_has_send_message_targets(self):
        assert "CONTRACTS.json" in ARCHITECTURE_LEAD_PROMPT

    def test_coding_lead_has_send_message_targets(self):
        assert "wave-e-lead" in CODING_LEAD_PROMPT

    def test_review_lead_has_send_message_targets(self):
        assert "wave-a-lead" in REVIEW_LEAD_PROMPT

    def test_testing_lead_has_send_message_targets(self):
        assert "orchestrator" in TESTING_LEAD_PROMPT

    def test_coding_lead_references_tasks_md(self):
        assert "TASKS.md" in CODING_LEAD_PROMPT

    def test_review_lead_is_adversarial(self):
        assert "adversarial" in REVIEW_LEAD_PROMPT.lower()

    def test_team_communication_protocol_exists(self):
        assert len(_TEAM_COMMUNICATION_PROTOCOL) > 100

    def test_team_protocol_has_sdk_subagent_header(self):
        assert "SDK Subagent Protocol" in _TEAM_COMMUNICATION_PROTOCOL

    def test_team_protocol_has_communication_rules(self):
        assert "Communication Rules" in _TEAM_COMMUNICATION_PROTOCOL

    def test_team_protocol_no_send_message(self):
        assert "do NOT use SendMessage" in _TEAM_COMMUNICATION_PROTOCOL or \
               "You do NOT use SendMessage" in _TEAM_COMMUNICATION_PROTOCOL

    def test_team_protocol_no_team_create(self):
        assert "TeamCreate" in _TEAM_COMMUNICATION_PROTOCOL  # mentioned as disallowed

    def test_team_protocol_has_return_format(self):
        assert "Return Format" in _TEAM_COMMUNICATION_PROTOCOL
        assert "Phase Result" in _TEAM_COMMUNICATION_PROTOCOL

    def test_team_protocol_has_shared_artifacts(self):
        assert "Shared Artifacts" in _TEAM_COMMUNICATION_PROTOCOL
        assert ".agent-team/" in _TEAM_COMMUNICATION_PROTOCOL

    def test_team_protocol_has_blocked_status(self):
        assert "BLOCKED" in _TEAM_COMMUNICATION_PROTOCOL

    def test_planning_lead_has_requirements_ready_format(self):
        assert "REQUIREMENTS.md" in PLANNING_LEAD_PROMPT

    def test_planning_lead_has_artifact_ownership(self):
        assert "Artifact Ownership" in PLANNING_LEAD_PROMPT

    def test_planning_lead_has_persistent_context(self):
        assert "Persistent Context" in PLANNING_LEAD_PROMPT

    def test_planning_lead_handles_escalation(self):
        assert "ESCALATION_REQUEST" in PLANNING_LEAD_PROMPT

    def test_architecture_lead_has_architecture_ready_format(self):
        assert "CONTRACTS.json" in ARCHITECTURE_LEAD_PROMPT

    def test_architecture_lead_has_artifact_ownership(self):
        assert "Artifact Ownership" in ARCHITECTURE_LEAD_PROMPT
        assert "CONTRACTS.json" in ARCHITECTURE_LEAD_PROMPT

    def test_architecture_lead_has_persistent_context(self):
        assert "Persistent Context" in ARCHITECTURE_LEAD_PROMPT

    def test_architecture_lead_handles_wiring_escalation(self):
        assert "wiring" in ARCHITECTURE_LEAD_PROMPT.lower()

    def test_coding_lead_has_wave_complete_format(self):
        assert "wave" in CODING_LEAD_PROMPT.lower()

    def test_coding_lead_has_debug_fix_complete_format(self):
        assert "debug" in CODING_LEAD_PROMPT.lower()

    def test_coding_lead_has_artifact_ownership(self):
        assert "Artifact Ownership" in CODING_LEAD_PROMPT

    def test_coding_lead_has_persistent_context(self):
        assert "Persistent Context" in CODING_LEAD_PROMPT

    def test_coding_lead_has_mock_data_gate(self):
        assert "MOCK DATA GATE" in CODING_LEAD_PROMPT

    def test_review_lead_has_review_results_format(self):
        assert "convergence" in REVIEW_LEAD_PROMPT.lower()

    def test_review_lead_has_wiring_escalation_format(self):
        assert "wiring escalation" in REVIEW_LEAD_PROMPT.lower()

    def test_review_lead_has_convergence_complete_format(self):
        assert "convergence ratio" in REVIEW_LEAD_PROMPT.lower()

    def test_review_lead_has_artifact_ownership(self):
        assert "Artifact Ownership" in REVIEW_LEAD_PROMPT

    def test_review_lead_has_persistent_context(self):
        assert "Persistent Context" in REVIEW_LEAD_PROMPT

    def test_review_lead_tracks_review_cycles(self):
        assert "review_cycles" in REVIEW_LEAD_PROMPT

    def test_review_lead_escalation_threshold(self):
        assert "3+" in REVIEW_LEAD_PROMPT or "3 cycles" in REVIEW_LEAD_PROMPT

    def test_testing_lead_has_testing_complete_format(self):
        assert "test" in TESTING_LEAD_PROMPT.lower() and "COMPLETE" in TESTING_LEAD_PROMPT

    def test_testing_lead_has_artifact_ownership(self):
        assert "Artifact Ownership" in TESTING_LEAD_PROMPT
        assert "VERIFICATION.md" in TESTING_LEAD_PROMPT

    def test_testing_lead_has_persistent_context(self):
        assert "Persistent Context" in TESTING_LEAD_PROMPT

    def test_testing_lead_has_security_auditor(self):
        assert "security-auditor" in TESTING_LEAD_PROMPT

    def test_planning_lead_has_spec_fidelity_validation(self):
        assert "Spec Fidelity Validation" in PLANNING_LEAD_PROMPT

    def test_planning_lead_spec_fidelity_is_mandatory(self):
        assert "MANDATORY before completing planning" in PLANNING_LEAD_PROMPT

    def test_planning_lead_spec_fidelity_has_prd_mapping(self):
        assert "PRD Feature X" in PLANNING_LEAD_PROMPT

    def test_testing_lead_has_runtime_fix_protocol(self):
        assert "Runtime Fix Protocol" in TESTING_LEAD_PROMPT

    def test_testing_lead_has_fix_request_message(self):
        assert "FIX_REQUEST" in TESTING_LEAD_PROMPT

    def test_testing_lead_runtime_fix_no_isolated_sessions(self):
        assert "Do NOT spawn isolated Claude sessions" in TESTING_LEAD_PROMPT

    def test_orchestrator_has_audit_lead(self):
        assert "wave-e-lead" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_orchestrator_has_audit_message_types(self):
        for msg_type in ["AUDIT_COMPLETE", "FIX_REQUEST", "REGRESSION_ALERT", "PLATEAU", "CONVERGED"]:
            assert msg_type in ORCHESTRATOR_SYSTEM_PROMPT, f"Missing audit message type: {msg_type}"

    def test_team_orchestrator_has_audit_lead(self):
        assert "wave-e-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_orchestrator_has_audit_workflow(self):
        # SDK subagent model uses Task tool delegation, not SendMessage types
        assert "wave-e-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "audit findings" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "AUDIT FIX CYCLE" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_orchestrator_audit_lead_in_delegation_workflow(self):
        assert "Task -> wave-e-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


# ===================================================================
# Phase lead agent definitions (agent_teams enabled)
# ===================================================================

class TestPhaseLeadAgentDefinitions:
    """Tests for phase lead agents when agent_teams is enabled."""

    def test_phase_leads_present_when_enabled(self, config_with_agent_teams):
        agents = build_agent_definitions(config_with_agent_teams, {})
        for name in ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]:
            assert name in agents, f"{name} missing from agent definitions"

    def test_phase_leads_absent_when_disabled(self, default_config):
        agents = build_agent_definitions(default_config, {})
        for name in ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]:
            assert name not in agents, f"{name} should not be in agents when teams disabled"

    def test_phase_leads_have_customized_tools(self, config_with_agent_teams):
        agents = build_agent_definitions(config_with_agent_teams, {})
        # Each lead gets its own tool set from PhaseLeadsConfig
        core_tools = {"Read", "Glob", "Grep"}
        for name in ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]:
            tools = set(agents[name]["tools"])
            assert core_tools.issubset(tools), f"{name} missing core tools: {core_tools - tools}"
        assert "Write" in agents["wave-a-lead"]["tools"]
        assert "Edit" in agents["wave-a-lead"]["tools"]
        assert "Bash" in agents["wave-t-lead"]["tools"]

    def test_phase_leads_have_descriptions(self, config_with_agent_teams):
        agents = build_agent_definitions(config_with_agent_teams, {})
        for name in ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]:
            assert len(agents[name]["description"]) > 0, f"{name} missing description"

    def test_phase_leads_have_prompts(self, config_with_agent_teams):
        agents = build_agent_definitions(config_with_agent_teams, {})
        for name in ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]:
            assert len(agents[name]["prompt"]) > 100, f"{name} prompt too short"

    def test_phase_leads_have_communication_protocol(self, config_with_agent_teams):
        agents = build_agent_definitions(config_with_agent_teams, {})
        for name in ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]:
            assert "SDK Subagent Protocol" in agents[name]["prompt"], \
                f"{name} missing SDK subagent protocol"

    def test_agent_count_with_teams_enabled(self, config_with_agent_teams):
        """Teams enabled adds 4 phase leads to the default 17 agents = 21."""
        agents = build_agent_definitions(config_with_agent_teams, {})
        phase_leads = {n for n in agents if n.endswith("-lead")}
        assert len(phase_leads) == 4
        assert len(agents) == 21

    def test_constraints_injected_into_phase_leads(self, config_with_agent_teams):
        constraints = [ConstraintEntry("no mock data", "prohibition", "task", 2)]
        agents = build_agent_definitions(config_with_agent_teams, {}, constraints=constraints)
        for name in ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]:
            assert "no mock data" in agents[name]["prompt"], f"{name} missing constraint"


# ===================================================================
# Slim team orchestrator prompt (TEAM_ORCHESTRATOR_SYSTEM_PROMPT)
# ===================================================================

class TestTeamOrchestratorSystemPrompt:
    """Tests for the slim team-mode orchestrator prompt."""

    def test_team_orchestrator_prompt_non_empty(self):
        assert len(TEAM_ORCHESTRATOR_SYSTEM_PROMPT) > 200

    def test_team_orchestrator_is_distinct_from_monolithic(self):
        assert TEAM_ORCHESTRATOR_SYSTEM_PROMPT != ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_orchestrator_is_significantly_shorter(self):
        assert len(TEAM_ORCHESTRATOR_SYSTEM_PROMPT) < len(ORCHESTRATOR_SYSTEM_PROMPT) / 2

    # Phase G Slice 4f: orchestrator prompt restructured into XML sections
    # (<role>, <wave_sequence>, <delegation_workflow>, <gates>, <escalation>,
    # <completion>, <enterprise_mode>, <conflicts>). Tests that assert the
    # old ALL-CAPS section headers ("CODEBASE MAP", "DEPTH DETECTION",
    # "PHASE LEAD COORDINATION", "Sequential Delegation Workflow",
    # "Completion Criteria", "Escalation Chains", "PRD MODE",
    # "SHARED ARTIFACTS", "CONVERGENCE GATES") were deleted because the
    # new contract is tested in tests/test_orchestrator_prompt.py.

    def test_team_orchestrator_has_all_wave_leads(self):
        for lead in ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]:
            assert lead in TEAM_ORCHESTRATOR_SYSTEM_PROMPT, f"Missing {lead}"

    def test_team_orchestrator_no_teamcreate(self):
        assert "TeamCreate" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_orchestrator_no_sendmessage(self):
        assert "SendMessage" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_orchestrator_does_not_have_fleet_sections(self):
        """Slim prompt should not contain fleet-mode sections."""
        assert "SECTION 1:" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "SECTION 3:" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "SECTION 5:" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "SECTION 6:" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "SECTION 7:" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_orchestrator_is_coordinator_not_implementer(self):
        assert "COORDINATOR" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
        assert "NOT write code" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


class TestGetOrchestratorSystemPrompt:
    """Tests for the prompt selector function."""

    def test_returns_monolithic_when_phase_leads_disabled(self):
        config = AgentTeamConfig()
        result = get_orchestrator_system_prompt(config)
        assert result == ORCHESTRATOR_SYSTEM_PROMPT

    def test_returns_slim_when_phase_leads_enabled(self):
        config = AgentTeamConfig(
            phase_leads=PhaseLeadsConfig(enabled=True),
        )
        result = get_orchestrator_system_prompt(config)
        assert result == TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_returns_monolithic_by_default(self):
        config = AgentTeamConfig()
        assert not config.phase_leads.enabled
        result = get_orchestrator_system_prompt(config)
        assert "SECTION 1:" in result  # monolithic has numbered sections
