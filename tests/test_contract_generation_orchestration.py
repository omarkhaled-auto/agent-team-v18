"""Tests for D-08 — CONTRACTS.json primary deterministic producer.

The orchestration phase now calls ``_run_contract_generation_phase``
which attempts static-analysis extraction first (no LLM) and only falls
back to the existing LLM recovery pass when the primary path does not
produce ``CONTRACTS.json``. These tests exercise the four branches:

1. Primary path succeeds (no runtime verification required).
2. Primary success → recovery runner is not invoked.
3. Primary path failure → recovery runs and succeeds.
4. Both primary AND recovery fail → phase returns ``"failed"``.

All extraction is mocked — no real NestJS parsing or LLM calls. The
phase helper accepts injectable primary/recovery runners specifically
to keep tests hermetic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config() -> AgentTeamConfig:
    return AgentTeamConfig()


def _make_primary_success(tmp_path: Path, file_name: str = "CONTRACTS.json"):
    """Build a primary runner that writes a valid contracts file."""

    def runner(project_root: Path, output_path: Path) -> tuple[bool, str | None]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"endpoints": [{"path": "/health"}]}, indent=2),
            encoding="utf-8",
        )
        return True, None

    return runner


def _make_primary_failure(error: str = "no code parsed"):
    def runner(project_root: Path, output_path: Path) -> tuple[bool, str | None]:
        return False, error

    return runner


def _make_recovery_success(out_path: Path, cost: float = 0.42):
    """Recovery runner that also writes a valid contracts file — simulates
    the LLM-based recovery pass after primary failed."""
    calls: list[int] = []

    def runner() -> float:
        calls.append(1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"endpoints": [{"path": "/health", "source": "llm"}]}),
            encoding="utf-8",
        )
        return cost

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _make_recovery_failure(cost: float = 0.0):
    calls: list[int] = []

    def runner() -> float:
        calls.append(1)
        return cost

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


# ---------------------------------------------------------------------------
# 1. Primary path generates CONTRACTS.json deterministically
# ---------------------------------------------------------------------------


def test_primary_path_produces_contracts_without_recovery(tmp_path: Path) -> None:
    """Primary (static-analysis) path writes CONTRACTS.json → marker=primary.

    Simulates an M1 build where runtime verification (docker compose) was
    skipped; the extractor still produces a usable bundle from source.
    """
    contract_path = tmp_path / ".agent-team" / "CONTRACTS.json"
    logs: dict[str, list[str]] = {"info": [], "warning": [], "error": []}

    recovery = _make_recovery_failure()

    marker, recovery_cost = _cli._run_contract_generation_phase(
        cwd=str(tmp_path),
        config=_config(),
        has_requirements=True,
        generator_enabled=True,
        contract_path=contract_path,
        primary_runner=_make_primary_success(tmp_path),
        recovery_runner=recovery,
        log_info=logs["info"].append,
        log_warning=logs["warning"].append,
        log_error=logs["error"].append,
    )

    assert marker == "primary"
    assert recovery_cost == 0.0
    assert contract_path.is_file()
    # Recovery MUST NOT be invoked when primary succeeds.
    assert recovery.calls == []  # type: ignore[attr-defined]
    # Log explicitly identifies which path produced the file.
    assert any("primary" in m and "static-analysis" in m for m in logs["info"])


# ---------------------------------------------------------------------------
# 2. Orchestrator already produced the file — no primary or recovery needed
# ---------------------------------------------------------------------------


def test_pre_existing_file_treated_as_primary(tmp_path: Path) -> None:
    """If the orchestrator itself wrote CONTRACTS.json during its turns
    the phase is a no-op and logs ``primary`` with source=orchestrator."""
    contract_path = tmp_path / ".agent-team" / "CONTRACTS.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text("{}", encoding="utf-8")

    logs: dict[str, list[str]] = {"info": [], "warning": [], "error": []}
    primary_calls: list[int] = []

    def primary_runner(root: Path, out: Path) -> tuple[bool, str | None]:
        primary_calls.append(1)
        return True, None

    recovery = _make_recovery_failure()

    marker, _ = _cli._run_contract_generation_phase(
        cwd=str(tmp_path),
        config=_config(),
        has_requirements=True,
        generator_enabled=True,
        contract_path=contract_path,
        primary_runner=primary_runner,
        recovery_runner=recovery,
        log_info=logs["info"].append,
        log_warning=logs["warning"].append,
        log_error=logs["error"].append,
    )

    assert marker == "primary"
    # Neither the static-analysis primary nor the LLM recovery is invoked.
    assert primary_calls == []
    assert recovery.calls == []  # type: ignore[attr-defined]
    assert any("orchestrator" in m for m in logs["info"])


# ---------------------------------------------------------------------------
# 3. Primary fails → recovery runs and succeeds → marker = recovery-fallback
# ---------------------------------------------------------------------------


def test_recovery_fallback_runs_when_primary_fails(tmp_path: Path) -> None:
    contract_path = tmp_path / ".agent-team" / "CONTRACTS.json"
    logs: dict[str, list[str]] = {"info": [], "warning": [], "error": []}

    recovery = _make_recovery_success(contract_path, cost=1.23)

    marker, recovery_cost = _cli._run_contract_generation_phase(
        cwd=str(tmp_path),
        config=_config(),
        has_requirements=True,
        generator_enabled=True,
        contract_path=contract_path,
        primary_runner=_make_primary_failure("extractor produced empty bundle"),
        recovery_runner=recovery,
        log_info=logs["info"].append,
        log_warning=logs["warning"].append,
        log_error=logs["error"].append,
    )

    assert marker == "recovery-fallback"
    assert recovery_cost == pytest.approx(1.23)
    # Warning explains why primary failed so operators can triage.
    assert any("primary path did not produce" in m for m in logs["warning"])
    # Final info log names the fallback path.
    assert any("recovery-fallback" in m for m in logs["info"])


# ---------------------------------------------------------------------------
# 4. Double failure → marker = failed (pipeline hard-fail signal)
# ---------------------------------------------------------------------------


def test_double_failure_marks_phase_failed(tmp_path: Path) -> None:
    contract_path = tmp_path / ".agent-team" / "CONTRACTS.json"
    logs: dict[str, list[str]] = {"info": [], "warning": [], "error": []}

    recovery = _make_recovery_failure(cost=0.0)  # does nothing

    marker, recovery_cost = _cli._run_contract_generation_phase(
        cwd=str(tmp_path),
        config=_config(),
        has_requirements=True,
        generator_enabled=True,
        contract_path=contract_path,
        primary_runner=_make_primary_failure(),
        recovery_runner=recovery,
        log_info=logs["info"].append,
        log_warning=logs["warning"].append,
        log_error=logs["error"].append,
    )

    assert marker == "failed"
    assert recovery_cost == 0.0
    assert not contract_path.is_file()
    # Hard-fail must be surfaced as an ERROR, not a silent warning.
    assert any("HARD-FAIL" in m for m in logs["error"])


# ---------------------------------------------------------------------------
# Module: skipped when generator disabled / no requirements
# ---------------------------------------------------------------------------


def test_phase_skipped_when_generator_disabled(tmp_path: Path) -> None:
    contract_path = tmp_path / ".agent-team" / "CONTRACTS.json"
    recovery = _make_recovery_failure()
    marker, _ = _cli._run_contract_generation_phase(
        cwd=str(tmp_path),
        config=_config(),
        has_requirements=True,
        generator_enabled=False,
        contract_path=contract_path,
        primary_runner=_make_primary_success(tmp_path),
        recovery_runner=recovery,
    )
    assert marker == "skipped"
    assert recovery.calls == []  # type: ignore[attr-defined]
    assert not contract_path.is_file()


def test_phase_skipped_without_requirements(tmp_path: Path) -> None:
    contract_path = tmp_path / ".agent-team" / "CONTRACTS.json"
    recovery = _make_recovery_failure()
    marker, _ = _cli._run_contract_generation_phase(
        cwd=str(tmp_path),
        config=_config(),
        has_requirements=False,
        generator_enabled=True,
        contract_path=contract_path,
        primary_runner=_make_primary_success(tmp_path),
        recovery_runner=recovery,
    )
    assert marker == "skipped"


# ---------------------------------------------------------------------------
# Default primary runner uses api_contract_extractor
# ---------------------------------------------------------------------------


def test_default_primary_uses_static_extractor(tmp_path: Path, monkeypatch) -> None:
    """When ``primary_runner`` is omitted the phase helper calls
    ``_run_contract_primary_generation`` which in turn uses
    ``api_contract_extractor``. We patch the extractor module to avoid
    real parsing and assert the default wiring succeeds."""

    class _StubBundle:
        endpoints = [object()]
        models: list[Any] = []
        enums: list[Any] = []

    from agent_team_v15 import api_contract_extractor as ace

    monkeypatch.setattr(ace, "extract_api_contracts", lambda root: _StubBundle())

    written: dict[str, Any] = {}

    def _save(bundle: Any, output_path: Path) -> None:
        written["path"] = output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(ace, "save_api_contracts", _save)

    contract_path = tmp_path / ".agent-team" / "CONTRACTS.json"
    produced, error = _cli._run_contract_primary_generation(
        tmp_path, contract_path
    )
    assert produced is True
    assert error is None
    assert contract_path.is_file()
    assert written["path"] == contract_path


def test_default_primary_empty_bundle_surfaces_error(
    tmp_path: Path, monkeypatch
) -> None:
    """An extractor that returns a bundle with no endpoints/models/enums
    is treated as a primary-path failure so recovery can take over."""

    class _EmptyBundle:
        endpoints: list[Any] = []
        models: list[Any] = []
        enums: list[Any] = []

    from agent_team_v15 import api_contract_extractor as ace

    monkeypatch.setattr(ace, "extract_api_contracts", lambda root: _EmptyBundle())

    saves: list[Any] = []

    def _save(bundle: Any, output_path: Path) -> None:
        saves.append((bundle, output_path))

    monkeypatch.setattr(ace, "save_api_contracts", _save)

    contract_path = tmp_path / ".agent-team" / "CONTRACTS.json"
    produced, error = _cli._run_contract_primary_generation(
        tmp_path, contract_path
    )
    assert produced is False
    assert error == "extractor produced empty bundle"
    # Writer must NOT be called on empty bundles.
    assert saves == []
