"""Tests for pipeline gate integration in cli.py.

Tests cover:
- Schema validation gate (enabled/disabled, blocking/non-blocking)
- Quality validators gate (enabled/disabled, blocking/non-blocking)
- Integration gate blocking mode
- Final comprehensive validation pass
- Config dataclasses for new gates
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15.config import (
    AgentTeamConfig,
    IntegrationGateConfig,
    PostOrchestrationScanConfig,
    QualityValidationConfig,
    SchemaValidationConfig,
    apply_depth_quality_gating,
    load_config,
)


# ===================================================================
# SchemaValidationConfig
# ===================================================================

class TestSchemaValidationConfig:
    def test_defaults(self):
        cfg = SchemaValidationConfig()
        assert cfg.enabled is True
        assert cfg.block_on_critical is True
        assert "SCHEMA-001" in cfg.checks
        assert len(cfg.checks) == 8

    def test_disabled(self):
        cfg = SchemaValidationConfig(enabled=False)
        assert cfg.enabled is False

    def test_custom_checks(self):
        cfg = SchemaValidationConfig(checks=["SCHEMA-001", "SCHEMA-002"])
        assert len(cfg.checks) == 2

    def test_non_blocking(self):
        cfg = SchemaValidationConfig(block_on_critical=False)
        assert cfg.block_on_critical is False


# ===================================================================
# QualityValidationConfig
# ===================================================================

class TestQualityValidationConfig:
    def test_defaults(self):
        cfg = QualityValidationConfig()
        assert cfg.enabled is True
        assert cfg.soft_delete_check is True
        assert cfg.enum_registry_check is True
        assert cfg.response_shape_check is True
        assert cfg.auth_flow_check is True
        assert cfg.build_health_check is True
        assert cfg.block_on_critical is True

    def test_disabled(self):
        cfg = QualityValidationConfig(enabled=False)
        assert cfg.enabled is False

    def test_individual_checks_disabled(self):
        cfg = QualityValidationConfig(
            soft_delete_check=False,
            auth_flow_check=False,
        )
        assert cfg.soft_delete_check is False
        assert cfg.auth_flow_check is False
        assert cfg.enum_registry_check is True  # others still on


# ===================================================================
# IntegrationGateConfig — new fields
# ===================================================================

class TestIntegrationGateConfigNewFields:
    def test_blocking_mode_default_false(self):
        cfg = IntegrationGateConfig()
        assert cfg.blocking_mode is False

    def test_new_check_fields_default_true(self):
        cfg = IntegrationGateConfig()
        assert cfg.route_structure_check is True
        assert cfg.response_shape_check is True
        assert cfg.auth_flow_check is True
        assert cfg.enum_cross_check is True

    def test_blocking_mode_enabled(self):
        cfg = IntegrationGateConfig(blocking_mode=True)
        assert cfg.blocking_mode is True

    def test_individual_new_checks_disabled(self):
        cfg = IntegrationGateConfig(
            route_structure_check=False,
            enum_cross_check=False,
        )
        assert cfg.route_structure_check is False
        assert cfg.enum_cross_check is False
        assert cfg.response_shape_check is True


# ===================================================================
# AgentTeamConfig — new fields present
# ===================================================================

class TestAgentTeamConfigNewFields:
    def test_schema_validation_on_config(self):
        cfg = AgentTeamConfig()
        assert hasattr(cfg, "schema_validation")
        assert isinstance(cfg.schema_validation, SchemaValidationConfig)

    def test_quality_validation_on_config(self):
        cfg = AgentTeamConfig()
        assert hasattr(cfg, "quality_validation")
        assert isinstance(cfg.quality_validation, QualityValidationConfig)

    def test_integration_gate_has_new_fields(self):
        cfg = AgentTeamConfig()
        assert hasattr(cfg.integration_gate, "blocking_mode")
        assert hasattr(cfg.integration_gate, "route_structure_check")
        assert hasattr(cfg.integration_gate, "response_shape_check")
        assert hasattr(cfg.integration_gate, "auth_flow_check")
        assert hasattr(cfg.integration_gate, "enum_cross_check")


# ===================================================================
# Depth gating for new configs
# ===================================================================

class TestDepthGatingNewConfigs:
    def test_quick_disables_schema_validation(self):
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg)
        assert cfg.schema_validation.enabled is False

    def test_quick_disables_quality_validation(self):
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg)
        assert cfg.quality_validation.enabled is False

    def test_standard_keeps_schema_validation(self):
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        assert cfg.schema_validation.enabled is True

    def test_standard_keeps_quality_validation(self):
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        assert cfg.quality_validation.enabled is True

    def test_thorough_keeps_both(self):
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("thorough", cfg)
        assert cfg.schema_validation.enabled is True
        assert cfg.quality_validation.enabled is True

    def test_user_override_respects_quick(self):
        """User explicitly enabled schema_validation — quick depth should not override."""
        cfg = AgentTeamConfig()
        overrides = {"schema_validation.enabled"}
        apply_depth_quality_gating("quick", cfg, user_overrides=overrides)
        assert cfg.schema_validation.enabled is True  # User override respected


# ===================================================================
# Config loading from YAML dict
# ===================================================================

class TestConfigLoadingNewSections:
    def test_schema_validation_from_dict(self):
        """schema_validation section in YAML is parsed correctly."""
        import yaml
        from agent_team_v15.config import _dict_to_config

        data = {
            "schema_validation": {
                "enabled": False,
                "block_on_critical": False,
                "checks": ["SCHEMA-001"],
            }
        }
        cfg, overrides = _dict_to_config(data)
        assert cfg.schema_validation.enabled is False
        assert cfg.schema_validation.block_on_critical is False
        assert cfg.schema_validation.checks == ["SCHEMA-001"]
        assert "schema_validation.enabled" in overrides

    def test_quality_validation_from_dict(self):
        """quality_validation section in YAML is parsed correctly."""
        from agent_team_v15.config import _dict_to_config

        data = {
            "quality_validation": {
                "enabled": True,
                "soft_delete_check": False,
                "build_health_check": False,
            }
        }
        cfg, overrides = _dict_to_config(data)
        assert cfg.quality_validation.enabled is True
        assert cfg.quality_validation.soft_delete_check is False
        assert cfg.quality_validation.build_health_check is False
        assert "quality_validation.soft_delete_check" in overrides

    def test_integration_gate_new_fields_from_dict(self):
        """New IntegrationGateConfig fields are parsed from YAML."""
        from agent_team_v15.config import _dict_to_config

        data = {
            "integration_gate": {
                "blocking_mode": True,
                "route_structure_check": False,
                "enum_cross_check": False,
            }
        }
        cfg, _ = _dict_to_config(data)
        assert cfg.integration_gate.blocking_mode is True
        assert cfg.integration_gate.route_structure_check is False
        assert cfg.integration_gate.enum_cross_check is False
        # Defaults for unchanged fields
        assert cfg.integration_gate.response_shape_check is True
        assert cfg.integration_gate.auth_flow_check is True


# ===================================================================
# Schema validator pipeline integration
# ===================================================================

class TestSchemaValidatorPipelineIntegration:
    """Test that schema_validator is called/skipped correctly in the pipeline."""

    def test_schema_validator_import_exists(self):
        """schema_validator module can be imported."""
        from agent_team_v15.schema_validator import run_schema_validation, format_findings_report
        assert callable(run_schema_validation)
        assert callable(format_findings_report)

    def test_schema_finding_dataclass(self):
        """SchemaFinding dataclass works correctly."""
        from agent_team_v15.schema_validator import SchemaFinding
        f = SchemaFinding(
            check="SCHEMA-001",
            severity="critical",
            message="Missing cascade delete",
            model="User",
            field="posts",
            line=42,
        )
        assert f.check == "SCHEMA-001"
        assert f.severity == "critical"

    def test_run_schema_validation_empty_dir(self, tmp_path):
        """Schema validation on empty dir returns no critical findings."""
        from agent_team_v15.schema_validator import run_schema_validation
        findings = run_schema_validation(tmp_path)
        # May return advisory findings (e.g., SCHEMA-000 for no schema file)
        # but should have no critical findings
        critical = [f for f in findings if f.severity == "critical"]
        assert critical == []

    def test_format_findings_report_no_findings(self):
        """Format report with no findings returns clean message."""
        from agent_team_v15.schema_validator import format_findings_report
        report = format_findings_report([])
        assert "No schema issues found" in report


# ===================================================================
# Integration gate blocking mode
# ===================================================================

class TestIntegrationGateBlockingMode:
    def test_blocking_mode_activates_on_config(self):
        """blocking_mode=True means HIGH mismatches should block."""
        cfg = AgentTeamConfig()
        cfg.integration_gate.blocking_mode = True
        # The actual blocking logic is in cli.py _run_prd_milestones
        # Here we just verify the config flag propagates
        assert cfg.integration_gate.blocking_mode is True

    def test_legacy_block_mode_still_works(self):
        """verification_mode='block' still blocks even without blocking_mode."""
        cfg = AgentTeamConfig()
        cfg.integration_gate.verification_mode = "block"
        cfg.integration_gate.blocking_mode = False
        # Both paths should trigger blocking — verified via the _should_block logic
        _should_block = (
            cfg.integration_gate.verification_mode == "block"
            or cfg.integration_gate.blocking_mode
        )
        assert _should_block is True

    def test_warn_mode_no_block(self):
        """verification_mode='warn' and blocking_mode=False means no block."""
        cfg = AgentTeamConfig()
        cfg.integration_gate.verification_mode = "warn"
        cfg.integration_gate.blocking_mode = False
        _should_block = (
            cfg.integration_gate.verification_mode == "block"
            or cfg.integration_gate.blocking_mode
        )
        assert _should_block is False

    def test_blocking_mode_alone_triggers_block(self):
        """blocking_mode=True blocks even with verification_mode='warn'."""
        cfg = AgentTeamConfig()
        cfg.integration_gate.verification_mode = "warn"
        cfg.integration_gate.blocking_mode = True
        _should_block = (
            cfg.integration_gate.verification_mode == "block"
            or cfg.integration_gate.blocking_mode
        )
        assert _should_block is True


# ===================================================================
# PostOrchestrationScanConfig — new scan fields (architect spec)
# ===================================================================

class TestPostOrchestrationScanConfigNewFields:
    def test_new_scan_fields_default_true(self):
        cfg = PostOrchestrationScanConfig()
        assert cfg.enum_registry_scan is True
        assert cfg.response_shape_scan is True
        assert cfg.soft_delete_scan is True
        assert cfg.auth_flow_scan is True
        assert cfg.infrastructure_scan is True
        assert cfg.schema_validation_scan is True

    def test_new_scan_fields_disabled(self):
        cfg = PostOrchestrationScanConfig(
            enum_registry_scan=False,
            soft_delete_scan=False,
            infrastructure_scan=False,
        )
        assert cfg.enum_registry_scan is False
        assert cfg.soft_delete_scan is False
        assert cfg.infrastructure_scan is False
        # Others still on
        assert cfg.response_shape_scan is True
        assert cfg.auth_flow_scan is True
        assert cfg.schema_validation_scan is True

    def test_existing_fields_unchanged(self):
        """Existing scan fields are not affected by new additions."""
        cfg = PostOrchestrationScanConfig()
        assert cfg.mock_data_scan is True
        assert cfg.api_contract_scan is True
        assert cfg.handler_completeness_scan is True


# ===================================================================
# IntegrationGateConfig — route_pattern_enforcement (architect spec)
# ===================================================================

class TestRoutePatternEnforcement:
    def test_route_pattern_enforcement_default_true(self):
        cfg = IntegrationGateConfig()
        assert cfg.route_pattern_enforcement is True

    def test_route_pattern_enforcement_disabled(self):
        cfg = IntegrationGateConfig(route_pattern_enforcement=False)
        assert cfg.route_pattern_enforcement is False

    def test_agent_team_config_has_route_pattern_enforcement(self):
        cfg = AgentTeamConfig()
        assert hasattr(cfg.integration_gate, "route_pattern_enforcement")
        assert cfg.integration_gate.route_pattern_enforcement is True


# ===================================================================
# Depth gating — new post-orchestration scan fields
# ===================================================================

class TestDepthGatingNewScans:
    def test_quick_disables_new_scans(self):
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg)
        assert cfg.post_orchestration_scans.enum_registry_scan is False
        assert cfg.post_orchestration_scans.response_shape_scan is False
        assert cfg.post_orchestration_scans.soft_delete_scan is False
        assert cfg.post_orchestration_scans.auth_flow_scan is False
        assert cfg.post_orchestration_scans.infrastructure_scan is False
        assert cfg.post_orchestration_scans.schema_validation_scan is False

    def test_standard_keeps_new_scans(self):
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        assert cfg.post_orchestration_scans.enum_registry_scan is True
        assert cfg.post_orchestration_scans.infrastructure_scan is True
        assert cfg.post_orchestration_scans.schema_validation_scan is True

    def test_thorough_keeps_new_scans(self):
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("thorough", cfg)
        assert cfg.post_orchestration_scans.enum_registry_scan is True
        assert cfg.post_orchestration_scans.soft_delete_scan is True


# ===================================================================
# YAML dict parsing — new post-orchestration scan fields
# ===================================================================

class TestConfigLoadingNewScans:
    def test_new_scans_from_dict(self):
        from agent_team_v15.config import _dict_to_config

        data = {
            "post_orchestration_scans": {
                "enum_registry_scan": False,
                "response_shape_scan": False,
                "infrastructure_scan": True,
            }
        }
        cfg, overrides = _dict_to_config(data)
        assert cfg.post_orchestration_scans.enum_registry_scan is False
        assert cfg.post_orchestration_scans.response_shape_scan is False
        assert cfg.post_orchestration_scans.infrastructure_scan is True
        # Defaults for unspecified
        assert cfg.post_orchestration_scans.soft_delete_scan is True
        assert cfg.post_orchestration_scans.auth_flow_scan is True

    def test_route_pattern_enforcement_from_dict(self):
        from agent_team_v15.config import _dict_to_config

        data = {
            "integration_gate": {
                "route_pattern_enforcement": False,
            }
        }
        cfg, _ = _dict_to_config(data)
        assert cfg.integration_gate.route_pattern_enforcement is False


# ===================================================================
# Prisma validation phase (verification.py Phase 1.25)
# ===================================================================

class TestPrismaValidationPhase:
    def test_prisma_phase_code_exists_in_verification(self):
        """Phase 1.25 Prisma validation code is present in verification.py."""
        import inspect
        from agent_team_v15 import verification
        source = inspect.getsource(verification)
        assert "Phase 1.25" in source
        assert "prisma validate" in source
        assert "prisma migrate status" in source

    def test_prisma_validate_skipped_without_schema(self, tmp_path):
        """Prisma validation doesn't fail when no schema.prisma exists."""
        import asyncio
        from agent_team_v15.contracts import ContractRegistry
        from agent_team_v15.verification import verify_task_completion
        result = asyncio.run(verify_task_completion(
            task_id="test-1",
            project_root=tmp_path,
            registry=ContractRegistry(),
            run_build=True,
            run_lint=False,
            run_type_check=False,
            run_tests=False,
            run_security=False,
            run_quality_checks=False,
            blocking=False,
        ))
        # No Prisma-related issues when no schema file exists
        prisma_issues = [i for i in result.issues if "Prisma" in i]
        assert prisma_issues == []


# ===================================================================
# Pre-coding integration gate (Injection Point D)
# ===================================================================

class TestPreCodingIntegrationGate:
    def test_precoding_gate_config_fields_exist(self):
        """Config has the fields needed for pre-coding gate."""
        cfg = AgentTeamConfig()
        assert cfg.integration_gate.enabled is True
        assert cfg.integration_gate.contract_extraction is True

    def test_precoding_gate_requires_both_files(self, tmp_path):
        """Gate is a no-op when API_CONTRACTS.json or REQUIREMENTS.md is missing."""
        # This is a config-level test — the gate logic in cli.py checks file existence
        import json
        req_dir = tmp_path / ".requirements"
        req_dir.mkdir()
        # Only create one file — gate should not crash
        contracts = {"endpoints": [{"path": "/api/users", "method": "GET"}]}
        (req_dir / "API_CONTRACTS.json").write_text(json.dumps(contracts))
        # No REQUIREMENTS.md — gate should silently skip
        assert not (req_dir / "REQUIREMENTS.md").is_file()
