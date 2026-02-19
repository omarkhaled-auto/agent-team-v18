"""MCP client session management for Agent Team.

Provides async context managers for connecting to MCP servers (Contract Engine,
Codebase Intelligence) via stdio transport.  Each session manager handles lazy
MCP SDK import, startup/tool timeouts, and error translation to
``MCPConnectionError``.

All MCP SDK imports are deferred to runtime so the rest of the package works
without the ``mcp`` package installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from .config import ContractEngineConfig, CodebaseIntelligenceConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MCPConnectionError(Exception):
    """Raised when an MCP server connection fails during initialisation.

    Wraps transient transport errors (TimeoutError, ConnectionError, OSError,
    ProcessLookupError) so callers can catch a single exception type.
    """


# ---------------------------------------------------------------------------
# Contract Engine session
# ---------------------------------------------------------------------------

@asynccontextmanager
async def create_contract_engine_session(
    config: "ContractEngineConfig",
) -> AsyncIterator[Any]:
    """Connect to the Contract Engine MCP server and yield a ``ClientSession``.

    Usage::

        async with create_contract_engine_session(config) as session:
            result = await session.call_tool("get_contract", {"contract_id": "abc"})

    The MCP SDK is imported lazily — if not installed an ``ImportError`` is
    raised with a helpful message.

    Raises:
        ImportError: ``mcp`` package is not installed.
        MCPConnectionError: Server failed to start or connect within the
            configured ``startup_timeout_ms``.
    """
    # -- Lazy import of MCP SDK ---------------------------------------------
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        raise ImportError(
            "MCP SDK not installed. pip install mcp"
        )

    # -- Build environment for the server process --------------------------
    # SEC-001: Only pass specific env vars — never spread os.environ
    # (would leak API keys and other secrets to MCP subprocesses).
    env: dict[str, str] | None = None
    db_path = config.database_path or os.getenv("CONTRACT_ENGINE_DB", "")
    if db_path:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "DATABASE_PATH": db_path,
        }

    server_params = StdioServerParameters(
        command=config.mcp_command,
        args=config.mcp_args,
        env=env,
        cwd=config.server_root if config.server_root else None,
    )

    startup_timeout = config.startup_timeout_ms / 1000.0  # convert to seconds

    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # Wait for initialisation with timeout
                await asyncio.wait_for(
                    session.initialize(),
                    timeout=startup_timeout,
                )
                yield session
    except (TimeoutError, ConnectionError, ProcessLookupError, OSError) as exc:
        raise MCPConnectionError(
            f"Failed to connect to Contract Engine MCP server: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Codebase Intelligence session
# ---------------------------------------------------------------------------

@asynccontextmanager
async def create_codebase_intelligence_session(
    config: "CodebaseIntelligenceConfig",
) -> AsyncIterator[Any]:
    """Connect to the Codebase Intelligence MCP server and yield a ``ClientSession``.

    Usage::

        async with create_codebase_intelligence_session(config) as session:
            result = await session.call_tool("search_code", {"query": "def main"})

    The MCP SDK is imported lazily — if not installed an ``ImportError`` is
    raised with a helpful message.

    Raises:
        ImportError: ``mcp`` package is not installed.
        MCPConnectionError: Server failed to start or connect within the
            configured ``startup_timeout_ms``.
    """
    # -- Lazy import of MCP SDK ---------------------------------------------
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        raise ImportError(
            "MCP SDK not installed. pip install mcp"
        )

    # -- Build environment for the server process --------------------------
    env: dict[str, str] | None = None
    env_vars: dict[str, str] = {}

    db_path = config.database_path or os.getenv("DATABASE_PATH", "")
    if db_path:
        env_vars["DATABASE_PATH"] = db_path

    chroma_path = config.chroma_path or os.getenv("CHROMA_PATH", "")
    if chroma_path:
        env_vars["CHROMA_PATH"] = chroma_path

    graph_path = config.graph_path or os.getenv("GRAPH_PATH", "")
    if graph_path:
        env_vars["GRAPH_PATH"] = graph_path

    if env_vars:
        # SEC-001: Only pass specific env vars — never spread os.environ
        # (would leak API keys and other secrets to MCP subprocesses).
        env = {
            "PATH": os.environ.get("PATH", ""),
            **env_vars,
        }

    server_params = StdioServerParameters(
        command=config.mcp_command,
        args=config.mcp_args,
        env=env,
        cwd=config.server_root if config.server_root else None,
    )

    startup_timeout = config.startup_timeout_ms / 1000.0  # convert to seconds

    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # Wait for initialisation with timeout
                await asyncio.wait_for(
                    session.initialize(),
                    timeout=startup_timeout,
                )
                yield session
    except (TimeoutError, ConnectionError, ProcessLookupError, OSError) as exc:
        raise MCPConnectionError(
            f"Failed to connect to Codebase Intelligence MCP server: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Architect MCP client
# ---------------------------------------------------------------------------

class ArchitectClient:
    """Client for the Architect MCP server.

    Wraps 4 Architect tools: decompose, get_service_map,
    get_contracts_for_service, and get_domain_model.

    Uses the same ``_call_with_retry`` retry pattern as
    :class:`ContractEngineClient` and :class:`CodebaseIntelligenceClient`:
    3 retries on transient errors with exponential backoff (1s, 2s, 4s).
    Every method catches all exceptions and returns a safe empty default,
    so callers never need to handle MCP failures.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    async def decompose(self, description: str) -> dict[str, Any]:
        """Decompose a system description into services.

        Returns dict with service decomposition on success,
        empty dict on any failure.
        """
        try:
            from .contract_client import _call_with_retry
            data = await _call_with_retry(
                self._session,
                "decompose",
                {"prd_text": description},
            )
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Architect decompose failed: %s", exc, exc_info=True)
            return {}

    async def get_service_map(self) -> dict[str, Any]:
        """Get the service map showing all services and their relationships.

        Returns dict with service map on success, empty dict on any failure.
        """
        try:
            from .contract_client import _call_with_retry
            data = await _call_with_retry(
                self._session,
                "get_service_map",
                {},
            )
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Architect get_service_map failed: %s", exc, exc_info=True)
            return {}

    async def get_contracts_for_service(self, service_name: str) -> list[dict[str, Any]]:
        """Get all contracts for a specific service.

        Returns list of contract dicts on success, empty list on any failure.
        """
        try:
            from .contract_client import _call_with_retry
            data = await _call_with_retry(
                self._session,
                "get_contracts_for_service",
                {"service_name": service_name},
            )
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning(
                "Architect get_contracts_for_service failed: %s", exc, exc_info=True,
            )
            return []

    async def get_domain_model(self, service_name: str = "") -> dict[str, Any]:
        """Get the domain model for a service or the entire system.

        Returns dict with domain model on success, empty dict on any failure.
        """
        try:
            args: dict[str, Any] = {}
            if service_name:
                args["service_name"] = service_name
            from .contract_client import _call_with_retry
            data = await _call_with_retry(
                self._session,
                "get_domain_model",
                args,
            )
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Architect get_domain_model failed: %s", exc, exc_info=True)
            return {}
