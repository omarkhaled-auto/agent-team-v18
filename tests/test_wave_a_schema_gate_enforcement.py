"""Phase H1b — ``cli._enforce_gate_wave_a_schema`` integration tests.

Mirrors the structure of :mod:`tests.test_gate_enforcement` for A.5 so the
schema gate and A.5 gate are proven to share a signature shape. Covers:

* ``(False, {})`` no-op when enforcement flag is OFF.
* ``(True, review)`` on first schema failure, within budget.
* ``GateEnforcementError(gate='A-SCHEMA')`` on budget exhaustion.
* ``architecture_md_enabled=False`` silently skips (logs once per
  milestone).
* ``WAVE_A_SCHEMA_REVIEW.json`` persisted under
  ``.agent-team/milestones/{id}/`` — sibling to ``WAVE_A5_REVIEW.json``.
* NO ``WAVE_A_VALIDATION_HISTORY.json`` file is created anywhere.
* ``_WAVE_A_SCHEMA_SKIP_LOGGED`` / ``_WAVE_A_SCHEMA_ALIAS_WARNED``
  module sets are reset between tests via fixture so tests do not bleed
  state.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_schema_dedupe_state() -> None:
    """No-op stub.

    Phase H1b follow-up removed the module-level dedupe sets in favor of
    ``warnings.warn(DeprecationWarning, ...)`` for the alias-deprecation
    path and unconditional INFO logging for the skip path. Python's
    warnings filter dedupes by default; there is nothing to reset.
    """
    yield


def _config(
    *,
    schema_enforce: bool = True,
    architecture_md: bool = True,
    budget: int = 2,
    legacy_budget: int | None = None,
) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a_schema_enforcement_enabled = schema_enforce
    cfg.v18.architecture_md_enabled = architecture_md
    cfg.v18.wave_a_rerun_budget = budget
    if legacy_budget is not None:
        cfg.v18.wave_a5_max_reruns = legacy_budget
    return cfg


def _seed_architecture_md(
    tmp_path: Path, milestone_id: str, body: str
) -> Path:
    path = (
        tmp_path
        / ".agent-team"
        / f"milestone-{milestone_id}"
        / "ARCHITECTURE.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


_PASSING_BODY = "\n".join(
    [
        "## Scope recap",
        "Milestone milestone-1.",
        "",
        "## What Wave A produced",
        "- schema.prisma",
        "",
        "## Seams Wave B must populate",
        "- main.ts",
        "",
        "## Seams Wave D must populate",
        "- layout.tsx",
        "",
        "## Seams Wave T must populate",
        "- jest",
        "",
        "## Seams Wave E must populate",
        "- lint",
        "",
        "## Open questions",
        "- None.",
        "",
    ]
)


_FAILING_BODY = _PASSING_BODY + "\n## Design-token contract\n- #112233\n"


# ---------------------------------------------------------------------------
# Signature mirror with _enforce_gate_a5
# ---------------------------------------------------------------------------


def test_schema_gate_signature_mirrors_a5() -> None:
    """Structural anti-pattern check: gate signatures must match."""
    a5_sig = inspect.signature(_cli._enforce_gate_a5)
    schema_sig = inspect.signature(_cli._enforce_gate_wave_a_schema)
    # Same parameter names.
    assert list(a5_sig.parameters.keys()) == list(schema_sig.parameters.keys())
    # Return-type annotation is a tuple[bool, ...] in both cases.
    assert a5_sig.return_annotation is not inspect.Signature.empty
    assert schema_sig.return_annotation is not inspect.Signature.empty


# ---------------------------------------------------------------------------
# Flag gating
# ---------------------------------------------------------------------------


def test_noop_when_schema_enforcement_disabled(tmp_path: Path) -> None:
    _seed_architecture_md(tmp_path, "milestone-1", _FAILING_BODY)
    should_rerun, review = _cli._enforce_gate_wave_a_schema(
        config=_config(schema_enforce=False),
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    assert should_rerun is False
    assert review == {}


def test_noop_when_architecture_md_disabled_and_logs_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="agent_team_v15.cli")
    _seed_architecture_md(tmp_path, "milestone-1", _FAILING_BODY)
    cfg = _config(architecture_md=False)
    # Reset the function-attribute dedupe set so this test sees a
    # clean slate regardless of other tests' state.
    if hasattr(_cli._enforce_gate_wave_a_schema, "_skip_logged_keys"):
        _cli._enforce_gate_wave_a_schema._skip_logged_keys.clear()
    for _ in range(3):
        should_rerun, review = _cli._enforce_gate_wave_a_schema(
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="milestone-1",
            rerun_count=0,
        )
        assert should_rerun is False
        assert review == {}
    # Phase H1b plan: the skip-path INFO is deduped to once per
    # milestone. Dedupe state lives as a function attribute (scoped,
    # not a module-level `_VAR` global). Assert exactly one skip log
    # for milestone-1 across three invocations.
    skip_messages = [
        r for r in caplog.records
        if "enforcement skipped" in r.getMessage()
        and "milestone-1" in r.getMessage()
    ]
    assert len(skip_messages) == 1, (
        "Expected exactly one 'enforcement skipped' INFO log for "
        f"milestone-1 across 3 gate invocations; got {len(skip_messages)}. "
        f"Captured: {[r.getMessage() for r in caplog.records]!r}"
    )


# ---------------------------------------------------------------------------
# Pass path
# ---------------------------------------------------------------------------


def test_pass_when_body_matches_schema(tmp_path: Path) -> None:
    _seed_architecture_md(tmp_path, "milestone-1", _PASSING_BODY)
    should_rerun, review = _cli._enforce_gate_wave_a_schema(
        config=_config(),
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    assert should_rerun is False
    # Review dict is empty on pass per the Wave 2A contract.
    assert review == {}


def test_pass_when_architecture_md_missing_returns_empty(tmp_path: Path) -> None:
    should_rerun, review = _cli._enforce_gate_wave_a_schema(
        config=_config(),
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    # Missing file → validator returns "skipped" → no findings → pass.
    assert should_rerun is False
    assert review == {}


# ---------------------------------------------------------------------------
# Fail path — within budget
# ---------------------------------------------------------------------------


def test_fail_within_budget_returns_true_and_review(tmp_path: Path) -> None:
    _seed_architecture_md(tmp_path, "milestone-1", _FAILING_BODY)
    should_rerun, review = _cli._enforce_gate_wave_a_schema(
        config=_config(budget=2),
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    assert should_rerun is True
    assert isinstance(review, dict)
    assert review["verdict"] == "FAIL"
    assert any(
        f.get("category") == "schema_rejection"
        for f in review.get("findings", [])
        if isinstance(f, dict)
    )


def test_review_json_persisted_to_milestones_dir(tmp_path: Path) -> None:
    _seed_architecture_md(tmp_path, "milestone-1", _FAILING_BODY)
    _cli._enforce_gate_wave_a_schema(
        config=_config(),
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    review_path = (
        tmp_path
        / ".agent-team"
        / "milestones"
        / "milestone-1"
        / "WAVE_A_SCHEMA_REVIEW.json"
    )
    assert review_path.is_file(), f"Expected {review_path} to be persisted"
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "FAIL"
    assert payload["findings"]


def test_no_validation_history_json_ever_created(tmp_path: Path) -> None:
    """Structural anti-pattern check: the plan forbids a
    ``WAVE_A_VALIDATION_HISTORY.json`` side file (Wave 2A anti-pattern #2).
    Drive the gate multiple rerun cycles and then scan the fixture
    directory."""
    _seed_architecture_md(tmp_path, "milestone-1", _FAILING_BODY)
    cfg = _config(budget=3)
    for rc in range(3):
        should_rerun, _ = _cli._enforce_gate_wave_a_schema(
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="milestone-1",
            rerun_count=rc,
        )
        assert should_rerun is True
    # Scan the whole tmp tree — no VALIDATION_HISTORY file must exist.
    for path in tmp_path.rglob("*"):
        assert path.name != "WAVE_A_VALIDATION_HISTORY.json", (
            f"Forbidden artifact found: {path}"
        )


# ---------------------------------------------------------------------------
# Fail path — budget exhausted
# ---------------------------------------------------------------------------


def test_raises_gate_enforcement_error_on_exhausted_budget(
    tmp_path: Path,
) -> None:
    _seed_architecture_md(tmp_path, "milestone-1", _FAILING_BODY)
    cfg = _config(budget=2)
    with pytest.raises(_cli.GateEnforcementError) as exc:
        _cli._enforce_gate_wave_a_schema(
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="milestone-1",
            rerun_count=2,
        )
    err = exc.value
    assert err.gate == "A-SCHEMA"
    assert err.milestone_id == "milestone-1"
    assert err.critical_count >= 1
    assert "A-SCHEMA" in str(err)


def test_budget_one_exhausted_on_second_rerun(tmp_path: Path) -> None:
    _seed_architecture_md(tmp_path, "milestone-1", _FAILING_BODY)
    cfg = _config(budget=1)
    # First rerun (count=0 < budget=1) should succeed.
    should_rerun, _ = _cli._enforce_gate_wave_a_schema(
        config=cfg,
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    assert should_rerun is True
    # Second call (count=1 >= budget=1) exhausts.
    with pytest.raises(_cli.GateEnforcementError):
        _cli._enforce_gate_wave_a_schema(
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="milestone-1",
            rerun_count=1,
        )


# ---------------------------------------------------------------------------
# Structural assertions
# ---------------------------------------------------------------------------


def test_schema_gate_uses_shared_rejection_channel_not_new_kwarg() -> None:
    """Anti-pattern #3: schema feedback must flow through
    ``stack_contract_rejection_context`` — not a new ``schema_rejection_context``
    parameter on ``build_wave_a_prompt``."""
    from agent_team_v15 import agents

    sig = inspect.signature(agents.build_wave_a_prompt)
    params = set(sig.parameters.keys())
    assert "stack_contract_rejection_context" in params
    # Forbidden: a parallel "schema_rejection_context" kwarg would double
    # the rejection channel.
    assert "schema_rejection_context" not in params
