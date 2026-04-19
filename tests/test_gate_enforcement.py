"""Phase G Slice 4e — GATE 8 / GATE 9 enforcement + ``GateEnforcementError``.

Covers ``cli._enforce_gate_a5`` + ``cli._enforce_gate_t5`` +
``cli.GateEnforcementError``:

- Flag-gated: when ``wave_{a5,t5}_gate_enforcement=False`` the functions
  are no-ops.
- On FAIL verdict + CRITICAL findings, GATE 8 asks orchestrator to re-run
  Wave A up to ``wave_a5_max_reruns`` times, then raises
  ``GateEnforcementError`` to block Wave B.
- On CRITICAL gap in Wave T.5, GATE 9 asks for Wave T iteration 2 once,
  then raises to block Wave E.
- ``GateEnforcementError`` carries ``.gate``, ``.milestone_id`` and
  ``.critical_count`` attributes for caller branching.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig


def _config(
    *,
    a5_enforce: bool = True,
    t5_enforce: bool = True,
    a5_max_reruns: int = 1,
) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a5_gate_enforcement = a5_enforce
    cfg.v18.wave_t5_gate_enforcement = t5_enforce
    cfg.v18.wave_a5_max_reruns = a5_max_reruns
    # Phase H1b: the A.5 gate now resolves its effective rerun budget via
    # the shared ``_get_effective_wave_a_rerun_budget`` resolver, which
    # prefers the canonical ``wave_a_rerun_budget`` unless the legacy
    # alias is overridden to a non-default value. Pin both so the tests
    # that target the A.5 gate exhaustion path continue to express
    # budget-of-N intent unambiguously after h1b.
    cfg.v18.wave_a_rerun_budget = a5_max_reruns
    return cfg


def _seed_a5_review(tmp_path: Path, milestone_id: str, data: dict) -> None:
    target = (
        tmp_path / ".agent-team" / "milestones" / milestone_id / "WAVE_A5_REVIEW.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data), encoding="utf-8")


def _seed_t5_gaps(tmp_path: Path, milestone_id: str, data: dict) -> None:
    target = (
        tmp_path / ".agent-team" / "milestones" / milestone_id / "WAVE_T5_GAPS.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# GATE 8 (Wave A.5 → Wave B)
# ---------------------------------------------------------------------------


def test_gate_8_noop_when_enforcement_disabled(tmp_path: Path) -> None:
    _seed_a5_review(
        tmp_path,
        "M1",
        {"verdict": "FAIL", "findings": [{"severity": "CRITICAL"}]},
    )
    should_rerun, findings = _cli._enforce_gate_a5(
        config=_config(a5_enforce=False),
        cwd=str(tmp_path),
        milestone_id="M1",
        rerun_count=0,
    )
    assert should_rerun is False
    assert findings == []


def test_gate_8_passes_on_pass_verdict(tmp_path: Path) -> None:
    _seed_a5_review(tmp_path, "M1", {"verdict": "PASS", "findings": []})
    should_rerun, findings = _cli._enforce_gate_a5(
        config=_config(),
        cwd=str(tmp_path),
        milestone_id="M1",
        rerun_count=0,
    )
    assert should_rerun is False
    assert findings == []


def test_gate_8_returns_rerun_on_first_critical_fail(tmp_path: Path) -> None:
    _seed_a5_review(
        tmp_path,
        "M1",
        {
            "verdict": "FAIL",
            "findings": [
                {"severity": "CRITICAL", "issue": "missing endpoint"},
            ],
        },
    )
    should_rerun, findings = _cli._enforce_gate_a5(
        config=_config(a5_max_reruns=1),
        cwd=str(tmp_path),
        milestone_id="M1",
        rerun_count=0,
    )
    assert should_rerun is True
    assert len(findings) == 1


def test_gate_8_raises_after_max_reruns(tmp_path: Path) -> None:
    _seed_a5_review(
        tmp_path,
        "M1",
        {
            "verdict": "FAIL",
            "findings": [{"severity": "CRITICAL", "issue": "bad"}],
        },
    )
    with pytest.raises(_cli.GateEnforcementError) as exc:
        _cli._enforce_gate_a5(
            config=_config(a5_max_reruns=1),
            cwd=str(tmp_path),
            milestone_id="M1",
            rerun_count=1,
        )
    err = exc.value
    assert err.gate == "A5"
    assert err.milestone_id == "M1"
    assert err.critical_count == 1
    assert "GATE 8" in str(err)


def test_gate_8_noop_when_findings_artifact_missing(tmp_path: Path) -> None:
    should_rerun, findings = _cli._enforce_gate_a5(
        config=_config(),
        cwd=str(tmp_path),
        milestone_id="M404",
        rerun_count=0,
    )
    assert should_rerun is False
    assert findings == []


# ---------------------------------------------------------------------------
# GATE 9 (Wave T.5 → Wave E)
# ---------------------------------------------------------------------------


def test_gate_9_returns_rerun_on_first_critical_gap(tmp_path: Path) -> None:
    _seed_t5_gaps(
        tmp_path,
        "M1",
        {"gaps": [{"severity": "CRITICAL", "missing_case": "edge"}]},
    )
    should_rerun, gaps = _cli._enforce_gate_t5(
        config=_config(),
        cwd=str(tmp_path),
        milestone_id="M1",
        rerun_count=0,
    )
    assert should_rerun is True
    assert len(gaps) == 1


def test_gate_9_raises_after_first_rerun(tmp_path: Path) -> None:
    _seed_t5_gaps(
        tmp_path,
        "M1",
        {"gaps": [{"severity": "CRITICAL", "missing_case": "x"}]},
    )
    with pytest.raises(_cli.GateEnforcementError) as exc:
        _cli._enforce_gate_t5(
            config=_config(),
            cwd=str(tmp_path),
            milestone_id="M1",
            rerun_count=1,
        )
    err = exc.value
    assert err.gate == "T5"
    assert err.milestone_id == "M1"
    assert err.critical_count == 1
    assert "GATE 9" in str(err)


def test_gate_9_passes_when_no_critical_gaps(tmp_path: Path) -> None:
    _seed_t5_gaps(
        tmp_path,
        "M1",
        {"gaps": [{"severity": "MEDIUM", "missing_case": "x"}]},
    )
    should_rerun, gaps = _cli._enforce_gate_t5(
        config=_config(),
        cwd=str(tmp_path),
        milestone_id="M1",
        rerun_count=0,
    )
    assert should_rerun is False
    assert gaps == []


# ---------------------------------------------------------------------------
# GateEnforcementError is a RuntimeError subclass with context attributes
# ---------------------------------------------------------------------------


def test_gate_enforcement_error_is_runtime_error() -> None:
    err = _cli.GateEnforcementError(
        "boom", gate="A5", milestone_id="M1", critical_count=3
    )
    assert isinstance(err, RuntimeError)
    assert err.gate == "A5"
    assert err.milestone_id == "M1"
    assert err.critical_count == 3
