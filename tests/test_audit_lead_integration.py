"""Tests for wave-e-lead integration — phase lead definition, prompt upgrades,
orchestrator prompt updates, validator script, config, and pipeline wiring.

Covers the isolated-to-team conversion:
  audit_agent.py → wave-e-lead phase lead + validator helper script
  prd_agent.py → absorbed into wave-a-lead prompt
  runtime_verification.py → absorbed into wave-t-lead prompt
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from agent_team_v15.agents import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    PLANNING_LEAD_PROMPT,
    REVIEW_LEAD_PROMPT,
    TESTING_LEAD_PROMPT,
    TEAM_ORCHESTRATOR_SYSTEM_PROMPT,
    _TEAM_COMMUNICATION_PROTOCOL,
    build_agent_definitions,
)
from agent_team_v15.config import (
    AgentConfig,
    AgentTeamConfig,
    AgentTeamsConfig,
    PhaseLeadsConfig,
)


# ===================================================================
# Helpers
# ===================================================================

def _build_team_agents() -> dict:
    """Build agent definitions with agent_teams and phase_leads enabled."""
    cfg = AgentTeamConfig()
    cfg.agent_teams = AgentTeamsConfig(enabled=True)
    cfg.phase_leads = PhaseLeadsConfig(enabled=True)
    return build_agent_definitions(cfg, mcp_servers={})


def _get_agent_prompt(name: str) -> str:
    """Get the full assembled prompt for a named agent."""
    agents = _build_team_agents()
    assert name in agents, f"Agent '{name}' not found in definitions. Available: {sorted(agents.keys())}"
    return agents[name]["prompt"]


# ===================================================================
# A. Audit-Lead Definition Tests
# ===================================================================


class TestAuditLeadDefinition:
    """Verify wave-e-lead agent definition exists and prompt has required content."""

    def test_wave_e_lead_exists_in_definitions(self):
        """wave-e-lead must be present in build_agent_definitions when teams enabled."""
        agents = _build_team_agents()
        assert "wave-e-lead" in agents, (
            f"wave-e-lead not found. Available agents: {sorted(agents.keys())}"
        )

    def test_wave_e_lead_has_description(self):
        agents = _build_team_agents()
        assert "wave-e-lead" in agents
        desc = agents["wave-e-lead"].get("description", "")
        assert len(desc) > 10, "wave-e-lead must have a meaningful description"

    def test_wave_e_lead_prompt_mentions_adversarial_review(self):
        prompt = _get_agent_prompt("wave-e-lead")
        assert "adversarial" in prompt.lower() and "review" in prompt.lower(), (
            "wave-e-lead prompt must mention adversarial review"
        )

    def test_wave_e_lead_prompt_mentions_wiring_escalation(self):
        prompt = _get_agent_prompt("wave-e-lead")
        assert "wiring escalation" in prompt.lower(), (
            "wave-e-lead prompt must mention wiring escalation"
        )

    def test_wave_e_lead_prompt_mentions_audit_complete(self):
        prompt = _get_agent_prompt("wave-e-lead")
        assert "audit" in prompt.lower() and "COMPLETE" in prompt, (
            "wave-e-lead prompt must mention audit completion (Status: COMPLETE)"
        )

    def test_wave_e_lead_prompt_mentions_fix_request(self):
        prompt = _get_agent_prompt("wave-e-lead")
        assert "fix" in prompt.lower() and "findings" in prompt.lower(), (
            "wave-e-lead prompt must mention fix cycle and findings"
        )

    def test_wave_e_lead_prompt_mentions_review_results(self):
        prompt = _get_agent_prompt("wave-e-lead")
        assert "review results" in prompt.lower(), (
            "wave-e-lead prompt must mention review results"
        )

    def test_wave_e_lead_prompt_mentions_convergence_tracking(self):
        prompt = _get_agent_prompt("wave-e-lead")
        assert "converge" in prompt.lower() or "CONVERGED" in prompt or "PLATEAU" in prompt, (
            "wave-e-lead prompt must mention convergence tracking (CONVERGED/PLATEAU)"
        )

    def test_wave_e_lead_prompt_mentions_convergence_complete(self):
        prompt = _get_agent_prompt("wave-e-lead")
        assert "COMPLETE status" in prompt, (
            "wave-e-lead prompt must mention COMPLETE status"
        )

    def test_wave_e_lead_prompt_mentions_wave_a_lead(self):
        prompt = _get_agent_prompt("wave-e-lead")
        assert "wave-a-lead" in prompt, (
            "wave-e-lead prompt must reference wave-a-lead for FIX_REQUEST routing"
        )

    def test_wave_e_lead_prompt_mentions_wave_d5_lead(self):
        prompt = _get_agent_prompt("wave-e-lead")
        assert "wave-d5-lead" in prompt, (
            "wave-e-lead prompt must reference wave-d5-lead for coordination"
        )

    def test_wave_e_lead_has_tools(self):
        agents = _build_team_agents()
        tools = agents["wave-e-lead"].get("tools", [])
        assert len(tools) > 0, "wave-e-lead must have tools assigned"
        # Should at least have Read and Bash for running validators
        assert "Read" in tools, "wave-e-lead must have Read tool"
        assert "Bash" in tools, "wave-e-lead must have Bash tool for running validators"


# ===================================================================
# B. Planning-Lead Upgrade Tests
# ===================================================================


class TestPlanningLeadUpgrade:
    """Verify wave-a-lead prompt has spec fidelity validation content."""

    def test_wave_a_lead_contains_spec_fidelity(self):
        prompt = _get_agent_prompt("wave-a-lead")
        has_spec_fidelity = "spec fidelity" in prompt.lower() or "spec validation" in prompt.lower()
        assert has_spec_fidelity, (
            "wave-a-lead prompt must contain 'spec fidelity' or 'spec validation'"
        )

    def test_wave_a_lead_mentions_comparing_against_prd(self):
        prompt = _get_agent_prompt("wave-a-lead")
        has_prd_compare = (
            "prd" in prompt.lower()
            or "original" in prompt.lower() and "request" in prompt.lower()
            or "compare" in prompt.lower()
        )
        assert has_prd_compare, (
            "wave-a-lead prompt must mention comparing against PRD or original request"
        )

    def test_wave_a_lead_requirements_ready_after_validation(self):
        prompt = _get_agent_prompt("wave-a-lead")
        assert "REQUIREMENTS.md" in prompt, (
            "wave-a-lead prompt must mention REQUIREMENTS.md"
        )
        assert "validation" in prompt.lower() or "Spec Fidelity" in prompt, (
            "wave-a-lead prompt must mention validation"
        )

    def test_wave_a_lead_not_broken_still_has_original_content(self):
        """Planning-lead prompt must still contain its original core content."""
        prompt = _get_agent_prompt("wave-a-lead")
        assert "PLANNING LEAD" in prompt, "wave-a-lead prompt must still identify as PLANNING LEAD"
        assert "REQUIREMENTS.md" in prompt, "wave-a-lead prompt must still reference REQUIREMENTS.md"
        assert "planner" in prompt.lower() or "planning" in prompt.lower(), (
            "wave-a-lead prompt must still reference its planning responsibilities"
        )


# ===================================================================
# C. Testing-Lead Upgrade Tests
# ===================================================================


class TestTestingLeadUpgrade:
    """Verify wave-t-lead prompt has runtime fix protocol content."""

    def test_wave_t_lead_contains_runtime_fix_or_fix_request(self):
        prompt = _get_agent_prompt("wave-t-lead")
        has_runtime = "runtime fix" in prompt.lower() or "FIX_REQUEST" in prompt
        assert has_runtime, (
            "wave-t-lead prompt must contain 'runtime fix' or 'FIX_REQUEST'"
        )

    def test_wave_t_lead_mentions_messaging_wave_a_lead(self):
        prompt = _get_agent_prompt("wave-t-lead")
        assert "wave-a-lead" in prompt, (
            "wave-t-lead prompt must mention messaging wave-a-lead for fixes"
        )

    def test_wave_t_lead_mentions_escalation_request(self):
        prompt = _get_agent_prompt("wave-t-lead")
        assert "escalation" in prompt.lower() or "BLOCKED" in prompt, (
            "wave-t-lead prompt must mention escalation or BLOCKED status"
        )

    def test_wave_t_lead_not_broken_still_has_original_content(self):
        """Testing-lead prompt must still contain its original core content."""
        prompt = _get_agent_prompt("wave-t-lead")
        assert "TESTING LEAD" in prompt, "wave-t-lead prompt must still identify as TESTING LEAD"
        assert "test" in prompt.lower(), "wave-t-lead prompt must still reference testing"
        assert "COMPLETE" in prompt, "wave-t-lead prompt must still have COMPLETE status"


# ===================================================================
# D. Orchestrator Prompt Tests
# ===================================================================


class TestOrchestratorPromptAuditLead:
    """Verify orchestrator prompts reference wave-e-lead."""

    def test_team_orchestrator_mentions_wave_e_lead(self):
        """TEAM_ORCHESTRATOR_SYSTEM_PROMPT or Section 15 must mention wave-e-lead."""
        combined = TEAM_ORCHESTRATOR_SYSTEM_PROMPT + ORCHESTRATOR_SYSTEM_PROMPT
        assert "wave-e-lead" in combined or "wave_e_lead" in combined, (
            "Orchestrator prompt (team or monolithic Section 15) must mention wave-e-lead"
        )

    def test_communication_protocol_has_return_format(self):
        """SDK subagent protocol must include structured return format."""
        assert "Phase Result" in _TEAM_COMMUNICATION_PROTOCOL, (
            "SDK subagent protocol must include Phase Result return format"
        )

    def test_communication_protocol_has_shared_artifacts(self):
        """SDK subagent protocol must reference shared artifacts."""
        assert "Shared Artifacts" in _TEAM_COMMUNICATION_PROTOCOL, (
            "SDK subagent protocol must include Shared Artifacts section"
        )


# ===================================================================
# E. Validator Script Tests
# ===================================================================


class TestValidatorScriptExists:
    """Verify scripts/run_validators.py exists and is importable."""

    def test_run_validators_script_exists(self):
        script_path = Path(__file__).parent.parent / "scripts" / "run_validators.py"
        assert script_path.exists(), (
            f"scripts/run_validators.py must exist at {script_path}"
        )

    def test_run_validators_valid_python_syntax(self):
        """Script must be valid Python (importable without syntax errors)."""
        script_path = Path(__file__).parent.parent / "scripts" / "run_validators.py"
        if not script_path.exists():
            pytest.skip("scripts/run_validators.py not yet created")
        source = script_path.read_text(encoding="utf-8")
        compile(source, str(script_path), "exec")

    def test_run_validators_handles_missing_project_path(self):
        """Script should handle missing project path gracefully (not crash on import)."""
        script_path = Path(__file__).parent.parent / "scripts" / "run_validators.py"
        if not script_path.exists():
            pytest.skip("scripts/run_validators.py not yet created")
        source = script_path.read_text(encoding="utf-8")
        # Script must have argparse or sys.argv handling
        has_arg_handling = (
            "argparse" in source
            or "sys.argv" in source
            or "click" in source
        )
        assert has_arg_handling, (
            "scripts/run_validators.py must handle command-line arguments"
        )

    def test_run_validators_handles_previous_flag(self):
        """Script should accept a --previous flag for regression detection."""
        script_path = Path(__file__).parent.parent / "scripts" / "run_validators.py"
        if not script_path.exists():
            pytest.skip("scripts/run_validators.py not yet created")
        source = script_path.read_text(encoding="utf-8")
        assert "--previous" in source or "previous" in source, (
            "scripts/run_validators.py must support --previous flag for regression detection"
        )


# ===================================================================
# F. Config Tests
# ===================================================================


class TestPhaseLeadsConfigAuditLead:
    """Verify PhaseLeadsConfig has wave_e_lead field."""

    def test_phase_leads_config_has_wave_e_lead_field(self):
        cfg = PhaseLeadsConfig()
        assert hasattr(cfg, "wave_e_lead"), (
            "PhaseLeadsConfig must have an 'wave_e_lead' field"
        )

    def test_wave_e_lead_defaults_to_enabled(self):
        cfg = PhaseLeadsConfig()
        wave_e_lead = getattr(cfg, "wave_e_lead", None)
        assert wave_e_lead is not None, "wave_e_lead must not be None"
        assert getattr(wave_e_lead, "enabled", None) is True, (
            "wave_e_lead must default to enabled=True"
        )

    def test_backward_compat_agent_team_config_constructor(self):
        """AgentTeamConfig() constructor must still work with new wave_e_lead field."""
        cfg = AgentTeamConfig()
        assert hasattr(cfg, "phase_leads"), "AgentTeamConfig must have phase_leads"
        assert hasattr(cfg.phase_leads, "wave_e_lead"), (
            "AgentTeamConfig().phase_leads must have wave_e_lead field"
        )


# ===================================================================
# G. Pipeline Wiring Tests
# ===================================================================


class TestPipelineWiring:
    """Verify cli.py source contains team-mode conditionals for audit-related modules."""

    @pytest.fixture(autouse=True)
    def _load_cli_source(self):
        cli_path = Path(__file__).parent.parent / "src" / "agent_team_v15" / "cli.py"
        self.cli_source = cli_path.read_text(encoding="utf-8")

    def test_cli_contains_team_mode_conditional_for_audit(self):
        """cli.py must have team-mode conditional for audit_agent usage."""
        has_audit_conditional = (
            "audit" in self.cli_source.lower()
            and ("team_mode" in self.cli_source or "_use_team_mode" in self.cli_source)
        )
        assert has_audit_conditional, (
            "cli.py must contain team-mode conditional for audit"
        )

    def test_cli_contains_team_mode_conditional_for_prd_agent(self):
        """cli.py must reference prd_agent in non-team mode."""
        assert "prd_agent" in self.cli_source, (
            "cli.py must reference prd_agent module"
        )

    def test_cli_contains_team_mode_conditional_for_runtime_verification(self):
        """cli.py must reference runtime_verification in non-team mode."""
        assert "runtime_verification" in self.cli_source, (
            "cli.py must reference runtime_verification module"
        )

    def test_non_team_mode_preserves_existing_behavior(self):
        """Non-team mode (agent_teams.enabled=False) must still produce standard agents."""
        cfg = AgentTeamConfig()
        cfg.agent_teams = AgentTeamsConfig(enabled=False)
        agents = build_agent_definitions(cfg, mcp_servers={})
        # Standard agents must still be present
        for name in ("planner", "researcher", "architect", "code-writer", "code-reviewer"):
            assert name in agents, f"Standard agent '{name}' must be present in non-team mode"
        # Phase leads should NOT be present
        for name in ("wave-a-lead", "wave-a-lead", "wave-e-lead", "wave-t-lead"):
            assert name not in agents, f"Phase lead '{name}' must NOT be present in non-team mode"
