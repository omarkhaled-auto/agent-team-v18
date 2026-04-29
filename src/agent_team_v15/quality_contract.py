"""Phase 5.5 §M.M1 + §H.3 — Quality Contract evaluator + single-resolver helper.

This module is **the only authorized function for quality-dependent terminal
status writes** on ``state.milestone_progress[id]``. It absorbs the
COMPLETE/DEGRADED/FAILED routing logic that was previously scattered across
five terminal sites in cli.py (Phase 5.4 threaded ``audit_fix_rounds``
manually at each site; Phase 5.5 consolidates).

Direct ``update_milestone_progress`` calls writing FAILED for hard-execution
failure (architecture gate, preflight, exception handler) remain allowed —
they don't have an audit_report and don't need contract evaluation.

Functions
---------

* :func:`_evaluate_quality_contract` — pure decision function. Returns
  ``(final_status, audit_status, unresolved_count, debt_severity)``.
  Reuses :func:`agent_team_v15.audit_team.cascade_quality_gate_blocks_complete`
  internally so the cascade gate's existing fixture-locked predicate is
  not duplicated.

* :func:`_finalize_milestone_with_quality_contract` — performs the write.
  Reads current ``audit_fix_rounds``; preserves it via REPLACE-preserve
  threading; resolves canonical AUDIT_REPORT.json path; populates all
  five Phase 5.3 quality fields; runs the layer-2 state-invariant
  validator.

  Accepts ``override_status`` + ``override_failure_reason`` for the two
  call patterns that pre-determine the terminal status:

  * ``8503`` audit-failure-anchor-restore helper (FAILED floor; caller
    supplies reason like ``regression``/``no_improvement``/
    ``cross_milestone_lock_violation``/``audit_fix_did_not_recover_build``).
  * ``6079``/``6094`` milestone-health-gate audit-score-override pair
    (DEGRADED/FAILED pre-decided; no audit_report in scope).

  When ``override_status`` is None (default), the resolver evaluates the
  Quality Contract from ``audit_report``.

* :func:`_max_severity` — helper computing the highest severity in a
  finding list.

* :func:`_warn_legacy_permissive_audit` — helper emitting the loud
  deprecation log when ``--legacy-permissive-audit`` allows a HIGH/CRITICAL
  milestone to ship as DEGRADED.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from .audit_models import AuditReport
    from .state import RunState


_SEVERITY_RANK: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
    "": 0,
}


_LEGACY_PERMISSIVE_AUDIT_DEPRECATION_LOG = (
    "[QUALITY-CONTRACT] Milestone %s: --legacy-permissive-audit active. "
    "%d unresolved FAIL finding(s), top severity %s, but routing to DEGRADED "
    "instead of FAILED (deprecated migration escape hatch). Address findings "
    "to migrate off this flag. Removal gate (Phase 5 §M.M15): ≥80%% live "
    "milestones clean for 4 consecutive weeks; ≥70%% confirmed-finding "
    "precision; no active CRITICAL suppression in audit_suppressions.json."
)


def _max_severity(findings) -> str:
    """Return the highest severity in a finding list, or ``""`` for empty."""

    best = ""
    best_rank = -1
    for f in findings or ():
        sev = str(getattr(f, "severity", "") or "").upper()
        rank = _SEVERITY_RANK.get(sev, 0)
        if rank > best_rank:
            best_rank = rank
            best = sev
    return best


def _warn_legacy_permissive_audit(
    milestone_id: str,
    unresolved_count: int,
    top_severity: str,
) -> None:
    """Emit the structured deprecation log line at WARNING level."""

    logger.warning(
        _LEGACY_PERMISSIVE_AUDIT_DEPRECATION_LOG,
        milestone_id,
        unresolved_count,
        top_severity or "UNKNOWN",
    )


def _resolve_canonical_audit_report_path(
    state: "RunState",
    milestone_id: str,
    cwd: Optional[str] = None,
) -> str:
    """Resolve the canonical post-Phase-5.2 AUDIT_REPORT.json path.

    Phase 5.2 canonical layout:
    ``<cwd-or-runroot>/.agent-team/milestones/<id>/.agent-team/AUDIT_REPORT.json``.

    Returns absolute path string when computable, ``""`` otherwise (caller
    threads ``""`` through ``audit_findings_path`` sentinel-skip — Phase 5.3
    contract).
    """

    base: Optional[Path] = None
    if cwd:
        base = Path(cwd)
    if base is None:
        # Fallback: derive from run_id if recorded; otherwise empty.
        return ""
    canonical = (
        base
        / ".agent-team"
        / "milestones"
        / milestone_id
        / ".agent-team"
        / "AUDIT_REPORT.json"
    )
    return str(canonical)


def _evaluate_quality_contract(
    audit_report: "AuditReport | None",
    run_state: "RunState",
    config,
    *,
    cwd: Optional[str] = None,
    milestone_id: Optional[str] = None,
) -> tuple[str, str, int, str]:
    """Phase 5.5 §H.3 — pure Quality Contract decision.

    Returns ``(final_status, audit_status, unresolved_count, debt_severity)``.

    Routes per Quality Contract §B:

    * No unresolved FAIL on executed waves → ``("COMPLETE", "clean", 0, "")``.
    * Unresolved FAIL exists but all ≤ MEDIUM → ``("DEGRADED", "degraded", N, sev)``.
    * ANY unresolved FAIL ≥ HIGH on executed waves → ``("FAILED", "failed", N, sev)``,
      unless ``config.v18.legacy_permissive_audit`` is True, in which case
      routes to ``("DEGRADED", "degraded", N, sev)`` and emits the deprecation log.
    * ``audit_report is None`` → ``("COMPLETE", "unknown", 0, "")`` (no signal;
      caller paths that have no audit context get the pre-Phase-5 self-verify
      semantics).

    DEFERRED findings (Phase 4.3 owner_wave-not-executed) are excluded from
    the unresolved set per :func:`agent_team_v15.wave_ownership.compute_finding_status`.

    Reuses :func:`agent_team_v15.audit_team.cascade_quality_gate_blocks_complete`
    for the HIGH/CRITICAL detection so its 7+ Phase 5.4 fixture contract
    stays load-bearing unchanged.
    """

    if audit_report is None:
        return ("COMPLETE", "unknown", 0, "")

    # Use findings-list filter directly per §H.3 plan code. The cascade
    # gate at audit_team.cascade_quality_gate_blocks_complete operates on
    # AuditScore severity counters which do NOT reflect DEFERRED or
    # operator-rejected (suppression) filtering. The Quality Contract
    # MUST filter both before deciding routing, so the resolver runs the
    # filter itself. The cascade gate's coarse check still drives the
    # Phase 4.5 cascade epilogue's reason-string selection upstream of
    # this resolver call (caller pre-evaluates the contract there to pick
    # the right reason). For the canonical 2026-04-28 smoke shape (5
    # CRITICAL + 8 HIGH FAIL, no DEFERRED, no rejected), both paths route
    # to FAILED — byte-identical preservation.
    from .wave_ownership import compute_finding_status

    # §M.M13 — load the suppression registry so we can validate
    # ``confirmation_status="rejected"`` claims on disk before excluding
    # the finding from the unresolved set. A finding marked ``rejected``
    # in AUDIT_REPORT.json is the operator's INTENT; the registry is the
    # AUTHORITATIVE record of approved suppressions. When cwd +
    # milestone_id are supplied, a rejected finding is excluded only if
    # the registry validates it. When not supplied (e.g., legacy lint
    # callers), the registry isn't consulted — and the SAFE behaviour is
    # to DISTRUST the disk-shape "rejected" claim and keep the finding
    # counted, so audit findings cannot bypass the contract via a
    # disk-edit alone.
    registry: dict | None = None
    if cwd and milestone_id:
        try:
            from .finding_confirmation import load_suppression_registry
            registry = load_suppression_registry(Path(cwd))
        except Exception:
            registry = None

    findings = list(getattr(audit_report, "findings", None) or ())
    unresolved_fail: list = []
    for f in findings:
        if str(getattr(f, "verdict", "") or "").upper() != "FAIL":
            continue
        # §M.M13 — operator-rejected findings excluded from the unresolved
        # count ONLY after the suppression registry validates the
        # rejection. Default ``"unconfirmed"`` keeps findings counted.
        # A bare ``"rejected"`` on disk without a registry entry does NOT
        # bypass the contract — Phase 5.5 closes the disk-edit loophole.
        if str(getattr(f, "confirmation_status", "unconfirmed") or "unconfirmed") == "rejected":
            if registry is not None and milestone_id:
                from .finding_confirmation import is_finding_suppressed
                finding_code = str(getattr(f, "finding_id", "") or "")
                if is_finding_suppressed(registry, finding_code, milestone_id):
                    continue
            # Either: registry not loaded (cwd/milestone_id absent) OR
            # registry doesn't validate this rejection. Don't trust
            # disk-shape alone; count the finding as unresolved.
        if compute_finding_status(f, run_state) == "DEFERRED":
            continue
        unresolved_fail.append(f)

    unresolved_count = len(unresolved_fail)

    if any(
        str(getattr(f, "severity", "") or "").upper() in ("CRITICAL", "HIGH")
        for f in unresolved_fail
    ):
        top_severity = _max_severity(unresolved_fail) or "HIGH"
        if getattr(getattr(config, "v18", None), "legacy_permissive_audit", False):
            return ("DEGRADED", "degraded", unresolved_count, top_severity)
        return ("FAILED", "failed", unresolved_count, top_severity)

    if unresolved_count > 0:
        # All unresolved are ≤ MEDIUM.
        return ("DEGRADED", "degraded", unresolved_count, _max_severity(unresolved_fail))

    return ("COMPLETE", "clean", 0, "")


def _finalize_milestone_with_quality_contract(
    state: "RunState",
    milestone_id: str,
    audit_report: "AuditReport | None",
    config,
    *,
    cwd: Optional[str] = None,
    override_status: Optional[str] = None,
    override_failure_reason: Optional[str] = None,
    failure_reason: Optional[str] = None,
    agent_team_dir: Optional[str] = None,
) -> tuple[str, str, int, str]:
    """Phase 5.5 §M.M1 — single resolver for quality-dependent terminal writes.

    Reads ``audit_fix_rounds`` from in-flight ``state.milestone_progress[id]``
    and threads it through the terminal write so REPLACE semantics don't
    clear the Phase 5.4 increment. Populates all five Phase 5.3 quality
    fields (status / audit_status / unresolved_findings_count /
    audit_debt_severity / audit_findings_path / audit_fix_rounds).

    Parameters
    ----------
    override_status : Optional[str]
        When supplied, overrides the Quality Contract decision verbatim.
        Used by:

        * The audit-failure-anchor-restore helper (cli.py:8503): caller
          passes ``override_status="FAILED"`` plus
          ``override_failure_reason=<regression|no_improvement|...>`` so
          anchor-restore failure paths cannot accidentally route through
          the contract to DEGRADED on low/medium-only findings.
        * The milestone-health-gate audit-score-override pair
          (cli.py:6079/6094): caller passes ``"DEGRADED"`` or ``"FAILED"``
          based on the in-wave audit-score (no audit_report yet; quality
          fields populated as best-effort sentinels).

        When None (default), the resolver evaluates the Quality Contract
        via :func:`_evaluate_quality_contract`.

    override_failure_reason : Optional[str]
        When supplied with ``override_status="FAILED"``, becomes the
        ``failure_reason`` on the terminal write. Preserved verbatim per
        the §M.M1 contract: caller-supplied reasons (regression /
        no_improvement / cross_milestone_lock_violation /
        audit_fix_did_not_recover_build) survive the resolver.

    failure_reason : Optional[str]
        Resolver-default failure_reason when the contract decides FAILED
        natively (e.g. cascade-FAILED with audit_fix_recovered_build_but_findings_remain).
        Ignored when ``override_failure_reason`` is supplied.

    agent_team_dir : Optional[str]
        Directory to call ``save_state`` against. When None, save_state
        is NOT called (caller is responsible) so existing
        save_state-after-update_milestone_progress patterns aren't
        double-fired.

    Returns
    -------
    tuple[str, str, int, str]
        ``(final_status, audit_status, unresolved_count, debt_severity)``
        — same shape as :func:`_evaluate_quality_contract`. Useful for
        callers that need to print the Quality Summary alongside the write.
    """

    from .state import save_state, update_completion_ratio, update_milestone_progress

    # In-flight failure_reason: when the audit-loop persisted a signal
    # like ``cost_cap_reached`` (Phase 5.4 §M.M3) ahead of this resolver
    # call, preserve it through the terminal write so operator-visible
    # QUALITY_DEBT entries can carry it. Caller-supplied
    # failure_reason / override_failure_reason still wins (the cascade
    # epilogue, for example, explicitly overwrites with
    # ``wave_fail_recovered`` / ``audit_fix_recovered_build_but_findings_remain``).
    progress = getattr(state, "milestone_progress", None) or {}
    _inflight_reason = ""
    _existing_entry = progress.get(milestone_id, {}) if isinstance(progress, dict) else {}
    if isinstance(_existing_entry, dict):
        _inflight_reason = str(_existing_entry.get("failure_reason", "") or "")

    # Resolve the routing decision: contract evaluation OR caller override.
    if override_status is None:
        final_status, audit_status, unresolved, severity = (
            _evaluate_quality_contract(
                audit_report, state, config,
                cwd=cwd, milestone_id=milestone_id,
            )
        )
        # Failure-reason precedence (§M.M2 Rule 3 + §M.M3 cost_cap_reached):
        #   1. Caller-supplied `failure_reason` wins (cascade epilogue uses
        #      this to set wave_fail_recovered or audit_fix_recovered_build_but_findings_remain).
        #   2. In-flight `state.milestone_progress[id].failure_reason` is
        #      preserved on FAILED (carries cost_cap_reached etc. into the
        #      operator-visible terminal write).
        #   3. Contract-decided FAILED with no caller AND no in-flight
        #      reason synthesizes ``audit_findings_block_complete`` —
        #      Rule 3 cannot fire on the resolver's own write.
        #   4. COMPLETE / DEGRADED with no caller / in-flight reason →
        #      empty string (no reason needed).
        if failure_reason:
            effective_failure_reason = failure_reason
        elif final_status == "FAILED" and _inflight_reason:
            effective_failure_reason = _inflight_reason
        elif final_status == "FAILED":
            effective_failure_reason = "audit_findings_block_complete"
        else:
            effective_failure_reason = ""
    else:
        # Caller pre-decided. Populate quality fields from audit_report
        # (when available) but respect the caller's status verbatim.
        # This is the §M.M1 carve-out for hard-execution-style overrides.
        final_status = str(override_status).upper()
        if audit_report is not None:
            _evaled = _evaluate_quality_contract(
                audit_report, state, config,
                cwd=cwd, milestone_id=milestone_id,
            )
            # Use the contract's audit_status / count / severity even
            # when status is overridden — quality fields reflect actual
            # audit signal, not the override decision.
            _, audit_status, unresolved, severity = _evaled
            # Diagnostic: contract would have decided differently than
            # the override. Surfaces forensics for post-hoc review of
            # health-gate / anchor-restore decision paths.
            if _evaled[0] != final_status:
                logger.info(
                    "[QUALITY-CONTRACT] milestone %s: override_status=%s "
                    "(caller-decided); contract evaluation would have said %s "
                    "(audit_status=%s, unresolved=%d, severity=%s).",
                    milestone_id,
                    final_status,
                    _evaled[0],
                    audit_status,
                    unresolved,
                    severity,
                )
        else:
            # No audit_report available (health-gate path or anchor-restore
            # without audit context). Quality fields default to sentinels.
            audit_status = "unknown"
            unresolved = 0
            severity = ""
        # Override-path reason precedence:
        #   1. override_failure_reason (caller verbatim — 8503 helper passes
        #      regression / no_improvement / cross_milestone_lock_violation /
        #      audit_fix_did_not_recover_build).
        #   2. caller-supplied `failure_reason` kwarg.
        #   3. In-flight reason from state (cost_cap_reached etc.) on FAILED only.
        #   4. Synthesized default for FAILED with nothing else; empty for non-FAILED.
        if override_failure_reason:
            effective_failure_reason = override_failure_reason
        elif failure_reason:
            effective_failure_reason = failure_reason
        elif final_status == "FAILED" and _inflight_reason:
            effective_failure_reason = _inflight_reason
        elif final_status == "FAILED":
            effective_failure_reason = "audit_findings_block_complete"
        else:
            effective_failure_reason = ""

    # Phase 5.4 REPLACE-preserve: read current audit_fix_rounds and thread
    # through. The cycle increment in _run_audit_loop wrote it via direct
    # dict mutation; the terminal write here uses update_milestone_progress's
    # REPLACE semantics, so the existing count must be supplied or it's
    # cleared. ``progress`` was already loaded above for in-flight reason.
    existing_rounds = int(progress.get(milestone_id, {}).get("audit_fix_rounds", 0) or 0)
    audit_fix_rounds_kwarg: Optional[int] = (
        existing_rounds if existing_rounds > 0 else None
    )

    audit_findings_path = ""
    if audit_report is not None:
        audit_findings_path = _resolve_canonical_audit_report_path(
            state, milestone_id, cwd=cwd,
        )

    # Phase 5.5 §M.M15 — emit the loud deprecation log at the override site
    # (when contract decision was FAILED and --legacy-permissive-audit
    # downgraded to DEGRADED). Only fires here on the contract path.
    if (
        override_status is None
        and final_status == "DEGRADED"
        and audit_status == "degraded"
        and severity in ("CRITICAL", "HIGH")
        and getattr(getattr(config, "v18", None), "legacy_permissive_audit", False)
    ):
        _warn_legacy_permissive_audit(milestone_id, unresolved, severity)

    update_milestone_progress(
        state,
        milestone_id,
        final_status,
        failure_reason=effective_failure_reason,
        audit_status=audit_status,
        unresolved_findings_count=unresolved if unresolved > 0 else -1,
        audit_debt_severity=severity,
        audit_findings_path=audit_findings_path,
        audit_fix_rounds=audit_fix_rounds_kwarg,
    )
    update_completion_ratio(state)

    # Phase 5.5 §M.M2 layer-2 — terminal-quality invariants. Fires AFTER
    # the write so the validator sees the just-written shape. Raises
    # StateInvariantViolation by default; warn-only mode is for migration
    # commands (rescan-quality-debt / confirm-findings).
    if cwd is not None:
        from .state_invariants import validate_terminal_quality_invariants
        validate_terminal_quality_invariants(
            state, cwd=Path(cwd), milestone_id=milestone_id,
        )

    if agent_team_dir is not None:
        save_state(state, directory=str(agent_team_dir))

    return (final_status, audit_status, unresolved, severity)


# ---------------------------------------------------------------------------
# Operator-visible Quality Summary print (§H.3 box)
# ---------------------------------------------------------------------------


def render_quality_summary(
    milestone_id: str,
    final_status: str,
    audit_status: str,
    unresolved_count: int,
    debt_severity: str,
    audit_report: "AuditReport | None",
    audit_findings_path: str,
) -> str:
    """Render the operator-visible Quality Summary box per §H.3.

    Returns a multi-line string. Caller is responsible for emitting via
    ``print_warning`` / ``print_info`` / direct ``print``. Box framing
    uses ``╭/╰/│/─`` (unicode) consistent with other Quality Summary
    boxes in cli.py.
    """

    # Per-severity breakdown from audit_report.score (if available).
    crit = high = med = low = 0
    if audit_report is not None:
        score = getattr(audit_report, "score", None)
        if score is not None:
            crit = int(getattr(score, "critical_count", 0) or 0)
            high = int(getattr(score, "high_count", 0) or 0)
            med = int(getattr(score, "medium_count", 0) or 0)
            low = int(getattr(score, "low_count", 0) or 0)

    title_line = f"{milestone_id}: {final_status}"
    if audit_status == "clean":
        # Single-line summary for COMPLETE/clean.
        return f"[QUALITY] {title_line} — clean (no unresolved findings)"

    breakdown = (
        f"  {crit} CRITICAL · {high} HIGH · {med} MEDIUM · {low} LOW"
    )
    findings_line = (
        f"Findings: {audit_findings_path}" if audit_findings_path else "Findings: (path unresolved)"
    )

    lines = [
        "╭───────────── Milestone Quality Summary ─────────────╮",
        f"│ {title_line}",
        f"│ Audit: {unresolved_count} unresolved finding(s)",
        f"│ {breakdown}",
        f"│ Top severity unresolved: {debt_severity or 'NONE'}",
        f"│ {findings_line}",
        "╰──────────────────────────────────────────────────────╯",
    ]
    return "\n".join(lines)


__all__ = (
    "_evaluate_quality_contract",
    "_finalize_milestone_with_quality_contract",
    "_max_severity",
    "_warn_legacy_permissive_audit",
    "render_quality_summary",
    "_resolve_canonical_audit_report_path",
)
