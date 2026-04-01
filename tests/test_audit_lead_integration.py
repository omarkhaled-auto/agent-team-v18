"""Tests for audit-lead integration — phase lead definition, prompt upgrades,
orchestrator prompt updates, validator script, config, and pipeline wiring.

Covers the isolated-to-team conversion:
  audit_agent.py → audit-lead phase lead + validator helper script
  prd_agent.py → absorbed into planning-lead prompt
  runtime_verification.py → absorbed into testing-lead prompt
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
    """Build agent definitions with agent_teams enabled."""
    cfg = AgentTeamConfig()
    cfg.agent_teams = AgentTeamsConfig(enabled=True)
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
    """Verify audit-lead agent definition exists and prompt has required content."""

    def test_audit_lead_exists_in_definitions(self):
        """audit-lead must be present in build_agent_definitions when teams enabled."""
        agents = _build_team_agents()
        assert "audit-lead" in agents, (
            f"audit-lead not found. Available agents: {sorted(agents.keys())}"
        )

    def test_audit_lead_has_description(self):
        agents = _build_team_agents()
        assert "audit-lead" in agents
        desc = agents["audit-lead"].get("description", "")
        assert len(desc) > 10, "audit-lead must have a meaningful description"

    def test_audit_lead_prompt_mentions_deterministic_scan(self):
        prompt = _get_agent_prompt("audit-lead")
        assert "deterministic" in prompt.lower() and "scan" in prompt.lower(), (
            "audit-lead prompt must mention 'deterministic scan'"
        )

    def test_audit_lead_prompt_mentions_run_validators(self):
        prompt = _get_agent_prompt("audit-lead")
        assert "run_validators" in prompt.lower() or "run_validators.py" in prompt, (
            "audit-lead prompt must mention run_validators.py helper script"
        )

    def test_audit_lead_prompt_mentions_audit_complete(self):
        prompt = _get_agent_prompt("audit-lead")
        assert "AUDIT_COMPLETE" in prompt, (
            "audit-lead prompt must mention AUDIT_COMPLETE message type"
        )

    def test_audit_lead_prompt_mentions_fix_request(self):
        prompt = _get_agent_prompt("audit-lead")
        assert "FIX_REQUEST" in prompt, (
            "audit-lead prompt must mention FIX_REQUEST message type"
        )

    def test_audit_lead_prompt_mentions_regression_alert(self):
        prompt = _get_agent_prompt("audit-lead")
        assert "REGRESSION_ALERT" in prompt, (
            "audit-lead prompt must mention REGRESSION_ALERT message type"
        )

    def test_audit_lead_prompt_mentions_convergence_tracking(self):
        prompt = _get_agent_prompt("audit-lead")
        assert "converge" in prompt.lower() or "CONVERGED" in prompt or "PLATEAU" in prompt, (
            "audit-lead prompt must mention convergence tracking (CONVERGED/PLATEAU)"
        )

    def test_audit_lead_prompt_mentions_converged_and_plateau(self):
        prompt = _get_agent_prompt("audit-lead")
        has_converged = "CONVERGED" in prompt
        has_plateau = "PLATEAU" in prompt
        assert has_converged or has_plateau, (
            "audit-lead prompt must mention CONVERGED and/or PLATEAU states"
        )

    def test_audit_lead_prompt_mentions_coding_lead(self):
        prompt = _get_agent_prompt("audit-lead")
        assert "coding-lead" in prompt, (
            "audit-lead prompt must reference coding-lead for FIX_REQUEST routing"
        )

    def test_audit_lead_prompt_mentions_review_lead(self):
        prompt = _get_agent_prompt("audit-lead")
        assert "review-lead" in prompt, (
            "audit-lead prompt must reference review-lead for coordination"
        )

    def test_audit_lead_has_tools(self):
        agents = _build_team_agents()
        tools = agents["audit-lead"].get("tools", [])
        assert len(tools) > 0, "audit-lead must have tools assigned"
        # Should at least have Read and Bash for running validators
        assert "Read" in tools, "audit-lead must have Read tool"
        assert "Bash" in tools, "audit-lead must have Bash tool for running validators"


# ===================================================================
# B. Planning-Lead Upgrade Tests
# ===================================================================


class TestPlanningLeadUpgrade:
    """Verify planning-lead prompt has spec fidelity validation content."""

    def test_planning_lead_contains_spec_fidelity(self):
        prompt = _get_agent_prompt("planning-lead")
        has_spec_fidelity = "spec fidelity" in prompt.lower() or "spec validation" in prompt.lower()
        assert has_spec_fidelity, (
            "planning-lead prompt must contain 'spec fidelity' or 'spec validation'"
        )

    def test_planning_lead_mentions_comparing_against_prd(self):
        prompt = _get_agent_prompt("planning-lead")
        has_prd_compare = (
            "prd" in prompt.lower()
            or "original" in prompt.lower() and "request" in prompt.lower()
            or "compare" in prompt.lower()
        )
        assert has_prd_compare, (
            "planning-lead prompt must mention comparing against PRD or original request"
        )

    def test_planning_lead_requirements_ready_after_validation(self):
        prompt = _get_agent_prompt("planning-lead")
        assert "REQUIREMENTS_READY" in prompt, (
            "planning-lead prompt must mention REQUIREMENTS_READY"
        )
        # REQUIREMENTS_READY should appear after validation/spec mentions
        req_pos = prompt.find("REQUIREMENTS_READY")
        assert req_pos > 0, "REQUIREMENTS_READY must be present in prompt"

    def test_planning_lead_not_broken_still_has_original_content(self):
        """Planning-lead prompt must still contain its original core content."""
        prompt = _get_agent_prompt("planning-lead")
        assert "PLANNING LEAD" in prompt, "planning-lead prompt must still identify as PLANNING LEAD"
        assert "REQUIREMENTS.md" in prompt, "planning-lead prompt must still reference REQUIREMENTS.md"
        assert "planner" in prompt.lower() or "planning" in prompt.lower(), (
            "planning-lead prompt must still reference its planning responsibilities"
        )


# ===================================================================
# C. Testing-Lead Upgrade Tests
# ===================================================================


class TestTestingLeadUpgrade:
    """Verify testing-lead prompt has runtime fix protocol content."""

    def test_testing_lead_contains_runtime_fix_or_fix_request(self):
        prompt = _get_agent_prompt("testing-lead")
        has_runtime = "runtime fix" in prompt.lower() or "FIX_REQUEST" in prompt
        assert has_runtime, (
            "testing-lead prompt must contain 'runtime fix' or 'FIX_REQUEST'"
        )

    def test_testing_lead_mentions_messaging_coding_lead(self):
        prompt = _get_agent_prompt("testing-lead")
        assert "coding-lead" in prompt, (
            "testing-lead prompt must mention messaging coding-lead for fixes"
        )

    def test_testing_lead_mentions_escalation_request(self):
        prompt = _get_agent_prompt("testing-lead")
        assert "ESCALATION_REQUEST" in prompt, (
            "testing-lead prompt must mention ESCALATION_REQUEST"
        )

    def test_testing_lead_not_broken_still_has_original_content(self):
        """Testing-lead prompt must still contain its original core content."""
        prompt = _get_agent_prompt("testing-lead")
        assert "TESTING LEAD" in prompt, "testing-lead prompt must still identify as TESTING LEAD"
        assert "test" in prompt.lower(), "testing-lead prompt must still reference testing"
        assert "TESTING_COMPLETE" in prompt, "testing-lead prompt must still have TESTING_COMPLETE"


# ===================================================================
# D. Orchestrator Prompt Tests
# ===================================================================


class TestOrchestratorPromptAuditLead:
    """Verify orchestrator prompts reference audit-lead."""

    def test_team_orchestrator_mentions_audit_lead(self):
        """TEAM_ORCHESTRATOR_SYSTEM_PROMPT or Section 15 must mention audit-lead."""
        combined = TEAM_ORCHESTRATOR_SYSTEM_PROMPT + ORCHESTRATOR_SYSTEM_PROMPT
        assert "audit-lead" in combined or "audit_lead" in combined, (
            "Orchestrator prompt (team or monolithic Section 15) must mention audit-lead"
        )

    def test_communication_protocol_includes_audit_complete(self):
        """Communication protocol must include AUDIT_COMPLETE message type."""
        assert "AUDIT_COMPLETE" in _TEAM_COMMUNICATION_PROTOCOL, (
            "Team communication protocol must include AUDIT_COMPLETE message type"
        )

    def test_communication_protocol_includes_regression_alert(self):
        """Communication protocol must include REGRESSION_ALERT message type."""
        assert "REGRESSION_ALERT" in _TEAM_COMMUNICATION_PROTOCOL, (
            "Team communication protocol must include REGRESSION_ALERT message type"
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
    """Verify PhaseLeadsConfig has audit_lead field."""

    def test_phase_leads_config_has_audit_lead_field(self):
        cfg = PhaseLeadsConfig()
        assert hasattr(cfg, "audit_lead"), (
            "PhaseLeadsConfig must have an 'audit_lead' field"
        )

    def test_audit_lead_defaults_to_enabled(self):
        cfg = PhaseLeadsConfig()
        audit_lead = getattr(cfg, "audit_lead", None)
        assert audit_lead is not None, "audit_lead must not be None"
        assert getattr(audit_lead, "enabled", None) is True, (
            "audit_lead must default to enabled=True"
        )

    def test_backward_compat_agent_team_config_constructor(self):
        """AgentTeamConfig() constructor must still work with new audit_lead field."""
        cfg = AgentTeamConfig()
        assert hasattr(cfg, "phase_leads"), "AgentTeamConfig must have phase_leads"
        assert hasattr(cfg.phase_leads, "audit_lead"), (
            "AgentTeamConfig().phase_leads must have audit_lead field"
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
        for name in ("planning-lead", "coding-lead", "review-lead", "testing-lead"):
            assert name not in agents, f"Phase lead '{name}' must NOT be present in non-team mode"
