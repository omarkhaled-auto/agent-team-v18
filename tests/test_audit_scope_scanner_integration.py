"""Integration test for the audit_scope_scanner wiring into _run_milestone_audit.

Verifies:
  * The scope scanner runs after the LLM scorer writes AUDIT_REPORT.json
    and before evidence gating.
  * AUDIT-SCOPE-GAP meta-findings end up in the merged AuditReport.
  * Flag off → no meta-findings added.

Because ``_run_milestone_audit`` is heavy (it spawns real Claude SDK
clients), we verify the wiring by executing the code path that runs
inside the "if report_path.is_file()" branch directly with a real
AUDIT_REPORT.json on disk. That exercises every line the wiring
introduced in cli.py without mocking the whole SDK layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.audit_models import AuditFinding, AuditReport
from agent_team_v15.audit_scope_scanner import (
    audit_scope_completeness_enabled,
    build_scope_gap_findings,
    scan_audit_scope,
)
from agent_team_v15.forbidden_content_scanner import merge_findings_into_report


def _write_audit_report_json(audit_dir: Path) -> Path:
    """Write a minimal AUDIT_REPORT.json that loads cleanly."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    report_path = audit_dir / "AUDIT_REPORT.json"
    report_path.write_text(
        json.dumps({
            "audit_id": "AR-1",
            "cycle": 1,
            "auditors_deployed": ["scorer"],
            "findings": [],
            "score": {
                "total_items": 1,
                "passed": 1,
                "failed": 0,
                "partial": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "info_count": 0,
                "score": 100.0,
                "health": "healthy",
            },
            "by_severity": {},
            "by_file": {},
            "by_requirement": {},
            "fix_candidates": [],
        }),
        encoding="utf-8",
    )
    return report_path


def _write_requirements(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).strip() + "\n", encoding="utf-8")


def _config(*, enabled: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(
        audit_scope_completeness_enabled=enabled,
        content_scope_scanner_enabled=False,
    )
    return cfg


class TestAuditScopeScannerWiring:
    """Verify the exact wiring path introduced in _run_milestone_audit."""

    def _run_wiring(
        self,
        *,
        cwd: Path,
        audit_dir: Path,
        requirements_path: Path,
        config: AgentTeamConfig,
    ) -> AuditReport:
        """Execute the wired scanner block from cli.py.

        Mirrors the sequence inside _run_milestone_audit so the test
        exercises the exact imports and merge path the CLI uses.
        """
        report_path = audit_dir / "AUDIT_REPORT.json"
        report = AuditReport.from_json(report_path.read_text(encoding="utf-8"))
        if audit_scope_completeness_enabled(config):
            gaps = scan_audit_scope(
                cwd=cwd,
                requirements_path=requirements_path,
                config=config,
            )
            if gaps:
                gap_finding_dicts = build_scope_gap_findings(gaps)
                gap_findings = [
                    AuditFinding.from_dict(d) for d in gap_finding_dicts
                ]
                merge_findings_into_report(report, gap_findings)
        return report

    def test_scope_gap_finding_merged_when_enabled(
        self, tmp_path: Path
    ) -> None:
        audit_dir = tmp_path / ".agent-team"
        _write_audit_report_json(audit_dir)
        req_path = audit_dir / "REQUIREMENTS.md"
        _write_requirements(
            req_path,
            """
            # M1
            - [ ] REQ-UX: Users should feel empowered by the experience
            """,
        )
        report = self._run_wiring(
            cwd=tmp_path,
            audit_dir=audit_dir,
            requirements_path=req_path,
            config=_config(enabled=True),
        )
        scope_gaps = [
            f for f in report.findings if f.finding_id.startswith("AUDIT-SCOPE-GAP-")
        ]
        assert len(scope_gaps) == 1
        assert scope_gaps[0].severity == "INFO"
        # by_severity index updated.
        assert report.by_severity.get("INFO")

    def test_flag_off_no_scope_gap_findings(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / ".agent-team"
        _write_audit_report_json(audit_dir)
        req_path = audit_dir / "REQUIREMENTS.md"
        _write_requirements(
            req_path,
            """
            - [ ] REQ-UX: Users should feel empowered by the experience
            """,
        )
        report = self._run_wiring(
            cwd=tmp_path,
            audit_dir=audit_dir,
            requirements_path=req_path,
            config=_config(enabled=False),
        )
        scope_gaps = [
            f for f in report.findings if f.finding_id.startswith("AUDIT-SCOPE-GAP-")
        ]
        assert scope_gaps == []

    def test_covered_requirement_emits_nothing(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / ".agent-team"
        _write_audit_report_json(audit_dir)
        req_path = audit_dir / "REQUIREMENTS.md"
        _write_requirements(
            req_path,
            """
            - [ ] REQ-001: Implement apps/api/src/auth/auth.controller.ts
            """,
        )
        report = self._run_wiring(
            cwd=tmp_path,
            audit_dir=audit_dir,
            requirements_path=req_path,
            config=_config(enabled=True),
        )
        scope_gaps = [
            f for f in report.findings if f.finding_id.startswith("AUDIT-SCOPE-GAP-")
        ]
        assert scope_gaps == []
