"""Audit worker — run as a subprocess by coordinated_builder._run_audit().

This module exists so the audit can be launched as a child process (identical
to how _run_builder launches the builder), which means claude_agent_sdk's CLI
calls are NOT nested inside an existing Claude Code session and work correctly.

Usage (invoked automatically by coordinated_builder._run_audit):
    python -m agent_team_v15._audit_worker \
        --prd PATH --cwd PATH --output PATH \
        [--run-number N] [--model MODEL] [--previous-report PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run audit and save AuditReport JSON")
    parser.add_argument("--prd", required=True, help="Path to original PRD file")
    parser.add_argument("--cwd", required=True, help="Codebase working directory")
    parser.add_argument("--output", required=True, help="Output path for AuditReport JSON")
    parser.add_argument("--run-number", type=int, default=1)
    parser.add_argument("--model", default="claude-opus-4-6")
    parser.add_argument("--evidence-mode", default="disabled")
    parser.add_argument("--previous-report", default=None,
                        help="Path to previous AuditReport JSON for regression detection")
    args = parser.parse_args()

    from agent_team_v15.audit_agent import AuditReport, run_full_audit

    # Load previous report if provided
    previous_report = None
    if args.previous_report:
        prev_path = Path(args.previous_report)
        if prev_path.exists():
            try:
                previous_report = AuditReport.from_dict(json.loads(prev_path.read_text()))
            except Exception as e:
                print(f"[AUDIT WORKER] Warning: could not load previous report: {e}", flush=True)

    print(f"[AUDIT WORKER] Starting audit run {args.run_number}", flush=True)
    print(f"[AUDIT WORKER] PRD: {args.prd}", flush=True)
    print(f"[AUDIT WORKER] CWD: {args.cwd}", flush=True)

    report = run_full_audit(
        original_prd_path=Path(args.prd),
        codebase_path=Path(args.cwd),
        previous_report=previous_report,
        run_number=args.run_number,
        config={
            "audit_model": args.model,
            "evidence_mode": args.evidence_mode,
        },
    )

    # Serialize and save
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.to_json(), encoding="utf-8")

    print(
        f"[AUDIT WORKER] Complete. Score: {report.score:.1f}% | "
        f"ACs: {report.passed_acs}/{report.total_acs} passed | "
        f"Findings: {len(report.findings)} | "
        f"CRITICAL: {report.critical_count} | "
        f"Comprehensive: {report.comprehensive_score}/1000",
        flush=True,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
