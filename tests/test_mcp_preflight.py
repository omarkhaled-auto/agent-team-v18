"""Tests for D-09 — Contract Engine MCP pre-flight + labeled fallback.

These tests exercise ``contract_engine_is_deployable``,
``run_mcp_preflight``, and ``ensure_contract_e2e_fidelity_header`` in
``agent_team_v15.mcp_servers``. Pre-flight decisions are injected via
``which`` / ``module_available`` callables so the tests do not touch
real ``shutil.which`` or ``importlib.util.find_spec``; no MCP
subprocesses are spawned.

Branch B was chosen in the D-09 investigation (the Contract Engine
server module ``src.contract_engine.mcp_server`` is not deployed in
this repo). The helpers guarantee that fact is now VISIBLE in
``MCP_PREFLIGHT.json`` and that the static-analysis fallback in
``CONTRACT_E2E_RESULTS.md`` gets a clearly-labeled fidelity header.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agent_team_v15.config import AgentTeamConfig
from agent_team_v15 import mcp_servers as mcp_mod
from agent_team_v15.mcp_servers import (
    CONTRACT_E2E_STATIC_FIDELITY_HEADER,
    contract_engine_is_deployable,
    ensure_contract_e2e_fidelity_header,
    run_mcp_preflight,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(
    *,
    ce_enabled: bool = False,
    ce_command: str = "python",
    ce_args: list[str] | None = None,
    ci_enabled: bool = False,
) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.contract_engine.enabled = ce_enabled
    cfg.contract_engine.mcp_command = ce_command
    if ce_args is not None:
        cfg.contract_engine.mcp_args = list(ce_args)
    cfg.codebase_intelligence.enabled = ci_enabled
    return cfg


# ---------------------------------------------------------------------------
# contract_engine_is_deployable — decision table
# ---------------------------------------------------------------------------


def test_deployable_false_when_disabled_in_config() -> None:
    cfg = _config(ce_enabled=False)
    ok, reason = contract_engine_is_deployable(cfg)
    assert ok is False
    assert reason == "disabled_in_config"


def test_deployable_false_when_command_not_on_path() -> None:
    cfg = _config(ce_enabled=True, ce_command="python")
    ok, reason = contract_engine_is_deployable(
        cfg,
        which=lambda cmd: None,
        module_available=lambda m: True,
    )
    assert ok is False
    assert reason.startswith("command_not_on_path:")
    assert "python" in reason


def test_deployable_false_when_module_not_importable() -> None:
    """The canonical invocation is ``python -m src.contract_engine.mcp_server``
    — if the module path after ``-m`` cannot be resolved, the tool is
    not deployable even when ``python`` itself is on PATH."""
    cfg = _config(
        ce_enabled=True,
        ce_command="python",
        ce_args=["-m", "src.contract_engine.mcp_server"],
    )
    ok, reason = contract_engine_is_deployable(
        cfg,
        which=lambda cmd: "/usr/bin/python",
        module_available=lambda m: False,
    )
    assert ok is False
    assert reason.startswith("module_not_importable:")
    assert "src.contract_engine.mcp_server" in reason


def test_deployable_true_when_command_and_module_resolve() -> None:
    cfg = _config(
        ce_enabled=True,
        ce_command="python",
        ce_args=["-m", "src.contract_engine.mcp_server"],
    )
    ok, reason = contract_engine_is_deployable(
        cfg,
        which=lambda cmd: "/usr/bin/python",
        module_available=lambda m: True,
    )
    assert ok is True
    assert reason == ""


def test_deployable_without_dash_m_trusts_which() -> None:
    """A standalone executable (no ``-m`` flag) relies solely on
    ``shutil.which`` to verify deployability."""
    cfg = _config(
        ce_enabled=True,
        ce_command="contract-engine-server",
        ce_args=[],
    )
    ok, _ = contract_engine_is_deployable(
        cfg,
        which=lambda cmd: "/opt/bin/contract-engine-server",
        module_available=lambda m: False,  # should not be consulted
    )
    assert ok is True


def test_deployable_false_when_command_unset() -> None:
    cfg = _config(ce_enabled=True, ce_command="")
    ok, reason = contract_engine_is_deployable(cfg)
    assert ok is False
    assert reason == "mcp_command_unset"


# ---------------------------------------------------------------------------
# run_mcp_preflight — structured log + JSON snapshot
# ---------------------------------------------------------------------------


def test_preflight_writes_structured_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-flight persists a per-tool status block to
    ``.agent-team/MCP_PREFLIGHT.json`` regardless of availability."""
    monkeypatch.setattr(mcp_mod.shutil, "which", lambda cmd: None)
    cfg = _config(ce_enabled=True)

    snapshot = run_mcp_preflight(tmp_path, cfg)

    target = tmp_path / ".agent-team" / "MCP_PREFLIGHT.json"
    assert target.is_file()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk == snapshot
    # Both tools present with structured fields.
    assert "validate_endpoint" in on_disk["tools"]
    assert "codebase_intelligence" in on_disk["tools"]
    for status in on_disk["tools"].values():
        assert "available" in status
        assert "reason" in status
        assert "provider" in status
    # ISO timestamp present and string-shaped.
    assert isinstance(on_disk["generated_at"], str)


def test_preflight_logs_missing_as_distinct_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Operator-visible log line must contain ``validate_endpoint`` and
    ``missing`` as distinct tokens. Build-j had no such line at all — the
    degradation was invisible until the audit read the markdown."""
    monkeypatch.setattr(mcp_mod.shutil, "which", lambda cmd: None)
    cfg = _config(ce_enabled=False)

    with caplog.at_level(logging.INFO, logger=mcp_mod.logger.name):
        run_mcp_preflight(tmp_path, cfg)

    messages = [rec.getMessage() for rec in caplog.records]
    assert any(
        "validate_endpoint" in m and "missing" in m for m in messages
    ), f"expected validate_endpoint/missing log; got {messages!r}"


def test_preflight_reports_available_when_deployable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: command on PATH + module importable → available=True."""
    monkeypatch.setattr(mcp_mod.shutil, "which", lambda cmd: "/usr/bin/python")
    monkeypatch.setattr(mcp_mod, "_module_spec_available", lambda mod: True)
    cfg = _config(
        ce_enabled=True,
        ce_command="python",
        ce_args=["-m", "src.contract_engine.mcp_server"],
    )

    snapshot = run_mcp_preflight(tmp_path, cfg)
    assert snapshot["tools"]["validate_endpoint"]["available"] is True
    assert snapshot["tools"]["validate_endpoint"]["reason"] == ""


# ---------------------------------------------------------------------------
# ensure_contract_e2e_fidelity_header — idempotent prepend
# ---------------------------------------------------------------------------


def _make_results_file(tmp_path: Path, body: str) -> Path:
    target = tmp_path / ".agent-team" / "CONTRACT_E2E_RESULTS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def test_fidelity_header_prepended_when_engine_missing(tmp_path: Path) -> None:
    target = _make_results_file(tmp_path, "# Contract Compliance E2E Results\n\n| ... |\n")

    modified = ensure_contract_e2e_fidelity_header(
        target, contract_engine_available=False
    )
    assert modified is True
    content = target.read_text(encoding="utf-8")
    assert content.startswith(CONTRACT_E2E_STATIC_FIDELITY_HEADER.splitlines()[0])
    assert "STATIC ANALYSIS (not runtime)" in content
    assert "NOT deployed" not in content  # spelling guard
    assert "`validate_endpoint`" in content
    # Original body preserved below the header.
    assert "| ... |" in content


def test_fidelity_header_idempotent(tmp_path: Path) -> None:
    """Calling the helper twice on the same file must not double-prepend."""
    target = _make_results_file(tmp_path, "# Results\n")

    first = ensure_contract_e2e_fidelity_header(
        target, contract_engine_available=False
    )
    assert first is True
    body_after_first = target.read_text(encoding="utf-8")

    second = ensure_contract_e2e_fidelity_header(
        target, contract_engine_available=False
    )
    assert second is False  # no modification on the second call
    assert target.read_text(encoding="utf-8") == body_after_first
    # Header appears exactly once.
    assert body_after_first.count("Verification fidelity:") == 1


def test_fidelity_header_skipped_when_engine_available(tmp_path: Path) -> None:
    """When the engine IS deployable, we do NOT prepend the static-analysis
    banner — runtime verification is the real source of truth."""
    target = _make_results_file(tmp_path, "# Real runtime results\n")

    modified = ensure_contract_e2e_fidelity_header(
        target, contract_engine_available=True
    )
    assert modified is False
    content = target.read_text(encoding="utf-8")
    assert "STATIC ANALYSIS" not in content
    assert content == "# Real runtime results\n"


def test_fidelity_header_noop_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / ".agent-team" / "CONTRACT_E2E_RESULTS.md"
    modified = ensure_contract_e2e_fidelity_header(
        missing, contract_engine_available=False
    )
    assert modified is False
    # Helper must not create the file.
    assert not missing.exists()


def test_fidelity_header_respects_existing_marker(tmp_path: Path) -> None:
    """If a prior run (or the LLM sub-agent) already wrote a fidelity
    banner, the helper leaves it alone — idempotent across producers."""
    preexisting = (
        "> **Verification fidelity:** STATIC ANALYSIS (sub-agent produced)\n\n"
        "# Results\n"
    )
    target = _make_results_file(tmp_path, preexisting)

    modified = ensure_contract_e2e_fidelity_header(
        target, contract_engine_available=False
    )
    assert modified is False
    assert target.read_text(encoding="utf-8") == preexisting
