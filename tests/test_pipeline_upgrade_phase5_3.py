"""Phase 5.3 — STATE.json quality-debt fields (R-#37 + R-#38 data layer).

Locks the five new ``milestone_progress[id]`` keys on
:func:`agent_team_v15.state.update_milestone_progress`:

* ``audit_status`` — ``""`` skip; canonical
  ``"clean" | "degraded" | "failed" | "unknown"``.
* ``unresolved_findings_count`` — ``-1`` skip; positive counts only.
* ``audit_debt_severity`` — ``""`` skip; canonical
  ``"CRITICAL" | "HIGH" | "MEDIUM" | "LOW"``.
* ``audit_findings_path`` — ``""`` skip; absolute path stored verbatim
  (no canonical-path computation in this layer).
* ``audit_fix_rounds`` — ``None`` skip; per-milestone counter (Phase 5.4
  wires the increment in ``_run_audit_fix_unified``).

All five use **sentinel-skip semantics** — mirrors the Phase 1.6
``failure_reason`` pattern at ``state.py``. Callers that don't pass audit
kwargs leave the inner dict byte-identical to the Phase 1.6 / 4.4 / 4.5
``{"status": ...}`` contract; Phase 5.5 readers default missing keys via
``entry.get("audit_status", "unknown")`` etc.

Plan: ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §F.4 ACs
1-5 (one fixture per AC).
"""
from __future__ import annotations

import json
from pathlib import Path

from agent_team_v15.state import (
    RunState,
    load_state,
    save_state,
    update_milestone_progress,
)


# ---- AC1 — round-trip ------------------------------------------------------


def test_ac1_round_trip_writes_loads_all_five_quality_fields(tmp_path: Path) -> None:
    """Write all five quality fields → ``save_state`` → ``load_state`` →
    every field round-trips byte-identical inside
    ``milestone_progress[id]``."""
    agent_team_dir = tmp_path / ".agent-team"
    state = RunState(run_id="ac1", task="ac1")
    findings_path = (
        "/abs/.agent-team/milestones/milestone-1/.agent-team/AUDIT_REPORT.json"
    )
    update_milestone_progress(
        state,
        "milestone-1",
        "DEGRADED",
        audit_status="degraded",
        unresolved_findings_count=28,
        audit_debt_severity="HIGH",
        audit_findings_path=findings_path,
        audit_fix_rounds=2,
    )
    save_state(state, str(agent_team_dir))
    loaded = load_state(str(agent_team_dir))
    assert loaded is not None
    entry = loaded.milestone_progress["milestone-1"]
    assert entry["status"] == "DEGRADED"
    assert entry["audit_status"] == "degraded"
    assert entry["unresolved_findings_count"] == 28
    assert entry["audit_debt_severity"] == "HIGH"
    assert entry["audit_findings_path"] == findings_path
    assert entry["audit_fix_rounds"] == 2


# ---- AC2 — backward-compat (old JSON loads with reader defaults) ----------


def test_ac2_pre_phase_5_3_state_json_loads_with_reader_defaults(tmp_path: Path) -> None:
    """Pre-Phase-5.3 STATE.json (no quality fields anywhere) loads without
    raising. ``entry.get(key, default)`` reader pattern resolves missing
    keys to the documented defaults: ``audit_status`` → ``"unknown"``,
    ``unresolved_findings_count`` → ``-1``, ``audit_debt_severity`` →
    ``""``, ``audit_findings_path`` → ``""``, ``audit_fix_rounds`` →
    ``None``. Phase 5.5's ``forbidden_complete_with_high_debt`` validator
    relies on this contract — it MUST NOT fire on absent keys."""
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir()
    old = {
        "schema_version": 3,
        "run_id": "ac2",
        "task": "ac2",
        "milestone_progress": {
            "milestone-1": {"status": "COMPLETE"},
            "milestone-2": {"status": "FAILED", "failure_reason": "regression"},
        },
        "completed_milestones": ["milestone-1"],
        "failed_milestones": ["milestone-2"],
        "milestone_order": ["milestone-1", "milestone-2"],
    }
    (agent_team_dir / "STATE.json").write_text(
        json.dumps(old), encoding="utf-8"
    )
    loaded = load_state(str(agent_team_dir))
    assert loaded is not None

    m1 = loaded.milestone_progress["milestone-1"]
    assert m1["status"] == "COMPLETE"
    # Reader-default contract — Phase 5.5 must use these defaults:
    assert m1.get("audit_status", "unknown") == "unknown"
    assert m1.get("unresolved_findings_count", -1) == -1
    assert m1.get("audit_debt_severity", "") == ""
    assert m1.get("audit_findings_path", "") == ""
    assert m1.get("audit_fix_rounds", None) is None
    # No Phase 5.3 keys leaked into the loaded dict:
    for key in (
        "audit_status",
        "unresolved_findings_count",
        "audit_debt_severity",
        "audit_findings_path",
        "audit_fix_rounds",
    ):
        assert key not in m1

    # Phase 1.6 ``failure_reason`` semantics still hold alongside Phase 5.3:
    m2 = loaded.milestone_progress["milestone-2"]
    assert m2["status"] == "FAILED"
    assert m2["failure_reason"] == "regression"


# ---- AC3 — update flow (all 5 kwargs persist to disk) ---------------------


def test_ac3_update_flow_all_five_kwargs_land_on_state_json(tmp_path: Path) -> None:
    """``update_milestone_progress(state, id, status, ... all 5 audit kwargs)``
    → STATE.json on disk JSON-parses to a dict with exactly the 6 expected
    keys (status + 5 quality fields) under ``milestone_progress[id]``."""
    agent_team_dir = tmp_path / ".agent-team"
    state = RunState(run_id="ac3", task="ac3")
    findings_path = (
        "/abs/.agent-team/milestones/milestone-1/.agent-team/AUDIT_REPORT.json"
    )
    update_milestone_progress(
        state,
        "milestone-1",
        "DEGRADED",
        audit_status="degraded",
        unresolved_findings_count=28,
        audit_debt_severity="HIGH",
        audit_findings_path=findings_path,
        audit_fix_rounds=2,
    )
    save_state(state, str(agent_team_dir))
    raw = json.loads(
        (agent_team_dir / "STATE.json").read_text(encoding="utf-8")
    )
    entry = raw["milestone_progress"]["milestone-1"]
    assert entry == {
        "status": "DEGRADED",
        "audit_status": "degraded",
        "unresolved_findings_count": 28,
        "audit_debt_severity": "HIGH",
        "audit_findings_path": findings_path,
        "audit_fix_rounds": 2,
    }


# ---- AC4 — default-preservation (no kwargs → no quality keys) -------------


def test_ac4_no_quality_kwargs_leaves_inner_dict_byte_identical(tmp_path: Path) -> None:
    """``update_milestone_progress(state, "m2", "COMPLETE")`` with no
    quality kwargs → ``state.milestone_progress["m2"] == {"status":
    "COMPLETE"}``. The five quality keys are ABSENT (NOT erased to None /
    "" / -1), preserving the Phase 1.6 byte-shape that downstream
    fixtures assert via strict ``==`` equality."""
    state = RunState(run_id="ac4", task="ac4")
    update_milestone_progress(state, "milestone-2", "COMPLETE")
    assert state.milestone_progress["milestone-2"] == {"status": "COMPLETE"}
    for key in (
        "audit_status",
        "unresolved_findings_count",
        "audit_debt_severity",
        "audit_findings_path",
        "audit_fix_rounds",
    ):
        assert key not in state.milestone_progress["milestone-2"]


# ---- AC5 — Phase 1.6 / 4.4 / 4.5 fixture parity ---------------------------


def test_ac5_phase_1_6_fixture_byte_shape_and_partial_supply_boundary() -> None:
    """Phase 1.6 fixtures at ``tests/test_audit_fix_guardrails_phase1_6.py``
    lines 77, 92, 211 use strict dict equality on
    ``state.milestone_progress[id]``. Phase 5.3's sentinel-skip semantics
    must preserve byte-identical shapes for those calls AND must skip the
    correct subset on partial-supply (some kwargs supplied, others left
    at sentinel) so future drift to always-write surfaces immediately."""
    state = RunState(run_id="ac5", task="ac5")

    # Phase 1.6 line 77 byte-shape — FAILED with no kwargs.
    update_milestone_progress(state, "milestone-1", "FAILED")
    assert state.milestone_progress["milestone-1"] == {"status": "FAILED"}

    # Phase 1.6 line 92 byte-shape — REPLACE auto-clears stale fields.
    update_milestone_progress(state, "milestone-1", "COMPLETE")
    assert state.milestone_progress["milestone-1"] == {"status": "COMPLETE"}

    # Phase 1.6 line 211 byte-shape — PENDING transition.
    update_milestone_progress(state, "milestone-1", "PENDING")
    assert state.milestone_progress["milestone-1"] == {"status": "PENDING"}

    # Phase 1.6 ``failure_reason`` byte-shape preserved alongside Phase 5.3:
    update_milestone_progress(
        state, "milestone-1", "FAILED", failure_reason="regression"
    )
    assert state.milestone_progress["milestone-1"] == {
        "status": "FAILED",
        "failure_reason": "regression",
    }

    # Partial-supply boundary — only some quality kwargs at non-sentinel:
    # ``audit_status`` supplied; ``unresolved_findings_count=0`` (0 ≠ -1
    # sentinel → written); the two omitted strings stay at sentinel and
    # must NOT appear; ``audit_fix_rounds=0`` (0 ≠ None → written).
    update_milestone_progress(
        state,
        "milestone-1",
        "DEGRADED",
        audit_status="degraded",
        unresolved_findings_count=0,
        audit_fix_rounds=0,
    )
    assert state.milestone_progress["milestone-1"] == {
        "status": "DEGRADED",
        "audit_status": "degraded",
        "unresolved_findings_count": 0,
        "audit_fix_rounds": 0,
    }
    # Explicit-absence assertion — locks the sentinel-skip contract for
    # the two unsupplied string fields.
    assert "audit_debt_severity" not in state.milestone_progress["milestone-1"]
    assert "audit_findings_path" not in state.milestone_progress["milestone-1"]
