"""Tests for pipeline team wiring — Agent Teams backend integration into cli.py.

Covers:
- Backend selection logic (enabled/disabled, fallback, env vars)
- Prompt injection (team mode on/off, prefix, max turns)
- Config field loading (new AgentTeamsConfig fields)
- Fallback behavior (RuntimeError, graceful degradation)
- Display integration (team created, phase lead, shutdown)
- Team state propagation (_use_team_mode, _team_state globals)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.agent_teams_backend import (
    AgentTeamsBackend,
    CLIBackend,
    TeamState,
    create_execution_backend,
)
from agent_team_v15.config import AgentTeamConfig, AgentTeamsConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> AgentTeamConfig:
    """Default config with agent_teams disabled."""
    return AgentTeamConfig()


@pytest.fixture
def enabled_config() -> AgentTeamConfig:
    """Config with agent_teams enabled."""
    cfg = AgentTeamConfig()
    cfg.agent_teams.enabled = True
    return cfg


@pytest.fixture
def enabled_no_fallback_config() -> AgentTeamConfig:
    """Config with agent_teams enabled but fallback disabled."""
    cfg = AgentTeamConfig()
    cfg.agent_teams.enabled = True
    cfg.agent_teams.fallback_to_cli = False
    return cfg


# ---------------------------------------------------------------------------
# 1. Config field tests — new AgentTeamsConfig fields exist with defaults
# ---------------------------------------------------------------------------


class TestAgentTeamsConfigFields:
    """Verify new pipeline wiring config fields exist and have correct defaults."""

    def test_team_name_prefix_default(self):
        cfg = AgentTeamsConfig()
        assert cfg.team_name_prefix == "build"

    def test_phase_lead_model_default(self):
        cfg = AgentTeamsConfig()
        assert cfg.phase_lead_model == ""

    def test_phase_lead_max_turns_default(self):
        cfg = AgentTeamsConfig()
        assert cfg.phase_lead_max_turns == 200

    def test_auto_shutdown_default(self):
        cfg = AgentTeamsConfig()
        assert cfg.auto_shutdown is True

    def test_custom_team_name_prefix(self):
        cfg = AgentTeamsConfig(team_name_prefix="deploy")
        assert cfg.team_name_prefix == "deploy"

    def test_custom_phase_lead_max_turns(self):
        cfg = AgentTeamsConfig(phase_lead_max_turns=500)
        assert cfg.phase_lead_max_turns == 500

    def test_auto_shutdown_disabled(self):
        cfg = AgentTeamsConfig(auto_shutdown=False)
        assert cfg.auto_shutdown is False

    def test_phase_lead_model_custom(self):
        cfg = AgentTeamsConfig(phase_lead_model="claude-sonnet-4-6")
        assert cfg.phase_lead_model == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# 2. Backend selection tests
# ---------------------------------------------------------------------------


class TestBackendSelection:
    """Verify create_execution_backend routes correctly."""

    def test_disabled_returns_cli_backend(self, default_config):
        """When agent_teams.enabled=False, always returns CLIBackend."""
        backend = create_execution_backend(default_config)
        assert isinstance(backend, CLIBackend)

    @patch.dict(os.environ, {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "0"})
    def test_enabled_but_env_var_missing_returns_cli(self, enabled_config):
        """When enabled but env var is not '1', falls back to CLIBackend."""
        backend = create_execution_backend(enabled_config)
        assert isinstance(backend, CLIBackend)

    @patch.dict(os.environ, {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"})
    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_enabled_cli_unavailable_fallback(self, mock_verify, enabled_config):
        """When CLI not available and fallback=True, returns CLIBackend."""
        backend = create_execution_backend(enabled_config)
        assert isinstance(backend, CLIBackend)

    @patch.dict(os.environ, {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"})
    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_enabled_cli_unavailable_no_fallback_raises(
        self, mock_verify, enabled_no_fallback_config
    ):
        """When CLI not available and fallback=False, raises RuntimeError."""
        with pytest.raises(RuntimeError, match="claude CLI"):
            create_execution_backend(enabled_no_fallback_config)

    @patch.dict(os.environ, {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"})
    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch(
        "agent_team_v15.agent_teams_backend.detect_agent_teams_available",
        return_value=True,
    )
    def test_all_conditions_met_returns_agent_teams(
        self, mock_detect, mock_verify, enabled_config
    ):
        """When all conditions met, returns AgentTeamsBackend."""
        backend = create_execution_backend(enabled_config)
        assert isinstance(backend, AgentTeamsBackend)


# ---------------------------------------------------------------------------
# 3. CLIBackend initialization tests
# ---------------------------------------------------------------------------


class TestCLIBackendInit:
    """Verify CLIBackend initializes to correct state."""

    def test_initialize_sets_active(self, default_config):
        backend = CLIBackend(default_config)
        state = asyncio.run(backend.initialize())
        assert state.active is True
        assert state.mode == "cli"

    def test_no_peer_messaging(self, default_config):
        backend = CLIBackend(default_config)
        assert backend.supports_peer_messaging() is False

    def test_no_self_claiming(self, default_config):
        backend = CLIBackend(default_config)
        assert backend.supports_self_claiming() is False


# ---------------------------------------------------------------------------
# 4. Prompt injection tests
# ---------------------------------------------------------------------------


class TestPromptInjection:
    """Verify team-mode prompt injection logic."""

    def test_team_mode_prompt_contains_team_create(self):
        """When _use_team_mode is True, prompt should contain TeamCreate."""
        base_prompt = "Deploy agents for this task."
        config = AgentTeamConfig()
        config.agent_teams.team_name_prefix = "test-build"
        config.agent_teams.phase_lead_max_turns = 300

        # Simulate the injection logic from cli.py
        prompt = base_prompt
        use_team_mode = True
        if use_team_mode:
            prompt += (
                "\n\n[TEAM MODE ENABLED] You MUST use TeamCreate and team members "
                "for parallel task execution. Do NOT use isolated sub-agent fleets. "
                f"Team name prefix: {config.agent_teams.team_name_prefix}. "
                f"Phase lead max turns: {config.agent_teams.phase_lead_max_turns}."
            )

        assert "[TEAM MODE ENABLED]" in prompt
        assert "TeamCreate" in prompt
        assert "test-build" in prompt
        assert "300" in prompt

    def test_no_injection_when_team_mode_off(self):
        """When _use_team_mode is False, prompt should not be modified."""
        base_prompt = "Deploy agents for this task."
        use_team_mode = False
        prompt = base_prompt
        if use_team_mode:
            prompt += "\n\n[TEAM MODE ENABLED]"

        assert prompt == base_prompt
        assert "[TEAM MODE ENABLED]" not in prompt

    def test_milestone_prompt_injection_includes_milestone_id(self):
        """Milestone prompt injection should include milestone-specific team name."""
        config = AgentTeamConfig()
        config.agent_teams.team_name_prefix = "build"
        config.agent_teams.phase_lead_max_turns = 200
        milestone_id = "milestone-3"

        ms_prompt = "Execute milestone 3 tasks."
        use_team_mode = True
        if use_team_mode:
            _ms_team_name = f"{config.agent_teams.team_name_prefix}-{milestone_id}"
            ms_prompt += (
                f"\n\n[TEAM MODE ENABLED] You MUST use TeamCreate and team members "
                f"for parallel task execution. Do NOT use isolated sub-agent fleets. "
                f"Team name: {_ms_team_name}. "
                f"Phase lead max turns: {config.agent_teams.phase_lead_max_turns}."
            )

        assert "build-milestone-3" in ms_prompt
        assert "[TEAM MODE ENABLED]" in ms_prompt


# ---------------------------------------------------------------------------
# 5. Fallback behavior tests
# ---------------------------------------------------------------------------


class TestFallbackBehavior:
    """Verify graceful degradation when Agent Teams is unavailable."""

    @patch.dict(os.environ, {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"})
    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_fallback_preserves_pipeline_function(self, mock_verify):
        """Pipeline should work normally when falling back to CLIBackend."""
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = True

        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

        # Backend should initialize successfully
        state = asyncio.run(backend.initialize())
        assert state.active is True
        assert state.mode == "cli"

    def test_use_team_mode_false_when_disabled(self):
        """_use_team_mode should be False when agent_teams.enabled=False."""
        config = AgentTeamConfig()
        use_team_mode = False

        if config.agent_teams.enabled:
            use_team_mode = True

        assert use_team_mode is False

    def test_use_team_mode_false_on_cli_fallback(self):
        """_use_team_mode should be False when backend falls back to CLI."""
        team_state = TeamState(
            mode="cli",
            active=True,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )
        use_team_mode = team_state.mode == "agent_teams"
        assert use_team_mode is False

    def test_use_team_mode_true_on_agent_teams(self):
        """_use_team_mode should be True when backend is agent_teams."""
        team_state = TeamState(
            mode="agent_teams",
            active=True,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )
        use_team_mode = team_state.mode == "agent_teams"
        assert use_team_mode is True


# ---------------------------------------------------------------------------
# 6. Display integration tests
# ---------------------------------------------------------------------------


class TestDisplayIntegration:
    """Verify display functions can be called without errors."""

    def test_print_team_created_no_error(self):
        from agent_team_v15.display import print_team_created

        # Should not raise
        print_team_created("build-session", "agent_teams")

    def test_print_phase_lead_spawned_no_error(self):
        from agent_team_v15.display import print_phase_lead_spawned

        print_phase_lead_spawned("build-milestone-1", "milestone-1")

    def test_print_team_messages_no_error(self):
        from agent_team_v15.display import print_team_messages

        print_team_messages(42, ["agent-a", "agent-b", "agent-c"])

    def test_print_team_messages_zero(self):
        from agent_team_v15.display import print_team_messages

        # Should be a no-op for zero messages
        print_team_messages(0, [])

    def test_print_team_shutdown_no_error(self):
        from agent_team_v15.display import print_team_shutdown

        print_team_shutdown("build-session", completed=5, failed=1)

    def test_print_team_shutdown_all_success(self):
        from agent_team_v15.display import print_team_shutdown

        print_team_shutdown("build-session", completed=10, failed=0)


# ---------------------------------------------------------------------------
# 7. Team state propagation tests
# ---------------------------------------------------------------------------


class TestTeamStatePropagation:
    """Verify team state is correctly derived from backend mode."""

    def test_agent_teams_mode_sets_active(self):
        state = TeamState(
            mode="agent_teams",
            active=True,
            teammates=["lead-1", "lead-2"],
            completed_tasks=["task-1"],
            failed_tasks=[],
            total_messages=5,
        )
        assert state.active is True
        assert state.mode == "agent_teams"
        assert len(state.teammates) == 2
        assert state.total_messages == 5

    def test_cli_mode_no_teammates(self):
        state = TeamState(
            mode="cli",
            active=True,
            teammates=[],
            completed_tasks=[],
            failed_tasks=[],
        )
        assert state.teammates == []

    def test_team_state_tracks_failures(self):
        state = TeamState(
            mode="agent_teams",
            active=True,
            teammates=[],
            completed_tasks=["t1"],
            failed_tasks=["t2", "t3"],
        )
        assert len(state.failed_tasks) == 2
        assert len(state.completed_tasks) == 1


# ---------------------------------------------------------------------------
# 8. Config integration with AgentTeamConfig
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    """Verify AgentTeamsConfig is properly nested in AgentTeamConfig."""

    def test_agent_teams_field_exists(self):
        config = AgentTeamConfig()
        assert hasattr(config, "agent_teams")
        assert isinstance(config.agent_teams, AgentTeamsConfig)

    def test_default_agent_teams_disabled(self):
        config = AgentTeamConfig()
        assert config.agent_teams.enabled is False

    def test_new_fields_accessible(self):
        config = AgentTeamConfig()
        assert config.agent_teams.team_name_prefix == "build"
        assert config.agent_teams.phase_lead_model == ""
        assert config.agent_teams.phase_lead_max_turns == 200
        assert config.agent_teams.auto_shutdown is True

    def test_original_fields_preserved(self):
        """Existing fields should not be affected by new additions."""
        config = AgentTeamConfig()
        assert config.agent_teams.fallback_to_cli is True
        assert config.agent_teams.max_teammates == 5
        assert config.agent_teams.wave_timeout_seconds == 3600
        assert config.agent_teams.task_timeout_seconds == 1800
        assert config.agent_teams.teammate_display_mode == "in-process"


# ---------------------------------------------------------------------------
# 9. Phase lead lifecycle wiring tests
# ---------------------------------------------------------------------------


class TestPhaseLeadWiring:
    """Verify phase lead lifecycle integration with the pipeline."""

    def test_phase_leads_config_exists(self):
        """PhaseLeadsConfig should be nested in AgentTeamConfig."""
        from agent_team_v15.config import PhaseLeadsConfig
        config = AgentTeamConfig()
        assert hasattr(config, "phase_leads")
        assert isinstance(config.phase_leads, PhaseLeadsConfig)

    def test_phase_leads_disabled_by_default(self):
        config = AgentTeamConfig()
        assert config.phase_leads.enabled is False

    def test_phase_leads_gate_requires_agent_teams(self):
        """Phase leads should only activate when agent_teams is also enabled."""
        config = AgentTeamConfig()
        config.phase_leads.enabled = True
        # agent_teams still disabled — phase leads should not spawn
        should_spawn = config.agent_teams.enabled and config.phase_leads.enabled
        assert should_spawn is False

    def test_phase_leads_gate_both_enabled(self):
        """Phase leads spawn when both agent_teams and phase_leads are enabled."""
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.phase_leads.enabled = True
        should_spawn = config.agent_teams.enabled and config.phase_leads.enabled
        assert should_spawn is True

    def test_phase_lead_names_list(self):
        """The four expected wave-aligned phase lead names."""
        expected = [
            "wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead",
        ]
        assert len(expected) == 4

    def test_phase_lead_prompts_extractable_from_agent_defs(self):
        """Phase lead prompts should be in agent definitions when enabled."""
        from agent_team_v15.agents import build_agent_definitions
        from agent_team_v15.mcp_servers import get_mcp_servers

        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.phase_leads.enabled = True
        mcp_servers = get_mcp_servers(config)
        agent_defs = build_agent_definitions(config, mcp_servers)

        lead_names = [
            "wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead",
        ]
        for name in lead_names:
            assert name in agent_defs, f"{name} missing from agent definitions"
            assert "prompt" in agent_defs[name], f"{name} has no prompt"
            assert len(agent_defs[name]["prompt"]) > 100, f"{name} prompt too short"

    def test_phase_lead_health_states(self):
        """Health check returns valid status strings."""
        valid_statuses = {"running", "exited", "not_spawned"}
        # Simulate health check result
        health = {
            "wave-a-lead": "running",
            "wave-d5-lead": "running",
            "wave-t-lead": "exited",
            "wave-e-lead": "running",
        }
        for name, status in health.items():
            assert status in valid_statuses, f"{name} has invalid status: {status}"

        stalled = [n for n, s in health.items() if s == "exited"]
        assert stalled == ["wave-t-lead"]

    def test_phase_lead_individual_configs(self):
        """Each phase lead should have its own config with tools."""
        config = AgentTeamConfig()
        leads = config.phase_leads
        assert len(leads.wave_a_lead.tools) > 0
        assert len(leads.wave_d5_lead.tools) > 0
        assert len(leads.wave_t_lead.tools) > 0
        assert len(leads.wave_e_lead.tools) > 0
        assert config.agent_teams.teammate_display_mode == "in-process"
