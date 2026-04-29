"""Phase 5.5 acceptance tests — Quality Contract + single-resolver helper + sidecar.

AC1–AC7 per plan §H.4. AC7 (live M1+M2 smoke) is deferred to the
closeout-smoke checklist per user direction; the source-level contracts
(_anchor/_complete/_quality.json shape, FAILED non-capture, no _anchor/_degraded
slot, Quality Summary print, deprecation notice) are locked at the
unit-fixture / replay-fixture level here.

Plus:
* Cascade-gate absorption byte-identity for the 2026-04-28 canonical
  smoke shape (5 CRITICAL + 8 HIGH FAIL → FAILED with
  audit_fix_recovered_build_but_findings_remain).
* 6526 quality-validators FAILED stays direct (preserves Phase 5.4
  audit_fix_rounds threading verbatim; documented deviation from §M.M1).
* 8503 helper FAILED-floor (anchor-restore failure paths cannot
  accidentally route to DEGRADED on low/medium-only findings).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.audit_models import AuditFinding, AuditReport, AuditScore
from agent_team_v15.quality_contract import (
    _evaluate_quality_contract,
    _finalize_milestone_with_quality_contract,
    _max_severity,
    render_quality_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_state(milestone_id: str = "m1", *, executed_waves=None, existing_rounds: int = 0):
    """Synthesize a real RunState for the resolver (save_state path requires it)."""
    from agent_team_v15.state import RunState
    progress = {milestone_id: {}}
    if existing_rounds > 0:
        progress[milestone_id]["audit_fix_rounds"] = existing_rounds
    state = RunState(
        run_id="test-run",
        task="test-task",
        depth="standard",
        milestone_progress=progress,
    )
    state.executed_waves = list(executed_waves or [])
    return state


def _make_config(*, legacy_permissive_audit: bool = False):
    return SimpleNamespace(
        v18=SimpleNamespace(legacy_permissive_audit=legacy_permissive_audit),
    )


def _make_finding(severity: str = "HIGH", verdict: str = "FAIL", owner_wave: str = "wave-agnostic"):
    return AuditFinding(
        finding_id=f"F-{severity}-{verdict}",
        auditor="scorer",
        requirement_id="REQ-1",
        verdict=verdict,
        severity=severity,
        summary=f"{severity} {verdict} finding",
        evidence=[],
        remediation="",
        confidence=1.0,
        source="llm",
        owner_wave=owner_wave,
    )


def _make_report(findings: list, *, critical: int = 0, high: int = 0, medium: int = 0, low: int = 0):
    score = AuditScore(
        total_items=max(len(findings), 1),
        passed=0 if findings else 1,
        failed=len(findings),
        partial=0,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
        info_count=0,
        score=80.0,
        health="failed" if (critical or high) else ("degraded" if findings else "healthy"),
        max_score=100,
    )
    return AuditReport(
        audit_id="test",
        timestamp="2026-04-29T00:00:00Z",
        cycle=1,
        auditors_deployed=["scorer"],
        findings=findings,
        score=score,
    )


# ---------------------------------------------------------------------------
# AC1 — synthetic milestone with no findings → COMPLETE/clean.
# ---------------------------------------------------------------------------


def test_ac1_no_findings_routes_to_complete_clean():
    state = _make_run_state()
    report = _make_report([])
    final, audit_status, count, severity = _evaluate_quality_contract(
        report, state, _make_config(),
    )
    assert (final, audit_status, count, severity) == ("COMPLETE", "clean", 0, "")


# ---------------------------------------------------------------------------
# AC2 — synthetic milestone with only LOW/MEDIUM unresolved → DEGRADED.
# ---------------------------------------------------------------------------


def test_ac2_low_medium_only_routes_to_degraded():
    state = _make_run_state()
    findings = [_make_finding("MEDIUM"), _make_finding("LOW"), _make_finding("MEDIUM")]
    report = _make_report(findings, medium=2, low=1)
    final, audit_status, count, severity = _evaluate_quality_contract(
        report, state, _make_config(),
    )
    assert final == "DEGRADED"
    assert audit_status == "degraded"
    assert count == 3
    assert severity == "MEDIUM"


# ---------------------------------------------------------------------------
# AC3 — synthetic milestone with HIGH unresolved (no flag) → FAILED.
# ---------------------------------------------------------------------------


def test_ac3_high_findings_route_to_failed_strict_default():
    state = _make_run_state()
    findings = [_make_finding("HIGH"), _make_finding("HIGH"), _make_finding("HIGH")]
    report = _make_report(findings, high=3)
    final, audit_status, count, severity = _evaluate_quality_contract(
        report, state, _make_config(legacy_permissive_audit=False),
    )
    assert final == "FAILED"
    assert audit_status == "failed"
    assert severity == "HIGH"


def test_ac3_critical_findings_route_to_failed_strict_default():
    state = _make_run_state()
    findings = [_make_finding("CRITICAL")]
    report = _make_report(findings, critical=1)
    final, _, _, severity = _evaluate_quality_contract(
        report, state, _make_config(legacy_permissive_audit=False),
    )
    assert final == "FAILED"
    assert severity == "CRITICAL"


# ---------------------------------------------------------------------------
# AC4 — --legacy-permissive-audit downgrades HIGH/CRITICAL → DEGRADED.
# ---------------------------------------------------------------------------


def test_ac4_legacy_permissive_audit_downgrades_high_to_degraded():
    state = _make_run_state()
    findings = [_make_finding("HIGH"), _make_finding("HIGH")]
    report = _make_report(findings, high=2)
    final, audit_status, count, severity = _evaluate_quality_contract(
        report, state, _make_config(legacy_permissive_audit=True),
    )
    assert final == "DEGRADED"
    assert audit_status == "degraded"
    assert severity == "HIGH"


def test_ac4_legacy_permissive_audit_downgrades_critical_to_degraded():
    state = _make_run_state()
    findings = [_make_finding("CRITICAL")]
    report = _make_report(findings, critical=1)
    final, _, _, severity = _evaluate_quality_contract(
        report, state, _make_config(legacy_permissive_audit=True),
    )
    assert final == "DEGRADED"
    assert severity == "CRITICAL"


# ---------------------------------------------------------------------------
# AC5 — All DEFERRED findings (Wave D didn't execute) → COMPLETE/clean.
# ---------------------------------------------------------------------------


def test_ac5_deferred_findings_route_to_complete_clean():
    state = _make_run_state(executed_waves=["A", "B"])  # Wave D not executed
    findings = [
        _make_finding("HIGH", owner_wave="D"),  # DEFERRED
        _make_finding("HIGH", owner_wave="D"),  # DEFERRED
    ]
    report = _make_report(findings, high=2)
    final, audit_status, count, _ = _evaluate_quality_contract(
        report, state, _make_config(),
    )
    assert final == "COMPLETE"
    assert audit_status == "clean"
    assert count == 0


# ---------------------------------------------------------------------------
# AC6 — Quality Summary print rendering.
# ---------------------------------------------------------------------------


def test_ac6_quality_summary_clean_renders_one_line():
    out = render_quality_summary(
        "m1", "COMPLETE", "clean", 0, "", _make_report([]), "/some/path",
    )
    assert "[QUALITY]" in out
    assert "clean" in out
    # One-line summary for clean.
    assert "\n" not in out


def test_ac6_quality_summary_degraded_renders_box():
    findings = [_make_finding("MEDIUM"), _make_finding("LOW"), _make_finding("MEDIUM")]
    report = _make_report(findings, medium=2, low=1)
    out = render_quality_summary(
        "m1", "DEGRADED", "degraded", 3, "MEDIUM", report,
        "/run/.agent-team/milestones/m1/.agent-team/AUDIT_REPORT.json",
    )
    assert "Milestone Quality Summary" in out
    assert "m1: DEGRADED" in out
    assert "3 unresolved" in out
    assert "MEDIUM" in out
    assert "/run/.agent-team/milestones/m1" in out


# ---------------------------------------------------------------------------
# Resolver finalize + state writes.
# ---------------------------------------------------------------------------


def test_resolver_finalize_writes_phase_5_3_quality_fields():
    state = _make_run_state()
    findings = [_make_finding("MEDIUM"), _make_finding("LOW")]
    report = _make_report(findings, medium=1, low=1)
    _finalize_milestone_with_quality_contract(
        state, "m1", report, _make_config(),
    )
    entry = state.milestone_progress["m1"]
    assert entry["status"] == "DEGRADED"
    assert entry["audit_status"] == "degraded"
    assert entry["unresolved_findings_count"] == 2
    assert entry["audit_debt_severity"] == "MEDIUM"


def test_resolver_finalize_preserves_audit_fix_rounds():
    """REPLACE-preserve contract: existing audit_fix_rounds threads through."""
    state = _make_run_state(existing_rounds=2)
    state.milestone_progress["m1"]["status"] = "FAILED"  # in-flight
    report = _make_report([])
    _finalize_milestone_with_quality_contract(
        state, "m1", report, _make_config(),
    )
    entry = state.milestone_progress["m1"]
    assert entry["status"] == "COMPLETE"
    assert entry["audit_fix_rounds"] == 2


def test_resolver_finalize_no_audit_fix_rounds_when_zero():
    """Phase 1.6 byte-shape preservation: zero rounds => no key written."""
    state = _make_run_state()
    report = _make_report([])
    _finalize_milestone_with_quality_contract(
        state, "m1", report, _make_config(),
    )
    entry = state.milestone_progress["m1"]
    assert "audit_fix_rounds" not in entry


# ---------------------------------------------------------------------------
# 8503 helper FAILED-floor: anchor-restore preserves caller failure_reason +
# never accidentally DEGRADES on low/medium-only findings.
# ---------------------------------------------------------------------------


def test_8503_helper_failed_floor_preserves_caller_reason_on_low_medium_findings(tmp_path: Path):
    """User-direction contract — anchor-restore fails always demote to FAILED, never DEGRADED, even on low/medium-only audit findings."""
    state = _make_run_state(existing_rounds=1)
    findings = [_make_finding("MEDIUM"), _make_finding("LOW")]  # contract would say DEGRADED
    report = _make_report(findings, medium=1, low=1)
    _finalize_milestone_with_quality_contract(
        state, "m1", report, _make_config(),
        cwd=str(tmp_path),
        override_status="FAILED",
        override_failure_reason="regression",
    )
    entry = state.milestone_progress["m1"]
    assert entry["status"] == "FAILED"
    assert entry["failure_reason"] == "regression"
    # Quality fields populated from audit_report even with override.
    assert entry["audit_status"] == "degraded"
    assert entry["unresolved_findings_count"] == 2
    assert entry["audit_debt_severity"] == "MEDIUM"
    # audit_fix_rounds preserved.
    assert entry["audit_fix_rounds"] == 1


def test_8503_helper_failed_floor_preserves_critical_findings_quality_fields(tmp_path: Path):
    """Anchor-restore with HIGH/CRITICAL findings still sets FAILED — and quality fields reflect actual debt."""
    state = _make_run_state()
    findings = [_make_finding("CRITICAL"), _make_finding("HIGH"), _make_finding("HIGH")]
    report = _make_report(findings, critical=1, high=2)
    _finalize_milestone_with_quality_contract(
        state, "m1", report, _make_config(),
        cwd=str(tmp_path),
        override_status="FAILED",
        override_failure_reason="audit_fix_did_not_recover_build",
    )
    entry = state.milestone_progress["m1"]
    assert entry["status"] == "FAILED"
    assert entry["failure_reason"] == "audit_fix_did_not_recover_build"
    assert entry["audit_debt_severity"] == "CRITICAL"


def test_8503_helper_failed_floor_no_audit_report_uses_sentinels(tmp_path: Path):
    """Anchor-restore without audit_report — FAILED with sentinel quality fields."""
    state = _make_run_state()
    _finalize_milestone_with_quality_contract(
        state, "m1", None, _make_config(),
        cwd=str(tmp_path),
        override_status="FAILED",
        override_failure_reason="cross_milestone_lock_violation",
    )
    entry = state.milestone_progress["m1"]
    assert entry["status"] == "FAILED"
    assert entry["failure_reason"] == "cross_milestone_lock_violation"
    # Sentinel quality fields → no keys written.
    assert "audit_status" not in entry or entry.get("audit_status") == "unknown"
    assert "unresolved_findings_count" not in entry
    assert "audit_debt_severity" not in entry or entry["audit_debt_severity"] == ""


# ---------------------------------------------------------------------------
# Cascade-gate absorption: 2026-04-28 canonical smoke shape (5 CRITICAL + 8 HIGH).
# ---------------------------------------------------------------------------


def test_cascade_absorption_canonical_smoke_shape_routes_to_failed(tmp_path: Path):
    """Phase 5.5 absorbs cascade_quality_gate_blocks_complete logic. The 2026-04-28
    Wave 1 closeout shape (5 CRITICAL + 8 HIGH FAIL) MUST route to FAILED, byte-identical
    to Phase 5.4's cascade-FAILED branch.
    """
    state = _make_run_state()
    findings = [_make_finding("CRITICAL") for _ in range(5)]
    findings.extend(_make_finding("HIGH") for _ in range(8))
    report = _make_report(findings, critical=5, high=8)
    final, audit_status, count, severity = _evaluate_quality_contract(
        report, state, _make_config(),
    )
    assert final == "FAILED"
    assert audit_status == "failed"
    assert count == 13  # 5 + 8
    assert severity == "CRITICAL"


def test_cascade_absorption_canonical_smoke_shape_with_legacy_permissive_routes_to_degraded():
    """Same shape under --legacy-permissive-audit → DEGRADED (deprecated)."""
    state = _make_run_state()
    findings = [_make_finding("CRITICAL") for _ in range(5)]
    findings.extend(_make_finding("HIGH") for _ in range(8))
    report = _make_report(findings, critical=5, high=8)
    final, audit_status, _, severity = _evaluate_quality_contract(
        report, state, _make_config(legacy_permissive_audit=True),
    )
    assert final == "DEGRADED"
    assert audit_status == "degraded"
    assert severity == "CRITICAL"


# ---------------------------------------------------------------------------
# 6526 quality-validators stays direct (deviation from §M.M1).
# ---------------------------------------------------------------------------


def test_6526_quality_validators_failed_stays_direct():
    """Phase 5.4 threaded audit_fix_rounds at cli.py:6526 (was 6504); Phase 5.5
    KEEPS this site direct (post-completion downstream check, NOT Quality
    Contract). Verify the literal still exists in cli.py.
    """
    cli = (Path(__file__).parent.parent / "src" / "agent_team_v15" / "cli.py").read_text(encoding="utf-8")
    # The 6526 site writes "FAILED" with audit_fix_rounds_kwarg threading.
    # Pattern: in the quality-validators block (search for marker comment).
    assert "Re-thread to preserve" in cli, (
        "Phase 5.4 quality-validators FAILED site marker comment lost — "
        "verify Phase 5.5 didn't accidentally migrate cli.py:6526."
    )
    # And the audit_fix_rounds threading is still in place.
    assert "_qv_audit_fix_rounds_kwarg" in cli, (
        "Phase 5.4 quality-validators audit_fix_rounds threading variable missing."
    )


# ---------------------------------------------------------------------------
# Confirmation status round-trip on AuditFinding.
# ---------------------------------------------------------------------------


def test_audit_finding_confirmation_status_default_is_unconfirmed():
    f = _make_finding()
    assert f.confirmation_status == "unconfirmed"


def test_audit_finding_to_dict_emits_confirmation_status():
    f = _make_finding()
    d = f.to_dict()
    assert d["confirmation_status"] == "unconfirmed"


def test_audit_finding_from_dict_reads_confirmation_status():
    f = _make_finding()
    f.confirmation_status = "rejected"
    d = f.to_dict()
    f2 = AuditFinding.from_dict(d)
    assert f2.confirmation_status == "rejected"


def test_audit_finding_confirmation_status_round_trip():
    f = _make_finding()
    f.confirmation_status = "confirmed"
    d = f.to_dict()
    f2 = AuditFinding.from_dict(d)
    assert f2.to_dict() == d


# ---------------------------------------------------------------------------
# _max_severity helper.
# ---------------------------------------------------------------------------


def test_max_severity_critical_wins():
    findings = [_make_finding("LOW"), _make_finding("CRITICAL"), _make_finding("HIGH")]
    assert _max_severity(findings) == "CRITICAL"


def test_max_severity_empty_returns_empty_string():
    assert _max_severity([]) == ""


def test_max_severity_only_low():
    assert _max_severity([_make_finding("LOW"), _make_finding("LOW")]) == "LOW"


# ---------------------------------------------------------------------------
# Suppressed (rejected) findings excluded from contract count.
# ---------------------------------------------------------------------------


def test_rejected_findings_excluded_from_contract_count():
    """§M.M13 — operator-rejected findings are excluded from the unresolved set."""
    state = _make_run_state()
    f1 = _make_finding("HIGH")
    f1.confirmation_status = "rejected"
    f2 = _make_finding("MEDIUM")
    report = _make_report([f1, f2], high=1, medium=1)
    final, _, count, severity = _evaluate_quality_contract(
        report, state, _make_config(),
    )
    # f1 (HIGH) is suppressed → only f2 (MEDIUM) remains → DEGRADED.
    assert final == "DEGRADED"
    assert count == 1
    assert severity == "MEDIUM"


# ---------------------------------------------------------------------------
# Sidecar shape on _capture_milestone_anchor_on_complete.
# ---------------------------------------------------------------------------


def test_sidecar_written_with_quality_fields_on_capture(tmp_path: Path):
    """§M.M8 — sidecar lands at _anchor/_complete/_quality.json with shape per spec."""
    from agent_team_v15.wave_executor import _capture_milestone_anchor_on_complete

    cwd = tmp_path
    (cwd / "src").mkdir()
    (cwd / "src" / "main.py").write_text("# test\n", encoding="utf-8")
    complete = _capture_milestone_anchor_on_complete(
        str(cwd), "m1",
        audit_status="degraded",
        unresolved_findings_count=3,
        audit_debt_severity="MEDIUM",
        audit_findings_path="/path/to/AUDIT_REPORT.json",
    )
    sidecar = complete / "_quality.json"
    assert sidecar.is_file()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    # §M.M8 6-field schema (no milestone_status).
    assert set(data.keys()) == {
        "quality",
        "audit_status",
        "unresolved_findings_count",
        "audit_debt_severity",
        "audit_findings_path",
        "captured_at",
    }
    assert data["quality"] == "degraded"
    assert data["audit_status"] == "degraded"
    assert data["unresolved_findings_count"] == 3
    assert data["audit_debt_severity"] == "MEDIUM"


def test_sidecar_clean_quality_when_audit_status_clean(tmp_path: Path):
    from agent_team_v15.wave_executor import _capture_milestone_anchor_on_complete

    cwd = tmp_path
    (cwd / "src").mkdir()
    (cwd / "src" / "main.py").write_text("# test\n", encoding="utf-8")
    complete = _capture_milestone_anchor_on_complete(
        str(cwd), "m1",
        audit_status="clean",
        unresolved_findings_count=0,
    )
    data = json.loads((complete / "_quality.json").read_text(encoding="utf-8"))
    assert data["quality"] == "clean"


def test_no_anchor_degraded_directory_created(tmp_path: Path):
    """§M.M8 — quality goes in sidecar; NO `_anchor/_degraded/` slot."""
    from agent_team_v15.wave_executor import _capture_milestone_anchor_on_complete

    cwd = tmp_path
    (cwd / "src").mkdir()
    (cwd / "src" / "main.py").write_text("# test\n", encoding="utf-8")
    _capture_milestone_anchor_on_complete(
        str(cwd), "m1",
        audit_status="degraded",
        unresolved_findings_count=3,
        audit_debt_severity="MEDIUM",
    )
    # Only _complete/ exists; never _degraded/.
    assert (cwd / ".agent-team" / "milestones" / "m1" / "_anchor" / "_complete").is_dir()
    assert not (cwd / ".agent-team" / "milestones" / "m1" / "_anchor" / "_degraded").exists()


# ---------------------------------------------------------------------------
# Confirmation registry round-trip.
# ---------------------------------------------------------------------------


def test_suppression_registry_round_trip(tmp_path: Path):
    from agent_team_v15.finding_confirmation import (
        is_finding_suppressed,
        load_suppression_registry,
        save_suppression_registry,
    )
    (tmp_path / ".agent-team").mkdir()
    registry = {"suppressions": [{
        "finding_code": "AUDIT-001",
        "milestone_id": "m1",
        "confirmation_status": "rejected",
        "operator": "alice",
        "reason": "false positive",
        "created_at": "2026-04-29T00:00:00Z",
        "expires_at": None,
        "auditor_prompt_hash": "scorer",
        "auditor_version": "v1",
    }]}
    save_suppression_registry(tmp_path, registry)
    loaded = load_suppression_registry(tmp_path)
    assert loaded == registry
    assert is_finding_suppressed(loaded, "AUDIT-001", "m1")
    assert not is_finding_suppressed(loaded, "AUDIT-002", "m1")
    # Cross-milestone isolation: same code, different milestone.
    assert not is_finding_suppressed(loaded, "AUDIT-001", "m2")


# ---------------------------------------------------------------------------
# Rescan QUALITY_DEBT_RESCAN.md generation.
# ---------------------------------------------------------------------------


def test_rescan_quality_debt_generates_report_and_populates_fields(tmp_path: Path):
    from agent_team_v15.quality_debt_rescan import rescan_quality_debt

    # Synthesize a minimal run-dir.
    at = tmp_path / ".agent-team"
    at.mkdir()
    state = {
        "milestone_progress": {
            "m1": {"status": "COMPLETE"},
            "m2": {"status": "COMPLETE"},
        },
        "completed_milestones": ["m1", "m2"],
        "failed_milestones": [],
        "executed_waves": ["A", "B"],
    }
    (at / "STATE.json").write_text(json.dumps(state), encoding="utf-8")

    # m1: clean audit
    m1_dir = at / "milestones" / "m1" / ".agent-team"
    m1_dir.mkdir(parents=True)
    m1_report = _make_report([])
    (m1_dir / "AUDIT_REPORT.json").write_text(m1_report.to_json(), encoding="utf-8")

    # m2: HIGH unresolved → contract says FAILED
    m2_dir = at / "milestones" / "m2" / ".agent-team"
    m2_dir.mkdir(parents=True)
    m2_findings = [_make_finding("HIGH"), _make_finding("HIGH")]
    m2_report = _make_report(m2_findings, high=2)
    (m2_dir / "AUDIT_REPORT.json").write_text(m2_report.to_json(), encoding="utf-8")

    rc = rescan_quality_debt(cwd=str(tmp_path))
    assert rc == 0

    report_path = at / "QUALITY_DEBT_RESCAN.md"
    assert report_path.is_file()
    body = report_path.read_text(encoding="utf-8")
    assert "Quality Debt Rescan Report" in body
    assert "m1" in body and "m2" in body

    # STATE.json populated with Phase 5.3 fields.
    updated = json.loads((at / "STATE.json").read_text(encoding="utf-8"))
    m2_entry = updated["milestone_progress"]["m2"]
    assert m2_entry["audit_status"] == "failed"
    assert m2_entry["audit_debt_severity"] == "HIGH"
    # Status preserved (not overwriting without --rescan-overwrite-status).
    assert m2_entry["status"] == "COMPLETE"


def test_rescan_quality_debt_overwrite_status_rewrites_complete_to_degraded(tmp_path: Path):
    from agent_team_v15.quality_debt_rescan import rescan_quality_debt

    at = tmp_path / ".agent-team"
    at.mkdir()
    state = {
        "milestone_progress": {"m1": {"status": "COMPLETE"}},
        "completed_milestones": ["m1"],
        "failed_milestones": [],
        "executed_waves": ["A", "B"],
    }
    (at / "STATE.json").write_text(json.dumps(state), encoding="utf-8")
    m1_dir = at / "milestones" / "m1" / ".agent-team"
    m1_dir.mkdir(parents=True)
    # MEDIUM-only findings → contract says DEGRADED.
    m1_report = _make_report([_make_finding("MEDIUM")], medium=1)
    (m1_dir / "AUDIT_REPORT.json").write_text(m1_report.to_json(), encoding="utf-8")

    rc = rescan_quality_debt(cwd=str(tmp_path), rescan_overwrite_status=True)
    assert rc == 0

    updated = json.loads((at / "STATE.json").read_text(encoding="utf-8"))
    assert updated["milestone_progress"]["m1"]["status"] == "DEGRADED"


def test_rescan_quality_debt_handles_nested_pre_phase_5_2_paths(tmp_path: Path):
    """Migration window — pre-Phase-5.2 nested AUDIT_REPORT.json layout still works."""
    from agent_team_v15.quality_debt_rescan import rescan_quality_debt

    at = tmp_path / ".agent-team"
    at.mkdir()
    state = {
        "milestone_progress": {"m1": {"status": "COMPLETE"}},
        "completed_milestones": ["m1"],
        "failed_milestones": [],
        "executed_waves": ["A", "B"],
    }
    (at / "STATE.json").write_text(json.dumps(state), encoding="utf-8")
    # Nested layout: <run-dir>/.agent-team/m1/.agent-team/AUDIT_REPORT.json
    m1_nested = at / "m1" / ".agent-team"
    m1_nested.mkdir(parents=True)
    (m1_nested / "AUDIT_REPORT.json").write_text(_make_report([]).to_json(), encoding="utf-8")

    rc = rescan_quality_debt(cwd=str(tmp_path))
    assert rc == 0
    updated = json.loads((at / "STATE.json").read_text(encoding="utf-8"))
    assert updated["milestone_progress"]["m1"]["audit_status"] == "clean"
