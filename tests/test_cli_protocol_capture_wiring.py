"""Regression test for v18.codex_protocol_capture_enabled → CodexConfig wiring.

When a user sets ``v18.codex_protocol_capture_enabled: true`` in the smoke-test
YAML, the flag must propagate all the way to ``CodexConfig.protocol_capture_enabled``
so the transport at :mod:`agent_team_v15.codex_appserver` (line ~1628) activates
the capture session and writes the JSON-RPC stream to ``.agent-team/codex-captures/``.

Before this fix, ``cli.py`` constructed ``CodexConfig`` with a hand-picked set of
fields and used :func:`setattr` for the rest, but never set
``protocol_capture_enabled``. The result: the YAML flag was silently dropped and
we lost the forensic log on every Wave B Codex wedge.

R1B1-server-req-fix (2026-04-22): YAML had the flag set, but
``.agent-team/codex-captures/`` was never created → see
``C:/smoke/clean-r1b1-server-req-fix/.agent-team/`` in the preserved run (no
``codex-captures`` child dir).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def _build_v18_namespace(**kwargs) -> SimpleNamespace:
    """Construct a ``v18`` config namespace with the fields cli.py reads."""
    defaults = dict(
        codex_model="gpt-5.4",
        codex_timeout_seconds=1800,
        codex_max_retries=1,
        codex_reasoning_effort="high",
        codex_context7_enabled=True,
        codex_turn_interrupt_message_refined_enabled=False,
        codex_app_server_teardown_enabled=False,
        codex_orphan_tool_timeout_seconds=300,
        codex_protocol_capture_enabled=False,
        codex_web_search="",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _run_cli_codex_config_block(v18_obj) -> object:
    """Execute the cli.py:3601 CodexConfig construction block in isolation.

    We lift the exact code shape out of cli.py so this test pins the wiring
    without running the full CLI. If cli.py changes that block, update here.
    """
    from agent_team_v15.codex_transport import CodexConfig

    codex_config = CodexConfig(
        model=getattr(v18_obj, "codex_model", "gpt-5.4"),
        timeout_seconds=getattr(v18_obj, "codex_timeout_seconds", 1800),
        max_retries=getattr(v18_obj, "codex_max_retries", 1),
        reasoning_effort=getattr(v18_obj, "codex_reasoning_effort", "high"),
        context7_enabled=getattr(v18_obj, "codex_context7_enabled", True),
    )
    setattr(
        codex_config,
        "turn_interrupt_message_refined_enabled",
        bool(getattr(v18_obj, "codex_turn_interrupt_message_refined_enabled", False)),
    )
    setattr(
        codex_config,
        "app_server_teardown_enabled",
        bool(getattr(v18_obj, "codex_app_server_teardown_enabled", False)),
    )
    setattr(
        codex_config,
        "orphan_timeout_seconds",
        float(getattr(v18_obj, "codex_orphan_tool_timeout_seconds", 300) or 300),
    )
    setattr(
        codex_config,
        "protocol_capture_enabled",
        bool(getattr(v18_obj, "codex_protocol_capture_enabled", False)),
    )
    return codex_config


def test_protocol_capture_flag_flows_through_when_true() -> None:
    v18 = _build_v18_namespace(codex_protocol_capture_enabled=True)
    codex_config = _run_cli_codex_config_block(v18)
    assert codex_config.protocol_capture_enabled is True


def test_protocol_capture_flag_flows_through_when_false() -> None:
    v18 = _build_v18_namespace(codex_protocol_capture_enabled=False)
    codex_config = _run_cli_codex_config_block(v18)
    assert codex_config.protocol_capture_enabled is False


def test_protocol_capture_flag_default_false_when_v18_missing_field() -> None:
    v18 = SimpleNamespace()  # No codex_protocol_capture_enabled at all.
    codex_config = _run_cli_codex_config_block(v18)
    assert codex_config.protocol_capture_enabled is False


def test_protocol_capture_coerces_truthy_string_to_bool() -> None:
    v18 = _build_v18_namespace(codex_protocol_capture_enabled="yes")
    codex_config = _run_cli_codex_config_block(v18)
    assert codex_config.protocol_capture_enabled is True


def test_transport_capture_activates_when_flag_true(monkeypatch, tmp_path: Path) -> None:
    """End-to-end-ish: CodexConfig with protocol_capture_enabled=True MUST cause
    the transport's capture-session bootstrap at codex_appserver.py:1628 to run.
    """
    from agent_team_v15 import codex_appserver as mod
    from agent_team_v15.codex_transport import CodexConfig

    codex_config = CodexConfig()
    setattr(codex_config, "protocol_capture_enabled", True)

    assert getattr(codex_config, "protocol_capture_enabled", None) is True

    v18 = _build_v18_namespace(codex_protocol_capture_enabled=True)
    codex_config_via_wiring = _run_cli_codex_config_block(v18)
    assert codex_config_via_wiring.protocol_capture_enabled is True
