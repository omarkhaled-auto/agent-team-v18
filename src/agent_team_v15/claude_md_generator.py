"""CLAUDE.md generator for Agent Teams teammate roles.

Generates role-specific ``.claude/CLAUDE.md`` files for each agent teammate,
including MCP tool awareness, convergence mandates, and contract context.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import AgentTeamConfig

logger = logging.getLogger(__name__)

# Marker comments for preserving existing CLAUDE.md content
_BEGIN_MARKER = "<!-- AGENT-TEAMS:BEGIN -->"
_END_MARKER = "<!-- AGENT-TEAMS:END -->"

# ── Role-specific instructions ──────────────────────────────────────────────

_ROLE_SECTIONS: dict[str, str] = {
    "architect": (
        "## Role: Architect\n\n"
        "You are an **architect** agent. Your responsibilities:\n"
        "- Design solution architecture with file ownership maps\n"
        "- Create integration roadmaps with wiring maps\n"
        "- Define interface contracts between components\n"
        "- Verify contract compliance when Contract Engine is available\n"
        "- Document endpoint schemas and response shapes\n"
        "- Use Codebase Intelligence for dependency analysis when available\n\n"
        "**Do NOT** mark items [x] in REQUIREMENTS.md — only reviewers may do that.\n"
        "**Do NOT** write implementation code — only design documents.\n"
    ),
    "code-writer": (
        "## Role: Code Writer\n\n"
        "You are a **code writer** agent. Your responsibilities:\n"
        "- Implement requirements from TASKS.md and REQUIREMENTS.md\n"
        "- Follow the architecture decision and file ownership map\n"
        "- Write complete, production-quality code with no TODOs or placeholders\n"
        "- Validate endpoints against contracts when Contract Engine is available\n"
        "- Use exact field names from API contracts — never guess\n"
        "- Register new artifacts with Codebase Intelligence when available\n\n"
        "**ZERO MOCK DATA POLICY**: Never use hardcoded mock/stub data.\n"
        "**Do NOT** mark items [x] in REQUIREMENTS.md.\n"
    ),
    "code-reviewer": (
        "## Role: Code Reviewer\n\n"
        "You are an **adversarial code reviewer** agent. Your responsibilities:\n"
        "- Find gaps, bugs, and missed requirements\n"
        "- Verify contract compliance for all endpoints\n"
        "- Check field name accuracy against API contracts\n"
        "- Detect mock data, orphan files, and missing wiring\n"
        "- Mark items [x] in REQUIREMENTS.md only when fully verified\n"
        "- Increment (review_cycles: N) on every evaluated item\n\n"
        "**Your job is to BREAK things**, not confirm they work.\n"
    ),
    "test-engineer": (
        "## Role: Test Engineer\n\n"
        "You are a **test engineer** agent. Your responsibilities:\n"
        "- Write comprehensive test suites (unit, integration, E2E)\n"
        "- Verify endpoint contract compliance through tests\n"
        "- Test edge cases, error handling, and boundary conditions\n"
        "- Use Contract Engine to generate contract-aware tests when available\n"
        "- Ensure all API endpoints have matching test coverage\n\n"
        "**Coverage goal**: Every requirement should have at least one test.\n"
    ),
    "wiring-verifier": (
        "## Role: Wiring Verifier\n\n"
        "You are a **wiring verifier** agent. Your responsibilities:\n"
        "- Verify all cross-file connections match the Integration Roadmap\n"
        "- Check that every SVC-xxx wiring entry has real implementations\n"
        "- Detect orphan files (created but never imported)\n"
        "- Verify endpoint paths, methods, and field names match contracts\n"
        "- Use Codebase Intelligence for dependency tracing when available\n\n"
        "**Every unwired service is a FAILURE**. No exceptions.\n"
    ),
}

_GENERIC_ROLE_SECTION = (
    "## Role: Agent\n\n"
    "You are an agent in the Agent Team system.\n"
    "Follow the instructions in REQUIREMENTS.md and TASKS.md.\n"
    "Coordinate with teammates as needed.\n"
)


def _generate_role_section(role: str) -> str:
    """Return role-specific instructions for the given role.

    Falls back to a generic section for unrecognized roles.
    """
    return _ROLE_SECTIONS.get(role, _GENERIC_ROLE_SECTION)


# ── MCP tools section ───────────────────────────────────────────────────────

# Module-level constants for MCP tool documentation
_CONTRACT_ENGINE_TOOLS: tuple[tuple[str, str], ...] = (
    ("get_contract", "Retrieve contract details by ID"),
    ("validate_endpoint", "Validate an endpoint against its contract"),
    ("generate_tests", "Generate contract-aware test stubs"),
    ("check_breaking_changes", "Detect breaking contract changes"),
    ("mark_implemented", "Mark a contract as implemented"),
    ("get_unimplemented_contracts", "List unimplemented contracts"),
)

_CODEBASE_INTELLIGENCE_TOOLS: tuple[tuple[str, str], ...] = (
    ("find_definition", "Find where a symbol is defined"),
    ("find_callers", "Find all callers of a symbol"),
    ("find_dependencies", "Analyze file dependencies"),
    ("search_semantic", "Semantic code search"),
    ("get_service_interface", "Get service endpoints and events"),
    ("check_dead_code", "Detect unused code"),
    ("register_artifact", "Register a new file in the index"),
)


def _generate_mcp_section(mcp_servers: dict[str, Any]) -> str:
    """Generate MCP tools documentation section.

    Lists Contract Engine and Codebase Intelligence tools when present
    in the mcp_servers dict. Returns empty string when neither is present.
    """
    parts: list[str] = []

    has_contract = "contract_engine" in mcp_servers
    has_codebase = "codebase_intelligence" in mcp_servers

    if not has_contract and not has_codebase:
        return ""

    parts.append("## Available MCP Tools\n")

    if has_contract:
        parts.append("### Contract Engine\n")
        parts.append("The following Contract Engine MCP tools are available:\n")
        for tool_name, description in _CONTRACT_ENGINE_TOOLS:
            parts.append(f"- `{tool_name}` — {description}")
        parts.append("")

    if has_codebase:
        parts.append("### Codebase Intelligence\n")
        parts.append("The following Codebase Intelligence MCP tools are available:\n")
        for tool_name, description in _CODEBASE_INTELLIGENCE_TOOLS:
            parts.append(f"- `{tool_name}` — {description}")
        parts.append("")

    return "\n".join(parts)


# ── Convergence section ─────────────────────────────────────────────────────

def _generate_convergence_section(config: "AgentTeamConfig") -> str:
    """Generate convergence mandates section with min_ratio from config."""
    min_ratio = getattr(config.convergence, "min_convergence_ratio", 0.9)

    return (
        "## Convergence Mandates\n\n"
        f"- Minimum completion ratio: **{min_ratio:.0%}**\n"
        "- Every requirement MUST be verified by a reviewer before marking [x]\n"
        "- Review cycles MUST be incremented on every evaluation\n"
        "- Zero-cycle items are flagged as unverified\n"
        "- The quality gate hook enforces completion ratio at stop time\n"
    )


# ── Contract context section ────────────────────────────────────────────────

def _generate_contract_section(
    contracts: list[dict[str, Any]] | None,
    contract_limit: int = 100,
) -> str:
    """Generate contract context section with truncation support.

    Parameters
    ----------
    contracts : list[dict] | None
        List of contract dicts to include. Each should have at minimum
        ``contract_id`` and ``provider_service`` keys.
    contract_limit : int
        Maximum number of contracts to include before truncation.
    """
    if not contracts:
        return ""

    parts: list[str] = ["## Active Contracts\n"]

    display_contracts = contracts[:contract_limit]
    for c in display_contracts:
        cid = c.get("contract_id", c.get("id", "unknown"))
        provider = c.get("provider_service", c.get("service_name", "unknown"))
        ctype = c.get("contract_type", c.get("type", ""))
        version = c.get("version", "")
        implemented = c.get("implemented", False)
        status_mark = "[x]" if implemented else "[ ]"

        parts.append(f"- {status_mark} `{cid}` — {provider} ({ctype} v{version})")

    if len(contracts) > contract_limit:
        overflow = len(contracts) - contract_limit
        parts.append(
            f"\n... and {overflow} more. "
            f"Use Contract Engine get_contract(contract_id) MCP tool "
            f"to fetch additional contracts on demand."
        )

    parts.append("")
    return "\n".join(parts)


# ── Public API ───────────────────────────────────────────────────────────────

def generate_claude_md(
    role: str,
    config: "AgentTeamConfig",
    mcp_servers: dict[str, Any],
    contracts: list[dict[str, Any]] | None = None,
    *,
    service_name: str = "",
    dependencies: list[str] | None = None,
    quality_standards: str = "",
    convergence_config: dict[str, Any] | None = None,
    tech_stack: str = "",
    codebase_context: str = "",
    graph_rag_context: str = "",
) -> str:
    """Generate the full CLAUDE.md content for a teammate role.

    Parameters
    ----------
    role : str
        One of: ``"architect"``, ``"code-writer"``, ``"code-reviewer"``,
        ``"test-engineer"``, ``"wiring-verifier"``. Unknown roles get a
        generic fallback.
    config : AgentTeamConfig
        The project configuration.
    mcp_servers : dict
        Active MCP servers dict (keys checked for ``"contract_engine"``
        and ``"codebase_intelligence"``).
    contracts : list[dict] | None
        Optional list of contract dicts for the contract context section.
    service_name : str
        Name of the service this teammate is working on.
    dependencies : list[str] | None
        Dependency list for the service.
    quality_standards : str
        Quality standards text to inject into the CLAUDE.md.
    convergence_config : dict | None
        Convergence config overrides (min_convergence_ratio, etc.).
    tech_stack : str
        Technology stack description for context.
    codebase_context : str
        Codebase index context from Codebase Intelligence.
    graph_rag_context : str
        Cross-service dependency context from Graph RAG.

    Returns
    -------
    str
        Non-empty CLAUDE.md content string.
    """
    contract_limit = getattr(
        getattr(config, "agent_teams", None), "contract_limit", 100
    )

    sections: list[str] = [
        "# Agent Teams — Teammate Instructions\n",
        _generate_role_section(role),
    ]

    # Service context section
    if service_name:
        sections.append(f"## Service: {service_name}\n")

    if dependencies:
        dep_lines = "\n".join(f"- `{d}`" for d in dependencies)
        sections.append(f"## Dependencies\n\n{dep_lines}\n")

    if tech_stack:
        sections.append(f"## Tech Stack\n\n{tech_stack}\n")

    if codebase_context:
        sections.append(f"## Codebase Context\n\n{codebase_context}\n")

    if graph_rag_context:
        sections.append(graph_rag_context)

    sections.append(_generate_mcp_section(mcp_servers))
    sections.append(_generate_convergence_section(config))

    if quality_standards:
        sections.append(f"## Quality Standards\n\n{quality_standards}\n")

    sections.append(_generate_contract_section(contracts, contract_limit=contract_limit))

    # Filter empty sections and join
    content = "\n".join(s for s in sections if s)

    return content


def write_teammate_claude_md(
    role: str,
    config: "AgentTeamConfig",
    mcp_servers: dict[str, Any],
    project_dir: Path,
    contracts: list[dict[str, Any]] | None = None,
) -> Path:
    """Write the .claude/CLAUDE.md file for a teammate.

    Preserves existing content outside the ``<!-- AGENT-TEAMS:BEGIN -->``
    and ``<!-- AGENT-TEAMS:END -->`` markers. If no markers exist, the
    generated content is appended after any existing content.

    Parameters
    ----------
    role : str
        Agent role name.
    config : AgentTeamConfig
        Project configuration.
    mcp_servers : dict
        Active MCP servers.
    project_dir : Path
        Root project directory.
    contracts : list[dict] | None
        Optional contract dicts.

    Returns
    -------
    Path
        Path to the written ``.claude/CLAUDE.md`` file.
    """
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    claude_md_path = claude_dir / "CLAUDE.md"

    generated = generate_claude_md(role, config, mcp_servers, contracts)
    marked_content = f"{_BEGIN_MARKER}\n{generated}\n{_END_MARKER}"

    if claude_md_path.is_file():
        existing = claude_md_path.read_text(encoding="utf-8")

        begin_idx = existing.find(_BEGIN_MARKER)
        end_idx = existing.find(_END_MARKER)

        if begin_idx != -1 and end_idx != -1:
            # Replace content between markers
            end_idx += len(_END_MARKER)
            new_content = existing[:begin_idx] + marked_content + existing[end_idx:]
        else:
            # No markers found — append after existing content
            new_content = existing.rstrip() + "\n\n" + marked_content + "\n"
    else:
        new_content = marked_content + "\n"

    claude_md_path.write_text(new_content, encoding="utf-8")
    logger.info("Wrote CLAUDE.md for role '%s' at %s", role, claude_md_path)

    return claude_md_path
