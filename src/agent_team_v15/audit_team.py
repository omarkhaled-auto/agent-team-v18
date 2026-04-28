"""Audit-team orchestration logic.

Replaces the single code-reviewer with a 6-agent parallel audit system:
  1. Requirements Auditor  (REQ-xxx, DESIGN-xxx, SEED-xxx, ENUM-xxx)
  2. Technical Auditor     (TECH-xxx, SDL-xxx, anti-patterns)
  3. Interface Auditor     (WIRE-xxx, SVC-xxx, API-xxx, orphans)
  4. Test Auditor          (TEST-xxx, test quality, coverage)
  5. MCP/Library Auditor   (library API correctness via Context7)
  6. PRD Fidelity Auditor  (DROPPED, DISTORTED, ORPHANED requirements)

Plus a Scorer agent that deduplicates, scores, and writes the report.

This module provides the pure logic functions used by the orchestrator
(cli.py) to dispatch auditors, compute scores, and manage the fix/re-audit
loop. It does NOT import cli.py or create Claude sessions directly.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .audit_models import (
    AUDITOR_NAMES,
    AUDITOR_PREFIXES,
    AuditFinding,
    AuditReport,
    AuditScore,
    FixTask,
    InvalidAuditScoreScale,
    build_report,
    compute_reaudit_scope,
    deduplicate_findings,
    detect_fix_conflicts,
    group_findings_into_fix_tasks,
)
from .audit_prompts import AUDIT_PROMPTS, get_auditor_prompt, get_scoped_auditor_prompt
from .wave_ownership import (
    compute_filtered_convergence_ratio,
    compute_finding_status,
    is_owner_wave_executed,
    resolve_owner_wave,
)

if TYPE_CHECKING:  # pragma: no cover
    from .audit_scope import AuditScope


# ---------------------------------------------------------------------------
# Auditor selection by depth
# ---------------------------------------------------------------------------

# Maps depth level to the set of auditors that should run
DEPTH_AUDITOR_MAP: dict[str, list[str]] = {
    "quick": [],  # audit-team disabled at quick depth
    "standard": ["requirements", "technical", "interface"],
    "thorough": list(AUDITOR_NAMES),  # all 6 (prd_fidelity skipped if no PRD)
    "exhaustive": list(AUDITOR_NAMES),  # all 6 (prd_fidelity skipped if no PRD)
    "enterprise": list(AUDITOR_NAMES),  # all 6 — enterprise is superset of exhaustive
}


def get_auditors_for_depth(depth: str) -> list[str]:
    """Return the list of auditor names to deploy for the given depth."""
    return list(DEPTH_AUDITOR_MAP.get(depth, DEPTH_AUDITOR_MAP["standard"]))


# ---------------------------------------------------------------------------
# Overlapping scan detection
# ---------------------------------------------------------------------------

# Post-orchestration scans that are covered by specific auditors
_SCAN_AUDITOR_OVERLAP: dict[str, str] = {
    "mock_data_scan": "interface",       # SVC-xxx mock data check
    # NOTE: ui_compliance_scan is intentionally NOT mapped here.
    # The requirements auditor checks DESIGN-xxx requirements but does NOT
    # replicate the regex-based SLOP-001..015 pattern scanning that
    # ui_compliance_scan performs. Skipping it would lose anti-pattern coverage.
    "api_contract_scan": "interface",    # API-001 through API-004
    "silent_data_loss_scan": "technical",  # SDL-001/002/003
    "endpoint_xref_scan": "interface",   # XREF-001/002
}


def should_skip_scan(scan_name: str, auditors_deployed: list[str]) -> bool:
    """Return True if the given post-orchestration scan can be skipped.

    A scan is skippable when the audit-team deployed an auditor that
    covers the same verification scope.
    """
    covering_auditor = _SCAN_AUDITOR_OVERLAP.get(scan_name)
    if not covering_auditor:
        return False
    return covering_auditor in auditors_deployed


# ---------------------------------------------------------------------------
# Re-audit termination logic
# ---------------------------------------------------------------------------

def _score_pct(score: AuditScore) -> float:
    """Normalize an ``AuditScore.score`` to a 0-100 percentage.

    Phase 5.1 (R-#33): ``score_healthy_threshold`` is documented and
    consumed as a percentage (0-100; see ``config.py:552, 711-712``).
    ``AuditScore.score`` may be either:

    * a 0-100 percentage (canonical compute path; see
      ``audit_models.py:AuditScore.compute``), or
    * a raw 0-``max_score`` integer (e.g., scorer-LLM dict output
      ``score=612, max_score=1000``).

    The helper divides to a percentage when ``max_score != 100``. When
    ``max_score == 100`` the value is already a percentage (canonical
    case) and is returned unchanged.

    Fail-closed: ``max_score <= 0`` raises ``InvalidAuditScoreScale``.
    A score reaching this site with an invalid scale signals that
    ``AuditReport.from_json``'s ``_normalize_score_severity_counts``
    did not repair it (e.g., a hand-constructed AuditScore in a
    legacy code path). Refuse to silently invent a denominator.
    """
    if score.max_score <= 0:
        raise InvalidAuditScoreScale(
            f"cannot compare audit score with max_score={score.max_score}; "
            f"AuditReport.from_json should have repaired the scale "
            f"(via AuditScore.compute(findings) when findings parseable, "
            f"or raised InvalidAuditScoreScale otherwise)"
        )
    if score.max_score == 100:
        return float(score.score)
    return (float(score.score) / float(score.max_score)) * 100.0


def format_audit_score(score: AuditScore) -> str:
    """Format an :class:`AuditScore` for display as ``"<raw>/<max> (<pct>%)"``.

    Phase 5.1 follow-up (R-#33 display-leak): the 2026-04-28 Wave 1
    closeout smoke surfaced raw 1000-scale scores being displayed with
    a literal ``%`` suffix (e.g., ``score=512%``) at the audit-loop +
    integration-audit log emission sites, because callers were
    interpolating ``report.score.score`` directly without normalising.
    A score >100% in operator output is structurally invalid and
    creates the illusion that the milestone passed even when the
    raw value happens to exceed the percentage threshold.

    The explicit ``"<raw>/<max> (<pct>%)"`` format keeps both numbers
    visible so operators can sanity-check the scale at a glance, and
    routes every comparison/display through the same normalisation
    contract enforced by :func:`_score_pct`. Callers that need the
    bare percentage should call ``_score_pct`` directly.

    Fail-closed via ``_score_pct`` propagation:
    ``InvalidAuditScoreScale`` is raised when ``max_score <= 0``;
    callers may catch and substitute a placeholder for display.
    """

    pct = _score_pct(score)
    return f"{score.score}/{score.max_score} ({pct:.1f}%)"


def cascade_quality_gate_blocks_complete(
    report: "AuditReport | None",
) -> tuple[bool, str]:
    """Phase 5.1 follow-up — cascade quality gate predicate.

    Returns ``(blocked, summary)`` where ``blocked`` is ``True`` when
    the post-recovery audit verdict carries blocking debt that must
    NOT mask itself behind ``COMPLETE / wave_fail_recovered``.

    The gate fires when ANY of:

    * ``report.extras["verdict"] == "FAIL"`` — the auditor explicitly
      rejected the milestone (M1 startup probe + scorer set this),
    * ``report.score.critical_count > 0``,
    * ``report.score.high_count > 0``.

    It does NOT fire on ``report is None`` (no audit context — the
    pre-Phase-5 ``self_verify_passed`` semantics are preserved for
    callers that haven't run the audit loop yet) or on a clean
    audit (verdict empty/PASS, zero critical/high). DEGRADED is
    deliberately NOT used here — per
    :func:`agent_team_v15.state._reconcile_milestone_lists` DEGRADED
    still satisfies the "completed" rollup and would unblock
    dependent milestones; the hollow-completion class this gate
    exists to prevent. Phase 5.5 introduces the Quality Contract
    DEGRADED semantics with explicit operator-visible quality-debt
    fields; until then, ``FAILED`` with failure_reason
    ``audit_fix_recovered_build_but_findings_remain`` is the
    structurally-loud signal callers should write.

    The 2026-04-28 Wave 1 closeout smoke reproduced the exact
    hollow-recovery shape this gate prevents: Wave D self-verify
    passed after audit-fix patched eslint/Dockerfile/.env surfaces,
    but the final AUDIT_REPORT.json still carried verdict=FAIL +
    5 CRITICAL + 8 HIGH findings (real defects). Pre-fix the
    cascade epilogue marked the milestone COMPLETE; this gate
    blocks the hollow COMPLETE.
    """

    if report is None:
        return False, ""
    verdict_str = ""
    extras = getattr(report, "extras", None)
    if isinstance(extras, dict):
        verdict_str = str(extras.get("verdict", "") or "").upper()
    score = getattr(report, "score", None)
    critical = int(score.critical_count) if score is not None else 0
    high = int(score.high_count) if score is not None else 0
    if verdict_str == "FAIL" or critical > 0 or high > 0:
        return True, (
            f"verdict={verdict_str or 'unknown'} "
            f"critical={critical} high={high}"
        )
    return False, ""


def should_terminate_reaudit(
    current_score: AuditScore,
    previous_score: AuditScore | None,
    cycle: int,
    max_cycles: int = 3,
    healthy_threshold: float = 90.0,
) -> tuple[bool, str]:
    """Determine whether to stop the re-audit loop.

    Returns (should_stop, reason) tuple.

    Phase 5.1 (R-#33): all score-based comparisons normalize to
    percentage via ``_score_pct``. The previous raw-vs-percentage
    confusion at the Cond 1 site let scorer-LLM dict output (e.g.,
    ``score=612, max_score=1000``) compare directly against the
    percentage threshold (default 90), exiting "healthy" at cycle 1
    despite real CRITICAL findings. Cond 3 (regression) and Cond 5
    (no_improvement) get the same normalization so cross-cycle
    comparisons remain apples-to-apples even when the scorer's score
    shape changes between cycles. Cond 2 (cycle >= max_cycles) and
    Cond 4 (CRITICAL-count rise) operate on integer counts and need
    no normalization.
    """
    current_pct = _score_pct(current_score)

    # Condition 1: Score meets healthy threshold with no criticals
    if current_pct >= healthy_threshold and current_score.critical_count == 0:
        return True, "healthy"

    # Condition 2: Max cycles reached
    if cycle >= max_cycles:
        return True, "max_cycles"

    # Condition 3: Score regressed by >10 (percentage) points (something broke)
    # Must be checked BEFORE no_improvement because no_improvement also catches drops.
    if previous_score is not None:
        previous_pct = _score_pct(previous_score)
        if current_pct < previous_pct - 10:
            return True, "regression"

    # Condition 4 (Phase 1 audit-fix-loop guardrails — promoted ahead of
    # the score-based no_improvement check so a CRITICAL count rise
    # cannot be swallowed when the aggregate score is flat or unchanged):
    # New CRITICAL findings appeared. Auditor LLM scoring is noisy; the
    # CRITICAL count is the deterministic signal we trust. Treating a
    # rise as a hard regression triggers anchor restore + FAILED-mark
    # in ``_run_audit_loop`` (Risk #15).
    if previous_score is not None:
        if current_score.critical_count > previous_score.critical_count:
            return True, "regression"

    # Condition 5: No improvement from previous cycle (percentage compare)
    if previous_score is not None:
        previous_pct = _score_pct(previous_score)
        if current_pct <= previous_pct and current_score.critical_count >= previous_score.critical_count:
            return True, "no_improvement"

    return False, ""


# ---------------------------------------------------------------------------
# Convergence tracking
# ---------------------------------------------------------------------------

def detect_convergence_plateau(
    metrics_history: list,
    window: int = 3,
) -> tuple[bool, str]:
    """Detect if the audit-fix loop has plateaued.

    A plateau is detected when the last *window* cycles show no
    meaningful score improvement (< 2 points total) and no net
    reduction in findings.

    Args:
        metrics_history: List of AuditCycleMetrics (or dicts with
            'score' and 'total_findings' keys).
        window: Number of recent cycles to consider.

    Returns:
        (is_plateau, reason) tuple.
    """
    if len(metrics_history) < window:
        return False, ""

    recent = metrics_history[-window:]

    # Check score movement
    scores = [m.score if hasattr(m, "score") else m["score"] for m in recent]
    score_delta = scores[-1] - scores[0]

    # Check finding count movement
    counts = [
        m.total_findings if hasattr(m, "total_findings") else m["total_findings"]
        for m in recent
    ]
    findings_delta = counts[-1] - counts[0]

    # Plateau: score improved < 2 points AND findings not decreasing
    if score_delta < 2.0 and findings_delta >= 0:
        return True, (
            f"Plateau detected over {window} cycles: "
            f"score {scores[0]:.1f} -> {scores[-1]:.1f} (+{score_delta:.1f}), "
            f"findings {counts[0]} -> {counts[-1]}"
        )

    # Oscillation: score going up and down with no net trend
    if len(scores) >= 3:
        ups = sum(1 for i in range(1, len(scores)) if scores[i] > scores[i - 1])
        downs = sum(1 for i in range(1, len(scores)) if scores[i] < scores[i - 1])
        if ups > 0 and downs > 0 and abs(score_delta) < 3.0:
            return True, (
                f"Oscillation detected over {window} cycles: "
                f"score {scores[0]:.1f} -> {scores[-1]:.1f} "
                f"({ups} ups, {downs} downs, net {score_delta:+.1f})"
            )

    return False, ""


def detect_regressions(
    current_findings: list,
    previous_findings: list,
) -> list[str]:
    """Detect findings that were fixed but reappeared.

    Compares current and previous finding lists by finding_id (for
    AuditFinding objects) or 'id' (for Finding dicts/objects).

    Returns list of regressed finding IDs.
    """
    def _get_id(f):
        if hasattr(f, "finding_id"):
            return f.finding_id
        if hasattr(f, "id"):
            return f.id
        if isinstance(f, dict):
            return f.get("finding_id", f.get("id", ""))
        return ""

    current_ids = {_get_id(f) for f in current_findings}
    previous_ids = {_get_id(f) for f in previous_findings}

    # Regressed = was not in current (fixed) in prev cycle, but now reappeared
    # Actually, regression means: something that PASSED before now FAILS.
    # We approximate: IDs in current that also existed in previous (same bug persisting).
    # True regressions are new failures on previously-passing items.
    # For finding-level regression: IDs that appear in both (not fixed).
    persistent = sorted(current_ids & previous_ids)
    return persistent


def compute_escalation_recommendation(
    metrics_history: list,
    max_cycles: int = 5,
) -> str | None:
    """Recommend an escalation action based on convergence analysis.

    Returns a recommendation string, or None if no escalation needed.
    """
    if not metrics_history:
        return None

    latest = metrics_history[-1]
    latest_score = latest.score if hasattr(latest, "score") else latest["score"]

    # Check for plateau
    is_plateau, reason = detect_convergence_plateau(metrics_history)

    if is_plateau and latest_score < 50.0:
        return (
            f"ESCALATE: {reason}. Score is critically low ({latest_score:.1f}%). "
            "Recommend manual review of deterministic findings and architectural changes."
        )

    if is_plateau and latest_score < 80.0:
        return (
            f"ESCALATE: {reason}. Score stalled at {latest_score:.1f}%. "
            "Consider focusing on deterministic findings only for next fix cycle."
        )

    if is_plateau:
        return (
            f"INFO: {reason}. Score is {latest_score:.1f}% — "
            "close to healthy, but fix loop may not improve further."
        )

    # Check for repeated regressions
    if len(metrics_history) >= 2:
        latest_m = metrics_history[-1]
        regressed = (
            latest_m.regressed_finding_ids
            if hasattr(latest_m, "regressed_finding_ids")
            else latest_m.get("regressed_finding_ids", [])
        )
        if len(regressed) >= 3:
            return (
                f"ESCALATE: {len(regressed)} regressions detected in cycle "
                f"{latest_m.cycle if hasattr(latest_m, 'cycle') else latest_m.get('cycle')}. "
                "Fix loop is introducing bugs. Consider narrower fix scope."
            )

    return None


# ---------------------------------------------------------------------------
# N-02 ownership-contract suppression helper (Phase B)
# ---------------------------------------------------------------------------


def _build_optional_suppression_block(config: Any) -> str:
    """Return a prompt suffix listing optional files so auditors do not
    raise missing-file findings for them. Empty string when the flag is
    off or the contract cannot be loaded.
    """
    v18 = getattr(config, "v18", None)
    if v18 is None or not getattr(v18, "ownership_contract_enabled", False):
        return ""
    try:
        from .scaffold_runner import load_ownership_contract
        contract = load_ownership_contract()
    except (FileNotFoundError, ValueError):
        return ""
    optional_rows = [f for f in contract.files if f.optional]
    if not optional_rows:
        return ""
    lines = [
        "",
        "",
        "## Ownership Contract — Optional Files (N-02)",
        "",
        "The following files are marked `optional: true` in",
        "docs/SCAFFOLD_OWNERSHIP.md. Do NOT raise a missing-file finding for",
        "these paths when they are absent from the generated project:",
        "",
    ]
    for row in optional_rows:
        lines.append(f"- {row.path}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Auditor agent definition builders
# ---------------------------------------------------------------------------

def build_auditor_agent_definitions(
    auditors: list[str],
    task_text: str | None = None,
    requirements_path: str | None = None,
    prd_path: str | None = None,
    tech_stack: list[str] | None = None,
    *,
    scope: "AuditScope | None" = None,
    config: Any = None,
    audit_output_root: str | None = None,
) -> dict[str, dict]:
    """Build agent definitions for the specified auditors.

    Returns a dict of agent_name -> agent_definition suitable for
    injection into build_agent_definitions() or direct use.

    If *prd_path* is ``None``, the ``prd_fidelity`` auditor is silently
    skipped (it requires a PRD to cross-reference).

    If *tech_stack* is provided, tech-stack-specific audit instructions
    are appended to each auditor prompt.

    When *scope* AND *config* are both provided, and
    ``config.v18.audit_milestone_scoping`` is True, each auditor prompt
    gains a milestone-scoped preamble (C-01). When either is ``None``
    the output is byte-identical to the pre-C-01 behaviour.

    Phase 5.2 R-#47 follow-up — *audit_output_root*: when supplied,
    each specialized auditor's prompt receives an explicit OUTPUT
    FILE directive instructing them to ``Write`` findings to the
    canonical filename
    ``{audit_output_root}/audit-<auditor>_findings.json`` (lowercase,
    with the ``_findings`` suffix the
    :mod:`agent_team_v15.audit_output_path_guard` allowlist enforces).

    The 2026-04-28 Wave 1 closeout smoke surfaced a contract drift
    where auditors ad-hoc invented filenames like
    ``AUDIT_<NAME>.json`` (uppercase, no suffix) or
    ``AUDIT_<NAME>_FINDINGS.json`` (uppercase + ``_FINDINGS``) that
    bypassed the guard's ``*_findings.json`` glob (case-sensitive on
    POSIX). Aligning the prompt directive to the plan §E.4.2 envelope
    is the structural fix — auditors write the canonical filename;
    the guard enforces it; live runs prove the contract end-to-end.

    The scorer agent retains its own ``AUDIT_REPORT.json`` directive
    (in :mod:`agent_team_v15.audit_prompts`) — that filename is also
    in the guard's envelope. The directive injected here covers the
    six specialized auditors (``audit-requirements``,
    ``audit-technical``, ``audit-interface``, ``audit-test``,
    ``audit-mcp-library``, ``audit-comprehensive``) plus any
    additional auditors the caller registers.

    When *audit_output_root* is ``None`` the prompts are byte-
    identical to the pre-fix behaviour so test fixtures that don't
    exercise R-#47 enforcement keep working unchanged.
    """
    agents: dict[str, dict] = {}

    # N-02 (Phase B): when the ownership-contract flag is ON, auditors also
    # receive a suppression list so they do not raise missing-file findings
    # for optional entries (.editorconfig, .nvmrc, apps/api/prisma/seed.ts).
    optional_suppression_block = _build_optional_suppression_block(config)

    # Helper: choose between the legacy prompt builder and the scoped
    # wrapper based on whether a scope was actually supplied. The scoped
    # wrapper itself checks the v18 feature flag, so when the flag is
    # off the preamble is suppressed even if a scope is passed in.
    def _prompt_for(name: str) -> str:
        if scope is None:
            base = get_auditor_prompt(
                name,
                requirements_path=requirements_path,
                prd_path=prd_path,
                tech_stack=tech_stack,
            )
        else:
            base = get_scoped_auditor_prompt(
                name,
                scope=scope,
                config=config,
                requirements_path=requirements_path,
                prd_path=prd_path,
                tech_stack=tech_stack,
            )
        if optional_suppression_block:
            return base + optional_suppression_block
        return base

    def _output_file_directive(name: str) -> str:
        """Phase 5.2 R-#47 follow-up — return the per-auditor write
        directive to append to the prompt when *audit_output_root* is
        supplied. Empty string when the param is absent (legacy
        callers byte-identical).
        """
        if not audit_output_root:
            return ""
        # Hyphenated agent name (SDK convention) + canonical
        # ``audit-<name>_findings.json`` filename so the
        # ``audit_output_path_guard`` ``*_findings.json`` glob matches.
        agent_name = name.replace("_", "-")
        target_filename = f"audit-{agent_name}_findings.json"
        return (
            "\n\n"
            "## OUTPUT FILE — MANDATORY\n"
            "\n"
            "Persist your findings to disk via the ``Write`` tool at the\n"
            f"EXACT path:\n\n"
            f"    {audit_output_root}/{target_filename}\n\n"
            "Use the lowercase, ``_findings.json``-suffixed filename above\n"
            "verbatim. The audit-output ``PreToolUse`` hook denies any\n"
            "other shape, including:\n\n"
            f"  - ``AUDIT_{name.upper()}.json`` (uppercase, no suffix)\n"
            f"  - ``AUDIT_{name.upper()}_FINDINGS.json`` (uppercase suffix)\n"
            "  - any nested subdirectory of the audit output root\n"
            "  - any project source file (``apps/``, ``packages/``, etc.)\n\n"
            "Findings persisted via these denied shapes will be lost.\n"
            "The scorer collects per-auditor findings from this exact\n"
            "filename to assemble ``AUDIT_REPORT.json``.\n"
        )

    for auditor_name in auditors:
        if auditor_name not in AUDIT_PROMPTS:
            continue
        # Skip prd_fidelity when no PRD is available
        if auditor_name == "prd_fidelity" and not prd_path:
            continue
        prompt = _prompt_for(auditor_name)
        if task_text and auditor_name == "requirements":
            prompt = f"[ORIGINAL USER REQUEST]\n{task_text}\n\n" + prompt
        prompt += _output_file_directive(auditor_name)

        # Agent name uses hyphens (SDK convention)
        agent_key = f"audit-{auditor_name.replace('_', '-')}"
        # Phase 5.2 (R-#47): auditors now persist findings inline rather
        # than returning JSON in the message body for the parent/scorer
        # to copy-paste. ``Write`` is structurally complemented by the
        # ``audit_output_path_guard`` PreToolUse hook (env-gated on
        # ``AGENT_TEAM_AUDIT_WRITER=1``) which restricts writes to
        # ``{audit_dir}/audit-*_findings.json`` /
        # ``{audit_dir}/AUDIT_REPORT.json`` and the requirements_path.
        agents[agent_key] = {
            "description": f"Audit-team {auditor_name} auditor",
            "prompt": prompt,
            "tools": (
                ["Read", "Write", "Glob", "Grep", "Bash"]
                if auditor_name == "test"
                else ["Read", "Write", "Glob", "Grep"]
            ),
            "model": "opus",
        }

    # Comprehensive auditor — final quality gate after all specialized auditors
    if "comprehensive" not in auditors:
        comp_prompt = _prompt_for("comprehensive")
        comp_prompt += _output_file_directive("comprehensive")
        agents["audit-comprehensive"] = {
            "description": "Audit-team comprehensive auditor — final 1000-point quality gate",
            "prompt": comp_prompt,
            # Phase 5.2 (R-#47): see specialized-auditor block above —
            # ``Write`` paired with audit-output path guard.
            "tools": ["Read", "Write", "Glob", "Grep"],
            "model": "opus",
        }

    # Scorer agent — receives the scope preamble too so it partitions
    # findings consistently with the auditors that produced them.
    # Note: get_scoped_auditor_prompt passes prd_path/tech_stack through
    # but the scorer's template only uses requirements_path — the rest
    # are safely ignored by get_auditor_prompt's substitution logic.
    scorer_prompt = _prompt_for("scorer") if scope is not None else get_auditor_prompt(
        "scorer", requirements_path=requirements_path,
    )
    agents["audit-scorer"] = {
        "description": "Audit-team scorer — deduplicates, scores, writes report",
        "prompt": scorer_prompt,
        "tools": ["Read", "Write", "Edit", "Glob", "Grep"],
        "model": "opus",
    }

    return agents


# ---------------------------------------------------------------------------
# Public API summary (used by cli.py integration)
# ---------------------------------------------------------------------------

__all__ = [
    "AUDITOR_NAMES",
    "AUDITOR_PREFIXES",
    "AUDIT_PROMPTS",
    "AuditFinding",
    "AuditReport",
    "AuditScore",
    "FixTask",
    "build_auditor_agent_definitions",
    "build_report",
    "cascade_quality_gate_blocks_complete",
    "compute_escalation_recommendation",
    # Phase 4.3 audit-wave-awareness re-exports. The audit-team's
    # callers (cli's audit-loop, the convergence-fail path) already
    # import from this module; re-exporting keeps the import path
    # stable and signals that wave-awareness is part of the audit
    # team's surface, not a separate subsystem.
    "compute_filtered_convergence_ratio",
    "compute_finding_status",
    "compute_reaudit_scope",
    "deduplicate_findings",
    "detect_convergence_plateau",
    "detect_fix_conflicts",
    "detect_regressions",
    "format_audit_score",
    "get_auditor_prompt",
    "get_auditors_for_depth",
    "group_findings_into_fix_tasks",
    "is_owner_wave_executed",
    "resolve_owner_wave",
    "should_skip_scan",
    "should_terminate_reaudit",
]
