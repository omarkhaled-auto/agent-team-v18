"""Phase G Slice 1b — Codex transport selector honors ``codex_transport_mode``.

Previously the exec transport was hard-coded (investigation report Surprise
#1). After Slice 1b, ``cli._run_prd_milestones`` consults
``config.v18.codex_transport_mode`` and imports either ``codex_appserver``
(default ``"app-server"``) or the legacy ``codex_transport`` test override.

These tests assert:
1. Both modules exist and expose ``execute_codex``.
2. The selector logic in ``cli.py:3229`` matches the spec.
3. The default value of the flag is ``"app-server"`` so every Codex-routed
   production wave uses the JSON-RPC app-server transport.
"""

from __future__ import annotations

import inspect

from agent_team_v15 import codex_appserver, codex_transport
from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig


def test_default_transport_mode_is_app_server() -> None:
    """Codex-routed waves use app-server unless a test opts out."""
    cfg = AgentTeamConfig()
    assert cfg.v18.provider_routing is True
    assert cfg.v18.codex_transport_mode == "app-server"
    assert cfg.v18.codex_protocol_capture_enabled is True


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


def test_cli_hardwire_overrides_legacy_wave_backend_config() -> None:
    """Production CLI runs ignore legacy config values that disable the new backends."""
    cfg = AgentTeamConfig()
    cfg.agent_teams.enabled = False
    cfg.agent_teams.fallback_to_cli = True
    cfg.v18.provider_routing = False
    cfg.v18.codex_transport_mode = "exec"
    cfg.v18.codex_fix_routing_enabled = False
    cfg.v18.codex_wave_b_prompt_hardening_enabled = False
    cfg.v18.codex_capture_enabled = False
    cfg.v18.codex_protocol_capture_enabled = False

    _cli._hardwire_wave_backend_config(cfg)

    assert cfg.agent_teams.enabled is True
    assert cfg.agent_teams.fallback_to_cli is False
    assert cfg.v18.provider_routing is True
    assert cfg.v18.codex_transport_mode == "app-server"
    assert cfg.v18.codex_fix_routing_enabled is True
    assert cfg.v18.codex_wave_b_prompt_hardening_enabled is True
    assert cfg.v18.codex_capture_enabled is True
    assert cfg.v18.codex_protocol_capture_enabled is True


def test_transport_mode_field_accepts_both_values() -> None:
    """The dataclass must allow both valid values."""
    cfg = AgentTeamConfig()
    cfg.v18.codex_transport_mode = "app-server"
    assert cfg.v18.codex_transport_mode == "app-server"
    cfg.v18.codex_transport_mode = "exec"
    assert cfg.v18.codex_transport_mode == "exec"
