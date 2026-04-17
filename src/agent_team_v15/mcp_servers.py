"""MCP server configurations for Agent Team.

Provides Firecrawl (web scraping / search) and Context7 (library docs) servers
that are injected into agents that need web research capabilities.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentTeamConfig, ContractEngineConfig, CodebaseIntelligenceConfig

logger = logging.getLogger(__name__)


def _firecrawl_server() -> dict[str, Any] | None:
    """Return Firecrawl MCP server config, or None if API key is missing."""
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        print("[warn] FIRECRAWL_API_KEY not set — Firecrawl MCP server disabled", file=sys.stderr)
        return None
    return {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "firecrawl-mcp"],
        "env": {"FIRECRAWL_API_KEY": api_key},
    }


def _context7_server() -> dict[str, Any]:
    """Return Context7 MCP server config."""
    env: dict[str, str] = {}
    api_key = os.environ.get("CONTEXT7_API_KEY", "")
    if api_key:
        env["CONTEXT7_API_KEY"] = api_key
    server: dict[str, Any] = {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
    }
    if env:
        server["env"] = env
    return server


def _sequential_thinking_server() -> dict[str, Any]:
    """Return Sequential Thinking MCP server config (orchestrator only)."""
    return {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@anthropic-ai/sequential-thinking-mcp"],
    }


def get_mcp_servers(config: AgentTeamConfig) -> dict[str, Any]:
    """Build the MCP servers dict based on config.

    Returns a dict suitable for ClaudeAgentOptions.mcp_servers.
    Skips servers that are disabled or missing required env vars.
    """
    servers: dict[str, Any] = {}

    firecrawl_cfg = config.mcp_servers.get("firecrawl")
    if firecrawl_cfg and firecrawl_cfg.enabled:
        fc = _firecrawl_server()
        if fc:
            servers["firecrawl"] = fc

    context7_cfg = config.mcp_servers.get("context7")
    if context7_cfg and context7_cfg.enabled:
        servers["context7"] = _context7_server()

    st_cfg = config.mcp_servers.get("sequential_thinking")
    if st_cfg and st_cfg.enabled:
        servers["sequential_thinking"] = _sequential_thinking_server()

    return servers


def get_orchestrator_st_tool_name() -> str:
    """Return the MCP tool name for Sequential Thinking."""
    return "mcp__sequential-thinking__sequentialthinking"


def get_research_tools(servers: dict[str, Any]) -> list[str]:
    """Return the list of allowed MCP tool names for research agents."""
    tools: list[str] = []
    if "firecrawl" in servers:
        tools.extend([
            "mcp__firecrawl__firecrawl_search",
            "mcp__firecrawl__firecrawl_scrape",
            "mcp__firecrawl__firecrawl_map",
            "mcp__firecrawl__firecrawl_extract",
            "mcp__firecrawl__firecrawl_agent",
            "mcp__firecrawl__firecrawl_agent_status",
        ])
    if "context7" in servers:
        tools.extend([
            "mcp__context7__resolve-library-id",
            "mcp__context7__query-docs",
        ])
    return tools


# Base tools shared by all orchestrator sessions.
_BASE_TOOLS: list[str] = [
    "Read", "Write", "Edit", "Bash", "Glob", "Grep",
    "Task", "WebSearch", "WebFetch",
]


def get_playwright_tools() -> list[str]:
    """Return the list of allowed MCP tool names for Playwright browser interaction."""
    _PLAYWRIGHT_TOOL_NAMES = [
        "browser_navigate",
        "browser_navigate_back",
        "browser_snapshot",
        "browser_click",
        "browser_hover",
        "browser_type",
        "browser_press_key",
        "browser_select_option",
        "browser_drag",
        "browser_take_screenshot",
        "browser_console_messages",
        "browser_network_requests",
        "browser_evaluate",
        "browser_run_code",
        "browser_fill_form",
        "browser_file_upload",
        "browser_handle_dialog",
        "browser_wait_for",
        "browser_tabs",
        "browser_close",
        "browser_resize",
        "browser_install",
    ]
    return [f"mcp__playwright__{name}" for name in _PLAYWRIGHT_TOOL_NAMES]


def recompute_allowed_tools(
    base_tools: list[str], servers: dict[str, Any]
) -> list[str]:
    """Recompute allowed_tools based on the current set of MCP servers.

    Call this whenever ``options.mcp_servers`` is replaced after
    ``_build_options()`` so that the tool allowlist stays in sync.

    Args:
        base_tools: The base tool names (Read, Write, etc.).
        servers: The MCP servers dict that will be used for the session.

    Returns:
        A new list combining base tools with research, ST, and Playwright
        tool names based on which servers are present.
    """
    tools = list(base_tools)
    tools.extend(get_research_tools(servers))
    if "sequential_thinking" in servers:
        tools.append(get_orchestrator_st_tool_name())
    if "playwright" in servers:
        tools.extend(get_playwright_tools())
    return tools


def is_firecrawl_available(config: AgentTeamConfig) -> bool:
    """Check if Firecrawl MCP server is configured and has an API key."""
    firecrawl_cfg = config.mcp_servers.get("firecrawl")
    if not firecrawl_cfg or not firecrawl_cfg.enabled:
        return False
    return bool(os.environ.get("FIRECRAWL_API_KEY"))


def get_firecrawl_only_servers(config: AgentTeamConfig) -> dict[str, Any]:
    """Return MCP servers dict with ONLY Firecrawl (for focused extraction sessions).

    Used by Phase 0.6 design reference extraction to create a minimal
    Claude session that can only scrape/search — no Context7, no ST.

    Returns empty dict if Firecrawl is unavailable.
    """
    servers: dict[str, Any] = {}
    firecrawl_cfg = config.mcp_servers.get("firecrawl")
    if firecrawl_cfg and firecrawl_cfg.enabled:
        fc = _firecrawl_server()
        if fc:
            servers["firecrawl"] = fc
    return servers


def get_context7_only_servers(config: AgentTeamConfig) -> dict[str, Any]:
    """Return MCP servers dict with ONLY Context7 (for tech research sessions).

    Used by Phase 1.5 tech stack research to create a minimal Claude session
    that can only query library documentation — no Firecrawl, no ST, no Playwright.

    Returns empty dict if Context7 is disabled in config.
    """
    servers: dict[str, Any] = {}
    context7_cfg = config.mcp_servers.get("context7")
    if context7_cfg and context7_cfg.enabled:
        servers["context7"] = _context7_server()
    return servers


def _playwright_mcp_server(headless: bool = True) -> dict[str, Any]:
    """Build Playwright MCP server config for browser testing.

    Uses ``@playwright/mcp@latest`` via npx. The headless flag controls
    whether a visible browser window is shown during execution.
    """
    args = ["-y", "@playwright/mcp@latest"]
    if headless:
        args.append("--headless")
    return {
        "type": "stdio",
        "command": "npx",
        "args": args,
    }


def get_browser_testing_servers(config: AgentTeamConfig) -> dict[str, Any]:
    """Build MCP servers dict for browser testing executor agents.

    Provides the Playwright MCP server for browser interaction, plus
    Context7 if enabled. Used by the workflow executor and regression
    sweep agents (NOT the startup or fix agents).
    """
    servers: dict[str, Any] = {}
    servers["playwright"] = _playwright_mcp_server(
        headless=config.browser_testing.headless,
    )

    context7_cfg = config.mcp_servers.get("context7")
    if context7_cfg and context7_cfg.enabled:
        servers["context7"] = _context7_server()

    return servers


def _contract_engine_mcp_server(config: ContractEngineConfig) -> dict[str, Any]:
    """Return Contract Engine MCP server config for the given configuration.

    Builds a stdio-type server definition using the command and args from
    *config*.  If ``config.database_path`` is non-empty it is passed as
    the ``DATABASE_PATH`` environment variable; otherwise no extra env vars
    are set.
    """
    env: dict[str, str] | None = None
    db_path = config.database_path or os.getenv("CONTRACT_ENGINE_DB", "")
    if db_path:
        env = {"DATABASE_PATH": db_path}
    server: dict[str, Any] = {
        "type": "stdio",
        "command": config.mcp_command,
        "args": list(config.mcp_args),
    }
    if env:
        server["env"] = env
    return server


def _codebase_intelligence_mcp_server(config: CodebaseIntelligenceConfig) -> dict[str, Any]:
    """Return Codebase Intelligence MCP server config for the given configuration.

    Builds a stdio-type server definition using the command and args from
    *config*.  Passes DATABASE_PATH, CHROMA_PATH, and GRAPH_PATH environment
    variables when non-empty.
    """
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
        env = env_vars

    server: dict[str, Any] = {
        "type": "stdio",
        "command": config.mcp_command,
        "args": list(config.mcp_args),
    }
    if env:
        server["env"] = env
    return server


def get_contract_aware_servers(config: AgentTeamConfig) -> dict[str, Any]:
    """Build MCP servers dict including Contract Engine when enabled.

    Starts with the standard servers from :func:`get_mcp_servers` and
    conditionally adds the Contract Engine MCP server based on
    ``config.contract_engine.enabled``.
    """
    servers = get_mcp_servers(config)

    if config.contract_engine.enabled:
        servers["contract_engine"] = _contract_engine_mcp_server(config.contract_engine)

    if config.codebase_intelligence.enabled:
        servers["codebase_intelligence"] = _codebase_intelligence_mcp_server(config.codebase_intelligence)

    return servers


# ---------------------------------------------------------------------------
# D-09 — Contract Engine MCP pre-flight + labeled static fallback
#
# Build-j degraded to static analysis silently ("validate_endpoint
# Contract Engine MCP tool was not available in the deployed toolset")
# because the Contract Engine MCP server command points at
# ``src.contract_engine.mcp_server`` — a module that is NOT shipped in
# this repository. These helpers make that degradation DETERMINISTIC:
#
#   * ``contract_engine_is_deployable`` checks (a) the config opt-in and
#     (b) whether the referenced command / module is actually available
#     in the current environment.
#   * ``run_mcp_preflight`` aggregates per-tool statuses, logs a
#     structured line (``MCP pre-flight: validate_endpoint missing``)
#     and persists ``.agent-team/MCP_PREFLIGHT.json``.
#   * ``ensure_contract_e2e_fidelity_header`` idempotently prepends a
#     clearly-labeled "Verification fidelity: STATIC ANALYSIS (not
#     runtime)" block to ``CONTRACT_E2E_RESULTS.md`` when the engine is
#     not deployable — the LLM sub-agent currently writes a similar
#     header free-hand; this helper makes it a deterministic guarantee.
#
# Wiring into ``cli.py`` is deliberately out of scope for this PR (the
# session-05 plan bans cli.py edits for PR C). Helpers are exported and
# will be wired in Session 6's Gate A smoke integration. Tests cover
# every branch directly.
# ---------------------------------------------------------------------------


CONTRACT_E2E_STATIC_FIDELITY_HEADER: str = (
    "> **Verification fidelity:** STATIC ANALYSIS (not runtime). The "
    "`validate_endpoint` Contract Engine MCP tool is not deployed in this "
    "environment. Results below are derived from source-code diff against "
    "`ENDPOINT_CONTRACTS.md`, not from live endpoint probing. Confidence "
    "is lower than a real runtime validation would provide.\n"
)


def _module_spec_available(dotted_module_path: str) -> bool:
    """Return True if the given dotted Python module path is importable
    in the current interpreter (without actually importing it).

    The Contract Engine MCP server is typically launched as
    ``python -m src.contract_engine.mcp_server``. Before spawning that
    subprocess it is cheap to check whether the target module is even
    present. ``importlib.util.find_spec`` performs the lookup against
    ``sys.path`` without executing the module body.
    """
    candidate = (dotted_module_path or "").strip()
    if not candidate:
        return False
    try:
        return importlib.util.find_spec(candidate) is not None
    except (ImportError, ValueError):
        return False


def contract_engine_is_deployable(
    config: AgentTeamConfig,
    *,
    which: Any | None = None,
    module_available: Any | None = None,
) -> tuple[bool, str]:
    """D-09: decide whether the Contract Engine MCP tool is actually
    launchable in the current environment.

    Returns ``(deployable, reason)`` where ``deployable`` is True only
    when every deployment precondition is satisfied and ``reason`` is a
    short human-readable string (``""`` on the happy path).

    ``which`` and ``module_available`` are injectable to keep tests
    hermetic — defaults call ``shutil.which`` and the
    ``_module_spec_available`` helper above.
    """
    which = which or shutil.which
    module_available = module_available or _module_spec_available

    ce = getattr(config, "contract_engine", None)
    if ce is None:
        return False, "contract_engine_config_missing"

    if not bool(getattr(ce, "enabled", False)):
        return False, "disabled_in_config"

    command = str(getattr(ce, "mcp_command", "") or "")
    if not command:
        return False, "mcp_command_unset"

    if which(command) is None:
        return False, f"command_not_on_path:{command}"

    # ``python -m module.path`` is the canonical invocation — extract
    # the module path after the ``-m`` flag and verify it resolves.
    args = list(getattr(ce, "mcp_args", []) or [])
    if "-m" in args:
        idx = args.index("-m")
        module_path = args[idx + 1] if idx + 1 < len(args) else ""
        if not module_path:
            return False, "module_path_missing_after_-m"
        if not module_available(module_path):
            return False, f"module_not_importable:{module_path}"
    # Without ``-m``, we trust ``shutil.which`` alone (e.g. a standalone
    # executable). Not our observed shape today, but structurally valid.
    return True, ""


def run_mcp_preflight(
    cwd: str | Path,
    config: AgentTeamConfig,
    *,
    log: Any | None = None,
) -> dict[str, Any]:
    """D-09: write ``.agent-team/MCP_PREFLIGHT.json`` with a structured
    per-tool status and emit one ``logger.info`` line per tool so
    operators can see the snapshot in real time.

    Returns the status dict (also persisted to disk). Safe to call
    repeatedly — each call overwrites the file with the current
    snapshot.
    """
    log = log or logger

    ce_ok, ce_reason = contract_engine_is_deployable(config)
    ci_cfg = getattr(config, "codebase_intelligence", None)
    ci_enabled = bool(getattr(ci_cfg, "enabled", False))

    tools: dict[str, dict[str, Any]] = {
        "validate_endpoint": {
            "provider": "contract_engine",
            "available": ce_ok,
            "reason": ce_reason,
        },
        "codebase_intelligence": {
            "provider": "codebase_intelligence",
            "available": ci_enabled,
            "reason": "" if ci_enabled else "disabled_in_config",
        },
    }

    for tool_name, tool_status in tools.items():
        status_word = "available" if tool_status["available"] else "missing"
        extra = f" ({tool_status['reason']})" if tool_status["reason"] else ""
        log.info("MCP pre-flight: %s %s%s", tool_name, status_word, extra)

    snapshot: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tools": tools,
    }

    try:
        target_dir = Path(cwd) / ".agent-team"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "MCP_PREFLIGHT.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - best effort
        log.warning("Failed to write MCP_PREFLIGHT.json: %s", exc)

    return snapshot


def ensure_contract_e2e_fidelity_header(
    path: str | Path,
    *,
    contract_engine_available: bool,
) -> bool:
    """D-09: idempotently prepend the static-analysis fidelity header to
    ``CONTRACT_E2E_RESULTS.md`` when ``contract_engine_available`` is
    False and the header is not already present. No-op when the engine
    is available OR the file does not exist.

    Returns True when the file was modified, False otherwise.
    """
    target = Path(path)
    if contract_engine_available:
        return False
    if not target.is_file():
        return False

    try:
        existing = target.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - best effort
        logger.warning("Failed to read %s for fidelity-header injection: %s", target, exc)
        return False

    # Idempotency anchor: the distinctive substring of the header. If
    # present anywhere in the opening 500 chars we treat the header as
    # already written and leave the file alone.
    anchor = "Verification fidelity:"
    if anchor in existing[:500]:
        return False

    new_text = CONTRACT_E2E_STATIC_FIDELITY_HEADER + "\n" + existing
    try:
        target.write_text(new_text, encoding="utf-8")
    except OSError as exc:  # pragma: no cover - best effort
        logger.warning("Failed to rewrite %s with fidelity header: %s", target, exc)
        return False
    return True


def ensure_fidelity_label_header(
    path: str | Path,
    label: str,
) -> bool:
    """D-14: idempotently prepend ``<!-- Verification fidelity: <label> -->``
    to a markdown verification artefact.

    Returns True when the file was modified, False otherwise.
    Safe to call repeatedly — uses the same ``"Verification fidelity:"``
    anchor as ``ensure_contract_e2e_fidelity_header`` so the two helpers
    share a single idempotency contract.
    """
    target = Path(path)
    if not target.is_file():
        return False
    try:
        existing = target.read_text(encoding="utf-8")
    except OSError:
        return False
    anchor = "Verification fidelity:"
    if anchor in existing[:500]:
        return False
    header = f"<!-- Verification fidelity: {label} -->\n"
    try:
        target.write_text(header + existing, encoding="utf-8")
    except OSError:
        return False
    return True
