"""Tests to validate MCP tool name references in prompts.

Ensures all MCP tool references in orchestrator/agent prompts use the
correct double-underscore format: mcp__<server>__<tool>

This prevents the root cause of Build 3's failure to use Context7 —
shorthand tool names (e.g., ``resolve-library-id``) silently fail
because Claude cannot find a tool matching that name.
"""

from __future__ import annotations

import re

import pytest

from agent_team_v15.agents import ORCHESTRATOR_SYSTEM_PROMPT
from agent_team_v15.mcp_servers import (
    get_mcp_servers,
    get_research_tools,
    get_orchestrator_st_tool_name,
    get_contract_aware_servers,
)
from agent_team_v15.config import AgentTeamConfig, MCPServerConfig
from agent_team_v15.design_reference import DESIGN_EXTRACTION_SYSTEM_PROMPT
from agent_team_v15.tech_research import TECH_RESEARCH_PROMPT


# ===================================================================
# Known MCP tool names (canonical source of truth)
# ===================================================================

KNOWN_FIRECRAWL_TOOLS = [
    "mcp__firecrawl__firecrawl_search",
    "mcp__firecrawl__firecrawl_scrape",
    "mcp__firecrawl__firecrawl_map",
    "mcp__firecrawl__firecrawl_extract",
    "mcp__firecrawl__firecrawl_agent",
    "mcp__firecrawl__firecrawl_agent_status",
]

KNOWN_CONTEXT7_TOOLS = [
    "mcp__context7__resolve-library-id",
    "mcp__context7__query-docs",
]

KNOWN_ST_TOOLS = [
    "mcp__sequential-thinking__sequentialthinking",
]

ALL_KNOWN_TOOLS = KNOWN_FIRECRAWL_TOOLS + KNOWN_CONTEXT7_TOOLS + KNOWN_ST_TOOLS


# ===================================================================
# Helper: extract tool-like references from prompt text
# ===================================================================

def _extract_mcp_tool_refs(text: str) -> list[str]:
    """Extract all mcp__*__* references from a prompt string."""
    return re.findall(r"mcp__[\w-]+__[\w-]+", text)


def _extract_shorthand_tool_refs(text: str) -> list[tuple[str, str]]:
    """Find shorthand tool references that should use full mcp__ prefix.

    Returns list of (shorthand, line) tuples for references that look like
    they're used as tool-call instructions (not descriptive text).

    Checks for patterns like:
    - ``Call resolve-library-id`` (instruction to call a tool)
    - ``Call firecrawl_scrape`` (instruction to call a tool)
    - backtick-quoted tool names without mcp__ prefix
    """
    issues: list[tuple[str, str]] = []

    # Shorthand Context7 tools used as instructions (not inside mcp__ prefix)
    for line in text.splitlines():
        # Skip lines that already have the full mcp__ prefix
        if "mcp__context7__" in line:
            continue
        # Check for bare resolve-library-id or query-docs used as tool calls
        if re.search(r"(?:Call|call|Use|use)\s+`?resolve-library-id", line):
            issues.append(("resolve-library-id", line.strip()))
        if re.search(r"(?:Call|call|Use|use)\s+`?query-docs", line):
            issues.append(("query-docs", line.strip()))

    # Shorthand Firecrawl tools used as instructions in orchestrator context
    for line in text.splitlines():
        if "mcp__firecrawl__" in line:
            continue
        # Only flag when used as "Call <tool>" instructions, not descriptions
        if re.search(r"(?:Call|call)\s+`?firecrawl_(scrape|search|map|extract|agent)\b", line):
            match = re.search(r"firecrawl_\w+", line)
            if match:
                issues.append((match.group(), line.strip()))

    return issues


# ===================================================================
# Test: Orchestrator prompt uses full mcp__ tool names
# ===================================================================

class TestOrchestratorPromptToolNames:
    """Verify ORCHESTRATOR_SYSTEM_PROMPT uses correct MCP tool names."""

    def test_all_mcp_refs_use_double_underscore(self):
        """Every mcp__*__* reference must use double underscores."""
        refs = _extract_mcp_tool_refs(ORCHESTRATOR_SYSTEM_PROMPT)
        assert len(refs) > 0, "Expected MCP tool references in orchestrator prompt"
        for ref in refs:
            assert ref in ALL_KNOWN_TOOLS, (
                f"Unknown MCP tool reference '{ref}' in orchestrator prompt. "
                f"Known tools: {ALL_KNOWN_TOOLS}"
            )

    def test_no_shorthand_tool_call_instructions(self):
        """No 'Call resolve-library-id' or 'Call firecrawl_scrape' shorthands."""
        issues = _extract_shorthand_tool_refs(ORCHESTRATOR_SYSTEM_PROMPT)
        assert issues == [], (
            f"Found shorthand tool references in orchestrator prompt "
            f"(should use mcp__<server>__<tool> format):\n"
            + "\n".join(f"  - '{name}' in: {line}" for name, line in issues)
        )

    def test_context7_tools_referenced(self):
        """Orchestrator prompt must reference both Context7 tools."""
        assert "mcp__context7__resolve-library-id" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "mcp__context7__query-docs" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_firecrawl_tools_referenced(self):
        """Orchestrator prompt must reference core Firecrawl tools."""
        assert "mcp__firecrawl__firecrawl_search" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "mcp__firecrawl__firecrawl_scrape" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "mcp__firecrawl__firecrawl_map" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "mcp__firecrawl__firecrawl_extract" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_sequential_thinking_tool_referenced(self):
        """Orchestrator prompt must reference Sequential Thinking tool."""
        assert "mcp__sequential-thinking__sequentialthinking" in ORCHESTRATOR_SYSTEM_PROMPT


# ===================================================================
# Test: Design extraction prompt uses full mcp__ tool names
# ===================================================================

class TestDesignExtractionPromptToolNames:
    """Verify DESIGN_EXTRACTION_SYSTEM_PROMPT uses correct MCP tool names."""

    def test_all_mcp_refs_use_double_underscore(self):
        refs = _extract_mcp_tool_refs(DESIGN_EXTRACTION_SYSTEM_PROMPT)
        assert len(refs) > 0, "Expected MCP tool references in design extraction prompt"
        for ref in refs:
            assert ref in ALL_KNOWN_TOOLS, (
                f"Unknown MCP tool reference '{ref}' in design extraction prompt"
            )

    def test_no_shorthand_tool_call_instructions(self):
        issues = _extract_shorthand_tool_refs(DESIGN_EXTRACTION_SYSTEM_PROMPT)
        assert issues == [], (
            f"Found shorthand tool references in design extraction prompt:\n"
            + "\n".join(f"  - '{name}' in: {line}" for name, line in issues)
        )

    def test_firecrawl_scrape_referenced(self):
        assert "mcp__firecrawl__firecrawl_scrape" in DESIGN_EXTRACTION_SYSTEM_PROMPT


# ===================================================================
# Test: Tech research prompt uses full mcp__ tool names
# ===================================================================

class TestTechResearchPromptToolNames:
    """Verify TECH_RESEARCH_PROMPT uses correct MCP tool names."""

    def test_all_mcp_refs_use_double_underscore(self):
        refs = _extract_mcp_tool_refs(TECH_RESEARCH_PROMPT)
        assert len(refs) > 0, "Expected MCP tool references in tech research prompt"
        for ref in refs:
            assert ref in ALL_KNOWN_TOOLS, (
                f"Unknown MCP tool reference '{ref}' in tech research prompt"
            )

    def test_context7_tools_referenced(self):
        assert "mcp__context7__resolve-library-id" in TECH_RESEARCH_PROMPT
        assert "mcp__context7__query-docs" in TECH_RESEARCH_PROMPT


# ===================================================================
# Test: MCP servers produce matching tool lists
# ===================================================================

class TestMcpToolListIntegrity:
    """Verify tool names in prompts match what get_research_tools returns."""

    def test_prompt_context7_tools_match_server_tools(self):
        """Every Context7 tool in the prompt must exist in get_research_tools output."""
        servers = {"firecrawl": {"type": "stdio"}, "context7": {"type": "stdio"}}
        tools = get_research_tools(servers)

        for tool in KNOWN_CONTEXT7_TOOLS:
            assert tool in tools, (
                f"Context7 tool '{tool}' referenced in prompts but not in "
                f"get_research_tools output: {tools}"
            )

    def test_prompt_firecrawl_tools_match_server_tools(self):
        """Every Firecrawl tool in the prompt must exist in get_research_tools output."""
        servers = {"firecrawl": {"type": "stdio"}, "context7": {"type": "stdio"}}
        tools = get_research_tools(servers)

        for tool in KNOWN_FIRECRAWL_TOOLS:
            assert tool in tools, (
                f"Firecrawl tool '{tool}' referenced in prompts but not in "
                f"get_research_tools output: {tools}"
            )

    def test_st_tool_matches_server_function(self):
        """Sequential Thinking tool name must match get_orchestrator_st_tool_name."""
        st_name = get_orchestrator_st_tool_name()
        assert st_name == "mcp__sequential-thinking__sequentialthinking"
        assert st_name in ORCHESTRATOR_SYSTEM_PROMPT

    def test_all_prompt_tool_refs_in_allowed_tools(self):
        """Every mcp__*__* reference in the orchestrator prompt must appear
        in the combined allowed_tools list when all servers are enabled."""
        cfg = AgentTeamConfig()
        cfg.mcp_servers["sequential_thinking"] = MCPServerConfig(enabled=True)
        servers = get_contract_aware_servers(cfg)
        tools = get_research_tools(servers)
        st_name = get_orchestrator_st_tool_name()
        all_allowed = tools + [st_name]

        prompt_refs = _extract_mcp_tool_refs(ORCHESTRATOR_SYSTEM_PROMPT)
        for ref in prompt_refs:
            assert ref in all_allowed, (
                f"Tool '{ref}' referenced in orchestrator prompt but not in "
                f"allowed_tools list. Allowed: {all_allowed}"
            )


# ===================================================================
# Test: No single-underscore mcp_ pattern in tool name positions
# ===================================================================

class TestNoSingleUnderscoreMcp:
    """Guard against mcp_ (single underscore) typos in tool names."""

    def test_orchestrator_no_single_underscore_tool_names(self):
        """No mcp_<something>__<something> patterns (single first underscore)."""
        # Match mcp_ followed by a non-underscore (single underscore variant)
        # but exclude Python identifiers like mcp_servers or mcp_clients
        bad = re.findall(r"\bmcp_(?!_)(?!servers|clients|command|args|json|config|map)\w+__\w+", ORCHESTRATOR_SYSTEM_PROMPT)
        assert bad == [], (
            f"Found single-underscore mcp_ tool references (should be mcp__): {bad}"
        )
