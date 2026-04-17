"""Tests for Bug #20: Codex app-server transport migration."""
import importlib
import inspect
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15"


# ---------------------------------------------------------------------------
# Module existence and public API
# ---------------------------------------------------------------------------

def test_codex_appserver_module_exists():
    """The codex_appserver module must be importable."""
    import agent_team_v15.codex_appserver as mod
    assert mod is not None


def test_codex_appserver_execute_codex_function_exists():
    """execute_codex must be a callable in codex_appserver."""
    from agent_team_v15.codex_appserver import execute_codex
    assert callable(execute_codex)
    assert inspect.iscoroutinefunction(execute_codex), "execute_codex must be async"


def test_codex_appserver_is_codex_available_function_exists():
    """is_codex_available must be a callable in codex_appserver."""
    from agent_team_v15.codex_appserver import is_codex_available
    assert callable(is_codex_available)


# ---------------------------------------------------------------------------
# CodexOrphanToolError
# ---------------------------------------------------------------------------

def test_codex_orphan_tool_error_exception():
    """CodexOrphanToolError must exist with tool_name, tool_id,
    age_seconds, and orphan_count fields."""
    from agent_team_v15.codex_appserver import CodexOrphanToolError

    err = CodexOrphanToolError(
        tool_name="shell",
        tool_id="tu-123",
        age_seconds=350.0,
        orphan_count=2,
    )
    assert err.tool_name == "shell"
    assert err.tool_id == "tu-123"
    assert err.age_seconds == 350.0
    assert err.orphan_count == 2
    assert isinstance(err, Exception)
    assert "shell" in str(err)


# ---------------------------------------------------------------------------
# Config flags
# ---------------------------------------------------------------------------

def test_codex_transport_mode_flag_exists():
    """V18Config must have codex_transport_mode with default 'exec'."""
    from agent_team_v15.config import V18Config

    cfg = V18Config()
    assert hasattr(cfg, "codex_transport_mode")
    assert cfg.codex_transport_mode == "exec"


def test_codex_orphan_timeout_flag_exists():
    """V18Config must have codex_orphan_tool_timeout_seconds with default 300."""
    from agent_team_v15.config import V18Config

    cfg = V18Config()
    assert hasattr(cfg, "codex_orphan_tool_timeout_seconds")
    assert cfg.codex_orphan_tool_timeout_seconds == 300


# ---------------------------------------------------------------------------
# Provider router integration
# ---------------------------------------------------------------------------

def test_provider_router_imports_codex_orphan_error():
    """provider_router must gracefully import CodexOrphanToolError from
    codex_appserver.  The import uses a try/except so that exec-only
    environments don't crash."""
    source = (SRC_DIR / "provider_router.py").read_text(encoding="utf-8")
    assert "CodexOrphanToolError" in source
    # The graceful fallback pattern
    assert "except ImportError" in source


def test_provider_router_catches_watchdog_timeout_for_fallback():
    """WaveWatchdogTimeoutError must be caught in the Codex execution path
    and route to _claude_fallback (NOT re-raise)."""
    source = (SRC_DIR / "provider_router.py").read_text(encoding="utf-8")
    assert "except WaveWatchdogTimeoutError" in source
    # After catching, it should call _claude_fallback
    idx = source.find("except WaveWatchdogTimeoutError")
    assert idx != -1
    region_after = source[idx:idx + 500]
    assert "_claude_fallback" in region_after


def test_provider_router_catches_orphan_error_for_fallback():
    """CodexOrphanToolError must be caught in the Codex execution path
    and route to _claude_fallback."""
    source = (SRC_DIR / "provider_router.py").read_text(encoding="utf-8")
    assert "_CodexOrphanToolError" in source
    idx = source.find("except _CodexOrphanToolError")
    assert idx != -1
    region_after = source[idx:idx + 800]
    assert "_claude_fallback" in region_after


# ---------------------------------------------------------------------------
# Transport factory routing
# ---------------------------------------------------------------------------

def test_codex_transport_factory_routes_by_flag():
    """When codex_transport_mode is 'app-server', the app-server module should
    be used; when 'exec', the original codex_transport module is used.
    We verify both modules have the required execute_codex API."""
    from agent_team_v15 import codex_appserver, codex_transport

    # Both modules must expose execute_codex
    assert hasattr(codex_appserver, "execute_codex")
    assert hasattr(codex_transport, "execute_codex")
    # Both must expose is_codex_available
    assert hasattr(codex_appserver, "is_codex_available")
    assert hasattr(codex_transport, "is_codex_available")


def test_old_codex_transport_preserved():
    """codex_transport.py must still be importable with unchanged public API:
    execute_codex, is_codex_available, CodexConfig, CodexResult."""
    from agent_team_v15.codex_transport import (
        execute_codex,
        is_codex_available,
        CodexConfig,
        CodexResult,
    )
    assert callable(execute_codex)
    assert callable(is_codex_available)
    assert inspect.isclass(CodexConfig)
    assert inspect.isclass(CodexResult)


def test_codex_appserver_reuses_codex_config_and_result():
    """codex_appserver must reuse CodexConfig and CodexResult from
    codex_transport so callers see identical types."""
    from agent_team_v15.codex_appserver import CodexConfig as AppConfig
    from agent_team_v15.codex_appserver import CodexResult as AppResult
    from agent_team_v15.codex_transport import CodexConfig, CodexResult

    assert AppConfig is CodexConfig, "codex_appserver.CodexConfig is not the same class"
    assert AppResult is CodexResult, "codex_appserver.CodexResult is not the same class"
