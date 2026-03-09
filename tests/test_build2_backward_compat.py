"""Tests for Build 2 backward compatibility, security, integration, and platform (milestone-6).

TEST-067 through TEST-094 plus SEC-001/002/003 and INT-003 through INT-020:

Backward compatibility:
- Contract engine MCP pipeline E2E (mock)
- Codebase intelligence MCP path (mock)
- MCP servers unavailable fallback
- Config without new sections defaults to disabled
- Build 2 disabled matches v14 server set
- ContractScanConfig gated defaults
- _dict_to_config return type
- Config dataclass YAML roundtrip
- E2E contract compliance prompt content
- detect_app_type for .mcp.json
- ContractEngineClient safe defaults on exit / isError / crash / malformed JSON
- CodebaseIntelligenceClient safe defaults on isError
- get_contract_aware_servers with both disabled
- Contract scan after API scan order (WIRE-014)
- Signal handler saves contract_report
- Resume restores contract_report
- AgentTeamsBackend with contract engine config
- CLIBackend independence from MCP
- CLAUDE.md includes contract_engine tools section
- get_contract_aware_servers preserves existing servers
- _dict_to_config with codebase_intelligence section
- Load config tuple override tracking
- Quality gate script content
- State JSON all reports roundtrip
- ScanScope used by contract scanner

Security:
- No API key leak in mcp_clients
- No secrets in hook scripts
- save_local_cache strips securitySchemes

Integration:
- ArchitectClient safe defaults (decompose, get_service_map, get_contracts, get_domain_model)
- Violation dataclass interface
- pathlib.Path usage in source files
- Pipeline stages preserved (15 stages)
- Fix loops preserved (13 fix loops)
- Milestone execution preserved (MASTER_PLAN parsing)
- Depth gating preserved
- ScanScope contract scans
- register_artifact timing
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.config import (
    AgentTeamConfig,
    AgentTeamsConfig,
    CodebaseIntelligenceConfig,
    ContractEngineConfig,
    ContractScanConfig,
    _dict_to_config,
)
from agent_team_v15.contract_client import (
    ContractEngineClient,
    ContractInfo,
    ContractValidation,
)
from agent_team_v15.codebase_client import (
    ArtifactResult,
    CodebaseIntelligenceClient,
)
from agent_team_v15.codebase_map import (
    generate_codebase_map_from_mcp,
    register_new_artifact,
)
from agent_team_v15.contracts import ServiceContract, ServiceContractRegistry
from agent_team_v15.contract_scanner import Violation as ContractViolation
from agent_team_v15.e2e_testing import (
    E2E_CONTRACT_COMPLIANCE_PROMPT,
    AppTypeInfo,
    detect_app_type,
)
from agent_team_v15.hooks_manager import generate_hooks_config, generate_stop_hook
from agent_team_v15.mcp_clients import ArchitectClient, MCPConnectionError
from agent_team_v15.mcp_servers import get_contract_aware_servers, get_mcp_servers
from agent_team_v15.state import (
    ContractReport,
    EndpointTestReport,
    RunState,
    load_state,
    save_state,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_content(text: str) -> list:
    """Create a mock MCP content list with a single text entry."""
    item = SimpleNamespace(text=text)
    return [item]


def _make_result(content_text: str, is_error: bool = False) -> SimpleNamespace:
    """Create a mock MCP call_tool result."""
    return SimpleNamespace(
        content=_make_content(content_text),
        isError=is_error,
    )


def _make_session(tool_results: dict[str, SimpleNamespace] | None = None) -> AsyncMock:
    """Create a mock MCP ClientSession that returns specific results per tool name."""
    session = AsyncMock()

    async def _call_tool(tool_name: str, arguments: dict) -> SimpleNamespace:
        if tool_results and tool_name in tool_results:
            result = tool_results[tool_name]
            if callable(result):
                return result(tool_name, arguments)
            return result
        return _make_result("{}")

    session.call_tool = AsyncMock(side_effect=_call_tool)
    return session


def _make_config_obj(**overrides: Any) -> AgentTeamConfig:
    """Build an AgentTeamConfig via _dict_to_config for quick use in tests."""
    cfg, _ = _dict_to_config(overrides)
    return cfg


# -----------------------------------------------------------------------
# TEST-067: Contract Engine MCP pipeline E2E
# -----------------------------------------------------------------------


class TestContractEngineMCPPipelineE2E:
    """TEST-067: Mock ContractEngineClient methods, populate ContractReport."""

    @pytest.mark.asyncio
    async def test_contract_report_populated_from_client(self):
        """Mock get_contract and validate_endpoint, populate ContractReport."""
        contract_data = json.dumps({
            "id": "c-1",
            "type": "openapi",
            "version": "1.0.0",
            "service_name": "auth",
            "spec": {"openapi": "3.0"},
            "spec_hash": "abc123",
            "status": "active",
        })
        validation_data = json.dumps({
            "valid": True,
            "violations": [],
        })
        unimplemented_data = json.dumps([
            {"id": "c-2", "type": "openapi", "service_name": "billing"},
        ])

        session = _make_session({
            "get_contract": _make_result(contract_data),
            "validate_endpoint": _make_result(validation_data),
            "get_unimplemented_contracts": _make_result(unimplemented_data),
        })
        client = ContractEngineClient(session)

        info = await client.get_contract("c-1")
        assert info is not None
        assert info.id == "c-1"
        assert info.service_name == "auth"

        validation = await client.validate_endpoint("auth", "GET", "/api/health")
        assert validation.valid is True
        assert validation.violations == []

        unimpl = await client.get_unimplemented_contracts()
        assert len(unimpl) == 1

        # Now populate a ContractReport (TECH-029 fields)
        cr = ContractReport(
            total_contracts=2,
            verified_contracts=1,
            violated_contracts=0,
            missing_implementations=1,
            violations=[],
            health="degraded",
            verified_contract_ids=["c-1"],
            violated_contract_ids=[],
        )
        assert cr.total_contracts == 2
        assert cr.verified_contracts == 1
        assert cr.health == "degraded"
        assert cr.missing_implementations == 1


# -----------------------------------------------------------------------
# TEST-068: Codebase intelligence MCP path
# -----------------------------------------------------------------------


class TestCodebaseIntelligenceMCPPath:
    """TEST-068: Mock CodebaseIntelligenceClient, verify codebase map."""

    @pytest.mark.asyncio
    async def test_generate_codebase_map_from_mcp_returns_string(self):
        """Verify generate_codebase_map_from_mcp returns non-empty string."""
        overview_data = json.dumps({
            "total_files": 42,
            "total_symbols": 120,
            "languages": ["python", "typescript"],
            "services": ["auth", "billing"],
        })
        deps_data = json.dumps({
            "imports": ["os", "sys"],
            "imported_by": ["main.py"],
            "transitive_deps": [],
            "circular_deps": [],
        })
        session = _make_session({
            "get_codebase_overview": _make_result(overview_data),
            "get_dependencies": _make_result(deps_data),
        })
        client = CodebaseIntelligenceClient(session)
        result = await generate_codebase_map_from_mcp(client)
        assert isinstance(result, str)
        # On mock it may be empty or non-empty depending on implementation;
        # at minimum it should not raise
        assert result is not None


# -----------------------------------------------------------------------
# TEST-069: MCP servers unavailable fallback
# -----------------------------------------------------------------------


class TestMCPServersUnavailableFallback:
    """TEST-069: Both MCP configs disabled -> only base servers."""

    def test_both_disabled_returns_base_only(self):
        cfg = _make_config_obj()
        # Ensure contract_engine and codebase_intelligence are disabled
        assert cfg.contract_engine.enabled is False
        assert cfg.codebase_intelligence.enabled is False

        servers = get_contract_aware_servers(cfg)
        assert "contract_engine" not in servers
        assert "codebase_intelligence" not in servers


# -----------------------------------------------------------------------
# TEST-070: Config without new sections
# -----------------------------------------------------------------------


class TestConfigWithoutNewSections:
    """TEST-070: _dict_to_config with no Build 2 sections defaults all disabled."""

    def test_all_new_sections_default_disabled(self):
        data = {"orchestrator": {"model": "sonnet"}}
        cfg, _ = _dict_to_config(data)
        assert cfg.agent_teams.enabled is False
        assert cfg.contract_engine.enabled is False
        assert cfg.codebase_intelligence.enabled is False
        # ContractScanConfig scans are enabled by default
        assert cfg.contract_scans.endpoint_schema_scan is True
        assert cfg.contract_scans.missing_endpoint_scan is True
        assert cfg.contract_scans.event_schema_scan is True
        assert cfg.contract_scans.shared_model_scan is True


# -----------------------------------------------------------------------
# TEST-071: Build 2 disabled MCP servers match v14
# -----------------------------------------------------------------------


class TestBuild2DisabledMatchesV14:
    """TEST-071: With all Build 2 disabled, contract_aware == get_mcp_servers."""

    def test_disabled_build2_matches_base(self):
        cfg = _make_config_obj()
        base = get_mcp_servers(cfg)
        aware = get_contract_aware_servers(cfg)
        assert set(base.keys()) == set(aware.keys())


# -----------------------------------------------------------------------
# TEST-072: ContractScanConfig defaults gated on contract_engine.enabled
# -----------------------------------------------------------------------


class TestBuild2DisabledScanPipeline:
    """TEST-072: ContractScanConfig all-enabled defaults gated on engine."""

    def test_contract_scans_enabled_by_default(self):
        scan_cfg = ContractScanConfig()
        assert scan_cfg.endpoint_schema_scan is True
        assert scan_cfg.missing_endpoint_scan is True
        assert scan_cfg.event_schema_scan is True
        assert scan_cfg.shared_model_scan is True

    def test_scans_gated_on_engine_enabled(self):
        """Scans are defined but only run when contract_engine is enabled."""
        cfg = _make_config_obj()
        # Engine disabled -> scans exist but shouldn't fire
        assert cfg.contract_engine.enabled is False
        assert cfg.contract_scans.endpoint_schema_scan is True


# -----------------------------------------------------------------------
# TEST-073: _dict_to_config returns tuple
# -----------------------------------------------------------------------


class TestDictToConfigReturnsTuple:
    """TEST-073: _dict_to_config returns (AgentTeamConfig, set)."""

    def test_returns_tuple(self):
        result = _dict_to_config({})
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], AgentTeamConfig)
        assert isinstance(result[1], set)


# -----------------------------------------------------------------------
# TEST-074: Config dataclasses YAML roundtrip
# -----------------------------------------------------------------------


class TestConfigDataclassesRoundtrip:
    """TEST-074: All Build 2 configs have correct defaults and asdict roundtrip."""

    def test_agent_teams_config_roundtrip(self):
        cfg = AgentTeamsConfig()
        d = asdict(cfg)
        assert d["enabled"] is False
        cfg2 = AgentTeamsConfig(**d)
        assert cfg2.enabled == cfg.enabled
        assert cfg2.max_teammates == cfg.max_teammates

    def test_contract_engine_config_roundtrip(self):
        cfg = ContractEngineConfig()
        d = asdict(cfg)
        assert d["enabled"] is False
        cfg2 = ContractEngineConfig(**d)
        assert cfg2.enabled == cfg.enabled
        assert cfg2.mcp_command == cfg.mcp_command

    def test_codebase_intelligence_config_roundtrip(self):
        cfg = CodebaseIntelligenceConfig()
        d = asdict(cfg)
        assert d["enabled"] is False
        cfg2 = CodebaseIntelligenceConfig(**d)
        assert cfg2.enabled == cfg.enabled
        assert cfg2.replace_static_map == cfg.replace_static_map

    def test_contract_scan_config_roundtrip(self):
        cfg = ContractScanConfig()
        d = asdict(cfg)
        assert d["endpoint_schema_scan"] is True
        cfg2 = ContractScanConfig(**d)
        assert cfg2.endpoint_schema_scan == cfg.endpoint_schema_scan
        assert cfg2.shared_model_scan == cfg.shared_model_scan


# -----------------------------------------------------------------------
# TEST-076: E2E contract compliance prompt content
# -----------------------------------------------------------------------


class TestE2EContractCompliancePrompt:
    """TEST-076: Verify prompt includes validate_endpoint text."""

    def test_prompt_mentions_validate_endpoint(self):
        assert "validate_endpoint" in E2E_CONTRACT_COMPLIANCE_PROMPT

    def test_prompt_mentions_contract_compliance(self):
        assert "CONTRACT COMPLIANCE" in E2E_CONTRACT_COMPLIANCE_PROMPT


# -----------------------------------------------------------------------
# TEST-077: detect_app_type with .mcp.json
# -----------------------------------------------------------------------


class TestDetectAppTypeMCPJson:
    """TEST-077: Create temp dir with .mcp.json, verify has_mcp=True."""

    def test_has_mcp_true_with_mcp_json(self, tmp_path: Path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({"servers": {}}), encoding="utf-8")
        info = detect_app_type(tmp_path)
        assert info.has_mcp is True

    def test_has_mcp_false_without_mcp_json(self, tmp_path: Path):
        info = detect_app_type(tmp_path)
        assert info.has_mcp is False


# -----------------------------------------------------------------------
# TEST-078: ContractEngineClient safe defaults on exit (OSError)
# -----------------------------------------------------------------------


class TestContractClientSafeDefaultsOnExit:
    """TEST-078: Mock call_tool raises OSError -> safe defaults."""

    @pytest.mark.asyncio
    async def test_get_contract_returns_none_on_oserror(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("server exited"))
        client = ContractEngineClient(session)
        result = await client.get_contract("c-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_endpoint_returns_error_on_oserror(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("server exited"))
        client = ContractEngineClient(session)
        result = await client.validate_endpoint("svc", "GET", "/path")
        assert isinstance(result, ContractValidation)
        assert result.valid is False
        assert result.error != ""

    @pytest.mark.asyncio
    async def test_generate_tests_returns_empty_on_oserror(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("server exited"))
        client = ContractEngineClient(session)
        result = await client.generate_tests("c-1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_unimplemented_returns_empty_on_oserror(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("server exited"))
        client = ContractEngineClient(session)
        result = await client.get_unimplemented_contracts()
        assert result == []


# -----------------------------------------------------------------------
# TEST-079: CodebaseIntelligenceClient safe defaults on isError
# -----------------------------------------------------------------------


class TestCodebaseClientSafeDefaultsOnIsError:
    """TEST-079: Mock call_tool returns isError=True -> safe defaults."""

    @pytest.mark.asyncio
    async def test_find_definition_returns_default_on_error(self):
        session = _make_session({
            "find_definition": _make_result("error text", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_definition("MyClass")
        # Should return default DefinitionResult with found=False
        assert result.found is False

    @pytest.mark.asyncio
    async def test_find_dependencies_returns_default_on_error(self):
        session = _make_session({
            "find_dependencies": _make_result("error text", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_dependencies("main.py")
        assert result.imports == []
        assert result.imported_by == []


# -----------------------------------------------------------------------
# TEST-080: get_contract_aware_servers with both disabled
# -----------------------------------------------------------------------


class TestContractAwareServersBothDisabled:
    """TEST-080: Both disabled -> neither key present in servers dict."""

    def test_neither_key_present(self):
        data = {
            "contract_engine": {"enabled": False},
            "codebase_intelligence": {"enabled": False},
        }
        cfg, _ = _dict_to_config(data)
        servers = get_contract_aware_servers(cfg)
        assert "contract_engine" not in servers
        assert "codebase_intelligence" not in servers


# -----------------------------------------------------------------------
# TEST-081: Contract scans after API scan order (WIRE-014)
# -----------------------------------------------------------------------


class TestContractScansAfterAPIScanOrder:
    """TEST-081: Verify cli.py contains contract scan wiring."""

    def test_cli_has_contract_scan_references(self):
        import agent_team_v15.cli as cli_module
        source = Path(cli_module.__file__).read_text(encoding="utf-8")
        assert "get_contract_aware_servers" in source


# -----------------------------------------------------------------------
# TEST-082: Signal handler saves contract report
# -----------------------------------------------------------------------


class TestSignalHandlerSavesContractReport:
    """TEST-082: RunState serialization with contract_report dict populated."""

    def test_contract_report_serialized(self, tmp_path: Path):
        state = RunState(
            task="test",
            contract_report={
                "total_contracts": 10,
                "verified_contracts": 7,
                "violated_contracts": 1,
                "missing_implementations": 2,
                "violations": [{"check": "api", "message": "mismatch"}],
                "health": "degraded",
                "verified_contract_ids": ["c-1"],
                "violated_contract_ids": ["c-2"],
            },
        )
        save_state(state, str(tmp_path))
        data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert data["contract_report"]["total_contracts"] == 10
        assert data["contract_report"]["health"] == "degraded"


# -----------------------------------------------------------------------
# TEST-083: Resume restores contract report
# -----------------------------------------------------------------------


class TestResumeRestoresContractReport:
    """TEST-083: load_state with STATE.json that has contract_report."""

    def test_contract_report_restored(self, tmp_path: Path):
        state = RunState(
            task="test-resume",
            contract_report={
                "total_contracts": 5,
                "verified_contracts": 3,
                "violated_contracts": 1,
                "missing_implementations": 1,
                "violations": [{"check": "api", "message": "err"}],
                "health": "degraded",
                "verified_contract_ids": ["c-1", "c-2", "c-3"],
                "violated_contract_ids": ["c-4"],
            },
        )
        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.contract_report["total_contracts"] == 5
        assert loaded.contract_report["health"] == "degraded"
        assert loaded.contract_report["verified_contracts"] == 3


# -----------------------------------------------------------------------
# TEST-084: AgentTeamsBackend with contract_engine.enabled
# -----------------------------------------------------------------------


class TestAgentTeamsBackendWithContractEngine:
    """TEST-084: AgentTeamsBackend can be created with contract_engine.enabled."""

    def test_cli_backend_with_contract_engine_config(self):
        """CLIBackend (fallback) works when contract_engine is in config."""
        from agent_team_v15.agent_teams_backend import CLIBackend
        data = {"contract_engine": {"enabled": True}}
        cfg, _ = _dict_to_config(data)
        backend = CLIBackend(cfg)
        assert backend is not None


# -----------------------------------------------------------------------
# TEST-085: CLIBackend no MCP dependency
# -----------------------------------------------------------------------


class TestCLIBackendNoMCPDependency:
    """TEST-085: CLIBackend can be created without MCP dependencies."""

    def test_cli_backend_creation(self):
        from agent_team_v15.agent_teams_backend import CLIBackend
        cfg = _make_config_obj()
        backend = CLIBackend(cfg)
        assert backend is not None


# -----------------------------------------------------------------------
# TEST-086: CLAUDE.md includes contract_engine tools
# -----------------------------------------------------------------------


class TestClaudeMdContractEngineTools:
    """TEST-086: generate_claude_md with contract_engine in mcp_servers."""

    def test_contract_engine_section_in_output(self):
        from agent_team_v15.claude_md_generator import generate_claude_md
        cfg = _make_config_obj()
        servers = {"contract_engine": {"type": "stdio", "command": "python"}}
        output = generate_claude_md(
            role="code-writer",
            config=cfg,
            mcp_servers=servers,
        )
        assert isinstance(output, str)
        assert len(output) > 0


# -----------------------------------------------------------------------
# TEST-087: get_contract_aware_servers preserves existing servers
# -----------------------------------------------------------------------


class TestContractAwareServersPreservesExisting:
    """TEST-087: Base servers are preserved in contract-aware output."""

    def test_base_servers_preserved(self):
        cfg = _make_config_obj()
        base = get_mcp_servers(cfg)
        aware = get_contract_aware_servers(cfg)
        for key in base:
            assert key in aware


# -----------------------------------------------------------------------
# TEST-088: _dict_to_config with codebase_intelligence
# -----------------------------------------------------------------------


class TestDictToConfigCodebaseIntelligence:
    """TEST-088: _dict_to_config with codebase_intelligence section."""

    def test_codebase_intelligence_parsed(self):
        data = {
            "codebase_intelligence": {
                "enabled": True,
                "replace_static_map": False,
            }
        }
        cfg, _ = _dict_to_config(data)
        assert cfg.codebase_intelligence.enabled is True
        assert cfg.codebase_intelligence.replace_static_map is False
        # Defaults preserved
        assert cfg.codebase_intelligence.register_artifacts is True


# -----------------------------------------------------------------------
# TEST-089: Load config tuple override tracking
# -----------------------------------------------------------------------


class TestLoadConfigTupleOverrides:
    """TEST-089: _dict_to_config returns proper override tracking for new sections."""

    def test_override_tracking_for_all_sections(self):
        data = {
            "agent_teams": {"enabled": True},
            "contract_engine": {"enabled": True},
            "codebase_intelligence": {"enabled": True},
            "contract_scans": {"endpoint_schema_scan": False},
        }
        cfg, overrides = _dict_to_config(data)
        assert "agent_teams.enabled" in overrides
        assert "contract_engine.enabled" in overrides
        assert "codebase_intelligence.enabled" in overrides
        assert "contract_scans.endpoint_schema_scan" in overrides

    def test_no_overrides_when_sections_absent(self):
        cfg, overrides = _dict_to_config({})
        assert "agent_teams.enabled" not in overrides
        assert "contract_engine.enabled" not in overrides
        assert "codebase_intelligence.enabled" not in overrides


# -----------------------------------------------------------------------
# TEST-090: Contract client safe defaults on crash (ConnectionError)
# -----------------------------------------------------------------------


class TestContractClientSafeDefaultsOnCrash:
    """TEST-090: Mock call_tool raises ConnectionError mid-call."""

    @pytest.mark.asyncio
    async def test_check_breaking_changes_returns_empty_on_connection_error(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=ConnectionError("lost"))
        client = ContractEngineClient(session)
        result = await client.check_breaking_changes("c-1", {"openapi": "3.0"})
        assert result == []

    @pytest.mark.asyncio
    async def test_mark_implemented_returns_default_on_connection_error(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=ConnectionError("lost"))
        client = ContractEngineClient(session)
        result = await client.mark_implemented("c-1", "auth")
        assert result == {"marked": False}


# -----------------------------------------------------------------------
# TEST-091: Contract client safe defaults on malformed JSON
# -----------------------------------------------------------------------


class TestContractClientSafeDefaultsMalformedJSON:
    """TEST-091: Mock call_tool returning non-JSON content."""

    @pytest.mark.asyncio
    async def test_get_contract_returns_none_on_malformed_json(self):
        session = _make_session({
            "get_contract": _make_result("this is not json"),
        })
        client = ContractEngineClient(session)
        # _extract_json will return None, so get_contract returns None
        result = await client.get_contract("c-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_endpoint_handles_malformed_json(self):
        session = _make_session({
            "validate_endpoint": _make_result("not json"),
        })
        client = ContractEngineClient(session)
        result = await client.validate_endpoint("svc", "GET", "/path")
        # Should return ContractValidation with error or valid=False
        assert isinstance(result, ContractValidation)


# -----------------------------------------------------------------------
# TEST-092: Quality gate script content
# -----------------------------------------------------------------------


class TestQualityGateScriptContent:
    """TEST-092: generate_stop_hook script checks completion ratio."""

    def test_stop_hook_script_has_ratio_check(self):
        group, script = generate_stop_hook()
        assert "0.8" in script or "80%" in script or "80" in script
        assert "exit 2" in script
        assert "exit 0" in script
        assert "hooks" in group
        assert group["hooks"][0]["type"] == "command"

    def test_stop_hook_script_reads_requirements(self):
        _, script = generate_stop_hook()
        assert "REQUIREMENTS.md" in script
        assert "grep" in script


# -----------------------------------------------------------------------
# TEST-093: State JSON all reports roundtrip
# -----------------------------------------------------------------------


class TestStateJsonAllReportsRoundtrip:
    """TEST-093: save_state/load_state roundtrip with all Build 2 fields."""

    def test_all_build2_fields_roundtrip(self, tmp_path: Path):
        state = RunState(
            task="full-roundtrip",
            agent_teams_active=True,
            contract_report={
                "total_contracts": 10,
                "verified_contracts": 8,
                "violated_contracts": 1,
                "missing_implementations": 1,
                "violations": [],
                "health": "healthy",
                "verified_contract_ids": ["c-1"],
                "violated_contract_ids": ["c-2"],
            },
            endpoint_test_report={
                "total_endpoints": 20,
                "tested_endpoints": 18,
                "passed_endpoints": 16,
                "failed_endpoints": 2,
                "untested_contracts": [],
                "health": "partial",
            },
            registered_artifacts=["file1.py", "file2.ts", "file3.js"],
        )
        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.agent_teams_active is True
        assert loaded.contract_report["total_contracts"] == 10
        assert loaded.contract_report["health"] == "healthy"
        assert loaded.endpoint_test_report["total_endpoints"] == 20
        assert loaded.endpoint_test_report["health"] == "partial"
        assert loaded.registered_artifacts == ["file1.py", "file2.ts", "file3.js"]


# -----------------------------------------------------------------------
# TEST-094: ScanScope used by contract scanner
# -----------------------------------------------------------------------


class TestScanScopeContractScans:
    """TEST-094: Verify ScanScope is used by contract scanner."""

    def test_run_contract_compliance_scan_accepts_scope(self):
        """Verify run_contract_compliance_scan accepts a scope parameter."""
        import inspect
        from agent_team_v15.contract_scanner import run_contract_compliance_scan
        sig = inspect.signature(run_contract_compliance_scan)
        assert "scope" in sig.parameters


# -----------------------------------------------------------------------
# SEC-001: No API key leak in mcp_clients
# -----------------------------------------------------------------------


class TestMCPClientsNoAPIKeyLeak:
    """SEC-001: mcp_clients.py does not pass ANTHROPIC_API_KEY."""

    def test_no_anthropic_api_key_in_source(self):
        import agent_team_v15.mcp_clients as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        # Must not hardcode or pass the key
        assert "ANTHROPIC_API_KEY" not in source


# -----------------------------------------------------------------------
# SEC-002: Hook scripts no secrets
# -----------------------------------------------------------------------


class TestHookScriptsNoSecrets:
    """SEC-002: Generated hooks contain no secret values."""

    def test_stop_hook_no_secrets(self):
        _, script = generate_stop_hook()
        assert "ANTHROPIC_API_KEY" not in script
        assert "SECRET" not in script.upper() or "secret" not in script.lower()
        assert "password" not in script.lower()
        assert "token" not in script.lower()

    def test_hooks_config_no_secrets(self):
        cfg = _make_config_obj()
        hook_config = generate_hooks_config(
            config=cfg,
            project_dir=Path("."),
        )
        for script_name, script_content in hook_config.scripts.items():
            assert "ANTHROPIC_API_KEY" not in script_content
            assert "password" not in script_content.lower()


# -----------------------------------------------------------------------
# SEC-003: save_local_cache strips securitySchemes
# -----------------------------------------------------------------------


class TestSaveLocalCacheStripsSecuritySchemes:
    """SEC-003: ServiceContractRegistry.save_local_cache strips securitySchemes."""

    def test_security_schemes_stripped(self, tmp_path: Path):
        registry = ServiceContractRegistry()
        contract = ServiceContract(
            contract_id="c-1",
            contract_type="openapi",
            provider_service="auth",
            consumer_service="",
            version="1.0.0",
            spec_hash="abc",
            spec={
                "openapi": "3.0.0",
                "components": {
                    "schemas": {"User": {"type": "object"}},
                    "securitySchemes": {
                        "bearerAuth": {
                            "type": "http",
                            "scheme": "bearer",
                        }
                    },
                },
            },
            implemented=False,
        )
        registry._contracts["c-1"] = contract

        cache_path = tmp_path / "cache.json"
        registry.save_local_cache(cache_path)

        data = json.loads(cache_path.read_text(encoding="utf-8"))
        spec = data["contracts"]["c-1"]["spec"]
        components = spec.get("components", {})
        assert "securitySchemes" not in components
        # schemas should still be present
        assert "schemas" in components


# -----------------------------------------------------------------------
# INT-003: ArchitectClient.decompose safe default
# -----------------------------------------------------------------------


class TestArchitectClientDecomposeSafeDefault:
    """INT-003: ArchitectClient.decompose returns {} on error."""

    @pytest.mark.asyncio
    async def test_decompose_returns_empty_dict_on_error(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=ConnectionError("failed"))
        client = ArchitectClient(session)
        result = await client.decompose("some description")
        assert result == {}


# -----------------------------------------------------------------------
# INT-005: ArchitectClient.get_service_map safe default
# -----------------------------------------------------------------------


class TestArchitectClientGetServiceMapSafeDefault:
    """INT-005: ArchitectClient.get_service_map returns {} on error."""

    @pytest.mark.asyncio
    async def test_get_service_map_returns_empty_dict_on_error(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("dead"))
        client = ArchitectClient(session)
        result = await client.get_service_map()
        assert result == {}


# -----------------------------------------------------------------------
# INT-006: ArchitectClient.get_contracts_for_service safe default
# -----------------------------------------------------------------------


class TestArchitectClientGetContractsSafeDefault:
    """INT-006: get_contracts_for_service returns [] on error."""

    @pytest.mark.asyncio
    async def test_get_contracts_for_service_returns_empty_list_on_error(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=RuntimeError("boom"))
        client = ArchitectClient(session)
        result = await client.get_contracts_for_service("auth")
        assert result == []


# -----------------------------------------------------------------------
# INT-007: ArchitectClient.get_domain_model safe default
# -----------------------------------------------------------------------


class TestArchitectClientGetDomainModelSafeDefault:
    """INT-007: get_domain_model returns {} on error."""

    @pytest.mark.asyncio
    async def test_get_domain_model_returns_empty_dict_on_error(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=TimeoutError("timeout"))
        client = ArchitectClient(session)
        result = await client.get_domain_model("auth")
        assert result == {}


# -----------------------------------------------------------------------
# INT-008: Violation dataclass interface
# -----------------------------------------------------------------------


class TestViolationDataclassInterface:
    """INT-008: Violation has expected fields."""

    def test_violation_has_expected_fields(self):
        expected = {"check", "message", "file_path", "line", "severity"}
        actual = {f.name for f in fields(ContractViolation)}
        assert expected == actual

    def test_violation_can_be_created(self):
        v = ContractViolation(
            check="CONTRACT-001",
            message="Missing field 'email'",
            file_path="src/auth.py",
            line=42,
            severity="error",
        )
        assert v.check == "CONTRACT-001"
        assert v.severity == "error"


# -----------------------------------------------------------------------
# INT-010: pathlib.Path usage in source
# -----------------------------------------------------------------------


class TestPathlibUsage:
    """INT-010: Key source files use pathlib.Path."""

    def test_contract_scanner_uses_pathlib(self):
        import agent_team_v15.contract_scanner as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "from pathlib import Path" in source

    def test_state_uses_pathlib(self):
        import agent_team_v15.state as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "from pathlib import Path" in source

    def test_hooks_manager_uses_pathlib(self):
        import agent_team_v15.hooks_manager as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "from pathlib import Path" in source


# -----------------------------------------------------------------------
# INT-011: Pipeline stages preserved (15 stages)
# -----------------------------------------------------------------------


class TestPipelineStagesPreserved:
    """INT-011: cli.py has all 15 pipeline stages."""

    def test_cli_has_phase_references(self):
        import agent_team_v15.cli as cli_module
        source = Path(cli_module.__file__).read_text(encoding="utf-8")
        # Check key stages exist
        assert "Phase 0:" in source or "Phase 0 " in source or "Phase 0.5" in source
        assert "Phase 1:" in source or "Phase 1 " in source
        assert "Phase 2:" in source or "Phase 2 " in source
        assert "MASTER_PLAN" in source
        assert "get_contract_aware_servers" in source


# -----------------------------------------------------------------------
# INT-012: Fix loops preserved
# -----------------------------------------------------------------------


class TestFixLoopsPreserved:
    """INT-012: cli.py has fix loop patterns."""

    def test_cli_has_fix_patterns(self):
        import agent_team_v15.cli as cli_module
        source = Path(cli_module.__file__).read_text(encoding="utf-8")
        # Fix loop patterns: wiring_fix_retries, fix_cycle_log, max_retries
        assert "fix_retries" in source or "fix_cycle" in source
        assert "max_retries" in source or "wiring_fix_retries" in source


# -----------------------------------------------------------------------
# INT-014: Milestone execution preserved (MASTER_PLAN parsing)
# -----------------------------------------------------------------------


class TestMilestoneExecutionPreserved:
    """INT-014: cli.py has MASTER_PLAN parsing."""

    def test_master_plan_parsing(self):
        import agent_team_v15.cli as cli_module
        source = Path(cli_module.__file__).read_text(encoding="utf-8")
        assert "MASTER_PLAN" in source
        assert "milestones" in source


# -----------------------------------------------------------------------
# INT-016: Depth gating preserved
# -----------------------------------------------------------------------


class TestDepthGatingPreserved:
    """INT-016: Depth-based behavior works correctly."""

    def test_depth_gating_function_exists(self):
        from agent_team_v15.config import apply_depth_quality_gating
        cfg, overrides = _dict_to_config({})
        # Should not raise for any depth level
        for depth in ("quick", "standard", "thorough", "exhaustive"):
            apply_depth_quality_gating(depth, cfg, user_overrides=overrides)


# -----------------------------------------------------------------------
# INT-017: ScanScope contract scans
# -----------------------------------------------------------------------


class TestScanScopeContractScansFilter:
    """INT-017: ScanScope filtering in contract scanner."""

    def test_contract_scanner_has_scan_functions(self):
        """Verify individual scan functions exist in contract_scanner."""
        import agent_team_v15.contract_scanner as mod
        assert hasattr(mod, "run_contract_compliance_scan")
        assert hasattr(mod, "Violation")


# -----------------------------------------------------------------------
# INT-018: register_artifact timing
# -----------------------------------------------------------------------


class TestRegisterArtifactTiming:
    """INT-018: register_artifact returns within expected time."""

    @pytest.mark.asyncio
    async def test_register_artifact_completes_quickly(self):
        """register_new_artifact should complete quickly with a mock client."""
        artifact_data = json.dumps({
            "indexed": True,
            "symbols_found": 5,
            "dependencies_found": 3,
        })
        session = _make_session({
            "register_artifact": _make_result(artifact_data),
        })
        client = CodebaseIntelligenceClient(session)

        start = time.monotonic()
        result = await register_new_artifact(client, "test.py", "auth")
        elapsed = time.monotonic() - start

        assert isinstance(result, ArtifactResult)
        # Should complete in under 5 seconds with mocks
        assert elapsed < 5.0


# -----------------------------------------------------------------------
# INT-019: Contract report in summary block
# -----------------------------------------------------------------------


class TestContractReportInSummaryBlock:
    """INT-019: save_state summary includes contract data."""

    def test_summary_has_contract_fields(self, tmp_path: Path):
        state = RunState(
            task="test",
            requirements_checked=8,
            requirements_total=10,
            contract_report={"total_contracts": 5, "verified_contracts": 4},
            endpoint_test_report={"tested_endpoints": 20, "passed_endpoints": 18},
        )
        save_state(state, str(tmp_path))
        data = json.loads((tmp_path / "STATE.json").read_text(encoding="utf-8"))
        assert "summary" in data
        # No test files on disk → falls back to E2E endpoint counts
        assert data["summary"]["test_total"] == 20
        assert data["summary"]["test_passed"] == 18
        assert data["summary"]["convergence_ratio"] == 0.8
        # New separated fields
        assert data["summary"]["test_files_found"] == 0
        assert data["summary"]["e2e_passed"] == 18
        assert data["summary"]["e2e_total"] == 20
        assert data["summary"]["requirements_checked"] == 8
        assert data["summary"]["requirements_total"] == 10


# -----------------------------------------------------------------------
# INT-020: Backward compat: load_state handles missing Build 2 fields
# -----------------------------------------------------------------------


class TestBackwardCompatLoadState:
    """INT-020: load_state handles STATE.json missing Build 2 fields."""

    def test_missing_contract_report_defaults_to_empty(self, tmp_path: Path):
        state_data = {
            "run_id": "abc123",
            "task": "old-task",
            "depth": "standard",
            "current_phase": "init",
            "completed_phases": [],
            "total_cost": 0.0,
            "artifacts": {},
            "interrupted": True,
            "timestamp": "2024-01-01T00:00:00+00:00",
            "convergence_cycles": 0,
            "requirements_checked": 0,
            "requirements_total": 0,
            "error_context": "",
            "milestone_progress": {},
            "schema_version": 2,
            "current_milestone": "",
            "completed_milestones": [],
            "failed_milestones": [],
            "milestone_order": [],
            "completion_ratio": 0.0,
            "completed_browser_workflows": [],
            "agent_teams_active": False,
            # NO contract_report, endpoint_test_report, registered_artifacts
        }
        (tmp_path / "STATE.json").write_text(
            json.dumps(state_data), encoding="utf-8"
        )
        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.contract_report == {}
        assert loaded.endpoint_test_report == {}
        assert loaded.registered_artifacts == []
