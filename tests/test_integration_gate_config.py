"""Tests for IntegrationGateConfig — defaults, YAML loading, and backward compatibility."""

from __future__ import annotations

import pytest
import yaml

from agent_team_v15.config import (
    AgentTeamConfig,
    IntegrationGateConfig,
    _dict_to_config,
    load_config,
)


# ===================================================================
# 1. Default Values
# ===================================================================


class TestIntegrationGateConfigDefaults:
    """Verify all IntegrationGateConfig defaults are correct."""

    def test_enabled_default(self):
        c = IntegrationGateConfig()
        assert c.enabled is True

    def test_contract_extraction_default(self):
        c = IntegrationGateConfig()
        assert c.contract_extraction is True

    def test_verification_enabled_default(self):
        c = IntegrationGateConfig()
        assert c.verification_enabled is True

    def test_verification_mode_default(self):
        c = IntegrationGateConfig()
        assert c.verification_mode == "block"

    def test_enriched_handoff_default(self):
        c = IntegrationGateConfig()
        assert c.enriched_handoff is True

    def test_cross_milestone_source_access_default(self):
        c = IntegrationGateConfig()
        assert c.cross_milestone_source_access is True

    def test_serialization_mandate_default(self):
        c = IntegrationGateConfig()
        assert c.serialization_mandate is True

    def test_contract_injection_max_chars_default(self):
        c = IntegrationGateConfig()
        assert c.contract_injection_max_chars == 15000

    def test_report_injection_max_chars_default(self):
        c = IntegrationGateConfig()
        assert c.report_injection_max_chars == 10000

    def test_backend_source_patterns_default(self):
        c = IntegrationGateConfig()
        assert isinstance(c.backend_source_patterns, list)
        assert "*.controller.ts" in c.backend_source_patterns
        assert "*.dto.ts" in c.backend_source_patterns
        assert "schema.prisma" in c.backend_source_patterns
        assert "*.routes.ts" in c.backend_source_patterns
        assert "*.router.ts" in c.backend_source_patterns

    def test_skip_directories_default(self):
        c = IntegrationGateConfig()
        assert isinstance(c.skip_directories, list)
        assert "node_modules" in c.skip_directories
        assert ".next" in c.skip_directories
        assert "dist" in c.skip_directories
        assert "build" in c.skip_directories
        assert "__pycache__" in c.skip_directories
        assert ".venv" in c.skip_directories

    def test_agent_team_config_has_integration_gate(self):
        """AgentTeamConfig has an integration_gate field with correct defaults."""
        cfg = AgentTeamConfig()
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True
        assert cfg.integration_gate.verification_mode == "block"


# ===================================================================
# 2. Config Loading from YAML
# ===================================================================


class TestIntegrationGateConfigLoading:
    """Verify IntegrationGateConfig is correctly loaded from YAML via _dict_to_config."""

    def test_full_config_from_yaml(self):
        """All integration_gate fields are loaded from a complete YAML dict."""
        cfg, _ = _dict_to_config({
            "integration_gate": {
                "enabled": False,
                "contract_extraction": False,
                "verification_enabled": False,
                "verification_mode": "block",
                "enriched_handoff": False,
                "cross_milestone_source_access": False,
                "serialization_mandate": False,
                "contract_injection_max_chars": 5000,
                "report_injection_max_chars": 3000,
                "backend_source_patterns": ["*.controller.ts"],
                "skip_directories": ["node_modules", "vendor"],
            }
        })
        ig = cfg.integration_gate
        assert ig.enabled is False
        assert ig.contract_extraction is False
        assert ig.verification_enabled is False
        assert ig.verification_mode == "block"
        assert ig.enriched_handoff is False
        assert ig.cross_milestone_source_access is False
        assert ig.serialization_mandate is False
        assert ig.contract_injection_max_chars == 5000
        assert ig.report_injection_max_chars == 3000
        assert ig.backend_source_patterns == ["*.controller.ts"]
        assert ig.skip_directories == ["node_modules", "vendor"]

    def test_partial_config_preserves_defaults(self):
        """Partial integration_gate config preserves defaults for unset fields."""
        cfg, _ = _dict_to_config({
            "integration_gate": {
                "enabled": False,
                "verification_mode": "block",
            }
        })
        ig = cfg.integration_gate
        assert ig.enabled is False
        assert ig.verification_mode == "block"
        # Unset fields preserve defaults
        assert ig.contract_extraction is True
        assert ig.verification_enabled is True
        assert ig.enriched_handoff is True
        assert ig.cross_milestone_source_access is True
        assert ig.serialization_mandate is True
        assert ig.contract_injection_max_chars == 15000
        assert ig.report_injection_max_chars == 10000

    def test_verification_mode_warn(self):
        """verification_mode='warn' is accepted."""
        cfg, _ = _dict_to_config({
            "integration_gate": {"verification_mode": "warn"}
        })
        assert cfg.integration_gate.verification_mode == "warn"

    def test_verification_mode_block(self):
        """verification_mode='block' is accepted."""
        cfg, _ = _dict_to_config({
            "integration_gate": {"verification_mode": "block"}
        })
        assert cfg.integration_gate.verification_mode == "block"

    def test_verification_mode_invalid_raises(self):
        """An invalid verification_mode raises ValueError."""
        with pytest.raises(ValueError, match="verification_mode"):
            _dict_to_config({
                "integration_gate": {"verification_mode": "invalid_mode"}
            })

    def test_contract_injection_max_chars_override(self):
        cfg, _ = _dict_to_config({
            "integration_gate": {"contract_injection_max_chars": 20000}
        })
        assert cfg.integration_gate.contract_injection_max_chars == 20000

    def test_report_injection_max_chars_override(self):
        cfg, _ = _dict_to_config({
            "integration_gate": {"report_injection_max_chars": 8000}
        })
        assert cfg.integration_gate.report_injection_max_chars == 8000

    def test_backend_source_patterns_override(self):
        cfg, _ = _dict_to_config({
            "integration_gate": {
                "backend_source_patterns": ["*.handler.ts", "*.service.ts"]
            }
        })
        assert cfg.integration_gate.backend_source_patterns == ["*.handler.ts", "*.service.ts"]

    def test_skip_directories_override(self):
        cfg, _ = _dict_to_config({
            "integration_gate": {
                "skip_directories": ["node_modules", "custom_vendor"]
            }
        })
        assert "custom_vendor" in cfg.integration_gate.skip_directories

    def test_load_from_yaml_file(self, tmp_path):
        """Integration gate config loads correctly from a real YAML file."""
        data = {
            "integration_gate": {
                "enabled": False,
                "verification_mode": "block",
                "contract_injection_max_chars": 7500,
            }
        }
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(data), encoding="utf-8")
        cfg, _ = load_config(config_path=str(p))
        assert cfg.integration_gate.enabled is False
        assert cfg.integration_gate.verification_mode == "block"
        assert cfg.integration_gate.contract_injection_max_chars == 7500


# ===================================================================
# 3. Backward Compatibility
# ===================================================================


class TestIntegrationGateBackwardCompatibility:
    """Verify AgentTeamConfig works correctly without integration_gate key in YAML."""

    def test_missing_integration_gate_uses_defaults(self):
        """No integration_gate key -> all defaults applied."""
        cfg, _ = _dict_to_config({})
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True
        assert cfg.integration_gate.verification_mode == "block"
        assert cfg.integration_gate.contract_extraction is True

    def test_other_config_sections_unaffected(self):
        """Setting other config sections does not affect integration_gate defaults."""
        cfg, _ = _dict_to_config({
            "orchestrator": {"model": "sonnet"},
            "depth": {"default": "thorough"},
        })
        assert cfg.orchestrator.model == "sonnet"
        assert cfg.depth.default == "thorough"
        # integration_gate should still have defaults
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True

    def test_empty_yaml_file(self, tmp_path):
        """An empty YAML config file does not break integration_gate defaults."""
        p = tmp_path / "config.yaml"
        p.write_text("", encoding="utf-8")
        cfg, _ = load_config(config_path=str(p))
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True

    def test_yaml_with_null_integration_gate(self):
        """integration_gate: null in YAML preserves defaults (non-dict is ignored)."""
        cfg, _ = _dict_to_config({"integration_gate": None})
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True

    def test_yaml_with_empty_dict_integration_gate(self):
        """integration_gate: {} in YAML preserves all defaults."""
        cfg, _ = _dict_to_config({"integration_gate": {}})
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True
        assert cfg.integration_gate.verification_mode == "block"
        assert cfg.integration_gate.contract_injection_max_chars == 15000

    def test_existing_configs_still_load(self, tmp_path):
        """A config file with only pre-existing keys (no integration_gate) loads fine."""
        data = {
            "orchestrator": {"model": "opus", "max_turns": 300},
            "depth": {"default": "standard"},
            "convergence": {"max_cycles": 5},
            "milestone": {"enabled": True},
        }
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(data), encoding="utf-8")
        cfg, _ = load_config(config_path=str(p))
        assert cfg.orchestrator.model == "opus"
        assert cfg.orchestrator.max_turns == 300
        assert cfg.milestone.enabled is True
        # integration_gate should be present with defaults
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True
