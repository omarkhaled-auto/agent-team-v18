"""Phase 5.1 pipeline-upgrade — audit termination scoring fix (R-#33 + R-#34).

Covers acceptance criteria AC1-AC9 from
``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §D.5 plus a
fail-closed test for invalid scale with no parseable findings:

* AC1 + AC3: ``should_terminate_reaudit`` normalizes raw 0-``max_score``
  ``score.score`` to a percentage before comparing against the
  percentage threshold. Raw 612/1000 with 3 CRITICAL findings does
  NOT terminate "healthy"; raw 870/1000 with 0 findings does (87% >
  85%).
* AC2 + AC7: canonical compute path (``max_score=100``, populated
  ``total_items``) still terminates "healthy" when score >= threshold
  AND ``critical_count == 0``. The post-parse normalizer is a no-op
  for the canonical compute output.
* AC4: replay M1 smoke shape — dict score with zeroed counters and
  populated ``by_severity`` ``{CRIT: 3, HIGH: 10, MEDIUM: 9, LOW: 6}``
  → ``AuditScore.critical_count == 3, high_count == 10`` after
  ``AuditReport.from_json``.
* AC5: flat-score AUDIT_REPORT.json with top-level ``finding_counts``
  → counters populated from ``finding_counts``.
* AC6: flat-score AUDIT_REPORT.json with no ``finding_counts`` and no
  ``by_severity`` but a populated findings list → counters populated
  by tallying severities from findings.
* AC8: regression check ``current.score < previous.score - 10`` also
  normalizes both sides — ``prev = 80/100 (80%)`` vs
  ``cur = 600/1000 (60%)`` triggers regression because the percentage
  delta is 20pp; without normalization the check would compare 600 vs
  70 and miss the regression.
* AC9: M2 smoke shape — dict score with ``score=525, max_score=0,
  by_severity={}`` and 28 parsed findings (4 CRITICAL) → normalizer
  recomputes via ``AuditScore.compute(findings)``, yielding
  ``max_score=100`` and ``critical_count=4``.

Plus the user-required fail-closed test:

* ``test_audit_report_from_json_invalid_scale_no_findings_raises``:
  ``score != 0`` AND ``max_score == 0`` AND ``findings == []`` →
  ``InvalidAuditScoreScale`` raised at parse time. Refuses to
  synthesize ``max_score=100``.

Plus a replay-smoke fixture using ``tests/fixtures/smoke_2026_04_28/``
copied verbatim from
``v18 test runs/m1-hardening-smoke-20260428-112339/.agent-team/milestone-1/.agent-team/AUDIT_REPORT.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.audit_models import (
    AuditFinding,
    AuditReport,
    AuditScore,
    InvalidAuditScoreScale,
    _normalize_score_severity_counts,
)
from agent_team_v15.audit_team import _score_pct, should_terminate_reaudit


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_score(
    *,
    score: float,
    max_score: int,
    critical_count: int = 0,
    high_count: int = 0,
    medium_count: int = 0,
    low_count: int = 0,
    info_count: int = 0,
    total_items: int = 0,
    passed: int = 0,
    failed: int = 0,
    partial: int = 0,
    health: str = "",
) -> AuditScore:
    """Build an AuditScore with explicit fields. Direct construction
    bypasses ``from_dict`` / ``compute`` so tests can lock raw vs.
    percentage scenarios without going through the normalizer.
    """
    return AuditScore(
        total_items=total_items,
        passed=passed,
        failed=failed,
        partial=partial,
        critical_count=critical_count,
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        info_count=info_count,
        score=score,
        health=health,
        max_score=max_score,
    )


def _make_finding(severity: str, finding_id: str, requirement_id: str) -> AuditFinding:
    """Build an AuditFinding with explicit severity for fixture-replay tests."""
    return AuditFinding(
        finding_id=finding_id,
        auditor="requirements",
        requirement_id=requirement_id,
        verdict="FAIL",
        severity=severity,
        summary=f"{finding_id} synthetic",
    )


def _findings_for_severity_distribution(
    *,
    critical: int,
    high: int,
    medium: int,
    low: int,
    info: int = 0,
) -> list[AuditFinding]:
    """Synthesize findings totalling the requested severity distribution.

    Each finding gets a unique ``requirement_id`` so ``AuditScore.compute``
    counts them as separate items (its req-verdict map dedups on
    requirement_id; same req_id → only the worst verdict counts).
    """
    findings: list[AuditFinding] = []
    counter = 0
    for sev, n in (
        ("CRITICAL", critical),
        ("HIGH", high),
        ("MEDIUM", medium),
        ("LOW", low),
        ("INFO", info),
    ):
        for _ in range(n):
            counter += 1
            findings.append(
                _make_finding(
                    severity=sev,
                    finding_id=f"F-{counter:03d}",
                    requirement_id=f"REQ-{counter:03d}",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# AC1 + AC3: should_terminate_reaudit normalizes raw score to percentage
# ---------------------------------------------------------------------------


def test_should_terminate_reaudit_normalizes_raw_score_to_percentage_not_healthy():
    """AC1: raw score=612 / max_score=1000 with 3 CRITICAL findings →
    61.2% < 85% threshold → NOT healthy, even though raw 612 >= 85.

    This is the canonical M1 hardening-smoke regression: pre-Phase-5.1
    the comparison ``612 >= 85`` was True → cycle 1 exited healthy →
    zero fixes dispatched → milestone marked COMPLETE with 3
    CRITICAL findings unaddressed.
    """
    current = _make_score(score=612.0, max_score=1000, critical_count=3, high_count=10)

    stop, reason = should_terminate_reaudit(
        current,
        previous_score=None,
        cycle=1,
        max_cycles=3,
        healthy_threshold=85.0,
    )

    assert stop is False
    assert reason == ""


def test_should_terminate_reaudit_normalizes_raw_score_to_percentage_healthy():
    """AC3: raw score=870 / max_score=1000 with 0 CRITICAL findings →
    87% >= 85% threshold → healthy. The legitimate raw-passes-after-
    normalization scenario.
    """
    current = _make_score(score=870.0, max_score=1000, critical_count=0)

    stop, reason = should_terminate_reaudit(
        current,
        previous_score=None,
        cycle=1,
        max_cycles=3,
        healthy_threshold=85.0,
    )

    assert stop is True
    assert reason == "healthy"


# ---------------------------------------------------------------------------
# AC2 + AC7: canonical compute path still works (backward-compat)
# ---------------------------------------------------------------------------


def test_should_terminate_reaudit_canonical_percentage_path_still_works():
    """AC2: canonical compute path (max_score=100, score is already a
    percentage) terminates healthy when score >= threshold AND
    critical_count == 0. ``_score_pct`` returns the score unchanged
    when ``max_score == 100``.
    """
    current = _make_score(score=92.0, max_score=100, critical_count=0)

    stop, reason = should_terminate_reaudit(
        current,
        previous_score=None,
        cycle=1,
        max_cycles=3,
        healthy_threshold=90.0,
    )

    assert stop is True
    assert reason == "healthy"


def test_audit_report_from_json_canonical_compute_path_unaffected():
    """AC7: canonical AUDIT_REPORT.json (computed score, max_score=100,
    populated by_severity from build_report) round-trips without the
    normalizer changing semantic counts.

    AuditScore.compute populates critical_count etc. from findings;
    by_severity from build_report's grouping has the same counts.
    Normalizer's by_severity-source lookup confirms-rather-than-changes.
    """
    findings = _findings_for_severity_distribution(critical=1, high=2, medium=3, low=4)
    score = AuditScore.compute(findings)
    # Build canonical-shape JSON: dict score + by_severity grouping by index.
    by_severity: dict[str, list[int]] = {}
    for i, f in enumerate(findings):
        by_severity.setdefault(f.severity, []).append(i)

    blob = json.dumps({
        "audit_id": "AR-AC7",
        "cycle": 1,
        "auditors_deployed": ["requirements"],
        "findings": [f.to_dict() for f in findings],
        "score": score.to_dict(),
        "by_severity": by_severity,
    })

    report = AuditReport.from_json(blob)

    assert report.score.critical_count == 1
    assert report.score.high_count == 2
    assert report.score.medium_count == 3
    assert report.score.low_count == 4
    assert report.score.max_score == 100
    # Canonical compute score: 0 PASS / 0 PARTIAL / 10 FAIL on 10 distinct
    # requirements → score = (0*100 + 0*50)/10 = 0.0.
    assert report.score.score == 0.0


# ---------------------------------------------------------------------------
# AC4: M1 dict-shape repair from by_severity
# ---------------------------------------------------------------------------


def test_audit_report_from_json_repairs_dict_score_zero_counts_from_by_severity():
    """AC4: canonical M1 hardening-smoke shape — dict score with zeroed
    severity counters but a populated top-level ``by_severity`` →
    normalizer reads by_severity and replaces the zero counters.

    Smoke shape (verbatim, see
    ``tests/fixtures/smoke_2026_04_28/AUDIT_REPORT.json``):
        score = {score: 612.0, max_score: 1000,
                 critical_count: 0, high_count: 0, ...}
        by_severity = {"CRITICAL": 3, "HIGH": 10,
                       "MEDIUM": 9, "LOW": 6}
        findings = [28 entries: 3 CRIT / 10 HIGH / 9 MED / 6 LOW]
    """
    findings = _findings_for_severity_distribution(
        critical=3, high=10, medium=9, low=6
    )

    blob = json.dumps({
        "audit_id": "AR-AC4",
        "cycle": 1,
        "auditors_deployed": ["requirements", "technical", "interface"],
        "findings": [f.to_dict() for f in findings],
        "score": {
            "total_items": 0,
            "passed": 0,
            "failed": 0,
            "partial": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "info_count": 0,
            "score": 612.0,
            "health": "",
            "max_score": 1000,
        },
        "by_severity": {
            "CRITICAL": 3,
            "HIGH": 10,
            "MEDIUM": 9,
            "LOW": 6,
        },
    })

    report = AuditReport.from_json(blob)

    assert report.score.critical_count == 3
    assert report.score.high_count == 10
    assert report.score.medium_count == 9
    assert report.score.low_count == 6
    # Score scale preserved (raw 612/1000); _score_pct converts at
    # comparison sites, the normalizer does NOT mutate score-storage.
    assert report.score.score == 612.0
    assert report.score.max_score == 1000

    # End-to-end gate: should_terminate_reaudit must NOT exit healthy
    # at cycle 1 on this shape (the canonical regression).
    stop, reason = should_terminate_reaudit(
        report.score,
        previous_score=None,
        cycle=1,
        max_cycles=3,
        healthy_threshold=85.0,
    )
    assert stop is False
    assert reason == ""


# ---------------------------------------------------------------------------
# AC5: finding_counts source (case-insensitive)
# ---------------------------------------------------------------------------


def test_audit_report_from_json_populates_critical_count_from_finding_counts():
    """AC5: synthetic AUDIT_REPORT.json with flat top-level ``score`` +
    ``max_score`` (flat-score branch) and a top-level
    ``finding_counts`` map → normalizer reads ``finding_counts`` and
    populates severity counters.

    Locks the case-insensitive key handling: lowercase ``critical``
    keys map to ``CRITICAL`` counter.
    """
    findings = _findings_for_severity_distribution(
        critical=3, high=10, medium=9, low=6
    )

    blob = json.dumps({
        "audit_id": "AR-AC5",
        "cycle": 1,
        "auditors_deployed": ["requirements"],
        "findings": [f.to_dict() for f in findings],
        "score": 612,
        "max_score": 1000,
        "finding_counts": {
            "critical": 3,
            "high": 10,
            "medium": 9,
            "low": 6,
        },
    })

    report = AuditReport.from_json(blob)

    assert report.score.critical_count == 3
    assert report.score.high_count == 10
    assert report.score.medium_count == 9
    assert report.score.low_count == 6
    assert report.score.score == 612.0
    assert report.score.max_score == 1000


# ---------------------------------------------------------------------------
# AC6: findings-list fallback (no finding_counts, no by_severity)
# ---------------------------------------------------------------------------


def test_audit_report_from_json_populates_critical_count_from_findings_list_fallback():
    """AC6: synthetic AUDIT_REPORT.json with flat score, no
    ``finding_counts``, no ``by_severity`` (or empty), but a
    populated findings list → normalizer tallies severities from
    findings.
    """
    findings = _findings_for_severity_distribution(
        critical=2, high=4, medium=1, low=0
    )

    blob = json.dumps({
        "audit_id": "AR-AC6",
        "cycle": 1,
        "auditors_deployed": ["requirements"],
        "findings": [f.to_dict() for f in findings],
        "score": 350,
        "max_score": 1000,
        # No finding_counts, no by_severity — normalizer must fall
        # through to the findings-list source.
    })

    report = AuditReport.from_json(blob)

    assert report.score.critical_count == 2
    assert report.score.high_count == 4
    assert report.score.medium_count == 1
    assert report.score.low_count == 0
    assert report.score.score == 350.0
    assert report.score.max_score == 1000


# ---------------------------------------------------------------------------
# AC8: regression check normalizes both scales
# ---------------------------------------------------------------------------


def test_should_terminate_reaudit_regression_check_normalizes_both_scales():
    """AC8: Cond 3 (``current.score < previous.score - 10``) normalizes
    both sides via ``_score_pct``.

    Without normalization the comparison ``600 < 80 - 10 = 70`` would
    be False — no regression detected — even though the percentage
    delta is 20pp (80% → 60%). With normalization the comparison is
    ``60 < 80 - 10 = 70`` → True → regression triggered.

    Locks the apples-to-apples invariant for cross-cycle comparisons
    when prior cycle's score was on a percentage scale (max_score=100,
    canonical compute) and current cycle's score is on a raw scale
    (max_score=1000, scorer-LLM dict output).
    """
    previous = _make_score(score=80.0, max_score=100, critical_count=0)
    current = _make_score(score=600.0, max_score=1000, critical_count=0)

    stop, reason = should_terminate_reaudit(
        current,
        previous_score=previous,
        cycle=2,
        max_cycles=5,  # avoid Cond 2 (cycle >= max_cycles) firing first
        healthy_threshold=90.0,
    )

    assert stop is True
    assert reason == "regression"


# ---------------------------------------------------------------------------
# AC9: M2 invalid-scale recompute
# ---------------------------------------------------------------------------


def test_audit_report_from_json_recomputes_invalid_scale_from_findings():
    """AC9: M2 hardening-smoke shape — dict score with
    ``score=525, max_score=0, critical_count=0, by_severity={}`` and
    28 parsed findings (4 CRITICAL, 10 HIGH, 11 MEDIUM, 3 LOW) →
    normalizer detects invalid scale (``max_score <= 0``) AND has
    findings → recomputes via ``AuditScore.compute(findings)``.

    Post-normalization: ``max_score=100`` (canonical compute return),
    ``critical_count=4`` (from compute's severity tally on the
    findings list). ``should_terminate_reaudit`` then sees the
    repaired scale, not bogus 525/0 or 525/100.
    """
    findings = _findings_for_severity_distribution(
        critical=4, high=10, medium=11, low=3
    )

    blob = json.dumps({
        "audit_id": "AR-AC9",
        "cycle": 1,
        "auditors_deployed": ["requirements", "technical"],
        "findings": [f.to_dict() for f in findings],
        "score": {
            "total_items": 0,
            "passed": 0,
            "failed": 0,
            "partial": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "info_count": 0,
            "score": 525.0,
            "health": "",
            "max_score": 0,
        },
        "by_severity": {},
    })

    report = AuditReport.from_json(blob)

    assert report.score.max_score == 100  # canonical compute path
    assert report.score.critical_count == 4
    assert report.score.high_count == 10
    assert report.score.medium_count == 11
    assert report.score.low_count == 3
    # compute's score formula: (passed*100 + partial*50) / total. All 28
    # findings are FAIL on distinct requirements → score = 0.0.
    assert report.score.score == 0.0

    # End-to-end: should_terminate_reaudit must not exit healthy with
    # 4 CRITICAL findings on the repaired scale.
    stop, reason = should_terminate_reaudit(
        report.score,
        previous_score=None,
        cycle=1,
        max_cycles=3,
        healthy_threshold=85.0,
    )
    assert stop is False
    assert reason == ""


# ---------------------------------------------------------------------------
# Fail-closed: invalid scale + no findings (per user constraint #2)
# ---------------------------------------------------------------------------


def test_audit_report_from_json_invalid_scale_no_findings_raises_invalid_scale():
    """User constraint #2: ``score != 0`` AND ``max_score == 0`` AND
    no parseable findings → ``InvalidAuditScoreScale`` raised at
    ``from_json`` time. Refuse to synthesize ``max_score=100`` from
    nothing.

    The empty-audit placeholder shape (``score=0, max_score=0,
    findings=[]``) is preserved by the normalizer's
    ``has_real_signal`` gate; THIS test locks the unrecoverable
    branch (real score signal + broken scale + nothing to recompute
    from).
    """
    blob = json.dumps({
        "audit_id": "AR-FAIL",
        "cycle": 1,
        "auditors_deployed": ["requirements"],
        "findings": [],  # nothing to recompute from
        "score": 525.0,
        "max_score": 0,
    })

    with pytest.raises(InvalidAuditScoreScale):
        AuditReport.from_json(blob)


def test_audit_report_from_json_empty_audit_placeholder_passes_through():
    """Sibling to the fail-closed test: the empty-audit shape
    (``score=0, max_score=0, findings=[]``) passes through unchanged.

    Locks the F-EDGE-003 backward-compat contract — pre-Phase-5
    callers and fixtures synthesize empty AuditReports as a
    placeholder; the normalizer must not raise on them.
    """
    blob = json.dumps({
        "audit_id": "AR-EMPTY",
        "cycle": 1,
    })

    report = AuditReport.from_json(blob)

    assert report.findings == []
    assert report.score.score == 0.0
    assert report.score.max_score == 0


# ---------------------------------------------------------------------------
# _score_pct fail-closed: defense-in-depth
# ---------------------------------------------------------------------------


def test_score_pct_raises_invalid_scale_on_unrepaired_zero_max_score():
    """``_score_pct`` raises ``InvalidAuditScoreScale`` when the score
    has ``max_score <= 0`` — defense-in-depth for hand-constructed
    AuditScore instances that bypass ``from_json``'s normalizer.

    A real AuditScore reaching this site with max_score=0 is a
    contract violation: the normalizer should have repaired or raised.
    The helper refuses to invent a denominator.
    """
    score = _make_score(score=525.0, max_score=0, critical_count=0)

    with pytest.raises(InvalidAuditScoreScale):
        _score_pct(score)


# ---------------------------------------------------------------------------
# Replay smoke fixture (frozen 2026-04-28 evidence)
# ---------------------------------------------------------------------------


_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "smoke_2026_04_28"


def test_replay_smoke_2026_04_28_cycle_1_does_not_terminate_healthy():
    """Replay fixture using verbatim AUDIT_REPORT.json from the
    2026-04-28 M1 hardening smoke (run-dir
    ``v18 test runs/m1-hardening-smoke-20260428-112339/``).

    Pre-Phase-5.1: ``should_terminate_reaudit`` returned
    ``(True, "healthy")`` at cycle 1 because raw 612 was compared
    directly against percentage threshold 85 → exit healthy → 0 fix
    dispatches → milestone "completed" with 3 CRITICAL findings
    unaddressed. The post-cycle-1 fix-dispatch site at
    ``cli.py:8503`` was unreachable.

    Post-Phase-5.1: from_json's normalizer reads the populated
    ``by_severity={CRITICAL:3, HIGH:10, ...}`` and replaces the dict
    score's zero counters; ``should_terminate_reaudit`` then sees
    ``critical_count=3`` and ``_score_pct`` normalizes 612/1000 →
    61.2% < 85% → NOT healthy.
    """
    fixture = _FIXTURE_ROOT / "AUDIT_REPORT.json"
    assert fixture.is_file(), (
        f"Phase 5.1 frozen smoke fixture missing: {fixture}. "
        f"Copy from 'v18 test runs/m1-hardening-smoke-20260428-112339/"
        f".agent-team/milestone-1/.agent-team/AUDIT_REPORT.json'."
    )

    report = AuditReport.from_json(fixture.read_text(encoding="utf-8"))

    # Sanity: the fixture is the M1 dict-score shape.
    assert report.score.score == 612.0
    assert report.score.max_score == 1000

    # Phase 5.1 normalizer repaired the zeroed dict counters from
    # the populated by_severity={"CRITICAL": 3, "HIGH": 10, ...}.
    assert report.score.critical_count == 3
    assert report.score.high_count == 10
    assert report.score.medium_count == 9
    assert report.score.low_count == 6

    # The canonical regression: cycle 1 must NOT exit healthy.
    stop, reason = should_terminate_reaudit(
        report.score,
        previous_score=None,
        cycle=1,
        max_cycles=3,
        healthy_threshold=85.0,
    )
    assert stop is False
    assert reason == ""


def test_replay_smoke_2026_04_28_m2_recomputes_invalid_scale():
    """Replay fixture using verbatim AUDIT_REPORT.json from the M2
    half of the same hardening smoke. Locks Phase 5.1's
    invalid-scale recompute path on a shape ``AuditScore.from_dict``
    cannot handle natively (``max_score=0``, empty ``by_severity``,
    zero counters with 4 CRITICAL findings).
    """
    fixture = _FIXTURE_ROOT / "AUDIT_REPORT_M2.json"
    assert fixture.is_file()

    report = AuditReport.from_json(fixture.read_text(encoding="utf-8"))

    # Repaired via AuditScore.compute(findings).
    assert report.score.max_score == 100
    assert report.score.critical_count == 4

    # Cycle 1 still must not exit healthy on M2 either.
    stop, reason = should_terminate_reaudit(
        report.score,
        previous_score=None,
        cycle=1,
        max_cycles=3,
        healthy_threshold=85.0,
    )
    assert stop is False
    assert reason == ""


# ---------------------------------------------------------------------------
# Helper-level regression coverage (sanity locks)
# ---------------------------------------------------------------------------


def test_severity_counts_helpers_handle_canonical_to_json_by_severity_shape():
    """``_severity_counts_from_by_severity`` handles BOTH shapes:

    * ``{severity: int}``     — scorer-LLM smoke shape.
    * ``{severity: list[int]}`` — canonical to_json grouping.
    """
    # Scorer-LLM shape (M1 smoke).
    blob_int = json.dumps({
        "audit_id": "AR-SHAPE-INT",
        "cycle": 1,
        "findings": [
            _make_finding(severity="CRITICAL", finding_id="F-001",
                          requirement_id="REQ-001").to_dict(),
        ],
        "score": 100,
        "max_score": 1000,
        "by_severity": {"CRITICAL": 1, "HIGH": 0},
    })
    rep = AuditReport.from_json(blob_int)
    assert rep.score.critical_count == 1
    assert rep.score.high_count == 0

    # Canonical to_json shape (list of indices).
    blob_list = json.dumps({
        "audit_id": "AR-SHAPE-LIST",
        "cycle": 1,
        "findings": [
            _make_finding(severity="CRITICAL", finding_id="F-001",
                          requirement_id="REQ-001").to_dict(),
            _make_finding(severity="HIGH", finding_id="F-002",
                          requirement_id="REQ-002").to_dict(),
            _make_finding(severity="HIGH", finding_id="F-003",
                          requirement_id="REQ-003").to_dict(),
        ],
        "score": 100,
        "max_score": 1000,
        "by_severity": {"CRITICAL": [0], "HIGH": [1, 2]},
    })
    rep = AuditReport.from_json(blob_list)
    assert rep.score.critical_count == 1
    assert rep.score.high_count == 2


def test_normalize_score_severity_counts_returns_unchanged_when_all_sources_empty():
    """No finding_counts, no by_severity, no findings → normalizer
    returns the score unchanged (no replace, no raise).
    """
    score = _make_score(score=72.0, max_score=100, critical_count=5)
    result = _normalize_score_severity_counts(score, data={}, findings=[])
    assert result is score
    assert result.critical_count == 5
