"""Phase 3 exhaustive verification tests for Build 2 backward compatibility and depth gating.

Covers gaps identified in Phase 2A (backward compatibility) and Phase 2D (depth gating):

Group 1: Unknown config keys -- _dict_to_config silently ignores unknown keys
Group 2: create_execution_backend integration -- all 4 factory branches
Group 3: Depth gating value assertions -- per-depth Build 2 field checks
Group 4: User override preservation under depth gating
Group 5: Server dict identity -- get_contract_aware_servers vs get_mcp_servers
Group 6: prd_mode depth gating -- browser_testing conditional on prd_mode
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from agent_team_v15.config import (
    AgentTeamConfig,
    AgentTeamsConfig,
    CodebaseIntelligenceConfig,
    ContractEngineConfig,
    ContractScanConfig,
    _dict_to_config,
    apply_depth_quality_gating,
)
from agent_team_v15.agent_teams_backend import (
    CLIBackend,
    AgentTeamsBackend,
    create_execution_backend,
)
from agent_team_v15.mcp_servers import get_contract_aware_servers, get_mcp_servers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_config(**overrides) -> tuple[AgentTeamConfig, set[str]]:
    """Build a fresh AgentTeamConfig via _dict_to_config for test isolation."""
    return _dict_to_config(overrides)


def _fresh_config_obj(**overrides) -> AgentTeamConfig:
    """Build a fresh AgentTeamConfig (config only, discard overrides)."""
    cfg, _ = _dict_to_config(overrides)
    return cfg


# ===========================================================================
# Group 1: Unknown Config Keys
# ===========================================================================


class TestUnknownConfigKeys:
    """Verify that _dict_to_config silently ignores unknown config keys."""

    def test_unknown_top_level_key_silently_ignored(self):
        """_dict_to_config({'totally_unknown': {'foo': 1}}) returns valid config without error."""
        cfg, overrides = _dict_to_config({"totally_unknown": {"foo": 1}})
        assert isinstance(cfg, AgentTeamConfig)
        assert isinstance(overrides, set)
        # All defaults should be intact
        assert cfg.orchestrator.model == "opus"
        assert cfg.agent_teams.enabled is False
        assert cfg.contract_engine.enabled is False

    def test_unknown_sub_key_in_known_section_ignored(self):
        """_dict_to_config({'orchestrator': {'unknown_field': 42}}) silently drops the unknown field."""
        cfg, _ = _dict_to_config({"orchestrator": {"unknown_field": 42}})
        assert isinstance(cfg, AgentTeamConfig)
        # Known defaults preserved -- the unknown field is simply not applied
        assert cfg.orchestrator.model == "opus"
        assert cfg.orchestrator.max_turns == 500
        # unknown_field does not appear anywhere
        assert not hasattr(cfg.orchestrator, "unknown_field")

    def test_mixed_known_and_unknown_keys(self):
        """Known keys are applied, unknown keys are silently ignored."""
        cfg, overrides = _dict_to_config({
            "orchestrator": {"model": "sonnet", "unknown_x": True},
            "totally_fake_section": {"a": 1, "b": 2},
            "agent_teams": {"enabled": True, "nonexistent_key": "ignored"},
        })
        # Known keys applied
        assert cfg.orchestrator.model == "sonnet"
        assert cfg.agent_teams.enabled is True
        # Override tracking still works for known keys
        assert "agent_teams.enabled" in overrides
        # Unknown sections/keys do not create attributes
        assert not hasattr(cfg, "totally_fake_section")

    def test_multiple_unknown_top_level_keys(self):
        """Multiple unknown top-level sections do not cause errors."""
        cfg, _ = _dict_to_config({
            "alpha": {"x": 1},
            "beta": {"y": 2},
            "gamma": "plain-string",
        })
        assert isinstance(cfg, AgentTeamConfig)
        assert cfg.orchestrator.model == "opus"

    def test_unknown_key_does_not_pollute_overrides(self):
        """Unknown keys do not appear in the user_overrides set."""
        _, overrides = _dict_to_config({
            "totally_unknown": {"foo": 1},
            "another_unknown": True,
        })
        assert len(overrides) == 0


# ===========================================================================
# Group 2: create_execution_backend Integration
# ===========================================================================


class TestCreateExecutionBackendIntegration:
    """Verify all branches of the create_execution_backend factory."""

    def test_disabled_returns_cli_backend(self):
        """agent_teams.enabled=False returns CLIBackend instance."""
        cfg = _fresh_config_obj()
        assert cfg.agent_teams.enabled is False
        backend = create_execution_backend(cfg)
        assert isinstance(backend, CLIBackend)

    def test_branch2_ignores_fallback_to_cli(self, monkeypatch):
        """When env var not set, returns CLIBackend even when fallback_to_cli=False.

        Branch 2: enabled=True but CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS is not '1'.
        The factory logs a warning and returns CLIBackend regardless of fallback_to_cli.
        """
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        cfg, _ = _dict_to_config({
            "agent_teams": {"enabled": True, "fallback_to_cli": False},
        })
        assert cfg.agent_teams.enabled is True
        assert cfg.agent_teams.fallback_to_cli is False
        backend = create_execution_backend(cfg)
        # Branch 2: env var not set -> CLIBackend (fallback_to_cli is irrelevant here)
        assert isinstance(backend, CLIBackend)

    def test_env_set_cli_unavailable_with_fallback(self, monkeypatch):
        """Branch 3: env var set + CLI unavailable + fallback_to_cli=True returns CLIBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        cfg, _ = _dict_to_config({
            "agent_teams": {"enabled": True, "fallback_to_cli": True},
        })
        # Mock _verify_claude_available to return False (CLI not installed)
        with patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False):
            backend = create_execution_backend(cfg)
        assert isinstance(backend, CLIBackend)

    def test_env_set_cli_unavailable_no_fallback(self, monkeypatch):
        """Branch 4: env var set + CLI unavailable + fallback_to_cli=False raises RuntimeError."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        cfg, _ = _dict_to_config({
            "agent_teams": {"enabled": True, "fallback_to_cli": False},
        })
        with patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False):
            with pytest.raises(RuntimeError, match="claude CLI is not installed"):
                create_execution_backend(cfg)

    def test_env_set_cli_available_returns_agent_teams_backend(self, monkeypatch):
        """Branch 5/6: all conditions met returns AgentTeamsBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        # Remove WT_SESSION to avoid Windows Terminal display-mode check
        monkeypatch.delenv("WT_SESSION", raising=False)
        cfg, _ = _dict_to_config({
            "agent_teams": {
                "enabled": True,
                "teammate_display_mode": "in-process",
            },
        })
        with patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True):
            backend = create_execution_backend(cfg)
        assert isinstance(backend, AgentTeamsBackend)

    def test_disabled_explicitly_false_returns_cli(self):
        """Explicitly setting enabled=False returns CLIBackend."""
        cfg, _ = _dict_to_config({
            "agent_teams": {"enabled": False},
        })
        backend = create_execution_backend(cfg)
        assert isinstance(backend, CLIBackend)


# ===========================================================================
# Group 3: Depth Gating Value Assertions
# ===========================================================================


class TestDepthGatingBuild2Values:
    """Exhaustive per-depth verification of Build 2 field values after gating."""

    # -- quick depth --------------------------------------------------------

    def test_quick_disables_contract_engine(self):
        """After apply_depth_quality_gating('quick', ...), contract_engine.enabled=False."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg)
        assert cfg.contract_engine.enabled is False

    def test_quick_disables_codebase_intelligence(self):
        """After quick, codebase_intelligence.enabled=False."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg)
        assert cfg.codebase_intelligence.enabled is False

    def test_quick_disables_agent_teams(self):
        """After quick, agent_teams.enabled=False."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg)
        assert cfg.agent_teams.enabled is False

    def test_quick_disables_all_contract_scans(self):
        """After quick, all 4 contract scan booleans are False."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg)
        assert cfg.contract_scans.endpoint_schema_scan is False
        assert cfg.contract_scans.missing_endpoint_scan is False
        assert cfg.contract_scans.event_schema_scan is False
        assert cfg.contract_scans.shared_model_scan is False

    # -- standard depth -----------------------------------------------------

    def test_standard_enables_contract_engine(self):
        """After standard, contract_engine.enabled=True."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        assert cfg.contract_engine.enabled is True

    def test_standard_contract_engine_limited(self):
        """After standard, validation_on_build=True but test_generation=False."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        assert cfg.contract_engine.validation_on_build is True
        assert cfg.contract_engine.test_generation is False

    def test_standard_enables_codebase_intelligence(self):
        """After standard, codebase_intelligence.enabled=True."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        assert cfg.codebase_intelligence.enabled is True

    def test_standard_codebase_intelligence_limited(self):
        """After standard, replace_static_map=False, register_artifacts=False."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        assert cfg.codebase_intelligence.replace_static_map is False
        assert cfg.codebase_intelligence.register_artifacts is False

    def test_standard_agent_teams_stays_disabled(self):
        """Agent teams is NOT gated at standard depth -- stays at default False."""
        cfg = AgentTeamConfig()
        assert cfg.agent_teams.enabled is False  # default
        apply_depth_quality_gating("standard", cfg)
        # standard does not touch agent_teams.enabled at all
        assert cfg.agent_teams.enabled is False

    def test_standard_disables_event_and_shared_scans(self):
        """After standard, event_schema_scan=False, shared_model_scan=False."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        assert cfg.contract_scans.event_schema_scan is False
        assert cfg.contract_scans.shared_model_scan is False

    def test_standard_keeps_endpoint_scans(self):
        """After standard, endpoint_schema_scan and missing_endpoint_scan stay True."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        # Standard does NOT disable endpoint_schema_scan or missing_endpoint_scan
        assert cfg.contract_scans.endpoint_schema_scan is True
        assert cfg.contract_scans.missing_endpoint_scan is True

    # -- thorough depth -----------------------------------------------------

    def test_thorough_enables_all_contract_engine(self):
        """After thorough, contract_engine.enabled=True, test_generation=True."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("thorough", cfg)
        assert cfg.contract_engine.enabled is True
        assert cfg.contract_engine.test_generation is True

    def test_thorough_enables_all_codebase_intelligence(self):
        """After thorough, replace_static_map=True, register_artifacts=True."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("thorough", cfg)
        assert cfg.codebase_intelligence.enabled is True
        assert cfg.codebase_intelligence.replace_static_map is True
        assert cfg.codebase_intelligence.register_artifacts is True

    def test_thorough_agent_teams_conditional_on_env(self, monkeypatch):
        """After thorough with env var set, agent_teams.enabled=True."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("thorough", cfg)
        assert cfg.agent_teams.enabled is True

    def test_thorough_agent_teams_stays_false_without_env(self, monkeypatch):
        """After thorough without env var, agent_teams.enabled stays False."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("thorough", cfg)
        assert cfg.agent_teams.enabled is False

    # -- exhaustive depth ---------------------------------------------------

    def test_exhaustive_same_as_thorough_for_build2(self, monkeypatch):
        """Exhaustive has same Build 2 settings as thorough."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)

        cfg_thorough = AgentTeamConfig()
        apply_depth_quality_gating("thorough", cfg_thorough)

        cfg_exhaustive = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", cfg_exhaustive)

        # Contract engine
        assert cfg_exhaustive.contract_engine.enabled == cfg_thorough.contract_engine.enabled
        assert cfg_exhaustive.contract_engine.test_generation == cfg_thorough.contract_engine.test_generation

        # Codebase intelligence
        assert cfg_exhaustive.codebase_intelligence.enabled == cfg_thorough.codebase_intelligence.enabled
        assert cfg_exhaustive.codebase_intelligence.replace_static_map == cfg_thorough.codebase_intelligence.replace_static_map
        assert cfg_exhaustive.codebase_intelligence.register_artifacts == cfg_thorough.codebase_intelligence.register_artifacts

        # Agent teams (both stay False without env var)
        assert cfg_exhaustive.agent_teams.enabled == cfg_thorough.agent_teams.enabled

    def test_exhaustive_enables_contract_engine(self):
        """Exhaustive explicitly enables contract_engine and test_generation."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", cfg)
        assert cfg.contract_engine.enabled is True
        assert cfg.contract_engine.test_generation is True

    def test_exhaustive_enables_codebase_intelligence(self):
        """Exhaustive explicitly enables full codebase_intelligence."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", cfg)
        assert cfg.codebase_intelligence.enabled is True
        assert cfg.codebase_intelligence.replace_static_map is True
        assert cfg.codebase_intelligence.register_artifacts is True

    def test_exhaustive_agent_teams_conditional_on_env(self, monkeypatch):
        """After exhaustive with env var set, agent_teams.enabled=True."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", cfg)
        assert cfg.agent_teams.enabled is True

    def test_exhaustive_agent_teams_stays_false_without_env(self, monkeypatch):
        """After exhaustive without env var, agent_teams.enabled stays False."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", cfg)
        assert cfg.agent_teams.enabled is False

    # -- contract scans per depth (parametrized) ----------------------------

    @pytest.mark.parametrize("depth", ["thorough", "exhaustive"])
    def test_thorough_exhaustive_preserve_all_contract_scans(self, depth):
        """Thorough and exhaustive do not disable any contract scans (defaults stay True)."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating(depth, cfg)
        assert cfg.contract_scans.endpoint_schema_scan is True
        assert cfg.contract_scans.missing_endpoint_scan is True
        assert cfg.contract_scans.event_schema_scan is True
        assert cfg.contract_scans.shared_model_scan is True


# ===========================================================================
# Group 4: User Override Preservation Under Depth Gating
# ===========================================================================


class TestUserOverridePreservation:
    """Verify that user-set overrides survive depth gating."""

    def test_user_override_contract_engine_survives_quick(self):
        """User sets contract_engine.enabled=True, quick depth does NOT override it."""
        cfg, overrides = _dict_to_config({
            "contract_engine": {"enabled": True},
        })
        assert "contract_engine.enabled" in overrides
        assert cfg.contract_engine.enabled is True

        apply_depth_quality_gating("quick", cfg, user_overrides=overrides)
        # User override preserved -- quick would normally set this to False
        assert cfg.contract_engine.enabled is True

    def test_user_override_agent_teams_survives_quick(self):
        """User sets agent_teams.enabled=True, quick depth does NOT override it."""
        cfg, overrides = _dict_to_config({
            "agent_teams": {"enabled": True},
        })
        assert "agent_teams.enabled" in overrides
        assert cfg.agent_teams.enabled is True

        apply_depth_quality_gating("quick", cfg, user_overrides=overrides)
        # User override preserved
        assert cfg.agent_teams.enabled is True

    def test_user_override_codebase_intelligence_survives_quick(self):
        """User sets codebase_intelligence.enabled=True, quick depth does NOT override it."""
        cfg, overrides = _dict_to_config({
            "codebase_intelligence": {"enabled": True},
        })
        assert "codebase_intelligence.enabled" in overrides
        assert cfg.codebase_intelligence.enabled is True

        apply_depth_quality_gating("quick", cfg, user_overrides=overrides)
        # User override preserved
        assert cfg.codebase_intelligence.enabled is True

    def test_user_override_scan_survives_standard(self):
        """User sets event_schema_scan=True, standard depth does NOT override it."""
        cfg, overrides = _dict_to_config({
            "contract_scans": {"event_schema_scan": True},
        })
        assert "contract_scans.event_schema_scan" in overrides
        assert cfg.contract_scans.event_schema_scan is True

        apply_depth_quality_gating("standard", cfg, user_overrides=overrides)
        # Standard would normally set event_schema_scan=False, but user override wins
        assert cfg.contract_scans.event_schema_scan is True

    def test_multiple_overrides_respected(self):
        """Multiple user overrides all preserved under depth gating."""
        cfg, overrides = _dict_to_config({
            "contract_engine": {"enabled": True, "test_generation": True},
            "codebase_intelligence": {"enabled": True, "replace_static_map": True},
            "agent_teams": {"enabled": True},
            "contract_scans": {
                "event_schema_scan": True,
                "shared_model_scan": True,
            },
        })

        # Verify overrides are tracked
        assert "contract_engine.enabled" in overrides
        assert "contract_engine.test_generation" in overrides
        assert "codebase_intelligence.enabled" in overrides
        assert "codebase_intelligence.replace_static_map" in overrides
        assert "agent_teams.enabled" in overrides
        assert "contract_scans.event_schema_scan" in overrides
        assert "contract_scans.shared_model_scan" in overrides

        # Apply quick depth -- the most aggressive disabling depth
        apply_depth_quality_gating("quick", cfg, user_overrides=overrides)

        # All user overrides should survive
        assert cfg.contract_engine.enabled is True
        assert cfg.contract_engine.test_generation is True
        assert cfg.codebase_intelligence.enabled is True
        assert cfg.codebase_intelligence.replace_static_map is True
        assert cfg.agent_teams.enabled is True
        assert cfg.contract_scans.event_schema_scan is True
        assert cfg.contract_scans.shared_model_scan is True

    def test_non_overridden_fields_still_gated(self):
        """Fields NOT in user_overrides are still gated by depth."""
        cfg, overrides = _dict_to_config({
            "contract_engine": {"enabled": True},
            # Note: test_generation is NOT set by user
        })
        assert "contract_engine.enabled" in overrides
        assert "contract_engine.test_generation" not in overrides

        apply_depth_quality_gating("standard", cfg, user_overrides=overrides)
        # enabled is user-overridden -> preserved
        assert cfg.contract_engine.enabled is True
        # test_generation is NOT overridden -> gated by standard to False
        assert cfg.contract_engine.test_generation is False

    def test_user_override_codebase_intelligence_register_artifacts_survives_standard(self):
        """User sets register_artifacts=True, standard depth does NOT override it."""
        cfg, overrides = _dict_to_config({
            "codebase_intelligence": {"register_artifacts": True},
        })
        assert "codebase_intelligence.register_artifacts" in overrides

        apply_depth_quality_gating("standard", cfg, user_overrides=overrides)
        # Standard would set register_artifacts=False, but user override wins
        assert cfg.codebase_intelligence.register_artifacts is True

    def test_empty_overrides_allows_full_gating(self):
        """With no user overrides, depth gating applies fully."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg, user_overrides=set())
        assert cfg.contract_engine.enabled is False
        assert cfg.codebase_intelligence.enabled is False
        assert cfg.agent_teams.enabled is False

    def test_none_overrides_allows_full_gating(self):
        """With user_overrides=None, depth gating applies fully."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg, user_overrides=None)
        assert cfg.contract_engine.enabled is False
        assert cfg.codebase_intelligence.enabled is False
        assert cfg.agent_teams.enabled is False


# ===========================================================================
# Group 5: Server Dict Identity
# ===========================================================================


class TestServerDictIdentity:
    """Verify MCP server dict composition with Build 2 features."""

    def test_disabled_build2_returns_identical_dict(self):
        """When both disabled, get_contract_aware_servers == get_mcp_servers (value equality)."""
        cfg = _fresh_config_obj()
        assert cfg.contract_engine.enabled is False
        assert cfg.codebase_intelligence.enabled is False

        base = get_mcp_servers(cfg)
        aware = get_contract_aware_servers(cfg)
        assert base == aware

    def test_only_contract_engine_adds_one_key(self):
        """When only contract_engine enabled, exactly one extra key 'contract_engine' is added."""
        cfg, _ = _dict_to_config({
            "contract_engine": {"enabled": True},
            "codebase_intelligence": {"enabled": False},
        })
        base = get_mcp_servers(cfg)
        aware = get_contract_aware_servers(cfg)

        extra_keys = set(aware.keys()) - set(base.keys())
        assert extra_keys == {"contract_engine"}

    def test_only_codebase_intelligence_adds_one_key(self):
        """When only codebase_intelligence enabled, exactly one extra key 'codebase_intelligence' is added."""
        cfg, _ = _dict_to_config({
            "contract_engine": {"enabled": False},
            "codebase_intelligence": {"enabled": True},
        })
        base = get_mcp_servers(cfg)
        aware = get_contract_aware_servers(cfg)

        extra_keys = set(aware.keys()) - set(base.keys())
        assert extra_keys == {"codebase_intelligence"}

    def test_both_enabled_adds_two_keys(self):
        """When both enabled, exactly two extra keys are added."""
        cfg, _ = _dict_to_config({
            "contract_engine": {"enabled": True},
            "codebase_intelligence": {"enabled": True},
        })
        base = get_mcp_servers(cfg)
        aware = get_contract_aware_servers(cfg)

        extra_keys = set(aware.keys()) - set(base.keys())
        assert extra_keys == {"contract_engine", "codebase_intelligence"}

    def test_base_servers_always_preserved(self):
        """Base MCP servers are always present regardless of Build 2 settings."""
        cfg, _ = _dict_to_config({
            "contract_engine": {"enabled": True},
            "codebase_intelligence": {"enabled": True},
        })
        base = get_mcp_servers(cfg)
        aware = get_contract_aware_servers(cfg)

        for key in base:
            assert key in aware
            assert aware[key] == base[key]

    def test_contract_engine_server_has_correct_structure(self):
        """The contract_engine server entry has 'type', 'command', 'args' keys."""
        cfg, _ = _dict_to_config({
            "contract_engine": {"enabled": True},
        })
        aware = get_contract_aware_servers(cfg)
        ce_server = aware["contract_engine"]
        assert ce_server["type"] == "stdio"
        assert "command" in ce_server
        assert "args" in ce_server

    def test_codebase_intelligence_server_has_correct_structure(self):
        """The codebase_intelligence server entry has 'type', 'command', 'args' keys."""
        cfg, _ = _dict_to_config({
            "codebase_intelligence": {"enabled": True},
        })
        aware = get_contract_aware_servers(cfg)
        ci_server = aware["codebase_intelligence"]
        assert ci_server["type"] == "stdio"
        assert "command" in ci_server
        assert "args" in ci_server


# ===========================================================================
# Group 6: prd_mode Depth Gating
# ===========================================================================


class TestPrdModeDepthGating:
    """Verify browser_testing gating conditioned on prd_mode flag."""

    def test_thorough_prd_mode_enables_browser_testing(self):
        """At thorough depth with prd_mode=True, browser_testing.enabled=True."""
        cfg = AgentTeamConfig()
        assert cfg.browser_testing.enabled is False  # default
        apply_depth_quality_gating("thorough", cfg, prd_mode=True)
        assert cfg.browser_testing.enabled is True

    def test_thorough_no_prd_mode_browser_testing_unchanged(self):
        """At thorough depth without prd_mode, browser_testing.enabled unchanged."""
        cfg = AgentTeamConfig()
        assert cfg.browser_testing.enabled is False  # default
        apply_depth_quality_gating("thorough", cfg, prd_mode=False)
        # Without prd_mode AND without milestone.enabled, browser_testing stays False
        assert cfg.browser_testing.enabled is False

    def test_thorough_milestone_enabled_enables_browser_testing(self):
        """At thorough depth with milestone.enabled=True (but prd_mode=False),
        browser_testing.enabled=True because the code checks config.milestone.enabled too."""
        cfg = AgentTeamConfig()
        cfg.milestone.enabled = True
        apply_depth_quality_gating("thorough", cfg, prd_mode=False)
        assert cfg.browser_testing.enabled is True

    def test_exhaustive_prd_mode_enables_browser_testing(self):
        """At exhaustive depth with prd_mode=True, browser_testing.enabled=True."""
        cfg = AgentTeamConfig()
        assert cfg.browser_testing.enabled is False
        apply_depth_quality_gating("exhaustive", cfg, prd_mode=True)
        assert cfg.browser_testing.enabled is True

    def test_exhaustive_no_prd_mode_browser_testing_unchanged(self):
        """At exhaustive depth without prd_mode, browser_testing stays unchanged."""
        cfg = AgentTeamConfig()
        assert cfg.browser_testing.enabled is False
        apply_depth_quality_gating("exhaustive", cfg, prd_mode=False)
        assert cfg.browser_testing.enabled is False

    def test_quick_prd_mode_disables_browser_testing(self):
        """At quick depth even with prd_mode=True, browser_testing.enabled=False."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg, prd_mode=True)
        assert cfg.browser_testing.enabled is False

    def test_standard_prd_mode_does_not_enable_browser_testing(self):
        """At standard depth with prd_mode=True, browser_testing is not touched (stays default)."""
        cfg = AgentTeamConfig()
        assert cfg.browser_testing.enabled is False
        apply_depth_quality_gating("standard", cfg, prd_mode=True)
        # Standard depth does not touch browser_testing at all
        assert cfg.browser_testing.enabled is False

    def test_thorough_prd_mode_sets_max_fix_retries(self):
        """At thorough depth with prd_mode=True, browser_testing.max_fix_retries=3."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("thorough", cfg, prd_mode=True)
        assert cfg.browser_testing.max_fix_retries == 3

    def test_exhaustive_prd_mode_sets_max_fix_retries(self):
        """At exhaustive depth with prd_mode=True, browser_testing.max_fix_retries=5."""
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", cfg, prd_mode=True)
        assert cfg.browser_testing.max_fix_retries == 5

    def test_user_override_browser_testing_survives_thorough_prd_mode(self):
        """User override of browser_testing.enabled=False survives thorough+prd_mode."""
        cfg, overrides = _dict_to_config({
            "browser_testing": {"enabled": False},
        })
        assert "browser_testing.enabled" in overrides

        apply_depth_quality_gating("thorough", cfg, user_overrides=overrides, prd_mode=True)
        # User explicitly said False -- depth gating respects this
        assert cfg.browser_testing.enabled is False
