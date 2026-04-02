"""Tests for enterprise mode configuration and depth gating."""
import pytest
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating


class TestEnterpriseModeConfig:
    def test_enterprise_mode_defaults_disabled(self):
        c = AgentTeamConfig()
        assert c.enterprise_mode.enabled is False

    def test_enterprise_depth_enables_enterprise_mode(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, {})
        assert c.enterprise_mode.enabled is True
        assert c.enterprise_mode.domain_agents is True
        assert c.enterprise_mode.parallel_review is True
        assert c.enterprise_mode.ownership_validation_gate is True
        assert c.phase_leads.enabled is True
        assert c.agent_teams.enabled is True

    def test_enterprise_depth_higher_convergence(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", c, {})
        assert c.convergence.max_cycles >= 5

    def test_enterprise_depth_higher_agent_counts(self):
        from agent_team_v15.config import DEPTH_AGENT_COUNTS
        assert "enterprise" in DEPTH_AGENT_COUNTS
        assert DEPTH_AGENT_COUNTS["enterprise"]["coding"][1] >= 10

    def test_standard_depth_does_not_enable_enterprise(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, {})
        assert c.enterprise_mode.enabled is False

    def test_enterprise_depth_in_agent_counts(self):
        """Enterprise depth is recognized in DEPTH_AGENT_COUNTS even if not in
        the keyword auto-detect map (enterprise depth is set explicitly)."""
        from agent_team_v15.config import DEPTH_AGENT_COUNTS
        assert "enterprise" in DEPTH_AGENT_COUNTS
