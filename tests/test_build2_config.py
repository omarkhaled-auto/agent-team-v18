"""Tests for Build 2 Agent Teams configuration and state integration.

Covers:
- AgentTeamsConfig dataclass defaults and field types
- _dict_to_config() parsing of the agent_teams section
- Validation of invalid field values (display mode, timeouts, max_teammates)
- RunState.agent_teams_active field and save/load roundtrip
- Backward compatibility with configs that omit agent_teams
- Full config roundtrip from dict -> AgentTeamConfig -> field verification
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import fields
from pathlib import Path

import pytest

from agent_team.config import (
    AgentTeamConfig,
    AgentTeamsConfig,
    _dict_to_config,
    apply_depth_quality_gating,
    load_config,
)
from agent_team.state import RunState, load_state, save_state


# -----------------------------------------------------------------------
# TEST-012: AgentTeamsConfig defaults
# -----------------------------------------------------------------------


def test_agent_teams_config_defaults():
    """All AgentTeamsConfig defaults match the Build 2 specification."""
    cfg = AgentTeamsConfig()
    assert cfg.enabled is False
    assert cfg.fallback_to_cli is True
    assert cfg.delegate_mode is True
    assert cfg.max_teammates == 5
    assert cfg.teammate_model == ""
    assert cfg.teammate_permission_mode == "acceptEdits"
    assert cfg.teammate_idle_timeout == 300
    assert cfg.task_completed_hook is True
    assert cfg.wave_timeout_seconds == 3600
    assert cfg.task_timeout_seconds == 1800
    assert cfg.teammate_display_mode == "in-process"
    assert cfg.contract_limit == 100


# -----------------------------------------------------------------------
# TEST-013: _dict_to_config() parsing
# -----------------------------------------------------------------------


def test_dict_to_config_parses_agent_teams():
    """_dict_to_config correctly parses the agent_teams section."""
    data = {
        "agent_teams": {
            "enabled": True,
            "max_teammates": 8,
            "teammate_model": "sonnet",
        }
    }
    cfg, overrides = _dict_to_config(data)
    assert cfg.agent_teams.enabled is True
    assert cfg.agent_teams.max_teammates == 8
    assert cfg.agent_teams.teammate_model == "sonnet"
    # Defaults preserved for unset fields
    assert cfg.agent_teams.fallback_to_cli is True
    assert cfg.agent_teams.wave_timeout_seconds == 3600


def test_dict_to_config_without_agent_teams():
    """Config without agent_teams section preserves all defaults."""
    data = {"orchestrator": {"model": "sonnet"}}
    cfg, overrides = _dict_to_config(data)
    assert cfg.agent_teams.enabled is False
    assert cfg.agent_teams.max_teammates == 5


# -----------------------------------------------------------------------
# Config dataclass structure tests
# -----------------------------------------------------------------------


def test_agent_teams_config_on_root():
    """AgentTeamConfig root dataclass has an agent_teams field."""
    root = AgentTeamConfig()
    assert hasattr(root, "agent_teams")
    assert isinstance(root.agent_teams, AgentTeamsConfig)


def test_agent_team_config_returns_agent_teams_instance():
    """AgentTeamConfig().agent_teams returns an AgentTeamsConfig instance."""
    root = AgentTeamConfig()
    assert type(root.agent_teams) is AgentTeamsConfig


def test_agent_teams_config_has_12_fields():
    """AgentTeamsConfig has exactly the 12 documented fields."""
    expected_names = {
        "enabled", "fallback_to_cli", "delegate_mode", "max_teammates",
        "teammate_model", "teammate_permission_mode", "teammate_idle_timeout",
        "task_completed_hook", "wave_timeout_seconds", "task_timeout_seconds",
        "teammate_display_mode", "contract_limit",
    }
    actual_names = {f.name for f in fields(AgentTeamsConfig)}
    assert actual_names == expected_names


def test_agent_teams_config_field_types():
    """All 12 AgentTeamsConfig fields have correct Python types at runtime."""
    cfg = AgentTeamsConfig()
    assert isinstance(cfg.enabled, bool)
    assert isinstance(cfg.fallback_to_cli, bool)
    assert isinstance(cfg.delegate_mode, bool)
    assert isinstance(cfg.max_teammates, int)
    assert isinstance(cfg.teammate_model, str)
    assert isinstance(cfg.teammate_permission_mode, str)
    assert isinstance(cfg.teammate_idle_timeout, int)
    assert isinstance(cfg.task_completed_hook, bool)
    assert isinstance(cfg.wave_timeout_seconds, int)
    assert isinstance(cfg.task_timeout_seconds, int)
    assert isinstance(cfg.teammate_display_mode, str)
    assert isinstance(cfg.contract_limit, int)


# -----------------------------------------------------------------------
# _dict_to_config() parsing edge cases
# -----------------------------------------------------------------------


def test_user_override_tracking_for_agent_teams_enabled():
    """Setting agent_teams.enabled in YAML records it as a user override."""
    data = {"agent_teams": {"enabled": True}}
    _cfg, overrides = _dict_to_config(data)
    assert "agent_teams.enabled" in overrides


def test_user_override_not_tracked_when_key_absent():
    """When agent_teams.enabled is NOT in dict, it is NOT in overrides."""
    data = {"agent_teams": {"max_teammates": 3}}
    _cfg, overrides = _dict_to_config(data)
    assert "agent_teams.enabled" not in overrides


def test_parse_all_12_fields_from_yaml():
    """_dict_to_config populates every AgentTeamsConfig field from a dict."""
    data = {
        "agent_teams": {
            "enabled": True,
            "fallback_to_cli": False,
            "delegate_mode": False,
            "max_teammates": 10,
            "teammate_model": "haiku",
            "teammate_permission_mode": "bypassPermissions",
            "teammate_idle_timeout": 600,
            "task_completed_hook": False,
            "wave_timeout_seconds": 7200,
            "task_timeout_seconds": 3600,
            "teammate_display_mode": "tmux",
            "contract_limit": 50,
        }
    }
    cfg, _ = _dict_to_config(data)
    at = cfg.agent_teams
    assert at.enabled is True
    assert at.fallback_to_cli is False
    assert at.delegate_mode is False
    assert at.max_teammates == 10
    assert at.teammate_model == "haiku"
    assert at.teammate_permission_mode == "bypassPermissions"
    assert at.teammate_idle_timeout == 600
    assert at.task_completed_hook is False
    assert at.wave_timeout_seconds == 7200
    assert at.task_timeout_seconds == 3600
    assert at.teammate_display_mode == "tmux"
    assert at.contract_limit == 50


def test_invalid_teammate_display_mode_raises():
    """Invalid teammate_display_mode raises ValueError."""
    data = {"agent_teams": {"teammate_display_mode": "invalid-mode"}}
    with pytest.raises(ValueError, match="teammate_display_mode"):
        _dict_to_config(data)


def test_invalid_max_teammates_zero_raises():
    """max_teammates of 0 raises ValueError."""
    data = {"agent_teams": {"max_teammates": 0}}
    with pytest.raises(ValueError, match="max_teammates"):
        _dict_to_config(data)


def test_invalid_max_teammates_negative_raises():
    """max_teammates of -1 raises ValueError."""
    data = {"agent_teams": {"max_teammates": -1}}
    with pytest.raises(ValueError, match="max_teammates"):
        _dict_to_config(data)


def test_invalid_wave_timeout_below_60_raises():
    """wave_timeout_seconds < 60 raises ValueError."""
    data = {"agent_teams": {"wave_timeout_seconds": 30}}
    with pytest.raises(ValueError, match="wave_timeout_seconds"):
        _dict_to_config(data)


def test_invalid_task_timeout_below_60_raises():
    """task_timeout_seconds < 60 raises ValueError."""
    data = {"agent_teams": {"task_timeout_seconds": 59}}
    with pytest.raises(ValueError, match="task_timeout_seconds"):
        _dict_to_config(data)


def test_teammate_model_converted_to_string():
    """Numeric teammate_model values are converted to string."""
    data = {"agent_teams": {"teammate_model": 12345}}
    cfg, _ = _dict_to_config(data)
    assert cfg.agent_teams.teammate_model == "12345"
    assert isinstance(cfg.agent_teams.teammate_model, str)


def test_empty_agent_teams_dict_uses_defaults():
    """An empty agent_teams dict falls back to all default values."""
    data = {"agent_teams": {}}
    cfg, _ = _dict_to_config(data)
    defaults = AgentTeamsConfig()
    assert cfg.agent_teams.enabled == defaults.enabled
    assert cfg.agent_teams.max_teammates == defaults.max_teammates
    assert cfg.agent_teams.wave_timeout_seconds == defaults.wave_timeout_seconds
    assert cfg.agent_teams.teammate_display_mode == defaults.teammate_display_mode


def test_agent_teams_non_dict_value_is_ignored():
    """When agent_teams key exists but is not a dict, defaults are kept."""
    data = {"agent_teams": "not-a-dict"}
    cfg, _ = _dict_to_config(data)
    # The isinstance check in _dict_to_config skips non-dict values
    assert cfg.agent_teams.enabled is False
    assert cfg.agent_teams.max_teammates == 5


# -----------------------------------------------------------------------
# State tests
# -----------------------------------------------------------------------


def test_run_state_has_agent_teams_active_field():
    """RunState dataclass exposes agent_teams_active defaulting to False."""
    state = RunState()
    assert hasattr(state, "agent_teams_active")
    assert state.agent_teams_active is False


def test_save_load_state_roundtrips_agent_teams_active():
    """save_state/load_state roundtrips the agent_teams_active field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = RunState(task="test-task", agent_teams_active=True)
        save_state(state, directory=tmpdir)
        loaded = load_state(directory=tmpdir)
        assert loaded is not None
        assert loaded.agent_teams_active is True


def test_load_state_handles_missing_agent_teams_active():
    """load_state gracefully handles JSON missing agent_teams_active."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "STATE.json"
        # Write minimal valid state WITHOUT agent_teams_active
        minimal = {
            "run_id": "abc123",
            "task": "hello",
            "depth": "standard",
            "current_phase": "init",
            "schema_version": 2,
        }
        state_path.write_text(json.dumps(minimal), encoding="utf-8")
        loaded = load_state(directory=tmpdir)
        assert loaded is not None
        # Should default to False when missing from JSON
        assert loaded.agent_teams_active is False


# -----------------------------------------------------------------------
# Backward compatibility tests
# -----------------------------------------------------------------------


def test_dict_to_config_returns_correct_tuple_type():
    """_dict_to_config returns (AgentTeamConfig, set)."""
    result = _dict_to_config({})
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], AgentTeamConfig)
    assert isinstance(result[1], set)


def test_load_config_returns_correct_tuple_type():
    """load_config returns (AgentTeamConfig, set) even with no YAML file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Point to a path that doesn't exist so it falls back to defaults
        cfg, overrides = load_config(config_path=Path(tmpdir) / "nonexistent.yaml")
        assert isinstance(cfg, AgentTeamConfig)
        assert isinstance(overrides, set)


def test_existing_config_without_agent_teams_works():
    """A config dict with other sections but no agent_teams works fine."""
    data = {
        "orchestrator": {"model": "opus", "max_turns": 300},
        "depth": {"default": "thorough"},
        "convergence": {"max_cycles": 5},
    }
    cfg, _ = _dict_to_config(data)
    # agent_teams defaults preserved
    assert cfg.agent_teams.enabled is False
    assert cfg.agent_teams.max_teammates == 5
    # other sections parsed correctly
    assert cfg.orchestrator.model == "opus"
    assert cfg.orchestrator.max_turns == 300
    assert cfg.depth.default == "thorough"
    assert cfg.convergence.max_cycles == 5


def test_all_existing_fields_preserved_when_agent_teams_added():
    """Adding agent_teams to a full config does not clobber other sections."""
    data = {
        "orchestrator": {"model": "sonnet", "max_turns": 200},
        "interview": {"enabled": False},
        "verification": {"run_tests": False},
        "agent_teams": {"enabled": True, "max_teammates": 7},
    }
    cfg, _ = _dict_to_config(data)
    # agent_teams applied
    assert cfg.agent_teams.enabled is True
    assert cfg.agent_teams.max_teammates == 7
    # other sections untouched
    assert cfg.orchestrator.model == "sonnet"
    assert cfg.orchestrator.max_turns == 200
    assert cfg.interview.enabled is False
    assert cfg.verification.run_tests is False


def test_depth_gating_does_not_crash_with_agent_teams():
    """apply_depth_quality_gating runs without errors when agent_teams is present."""
    cfg, overrides = _dict_to_config({"agent_teams": {"enabled": True}})
    # Should not raise for any depth level
    for depth in ("quick", "standard", "thorough", "exhaustive"):
        apply_depth_quality_gating(depth, cfg, user_overrides=overrides)
    # Verify agent_teams config survived depth gating
    assert cfg.agent_teams.enabled is True


# -----------------------------------------------------------------------
# Integration tests
# -----------------------------------------------------------------------


def test_full_config_roundtrip_all_fields():
    """Full roundtrip: dict -> config -> verify every agent_teams field."""
    data = {
        "agent_teams": {
            "enabled": True,
            "fallback_to_cli": False,
            "delegate_mode": False,
            "max_teammates": 3,
            "teammate_model": "opus",
            "teammate_permission_mode": "plan",
            "teammate_idle_timeout": 120,
            "task_completed_hook": False,
            "wave_timeout_seconds": 120,
            "task_timeout_seconds": 60,
            "teammate_display_mode": "split",
            "contract_limit": 200,
        }
    }
    cfg, overrides = _dict_to_config(data)
    at = cfg.agent_teams

    assert at.enabled is True
    assert at.fallback_to_cli is False
    assert at.delegate_mode is False
    assert at.max_teammates == 3
    assert at.teammate_model == "opus"
    assert at.teammate_permission_mode == "plan"
    assert at.teammate_idle_timeout == 120
    assert at.task_completed_hook is False
    assert at.wave_timeout_seconds == 120
    assert at.task_timeout_seconds == 60
    assert at.teammate_display_mode == "split"
    assert at.contract_limit == 200

    # enabled was explicitly set -> tracked as override
    assert "agent_teams.enabled" in overrides


def test_dict_to_config_with_all_sections_including_agent_teams():
    """_dict_to_config with many sections including agent_teams parses all."""
    data = {
        "orchestrator": {"model": "opus"},
        "depth": {"default": "standard"},
        "convergence": {"max_cycles": 8},
        "interview": {"enabled": True},
        "scheduler": {"enabled": True},
        "verification": {"enabled": True},
        "quality": {"craft_review": True},
        "milestone": {"enabled": True},
        "e2e_testing": {"enabled": True},
        "tech_research": {"enabled": True},
        "agent_teams": {
            "enabled": True,
            "max_teammates": 4,
            "teammate_display_mode": "tmux",
        },
    }
    cfg, overrides = _dict_to_config(data)

    # Spot-check several sections
    assert cfg.orchestrator.model == "opus"
    assert cfg.convergence.max_cycles == 8
    assert cfg.milestone.enabled is True
    assert cfg.e2e_testing.enabled is True
    assert cfg.tech_research.enabled is True

    # agent_teams
    assert cfg.agent_teams.enabled is True
    assert cfg.agent_teams.max_teammates == 4
    assert cfg.agent_teams.teammate_display_mode == "tmux"
    # Defaults for unset agent_teams fields
    assert cfg.agent_teams.fallback_to_cli is True
    assert cfg.agent_teams.contract_limit == 100


def test_save_load_state_roundtrips_agent_teams_active_false():
    """save_state/load_state roundtrips agent_teams_active=False correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = RunState(task="test-task-false", agent_teams_active=False)
        save_state(state, directory=tmpdir)
        loaded = load_state(directory=tmpdir)
        assert loaded is not None
        assert loaded.agent_teams_active is False


def test_valid_display_modes_accepted():
    """All three valid teammate_display_mode values are accepted."""
    for mode in ("in-process", "tmux", "split"):
        data = {"agent_teams": {"teammate_display_mode": mode}}
        cfg, _ = _dict_to_config(data)
        assert cfg.agent_teams.teammate_display_mode == mode
