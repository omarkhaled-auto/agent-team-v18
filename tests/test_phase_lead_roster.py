"""Phase 1 Task 1.1: PHASE_LEAD_NAMES and PhaseLeadsConfig are wave-aligned."""
from __future__ import annotations

from agent_team_v15.agent_teams_backend import AgentTeamsBackend
from agent_team_v15.config import AgentTeamConfig, PhaseLeadsConfig


def test_phase_lead_names_are_wave_aligned():
    """PHASE_LEAD_NAMES lists only wave-aligned leads."""
    expected = {"wave-a-lead", "wave-d5-lead", "wave-t-lead", "wave-e-lead"}
    assert set(AgentTeamsBackend.PHASE_LEAD_NAMES) == expected


def test_phase_lead_names_no_legacy_names():
    """Legacy generic names must be absent."""
    legacy_prefixes = {"planning", "architecture", "coding", "review", "testing", "audit"}
    legacy = {f"{prefix}-lead" for prefix in legacy_prefixes}
    overlap = legacy & set(AgentTeamsBackend.PHASE_LEAD_NAMES)
    assert not overlap, f"Legacy names still present: {overlap}"


def test_phase_leads_config_fields_match_roster():
    """Every name in PHASE_LEAD_NAMES maps to a PhaseLeadsConfig attribute."""
    cfg = PhaseLeadsConfig()
    assert cfg is not None
    backend = AgentTeamsBackend.__new__(AgentTeamsBackend)
    backend._config = AgentTeamConfig()
    for name in AgentTeamsBackend.PHASE_LEAD_NAMES:
        lead_cfg = backend._get_phase_lead_config(name)
        assert lead_cfg is not None, f"No PhaseLeadConfig mapped for {name!r}"
        assert hasattr(lead_cfg, "enabled"), (
            f"_get_phase_lead_config({name!r}) must return a PhaseLeadConfig"
        )


def test_phase_leads_config_preserves_handoff_and_parallel_fields():
    """Correction #8: handoff_timeout_seconds and allow_parallel_phases remain."""
    cfg = PhaseLeadsConfig()
    assert hasattr(cfg, "handoff_timeout_seconds")
    assert hasattr(cfg, "allow_parallel_phases")
    assert isinstance(cfg.handoff_timeout_seconds, int)
    assert isinstance(cfg.allow_parallel_phases, bool)
