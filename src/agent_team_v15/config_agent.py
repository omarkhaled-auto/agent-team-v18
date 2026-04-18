"""Configuration Agent — Decides whether to stop or continue the fix loop.

Evaluates four stop conditions plus a three-level circuit breaker,
triages findings by severity and budget, and produces a LoopDecision.

Typical usage::

    from agent_team_v15.config_agent import evaluate_stop_conditions, LoopState

    state = LoopState(original_prd_path="prd.md", codebase_path="./out")
    decision = evaluate_stop_conditions(state, audit_report)
    if decision.action == "STOP":
        print(f"Done: {decision.reason}")
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent_team_v15.audit_agent import (
    AuditReport,
    Finding,
    FindingCategory,
    Severity,
)
from agent_team_v15.fix_prd_agent import filter_findings_for_fix


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RunRecord:
    """Summary of a single builder run."""

    run_number: int
    run_type: str  # "initial" or "fix"
    prd_path: str
    cost: float
    score: float
    total_acs: int
    passed_acs: int
    partial_acs: int
    failed_acs: int
    skipped_acs: int
    critical_count: int
    high_count: int
    medium_count: int
    finding_count: int
    regression_count: int
    audit_report_path: str = ""
    fix_prd_path: str = ""
    state_archive_path: str = ""
    timestamp: str = ""


@dataclass
class LoopState:
    """Tracks state across all runs in the coordinated build."""

    original_prd_path: str = ""
    codebase_path: str = ""
    max_budget: float = 300.0
    max_iterations: int = 4
    min_improvement_threshold: float = 3.0
    depth: str = "exhaustive"
    audit_model: str = "claude-sonnet-4-20250514"

    runs: list[RunRecord] = field(default_factory=list)
    total_cost: float = 0.0
    current_run: int = 0
    status: str = "running"  # "running" | "converged" | "stopped" | "failed"
    stop_reason: str = ""
    # Truth scoring (Feature #2)
    regression_count: int = 0
    truth_score_threshold: float = 0.95
    max_regressions: int = 5  # Stop if exceeded
    last_truth_score: float = 0.0
    last_truth_gate: str = ""  # "pass" | "retry" | "escalate"
    truth_dimensions: dict[str, float] = field(default_factory=dict)

    def add_run(
        self,
        report: AuditReport,
        cost: float,
        run_type: str = "fix",
        prd_path: str = "",
    ) -> None:
        """Record a completed run."""
        record = RunRecord(
            run_number=self.current_run + 1,
            run_type=run_type,
            prd_path=prd_path,
            cost=cost,
            score=report.score,
            total_acs=report.total_acs,
            passed_acs=report.passed_acs,
            partial_acs=report.partial_acs,
            failed_acs=report.failed_acs,
            skipped_acs=report.skipped_acs,
            critical_count=report.critical_count,
            high_count=report.high_count,
            medium_count=report.actionable_count - report.critical_count - report.high_count,
            finding_count=len(report.findings),
            regression_count=len(report.regressions),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self.runs.append(record)
        self.total_cost += cost
        self.current_run += 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON persistence."""
        return {
            "schema_version": 1,
            "original_prd_path": self.original_prd_path,
            "codebase_path": self.codebase_path,
            "config": {
                "max_budget": self.max_budget,
                "max_iterations": self.max_iterations,
                "min_improvement": self.min_improvement_threshold,
                "depth": self.depth,
                "audit_model": self.audit_model,
                "truth_score_threshold": self.truth_score_threshold,
                "max_regressions": self.max_regressions,
            },
            "runs": [asdict(r) for r in self.runs],
            "total_cost": self.total_cost,
            "current_run": self.current_run,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "regression_count": self.regression_count,
            "last_truth_score": self.last_truth_score,
            "last_truth_gate": self.last_truth_gate,
            "truth_dimensions": self.truth_dimensions,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoopState:
        """Deserialize from dict."""
        config = data.get("config", {})
        state = cls(
            original_prd_path=data.get("original_prd_path", ""),
            codebase_path=data.get("codebase_path", ""),
            max_budget=config.get("max_budget", 300.0),
            max_iterations=config.get("max_iterations", 4),
            min_improvement_threshold=config.get("min_improvement", 3.0),
            depth=config.get("depth", "exhaustive"),
            audit_model=config.get("audit_model", "claude-sonnet-4-20250514"),
            total_cost=data.get("total_cost", 0.0),
            current_run=data.get("current_run", 0),
            status=data.get("status", "running"),
            stop_reason=data.get("stop_reason", ""),
            regression_count=data.get("regression_count", 0),
            truth_score_threshold=config.get("truth_score_threshold", 0.95),
            max_regressions=config.get("max_regressions", 5),
            last_truth_score=data.get("last_truth_score", 0.0),
            last_truth_gate=data.get("last_truth_gate", ""),
            truth_dimensions=data.get("truth_dimensions", {}),
        )
        for r in data.get("runs", []):
            state.runs.append(RunRecord(**r))
        return state

    def save(self, directory: Path) -> Path:
        """Save coordinated state to JSON file."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "coordinated_state.json"
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, directory: Path) -> Optional[LoopState]:
        """Load coordinated state from JSON file."""
        path = directory / "coordinated_state.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None


@dataclass
class LoopDecision:
    """Decision from the configuration agent."""

    action: str  # "STOP" or "CONTINUE"
    reason: str
    findings_for_fix: list[Finding] = field(default_factory=list)
    deferred_findings: list[Finding] = field(default_factory=list)
    estimated_cost: float = 0.0
    run_number: int = 0
    circuit_breaker_level: int = 0  # 0=none, 1=warning, 2=stop, 3=stop


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

_BASE_COST: dict[str, float] = {
    "code_fix": 3.0,
    "missing_feature": 8.0,
    "security": 5.0,
    "regression": 5.0,
    "test_gap": 3.0,
    "performance": 5.0,
    "ux": 5.0,
}

_EFFORT_MULTIPLIER: dict[str, float] = {
    "trivial": 0.5,
    "small": 1.0,
    "medium": 1.5,
    "large": 2.5,
}


def estimate_fix_cost(findings: list[Finding]) -> float:
    """Estimate the builder cost to fix a set of findings."""
    total = 0.0
    for f in findings:
        base = _BASE_COST.get(f.category.value, 5.0)
        mult = _EFFORT_MULTIPLIER.get(f.estimated_effort, 1.0)
        total += base * mult
    return round(total, 2)


# ---------------------------------------------------------------------------
# Finding → Scoring Category Mapping
# ---------------------------------------------------------------------------

# Keywords that signal which of the 8 scoring categories a finding belongs to.
_SCORING_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "frontend_backend_wiring": [
        "wiring", "wire", "integration", "endpoint mismatch", "contract",
        "field mismatch", "api call", "response shape", "unwrap",
        "XREF", "SVC-", "API-", "MOCK-", "pagination wrapper",
    ],
    "prd_ac_compliance": [
        "acceptance criteria", "prd", "requirement", "missing feature",
        "not implemented", "feature gap", "AC-",
    ],
    "entity_database": [
        "entity", "database", "schema", "migration", "model", "prisma",
        "typeorm", "table", "column", "relation", "seed",
    ],
    "business_logic": [
        "business logic", "calculation", "formula", "state machine",
        "transition", "validation rule", "domain", "workflow",
    ],
    "frontend_quality": [
        "frontend", "component", "page", "loading state", "empty state",
        "error state", "ui", "form", "slop", "design", "layout",
    ],
    "backend_architecture": [
        "backend", "controller", "service", "handler", "middleware",
        "module", "architecture", "dependency injection", "performance",
    ],
    "security_auth": [
        "security", "auth", "jwt", "guard", "permission", "role",
        "csrf", "xss", "injection", "owasp", "cors",
    ],
    "infrastructure": [
        "docker", "deploy", "ci/cd", "nginx", "port", "environment",
        "config", "build", "infrastructure", "health check",
    ],
}


def _map_finding_to_scoring_category(finding: Finding) -> str:
    """Map a Finding to one of the 8 CATEGORY_WEIGHTS scoring categories.

    Uses FindingCategory as a primary signal, then keyword-matches on
    the finding's title and description for finer classification.
    """
    # Direct mapping for unambiguous FindingCategory values
    _CATEGORY_DIRECT: dict[str, str] = {
        "security": "security_auth",
        "performance": "backend_architecture",
        "ux": "frontend_quality",
    }
    cat_val = finding.category.value if finding.category else ""
    if cat_val in _CATEGORY_DIRECT:
        return _CATEGORY_DIRECT[cat_val]

    # Keyword matching on title + description + id
    text = f"{finding.id} {finding.title} {finding.description}".lower()
    best_category = "prd_ac_compliance"  # Default fallback
    best_score = 0
    for category, keywords in _SCORING_CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > best_score:
            best_score = score
            best_category = category
    return best_category


# ---------------------------------------------------------------------------
# Stop condition evaluation
# ---------------------------------------------------------------------------


def evaluate_stop_conditions(
    state: LoopState,
    current_report: AuditReport,
) -> LoopDecision:
    """Evaluate all stop conditions and return STOP or CONTINUE with scoped findings.

    Stop conditions are checked in order (first triggered wins):
    1. Circuit breaker (regression spiral or oscillation)
    2. Convergence (< threshold improvement with zero CRITICAL/HIGH)
    3. Zero actionable findings
    4. Budget exhausted
    5. Max iterations reached

    If none trigger: CONTINUE with triaged findings.
    """

    # --- Circuit breaker (checked first — safety mechanism) ---
    cb_level, cb_reason = _check_circuit_breaker(state, current_report)

    if cb_level >= 2:
        return LoopDecision(
            action="STOP",
            reason=f"CIRCUIT BREAKER (L{cb_level}): {cb_reason}",
            deferred_findings=current_report.findings,
            run_number=state.current_run,
            circuit_breaker_level=cb_level,
        )

    # --- Condition 0b: Regression limit (Feature #2) ---
    if state.regression_count >= state.max_regressions:
        return LoopDecision(
            action="STOP",
            reason=(
                f"REGRESSION_LIMIT: {state.regression_count} total regressions "
                f"across all runs (limit: {state.max_regressions}). "
                f"Fix loop is causing more damage than progress."
            ),
            deferred_findings=current_report.findings,
            run_number=state.current_run,
            circuit_breaker_level=2,
        )

    # --- Condition 0b2: AC pass rate convergence (primary metric) ---
    ac_results = current_report.ac_results or []
    if ac_results and len(state.runs) >= 1:
        passing = sum(1 for r in ac_results if r.status == "PASS")
        partial = sum(1 for r in ac_results if r.status in {"PARTIAL", "UNVERIFIED"})
        total = len(ac_results)  # No exclusions — everything counts
        pass_rate = (passing + 0.5 * partial) / total if total > 0 else 0
        target = 0.90

        if pass_rate >= target and current_report.critical_count == 0:
            return LoopDecision(
                action="STOP",
                reason=(
                    f"AC_PASS_RATE: {pass_rate:.1%} >= {target:.0%} target "
                    f"({passing} PASS + {partial} PARTIAL out of {total} total)"
                ),
                deferred_findings=current_report.findings,
                run_number=state.current_run,
            )

    # --- Condition 0c: Weighted score stop (1000-point scale, >= 850) ---
    # Only meaningful when: (a) actionable findings exist (CRITICAL/HIGH/MEDIUM),
    # and (b) at least one prior run exists so this is a convergence decision.
    if current_report.actionable_count > 0 and len(state.runs) >= 1:
        try:
            from agent_team_v15.quality_checks import CATEGORY_WEIGHTS, compute_weighted_score
            # Start every scoring category at 100 (perfect).  Deduct per finding.
            _cat_scores: dict[str, float] = {k: 100.0 for k in CATEGORY_WEIGHTS}
            for f in current_report.findings:
                _cat_key = _map_finding_to_scoring_category(f)
                if _cat_key not in _cat_scores:
                    continue  # Unmappable finding — skip
                sev_val = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
                deduction = {"critical": 25, "high": 15, "medium": 8, "low": 3}.get(sev_val, 5)
                _cat_scores[_cat_key] = max(0.0, _cat_scores[_cat_key] - deduction)
            weighted = compute_weighted_score(_cat_scores)

            # Gate 4 (Level C): Agent deployment under-staffing penalty
            try:
                from agent_team_v15.quality_checks import check_agent_deployment
                _deploy_v = check_agent_deployment(
                    Path(state.codebase_path), depth=state.depth,
                )
                if _deploy_v:
                    # Each deployment violation costs 30 points off the weighted score
                    deploy_penalty = len(_deploy_v) * 30
                    weighted = max(0, weighted - deploy_penalty)
            except Exception:
                pass

            # Gate 6 (Level C): Quality score prediction penalty
            try:
                from agent_team_v15.quality_checks import compute_quality_score
                _qs = compute_quality_score(Path(state.codebase_path))
                quality_predicted = _qs.get("predicted_score", 12000)
                # If quality score < 6000 (half of 12000), penalize proportionally
                if quality_predicted < 6000:
                    # Map 0-6000 to a 0-100 penalty on the 1000-point scale
                    quality_penalty = int((6000 - quality_predicted) / 6000 * 100)
                    weighted = max(0, weighted - quality_penalty)
            except Exception:
                pass

            if weighted >= 850 and current_report.critical_count == 0 and current_report.high_count == 0:
                return LoopDecision(
                    action="STOP",
                    reason=(
                        f"WEIGHTED SCORE: {weighted}/1000 (>= 850 threshold), "
                        f"zero CRITICAL findings"
                    ),
                    deferred_findings=current_report.findings,
                    run_number=state.current_run,
                )
        except Exception as e:
            import traceback
            import logging
            logging.getLogger(__name__).error(f"Weighted scoring failed: {e}\n{traceback.format_exc()}")

    # --- Condition 0d: Truth score gate (Level B — block convergence) ---
    if (
        hasattr(state, "last_truth_gate")
        and state.last_truth_gate in ("retry", "escalate")
        and len(state.runs) >= 1
    ):
        # Don't allow convergence if truth scorer says RETRY or ESCALATE
        # This is checked early so it can block the convergence condition below
        pass  # Actual blocking is done in coordinated_builder post-audit section

    # --- Condition 0e: Review integrity (Level B — block convergence) ---
    if len(state.runs) >= 1:
        try:
            from agent_team_v15.quality_checks import verify_review_integrity
            _review_v = verify_review_integrity(Path(state.codebase_path))
            if _review_v:
                # Review integrity violations prevent convergence
                # but don't force CONTINUE on their own — that's handled in coordinated_builder
                pass
        except Exception:
            pass

    # --- Condition 1: Convergence ---
    if len(state.runs) >= 1:
        prev_score = state.runs[-1].score
        improvement = current_report.score - prev_score
        if (
            improvement < state.min_improvement_threshold
            and current_report.critical_count == 0
            and current_report.high_count == 0
        ):
            return LoopDecision(
                action="STOP",
                reason=(
                    f"CONVERGED: {improvement:+.1f}% improvement "
                    f"(below {state.min_improvement_threshold}% threshold), "
                    f"zero CRITICAL/HIGH"
                ),
                deferred_findings=current_report.findings,
                run_number=state.current_run,
            )

    # --- Condition 2: Zero actionable ---
    if current_report.actionable_count == 0:
        return LoopDecision(
            action="STOP",
            reason=(
                f"COMPLETE: Zero actionable findings "
                f"(CRITICAL: 0, HIGH: 0, MEDIUM: 0)"
            ),
            deferred_findings=current_report.findings,
            run_number=state.current_run,
        )

    # --- Phase F: Budget is advisory only ---
    # The former Condition 3 halted the loop when total_cost crossed
    # ``state.max_budget``. We now emit a telemetry note (via caller logs)
    # and let convergence / plateau / max_iterations drive termination.
    # ``state.max_budget`` is still carried for observability only.

    # --- Condition 4: Max iterations ---
    if state.current_run >= state.max_iterations:
        return LoopDecision(
            action="STOP",
            reason=(
                f"MAX ITERATIONS: {state.current_run} runs completed "
                f"(cap: {state.max_iterations})"
            ),
            deferred_findings=current_report.findings,
            run_number=state.current_run,
        )

    # --- CONTINUE: Triage findings ---
    # Phase F: triage by severity only; there is no budget-based deferral.
    actionable, deferred = _triage_findings(current_report.findings)

    estimated_cost = estimate_fix_cost(actionable)

    return LoopDecision(
        action="CONTINUE",
        reason=(
            f"{len(actionable)} actionable findings, "
            f"estimated ${estimated_cost:.2f} (advisory only)"
        ),
        findings_for_fix=actionable,
        deferred_findings=deferred,
        estimated_cost=estimated_cost,
        run_number=state.current_run,
        circuit_breaker_level=cb_level,
    )


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def _check_circuit_breaker(
    state: LoopState,
    current_report: AuditReport,
) -> tuple[int, str]:
    """Check circuit breaker conditions.

    Returns (level, reason):
    - (0, ""): No issue
    - (1, reason): Warning — score dropped but continue
    - (2, reason): Stop — oscillating (2 consecutive drops)
    - (3, reason): Stop — regression spiral
    """
    # Level 3: Regression spiral (regressions > newly fixed items)
    if current_report.regressions and len(state.runs) >= 1:
        prev = state.runs[-1]
        # Estimate fixes: items that were failing before but pass now
        new_fixes = max(0, current_report.passed_acs - prev.passed_acs)
        if len(current_report.regressions) > max(new_fixes, 0) + 2:
            return (
                3,
                f"{len(current_report.regressions)} regressions > "
                f"{new_fixes} new fixes",
            )

    # Level 2: Oscillating (score dropped 2 consecutive runs)
    if len(state.runs) >= 2:
        prev_score = state.runs[-1].score
        prev_prev_score = state.runs[-2].score
        if (
            prev_score < prev_prev_score
            and current_report.score < prev_score
        ):
            return (
                2,
                f"Score dropped 2 consecutive runs: "
                f"{prev_prev_score:.1f}% → {prev_score:.1f}% → {current_report.score:.1f}%",
            )

    # Level 1: Score dropped (warning only)
    if len(state.runs) >= 1:
        prev_score = state.runs[-1].score
        if current_report.score < prev_score:
            return (
                1,
                f"Score dropped from {prev_score:.1f}% to {current_report.score:.1f}%",
            )

    return (0, "")


# ---------------------------------------------------------------------------
# Finding triage
# ---------------------------------------------------------------------------

_MAX_FINDINGS_PER_FIX = 100  # Include ALL findings — let the builder handle milestones


def _triage_findings(
    findings: list[Finding],
    remaining_budget: float | None = None,
) -> tuple[list[Finding], list[Finding]]:
    """Separate findings into fix-now vs deferred.

    Priority:
    1. CRITICAL (always included)
    2. HIGH
    3. MEDIUM code_fix / missing_feature / security
    4. Everything else → deferred

    ``remaining_budget`` is accepted for backwards compatibility with
    callers that still pass it, but Phase F removes budget-based
    deferral: triage is purely severity-driven so the pipeline keeps
    fixing until convergence/plateau/max_iterations.
    """
    actionable: list[Finding] = []
    deferred: list[Finding] = []

    # Separate by priority tier
    critical: list[Finding] = []
    high: list[Finding] = []
    medium_fixable: list[Finding] = []
    rest: list[Finding] = []

    for f in findings:
        if f.severity == Severity.CRITICAL:
            critical.append(f)
        elif f.severity == Severity.HIGH:
            high.append(f)
        elif f.severity == Severity.MEDIUM and f.category in (
            FindingCategory.CODE_FIX,
            FindingCategory.MISSING_FEATURE,
            FindingCategory.SECURITY,
        ):
            medium_fixable.append(f)
        else:
            rest.append(f)

    # Phase F: severity-driven triage only. The former budget-based
    # deferral has been removed — high-priority findings no longer get
    # pushed to ``deferred`` simply because their estimated fix cost
    # would exceed a remaining-budget projection. The per-fix cap
    # (_MAX_FINDINGS_PER_FIX) is retained as a structural safety rail.
    for tier in [critical, high, medium_fixable]:
        for f in tier:
            if len(actionable) >= _MAX_FINDINGS_PER_FIX:
                deferred.append(f)
                continue
            actionable.append(f)

    deferred.extend(rest)

    # Apply the 20-finding cap with priority filtering (was dead code — now wired)
    actionable = filter_findings_for_fix(actionable, max_findings=20)
    return actionable, deferred
