"""Phase 5.5 §M.M2 — State-invariant validator (two layers) lint + per-rule fixtures.

Locks the contract that future Phase 6+ rule additions extend
``state_invariants.KNOWN_RULES`` and ship at least one passing + one
failing fixture per rule. Layer-1 returns a list (never raises) so
``save_state`` can log and continue; layer-2 raises by default with
``warn_only`` mode for migration commands.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.state_invariants import (
    KNOWN_RULES,
    StateInvariantViolation,
    validate_state_shape_invariants,
    validate_terminal_quality_invariants,
)


def _state(progress):
    """Synthesize a duck-typed RunState for the validators."""
    return SimpleNamespace(milestone_progress=progress)


# ---------------------------------------------------------------------------
# Lint — KNOWN_RULES contains exactly the three rules Phase 5.5 ships.
# ---------------------------------------------------------------------------


def test_known_rules_locked_at_phase_5_5():
    """KNOWN_RULES is the lint anchor for Phase 6+ extensions.

    Future rules must extend this tuple AND ship fixtures; this test
    fails when a rule is added without a corresponding fixture.
    """

    assert KNOWN_RULES == (
        "forbidden_complete_with_high_debt",
        "forbidden_failed_without_failure_reason",
        "forbidden_anchor_without_quality_sidecar",
    )


# ---------------------------------------------------------------------------
# Rule 1 — forbidden_complete_with_high_debt.
# ---------------------------------------------------------------------------


def test_rule1_passes_on_clean_complete():
    state = _state({"m1": {"status": "COMPLETE"}})
    assert validate_state_shape_invariants(state) == []


def test_rule1_passes_on_complete_with_low_severity_debt():
    state = _state({"m1": {
        "status": "COMPLETE",
        "unresolved_findings_count": 5,
        "audit_debt_severity": "MEDIUM",
    }})
    assert validate_state_shape_invariants(state) == []


def test_rule1_fires_on_complete_with_high_debt():
    state = _state({"m1": {
        "status": "COMPLETE",
        "unresolved_findings_count": 3,
        "audit_debt_severity": "HIGH",
    }})
    violations = validate_state_shape_invariants(state)
    assert len(violations) == 1
    assert "forbidden_complete_with_high_debt" in violations[0]


def test_rule1_fires_on_complete_with_critical_debt():
    state = _state({"m1": {
        "status": "COMPLETE",
        "unresolved_findings_count": 1,
        "audit_debt_severity": "CRITICAL",
    }})
    assert any("CRITICAL" in v for v in validate_state_shape_invariants(state))


def test_rule1_sentinel_aware_missing_keys():
    """Phase 5.3 AC2 contract — missing audit_* keys do NOT trip rule 1."""
    state = _state({"m1": {"status": "COMPLETE"}})
    assert validate_state_shape_invariants(state) == []


def test_rule1_sentinel_aware_minus_one_count():
    """unresolved_findings_count == -1 is the skip sentinel."""
    state = _state({"m1": {
        "status": "COMPLETE",
        "unresolved_findings_count": -1,
        "audit_debt_severity": "HIGH",
    }})
    assert validate_state_shape_invariants(state) == []


def test_rule1_sentinel_aware_empty_severity():
    """audit_debt_severity == '' is the skip sentinel."""
    state = _state({"m1": {
        "status": "COMPLETE",
        "unresolved_findings_count": 5,
        "audit_debt_severity": "",
    }})
    assert validate_state_shape_invariants(state) == []


# ---------------------------------------------------------------------------
# Rule 3 — forbidden_failed_without_failure_reason. LAYER 2 ONLY.
# ---------------------------------------------------------------------------


def test_rule3_layer1_does_not_fire_on_reason_less_failed(tmp_path: Path):
    """Hard-execution FAILED sites at cli.py:5050/5471/etc. don't pass
    failure_reason today. Layer 1 MUST NOT fire — would brick existing
    code. Layer 2 fires only at quality-dependent boundaries.
    """
    state = _state({"m1": {"status": "FAILED"}})
    # Layer 1 should NOT include rule 3 violations.
    layer1 = validate_state_shape_invariants(state)
    assert all("forbidden_failed_without_failure_reason" not in v for v in layer1)


def test_rule3_layer2_fires_on_reason_less_failed(tmp_path: Path):
    state = _state({"m1": {"status": "FAILED"}})
    with pytest.raises(StateInvariantViolation) as excinfo:
        validate_terminal_quality_invariants(
            state, cwd=tmp_path, milestone_id="m1",
        )
    assert "forbidden_failed_without_failure_reason" in str(excinfo.value)


def test_rule3_layer2_passes_on_failed_with_reason(tmp_path: Path):
    state = _state({"m1": {"status": "FAILED", "failure_reason": "regression"}})
    # Should not raise.
    validate_terminal_quality_invariants(
        state, cwd=tmp_path, milestone_id="m1",
    )


# ---------------------------------------------------------------------------
# Rule 2 — forbidden_anchor_without_quality_sidecar. LAYER 2 ONLY.
# ---------------------------------------------------------------------------


def test_rule2_passes_when_no_anchor_on_disk(tmp_path: Path):
    """No anchor → no rule violation."""
    state = _state({"m1": {"status": "COMPLETE"}})
    validate_terminal_quality_invariants(
        state, cwd=tmp_path, milestone_id="m1",
    )


def test_rule2_passes_when_anchor_has_sidecar(tmp_path: Path):
    anchor = tmp_path / ".agent-team" / "milestones" / "m1" / "_anchor" / "_complete"
    anchor.mkdir(parents=True)
    (anchor / "_quality.json").write_text('{"quality":"clean"}', encoding="utf-8")
    state = _state({"m1": {"status": "COMPLETE"}})
    validate_terminal_quality_invariants(
        state, cwd=tmp_path, milestone_id="m1",
    )


def test_rule2_fires_when_anchor_missing_sidecar(tmp_path: Path):
    anchor = tmp_path / ".agent-team" / "milestones" / "m1" / "_anchor" / "_complete"
    anchor.mkdir(parents=True)
    # No _quality.json written.
    state = _state({"m1": {"status": "COMPLETE"}})
    with pytest.raises(StateInvariantViolation) as excinfo:
        validate_terminal_quality_invariants(
            state, cwd=tmp_path, milestone_id="m1",
        )
    assert "forbidden_anchor_without_quality_sidecar" in str(excinfo.value)


# ---------------------------------------------------------------------------
# warn_only mode — migration commands surface violations without raising.
# ---------------------------------------------------------------------------


def test_warn_only_mode_returns_violations_without_raising(tmp_path: Path):
    state = _state({
        "m1": {"status": "FAILED"},  # rule 3 fires
        "m2": {
            "status": "COMPLETE",
            "unresolved_findings_count": 2,
            "audit_debt_severity": "HIGH",
        },  # rule 1 fires
    })
    violations = validate_terminal_quality_invariants(
        state, cwd=tmp_path, milestone_id="m1", warn_only=True,
    )
    assert len(violations) >= 2
    # Both rule 1 and rule 3 surface in the same call.
    assert any("forbidden_failed_without_failure_reason" in v for v in violations)
    assert any("forbidden_complete_with_high_debt" in v for v in violations)


# ---------------------------------------------------------------------------
# Backward-compat smoke: Phase 1.6 / 4.4 / 4.5 byte-shape stays clean.
# ---------------------------------------------------------------------------


def test_layer1_clean_on_phase_1_6_byte_shape():
    """Phase 1.6: status=FAILED with reason; Phase 5.5 layer-1 passes
    (rule 3 is layer-2-only)."""
    state = _state({"m1": {"status": "FAILED", "failure_reason": "regression"}})
    assert validate_state_shape_invariants(state) == []


def test_layer1_clean_on_phase_4_5_cascade_complete_byte_shape():
    """Phase 4.5 cascade-COMPLETE writes status=COMPLETE with
    failure_reason='wave_fail_recovered'. Phase 5.5 layer-1 passes
    (no quality fields populated → sentinel; rule 1 does not fire)."""
    state = _state({"m1": {
        "status": "COMPLETE",
        "failure_reason": "wave_fail_recovered",
    }})
    assert validate_state_shape_invariants(state) == []


def test_layer1_clean_on_phase_5_3_byte_shape():
    """Phase 5.3 byte-shape with all sentinels populated correctly."""
    state = _state({"m1": {
        "status": "COMPLETE",
        "audit_status": "clean",
        # unresolved_findings_count absent → sentinel
        # audit_debt_severity absent → sentinel
    }})
    assert validate_state_shape_invariants(state) == []
