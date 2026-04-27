"""Phase 4.3 of the pipeline upgrade — audit wave-awareness.

Plan: ``docs/plans/2026-04-26-pipeline-upgrade-phase4.md`` §F (Phase 4.3).

Phase 4.3 tags every audit finding with an ``owner_wave`` derived from
its primary file path, exposes a deferred-status helper that filters
findings whose owner-wave never executed, narrows the audit-fix
classifier so it skips features whose entire file set lives behind
non-executed waves, and emits a wave-aware convergence ratio so the
audit-team's terminate-or-continue signal is no longer inflated by
findings that are downstream of waves that never ran (Risks #25 + #30).

The 2026-04-26 M1 hardening smoke (frozen at
``tests/fixtures/smoke_2026_04_26/``) is the data-driven proof input:
46 audit findings (11 critical, 17 high) where ≥4 of the criticals
trace back to Waves D / C that never executed. The replay fixtures
below load the actual ``AUDIT_REPORT.json`` + ``STATE.json`` and lock
the classifier output against the §B.6 manual classification.

Each fixture targets one acceptance criterion from §F AC1..AC6.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "smoke_2026_04_26"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_run_state(*, completed_waves_per_milestone: dict[str, list[str]],
                    failed_waves_per_milestone: dict[str, str] | None = None) -> Any:
    """Build a minimal ``RunState`` with per-milestone wave_progress.

    Phase 4.3's ``is_owner_wave_executed`` reads
    ``state.wave_progress[milestone_id]["completed_waves"]`` and
    ``["failed_wave"]`` to decide whether a wave letter ran (regardless
    of pass/fail).
    """
    from agent_team_v15.state import RunState

    state = RunState()
    state.wave_progress = {}
    for milestone_id, waves in completed_waves_per_milestone.items():
        entry: dict[str, Any] = {
            "current_wave": waves[-1] if waves else "",
            "completed_waves": list(waves),
            "wave_artifacts": {},
        }
        if failed_waves_per_milestone and milestone_id in failed_waves_per_milestone:
            entry["failed_wave"] = failed_waves_per_milestone[milestone_id]
        state.wave_progress[milestone_id] = entry
    return state


def _load_run_state_from_smoke_fixture() -> Any:
    """Build a ``RunState`` mirroring the frozen 2026-04-26 smoke."""
    state_blob = json.loads((FIXTURE_ROOT / "STATE.json").read_text(encoding="utf-8"))
    completed: dict[str, list[str]] = {}
    failed: dict[str, str] = {}
    for milestone_id, entry in state_blob.get("wave_progress", {}).items():
        completed[milestone_id] = list(entry.get("completed_waves", []) or [])
        failed_wave = entry.get("failed_wave")
        if failed_wave:
            failed[milestone_id] = str(failed_wave)
    return _load_run_state(
        completed_waves_per_milestone=completed,
        failed_waves_per_milestone=failed,
    )


# ---------------------------------------------------------------------------
# AC1 — resolve_owner_wave path classification
# ---------------------------------------------------------------------------


def test_owner_wave_resolver_apps_api_to_wave_b() -> None:
    from agent_team_v15.wave_ownership import resolve_owner_wave

    assert resolve_owner_wave("apps/api/src/foo.ts") == "B"
    assert resolve_owner_wave("apps/api/Dockerfile") == "B"


def test_owner_wave_resolver_apps_web_to_wave_d() -> None:
    from agent_team_v15.wave_ownership import resolve_owner_wave

    assert resolve_owner_wave("apps/web/src/middleware.ts") == "D"
    assert resolve_owner_wave("apps/web/src/app/layout.tsx") == "D"


def test_owner_wave_resolver_packages_api_client_to_wave_c() -> None:
    from agent_team_v15.wave_ownership import resolve_owner_wave

    assert resolve_owner_wave("packages/api-client/src/index.ts") == "C"
    assert resolve_owner_wave("packages/api-client") == "C"


def test_owner_wave_resolver_apps_web_locales_to_wave_d() -> None:
    """``apps/web/locales/`` is Wave D's, even though ``locales/`` is also
    listed in Wave B's allowed_file_globs in the smoke prompt. Phase 4.3
    classifies by physical path ownership, not by Wave B's permissive
    allowlist."""
    from agent_team_v15.wave_ownership import resolve_owner_wave

    assert resolve_owner_wave("apps/web/locales/en/common.json") == "D"
    assert resolve_owner_wave("apps/web/locales/ar/common.json") == "D"


def test_owner_wave_resolver_prisma_to_wave_b() -> None:
    from agent_team_v15.wave_ownership import resolve_owner_wave

    assert resolve_owner_wave("prisma/schema.prisma") == "B"
    assert resolve_owner_wave("prisma/migrations/0001_init/migration.sql") == "B"


def test_owner_wave_resolver_e2e_tests_to_wave_t() -> None:
    from agent_team_v15.wave_ownership import resolve_owner_wave

    assert resolve_owner_wave("e2e/tests/smoke.spec.ts") == "T"
    assert resolve_owner_wave("tests/integration/auth.spec.ts") == "T"


def test_owner_wave_resolver_falls_back_to_wave_agnostic() -> None:
    """Paths not matching any wave-specific pattern → ``wave-agnostic``."""
    from agent_team_v15.wave_ownership import resolve_owner_wave

    assert resolve_owner_wave(".gitignore") == "wave-agnostic"
    assert resolve_owner_wave("package.json") == "wave-agnostic"
    assert resolve_owner_wave("docker-compose.yml") == "wave-agnostic"
    assert resolve_owner_wave(".env.example") == "wave-agnostic"
    # Empty input is also wave-agnostic (defensive).
    assert resolve_owner_wave("") == "wave-agnostic"


def test_owner_wave_resolver_handles_windows_separators() -> None:
    """Windows-style separators must round-trip to the same wave letter
    so audit findings ingested from a Windows run-dir don't mis-classify."""
    from agent_team_v15.wave_ownership import resolve_owner_wave

    assert resolve_owner_wave("apps\\api\\src\\foo.ts") == "B"
    assert resolve_owner_wave("apps\\web\\src\\middleware.ts") == "D"


# ---------------------------------------------------------------------------
# AC2 — Finding gets owner_wave field auto-populated by from_dict
# ---------------------------------------------------------------------------


def test_audit_finding_from_dict_populates_owner_wave_from_file_path() -> None:
    """``AuditFinding.from_dict`` derives ``owner_wave`` from the
    canonical ``file_path`` key when no explicit owner_wave is present."""
    from agent_team_v15.audit_models import AuditFinding

    payload = {
        "finding_id": "F-001",
        "auditor": "interface",
        "requirement_id": "milestone-1",
        "verdict": "FAIL",
        "severity": "CRITICAL",
        "summary": "next-intl locale routing not wired",
        "file_path": "apps/web/src/middleware.ts",
        "line_number": 5,
    }
    finding = AuditFinding.from_dict(payload)
    assert finding.owner_wave == "D"


def test_audit_finding_from_dict_populates_owner_wave_from_legacy_file_key() -> None:
    """Legacy ``file`` key still works (backward-compat with the smoke
    fixture's actual schema)."""
    from agent_team_v15.audit_models import AuditFinding

    payload = {
        "finding_id": "F-005",
        "severity": "CRITICAL",
        "summary": "packages/api-client/ directory does not exist",
        "file": "packages/api-client",
    }
    finding = AuditFinding.from_dict(payload)
    assert finding.owner_wave == "C"


def test_audit_finding_from_dict_prefers_explicit_owner_wave() -> None:
    """When the audit JSON carries an explicit ``owner_wave`` it wins
    over path-based resolution."""
    from agent_team_v15.audit_models import AuditFinding

    payload = {
        "finding_id": "F-001",
        "severity": "CRITICAL",
        "summary": "test",
        "file_path": "apps/web/src/middleware.ts",
        "owner_wave": "T",  # auditor explicitly tagged it
    }
    finding = AuditFinding.from_dict(payload)
    assert finding.owner_wave == "T"


def test_audit_finding_from_dict_default_owner_wave_when_no_path() -> None:
    """Findings without any path information fall back to wave-agnostic."""
    from agent_team_v15.audit_models import AuditFinding

    finding = AuditFinding.from_dict({
        "finding_id": "X-001",
        "severity": "MEDIUM",
        "summary": "Something",
    })
    assert finding.owner_wave == "wave-agnostic"


def test_audit_finding_to_dict_round_trips_owner_wave() -> None:
    """to_dict → from_dict preserves owner_wave."""
    from agent_team_v15.audit_models import AuditFinding

    finding = AuditFinding.from_dict({
        "finding_id": "F-001",
        "severity": "CRITICAL",
        "summary": "test",
        "file_path": "apps/api/src/foo.ts",
    })
    payload = finding.to_dict()
    assert payload.get("owner_wave") == "B"
    rehydrated = AuditFinding.from_dict(payload)
    assert rehydrated.owner_wave == "B"


def test_finding_dispatch_type_carries_owner_wave_field() -> None:
    """``audit_agent.Finding`` (the dispatch boundary type) gains the
    owner_wave field too, so ``cli._convert_findings`` can propagate it
    end-to-end without losing wave information."""
    from agent_team_v15.audit_agent import Finding, FindingCategory, Severity

    finding = Finding(
        id="F-001",
        feature="F-001",
        acceptance_criterion="",
        severity=Severity.CRITICAL,
        category=FindingCategory.CODE_FIX,
        title="t",
        description="d",
        prd_reference="",
        current_behavior="",
        expected_behavior="",
        owner_wave="D",
    )
    assert finding.owner_wave == "D"


def test_audit_agent_finding_default_owner_wave_is_wave_agnostic() -> None:
    """Backward-compat: existing callers that don't set owner_wave get
    the safe ``wave-agnostic`` default."""
    from agent_team_v15.audit_agent import Finding, FindingCategory, Severity

    finding = Finding(
        id="L-001",
        feature="LEGACY",
        acceptance_criterion="",
        severity=Severity.MEDIUM,
        category=FindingCategory.CODE_FIX,
        title="t",
        description="d",
        prd_reference="",
        current_behavior="",
        expected_behavior="",
    )
    assert finding.owner_wave == "wave-agnostic"


# ---------------------------------------------------------------------------
# AC3 — Convergence ratio excludes findings whose owner_wave is DEFERRED
# ---------------------------------------------------------------------------


def test_finding_status_DEFERRED_when_owner_wave_did_not_run() -> None:
    """A finding whose owner_wave never executed has status DEFERRED."""
    from agent_team_v15.audit_models import AuditFinding
    from agent_team_v15.wave_ownership import compute_finding_status

    finding = AuditFinding.from_dict({
        "finding_id": "F-001",
        "severity": "CRITICAL",
        "summary": "test",
        "file_path": "apps/web/src/middleware.ts",
    })
    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        failed_waves_per_milestone={"milestone-1": "B"},
    )
    assert finding.owner_wave == "D"
    assert compute_finding_status(finding, state) == "DEFERRED"


def test_finding_status_FAIL_when_owner_wave_ran_and_failed() -> None:
    """A finding whose owner_wave ran (even if it failed) keeps its
    original verdict — DEFERRED is reserved for waves that never ran."""
    from agent_team_v15.audit_models import AuditFinding
    from agent_team_v15.wave_ownership import compute_finding_status

    finding = AuditFinding.from_dict({
        "finding_id": "F-009",
        "severity": "CRITICAL",
        "verdict": "FAIL",
        "summary": "Wave B build failure",
        "file_path": "apps/api/Dockerfile",
    })
    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        # Wave B FAILED but it executed — should not become DEFERRED.
        failed_waves_per_milestone={"milestone-1": "B"},
    )
    assert finding.owner_wave == "B"
    assert compute_finding_status(finding, state) == "FAIL"


def test_wave_agnostic_findings_are_never_deferred() -> None:
    """A wave-agnostic finding has no owner-wave; it can never be
    DEFERRED — the audit team must always treat it as actionable."""
    from agent_team_v15.audit_models import AuditFinding
    from agent_team_v15.wave_ownership import compute_finding_status

    finding = AuditFinding.from_dict({
        "finding_id": "AGN-001",
        "severity": "HIGH",
        "verdict": "FAIL",
        "summary": "package.json drift",
        "file_path": "package.json",
    })
    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        failed_waves_per_milestone={"milestone-1": "B"},
    )
    assert finding.owner_wave == "wave-agnostic"
    assert compute_finding_status(finding, state) == "FAIL"


def test_convergence_ratio_excludes_deferred_findings() -> None:
    """Convergence ratio is computed over executed-wave findings only."""
    from agent_team_v15.audit_models import AuditFinding
    from agent_team_v15.wave_ownership import compute_filtered_convergence_ratio

    findings = []
    # 5 findings on Wave B (executed → counted). 1 PASS, 4 FAIL.
    for i in range(5):
        findings.append(AuditFinding.from_dict({
            "finding_id": f"B-{i}",
            "severity": "CRITICAL",
            "verdict": "PASS" if i == 0 else "FAIL",
            "summary": f"b{i}",
            "file_path": f"apps/api/src/m{i}.ts",
        }))
    # 5 findings on Wave D (never executed → DEFERRED, excluded).
    for i in range(5):
        findings.append(AuditFinding.from_dict({
            "finding_id": f"D-{i}",
            "severity": "CRITICAL",
            "verdict": "FAIL",
            "summary": f"d{i}",
            "file_path": f"apps/web/src/m{i}.tsx",
        }))
    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        failed_waves_per_milestone={"milestone-1": "B"},
    )
    # Filtered total = 5 (B only); passed = 1; ratio = 0.2.
    ratio = compute_filtered_convergence_ratio(findings, state)
    assert ratio == pytest.approx(0.2)


def test_convergence_ratio_zero_when_no_executed_findings() -> None:
    """When all findings are DEFERRED, the filtered ratio is 0.0
    (degenerate input — no executed-wave signal to converge on)."""
    from agent_team_v15.audit_models import AuditFinding
    from agent_team_v15.wave_ownership import compute_filtered_convergence_ratio

    findings = [
        AuditFinding.from_dict({
            "finding_id": "D-1",
            "severity": "CRITICAL",
            "verdict": "FAIL",
            "summary": "d1",
            "file_path": "apps/web/src/foo.tsx",
        }),
    ]
    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
    )
    assert compute_filtered_convergence_ratio(findings, state) == 0.0


# ---------------------------------------------------------------------------
# AC4 — _classify_fix_features skips features all-DEFERRED
# ---------------------------------------------------------------------------


def test_classify_fix_features_marks_owner_wave_deferred(tmp_path) -> None:
    """When every file in a feature maps to a non-executed wave, the
    classifier tags ``skip_reason="owner_wave_deferred"`` and records
    the deferred-to wave letter."""
    from agent_team_v15.fix_executor import _classify_fix_features

    fix_prd = (
        "## Features\n\n"
        "### F-FIX-001: missing locales\n"
        "[SEVERITY: CRITICAL]\n"
        "[EXECUTION_MODE: patch]\n\n"
        "Description.\n\n"
        "#### Files to Modify\n"
        "- `apps/web/locales/en/common.json`\n"
        "- `apps/web/src/middleware.ts`\n\n"
        "#### Acceptance Criteria\n"
        "- AC-FIX-001: do the thing\n"
    )
    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        failed_waves_per_milestone={"milestone-1": "B"},
    )

    features = _classify_fix_features(fix_prd, str(tmp_path), run_state=state)
    assert features, "expected one feature parsed"
    feat = features[0]
    assert feat.get("skip_reason") == "owner_wave_deferred"
    assert feat.get("deferred_to_wave") == "D"


def test_classify_fix_features_does_not_mark_when_any_file_executed(tmp_path) -> None:
    """If at least one file in the feature maps to an executed wave,
    the feature is NOT all-deferred and stays dispatchable."""
    from agent_team_v15.fix_executor import _classify_fix_features

    fix_prd = (
        "## Features\n\n"
        "### F-FIX-001: mixed feature\n"
        "[SEVERITY: HIGH]\n"
        "[EXECUTION_MODE: patch]\n\n"
        "Description.\n\n"
        "#### Files to Modify\n"
        "- `apps/api/src/foo.ts`\n"
        "- `apps/web/src/bar.tsx`\n\n"
        "#### Acceptance Criteria\n"
        "- AC-FIX-001: x\n"
    )
    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        failed_waves_per_milestone={"milestone-1": "B"},
    )

    features = _classify_fix_features(fix_prd, str(tmp_path), run_state=state)
    assert features
    feat = features[0]
    assert feat.get("skip_reason") != "owner_wave_deferred"
    assert "deferred_to_wave" not in feat


def test_classify_fix_features_back_compat_without_run_state(tmp_path) -> None:
    """Legacy callers that don't pass run_state get pre-Phase-4.3
    behaviour (no owner_wave classification)."""
    from agent_team_v15.fix_executor import _classify_fix_features

    fix_prd = (
        "## Features\n\n"
        "### F-FIX-001: legacy\n"
        "[SEVERITY: HIGH]\n"
        "[EXECUTION_MODE: patch]\n\n"
        "Description.\n\n"
        "#### Files to Modify\n"
        "- `apps/web/src/foo.tsx`\n\n"
        "#### Acceptance Criteria\n"
        "- AC-FIX-001: x\n"
    )

    features = _classify_fix_features(fix_prd, str(tmp_path))
    assert features
    feat = features[0]
    # No owner_wave_deferred tag because run_state was not supplied.
    assert feat.get("skip_reason") != "owner_wave_deferred"


def test_classify_fix_features_logs_fix_deferred_warning(tmp_path, capsys) -> None:
    """The classifier emits a ``[FIX-DEFERRED]`` log line for each
    skipped feature so operators can audit the wave-awareness gate
    after a run."""
    from agent_team_v15.fix_executor import _classify_fix_features

    fix_prd = (
        "## Features\n\n"
        "### F-FIX-001: missing chassis\n"
        "[SEVERITY: CRITICAL]\n"
        "[EXECUTION_MODE: patch]\n\n"
        "Description.\n\n"
        "#### Files to Modify\n"
        "- `apps/web/src/middleware.ts`\n\n"
        "#### Acceptance Criteria\n"
        "- AC-FIX-001: x\n"
    )
    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        failed_waves_per_milestone={"milestone-1": "B"},
    )

    _classify_fix_features(fix_prd, str(tmp_path), run_state=state)
    captured = capsys.readouterr()
    assert "[FIX-DEFERRED]" in captured.out
    assert "missing chassis" in captured.out
    assert "Wave D" in captured.out or "wave D" in captured.out


def test_classify_fix_features_no_target_files_takes_precedence(tmp_path) -> None:
    """When a feature has no files at all, Phase 3.5's
    ``no_target_files`` ship-block stays first — owner_wave_deferred
    only applies when files exist."""
    from agent_team_v15.fix_executor import _classify_fix_features

    fix_prd = (
        "## Features\n\n"
        "### F-FIX-001: prose-only finding\n"
        "[SEVERITY: HIGH]\n"
        "[EXECUTION_MODE: patch]\n\n"
        "Build halted in orchestration phase. No file to fix.\n\n"
        "#### Acceptance Criteria\n"
        "- AC-FIX-001: investigate\n"
    )
    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        failed_waves_per_milestone={"milestone-1": "B"},
    )

    features = _classify_fix_features(fix_prd, str(tmp_path), run_state=state)
    assert features
    feat = features[0]
    assert feat.get("skip_reason") == "no_target_files"


# ---------------------------------------------------------------------------
# AC5 — Replay smoke: ≥4 critical findings get owner_wave="D" or "C" + DEFERRED
# ---------------------------------------------------------------------------


def test_replay_smoke_2026_04_26_findings_classification() -> None:
    """Load the real ``AUDIT_REPORT.json`` from the 2026-04-26 smoke;
    assert ≥4 of 11 critical findings get classified to Wave D or C
    (waves that never ran in this smoke) and are marked DEFERRED.

    Per §B.6 manual classification:
      Owner = Wave D: F-001, F-002, F-003, F-004, F-010 (5 critical)
      Owner = Wave C: F-005 (1 critical)
      Owner = Wave B: F-006..F-009, F-011 (5 critical; B did execute)

    Filtered convergence ratio must be > 0.0 — the executed-wave subset
    contains the 5 Wave B findings, none of which passed in this smoke.
    But the ratio is computed over the executed-wave subset only, so it
    is well-defined (5 critical Wave B findings, 0 PASS → 0.0 over the
    Wave B subset). The ratio over the full unfiltered set is ALSO 0.0
    today; the win is the SCOPE — Phase 4.5's audit-fix dispatch will
    only attempt the 5 Wave B findings instead of all 11.
    """
    from agent_team_v15.audit_models import AuditFinding
    from agent_team_v15.wave_ownership import compute_finding_status

    payload = json.loads((FIXTURE_ROOT / "AUDIT_REPORT.json").read_text(encoding="utf-8"))
    findings = [AuditFinding.from_dict(f) for f in payload.get("findings", [])]
    state = _load_run_state_from_smoke_fixture()

    critical = [f for f in findings if str(f.severity).upper() == "CRITICAL"]
    assert len(critical) == 11, f"expected 11 critical, got {len(critical)}"

    deferred_to_d_or_c = [
        f for f in critical
        if f.owner_wave in ("D", "C")
        and compute_finding_status(f, state) == "DEFERRED"
    ]
    assert len(deferred_to_d_or_c) >= 4, (
        f"expected ≥4 critical findings deferred to Wave D or C; "
        f"got {len(deferred_to_d_or_c)}: {[(f.finding_id, f.owner_wave) for f in deferred_to_d_or_c]}"
    )

    # Sanity: at least one critical finding owns Wave B and is NOT
    # DEFERRED (Wave B did execute even though it failed).
    wave_b_critical = [
        f for f in critical
        if f.owner_wave == "B"
        and compute_finding_status(f, state) != "DEFERRED"
    ]
    assert len(wave_b_critical) >= 1


# ---------------------------------------------------------------------------
# AC6 — Backward-compat: existing callers without owner_wave info get
# "wave-agnostic" default.
# ---------------------------------------------------------------------------


def test_backward_compat_audit_finding_constructor_default_owner_wave() -> None:
    """Constructing AuditFinding directly without owner_wave defaults
    to wave-agnostic (no breaking change for existing callers)."""
    from agent_team_v15.audit_models import AuditFinding

    finding = AuditFinding(
        finding_id="X",
        auditor="scorer",
        requirement_id="",
        verdict="FAIL",
        severity="LOW",
        summary="anything",
    )
    assert finding.owner_wave == "wave-agnostic"


# ---------------------------------------------------------------------------
# Config flag — kill switch
# ---------------------------------------------------------------------------


def test_audit_team_config_exposes_audit_wave_awareness_flag_default_true() -> None:
    """The kill-switch ``audit_wave_awareness_enabled`` defaults to
    True so Phase 4.3 ships in the on-state. Operators flip to False to
    restore pre-Phase-4.3 wave-blind behaviour."""
    from agent_team_v15.config import AuditTeamConfig

    cfg = AuditTeamConfig()
    assert cfg.audit_wave_awareness_enabled is True


# ---------------------------------------------------------------------------
# is_owner_wave_executed — semantics
# ---------------------------------------------------------------------------


def test_is_owner_wave_executed_true_for_completed_wave() -> None:
    from agent_team_v15.wave_ownership import is_owner_wave_executed

    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A", "B"]},
    )
    assert is_owner_wave_executed("A", state) is True
    assert is_owner_wave_executed("B", state) is True


def test_is_owner_wave_executed_true_for_failed_wave() -> None:
    """A wave that ran-and-failed (``failed_wave``) still counts as
    executed; the ``DEFERRED`` carve-out is reserved for waves that
    NEVER started."""
    from agent_team_v15.wave_ownership import is_owner_wave_executed

    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        failed_waves_per_milestone={"milestone-1": "B"},
    )
    assert is_owner_wave_executed("B", state) is True


def test_is_owner_wave_executed_false_when_wave_never_ran() -> None:
    from agent_team_v15.wave_ownership import is_owner_wave_executed

    state = _load_run_state(
        completed_waves_per_milestone={"milestone-1": ["A"]},
        failed_waves_per_milestone={"milestone-1": "B"},
    )
    assert is_owner_wave_executed("D", state) is False
    assert is_owner_wave_executed("C", state) is False


def test_is_owner_wave_executed_wave_agnostic_always_true() -> None:
    """``wave-agnostic`` is always considered executed — these findings
    don't have a wave to defer to."""
    from agent_team_v15.wave_ownership import is_owner_wave_executed

    state = _load_run_state(completed_waves_per_milestone={})
    assert is_owner_wave_executed("wave-agnostic", state) is True


def test_is_owner_wave_executed_handles_missing_run_state() -> None:
    """Defensive: a None run_state is treated as 'no wave info' — every
    wave letter is reported as not-executed (so audit-team falls back
    to legacy unfiltered semantics — the kill switch handles the
    same-day rollback case)."""
    from agent_team_v15.wave_ownership import is_owner_wave_executed

    assert is_owner_wave_executed("B", None) is False
    # wave-agnostic still wins.
    assert is_owner_wave_executed("wave-agnostic", None) is True


# ---------------------------------------------------------------------------
# audit_team.py — convergence ratio filter is wired into the public surface
# ---------------------------------------------------------------------------


def test_audit_team_module_exposes_filtered_convergence_helper() -> None:
    """``audit_team`` re-exports ``compute_filtered_convergence_ratio``
    so callers that already import from ``audit_team`` (e.g. cli's
    audit-loop) can pick up the filter without a new import path."""
    import agent_team_v15.audit_team as audit_team

    assert hasattr(audit_team, "compute_filtered_convergence_ratio")
    # Smoke check: callable and accepts a list + run_state.
    state = _load_run_state(completed_waves_per_milestone={"m": ["A"]})
    assert audit_team.compute_filtered_convergence_ratio([], state) == 0.0
