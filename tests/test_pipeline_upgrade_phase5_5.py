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
# Finding #1 — natural-contract FAILED synthesizes a reason; in-flight
# (cost_cap_reached) preserved when no caller arg.
# ---------------------------------------------------------------------------


def test_natural_contract_failed_synthesizes_audit_findings_block_complete_reason(tmp_path: Path):
    """Per finding #1 — natural-completion path with a HIGH finding routes
    to FAILED via the contract; the resolver MUST synthesize a default
    reason so layer-2 Rule 3 doesn't fire on its own write.
    """
    state = _make_run_state()
    findings = [_make_finding("HIGH")]
    report = _make_report(findings, high=1)
    # No failure_reason supplied (mirrors natural-completion at cli.py:6443).
    final, audit_status, _, severity = _finalize_milestone_with_quality_contract(
        state, "m1", report, _make_config(),
        cwd=str(tmp_path),
    )
    entry = state.milestone_progress["m1"]
    assert entry["status"] == "FAILED"
    # Synthesized reason — Rule 3 cannot fire on the resolver's own write.
    assert entry["failure_reason"] == "audit_findings_block_complete"
    assert audit_status == "failed"
    assert severity == "HIGH"


def test_natural_contract_failed_preserves_inflight_cost_cap_reached(tmp_path: Path):
    """Per finding #1 — when Phase 5.4 cost-cap path persisted
    failure_reason='cost_cap_reached' before this resolver call, and the
    caller doesn't pass an explicit reason, the in-flight reason is
    preserved through the terminal write so QUALITY_DEBT entries surface
    the cost-cap signal.
    """
    state = _make_run_state()
    state.milestone_progress["m1"]["failure_reason"] = "cost_cap_reached"
    findings = [_make_finding("HIGH")]
    report = _make_report(findings, high=1)
    _finalize_milestone_with_quality_contract(
        state, "m1", report, _make_config(),
        cwd=str(tmp_path),
        # No failure_reason kwarg — in-flight wins.
    )
    entry = state.milestone_progress["m1"]
    assert entry["status"] == "FAILED"
    assert entry["failure_reason"] == "cost_cap_reached"


def test_caller_failure_reason_wins_over_inflight(tmp_path: Path):
    """Caller-supplied failure_reason wins over in-flight (cascade epilogue
    must be able to overwrite cost_cap_reached with wave_fail_recovered).
    """
    state = _make_run_state()
    state.milestone_progress["m1"]["failure_reason"] = "wave_fail_recovery_attempt"
    findings = [_make_finding("HIGH")]
    report = _make_report(findings, high=1)
    _finalize_milestone_with_quality_contract(
        state, "m1", report, _make_config(),
        cwd=str(tmp_path),
        failure_reason="audit_fix_recovered_build_but_findings_remain",
    )
    entry = state.milestone_progress["m1"]
    assert entry["failure_reason"] == "audit_fix_recovered_build_but_findings_remain"


def test_natural_contract_complete_no_reason(tmp_path: Path):
    """Contract-decided COMPLETE with no caller / in-flight reason → empty."""
    state = _make_run_state()
    report = _make_report([])
    _finalize_milestone_with_quality_contract(
        state, "m1", report, _make_config(), cwd=str(tmp_path),
    )
    entry = state.milestone_progress["m1"]
    assert entry["status"] == "COMPLETE"
    assert "failure_reason" not in entry  # sentinel-skip: empty reason


# ---------------------------------------------------------------------------
# Finding #3 — sidecar atomicity at capture (rollback on failure + raise).
# ---------------------------------------------------------------------------


def test_sidecar_write_failure_rolls_back_anchor(tmp_path: Path, monkeypatch):
    """Per finding #3 — when _quality.json write fails, the partial
    `_anchor/_complete/` directory is removed and the exception
    propagates so the caller's existing best-effort try/except surfaces
    a missed snapshot rather than landing a half-captured anchor.
    """
    from agent_team_v15.wave_executor import _capture_milestone_anchor_on_complete
    cwd = tmp_path
    (cwd / "src").mkdir()
    (cwd / "src" / "main.py").write_text("# test\n", encoding="utf-8")

    # Force sidecar write to fail.
    original_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if self.name == "_quality.json":
            raise OSError("disk full (synthetic)")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)
    with pytest.raises(OSError):
        _capture_milestone_anchor_on_complete(
            str(cwd), "m1",
            audit_status="clean",
            unresolved_findings_count=0,
        )
    # Anchor directory must NOT exist post-rollback.
    anchor_dir = cwd / ".agent-team" / "milestones" / "m1" / "_anchor" / "_complete"
    assert not anchor_dir.exists(), (
        "Phase 5.5 §M.M8 atomicity: sidecar write failure must roll back "
        "the partial anchor capture; got dangling anchor at "
        f"{anchor_dir}."
    )


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


def test_rejected_findings_excluded_only_when_registry_validates(tmp_path: Path):
    """§M.M13 — operator-rejected findings excluded from the unresolved set
    ONLY after the suppression registry validates the rejection.

    Per finding #2 user-mandated negative test contract.
    """
    from agent_team_v15.finding_confirmation import save_suppression_registry

    # Synthesize a run-dir + suppression registry.
    (tmp_path / ".agent-team").mkdir()
    save_suppression_registry(tmp_path, {
        "suppressions": [{
            "finding_code": "F-HIGH-FAIL",
            "milestone_id": "m1",
            "confirmation_status": "rejected",
            "operator": "tester",
            "reason": "false positive",
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": None,
            "auditor_prompt_hash": "scorer",
            "auditor_version": "v1",
        }],
    })
    state = _make_run_state()
    f1 = _make_finding("HIGH")  # finding_id = "F-HIGH-FAIL" per _make_finding
    f1.confirmation_status = "rejected"
    f2 = _make_finding("MEDIUM")
    report = _make_report([f1, f2], high=1, medium=1)
    final, _, count, severity = _evaluate_quality_contract(
        report, state, _make_config(),
        cwd=str(tmp_path), milestone_id="m1",
    )
    # f1 (HIGH) suppressed via registry → only f2 (MEDIUM) remains → DEGRADED.
    assert final == "DEGRADED"
    assert count == 1
    assert severity == "MEDIUM"


def test_rejected_findings_NOT_excluded_without_registry(tmp_path: Path):
    """§M.M13 disk-edit loophole — finding marked rejected on disk but no
    matching suppression registry entry MUST stay counted as unresolved.
    Otherwise an attacker (or accidental disk edit) could bypass the
    Quality Contract by flipping confirmation_status.

    Per finding #2 user-mandated negative test.
    """
    (tmp_path / ".agent-team").mkdir()
    # Empty registry on disk.
    state = _make_run_state()
    f1 = _make_finding("HIGH")  # disk says rejected but no registry entry
    f1.confirmation_status = "rejected"
    report = _make_report([f1], high=1)
    final, audit_status, count, severity = _evaluate_quality_contract(
        report, state, _make_config(),
        cwd=str(tmp_path), milestone_id="m1",
    )
    # Disk-edit-rejected without registry → still FAILED.
    assert final == "FAILED"
    assert audit_status == "failed"
    assert count == 1
    assert severity == "HIGH"


def test_rejected_findings_NOT_excluded_when_cwd_milestone_id_absent():
    """When the resolver isn't given cwd + milestone_id (e.g., legacy
    direct callers), the registry can't be loaded — SAFE behaviour is
    to distrust disk-shape and keep the finding counted.
    """
    state = _make_run_state()
    f1 = _make_finding("HIGH")
    f1.confirmation_status = "rejected"
    report = _make_report([f1], high=1)
    final, _, count, _ = _evaluate_quality_contract(
        report, state, _make_config(),
        # No cwd/milestone_id → registry cannot be consulted.
    )
    assert final == "FAILED"
    assert count == 1


# ---------------------------------------------------------------------------
# Round-2 finding #1 — strict suppression registry validation.
# Plan §M.M13 line 1629 requires full evidence schema + CRITICAL emergency-state.
# ---------------------------------------------------------------------------


def test_rejected_minimal_registry_row_does_NOT_bypass_contract(tmp_path: Path):
    """Per Round-2 finding #1 negative test (minimal registry).

    A registry entry with only finding_code + milestone_id + confirmation_status
    (missing operator / reason / created_at / auditor_prompt_hash /
    auditor_version) MUST NOT bypass the Quality Contract — the §M.M13
    schema requires every evidence field populated and non-empty.
    """
    from agent_team_v15.finding_confirmation import save_suppression_registry

    (tmp_path / ".agent-team").mkdir()
    save_suppression_registry(tmp_path, {
        "suppressions": [{
            "finding_code": "F-HIGH-FAIL",
            "milestone_id": "m1",
            "confirmation_status": "rejected",
            # Missing: operator, reason, created_at, auditor_prompt_hash, auditor_version.
        }],
    })
    state = _make_run_state()
    f1 = _make_finding("HIGH")
    f1.confirmation_status = "rejected"
    report = _make_report([f1], high=1)
    final, audit_status, count, severity = _evaluate_quality_contract(
        report, state, _make_config(),
        cwd=str(tmp_path), milestone_id="m1",
    )
    assert final == "FAILED", (
        "Phase 5.5 §M.M13: minimal one-field registry row must NOT bypass "
        "the Quality Contract; got "
        f"({final!r}, {audit_status!r}, {count!r}, {severity!r})"
    )


def test_rejected_critical_without_emergency_state_does_NOT_bypass_contract(tmp_path: Path):
    """Per Round-2 finding #1 negative test (CRITICAL without emergency flag).

    CRITICAL findings require ``emergency_critical_suppression=true`` on
    STATE.json before the rejection takes effect; the flag is set by
    ``confirm-findings --emergency-suppress-critical``. A registry-validated
    rejection without the emergency flag MUST stay counted.
    """
    from agent_team_v15.finding_confirmation import save_suppression_registry

    (tmp_path / ".agent-team").mkdir()
    # Full schema entry — every evidence field populated.
    save_suppression_registry(tmp_path, {
        "suppressions": [{
            "finding_code": "F-CRITICAL-FAIL",
            "milestone_id": "m1",
            "confirmation_status": "rejected",
            "operator": "alice",
            "reason": "false positive",
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": None,
            "auditor_prompt_hash": "scorer",
            "auditor_version": "v1",
        }],
    })
    # Synthesize STATE.json WITHOUT emergency_critical_suppression.
    import json as _j
    (tmp_path / ".agent-team" / "STATE.json").write_text(
        _j.dumps({"emergency_critical_suppression": False}),
        encoding="utf-8",
    )
    state = _make_run_state()
    f1 = _make_finding("CRITICAL")
    f1.confirmation_status = "rejected"
    report = _make_report([f1], critical=1)
    final, audit_status, count, severity = _evaluate_quality_contract(
        report, state, _make_config(),
        cwd=str(tmp_path), milestone_id="m1",
    )
    assert final == "FAILED", (
        "Phase 5.5 §M.M13: CRITICAL suppression without emergency flag must "
        f"stay FAILED; got ({final!r}, {audit_status!r}, {count!r}, {severity!r})"
    )
    assert severity == "CRITICAL"


def test_rejected_critical_WITH_emergency_state_DOES_bypass(tmp_path: Path):
    """When emergency_critical_suppression=True is set, CRITICAL rejection
    DOES take effect (the documented escape hatch with red-warning trail).
    """
    from agent_team_v15.finding_confirmation import save_suppression_registry

    (tmp_path / ".agent-team").mkdir()
    save_suppression_registry(tmp_path, {
        "suppressions": [{
            "finding_code": "F-CRITICAL-FAIL",
            "milestone_id": "m1",
            "confirmation_status": "rejected",
            "operator": "alice",
            "reason": "false positive",
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": None,
            "auditor_prompt_hash": "scorer",
            "auditor_version": "v1",
        }],
    })
    import json as _j
    (tmp_path / ".agent-team" / "STATE.json").write_text(
        _j.dumps({"emergency_critical_suppression": True}),
        encoding="utf-8",
    )
    state = _make_run_state()
    f1 = _make_finding("CRITICAL")
    f1.confirmation_status = "rejected"
    report = _make_report([f1], critical=1)
    final, _, count, _ = _evaluate_quality_contract(
        report, state, _make_config(),
        cwd=str(tmp_path), milestone_id="m1",
    )
    assert final == "COMPLETE"
    assert count == 0


def test_rejected_with_empty_evidence_field_does_NOT_bypass(tmp_path: Path):
    """Per Round-2 finding #1 — even ONE empty required evidence field
    invalidates the suppression. Tests `reason=""`."""
    from agent_team_v15.finding_confirmation import save_suppression_registry

    (tmp_path / ".agent-team").mkdir()
    save_suppression_registry(tmp_path, {
        "suppressions": [{
            "finding_code": "F-HIGH-FAIL",
            "milestone_id": "m1",
            "confirmation_status": "rejected",
            "operator": "alice",
            "reason": "",  # EMPTY → schema fail
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": None,
            "auditor_prompt_hash": "scorer",
            "auditor_version": "v1",
        }],
    })
    state = _make_run_state()
    f1 = _make_finding("HIGH")
    f1.confirmation_status = "rejected"
    report = _make_report([f1], high=1)
    final, _, _, _ = _evaluate_quality_contract(
        report, state, _make_config(),
        cwd=str(tmp_path), milestone_id="m1",
    )
    assert final == "FAILED"


def test_rejected_with_expired_suppression_does_NOT_bypass(tmp_path: Path):
    """Expired suppression entries are ignored."""
    from agent_team_v15.finding_confirmation import save_suppression_registry

    (tmp_path / ".agent-team").mkdir()
    save_suppression_registry(tmp_path, {
        "suppressions": [{
            "finding_code": "F-HIGH-FAIL",
            "milestone_id": "m1",
            "confirmation_status": "rejected",
            "operator": "alice",
            "reason": "false positive",
            "created_at": "2024-01-01T00:00:00Z",
            "expires_at": "2024-12-31T00:00:00Z",  # expired
            "auditor_prompt_hash": "scorer",
            "auditor_version": "v1",
        }],
    })
    state = _make_run_state()
    f1 = _make_finding("HIGH")
    f1.confirmation_status = "rejected"
    report = _make_report([f1], high=1)
    final, _, _, _ = _evaluate_quality_contract(
        report, state, _make_config(),
        cwd=str(tmp_path), milestone_id="m1",
    )
    assert final == "FAILED"


# ---------------------------------------------------------------------------
# Round-2 finding #2 — capture-boundary Rule 2 validation.
# ---------------------------------------------------------------------------


def test_capture_rule_2_rolls_back_on_state_sidecar_inconsistency(tmp_path: Path):
    """Per Round-2 finding #2 — when the capture site writes a sidecar
    that disagrees with STATE.json (e.g., recovery path with default
    sentinel quality fields while STATE has actual values), the
    capture-boundary Rule 2 validation MUST raise and roll back the
    partial anchor.
    """
    from agent_team_v15.wave_executor import _capture_milestone_anchor_on_complete

    cwd = tmp_path
    (cwd / "src").mkdir()
    (cwd / "src" / "main.py").write_text("# test\n", encoding="utf-8")

    # State carries audit_status=clean but caller passes default sentinels
    # (audit_status="" → sidecar audit_status="unknown"). Rule 2 STATE
    # consistency check should raise.
    state = _make_run_state()
    state.milestone_progress["m1"]["audit_status"] = "clean"

    with pytest.raises(Exception) as excinfo:
        _capture_milestone_anchor_on_complete(
            str(cwd), "m1",
            # No audit_status / unresolved / etc. → sidecar gets sentinels.
            state=state,
        )
    assert "audit_status" in str(excinfo.value) or "forbidden_anchor_without_quality_sidecar" in str(excinfo.value)
    # Anchor must NOT exist post-rollback.
    anchor_dir = cwd / ".agent-team" / "milestones" / "m1" / "_anchor" / "_complete"
    assert not anchor_dir.exists()


# ---------------------------------------------------------------------------
# Round-3 finding — §M.M13 dispatch-boundary suppression filtering.
# Plan line 1630: "Suppressions are applied during dispatch + Quality
# Contract evaluation only after the registry entry validates."
# ---------------------------------------------------------------------------


def _make_audit_report_for_dispatch(findings: list, *, critical: int = 0, high: int = 0, medium: int = 0, low: int = 0):
    """Like _make_report but returns a report with verdict=FAIL extras + fix_candidates populated."""
    rep = _make_report(findings, critical=critical, high=high, medium=medium, low=low)
    rep.extras = {"verdict": "FAIL"}
    rep.fix_candidates = list(range(len(findings)))
    return rep


@pytest.mark.asyncio
async def test_dispatch_filters_validated_suppression_before_dispatch(tmp_path: Path, monkeypatch):
    """Per round-3 finding — a finding with a fully-validated §M.M13
    suppression entry MUST be filtered out of audit-fix dispatch. The
    pre-fix narrow repro showed `dispatch_findings_seen: ['F-HIGH-FAIL']`
    even with a valid registry entry.
    """
    from agent_team_v15.finding_confirmation import save_suppression_registry
    from agent_team_v15 import cli as _cli

    (tmp_path / ".agent-team").mkdir()
    save_suppression_registry(tmp_path, {
        "suppressions": [{
            "finding_code": "F-HIGH-FAIL",
            "milestone_id": "m1",
            "confirmation_status": "rejected",
            "operator": "alice",
            "reason": "false positive",
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": None,
            "auditor_prompt_hash": "scorer",
            "auditor_version": "v1",
        }],
    })

    f1 = _make_finding("HIGH")
    f1.confirmation_status = "rejected"
    f2 = _make_finding("MEDIUM")
    f2.finding_id = "F-MEDIUM-FAIL"
    report = _make_audit_report_for_dispatch([f1, f2], high=1, medium=1)

    # Capture findings handed to the dispatch executor.
    seen: list[str] = []

    async def fake_execute_unified_fix_async(*args, **kwargs):
        # audit_agent.Finding uses ``id``; AuditFinding uses ``finding_id``.
        # _convert_findings copies finding_id → id, so read both for safety.
        for f in kwargs.get("findings", []) or []:
            code = str(getattr(f, "id", "") or getattr(f, "finding_id", "") or "")
            seen.append(code)
        return 0.0

    monkeypatch.setattr(
        "agent_team_v15.fix_executor.execute_unified_fix_async",
        fake_execute_unified_fix_async,
    )
    # Avoid hook-writer side effects.
    monkeypatch.setattr(
        "agent_team_v15.agent_teams_backend.AgentTeamsBackend._ensure_wave_d_path_guard_settings",
        lambda *a, **kw: None,
    )

    config = SimpleNamespace(
        v18=SimpleNamespace(legacy_permissive_audit=False, codex_fix_routing_enabled=False, provider_routing=False),
        audit_team=SimpleNamespace(
            milestone_anchor_enabled=False,
            test_surface_lock_enabled=False,
            audit_wave_awareness_enabled=False,
            lift_risk_1_when_nets_armed=False,
        ),
    )

    modified, _cost = await _cli._run_audit_fix_unified(
        report, config, str(tmp_path), "synthetic prd", "standard",
        fix_round=1,
        milestone_id="m1",
    )
    # F-HIGH-FAIL is suppressed and validated → must NOT reach dispatch.
    # F-MEDIUM-FAIL has no suppression → MUST reach dispatch.
    assert "F-HIGH-FAIL" not in seen, (
        f"Phase 5.5 §M.M13 dispatch filter: validated suppression "
        f"reached dispatch; seen={seen}"
    )
    assert "F-MEDIUM-FAIL" in seen, (
        f"non-suppressed finding must still dispatch; seen={seen}"
    )


@pytest.mark.asyncio
async def test_dispatch_does_NOT_filter_minimal_invalid_suppression(tmp_path: Path, monkeypatch):
    """Minimal one-field registry entry MUST NOT bypass dispatch — the
    §M.M13 strict validator requires every evidence field populated.
    """
    from agent_team_v15.finding_confirmation import save_suppression_registry
    from agent_team_v15 import cli as _cli

    (tmp_path / ".agent-team").mkdir()
    save_suppression_registry(tmp_path, {
        "suppressions": [{
            "finding_code": "F-HIGH-FAIL",
            "milestone_id": "m1",
            "confirmation_status": "rejected",
            # Missing operator/reason/created_at/auditor_*.
        }],
    })
    f1 = _make_finding("HIGH")
    f1.confirmation_status = "rejected"
    report = _make_audit_report_for_dispatch([f1], high=1)

    seen: list[str] = []

    async def fake_execute_unified_fix_async(*args, **kwargs):
        # audit_agent.Finding uses ``id``; AuditFinding uses ``finding_id``.
        # _convert_findings copies finding_id → id, so read both for safety.
        for f in kwargs.get("findings", []) or []:
            code = str(getattr(f, "id", "") or getattr(f, "finding_id", "") or "")
            seen.append(code)
        return 0.0

    monkeypatch.setattr(
        "agent_team_v15.fix_executor.execute_unified_fix_async",
        fake_execute_unified_fix_async,
    )
    monkeypatch.setattr(
        "agent_team_v15.agent_teams_backend.AgentTeamsBackend._ensure_wave_d_path_guard_settings",
        lambda *a, **kw: None,
    )
    config = SimpleNamespace(
        v18=SimpleNamespace(legacy_permissive_audit=False, codex_fix_routing_enabled=False, provider_routing=False),
        audit_team=SimpleNamespace(
            milestone_anchor_enabled=False,
            test_surface_lock_enabled=False,
            audit_wave_awareness_enabled=False,
            lift_risk_1_when_nets_armed=False,
        ),
    )
    await _cli._run_audit_fix_unified(
        report, config, str(tmp_path), "synthetic prd", "standard",
        fix_round=1,
        milestone_id="m1",
    )
    assert "F-HIGH-FAIL" in seen, (
        f"Phase 5.5 §M.M13: minimal invalid suppression must NOT bypass "
        f"dispatch; seen={seen}"
    )


@pytest.mark.asyncio
async def test_dispatch_does_NOT_filter_critical_without_emergency_state(tmp_path: Path, monkeypatch):
    """CRITICAL severity findings stay in dispatch unless STATE.json carries
    emergency_critical_suppression=true (set by
    `confirm-findings --emergency-suppress-critical`).
    """
    from agent_team_v15.finding_confirmation import save_suppression_registry
    from agent_team_v15 import cli as _cli

    (tmp_path / ".agent-team").mkdir()
    # Full schema entry but CRITICAL severity.
    save_suppression_registry(tmp_path, {
        "suppressions": [{
            "finding_code": "F-CRITICAL-FAIL",
            "milestone_id": "m1",
            "confirmation_status": "rejected",
            "operator": "alice",
            "reason": "false positive",
            "created_at": "2026-04-29T00:00:00Z",
            "expires_at": None,
            "auditor_prompt_hash": "scorer",
            "auditor_version": "v1",
        }],
    })
    # STATE.json without emergency flag.
    (tmp_path / ".agent-team" / "STATE.json").write_text(
        json.dumps({"emergency_critical_suppression": False}),
        encoding="utf-8",
    )
    f1 = _make_finding("CRITICAL")
    f1.confirmation_status = "rejected"
    report = _make_audit_report_for_dispatch([f1], critical=1)

    seen: list[str] = []

    async def fake_execute_unified_fix_async(*args, **kwargs):
        # audit_agent.Finding uses ``id``; AuditFinding uses ``finding_id``.
        # _convert_findings copies finding_id → id, so read both for safety.
        for f in kwargs.get("findings", []) or []:
            code = str(getattr(f, "id", "") or getattr(f, "finding_id", "") or "")
            seen.append(code)
        return 0.0

    monkeypatch.setattr(
        "agent_team_v15.fix_executor.execute_unified_fix_async",
        fake_execute_unified_fix_async,
    )
    monkeypatch.setattr(
        "agent_team_v15.agent_teams_backend.AgentTeamsBackend._ensure_wave_d_path_guard_settings",
        lambda *a, **kw: None,
    )
    config = SimpleNamespace(
        v18=SimpleNamespace(legacy_permissive_audit=False, codex_fix_routing_enabled=False, provider_routing=False),
        audit_team=SimpleNamespace(
            milestone_anchor_enabled=False,
            test_surface_lock_enabled=False,
            audit_wave_awareness_enabled=False,
            lift_risk_1_when_nets_armed=False,
        ),
    )
    await _cli._run_audit_fix_unified(
        report, config, str(tmp_path), "synthetic prd", "standard",
        fix_round=1,
        milestone_id="m1",
    )
    assert "F-CRITICAL-FAIL" in seen, (
        "Phase 5.5 §M.M13: CRITICAL suppression without emergency flag "
        f"must stay in dispatch; seen={seen}"
    )


def test_capture_rule_2_passes_when_state_and_sidecar_agree(tmp_path: Path):
    """Capture lands cleanly when sidecar and STATE.json carry the same
    quality fields."""
    from agent_team_v15.wave_executor import _capture_milestone_anchor_on_complete

    cwd = tmp_path
    (cwd / "src").mkdir()
    (cwd / "src" / "main.py").write_text("# test\n", encoding="utf-8")

    state = _make_run_state()
    state.milestone_progress["m1"]["audit_status"] = "degraded"
    state.milestone_progress["m1"]["unresolved_findings_count"] = 3
    state.milestone_progress["m1"]["audit_debt_severity"] = "MEDIUM"

    complete = _capture_milestone_anchor_on_complete(
        str(cwd), "m1",
        audit_status="degraded",
        unresolved_findings_count=3,
        audit_debt_severity="MEDIUM",
        state=state,
    )
    assert complete.is_dir()
    sidecar = complete / "_quality.json"
    assert sidecar.is_file()


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
