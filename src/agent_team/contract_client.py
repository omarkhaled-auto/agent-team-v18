"""Contract Engine MCP client for Agent Team.

Wraps 6 of the Contract Engine MCP server tools with retry logic, safe
defaults, and proper error handling.  All methods accept a ``ClientSession``
(obtained from :func:`mcp_clients.create_contract_engine_session`) and
return typed dataclasses or safe default values on failure.

Retry policy:
    * 3 retries on transient errors (``OSError``, ``TimeoutError``,
      ``ConnectionError``) with exponential backoff (1 s, 2 s, 4 s).
    * Safe defaults immediately on non-transient errors (``TypeError``,
      ``ValueError``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Retry configuration
_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1, 2, 4]
_TRANSIENT_ERRORS = (OSError, TimeoutError, ConnectionError)
_NON_TRANSIENT_ERRORS = (TypeError, ValueError)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ContractValidation:
    """Result of validating an endpoint against a contract."""

    valid: bool = False
    violations: list[dict[str, str]] = field(default_factory=list)
    error: str = ""


@dataclass
class ContractInfo:
    """Information about a single contract from the Contract Engine."""

    id: str = ""
    type: str = ""
    version: str = ""
    service_name: str = ""
    spec: dict[str, Any] = field(default_factory=dict)
    spec_hash: str = ""
    status: str = ""


# ---------------------------------------------------------------------------
# Content extraction helpers
# ---------------------------------------------------------------------------

def _extract_json(content: list[Any] | None) -> Any:
    """Extract JSON data from MCP tool result content.

    The MCP ``call_tool`` response wraps results in a list of content
    objects, each with a ``text`` attribute containing a JSON string.

    Args:
        content: The ``result.content`` list from an MCP call_tool response.

    Returns:
        Parsed JSON data, or ``None`` on any parse failure.
    """
    if not content:
        return None
    try:
        text = content[0].text
        return json.loads(text)
    except (json.JSONDecodeError, AttributeError, IndexError, TypeError):
        return None


def _extract_text(content: list[Any] | None) -> str:
    """Extract plain text from MCP tool result content.

    Args:
        content: The ``result.content`` list from an MCP call_tool response.

    Returns:
        The text content, or empty string on any failure.
    """
    if not content:
        return ""
    try:
        return content[0].text or ""
    except (AttributeError, IndexError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

async def _call_with_retry(
    session: Any,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    extract_fn: str = "json",
    timeout_ms: float = 60000,
) -> Any:
    """Call an MCP tool with retry logic for transient errors.

    Args:
        session: MCP ``ClientSession``.
        tool_name: Name of the MCP tool to call.
        arguments: Tool arguments dict.
        extract_fn: ``"json"`` or ``"text"`` — which extractor to use.
        timeout_ms: Per-call timeout in milliseconds (default 60000).

    Returns:
        Extracted result data.

    Raises:
        Exception: The last transient error after all retries are exhausted,
            or any non-transient error immediately.
    """
    last_error: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments),
                timeout=timeout_ms / 1000,
            )

            # Check for MCP-level errors
            if getattr(result, "isError", False):
                error_text = _extract_text(getattr(result, "content", None))
                raise RuntimeError(f"MCP tool error: {error_text}")

            content = getattr(result, "content", None)
            if extract_fn == "json":
                return _extract_json(content)
            else:
                return _extract_text(content)

        except _NON_TRANSIENT_ERRORS as exc:
            # Non-transient: fail immediately, no retry
            raise exc

        except _TRANSIENT_ERRORS as exc:
            last_error = exc
            if attempt < _MAX_RETRIES - 1:
                backoff = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "MCP tool %s transient error (attempt %d/%d), retrying in %ds: %s",
                    tool_name, attempt + 1, _MAX_RETRIES, backoff, exc,
                )
                await asyncio.sleep(backoff)
            else:
                logger.warning(
                    "MCP tool %s failed after %d retries: %s",
                    tool_name, _MAX_RETRIES, exc,
                    exc_info=True,
                )
                raise exc

        except Exception as exc:
            # Other errors (RuntimeError from isError, etc.) — treat as transient
            last_error = exc
            if attempt < _MAX_RETRIES - 1:
                backoff = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "MCP tool %s error (attempt %d/%d), retrying in %ds: %s",
                    tool_name, attempt + 1, _MAX_RETRIES, backoff, exc,
                )
                await asyncio.sleep(backoff)
            else:
                logger.warning(
                    "MCP tool %s failed after %d retries: %s",
                    tool_name, _MAX_RETRIES, exc,
                    exc_info=True,
                )
                raise exc

    # Should never reach here, but just in case
    if last_error:  # pragma: no cover
        raise last_error
    return None  # pragma: no cover


# ---------------------------------------------------------------------------
# ContractEngineClient
# ---------------------------------------------------------------------------

class ContractEngineClient:
    """Client for the Contract Engine MCP server.

    Wraps 6 MCP tools with retry logic and safe default values on failure.
    Requires a live ``ClientSession`` obtained from
    :func:`mcp_clients.create_contract_engine_session`.

    Example::

        async with create_contract_engine_session(config) as session:
            client = ContractEngineClient(session)
            info = await client.get_contract("contract-123")
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    # -- SVC-001: get_contract ---------------------------------------------

    async def get_contract(self, contract_id: str) -> ContractInfo | None:
        """Retrieve contract information by ID.

        Returns:
            :class:`ContractInfo` on success, ``None`` on error.
        """
        try:
            data = await _call_with_retry(
                self._session,
                "get_contract",
                {"contract_id": contract_id},
            )
            if data is None:
                return None
            return ContractInfo(
                id=data.get("id", ""),
                type=data.get("type", ""),
                version=data.get("version", ""),
                service_name=data.get("service_name", ""),
                spec=data.get("spec", {}),
                spec_hash=data.get("spec_hash", ""),
                status=data.get("status", ""),
            )
        except Exception as exc:
            logger.warning("get_contract(%s) failed: %s", contract_id, exc, exc_info=True)
            return None

    # -- SVC-002: validate_endpoint ----------------------------------------

    async def validate_endpoint(
        self,
        service_name: str,
        method: str,
        path: str,
        response_body: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> ContractValidation:
        """Validate an endpoint response against its contract.

        Returns:
            :class:`ContractValidation` — always returns a value (never
            raises).  On error, ``error`` is populated.
        """
        try:
            data = await _call_with_retry(
                self._session,
                "validate_endpoint",
                {
                    "service_name": service_name,
                    "method": method,
                    "path": path,
                    "response_body": response_body or {},
                    "status_code": status_code,
                },
            )
            if data is None:
                return ContractValidation(error="No response from MCP")
            return ContractValidation(
                valid=data.get("valid", False),
                violations=data.get("violations", []),
            )
        except Exception as exc:
            logger.warning(
                "validate_endpoint(%s %s %s) failed: %s",
                service_name, method, path, exc,
                exc_info=True,
            )
            return ContractValidation(error=str(exc))

    # -- SVC-003: generate_tests -------------------------------------------

    async def generate_tests(
        self,
        contract_id: str,
        framework: str = "pytest",
        include_negative: bool = True,
    ) -> str:
        """Generate test file content for a contract.

        Returns:
            Test file content string, or ``""`` on error.
        """
        try:
            text = await _call_with_retry(
                self._session,
                "generate_tests",
                {
                    "contract_id": contract_id,
                    "framework": framework,
                    "include_negative": include_negative,
                },
                extract_fn="text",
            )
            return text or ""
        except Exception as exc:
            logger.warning("generate_tests(%s) failed: %s", contract_id, exc, exc_info=True)
            return ""

    # -- SVC-004: check_breaking_changes -----------------------------------

    async def check_breaking_changes(
        self,
        contract_id: str,
        new_spec: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Check for breaking changes between current and new spec.

        Returns:
            List of change dicts, or ``[]`` on error.
        """
        try:
            data = await _call_with_retry(
                self._session,
                "check_breaking_changes",
                {
                    "contract_id": contract_id,
                    "new_spec": new_spec,
                },
            )
            if isinstance(data, list):
                return data
            return []
        except Exception as exc:
            logger.warning("check_breaking_changes(%s) failed: %s", contract_id, exc, exc_info=True)
            return []

    # -- SVC-005: mark_implemented -----------------------------------------

    async def mark_implemented(
        self,
        contract_id: str,
        service_name: str,
        evidence_path: str = "",
    ) -> dict[str, Any]:
        """Mark a contract as implemented with optional evidence.

        Returns:
            Result dict with ``marked``, ``total``, ``all_implemented``
            keys, or ``{"marked": False}`` on error.
        """
        try:
            data = await _call_with_retry(
                self._session,
                "mark_implemented",
                {
                    "contract_id": contract_id,
                    "service_name": service_name,
                    "evidence_path": evidence_path,
                },
            )
            if isinstance(data, dict):
                return data
            return {"marked": False}
        except Exception as exc:
            logger.warning(
                "mark_implemented(%s, %s) failed: %s",
                contract_id, service_name, exc,
                exc_info=True,
            )
            return {"marked": False}

    # -- SVC-006: get_unimplemented_contracts ------------------------------

    async def get_unimplemented_contracts(
        self,
        service_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get contracts that have not been implemented yet.

        Returns:
            List of contract dicts, or ``[]`` on error.
        """
        try:
            params: dict[str, Any] = {}
            if service_name is not None:
                params["service_name"] = service_name
            data = await _call_with_retry(
                self._session,
                "get_unimplemented_contracts",
                params,
            )
            if isinstance(data, list):
                return data
            return []
        except Exception as exc:
            logger.warning(
                "get_unimplemented_contracts(%s) failed: %s",
                service_name, exc,
                exc_info=True,
            )
            return []
