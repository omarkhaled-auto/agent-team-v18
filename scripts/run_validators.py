"""Run all deterministic validators and output structured JSON.

Usage:
    python scripts/run_validators.py <project_path> [--previous <prev_report.json>]

Output: JSON to stdout with findings, severities, check IDs, scan time.
When --previous is given, also outputs regression analysis (new/fixed/unchanged).

Exit code: 0 if no critical findings, 1 if critical findings exist.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure the package is importable when running from repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


def _run_schema_validator(project_path: Path) -> list[dict]:
    """Run schema_validator and return normalized findings."""
    from agent_team_v15.schema_validator import run_schema_validation

    findings = []
    for sf in run_schema_validation(project_path):
        findings.append({
            "id": sf.check,
            "scanner": "schema_validator",
            "severity": sf.severity,
            "message": sf.message,
            "model": sf.model,
            "field": sf.field,
            "line": sf.line,
            "file_path": "schema.prisma",
            "suggestion": sf.suggestion,
        })
    return findings


def _run_quality_validators(project_path: Path) -> list[dict]:
    """Run quality_validators and return normalized findings."""
    from agent_team_v15.quality_validators import run_quality_validators

    findings = []
    for qv in run_quality_validators(project_path):
        findings.append({
            "id": qv.check,
            "scanner": "quality_validators",
            "severity": qv.severity,
            "message": qv.message,
            "file_path": qv.file_path,
            "line": qv.line,
        })
    return findings


def _run_integration_verifier(project_path: Path) -> list[dict]:
    """Run integration_verifier and return normalized findings."""
    from agent_team_v15.integration_verifier import verify_integration

    findings = []
    report = verify_integration(project_path, run_mode="warn")
    if hasattr(report, "mismatches"):
        for mm in report.mismatches:
            findings.append({
                "id": "API_CONTRACT",
                "scanner": "integration_verifier",
                "severity": getattr(mm, "severity", "high"),
                "message": getattr(mm, "description", str(mm)),
                "file_path": getattr(mm, "file_path", ""),
                "line": getattr(mm, "line", 0),
                "frontend_value": getattr(mm, "frontend_value", ""),
                "backend_value": getattr(mm, "backend_value", ""),
                "suggestion": getattr(mm, "suggestion", ""),
            })
    return findings


def _run_spot_checks(project_path: Path) -> list[dict]:
    """Run quality_checks spot checks and return normalized findings."""
    from agent_team_v15.quality_checks import run_spot_checks

    findings = []
    for sv in run_spot_checks(project_path):
        findings.append({
            "id": sv.check,
            "scanner": "quality_checks",
            "severity": sv.severity,
            "message": sv.message,
            "file_path": sv.file_path,
            "line": sv.line,
        })
    return findings


def _normalize_severity(sev: str) -> str:
    """Normalize severity strings to canonical form."""
    s = sev.lower()
    if s in ("error",):
        return "high"
    if s in ("warning",):
        return "medium"
    if s in ("info",):
        return "low"
    if s in ("critical", "high", "medium", "low"):
        return s
    return "medium"


def _finding_signature(f: dict) -> str:
    """Create a stable signature for deduplication and regression tracking."""
    return f"{f['id']}|{f.get('file_path', '')}|{f.get('line', 0)}|{f.get('message', '')[:100]}"


def _compute_regression(current: list[dict], previous: list[dict]) -> dict:
    """Compare current vs previous findings and classify changes."""
    current_sigs = {_finding_signature(f): f for f in current}
    previous_sigs = {_finding_signature(f): f for f in previous}

    current_keys = set(current_sigs.keys())
    previous_keys = set(previous_sigs.keys())

    new_keys = current_keys - previous_keys
    fixed_keys = previous_keys - current_keys
    unchanged_keys = current_keys & previous_keys

    return {
        "new_findings": [current_sigs[k] for k in sorted(new_keys)],
        "fixed_findings": [previous_sigs[k] for k in sorted(fixed_keys)],
        "unchanged_count": len(unchanged_keys),
        "new_count": len(new_keys),
        "fixed_count": len(fixed_keys),
        "improvement_rate": (
            round(len(fixed_keys) / max(len(previous_keys), 1) * 100, 1)
        ),
    }


def run_all(project_path: Path, previous_path: Path | None = None) -> dict:
    """Run all validators and return structured results."""
    start_ms = time.monotonic()
    all_findings: list[dict] = []
    scanner_results: dict[str, dict] = {}

    scanners = [
        ("schema_validator", _run_schema_validator),
        ("quality_validators", _run_quality_validators),
        ("integration_verifier", _run_integration_verifier),
        ("quality_checks", _run_spot_checks),
    ]

    for name, fn in scanners:
        try:
            results = fn(project_path)
            # Normalize severities
            for r in results:
                r["severity"] = _normalize_severity(r.get("severity", "medium"))
            all_findings.extend(results)
            scanner_results[name] = {
                "count": len(results),
                "status": "ok",
            }
        except ImportError:
            scanner_results[name] = {"count": 0, "status": "unavailable"}
        except Exception as e:
            scanner_results[name] = {"count": 0, "status": f"error: {e}"}

    elapsed_ms = round((time.monotonic() - start_ms) * 1000)

    # Severity breakdown
    by_severity: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in all_findings:
        sev = f.get("severity", "medium")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # Unique check IDs
    check_ids = sorted(set(f["id"] for f in all_findings))

    result: dict = {
        "total": len(all_findings),
        "by_scanner": scanner_results,
        "by_severity": by_severity,
        "check_ids": check_ids,
        "scan_time_ms": elapsed_ms,
        "findings": all_findings,
    }

    # Regression analysis if previous report provided
    if previous_path is not None:
        try:
            with open(previous_path, "r") as fh:
                prev_data = json.load(fh)
            prev_findings = prev_data.get("findings", [])
            result["regression"] = _compute_regression(all_findings, prev_findings)
        except (json.JSONDecodeError, OSError) as e:
            result["regression"] = {"error": f"Could not load previous report: {e}"}

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run all deterministic validators and output structured JSON."
    )
    parser.add_argument("project_path", type=Path, help="Path to the project to scan")
    parser.add_argument(
        "--previous", type=Path, default=None,
        help="Path to a previous JSON report for regression analysis",
    )
    args = parser.parse_args()

    if not args.project_path.is_dir():
        print(json.dumps({"error": f"Not a directory: {args.project_path}"}), file=sys.stdout)
        return 1

    result = run_all(args.project_path, args.previous)
    print(json.dumps(result, indent=2))

    # Exit 1 if any critical findings
    has_critical = result.get("by_severity", {}).get("critical", 0) > 0
    return 1 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())
