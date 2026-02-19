"""Tests for agent_team.mcp_servers."""

from __future__ import annotations

from agent_team_v15.config import AgentTeamConfig, MCPServerConfig
from agent_team_v15.mcp_servers import (
    _BASE_TOOLS,
    _context7_server,
    _firecrawl_server,
    _sequential_thinking_server,
    get_mcp_servers,
    get_playwright_tools,
    get_research_tools,
    is_firecrawl_available,
    recompute_allowed_tools,
)


# ===================================================================
# _firecrawl_server()
# ===================================================================

class TestFirecrawlServer:
    def test_with_key_returns_dict(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
        result = _firecrawl_server()
        assert result is not None
        assert isinstance(result, dict)
        assert result["type"] == "stdio"

    def test_without_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        result = _firecrawl_server()
        assert result is None

    def test_uses_npx(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
        result = _firecrawl_server()
        assert result["command"] == "npx"

    def test_env_contains_key(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
        result = _firecrawl_server()
        assert result["env"]["FIRECRAWL_API_KEY"] == "fc-test-key"


# ===================================================================
# _context7_server()
# ===================================================================

class TestContext7Server:
    def test_returns_dict(self):
        result = _context7_server()
        assert isinstance(result, dict)

    def test_no_env_when_key_absent(self, monkeypatch):
        monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
        result = _context7_server()
        assert "env" not in result

    def test_uses_npx(self):
        result = _context7_server()
        assert result["command"] == "npx"

    def test_with_api_key_includes_env(self, monkeypatch):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-test-key")
        result = _context7_server()
        assert "env" in result
        assert result["env"]["CONTEXT7_API_KEY"] == "ctx7-test-key"

    def test_uses_upstash_package(self):
        result = _context7_server()
        assert "@upstash/context7-mcp" in result["args"]


# ===================================================================
# _sequential_thinking_server()
# ===================================================================

class TestSequentialThinkingServer:
    def test_returns_dict(self):
        result = _sequential_thinking_server()
        assert isinstance(result, dict)

    def test_no_env_key_needed(self):
        result = _sequential_thinking_server()
        assert "env" not in result

    def test_uses_npx(self):
        result = _sequential_thinking_server()
        assert result["command"] == "npx"

    def test_correct_package(self):
        result = _sequential_thinking_server()
        assert "@anthropic-ai/sequential-thinking-mcp" in result["args"]

    def test_type_is_stdio(self):
        result = _sequential_thinking_server()
        assert result["type"] == "stdio"


# ===================================================================
# get_mcp_servers()
# ===================================================================

class TestGetMcpServers:
    def test_both_enabled_and_present(self, env_with_api_keys):
        cfg = AgentTeamConfig()
        servers = get_mcp_servers(cfg)
        assert "firecrawl" in servers
        assert "context7" in servers

    def test_firecrawl_disabled(self, env_with_api_keys):
        cfg = AgentTeamConfig()
        cfg.mcp_servers["firecrawl"] = MCPServerConfig(enabled=False)
        servers = get_mcp_servers(cfg)
        assert "firecrawl" not in servers
        assert "context7" in servers

    def test_context7_disabled(self, env_with_api_keys):
        cfg = AgentTeamConfig()
        cfg.mcp_servers["context7"] = MCPServerConfig(enabled=False)
        servers = get_mcp_servers(cfg)
        assert "firecrawl" in servers
        assert "context7" not in servers

    def test_both_disabled_returns_empty(self, config_with_disabled_mcp):
        servers = get_mcp_servers(config_with_disabled_mcp)
        assert servers == {}

    def test_firecrawl_no_api_key_excluded(self, env_with_anthropic_only):
        cfg = AgentTeamConfig()
        servers = get_mcp_servers(cfg)
        assert "firecrawl" not in servers
        assert "context7" in servers

    def test_missing_config_key_skipped(self):
        cfg = AgentTeamConfig()
        # Remove the firecrawl key entirely
        del cfg.mcp_servers["firecrawl"]
        servers = get_mcp_servers(cfg)
        # Should still work, just without firecrawl
        assert "firecrawl" not in servers

    def test_sequential_thinking_included_when_enabled(self, env_with_api_keys):
        cfg = AgentTeamConfig()
        cfg.mcp_servers["sequential_thinking"] = MCPServerConfig(enabled=True)
        servers = get_mcp_servers(cfg)
        assert "sequential_thinking" in servers
        assert servers["sequential_thinking"]["command"] == "npx"

    def test_sequential_thinking_excluded_when_disabled(self, env_with_api_keys):
        cfg = AgentTeamConfig()
        cfg.mcp_servers["sequential_thinking"] = MCPServerConfig(enabled=False)
        servers = get_mcp_servers(cfg)
        assert "sequential_thinking" not in servers

    def test_sequential_thinking_excluded_when_absent(self, env_with_api_keys):
        cfg = AgentTeamConfig()
        # Remove ST from mcp_servers to verify absent key is skipped
        cfg.mcp_servers.pop("sequential_thinking", None)
        servers = get_mcp_servers(cfg)
        assert "sequential_thinking" not in servers


# ===================================================================
# get_research_tools()
# ===================================================================

class TestGetResearchTools:
    def test_both_servers_8_tools(self):
        servers = {"firecrawl": {"type": "stdio"}, "context7": {"type": "stdio"}}
        tools = get_research_tools(servers)
        assert len(tools) == 8

    def test_firecrawl_only_6_tools(self):
        servers = {"firecrawl": {"type": "stdio"}}
        tools = get_research_tools(servers)
        assert len(tools) == 6

    def test_context7_only_2_tools(self):
        servers = {"context7": {"type": "stdio"}}
        tools = get_research_tools(servers)
        assert len(tools) == 2

    def test_empty_servers_returns_empty_list(self):
        """Bug #7: should return [] not None."""
        tools = get_research_tools({})
        assert tools == []
        assert isinstance(tools, list)

    def test_correct_tool_names(self):
        servers = {"firecrawl": {"type": "stdio"}, "context7": {"type": "stdio"}}
        tools = get_research_tools(servers)
        assert "mcp__firecrawl__firecrawl_search" in tools
        assert "mcp__firecrawl__firecrawl_scrape" in tools
        assert "mcp__firecrawl__firecrawl_map" in tools
        assert "mcp__firecrawl__firecrawl_extract" in tools
        assert "mcp__firecrawl__firecrawl_agent" in tools
        assert "mcp__firecrawl__firecrawl_agent_status" in tools
        assert "mcp__context7__resolve-library-id" in tools
        assert "mcp__context7__query-docs" in tools


# ===================================================================
# is_firecrawl_available()
# ===================================================================

class TestIsFirecrawlAvailable:
    def test_is_firecrawl_available_with_key(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
        cfg = AgentTeamConfig()
        assert is_firecrawl_available(cfg) is True

    def test_is_firecrawl_available_no_key(self, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        cfg = AgentTeamConfig()
        assert is_firecrawl_available(cfg) is False

    def test_is_firecrawl_available_disabled(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
        cfg = AgentTeamConfig()
        cfg.mcp_servers["firecrawl"] = MCPServerConfig(enabled=False)
        assert is_firecrawl_available(cfg) is False

    def test_is_firecrawl_available_missing_config(self):
        cfg = AgentTeamConfig()
        del cfg.mcp_servers["firecrawl"]
        assert is_firecrawl_available(cfg) is False


# ===================================================================
# get_playwright_tools()
# ===================================================================

class TestGetPlaywrightTools:
    def test_returns_list(self):
        tools = get_playwright_tools()
        assert isinstance(tools, list)

    def test_all_prefixed_with_mcp__playwright__(self):
        tools = get_playwright_tools()
        for tool in tools:
            assert tool.startswith("mcp__playwright__"), f"{tool} missing prefix"

    def test_contains_core_tools(self):
        tools = get_playwright_tools()
        expected_core = [
            "mcp__playwright__browser_navigate",
            "mcp__playwright__browser_snapshot",
            "mcp__playwright__browser_click",
            "mcp__playwright__browser_type",
            "mcp__playwright__browser_take_screenshot",
            "mcp__playwright__browser_evaluate",
            "mcp__playwright__browser_close",
        ]
        for name in expected_core:
            assert name in tools, f"{name} not in playwright tools"

    def test_contains_all_22_tools(self):
        tools = get_playwright_tools()
        assert len(tools) == 22

    def test_no_duplicates(self):
        tools = get_playwright_tools()
        assert len(tools) == len(set(tools))


# ===================================================================
# recompute_allowed_tools()
# ===================================================================

class TestRecomputeAllowedTools:
    def test_empty_servers_returns_base_tools_only(self):
        result = recompute_allowed_tools(_BASE_TOOLS, {})
        assert set(_BASE_TOOLS).issubset(set(result))
        assert len(result) == len(_BASE_TOOLS)

    def test_includes_base_tools_always(self):
        servers = {"playwright": {"type": "stdio"}, "context7": {"type": "stdio"}}
        result = recompute_allowed_tools(_BASE_TOOLS, servers)
        for tool in _BASE_TOOLS:
            assert tool in result

    def test_includes_context7_tools_when_present(self):
        servers = {"context7": {"type": "stdio"}}
        result = recompute_allowed_tools(_BASE_TOOLS, servers)
        assert "mcp__context7__resolve-library-id" in result
        assert "mcp__context7__query-docs" in result

    def test_includes_firecrawl_tools_when_present(self):
        servers = {"firecrawl": {"type": "stdio"}}
        result = recompute_allowed_tools(_BASE_TOOLS, servers)
        assert "mcp__firecrawl__firecrawl_search" in result
        assert "mcp__firecrawl__firecrawl_scrape" in result

    def test_includes_playwright_tools_when_present(self):
        servers = {"playwright": {"type": "stdio"}}
        result = recompute_allowed_tools(_BASE_TOOLS, servers)
        playwright_tools = get_playwright_tools()
        for tool in playwright_tools:
            assert tool in result, f"{tool} missing from allowed_tools"

    def test_includes_st_tool_when_present(self):
        servers = {"sequential_thinking": {"type": "stdio"}}
        result = recompute_allowed_tools(_BASE_TOOLS, servers)
        assert "mcp__sequential-thinking__sequentialthinking" in result

    def test_all_servers_present(self):
        servers = {
            "firecrawl": {"type": "stdio"},
            "context7": {"type": "stdio"},
            "sequential_thinking": {"type": "stdio"},
            "playwright": {"type": "stdio"},
        }
        result = recompute_allowed_tools(_BASE_TOOLS, servers)
        # Base tools
        for tool in _BASE_TOOLS:
            assert tool in result
        # Context7
        assert "mcp__context7__resolve-library-id" in result
        # Firecrawl
        assert "mcp__firecrawl__firecrawl_search" in result
        # ST
        assert "mcp__sequential-thinking__sequentialthinking" in result
        # Playwright
        assert "mcp__playwright__browser_navigate" in result
        assert "mcp__playwright__browser_click" in result

    def test_does_not_include_playwright_when_absent(self):
        servers = {"context7": {"type": "stdio"}}
        result = recompute_allowed_tools(_BASE_TOOLS, servers)
        assert not any(t.startswith("mcp__playwright__") for t in result)

    def test_does_not_include_firecrawl_when_absent(self):
        servers = {"context7": {"type": "stdio"}}
        result = recompute_allowed_tools(_BASE_TOOLS, servers)
        assert not any(t.startswith("mcp__firecrawl__") for t in result)

    def test_does_not_mutate_base_tools(self):
        base_copy = list(_BASE_TOOLS)
        servers = {"playwright": {"type": "stdio"}, "context7": {"type": "stdio"}}
        recompute_allowed_tools(_BASE_TOOLS, servers)
        assert _BASE_TOOLS == base_copy

    def test_returns_new_list(self):
        result = recompute_allowed_tools(_BASE_TOOLS, {})
        assert result is not _BASE_TOOLS
