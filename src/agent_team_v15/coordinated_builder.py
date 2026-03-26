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

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent_team_v15.audit_agent import AuditReport, Finding, Severity, run_audit
from agent_team_v15.config_agent import (
    LoopDecision,
    LoopState,
    evaluate_stop_conditions,
)
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


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CoordinatedBuildError(Exception):
    """Base error for coordinated builder."""


class BuilderRunError(CoordinatedBuildError):
    """Builder subprocess failed."""


class AuditError(CoordinatedBuildError):
    """Audit agent failed."""


class PRDGenerationError(CoordinatedBuildError):
    """Fix PRD generation failed."""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    """Print a timestamped log message."""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


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
    if state and state.status in ("running", "converged", "stopped"):
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

        # Git snapshot
        _git_snapshot(cwd, 1)
    elif config.get("skip_initial_build", False) and state.current_run == 0:
        initial_cost = config.get("initial_cost", 0.0)
        _log(f"Skipping initial build (cost override: ${initial_cost:.2f})")
    else:
        initial_cost = 0.0

    # --- Audit-Fix Loop ---
    last_report: Optional[AuditReport] = None

    while True:
        run_num = state.current_run + 1

        _log("=" * 60)
        _log(f"AUDIT (after Run {run_num - 1 if run_num > 1 else 1})")
        _log("=" * 60)

        # Run audit
        try:
            previous_report = last_report
            report = run_audit(
                original_prd_path=prd_path,
                codebase_path=cwd,
                previous_report=previous_report,
                run_number=run_num,
                config={"audit_model": state.audit_model},
            )
        except Exception as e:
            _log(f"Audit failed: {e}")
            # Retry once
            try:
                report = run_audit(
                    original_prd_path=prd_path,
                    codebase_path=cwd,
                    run_number=run_num,
                    config={"audit_model": state.audit_model},
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

        if decision.circuit_breaker_level == 1:
            _log(f"WARNING: {decision.reason}")

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

        # Save fix PRD
        fix_prd_path = agent_team_dir / f"fix_prd_run{state.current_run + 1}.md"
        fix_prd_path.write_text(fix_prd_text, encoding="utf-8")
        _log(f"Fix PRD saved: {fix_prd_path} ({len(fix_prd_text)} chars, {len(decision.findings_for_fix)} findings)")

        # --- Run Builder on Fix PRD ---
        _log("=" * 60)
        _log(f"RUN {state.current_run + 1}: FIX BUILD")
        _log("=" * 60)

        # Archive current STATE.json
        _archive_state(agent_team_dir, state.current_run)

        # Git snapshot before fix run
        _git_snapshot(cwd, state.current_run + 1)

        try:
            fix_cost = _run_builder(fix_prd_path, cwd, config)
        except BuilderRunError as e:
            _log(f"Fix build failed: {e}")
            state.status = "failed"
            state.stop_reason = f"BUILDER_FAILURE: {e}"
            state.save(agent_team_dir)
            return _build_result(state, report, str(e))

        # Record the fix run (will be audited on next loop iteration)
        state.add_run(report, fix_cost, run_type="fix", prd_path=str(fix_prd_path))
        state.save(agent_team_dir)

        _log(f"Fix build complete. Cost: ${fix_cost:.2f}, Total: ${state.total_cost:.2f}")

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
    report = run_audit(
        original_prd_path=prd_path,
        codebase_path=cwd,
        config={"audit_model": config.get("audit_model", "claude-opus-4-6")},
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
            timeout=config.get("builder_timeout", 7200),  # 2 hour default
        )

        if result.returncode != 0:
            stderr = result.stderr[-500:] if result.stderr else "No stderr"
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
        state_path.unlink()  # Clean for fresh run


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
                fix_cost = _run_builder(fix_prd_path, cwd, config)
                _log(f"Browser fix build complete. Cost: ${fix_cost:.2f}")
            except BuilderRunError as e:
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
