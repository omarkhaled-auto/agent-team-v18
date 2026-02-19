"""Codebase Intelligence MCP client for Agent Team.

Wraps 7 of the Codebase Intelligence MCP server tools with retry logic,
safe defaults, and proper error handling.  All methods accept a
``ClientSession`` (obtained from
:func:`mcp_clients.create_codebase_intelligence_session`) and return typed
dataclasses, plain collections, or safe default values on failure.

Retry policy:
    * 3 retries on transient errors (``OSError``, ``TimeoutError``,
      ``ConnectionError``) with exponential backoff (1 s, 2 s, 4 s).
    * Safe defaults immediately on non-transient errors (``TypeError``,
      ``ValueError``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .contract_client import _call_with_retry, _extract_json

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DefinitionResult:
    """Result of looking up a symbol definition in the codebase."""

    file: str = ""
    line: int = 0
    kind: str = ""
    signature: str = ""
    found: bool = False


@dataclass
class DependencyResult:
    """Dependency graph information for a single file."""

    imports: list[str] = field(default_factory=list)
    imported_by: list[str] = field(default_factory=list)
    transitive_deps: list[str] = field(default_factory=list)
    circular_deps: list[list[str]] = field(default_factory=list)


@dataclass
class ArtifactResult:
    """Result of registering a file artifact in the codebase index."""

    indexed: bool = False
    symbols_found: int = 0
    dependencies_found: int = 0


# ---------------------------------------------------------------------------
# CodebaseIntelligenceClient
# ---------------------------------------------------------------------------

class CodebaseIntelligenceClient:
    """Client for the Codebase Intelligence MCP server.

    Wraps 7 MCP tools with retry logic and safe default values on failure.
    Requires a live ``ClientSession`` obtained from
    :func:`mcp_clients.create_codebase_intelligence_session`.

    Example::

        async with create_codebase_intelligence_session(config) as session:
            client = CodebaseIntelligenceClient(session)
            defn = await client.find_definition("MyClass")
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    # -- SVC-007: find_definition -------------------------------------------

    async def find_definition(
        self,
        symbol: str,
        language: str = "",
    ) -> DefinitionResult:
        """Find the definition of a symbol in the codebase.

        Returns:
            :class:`DefinitionResult` with ``found=True`` if the symbol was
            located.  Returns ``DefinitionResult()`` (all defaults, ``found=False``)
            on error.
        """
        try:
            data = await _call_with_retry(
                self._session,
                "find_definition",
                {"symbol": symbol, "language": language},
            )
            if data is None:
                return DefinitionResult()
            file_val = data.get("file", "")
            return DefinitionResult(
                file=file_val,
                line=data.get("line", 0),
                kind=data.get("kind", ""),
                signature=data.get("signature", ""),
                found=bool(file_val),
            )
        except Exception as exc:
            logger.warning(
                "find_definition(%s) failed: %s", symbol, exc, exc_info=True,
            )
            return DefinitionResult()

    # -- SVC-008: find_callers ----------------------------------------------

    async def find_callers(
        self,
        symbol: str,
        max_results: int = 50,
    ) -> list:
        """Find all callers of a symbol.

        Returns:
            List of caller dicts, or ``[]`` on error.
        """
        try:
            data = await _call_with_retry(
                self._session,
                "find_callers",
                {"symbol": symbol, "max_results": max_results},
            )
            if isinstance(data, list):
                return data
            return []
        except Exception as exc:
            logger.warning(
                "find_callers(%s) failed: %s", symbol, exc, exc_info=True,
            )
            return []

    # -- SVC-009: find_dependencies -----------------------------------------

    async def find_dependencies(self, file_path: str) -> DependencyResult:
        """Find all dependencies for a file.

        Returns:
            :class:`DependencyResult` on success.  Returns
            ``DependencyResult()`` (all empty lists) on error.
        """
        try:
            data = await _call_with_retry(
                self._session,
                "find_dependencies",
                {"file_path": file_path},
            )
            if data is None:
                return DependencyResult()
            return DependencyResult(
                imports=data.get("imports", []),
                imported_by=data.get("imported_by", []),
                transitive_deps=data.get("transitive_deps", []),
                circular_deps=data.get("circular_deps", []),
            )
        except Exception as exc:
            logger.warning(
                "find_dependencies(%s) failed: %s", file_path, exc, exc_info=True,
            )
            return DependencyResult()

    # -- SVC-010: search_semantic -------------------------------------------

    async def search_semantic(
        self,
        query: str,
        language: str = "",
        service_name: str = "",
        n_results: int = 10,
    ) -> list:
        """Perform a semantic search across the codebase.

        Returns:
            List of search result dicts, or ``[]`` on error.
        """
        try:
            args: dict[str, Any] = {"query": query}
            if language:
                args["language"] = language
            if service_name:
                args["service_name"] = service_name
            if n_results != 10:
                args["n_results"] = n_results

            data = await _call_with_retry(
                self._session,
                "search_semantic",
                args,
            )
            if isinstance(data, list):
                return data
            return []
        except Exception as exc:
            logger.warning(
                "search_semantic(%s) failed: %s", query, exc, exc_info=True,
            )
            return []

    # -- SVC-011: get_service_interface -------------------------------------

    async def get_service_interface(self, service_name: str) -> dict:
        """Retrieve the public interface of a service.

        Returns:
            Dict describing the service interface, or ``{}`` on error.
        """
        try:
            data = await _call_with_retry(
                self._session,
                "get_service_interface",
                {"service_name": service_name},
            )
            if isinstance(data, dict):
                return data
            return {}
        except Exception as exc:
            logger.warning(
                "get_service_interface(%s) failed: %s",
                service_name, exc,
                exc_info=True,
            )
            return {}

    # -- SVC-012: check_dead_code -------------------------------------------

    async def check_dead_code(self, service_name: str | None = None) -> list:
        """Check for dead (unreferenced) code in a service.

        Returns:
            List of dead code entries, or ``[]`` on error.
        """
        try:
            params: dict[str, Any] = {}
            if service_name is not None:
                params["service_name"] = service_name
            data = await _call_with_retry(
                self._session,
                "check_dead_code",
                params,
            )
            if isinstance(data, list):
                return data
            return []
        except Exception as exc:
            logger.warning(
                "check_dead_code(%s) failed: %s",
                service_name, exc,
                exc_info=True,
            )
            return []

    # -- SVC-013: register_artifact -----------------------------------------

    async def register_artifact(
        self,
        file_path: str,
        service_name: str = "",
        timeout_ms: float = 60000,
    ) -> ArtifactResult:
        """Register a file artifact in the codebase index.

        Single attempt with timeout — no retry (per INT-005).

        Returns:
            :class:`ArtifactResult` on success.  Returns
            ``ArtifactResult()`` (all defaults) on error.
        """
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(
                    "register_artifact",
                    {"file_path": file_path, "service_name": service_name},
                ),
                timeout=timeout_ms / 1000,
            )
            if getattr(result, "isError", False):
                return ArtifactResult()
            data = _extract_json(getattr(result, "content", None))
            if data is None:
                return ArtifactResult()
            return ArtifactResult(
                indexed=data.get("indexed", False),
                symbols_found=data.get("symbols_found", 0),
                dependencies_found=data.get("dependencies_found", 0),
            )
        except (asyncio.TimeoutError, OSError, ConnectionError) as exc:
            logger.warning("register_artifact(%s) failed: %s", file_path, exc)
            return ArtifactResult()
        except Exception as exc:
            logger.warning(
                "register_artifact(%s) failed: %s",
                file_path, exc,
                exc_info=True,
            )
            return ArtifactResult()
