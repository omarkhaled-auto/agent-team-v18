"""Phase 2B gap-coverage tests for Contract Engine integration.

Covers gaps identified in:
- MCP session lifecycle (create_contract_engine_session error wrapping)
- ArchitectClient (zero prior coverage)
- ServiceContractRegistry edge cases (MCP fallback, mark_implemented failures)
- Retry logic edge cases (ConnectionError retry, exhaustion, isError retry)
- Contract scanner edge cases (severity sort order, FastAPI route detection)

These tests are additive — no existing test files are modified.
"""

from __future__ import annotations

import asyncio
import json
import os
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.contract_client import (
    ContractEngineClient,
    ContractInfo,
    ContractValidation,
    _call_with_retry,
    _extract_json,
    _extract_text,
)
from agent_team_v15.contracts import ServiceContract, ServiceContractRegistry
from agent_team_v15.mcp_clients import ArchitectClient, MCPConnectionError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_content(text: str) -> list:
    """Create a mock MCP content list with a single text entry."""
    return [SimpleNamespace(text=text)]


def _make_result(content_text: str, is_error: bool = False) -> SimpleNamespace:
    """Create a mock MCP call_tool result."""
    return SimpleNamespace(
        content=_make_content(content_text),
        isError=is_error,
    )


# =========================================================================
# Test Group 1: MCP Session Lifecycle (Mock Tests)
# =========================================================================


class TestContractEngineSessionLifecycle:
    """Verify create_contract_engine_session error wrapping and call order."""

    @pytest.mark.asyncio
    async def test_session_initialize_called_before_yield(self):
        """Mock stdio_client and ClientSession, verify initialize() is called before the session is yielded."""
        from agent_team_v15.config import ContractEngineConfig

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        # Track call order
        call_order: list[str] = []
        original_initialize = mock_session.initialize

        async def tracked_initialize():
            call_order.append("initialize")
            return await original_initialize()

        mock_session.initialize = tracked_initialize

        # We need to mock the entire MCP import chain inside
        # create_contract_engine_session
        mock_stdio_client = MagicMock()
        mock_read_stream = MagicMock()
        mock_write_stream = MagicMock()

        # stdio_client is an async context manager
        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aenter__ = AsyncMock(
            return_value=(mock_read_stream, mock_write_stream)
        )
        mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)
        mock_stdio_client.return_value = mock_stdio_cm

        # ClientSession is an async context manager
        mock_client_session_cls = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client_session_cls.return_value = mock_session_cm

        mock_server_params = MagicMock()

        mock_mcp = MagicMock()
        mock_mcp.ClientSession = mock_client_session_cls
        mock_mcp.StdioServerParameters = mock_server_params

        mock_mcp_client_stdio = MagicMock()
        mock_mcp_client_stdio.stdio_client = mock_stdio_client

        config = ContractEngineConfig(
            enabled=True,
            startup_timeout_ms=5000,
        )

        with patch.dict(
            "sys.modules",
            {"mcp": mock_mcp, "mcp.client.stdio": mock_mcp_client_stdio},
        ):
            # Re-import to pick up patched modules
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod

            reload(mcp_mod)

            async with mcp_mod.create_contract_engine_session(config) as session:
                call_order.append("yielded")

        assert "initialize" in call_order
        assert "yielded" in call_order
        # initialize must come before yielded
        assert call_order.index("initialize") < call_order.index("yielded")

    @pytest.mark.asyncio
    async def test_timeout_error_wrapped_to_mcp_connection_error(self):
        """TimeoutError during initialize() is wrapped into MCPConnectionError."""
        from agent_team_v15.config import ContractEngineConfig

        mock_stdio_client = MagicMock()
        mock_read_stream = MagicMock()
        mock_write_stream = MagicMock()

        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aenter__ = AsyncMock(
            return_value=(mock_read_stream, mock_write_stream)
        )
        mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)
        mock_stdio_client.return_value = mock_stdio_cm

        mock_session = AsyncMock()
        # initialize raises TimeoutError
        mock_session.initialize = AsyncMock(side_effect=TimeoutError("timed out"))

        mock_client_session_cls = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client_session_cls.return_value = mock_session_cm

        mock_server_params = MagicMock()

        mock_mcp = MagicMock()
        mock_mcp.ClientSession = mock_client_session_cls
        mock_mcp.StdioServerParameters = mock_server_params

        mock_mcp_client_stdio = MagicMock()
        mock_mcp_client_stdio.stdio_client = mock_stdio_client

        config = ContractEngineConfig(enabled=True, startup_timeout_ms=1000)

        with patch.dict(
            "sys.modules",
            {"mcp": mock_mcp, "mcp.client.stdio": mock_mcp_client_stdio},
        ):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod

            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError, match="Contract Engine"):
                async with mcp_mod.create_contract_engine_session(config) as _s:
                    pass

    @pytest.mark.asyncio
    async def test_connection_error_wrapped(self):
        """ConnectionError during stdio_client is wrapped into MCPConnectionError."""
        from agent_team_v15.config import ContractEngineConfig

        mock_stdio_client = MagicMock()
        # stdio_client raises ConnectionError on enter
        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aenter__ = AsyncMock(
            side_effect=ConnectionError("refused")
        )
        mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)
        mock_stdio_client.return_value = mock_stdio_cm

        mock_server_params = MagicMock()

        mock_mcp = MagicMock()
        mock_mcp.ClientSession = MagicMock()
        mock_mcp.StdioServerParameters = mock_server_params

        mock_mcp_client_stdio = MagicMock()
        mock_mcp_client_stdio.stdio_client = mock_stdio_client

        config = ContractEngineConfig(enabled=True, startup_timeout_ms=1000)

        with patch.dict(
            "sys.modules",
            {"mcp": mock_mcp, "mcp.client.stdio": mock_mcp_client_stdio},
        ):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod

            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError, match="Contract Engine"):
                async with mcp_mod.create_contract_engine_session(config) as _s:
                    pass

    @pytest.mark.asyncio
    async def test_process_lookup_error_wrapped(self):
        """ProcessLookupError is wrapped into MCPConnectionError."""
        from agent_team_v15.config import ContractEngineConfig

        mock_stdio_client = MagicMock()
        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aenter__ = AsyncMock(
            side_effect=ProcessLookupError("no such process")
        )
        mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)
        mock_stdio_client.return_value = mock_stdio_cm

        mock_server_params = MagicMock()

        mock_mcp = MagicMock()
        mock_mcp.ClientSession = MagicMock()
        mock_mcp.StdioServerParameters = mock_server_params

        mock_mcp_client_stdio = MagicMock()
        mock_mcp_client_stdio.stdio_client = mock_stdio_client

        config = ContractEngineConfig(enabled=True, startup_timeout_ms=1000)

        with patch.dict(
            "sys.modules",
            {"mcp": mock_mcp, "mcp.client.stdio": mock_mcp_client_stdio},
        ):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod

            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError, match="Contract Engine"):
                async with mcp_mod.create_contract_engine_session(config) as _s:
                    pass

    @pytest.mark.asyncio
    async def test_os_error_wrapped(self):
        """OSError is wrapped into MCPConnectionError."""
        from agent_team_v15.config import ContractEngineConfig

        mock_stdio_client = MagicMock()
        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aenter__ = AsyncMock(
            side_effect=OSError("broken pipe")
        )
        mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)
        mock_stdio_client.return_value = mock_stdio_cm

        mock_server_params = MagicMock()

        mock_mcp = MagicMock()
        mock_mcp.ClientSession = MagicMock()
        mock_mcp.StdioServerParameters = mock_server_params

        mock_mcp_client_stdio = MagicMock()
        mock_mcp_client_stdio.stdio_client = mock_stdio_client

        config = ContractEngineConfig(enabled=True, startup_timeout_ms=1000)

        with patch.dict(
            "sys.modules",
            {"mcp": mock_mcp, "mcp.client.stdio": mock_mcp_client_stdio},
        ):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod

            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError, match="Contract Engine"):
                async with mcp_mod.create_contract_engine_session(config) as _s:
                    pass

    @pytest.mark.asyncio
    async def test_env_none_when_no_database_path(self):
        """When database_path is empty and env var not set, env=None (no env dict passed)."""
        from agent_team_v15.config import ContractEngineConfig

        config = ContractEngineConfig(
            enabled=True,
            database_path="",
            startup_timeout_ms=1000,
        )

        captured_params: list[Any] = []
        mock_server_params = MagicMock(side_effect=lambda **kwargs: captured_params.append(kwargs) or MagicMock())

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        mock_stdio_client = MagicMock()
        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)
        mock_stdio_client.return_value = mock_stdio_cm

        mock_client_session_cls = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client_session_cls.return_value = mock_session_cm

        mock_mcp = MagicMock()
        mock_mcp.ClientSession = mock_client_session_cls
        mock_mcp.StdioServerParameters = mock_server_params

        mock_mcp_client_stdio = MagicMock()
        mock_mcp_client_stdio.stdio_client = mock_stdio_client

        # Ensure the env var is not set
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONTRACT_ENGINE_DB", None)

            with patch.dict(
                "sys.modules",
                {"mcp": mock_mcp, "mcp.client.stdio": mock_mcp_client_stdio},
            ):
                from importlib import reload
                import agent_team_v15.mcp_clients as mcp_mod

                reload(mcp_mod)

                async with mcp_mod.create_contract_engine_session(config) as _s:
                    pass

        # StdioServerParameters should have been called with env=None
        assert len(captured_params) >= 1
        assert captured_params[0]["env"] is None


# =========================================================================
# Test Group 2: ArchitectClient (Zero Coverage)
# =========================================================================


class TestArchitectClient:
    """Verify all 4 ArchitectClient methods with mocked MCP session."""

    @pytest.mark.asyncio
    async def test_decompose_happy_path(self):
        """decompose returns dict from MCP call."""
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_make_result(json.dumps({"services": ["auth", "billing"]}))
        )
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.decompose("Build a SaaS app")

        assert isinstance(result, dict)
        assert result["services"] == ["auth", "billing"]

    @pytest.mark.asyncio
    async def test_decompose_returns_empty_dict_on_error(self):
        """decompose returns {} on exception."""
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.decompose("Build a SaaS app")

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_service_map_happy_path(self):
        """get_service_map returns dict from MCP call."""
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_make_result(json.dumps({"nodes": ["a"], "edges": []}))
        )
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_service_map()

        assert isinstance(result, dict)
        assert "nodes" in result

    @pytest.mark.asyncio
    async def test_get_service_map_returns_empty_dict_on_error(self):
        """get_service_map returns {} on exception."""
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("down"))
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_service_map()

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_contracts_for_service_happy_path(self):
        """get_contracts_for_service returns list from MCP call."""
        contracts = [{"id": "c-1"}, {"id": "c-2"}]
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_make_result(json.dumps(contracts))
        )
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_contracts_for_service("auth")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "c-1"

    @pytest.mark.asyncio
    async def test_get_contracts_for_service_returns_empty_list_on_error(self):
        """get_contracts_for_service returns [] on exception."""
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("fail"))
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_contracts_for_service("auth")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_domain_model_happy_path(self):
        """get_domain_model returns dict from MCP call."""
        model = {"entities": ["User", "Order"]}
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_make_result(json.dumps(model))
        )
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_domain_model("auth")

        assert isinstance(result, dict)
        assert result["entities"] == ["User", "Order"]

    @pytest.mark.asyncio
    async def test_get_domain_model_returns_empty_dict_on_error(self):
        """get_domain_model returns {} on exception."""
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("fail"))
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_domain_model("auth")

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_domain_model_with_service_name(self):
        """get_domain_model passes service_name in args when provided."""
        captured_args: list[dict] = []

        async def _capture_call(tool_name: str, arguments: dict):
            captured_args.append(arguments)
            return _make_result(json.dumps({"entities": []}))

        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=_capture_call)
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            await client.get_domain_model("billing")

        assert len(captured_args) >= 1
        assert captured_args[0]["service_name"] == "billing"

    @pytest.mark.asyncio
    async def test_get_domain_model_without_service_name(self):
        """get_domain_model passes empty args when no service_name."""
        captured_args: list[dict] = []

        async def _capture_call(tool_name: str, arguments: dict):
            captured_args.append(arguments)
            return _make_result(json.dumps({"entities": []}))

        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=_capture_call)
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            await client.get_domain_model()

        assert len(captured_args) >= 1
        assert "service_name" not in captured_args[0]

    @pytest.mark.asyncio
    async def test_type_check_dict_returns_empty_on_list(self):
        """decompose returns {} when MCP returns a list instead of dict."""
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_make_result(json.dumps(["not", "a", "dict"]))
        )
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.decompose("description")

        assert result == {}

    @pytest.mark.asyncio
    async def test_type_check_list_returns_empty_on_dict(self):
        """get_contracts_for_service returns [] when MCP returns a dict instead of list."""
        session = AsyncMock()
        session.call_tool = AsyncMock(
            return_value=_make_result(json.dumps({"not": "a list"}))
        )
        client = ArchitectClient(session)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.get_contracts_for_service("auth")

        assert result == []


# =========================================================================
# Test Group 3: ServiceContractRegistry Edge Cases
# =========================================================================


class TestRegistryEdgeCases:
    """Edge-case coverage for ServiceContractRegistry."""

    @pytest.mark.asyncio
    async def test_load_from_mcp_with_cache_fallback(self, tmp_path):
        """When MCP fails and cache_path provided, falls back to load_from_local."""
        # Create a valid local cache file
        cache_path = tmp_path / "contracts_cache.json"
        cache_data = {
            "version": "1.0",
            "contracts": {
                "c-fallback": {
                    "contract_type": "openapi",
                    "provider_service": "cached-svc",
                    "consumer_service": "",
                    "version": "1.0",
                    "spec_hash": "abc",
                    "spec": {},
                    "implemented": False,
                    "evidence_path": "",
                }
            },
        }
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        # Mock client that fails
        mock_client = AsyncMock()
        mock_client.get_unimplemented_contracts = AsyncMock(
            side_effect=ConnectionError("MCP server unreachable")
        )

        registry = ServiceContractRegistry()
        await registry.load_from_mcp(mock_client, cache_path=cache_path)

        # Should have loaded from the local cache fallback
        assert len(registry.contracts) == 1
        assert "c-fallback" in registry.contracts
        assert registry.contracts["c-fallback"].provider_service == "cached-svc"

    @pytest.mark.asyncio
    async def test_mark_implemented_returns_false_no_local_update(self):
        """When MCP returns {'marked': False}, local contract state is NOT updated."""
        registry = ServiceContractRegistry()
        registry._contracts["c-1"] = ServiceContract(
            contract_id="c-1",
            contract_type="openapi",
            provider_service="auth",
            consumer_service="",
            version="1.0",
            spec_hash="abc",
            implemented=False,
            evidence_path="",
        )

        mock_client = AsyncMock()
        mock_client.mark_implemented = AsyncMock(
            return_value={"marked": False, "reason": "contract not found on server"}
        )

        result = await registry.mark_implemented(mock_client, "c-1", "auth", "/evidence.py")

        assert result["marked"] is False
        # Local state should NOT be updated
        assert registry.contracts["c-1"].implemented is False
        assert registry.contracts["c-1"].evidence_path == ""

    @pytest.mark.asyncio
    async def test_mark_implemented_unknown_contract_id(self):
        """When contract_id not in registry, no KeyError (graceful)."""
        registry = ServiceContractRegistry()
        # Registry is empty -- "c-unknown" does not exist

        mock_client = AsyncMock()
        mock_client.mark_implemented = AsyncMock(
            return_value={"marked": True, "total": 1, "all_implemented": False}
        )

        # Should not raise KeyError
        result = await registry.mark_implemented(mock_client, "c-unknown", "auth")

        assert result["marked"] is True
        # The contract should NOT have been magically added to the registry
        assert "c-unknown" not in registry.contracts

    def test_load_from_local_invalid_json(self, tmp_path):
        """load_from_local with invalid JSON file does not crash."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json!!!}", encoding="utf-8")

        registry = ServiceContractRegistry()
        # Should not raise
        registry.load_from_local(bad_file)

        assert len(registry.contracts) == 0

    def test_load_from_local_missing_file(self, tmp_path):
        """load_from_local with nonexistent file does not crash."""
        registry = ServiceContractRegistry()
        registry.load_from_local(tmp_path / "nonexistent" / "cache.json")

        assert len(registry.contracts) == 0


# =========================================================================
# Test Group 4: Retry Logic Edge Cases
# =========================================================================


class TestRetryEdgeCases:
    """Edge-case coverage for _call_with_retry retry logic."""

    @pytest.mark.asyncio
    async def test_connection_error_is_retried(self):
        """ConnectionError triggers retry (not just TimeoutError)."""
        call_count = 0

        async def _failing_then_ok(tool_name, arguments):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("connection reset")
            return _make_result(json.dumps({"ok": True}))

        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=_failing_then_ok)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await _call_with_retry(session, "test_tool", {})

        assert result == {"ok": True}
        assert call_count == 3  # 2 failures + 1 success
        # Verify backoff sleep was called twice (attempt 0 and 1)
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises_last_error(self):
        """After 3 retries, the last error is raised."""
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("persistent failure"))

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(OSError, match="persistent failure"):
                await _call_with_retry(session, "test_tool", {})

        # Should have been called exactly 3 times (_MAX_RETRIES)
        assert session.call_tool.call_count == 3

    @pytest.mark.asyncio
    async def test_is_error_response_retried(self):
        """MCP isError=True responses are retried up to 3 times."""
        call_count = 0

        async def _is_error_then_ok(tool_name, arguments):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return _make_result("Server error", is_error=True)
            return _make_result(json.dumps({"success": True}))

        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=_is_error_then_ok)

        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await _call_with_retry(session, "test_tool", {})

        assert result == {"success": True}
        assert call_count == 3  # 2 isError retries + 1 success


# =========================================================================
# Test Group 5: Contract Scanner Edge Cases
# =========================================================================


class TestContractScannerEdgeCases:
    """Edge-case coverage for contract_scanner module."""

    def test_severity_sort_order(self, tmp_path):
        """run_contract_compliance_scan returns errors before warnings."""
        from agent_team_v15.contract_scanner import run_contract_compliance_scan

        # Create a contract that will produce both errors and warnings
        # CONTRACT-002 (missing endpoint) will produce errors
        # CONTRACT-004 (shared model drift) may produce warnings
        contract = {
            "contract_id": "sort-test",
            "contract_type": "openapi",
            "provider_service": "test-service",
            "consumer_service": "",
            "version": "1.0.0",
            "spec": {
                "openapi": "3.0.0",
                "paths": {
                    "/items": {
                        "get": {
                            "responses": {
                                "200": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "itemId": {"type": "string"},
                                                    "itemName": {"type": "string"},
                                                },
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "/orders": {
                        "post": {
                            "responses": {
                                "201": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "orderId": {"type": "string"},
                                                },
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                },
                "components": {
                    "schemas": {
                        "Item": {
                            "type": "object",
                            "properties": {
                                "itemId": {"type": "string"},
                                "itemName": {"type": "string"},
                            },
                        }
                    }
                },
            },
            "implemented": False,
        }

        # Create a Python file with ALLCAPS variant to trigger CONTRACT-004
        # drift warning (case-insensitive match but not proper casing convention)
        py_file = tmp_path / "src" / "models" / "item.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text(textwrap.dedent("""
            from dataclasses import dataclass

            @dataclass
            class Item:
                ITEMID: str = ""
                ITEMNAME: str = ""
        """))

        violations = run_contract_compliance_scan(tmp_path, [contract])

        if len(violations) >= 2:
            # Verify that errors come before warnings in the sorted output
            saw_warning = False
            for v in violations:
                if v.severity == "warning":
                    saw_warning = True
                elif v.severity == "error" and saw_warning:
                    pytest.fail(
                        "Found an error after a warning -- violations are not sorted correctly"
                    )

    def test_fastapi_route_detection(self, tmp_path):
        """FastAPI @router.get('/path') is detected as a route."""
        from agent_team_v15.contract_scanner import run_missing_endpoint_scan

        # Create a FastAPI-style route file
        py_file = tmp_path / "src" / "routes" / "items.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text(textwrap.dedent("""
            from fastapi import APIRouter

            router = APIRouter()

            @router.get('/items')
            async def list_items():
                return []

            @router.post('/items')
            async def create_item(data: dict):
                return data
        """))

        # Contract expects GET /items and POST /items
        contract = {
            "contract_id": "fastapi-test",
            "contract_type": "openapi",
            "provider_service": "item-service",
            "version": "1.0.0",
            "spec": {
                "openapi": "3.0.0",
                "paths": {
                    "/items": {
                        "get": {
                            "operationId": "listItems",
                            "responses": {"200": {}},
                        },
                        "post": {
                            "operationId": "createItem",
                            "responses": {"201": {}},
                        },
                    }
                },
            },
            "implemented": False,
        }

        violations = run_missing_endpoint_scan(tmp_path, [contract])

        # Both routes should be detected -- no CONTRACT-002 violations
        assert len(violations) == 0, (
            f"Expected 0 violations for FastAPI routes but got {len(violations)}: "
            + "; ".join(v.message for v in violations)
        )


# =========================================================================
# Test Group 6: _normalize_path coverage
# =========================================================================


class TestNormalizePath:
    """Verify _normalize_path handles various route path formats."""

    def test_strip_trailing_slash(self):
        from agent_team_v15.contract_scanner import _normalize_path

        assert _normalize_path("/users/") == "/users"

    def test_curly_brace_param(self):
        from agent_team_v15.contract_scanner import _normalize_path

        result = _normalize_path("/users/{userId}")
        assert result == "/users/:param"

    def test_flask_angle_bracket_param(self):
        from agent_team_v15.contract_scanner import _normalize_path

        result = _normalize_path("/users/<int:user_id>")
        assert result == "/users/:param"

    def test_express_colon_param(self):
        from agent_team_v15.contract_scanner import _normalize_path

        result = _normalize_path("/users/:userId")
        assert result == "/users/:param"

    def test_lowercase_normalization(self):
        from agent_team_v15.contract_scanner import _normalize_path

        assert _normalize_path("/Users/Profile") == "/users/profile"
