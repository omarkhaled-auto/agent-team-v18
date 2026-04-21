"""Integration tests for the Enterprise v2 Department Model pipeline.

Covers end-to-end flows: config → agents → prompts → state, department
lifecycle simulation, orchestrator prompt alignment, state round-trips,
and realistic project scenarios.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

from agent_team_v15.config import (
    AgentConfig,
    AgentTeamConfig,
    DepartmentConfig,
    DepartmentsConfig,
    EnterpriseModeConfig,
    apply_depth_quality_gating,
    detect_depth,
    load_config,
    DEPTH_AGENT_COUNTS,
)
from agent_team_v15.state import RunState, save_state, load_state
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
# Shared fixtures & helpers
# ---------------------------------------------------------------------------

SAMPLE_OWNERSHIP_MAP = {
    "version": 1,
    "build_id": "integ-test-001",
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
    """Config with enterprise depth gating applied."""
    c = AgentTeamConfig()
    apply_depth_quality_gating("enterprise", c, set())
    return c


def _department_config() -> AgentTeamConfig:
    """Config with enterprise depth (includes department model)."""
    c = _enterprise_config()
    assert c.enterprise_mode.department_model is True
    assert c.departments.enabled is True
    return c


# =========================================================================
# Group 1: Full Pipeline Tests
# =========================================================================

class TestFullPipeline:
    """End-to-end: depth detection -> gating -> agent build -> prompt."""

    def test_enterprise_depth_full_pipeline(self):
        """Full pipeline: depth detection -> gating -> agent build -> prompt -> all pieces connect."""
        cfg = AgentTeamConfig()
        # 1. Depth gating
        apply_depth_quality_gating("enterprise", cfg, set())
        assert cfg.enterprise_mode.enabled is True
        assert cfg.enterprise_mode.department_model is True
        assert cfg.departments.enabled is True
        assert cfg.phase_leads.enabled is True
        assert cfg.agent_teams.enabled is True

        # 2. Agent build
        agents = build_agent_definitions(cfg, mcp_servers={})
        # Department agents registered
        for name in CODING_DEPARTMENT_MEMBERS:
            assert name in agents, f"Missing coding dept agent: {name}"
        for name in REVIEW_DEPARTMENT_MEMBERS:
            assert name in agents, f"Missing review dept agent: {name}"
        # Domain reviewer (generic subagent) also registered
        assert "domain-reviewer" in agents

        # 3. System prompt generated
        prompt = get_orchestrator_system_prompt(cfg)
        assert "DEPARTMENT MODEL" in prompt
        assert "coding-dept-head" in prompt

        # 4. Wave-aligned phase leads still present
        for lead in ("wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"):
            assert lead in agents, f"Phase lead missing: {lead}"

    def test_enterprise_config_to_agents_to_prompt_consistency(self):
        """Config with departments -> build agents -> system prompt -> names are consistent."""
        cfg = _department_config()
        agents = build_agent_definitions(cfg, mcp_servers={})
        prompt = get_orchestrator_system_prompt(cfg)

        # Every department member in agents should be referenced in SOME prompt
        dept_prompt = build_orchestrator_department_prompt(
            team_prefix=cfg.agent_teams.team_name_prefix,
            coding_enabled=cfg.departments.coding.enabled,
            review_enabled=cfg.departments.review.enabled,
        )
        for member in CODING_DEPARTMENT_MEMBERS:
            assert member in agents
            assert member in dept_prompt, f"{member} not in department prompt"
        for member in REVIEW_DEPARTMENT_MEMBERS:
            assert member in agents
            assert member in dept_prompt, f"{member} not in department prompt"

    def test_yaml_to_agents_pipeline(self, tmp_path):
        """YAML with custom department config -> load_config -> build agents -> verify."""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "enterprise_mode:\n"
            "  enabled: true\n"
            "  department_model: true\n"
            "agent_teams:\n"
            "  enabled: true\n"
            "departments:\n"
            "  enabled: true\n"
            "  coding:\n"
            "    max_managers: 6\n"
            "    wave_timeout: 3600\n"
            "  review:\n"
            "    max_managers: 5\n",
            encoding="utf-8",
        )
        cfg, overrides = load_config(config_path=str(yaml_path))
        assert cfg.departments.enabled is True
        assert cfg.departments.coding.max_managers == 6
        assert cfg.departments.coding.wave_timeout == 3600
        assert cfg.departments.review.max_managers == 5

        agents = build_agent_definitions(cfg, mcp_servers={})
        assert "coding-dept-head" in agents
        assert "review-dept-head" in agents

    def test_yaml_override_department_max_managers(self, tmp_path):
        """YAML sets max_managers=6 -> verify it reaches agent registration."""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "enterprise_mode:\n"
            "  enabled: true\n"
            "  department_model: true\n"
            "agent_teams:\n"
            "  enabled: true\n"
            "departments:\n"
            "  enabled: true\n"
            "  coding:\n"
            "    max_managers: 6\n",
            encoding="utf-8",
        )
        cfg, _ = load_config(config_path=str(yaml_path))
        assert cfg.departments.coding.max_managers == 6
        # compute_department_size should cap at this value
        size = compute_department_size(SAMPLE_OWNERSHIP_MAP, "coding", cfg.departments.coding.max_managers)
        assert size <= 6

    def test_depth_gating_plus_yaml_override_departments_disabled(self, tmp_path):
        """Enterprise depth gating + YAML override for departments.enabled=False -> disabled."""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "departments:\n"
            "  enabled: false\n",
            encoding="utf-8",
        )
        cfg, overrides = load_config(config_path=str(yaml_path))
        # Depth gating should enable departments, but user override disables it
        apply_depth_quality_gating("enterprise", cfg, overrides)
        # The user explicitly set departments.enabled=false
        # But depth gating only uses _gate which checks overrides...
        # departments.enabled is tracked through config load, not depth gating overrides
        # Let's check what actually happens:
        # The enterprise depth gating sets departments.enabled=True via _gate
        # but _gate checks if "departments.enabled" is in user_overrides
        assert "departments.enabled" in overrides
        # Since user explicitly set it, _gate should respect the override
        assert cfg.departments.enabled is False

    def test_all_depths_produce_correct_agent_sets(self):
        """For each of 5 depths, verify the correct set of agents is produced."""
        depths = ["quick", "standard", "thorough", "exhaustive", "enterprise"]
        for depth in depths:
            cfg = AgentTeamConfig()
            apply_depth_quality_gating(depth, cfg, set())
            agents = build_agent_definitions(cfg, mcp_servers={})

            # Base agents present at all depths
            assert "planner" in agents, f"planner missing at {depth}"
            assert "code-writer" in agents, f"code-writer missing at {depth}"

            # Wave-aligned phase leads always enabled
            if cfg.phase_leads.enabled:
                assert "wave-a-lead" in agents, f"wave-a-lead missing at {depth}"
                assert "wave-e-lead" in agents, f"wave-e-lead missing at {depth}"

            # Department agents only at enterprise
            if depth == "enterprise":
                assert "coding-dept-head" in agents
                assert "review-dept-head" in agents
            else:
                assert "coding-dept-head" not in agents, f"dept agents at {depth}!"
                assert "review-dept-head" not in agents, f"dept agents at {depth}!"

            # Enterprise domain agents: v1 domain agents are REPLACED by department
            # managers when department_model is active, so they should NOT be present
            # at enterprise depth (which enables department_model).
            if depth == "enterprise":
                assert "backend-dev" not in agents, "v1 domain agents replaced by dept managers"
                assert "backend-manager" in agents

    def test_department_replaces_v1_domain_agents(self):
        """Enterprise dept mode replaces v1 domain agents with v2 department managers."""
        cfg = _department_config()
        agents = build_agent_definitions(cfg, mcp_servers={})

        # v1 domain agents are REPLACED (not coexisting) when department_model is active
        assert "backend-dev" not in agents
        assert "frontend-dev" not in agents
        assert "infra-dev" not in agents

        # v2 department agents present instead
        assert "coding-dept-head" in agents
        assert "backend-manager" in agents
        assert "frontend-manager" in agents
        assert "infra-manager" in agents
        assert "integration-manager" in agents
        assert "review-dept-head" in agents

    def test_v1_domain_agents_without_department_model(self):
        """Enterprise mode WITHOUT department_model keeps v1 domain agents."""
        cfg = AgentTeamConfig()
        cfg.enterprise_mode.enabled = True
        cfg.enterprise_mode.domain_agents = True
        cfg.enterprise_mode.department_model = False
        cfg.departments.enabled = False
        cfg.phase_leads.enabled = True
        cfg.agent_teams.enabled = True
        agents = build_agent_definitions(cfg, mcp_servers={})

        # v1 domain agents present
        assert "backend-dev" in agents
        assert "frontend-dev" in agents
        assert "infra-dev" in agents
        # v2 department agents NOT present
        assert "coding-dept-head" not in agents
        assert "review-dept-head" not in agents

    def test_phase_leads_still_registered_with_departments(self):
        """Phase leads not removed when departments are active."""
        cfg = _department_config()
        agents = build_agent_definitions(cfg, mcp_servers={})
        for lead in ("wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"):
            assert lead in agents, f"Phase lead {lead} missing with departments"

    def test_enterprise_agents_have_required_tools(self):
        """All department agents have the tools specified in their definitions."""
        cfg = _department_config()
        agents = build_agent_definitions(cfg, mcp_servers={})

        # coding-dept-head: coordinator, has Read/Write/Glob/Grep
        cdh_tools = agents["coding-dept-head"]["tools"]
        for t in ["Read", "Write", "Glob", "Grep"]:
            assert t in cdh_tools

        # backend-manager: full code tools
        bm_tools = agents["backend-manager"]["tools"]
        for t in ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]:
            assert t in bm_tools

        # integration-manager: no Bash
        im_tools = agents["integration-manager"]["tools"]
        assert "Bash" not in im_tools
        for t in ["Read", "Write", "Edit", "Glob", "Grep"]:
            assert t in im_tools


# =========================================================================
# Group 2: Department Lifecycle Simulation
# =========================================================================

class TestDepartmentLifecycle:
    """Simulate realistic department operations end-to-end."""

    def test_ownership_map_to_manager_assignments_to_context_slices(self):
        """Create ownership map -> route to managers -> slice per manager -> verify scope."""
        assignments = build_manager_assignments(SAMPLE_OWNERSHIP_MAP)

        # backend-manager gets nestjs domains
        assert "backend-manager" in assignments
        assert "auth-service" in assignments["backend-manager"]
        assert "task-service" in assignments["backend-manager"]

        # frontend-manager gets nextjs domains
        assert "frontend-manager" in assignments
        assert "dashboard-ui" in assignments["frontend-manager"]

        # infra-manager gets docker domains
        assert "infra-manager" in assignments
        assert "infra" in assignments["infra-manager"]

        # Each manager's context slice only contains its domains
        for manager, domains in assignments.items():
            sliced = context_slice_ownership_map(
                SAMPLE_OWNERSHIP_MAP, domain_names=domains,
            )
            assert set(sliced["domains"].keys()) == set(domains)
            # Waves should only reference included domains
            for wave in sliced["waves"]:
                for d in wave["domains"]:
                    assert d in domains, f"Wave includes domain {d} not in {manager}'s assignment"

    def test_wave_execution_simulation(self):
        """For each wave: get domains, assign to managers, build messages, verify workflow."""
        waves = SAMPLE_OWNERSHIP_MAP["waves"]
        all_domains_processed = []

        for wave in waves:
            wave_id = wave["id"]
            wave_name = wave["name"]
            wave_domains = get_wave_domains(SAMPLE_OWNERSHIP_MAP, wave_id)
            assert wave_domains == wave["domains"]

            # Build domain data for this wave
            domain_data = [
                {"name": d, **SAMPLE_OWNERSHIP_MAP["domains"][d]}
                for d in wave_domains
            ]

            # Build assignment message
            msg = build_domain_assignment_message(wave_id, wave_name, domain_data)
            parsed = json.loads(msg)
            assert parsed["type"] == "DOMAIN_ASSIGNMENT"
            assert parsed["wave_id"] == wave_id
            assert parsed["wave_name"] == wave_name
            assert len(parsed["domains"]) == len(wave_domains)

            # Simulate completion for each domain
            for domain_name in wave_domains:
                complete_msg = build_domain_complete_message(
                    wave_id=wave_id,
                    domain=domain_name,
                    status="COMPLETE",
                    files_written=["src/test.ts"],
                    issues=[],
                )
                parsed_c = json.loads(complete_msg)
                assert parsed_c["type"] == "DOMAIN_COMPLETE"
                assert parsed_c["domain"] == domain_name
                assert parsed_c["status"] == "COMPLETE"

            all_domains_processed.extend(wave_domains)

        # All domains processed across all waves
        expected = set(SAMPLE_OWNERSHIP_MAP["domains"].keys())
        assert set(all_domains_processed) == expected

    def test_smart_sizing_integration(self):
        """Various map sizes -> assignments -> should_work_directly -> verify decisions."""
        # Small: 1 domain per manager -> work directly
        small_map = {
            "domains": {
                "auth": {"tech_stack": "nestjs", "agent_type": "backend-dev"},
            },
            "waves": [{"id": 1, "name": "w1", "domains": ["auth"]}],
        }
        assignments = build_manager_assignments(small_map)
        for manager, domains in assignments.items():
            assert should_manager_work_directly(len(domains)) is True

        # Medium: 2 domains per manager -> still direct
        medium_map = {
            "domains": {
                "auth": {"tech_stack": "nestjs"},
                "users": {"tech_stack": "nestjs"},
            },
            "waves": [{"id": 1, "name": "w1", "domains": ["auth", "users"]}],
        }
        assignments = build_manager_assignments(medium_map)
        for manager, domains in assignments.items():
            assert should_manager_work_directly(len(domains)) is True

        # Large: 3+ domains per manager -> spawn workers
        large_map = {
            "domains": {
                "auth": {"tech_stack": "nestjs"},
                "users": {"tech_stack": "nestjs"},
                "billing": {"tech_stack": "nestjs"},
            },
            "waves": [{"id": 1, "name": "w1", "domains": ["auth", "users", "billing"]}],
        }
        assignments = build_manager_assignments(large_map)
        for manager, domains in assignments.items():
            if len(domains) > 2:
                assert should_manager_work_directly(len(domains)) is False

    def test_integration_manager_wave_end_flow(self):
        """Simulate wave completion, verify integration-manager receives correct context."""
        # After wave 2 completes, integration-manager gets all backend domains
        wave_2_domains = get_wave_domains(SAMPLE_OWNERSHIP_MAP, 2)
        assert set(wave_2_domains) == {"auth-service", "task-service"}

        # Slice for integration-manager = all domains (it sees everything)
        full_slice = context_slice_ownership_map(
            SAMPLE_OWNERSHIP_MAP, domain_names=list(SAMPLE_OWNERSHIP_MAP["domains"].keys()),
        )
        assert len(full_slice["domains"]) == 4

        # Build completion messages from each domain
        completions = []
        for domain_name in wave_2_domains:
            msg = build_domain_complete_message(
                wave_id=2, domain=domain_name, status="COMPLETE",
                files_written=[f"src/{domain_name}/module.ts"],
                issues=[],
            )
            completions.append(json.loads(msg))
        assert all(c["status"] == "COMPLETE" for c in completions)

    def test_cross_department_fix_flow(self):
        """Review returns PARTIAL -> verify coding dept prompt contains fix flow."""
        dept_prompt = build_orchestrator_department_prompt(
            team_prefix="build",
            coding_enabled=True,
            review_enabled=True,
        )
        # Fix flow instructions present
        assert "CROSS-DEPARTMENT FIX FLOW" in dept_prompt
        assert "PARTIAL" in dept_prompt
        assert "FIX_REQUIRED" in dept_prompt
        assert "coding-dept-head" in dept_prompt

    def test_department_team_names(self):
        """Team names generated match what orchestrator prompt references."""
        prefix = "build"
        coding_team = get_department_team_name(prefix, "coding")
        review_team = get_department_team_name(prefix, "review")
        assert coding_team == "build-coding-dept"
        assert review_team == "build-review-dept"

        # Department prompt references these names
        dept_prompt = build_orchestrator_department_prompt(
            team_prefix=prefix, coding_enabled=True, review_enabled=True,
        )
        assert coding_team in dept_prompt
        assert review_team in dept_prompt


# =========================================================================
# Group 3: Orchestrator Prompt Integration
# =========================================================================

class TestOrchestratorPromptIntegration:
    """Verify system prompt and task prompt alignment.

    Phase G Slice 4f rewrote ``TEAM_ORCHESTRATOR_SYSTEM_PROMPT`` from the
    ALL-CAPS section-header shape to an XML-section shape (<role> /
    <gates> / <enterprise_mode>). The orchestrator-prompt-content-only
    assertions (e.g., ``"PHASE LEAD COORDINATION"`` banner presence) have
    been retired — the NEW body-content contract is covered by
    ``tests/test_orchestrator_prompt.py``.

    The tests here remain because they cover the DEPARTMENT-MODEL SWAP
    mechanism (``get_orchestrator_system_prompt`` merging
    ``_DEPARTMENT_MODEL_ENTERPRISE_SECTION`` into the base prompt when
    ``department_model=True``). That mechanism is intentional functional
    behavior; Slice 4f follow-up re-anchors the swap on the new XML
    ``<enterprise_mode>`` tag so these tests pass again.
    """

    def test_system_prompt_and_task_prompt_alignment(self):
        """System prompt and department prompt mention same team names and agent names."""
        cfg = _department_config()
        system_prompt = get_orchestrator_system_prompt(cfg)
        dept_prompt = build_orchestrator_department_prompt(
            team_prefix=cfg.agent_teams.team_name_prefix,
            coding_enabled=cfg.departments.coding.enabled,
            review_enabled=cfg.departments.review.enabled,
        )

        # Both should reference coding-dept-head
        assert "coding-dept-head" in system_prompt
        assert "coding-dept-head" in dept_prompt

        # Both should reference review-dept-head
        assert "review-dept-head" in system_prompt
        assert "review-dept-head" in dept_prompt

    def test_system_prompt_swap_preserves_other_phases(self):
        """Department mode swaps enterprise section, keeps planning/testing/audit sections."""
        cfg = _department_config()
        prompt = get_orchestrator_system_prompt(cfg)

        # Planning/Wave A still described
        assert "wave-a-lead" in prompt
        # Testing phase still described
        assert "wave-t-lead" in prompt
        # Audit phase still described
        assert "wave-e-lead" in prompt

    def test_department_prompt_contains_all_registered_agents(self):
        """Every department agent name in system prompt is actually registered."""
        cfg = _department_config()
        agents = build_agent_definitions(cfg, mcp_servers={})

        # Check that department members referenced in the prompt are registered
        dept_members = CODING_DEPARTMENT_MEMBERS + REVIEW_DEPARTMENT_MEMBERS
        for member in dept_members:
            assert member in agents, f"{member} referenced but not in agent definitions"

    def test_task_prompt_injection_matches_system_prompt(self):
        """CLI injection (department prompt) complements system prompt."""
        cfg = _department_config()
        system_prompt = get_orchestrator_system_prompt(cfg)
        task_prompt = build_orchestrator_department_prompt(
            team_prefix=cfg.agent_teams.team_name_prefix,
            coding_enabled=cfg.departments.coding.enabled,
            review_enabled=cfg.departments.review.enabled,
        )

        # System prompt uses DEPARTMENT MODEL section
        assert "DEPARTMENT MODEL" in system_prompt

        # Task prompt (CLI injection) provides operational details
        assert "ENTERPRISE MODE" in task_prompt
        assert "DEPARTMENT MODEL" in task_prompt

        # No contradictions: both reference department heads
        assert "coding-dept-head" in system_prompt
        assert "coding-dept-head" in task_prompt

    def test_non_department_enterprise_system_prompt(self):
        """Enterprise mode without department_model has original enterprise section."""
        cfg = AgentTeamConfig()
        cfg.enterprise_mode.enabled = True
        cfg.enterprise_mode.department_model = False
        cfg.departments.enabled = False
        cfg.phase_leads.enabled = True
        cfg.agent_teams.enabled = True

        prompt = get_orchestrator_system_prompt(cfg)
        # Should have the base (non-department) enterprise section, not the
        # department-model swap content.
        assert "DEPARTMENT MODEL" not in prompt
        # Department-head names must not leak into the non-department prompt.
        assert "coding-dept-head" not in prompt
        assert "review-dept-head" not in prompt


# =========================================================================
# Group 4: State Integration
# =========================================================================

class TestStateIntegration:
    """State persistence round-trips with department fields."""

    def test_state_round_trip_with_department_fields(self, tmp_path):
        """Create state with department data, save, load, verify."""
        state = RunState(
            task="Build enterprise app",
            depth="enterprise",
            department_mode_active=True,
            departments_created=["build-coding-dept", "build-review-dept"],
            manager_count=7,
            enterprise_mode_active=True,
            waves_completed=3,
        )
        state_dir = str(tmp_path / ".agent-team")
        save_state(state, directory=state_dir)

        loaded = load_state(directory=state_dir)
        assert loaded is not None
        assert loaded.department_mode_active is True
        assert loaded.departments_created == ["build-coding-dept", "build-review-dept"]
        assert loaded.manager_count == 7
        assert loaded.enterprise_mode_active is True
        assert loaded.waves_completed == 3

    def test_state_backwards_compat_load(self, tmp_path):
        """Load v1 state (no department fields) -> no crash, defaults used."""
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir(parents=True)
        v1_data = {
            "run_id": "abc123",
            "task": "Build app",
            "depth": "standard",
            "current_phase": "coding",
            "completed_phases": ["planning", "architecture"],
            "total_cost": 5.0,
            "schema_version": 1,
            # NO department fields
        }
        (state_dir / "STATE.json").write_text(
            json.dumps(v1_data), encoding="utf-8",
        )
        loaded = load_state(directory=str(state_dir))
        assert loaded is not None
        # Department fields should have defaults
        assert loaded.department_mode_active is False
        assert loaded.departments_created == []
        assert loaded.manager_count == 0
        # Original fields preserved
        assert loaded.task == "Build app"
        assert loaded.depth == "standard"

    def test_state_forward_compat(self, tmp_path):
        """v2 state with extra department fields loaded by code (extra fields ignored)."""
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir(parents=True)
        v2_data = {
            "run_id": "def456",
            "task": "Enterprise build",
            "depth": "enterprise",
            "current_phase": "review",
            "completed_phases": ["planning", "architecture", "coding"],
            "schema_version": 2,
            "department_mode_active": True,
            "departments_created": ["build-coding-dept"],
            "manager_count": 4,
            # Hypothetical future field that current code doesn't know about
            "department_health_scores": {"coding": 95, "review": 88},
        }
        (state_dir / "STATE.json").write_text(
            json.dumps(v2_data), encoding="utf-8",
        )
        loaded = load_state(directory=str(state_dir))
        assert loaded is not None
        assert loaded.department_mode_active is True
        assert loaded.departments_created == ["build-coding-dept"]
        assert loaded.manager_count == 4

    def test_department_state_reflects_config(self):
        """Enterprise config -> department_mode_active should be settable."""
        cfg = _department_config()
        state = RunState(
            task="Enterprise build",
            depth="enterprise",
            enterprise_mode_active=cfg.enterprise_mode.enabled,
            department_mode_active=(
                cfg.enterprise_mode.department_model and cfg.departments.enabled
            ),
        )
        assert state.enterprise_mode_active is True
        assert state.department_mode_active is True


# =========================================================================
# Group 5: Realistic Scenario Tests
# =========================================================================

class TestRealisticScenarios:
    """Simulate real-world project configurations end-to-end."""

    def test_small_project_scenario(self):
        """2 domains, 1 wave -> managers work directly, no workers."""
        ownership_map = {
            "domains": {
                "api": {"tech_stack": "nestjs+prisma", "files": ["src/api/**"], "requirements": ["REQ-001"]},
                "web": {"tech_stack": "nextjs+react", "files": ["src/web/**"], "requirements": ["REQ-002"]},
            },
            "waves": [
                {"id": 1, "name": "all", "domains": ["api", "web"], "parallel": True},
            ],
            "shared_scaffolding": [],
        }
        assignments = build_manager_assignments(ownership_map)
        for manager, domains in assignments.items():
            assert should_manager_work_directly(len(domains)) is True
            assert len(domains) <= 2

        # Only 1 wave
        assert len(ownership_map["waves"]) == 1

    def test_medium_project_scenario(self):
        """5 domains, 3 waves -> mixed direct/worker execution."""
        ownership_map = {
            "domains": {
                "auth": {"tech_stack": "nestjs", "requirements": ["REQ-001"]},
                "users": {"tech_stack": "nestjs", "requirements": ["REQ-002"]},
                "billing": {"tech_stack": "nestjs", "requirements": ["REQ-003"]},
                "dashboard": {"tech_stack": "nextjs", "requirements": ["REQ-004"]},
                "infra": {"tech_stack": "docker", "requirements": ["REQ-005"]},
            },
            "waves": [
                {"id": 1, "name": "foundation", "domains": ["infra"], "parallel": False},
                {"id": 2, "name": "backend", "domains": ["auth", "users", "billing"], "parallel": True},
                {"id": 3, "name": "frontend", "domains": ["dashboard"], "parallel": False},
            ],
            "shared_scaffolding": [],
        }
        assignments = build_manager_assignments(ownership_map)
        # backend-manager has 3 domains -> spawn workers
        assert "backend-manager" in assignments
        assert len(assignments["backend-manager"]) == 3
        assert should_manager_work_directly(len(assignments["backend-manager"])) is False

        # frontend-manager has 1 domain -> work directly
        assert "frontend-manager" in assignments
        assert len(assignments["frontend-manager"]) == 1
        assert should_manager_work_directly(len(assignments["frontend-manager"])) is True

        # infra-manager has 1 domain -> work directly
        assert "infra-manager" in assignments
        assert should_manager_work_directly(len(assignments["infra-manager"])) is True

    def test_large_project_scenario(self):
        """10+ domains, 5 waves -> all managers spawn workers."""
        domains = {}
        for i in range(5):
            domains[f"backend-svc-{i}"] = {"tech_stack": "nestjs+prisma", "requirements": [f"REQ-B{i}"]}
        for i in range(4):
            domains[f"frontend-app-{i}"] = {"tech_stack": "nextjs+react", "requirements": [f"REQ-F{i}"]}
        domains["infra-main"] = {"tech_stack": "docker+ci", "requirements": ["REQ-I0"]}
        domains["infra-monitoring"] = {"tech_stack": "docker", "requirements": ["REQ-I1"]}

        ownership_map = {
            "domains": domains,
            "waves": [
                {"id": 1, "name": "infra", "domains": ["infra-main", "infra-monitoring"]},
                {"id": 2, "name": "backend-w1", "domains": ["backend-svc-0", "backend-svc-1", "backend-svc-2"]},
                {"id": 3, "name": "backend-w2", "domains": ["backend-svc-3", "backend-svc-4"]},
                {"id": 4, "name": "frontend-w1", "domains": ["frontend-app-0", "frontend-app-1"]},
                {"id": 5, "name": "frontend-w2", "domains": ["frontend-app-2", "frontend-app-3"]},
            ],
        }
        assignments = build_manager_assignments(ownership_map)
        # backend-manager has 5 domains -> definitely spawn workers
        assert len(assignments.get("backend-manager", [])) == 5
        assert should_manager_work_directly(5) is False

        # frontend-manager has 4 domains -> spawn workers
        assert len(assignments.get("frontend-manager", [])) == 4
        assert should_manager_work_directly(4) is False

        # infra-manager has 2 domains -> work directly
        assert len(assignments.get("infra-manager", [])) == 2
        assert should_manager_work_directly(2) is True

        # Department size calculation
        cfg = _department_config()
        coding_size = compute_department_size(
            ownership_map, "coding", cfg.departments.coding.max_managers,
        )
        assert coding_size >= 3  # backend + frontend + infra + integration
        review_size = compute_department_size(
            ownership_map, "review", cfg.departments.review.max_managers,
        )
        assert review_size <= 3  # capped at 3 for review

    def test_monorepo_scenario(self):
        """All domains same tech stack -> only 1 manager type needed."""
        domains = {}
        for i in range(6):
            domains[f"service-{i}"] = {"tech_stack": "nestjs+prisma", "requirements": [f"REQ-{i}"]}
        ownership_map = {
            "domains": domains,
            "waves": [
                {"id": 1, "name": "batch-1", "domains": [f"service-{i}" for i in range(3)]},
                {"id": 2, "name": "batch-2", "domains": [f"service-{i}" for i in range(3, 6)]},
            ],
        }
        assignments = build_manager_assignments(ownership_map)
        # All domains go to backend-manager (all nestjs)
        assert len(assignments) == 1
        assert "backend-manager" in assignments
        assert len(assignments["backend-manager"]) == 6

        # All domains in one manager's context slice
        sliced = context_slice_ownership_map(
            ownership_map, domain_names=assignments["backend-manager"],
        )
        assert len(sliced["domains"]) == 6


# =========================================================================
# Group 6: Cross-Module Interaction Tests
# =========================================================================

class TestCrossModuleInteractions:
    """Verify assumptions between modules don't silently break."""

    def test_department_members_match_agent_definitions(self):
        """CODING_DEPARTMENT_MEMBERS and REVIEW_DEPARTMENT_MEMBERS match agents.py registrations."""
        cfg = _department_config()
        agents = build_agent_definitions(cfg, mcp_servers={})

        for member in CODING_DEPARTMENT_MEMBERS:
            assert member in agents, f"Coding member {member} not registered in agents"
        for member in REVIEW_DEPARTMENT_MEMBERS:
            assert member in agents, f"Review member {member} not registered in agents"

    def test_tech_stack_map_covers_common_stacks(self):
        """TECH_STACK_MANAGER_MAP covers the stacks used in test ownership maps."""
        # Check common tech stacks resolve to a manager
        test_stacks = ["nestjs", "prisma", "express", "nextjs", "react", "vue",
                        "docker", "terraform", "k8s"]
        for stack in test_stacks:
            domain = {"tech_stack": stack}
            manager = resolve_manager_for_domain(domain)
            assert manager in CODING_DEPARTMENT_MEMBERS, f"{stack} -> {manager} not a dept member"

    def test_context_slice_preserves_shared_scaffolding(self):
        """Context slicing always includes shared_scaffolding regardless of domain filter."""
        sliced = context_slice_ownership_map(
            SAMPLE_OWNERSHIP_MAP, domain_names=["auth-service"],
        )
        assert sliced["shared_scaffolding"] == SAMPLE_OWNERSHIP_MAP["shared_scaffolding"]

    def test_department_size_respects_config_cap(self):
        """compute_department_size never exceeds config_max_managers."""
        # Even with many manager types, department size is capped
        large_map = {
            "domains": {
                f"svc-{i}": {"tech_stack": stack}
                for i, stack in enumerate(["nestjs", "react", "docker", "terraform", "vue", "express"])
            },
            "waves": [],
        }
        size = compute_department_size(large_map, "coding", 3)  # cap at 3
        assert size <= 3

    def test_wave_domains_returns_empty_for_missing_wave(self):
        """get_wave_domains returns [] for non-existent wave id."""
        result = get_wave_domains(SAMPLE_OWNERSHIP_MAP, 999)
        assert result == []

    def test_department_prompt_disabled_coding(self):
        """Department prompt with coding_enabled=False omits coding section."""
        prompt = build_orchestrator_department_prompt(
            team_prefix="build", coding_enabled=False, review_enabled=True,
        )
        assert "CODING DEPARTMENT" not in prompt
        assert "REVIEW DEPARTMENT" in prompt

    def test_department_prompt_disabled_review(self):
        """Department prompt with review_enabled=False omits review section."""
        prompt = build_orchestrator_department_prompt(
            team_prefix="build", coding_enabled=True, review_enabled=False,
        )
        assert "CODING DEPARTMENT" in prompt
        assert "REVIEW DEPARTMENT" not in prompt

    def test_mcp_servers_propagate_to_department_agents(self):
        """When MCP servers are available, department agents get the right MCP tools."""
        cfg = _department_config()
        mcp_servers = {"context7": {}, "sequential_thinking": {}}
        agents = build_agent_definitions(cfg, mcp_servers=mcp_servers)

        # coding-dept-head should get ST tools
        cdh = agents["coding-dept-head"]
        assert "mcp__sequential-thinking__sequentialthinking" in cdh["tools"]

        # backend-manager should get context7 tools
        bm = agents["backend-manager"]
        assert "mcp__context7__resolve-library-id" in bm["tools"]
        assert "mcp__context7__query-docs" in bm["tools"]

        # integration-manager should NOT get MCP tools
        im = agents["integration-manager"]
        assert all("mcp__" not in t for t in im["tools"])

    def test_mcp_servers_empty_no_mcp_tools(self):
        """When no MCP servers available, no mcp__ tools on any department agent."""
        cfg = _department_config()
        agents = build_agent_definitions(cfg, mcp_servers={})

        for name in CODING_DEPARTMENT_MEMBERS + REVIEW_DEPARTMENT_MEMBERS:
            agent = agents[name]
            mcp_tools = [t for t in agent["tools"] if "mcp__" in t]
            assert mcp_tools == [], f"{name} has MCP tools with empty servers: {mcp_tools}"
