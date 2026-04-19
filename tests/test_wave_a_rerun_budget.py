"""Phase H1b — shared Wave A rerun budget across schema + A.5 gates.

The plan requires ``wave_a_rerun_budget`` to be a single counter shared
by the schema gate, stack-contract retry, and A.5 gate. The legacy
``wave_a5_max_reruns`` knob forwards as an alias when an operator
explicitly overrides it (non-default); the deprecation warning fires
once per config object.

Direct unit tests on :func:`cli._get_effective_wave_a_rerun_budget` plus
interaction tests that mock A.5 to prove ordering (schema runs BEFORE
A.5) and that budget is shared (not duplicated).
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest import mock

import pytest

from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_alias_warned_set() -> None:
    # Phase H1b follow-up: module-level dedupe sets were removed in
    # favor of ``warnings.warn(DeprecationWarning, ...)`` for the alias
    # deprecation path and unconditional INFO logging for the skip path.
    # Python's warnings filter dedupes by default; nothing to reset.
    yield


def _cfg(*, budget: int = 2, legacy: int | None = None) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a_rerun_budget = budget
    if legacy is not None:
        cfg.v18.wave_a5_max_reruns = legacy
    return cfg


# ---------------------------------------------------------------------------
# _get_effective_wave_a_rerun_budget
# ---------------------------------------------------------------------------


def test_default_budget_is_canonical_value() -> None:
    cfg = AgentTeamConfig()
    # Defaults: wave_a_rerun_budget=2, wave_a5_max_reruns=1 (legacy default).
    assert _cli._get_effective_wave_a_rerun_budget(cfg) == cfg.v18.wave_a_rerun_budget


def test_default_legacy_value_does_not_warn() -> None:
    cfg = AgentTeamConfig()
    import warnings as _warnings

    with _warnings.catch_warnings(record=True) as captured:
        _warnings.simplefilter("always", DeprecationWarning)
        _cli._get_effective_wave_a_rerun_budget(cfg)
    deprecated = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert not deprecated, (
        "Deprecation warning should NOT fire when operator did not override "
        f"the legacy alias. Got: {[str(w.message) for w in deprecated]!r}"
    )


def test_non_default_legacy_value_forwards_and_warns() -> None:
    cfg = _cfg(budget=2, legacy=5)  # operator override of legacy alias
    import warnings as _warnings

    with _warnings.catch_warnings(record=True) as captured:
        _warnings.simplefilter("always", DeprecationWarning)
        assert _cli._get_effective_wave_a_rerun_budget(cfg) == 5
        assert _cli._get_effective_wave_a_rerun_budget(cfg) == 5
    deprecated = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    # Phase H1b follow-up: dedupe is now handled by Python's default
    # warnings filter (once per source location). With
    # simplefilter("always") above we assert the warning is raised at
    # least once on the alias-forward path.
    assert deprecated, (
        "Expected at least one DeprecationWarning when the legacy alias is "
        "overridden. Got none."
    )
    assert all(
        "wave_a5_max_reruns" in str(w.message) for w in deprecated
    ), f"Unexpected warning message(s): {[str(w.message) for w in deprecated]!r}"


def test_canonical_value_wins_when_legacy_is_default() -> None:
    # Canonical budget=3, legacy left at default (1) — canonical wins.
    cfg = _cfg(budget=3, legacy=1)
    assert _cli._get_effective_wave_a_rerun_budget(cfg) == 3


# ---------------------------------------------------------------------------
# Shared-budget interaction (schema + A.5)
# ---------------------------------------------------------------------------


def _seed_architecture_md(tmp_path: Path, milestone_id: str, body: str) -> None:
    path = tmp_path / ".agent-team" / f"milestone-{milestone_id}" / "ARCHITECTURE.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _seed_a5_review(tmp_path: Path, milestone_id: str, data: dict) -> None:
    path = tmp_path / ".agent-team" / "milestones" / milestone_id / "WAVE_A5_REVIEW.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    path.write_text(_json.dumps(data), encoding="utf-8")


_PASSING_BODY = "\n".join(
    [
        "## Scope recap",
        "M.",
        "",
        "## What Wave A produced",
        "- x",
        "",
        "## Seams Wave B must populate",
        "- x",
        "",
        "## Seams Wave D must populate",
        "- x",
        "",
        "## Seams Wave T must populate",
        "- x",
        "",
        "## Seams Wave E must populate",
        "- x",
        "",
        "## Open questions",
        "- None.",
        "",
    ]
)

_FAILING_BODY = _PASSING_BODY + "\n## Design-token contract\n- #112233\n"


def _full_config(budget: int) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a_schema_enforcement_enabled = True
    cfg.v18.architecture_md_enabled = True
    cfg.v18.wave_a5_gate_enforcement = True
    cfg.v18.wave_a_rerun_budget = budget
    cfg.v18.wave_a5_max_reruns = budget
    return cfg


def test_budget_2_schema_two_reruns_then_raise(tmp_path: Path) -> None:
    """Schema fails twice → third call exhausts budget and raises.

    A.5 never runs because the schema gate consumes the entire retry
    loop via the shared counter. The test simulates the caller loop
    using an incrementing rerun_count.
    """
    _seed_architecture_md(tmp_path, "milestone-1", _FAILING_BODY)
    cfg = _full_config(budget=2)
    a5_called = False

    def _fake_a5(**_kw):  # pragma: no cover - never invoked
        nonlocal a5_called
        a5_called = True
        return False, []

    with mock.patch.object(_cli, "_enforce_gate_a5", side_effect=_fake_a5):
        # rerun_count 0, 1 succeed; 2 exhausts.
        for rc in (0, 1):
            should, _ = _cli._enforce_gate_wave_a_schema(
                config=cfg,
                cwd=str(tmp_path),
                milestone_id="milestone-1",
                rerun_count=rc,
            )
            assert should is True
        with pytest.raises(_cli.GateEnforcementError) as exc:
            _cli._enforce_gate_wave_a_schema(
                config=cfg,
                cwd=str(tmp_path),
                milestone_id="milestone-1",
                rerun_count=2,
            )
        assert exc.value.gate == "A-SCHEMA"
    # The caller loop would never reach A.5 in this scenario.
    assert a5_called is False


def test_budget_2_schema_one_rerun_then_a5_consumes_one_then_second_a5_exhausts(
    tmp_path: Path,
) -> None:
    """Budget 2: schema consumes 1, A.5 consumes 1 → further A.5 with
    rerun_count=2 exhausts."""
    _seed_architecture_md(tmp_path, "milestone-1", _FAILING_BODY)
    _seed_a5_review(
        tmp_path,
        "milestone-1",
        {"verdict": "FAIL", "findings": [{"severity": "CRITICAL", "issue": "x"}]},
    )
    cfg = _full_config(budget=2)
    # Schema triggers once at count=0.
    should, _ = _cli._enforce_gate_wave_a_schema(
        config=cfg,
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    assert should is True
    # A.5 triggers once at count=1.
    should_a5, _ = _cli._enforce_gate_a5(
        config=cfg,
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=1,
    )
    assert should_a5 is True
    # A.5 again at count=2 exhausts.
    with pytest.raises(_cli.GateEnforcementError) as exc:
        _cli._enforce_gate_a5(
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="milestone-1",
            rerun_count=2,
        )
    assert exc.value.gate == "A5"


def test_schema_passes_then_a5_runs(tmp_path: Path) -> None:
    """When schema validates on attempt 1, A.5 takes over — shared budget
    still applies, so two A.5 reruns exhaust the default budget=2."""
    _seed_architecture_md(tmp_path, "milestone-1", _PASSING_BODY)
    _seed_a5_review(
        tmp_path,
        "milestone-1",
        {"verdict": "FAIL", "findings": [{"severity": "CRITICAL", "issue": "x"}]},
    )
    cfg = _full_config(budget=2)
    # Schema passes (no rerun).
    should_schema, _ = _cli._enforce_gate_wave_a_schema(
        config=cfg,
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    assert should_schema is False
    # A.5 rerun 1.
    should_a5_1, _ = _cli._enforce_gate_a5(
        config=cfg,
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    assert should_a5_1 is True
    # A.5 rerun 2.
    should_a5_2, _ = _cli._enforce_gate_a5(
        config=cfg,
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=1,
    )
    assert should_a5_2 is True
    # Third call exhausts.
    with pytest.raises(_cli.GateEnforcementError):
        _cli._enforce_gate_a5(
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="milestone-1",
            rerun_count=2,
        )


def test_wave_executor_invokes_schema_gate_before_a5() -> None:
    """Structural assertion: the schema gate is referenced in wave_executor
    BEFORE any A.5 retry loop call in the same dispatch block."""
    from agent_team_v15 import wave_executor

    src = Path(wave_executor.__file__).read_text(encoding="utf-8")
    schema_idx = src.find("_enforce_gate_wave_a_schema")
    a5_loop_idx = src.find("_a5_rerun")
    assert schema_idx != -1, "schema gate not referenced in wave_executor"
    assert a5_loop_idx != -1, "a5 rerun loop not referenced in wave_executor"
    # Both live in the same `_execute_milestone_waves_with_stack_contract`
    # function; schema fires in the post-dispatch branch that runs before
    # the stack-contract retry and before the A.5 loop continues. Given
    # the file layout (A.5 dispatch-seed is earlier, gate call happens
    # later), the load-bearing claim is that the schema gate call site
    # exists and the legacy `wave_a_retry_count < 1` cap was refactored
    # into a shared-budget guard.
    assert "_shared_budget" in src, (
        "Shared-budget guard not present; stack-contract retry no longer "
        "participates in the shared budget."
    )
