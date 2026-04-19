"""Run state persistence for Agent Team.

Supports saving/loading state for graceful interrupt/resume workflows.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class RunState:
    """Captures the state of an agent-team run for resume capability."""

    run_id: str = ""
    task: str = ""
    depth: str = "standard"
    current_phase: str = "init"
    completed_phases: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    artifacts: dict[str, str] = field(default_factory=dict)  # name -> path
    interrupted: bool = False
    timestamp: str = ""
    # Granular convergence tracking (Root Cause #2, #3)
    convergence_cycles: int = 0
    requirements_checked: int = 0
    requirements_total: int = 0
    error_context: str = ""
    milestone_progress: dict[str, dict] = field(default_factory=dict)
    v18_config: dict[str, Any] = field(default_factory=dict)
    wave_progress: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Per-milestone orchestration fields (schema version 3)
    schema_version: int = 3
    current_milestone: str = ""
    completed_milestones: list[str] = field(default_factory=list)
    failed_milestones: list[str] = field(default_factory=list)
    milestone_order: list[str] = field(default_factory=list)
    completion_ratio: float = 0.0  # completed_milestones / total_milestones
    completed_browser_workflows: list[int] = field(default_factory=list)
    agent_teams_active: bool = False
    # Enterprise mode tracking
    enterprise_mode_active: bool = False
    ownership_map_validated: bool = False
    waves_completed: int = 0
    domain_agents_deployed: int = 0
    # Enterprise v2: department model tracking
    department_mode_active: bool = False
    departments_created: list[str] = field(default_factory=list)
    manager_count: int = 0
    # Audit tracking (backported from v0)
    audit_score: float = 0.0
    audit_health: str = ""
    audit_fix_rounds: int = 0
    # Build 2: Contract and codebase intelligence state
    contract_report: dict[str, Any] = field(default_factory=dict)
    endpoint_test_report: dict[str, Any] = field(default_factory=dict)
    registered_artifacts: list[str] = field(default_factory=list)
    # Truth scoring (Feature #2)
    truth_scores: dict[str, float] = field(default_factory=dict)  # requirement_id -> score
    previous_passing_acs: list[str] = field(default_factory=list)  # ACs that passed in prior run
    regression_count: int = 0
    # Pseudocode phase tracking
    pseudocode_validated: bool = False
    pseudocode_artifacts: dict[str, str] = field(default_factory=dict)  # task_id -> pseudocode file path
    # Gate enforcement tracking (Feature #3)
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    gates_passed: int = 0
    gates_failed: int = 0
    # Pattern memory tracking (Feature #4)
    patterns_captured: int = 0
    patterns_retrieved: int = 0
    # Fix recipe tracking (Feature #4.1)
    recipes_captured: int = 0
    recipes_applied: int = 0
    # Convergence debug & escalation tracking
    debug_fleet_deployed: bool = False
    escalation_triggered: bool = False
    # Routing tracking (Feature #5)
    routing_decisions: list[dict[str, Any]] = field(default_factory=list)
    routing_tier_counts: dict[str, int] = field(default_factory=dict)
    stack_contract: dict[str, Any] = field(default_factory=dict)
    # D-13: summary block for quick inspection. Populated by
    # :meth:`finalize` (and, for back-compat, by :func:`save_state` when
    # ``finalize`` has not been called). Kept as a first-class field so
    # ``finalize``-derived values (e.g. ``success`` derived from
    # ``failed_milestones``) survive the round-trip through save_state.
    summary: dict[str, Any] = field(default_factory=dict)

    def finalize(self, agent_team_dir: "Path | str | None" = None) -> None:
        """Reconcile aggregate fields from authoritative sources.

        D-13: called once at the end of a pipeline run, before the final
        ``STATE.json`` write. Idempotent — calling twice produces
        identical output.

        Reconciliations:
          * ``summary["success"]`` := ``not interrupted and
            len(failed_milestones) == 0``.
          * ``audit_health`` := scorer-reported ``health`` from
            ``AUDIT_REPORT.json`` (read via permissive
            ``AuditReport.from_json`` — D-07 makes this tolerant to both
            legacy + scorer shapes).
          * ``current_wave`` cleared from every ``wave_progress`` entry
            when ``current_phase == "complete"``.
          * ``stack_contract.confidence`` := ``"low"`` when both
            ``backend_framework`` and ``frontend_framework`` are empty.
            A caller-supplied value on a populated contract is preserved
            verbatim.
          * ``gate_results`` := loaded from ``GATE_FINDINGS.json`` when
            present (handles both list-at-root and
            ``{"findings": [...]}`` shapes).

        Parameters
        ----------
        agent_team_dir :
            Optional path to the ``.agent-team`` directory. When provided,
            ``finalize`` looks for ``AUDIT_REPORT.json`` and
            ``GATE_FINDINGS.json`` there. When omitted, falls back to
            ``artifacts["audit_report_path"]`` and
            ``artifacts["gate_findings_path"]``.
        """
        from pathlib import Path as _Path

        # --- summary.success: authoritative on failed_milestones + interrupted
        if not isinstance(self.summary, dict):
            self.summary = {}
        self.summary["success"] = (
            (not self.interrupted) and len(self.failed_milestones) == 0
        )

        # --- audit_health: read scorer-produced AUDIT_REPORT.json
        audit_path: _Path | None = None
        if agent_team_dir is not None:
            candidate = _Path(agent_team_dir) / "AUDIT_REPORT.json"
            if candidate.is_file():
                audit_path = candidate
        if audit_path is None:
            ap = self.artifacts.get("audit_report_path") if isinstance(self.artifacts, dict) else None
            if ap and _Path(ap).is_file():
                audit_path = _Path(ap)
        if audit_path is not None:
            try:
                from .audit_models import AuditReport

                report = AuditReport.from_json(audit_path.read_text(encoding="utf-8"))
                # Scorer reports carry ``health`` as a top-level field, which
                # D-07's permissive parser captures onto ``extras``. Legacy
                # ``to_json`` writes ``score.health``. Prefer scorer truth,
                # fall back to legacy score.health.
                health = ""
                if isinstance(report.extras, dict):
                    health = str(report.extras.get("health") or "")
                if not health:
                    health = report.score.health or ""
                if health:
                    self.audit_health = health
            except Exception:
                # Best-effort — do not crash finalize on parse failure.
                pass

        # --- current_wave: clear when phase complete
        if self.current_phase == "complete" and isinstance(self.wave_progress, dict):
            for ms_entry in self.wave_progress.values():
                if isinstance(ms_entry, dict):
                    ms_entry.pop("current_wave", None)

        # --- stack_contract.confidence: low when struct fields are empty
        sc = self.stack_contract
        if isinstance(sc, dict):
            has_backend = bool(sc.get("backend_framework"))
            has_frontend = bool(sc.get("frontend_framework"))
            if not has_backend and not has_frontend:
                sc["confidence"] = "low"

        # --- gate_results: load from GATE_FINDINGS.json when present
        gate_path: _Path | None = None
        if agent_team_dir is not None:
            candidate = _Path(agent_team_dir) / "GATE_FINDINGS.json"
            if candidate.is_file():
                gate_path = candidate
        if gate_path is None:
            gp = self.artifacts.get("gate_findings_path") if isinstance(self.artifacts, dict) else None
            if gp and _Path(gp).is_file():
                gate_path = _Path(gp)
        if gate_path is not None:
            try:
                data = json.loads(gate_path.read_text(encoding="utf-8"))
                # GATE_FINDINGS.json ships as a flat list-at-root in build-j;
                # ``{"findings": [...]}`` is the alternate shape cited in the
                # D-13 plan. Accept either.
                if isinstance(data, list):
                    self.gate_results = list(data)
                elif isinstance(data, dict):
                    findings = data.get("findings", [])
                    if isinstance(findings, list):
                        self.gate_results = list(findings)
            except Exception:
                # Best-effort — preserve existing gate_results on parse failure.
                pass

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


_RUN_STATE_FIELD_NAMES = {item.name for item in fields(RunState)}


@dataclass
class RunSummary:
    """Summary of a completed agent-team run."""

    task: str = ""
    depth: str = "standard"
    total_cost: float = 0.0
    cycle_count: int = 0
    requirements_passed: int = 0
    requirements_total: int = 0
    files_changed: list[str] = field(default_factory=list)
    health: str = "unknown"
    recovery_passes_triggered: int = 0
    recovery_types: list[str] = field(default_factory=list)


@dataclass
class ConvergenceReport:
    """Result of a convergence health check after orchestration."""

    total_requirements: int = 0
    checked_requirements: int = 0
    review_cycles: int = 0
    convergence_ratio: float = 0.0  # checked/total
    review_fleet_deployed: bool = False  # cycles > 0
    health: str = "unknown"  # "healthy" | "degraded" | "failed"
    escalated_items: list[str] = field(default_factory=list)  # items at escalation threshold still unchecked
    # M3: Zero-cycle milestone tracking (Issue #10)
    zero_cycle_milestones: list[str] = field(default_factory=list)  # milestones with 0 review cycles
    # Audit-team structured score (None when using legacy review fleet)
    audit_score: dict[str, Any] | None = None


@dataclass
class E2ETestReport:
    """Result of E2E testing phase — tracks backend API and frontend Playwright tests."""

    backend_total: int = 0
    backend_passed: int = 0
    frontend_total: int = 0
    frontend_passed: int = 0
    fix_retries_used: int = 0
    total_fix_cycles: int = 0       # Total fix cycles across both parts
    skipped: bool = False
    skip_reason: str = ""           # "Build failed", "No backend detected", etc.
    health: str = "unknown"         # "passed" | "partial" | "failed" | "skipped"
    failed_tests: list[str] = field(default_factory=list)


@dataclass
class WorkflowResult:
    """Per-workflow outcome from browser testing."""

    workflow_id: int = 0
    workflow_name: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    health: str = "pending"          # pending | passed | failed | skipped
    failed_step: str = ""
    failure_reason: str = ""
    fix_retries_used: int = 0
    screenshots: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)


@dataclass
class BrowserTestReport:
    """Aggregate browser testing phase outcome."""

    total_workflows: int = 0
    passed_workflows: int = 0
    failed_workflows: int = 0
    skipped_workflows: int = 0
    total_fix_cycles: int = 0
    workflow_results: list[WorkflowResult] = field(default_factory=list)
    health: str = "unknown"          # passed | partial | failed | skipped
    skip_reason: str = ""
    regression_sweep_passed: bool = False
    total_screenshots: int = 0


@dataclass
class ContractReport:
    """Contract compliance report from pipeline execution (TECH-029)."""

    total_contracts: int = 0
    verified_contracts: int = 0
    violated_contracts: int = 0
    missing_implementations: int = 0
    violations: list[dict] = field(default_factory=list)
    health: str = "unknown"  # "healthy" | "degraded" | "failed" | "unknown"
    verified_contract_ids: list[str] = field(default_factory=list)
    violated_contract_ids: list[str] = field(default_factory=list)


@dataclass
class EndpointTestReport:
    """Endpoint test results from pipeline execution (TECH-030)."""

    total_endpoints: int = 0
    tested_endpoints: int = 0
    passed_endpoints: int = 0
    failed_endpoints: int = 0
    untested_contracts: list[str] = field(default_factory=list)
    health: str = "unknown"  # "passed" | "partial" | "failed" | "unknown"


_STATE_FILE = "STATE.json"
_CURRENT_SCHEMA_VERSION = 3

# Test file patterns for on-disk counting
_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py", "*.spec.ts", "*.test.ts",
                       "*.spec.js", "*.test.js", "*.spec.tsx", "*.test.tsx")
_TEST_SKIP_SEGMENTS = {"node_modules", "__pycache__", "dist", ".venv", "venv"}


class StateInvariantError(RuntimeError):
    """Raised when STATE.json is about to be written with mutually inconsistent fields.

    The canonical invariant is:
      summary["success"] == (not interrupted) and len(failed_milestones) == 0

    Violation indicates a mutation site bypassed update_milestone_progress /
    finalize or that finalize threw silently (cli.py:13491). Raising here
    fails loud so the bug is caught at write-time rather than at product
    inspection.
    """


def count_test_files(output_dir: Path) -> int:
    """Count actual test files on disk (not requirement checkboxes).

    Scans *output_dir* recursively for files matching common test naming
    conventions while skipping dependency/build directories.
    """
    # Safe walker — prunes node_modules / .pnpm at descent so Windows
    # MAX_PATH inside pnpm's symlink tree can't raise WinError 3
    # (project_walker.py post smoke #9/#10).
    from .project_walker import DEFAULT_SKIP_DIRS, iter_project_files

    merged_skips = set(DEFAULT_SKIP_DIRS) | set(_TEST_SKIP_SEGMENTS)
    seen: set[Path] = set()
    try:
        matches = iter_project_files(
            output_dir, patterns=_TEST_FILE_PATTERNS, skip_dirs=merged_skips,
        )
    except OSError:
        return 0
    for f in matches:
        try:
            resolved = f.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
    return len(seen)


def _reconcile_milestone_lists(state: RunState) -> None:
    """Derive ``completed_milestones`` and ``failed_milestones`` from ``milestone_progress``.

    This ensures a single source of truth: ``milestone_progress[ms]["status"]``
    is canonical, and the two lists are always consistent projections of it.
    DEGRADED milestones are treated as completed so dependent milestones can proceed.
    """
    state.completed_milestones = [
        ms for ms, data in state.milestone_progress.items()
        if data.get("status") in ("COMPLETE", "DEGRADED")
    ]
    state.failed_milestones = [
        ms for ms, data in state.milestone_progress.items()
        if data.get("status") == "FAILED"
    ]


def update_milestone_progress(
    state: RunState,
    milestone_id: str,
    status: str,
) -> None:
    """Update the milestone tracking fields on *state* in place.

    Parameters
    ----------
    state : RunState
        The run state to update.
    milestone_id : str
        The milestone whose status changed.
    status : str
        New status: ``"IN_PROGRESS"``, ``"COMPLETE"``, ``"DEGRADED"``, or ``"FAILED"``.
    """
    status_upper = status.upper()
    if status_upper == "IN_PROGRESS":
        state.current_milestone = milestone_id
    elif status_upper in ("COMPLETE", "DEGRADED"):
        state.current_milestone = ""
        if milestone_id not in state.completed_milestones:
            state.completed_milestones.append(milestone_id)
        # Remove from failed if it was retried successfully
        if milestone_id in state.failed_milestones:
            state.failed_milestones.remove(milestone_id)
    elif status_upper == "FAILED":
        state.current_milestone = ""
        if milestone_id not in state.failed_milestones:
            state.failed_milestones.append(milestone_id)

    state.milestone_progress[milestone_id] = {"status": status_upper}


def get_resume_milestone(state: RunState) -> str | None:
    """Determine which milestone to resume from after an interruption.

    Returns the milestone ID to resume from, or ``None`` if there is
    nothing to resume.
    """
    # If there was a milestone in progress when interrupted, resume there
    if state.current_milestone:
        return state.current_milestone

    # Otherwise find the first milestone in order that isn't complete
    for mid in state.milestone_order:
        if mid not in state.completed_milestones:
            return mid

    return None


def update_completion_ratio(state: RunState) -> None:
    """Recompute completion_ratio from completed/total milestones."""
    total = len(state.milestone_order)
    if total > 0:
        state.completion_ratio = len(state.completed_milestones) / total
    else:
        state.completion_ratio = 0.0


def _dedupe_preserve_order(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    deduped: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _set_extra_state_data(state: RunState, data: dict[str, Any]) -> None:
    object.__setattr__(state, "_extra_state_data", dict(data))


def _get_extra_state_data(state: RunState) -> dict[str, Any]:
    data = getattr(state, "_extra_state_data", {})
    return dict(data) if isinstance(data, dict) else {}


def _canonicalize_state(state: RunState) -> RunState:
    """Normalize loaded or in-memory state to the current schema shape."""
    state.schema_version = _CURRENT_SCHEMA_VERSION
    state.artifacts = state.artifacts if isinstance(state.artifacts, dict) else {}
    state.milestone_progress = state.milestone_progress if isinstance(state.milestone_progress, dict) else {}
    if isinstance(state.v18_config, dict):
        state.v18_config = dict(state.v18_config)
    elif is_dataclass(state.v18_config):
        state.v18_config = asdict(state.v18_config)
    else:
        state.v18_config = {}
    state.wave_progress = state.wave_progress if isinstance(state.wave_progress, dict) else {}
    state.contract_report = state.contract_report if isinstance(state.contract_report, dict) else {}
    state.endpoint_test_report = state.endpoint_test_report if isinstance(state.endpoint_test_report, dict) else {}
    state.truth_scores = state.truth_scores if isinstance(state.truth_scores, dict) else {}
    state.pseudocode_artifacts = state.pseudocode_artifacts if isinstance(state.pseudocode_artifacts, dict) else {}
    state.routing_tier_counts = state.routing_tier_counts if isinstance(state.routing_tier_counts, dict) else {}
    state.stack_contract = state.stack_contract if isinstance(state.stack_contract, dict) else {}
    state.summary = state.summary if isinstance(state.summary, dict) else {}

    state.completed_phases = _dedupe_preserve_order(state.completed_phases if isinstance(state.completed_phases, list) else [])
    state.completed_milestones = _dedupe_preserve_order(
        state.completed_milestones if isinstance(state.completed_milestones, list) else []
    )
    state.failed_milestones = _dedupe_preserve_order(
        state.failed_milestones if isinstance(state.failed_milestones, list) else []
    )
    state.milestone_order = _dedupe_preserve_order(state.milestone_order if isinstance(state.milestone_order, list) else [])
    state.completed_browser_workflows = _dedupe_preserve_order(
        state.completed_browser_workflows if isinstance(state.completed_browser_workflows, list) else []
    )
    state.departments_created = _dedupe_preserve_order(
        state.departments_created if isinstance(state.departments_created, list) else []
    )
    state.registered_artifacts = _dedupe_preserve_order(
        state.registered_artifacts if isinstance(state.registered_artifacts, list) else []
    )
    state.previous_passing_acs = _dedupe_preserve_order(
        state.previous_passing_acs if isinstance(state.previous_passing_acs, list) else []
    )

    if state.milestone_progress:
        _reconcile_milestone_lists(state)
    if state.milestone_order:
        update_completion_ratio(state)
    return state


def save_state(state: RunState, directory: str = ".agent-team") -> Path:
    """Save run state to a JSON file in the given directory.

    Returns the path to the saved state file.

    Reconciles milestone lists before writing to ensure consistency.
    """
    dir_path = Path(directory)
    dir_path.mkdir(parents=True, exist_ok=True)
    _canonicalize_state(state)

    # Reconcile milestone lists from single source of truth before saving
    if state.milestone_progress:
        _reconcile_milestone_lists(state)

    # Create a copy of state data — preserve the in-memory interrupted flag
    data = _get_extra_state_data(state)
    data.pop("summary", None)
    data.update(asdict(state))
    data["schema_version"] = _CURRENT_SCHEMA_VERSION

    # Add summary block for quick inspection (Build 3 SVC-009 contract)
    req_total = state.requirements_total or 0
    req_checked = state.requirements_checked or 0
    convergence = req_checked / req_total if req_total > 0 else 0.0

    # Count actual test files on disk (project root = parent of .agent-team dir)
    project_root = dir_path.parent
    test_files_on_disk = count_test_files(project_root)

    # Endpoint test report (E2E tests) — separate from file counts
    e2e_passed = state.endpoint_test_report.get("passed_endpoints", 0) if state.endpoint_test_report else 0
    e2e_total = state.endpoint_test_report.get("tested_endpoints", 0) if state.endpoint_test_report else 0

    # test_passed/test_total: use actual test file counts, falling back to
    # E2E endpoint counts only when test files aren't found on disk.
    if test_files_on_disk > 0:
        test_passed = test_files_on_disk
        test_total = test_files_on_disk
    else:
        test_passed = e2e_passed
        test_total = e2e_total

    # D-13 + NEW-7: let finalize()-populated summary fields (notably
    # ``success``) win over computed defaults, but the computed default
    # itself honors the write-time invariant — ``success`` is False when
    # either ``interrupted`` OR ``failed_milestones`` is non-empty. This
    # makes mid-pipeline save_state() calls self-consistent with the
    # invariant check below, so the loud-fail raise fires only on an
    # explicit upstream lie (e.g., stale ``state.summary`` carrying a
    # prior phase's True through a new failure).
    finalized = dict(state.summary) if isinstance(state.summary, dict) else {}
    data["summary"] = {
        "success": finalized.get("success", (not state.interrupted) and len(state.failed_milestones) == 0),
        "test_passed": finalized.get("test_passed", test_passed),
        "test_total": finalized.get("test_total", test_total),
        "test_files_found": finalized.get("test_files_found", test_files_on_disk),
        "e2e_passed": finalized.get("e2e_passed", e2e_passed),
        "e2e_total": finalized.get("e2e_total", e2e_total),
        "requirements_checked": finalized.get("requirements_checked", req_checked),
        "requirements_total": finalized.get("requirements_total", req_total),
        "convergence_ratio": finalized.get("convergence_ratio", convergence),
    }
    # Preserve any additional keys set by ``finalize`` callers.
    for k, v in finalized.items():
        data["summary"].setdefault(k, v)

    # NEW-7: STATE.json invariant — summary.success must be consistent with
    # failed_milestones + interrupted. Fails loud at write-time rather than
    # letting an inconsistent report escape to disk (build-l root cause).
    _expected_success = (not state.interrupted) and len(state.failed_milestones) == 0
    if bool(data["summary"].get("success")) != _expected_success:
        raise StateInvariantError(
            f"STATE.json invariant violation: summary.success="
            f"{data['summary'].get('success')!r} but "
            f"interrupted={state.interrupted!r}, "
            f"failed_milestones={state.failed_milestones!r} "
            f"(expected success={_expected_success!r}). "
            f"Likely cause: finalize() was not called or threw silently. "
            f"See cli.py:13491-13498."
        )

    state_path = dir_path / _STATE_FILE

    # Atomic write: write to temp file, then replace atomically
    fd, temp_path = tempfile.mkstemp(
        dir=str(dir_path),
        prefix=".STATE_",
        suffix=".tmp"
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, state_path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temp_path)
        raise

    return state_path


def _expect(value: Any, typ: type | tuple[type, ...], default: Any) -> Any:
    """Return value if it matches the expected type, otherwise return default."""
    return value if isinstance(value, typ) else default


def load_state(directory: str = ".agent-team") -> RunState | None:
    """Load run state from the JSON file in the given directory.

    Returns None if no state file exists or it cannot be parsed.
    """
    state_path = Path(directory) / _STATE_FILE
    if not state_path.is_file():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        state = RunState(
            run_id=_expect(data.get("run_id", ""), str, ""),
            task=_expect(data.get("task", ""), str, ""),
            depth=_expect(data.get("depth", "standard"), str, "standard"),
            current_phase=_expect(data.get("current_phase", "init"), str, "init"),
            completed_phases=_expect(data.get("completed_phases", []), list, []),
            total_cost=_expect(data.get("total_cost", 0.0), (int, float), 0.0),
            artifacts=_expect(data.get("artifacts", {}), dict, {}),
            interrupted=_expect(data.get("interrupted", False), bool, False),
            timestamp=_expect(data.get("timestamp", ""), str, ""),
            convergence_cycles=_expect(data.get("convergence_cycles", 0), (int, float), 0),
            requirements_checked=_expect(data.get("requirements_checked", 0), (int, float), 0),
            requirements_total=_expect(data.get("requirements_total", 0), (int, float), 0),
            error_context=_expect(data.get("error_context", ""), str, ""),
            milestone_progress=_expect(data.get("milestone_progress", {}), dict, {}),
            v18_config=_expect(data.get("v18_config", {}), dict, {}),
            wave_progress=_expect(data.get("wave_progress", {}), dict, {}),
            # Schema version 3 fields — backward-compatible defaults
            schema_version=_expect(data.get("schema_version", 1), (int, float), 1),
            current_milestone=_expect(data.get("current_milestone", ""), str, ""),
            completed_milestones=_expect(data.get("completed_milestones", []), list, []),
            failed_milestones=_expect(data.get("failed_milestones", []), list, []),
            milestone_order=_expect(data.get("milestone_order", []), list, []),
            completion_ratio=_expect(data.get("completion_ratio", 0.0), (int, float), 0.0),
            completed_browser_workflows=_expect(data.get("completed_browser_workflows", []), list, []),
            agent_teams_active=_expect(data.get("agent_teams_active", False), bool, False),
            # Enterprise mode tracking
            enterprise_mode_active=_expect(data.get("enterprise_mode_active", False), bool, False),
            ownership_map_validated=_expect(data.get("ownership_map_validated", False), bool, False),
            waves_completed=_expect(data.get("waves_completed", 0), (int, float), 0),
            domain_agents_deployed=_expect(data.get("domain_agents_deployed", 0), (int, float), 0),
            # Enterprise v2: department model tracking
            department_mode_active=_expect(data.get("department_mode_active", False), bool, False),
            departments_created=_expect(data.get("departments_created", []), list, []),
            manager_count=_expect(data.get("manager_count", 0), (int, float), 0),
            # Audit tracking (backported from v0)
            audit_score=_expect(data.get("audit_score", 0.0), (int, float), 0.0),
            audit_health=_expect(data.get("audit_health", ""), str, ""),
            audit_fix_rounds=_expect(data.get("audit_fix_rounds", 0), (int, float), 0),
            # Build 2 fields — backward-compatible defaults
            contract_report=_expect(data.get("contract_report", {}), dict, {}),
            endpoint_test_report=_expect(data.get("endpoint_test_report", {}), dict, {}),
            registered_artifacts=_expect(data.get("registered_artifacts", []), list, []),
            # Truth scoring (Feature #2) — backward-compatible defaults
            truth_scores=_expect(data.get("truth_scores", {}), dict, {}),
            previous_passing_acs=_expect(data.get("previous_passing_acs", []), list, []),
            regression_count=_expect(data.get("regression_count", 0), (int, float), 0),
            # Pseudocode phase tracking
            pseudocode_validated=_expect(data.get("pseudocode_validated", False), bool, False),
            pseudocode_artifacts=_expect(data.get("pseudocode_artifacts", {}), dict, {}),
            # Gate enforcement tracking (Feature #3)
            gate_results=_expect(data.get("gate_results", []), list, []),
            gates_passed=_expect(data.get("gates_passed", 0), (int, float), 0),
            gates_failed=_expect(data.get("gates_failed", 0), (int, float), 0),
            # Pattern memory tracking (Feature #4) — backward-compatible defaults
            patterns_captured=_expect(data.get("patterns_captured", 0), (int, float), 0),
            patterns_retrieved=_expect(data.get("patterns_retrieved", 0), (int, float), 0),
            # Fix recipe tracking (Feature #4.1) — backward-compatible defaults
            recipes_captured=_expect(data.get("recipes_captured", 0), (int, float), 0),
            recipes_applied=_expect(data.get("recipes_applied", 0), (int, float), 0),
            # Convergence debug & escalation tracking — backward-compatible defaults
            debug_fleet_deployed=_expect(data.get("debug_fleet_deployed", False), bool, False),
            escalation_triggered=_expect(data.get("escalation_triggered", False), bool, False),
            # Routing tracking (Feature #5) — backward-compatible defaults
            routing_decisions=_expect(data.get("routing_decisions", []), list, []),
            routing_tier_counts=_expect(data.get("routing_tier_counts", {}), dict, {}),
            stack_contract=_expect(data.get("stack_contract", {}), dict, {}),
            summary=_expect(data.get("summary", {}), dict, {}),
        )
        _set_extra_state_data(
            state,
            {
                key: value
                for key, value in data.items()
                if key not in _RUN_STATE_FIELD_NAMES and key != "summary"
            },
        )
        return _canonicalize_state(state)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError, UnicodeDecodeError):
        return None


def clear_state(directory: str = ".agent-team") -> None:
    """Delete the state file after a successful run."""
    state_path = Path(directory) / _STATE_FILE
    with contextlib.suppress(OSError):
        state_path.unlink(missing_ok=True)


def validate_for_resume(state: RunState) -> list[str]:
    """Validate saved state for resume. Returns warning/error messages."""
    issues: list[str] = []
    if not state.task:
        issues.append("ERROR: No task recorded in saved state.")
    if state.timestamp:
        try:
            saved = datetime.fromisoformat(state.timestamp)
            age_h = (datetime.now(timezone.utc) - saved).total_seconds() / 3600
            if age_h > 24:
                issues.append(f"WARNING: State is {int(age_h)}h old. Files may have changed.")
        except (ValueError, TypeError):
            pass
    return issues


def is_stale(state: RunState, current_task: str) -> bool:
    """Check if a saved state is stale (from a different task).

    A state is considered stale if the saved task differs from the
    current task (case-insensitive, stripped comparison).
    """
    if not state.task or not current_task:
        return True
    return state.task.strip().lower() != current_task.strip().lower()
