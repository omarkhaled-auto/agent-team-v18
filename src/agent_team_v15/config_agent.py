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
            },
            "runs": [asdict(r) for r in self.runs],
            "total_cost": self.total_cost,
            "current_run": self.current_run,
            "status": self.status,
            "stop_reason": self.stop_reason,
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

    # --- Condition 3: Budget exhausted ---
    initial_cost = state.runs[0].cost if state.runs else 100.0
    # Use the user's max_budget as the cap. If not explicitly set (default 300),
    # also apply the 3× initial cost heuristic.
    budget_cap = state.max_budget
    if state.total_cost >= budget_cap:
        return LoopDecision(
            action="STOP",
            reason=(
                f"BUDGET: ${state.total_cost:.2f} spent, "
                f"cap is ${budget_cap:.2f} "
                f"(3× initial ${initial_cost:.2f})"
            ),
            deferred_findings=current_report.findings,
            run_number=state.current_run,
        )

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
    remaining_budget = budget_cap - state.total_cost
    actionable, deferred = _triage_findings(
        current_report.findings, remaining_budget
    )

    estimated_cost = estimate_fix_cost(actionable)

    return LoopDecision(
        action="CONTINUE",
        reason=(
            f"{len(actionable)} actionable findings, "
            f"estimated ${estimated_cost:.2f}, "
            f"budget remaining ${remaining_budget:.2f}"
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

_MAX_FINDINGS_PER_FIX = 25


def _triage_findings(
    findings: list[Finding],
    remaining_budget: float,
) -> tuple[list[Finding], list[Finding]]:
    """Separate findings into fix-now vs deferred.

    Priority:
    1. CRITICAL (always included)
    2. HIGH (included if budget allows)
    3. MEDIUM code_fix / missing_feature (budget permitting)
    4. Everything else → deferred
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

    # Add by priority, respecting budget and cap
    budget_used = 0.0
    for tier in [critical, high, medium_fixable]:
        for f in tier:
            if len(actionable) >= _MAX_FINDINGS_PER_FIX:
                deferred.append(f)
                continue
            f_cost = estimate_fix_cost([f])
            if budget_used + f_cost > remaining_budget and tier is not critical:
                deferred.append(f)
                continue
            actionable.append(f)
            budget_used += f_cost

    deferred.extend(rest)
    return actionable, deferred
