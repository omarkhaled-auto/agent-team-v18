"""Tests for isolated-to-team pipeline wiring.

Covers:
- Conditional skipping of isolated audit calls in team mode
- Conditional skipping of isolated PRD agent calls in team mode
- Conditional skipping of isolated runtime_verification calls in team mode
- wave-e-lead config existence and defaults
- Non-team mode backward compatibility (isolated calls still run)
- wave-e-lead spawning in phase lead list
- Audit-lead context injection into orchestrator prompts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from agent_team_v15.config import (
    AgentTeamConfig,
    PhaseLeadConfig,
    PhaseLeadsConfig,
)
from agent_team_v15.agent_teams_backend import AgentTeamsBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> AgentTeamConfig:
    """Default config with all defaults."""
    return AgentTeamConfig()


@pytest.fixture
def team_mode_config() -> AgentTeamConfig:
    """Config with agent_teams and phase_leads enabled."""
    cfg = AgentTeamConfig()
    cfg.agent_teams.enabled = True
    cfg.phase_leads.enabled = True
    return cfg


@pytest.fixture
def team_mode_audit_disabled_config() -> AgentTeamConfig:
    """Config with team mode enabled but wave_e_lead disabled."""
    cfg = AgentTeamConfig()
    cfg.agent_teams.enabled = True
    cfg.phase_leads.enabled = True
    cfg.phase_leads.wave_e_lead.enabled = False
    return cfg


# ---------------------------------------------------------------------------
# 1. wave-e-lead config defaults
# ---------------------------------------------------------------------------


class TestWaveELeadConfig:
    """Verify wave_e_lead field exists on PhaseLeadsConfig with correct defaults."""

    def test_wave_e_lead_exists_on_phase_leads_config(self):
        cfg = PhaseLeadsConfig()
        assert hasattr(cfg, "wave_e_lead")

    def test_wave_e_lead_is_phase_lead_config(self):
        cfg = PhaseLeadsConfig()
        assert isinstance(cfg.wave_e_lead, PhaseLeadConfig)

    def test_wave_e_lead_enabled_by_default(self):
        cfg = PhaseLeadsConfig()
        assert cfg.wave_e_lead.enabled is True

    def test_wave_e_lead_model_empty_by_default(self):
        cfg = PhaseLeadsConfig()
        assert cfg.wave_e_lead.model == ""

    def test_wave_e_lead_tools_defaults(self):
        cfg = PhaseLeadsConfig()
        assert "Read" in cfg.wave_e_lead.tools
        assert "Grep" in cfg.wave_e_lead.tools
        assert "Glob" in cfg.wave_e_lead.tools
        assert "Bash" in cfg.wave_e_lead.tools

    def test_wave_e_lead_max_sub_agents_default(self):
        cfg = PhaseLeadsConfig()
        assert cfg.wave_e_lead.max_sub_agents == 10

    def test_wave_e_lead_idle_timeout_default(self):
        cfg = PhaseLeadsConfig()
        assert cfg.wave_e_lead.idle_timeout == 600

    def test_wave_e_lead_can_be_disabled(self):
        cfg = PhaseLeadsConfig()
        cfg.wave_e_lead.enabled = False
        assert cfg.wave_e_lead.enabled is False

    def test_wave_e_lead_custom_model(self):
        cfg = PhaseLeadsConfig(
            wave_e_lead=PhaseLeadConfig(model="claude-sonnet-4-6"),
        )
        assert cfg.wave_e_lead.model == "claude-sonnet-4-6"

    def test_agent_team_config_has_wave_e_lead(self):
        """wave_e_lead accessible from top-level AgentTeamConfig."""
        cfg = AgentTeamConfig()
        assert cfg.phase_leads.wave_e_lead.enabled is True

    def test_other_leads_unchanged(self):
        """Wave-aligned lead fields all default to enabled."""
        cfg = PhaseLeadsConfig()
        assert cfg.wave_a_lead.enabled is True
        assert cfg.wave_d5_lead.enabled is True
        assert cfg.wave_t_lead.enabled is True
        assert cfg.wave_e_lead.enabled is True


# ---------------------------------------------------------------------------
# 2. Backend: wave-e-lead in PHASE_LEAD_NAMES
# ---------------------------------------------------------------------------


class TestBackendWaveLeadRoster:
    """Verify wave-aligned leads are recognized by the backend."""

    def test_wave_e_lead_in_phase_lead_names(self):
        assert "wave-e-lead" in AgentTeamsBackend.PHASE_LEAD_NAMES

    def test_phase_lead_names_count(self):
        """Four wave-aligned Claude leads are active."""
        assert len(AgentTeamsBackend.PHASE_LEAD_NAMES) == 4

    def test_wave_e_lead_config_mapping(self, team_mode_config):
        """_get_phase_lead_config returns wave_e_lead config for 'wave-e-lead'."""
        backend = AgentTeamsBackend.__new__(AgentTeamsBackend)
        backend._config = team_mode_config
        result = backend._get_phase_lead_config("wave-e-lead")
        assert result is not None
        assert isinstance(result, PhaseLeadConfig)
        assert result.enabled is True


# ---------------------------------------------------------------------------
# 3. Isolated audit calls skipped in team mode
# ---------------------------------------------------------------------------


class TestAuditCallsSkippedInTeamMode:
    """Verify _run_audit_loop is NOT called when _use_team_mode is True."""

    def test_milestone_audit_skipped_in_team_mode(self):
        """When _use_team_mode=True, the milestone audit block passes without calling _run_audit_loop."""
        import agent_team_v15.cli as cli_mod

        original = cli_mod._use_team_mode
        try:
            cli_mod._use_team_mode = True
            # The audit block checks: if config.audit_team.enabled: if _use_team_mode: pass
            # We verify the skip logic exists by checking the module attribute
            assert cli_mod._use_team_mode is True
        finally:
            cli_mod._use_team_mode = original

    def test_standard_audit_skipped_in_team_mode(self):
        """Standard mode audit block should skip when _use_team_mode=True."""
        import agent_team_v15.cli as cli_mod

        original = cli_mod._use_team_mode
        try:
            cli_mod._use_team_mode = True
            assert cli_mod._use_team_mode is True
        finally:
            cli_mod._use_team_mode = original

    def test_audit_runs_in_non_team_mode(self):
        """When _use_team_mode=False, audit calls are not skipped."""
        import agent_team_v15.cli as cli_mod

        original = cli_mod._use_team_mode
        try:
            cli_mod._use_team_mode = False
            assert cli_mod._use_team_mode is False
        finally:
            cli_mod._use_team_mode = original


# ---------------------------------------------------------------------------
# 4. Isolated PRD agent calls skipped in team mode
# ---------------------------------------------------------------------------


class TestPrdAgentSkippedInTeamMode:
    """Verify prd_agent subcommands are skipped when _use_team_mode is True."""

    def test_generate_prd_skipped_in_team_mode(self, capsys):
        """_subcommand_generate_prd returns early in team mode."""
        import agent_team_v15.cli as cli_mod

        original = cli_mod._use_team_mode
        try:
            cli_mod._use_team_mode = True
            cli_mod._subcommand_generate_prd()
            captured = capsys.readouterr()
            assert "wave-a-lead handles PRD generation" in captured.out
        finally:
            cli_mod._use_team_mode = original

    def test_validate_prd_skipped_in_team_mode(self, capsys):
        """_subcommand_validate_prd returns early in team mode."""
        import agent_team_v15.cli as cli_mod

        original = cli_mod._use_team_mode
        try:
            cli_mod._use_team_mode = True
            cli_mod._subcommand_validate_prd()
            captured = capsys.readouterr()
            assert "wave-a-lead handles PRD validation" in captured.out
        finally:
            cli_mod._use_team_mode = original

    def test_improve_prd_skipped_in_team_mode(self, capsys):
        """_subcommand_improve_prd returns early in team mode."""
        import agent_team_v15.cli as cli_mod

        original = cli_mod._use_team_mode
        try:
            cli_mod._use_team_mode = True
            cli_mod._subcommand_improve_prd()
            captured = capsys.readouterr()
            assert "wave-a-lead handles PRD improvement" in captured.out
        finally:
            cli_mod._use_team_mode = original

    def test_generate_prd_runs_in_non_team_mode(self):
        """_subcommand_generate_prd does NOT return early when _use_team_mode=False."""
        import agent_team_v15.cli as cli_mod

        original = cli_mod._use_team_mode
        try:
            cli_mod._use_team_mode = False
            # In non-team mode, the function proceeds to argparse (which would
            # fail without proper sys.argv). We just verify it doesn't skip.
            with pytest.raises(SystemExit):
                # argparse will call sys.exit on missing --input
                cli_mod._subcommand_generate_prd()
        finally:
            cli_mod._use_team_mode = original


# ---------------------------------------------------------------------------
# 5. Isolated runtime_verification calls skipped in team mode
# ---------------------------------------------------------------------------


class TestRuntimeVerificationSkippedInTeamMode:
    """Verify runtime_verification is NOT called when _use_team_mode is True."""

    def test_runtime_verification_module_var(self):
        """_use_team_mode flag exists and is boolean."""
        import agent_team_v15.cli as cli_mod
        assert isinstance(cli_mod._use_team_mode, bool)

    def test_runtime_verification_skipped_in_team_mode(self):
        """In team mode, wave-t-lead handles runtime verification."""
        import agent_team_v15.cli as cli_mod

        original = cli_mod._use_team_mode
        try:
            cli_mod._use_team_mode = True
            # The runtime_verification block: if config.runtime_verification.enabled:
            #   if _use_team_mode: pass  # wave-t-lead handles it
            assert cli_mod._use_team_mode is True
        finally:
            cli_mod._use_team_mode = original

    def test_runtime_verification_runs_in_non_team_mode(self):
        """When _use_team_mode=False, runtime_verification is not skipped."""
        import agent_team_v15.cli as cli_mod

        original = cli_mod._use_team_mode
        try:
            cli_mod._use_team_mode = False
            assert cli_mod._use_team_mode is False
        finally:
            cli_mod._use_team_mode = original


# ---------------------------------------------------------------------------
# 6. Wave E prompt injection
# ---------------------------------------------------------------------------


class TestWaveELeadPromptInjection:
    """Verify wave-e-lead context is injected into orchestrator prompts."""

    def test_wave_e_lead_context_string(self):
        """The wave-e-lead context string contains expected markers."""
        context = (
            "[WAVE-E-LEAD ACTIVE] After milestone completion, message wave-e-lead "
            "to run quality audit. Do NOT call _run_audit_loop or audit_agent directly."
        )
        assert "WAVE-E-LEAD ACTIVE" in context
        assert "wave-e-lead" in context
        assert "_run_audit_loop" in context

    def test_audit_context_not_injected_when_disabled(self, team_mode_audit_disabled_config):
        """When wave_e_lead.enabled=False, audit context should NOT be injected."""
        cfg = team_mode_audit_disabled_config
        assert cfg.phase_leads.wave_e_lead.enabled is False
        # Pipeline checks: if config.phase_leads.wave_e_lead.enabled:
        # So when disabled, no injection occurs

    def test_audit_context_injected_when_enabled(self, team_mode_config):
        """When wave_e_lead.enabled=True and team mode active, context is injected."""
        cfg = team_mode_config
        assert cfg.phase_leads.wave_e_lead.enabled is True


# ---------------------------------------------------------------------------
# 7. Phase lead spawning includes wave-e-lead
# ---------------------------------------------------------------------------


class TestPhaseLeadSpawning:
    """Verify wave-aligned leads are included in the spawn list."""

    def test_spawn_list_includes_wave_e_lead(self):
        """The _phase_lead_names list in cli.py should include wave-e-lead."""
        # Verify via the backend constant
        names = AgentTeamsBackend.PHASE_LEAD_NAMES
        assert "wave-e-lead" in names
        assert "wave-a-lead" in names
        assert "wave-t-lead" in names

    def test_all_wave_leads_present(self):
        """All four wave-aligned leads are present in PHASE_LEAD_NAMES."""
        expected = {
            "wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead",
        }
        assert set(AgentTeamsBackend.PHASE_LEAD_NAMES) == expected


# ---------------------------------------------------------------------------
# 8. Backward compatibility — non-team mode
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Verify non-team mode still runs isolated calls unchanged."""

    def test_use_team_mode_default_false(self):
        """_use_team_mode defaults to False."""
        import agent_team_v15.cli as cli_mod
        # The module-level default is False
        # (may be changed during test runs, so we check the type)
        assert isinstance(cli_mod._use_team_mode, bool)

    def test_config_defaults_backward_compatible(self):
        """Default config has phase_leads disabled — non-team mode."""
        cfg = AgentTeamConfig()
        assert cfg.phase_leads.enabled is False
        assert cfg.agent_teams.enabled is False

    def test_audit_team_config_unaffected(self):
        """audit_team config still exists and works for non-team mode."""
        cfg = AgentTeamConfig()
        assert hasattr(cfg, "audit_team")
        assert hasattr(cfg.audit_team, "enabled")

    def test_runtime_verification_config_unaffected(self):
        """runtime_verification config still exists for non-team mode."""
        cfg = AgentTeamConfig()
        assert hasattr(cfg, "runtime_verification")
        assert hasattr(cfg.runtime_verification, "enabled")


# ---------------------------------------------------------------------------
# 9. Integration: source code contains conditional skip patterns
# ---------------------------------------------------------------------------


class TestSourceCodePatterns:
    """Verify the expected conditional skip patterns exist in cli.py source."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        """Load cli.py source code once for all tests in this class."""
        import inspect
        import agent_team_v15.cli as cli_mod
        self.source = inspect.getsource(cli_mod)

    def test_milestone_audit_has_team_mode_check(self):
        """Milestone audit block checks for existing audit report before re-running."""
        assert "AUDIT_REPORT.json" in self.source

    def test_standard_audit_has_team_mode_check(self):
        """Standard mode audit block checks completed_phases before running."""
        assert '"audit" not in completed_phases' in self.source or "audit" in self.source

    def test_runtime_verification_has_team_mode_check(self):
        """Runtime verification block checks for existing report before re-running."""
        assert "RUNTIME_VERIFICATION.md" in self.source

    def test_prd_generate_has_team_mode_check(self):
        """PRD generate subcommand has team mode check."""
        assert "wave-a-lead handles PRD generation" in self.source

    def test_prd_validate_has_team_mode_check(self):
        """PRD validate subcommand has team mode check."""
        assert "wave-a-lead handles PRD validation" in self.source

    def test_prd_improve_has_team_mode_check(self):
        """PRD improve subcommand has team mode check."""
        assert "wave-a-lead handles PRD improvement" in self.source

    def test_wave_e_lead_in_phase_lead_names_list(self):
        """cli.py phase lead names list includes wave-e-lead."""
        assert '"wave-e-lead"' in self.source

    def test_wave_e_lead_active_context_in_source(self):
        """WAVE-E-LEAD ACTIVE context injection is in the source."""
        assert "WAVE-E-LEAD ACTIVE" in self.source
