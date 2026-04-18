"""Coordinated Builder — Orchestrates the audit-fix loop.

Runs the initial build, then iterates: audit → decide → fix PRD → rebuild
until convergence or a stop condition is met.

Typical usage::

    from pathlib import Path
    from agent_team_v15.coordinated_builder import run_coordinated_build

    result = run_coordinated_build(
        prd_path=Path("my_app.md"),
        cwd=Path("./output"),
        config={"max_budget": 300, "max_iterations": 4, "depth": "exhaustive"},
    )
    print(f"Final: {result.final_score:.1f}%, Runs: {result.total_runs}, Cost: ${result.total_cost:.2f}")
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent_team_v15.audit_agent import AuditReport, Finding, FindingCategory, Severity, run_full_audit
from agent_team_v15.config_agent import (
    LoopDecision,
    LoopState,
    evaluate_stop_conditions,
)
from agent_team_v15.fix_executor import execute_unified_fix
from agent_team_v15.fix_prd_agent import generate_fix_prd

# Browser test phase imports (lazy — only loaded when browser tests run)
_browser_test_loaded = False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CoordinatedBuildResult:
    """Result of a coordinated build run."""

    total_runs: int
    total_cost: float
    final_score: float
    final_acs_passed: int
    final_acs_total: int
    remaining_findings: list[Finding] = field(default_factory=list)
    stop_reason: str = ""
    success: bool = False
    error: str = ""
    # Browser test phase results (v17)
    browser_test_passed: Optional[bool] = None
    browser_test_report: Optional[Any] = None  # BrowserTestReport
    browser_fix_iterations: int = 0
    # Truth scoring / regression (Feature #2)
    regressions_detected: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CoordinatedBuildError(Exception):
    """Base error for coordinated builder."""


class BuilderRunError(CoordinatedBuildError):
    """Builder subprocess failed."""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    """Print a timestamped log message."""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ---------------------------------------------------------------------------
# Fix recipe helpers
# ---------------------------------------------------------------------------

_FILE_PATH_RE = re.compile(r"^([\w./\\-]+\.\w+)")


def _extract_file_paths_from_finding(finding: Any) -> list[str]:
    """Parse file paths from a finding's evidence strings."""
    paths: list[str] = []
    evidence = getattr(finding, "evidence", []) or []
    if isinstance(evidence, str):
        evidence = [evidence]
    for item in evidence:
        if not isinstance(item, str):
            continue
        # Strip line/column suffixes: "path/file.ts:10" or "path/file.ts:10-20"
        cleaned = item.split(" -- ")[0].strip()
        cleaned = cleaned.split(":")[0].strip() if ":" in cleaned else cleaned
        m = _FILE_PATH_RE.match(cleaned)
        if m:
            paths.append(m.group(1))
    # Also check file_path attribute directly
    fp = getattr(finding, "file_path", "") or ""
    if fp and fp not in paths:
        paths.append(fp)
    return paths


def _snapshot_failing_findings(
    report: Any,
    cwd: Path,
    max_files: int = 50,
    max_file_size: int = 102400,
) -> dict[str, dict[str, str]]:
    """Snapshot file contents for failing findings before a fix build."""
    snapshots: dict[str, dict[str, str]] = {}
    total_files = 0
    for finding in getattr(report, "findings", []):
        verdict = getattr(finding, "verdict", "") or ""
        severity = getattr(finding, "severity", None)
        sev_val = severity.value if hasattr(severity, "value") else str(severity)
        if verdict.upper() == "PASS" or sev_val in ("acceptable_deviation",):
            continue
        fid = getattr(finding, "id", "") or getattr(finding, "finding_id", "")
        if not fid:
            continue
        file_paths = _extract_file_paths_from_finding(finding)
        if not file_paths:
            continue
        file_contents: dict[str, str] = {}
        for fp in file_paths:
            if total_files >= max_files:
                _log(f"[RECIPE] Snapshot cap reached ({max_files} files)")
                break
            full = cwd / fp
            if not full.is_file():
                continue
            try:
                size = full.stat().st_size
                if size > max_file_size:
                    _log(f"[RECIPE] Skipping large file: {fp} ({size} bytes)")
                    continue
                content = full.read_text(encoding="utf-8")
                file_contents[fp] = content
                total_files += 1
            except (UnicodeDecodeError, OSError):
                continue
        if file_contents:
            snapshots[fid] = file_contents
    return snapshots


def _capture_resolved_recipes(
    current_report: Any,
    previous_report: Any | None,
    pending_snapshots: dict[str, dict[str, str]],
    cwd: Path,
    agent_team_dir: Path,
) -> int:
    """Capture fix recipes for findings that resolved since last audit."""
    if previous_report is None or not pending_snapshots:
        return 0

    # Build set of currently passing finding IDs
    current_pass_ids: set[str] = set()
    for f in getattr(current_report, "findings", []):
        verdict = getattr(f, "verdict", "") or ""
        if verdict.upper() == "PASS":
            fid = getattr(f, "id", "") or getattr(f, "finding_id", "")
            if fid:
                current_pass_ids.add(fid)

    # Build set of previously failing finding IDs
    prev_fail_ids: set[str] = set()
    for f in getattr(previous_report, "findings", []):
        verdict = getattr(f, "verdict", "") or ""
        if verdict.upper() != "PASS":
            fid = getattr(f, "id", "") or getattr(f, "finding_id", "")
            if fid:
                prev_fail_ids.add(fid)

    # Resolved = was failing, now passing
    resolved = prev_fail_ids & current_pass_ids
    if not resolved:
        return 0

    captured = 0
    try:
        from agent_team_v15.pattern_memory import FixRecipe, PatternMemory

        db_path = agent_team_dir / "pattern_memory.db"
        memory = PatternMemory(db_path=db_path)
        try:
            for fid in resolved:
                if fid not in pending_snapshots:
                    continue
                # Find description from current report
                desc = ""
                for f in getattr(current_report, "findings", []):
                    f_id = getattr(f, "id", "") or getattr(f, "finding_id", "")
                    if f_id == fid:
                        desc = getattr(f, "title", "") or getattr(f, "description", "")
                        break

                for fp, before_content in pending_snapshots[fid].items():
                    full = cwd / fp
                    if not full.is_file():
                        continue
                    try:
                        after_content = full.read_text(encoding="utf-8")
                    except (UnicodeDecodeError, OSError):
                        continue
                    if before_content == after_content:
                        continue  # No change — skip

                    diff_text = "".join(difflib.unified_diff(
                        before_content.splitlines(keepends=True),
                        after_content.splitlines(keepends=True),
                        fromfile=f"a/{fp}",
                        tofile=f"b/{fp}",
                    ))
                    if not diff_text:
                        continue
                    # Truncate very large diffs for storage
                    if len(diff_text) > 51200:
                        diff_text = diff_text[:51200] + "\n... (truncated)"

                    recipe = FixRecipe(
                        finding_id=fid,
                        finding_description=desc[:500],
                        file_path=fp,
                        diff_text=diff_text,
                    )
                    memory.store_fix_recipe(recipe)
                    captured += 1
        finally:
            memory.close()
    except Exception as exc:
        _log(f"[RECIPE] Capture failed: {exc}")
    return captured


def _load_recipes_for_findings(
    findings: list[Any],
    cwd: Path,
    agent_team_dir: Path,
) -> str:
    """Load and format fix recipes for findings. Returns markdown or empty string."""
    try:
        from agent_team_v15.pattern_memory import PatternMemory

        db_path = agent_team_dir / "pattern_memory.db"
        if not db_path.exists():
            return ""
        memory = PatternMemory(db_path=db_path)
        try:
            finding_dicts = []
            for f in findings:
                fid = getattr(f, "id", "") or getattr(f, "finding_id", "")
                desc = getattr(f, "title", "") or getattr(f, "description", "")
                if fid:
                    finding_dicts.append({"finding_id": fid, "description": desc})
            if not finding_dicts:
                return ""
            return memory.format_recipes_for_prompt(finding_dicts)
        finally:
            memory.close()
    except Exception as exc:
        _log(f"[RECIPE] Load failed: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Violation → Finding converters (gate promotions)
# ---------------------------------------------------------------------------


def _depth_violation_to_finding(violation_text: str) -> Finding:
    """Convert a check_implementation_depth violation string to a Finding."""
    # Extract the check code (e.g., DEPTH-001) and file path
    parts = violation_text.split(":", 1)
    check_code = parts[0].strip() if len(parts) > 1 else "DEPTH-000"
    detail = parts[1].strip() if len(parts) > 1 else violation_text

    return Finding(
        id=f"GATE-{check_code}",
        feature="IMPLEMENTATION_DEPTH",
        acceptance_criterion="Implementation must meet depth requirements",
        severity=Severity.MEDIUM,
        category=FindingCategory.CODE_FIX,
        title=f"Implementation depth violation: {check_code}",
        description=detail,
        prd_reference="builder depth gate",
        current_behavior=detail,
        expected_behavior="Complete implementation with tests, error handling, and UI states",
        estimated_effort="small",
    )


def _contract_violation_to_finding(violation_text: str) -> Finding:
    """Convert a verify_endpoint_contracts violation string to a Finding."""
    parts = violation_text.split(":", 1)
    check_code = parts[0].strip() if len(parts) > 1 else "CONTRACT-000"
    detail = parts[1].strip() if len(parts) > 1 else violation_text

    return Finding(
        id=f"GATE-{check_code}",
        feature="ENDPOINT_CONTRACTS",
        acceptance_criterion="Frontend API calls must match endpoint contracts",
        severity=Severity.HIGH,
        category=FindingCategory.CODE_FIX,
        title=f"Endpoint contract violation: {check_code}",
        description=detail,
        prd_reference="contract-first protocol",
        current_behavior=detail,
        expected_behavior="All frontend API calls must match ENDPOINT_CONTRACTS.md entries",
        estimated_effort="medium",
    )


def _spot_violation_to_finding(violation: Any) -> Finding:
    """Convert a run_spot_checks Violation to a Finding."""
    check = getattr(violation, "check", "SPOT-000")
    message = getattr(violation, "message", str(violation))
    file_path = getattr(violation, "file_path", "")
    severity_str = getattr(violation, "severity", "warning")

    sev_map = {"error": Severity.HIGH, "warning": Severity.MEDIUM, "info": Severity.LOW}
    severity = sev_map.get(severity_str, Severity.MEDIUM)

    return Finding(
        id=f"GATE-{check}",
        feature="ANTI_PATTERN",
        acceptance_criterion="Code must not contain anti-patterns",
        severity=severity,
        category=FindingCategory.CODE_FIX,
        title=f"Anti-pattern: {check}",
        description=message,
        prd_reference="quality gate spot check",
        current_behavior=message,
        expected_behavior="No anti-pattern violations",
        file_path=file_path,
        estimated_effort="small",
    )


def _check_infrastructure_deliverables(cwd: Path) -> list[str]:
    """Check that required infrastructure files exist in the build output.

    Returns a list of violation strings (empty = all present).
    """
    violations: list[str] = []

    # 1. Dockerfile
    dockerfile = cwd / "Dockerfile"
    if not dockerfile.is_file():
        # Also check common alternative locations
        alt_locations = [cwd / "apps" / "api" / "Dockerfile", cwd / "docker" / "Dockerfile"]
        if not any(p.is_file() for p in alt_locations):
            violations.append("INFRA-001: Dockerfile is missing — multi-stage build for backend API service required")

    # 2. docker-compose.yml
    compose_files = [
        cwd / "docker-compose.yml",
        cwd / "docker-compose.yaml",
        cwd / "docker-compose.dev.yml",
        cwd / "docker-compose.dev.yaml",
    ]
    if not any(p.is_file() for p in compose_files):
        violations.append("INFRA-002: docker-compose.yml is missing — development environment with app, db, cache required")

    # 3. .env.example
    env_example_files = [
        cwd / ".env.example",
        cwd / ".env.sample",
        cwd / ".env.template",
        cwd / "apps" / "api" / ".env.example",
    ]
    if not any(p.is_file() for p in env_example_files):
        violations.append(
            "INFRA-003: .env.example is missing — must document ALL required environment variables "
            "(DATABASE_URL, REDIS_URL, JWT keys, third-party API keys)"
        )

    # 4. Database migrations
    migration_dirs = [
        cwd / "database" / "migrations",
        cwd / "src" / "database" / "migrations",
        cwd / "apps" / "api" / "src" / "database" / "migrations",
        cwd / "prisma" / "migrations",
        cwd / "apps" / "api" / "prisma" / "migrations",
        cwd / "migrations",
    ]
    has_migrations = False
    for mdir in migration_dirs:
        if mdir.is_dir():
            # Check it actually has migration files (not empty dir)
            migration_files = [
                f for f in mdir.iterdir()
                if f.is_file() and f.suffix in (".ts", ".js", ".sql")
            ]
            # Also check subdirs (Prisma uses timestamp dirs)
            migration_subdirs = [d for d in mdir.iterdir() if d.is_dir()]
            if migration_files or migration_subdirs:
                has_migrations = True
                break
    if not has_migrations:
        # Check for entity/model files — if they exist but no migrations, that's a violation
        entity_dirs = [
            cwd / "src" / "database" / "entities",
            cwd / "apps" / "api" / "src" / "database" / "entities",
            cwd / "src" / "entities",
        ]
        schema_files = [cwd / "prisma" / "schema.prisma", cwd / "apps" / "api" / "prisma" / "schema.prisma"]
        has_entities = any(d.is_dir() and any(d.iterdir()) for d in entity_dirs if d.is_dir())
        has_schema = any(f.is_file() for f in schema_files)
        if has_entities or has_schema:
            violations.append(
                "INFRA-004: Database migrations directory is empty or missing — "
                "entities/models exist but no migration files were generated. "
                "For TypeORM: run typeorm migration:generate. For Prisma: run prisma migrate dev."
            )

    return violations


def _infra_violation_to_finding(violation_text: str) -> Finding:
    """Convert an infrastructure deliverable violation to a Finding."""
    parts = violation_text.split(":", 1)
    check_code = parts[0].strip() if len(parts) > 1 else "INFRA-000"
    detail = parts[1].strip() if len(parts) > 1 else violation_text

    return Finding(
        id=f"GATE-{check_code}",
        feature="INFRASTRUCTURE",
        acceptance_criterion="Infrastructure deliverables must be present for a complete build",
        severity=Severity.HIGH,
        category=FindingCategory.MISSING_FEATURE,
        title=f"Infrastructure missing: {check_code}",
        description=detail,
        prd_reference="infrastructure deliverables gate",
        current_behavior=detail,
        expected_behavior="All infrastructure files (Dockerfile, docker-compose, .env.example, migrations) must exist",
        estimated_effort="medium",
    )


def _enforcement_violation_to_finding(violation_text: str, gate_name: str) -> Finding:
    """Convert a Mission 3 enforcement violation string to a Finding."""
    parts = violation_text.split(":", 1)
    check_code = parts[0].strip() if len(parts) > 1 else f"{gate_name}-000"
    detail = parts[1].strip() if len(parts) > 1 else violation_text

    return Finding(
        id=f"GATE-{check_code}",
        feature=gate_name.upper(),
        acceptance_criterion=f"{gate_name} enforcement gate",
        severity=Severity.HIGH,
        category=FindingCategory.CODE_FIX,
        title=f"{gate_name} violation: {check_code}",
        description=detail,
        prd_reference=f"enforcement hardening: {gate_name}",
        current_behavior=detail,
        expected_behavior=f"No {gate_name} violations",
        estimated_effort="medium",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_coordinated_build(
    prd_path: Path,
    cwd: Path,
    config: Optional[dict[str, Any]] = None,
) -> CoordinatedBuildResult:
    """Run the full coordinated build: initial build + audit-fix loop.

    Args:
        prd_path: Path to the original PRD file.
        cwd: Working directory / output directory for the build.
        config: Configuration dict with keys:
            max_budget (float): Maximum total spend. Default: 300.
            max_iterations (int): Maximum runs including initial. Default: 4.
            min_improvement (float): Minimum score improvement %. Default: 3.0.
            depth (str): Build depth. Default: "exhaustive".
            audit_model (str): Model for audit Claude calls. Default: "claude-opus-4-6".
            skip_initial_build (bool): Skip initial build (for testing). Default: False.

    Returns:
        CoordinatedBuildResult with final scores and remaining findings.
    """
    config = config or {}
    agent_team_dir = cwd / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing coordinated state (resume)
    state = LoopState.load(agent_team_dir)
    if state and state.status in ("running", "converged", "stopped", "failed"):
        if state.status != "running":
            _log(f"Re-opening previously {state.status} build at run {state.current_run}")
            state.status = "running"
            state.stop_reason = ""
        else:
            _log(f"Resuming from run {state.current_run} (${state.total_cost:.2f} spent)")
        # Override config from CLI args (allows bumping max_iterations on resume)
        state.max_budget = config.get("max_budget", state.max_budget)
        state.max_iterations = config.get("max_iterations", state.max_iterations)
        state.min_improvement_threshold = config.get("min_improvement", state.min_improvement_threshold)
        state.audit_model = config.get("audit_model", state.audit_model)
    else:
        state = LoopState(
            original_prd_path=str(prd_path),
            codebase_path=str(cwd),
            max_budget=config.get("max_budget", 300.0),
            max_iterations=config.get("max_iterations", 4),
            min_improvement_threshold=config.get("min_improvement", 3.0),
            depth=config.get("depth", "exhaustive"),
            audit_model=config.get("audit_model", "claude-opus-4-6"),
        )

    # --- Run 1: Initial build ---
    if state.current_run == 0 and not config.get("skip_initial_build", False):
        _log("=" * 60)
        _log("RUN 1: INITIAL BUILD")
        _log("=" * 60)

        try:
            initial_cost = _run_builder(prd_path, cwd, config)
        except BuilderRunError as e:
            state.status = "failed"
            state.stop_reason = f"BUILDER_FAILURE: {e}"
            state.save(agent_team_dir)
            return CoordinatedBuildResult(
                total_runs=0,
                total_cost=0,
                final_score=0,
                final_acs_passed=0,
                final_acs_total=0,
                stop_reason=str(e),
                error=str(e),
            )

        _log(f"Initial build complete. Cost: ${initial_cost:.2f}")

        # Run migration generation after initial build
        try:
            migration_issues = _run_migration_generation(cwd)
            if migration_issues:
                _log(f"[MIGRATION] {len(migration_issues)} blocking migration issue(s) after initial build:")
                for _mi in migration_issues:
                    _log(f"  {_mi}")
        except Exception as e:
            _log(f"[MIGRATION] Migration generation skipped: {e}")

        # Git snapshot
        _git_snapshot(cwd, 1)
    elif config.get("skip_initial_build", False) and state.current_run == 0:
        initial_cost = config.get("initial_cost", 0.0)
        _log(f"Skipping initial build (cost override: ${initial_cost:.2f})")
    else:
        initial_cost = 0.0

    # --- Audit-Fix Loop ---
    last_report: Optional[AuditReport] = None
    pending_snapshots: dict[str, dict[str, str]] = {}

    while True:
        run_num = state.current_run + 1

        _log("=" * 60)
        _log(f"AUDIT (after Run {run_num - 1 if run_num > 1 else 1})")
        _log("=" * 60)

        # Phase F: budget advisory — emit a note when crossed but always
        # continue. Audit runs until convergence / plateau / max_iterations
        # (see config_agent.evaluate_stop_conditions).
        if state.total_cost >= state.max_budget:
            _log(
                f"BUDGET ADVISORY: cumulative ${state.total_cost:.2f} has "
                f"crossed configured max_budget ${state.max_budget:.2f}. "
                f"Continuing audit (no cap enforced)."
            )

        # Run audit
        try:
            previous_report = last_report
            report = _run_audit(
                prd_path=prd_path,
                cwd=cwd,
                config={"audit_model": state.audit_model},
                run_number=run_num,
                previous_report=previous_report,
            )
        except Exception as e:
            _log(f"Audit failed: {e}")
            # Retry once (preserve previous_report for regression detection)
            try:
                report = _run_audit(
                    prd_path=prd_path,
                    cwd=cwd,
                    config={"audit_model": state.audit_model},
                    run_number=run_num,
                    previous_report=previous_report,
                )
            except Exception as e2:
                state.status = "failed"
                state.stop_reason = f"AUDIT_FAILURE: {e2}"
                state.save(agent_team_dir)
                return _build_result(state, last_report, str(e2))

        # Save audit report
        report_path = agent_team_dir / f"audit_run{run_num}.json"
        report_path.write_text(report.to_json(), encoding="utf-8")

        _log(
            f"Score: {report.score:.1f}%, "
            f"ACs: {report.passed_acs}/{report.total_acs}, "
            f"CRITICAL: {report.critical_count}, HIGH: {report.high_count}, "
            f"Regressions: {len(report.regressions)}"
        )

        # --- Regression detection (Feature #2) ---
        _log("[REGRESSION] Checking for regressions...")
        regression_acs = _check_regressions(report, last_report)
        if regression_acs:
            _log(
                f"[REGRESSION] REGRESSION DETECTED: {len(regression_acs)} previously-passing "
                f"ACs now failing: {regression_acs[:5]}{'...' if len(regression_acs) > 5 else ''}"
            )
            state.regression_count = getattr(state, 'regression_count', 0) + len(regression_acs)
            rollback_msg = _suggest_rollback(cwd, regression_acs, run_num)
            _log(rollback_msg)
        else:
            _log("[REGRESSION] No regressions detected")

        # --- Truth scoring (Feature #2) ---
        try:
            from agent_team_v15.quality_checks import TruthScorer
            truth_scorer = TruthScorer(cwd)
            truth_score = truth_scorer.score()
            state.last_truth_score = truth_score.overall
            state.last_truth_gate = truth_score.gate.value
            state.truth_dimensions = dict(truth_score.dimensions)
            _log(
                f"[TRUTH] Score: {truth_score.overall:.3f} "
                f"(gate: {truth_score.gate.value}) "
                f"dims: {', '.join(f'{k}={v:.2f}' for k, v in truth_score.dimensions.items())}"
            )
        except Exception as e:
            _log(f"Truth scoring skipped: {e}")

        # --- Quality score prediction / regression guardrail ---
        try:
            from agent_team_v15.quality_checks import compute_quality_score
            _qs = compute_quality_score(cwd)
            _log(
                f"[QUALITY] Predicted score: {_qs['predicted_score']}/{_qs['base']} "
                f"(deductions: {_qs['total_deduction']}, "
                f"stubs: {_qs['scan_counts']['handler_stubs']}, "
                f"spots: {_qs['scan_counts']['spot_checks']})"
            )
        except Exception as e:
            _log(f"Quality score prediction skipped: {e}")

        # --- Department skill update (Feature #3.5) ---
        try:
            from agent_team_v15.skills import update_skills_from_build as _update_skills_cb
            from agent_team_v15.state import RunState as _CbRunState
            # Build a lightweight state-like object with truth scores
            _cb_skill_state = type("_SkillState", (), {
                "truth_scores": dict(state.truth_dimensions) if hasattr(state, "truth_dimensions") else {},
            })()
            if hasattr(state, "last_truth_score") and state.last_truth_score > 0:
                _cb_skill_state.truth_scores["overall"] = state.last_truth_score
            _cb_skills_dir = cwd / ".agent-team" / "skills"
            # Use the per-run audit report (coordinated builder writes audit_runN.json, not AUDIT_REPORT.json)
            _cb_audit_path = agent_team_dir / f"audit_run{run_num}.json"
            _cb_gate_log = cwd / ".agent-team" / "GATE_AUDIT.log"
            _update_skills_cb(
                skills_dir=_cb_skills_dir,
                state=_cb_skill_state,
                audit_report_path=_cb_audit_path,
                gate_log_path=_cb_gate_log,
            )
            _log("[SKILL] Department skills updated from audit cycle")
        except Exception as e:
            _log(f"Skill update skipped: {e}\n{traceback.format_exc()}")

        # HOOK: post_audit — emit for coordinated build audit cycle
        try:
            _cb_hook_registry = config.get("hook_registry")
            if _cb_hook_registry is not None:
                _cb_hook_registry.emit(
                    "post_audit",
                    state=_cb_skill_state,
                    config=config,
                    cwd=str(cwd),
                    audit_report=report,
                )
                _log("[HOOK] post_audit hooks executed from coordinated build")
        except Exception as e:
            _log(f"[HOOK] post_audit emission skipped: {e}")

        # --- Fix recipe capture (Feature #4.1) ---
        try:
            recipes_captured = _capture_resolved_recipes(
                current_report=report,
                previous_report=previous_report,
                pending_snapshots=pending_snapshots,
                cwd=cwd,
                agent_team_dir=agent_team_dir,
            )
            if recipes_captured > 0:
                _log(f"[RECIPE] Captured {recipes_captured} fix recipe(s) from resolved findings")
        except Exception as e:
            _log(f"[RECIPE] Recipe capture skipped: {e}")

        # Record the run
        if state.current_run == 0:
            # First audit — record initial build
            state.add_run(report, initial_cost, run_type="initial", prd_path=str(prd_path))
        else:
            # Fix run — cost was tracked when builder ran
            pass  # Already recorded in the fix section below

        state.save(agent_team_dir)

        # Evaluate stop conditions
        decision = evaluate_stop_conditions(state, report)

        # Gate enforcement: if gate_enforcement is provided in config,
        # check convergence before allowing STOP
        _cb_gate_config = config.get("gate_enforcement", {})
        if _cb_gate_config.get("enabled", False) and decision.action == "STOP":
            # Check if convergence threshold is actually met
            req_ratio = report.passed_acs / report.total_acs if report.total_acs > 0 else 0.0
            min_ratio = _cb_gate_config.get("min_convergence_ratio", 0.9)
            if req_ratio < min_ratio and report.critical_count > 0:
                _log(
                    f"GATE OVERRIDE: Stop decision overridden — "
                    f"convergence {req_ratio:.1%} < {min_ratio:.1%} with "
                    f"{report.critical_count} critical findings. Forcing CONTINUE."
                )
                decision = LoopDecision(
                    action="CONTINUE",
                    reason=f"Gate override: convergence {req_ratio:.1%} below threshold",
                    findings_for_fix=decision.findings_for_fix or [
                        f for f in report.findings
                        if f.severity.value in ("critical", "high")
                    ],
                    run_number=state.current_run,
                )

        if decision.circuit_breaker_level == 1:
            _log(f"WARNING: {decision.reason}")

        # --- Post-audit quality gate checks (BLOCKING — gate promotions) ---
        _gate_findings: list[Finding] = []
        try:
            from agent_team_v15.quality_checks import (
                check_agent_deployment,
                check_implementation_depth,
                check_test_colocation_quality,
                detect_pagination_wrapper_mismatch,
                run_dto_contract_scan,
                run_spot_checks,
                scan_generated_client_field_alignment,
                scan_generated_client_import_usage,
                scan_request_body_casing,
                verify_contracts_exist,
                verify_endpoint_contracts,
                verify_requirement_granularity,
                verify_review_integrity,
            )

            _depth = config.get("depth", state.depth)

            # Gate 1 (Level A): Implementation depth → feed fix cycle
            depth_violations = check_implementation_depth(cwd)
            if depth_violations:
                _log(f"[DEPTH] {len(depth_violations)} implementation depth violation(s) → fix cycle")
                for _dv in depth_violations[:5]:
                    _log(f"  {_dv}")
                _gate_findings.extend(
                    _depth_violation_to_finding(v) for v in depth_violations
                )

            # Gate 2 (Level A): Endpoint contracts → feed fix cycle
            contract_violations = verify_endpoint_contracts(cwd)
            if contract_violations:
                _log(f"[CONTRACT] {len(contract_violations)} endpoint contract violation(s) → fix cycle")
                for _cv in contract_violations[:5]:
                    _log(f"  {_cv}")
                _gate_findings.extend(
                    _contract_violation_to_finding(v) for v in contract_violations
                )

            # Gate 7 (Level A): Spot checks → feed fix cycle
            spot_violations = run_spot_checks(cwd)
            if spot_violations:
                _log(f"[SPOT] {len(spot_violations)} anti-pattern violation(s) → fix cycle")
                for _sv in spot_violations[:5]:
                    _log(f"  [{_sv.check}] {_sv.message}")
                _gate_findings.extend(
                    _spot_violation_to_finding(v) for v in spot_violations
                )

            # Gate 7.5 (Level A): DTO contract completeness → feed fix cycle
            dto_contract_violations = run_dto_contract_scan(cwd)
            if dto_contract_violations:
                _log(f"[DTO] {len(dto_contract_violations)} DTO contract violation(s) → fix cycle")
                for _dv in dto_contract_violations[:5]:
                    _log(f"  [{_dv.check}] {_dv.message}")
                for _dv2 in dto_contract_violations:
                    _gate_findings.append(Finding(
                        id=f"GATE-{_dv2.check}",
                        feature="CONTRACT",
                        acceptance_criterion=_dv2.check,
                        severity=Severity.CRITICAL,
                        category=FindingCategory.CODE_FIX,
                        title=f"DTO contract gap: {_dv2.check}",
                        description=_dv2.message,
                        prd_reference="Wave C typed-client generation",
                        current_behavior=_dv2.message,
                        expected_behavior=(
                            "NestJS DTO fields must keep Swagger metadata and camelCase names "
                            "so Wave C can generate complete client types"
                        ),
                        file_path=_dv2.file_path,
                        line_number=_dv2.line,
                        estimated_effort="small",
                    ))

            # Gate 8 (Level A): Wiring mismatches → feed fix cycle
            wiring_violations = [
                *scan_request_body_casing(cwd),
                *scan_generated_client_import_usage(cwd),
                *scan_generated_client_field_alignment(cwd),
            ]
            if wiring_violations:
                _log(f"[WIRING] {len(wiring_violations)} wiring violation(s) → fix cycle")
                for _wv in wiring_violations[:5]:
                    _log(f"  [{_wv.check}] {_wv.message}")
                for _wv2 in wiring_violations:
                    if _wv2.check == "WIRING-CLIENT-001":
                        acceptance = (
                            "Frontend must import and call generated API client functions "
                            "from packages/api-client"
                        )
                        expected_behavior = (
                            "Frontend data flows must import and call the generated API "
                            "client from packages/api-client"
                        )
                        title = f"Generated-client wiring gap: {_wv2.check}"
                    elif _wv2.check in {"CONTRACT-FIELD-001", "CONTRACT-FIELD-002"}:
                        acceptance = (
                            "Frontend shadow interfaces must stay aligned with generated client types"
                        )
                        expected_behavior = (
                            "Local frontend types must match packages/api-client/types.ts "
                            "field names and casing"
                        )
                        title = f"Generated-client field mismatch: {_wv2.check}"
                    else:
                        acceptance = (
                            "Frontend request body fields must use camelCase matching backend DTOs"
                        )
                        expected_behavior = (
                            "Frontend request body field names must use camelCase matching "
                            "the backend DTO"
                        )
                        title = f"Wiring mismatch: {_wv2.check}"
                    _gate_findings.append(Finding(
                        id=f"GATE-{_wv2.check}",
                        feature="WIRING",
                        acceptance_criterion=acceptance,
                        severity=Severity.CRITICAL,
                        category=FindingCategory.CODE_FIX,
                        title=title,
                        description=_wv2.message,
                        prd_reference="contract-first protocol",
                        current_behavior=_wv2.message,
                        expected_behavior=expected_behavior,
                        file_path=_wv2.file_path,
                        line_number=_wv2.line,
                        estimated_effort="small",
                    ))

            # Gate 3 (Level B): Review integrity → block convergence
            # (handled in evaluate_stop_conditions via review_violations passed below)
            review_violations = verify_review_integrity(cwd)
            if review_violations:
                for _rv in review_violations:
                    _log(f"[REVIEW] {_rv}")
                # If decision was STOP, override to CONTINUE
                if decision.action == "STOP":
                    _log("[GATE] Review integrity violations block convergence → CONTINUE")
                    decision = LoopDecision(
                        action="CONTINUE",
                        reason=f"Review integrity violations: {len(review_violations)} self-checked requirements",
                        findings_for_fix=decision.findings_for_fix or [
                            f for f in report.findings
                            if f.severity.value in ("critical", "high")
                        ],
                        run_number=state.current_run,
                    )

            # Gate 4 (Level C): Agent deployment → degrade score
            deploy_violations = check_agent_deployment(cwd, depth=_depth)
            if deploy_violations:
                for _av in deploy_violations:
                    _log(f"[DEPLOY] {_av}")
                # Score penalty is applied in evaluate_stop_conditions scoring section

            # Gate 5 (Level B): Truth scorer gate → block convergence
            if (
                decision.action == "STOP"
                and hasattr(state, "last_truth_gate")
                and state.last_truth_gate in ("retry", "escalate")
            ):
                _log(
                    f"[GATE] Truth score gate={state.last_truth_gate} blocks convergence → CONTINUE"
                )
                decision = LoopDecision(
                    action="CONTINUE",
                    reason=f"Truth score gate: {state.last_truth_gate} (score: {state.last_truth_score:.3f})",
                    findings_for_fix=decision.findings_for_fix or [
                        f for f in report.findings
                        if f.severity.value in ("critical", "high")
                    ],
                    run_number=state.current_run,
                )

            # Mission 3 enforcement functions → feed fix cycle (Level A)
            # Hardening P2: Contract existence
            ce_violations = verify_contracts_exist(cwd)
            if ce_violations:
                for _cev in ce_violations:
                    _log(f"[CONTRACT-EXIST] {_cev}")
                _gate_findings.extend(
                    _enforcement_violation_to_finding(v, "CONTRACT") for v in ce_violations
                )

            # Hardening P3: Pagination wrapper mismatch
            pw_violations = detect_pagination_wrapper_mismatch(cwd)
            if pw_violations:
                for _pwv in pw_violations:
                    _log(f"[WRAPPER] {_pwv}")
                _gate_findings.extend(
                    _enforcement_violation_to_finding(v, "PAGINATION") for v in pw_violations
                )

            # Hardening P4: Requirement granularity
            rg_violations = verify_requirement_granularity(cwd)
            if rg_violations:
                for _rgv in rg_violations:
                    _log(f"[ATOMIC] {_rgv}")
                _gate_findings.extend(
                    _enforcement_violation_to_finding(v, "GRANULARITY") for v in rg_violations
                )

            # Hardening P5: Test co-location quality
            tc_violations = check_test_colocation_quality(cwd)
            if tc_violations:
                _log(f"[TEST-QUALITY] {len(tc_violations)} test quality violation(s) → fix cycle")
                for _tcv in tc_violations[:5]:
                    _log(f"  {_tcv}")
                _gate_findings.extend(
                    _depth_violation_to_finding(v) for v in tc_violations
                )

            # Gate 6 (Level A): Infrastructure deliverables → feed fix cycle
            infra_violations = _check_infrastructure_deliverables(cwd)
            if infra_violations:
                _log(f"[INFRA] {len(infra_violations)} infrastructure deliverable(s) missing → fix cycle")
                for _iv in infra_violations:
                    _log(f"  {_iv}")
                _gate_findings.extend(
                    _infra_violation_to_finding(v) for v in infra_violations
                )
        except Exception as e:
            _log(f"Post-audit quality gate checks FAILED: {e}")
            _log(traceback.format_exc())
            # Re-raise — a broken gate check should not silently pass
            raise

        # Inject gate findings into fix cycle (capped at 20 total)
        if _gate_findings and decision.action == "CONTINUE":
            available_slots = max(0, 20 - len(decision.findings_for_fix))
            sorted_gate = sorted(
                _gate_findings,
                key=lambda f: {"critical": 0, "high": 1, "medium": 2}.get(
                    f.severity.value if hasattr(f.severity, "value") else str(f.severity), 3
                ),
            )
            decision.findings_for_fix.extend(sorted_gate[:available_slots])
            _log(
                f"[GATE] Injecting {min(len(sorted_gate), available_slots)}/{len(_gate_findings)} "
                f"gate findings into fix cycle (cap: 20 total)"
            )

        if decision.action == "STOP":
            _log("=" * 60)
            _log(f"STOPPING: {decision.reason}")
            _log("=" * 60)
            state.status = "converged" if "CONVERG" in decision.reason or "COMPLETE" in decision.reason else "stopped"
            state.stop_reason = decision.reason
            state.save(agent_team_dir)

            # --- Browser Test Phase (v17) ---
            browser_report = _run_browser_test_phase(
                prd_path, cwd, config, state, report,
            )

            _generate_final_report(state, report, agent_team_dir)
            result = _build_result(state, report, decision.reason)
            if browser_report is not None:
                result.browser_test_passed = browser_report.all_passed
                result.browser_test_report = browser_report
            return result

        # --- Generate Fix PRD ---
        _log("=" * 60)
        _log(f"GENERATING FIX PRD (Run {state.current_run + 1})")
        _log("=" * 60)

        try:
            fix_prd_text = generate_fix_prd(
                original_prd_path=prd_path,
                codebase_path=cwd,
                findings=decision.findings_for_fix,
                run_number=state.current_run + 1,
                previously_passing_acs=report.previously_passing,
            )
        except Exception as e:
            state.status = "failed"
            state.stop_reason = f"PRD_GENERATION_FAILURE: {e}"
            state.save(agent_team_dir)
            return _build_result(state, report, str(e))

        # Fix PRD structural validation
        valid, validation_msg = _validate_fix_prd_structure(fix_prd_text)
        if not valid:
            _log(f"WARNING: Fix PRD validation failed: {validation_msg}")
        else:
            _log(f"Fix PRD validated: {validation_msg}")

        # Fix PRD size guard — prevent LLM context window overflow
        MAX_FIX_PRD_CHARS = 50_000
        if len(fix_prd_text) > MAX_FIX_PRD_CHARS:
            _log(f"Fix PRD too large ({len(fix_prd_text)} chars > {MAX_FIX_PRD_CHARS}). Truncating.")
            fix_prd_text = fix_prd_text[:MAX_FIX_PRD_CHARS]
            last_section = fix_prd_text.rfind("\n### ")
            if last_section > MAX_FIX_PRD_CHARS // 2:
                fix_prd_text = fix_prd_text[:last_section]

        # Inject fix recipes into fix PRD (Feature #4.1)
        try:
            recipe_text = _load_recipes_for_findings(
                decision.findings_for_fix, cwd, agent_team_dir,
            )
            if recipe_text:
                fix_prd_text += "\n\n" + recipe_text
                _log("[RECIPE] Injected fix recipes into fix PRD")
        except Exception as e:
            _log(f"[RECIPE] Recipe injection skipped: {e}")

        # Save fix PRD
        fix_prd_path = agent_team_dir / f"fix_prd_run{state.current_run + 1}.md"
        fix_prd_path.write_text(fix_prd_text, encoding="utf-8")
        _log(f"Fix PRD saved: {fix_prd_path} ({len(fix_prd_text)} chars, {len(decision.findings_for_fix)} findings)")

        # --- Run Builder on Fix PRD ---
        _log("=" * 60)
        _log(f"RUN {state.current_run + 1}: FIX BUILD")
        _log("=" * 60)

        # Snapshot files for failing findings before fix build (Feature #4.1)
        try:
            pending_snapshots = _snapshot_failing_findings(report, cwd)
            if pending_snapshots:
                _log(f"[RECIPE] Snapshotted files for {len(pending_snapshots)} failing finding(s)")
        except Exception as e:
            pending_snapshots = {}
            _log(f"[RECIPE] Snapshot skipped: {e}")

        # Archive current STATE.json
        _archive_state(agent_team_dir, state.current_run)

        # Git snapshot before fix run
        _git_snapshot(cwd, state.current_run + 1)

        # Snapshot file checksums before fix build for unintended change detection
        checksums_before: dict[str, str] = {}
        try:
            checksums_before = _snapshot_file_checksums(cwd, fix_prd_text)
        except Exception as e:
            _log(f"[PROTECT] File checksum snapshot skipped: {e}")

        fix_start_time = time.time()

        # Phase F: budget advisory — emit a note when crossed but always
        # continue. Fix build proceeds; convergence/plateau/max_iterations
        # drive loop termination instead.
        if state.total_cost >= state.max_budget:
            _log(
                f"BUDGET ADVISORY: cumulative ${state.total_cost:.2f} has "
                f"crossed configured max_budget ${state.max_budget:.2f}. "
                f"Continuing fix build (no cap enforced)."
            )

        try:
            fix_cost = execute_unified_fix(
                findings=decision.findings_for_fix,
                original_prd_path=prd_path,
                cwd=cwd,
                config=config,
                run_number=state.current_run + 1,
                previously_passing_acs=report.previously_passing,
                fix_prd_text=fix_prd_text,
                fix_prd_path=fix_prd_path,
                run_full_build=_run_builder,
                log=_log,
            )
        except (BuilderRunError, RuntimeError) as e:
            _log(f"Fix build failed: {e}")
            state.status = "failed"
            state.stop_reason = f"BUILDER_FAILURE: {e}"
            state.save(agent_team_dir)
            return _build_result(state, report, str(e))

        # Detect stale STATE.json (fix build may have failed silently)
        state_json_path = cwd / ".agent-team" / "STATE.json"
        if state_json_path.exists():
            state_mtime = state_json_path.stat().st_mtime
            if state_mtime < fix_start_time:
                _log("WARNING: STATE.json is stale (predates fix build start). Fix build may have failed silently.")

        # Check for unintended file changes outside fix scope
        if checksums_before:
            try:
                violations = _check_unintended_changes(cwd, checksums_before)
                if violations:
                    _log(f"[PROTECT] {len(violations)} unintended file change(s) detected:")
                    for v in violations[:10]:
                        _log(f"  {v}")
            except Exception as e:
                _log(f"[PROTECT] Unintended change check failed: {e}")

        # Record the fix run (will be audited on next loop iteration)
        state.add_run(report, fix_cost, run_type="fix", prd_path=str(fix_prd_path))
        state.save(agent_team_dir)

        _log(f"Fix build complete. Cost: ${fix_cost:.2f}, Total: ${state.total_cost:.2f}")

        try:
            from .fix_executor import run_regression_check

            regressed_acs = run_regression_check(
                cwd=str(cwd),
                previously_passing_acs=report.previously_passing,
                config=config,
            )
            if regressed_acs:
                _log(
                    "[REGRESSION] Post-fix verification detected PASS -> FAIL regressions: "
                    + ", ".join(regressed_acs)
                )
                state.status = "failed"
                state.stop_reason = f"REGRESSION_AFTER_FIX: {', '.join(regressed_acs)}"
                state.save(agent_team_dir)
                return _build_result(state, report, state.stop_reason)
        except Exception as e:
            _log(f"[REGRESSION] Post-fix verification skipped: {e}")

        # Run migration generation after fix build
        try:
            migration_issues = _run_migration_generation(cwd)
            if migration_issues:
                _log(f"[MIGRATION] {len(migration_issues)} blocking migration issue(s) after fix build:")
                for _mi in migration_issues:
                    _log(f"  {_mi}")
        except Exception as e:
            _log(f"[MIGRATION] Migration generation skipped: {e}")

        last_report = report


# ---------------------------------------------------------------------------
# Standalone audit command
# ---------------------------------------------------------------------------


def run_standalone_audit(
    prd_path: Path,
    cwd: Path,
    output_path: Optional[Path] = None,
    config: Optional[dict[str, Any]] = None,
) -> AuditReport:
    """Run a standalone audit without the full coordinated loop."""
    config = config or {}
    report = run_full_audit(
        original_prd_path=prd_path,
        codebase_path=cwd,
        run_number=int(config.get("run_number", 1) or 1),
        previous_report=config.get("previous_report"),
        config={
            "audit_model": config.get("audit_model", "claude-opus-4-6"),
            "evidence_mode": config.get("evidence_mode", "disabled"),
        },
    )

    if output_path:
        output_path.write_text(report.to_json(), encoding="utf-8")
        _log(f"Audit report saved: {output_path}")

    return report


# ---------------------------------------------------------------------------
# Standalone fix PRD generation
# ---------------------------------------------------------------------------


def generate_standalone_fix_prd(
    prd_path: Path,
    cwd: Path,
    audit_report_path: Path,
    output_path: Optional[Path] = None,
) -> str:
    """Generate a fix PRD from an existing audit report."""
    report = AuditReport.from_dict(
        json.loads(audit_report_path.read_text(encoding="utf-8"))
    )

    # Use actionable findings
    actionable = [
        f for f in report.findings
        if f.severity.value in ("critical", "high", "medium")
    ]

    fix_prd = generate_fix_prd(
        original_prd_path=prd_path,
        codebase_path=cwd,
        findings=actionable,
        run_number=report.run_number + 1,
        previously_passing_acs=report.previously_passing,
    )

    if output_path:
        output_path.write_text(fix_prd, encoding="utf-8")
        _log(f"Fix PRD saved: {output_path}")

    return fix_prd


# ---------------------------------------------------------------------------
# Audit invocation (subprocess — mirrors _run_builder to avoid nested CLI)
# ---------------------------------------------------------------------------


def _run_audit(
    prd_path: Path,
    cwd: Path,
    config: dict[str, Any],
    run_number: int = 1,
    previous_report: Optional["AuditReport"] = None,
) -> "AuditReport":
    """Run the audit as a subprocess so claude_agent_sdk CLI calls are not nested.

    Mirrors _run_builder(): spawns a fresh python process so the CLI backend
    works correctly even when called from inside an existing Claude Code session.
    """
    from agent_team_v15.audit_agent import AuditReport

    if config.get("audit_subprocess", True) is False:
        return run_full_audit(
            original_prd_path=prd_path,
            codebase_path=cwd,
            run_number=run_number,
            previous_report=previous_report,
            config={
                "audit_model": config.get("audit_model", "claude-opus-4-6"),
                "evidence_mode": config.get("evidence_mode", "disabled"),
            },
        )

    agent_team_dir = cwd / ".agent-team"
    output_path = agent_team_dir / f"audit_run{run_number}_result.json"

    # Save previous report to a temp file if provided
    prev_report_arg: list[str] = []
    if previous_report is not None:
        prev_path = agent_team_dir / f"audit_run{run_number}_prev.json"
        prev_path.write_text(previous_report.to_json(), encoding="utf-8")
        prev_report_arg = ["--previous-report", str(prev_path)]

    cmd = [
        sys.executable, "-m", "agent_team_v15._audit_worker",
        "--prd", str(prd_path),
        "--cwd", str(cwd),
        "--output", str(output_path),
        "--run-number", str(run_number),
        "--model", config.get("audit_model", "claude-opus-4-6"),
        "--evidence-mode", config.get("evidence_mode", "disabled"),
        *prev_report_arg,
    ]

    _log(f"Running audit subprocess (run {run_number}): {Path(sys.executable).name} -m agent_team_v15._audit_worker")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd),
            timeout=7200,  # 2-hour audit timeout
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Audit subprocess timed out after 2 hours")
    except FileNotFoundError:
        raise RuntimeError(f"Python executable not found: {sys.executable}")

    # Stream worker output to coordinated build log
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            _log(f"[AUDIT] {line}")

    if result.returncode != 0:
        stderr = (result.stderr or "")[-1000:]
        # Check if output file was produced despite non-zero exit
        # (CLI transport errors can cause non-zero exit even on success)
        if not output_path.exists():
            raise RuntimeError(
                f"Audit subprocess failed (exit {result.returncode}): {stderr}"
            )
        _log(f"[AUDIT] Subprocess exited {result.returncode} but output exists — treating as success")

    if not output_path.exists():
        raise RuntimeError(
            f"Audit subprocess completed but output file missing: {output_path}"
        )

    return AuditReport.from_dict(json.loads(output_path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Builder invocation
# ---------------------------------------------------------------------------


def _run_builder(
    prd_path: Path,
    cwd: Path,
    config: dict[str, Any],
) -> float:
    """Run the builder pipeline as a subprocess. Returns cost."""
    cmd = [
        sys.executable, "-m", "agent_team_v15",
        "--prd", str(prd_path),
        "--cwd", str(cwd),
        "--depth", config.get("depth", "exhaustive"),
        "--no-interview",
    ]

    max_cost = config.get("max_cost_per_run")
    if max_cost:
        cmd.extend(["--max-cost", str(max_cost)])

    _log(f"Running builder: {' '.join(cmd[-6:])}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd),
            timeout=config.get("builder_timeout", 14400),  # 4 hour default
        )

        if result.returncode != 0:
            stderr = result.stderr[-500:] if result.stderr else "No stderr"
            # Tolerate non-zero exit when builder actually produced output
            # (CLI backend transport errors cause non-zero exit even on success)
            state_file = cwd / ".agent-team" / "STATE.json"
            if state_file.is_file():
                _log(f"Builder exited with code {result.returncode} but STATE.json exists — treating as success")
            else:
                raise BuilderRunError(
                    f"Builder exited with code {result.returncode}: {stderr}"
                )

    except subprocess.TimeoutExpired:
        raise BuilderRunError("Builder timed out")
    except FileNotFoundError:
        raise BuilderRunError(f"Python executable not found: {sys.executable}")

    # Read cost from STATE.json
    from agent_team_v15.state import load_state

    state = load_state(str(cwd / ".agent-team"))
    return state.total_cost if state else 0.0


# ---------------------------------------------------------------------------
# Migration generation
# ---------------------------------------------------------------------------


def _run_migration_generation(cwd: Path) -> list[str]:
    """Run ORM migration generation if TypeORM or Prisma is detected.

    Returns a list of blocking issue strings (empty = success or skipped).
    """
    issues: list[str] = []

    # Detect ORM type
    typeorm_datasource_paths = [
        cwd / "src" / "database" / "data-source.ts",
        cwd / "apps" / "api" / "src" / "database" / "data-source.ts",
        cwd / "src" / "data-source.ts",
        cwd / "ormconfig.ts",
    ]
    prisma_schema_paths = [
        cwd / "prisma" / "schema.prisma",
        cwd / "apps" / "api" / "prisma" / "schema.prisma",
    ]

    is_typeorm = any(p.is_file() for p in typeorm_datasource_paths)
    is_prisma = any(p.is_file() for p in prisma_schema_paths)

    if not is_typeorm and not is_prisma:
        _log("[MIGRATION] No TypeORM data-source or Prisma schema detected — skipping migration generation")
        return issues

    if is_typeorm:
        # Find the actual data-source path
        ds_path = next(p for p in typeorm_datasource_paths if p.is_file())
        ds_relative = str(ds_path.relative_to(cwd)).replace("\\", "/")

        # Determine migrations output dir
        migrations_dir = ds_path.parent / "migrations"
        migrations_relative = str(migrations_dir.relative_to(cwd)).replace("\\", "/")

        cmd = [
            "npx", "typeorm", "migration:generate",
            "-d", ds_relative,
            f"{migrations_relative}/AutoGenerated",
        ]
        _log(f"[MIGRATION] Running TypeORM migration generation: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            if result.returncode != 0:
                stderr = result.stderr[-500:] if result.stderr else "No stderr"
                # "No changes in database schema" is not an error — it means migrations are up to date
                if "no changes" in stderr.lower() or "no changes" in (result.stdout or "").lower():
                    _log("[MIGRATION] TypeORM: no pending schema changes (migrations are up to date)")
                else:
                    issues.append(
                        f"MIGRATION-001: TypeORM migration:generate failed (exit {result.returncode}): {stderr}"
                    )
                    _log(f"[MIGRATION] TypeORM migration generation FAILED: {stderr}")
            else:
                _log("[MIGRATION] TypeORM migration generated successfully")
        except subprocess.TimeoutExpired:
            issues.append("MIGRATION-001: TypeORM migration:generate timed out (120s)")
            _log("[MIGRATION] TypeORM migration generation timed out")
        except FileNotFoundError:
            issues.append("MIGRATION-001: npx not found — cannot run TypeORM migration:generate")
            _log("[MIGRATION] npx not found — skipping TypeORM migration generation")

    if is_prisma:
        cmd = ["npx", "prisma", "migrate", "dev", "--name", "init", "--create-only"]
        _log(f"[MIGRATION] Running Prisma migration generation: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            if result.returncode != 0:
                stderr = result.stderr[-500:] if result.stderr else "No stderr"
                # "already in sync" or "nothing to migrate" is not an error
                if "already in sync" in stderr.lower() or "nothing" in stderr.lower():
                    _log("[MIGRATION] Prisma: schema already in sync (no pending migrations)")
                else:
                    issues.append(
                        f"MIGRATION-002: Prisma migrate dev failed (exit {result.returncode}): {stderr}"
                    )
                    _log(f"[MIGRATION] Prisma migration generation FAILED: {stderr}")
            else:
                _log("[MIGRATION] Prisma migration generated successfully")
        except subprocess.TimeoutExpired:
            issues.append("MIGRATION-002: Prisma migrate dev timed out (120s)")
            _log("[MIGRATION] Prisma migration generation timed out")
        except FileNotFoundError:
            issues.append("MIGRATION-002: npx not found — cannot run Prisma migrate dev")
            _log("[MIGRATION] npx not found — skipping Prisma migration generation")

    return issues


# ---------------------------------------------------------------------------
# Git snapshots
# ---------------------------------------------------------------------------


def _git_snapshot(cwd: Path, run_number: int) -> None:
    """Create a git snapshot before a run for regression safety."""
    try:
        # Check if git repo exists
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            # Not a git repo — initialize one
            subprocess.run(
                ["git", "init"],
                cwd=str(cwd),
                capture_output=True,
                timeout=10,
            )

        # Stage and commit
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(cwd),
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            ["git", "commit", "-m", f"pre-fix-run-{run_number} snapshot", "--allow-empty"],
            cwd=str(cwd),
            capture_output=True,
            timeout=30,
        )
        _log(f"Git snapshot: pre-fix-run-{run_number}")
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        _log("Warning: Git snapshot failed (continuing without safety net)")


def _archive_state(agent_team_dir: Path, run_number: int) -> None:
    """Archive the current STATE.json before the next run."""
    state_path = agent_team_dir / "STATE.json"
    if state_path.exists():
        archive_path = agent_team_dir / f"STATE.json.run{run_number}"
        shutil.copy2(state_path, archive_path)
        backup = state_path.with_suffix(".json.bak")
        shutil.copy2(archive_path, backup)
        _log(f"Backed up STATE.json to {backup}")
        state_path.unlink()  # Clean for fresh run


# ---------------------------------------------------------------------------
# Fix PRD structural validation
# ---------------------------------------------------------------------------


def _validate_fix_prd_structure(fix_text: str) -> tuple[bool, str]:
    """Validate that a fix PRD has the required structure for the builder."""
    if len(fix_text) < 200:
        return False, "Fix PRD too short"
    if not re.search(r"^# ", fix_text, re.MULTILINE):
        return False, "No H1 heading"

    # Check for parseable features (any of these formats)
    features = re.findall(r"^### (?:F-|FEAT-|FIX-)\S+", fix_text, re.MULTILINE)
    if len(features) == 0:
        return False, "No features found (expected ### F-FIX-NNN:, ### FEAT-NNN:, or ### FIX-NNN: headings)"

    # Check for acceptance criteria or success criteria
    acs = re.findall(r"^- AC-|^\d+\.\s+\*\*(?:DET-|F\d|FIX-|FEAT-)", fix_text, re.MULTILINE)
    if len(acs) == 0:
        return False, "No acceptance/success criteria found"

    # Size check
    if len(fix_text) > 50_000:
        return False, f"Fix PRD too large ({len(fix_text)} chars, max 50,000)"

    return True, f"Valid: {len(features)} features, {len(acs)} criteria"


# ---------------------------------------------------------------------------
# Working file protection
# ---------------------------------------------------------------------------


def _snapshot_file_checksums(cwd: Path, fix_prd_text: str) -> dict[str, str]:
    """Snapshot checksums of files NOT in the fix scope."""
    fix_files: set[str] = set()
    for match in re.finditer(r"#### Files to (?:Modify|Create)\n((?:- .+\n)+)", fix_prd_text):
        for line in match.group(1).strip().split("\n"):
            fix_files.add(line.strip("- ").strip().split(" (")[0])

    checksums: dict[str, str] = {}
    # Safe walker — node_modules / .pnpm pruned at descent
    # (project_walker.py post smoke #9/#10).
    from .project_walker import iter_project_files
    for src_file in iter_project_files(cwd, patterns=("*.ts", "*.tsx")):
        rel = str(src_file.relative_to(cwd)).replace("\\", "/")
        if rel not in fix_files:
            try:
                checksums[rel] = hashlib.md5(src_file.read_bytes()).hexdigest()
            except OSError:
                pass
    return checksums


def _check_unintended_changes(cwd: Path, checksums_before: dict[str, str]) -> list[str]:
    """Check for files modified outside the fix scope."""
    violations = []
    for rel, old_hash in checksums_before.items():
        f = cwd / rel
        if f.exists():
            try:
                new_hash = hashlib.md5(f.read_bytes()).hexdigest()
            except OSError:
                continue
            if new_hash != old_hash:
                violations.append(f"UNINTENDED CHANGE: {rel} was modified but not in fix scope")
    return violations


# ---------------------------------------------------------------------------
# Final report generation
# ---------------------------------------------------------------------------


def _generate_final_report(
    state: LoopState,
    final_report: AuditReport,
    agent_team_dir: Path,
) -> None:
    """Generate FINAL_REPORT.md summarizing all runs."""
    lines = [
        "# Coordinated Builder — Final Report",
        "",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Original PRD:** {state.original_prd_path}",
        f"**Total Runs:** {state.current_run}",
        f"**Total Cost:** ${state.total_cost:.2f}",
        f"**Stop Reason:** {state.stop_reason}",
        f"**Final Status:** {state.status}",
        "",
        "## Score Progression",
        "",
        "| Run | Type | Score | ACs Passed | CRIT | HIGH | Regressions | Cost |",
        "|-----|------|-------|-----------|------|------|-------------|------|",
    ]

    for r in state.runs:
        lines.append(
            f"| {r.run_number} | {r.run_type} | {r.score:.1f}% | "
            f"{r.passed_acs}/{r.total_acs} | {r.critical_count} | "
            f"{r.high_count} | {r.regression_count} | ${r.cost:.2f} |"
        )

    lines.extend([
        "",
        "## Remaining Findings",
        "",
    ])

    if final_report.findings:
        for f in final_report.findings:
            lines.append(f"- [{f.severity.value.upper()}] {f.id}: {f.title}")
    else:
        lines.append("No remaining findings.")

    # Truth scoring section (Feature #2)
    if state.last_truth_score > 0:
        lines.extend([
            "",
            "## Truth Score",
            "",
            f"**Overall:** {state.last_truth_score:.3f} (gate: {state.last_truth_gate})",
            "",
        ])
        if state.truth_dimensions:
            lines.append("| Dimension | Score |")
            lines.append("|-----------|-------|")
            for dim, score in sorted(state.truth_dimensions.items()):
                lines.append(f"| {dim} | {score:.3f} |")
            lines.append("")

    if state.regression_count > 0:
        lines.extend([
            "",
            "## Regressions",
            "",
            f"**Total regressions detected:** {state.regression_count}",
            "",
        ])

    lines.extend([
        "",
        "## Deferred Items (REQUIRES_HUMAN)",
        "",
    ])

    human_items = [
        f for f in final_report.findings
        if f.severity == Severity.REQUIRES_HUMAN
    ]
    if human_items:
        for f in human_items:
            lines.append(f"- {f.id}: {f.title}")
    else:
        lines.append("No items requiring human review.")

    report_path = agent_team_dir / "FINAL_REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    _log(f"Final report: {report_path}")


def _run_browser_test_phase(
    prd_path: Path,
    cwd: Path,
    config: dict[str, Any],
    state: LoopState,
    last_report: Optional[AuditReport],
) -> Optional[Any]:
    """Run the browser test phase after audit-fix convergence (v17).

    Starts the application, extracts workflows from PRD, executes them
    via Playwright MCP, and returns a BrowserTestReport. Failures trigger
    up to max_iterations fix-build-retest cycles.

    Returns BrowserTestReport or None if browser tests are disabled/failed to start.
    """
    browser_config = config.get("browser_tests", {})
    if not browser_config.get("enabled", True):
        _log("Browser tests disabled, skipping")
        return None

    # Lazy import to avoid circular deps and startup cost
    try:
        from agent_team_v15.browser_test_agent import (
            BrowserTestEngine,
            extract_workflows_from_prd,
            generate_browser_test_report,
        )
        from agent_team_v15.app_lifecycle import AppLifecycleManager, AuthSetup
    except ImportError as e:
        _log(f"Browser test imports failed: {e}")
        return None

    max_iterations = browser_config.get("max_iterations", 2)
    port = browser_config.get("port", 3080)
    operator_model = browser_config.get("operator_model", "claude-opus-4-6")
    agent_team_dir = cwd / ".agent-team"

    _log("=" * 60)
    _log("BROWSER TEST PHASE")
    _log("=" * 60)

    # Extract workflows from PRD (one-time)
    try:
        suite = extract_workflows_from_prd(
            prd_path,
            codebase_path=cwd,
            config={"extraction_model": operator_model},
        )
    except Exception as e:
        _log(f"Workflow extraction failed: {e}")
        return None

    if not suite.workflows:
        _log("No workflows extracted from PRD, skipping browser tests")
        return None

    _log(
        f"Extracted {len(suite.workflows)} workflows "
        f"({len(suite.critical_workflows)} critical)"
    )

    # Start the application
    lifecycle = AppLifecycleManager(cwd, port=port)
    browser_report = None

    try:
        app = lifecycle.start()
        _log(f"Application started at http://localhost:{app.port}")

        # Setup test authentication
        auth_setup = AuthSetup(cwd)
        credentials = auth_setup.get_seed_credentials()
        auth_token = ""
        if credentials:
            _log(f"Found seed credentials for roles: {list(credentials.keys())}")
        else:
            # Try direct session creation
            test_user = auth_setup.create_test_session()
            if test_user and test_user.token:
                auth_token = test_user.token
                _log(f"Created test session for {test_user.email}")

        # Browser test loop
        failed_workflow_ids: Optional[list[str]] = None

        for iteration in range(max_iterations + 1):
            _log(f"--- Browser Test Iteration {iteration + 1} ---")

            screenshot_dir = agent_team_dir / f"screenshots/iteration_{iteration + 1}"
            engine = BrowserTestEngine(
                app_url=f"http://localhost:{app.port}",
                screenshot_dir=screenshot_dir,
                auth_token=auth_token,
                operator_model=operator_model,
            )

            browser_report = engine.run_all(suite, only_failed_ids=failed_workflow_ids)

            # Generate report
            report_path = generate_browser_test_report(browser_report, agent_team_dir)
            _log(
                f"Browser test report: {report_path}\n"
                f"  Results: {browser_report.workflows_passed}/{browser_report.workflows_tested} "
                f"workflows, {browser_report.total_passed}/{browser_report.total_steps} steps "
                f"({browser_report.pass_rate:.1f}%)"
            )

            # All passed?
            if browser_report.all_passed:
                _log("ALL BROWSER TESTS PASS")
                break

            # Exhausted iterations?
            if iteration >= max_iterations:
                _log(f"MAX BROWSER FIX ITERATIONS ({max_iterations}) REACHED")
                break

            # Generate fix PRD from browser failures
            browser_findings = browser_report.to_findings()
            _log(f"Browser failures: {len(browser_findings)} findings, generating fix PRD...")

            # Stop app before running builder
            lifecycle.stop()

            # Generate and run fix PRD
            try:
                fix_prd_text = generate_fix_prd(
                    original_prd_path=prd_path,
                    codebase_path=cwd,
                    findings=browser_findings,
                    run_number=state.current_run + 1,
                    previously_passing_acs=(
                        last_report.previously_passing if last_report else None
                    ),
                )
            except Exception as e:
                _log(f"Browser fix PRD generation failed: {e}")
                break

            fix_prd_path = agent_team_dir / f"browser_fix_prd_iteration_{iteration + 1}.md"
            fix_prd_path.write_text(fix_prd_text, encoding="utf-8")
            _log(f"Browser fix PRD: {fix_prd_path}")

            try:
                fix_cost = execute_unified_fix(
                    findings=browser_findings,
                    original_prd_path=prd_path,
                    cwd=cwd,
                    config=config,
                    run_number=state.current_run + 1,
                    previously_passing_acs=(
                        last_report.previously_passing if last_report else None
                    ),
                    fix_prd_text=fix_prd_text,
                    fix_prd_path=fix_prd_path,
                    run_full_build=_run_builder,
                    log=_log,
                )
                _log(f"Browser fix build complete. Cost: ${fix_cost:.2f}")
                try:
                    from .fix_executor import run_regression_check

                    regressed_acs = run_regression_check(
                        cwd=str(cwd),
                        previously_passing_acs=(last_report.previously_passing if last_report else []),
                        config=config,
                    )
                    if regressed_acs:
                        _log(
                            "[REGRESSION] Browser fix verification detected PASS -> FAIL regressions: "
                            + ", ".join(regressed_acs)
                        )
                        break
                except Exception as exc:
                    _log(f"[REGRESSION] Browser fix verification skipped: {exc}")
            except (BuilderRunError, RuntimeError) as e:
                _log(f"Browser fix build failed: {e}")
                break

            # Track failed workflows for targeted re-test
            failed_workflow_ids = [
                wr.workflow.id
                for wr in browser_report.results
                if wr.status != "pass"
            ]

            # Restart app for re-testing
            app = lifecycle.start()

    except Exception as e:
        _log(f"Browser test phase error: {e}")
    finally:
        lifecycle.stop()

    return browser_report


def _build_result(
    state: LoopState,
    report: Optional[AuditReport],
    reason: str,
) -> CoordinatedBuildResult:
    """Build the final result object."""
    if report:
        remaining = [
            f for f in report.findings
            if f.severity != Severity.ACCEPTABLE_DEVIATION
        ]
        return CoordinatedBuildResult(
            total_runs=state.current_run,
            total_cost=state.total_cost,
            final_score=report.score,
            final_acs_passed=report.passed_acs,
            final_acs_total=report.total_acs,
            remaining_findings=remaining,
            stop_reason=reason,
            success="CONVERG" in reason or "COMPLETE" in reason,
            regressions_detected=report.regressions,
        )
    return CoordinatedBuildResult(
        total_runs=state.current_run,
        total_cost=state.total_cost,
        final_score=0,
        final_acs_passed=0,
        final_acs_total=0,
        stop_reason=reason,
        error=reason,
    )


# ---------------------------------------------------------------------------
# Regression detection + rollback advisory (Feature #2)
# ---------------------------------------------------------------------------


def _check_regressions(
    current_report: AuditReport,
    previous_report: Optional[AuditReport],
) -> list[str]:
    """Compare current vs previous audit to detect AC regressions.

    Returns list of AC IDs that previously passed but now fail or are partial.
    This is a LOCAL helper that supplements the audit agent's own regression
    detection (which compares within the audit itself).
    """
    if previous_report is None:
        return []

    prev_passing = set(previous_report.previously_passing)
    if not prev_passing:
        # Fallback: compute from the report's pass count
        # The audit agent stores previously_passing as AC IDs
        return []

    current_passing = set(current_report.previously_passing)
    # Regressions = ACs that were in prev_passing but NOT in current_passing
    regressions = sorted(prev_passing - current_passing)
    return regressions


def _suggest_rollback(
    cwd: Path,
    regression_acs: list[str],
    run_number: int,
) -> str:
    """Query git for changed files and suggest rollback when regressions detected.

    Does NOT auto-execute rollback (too destructive). Returns a message
    string that is logged and included in the fix PRD so the next cycle
    can explicitly address it.
    """
    suggestion_lines = [
        f"[REGRESSION] ADVISORY (Run {run_number}):",
        f"[REGRESSION]   {len(regression_acs)} acceptance criteria regressed.",
    ]

    # Query git for changed files since last snapshot
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            changed = result.stdout.strip().splitlines()
            suggestion_lines.append(f"  Changed files since last snapshot: {len(changed)}")
            for f in changed[:10]:
                suggestion_lines.append(f"    - {f}")
            if len(changed) > 10:
                suggestion_lines.append(f"    ... and {len(changed) - 10} more")
            suggestion_lines.append(
                "  SUGGESTION: Review these files for unintended changes. "
                "Consider `git diff HEAD~1` to inspect."
            )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        suggestion_lines.append("  (Git not available — cannot determine changed files)")

    suggestion_lines.append(
        "  The next fix PRD will include REGRESSION markers for these ACs."
    )
    return "\n".join(suggestion_lines)
