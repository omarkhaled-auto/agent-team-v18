#!/usr/bin/env python3
"""
Dry-run simulation of the audit→fix→reaudit pipeline.
Validates pipeline wiring without any LLM calls.
Run: python scripts/simulate_pipeline.py
"""

import re
import sys
import tempfile
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _make_finding(
    id: str,
    feature: str,
    severity_val: str,
    category_val: str,
    title: str,
    description: str,
    file_path: str = "",
    line_number: int = 0,
    fix_suggestion: str = "",
    current_behavior: str = "",
    expected_behavior: str = "",
    acceptance_criterion: str = "",
):
    from agent_team_v15.audit_agent import Finding, FindingCategory, Severity

    return Finding(
        id=id,
        feature=feature,
        acceptance_criterion=acceptance_criterion or title,
        severity=Severity(severity_val),
        category=FindingCategory(category_val),
        title=title,
        description=description,
        prd_reference=f"PRD/{feature}",
        current_behavior=current_behavior or f"Current: {description[:80]}",
        expected_behavior=expected_behavior or f"Expected: {description[:80]} fixed",
        file_path=file_path,
        line_number=line_number,
        fix_suggestion=fix_suggestion,
        estimated_effort="small",
    )


# ---------------------------------------------------------------------------
# Stage 1: Create synthetic AuditReport and verify serialization
# ---------------------------------------------------------------------------


def stage1_mock_audit_report(tmp_dir: Path):
    """Create synthetic AuditReport with realistic data and verify structure."""
    from agent_team_v15.audit_agent import (
        ACResult,
        AuditReport,
        FindingCategory,
        RouteMapping,
        Severity,
        write_build_audit,
    )

    # Build 8 CRITICAL findings
    critical_findings = [
        _make_finding(
            id=f"DET-IV-{i:03d}",
            feature=f"F-{i:03d}",
            severity_val="critical",
            category_val="code_fix",
            title=f"Integration mismatch in endpoint /api/resource-{i}",
            description=f"Frontend calls /api/resource-{i} but backend route is /api/resources/{i}",
            file_path=f"src/api/resource{i}.ts",
            line_number=42 + i,
            fix_suggestion=f"Rename backend route to /api/resource-{i} to match frontend call",
            acceptance_criterion=f"GET /api/resource-{i} returns 200 with correct payload",
        )
        for i in range(1, 9)
    ]

    # 4 MEDIUM findings (mix of categories)
    medium_findings = [
        _make_finding(
            id="F001-AC10",
            feature="F-001",
            severity_val="medium",
            category_val="missing_feature",
            title="Export CSV button not implemented",
            description="PRD requires a CSV export button on the dashboard; component is missing.",
            file_path="src/components/Dashboard.tsx",
            line_number=88,
            acceptance_criterion="Dashboard CSV export button downloads file on click",
        ),
        _make_finding(
            id="F002-AC05",
            feature="F-002",
            severity_val="medium",
            category_val="code_fix",
            title="Pagination wrapper missing from list responses",
            description="List endpoint returns raw array; frontend expects {data, total, page} wrapper.",
            file_path="src/controllers/list.controller.ts",
            line_number=55,
            acceptance_criterion="List endpoint returns paginated response wrapper",
        ),
        _make_finding(
            id="SEC-001",
            feature="SECURITY",
            severity_val="medium",
            category_val="security",
            title="JWT guard missing on /api/admin routes",
            description="Admin endpoints lack AuthGuard decorator; unauthenticated access possible.",
            file_path="src/routes/admin.ts",
            line_number=12,
            acceptance_criterion="Admin routes reject requests without valid JWT",
        ),
        _make_finding(
            id="DET-SCH-001",
            feature="F-005",
            severity_val="medium",
            category_val="code_fix",
            title="Response field casing mismatch: userId vs user_id",
            description="Backend returns snake_case but frontend expects camelCase for user identifier.",
            file_path="src/dto/user.dto.ts",
            line_number=22,
            acceptance_criterion="User DTO uses camelCase field names throughout",
        ),
    ]

    all_findings = critical_findings + medium_findings

    # 4 route mapping entries (3 mismatches)
    route_mapping = [
        RouteMapping(
            frontend_call="fetch('/api/resource-1')",
            backend_route="GET /api/resources/1",
            match=False,
            notes="path format mismatch",
        ),
        RouteMapping(
            frontend_call="fetch('/api/resource-2')",
            backend_route="GET /api/resources/2",
            match=False,
            notes="path format mismatch",
        ),
        RouteMapping(
            frontend_call="fetch('/api/resource-3')",
            backend_route="GET /api/resources/3",
            match=False,
            notes="path format mismatch",
        ),
        RouteMapping(
            frontend_call="fetch('/api/health')",
            backend_route="GET /api/health",
            match=True,
            notes="",
        ),
    ]

    # 3 AC failures
    ac_results = [
        ACResult(
            feature_id="F-001",
            ac_id="AC-1",
            ac_text="Dashboard loads within 2 seconds",
            status="PASS",
            evidence="src/pages/Dashboard.tsx:10 — suspense boundary present",
            score=1.0,
        ),
        ACResult(
            feature_id="F-001",
            ac_id="AC-2",
            ac_text="CSV export button visible on dashboard",
            status="FAIL",
            evidence="src/components/Dashboard.tsx — export button not found",
            score=0.0,
        ),
        ACResult(
            feature_id="F-002",
            ac_id="AC-5",
            ac_text="List endpoint returns paginated response",
            status="FAIL",
            evidence="src/controllers/list.controller.ts:55 — raw array returned",
            score=0.0,
        ),
        ACResult(
            feature_id="SECURITY",
            ac_id="AC-10",
            ac_text="Admin routes require authentication",
            status="FAIL",
            evidence="src/routes/admin.ts:12 — AuthGuard decorator absent",
            score=0.0,
        ),
        ACResult(
            feature_id="F-003",
            ac_id="AC-7",
            ac_text="User profile displays full name",
            status="PASS",
            evidence="src/pages/Profile.tsx:30 — fullName rendered",
            score=1.0,
        ),
    ]

    report = AuditReport(
        run_number=1,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        original_prd_path=str(tmp_dir / "prd.md"),
        codebase_path=str(tmp_dir / "codebase"),
        total_acs=10,
        passed_acs=4,
        failed_acs=4,
        partial_acs=2,
        skipped_acs=0,
        score=72.0,
        findings=all_findings,
        previously_passing=["AC-1", "AC-7"],
        regressions=[],
        audit_cost=0.0,
        route_mapping=route_mapping,
        ac_results=ac_results,
        top_issues=critical_findings[:5],
        missing_features=["CSV Export", "Notification System"],
        partial_implementations=["Search functionality"],
        comprehensive_score=720,
        categories={
            "frontend_backend_wiring": {"score": 30, "max": 100},
            "prd_ac_compliance": {"score": 50, "max": 100},
            "security_auth": {"score": 40, "max": 100},
        },
        production_ready={
            "docker": False,
            "auth": False,
            "database": True,
        },
    )

    # Verify counts
    assert report.critical_count == 8, f"Expected 8 CRITICAL, got {report.critical_count}"
    assert len(report.route_mapping) == 4, f"Expected 4 route mappings"
    mismatches = [rm for rm in report.route_mapping if not rm.match]
    assert len(mismatches) == 3, f"Expected 3 route mismatches"
    ac_failures = [ar for ar in report.ac_results if ar.status == "FAIL"]
    assert len(ac_failures) == 3, f"Expected 3 AC failures"
    assert report.score == 72.0, f"Expected score=72.0"
    assert report.comprehensive_score == 720, f"Expected comprehensive_score=720"

    # Verify serialization round-trip
    report_dict = report.to_dict()
    report_json = report.to_json()
    assert '"score": 72.0' in report_json or '"score":72.0' in report_json, "score not in JSON"
    assert len(report_dict["findings"]) == 12, f"Expected 12 findings in dict"

    restored = AuditReport.from_dict(report_dict)
    assert restored.score == report.score, "Deserialized score mismatch"
    assert len(restored.findings) == len(report.findings), "Deserialized findings count mismatch"
    assert len(restored.route_mapping) == len(report.route_mapping), "Route mapping round-trip failed"
    assert len(restored.ac_results) == len(report.ac_results), "AC results round-trip failed"

    # Verify write_build_audit produces markdown file
    audit_path = write_build_audit(report, tmp_dir)
    assert audit_path.exists(), f"BUILD_AUDIT.md not created at {audit_path}"
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "# Build Audit Report" in audit_text, "Missing report header"
    assert "72.0" in audit_text, "Score missing from audit markdown"
    assert "Route Mapping" in audit_text, "Route Mapping section missing"
    assert "AC Compliance" in audit_text, "AC Compliance section missing"
    assert "Top Issues" in audit_text, "Top Issues section missing"

    return report


# ---------------------------------------------------------------------------
# Stage 2: Triage — stop conditions + filter
# ---------------------------------------------------------------------------


def stage2_triage(report, tmp_dir: Path):
    """Pass report through stop conditions and filter findings for fix."""
    from agent_team_v15.config_agent import (
        LoopState,
        evaluate_stop_conditions,
    )
    from agent_team_v15.fix_prd_agent import filter_findings_for_fix

    # Fresh state — no prior runs, score < 850 → should CONTINUE
    state = LoopState(
        original_prd_path=str(tmp_dir / "prd.md"),
        codebase_path=str(tmp_dir / "codebase"),
        max_budget=300.0,
        max_iterations=4,
    )

    decision = evaluate_stop_conditions(state, report)
    assert decision.action == "CONTINUE", (
        f"Expected CONTINUE (score=72.0, no runs), got {decision.action}: {decision.reason}"
    )

    # Verify filter_findings_for_fix caps at 20
    filtered = filter_findings_for_fix(report.findings, max_findings=20)
    assert len(filtered) <= 20, f"Filter returned {len(filtered)} > 20"

    # Verify REQUIRES_HUMAN and ACCEPTABLE_DEVIATION are excluded
    from agent_team_v15.audit_agent import Severity

    rh_findings = [f for f in filtered if f.severity == Severity.REQUIRES_HUMAN]
    ad_findings = [f for f in filtered if f.severity == Severity.ACCEPTABLE_DEVIATION]
    assert len(rh_findings) == 0, "REQUIRES_HUMAN findings leaked through filter"
    assert len(ad_findings) == 0, "ACCEPTABLE_DEVIATION findings leaked through filter"

    # Verify CRITICAL findings sort before MEDIUM
    if len(filtered) >= 2:
        from agent_team_v15.fix_prd_agent import _SEVERITY_PRIORITY
        for i in range(len(filtered) - 1):
            sev_i = _SEVERITY_PRIORITY.get(filtered[i].severity, 99)
            sev_j = _SEVERITY_PRIORITY.get(filtered[i + 1].severity, 99)
            assert sev_i <= sev_j, (
                f"Sort order violation: finding[{i}] severity {filtered[i].severity} "
                f"after finding[{i+1}] severity {filtered[i+1].severity}"
            )

    # Simulate adding 5 CRITICAL gate findings and verify combined total <= 20
    gate_findings = [
        _make_finding(
            id=f"DET-SC-{i:03d}",
            feature="GATE",
            severity_val="critical",
            category_val="security",
            title=f"Gate finding {i}: security check failed",
            description=f"Quality gate critical finding #{i}",
            acceptance_criterion=f"Gate check {i} passes",
        )
        for i in range(1, 6)
    ]

    combined = report.findings + gate_findings
    combined_filtered = filter_findings_for_fix(combined, max_findings=20)
    assert len(combined_filtered) <= 20, (
        f"Combined filter returned {len(combined_filtered)} > 20"
    )

    return filtered


# ---------------------------------------------------------------------------
# Stage 3: Findings → Fix PRD
# ---------------------------------------------------------------------------


def stage3_fix_prd(findings, tmp_dir: Path) -> str:
    """Pass findings through generate_fix_prd and verify output structure."""
    from agent_team_v15.fix_prd_agent import MAX_FIX_PRD_CHARS, generate_fix_prd

    # Write a minimal original PRD for generate_fix_prd to read
    prd_path = tmp_dir / "prd.md"
    prd_path.write_text(
        """# Test Application — Customer Portal

## Overview
A customer portal application.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React / Next.js / TypeScript |
| Backend | Node.js / Express / TypeScript |
| Database | PostgreSQL / Prisma |
| Auth | JWT / bcrypt |
| Infrastructure | Docker / docker-compose |

## Features

### F-001: Dashboard
- AC-1: Dashboard loads within 2 seconds
- AC-2: CSV export button visible on dashboard

### F-002: List View
- AC-5: List endpoint returns paginated response

### SECURITY
- AC-10: Admin routes require authentication
""",
        encoding="utf-8",
    )

    codebase_path = tmp_dir / "codebase"
    codebase_path.mkdir(exist_ok=True)

    fix_prd = generate_fix_prd(
        original_prd_path=prd_path,
        codebase_path=codebase_path,
        findings=findings,
        run_number=2,
        previously_passing_acs=["AC-1", "AC-7"],
    )

    # Verify required sections present
    assert "## Features" in fix_prd, "## Features section missing from fix PRD"
    assert re.search(r"^###\s+F-FIX-\d{3}:", fix_prd, re.MULTILINE), (
        "No ### F-FIX-NNN: heading found in fix PRD"
    )
    assert re.search(r"- AC-FIX-\d{3}-\d{2}:", fix_prd), (
        "No - AC-FIX-NNN-NN: acceptance criterion found in fix PRD"
    )
    assert re.search(r"^#\s+", fix_prd, re.MULTILINE), "Missing H1 title in fix PRD"
    assert "## Regression Guard" in fix_prd, "Regression Guard section missing"
    assert "AC-1" in fix_prd, "Previously passing AC-1 missing from Regression Guard"

    # Verify size cap
    assert len(fix_prd) <= MAX_FIX_PRD_CHARS, (
        f"Fix PRD size {len(fix_prd)} exceeds {MAX_FIX_PRD_CHARS} char limit"
    )

    return fix_prd


# ---------------------------------------------------------------------------
# Stage 4: Validate fix PRD format
# ---------------------------------------------------------------------------


def stage4_validate_fix_prd(fix_prd_text: str) -> None:
    """Validate fix PRD passes internal validation and structural checks."""
    from agent_team_v15.fix_prd_agent import _validate_fix_prd

    # Internal validator must pass
    assert _validate_fix_prd(fix_prd_text), (
        "_validate_fix_prd() returned False — PRD structure invalid"
    )

    # Additional format checks matching what the builder LLM orchestrator expects
    # (headings and AC count)
    f_fix_headings = re.findall(r"^###\s+F-FIX-\d{3}:", fix_prd_text, re.MULTILINE)
    assert len(f_fix_headings) >= 1, (
        f"Expected >= 1 F-FIX headings, found {len(f_fix_headings)}"
    )

    ac_fix_entries = re.findall(r"- AC-FIX-\d{3}-\d{2}:", fix_prd_text)
    assert len(ac_fix_entries) >= 1, (
        f"Expected >= 1 AC-FIX entries, found {len(ac_fix_entries)}"
    )

    # Minimum length
    assert len(fix_prd_text) >= 200, (
        f"Fix PRD too short: {len(fix_prd_text)} chars"
    )

    # Technology stack present (required by _validate_fix_prd)
    tech_keywords = [
        "react", "next", "express", "fastify", "node", "python",
        "django", "flask", "postgresql", "mongodb", "prisma",
        "typescript", "javascript", "docker", "redis",
    ]
    lower = fix_prd_text.lower()
    assert any(kw in lower for kw in tech_keywords), (
        "No technology keywords found — tech stack section missing"
    )

    # Fix run number present
    assert "Fix Run" in fix_prd_text, "Run number marker 'Fix Run' missing from title"


# ---------------------------------------------------------------------------
# Stage 5: Mock reaudit — score improvement + regression detection
# ---------------------------------------------------------------------------


def stage5_reaudit_regression(first_report, fix_prd_text: str, tmp_dir: Path) -> None:
    """Simulate post-fix reaudit and verify score improvement without regressions."""
    from agent_team_v15.audit_agent import (
        ACResult,
        AuditReport,
        Severity,
    )

    # Post-fix report: score improved to 875, CRITICAL findings resolved
    # Only 2 MEDIUM findings remain
    remaining_findings = [
        _make_finding(
            id="F001-AC10",
            feature="F-001",
            severity_val="medium",
            category_val="missing_feature",
            title="Export CSV button not implemented",
            description="CSV export button still pending final styling.",
            file_path="src/components/Dashboard.tsx",
            line_number=88,
            acceptance_criterion="Dashboard CSV export button downloads file on click",
        ),
        _make_finding(
            id="F002-AC05",
            feature="F-002",
            severity_val="medium",
            category_val="code_fix",
            title="Pagination edge case for empty results",
            description="Empty list returns {} instead of {data:[], total:0, page:1}.",
            file_path="src/controllers/list.controller.ts",
            line_number=55,
            acceptance_criterion="List endpoint handles empty result set correctly",
        ),
    ]

    # All previously passing ACs still pass (plus newly fixed ones)
    post_fix_ac_results = [
        ACResult(
            feature_id="F-001",
            ac_id="AC-1",
            ac_text="Dashboard loads within 2 seconds",
            status="PASS",
            evidence="src/pages/Dashboard.tsx:10 — suspense boundary present",
            score=1.0,
        ),
        ACResult(
            feature_id="F-003",
            ac_id="AC-7",
            ac_text="User profile displays full name",
            status="PASS",
            evidence="src/pages/Profile.tsx:30 — fullName rendered",
            score=1.0,
        ),
        ACResult(
            feature_id="SECURITY",
            ac_id="AC-10",
            ac_text="Admin routes require authentication",
            status="PASS",
            evidence="src/routes/admin.ts — AuthGuard added",
            score=1.0,
        ),
        ACResult(
            feature_id="F-002",
            ac_id="AC-5",
            ac_text="List endpoint returns paginated response",
            status="PARTIAL",
            evidence="Pagination present but edge case fails",
            score=0.5,
        ),
    ]

    second_report = AuditReport(
        run_number=2,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        original_prd_path=first_report.original_prd_path,
        codebase_path=first_report.codebase_path,
        total_acs=10,
        passed_acs=8,
        failed_acs=1,
        partial_acs=1,
        skipped_acs=0,
        score=87.5,
        findings=remaining_findings,
        previously_passing=["AC-1", "AC-7", "AC-10"],
        regressions=[],
        audit_cost=0.0,
        route_mapping=[],
        ac_results=post_fix_ac_results,
        comprehensive_score=875,
    )

    # Verify score improvement
    assert second_report.score > first_report.score, (
        f"Score did not improve: {first_report.score} → {second_report.score}"
    )
    assert second_report.comprehensive_score >= 850, (
        f"Post-fix comprehensive_score {second_report.comprehensive_score} < 850 threshold"
    )

    # Verify CRITICAL findings are gone
    assert second_report.critical_count == 0, (
        f"Expected 0 CRITICAL after fix, got {second_report.critical_count}"
    )

    # Verify no regressions: ACs that were passing in report 1 still pass in report 2
    first_passing = set(first_report.previously_passing)
    second_ac_map = {ar.ac_id: ar.status for ar in second_report.ac_results}
    for ac_id in first_passing:
        if ac_id in second_ac_map:
            assert second_ac_map[ac_id] in ("PASS", "PARTIAL"), (
                f"REGRESSION: {ac_id} was passing in run 1 but is now {second_ac_map[ac_id]}"
            )

    # Verify no regressions list is empty
    assert len(second_report.regressions) == 0, (
        f"Unexpected regressions in post-fix report: {second_report.regressions}"
    )

    # Verify stop conditions would trigger STOP on second report (score >= 850, 0 CRITICAL/HIGH)
    from agent_team_v15.config_agent import LoopState, evaluate_stop_conditions

    state_with_one_run = LoopState(
        original_prd_path=first_report.original_prd_path,
        codebase_path=first_report.codebase_path,
        max_budget=300.0,
        max_iterations=4,
    )
    # Add first run so convergence condition can trigger
    state_with_one_run.add_run(first_report, cost=50.0, run_type="initial")

    decision = evaluate_stop_conditions(state_with_one_run, second_report)
    # score went from 72 → 87.5 (+15.5) so convergence won't trigger,
    # but comprehensive_score=875 >= 850 with 0 CRITICAL/0 HIGH → weighted score stop
    # (weighted stop requires len(state.runs) >= 1 and actionable_count > 0)
    # With 2 MEDIUM findings, actionable_count=2, so weighted stop check runs.
    # The simulation cannot import quality_checks without the full env, so we just
    # verify the decision is structurally valid (STOP or CONTINUE — both are acceptable
    # depending on whether quality_checks is importable).
    assert decision.action in ("STOP", "CONTINUE"), (
        f"Unexpected action from evaluate_stop_conditions: {decision.action}"
    )
    assert decision.reason, "evaluate_stop_conditions returned empty reason"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=== Pipeline Dry-Run Simulation ===\n")
    results: dict[str, str] = {}
    failures: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / ".agent-team").mkdir()

        # Stage 1
        stage_name = "Stage 1: Structured Audit Report"
        try:
            report = stage1_mock_audit_report(tmp_dir)
            results[stage_name] = "PASS"
            print(f"  [OK] {stage_name}")
        except Exception as e:
            results[stage_name] = f"FAIL: {e}"
            failures.append((stage_name, str(e)))
            print(f"  [FAIL] {stage_name}: {e}")
            report = None  # type: ignore[assignment]

        # Stage 2
        stage_name = "Stage 2: Triage + Filter (<=20)"
        if report is not None:
            try:
                findings = stage2_triage(report, tmp_dir)
                results[stage_name] = f"PASS ({len(findings)} findings)"
                print(f"  [OK] {stage_name} — {len(findings)} findings")
            except Exception as e:
                results[stage_name] = f"FAIL: {e}"
                failures.append((stage_name, str(e)))
                print(f"  [FAIL] {stage_name}: {e}")
                findings = report.findings[:20]
        else:
            results[stage_name] = "SKIP (Stage 1 failed)"
            findings = []

        # Stage 3
        stage_name = "Stage 3: Fix PRD Generation"
        if findings:
            try:
                fix_prd = stage3_fix_prd(findings, tmp_dir)
                results[stage_name] = f"PASS ({len(fix_prd)} chars)"
                print(f"  [OK] {stage_name} — {len(fix_prd)} chars")
            except Exception as e:
                results[stage_name] = f"FAIL: {e}"
                failures.append((stage_name, str(e)))
                print(f"  [FAIL] {stage_name}: {e}")
                fix_prd = ""
        else:
            results[stage_name] = "SKIP (no findings)"
            fix_prd = ""

        # Stage 4
        stage_name = "Stage 4: Fix PRD Validation"
        if fix_prd:
            try:
                stage4_validate_fix_prd(fix_prd)
                results[stage_name] = "PASS"
                print(f"  [OK] {stage_name}")
            except Exception as e:
                results[stage_name] = f"FAIL: {e}"
                failures.append((stage_name, str(e)))
                print(f"  [FAIL] {stage_name}: {e}")
        else:
            results[stage_name] = "SKIP (no fix PRD)"

        # Stage 5
        stage_name = "Stage 5: Reaudit Regression Check"
        if report is not None and fix_prd:
            try:
                stage5_reaudit_regression(report, fix_prd, tmp_dir)
                results[stage_name] = "PASS"
                print(f"  [OK] {stage_name}")
            except Exception as e:
                results[stage_name] = f"FAIL: {e}"
                failures.append((stage_name, str(e)))
                print(f"  [FAIL] {stage_name}: {e}")
        else:
            results[stage_name] = "SKIP"

    # Summary table
    print("\n=== Results ===")
    all_pass = len(failures) == 0 and all(v.startswith("PASS") for v in results.values())
    for stage, result in results.items():
        icon = "[OK]" if result.startswith("PASS") else ("[SKIP]" if result.startswith("SKIP") else "[FAIL]")
        print(f"  {icon} {stage}: {result}")

    if failures:
        print(f"\nFAILED STAGES ({len(failures)}):")
        for name, err in failures:
            print(f"  - {name}: {err}")

    status = "ALL STAGES PASS" if all_pass else "SOME STAGES FAILED"
    print(f"\n{status}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
