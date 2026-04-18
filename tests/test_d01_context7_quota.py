"""Tests for D-01 context7 quota graceful degradation.

Covers run_mcp_preflight context7 entry and related wave prompt
warning on empty context.
"""
from unittest.mock import MagicMock

from agent_team_v15.mcp_servers import run_mcp_preflight


def _make_config(context7_enabled=True):
    """Build a minimal mock config for preflight testing."""
    cfg = MagicMock()

    # mcp_servers.get("context7") returns a mock with .enabled
    context7_cfg = MagicMock()
    context7_cfg.enabled = context7_enabled
    cfg.mcp_servers = {"context7": context7_cfg} if context7_enabled else {}

    # contract_engine needs to be set for existing preflight checks
    cfg.contract_engine = MagicMock()
    cfg.contract_engine.enabled = False
    cfg.contract_engine.mcp_command = ""

    # codebase_intelligence
    cfg.codebase_intelligence = MagicMock()
    cfg.codebase_intelligence.enabled = False

    return cfg


def test_preflight_includes_context7_available(tmp_path):
    cfg = _make_config(context7_enabled=True)
    result = run_mcp_preflight(str(tmp_path), cfg)
    assert result["tools"]["context7"]["available"] is True


def test_preflight_includes_context7_disabled(tmp_path):
    cfg = _make_config(context7_enabled=False)
    result = run_mcp_preflight(str(tmp_path), cfg)
    assert result["tools"]["context7"]["available"] is False


def test_preflight_context7_reason_when_disabled(tmp_path):
    cfg = _make_config(context7_enabled=False)
    result = run_mcp_preflight(str(tmp_path), cfg)
    assert result["tools"]["context7"]["reason"] == "disabled_in_config"


def test_preflight_context7_no_reason_when_enabled(tmp_path):
    cfg = _make_config(context7_enabled=True)
    result = run_mcp_preflight(str(tmp_path), cfg)
    assert result["tools"]["context7"]["reason"] == ""


def test_preflight_snapshot_persisted(tmp_path):
    """Preflight should write MCP_PREFLIGHT.json to .agent-team/."""
    cfg = _make_config(context7_enabled=True)
    run_mcp_preflight(str(tmp_path), cfg)
    preflight_file = tmp_path / ".agent-team" / "MCP_PREFLIGHT.json"
    assert preflight_file.exists()


def test_preflight_snapshot_contains_context7_key(tmp_path):
    """The persisted JSON should contain the context7 tool entry."""
    import json
    cfg = _make_config(context7_enabled=True)
    run_mcp_preflight(str(tmp_path), cfg)
    preflight_file = tmp_path / ".agent-team" / "MCP_PREFLIGHT.json"
    data = json.loads(preflight_file.read_text())
    assert "context7" in data["tools"]
    assert data["tools"]["context7"]["available"] is True
