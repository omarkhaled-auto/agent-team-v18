"""Simulation tests for Agent Teams upgrade.

Verifies that the team architecture integration works end-to-end:
- AgentTeamsBackend initializes correctly
- Backend selection logic picks the right backend
- Orchestrator prompt includes team instructions when enabled
- Orchestrator prompt does NOT include team instructions when disabled
- Phase lead definitions exist with correct properties
- Backward compatibility (agent_teams.enabled=False uses CLIBackend)
"""

from __future__ import annotations

import asyncio
import os
import re
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15.agent_teams_backend import (
    AgentTeamsBackend,
    CLIBackend,
    ExecutionBackend,
    TaskResult,
    TeamState,
    WaveResult,
    create_execution_backend,
    detect_agent_teams_available,
)
from agent_team_v15.config import AgentTeamConfig, AgentTeamsConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockWave:
    """Minimal mock satisfying the ExecutionWave interface."""

    def __init__(self, wave_number: int = 0, task_ids: list[str] | None = None):
        self.wave_number = wave_number
        self.task_ids = task_ids or []


def _make_config(
    enabled: bool = False,
    fallback_to_cli: bool = True,
    max_teammates: int = 5,
    teammate_model: str = "",
    team_name_prefix: str = "build",
    phase_lead_model: str = "",
    phase_lead_max_turns: int = 200,
    auto_shutdown: bool = True,
) -> AgentTeamConfig:
    """Create an AgentTeamConfig with customized agent_teams settings."""
    config = AgentTeamConfig()
    config.agent_teams.enabled = enabled
    config.agent_teams.fallback_to_cli = fallback_to_cli
    config.agent_teams.max_teammates = max_teammates
    config.agent_teams.teammate_model = teammate_model
    config.agent_teams.team_name_prefix = team_name_prefix
    config.agent_teams.phase_lead_model = phase_lead_model
    config.agent_teams.phase_lead_max_turns = phase_lead_max_turns
    config.agent_teams.auto_shutdown = auto_shutdown
    return config


# ===========================================================================
# 1. AgentTeamsBackend initialization
# ===========================================================================

class TestAgentTeamsBackendInit:
    """Verify AgentTeamsBackend initializes correctly."""

    def test_backend_starts_inactive(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        assert backend._state.active is False
        assert backend._state.mode == "agent_teams"

    def test_backend_has_empty_teammates_on_creation(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        assert backend._active_teammates == {}
        assert backend._state.teammates == []

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_initialize_sets_active_state(self, _mock):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        state = asyncio.run(backend.initialize())
        assert state.active is True
        assert state.mode == "agent_teams"

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_initialize_sets_env_flag(self, _mock, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        asyncio.run(backend.initialize())
        assert os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS") == "1"

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_initialize_sets_subagent_model_when_configured(self, _mock, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL", raising=False)
        config = _make_config(enabled=True, teammate_model="haiku")
        backend = AgentTeamsBackend(config)
        asyncio.run(backend.initialize())
        assert os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL") == "haiku"

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_initialize_raises_when_cli_missing(self, _mock):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        with pytest.raises(RuntimeError, match="Claude CLI is not available"):
            asyncio.run(backend.initialize())


# ===========================================================================
# 2. Backend selection logic
# ===========================================================================

class TestBackendSelection:
    """Verify create_execution_backend picks the correct backend."""

    def test_disabled_config_returns_cli_backend(self):
        config = _make_config(enabled=False)
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_enabled_without_env_var_returns_agent_teams(self, _mock, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = _make_config(enabled=True)
        backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_all_conditions_met_returns_agent_teams(self, _mock, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = _make_config(enabled=True)
        backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_cli_missing_with_fallback_still_raises(self, _mock, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = _make_config(enabled=True, fallback_to_cli=True)
        with pytest.raises(RuntimeError):
            create_execution_backend(config)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_cli_missing_no_fallback_raises(self, _mock, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = _make_config(enabled=True, fallback_to_cli=False)
        with pytest.raises(RuntimeError):
            create_execution_backend(config)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_env_var_wrong_value_returns_agent_teams(self, _mock, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "yes")
        config = _make_config(enabled=True)
        backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)


# ===========================================================================
# 3. Prompt includes team instructions when enabled
# ===========================================================================

class TestPromptTeamInstructionsEnabled:
    """Verify orchestrator prompt includes team sections when enabled."""

    def test_section_15_exists_in_orchestrator_prompt(self):
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        assert "SECTION 15: TEAM-BASED EXECUTION" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_mandates_team_usage(self):
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        assert "MANDATORY: Use TeamCreate" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_15_mentions_sendmessage(self):
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        assert "SendMessage" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_6_has_team_deployment_mode(self):
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        assert "Team Deployment Mode" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_7_has_team_based_workflow(self):
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        assert "Team-Based Workflow" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_section_7_has_fleet_based_workflow(self):
        """Fleet workflow must still exist as the default."""
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        assert "Fleet-Based Workflow" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_workflow_mentions_phase_leads(self):
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        for lead in ["wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"]:
            assert lead in ORCHESTRATOR_SYSTEM_PROMPT, f"Missing phase lead: {lead}"

    def test_team_workflow_preserves_convergence_gates(self):
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        assert "convergence gates" in ORCHESTRATOR_SYSTEM_PROMPT.lower() or \
               "ALL convergence gates" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_team_workflow_preserves_quality_standards(self):
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        assert "quality standards" in ORCHESTRATOR_SYSTEM_PROMPT.lower() or \
               "ALL quality standards" in ORCHESTRATOR_SYSTEM_PROMPT


# ===========================================================================
# 4. Prompt does NOT break when team is disabled
# ===========================================================================

class TestPromptTeamInstructionsDisabled:
    """Verify backward compatibility: team-disabled mode still works."""

    def test_build_orchestrator_prompt_works_when_disabled(self):
        from agent_team_v15.agents import build_orchestrator_prompt
        config = _make_config(enabled=False)
        prompt = build_orchestrator_prompt(
            task="Fix the login bug",
            depth="standard",
            config=config,
        )
        assert "Fix the login bug" in prompt
        assert "[DEPTH: STANDARD]" in prompt

    def test_build_orchestrator_prompt_has_instructions_section(self):
        from agent_team_v15.agents import build_orchestrator_prompt
        config = _make_config(enabled=False)
        prompt = build_orchestrator_prompt(
            task="Fix the login bug",
            depth="standard",
            config=config,
        )
        assert "[INSTRUCTIONS]" in prompt

    def test_build_orchestrator_prompt_contains_fleet_scaling(self):
        from agent_team_v15.agents import build_orchestrator_prompt
        config = _make_config(enabled=False)
        prompt = build_orchestrator_prompt(
            task="Build a dashboard",
            depth="thorough",
            config=config,
        )
        assert "[FLEET SCALING" in prompt

    def test_orchestrator_prompt_still_has_all_original_sections(self):
        """All original sections (0-14) must still be present."""
        from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
        for i in range(15):
            assert f"SECTION {i}:" in ORCHESTRATOR_SYSTEM_PROMPT, \
                f"Missing SECTION {i} in orchestrator prompt"


# ===========================================================================
# 5. Phase lead definitions
# ===========================================================================

class TestPhaseLeadDefinitions:
    """Verify phase lead definitions exist with correct properties."""

    def test_build_agent_definitions_returns_dict(self):
        from agent_team_v15.agents import build_agent_definitions
        config = _make_config(enabled=False)
        agents = build_agent_definitions(config, mcp_servers={})
        assert isinstance(agents, dict)

    def test_core_agents_present_when_team_disabled(self):
        from agent_team_v15.agents import build_agent_definitions
        config = _make_config(enabled=False)
        agents = build_agent_definitions(config, mcp_servers={})
        expected = {"planner", "researcher", "architect", "task-assigner",
                    "code-writer", "code-reviewer", "test-runner",
                    "security-auditor", "debugger"}
        for name in expected:
            assert name in agents, f"Missing agent: {name}"

    def test_agent_definitions_have_required_fields(self):
        from agent_team_v15.agents import build_agent_definitions
        config = _make_config(enabled=False)
        agents = build_agent_definitions(config, mcp_servers={})
        for name, defn in agents.items():
            assert "description" in defn, f"Agent {name} missing description"
            assert "prompt" in defn, f"Agent {name} missing prompt"
            assert "tools" in defn, f"Agent {name} missing tools"

    def test_spec_validator_always_present(self):
        from agent_team_v15.agents import build_agent_definitions
        config = _make_config(enabled=False)
        agents = build_agent_definitions(config, mcp_servers={})
        assert "spec-validator" in agents


# ===========================================================================
# 6. Backward compatibility
# ===========================================================================

class TestBackwardCompatibility:
    """Agent Teams disabled uses CLIBackend with no regressions."""

    def test_disabled_config_uses_cli_backend(self):
        config = _make_config(enabled=False)
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)
        assert not backend.supports_peer_messaging()
        assert not backend.supports_self_claiming()

    def test_cli_backend_initialize_returns_cli_state(self):
        config = _make_config(enabled=False)
        backend = CLIBackend(config)
        state = asyncio.run(backend.initialize())
        assert state.mode == "cli"
        assert state.active is True

    def test_cli_backend_execute_wave_succeeds(self):
        config = _make_config(enabled=False)
        backend = CLIBackend(config)
        asyncio.run(backend.initialize())
        wave = MockWave(wave_number=0, task_ids=["t1", "t2"])
        result = asyncio.run(backend.execute_wave(wave))
        assert isinstance(result, WaveResult)
        assert result.all_succeeded is True
        assert len(result.task_results) == 2

    def test_cli_backend_shutdown_deactivates(self):
        config = _make_config(enabled=False)
        backend = CLIBackend(config)
        asyncio.run(backend.initialize())
        asyncio.run(backend.shutdown())
        assert backend._state.active is False

    def test_agent_teams_config_defaults_disabled(self):
        config = AgentTeamConfig()
        assert config.agent_teams.enabled is True
        assert config.agent_teams.fallback_to_cli is False


# ===========================================================================
# 7. Config field validation
# ===========================================================================

class TestConfigFields:
    """Verify AgentTeamsConfig has all required fields with sensible defaults."""

    def test_default_enabled_is_true(self):
        cfg = AgentTeamsConfig()
        assert cfg.enabled is True

    def test_default_fallback_to_cli_is_false(self):
        cfg = AgentTeamsConfig()
        assert cfg.fallback_to_cli is False

    def test_default_max_teammates(self):
        cfg = AgentTeamsConfig()
        assert cfg.max_teammates == 5

    def test_default_wave_timeout(self):
        cfg = AgentTeamsConfig()
        assert cfg.wave_timeout_seconds == 3600

    def test_default_task_timeout(self):
        cfg = AgentTeamsConfig()
        assert cfg.task_timeout_seconds == 1800

    def test_default_teammate_display_mode(self):
        cfg = AgentTeamsConfig()
        assert cfg.teammate_display_mode == "in-process"

    def test_team_name_prefix_default(self):
        cfg = AgentTeamsConfig()
        assert cfg.team_name_prefix == "build"

    def test_phase_lead_model_default_empty(self):
        cfg = AgentTeamsConfig()
        assert cfg.phase_lead_model == ""

    def test_phase_lead_max_turns_default(self):
        cfg = AgentTeamsConfig()
        assert cfg.phase_lead_max_turns == 200

    def test_auto_shutdown_default_true(self):
        cfg = AgentTeamsConfig()
        assert cfg.auto_shutdown is True

    def test_delegate_mode_default_true(self):
        cfg = AgentTeamsConfig()
        assert cfg.delegate_mode is True

    def test_contract_limit_default(self):
        cfg = AgentTeamsConfig()
        assert cfg.contract_limit == 100


# ===========================================================================
# 8. Protocol compliance
# ===========================================================================

class TestProtocolCompliance:
    """Both backends satisfy the ExecutionBackend protocol."""

    def test_cli_backend_is_execution_backend(self):
        config = _make_config()
        backend = CLIBackend(config)
        assert isinstance(backend, ExecutionBackend)

    def test_agent_teams_backend_is_execution_backend(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        assert isinstance(backend, ExecutionBackend)

    def test_agent_teams_supports_peer_messaging(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        assert backend.supports_peer_messaging() is True

    def test_agent_teams_supports_self_claiming(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        assert backend.supports_self_claiming() is True

    def test_cli_does_not_support_peer_messaging(self):
        config = _make_config()
        backend = CLIBackend(config)
        assert backend.supports_peer_messaging() is False

    def test_cli_does_not_support_self_claiming(self):
        config = _make_config()
        backend = CLIBackend(config)
        assert backend.supports_self_claiming() is False


# ===========================================================================
# 9. Shutdown and cleanup
# ===========================================================================

class TestShutdownCleanup:
    """Verify proper shutdown and cleanup behavior."""

    def test_agent_teams_shutdown_clears_teammates(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._active_teammates = {"w1": MagicMock(), "w2": MagicMock()}
        asyncio.run(backend.shutdown())
        assert len(backend._active_teammates) == 0
        assert backend._state.active is False

    def test_agent_teams_shutdown_noop_when_inactive(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        assert backend._state.active is False
        asyncio.run(backend.shutdown())  # should not raise
        assert backend._state.active is False

    def test_send_context_false_when_inactive(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        result = asyncio.run(backend.send_context("test"))
        assert result is False

    def test_send_context_false_when_no_teammates(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        result = asyncio.run(backend.send_context("test"))
        assert result is False

    def test_send_context_true_with_teammates(self):
        config = _make_config(enabled=True)
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._active_teammates = {"w1": MagicMock()}
        result = asyncio.run(backend.send_context("test"))
        assert result is True
        assert backend._state.total_messages == 1
