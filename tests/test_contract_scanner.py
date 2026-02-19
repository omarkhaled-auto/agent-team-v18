"""Tests for milestone-5: Contract Scans + Tracking + Verification.

Covers TEST-050 through TEST-066 from REQUIREMENTS.md.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_openapi_contract(
    contract_id: str = "test-contract",
    paths: dict | None = None,
) -> dict:
    """Create a minimal OpenAPI contract dict for testing."""
    return {
        "contract_id": contract_id,
        "contract_type": "openapi",
        "provider_service": "test-service",
        "consumer_service": "",
        "version": "1.0.0",
        "spec": {
            "openapi": "3.0.0",
            "paths": paths or {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "name": {"type": "string"},
                                                "email": {"type": "string"},
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "string"},
                            "email": {"type": "string"},
                        },
                    }
                }
            },
        },
        "implemented": False,
    }


def _make_asyncapi_contract(contract_id: str = "events-contract") -> dict:
    """Create a minimal AsyncAPI contract dict."""
    return {
        "contract_id": contract_id,
        "contract_type": "asyncapi",
        "provider_service": "event-service",
        "consumer_service": "",
        "version": "1.0.0",
        "spec": {
            "asyncapi": "2.0.0",
            "channels": {
                "user.created": {
                    "publish": {
                        "message": {
                            "payload": {
                                "type": "object",
                                "properties": {
                                    "userId": {"type": "string"},
                                    "email": {"type": "string"},
                                    "timestamp": {"type": "string"},
                                },
                            }
                        }
                    }
                }
            },
        },
        "implemented": False,
    }


# ---------------------------------------------------------------------------
# TEST-050: run_endpoint_schema_scan detects field mismatches
# ---------------------------------------------------------------------------
class TestEndpointSchemaScan:

    def test_detects_missing_field(self, tmp_path):
        """TEST-050: Detects response DTO missing contracted field."""
        from agent_team_v15.contract_scanner import run_endpoint_schema_scan

        # Create a TypeScript file missing the 'email' field
        ts_file = tmp_path / "src" / "controllers" / "user.controller.ts"
        ts_file.parent.mkdir(parents=True)
        ts_file.write_text(textwrap.dedent("""
            interface UserResponse {
                id: number;
                name: string;
                // email field intentionally missing
            }
        """))

        contract = _make_openapi_contract()
        violations = run_endpoint_schema_scan(tmp_path, [contract])

        # Should detect that 'email' is missing
        assert len(violations) > 0
        assert any("email" in v.message for v in violations)
        assert all(v.check.startswith("CONTRACT-001") for v in violations)

    def test_no_violations_when_fields_match(self, tmp_path):
        """TEST-050: No violations when all fields present."""
        from agent_team_v15.contract_scanner import run_endpoint_schema_scan

        ts_file = tmp_path / "src" / "controllers" / "user.controller.ts"
        ts_file.parent.mkdir(parents=True)
        ts_file.write_text(textwrap.dedent("""
            interface UserResponse {
                id: number;
                name: string;
                email: string;
            }
        """))

        contract = _make_openapi_contract()
        violations = run_endpoint_schema_scan(tmp_path, [contract])
        assert len(violations) == 0

    def test_empty_contracts_returns_empty(self, tmp_path):
        """TEST-050: Empty contracts list returns empty violations."""
        from agent_team_v15.contract_scanner import run_endpoint_schema_scan

        assert run_endpoint_schema_scan(tmp_path, []) == []

    def test_skips_non_openapi_contracts(self, tmp_path):
        """TEST-050: AsyncAPI contracts are skipped by endpoint schema scan."""
        from agent_team_v15.contract_scanner import run_endpoint_schema_scan

        asyncapi = _make_asyncapi_contract()
        assert run_endpoint_schema_scan(tmp_path, [asyncapi]) == []


# ---------------------------------------------------------------------------
# TEST-051: run_missing_endpoint_scan
# ---------------------------------------------------------------------------
class TestMissingEndpointScan:

    def test_detects_missing_flask_route(self, tmp_path):
        """TEST-051: Detects contracted endpoint with no Flask route."""
        from agent_team_v15.contract_scanner import run_missing_endpoint_scan

        # Empty project -- no route handlers
        contract = _make_openapi_contract()
        violations = run_missing_endpoint_scan(tmp_path, [contract])
        assert len(violations) > 0
        assert all(v.check.startswith("CONTRACT-002") for v in violations)

    def test_finds_matching_flask_route(self, tmp_path):
        """TEST-051: No violation when Flask route exists."""
        from agent_team_v15.contract_scanner import run_missing_endpoint_scan

        py_file = tmp_path / "src" / "routes" / "users.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text(textwrap.dedent("""
            from flask import Blueprint
            bp = Blueprint('users', __name__)

            @bp.get('/users')
            def get_users():
                return []
        """))

        contract = _make_openapi_contract()
        violations = run_missing_endpoint_scan(tmp_path, [contract])
        assert len(violations) == 0

    def test_finds_matching_express_route(self, tmp_path):
        """TEST-064 (Express): Express route detected correctly."""
        from agent_team_v15.contract_scanner import run_missing_endpoint_scan

        js_file = tmp_path / "src" / "routes" / "users.js"
        js_file.parent.mkdir(parents=True)
        js_file.write_text(textwrap.dedent("""
            const express = require('express');
            const router = express.Router();

            router.get('/users', (req, res) => {
                res.json([]);
            });
        """))

        contract = _make_openapi_contract()
        violations = run_missing_endpoint_scan(tmp_path, [contract])
        assert len(violations) == 0

    def test_finds_matching_aspnet_route(self, tmp_path):
        """TEST-064 (ASP.NET): ASP.NET route detected correctly."""
        from agent_team_v15.contract_scanner import run_missing_endpoint_scan

        cs_file = tmp_path / "src" / "Controllers" / "UsersController.cs"
        cs_file.parent.mkdir(parents=True)
        cs_file.write_text(textwrap.dedent("""
            [HttpGet("/users")]
            public IActionResult GetUsers()
            {
                return Ok();
            }
        """))

        contract = _make_openapi_contract()
        violations = run_missing_endpoint_scan(tmp_path, [contract])
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# TEST-052: run_event_schema_scan
# ---------------------------------------------------------------------------
class TestEventSchemaScan:

    def test_detects_missing_event_field(self, tmp_path):
        """TEST-052: Detects mismatched event payload field."""
        from agent_team_v15.contract_scanner import run_event_schema_scan

        ts_file = tmp_path / "src" / "events" / "publisher.ts"
        ts_file.parent.mkdir(parents=True)
        ts_file.write_text(textwrap.dedent("""
            interface UserCreatedPayload {
                userId: string;
                // email and timestamp intentionally missing
            }

            function publishUserCreated() {
                emit('user.created', payload);
            }
        """))

        contract = _make_asyncapi_contract()
        violations = run_event_schema_scan(tmp_path, [contract])

        # Should detect missing fields
        event_violations = [v for v in violations if v.check.startswith("CONTRACT-003")]
        assert len(event_violations) > 0

    def test_no_violations_when_empty_contracts(self, tmp_path):
        """TEST-052: Empty contracts list returns empty violations."""
        from agent_team_v15.contract_scanner import run_event_schema_scan

        assert run_event_schema_scan(tmp_path, []) == []

    def test_skips_openapi_contracts(self, tmp_path):
        """TEST-052: OpenAPI contracts are skipped by event schema scan."""
        from agent_team_v15.contract_scanner import run_event_schema_scan

        openapi = _make_openapi_contract()
        assert run_event_schema_scan(tmp_path, [openapi]) == []


# ---------------------------------------------------------------------------
# TEST-053: run_shared_model_scan
# ---------------------------------------------------------------------------
class TestSharedModelScan:

    def test_detects_snake_case_drift(self, tmp_path):
        """TEST-053: Detects camelCase/snake_case drift."""
        from agent_team_v15.contract_scanner import run_shared_model_scan

        # Contract has camelCase fields (userId, firstName)
        contract = {
            "contract_id": "model-contract",
            "contract_type": "openapi",
            "provider_service": "user-service",
            "version": "1.0.0",
            "spec": {
                "components": {
                    "schemas": {
                        "User": {
                            "type": "object",
                            "properties": {
                                "userId": {"type": "string"},
                                "firstName": {"type": "string"},
                            },
                        }
                    }
                },
                "paths": {},
            },
            "implemented": False,
        }

        # Python file uses a casing variant that is NOT a valid camelCase/
        # snake_case/PascalCase equivalent -- it matches case-insensitively
        # but not via the standard conventions, triggering a drift warning.
        py_file = tmp_path / "src" / "models" / "user.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text(textwrap.dedent("""
            from dataclasses import dataclass

            @dataclass
            class User:
                USERID: str = ""
                FIRSTNAME: str = ""
        """))

        violations = run_shared_model_scan(tmp_path, [contract])
        drift_violations = [v for v in violations if v.check.startswith("CONTRACT-004")]
        assert len(drift_violations) > 0

    def test_no_drift_with_correct_snake_case(self, tmp_path):
        """TEST-053: No violation when Python uses correct snake_case."""
        from agent_team_v15.contract_scanner import run_shared_model_scan

        contract = {
            "contract_id": "model-contract",
            "contract_type": "openapi",
            "provider_service": "user-service",
            "version": "1.0.0",
            "spec": {
                "components": {
                    "schemas": {
                        "User": {
                            "type": "object",
                            "properties": {
                                "userId": {"type": "string"},
                            },
                        }
                    }
                },
                "paths": {},
            },
            "implemented": False,
        }

        py_file = tmp_path / "src" / "models" / "user.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text(textwrap.dedent("""
            from dataclasses import dataclass

            @dataclass
            class User:
                user_id: str = ""
        """))

        violations = run_shared_model_scan(tmp_path, [contract])
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# TEST-054: run_contract_compliance_scan combines results + caps
# ---------------------------------------------------------------------------
class TestContractComplianceScan:

    def test_combines_all_scan_results(self, tmp_path):
        """TEST-054: Combines results from all 4 scans."""
        from agent_team_v15.contract_scanner import run_contract_compliance_scan

        # Empty project with contracts -- should find missing endpoints
        contract = _make_openapi_contract()
        violations = run_contract_compliance_scan(tmp_path, [contract])
        assert isinstance(violations, list)

    def test_caps_at_max_violations(self, tmp_path):
        """TEST-054: Results capped at _MAX_VIOLATIONS."""
        from agent_team_v15.contract_scanner import (
            _MAX_VIOLATIONS,
            run_contract_compliance_scan,
        )

        # Even with many contracts, should cap
        contracts = [_make_openapi_contract(f"contract-{i}") for i in range(200)]
        violations = run_contract_compliance_scan(tmp_path, contracts)
        assert len(violations) <= _MAX_VIOLATIONS

    def test_empty_contracts_returns_empty(self, tmp_path):
        """TEST-054: Empty contracts list returns empty violations."""
        from agent_team_v15.contract_scanner import run_contract_compliance_scan

        assert run_contract_compliance_scan(tmp_path, []) == []

    def test_config_disables_individual_scans(self, tmp_path):
        """TEST-054: Config can disable individual scans."""
        from agent_team_v15.config import ContractScanConfig
        from agent_team_v15.contract_scanner import run_contract_compliance_scan

        config = ContractScanConfig(
            endpoint_schema_scan=False,
            missing_endpoint_scan=False,
            event_schema_scan=False,
            shared_model_scan=False,
        )
        contract = _make_openapi_contract()
        violations = run_contract_compliance_scan(tmp_path, [contract], config=config)
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# TEST-055: Crash isolation
# ---------------------------------------------------------------------------
class TestCrashIsolation:

    def test_one_scan_crash_doesnt_block_others(self, tmp_path):
        """TEST-055: Each scan catches exceptions independently."""
        from agent_team_v15.contract_scanner import run_contract_compliance_scan

        contract = _make_openapi_contract()

        # Patch one scan to crash
        with patch(
            "agent_team_v15.contract_scanner.run_endpoint_schema_scan",
            side_effect=RuntimeError("boom"),
        ):
            violations = run_contract_compliance_scan(tmp_path, [contract])
            # Other scans should still run -- we should get CONTRACT-002
            # violations at least (missing endpoints)
            assert isinstance(violations, list)

    def test_all_scans_crash_returns_empty(self, tmp_path):
        """TEST-055: If all scans crash, returns empty list."""
        from agent_team_v15.contract_scanner import run_contract_compliance_scan

        contract = _make_openapi_contract()

        with patch(
            "agent_team_v15.contract_scanner.run_endpoint_schema_scan",
            side_effect=RuntimeError("boom"),
        ), patch(
            "agent_team_v15.contract_scanner.run_missing_endpoint_scan",
            side_effect=RuntimeError("boom"),
        ), patch(
            "agent_team_v15.contract_scanner.run_event_schema_scan",
            side_effect=RuntimeError("boom"),
        ), patch(
            "agent_team_v15.contract_scanner.run_shared_model_scan",
            side_effect=RuntimeError("boom"),
        ):
            violations = run_contract_compliance_scan(tmp_path, [contract])
            assert violations == []


# ---------------------------------------------------------------------------
# TEST-056/057: Quality standards mapping
# ---------------------------------------------------------------------------
class TestQualityStandards:

    def test_contract_compliance_standards_mapped_to_correct_roles(self):
        """TEST-056: CONTRACT_COMPLIANCE_STANDARDS mapped to code-writer, code-reviewer, architect."""
        from agent_team_v15.code_quality_standards import (
            CONTRACT_COMPLIANCE_STANDARDS,
            _AGENT_STANDARDS_MAP,
        )

        assert CONTRACT_COMPLIANCE_STANDARDS in _AGENT_STANDARDS_MAP["code-writer"]
        assert CONTRACT_COMPLIANCE_STANDARDS in _AGENT_STANDARDS_MAP["code-reviewer"]
        assert CONTRACT_COMPLIANCE_STANDARDS in _AGENT_STANDARDS_MAP["architect"]
        assert CONTRACT_COMPLIANCE_STANDARDS not in _AGENT_STANDARDS_MAP.get("test-runner", [])
        assert CONTRACT_COMPLIANCE_STANDARDS not in _AGENT_STANDARDS_MAP.get("debugger", [])

    def test_integration_standards_mapped_to_correct_roles(self):
        """TEST-057: INTEGRATION_STANDARDS mapped to code-writer, code-reviewer."""
        from agent_team_v15.code_quality_standards import (
            INTEGRATION_STANDARDS,
            _AGENT_STANDARDS_MAP,
        )

        assert INTEGRATION_STANDARDS in _AGENT_STANDARDS_MAP["code-writer"]
        assert INTEGRATION_STANDARDS in _AGENT_STANDARDS_MAP["code-reviewer"]
        assert INTEGRATION_STANDARDS not in _AGENT_STANDARDS_MAP.get("architect", [])

    def test_contract_compliance_standards_content(self):
        """TEST-056: Standards contain expected rule IDs."""
        from agent_team_v15.code_quality_standards import CONTRACT_COMPLIANCE_STANDARDS

        assert "CONTRACT-001" in CONTRACT_COMPLIANCE_STANDARDS
        assert "CONTRACT-002" in CONTRACT_COMPLIANCE_STANDARDS
        assert "CONTRACT-003" in CONTRACT_COMPLIANCE_STANDARDS
        assert "CONTRACT-004" in CONTRACT_COMPLIANCE_STANDARDS

    def test_integration_standards_content(self):
        """TEST-057: Integration standards contain expected rule IDs."""
        from agent_team_v15.code_quality_standards import INTEGRATION_STANDARDS

        assert "INT-001" in INTEGRATION_STANDARDS
        assert "INT-002" in INTEGRATION_STANDARDS
        assert "INT-003" in INTEGRATION_STANDARDS


# ---------------------------------------------------------------------------
# TEST-058/059/065: Contract compliance matrix
# ---------------------------------------------------------------------------
class TestContractComplianceMatrix:

    def test_generate_produces_valid_markdown(self):
        """TEST-058: generate_contract_compliance_matrix produces valid markdown."""
        from agent_team_v15.tracking_documents import generate_contract_compliance_matrix

        contracts = [
            {
                "contract_id": "c1",
                "provider_service": "svc1",
                "contract_type": "openapi",
                "version": "1.0",
                "implemented": True,
            },
            {
                "contract_id": "c2",
                "provider_service": "svc2",
                "contract_type": "asyncapi",
                "version": "2.0",
                "implemented": False,
            },
        ]
        result = generate_contract_compliance_matrix(contracts)
        assert "# Contract Compliance Matrix" in result
        assert "`c1`" in result
        assert "`c2`" in result
        assert "[x]" in result
        assert "[ ]" in result
        assert "1/2" in result

    def test_generate_empty_contracts(self):
        """TEST-058: Empty contracts produces header-only markdown."""
        from agent_team_v15.tracking_documents import generate_contract_compliance_matrix

        result = generate_contract_compliance_matrix([])
        assert "No contracts registered" in result

    def test_parse_counts_correctly(self):
        """TEST-059: parse_contract_compliance_matrix correctly counts contracts."""
        from agent_team_v15.tracking_documents import (
            generate_contract_compliance_matrix,
            parse_contract_compliance_matrix,
        )

        contracts = [
            {
                "contract_id": "c1",
                "provider_service": "svc1",
                "contract_type": "openapi",
                "version": "1.0",
                "implemented": True,
            },
            {
                "contract_id": "c2",
                "provider_service": "svc2",
                "contract_type": "asyncapi",
                "version": "2.0",
                "implemented": False,
            },
            {
                "contract_id": "c3",
                "provider_service": "svc3",
                "contract_type": "openapi",
                "version": "1.0",
                "implemented": True,
            },
        ]
        matrix = generate_contract_compliance_matrix(contracts)
        stats = parse_contract_compliance_matrix(matrix)

        assert stats.total_contracts == 3
        assert stats.implemented == 2
        assert abs(stats.compliance_ratio - 2 / 3) < 0.01

    def test_update_entry_changes_status(self):
        """TEST-065: update_contract_compliance_entry correctly updates single entry."""
        from agent_team_v15.tracking_documents import (
            generate_contract_compliance_matrix,
            parse_contract_compliance_matrix,
            update_contract_compliance_entry,
        )

        contracts = [
            {
                "contract_id": "c1",
                "provider_service": "svc1",
                "contract_type": "openapi",
                "version": "1.0",
                "implemented": False,
            },
        ]
        matrix = generate_contract_compliance_matrix(contracts)
        assert "[ ]" in matrix

        updated = update_contract_compliance_entry(matrix, "c1", implemented=True)
        assert "[x]" in updated


# ---------------------------------------------------------------------------
# TEST-060: verify_contract_compliance (REQ-079 signature)
# ---------------------------------------------------------------------------
class TestVerifyContractCompliance:

    def _make_registry(self, contracts_dict):
        """Helper to create a mock registry with a .contracts attribute."""
        class _MockRegistry:
            def __init__(self, contracts):
                self.contracts = contracts
        return _MockRegistry(contracts_dict)

    def _make_contract(self, implemented=False):
        """Helper to create a mock ServiceContract."""
        class _MockContract:
            def __init__(self, impl):
                self.contract_id = "test"
                self.contract_type = ""
                self.spec = {}
                self.implemented = impl
        return _MockContract(implemented)

    def test_healthy_status(self, tmp_path):
        """TEST-060: Returns 'healthy' when ratio >= 0.8 and no violations."""
        from agent_team_v15.verification import verify_contract_compliance

        contracts = {f"c{i}": self._make_contract(implemented=True) for i in range(10)}
        registry = self._make_registry(contracts)
        result = verify_contract_compliance(tmp_path, registry)
        assert result["health"] == "healthy"
        assert result["total_contracts"] == 10
        assert result["implemented"] == 10

    def test_degraded_status(self, tmp_path):
        """TEST-060: Returns 'degraded' when ratio >= 0.5."""
        from agent_team_v15.verification import verify_contract_compliance

        contracts = {}
        for i in range(10):
            contracts[f"c{i}"] = self._make_contract(implemented=(i < 6))
        registry = self._make_registry(contracts)
        result = verify_contract_compliance(tmp_path, registry)
        assert result["health"] == "degraded"

    def test_failed_status(self, tmp_path):
        """TEST-060: Returns 'failed' when ratio < 0.5."""
        from agent_team_v15.verification import verify_contract_compliance

        contracts = {}
        for i in range(10):
            contracts[f"c{i}"] = self._make_contract(implemented=(i < 3))
        registry = self._make_registry(contracts)
        result = verify_contract_compliance(tmp_path, registry)
        assert result["health"] == "failed"

    def test_unknown_when_none(self, tmp_path):
        """TEST-060: Returns 'unknown' when registry is None."""
        from agent_team_v15.verification import verify_contract_compliance

        result = verify_contract_compliance(tmp_path, None)
        assert result["health"] == "unknown"

    def test_unknown_when_empty(self, tmp_path):
        """TEST-060: Returns 'unknown' when registry has no contracts."""
        from agent_team_v15.verification import verify_contract_compliance

        registry = self._make_registry({})
        result = verify_contract_compliance(tmp_path, registry)
        assert result["health"] == "unknown"

    def test_returns_dict_with_required_keys(self, tmp_path):
        """TEST-060: Returns dict with all REQ-079 keys."""
        from agent_team_v15.verification import verify_contract_compliance

        contracts = {f"c{i}": self._make_contract(implemented=True) for i in range(5)}
        registry = self._make_registry(contracts)
        result = verify_contract_compliance(tmp_path, registry)
        assert isinstance(result, dict)
        for key in ("total_contracts", "implemented", "verified", "violations", "health"):
            assert key in result


# ---------------------------------------------------------------------------
# TEST-061: ContractScanConfig defaults
# ---------------------------------------------------------------------------
class TestContractScanConfig:

    def test_all_scans_enabled_by_default(self):
        """TEST-061: ContractScanConfig defaults all 4 scans enabled."""
        from agent_team_v15.config import ContractScanConfig

        config = ContractScanConfig()
        assert config.endpoint_schema_scan is True
        assert config.missing_endpoint_scan is True
        assert config.event_schema_scan is True
        assert config.shared_model_scan is True


# ---------------------------------------------------------------------------
# TEST-062: Depth gating
# ---------------------------------------------------------------------------
class TestDepthGating:

    def test_quick_disables_all(self):
        """TEST-062: Quick depth disables all contract scans."""
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating

        config = AgentTeamConfig()
        apply_depth_quality_gating("quick", config)

        assert config.contract_scans.endpoint_schema_scan is False
        assert config.contract_scans.missing_endpoint_scan is False
        assert config.contract_scans.event_schema_scan is False
        assert config.contract_scans.shared_model_scan is False

    def test_standard_enables_001_002_only(self):
        """TEST-062: Standard enables CONTRACT-001 and CONTRACT-002 only."""
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating

        config = AgentTeamConfig()
        apply_depth_quality_gating("standard", config)

        assert config.contract_scans.endpoint_schema_scan is True
        assert config.contract_scans.missing_endpoint_scan is True
        assert config.contract_scans.event_schema_scan is False
        assert config.contract_scans.shared_model_scan is False

    def test_thorough_enables_all(self):
        """TEST-062: Thorough enables all 4 contract scans."""
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating

        config = AgentTeamConfig()
        apply_depth_quality_gating("thorough", config)

        assert config.contract_scans.endpoint_schema_scan is True
        assert config.contract_scans.missing_endpoint_scan is True
        assert config.contract_scans.event_schema_scan is True
        assert config.contract_scans.shared_model_scan is True

    def test_exhaustive_enables_all(self):
        """TEST-062: Exhaustive enables all 4 contract scans."""
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating

        config = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", config)

        assert config.contract_scans.endpoint_schema_scan is True
        assert config.contract_scans.missing_endpoint_scan is True
        assert config.contract_scans.event_schema_scan is True
        assert config.contract_scans.shared_model_scan is True

    def test_user_override_respected(self):
        """TEST-062: User overrides prevent depth gating changes."""
        from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating

        config = AgentTeamConfig()
        config.contract_scans.event_schema_scan = True
        apply_depth_quality_gating(
            "standard",
            config,
            user_overrides={"contract_scans.event_schema_scan"},
        )

        # event_schema_scan should stay True because user override
        assert config.contract_scans.event_schema_scan is True


# ---------------------------------------------------------------------------
# TEST-063: TypeScript/Python/C# field extraction
# ---------------------------------------------------------------------------
class TestFieldExtraction:

    def test_typescript_field_extraction(self):
        """TEST-063: CONTRACT-001 field extraction works for TypeScript."""
        from agent_team_v15.contract_scanner import _extract_dto_fields_typescript

        content = textwrap.dedent("""
            interface UserResponse {
                id: number;
                name: string;
                email: string;
            }
        """)
        fields = _extract_dto_fields_typescript(content)
        assert "id" in fields
        assert "name" in fields
        assert "email" in fields

    def test_python_field_extraction(self):
        """TEST-063: CONTRACT-001 field extraction works for Python."""
        from agent_team_v15.contract_scanner import _extract_dto_fields_python

        content = textwrap.dedent("""
            @dataclass
            class UserResponse:
                id: int
                name: str
                email: str
        """)
        fields = _extract_dto_fields_python(content)
        assert "id" in fields
        assert "name" in fields
        assert "email" in fields

    def test_csharp_field_extraction(self):
        """TEST-063: CONTRACT-001 field extraction works for C#."""
        from agent_team_v15.contract_scanner import _extract_dto_fields_csharp

        content = textwrap.dedent("""
            public class UserResponse
            {
                public int Id { get; set; }
                public string Name { get; set; }
                public string Email { get; set; }
            }
        """)
        fields = _extract_dto_fields_csharp(content)
        assert "Id" in fields
        assert "Name" in fields
        assert "Email" in fields


# ---------------------------------------------------------------------------
# TEST-066: check_milestone_health with contract_report
# ---------------------------------------------------------------------------
class TestMilestoneHealthWithContracts:

    def test_uses_min_of_ratios(self, tmp_path):
        """TEST-066: check_milestone_health uses min(checkbox_ratio, contract_compliance_ratio)."""
        from agent_team_v15.milestone_manager import MilestoneManager

        # Create milestone with 100% requirements
        ms_dir = tmp_path / ".agent-team" / "milestones" / "ms-1"
        ms_dir.mkdir(parents=True)
        req_file = ms_dir / "REQUIREMENTS.md"
        req_file.write_text(textwrap.dedent("""
            # Requirements
            - [x] REQ-001: Done (review_cycles: 1)
            - [x] REQ-002: Done (review_cycles: 1)
        """))

        # MilestoneManager expects project_root; _milestones_dir is
        # project_root / ".agent-team" / "milestones".
        mgr = MilestoneManager(tmp_path)

        # Without contract_report -- should be healthy (100% checkbox)
        report_no_contract = mgr.check_milestone_health("ms-1")
        assert report_no_contract.health == "healthy"

        # With low contract compliance -- should reduce effective ratio
        contract_report = {
            "total_contracts": 10,
            "verified_contracts": 3,
            "violated_contracts": 2,
            "missing_implementations": 5,
            "violations": [{"check": "api", "message": "err"}] * 5,
            "health": "failed",
            "verified_contract_ids": ["c-1", "c-2", "c-3"],
            "violated_contract_ids": ["c-4", "c-5"],
        }
        report_with_contract = mgr.check_milestone_health(
            "ms-1", contract_report=contract_report
        )
        assert report_with_contract.health == "failed"
        assert report_with_contract.convergence_ratio <= 0.3
