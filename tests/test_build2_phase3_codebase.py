"""Tests for Build 2 Phase 3 — Codebase Intelligence gap coverage.

Covers gaps identified in Phase 2C:
- INT-005: register_artifact timeout behavior (no retry, single attempt)
- Codebase Intelligence session exception wrapping (MCPConnectionError)
- CodebaseIntelligenceClient edge cases (parameter inclusion/omission)
- Retry behavior through codebase client (_call_with_retry integration)
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.codebase_client import (
    ArtifactResult,
    CodebaseIntelligenceClient,
    DefinitionResult,
    DependencyResult,
)
from agent_team_v15.mcp_clients import (
    MCPConnectionError,
    create_codebase_intelligence_session,
)


# ---------------------------------------------------------------------------
# Helpers
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


def _make_session(tool_results: dict[str, SimpleNamespace | Any] | None = None) -> AsyncMock:
    """Create a mock MCP ClientSession that returns specific results per tool name."""
    session = AsyncMock()

    async def _call_tool(tool_name: str, arguments: dict) -> SimpleNamespace:
        if tool_results and tool_name in tool_results:
            result = tool_results[tool_name]
            if callable(result) and not asyncio.iscoroutine(result):
                return result(tool_name, arguments)
            return result
        return _make_result("{}")

    session.call_tool = AsyncMock(side_effect=_call_tool)
    return session


def _make_codebase_config(**overrides: Any) -> SimpleNamespace:
    """Build a minimal CodebaseIntelligenceConfig-like object."""
    defaults = dict(
        enabled=True,
        mcp_command="python",
        mcp_args=["-m", "src.codebase_intelligence.mcp_server"],
        database_path="",
        chroma_path="",
        graph_path="",
        replace_static_map=True,
        register_artifacts=True,
        server_root="",
        startup_timeout_ms=30000,
        tool_timeout_ms=60000,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ===========================================================================
# Test Group 1: register_artifact Timeout Behavior (INT-005)
# ===========================================================================


class TestRegisterArtifactTimeout:
    """INT-005: register_artifact uses asyncio.wait_for, no retry."""

    @pytest.mark.asyncio
    async def test_register_artifact_timeout_returns_default(self):
        """When call_tool exceeds timeout_ms, returns ArtifactResult() with indexed=False."""
        session = AsyncMock()

        async def _hang(*args: Any, **kwargs: Any) -> SimpleNamespace:
            await asyncio.sleep(10)  # hang for 10 seconds
            return _make_result(json.dumps({"indexed": True}))

        session.call_tool = _hang

        client = CodebaseIntelligenceClient(session)
        result = await client.register_artifact(
            file_path="test.py",
            service_name="auth",
            timeout_ms=100,  # 100ms — will timeout before _hang completes
        )

        assert isinstance(result, ArtifactResult)
        assert result.indexed is False
        assert result.symbols_found == 0
        assert result.dependencies_found == 0

    @pytest.mark.asyncio
    async def test_register_artifact_custom_timeout_respected(self):
        """Custom timeout_ms value is converted to seconds for asyncio.wait_for."""
        session = AsyncMock()
        call_times: list[float] = []

        async def _slow_call(*args: Any, **kwargs: Any) -> SimpleNamespace:
            # Takes 0.3 seconds — should succeed with 1000ms timeout,
            # but fail with 100ms timeout
            await asyncio.sleep(0.3)
            call_times.append(1)
            return _make_result(json.dumps({"indexed": True, "symbols_found": 5}))

        session.call_tool = _slow_call
        client = CodebaseIntelligenceClient(session)

        # With 100ms timeout: should timeout (0.3s > 0.1s)
        result_short = await client.register_artifact("test.py", timeout_ms=100)
        assert result_short.indexed is False
        assert len(call_times) == 0  # never completed

        # With 1000ms timeout: should succeed (0.3s < 1.0s)
        result_long = await client.register_artifact("test.py", timeout_ms=1000)
        assert result_long.indexed is True
        assert result_long.symbols_found == 5
        assert len(call_times) == 1

    @pytest.mark.asyncio
    async def test_register_artifact_no_retry_on_failure(self):
        """register_artifact does NOT retry on failure (single attempt per INT-005)."""
        session = AsyncMock()
        call_count = 0

        async def _fail_once(*args: Any, **kwargs: Any) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            raise OSError("server crashed")

        session.call_tool = _fail_once

        client = CodebaseIntelligenceClient(session)
        result = await client.register_artifact("test.py", service_name="auth")

        # Should be called exactly once — no retry
        assert call_count == 1
        assert isinstance(result, ArtifactResult)
        assert result.indexed is False

    @pytest.mark.asyncio
    async def test_register_artifact_success_path(self):
        """register_artifact returns populated ArtifactResult on success."""
        data = json.dumps({
            "indexed": True,
            "symbols_found": 12,
            "dependencies_found": 4,
        })
        session = _make_session({
            "register_artifact": _make_result(data),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.register_artifact("main.py", service_name="core")

        assert isinstance(result, ArtifactResult)
        assert result.indexed is True
        assert result.symbols_found == 12
        assert result.dependencies_found == 4

    @pytest.mark.asyncio
    async def test_register_artifact_is_error_returns_default(self):
        """register_artifact returns default ArtifactResult when isError=True."""
        session = _make_session({
            "register_artifact": _make_result("error message", is_error=True),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.register_artifact("bad.py")

        assert isinstance(result, ArtifactResult)
        assert result.indexed is False

    @pytest.mark.asyncio
    async def test_register_artifact_default_timeout_is_60000(self):
        """Default timeout_ms is 60000 (60 seconds)."""
        import inspect
        sig = inspect.signature(CodebaseIntelligenceClient.register_artifact)
        timeout_param = sig.parameters["timeout_ms"]
        assert timeout_param.default == 60000


# ===========================================================================
# Test Group 2: Codebase Intelligence Session Exception Wrapping
# ===========================================================================


class TestCodebaseIntelligenceSessionExceptions:
    """Exception wrapping in create_codebase_intelligence_session.

    The function lazily imports from ``mcp`` and ``mcp.client.stdio`` inside
    its body, so we patch sys.modules and reload, matching the proven pattern
    from TestContractEngineSessionLifecycle.
    """

    @staticmethod
    def _build_mcp_mocks(
        *,
        stdio_side_effect: Exception | None = None,
        session_init_side_effect: Exception | None = None,
    ):
        """Build mock MCP modules for lazy-import patching.

        Returns (mock_mcp, mock_mcp_client_stdio, mock_session).
        """
        mock_session = AsyncMock()
        if session_init_side_effect:
            mock_session.initialize = AsyncMock(side_effect=session_init_side_effect)
        else:
            mock_session.initialize = AsyncMock()

        mock_stdio_client_fn = MagicMock()
        if stdio_side_effect:
            # Make the async context manager __aenter__ raise
            mock_stdio_cm = AsyncMock()
            mock_stdio_cm.__aenter__ = AsyncMock(side_effect=stdio_side_effect)
            mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)
            mock_stdio_client_fn.return_value = mock_stdio_cm
        else:
            mock_read = MagicMock()
            mock_write = MagicMock()
            mock_stdio_cm = AsyncMock()
            mock_stdio_cm.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
            mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)
            mock_stdio_client_fn.return_value = mock_stdio_cm

        mock_session_cls = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session_cm

        mock_server_params = MagicMock()

        mock_mcp = MagicMock()
        mock_mcp.ClientSession = mock_session_cls
        mock_mcp.StdioServerParameters = mock_server_params

        mock_mcp_client_stdio = MagicMock()
        mock_mcp_client_stdio.stdio_client = mock_stdio_client_fn

        return mock_mcp, mock_mcp_client_stdio, mock_session, mock_server_params

    @pytest.mark.asyncio
    async def test_timeout_error_wrapped_to_mcp_connection_error(self):
        """TimeoutError during session creation -> MCPConnectionError."""
        mock_mcp, mock_stdio, _, _ = self._build_mcp_mocks(
            stdio_side_effect=TimeoutError("connection timed out"),
        )
        mock_config = _make_codebase_config(startup_timeout_ms=100)

        with patch.dict("sys.modules", {"mcp": mock_mcp, "mcp.client.stdio": mock_stdio}):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod
            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError, match="Codebase Intelligence"):
                async with mcp_mod.create_codebase_intelligence_session(mock_config) as _s:
                    pass

    @pytest.mark.asyncio
    async def test_connection_error_wrapped(self):
        """ConnectionError during session creation -> MCPConnectionError."""
        mock_mcp, mock_stdio, _, _ = self._build_mcp_mocks(
            stdio_side_effect=ConnectionError("refused"),
        )
        mock_config = _make_codebase_config()

        with patch.dict("sys.modules", {"mcp": mock_mcp, "mcp.client.stdio": mock_stdio}):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod
            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError, match="Codebase Intelligence"):
                async with mcp_mod.create_codebase_intelligence_session(mock_config) as _s:
                    pass

    @pytest.mark.asyncio
    async def test_process_lookup_error_wrapped(self):
        """ProcessLookupError during session creation -> MCPConnectionError."""
        mock_mcp, mock_stdio, _, _ = self._build_mcp_mocks(
            stdio_side_effect=ProcessLookupError("no such process"),
        )
        mock_config = _make_codebase_config()

        with patch.dict("sys.modules", {"mcp": mock_mcp, "mcp.client.stdio": mock_stdio}):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod
            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError, match="Codebase Intelligence"):
                async with mcp_mod.create_codebase_intelligence_session(mock_config) as _s:
                    pass

    @pytest.mark.asyncio
    async def test_os_error_wrapped(self):
        """OSError during session creation -> MCPConnectionError."""
        mock_mcp, mock_stdio, _, _ = self._build_mcp_mocks(
            stdio_side_effect=OSError("broken pipe"),
        )
        mock_config = _make_codebase_config()

        with patch.dict("sys.modules", {"mcp": mock_mcp, "mcp.client.stdio": mock_stdio}):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod
            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError, match="Codebase Intelligence"):
                async with mcp_mod.create_codebase_intelligence_session(mock_config) as _s:
                    pass

    @pytest.mark.asyncio
    async def test_env_includes_path_plus_vars(self):
        """When env vars are set, env dict includes PATH + specific vars only."""
        mock_mcp, mock_stdio, _, mock_server_params = self._build_mcp_mocks(
            stdio_side_effect=OSError("intercepted"),
        )
        mock_config = _make_codebase_config(
            database_path="/data/db.sqlite",
            chroma_path="/data/chroma",
            graph_path="/data/graph",
        )

        with patch.dict("sys.modules", {"mcp": mock_mcp, "mcp.client.stdio": mock_stdio}):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod
            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError):
                async with mcp_mod.create_codebase_intelligence_session(mock_config) as _s:
                    pass

            # Check what env was passed to StdioServerParameters
            assert mock_server_params.called
            call_kwargs = mock_server_params.call_args
            env = call_kwargs.kwargs.get("env")

            assert env is not None, "env should not be None when paths are set"
            assert "PATH" in env
            assert "DATABASE_PATH" in env
            assert env["DATABASE_PATH"] == "/data/db.sqlite"
            assert "CHROMA_PATH" in env
            assert env["CHROMA_PATH"] == "/data/chroma"
            assert "GRAPH_PATH" in env
            assert env["GRAPH_PATH"] == "/data/graph"
            # SEC-001: Should NOT have ANTHROPIC_API_KEY or other secrets
            assert "ANTHROPIC_API_KEY" not in env

    @pytest.mark.asyncio
    async def test_env_none_when_no_vars(self):
        """When no database_path/chroma_path/graph_path, env=None."""
        mock_mcp, mock_stdio, _, mock_server_params = self._build_mcp_mocks(
            stdio_side_effect=OSError("intercepted"),
        )
        mock_config = _make_codebase_config(
            database_path="",
            chroma_path="",
            graph_path="",
        )

        with patch.dict("sys.modules", {"mcp": mock_mcp, "mcp.client.stdio": mock_stdio}), \
             patch.dict("os.environ", {"DATABASE_PATH": "", "CHROMA_PATH": "", "GRAPH_PATH": ""}, clear=False):
            from importlib import reload
            import agent_team_v15.mcp_clients as mcp_mod
            reload(mcp_mod)

            with pytest.raises(mcp_mod.MCPConnectionError):
                async with mcp_mod.create_codebase_intelligence_session(mock_config) as _s:
                    pass

            assert mock_server_params.called
            call_kwargs = mock_server_params.call_args
            env = call_kwargs.kwargs.get("env")
            assert env is None, "env should be None when no paths are set"


# ===========================================================================
# Test Group 3: CodebaseIntelligenceClient Edge Cases
# ===========================================================================


class TestCodebaseClientEdgeCases:
    """Edge cases for parameter inclusion/omission in CodebaseIntelligenceClient."""

    @pytest.mark.asyncio
    async def test_check_dead_code_with_none_service(self):
        """check_dead_code(service_name=None) omits service_name from params."""
        session = AsyncMock()
        captured_args: list[dict] = []

        async def _capture_call(tool_name: str, arguments: dict) -> SimpleNamespace:
            captured_args.append(arguments)
            return _make_result(json.dumps([]))

        session.call_tool = AsyncMock(side_effect=_capture_call)
        client = CodebaseIntelligenceClient(session)

        await client.check_dead_code(service_name=None)

        assert len(captured_args) == 1
        assert "service_name" not in captured_args[0]

    @pytest.mark.asyncio
    async def test_check_dead_code_with_string_service(self):
        """check_dead_code(service_name='auth') includes service_name in params."""
        session = AsyncMock()
        captured_args: list[dict] = []

        async def _capture_call(tool_name: str, arguments: dict) -> SimpleNamespace:
            captured_args.append(arguments)
            return _make_result(json.dumps([{"symbol": "unused_fn", "file": "auth.py"}]))

        session.call_tool = AsyncMock(side_effect=_capture_call)
        client = CodebaseIntelligenceClient(session)

        result = await client.check_dead_code(service_name="auth")

        assert len(captured_args) == 1
        assert captured_args[0]["service_name"] == "auth"
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_check_dead_code_default_is_none(self):
        """check_dead_code default service_name is None."""
        import inspect
        sig = inspect.signature(CodebaseIntelligenceClient.check_dead_code)
        assert sig.parameters["service_name"].default is None

    @pytest.mark.asyncio
    async def test_search_semantic_default_n_results_omitted(self):
        """search_semantic with default n_results=10 does not include n_results in params."""
        session = AsyncMock()
        captured_args: list[dict] = []

        async def _capture_call(tool_name: str, arguments: dict) -> SimpleNamespace:
            captured_args.append(arguments)
            return _make_result(json.dumps([]))

        session.call_tool = AsyncMock(side_effect=_capture_call)
        client = CodebaseIntelligenceClient(session)

        await client.search_semantic(query="authentication flow")

        assert len(captured_args) == 1
        assert "n_results" not in captured_args[0]
        assert captured_args[0]["query"] == "authentication flow"

    @pytest.mark.asyncio
    async def test_search_semantic_custom_n_results_included(self):
        """search_semantic with n_results=5 includes n_results in params."""
        session = AsyncMock()
        captured_args: list[dict] = []

        async def _capture_call(tool_name: str, arguments: dict) -> SimpleNamespace:
            captured_args.append(arguments)
            return _make_result(json.dumps([{"file": "auth.py", "score": 0.9}]))

        session.call_tool = AsyncMock(side_effect=_capture_call)
        client = CodebaseIntelligenceClient(session)

        result = await client.search_semantic(query="auth", n_results=5)

        assert len(captured_args) == 1
        assert captured_args[0]["n_results"] == 5
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_semantic_language_included_when_set(self):
        """search_semantic includes language in params when non-empty."""
        session = AsyncMock()
        captured_args: list[dict] = []

        async def _capture_call(tool_name: str, arguments: dict) -> SimpleNamespace:
            captured_args.append(arguments)
            return _make_result(json.dumps([]))

        session.call_tool = AsyncMock(side_effect=_capture_call)
        client = CodebaseIntelligenceClient(session)

        await client.search_semantic(query="auth", language="python")

        assert len(captured_args) == 1
        assert captured_args[0]["language"] == "python"

    @pytest.mark.asyncio
    async def test_search_semantic_language_omitted_when_empty(self):
        """search_semantic omits language from params when empty string."""
        session = AsyncMock()
        captured_args: list[dict] = []

        async def _capture_call(tool_name: str, arguments: dict) -> SimpleNamespace:
            captured_args.append(arguments)
            return _make_result(json.dumps([]))

        session.call_tool = AsyncMock(side_effect=_capture_call)
        client = CodebaseIntelligenceClient(session)

        await client.search_semantic(query="auth", language="")

        assert len(captured_args) == 1
        assert "language" not in captured_args[0]

    @pytest.mark.asyncio
    async def test_search_semantic_service_name_included_when_set(self):
        """search_semantic includes service_name when non-empty."""
        session = AsyncMock()
        captured_args: list[dict] = []

        async def _capture_call(tool_name: str, arguments: dict) -> SimpleNamespace:
            captured_args.append(arguments)
            return _make_result(json.dumps([]))

        session.call_tool = AsyncMock(side_effect=_capture_call)
        client = CodebaseIntelligenceClient(session)

        await client.search_semantic(query="auth", service_name="auth-svc")

        assert len(captured_args) == 1
        assert captured_args[0]["service_name"] == "auth-svc"

    @pytest.mark.asyncio
    async def test_find_definition_returns_dataclass(self):
        """find_definition returns properly populated DefinitionResult."""
        data = json.dumps({
            "file": "src/auth.py",
            "line": 42,
            "kind": "class",
            "signature": "class AuthService:",
        })
        session = _make_session({
            "find_definition": _make_result(data),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_definition("AuthService")

        assert isinstance(result, DefinitionResult)
        assert result.found is True
        assert result.file == "src/auth.py"
        assert result.line == 42
        assert result.kind == "class"
        assert result.signature == "class AuthService:"

    @pytest.mark.asyncio
    async def test_find_definition_empty_file_means_not_found(self):
        """find_definition with empty file field returns found=False."""
        data = json.dumps({
            "file": "",
            "line": 0,
            "kind": "",
            "signature": "",
        })
        session = _make_session({
            "find_definition": _make_result(data),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_definition("NonExistent")

        assert isinstance(result, DefinitionResult)
        assert result.found is False

    @pytest.mark.asyncio
    async def test_find_dependencies_returns_dataclass(self):
        """find_dependencies returns properly populated DependencyResult."""
        data = json.dumps({
            "imports": ["os", "sys", "json"],
            "imported_by": ["main.py", "test_auth.py"],
            "transitive_deps": ["pathlib"],
            "circular_deps": [["a.py", "b.py"]],
        })
        session = _make_session({
            "find_dependencies": _make_result(data),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_dependencies("auth.py")

        assert isinstance(result, DependencyResult)
        assert result.imports == ["os", "sys", "json"]
        assert result.imported_by == ["main.py", "test_auth.py"]
        assert result.transitive_deps == ["pathlib"]
        assert result.circular_deps == [["a.py", "b.py"]]

    @pytest.mark.asyncio
    async def test_find_dependencies_none_data_returns_default(self):
        """find_dependencies with None data returns default DependencyResult."""
        # When _extract_json returns None (e.g., empty content)
        session = _make_session({
            "find_dependencies": SimpleNamespace(content=[], isError=False),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_dependencies("missing.py")

        assert isinstance(result, DependencyResult)
        assert result.imports == []
        assert result.imported_by == []

    @pytest.mark.asyncio
    async def test_find_callers_returns_list(self):
        """find_callers returns list of caller dicts on success."""
        data = json.dumps([
            {"file": "main.py", "line": 10, "symbol": "handle_request"},
            {"file": "api.py", "line": 25, "symbol": "process"},
        ])
        session = _make_session({
            "find_callers": _make_result(data),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_callers("auth_check", max_results=50)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["file"] == "main.py"

    @pytest.mark.asyncio
    async def test_find_callers_returns_empty_on_non_list(self):
        """find_callers returns [] when data is not a list."""
        session = _make_session({
            "find_callers": _make_result(json.dumps({"error": "not found"})),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.find_callers("unknown_fn")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_service_interface_returns_dict(self):
        """get_service_interface returns dict on success."""
        data = json.dumps({
            "service_name": "auth",
            "methods": ["login", "logout", "refresh_token"],
            "events": ["user_created"],
        })
        session = _make_session({
            "get_service_interface": _make_result(data),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.get_service_interface("auth")

        assert isinstance(result, dict)
        assert result["service_name"] == "auth"
        assert "login" in result["methods"]

    @pytest.mark.asyncio
    async def test_get_service_interface_returns_empty_on_non_dict(self):
        """get_service_interface returns {} when data is not a dict."""
        session = _make_session({
            "get_service_interface": _make_result(json.dumps([])),
        })
        client = CodebaseIntelligenceClient(session)
        result = await client.get_service_interface("unknown")

        assert result == {}


# ===========================================================================
# Test Group 4: Retry Behavior Through Codebase Client
# ===========================================================================


class TestCodebaseClientRetryBehavior:
    """Retry behavior of codebase client methods via _call_with_retry."""

    @pytest.mark.asyncio
    async def test_find_definition_retries_on_transient_error(self):
        """find_definition retries on OSError (via _call_with_retry)."""
        session = AsyncMock()
        call_count = 0

        async def _fail_then_succeed(tool_name: str, arguments: dict) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise OSError("server unavailable")
            return _make_result(json.dumps({
                "file": "auth.py",
                "line": 10,
                "kind": "function",
                "signature": "def login():",
            }))

        session.call_tool = AsyncMock(side_effect=_fail_then_succeed)

        client = CodebaseIntelligenceClient(session)
        # Patch sleep to avoid actual delays
        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.find_definition("login")

        # Should have been called 3 times (2 failures + 1 success)
        assert call_count == 3
        assert result.found is True
        assert result.file == "auth.py"

    @pytest.mark.asyncio
    async def test_find_callers_retries_on_timeout(self):
        """find_callers retries on TimeoutError."""
        session = AsyncMock()
        call_count = 0

        async def _timeout_then_succeed(tool_name: str, arguments: dict) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise TimeoutError("timed out")
            return _make_result(json.dumps([
                {"file": "api.py", "line": 5, "symbol": "handler"},
            ]))

        session.call_tool = AsyncMock(side_effect=_timeout_then_succeed)

        client = CodebaseIntelligenceClient(session)
        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.find_callers("my_func")

        # Should have retried: 1 failure + 1 success = 2 calls
        assert call_count == 2
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_semantic_no_retry_on_type_error(self):
        """search_semantic does NOT retry on TypeError (non-transient)."""
        session = AsyncMock()
        call_count = 0

        async def _type_error(*args: Any, **kwargs: Any) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            raise TypeError("unsupported operand")

        session.call_tool = AsyncMock(side_effect=_type_error)

        client = CodebaseIntelligenceClient(session)
        result = await client.search_semantic(query="auth")

        # TypeError is non-transient: called once, then caught by outer except
        assert call_count == 1
        assert result == []

    @pytest.mark.asyncio
    async def test_find_dependencies_retries_on_connection_error(self):
        """find_dependencies retries on ConnectionError."""
        session = AsyncMock()
        call_count = 0

        async def _conn_error_then_succeed(tool_name: str, arguments: dict) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError("connection reset")
            return _make_result(json.dumps({
                "imports": ["os"],
                "imported_by": [],
                "transitive_deps": [],
                "circular_deps": [],
            }))

        session.call_tool = AsyncMock(side_effect=_conn_error_then_succeed)

        client = CodebaseIntelligenceClient(session)
        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.find_dependencies("main.py")

        assert call_count == 3
        assert result.imports == ["os"]

    @pytest.mark.asyncio
    async def test_find_definition_fails_after_max_retries(self):
        """find_definition returns default after all 3 retries exhausted."""
        session = AsyncMock()
        call_count = 0

        async def _always_fail(*args: Any, **kwargs: Any) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            raise OSError("permanently unavailable")

        session.call_tool = AsyncMock(side_effect=_always_fail)

        client = CodebaseIntelligenceClient(session)
        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.find_definition("missing_symbol")

        # 3 attempts (max retries)
        assert call_count == 3
        assert isinstance(result, DefinitionResult)
        assert result.found is False

    @pytest.mark.asyncio
    async def test_get_service_interface_no_retry_on_value_error(self):
        """get_service_interface does NOT retry on ValueError (non-transient)."""
        session = AsyncMock()
        call_count = 0

        async def _value_error(*args: Any, **kwargs: Any) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            raise ValueError("invalid argument")

        session.call_tool = AsyncMock(side_effect=_value_error)

        client = CodebaseIntelligenceClient(session)
        result = await client.get_service_interface("auth")

        # ValueError is non-transient: no retry
        assert call_count == 1
        assert result == {}

    @pytest.mark.asyncio
    async def test_check_dead_code_retries_on_os_error(self):
        """check_dead_code retries on OSError then returns results."""
        session = AsyncMock()
        call_count = 0

        async def _fail_once_then_succeed(tool_name: str, arguments: dict) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise OSError("pipe broken")
            return _make_result(json.dumps([
                {"symbol": "unused_helper", "file": "utils.py", "line": 15},
            ]))

        session.call_tool = AsyncMock(side_effect=_fail_once_then_succeed)

        client = CodebaseIntelligenceClient(session)
        with patch("agent_team_v15.contract_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.check_dead_code(service_name="utils")

        assert call_count == 2
        assert len(result) == 1
        assert result[0]["symbol"] == "unused_helper"
