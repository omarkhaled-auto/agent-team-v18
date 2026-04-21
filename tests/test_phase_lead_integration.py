"""Smoke tests for phase lead SDK subagent integration."""
import pytest
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating
from agent_team_v15.agents import (
    build_agent_definitions,
    get_orchestrator_system_prompt,
    TEAM_ORCHESTRATOR_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
)


class TestDepthGating:
    """Phase leads are enabled/disabled by depth."""

    def test_quick_depth_enables_phase_leads(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("quick", c, {})
        assert c.phase_leads.enabled is True

    def test_standard_depth_enables_phase_leads(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, {})
        assert c.phase_leads.enabled is True

    def test_thorough_depth_enables_phase_leads(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("thorough", c, {})
        assert c.phase_leads.enabled is True

    def test_exhaustive_depth_enables_phase_leads(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", c, {})
        assert c.phase_leads.enabled is True

    def test_phase_leads_and_agent_teams_coactivate(self):
        """phase_leads and agent_teams are both enabled at standard depth."""
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, {})
        assert c.phase_leads.enabled is True
        assert c.agent_teams.enabled is True  # agent_teams co-activates with phase_leads


class TestAgentDefinitions:
    """Phase leads are registered as AgentDefinition objects."""

    def _standard_config(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, {})
        return c

    def test_standard_depth_includes_wave_phase_leads(self):
        defs = build_agent_definitions(self._standard_config(), {})
        leads = sorted(k for k in defs if k.endswith("-lead"))
        assert leads == [
            "wave-a-lead",
            "wave-d5-lead",
            "wave-e-lead",
            "wave-t-lead",
        ]

    def test_quick_depth_includes_phase_leads(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("quick", c, {})
        defs = build_agent_definitions(c, {})
        leads = [k for k in defs if k.endswith("-lead")]
        assert len(leads) > 0

    def test_per_lead_tool_customization(self):
        """Wave E lead has restricted tools (no Write/Edit)."""
        defs = build_agent_definitions(self._standard_config(), {})
        audit_tools = defs["wave-e-lead"]["tools"]
        assert "Read" in audit_tools
        assert "Bash" in audit_tools
        # Wave E should NOT have Write or Edit
        assert "Write" not in audit_tools or "Edit" not in audit_tools

    def test_wave_a_lead_has_write_tools(self):
        defs = build_agent_definitions(self._standard_config(), {})
        coding_tools = defs["wave-a-lead"]["tools"]
        assert "Write" in coding_tools
        assert "Edit" in coding_tools

    def test_each_lead_has_required_fields(self):
        defs = build_agent_definitions(self._standard_config(), {})
        for name in [k for k in defs if k.endswith("-lead")]:
            agent = defs[name]
            assert "description" in agent, f"{name} missing description"
            assert "prompt" in agent, f"{name} missing prompt"
            assert "tools" in agent, f"{name} missing tools"
            assert "model" in agent, f"{name} missing model"
            assert len(agent["prompt"]) > 100, f"{name} prompt too short"

    def test_disabled_lead_excluded(self):
        """If a specific lead is disabled, it should be excluded."""
        c = self._standard_config()
        c.phase_leads.wave_e_lead.enabled = False
        defs = build_agent_definitions(c, {})
        assert "wave-e-lead" not in defs
        # Other leads should still be present
        assert "wave-a-lead" in defs


class TestOrchestratorPromptSelection:
    """Correct orchestrator prompt is selected based on config."""

    def test_standard_depth_uses_team_prompt(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("standard", c, {})
        prompt = get_orchestrator_system_prompt(c)
        assert prompt is TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_quick_depth_uses_team_prompt(self):
        c = AgentTeamConfig()
        apply_depth_quality_gating("quick", c, {})
        prompt = get_orchestrator_system_prompt(c)
        assert prompt is TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_prompt_references_task_tool(self):
        assert "Task tool" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT or "Task" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_prompt_no_teamcreate(self):
        assert "TeamCreate" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_prompt_no_sendmessage(self):
        assert "SendMessage" not in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
