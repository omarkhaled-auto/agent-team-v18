"""Tests for NEW-10 Step 1: audit_agent.py query() -> ClaudeSDKClient migration."""
import ast
import inspect
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock


SRC_PATH = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15" / "audit_agent.py"


def _read_source() -> str:
    return SRC_PATH.read_text(encoding="utf-8")


def _parse_ast() -> ast.Module:
    return ast.compile(_read_source(), str(SRC_PATH), "exec", ast.PyCF_ONLY_AST)


# ---------------------------------------------------------------------------
# 1. ClaudeSDKClient is used, not bare query()
# ---------------------------------------------------------------------------

def test_audit_agent_uses_claude_sdk_client_not_query():
    """The _call_claude_sdk function should use ClaudeSDKClient, not a bare
    one-shot query() pattern.  Both Try-2 call sites must import and
    instantiate ClaudeSDKClient."""
    source = _read_source()
    # ClaudeSDKClient must appear (the migration target)
    assert "ClaudeSDKClient" in source, "ClaudeSDKClient not found in audit_agent.py"
    # The old bare `query(` one-shot pattern (outside of `client.query(`) should
    # not exist.  We check that every `query(` call is preceded by `client.` or
    # `await client.` — i.e. it is a method call on a ClaudeSDKClient instance.
    import re
    # Find all query( calls that are NOT `client.query(` or `.query(`
    bare_query_calls = re.findall(r'(?<!\.)query\s*\(', source)
    # All remaining matches should be zero (only client.query exists)
    assert len(bare_query_calls) == 0, (
        f"Found {len(bare_query_calls)} bare query() calls that are not client.query()"
    )


def test_audit_agent_call_claude_sdk_imports_correctly():
    """Verify ClaudeSDKClient and ClaudeAgentOptions are imported."""
    source = _read_source()
    assert "from claude_agent_sdk import ClaudeSDKClient" in source
    assert "ClaudeAgentOptions" in source


# ---------------------------------------------------------------------------
# 2. MCP servers are wired
# ---------------------------------------------------------------------------

def test_audit_agent_has_mcp_servers():
    """Both _call_claude_sdk call sites should populate mcp_servers dict
    with context7 and sequential_thinking."""
    source = _read_source()
    assert "mcp_servers" in source
    assert "context7" in source
    assert "sequential_thinking" in source


def test_audit_agent_mcp_graceful_degradation():
    """MCP import failure is caught with a bare except/pass so the audit
    scorer can still function without MCP servers."""
    source = _read_source()
    # There should be at least one try/except around the mcp_servers import
    assert "except Exception:" in source or "except ImportError:" in source
    # And the pass fallback
    assert "pass  # MCP servers are optional" in source


# ---------------------------------------------------------------------------
# 3. Client interrupt availability
# ---------------------------------------------------------------------------

def test_audit_agent_client_interrupt_available():
    """ClaudeSDKClient instances created in _call_claude_sdk should have
    an interrupt method.  We verify this structurally: the `async with
    ClaudeSDKClient(options=options) as client:` pattern implies the
    client object has the full SDK API including interrupt()."""
    source = _read_source()
    # Verify the async context manager pattern is used
    assert "async with ClaudeSDKClient(options=options) as client:" in source


# ---------------------------------------------------------------------------
# 4. Public API preserved
# ---------------------------------------------------------------------------

def test_audit_agent_public_api_preserved():
    """run_audit, AuditReport, Severity, FindingCategory must all be importable."""
    from agent_team_v15.audit_agent import run_audit, AuditReport, Severity, FindingCategory
    assert callable(run_audit)
    assert inspect.isclass(AuditReport)
    assert issubclass(Severity, __import__("enum").Enum)
    assert issubclass(FindingCategory, __import__("enum").Enum)


# ---------------------------------------------------------------------------
# 5. Timeouts preserved
# ---------------------------------------------------------------------------

def test_audit_agent_timeout_preserved():
    """The 120s (scorer) and 600s (agentic) timeouts must still be present."""
    source = _read_source()
    assert "timeout=120" in source, "120s scorer timeout missing"
    assert "timeout=600" in source, "600s agentic timeout missing"


# ---------------------------------------------------------------------------
# 6. Try-1 path (direct Anthropic API) not modified
# ---------------------------------------------------------------------------

def test_audit_agent_try1_path_unchanged():
    """_call_claude_sdk Try 1 still uses the direct anthropic.Anthropic() client,
    not ClaudeSDKClient.  This path is intentionally preserved for environments
    where ANTHROPIC_API_KEY is set and the CLI is unavailable."""
    source = _read_source()
    assert "anthropic.Anthropic(" in source, "Direct Anthropic API path (Try 1) removed"
    assert "client.messages.create(" in source, "Direct messages.create call (Try 1) removed"
