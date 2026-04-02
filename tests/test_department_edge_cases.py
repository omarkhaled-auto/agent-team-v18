"""Exhaustive edge-case tests for Enterprise v2 Department Model.

Covers config validation, department module functions, context slicing,
agent registration, orchestrator prompt swap, and state round-tripping.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from agent_team_v15.config import (
    AgentConfig,
    AgentTeamConfig,
    AgentTeamsConfig,
    DepartmentConfig,
    DepartmentsConfig,
    EnterpriseModeConfig,
    PhaseLeadsConfig,
    _dict_to_config,
    apply_depth_quality_gating,
)
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
    load_ownership_map,
    resolve_manager_for_domain,
    should_manager_work_directly,
)
from agent_team_v15.state import RunState, load_state, save_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_enterprise_config(**overrides: Any) -> AgentTeamConfig:
    """Return an AgentTeamConfig with enterprise + departments enabled."""
    cfg = AgentTeamConfig()
    cfg.enterprise_mode = EnterpriseModeConfig(
        enabled=True,
        department_model=True,
    )
    cfg.departments = DepartmentsConfig(
        enabled=True,
        coding=DepartmentConfig(enabled=True, max_managers=4),
        review=DepartmentConfig(enabled=True, max_managers=3),
    )
    cfg.agent_teams = AgentTeamsConfig(enabled=True)
    cfg.phase_leads = PhaseLeadsConfig(enabled=True)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _sample_ownership_map() -> dict:
    return {
        "version": 2,
        "build_id": "test-build",
        "domains": {
            "user-service": {"tech_stack": "NestJS+Prisma", "files": ["src/users/"]},
            "auth-service": {"tech_stack": "NestJS+Prisma", "files": ["src/auth/"]},
            "dashboard": {"tech_stack": "Next.js+React", "files": ["src/app/dashboard/"]},
            "landing": {"tech_stack": "Next.js+React", "files": ["src/app/landing/"]},
            "infra": {"tech_stack": "Docker+CI", "files": ["docker/", ".github/"]},
        },
        "waves": [
            {"id": 1, "name": "Foundation", "domains": ["infra"]},
            {"id": 2, "name": "Backend", "domains": ["user-service", "auth-service"]},
            {"id": 3, "name": "Frontend", "domains": ["dashboard", "landing"]},
        ],
        "shared_scaffolding": ["prisma/schema.prisma", "docker-compose.yml"],
    }


# ===================================================================
# Group 1: Config Edge Cases (17 tests)
# ===================================================================

class TestConfigEdgeCases:
    """DepartmentConfig, DepartmentsConfig, YAML loading, validation, depth gating."""

    def test_negative_max_managers(self):
        """Negative max_managers is accepted by dataclass (no validation on raw field)."""
        dc = DepartmentConfig(max_managers=-1)
        assert dc.max_managers == -1

    def test_zero_max_managers(self):
        dc = DepartmentConfig(max_managers=0)
        assert dc.max_managers == 0

    def test_huge_max_managers(self):
        dc = DepartmentConfig(max_managers=999999)
        assert dc.max_managers == 999999

    def test_negative_wave_timeout(self):
        dc = DepartmentConfig(wave_timeout=-100)
        assert dc.wave_timeout == -100

    def test_zero_communication_timeout(self):
        dc = DepartmentConfig(communication_timeout=0)
        assert dc.communication_timeout == 0

    def test_departments_enabled_without_enterprise_mode(self):
        """departments.enabled=True without enterprise_mode -> forced disabled."""
        cfg, _ = _dict_to_config({
            "departments": {"enabled": True},
            "agent_teams": {"enabled": True},
        })
        assert cfg.departments.enabled is False

    def test_departments_enabled_without_agent_teams(self):
        """departments.enabled=True without agent_teams -> forced disabled."""
        cfg, _ = _dict_to_config({
            "enterprise_mode": {"enabled": True},
            "departments": {"enabled": True},
            "phase_leads": {"enabled": True},
        })
        assert cfg.departments.enabled is False

    def test_both_deps_disabled(self):
        """Both coding and review departments disabled simultaneously."""
        cfg = DepartmentsConfig(
            enabled=True,
            coding=DepartmentConfig(enabled=False),
            review=DepartmentConfig(enabled=False),
        )
        assert cfg.enabled is True
        assert cfg.coding.enabled is False
        assert cfg.review.enabled is False

    def test_department_model_true_but_departments_config_disabled(self):
        """enterprise_mode.department_model=True but departments.enabled=False."""
        cfg = AgentTeamConfig()
        cfg.enterprise_mode = EnterpriseModeConfig(enabled=True, department_model=True)
        cfg.departments = DepartmentsConfig(enabled=False)
        assert cfg.enterprise_mode.department_model is True
        assert cfg.departments.enabled is False

    def test_yaml_coding_as_string(self):
        """YAML with coding as a string instead of dict -> defaults preserved."""
        cfg, _ = _dict_to_config({
            "departments": {
                "enabled": False,
                "coding": "invalid-string",
            },
        })
        # When coding is not a dict, _dict_to_config preserves default
        assert cfg.departments.coding.max_managers == 4

    def test_yaml_coding_as_number(self):
        cfg, _ = _dict_to_config({
            "departments": {
                "enabled": False,
                "coding": 42,
            },
        })
        assert cfg.departments.coding.max_managers == 4

    def test_yaml_coding_as_null(self):
        cfg, _ = _dict_to_config({
            "departments": {
                "enabled": False,
                "coding": None,
            },
        })
        assert cfg.departments.coding.max_managers == 4

    def test_yaml_coding_as_empty_dict(self):
        """Empty dict -> all defaults."""
        cfg, _ = _dict_to_config({
            "departments": {
                "enabled": False,
                "coding": {},
            },
        })
        assert cfg.departments.coding.enabled is True  # default
        assert cfg.departments.coding.max_managers == 4

    def test_yaml_with_extra_unknown_keys(self):
        """Extra unknown keys in departments section are ignored."""
        cfg, overrides = _dict_to_config({
            "departments": {
                "enabled": False,
                "unknown_field": True,
                "another_thing": {"nested": 42},
            },
        })
        assert cfg.departments.enabled is False
        assert "departments.unknown_field" in overrides

    def test_double_depth_gating_idempotent(self):
        """Applying enterprise depth gating twice produces same result."""
        cfg1 = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", cfg1)
        snapshot1 = (cfg1.departments.enabled, cfg1.enterprise_mode.department_model)
        apply_depth_quality_gating("enterprise", cfg1)
        snapshot2 = (cfg1.departments.enabled, cfg1.enterprise_mode.department_model)
        assert snapshot1 == snapshot2

    def test_all_five_depths_department_defaults(self):
        """Only enterprise depth enables departments; all others preserve defaults (disabled)."""
        for depth in ("quick", "standard", "thorough", "exhaustive"):
            cfg = AgentTeamConfig()
            apply_depth_quality_gating(depth, cfg)
            assert cfg.departments.enabled is False, f"depth={depth} should not enable departments"
            assert cfg.enterprise_mode.department_model is False, f"depth={depth} should not enable department_model"

    def test_enterprise_depth_enables_departments(self):
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", cfg)
        assert cfg.departments.enabled is True
        assert cfg.enterprise_mode.department_model is True

    def test_yaml_float_max_managers_coercion(self):
        """Float values in max_managers are coerced to int via _load_dept_cfg."""
        cfg, _ = _dict_to_config({
            "departments": {
                "enabled": False,
                "coding": {"max_managers": 3.7},
            },
        })
        assert cfg.departments.coding.max_managers == 3
        assert isinstance(cfg.departments.coding.max_managers, int)


# ===================================================================
# Group 2: Department Module Edge Cases (22 tests)
# ===================================================================

class TestResolveManager:
    """resolve_manager_for_domain edge cases."""

    def test_empty_tech_stack(self):
        assert resolve_manager_for_domain({"tech_stack": ""}) == "backend-manager"

    def test_none_tech_stack(self):
        assert resolve_manager_for_domain({}) == "backend-manager"

    def test_missing_tech_stack_key(self):
        assert resolve_manager_for_domain({"files": []}) == "backend-manager"

    def test_mixed_case_tech_stack(self):
        """NestJS+Prisma with mixed case still matches (lowercased)."""
        assert resolve_manager_for_domain({"tech_stack": "NestJS+Prisma"}) == "backend-manager"

    def test_compound_tech_stack_frontend(self):
        assert resolve_manager_for_domain({"tech_stack": "Next.js+React+Tailwind"}) == "frontend-manager"

    def test_docker_infra(self):
        assert resolve_manager_for_domain({"tech_stack": "Docker+CI"}) == "infra-manager"

    def test_kubernetes_infra(self):
        assert resolve_manager_for_domain({"tech_stack": "kubernetes"}) == "infra-manager"

    def test_unknown_tech_stack_fallback(self):
        assert resolve_manager_for_domain({"tech_stack": "Haskell+Elm"}) == "backend-manager"

    def test_all_known_keywords_resolve(self):
        """Every keyword in TECH_STACK_MANAGER_MAP resolves to the expected manager."""
        for keyword, expected_manager in TECH_STACK_MANAGER_MAP.items():
            result = resolve_manager_for_domain({"tech_stack": keyword})
            assert result == expected_manager, f"keyword={keyword}"


class TestBuildManagerAssignments:
    """build_manager_assignments edge cases."""

    def test_empty_ownership_map(self):
        assert build_manager_assignments({}) == {}

    def test_empty_domains(self):
        assert build_manager_assignments({"domains": {}}) == {}

    def test_single_domain(self):
        result = build_manager_assignments({
            "domains": {"svc": {"tech_stack": "NestJS"}},
        })
        assert result == {"backend-manager": ["svc"]}

    def test_all_domains_same_tech(self):
        result = build_manager_assignments({
            "domains": {
                "a": {"tech_stack": "NestJS"},
                "b": {"tech_stack": "NestJS+Prisma"},
            },
        })
        assert "backend-manager" in result
        assert len(result) == 1
        assert sorted(result["backend-manager"]) == ["a", "b"]


class TestSmartSizing:
    """should_manager_work_directly boundary conditions."""

    def test_zero_domains(self):
        assert should_manager_work_directly(0) is True

    def test_one_domain(self):
        assert should_manager_work_directly(1) is True

    def test_exactly_two(self):
        assert should_manager_work_directly(2) is True

    def test_exactly_three(self):
        assert should_manager_work_directly(3) is False

    def test_large_count(self):
        assert should_manager_work_directly(100) is False


class TestGetWaveDomains:
    """get_wave_domains edge cases."""

    def test_wave_id_exists(self):
        omap = _sample_ownership_map()
        assert get_wave_domains(omap, 2) == ["user-service", "auth-service"]

    def test_wave_id_not_found(self):
        omap = _sample_ownership_map()
        assert get_wave_domains(omap, 99) == []

    def test_empty_waves(self):
        assert get_wave_domains({"waves": []}, 1) == []

    def test_no_waves_key(self):
        assert get_wave_domains({}, 1) == []

    def test_wave_missing_domains_key(self):
        assert get_wave_domains({"waves": [{"id": 1}]}, 1) == []


class TestComputeDepartmentSize:
    """compute_department_size edge cases."""

    def test_review_always_capped_at_3(self):
        omap = _sample_ownership_map()
        assert compute_department_size(omap, "review", 10) == 3

    def test_review_max_managers_below_3(self):
        omap = _sample_ownership_map()
        assert compute_department_size(omap, "review", 2) == 2

    def test_coding_empty_map(self):
        assert compute_department_size({"domains": {}}, "coding", 10) == 1  # +1 for integration-manager

    def test_coding_exceeding_max_managers(self):
        omap = _sample_ownership_map()
        # Should be clamped to max_managers
        size = compute_department_size(omap, "coding", 2)
        assert size == 2

    def test_coding_normal(self):
        omap = _sample_ownership_map()
        # 3 unique managers (backend, frontend, infra) + 1 integration = 4
        size = compute_department_size(omap, "coding", 10)
        assert size == 4


class TestMessageBuilders:
    """Message builder edge cases."""

    def test_assignment_message_valid_json(self):
        msg = build_domain_assignment_message(1, "Wave 1", [{"name": "svc"}])
        parsed = json.loads(msg)
        assert parsed["type"] == "DOMAIN_ASSIGNMENT"
        assert parsed["wave_id"] == 1

    def test_assignment_message_empty_domains(self):
        msg = build_domain_assignment_message(0, "", [])
        parsed = json.loads(msg)
        assert parsed["domains"] == []

    def test_complete_message_special_chars(self):
        msg = build_domain_complete_message(
            1, "user-service", "DONE",
            ["src/file with spaces.ts"],
            ['Error: "quote" problem'],
        )
        parsed = json.loads(msg)
        assert parsed["issues"] == ['Error: "quote" problem']

    def test_complete_message_empty_lists(self):
        msg = build_domain_complete_message(1, "svc", "OK", [], [])
        parsed = json.loads(msg)
        assert parsed["files_written"] == []
        assert parsed["issues"] == []


class TestTeamName:
    """get_department_team_name edge cases."""

    def test_normal(self):
        assert get_department_team_name("build", "coding") == "build-coding-dept"

    def test_empty_prefix(self):
        assert get_department_team_name("", "review") == "-review-dept"

    def test_special_chars_prefix(self):
        assert get_department_team_name("my-app_v2", "coding") == "my-app_v2-coding-dept"


class TestLoadOwnershipMap:
    """load_ownership_map: nonexistent, invalid JSON, empty file, valid file."""

    def test_nonexistent_directory(self, tmp_path: Path):
        result = load_ownership_map(tmp_path / "nonexistent")
        assert result is None

    def test_invalid_json(self, tmp_path: Path):
        (tmp_path / ".agent-team").mkdir()
        (tmp_path / ".agent-team" / "OWNERSHIP_MAP.json").write_text("not json!", encoding="utf-8")
        result = load_ownership_map(tmp_path)
        assert result is None

    def test_empty_file(self, tmp_path: Path):
        (tmp_path / ".agent-team").mkdir()
        (tmp_path / ".agent-team" / "OWNERSHIP_MAP.json").write_text("", encoding="utf-8")
        result = load_ownership_map(tmp_path)
        assert result is None

    def test_valid_file(self, tmp_path: Path):
        (tmp_path / ".agent-team").mkdir()
        data = {"version": 1, "domains": {}}
        (tmp_path / ".agent-team" / "OWNERSHIP_MAP.json").write_text(
            json.dumps(data), encoding="utf-8",
        )
        result = load_ownership_map(tmp_path)
        assert result == data


class TestDepartmentMembers:
    """Verify member lists are consistent."""

    def test_coding_department_has_five_members(self):
        assert len(CODING_DEPARTMENT_MEMBERS) == 5

    def test_review_department_has_four_members(self):
        assert len(REVIEW_DEPARTMENT_MEMBERS) == 4

    def test_no_overlap_between_departments(self):
        overlap = set(CODING_DEPARTMENT_MEMBERS) & set(REVIEW_DEPARTMENT_MEMBERS)
        assert overlap == set()


# ===================================================================
# Group 3: Context Slicing Edge Cases (14 tests)
# ===================================================================

class TestContextSliceOwnershipMap:
    """context_slice_ownership_map edge cases."""

    def _import_fn(self):
        from agent_team_v15.agents import context_slice_ownership_map
        return context_slice_ownership_map

    def test_empty_map(self):
        fn = self._import_fn()
        result = fn({})
        assert result["domains"] == {}
        assert result["waves"] == []

    def test_map_with_no_domains_key(self):
        fn = self._import_fn()
        result = fn({"waves": [{"id": 1, "domains": ["x"]}]})
        assert result["domains"] == {}
        assert result["waves"] == []  # no included domains, so waves filtered out

    def test_map_with_no_waves_key(self):
        fn = self._import_fn()
        result = fn({"domains": {"svc": {"tech_stack": "NestJS"}}})
        assert "svc" in result["domains"]
        assert result["waves"] == []

    def test_map_with_no_shared_scaffolding_key(self):
        fn = self._import_fn()
        result = fn({"domains": {"svc": {}}})
        assert result["shared_scaffolding"] == []

    def test_both_filters_and_semantics(self):
        """Both filters provided -> AND semantics."""
        fn = self._import_fn()
        omap = _sample_ownership_map()
        result = fn(omap, tech_stack_filter="NestJS", domain_names=["user-service"])
        assert list(result["domains"].keys()) == ["user-service"]

    def test_both_filters_no_match(self):
        fn = self._import_fn()
        omap = _sample_ownership_map()
        result = fn(omap, tech_stack_filter="NestJS", domain_names=["dashboard"])
        assert result["domains"] == {}

    def test_empty_domain_names_list(self):
        """Empty domain_names list -> no domains pass (truthy empty list is falsy for 'if domain_names')."""
        fn = self._import_fn()
        omap = _sample_ownership_map()
        # Empty list is falsy, so the domain_names filter is skipped
        result = fn(omap, domain_names=[])
        assert len(result["domains"]) == len(omap["domains"])

    def test_empty_tech_stack_filter(self):
        """Empty string tech_stack_filter is falsy -> all domains pass."""
        fn = self._import_fn()
        omap = _sample_ownership_map()
        result = fn(omap, tech_stack_filter="")
        assert len(result["domains"]) == len(omap["domains"])

    def test_mutation_isolation(self):
        """Modify sliced map, verify original unchanged."""
        fn = self._import_fn()
        omap = _sample_ownership_map()
        original_files = omap["domains"]["user-service"]["files"][:]
        sliced = fn(omap, domain_names=["user-service"])
        sliced["domains"]["user-service"]["files"].append("MUTATED")
        assert omap["domains"]["user-service"]["files"] == original_files

    def test_wave_with_mixed_included_excluded_domains(self):
        """Wave referencing both included and excluded domains -> only included kept."""
        fn = self._import_fn()
        omap = {
            "domains": {
                "a": {"tech_stack": "NestJS"},
                "b": {"tech_stack": "React"},
            },
            "waves": [{"id": 1, "domains": ["a", "b"]}],
        }
        result = fn(omap, tech_stack_filter="NestJS")
        assert result["waves"][0]["domains"] == ["a"]

    def test_preserves_domain_fields(self):
        fn = self._import_fn()
        omap = {
            "domains": {
                "svc": {
                    "tech_stack": "NestJS",
                    "files": ["a.ts"],
                    "contracts": ["C1"],
                    "custom_field": 42,
                },
            },
        }
        result = fn(omap, domain_names=["svc"])
        assert result["domains"]["svc"]["custom_field"] == 42
        assert result["domains"]["svc"]["contracts"] == ["C1"]

    def test_version_and_build_id_preserved(self):
        fn = self._import_fn()
        omap = _sample_ownership_map()
        result = fn(omap, domain_names=["user-service"])
        assert result["version"] == 2
        assert result["build_id"] == "test-build"

    def test_shared_scaffolding_preserved(self):
        fn = self._import_fn()
        omap = _sample_ownership_map()
        result = fn(omap, domain_names=["user-service"])
        assert result["shared_scaffolding"] == omap["shared_scaffolding"]

    def test_none_filters_returns_all(self):
        fn = self._import_fn()
        omap = _sample_ownership_map()
        result = fn(omap, tech_stack_filter=None, domain_names=None)
        assert len(result["domains"]) == len(omap["domains"])


# ===================================================================
# Group 4: Agent Registration Edge Cases (10 tests)
# ===================================================================

class TestAgentRegistration:
    """Verify department agent registration when enterprise department mode is active."""

    def _get_agents(self, config: AgentTeamConfig | None = None) -> dict:
        from agent_team_v15.agents import build_agent_definitions
        cfg = config or _full_enterprise_config()
        mcp_servers = {
            k: v for k, v in cfg.mcp_servers.items() if v.enabled
        }
        return build_agent_definitions(cfg, mcp_servers)

    def test_dept_agents_have_non_empty_prompt(self):
        agents = self._get_agents()
        dept_names = CODING_DEPARTMENT_MEMBERS + REVIEW_DEPARTMENT_MEMBERS
        for name in dept_names:
            assert name in agents, f"{name} not registered"
            assert agents[name].get("prompt", "").strip() != "", f"{name} has empty prompt"

    def test_dept_agents_have_non_empty_description(self):
        agents = self._get_agents()
        dept_names = CODING_DEPARTMENT_MEMBERS + REVIEW_DEPARTMENT_MEMBERS
        for name in dept_names:
            assert agents[name].get("description", "").strip() != "", f"{name} has empty description"

    def test_dept_agents_have_model(self):
        agents = self._get_agents()
        dept_names = CODING_DEPARTMENT_MEMBERS + REVIEW_DEPARTMENT_MEMBERS
        for name in dept_names:
            assert "model" in agents[name], f"{name} missing model key"

    def test_dept_heads_mention_sendmessage(self):
        """Dept heads' prompts must reference SendMessage for intra-team communication."""
        agents = self._get_agents()
        for head in ["coding-dept-head", "review-dept-head"]:
            prompt = agents[head]["prompt"]
            assert "SendMessage" in prompt, f"{head} prompt doesn't mention SendMessage"

    def test_managers_mention_agent(self):
        """Domain managers reference Agent() for worker spawning."""
        agents = self._get_agents()
        for mgr in ["backend-manager", "frontend-manager"]:
            prompt = agents[mgr]["prompt"]
            assert "Agent(" in prompt or "agent" in prompt.lower(), f"{mgr} prompt doesn't reference Agent"

    def test_integration_manager_no_bash(self):
        """Integration manager should NOT have Bash tool (file merges only)."""
        agents = self._get_agents()
        tools = agents["integration-manager"]["tools"]
        assert "Bash" not in tools

    def test_no_mcp_servers_config(self):
        """With all MCP servers disabled, agents still register."""
        cfg = _full_enterprise_config()
        cfg.mcp_servers = {}
        agents = self._get_agents(cfg)
        assert "coding-dept-head" in agents

    def test_context7_only(self):
        """With only context7 enabled."""
        cfg = _full_enterprise_config()
        from agent_team_v15.config import MCPServerConfig
        cfg.mcp_servers = {"context7": MCPServerConfig(enabled=True)}
        agents = self._get_agents(cfg)
        # backend-manager should have context7 tools
        be_tools = agents["backend-manager"]["tools"]
        assert any("context7" in t for t in be_tools)

    def test_sequential_thinking_only(self):
        """With only sequential_thinking enabled."""
        cfg = _full_enterprise_config()
        from agent_team_v15.config import MCPServerConfig
        cfg.mcp_servers = {"sequential_thinking": MCPServerConfig(enabled=True)}
        agents = self._get_agents(cfg)
        # dept heads should have ST tools
        head_tools = agents["coding-dept-head"]["tools"]
        assert any("sequential-thinking" in t for t in head_tools)

    def test_both_mcp_servers(self):
        cfg = _full_enterprise_config()
        from agent_team_v15.config import MCPServerConfig
        cfg.mcp_servers = {
            "context7": MCPServerConfig(enabled=True),
            "sequential_thinking": MCPServerConfig(enabled=True),
        }
        agents = self._get_agents(cfg)
        # Head has ST, manager has C7
        assert any("sequential-thinking" in t for t in agents["coding-dept-head"]["tools"])
        assert any("context7" in t for t in agents["backend-manager"]["tools"])


# ===================================================================
# Group 5: Orchestrator Prompt + State Edge Cases (10 tests)
# ===================================================================

class TestOrchestratorPromptSwap:
    """get_orchestrator_system_prompt department model swap."""

    def test_prompt_swap_activates_for_department_config(self):
        from agent_team_v15.agents import get_orchestrator_system_prompt
        cfg = _full_enterprise_config()
        prompt = get_orchestrator_system_prompt(cfg)
        assert "DEPARTMENT MODEL" in prompt

    def test_prompt_swap_preserves_non_enterprise_content(self):
        """Content before and after the enterprise section should survive the swap."""
        from agent_team_v15.agents import get_orchestrator_system_prompt
        cfg = _full_enterprise_config()
        prompt = get_orchestrator_system_prompt(cfg)
        # Should still contain phase lead instructions
        assert "TEAM ORCHESTRATOR" in prompt or "phase" in prompt.lower()

    def test_double_call_produces_same_result(self):
        from agent_team_v15.agents import get_orchestrator_system_prompt
        cfg = _full_enterprise_config()
        p1 = get_orchestrator_system_prompt(cfg)
        p2 = get_orchestrator_system_prompt(cfg)
        assert p1 == p2

    def test_no_swap_when_department_model_disabled(self):
        from agent_team_v15.agents import get_orchestrator_system_prompt
        cfg = _full_enterprise_config()
        cfg.enterprise_mode.department_model = False
        cfg.departments.enabled = False
        prompt = get_orchestrator_system_prompt(cfg)
        assert "DEPARTMENT MODEL" not in prompt

    def test_build_orchestrator_department_prompt_coding_only(self):
        prompt = build_orchestrator_department_prompt("build", True, False)
        assert "CODING DEPARTMENT" in prompt
        assert "REVIEW DEPARTMENT" not in prompt

    def test_build_orchestrator_department_prompt_review_only(self):
        prompt = build_orchestrator_department_prompt("build", False, True)
        assert "CODING DEPARTMENT" not in prompt
        assert "REVIEW DEPARTMENT" in prompt

    def test_build_orchestrator_department_prompt_both(self):
        prompt = build_orchestrator_department_prompt("build", True, True)
        assert "CODING DEPARTMENT" in prompt
        assert "REVIEW DEPARTMENT" in prompt

    def test_build_orchestrator_department_prompt_neither(self):
        prompt = build_orchestrator_department_prompt("build", False, False)
        assert "CODING DEPARTMENT" not in prompt
        assert "REVIEW DEPARTMENT" not in prompt
        assert "DEPARTMENT MODEL" in prompt  # header always present


class TestStateDepartmentFields:
    """RunState department-related fields and round-tripping."""

    def test_state_fields_in_asdict(self):
        s = RunState()
        d = asdict(s)
        assert "department_mode_active" in d
        assert "departments_created" in d
        assert "manager_count" in d

    def test_state_default_department_values(self):
        s = RunState()
        assert s.department_mode_active is False
        assert s.departments_created == []
        assert s.manager_count == 0

    def test_state_load_with_missing_department_fields(self, tmp_path: Path):
        """Backwards compat: old state files without department fields."""
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir()
        data = {
            "run_id": "abc123",
            "task": "test",
            "depth": "standard",
            "current_phase": "init",
            "completed_phases": [],
            "total_cost": 0.0,
            "artifacts": {},
            "interrupted": False,
            "timestamp": "2024-01-01T00:00:00+00:00",
            "convergence_cycles": 0,
            "requirements_checked": 0,
            "requirements_total": 0,
            "error_context": "",
            "milestone_progress": {},
        }
        (state_dir / "STATE.json").write_text(json.dumps(data), encoding="utf-8")
        loaded = load_state(str(state_dir))
        assert loaded is not None
        assert loaded.department_mode_active is False
        assert loaded.departments_created == []
        assert loaded.manager_count == 0

    def test_state_load_with_extra_unknown_fields(self, tmp_path: Path):
        """Extra unknown fields in JSON should not crash load_state."""
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir()
        data = {
            "run_id": "abc123",
            "task": "test",
            "future_field": "hello",
            "another_future": [1, 2, 3],
        }
        (state_dir / "STATE.json").write_text(json.dumps(data), encoding="utf-8")
        loaded = load_state(str(state_dir))
        assert loaded is not None
        assert loaded.task == "test"

    def test_departments_created_round_trip(self, tmp_path: Path):
        """departments_created list survives save/load."""
        state_dir = str(tmp_path / ".agent-team")
        s = RunState(
            department_mode_active=True,
            departments_created=["coding-dept", "review-dept"],
            manager_count=7,
        )
        save_state(s, state_dir)
        loaded = load_state(state_dir)
        assert loaded is not None
        assert loaded.department_mode_active is True
        assert loaded.departments_created == ["coding-dept", "review-dept"]
        assert loaded.manager_count == 7

    def test_manager_count_float_coercion(self, tmp_path: Path):
        """manager_count stored as float in JSON is coerced back to int-compatible."""
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir()
        data = {
            "run_id": "abc",
            "task": "test",
            "manager_count": 5.0,
        }
        (state_dir / "STATE.json").write_text(json.dumps(data), encoding="utf-8")
        loaded = load_state(str(state_dir))
        assert loaded is not None
        assert loaded.manager_count == 5

    def test_state_corrupt_json(self, tmp_path: Path):
        """Corrupt JSON returns None."""
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir()
        (state_dir / "STATE.json").write_text("{broken json", encoding="utf-8")
        assert load_state(str(state_dir)) is None

    def test_enterprise_state_fields_round_trip(self, tmp_path: Path):
        """Full enterprise state round-trips correctly."""
        state_dir = str(tmp_path / ".agent-team")
        s = RunState(
            enterprise_mode_active=True,
            ownership_map_validated=True,
            waves_completed=3,
            domain_agents_deployed=5,
            department_mode_active=True,
            departments_created=["coding-dept"],
            manager_count=4,
        )
        save_state(s, state_dir)
        loaded = load_state(state_dir)
        assert loaded is not None
        assert loaded.enterprise_mode_active is True
        assert loaded.ownership_map_validated is True
        assert loaded.waves_completed == 3
        assert loaded.domain_agents_deployed == 5
        assert loaded.department_mode_active is True
