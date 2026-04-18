"""Phase G Slice 1b — Codex transport selector honors ``codex_transport_mode``.

Previously the exec transport was hard-coded (investigation report Surprise
#1). After Slice 1b, ``cli._run_prd_milestones`` consults
``config.v18.codex_transport_mode`` and imports either ``codex_transport``
(default ``"exec"``) or ``codex_appserver`` (``"app-server"``).

These tests assert:
1. Both modules exist and expose ``execute_codex``.
2. The selector logic in ``cli.py:3229`` matches the spec.
3. The default value of the flag is ``"exec"`` so legacy behaviour is
   preserved on flag-off (structural, behaviour-neutral change).
"""

from __future__ import annotations

import inspect

from agent_team_v15 import codex_appserver, codex_transport
from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig


def test_default_transport_mode_is_exec() -> None:
    """Preserves legacy behaviour on flag-off."""
    cfg = AgentTeamConfig()
    assert cfg.v18.codex_transport_mode == "exec"


def test_both_transport_modules_expose_execute_codex() -> None:
    """Selector requires both modules to share the ``execute_codex`` ABI."""
    assert hasattr(codex_transport, "execute_codex")
    assert hasattr(codex_appserver, "execute_codex")


def test_cli_source_selects_by_codex_transport_mode() -> None:
    """The branch at ``cli.py:3229`` reads ``codex_transport_mode`` and
    imports codex_appserver when value is ``"app-server"``.
    """
    src = inspect.getsource(_cli._run_prd_milestones)
    # Must read the flag
    assert 'getattr(v18, "codex_transport_mode"' in src
    # Must branch on the literal "app-server"
    assert '"app-server"' in src
    # Must import BOTH modules conditionally
    assert "agent_team_v15.codex_appserver" in src
    assert "agent_team_v15.codex_transport" in src


def test_cli_source_threads_selected_module_into_provider_routing() -> None:
    """The selected module is stored under ``codex_transport`` key in the
    provider_routing dict so downstream waves all share the same transport."""
    src = inspect.getsource(_cli._run_prd_milestones)
    assert '"codex_transport":' in src


def test_transport_mode_field_accepts_both_values() -> None:
    """The dataclass must allow both valid values."""
    cfg = AgentTeamConfig()
    cfg.v18.codex_transport_mode = "app-server"
    assert cfg.v18.codex_transport_mode == "app-server"
    cfg.v18.codex_transport_mode = "exec"
    assert cfg.v18.codex_transport_mode == "exec"
