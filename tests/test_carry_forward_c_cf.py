"""Carry-forward tests: C-CF-1, C-CF-2, C-CF-3.

Covers:
- C-CF-1: AuditFinding.from_dict evidence fold (canonical, scorer w/ file+desc, scorer w/ file only)
- C-CF-1: build-l replay — all 28 findings have evidence
- C-CF-2: 8 scaffold files emitted (nest-cli.json, tsconfig.build.json, 5 module stubs, turbo.json)
- C-CF-2: module stub content pattern
- C-CF-3: build_report(extras=...) preserves extras
- C-CF-3: extras survive to_json round-trip
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.audit_models import AuditFinding, AuditReport, build_report
from agent_team_v15.scaffold_runner import (
    _scaffold_api_nest_cli_template,
    _scaffold_api_tsconfig_build_template,
    _scaffold_module_stub_template,
    _scaffold_root_turbo_template,
)


# Path to the preserved build-l AUDIT_REPORT.json
_BUILD_L_ROOT = Path(__file__).resolve().parent.parent / "v18 test runs" / "build-l-gate-a-20260416"
_BUILD_L_AUDIT_REPORT = _BUILD_L_ROOT / ".agent-team" / "AUDIT_REPORT.json"


# =========================================================================
# C-CF-1: Evidence fold in AuditFinding.from_dict
# =========================================================================

class TestCCF1EvidenceFold:
    """C-CF-1: AuditFinding.from_dict evidence synthesis."""

    def test_canonical_shape_explicit_evidence_preserved(self) -> None:
        data = {
            "finding_id": "TA-001",
            "auditor": "technical",
            "requirement_id": "REQ-001",
            "verdict": "FAIL",
            "severity": "HIGH",
            "summary": "Missing error handler",
            "evidence": ["src/app.ts:10 -- no try-catch"],
        }
        finding = AuditFinding.from_dict(data)
        assert finding.evidence == ["src/app.ts:10 -- no try-catch"]

    def test_scorer_shape_file_and_description_synthesizes_evidence(self) -> None:
        data = {
            "id": "AUD-001",
            "severity": "critical",
            "title": "Missing package",
            "description": "The monorepo root has no packages/ directory",
            "file": "packages/",
        }
        finding = AuditFinding.from_dict(data)
        assert len(finding.evidence) == 1
        assert "packages/" in finding.evidence[0]
        assert "The monorepo root has no packages/ directory" in finding.evidence[0]

    def test_scorer_shape_file_only_evidence_is_file(self) -> None:
        data = {
            "id": "AUD-002",
            "severity": "high",
            "title": "Missing file",
            "file": "apps/web/src/",
        }
        finding = AuditFinding.from_dict(data)
        assert len(finding.evidence) == 1
        assert finding.evidence[0] == "apps/web/src/"

    def test_no_evidence_no_file_empty_list(self) -> None:
        data = {
            "id": "AUD-003",
            "severity": "medium",
            "title": "General issue",
        }
        finding = AuditFinding.from_dict(data)
        assert finding.evidence == []

    def test_evidence_truncated_to_80_chars(self) -> None:
        long_desc = "x" * 200
        data = {
            "id": "AUD-004",
            "severity": "high",
            "title": "Long desc",
            "description": long_desc,
            "file": "src/foo.ts",
        }
        finding = AuditFinding.from_dict(data)
        assert len(finding.evidence) == 1
        # The description portion should be truncated to 80 chars
        desc_portion = finding.evidence[0].split(" — ")[1] if " — " in finding.evidence[0] else ""
        assert len(desc_portion) <= 80


class TestCCF1BuildLReplay:
    """C-CF-1: build-l replay — all findings have evidence."""

    @pytest.fixture()
    def build_l_report(self) -> AuditReport:
        assert _BUILD_L_AUDIT_REPORT.is_file(), (
            f"build-l AUDIT_REPORT.json not found at {_BUILD_L_AUDIT_REPORT}"
        )
        raw = _BUILD_L_AUDIT_REPORT.read_text(encoding="utf-8")
        return AuditReport.from_json(raw)

    def test_all_findings_have_evidence(self, build_l_report: AuditReport) -> None:
        for finding in build_l_report.findings:
            assert len(finding.evidence) > 0, (
                f"Finding {finding.finding_id} has no evidence"
            )

    def test_finding_count_matches_expected(self, build_l_report: AuditReport) -> None:
        # build-l has 28 deduplicated findings per the report header
        assert len(build_l_report.findings) == 28


# =========================================================================
# C-CF-2: Scaffold file emissions
# =========================================================================

class TestCCF2ScaffoldEmissions:
    """C-CF-2: 8 scaffold files — nest-cli.json, tsconfig.build.json, 5 module stubs, turbo.json."""

    def test_nest_cli_json_is_valid_json(self) -> None:
        content = _scaffold_api_nest_cli_template()
        data = json.loads(content)
        assert data["collection"] == "@nestjs/schematics"
        assert "compilerOptions" in data

    def test_tsconfig_build_json_is_valid_json(self) -> None:
        content = _scaffold_api_tsconfig_build_template()
        data = json.loads(content)
        assert data["extends"] == "./tsconfig.json"
        assert "exclude" in data

    def test_turbo_json_is_valid_json(self) -> None:
        content = _scaffold_root_turbo_template()
        data = json.loads(content)
        assert "pipeline" in data
        assert "build" in data["pipeline"]

    def test_module_stub_auth(self) -> None:
        content = _scaffold_module_stub_template("auth")
        assert "@Module(" in content
        assert "export class AuthModule {}" in content

    def test_module_stub_users(self) -> None:
        content = _scaffold_module_stub_template("users")
        assert "@Module(" in content
        assert "export class UsersModule {}" in content

    def test_module_stub_projects(self) -> None:
        content = _scaffold_module_stub_template("projects")
        assert "export class ProjectsModule {}" in content

    def test_module_stub_tasks(self) -> None:
        content = _scaffold_module_stub_template("tasks")
        assert "export class TasksModule {}" in content

    def test_module_stub_comments(self) -> None:
        content = _scaffold_module_stub_template("comments")
        assert "export class CommentsModule {}" in content

    def test_module_stub_pattern_imports_module_decorator(self) -> None:
        content = _scaffold_module_stub_template("auth")
        assert "import { Module } from '@nestjs/common'" in content


# =========================================================================
# C-CF-3: build_report extras passthrough
# =========================================================================

class TestCCF3BuildReportExtras:
    """C-CF-3: build_report(extras=...) preserves extras."""

    def test_extras_preserved_in_report(self) -> None:
        report = build_report(
            audit_id="test-audit-001",
            cycle=1,
            auditors_deployed=["requirements"],
            findings=[],
            extras={"verdict": "FAIL", "health": "degraded"},
        )
        assert report.extras["verdict"] == "FAIL"
        assert report.extras["health"] == "degraded"

    def test_extras_none_uses_empty_dict(self) -> None:
        report = build_report(
            audit_id="test-audit-002",
            cycle=1,
            auditors_deployed=[],
            findings=[],
            extras=None,
        )
        assert report.extras == {}

    def test_extras_survive_to_json_round_trip(self) -> None:
        report = build_report(
            audit_id="test-audit-003",
            cycle=1,
            auditors_deployed=["requirements"],
            findings=[],
            extras={"verdict": "PASS", "notes": "All good"},
        )
        json_str = report.to_json()
        data = json.loads(json_str)
        # Extras are spread at the top level per to_json semantics
        assert data["verdict"] == "PASS"
        assert data["notes"] == "All good"

    def test_extras_do_not_override_canonical_fields(self) -> None:
        report = build_report(
            audit_id="test-audit-004",
            cycle=1,
            auditors_deployed=["requirements"],
            findings=[],
            extras={"audit_id": "should-not-override", "cycle": 999},
        )
        json_str = report.to_json()
        data = json.loads(json_str)
        # Canonical fields must win over extras
        assert data["audit_id"] == "test-audit-004"
        assert data["cycle"] == 1
