"""Tests for enterprise domain agent registration."""
import pytest
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
from agent_team_v15.agents import build_agent_definitions


class TestEnterpriseDomainAgents:
    def _enterprise_config_v1(self):
        """Enterprise config with department_model OFF (v1: domain agents)."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, {})
        c.enterprise_mode.department_model = False
        c.departments.enabled = False
        return c

    def _enterprise_config(self):
        """Enterprise config with department_model ON (v2: default)."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, {})
        return c

    def test_enterprise_v1_registers_domain_agents(self):
        defs = build_agent_definitions(self._enterprise_config_v1(), {"context7": {}})
        assert "backend-dev" in defs
        assert "frontend-dev" in defs
        assert "infra-dev" in defs

    def test_enterprise_v2_excludes_domain_agents(self):
        defs = build_agent_definitions(self._enterprise_config(), {"context7": {}})
        assert "backend-dev" not in defs
        assert "frontend-dev" not in defs
        assert "infra-dev" not in defs
        # Department agents are registered instead
        assert "coding-dept-head" in defs
        assert "backend-manager" in defs

    def test_standard_does_not_register_domain_agents(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, {})
        defs = build_agent_definitions(c, {})
        assert "backend-dev" not in defs

    def test_backend_dev_has_context7(self):
        defs = build_agent_definitions(self._enterprise_config_v1(), {"context7": {}})
        tools = defs["backend-dev"]["tools"]
        assert "mcp__context7__query-docs" in tools

    def test_infra_dev_no_context7(self):
        defs = build_agent_definitions(self._enterprise_config_v1(), {"context7": {}})
        tools = defs["infra-dev"]["tools"]
        assert "mcp__context7__query-docs" not in tools

    def test_domain_agents_have_required_fields(self):
        defs = build_agent_definitions(self._enterprise_config_v1(), {})
        for name in ["backend-dev", "frontend-dev", "infra-dev"]:
            assert "description" in defs[name]
            assert "prompt" in defs[name]
            assert "tools" in defs[name]
            assert len(defs[name]["prompt"]) > 200

    def test_enterprise_still_has_phase_leads(self):
        defs = build_agent_definitions(self._enterprise_config(), {})
        assert "wave-a-lead" in defs
        assert "wave-e-lead" in defs
        assert "wave-d5-lead" in defs
