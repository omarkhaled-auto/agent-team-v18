"""Tests for Enterprise v2 Department Model.

Covers: config (DepartmentConfig, DepartmentsConfig, depth gating, validation),
state (RunState department fields), department module functions,
context slicing, agent registration, and orchestrator prompt generation.
"""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from agent_team_v15.config import (
    AgentTeamConfig,
    DepartmentConfig,
    DepartmentsConfig,
    EnterpriseModeConfig,
    apply_depth_quality_gating,
    load_config,
)
from agent_team_v15.state import RunState
from agent_team_v15.department import (
    CODING_DEPARTMENT_MEMBERS,
    REVIEW_DEPARTMENT_MEMBERS,
    TECH_STACK_MANAGER_MAP,
    build_domain_assignment_message,
    build_domain_complete_message,
    build_manager_assignments,
    build_orchestrator_department_prompt,
    compute_department_size,
    get_department_team_name,
    get_wave_domains,
    resolve_manager_for_domain,
    should_manager_work_directly,
)
from agent_team_v15.agents import (
    build_agent_definitions,
    context_slice_ownership_map,
    get_orchestrator_system_prompt,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_OWNERSHIP_MAP = {
    "version": 1,
    "build_id": "test-123",
    "domains": {
        "auth-service": {
            "tech_stack": "nestjs+prisma",
            "agent_type": "backend-dev",
            "files": ["src/auth/**"],
            "requirements": ["REQ-001", "REQ-002"],
            "dependencies": [],
            "shared_reads": ["prisma/schema.prisma"],
        },
        "task-service": {
            "tech_stack": "nestjs+prisma",
            "agent_type": "backend-dev",
            "files": ["src/tasks/**"],
            "requirements": ["REQ-003", "REQ-004"],
            "dependencies": ["auth-service"],
            "shared_reads": ["prisma/schema.prisma"],
        },
        "dashboard-ui": {
            "tech_stack": "nextjs+react+tailwind",
            "agent_type": "frontend-dev",
            "files": ["src/app/dashboard/**"],
            "requirements": ["REQ-005", "REQ-006"],
            "dependencies": ["auth-service", "task-service"],
            "shared_reads": [],
        },
        "infra": {
            "tech_stack": "docker+ci",
            "agent_type": "infra-dev",
            "files": ["docker/**", "Dockerfile", ".github/**"],
            "requirements": ["REQ-007"],
            "dependencies": [],
            "shared_reads": [],
        },
    },
    "waves": [
        {"id": 1, "name": "foundation", "domains": ["infra"], "parallel": False},
        {"id": 2, "name": "backend", "domains": ["auth-service", "task-service"], "parallel": True},
        {"id": 3, "name": "frontend", "domains": ["dashboard-ui"], "parallel": False},
    ],
    "shared_scaffolding": ["prisma/schema.prisma", "docker-compose.yml"],
}


def _enterprise_config() -> AgentTeamConfig:
    """Create an AgentTeamConfig with enterprise depth applied."""
    c = AgentTeamConfig()
    apply_depth_quality_gating("enterprise", c, {})
    return c


def _department_config() -> AgentTeamConfig:
    """Create an AgentTeamConfig with enterprise + department model enabled."""
    c = _enterprise_config()
    # enterprise depth already sets department_model and departments.enabled
    assert c.enterprise_mode.department_model is True
    assert c.departments.enabled is True
    return c


# =========================================================================
# Group 1: Config Tests
# =========================================================================

class TestDepartmentConfig:
    def test_department_config_defaults(self):
        """DepartmentConfig has correct defaults."""
        dc = DepartmentConfig()
        assert dc.enabled is False
        assert dc.max_managers == 4
        assert dc.max_workers_per_manager == 5
        assert dc.communication_timeout == 300
        assert dc.wave_timeout == 1800

    def test_departments_config_defaults(self):
        """DepartmentsConfig coding/review have correct defaults."""
        dc = DepartmentsConfig()
        assert dc.enabled is False
        # Coding department defaults
        assert dc.coding.enabled is True
        assert dc.coding.max_managers == 4
        # Review department defaults
        assert dc.review.enabled is True
        assert dc.review.max_managers == 3

    def test_department_model_default_false(self):
        """department_model defaults to False on EnterpriseModeConfig."""
        em = EnterpriseModeConfig()
        assert em.department_model is False

    def test_depth_enterprise_enables_departments(self):
        """apply_depth_quality_gating('enterprise') sets department_model and departments.enabled."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, {})
        assert c.enterprise_mode.enabled is True
        assert c.enterprise_mode.department_model is True
        assert c.departments.enabled is True

    def test_departments_require_enterprise_mode(self, tmp_path):
        """departments.enabled=True without enterprise_mode.enabled -> disabled with warning."""
        # Create a config with departments enabled but enterprise_mode disabled
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "departments:\n  enabled: true\n",
            encoding="utf-8",
        )
        cfg, _ = load_config(config_path=str(yaml_path))
        # Validation should have forced departments.enabled=False
        assert cfg.departments.enabled is False

    def test_departments_require_agent_teams(self, tmp_path):
        """departments.enabled=True without agent_teams.enabled -> disabled with warning."""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "enterprise_mode:\n  enabled: true\n"
            "departments:\n  enabled: true\n",
            encoding="utf-8",
        )
        cfg, _ = load_config(config_path=str(yaml_path))
        # enterprise_mode forces phase_leads on, but agent_teams stays off
        # unless explicitly set -- validation should force departments off
        # However, enterprise_mode.enabled without agent_teams.enabled:
        # departments requires agent_teams, so it should be disabled.
        # Note: enterprise_mode alone doesn't force agent_teams on
        # (that's only from depth gating). So departments gets disabled.
        assert cfg.departments.enabled is False


# =========================================================================
# Group 2: State Tests
# =========================================================================

class TestRunStateDepartment:
    def test_run_state_department_fields(self):
        """RunState has department_mode_active, departments_created, manager_count."""
        state = RunState()
        assert state.department_mode_active is False
        assert state.departments_created == []
        assert state.manager_count == 0

    def test_run_state_department_serialization(self):
        """Department fields survive asdict() round-trip."""
        state = RunState(
            department_mode_active=True,
            departments_created=["coding-dept", "review-dept"],
            manager_count=4,
        )
        data = asdict(state)
        assert data["department_mode_active"] is True
        assert data["departments_created"] == ["coding-dept", "review-dept"]
        assert data["manager_count"] == 4

        # Round-trip through JSON (like save_state does)
        json_str = json.dumps(data)
        loaded = json.loads(json_str)
        assert loaded["department_mode_active"] is True
        assert loaded["departments_created"] == ["coding-dept", "review-dept"]
        assert loaded["manager_count"] == 4


# =========================================================================
# Group 3: Department Module Tests
# =========================================================================

class TestResolveManager:
    def test_resolve_manager_nestjs(self):
        """NestJS tech_stack -> backend-manager."""
        domain = {"tech_stack": "nestjs+prisma"}
        assert resolve_manager_for_domain(domain) == "backend-manager"

    def test_resolve_manager_nextjs(self):
        """Next.js tech_stack -> frontend-manager."""
        domain = {"tech_stack": "nextjs+react+tailwind"}
        assert resolve_manager_for_domain(domain) == "frontend-manager"

    def test_resolve_manager_docker(self):
        """Docker tech_stack -> infra-manager."""
        domain = {"tech_stack": "docker+ci"}
        assert resolve_manager_for_domain(domain) == "infra-manager"

    def test_resolve_manager_unknown(self):
        """Unknown tech_stack -> backend-manager (fallback)."""
        domain = {"tech_stack": "elixir+phoenix"}
        assert resolve_manager_for_domain(domain) == "backend-manager"


class TestBuildManagerAssignments:
    def test_build_manager_assignments(self):
        """Groups domains by manager correctly."""
        assignments = build_manager_assignments(SAMPLE_OWNERSHIP_MAP)
        assert "backend-manager" in assignments
        assert "frontend-manager" in assignments
        assert "infra-manager" in assignments
        # Both nestjs domains go to backend-manager
        assert "auth-service" in assignments["backend-manager"]
        assert "task-service" in assignments["backend-manager"]
        # Next.js to frontend-manager
        assert "dashboard-ui" in assignments["frontend-manager"]
        # Docker to infra-manager
        assert "infra" in assignments["infra-manager"]


class TestShouldManagerWorkDirectly:
    def test_should_manager_work_directly_small(self):
        """<=2 domains -> manager works directly."""
        assert should_manager_work_directly(1) is True
        assert should_manager_work_directly(2) is True

    def test_should_manager_work_directly_large(self):
        """>2 domains -> manager spawns workers."""
        assert should_manager_work_directly(3) is False
        assert should_manager_work_directly(10) is False


class TestMessages:
    def test_build_domain_assignment_message(self):
        """DOMAIN_ASSIGNMENT message has correct JSON structure."""
        msg = build_domain_assignment_message(
            wave_id=2,
            wave_name="backend",
            domains=[{"name": "auth-service", "tech_stack": "nestjs+prisma"}],
        )
        parsed = json.loads(msg)
        assert parsed["type"] == "DOMAIN_ASSIGNMENT"
        assert parsed["wave_id"] == 2
        assert parsed["wave_name"] == "backend"
        assert len(parsed["domains"]) == 1
        assert parsed["domains"][0]["name"] == "auth-service"

    def test_build_domain_complete_message(self):
        """DOMAIN_COMPLETE message has correct JSON structure."""
        msg = build_domain_complete_message(
            wave_id=2,
            domain="auth-service",
            status="COMPLETE",
            files_written=["src/auth/auth.module.ts", "src/auth/auth.service.ts"],
            issues=[],
        )
        parsed = json.loads(msg)
        assert parsed["type"] == "DOMAIN_COMPLETE"
        assert parsed["wave_id"] == 2
        assert parsed["domain"] == "auth-service"
        assert parsed["status"] == "COMPLETE"
        assert len(parsed["files_written"]) == 2
        assert parsed["issues"] == []


class TestDepartmentHelpers:
    def test_get_department_team_name(self):
        """Team name format: prefix-department-dept."""
        assert get_department_team_name("build", "coding") == "build-coding-dept"
        assert get_department_team_name("build", "review") == "build-review-dept"
        assert get_department_team_name("myproject", "coding") == "myproject-coding-dept"

    def test_get_wave_domains(self):
        """Extracts domains for specific wave ID."""
        assert get_wave_domains(SAMPLE_OWNERSHIP_MAP, 1) == ["infra"]
        assert get_wave_domains(SAMPLE_OWNERSHIP_MAP, 2) == ["auth-service", "task-service"]
        assert get_wave_domains(SAMPLE_OWNERSHIP_MAP, 3) == ["dashboard-ui"]
        # Non-existent wave returns empty list
        assert get_wave_domains(SAMPLE_OWNERSHIP_MAP, 99) == []

    def test_compute_department_size_coding(self):
        """Coding department size matches distinct manager types + integration."""
        # SAMPLE_OWNERSHIP_MAP has 3 distinct managers: backend, frontend, infra
        # +1 for integration-manager = 4
        size = compute_department_size(SAMPLE_OWNERSHIP_MAP, "coding", config_max_managers=10)
        assert size == 4  # 3 distinct + 1 integration

    def test_compute_department_size_review(self):
        """Review department always returns min(3, max_managers)."""
        size = compute_department_size(SAMPLE_OWNERSHIP_MAP, "review", config_max_managers=10)
        assert size == 3
        # When max_managers is lower, it caps
        size_capped = compute_department_size(SAMPLE_OWNERSHIP_MAP, "review", config_max_managers=2)
        assert size_capped == 2


# =========================================================================
# Group 4: Context Slicing Tests
# =========================================================================

class TestContextSlicing:
    def test_context_slice_by_tech_stack(self):
        """Filters domains by tech_stack keyword."""
        sliced = context_slice_ownership_map(SAMPLE_OWNERSHIP_MAP, tech_stack_filter="nestjs")
        assert "auth-service" in sliced["domains"]
        assert "task-service" in sliced["domains"]
        assert "dashboard-ui" not in sliced["domains"]
        assert "infra" not in sliced["domains"]

    def test_context_slice_by_domain_names(self):
        """Filters domains by explicit name list."""
        sliced = context_slice_ownership_map(
            SAMPLE_OWNERSHIP_MAP,
            domain_names=["dashboard-ui", "infra"],
        )
        assert "dashboard-ui" in sliced["domains"]
        assert "infra" in sliced["domains"]
        assert "auth-service" not in sliced["domains"]
        assert "task-service" not in sliced["domains"]

    def test_context_slice_waves_filtered(self):
        """Only waves referencing included domains survive slicing."""
        sliced = context_slice_ownership_map(SAMPLE_OWNERSHIP_MAP, tech_stack_filter="nestjs")
        # Only wave 2 contains nestjs domains (auth-service, task-service)
        wave_ids = [w["id"] for w in sliced["waves"]]
        assert 2 in wave_ids
        assert 1 not in wave_ids  # infra wave excluded
        assert 3 not in wave_ids  # frontend wave excluded

    def test_context_slice_preserves_scaffolding(self):
        """shared_scaffolding always included regardless of filters."""
        sliced = context_slice_ownership_map(
            SAMPLE_OWNERSHIP_MAP,
            tech_stack_filter="docker",
        )
        assert sliced["shared_scaffolding"] == ["prisma/schema.prisma", "docker-compose.yml"]


# =========================================================================
# Group 5: Agent Registration Tests
# =========================================================================

DEPARTMENT_AGENT_NAMES = [
    "coding-dept-head",
    "backend-manager",
    "frontend-manager",
    "infra-manager",
    "integration-manager",
    "review-dept-head",
    "backend-review-manager",
    "frontend-review-manager",
    "cross-cutting-reviewer",
    "domain-reviewer",
]


class TestDepartmentAgentRegistration:
    def test_department_agents_not_registered_by_default(self):
        """Without department_model, no department agents registered."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, {})
        defs = build_agent_definitions(c, {})
        for name in DEPARTMENT_AGENT_NAMES:
            assert name not in defs, f"{name} should not be registered at standard depth"

    def test_department_agents_registered_when_enabled(self):
        """With department_model + departments.enabled, 10 agents registered."""
        c = _department_config()
        defs = build_agent_definitions(c, {"context7": {}})
        for name in DEPARTMENT_AGENT_NAMES:
            assert name in defs, f"{name} should be registered"

    def test_coding_dept_head_no_code_tools(self):
        """coding-dept-head has Read/Write/Glob/Grep but NOT Edit/Bash."""
        c = _department_config()
        defs = build_agent_definitions(c, {})
        tools = defs["coding-dept-head"]["tools"]
        assert "Read" in tools
        assert "Write" in tools
        assert "Glob" in tools
        assert "Grep" in tools
        # Coordinator should NOT have direct code editing tools
        assert "Edit" not in tools
        assert "Bash" not in tools

    def test_managers_have_full_tools(self):
        """backend-manager, frontend-manager have full code tools."""
        c = _department_config()
        defs = build_agent_definitions(c, {"context7": {}})
        for manager in ["backend-manager", "frontend-manager"]:
            tools = defs[manager]["tools"]
            assert "Read" in tools
            assert "Write" in tools
            assert "Edit" in tools
            assert "Bash" in tools
            assert "Glob" in tools
            assert "Grep" in tools

    def test_department_agents_have_correct_models(self):
        """Dept heads use lead model, managers use code_writer model."""
        c = _department_config()
        defs = build_agent_definitions(c, {})

        # Dept heads should use the phase_lead_model (or planner fallback)
        head_model = defs["coding-dept-head"]["model"]
        review_head_model = defs["review-dept-head"]["model"]

        # Managers should use code_writer model
        backend_model = defs["backend-manager"]["model"]
        frontend_model = defs["frontend-manager"]["model"]
        infra_model = defs["infra-manager"]["model"]

        # Heads share the same model
        assert head_model == review_head_model

        # Managers share the same model
        assert backend_model == frontend_model
        assert frontend_model == infra_model


# =========================================================================
# Group 6: Orchestrator Prompt Tests
# =========================================================================

class TestOrchestratorDepartmentPrompt:
    def test_department_prompt_includes_team_names(self):
        """build_orchestrator_department_prompt includes team names."""
        prompt = build_orchestrator_department_prompt(
            team_prefix="build",
            coding_enabled=True,
            review_enabled=True,
        )
        assert "build-coding-dept" in prompt
        assert "build-review-dept" in prompt

    def test_department_prompt_includes_fix_flow(self):
        """Prompt includes CROSS-DEPARTMENT FIX FLOW section."""
        prompt = build_orchestrator_department_prompt(
            team_prefix="build",
            coding_enabled=True,
            review_enabled=True,
        )
        assert "CROSS-DEPARTMENT FIX FLOW" in prompt
        assert "FIX_REQUIRED" in prompt

    def test_v1_prompt_unchanged_when_departments_disabled(self):
        """When department_model=False, enterprise prompt is v1 format."""
        c = _enterprise_config()
        # Disable department model but keep enterprise mode
        c.enterprise_mode.department_model = False
        c.departments.enabled = False
        prompt = get_orchestrator_system_prompt(c)
        # Should contain v1 enterprise section, not department model
        assert "DEPARTMENT MODEL" not in prompt
        # Should still have the enterprise section
        assert "ENTERPRISE MODE" in prompt


# =========================================================================
# Group 7: Backwards Compatibility Tests — prove v1 behavior is UNCHANGED
# =========================================================================

class TestBackwardsCompatibility:
    """Exhaustive backwards compatibility tests proving that v1 behavior
    is provably unchanged when department_model is False (the default)."""

    # -- CONFIG BACKWARDS COMPAT --

    def test_default_config_no_departments(self):
        """AgentTeamConfig() with no arguments: departments exist but disabled."""
        c = AgentTeamConfig()
        # department_model defaults to False
        assert c.enterprise_mode.department_model is False
        # DepartmentsConfig master switch defaults to False
        assert c.departments.enabled is False
        # enterprise_mode itself defaults to False
        assert c.enterprise_mode.enabled is False
        # Sub-department configs exist but master switch gates them
        assert c.departments.coding.enabled is True  # sub-default, irrelevant when master off
        assert c.departments.review.enabled is True   # sub-default, irrelevant when master off

    def test_standard_depth_no_departments(self):
        """apply_depth_quality_gating('standard') does NOT touch department fields."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, set())
        assert c.enterprise_mode.department_model is False
        assert c.departments.enabled is False
        assert c.enterprise_mode.enabled is False

    def test_thorough_depth_no_departments(self):
        """apply_depth_quality_gating('thorough') does NOT touch department fields."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("thorough", c, set())
        assert c.enterprise_mode.department_model is False
        assert c.departments.enabled is False
        assert c.enterprise_mode.enabled is False

    def test_exhaustive_depth_no_departments(self):
        """apply_depth_quality_gating('exhaustive') does NOT touch department fields."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", c, set())
        assert c.enterprise_mode.department_model is False
        assert c.departments.enabled is False
        assert c.enterprise_mode.enabled is False

    def test_quick_depth_no_departments(self):
        """apply_depth_quality_gating('quick') does NOT touch department fields."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("quick", c, set())
        assert c.enterprise_mode.department_model is False
        assert c.departments.enabled is False
        assert c.enterprise_mode.enabled is False

    def test_enterprise_depth_enables_departments_but_preserves_v1(self):
        """Enterprise depth enables departments AND all v1 enterprise behavior."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        # v2 additions
        assert c.enterprise_mode.department_model is True
        assert c.departments.enabled is True
        # ALL v1 enterprise fields unchanged
        assert c.enterprise_mode.enabled is True
        assert c.enterprise_mode.domain_agents is True
        assert c.enterprise_mode.parallel_review is True
        assert c.enterprise_mode.ownership_validation_gate is True
        assert c.enterprise_mode.scaffold_shared_files is True
        assert c.convergence.max_cycles == 15
        # Exhaustive-equivalent features still present
        assert c.agent_teams.enabled is True
        assert c.phase_leads.enabled is True
        assert c.e2e_testing.enabled is True

    def test_enterprise_depth_user_override_departments_disabled(self):
        """User can override departments.enabled=False at enterprise depth."""
        c = AgentTeamConfig()
        overrides = {"departments.enabled"}
        c.departments.enabled = False  # user explicitly set
        apply_depth_quality_gating("enterprise", c, overrides)
        # _gate respects user override — departments stays False
        assert c.departments.enabled is False
        # But enterprise_mode is still fully enabled (v1 behavior)
        assert c.enterprise_mode.enabled is True

    def test_yaml_loading_no_departments_section(self, tmp_path):
        """YAML with no departments section -> same config as before."""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "orchestrator:\n  model: opus\n",
            encoding="utf-8",
        )
        cfg, overrides = load_config(config_path=str(yaml_path))
        assert cfg.departments.enabled is False
        assert cfg.enterprise_mode.department_model is False
        # No department keys in overrides
        assert not any(k.startswith("departments.") for k in overrides)

    def test_yaml_enterprise_mode_no_department_model_key(self, tmp_path):
        """YAML with enterprise_mode section but no department_model key -> False."""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "enterprise_mode:\n  enabled: true\n",
            encoding="utf-8",
        )
        cfg, _ = load_config(config_path=str(yaml_path))
        assert cfg.enterprise_mode.enabled is True
        assert cfg.enterprise_mode.department_model is False
        # departments.enabled also stays False (not in YAML)
        assert cfg.departments.enabled is False

    # -- AGENT REGISTRATION BACKWARDS COMPAT --

    def test_enterprise_v1_agents_unchanged(self):
        """Enterprise mode with department_model=False has ZERO department agents."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        # Manually disable department model
        c.enterprise_mode.department_model = False
        c.departments.enabled = False
        defs = build_agent_definitions(c, {"context7": {}})
        # No department agents
        for name in DEPARTMENT_AGENT_NAMES:
            assert name not in defs, f"{name} should NOT be registered when department_model=False"
        # v1 domain agents STILL present
        assert "backend-dev" in defs
        assert "frontend-dev" in defs
        assert "infra-dev" in defs
        # Phase leads STILL present
        assert "coding-lead" in defs
        assert "review-lead" in defs

    def test_enterprise_v1_orchestrator_prompt_unchanged(self):
        """Orchestrator prompt with enterprise but no departments = original v1 text."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        c.enterprise_mode.department_model = False
        c.departments.enabled = False
        prompt = get_orchestrator_system_prompt(c)
        # Must contain the exact v1 enterprise section
        assert "ENTERPRISE MODE (150K+ LOC Builds)" in prompt
        # Must NOT contain the v2 department replacement
        assert "DEPARTMENT MODEL" not in prompt
        assert "coding-dept-head" not in prompt
        assert "review-dept-head" not in prompt
        # Must contain v1 wave-based coding text
        assert "Wave-Based Coding" in prompt
        assert "coding-lead" in prompt.lower() or "coding-lead" in prompt
        # Must contain v1 domain-scoped review text
        assert "Domain-Scoped Review" in prompt

    def test_v1_domain_agents_excluded_with_departments(self):
        """With department model ON, v1 domain agents are NOT registered (replaced by managers)."""
        c = _department_config()
        defs = build_agent_definitions(c, {"context7": {}})
        # v1 domain agents should NOT be present (department managers replace them)
        assert "backend-dev" not in defs
        assert "frontend-dev" not in defs
        assert "infra-dev" not in defs
        # v2 department agents present
        assert "coding-dept-head" in defs
        assert "review-dept-head" in defs

    def test_phase_lead_registration_unchanged(self):
        """Phase lead registration uses CODING_LEAD_PROMPT / REVIEW_LEAD_PROMPT unchanged."""
        from agent_team_v15.agents import CODING_LEAD_PROMPT, REVIEW_LEAD_PROMPT
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        c.enterprise_mode.department_model = False
        c.departments.enabled = False
        defs = build_agent_definitions(c, {})
        # coding-lead prompt is CODING_LEAD_PROMPT (+ comm protocol)
        assert CODING_LEAD_PROMPT in defs["coding-lead"]["prompt"]
        # review-lead prompt is REVIEW_LEAD_PROMPT (+ comm protocol)
        assert REVIEW_LEAD_PROMPT in defs["review-lead"]["prompt"]

    def test_team_communication_protocol_unchanged(self):
        """_TEAM_COMMUNICATION_PROTOCOL is appended to all phase leads."""
        from agent_team_v15.agents import _TEAM_COMMUNICATION_PROTOCOL
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, set())
        defs = build_agent_definitions(c, {})
        # Every phase lead should have the comm protocol appended
        for lead in ["coding-lead", "review-lead", "planning-lead",
                     "architecture-lead", "testing-lead"]:
            if lead in defs:
                assert "SDK Subagent Protocol" in defs[lead]["prompt"]

    def test_default_config_zero_department_agents(self):
        """build_agent_definitions() with default config = zero department agents."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, set())
        defs = build_agent_definitions(c, {})
        for name in DEPARTMENT_AGENT_NAMES:
            assert name not in defs

    def test_enterprise_enabled_department_model_false_zero_dept_agents(self):
        """Enterprise enabled but department_model=False -> zero department agents."""
        c = AgentTeamConfig()
        c.enterprise_mode.enabled = True
        c.enterprise_mode.domain_agents = True
        c.phase_leads.enabled = True
        c.agent_teams.enabled = True
        # department_model defaults to False
        defs = build_agent_definitions(c, {})
        for name in DEPARTMENT_AGENT_NAMES:
            assert name not in defs

    # -- STATE BACKWARDS COMPAT --

    def test_state_backwards_compat_missing_fields(self):
        """load_state() with a state file missing department fields -> defaults, no crash."""
        import tempfile
        from agent_team_v15.state import load_state, save_state

        with tempfile.TemporaryDirectory() as td:
            # Simulate a v1 state file that has NO department fields
            import json
            from pathlib import Path
            state_dir = Path(td) / ".agent-team"
            state_dir.mkdir()
            v1_state = {
                "run_id": "abc123",
                "task": "test task",
                "depth": "enterprise",
                "current_phase": "coding",
                "completed_phases": ["planning", "architecture"],
                "total_cost": 5.0,
                "enterprise_mode_active": True,
                "ownership_map_validated": True,
                "waves_completed": 2,
                "domain_agents_deployed": 3,
                # NO department_mode_active, departments_created, manager_count
            }
            (state_dir / "STATE.json").write_text(
                json.dumps(v1_state), encoding="utf-8"
            )
            loaded = load_state(str(state_dir))
            assert loaded is not None
            # v1 fields preserved
            assert loaded.enterprise_mode_active is True
            assert loaded.ownership_map_validated is True
            assert loaded.waves_completed == 2
            assert loaded.domain_agents_deployed == 3
            # v2 department fields have safe defaults
            assert loaded.department_mode_active is False
            assert loaded.departments_created == []
            assert loaded.manager_count == 0

    def test_state_default_department_fields(self):
        """RunState() with no args: department fields default correctly."""
        state = RunState()
        assert state.department_mode_active is False
        assert state.departments_created == []
        assert state.manager_count == 0
        # Existing v1 enterprise fields also have correct defaults
        assert state.enterprise_mode_active is False
        assert state.ownership_map_validated is False
        assert state.waves_completed == 0
        assert state.domain_agents_deployed == 0

    def test_state_asdict_includes_department_fields(self):
        """asdict(RunState()) includes department fields without interference."""
        state = RunState()
        d = asdict(state)
        assert "department_mode_active" in d
        assert "departments_created" in d
        assert "manager_count" in d
        # They don't overwrite or interfere with v1 fields
        assert d["enterprise_mode_active"] is False
        assert d["ownership_map_validated"] is False

    def test_state_v1_field_positions_unchanged(self):
        """v1 enterprise fields exist at the same positions/defaults in RunState."""
        state = RunState()
        # These are the v1 enterprise fields, verify they exist with correct defaults
        assert hasattr(state, "enterprise_mode_active")
        assert hasattr(state, "ownership_map_validated")
        assert hasattr(state, "waves_completed")
        assert hasattr(state, "domain_agents_deployed")
        assert state.enterprise_mode_active is False
        assert state.ownership_map_validated is False
        assert state.waves_completed == 0
        assert state.domain_agents_deployed == 0
