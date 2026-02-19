"""Tests for Contract Engine MCP client and related milestone-2 components.

Covers:
- ContractEngineClient with 6 MCP tool methods (TEST-018 through TEST-020)
- _extract_json and _extract_text helpers (TEST-021, TEST-022)
- create_contract_engine_session error handling (TEST-023, TEST-024)
- ContractEngineConfig defaults and parsing (TEST-025, TEST-026)
- _contract_engine_mcp_server config (TEST-027)
- ServiceContractRegistry lifecycle (TEST-028, TEST-029, TEST-030)
- save_local_cache securitySchemes stripping (TEST-030A)
- Retry logic with exponential backoff (TEST-030B, TEST-030C)
- MCPConnectionError on server exit (TEST-030D)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.config import (
    AgentTeamConfig,
    ContractEngineConfig,
    _dict_to_config,
)
from agent_team_v15.contract_client import (
    ContractEngineClient,
    ContractInfo,
    ContractValidation,
    _extract_json,
    _extract_text,
)
from agent_team_v15.contracts import ServiceContract, ServiceContractRegistry
from agent_team_v15.mcp_clients import MCPConnectionError
from agent_team_v15.mcp_servers import (
    _contract_engine_mcp_server,
    get_contract_aware_servers,
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


# -----------------------------------------------------------------------
# TEST-018: All 6 client methods return correct dataclasses with valid
#           mocked MCP responses
# -----------------------------------------------------------------------


class TestClientValidResponses:
    """TEST-018: Verify all 6 methods work with valid MCP responses."""

    @pytest.mark.asyncio
    async def test_get_contract_valid(self):
        response_data = {
            "id": "c-123",
            "type": "openapi",
            "version": "1.0.0",
            "service_name": "auth-service",
            "spec": {"openapi": "3.0.0"},
            "spec_hash": "abc123",
            "status": "active",
        }
        session = _make_session({
            "get_contract": _make_result(json.dumps(response_data)),
        })
        client = ContractEngineClient(session)
        result = await client.get_contract("c-123")

        assert result is not None
        assert isinstance(result, ContractInfo)
        assert result.id == "c-123"
        assert result.type == "openapi"
        assert result.version == "1.0.0"
        assert result.service_name == "auth-service"
        assert result.spec == {"openapi": "3.0.0"}
        assert result.spec_hash == "abc123"
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_validate_endpoint_valid(self):
        response_data = {
            "valid": True,
            "violations": [],
        }
        session = _make_session({
            "validate_endpoint": _make_result(json.dumps(response_data)),
        })
        client = ContractEngineClient(session)
        result = await client.validate_endpoint(
            service_name="auth",
            method="GET",
            path="/users",
            response_body={"id": 1},
            status_code=200,
        )

        assert isinstance(result, ContractValidation)
        assert result.valid is True
        assert result.violations == []
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_validate_endpoint_with_violations(self):
        response_data = {
            "valid": False,
            "violations": [
                {"field": "name", "expected": "string", "actual": "number"}
            ],
        }
        session = _make_session({
            "validate_endpoint": _make_result(json.dumps(response_data)),
        })
        client = ContractEngineClient(session)
        result = await client.validate_endpoint("auth", "GET", "/users")

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0]["field"] == "name"

    @pytest.mark.asyncio
    async def test_generate_tests_valid(self):
        test_content = "def test_example():\n    assert True\n"
        session = _make_session({
            "generate_tests": _make_result(test_content),
        })
        client = ContractEngineClient(session)
        result = await client.generate_tests("c-123", "pytest", True)

        assert isinstance(result, str)
        assert "test_example" in result

    @pytest.mark.asyncio
    async def test_check_breaking_changes_valid(self):
        changes = [
            {"type": "removed_field", "path": "/users/{id}", "field": "email"}
        ]
        session = _make_session({
            "check_breaking_changes": _make_result(json.dumps(changes)),
        })
        client = ContractEngineClient(session)
        result = await client.check_breaking_changes("c-123", {"openapi": "3.0.0"})

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "removed_field"

    @pytest.mark.asyncio
    async def test_mark_implemented_valid(self):
        response_data = {
            "marked": True,
            "total": 5,
            "all_implemented": False,
        }
        session = _make_session({
            "mark_implemented": _make_result(json.dumps(response_data)),
        })
        client = ContractEngineClient(session)
        result = await client.mark_implemented("c-123", "auth-service", "/tests/test_auth.py")

        assert isinstance(result, dict)
        assert result["marked"] is True
        assert result["total"] == 5
        assert result["all_implemented"] is False

    @pytest.mark.asyncio
    async def test_get_unimplemented_contracts_valid(self):
        contracts = [
            {"id": "c-1", "service_name": "auth"},
            {"id": "c-2", "service_name": "auth"},
        ]
        session = _make_session({
            "get_unimplemented_contracts": _make_result(json.dumps(contracts)),
        })
        client = ContractEngineClient(session)
        result = await client.get_unimplemented_contracts("auth")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "c-1"


# -----------------------------------------------------------------------
# TEST-019: All 6 methods return safe defaults with mocked Exception
# -----------------------------------------------------------------------


class TestClientExceptionDefaults:
    """TEST-019: Verify safe defaults when exceptions occur."""

    @pytest.mark.asyncio
    async def test_get_contract_exception(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = ContractEngineClient(session)
        result = await client.get_contract("c-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_validate_endpoint_exception(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = ContractEngineClient(session)
        result = await client.validate_endpoint("auth", "GET", "/users")

        assert isinstance(result, ContractValidation)
        assert result.valid is False
        assert "connection lost" in result.error

    @pytest.mark.asyncio
    async def test_generate_tests_exception(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = ContractEngineClient(session)
        result = await client.generate_tests("c-123")

        assert result == ""

    @pytest.mark.asyncio
    async def test_check_breaking_changes_exception(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = ContractEngineClient(session)
        result = await client.check_breaking_changes("c-123", {})

        assert result == []

    @pytest.mark.asyncio
    async def test_mark_implemented_exception(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = ContractEngineClient(session)
        result = await client.mark_implemented("c-123", "auth")

        assert result == {"marked": False}

    @pytest.mark.asyncio
    async def test_get_unimplemented_contracts_exception(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = ContractEngineClient(session)
        result = await client.get_unimplemented_contracts("auth")

        assert result == []


# -----------------------------------------------------------------------
# TEST-020: All 6 methods return safe defaults with result.isError = True
# -----------------------------------------------------------------------


class TestClientIsErrorDefaults:
    """TEST-020: Verify safe defaults when MCP result has isError=True."""

    @pytest.mark.asyncio
    async def test_get_contract_is_error(self):
        session = _make_session({
            "get_contract": _make_result("Tool error", is_error=True),
        })
        client = ContractEngineClient(session)
        result = await client.get_contract("c-123")

        # isError causes RuntimeError which triggers safe default
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_endpoint_is_error(self):
        session = _make_session({
            "validate_endpoint": _make_result("Tool error", is_error=True),
        })
        client = ContractEngineClient(session)
        result = await client.validate_endpoint("auth", "GET", "/users")

        assert isinstance(result, ContractValidation)
        assert result.valid is False
        assert result.error != ""

    @pytest.mark.asyncio
    async def test_generate_tests_is_error(self):
        session = _make_session({
            "generate_tests": _make_result("Tool error", is_error=True),
        })
        client = ContractEngineClient(session)
        result = await client.generate_tests("c-123")

        assert result == ""

    @pytest.mark.asyncio
    async def test_check_breaking_changes_is_error(self):
        session = _make_session({
            "check_breaking_changes": _make_result("Tool error", is_error=True),
        })
        client = ContractEngineClient(session)
        result = await client.check_breaking_changes("c-123", {})

        assert result == []

    @pytest.mark.asyncio
    async def test_mark_implemented_is_error(self):
        session = _make_session({
            "mark_implemented": _make_result("Tool error", is_error=True),
        })
        client = ContractEngineClient(session)
        result = await client.mark_implemented("c-123", "auth")

        assert result == {"marked": False}

    @pytest.mark.asyncio
    async def test_get_unimplemented_is_error(self):
        session = _make_session({
            "get_unimplemented_contracts": _make_result("Tool error", is_error=True),
        })
        client = ContractEngineClient(session)
        result = await client.get_unimplemented_contracts("auth")

        assert result == []


# -----------------------------------------------------------------------
# TEST-021: _extract_json handles valid JSON, invalid JSON, empty, None
# -----------------------------------------------------------------------


class TestExtractJson:
    """TEST-021: Verify _extract_json edge cases."""

    def test_valid_json(self):
        content = _make_content('{"key": "value"}')
        result = _extract_json(content)
        assert result == {"key": "value"}

    def test_valid_json_list(self):
        content = _make_content('[1, 2, 3]')
        result = _extract_json(content)
        assert result == [1, 2, 3]

    def test_invalid_json(self):
        content = _make_content("not json")
        result = _extract_json(content)
        assert result is None

    def test_empty_content(self):
        result = _extract_json([])
        assert result is None

    def test_none_content(self):
        result = _extract_json(None)
        assert result is None

    def test_content_without_text_attr(self):
        result = _extract_json([42])
        assert result is None


# -----------------------------------------------------------------------
# TEST-022: _extract_text handles valid text, empty content, no text
# -----------------------------------------------------------------------


class TestExtractText:
    """TEST-022: Verify _extract_text edge cases."""

    def test_valid_text(self):
        content = _make_content("Hello world")
        result = _extract_text(content)
        assert result == "Hello world"

    def test_empty_text(self):
        content = _make_content("")
        result = _extract_text(content)
        assert result == ""

    def test_empty_content(self):
        result = _extract_text([])
        assert result == ""

    def test_none_content(self):
        result = _extract_text(None)
        assert result == ""

    def test_none_text_attribute(self):
        item = SimpleNamespace(text=None)
        result = _extract_text([item])
        assert result == ""


# -----------------------------------------------------------------------
# TEST-023: create_contract_engine_session raises ImportError when mcp
#           missing
# -----------------------------------------------------------------------


class TestSessionImportError:
    """TEST-023: Verify ImportError when mcp package not installed."""

    @pytest.mark.asyncio
    async def test_import_error_when_mcp_missing(self):
        with patch.dict(sys.modules, {"mcp": None, "mcp.client.stdio": None}):
            from agent_team_v15.mcp_clients import create_contract_engine_session
            config = ContractEngineConfig(enabled=True)
            with pytest.raises(ImportError, match="MCP SDK not installed"):
                async with create_contract_engine_session(config) as _session:
                    pass


# -----------------------------------------------------------------------
# TEST-024: Session passes DATABASE_PATH when non-empty, None when empty
# -----------------------------------------------------------------------


class TestSessionDatabasePath:
    """TEST-024: Verify DATABASE_PATH env var handling."""

    def test_config_with_database_path(self):
        config = ContractEngineConfig(database_path="/data/contracts.db")
        assert config.database_path == "/data/contracts.db"

    def test_config_without_database_path(self):
        config = ContractEngineConfig(database_path="")
        assert config.database_path == ""


# -----------------------------------------------------------------------
# TEST-025: ContractEngineConfig defaults verified
# -----------------------------------------------------------------------


class TestContractEngineConfigDefaults:
    """TEST-025: Verify all ContractEngineConfig defaults."""

    def test_all_defaults(self):
        cfg = ContractEngineConfig()
        assert cfg.enabled is False
        assert cfg.mcp_command == "python"
        assert cfg.mcp_args == ["-m", "src.contract_engine.mcp_server"]
        assert cfg.database_path == ""
        assert cfg.validation_on_build is True
        assert cfg.test_generation is True
        assert cfg.server_root == ""
        assert cfg.startup_timeout_ms == 30000
        assert cfg.tool_timeout_ms == 60000


# -----------------------------------------------------------------------
# TEST-026: _dict_to_config parses contract_engine YAML; missing section
#           yields defaults
# -----------------------------------------------------------------------


class TestContractEngineConfigParsing:
    """TEST-026: Verify YAML parsing of contract_engine section."""

    def test_missing_section_yields_defaults(self):
        cfg, overrides = _dict_to_config({})
        assert cfg.contract_engine.enabled is False
        assert cfg.contract_engine.mcp_command == "python"
        assert "contract_engine.enabled" not in overrides

    def test_explicit_enabled_tracked_in_overrides(self):
        cfg, overrides = _dict_to_config({
            "contract_engine": {"enabled": True}
        })
        assert cfg.contract_engine.enabled is True
        assert "contract_engine.enabled" in overrides

    def test_full_section_parsed(self):
        cfg, overrides = _dict_to_config({
            "contract_engine": {
                "enabled": True,
                "mcp_command": "node",
                "mcp_args": ["server.js"],
                "database_path": "/tmp/db.sqlite",
                "validation_on_build": False,
                "test_generation": False,
                "server_root": "/srv",
                "startup_timeout_ms": 5000,
                "tool_timeout_ms": 10000,
            }
        })
        assert cfg.contract_engine.enabled is True
        assert cfg.contract_engine.mcp_command == "node"
        assert cfg.contract_engine.mcp_args == ["server.js"]
        assert cfg.contract_engine.database_path == "/tmp/db.sqlite"
        assert cfg.contract_engine.validation_on_build is False
        assert cfg.contract_engine.test_generation is False
        assert cfg.contract_engine.server_root == "/srv"
        assert cfg.contract_engine.startup_timeout_ms == 5000
        assert cfg.contract_engine.tool_timeout_ms == 10000

    def test_invalid_startup_timeout(self):
        with pytest.raises(ValueError, match="startup_timeout_ms"):
            _dict_to_config({"contract_engine": {"startup_timeout_ms": 500}})

    def test_invalid_tool_timeout(self):
        with pytest.raises(ValueError, match="tool_timeout_ms"):
            _dict_to_config({"contract_engine": {"tool_timeout_ms": 100}})

    def test_backward_compatible_without_section(self):
        """Configs without contract_engine section should work (backward compat)."""
        cfg, _ = _dict_to_config({"orchestrator": {"model": "opus"}})
        assert hasattr(cfg, "contract_engine")
        assert cfg.contract_engine.enabled is False

    def test_contract_engine_in_agent_team_config(self):
        """contract_engine field exists on AgentTeamConfig."""
        cfg = AgentTeamConfig()
        assert hasattr(cfg, "contract_engine")
        assert isinstance(cfg.contract_engine, ContractEngineConfig)


# -----------------------------------------------------------------------
# TEST-027: _contract_engine_mcp_server returns correct dict
# -----------------------------------------------------------------------


class TestContractEngineMCPServer:
    """TEST-027: Verify MCP server config generation."""

    def test_basic_config(self):
        config = ContractEngineConfig()
        result = _contract_engine_mcp_server(config)

        assert result["type"] == "stdio"
        assert result["command"] == "python"
        assert result["args"] == ["-m", "src.contract_engine.mcp_server"]
        assert "env" not in result  # No database path

    def test_with_database_path(self):
        config = ContractEngineConfig(database_path="/data/contracts.db")
        result = _contract_engine_mcp_server(config)

        assert result["type"] == "stdio"
        assert "env" in result
        assert result["env"]["DATABASE_PATH"] == "/data/contracts.db"

    def test_custom_command_and_args(self):
        config = ContractEngineConfig(
            mcp_command="node",
            mcp_args=["dist/server.js", "--port", "3000"],
        )
        result = _contract_engine_mcp_server(config)

        assert result["command"] == "node"
        assert result["args"] == ["dist/server.js", "--port", "3000"]

    def test_get_contract_aware_servers_includes_contract_engine(self):
        cfg = AgentTeamConfig()
        cfg.contract_engine = ContractEngineConfig(enabled=True)
        servers = get_contract_aware_servers(cfg)

        assert "contract_engine" in servers

    def test_get_contract_aware_servers_excludes_when_disabled(self):
        cfg = AgentTeamConfig()
        cfg.contract_engine = ContractEngineConfig(enabled=False)
        servers = get_contract_aware_servers(cfg)

        assert "contract_engine" not in servers


# -----------------------------------------------------------------------
# TEST-028: ServiceContractRegistry load lifecycle
# -----------------------------------------------------------------------


class TestServiceContractRegistryLoad:
    """TEST-028: Verify load_from_mcp and load_from_local."""

    @pytest.mark.asyncio
    async def test_load_from_mcp_success(self):
        mock_client = AsyncMock()
        mock_client.get_unimplemented_contracts = AsyncMock(return_value=[
            {"id": "c-1", "service_name": "auth"},
            {"id": "c-2", "service_name": "billing"},
        ])
        mock_client.get_contract = AsyncMock(side_effect=[
            ContractInfo(
                id="c-1", type="openapi", version="1.0",
                service_name="auth", spec={"openapi": "3.0.0"},
                spec_hash="hash1", status="active",
            ),
            ContractInfo(
                id="c-2", type="asyncapi", version="2.0",
                service_name="billing", spec={"asyncapi": "2.0.0"},
                spec_hash="hash2", status="active",
            ),
        ])

        registry = ServiceContractRegistry()
        await registry.load_from_mcp(mock_client)

        assert len(registry.contracts) == 2
        assert "c-1" in registry.contracts
        assert registry.contracts["c-1"].contract_type == "openapi"
        assert registry.contracts["c-2"].provider_service == "billing"

    @pytest.mark.asyncio
    async def test_load_from_mcp_failure_silent(self):
        mock_client = AsyncMock()
        mock_client.get_unimplemented_contracts = AsyncMock(
            side_effect=OSError("connection lost")
        )

        registry = ServiceContractRegistry()
        await registry.load_from_mcp(mock_client)

        # Should not raise, just log warning
        assert len(registry.contracts) == 0

    def test_load_from_local_success(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({
                "version": "1.0",
                "contracts": {
                    "c-1": {
                        "contract_type": "openapi",
                        "provider_service": "auth",
                        "consumer_service": "gateway",
                        "version": "1.0",
                        "spec_hash": "abc",
                        "spec": {},
                        "implemented": False,
                        "evidence_path": "",
                    }
                }
            }, f)
            f.flush()

            registry = ServiceContractRegistry()
            registry.load_from_local(Path(f.name))

            assert len(registry.contracts) == 1
            assert registry.contracts["c-1"].provider_service == "auth"

    def test_load_from_local_missing_file(self):
        registry = ServiceContractRegistry()
        registry.load_from_local(Path("/nonexistent/path.json"))

        assert len(registry.contracts) == 0


# -----------------------------------------------------------------------
# TEST-029: ServiceContractRegistry save lifecycle
# -----------------------------------------------------------------------


class TestServiceContractRegistrySave:
    """TEST-029: Verify save_local_cache."""

    def test_save_and_reload(self):
        registry = ServiceContractRegistry()
        registry._contracts["c-1"] = ServiceContract(
            contract_id="c-1",
            contract_type="openapi",
            provider_service="auth",
            consumer_service="gateway",
            version="1.0",
            spec_hash="abc",
            spec={"openapi": "3.0.0"},
            implemented=True,
            evidence_path="/tests/test_auth.py",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            registry.save_local_cache(cache_path)

            # Reload
            registry2 = ServiceContractRegistry()
            registry2.load_from_local(cache_path)

            assert len(registry2.contracts) == 1
            c = registry2.contracts["c-1"]
            assert c.contract_type == "openapi"
            assert c.provider_service == "auth"
            assert c.implemented is True
            assert c.evidence_path == "/tests/test_auth.py"


# -----------------------------------------------------------------------
# TEST-030: ServiceContractRegistry validate/mark lifecycle
# -----------------------------------------------------------------------


class TestServiceContractRegistryOperations:
    """TEST-030: Verify validate_endpoint, mark_implemented, get_unimplemented."""

    @pytest.mark.asyncio
    async def test_validate_endpoint_delegates(self):
        mock_client = AsyncMock()
        expected = ContractValidation(valid=True)
        mock_client.validate_endpoint = AsyncMock(return_value=expected)

        registry = ServiceContractRegistry()
        result = await registry.validate_endpoint(
            mock_client, "auth", "GET", "/users", {}, 200,
        )

        assert result.valid is True
        mock_client.validate_endpoint.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_implemented_updates_local(self):
        registry = ServiceContractRegistry()
        registry._contracts["c-1"] = ServiceContract(
            contract_id="c-1",
            contract_type="openapi",
            provider_service="auth",
            consumer_service="",
            version="1.0",
            spec_hash="abc",
        )

        mock_client = AsyncMock()
        mock_client.mark_implemented = AsyncMock(
            return_value={"marked": True, "total": 1, "all_implemented": True}
        )

        result = await registry.mark_implemented(mock_client, "c-1", "auth", "/evidence.py")

        assert result["marked"] is True
        assert registry.contracts["c-1"].implemented is True
        assert registry.contracts["c-1"].evidence_path == "/evidence.py"

    def test_get_unimplemented_all(self):
        registry = ServiceContractRegistry()
        registry._contracts["c-1"] = ServiceContract(
            contract_id="c-1",
            contract_type="openapi",
            provider_service="auth",
            consumer_service="",
            version="1.0",
            spec_hash="abc",
            implemented=False,
        )
        registry._contracts["c-2"] = ServiceContract(
            contract_id="c-2",
            contract_type="openapi",
            provider_service="auth",
            consumer_service="",
            version="1.0",
            spec_hash="def",
            implemented=True,
        )

        result = registry.get_unimplemented()
        assert len(result) == 1
        assert result[0].contract_id == "c-1"

    def test_get_unimplemented_by_service(self):
        registry = ServiceContractRegistry()
        registry._contracts["c-1"] = ServiceContract(
            contract_id="c-1",
            contract_type="openapi",
            provider_service="auth",
            consumer_service="",
            version="1.0",
            spec_hash="abc",
            implemented=False,
        )
        registry._contracts["c-2"] = ServiceContract(
            contract_id="c-2",
            contract_type="openapi",
            provider_service="billing",
            consumer_service="",
            version="1.0",
            spec_hash="def",
            implemented=False,
        )

        result = registry.get_unimplemented("auth")
        assert len(result) == 1
        assert result[0].provider_service == "auth"


# -----------------------------------------------------------------------
# TEST-030A: save_local_cache strips securitySchemes
# -----------------------------------------------------------------------


class TestSaveLocalCacheStripsSecurity:
    """TEST-030A: Verify SEC-003 compliance."""

    def test_strips_security_schemes(self):
        registry = ServiceContractRegistry()
        registry._contracts["c-1"] = ServiceContract(
            contract_id="c-1",
            contract_type="openapi",
            provider_service="auth",
            consumer_service="",
            version="1.0",
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
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            registry.save_local_cache(cache_path)

            data = json.loads(cache_path.read_text())
            spec = data["contracts"]["c-1"]["spec"]
            assert "securitySchemes" not in spec.get("components", {})
            # Schemas should still be there
            assert "schemas" in spec["components"]

    def test_does_not_mutate_in_memory_spec(self):
        """Stripping should not affect the in-memory contract."""
        registry = ServiceContractRegistry()
        registry._contracts["c-1"] = ServiceContract(
            contract_id="c-1",
            contract_type="openapi",
            provider_service="auth",
            consumer_service="",
            version="1.0",
            spec_hash="abc",
            spec={
                "components": {
                    "securitySchemes": {"bearer": {"type": "http"}},
                },
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            registry.save_local_cache(cache_path)

        # In-memory spec should still have securitySchemes
        assert "securitySchemes" in registry.contracts["c-1"].spec["components"]


# -----------------------------------------------------------------------
# TEST-030B: Retry 3 times on TimeoutError with exponential backoff
# -----------------------------------------------------------------------


class TestRetryBackoff:
    """TEST-030B: Verify retry behavior on transient errors."""

    @pytest.mark.asyncio
    async def test_retries_on_timeout_error(self):
        call_count = 0

        async def _failing_call(tool_name, arguments):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("timeout")
            return _make_result(json.dumps({"id": "c-1"}))

        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=_failing_call)
        client = ContractEngineClient(session)

        # Patch asyncio.sleep to avoid actual waiting
        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_contract("c-1")

        assert result is not None
        assert result.id == "c-1"
        assert call_count == 3  # 2 retries + 1 success

    @pytest.mark.asyncio
    async def test_exhausts_retries_then_safe_default(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=TimeoutError("timeout"))
        client = ContractEngineClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_contract("c-1")

        assert result is None  # Safe default
        assert session.call_tool.call_count == 3  # All 3 attempts


# -----------------------------------------------------------------------
# TEST-030C: Safe defaults immediately on TypeError (no retry)
# -----------------------------------------------------------------------


class TestNonTransientNoRetry:
    """TEST-030C: Verify non-transient errors skip retry."""

    @pytest.mark.asyncio
    async def test_type_error_no_retry(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=TypeError("bad type"))
        client = ContractEngineClient(session)

        result = await client.get_contract("c-1")

        assert result is None  # Safe default
        assert session.call_tool.call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_value_error_no_retry(self):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=ValueError("bad value"))
        client = ContractEngineClient(session)

        result = await client.check_breaking_changes("c-1", {})

        assert result == []  # Safe default
        assert session.call_tool.call_count == 1  # No retry


# -----------------------------------------------------------------------
# TEST-030D: MCPConnectionError raised when MCP server exits during init
# -----------------------------------------------------------------------


class TestMCPConnectionError:
    """TEST-030D: Verify MCPConnectionError on server exit."""

    def test_mcp_connection_error_is_exception(self):
        assert issubclass(MCPConnectionError, Exception)

    def test_mcp_connection_error_message(self):
        err = MCPConnectionError("Server crashed")
        assert str(err) == "Server crashed"

    def test_mcp_connection_error_with_cause(self):
        cause = OSError("process died")
        err = MCPConnectionError("Failed")
        err.__cause__ = cause
        assert err.__cause__ is cause
