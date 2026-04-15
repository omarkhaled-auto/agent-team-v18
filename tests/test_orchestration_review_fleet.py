"""Tests for D-04 — review-fleet deployment invariant.

Covers the top-level ``_enforce_review_fleet_invariant`` helper in
``agent_team_v15.cli`` which fires after the GATE 5 recovery path has
had a chance to run. When ``config.v18.review_fleet_enforcement`` is
``True`` (default), the invariant raises ``ReviewFleetNotDeployedError``
so the pipeline halts instead of completing with a known bad state.
When the flag is ``False``, the pre-fix warn-only behaviour is
preserved.

No SDK, subprocess, or network calls — pure function tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeReport:
    """Minimal stand-in for ``ConvergenceReport``; only the fields read by
    the invariant are populated."""

    review_cycles: int = 0
    total_requirements: int = 0
    checked_requirements: int = 0


def _config(flag: bool = True) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.review_fleet_enforcement = flag
    return cfg


# ---------------------------------------------------------------------------
# Invariant behaviour — flag ON (default)
# ---------------------------------------------------------------------------


def test_invariant_raises_on_zero_cycle_with_requirements_flag_on() -> None:
    """Fresh orchestration ended with 8 requirements, 0 review cycles.

    Asserts ``ReviewFleetNotDeployedError`` is raised — the post-recovery
    pipeline must not silently proceed in this state.
    """
    report = _FakeReport(review_cycles=0, total_requirements=8, checked_requirements=0)
    with pytest.raises(_cli.ReviewFleetNotDeployedError) as excinfo:
        _cli._enforce_review_fleet_invariant(report, _config(True))
    # Error message must surface the counts so operators can triage.
    message = str(excinfo.value)
    assert "0/8" in message
    assert "0 review cycles" in message


def test_invariant_silent_when_review_cycles_deployed_flag_on() -> None:
    """Review fleet was deployed → invariant is a no-op (flag on)."""
    report = _FakeReport(review_cycles=1, total_requirements=8, checked_requirements=8)
    # Must not raise and must not call the warn fallback.
    warned: list[str] = []
    _cli._enforce_review_fleet_invariant(
        report, _config(True), warn=warned.append
    )
    assert warned == []


def test_invariant_silent_when_no_requirements_flag_on() -> None:
    """No requirements at all → invariant is a no-op regardless of cycles."""
    report = _FakeReport(review_cycles=0, total_requirements=0, checked_requirements=0)
    _cli._enforce_review_fleet_invariant(report, _config(True))


def test_invariant_silent_when_report_is_none() -> None:
    """Missing report (e.g. non-milestone mode, no convergence check) → no-op."""
    _cli._enforce_review_fleet_invariant(None, _config(True))


# ---------------------------------------------------------------------------
# Invariant behaviour — flag OFF (legacy warn-only)
# ---------------------------------------------------------------------------


def test_invariant_flag_off_warns_but_does_not_raise() -> None:
    """With ``review_fleet_enforcement=False`` the pipeline continues with
    a warning — preserves pre-fix behaviour for rollback safety."""
    report = _FakeReport(review_cycles=0, total_requirements=8, checked_requirements=0)
    warnings: list[str] = []
    _cli._enforce_review_fleet_invariant(
        report, _config(False), warn=warnings.append
    )
    assert len(warnings) == 1
    assert "REVIEW FLEET INVARIANT" in warnings[0]
    assert "flag off" in warnings[0]
    # Counts also surfaced for diagnosability.
    assert "0/8" in warnings[0]


def test_invariant_flag_off_silent_when_invariant_satisfied() -> None:
    """Flag off + healthy state → no warning."""
    report = _FakeReport(review_cycles=2, total_requirements=8, checked_requirements=7)
    warnings: list[str] = []
    _cli._enforce_review_fleet_invariant(
        report, _config(False), warn=warnings.append
    )
    assert warnings == []
