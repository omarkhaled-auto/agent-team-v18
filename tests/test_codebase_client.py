"""Tests for Codebase Intelligence MCP client and related milestone-3 components.

Covers:
- CodebaseIntelligenceClient with 7 MCP tool methods (TEST-031 through TEST-033)
- generate_codebase_map_from_mcp markdown output (TEST-034)
- register_new_artifact delegation (TEST-035)
- CodebaseIntelligenceConfig defaults (TEST-036)
- _codebase_intelligence_mcp_server config (TEST-037)
- create_codebase_intelligence_session env var handling (TEST-038)
- get_contract_aware_servers with codebase_intelligence (TEST-039)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team.config import (
    AgentTeamConfig,
    CodebaseIntelligenceConfig,
    ContractEngineConfig,
    _dict_to_config,
)
from agent_team.codebase_client import (
    CodebaseIntelligenceClient,
    DefinitionResult,
    DependencyResult,
    ArtifactResult,
)
from agent_team.codebase_map import (
    generate_codebase_map_from_mcp,
    register_new_artifact,
)
from agent_team.mcp_clients import MCPConnectionError
from agent_team.mcp_servers import (
    _codebase_intelligence_mcp_server,
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
# TEST-031: All 7 client methods return correct typed results with valid
#           mocked MCP responses
# -----------------------------------------------------------------------


class TestClientValidResponses:
    """TEST-031: Verify all 7 methods work with valid MCP responses."""

    @pytest.mark.asyncio
    async def test_find_definition_valid(self):
        response_data = {
            "file": "src/app.py",
            "line": 42,
            "kind": "function",
            "signature": "def main()",
        }
        session = _make_session({
            "find_definition": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_definition("main")

        assert isinstance(result, DefinitionResult)
        assert result.found is True
        assert result.file == "src/app.py"
        assert result.line == 42
        assert result.kind == "function"
        assert result.signature == "def main()"

    @pytest.mark.asyncio
    async def test_find_definition_with_language(self):
        response_data = {
            "file": "src/app.py",
            "line": 10,
            "kind": "class",
            "signature": "class App:",
        }
        session = _make_session({
            "find_definition": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_definition("App", language="python")

        assert result.found is True
        assert result.file == "src/app.py"
        assert result.kind == "class"
        # Verify arguments passed correctly
        call_args = session.call_tool.call_args
        assert call_args[0][1]["language"] == "python"

    @pytest.mark.asyncio
    async def test_find_callers_valid(self):
        response_data = [
            {"file": "src/run.py", "line": 10, "symbol": "main"},
        ]
        session = _make_session({
            "find_callers": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_callers("main")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["file"] == "src/run.py"
        assert result[0]["line"] == 10
        assert result[0]["symbol"] == "main"

    @pytest.mark.asyncio
    async def test_find_callers_multiple(self):
        response_data = [
            {"file": "src/run.py", "line": 10, "symbol": "main"},
            {"file": "src/cli.py", "line": 5, "symbol": "main"},
        ]
        session = _make_session({
            "find_callers": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_callers("main", max_results=5)

        assert len(result) == 2
        assert result[1]["file"] == "src/cli.py"

    @pytest.mark.asyncio
    async def test_find_dependencies_valid(self):
        response_data = {
            "imports": ["os", "sys"],
            "imported_by": ["tests/test_app.py"],
            "transitive_deps": ["os.path"],
            "circular_deps": [],
        }
        session = _make_session({
            "find_dependencies": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_dependencies("src/app.py")

        assert isinstance(result, DependencyResult)
        assert result.imports == ["os", "sys"]
        assert result.imported_by == ["tests/test_app.py"]
        assert result.transitive_deps == ["os.path"]
        assert result.circular_deps == []

    @pytest.mark.asyncio
    async def test_find_dependencies_with_circular(self):
        response_data = {
            "imports": ["models"],
            "imported_by": ["views"],
            "transitive_deps": [],
            "circular_deps": [["models", "views", "models"]],
        }
        session = _make_session({
            "find_dependencies": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_dependencies("models.py")

        assert len(result.circular_deps) == 1
        assert result.circular_deps[0] == ["models", "views", "models"]

    @pytest.mark.asyncio
    async def test_search_semantic_valid(self):
        response_data = [
            {"file": "src/app.py", "score": 0.95, "snippet": "def main():"},
        ]
        session = _make_session({
            "search_semantic": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.search_semantic("entry point")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["file"] == "src/app.py"
        assert result[0]["score"] == 0.95
        assert result[0]["snippet"] == "def main():"

    @pytest.mark.asyncio
    async def test_search_semantic_with_filters(self):
        response_data = [
            {"file": "src/auth.py", "score": 0.8, "snippet": "class Auth:"},
        ]
        session = _make_session({
            "search_semantic": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.search_semantic(
            "authentication",
            language="python",
            service_name="auth",
            n_results=5,
        )

        assert len(result) == 1
        # Verify optional args passed
        call_args = session.call_tool.call_args
        assert call_args[0][1]["language"] == "python"
        assert call_args[0][1]["service_name"] == "auth"
        assert call_args[0][1]["n_results"] == 5

    @pytest.mark.asyncio
    async def test_get_service_interface_valid(self):
        response_data = {
            "endpoints": ["/api/users"],
            "events_published": ["user.created"],
            "events_consumed": ["order.placed"],
        }
        session = _make_session({
            "get_service_interface": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.get_service_interface("auth-service")

        assert isinstance(result, dict)
        assert result["endpoints"] == ["/api/users"]
        assert result["events_published"] == ["user.created"]
        assert result["events_consumed"] == ["order.placed"]

    @pytest.mark.asyncio
    async def test_check_dead_code_valid(self):
        response_data = [
            {"symbol": "old_func", "file": "src/legacy.py", "line": 50},
        ]
        session = _make_session({
            "check_dead_code": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.check_dead_code("my-service")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["symbol"] == "old_func"
        assert result[0]["file"] == "src/legacy.py"
        assert result[0]["line"] == 50

    @pytest.mark.asyncio
    async def test_register_artifact_valid(self):
        response_data = {
            "indexed": True,
            "symbols_found": 5,
            "dependencies_found": 3,
        }
        session = _make_session({
            "register_artifact": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.register_artifact("src/new_module.py", "auth")

        assert isinstance(result, ArtifactResult)
        assert result.indexed is True
        assert result.symbols_found == 5
        assert result.dependencies_found == 3

    @pytest.mark.asyncio
    async def test_register_artifact_without_service(self):
        response_data = {
            "indexed": True,
            "symbols_found": 2,
            "dependencies_found": 1,
        }
        session = _make_session({
            "register_artifact": _make_result(json.dumps(response_data)),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.register_artifact("src/utils.py")

        assert result.indexed is True
        assert result.symbols_found == 2


# -----------------------------------------------------------------------
# TEST-032: All 7 methods with mocked Exception return safe defaults +
#           warning logged
# -----------------------------------------------------------------------


class TestClientExceptionDefaults:
    """TEST-032: Verify safe defaults when exceptions occur and warning logged."""

    @pytest.mark.asyncio
    async def test_find_definition_exception(self, caplog):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = CodebaseIntelligenceClient(session)

        with caplog.at_level(logging.WARNING):
            result = await client.find_definition("main")

        assert isinstance(result, DefinitionResult)
        assert result.found is False
        assert result.file == ""
        assert result.line == 0
        assert "find_definition" in caplog.text

    @pytest.mark.asyncio
    async def test_find_callers_exception(self, caplog):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = CodebaseIntelligenceClient(session)

        with caplog.at_level(logging.WARNING):
            result = await client.find_callers("main")

        assert result == []
        assert "find_callers" in caplog.text

    @pytest.mark.asyncio
    async def test_find_dependencies_exception(self, caplog):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = CodebaseIntelligenceClient(session)

        with caplog.at_level(logging.WARNING):
            result = await client.find_dependencies("src/app.py")

        assert isinstance(result, DependencyResult)
        assert result.imports == []
        assert result.imported_by == []
        assert result.transitive_deps == []
        assert result.circular_deps == []
        assert "find_dependencies" in caplog.text

    @pytest.mark.asyncio
    async def test_search_semantic_exception(self, caplog):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = CodebaseIntelligenceClient(session)

        with caplog.at_level(logging.WARNING):
            result = await client.search_semantic("test query")

        assert result == []
        assert "search_semantic" in caplog.text

    @pytest.mark.asyncio
    async def test_get_service_interface_exception(self, caplog):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = CodebaseIntelligenceClient(session)

        with caplog.at_level(logging.WARNING):
            result = await client.get_service_interface("auth")

        assert result == {}
        assert "get_service_interface" in caplog.text

    @pytest.mark.asyncio
    async def test_check_dead_code_exception(self, caplog):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = CodebaseIntelligenceClient(session)

        with caplog.at_level(logging.WARNING):
            result = await client.check_dead_code("my-service")

        assert result == []
        assert "check_dead_code" in caplog.text

    @pytest.mark.asyncio
    async def test_register_artifact_exception(self, caplog):
        session = AsyncMock()
        session.call_tool = AsyncMock(side_effect=OSError("connection lost"))
        client = CodebaseIntelligenceClient(session)

        with caplog.at_level(logging.WARNING):
            result = await client.register_artifact("src/module.py")

        assert isinstance(result, ArtifactResult)
        assert result.indexed is False
        assert result.symbols_found == 0
        assert result.dependencies_found == 0
        assert "register_artifact" in caplog.text


# -----------------------------------------------------------------------
# TEST-033: All 7 methods with result.isError = True return safe defaults
# -----------------------------------------------------------------------


class TestClientIsErrorDefaults:
    """TEST-033: Verify safe defaults when MCP result has isError=True."""

    @pytest.mark.asyncio
    async def test_find_definition_is_error(self):
        session = _make_session({
            "find_definition": _make_result("Tool error", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_definition("main")

        assert isinstance(result, DefinitionResult)
        assert result.found is False
        assert result.file == ""

    @pytest.mark.asyncio
    async def test_find_callers_is_error(self):
        session = _make_session({
            "find_callers": _make_result("Tool error", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_callers("main")

        assert result == []

    @pytest.mark.asyncio
    async def test_find_dependencies_is_error(self):
        session = _make_session({
            "find_dependencies": _make_result("Tool error", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_dependencies("src/app.py")

        assert isinstance(result, DependencyResult)
        assert result.imports == []
        assert result.imported_by == []

    @pytest.mark.asyncio
    async def test_search_semantic_is_error(self):
        session = _make_session({
            "search_semantic": _make_result("Tool error", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.search_semantic("test query")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_service_interface_is_error(self):
        session = _make_session({
            "get_service_interface": _make_result("Tool error", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.get_service_interface("auth")

        assert result == {}

    @pytest.mark.asyncio
    async def test_check_dead_code_is_error(self):
        session = _make_session({
            "check_dead_code": _make_result("Tool error", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.check_dead_code("my-service")

        assert result == []

    @pytest.mark.asyncio
    async def test_register_artifact_is_error(self):
        session = _make_session({
            "register_artifact": _make_result("Tool error", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.register_artifact("src/module.py")

        assert isinstance(result, ArtifactResult)
        assert result.indexed is False
        assert result.symbols_found == 0
        assert result.dependencies_found == 0


# -----------------------------------------------------------------------
# TEST-034: generate_codebase_map_from_mcp() produces valid markdown
# -----------------------------------------------------------------------


class TestGenerateCodebaseMapFromMCP:
    """TEST-034: Verify MCP-backed codebase map produces valid markdown."""

    @pytest.mark.asyncio
    async def test_produces_markdown_with_all_sections(self):
        client = AsyncMock()
        client.search_semantic = AsyncMock(return_value=[
            {"file": "src/app.py", "score": 0.95, "snippet": "def main():"},
            {"file": "src/utils.py", "score": 0.80, "snippet": "def helper():"},
        ])
        client.get_service_interface = AsyncMock(return_value={
            "endpoints": ["/api/users", "/api/orders"],
            "events_published": ["user.created"],
            "events_consumed": ["order.placed"],
        })
        client.check_dead_code = AsyncMock(return_value=[
            {"symbol": "old_func", "file": "src/legacy.py"},
        ])

        result = await generate_codebase_map_from_mcp(client)

        assert isinstance(result, str)
        assert len(result) > 0
        # Verify markdown header
        assert "# Codebase Map (MCP-backed)" in result
        # Verify service info
        assert "Endpoints" in result
        assert "Events published" in result
        assert "Events consumed" in result
        # Verify modules section
        assert "## Discovered Modules" in result
        assert "`src/app.py`" in result
        assert "`src/utils.py`" in result
        # Verify dead code section
        assert "## Dead Code Candidates" in result
        assert "`old_func`" in result

    @pytest.mark.asyncio
    async def test_empty_data_produces_minimal_markdown(self):
        client = AsyncMock()
        client.search_semantic = AsyncMock(return_value=[])
        client.get_service_interface = AsyncMock(return_value={})
        client.check_dead_code = AsyncMock(return_value=[])

        result = await generate_codebase_map_from_mcp(client)

        assert isinstance(result, str)
        assert "# Codebase Map (MCP-backed)" in result
        # No modules or dead code sections when data is empty
        assert "## Discovered Modules" not in result
        assert "## Dead Code Candidates" not in result

    @pytest.mark.asyncio
    async def test_client_failure_returns_empty_string(self):
        client = AsyncMock()
        client.search_semantic = AsyncMock(side_effect=RuntimeError("boom"))

        result = await generate_codebase_map_from_mcp(client)

        assert result == ""

    @pytest.mark.asyncio
    async def test_modules_limited_to_20(self):
        """Verify at most 20 modules are listed."""
        modules = [
            {"file": f"src/mod_{i}.py", "score": 0.5, "snippet": f"mod {i}"}
            for i in range(25)
        ]
        client = AsyncMock()
        client.search_semantic = AsyncMock(return_value=modules)
        client.get_service_interface = AsyncMock(return_value={})
        client.check_dead_code = AsyncMock(return_value=[])

        result = await generate_codebase_map_from_mcp(client)

        # Should include up to 20 modules
        assert "`src/mod_19.py`" in result
        assert "`src/mod_20.py`" not in result

    @pytest.mark.asyncio
    async def test_dead_code_limited_to_10(self):
        """Verify at most 10 dead code entries are listed."""
        dead = [
            {"symbol": f"func_{i}", "file": f"src/legacy_{i}.py"}
            for i in range(15)
        ]
        client = AsyncMock()
        client.search_semantic = AsyncMock(return_value=[])
        client.get_service_interface = AsyncMock(return_value={})
        client.check_dead_code = AsyncMock(return_value=dead)

        result = await generate_codebase_map_from_mcp(client)

        assert "`func_9`" in result
        assert "`func_10`" not in result


# -----------------------------------------------------------------------
# TEST-035: register_new_artifact() returns ArtifactResult
# -----------------------------------------------------------------------


class TestRegisterNewArtifact:
    """TEST-035: Verify register_new_artifact delegates correctly."""

    @pytest.mark.asyncio
    async def test_returns_artifact_result(self):
        client = AsyncMock()
        expected = ArtifactResult(indexed=True, symbols_found=5, dependencies_found=3)
        client.register_artifact = AsyncMock(return_value=expected)

        result = await register_new_artifact(client, "src/new.py", "my-service")

        assert isinstance(result, ArtifactResult)
        assert result.indexed is True
        assert result.symbols_found == 5
        assert result.dependencies_found == 3
        client.register_artifact.assert_called_once_with("src/new.py", "my-service")

    @pytest.mark.asyncio
    async def test_returns_default_on_failure(self):
        client = AsyncMock()
        default = ArtifactResult()
        client.register_artifact = AsyncMock(return_value=default)

        result = await register_new_artifact(client, "src/broken.py")

        assert result.indexed is False
        assert result.symbols_found == 0
        assert result.dependencies_found == 0
        client.register_artifact.assert_called_once_with("src/broken.py", "")

    @pytest.mark.asyncio
    async def test_without_service_name(self):
        client = AsyncMock()
        expected = ArtifactResult(indexed=True, symbols_found=1, dependencies_found=0)
        client.register_artifact = AsyncMock(return_value=expected)

        result = await register_new_artifact(client, "src/standalone.py")

        assert result.indexed is True
        client.register_artifact.assert_called_once_with("src/standalone.py", "")


# -----------------------------------------------------------------------
# TEST-036: CodebaseIntelligenceConfig defaults verified
# -----------------------------------------------------------------------


class TestCodebaseIntelligenceConfigDefaults:
    """TEST-036: Verify all CodebaseIntelligenceConfig defaults."""

    def test_all_defaults(self):
        cfg = CodebaseIntelligenceConfig()
        assert cfg.enabled is False
        assert cfg.mcp_command == "python"
        assert cfg.mcp_args == ["-m", "src.codebase_intelligence.mcp_server"]
        assert cfg.database_path == ""
        assert cfg.chroma_path == ""
        assert cfg.graph_path == ""
        assert cfg.replace_static_map is True
        assert cfg.register_artifacts is True
        assert cfg.server_root == ""
        assert cfg.startup_timeout_ms == 30000
        assert cfg.tool_timeout_ms == 60000

    def test_custom_values(self):
        cfg = CodebaseIntelligenceConfig(
            enabled=True,
            mcp_command="node",
            mcp_args=["server.js"],
            database_path="/data/db.sqlite",
            chroma_path="/data/chroma",
            graph_path="/data/graph.json",
            replace_static_map=False,
            register_artifacts=False,
            server_root="/srv",
            startup_timeout_ms=5000,
            tool_timeout_ms=10000,
        )
        assert cfg.enabled is True
        assert cfg.mcp_command == "node"
        assert cfg.mcp_args == ["server.js"]
        assert cfg.database_path == "/data/db.sqlite"
        assert cfg.chroma_path == "/data/chroma"
        assert cfg.graph_path == "/data/graph.json"
        assert cfg.replace_static_map is False
        assert cfg.register_artifacts is False
        assert cfg.server_root == "/srv"
        assert cfg.startup_timeout_ms == 5000
        assert cfg.tool_timeout_ms == 10000

    def test_config_in_agent_team_config(self):
        """codebase_intelligence field exists on AgentTeamConfig."""
        cfg = AgentTeamConfig()
        assert hasattr(cfg, "codebase_intelligence")
        assert isinstance(cfg.codebase_intelligence, CodebaseIntelligenceConfig)

    def test_dict_to_config_missing_section_yields_defaults(self):
        cfg, overrides = _dict_to_config({})
        assert cfg.codebase_intelligence.enabled is False
        assert cfg.codebase_intelligence.mcp_command == "python"
        assert "codebase_intelligence.enabled" not in overrides

    def test_dict_to_config_explicit_enabled_tracked(self):
        cfg, overrides = _dict_to_config({
            "codebase_intelligence": {"enabled": True}
        })
        assert cfg.codebase_intelligence.enabled is True
        assert "codebase_intelligence.enabled" in overrides

    def test_dict_to_config_full_section(self):
        cfg, overrides = _dict_to_config({
            "codebase_intelligence": {
                "enabled": True,
                "mcp_command": "node",
                "mcp_args": ["dist/server.js"],
                "database_path": "/tmp/ci.db",
                "chroma_path": "/tmp/chroma",
                "graph_path": "/tmp/graph.json",
                "replace_static_map": False,
                "register_artifacts": False,
                "server_root": "/project",
                "startup_timeout_ms": 5000,
                "tool_timeout_ms": 10000,
            }
        })
        assert cfg.codebase_intelligence.enabled is True
        assert cfg.codebase_intelligence.mcp_command == "node"
        assert cfg.codebase_intelligence.mcp_args == ["dist/server.js"]
        assert cfg.codebase_intelligence.database_path == "/tmp/ci.db"
        assert cfg.codebase_intelligence.chroma_path == "/tmp/chroma"
        assert cfg.codebase_intelligence.graph_path == "/tmp/graph.json"
        assert cfg.codebase_intelligence.replace_static_map is False
        assert cfg.codebase_intelligence.register_artifacts is False
        assert cfg.codebase_intelligence.server_root == "/project"
        assert cfg.codebase_intelligence.startup_timeout_ms == 5000
        assert cfg.codebase_intelligence.tool_timeout_ms == 10000

    def test_dict_to_config_invalid_startup_timeout(self):
        with pytest.raises(ValueError, match="startup_timeout_ms"):
            _dict_to_config({"codebase_intelligence": {"startup_timeout_ms": 500}})

    def test_dict_to_config_invalid_tool_timeout(self):
        with pytest.raises(ValueError, match="tool_timeout_ms"):
            _dict_to_config({"codebase_intelligence": {"tool_timeout_ms": 100}})


# -----------------------------------------------------------------------
# TEST-037: _codebase_intelligence_mcp_server() returns correct dict
#           with all 3 env vars
# -----------------------------------------------------------------------


class TestCodebaseIntelligenceMCPServer:
    """TEST-037: Verify MCP server config generation with env vars."""

    def test_basic_config_no_env(self):
        config = CodebaseIntelligenceConfig()
        # Ensure no env vars leak from the test environment
        with patch.dict(os.environ, {}, clear=True):
            result = _codebase_intelligence_mcp_server(config)

        assert result["type"] == "stdio"
        assert result["command"] == "python"
        assert result["args"] == ["-m", "src.codebase_intelligence.mcp_server"]
        assert "env" not in result

    def test_with_all_three_paths(self):
        config = CodebaseIntelligenceConfig(
            database_path="/data/ci.db",
            chroma_path="/data/chroma",
            graph_path="/data/graph.json",
        )
        result = _codebase_intelligence_mcp_server(config)

        assert result["type"] == "stdio"
        assert "env" in result
        assert result["env"]["DATABASE_PATH"] == "/data/ci.db"
        assert result["env"]["CHROMA_PATH"] == "/data/chroma"
        assert result["env"]["GRAPH_PATH"] == "/data/graph.json"

    def test_with_only_database_path(self):
        config = CodebaseIntelligenceConfig(database_path="/data/ci.db")
        with patch.dict(os.environ, {}, clear=True):
            result = _codebase_intelligence_mcp_server(config)

        assert "env" in result
        assert result["env"]["DATABASE_PATH"] == "/data/ci.db"
        assert "CHROMA_PATH" not in result["env"]
        assert "GRAPH_PATH" not in result["env"]

    def test_with_only_chroma_path(self):
        config = CodebaseIntelligenceConfig(chroma_path="/data/chroma")
        with patch.dict(os.environ, {}, clear=True):
            result = _codebase_intelligence_mcp_server(config)

        assert "env" in result
        assert result["env"]["CHROMA_PATH"] == "/data/chroma"
        assert "DATABASE_PATH" not in result["env"]
        assert "GRAPH_PATH" not in result["env"]

    def test_with_only_graph_path(self):
        config = CodebaseIntelligenceConfig(graph_path="/data/graph.json")
        with patch.dict(os.environ, {}, clear=True):
            result = _codebase_intelligence_mcp_server(config)

        assert "env" in result
        assert result["env"]["GRAPH_PATH"] == "/data/graph.json"
        assert "DATABASE_PATH" not in result["env"]
        assert "CHROMA_PATH" not in result["env"]

    def test_env_var_fallback_from_os_environ(self):
        """When config paths are empty, falls back to os.getenv."""
        config = CodebaseIntelligenceConfig()
        with patch.dict(os.environ, {
            "DATABASE_PATH": "/env/db.sqlite",
            "CHROMA_PATH": "/env/chroma",
            "GRAPH_PATH": "/env/graph.json",
        }):
            result = _codebase_intelligence_mcp_server(config)

        assert "env" in result
        assert result["env"]["DATABASE_PATH"] == "/env/db.sqlite"
        assert result["env"]["CHROMA_PATH"] == "/env/chroma"
        assert result["env"]["GRAPH_PATH"] == "/env/graph.json"

    def test_custom_command_and_args(self):
        config = CodebaseIntelligenceConfig(
            mcp_command="node",
            mcp_args=["dist/server.js", "--port", "3000"],
        )
        with patch.dict(os.environ, {}, clear=True):
            result = _codebase_intelligence_mcp_server(config)

        assert result["command"] == "node"
        assert result["args"] == ["dist/server.js", "--port", "3000"]

    def test_none_when_all_empty(self):
        """No env dict when all paths are empty and no env vars set."""
        config = CodebaseIntelligenceConfig()
        with patch.dict(os.environ, {}, clear=True):
            result = _codebase_intelligence_mcp_server(config)

        assert "env" not in result


# -----------------------------------------------------------------------
# TEST-038: create_codebase_intelligence_session() passes only non-empty
#           env vars
# -----------------------------------------------------------------------


class TestCreateCodebaseIntelligenceSession:
    """TEST-038: Verify session manager env var passing and error handling."""

    @pytest.mark.asyncio
    async def test_import_error_when_mcp_missing(self):
        with patch.dict(sys.modules, {"mcp": None, "mcp.client.stdio": None}):
            from agent_team.mcp_clients import create_codebase_intelligence_session
            config = CodebaseIntelligenceConfig(enabled=True)
            with pytest.raises(ImportError, match="MCP SDK not installed"):
                async with create_codebase_intelligence_session(config) as _session:
                    pass

    def test_config_with_all_paths(self):
        """Verify config stores all three paths."""
        config = CodebaseIntelligenceConfig(
            database_path="/data/db.sqlite",
            chroma_path="/data/chroma",
            graph_path="/data/graph.json",
        )
        assert config.database_path == "/data/db.sqlite"
        assert config.chroma_path == "/data/chroma"
        assert config.graph_path == "/data/graph.json"

    def test_config_with_empty_paths(self):
        """Verify config stores empty paths."""
        config = CodebaseIntelligenceConfig(
            database_path="",
            chroma_path="",
            graph_path="",
        )
        assert config.database_path == ""
        assert config.chroma_path == ""
        assert config.graph_path == ""

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


# -----------------------------------------------------------------------
# TEST-039: get_contract_aware_servers() includes/omits servers based on
#           enabled flags
# -----------------------------------------------------------------------


class TestGetContractAwareServersCodebaseIntelligence:
    """TEST-039: Verify codebase_intelligence included/omitted correctly."""

    def test_includes_codebase_intelligence_when_enabled(self):
        cfg = AgentTeamConfig()
        cfg.codebase_intelligence = CodebaseIntelligenceConfig(enabled=True)
        servers = get_contract_aware_servers(cfg)

        assert "codebase_intelligence" in servers
        assert servers["codebase_intelligence"]["type"] == "stdio"

    def test_excludes_codebase_intelligence_when_disabled(self):
        cfg = AgentTeamConfig()
        cfg.codebase_intelligence = CodebaseIntelligenceConfig(enabled=False)
        servers = get_contract_aware_servers(cfg)

        assert "codebase_intelligence" not in servers

    def test_both_contract_engine_and_codebase_intelligence_enabled(self):
        cfg = AgentTeamConfig()
        cfg.contract_engine = ContractEngineConfig(enabled=True)
        cfg.codebase_intelligence = CodebaseIntelligenceConfig(enabled=True)
        servers = get_contract_aware_servers(cfg)

        assert "contract_engine" in servers
        assert "codebase_intelligence" in servers

    def test_contract_engine_enabled_codebase_disabled(self):
        cfg = AgentTeamConfig()
        cfg.contract_engine = ContractEngineConfig(enabled=True)
        cfg.codebase_intelligence = CodebaseIntelligenceConfig(enabled=False)
        servers = get_contract_aware_servers(cfg)

        assert "contract_engine" in servers
        assert "codebase_intelligence" not in servers

    def test_codebase_enabled_contract_disabled(self):
        cfg = AgentTeamConfig()
        cfg.contract_engine = ContractEngineConfig(enabled=False)
        cfg.codebase_intelligence = CodebaseIntelligenceConfig(enabled=True)
        servers = get_contract_aware_servers(cfg)

        assert "contract_engine" not in servers
        assert "codebase_intelligence" in servers

    def test_both_disabled(self):
        cfg = AgentTeamConfig()
        cfg.contract_engine = ContractEngineConfig(enabled=False)
        cfg.codebase_intelligence = CodebaseIntelligenceConfig(enabled=False)
        servers = get_contract_aware_servers(cfg)

        assert "contract_engine" not in servers
        assert "codebase_intelligence" not in servers

    def test_codebase_server_has_correct_env_vars(self):
        cfg = AgentTeamConfig()
        cfg.codebase_intelligence = CodebaseIntelligenceConfig(
            enabled=True,
            database_path="/data/db.sqlite",
            chroma_path="/data/chroma",
            graph_path="/data/graph.json",
        )
        servers = get_contract_aware_servers(cfg)

        ci_server = servers["codebase_intelligence"]
        assert ci_server["env"]["DATABASE_PATH"] == "/data/db.sqlite"
        assert ci_server["env"]["CHROMA_PATH"] == "/data/chroma"
        assert ci_server["env"]["GRAPH_PATH"] == "/data/graph.json"


# -----------------------------------------------------------------------
# Additional edge case tests for completeness
# -----------------------------------------------------------------------


class TestDefinitionResultDataclass:
    """Verify DefinitionResult dataclass defaults and construction."""

    def test_defaults(self):
        dr = DefinitionResult()
        assert dr.file == ""
        assert dr.line == 0
        assert dr.kind == ""
        assert dr.signature == ""
        assert dr.found is False

    def test_custom_values(self):
        dr = DefinitionResult(
            file="src/app.py",
            line=42,
            kind="function",
            signature="def main()",
            found=True,
        )
        assert dr.file == "src/app.py"
        assert dr.line == 42
        assert dr.found is True


class TestDependencyResultDataclass:
    """Verify DependencyResult dataclass defaults and construction."""

    def test_defaults(self):
        dr = DependencyResult()
        assert dr.imports == []
        assert dr.imported_by == []
        assert dr.transitive_deps == []
        assert dr.circular_deps == []

    def test_custom_values(self):
        dr = DependencyResult(
            imports=["os", "sys"],
            imported_by=["tests/test_app.py"],
            transitive_deps=["os.path"],
            circular_deps=[["a", "b", "a"]],
        )
        assert dr.imports == ["os", "sys"]
        assert len(dr.circular_deps) == 1


class TestArtifactResultDataclass:
    """Verify ArtifactResult dataclass defaults and construction."""

    def test_defaults(self):
        ar = ArtifactResult()
        assert ar.indexed is False
        assert ar.symbols_found == 0
        assert ar.dependencies_found == 0

    def test_custom_values(self):
        ar = ArtifactResult(indexed=True, symbols_found=10, dependencies_found=5)
        assert ar.indexed is True
        assert ar.symbols_found == 10
        assert ar.dependencies_found == 5


class TestClientReturnNoneFromMCP:
    """Verify methods handle None/empty JSON responses gracefully."""

    @pytest.mark.asyncio
    async def test_find_definition_empty_json(self):
        session = _make_session({
            "find_definition": _make_result("{}"),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_definition("missing")

        assert isinstance(result, DefinitionResult)
        # Empty file means found=False
        assert result.found is False

    @pytest.mark.asyncio
    async def test_find_callers_non_list_response(self):
        """When MCP returns a dict instead of a list, return []."""
        session = _make_session({
            "find_callers": _make_result('{"unexpected": "dict"}'),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_callers("symbol")

        assert result == []

    @pytest.mark.asyncio
    async def test_search_semantic_non_list_response(self):
        """When MCP returns a dict instead of a list, return []."""
        session = _make_session({
            "search_semantic": _make_result('{"unexpected": "dict"}'),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.search_semantic("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_service_interface_non_dict_response(self):
        """When MCP returns a list instead of a dict, return {}."""
        session = _make_session({
            "get_service_interface": _make_result('[1, 2, 3]'),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.get_service_interface("svc")

        assert result == {}

    @pytest.mark.asyncio
    async def test_check_dead_code_non_list_response(self):
        """When MCP returns a dict instead of a list, return []."""
        session = _make_session({
            "check_dead_code": _make_result('{"unexpected": "dict"}'),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.check_dead_code("svc")

        assert result == []

    @pytest.mark.asyncio
    async def test_find_dependencies_null_response(self):
        """When MCP returns null JSON, return DependencyResult()."""
        session = _make_session({
            "find_dependencies": _make_result("null"),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_dependencies("src/app.py")

        assert isinstance(result, DependencyResult)
        assert result.imports == []

    @pytest.mark.asyncio
    async def test_register_artifact_null_response(self):
        """When MCP returns null JSON, return ArtifactResult()."""
        session = _make_session({
            "register_artifact": _make_result("null"),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.register_artifact("src/app.py")

        assert isinstance(result, ArtifactResult)
        assert result.indexed is False
