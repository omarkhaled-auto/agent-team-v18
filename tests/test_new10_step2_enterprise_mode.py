"""Tests for NEW-10 Step 2: enterprise-mode Task() dispatch elimination."""
import ast
import inspect
import re
from pathlib import Path


AGENTS_PATH = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15" / "agents.py"
CLI_PATH = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15" / "cli.py"


def _read_agents_source() -> str:
    return AGENTS_PATH.read_text(encoding="utf-8")


def _read_cli_source() -> str:
    return CLI_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Enterprise section boundaries — we test only the enterprise-mode portions
# of agents.py (roughly lines 1814-1905)
# ---------------------------------------------------------------------------

def _extract_enterprise_section(source: str) -> str:
    """Extract the ENTERPRISE MODE section from agents.py source."""
    # Standard model
    start = source.find("ENTERPRISE MODE (150K+ LOC Builds)")
    # Department model extends to end of _DEPARTMENT_MODEL_ENTERPRISE_SECTION
    end = source.find("Audit findings resolved\"\"\"", start)
    if start == -1 or end == -1:
        return source  # fallback to full source
    return source[start:end + len("Audit findings resolved\"\"\"")]


# ---------------------------------------------------------------------------
# 1. No Task() dispatch in enterprise mode — standard model
# ---------------------------------------------------------------------------

def test_enterprise_mode_no_task_dispatch_standard():
    """The standard enterprise-mode section must NOT contain Task('architecture-lead'),
    Task('coding-lead'), or Task('review-lead') dispatch instructions."""
    section = _extract_enterprise_section(_read_agents_source())
    # Task( dispatches should be gone
    assert 'Task("architecture-lead")' not in section
    assert "Task('architecture-lead')" not in section
    assert 'Task("coding-lead")' not in section
    assert "Task('coding-lead')" not in section
    assert 'Task("review-lead")' not in section
    assert "Task('review-lead')" not in section


def test_enterprise_mode_no_task_dispatch_department():
    """The department enterprise-mode section must NOT contain Task('coding-dept-head')
    or Task('review-dept-head') dispatch instructions."""
    section = _extract_enterprise_section(_read_agents_source())
    assert 'Task("coding-dept-head")' not in section
    assert "Task('coding-dept-head')" not in section
    assert 'Task("review-dept-head")' not in section
    assert "Task('review-dept-head')" not in section


# ---------------------------------------------------------------------------
# 2. Enterprise-mode flow documentation preserved
# ---------------------------------------------------------------------------

def test_enterprise_mode_flow_documentation_preserved():
    """The enterprise-mode prompt must still describe the multi-step architecture
    and wave-based coding flow, even though Task() dispatch is removed."""
    section = _extract_enterprise_section(_read_agents_source())
    assert "architecture-lead" in section, "architecture-lead flow description missing"
    assert "coding-lead" in section, "coding-lead flow description missing"
    assert "review-lead" in section, "review-lead flow description missing"
    assert "ARCHITECTURE.md" in section, "ARCHITECTURE.md reference missing"
    assert "OWNERSHIP_MAP.json" in section, "OWNERSHIP_MAP.json reference missing"


# ---------------------------------------------------------------------------
# 3. _execute_enterprise_role_session exists in cli.py
# ---------------------------------------------------------------------------

def test_execute_enterprise_role_session_exists():
    """The function _execute_enterprise_role_session must exist in cli.py."""
    source = _read_cli_source()
    assert "async def _execute_enterprise_role_session(" in source


def test_execute_enterprise_role_session_uses_clone_options():
    """_execute_enterprise_role_session must call _clone_agent_options to create
    a per-role mutable copy of SDK options."""
    source = _read_cli_source()
    # Find the function body
    start = source.find("async def _execute_enterprise_role_session(")
    assert start != -1
    # Look for _clone_agent_options in the next ~50 lines
    func_region = source[start:start + 2000]
    assert "_clone_agent_options" in func_region, (
        "_execute_enterprise_role_session does not call _clone_agent_options"
    )


def test_execute_enterprise_role_session_uses_claude_sdk_client():
    """_execute_enterprise_role_session must use ClaudeSDKClient for the sub-agent session."""
    source = _read_cli_source()
    start = source.find("async def _execute_enterprise_role_session(")
    assert start != -1
    func_region = source[start:start + 2000]
    assert "ClaudeSDKClient" in func_region, (
        "_execute_enterprise_role_session does not use ClaudeSDKClient"
    )


def test_execute_enterprise_role_session_returns_cost():
    """_execute_enterprise_role_session should return a float (the cost)."""
    source = _read_cli_source()
    start = source.find("async def _execute_enterprise_role_session(")
    assert start != -1
    func_region = source[start:start + 2000]
    assert "-> float:" in func_region or "return cost" in func_region, (
        "_execute_enterprise_role_session does not return a float cost"
    )


# ---------------------------------------------------------------------------
# 4. Enterprise sub-agent inherits MCP servers
# ---------------------------------------------------------------------------

def test_enterprise_sub_agent_inherits_mcp_servers():
    """_clone_agent_options must preserve mcp_servers in the clone so enterprise
    sub-agents inherit context7/sequential-thinking."""
    source = _read_cli_source()
    start = source.find("def _clone_agent_options(")
    assert start != -1
    func_region = source[start:start + 500]
    assert "mcp_servers" in func_region, (
        "_clone_agent_options does not handle mcp_servers"
    )


# ---------------------------------------------------------------------------
# 5. CRITICAL REMINDERS updated
# ---------------------------------------------------------------------------

def test_enterprise_mode_critical_reminders_updated():
    """The CRITICAL REMINDERS block in the enterprise-mode orchestrator prompt
    must not contain 'via Task tool' — that dispatch mechanism is eliminated."""
    source = _read_agents_source()
    # Find the CRITICAL REMINDERS block near the enterprise section
    cr_start = source.find("CRITICAL REMINDERS")
    if cr_start != -1:
        cr_region = source[cr_start:cr_start + 500]
        assert "via Task tool" not in cr_region, (
            "CRITICAL REMINDERS still references 'via Task tool'"
        )


# ---------------------------------------------------------------------------
# 6. Both models covered
# ---------------------------------------------------------------------------

def test_enterprise_mode_both_models_covered():
    """Both the standard enterprise model and the department model sections
    must exist in agents.py."""
    source = _read_agents_source()
    assert "ENTERPRISE MODE (150K+ LOC Builds)" in source, "Standard enterprise section missing"
    assert "ENTERPRISE MODE" in source and "DEPARTMENT MODEL" in source, (
        "Department enterprise section missing"
    )
