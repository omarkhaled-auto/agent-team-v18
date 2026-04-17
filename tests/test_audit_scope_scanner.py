"""Phase F auditor scope completeness scanner — tests.

Covers:
  * Requirements with explicit file-path evidence → covered
  * Requirements referencing i18n/RTL with N-10 active → covered
  * Requirements referencing i18n/RTL with N-10 disabled → gap
  * Requirements mentioning design tokens with UI_DESIGN_TOKENS.json
    present → covered; missing → gap
  * Requirements without any matching keyword / path → gap
  * Flag-off returns empty list regardless of state
  * ``build_scope_gap_findings`` produces INFO-severity meta-findings
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.audit_scope_scanner import (
    build_scope_gap_findings,
    scan_audit_scope,
)


def _config(
    *,
    enabled: bool = True,
    content_scope: bool = False,
) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(
        audit_scope_completeness_enabled=enabled,
        content_scope_scanner_enabled=content_scope,
    )
    return cfg


def _write_requirements(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).strip() + "\n", encoding="utf-8")


class TestFlagGating:
    def test_flag_off_returns_empty(self, tmp_path: Path) -> None:
        req = tmp_path / ".agent-team" / "milestones" / "m1" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            # REQ-001: something without coverage
            - [ ] REQ-001: something without coverage
            """,
        )
        cfg = _config(enabled=False)
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=cfg,
        )
        assert gaps == []


class TestCoverageDetection:
    def test_file_path_in_title_is_covered(self, tmp_path: Path) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            - [ ] REQ-001: Implement apps/api/src/auth/auth.controller.ts
            """,
        )
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=_config(),
        )
        assert gaps == []

    def test_i18n_requirement_with_n10_active_is_covered(
        self, tmp_path: Path
    ) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            - [ ] REQ-002: Arabic RTL translation support across dashboards
            """,
        )
        cfg = _config(content_scope=True)
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=cfg,
        )
        assert gaps == []

    def test_i18n_requirement_without_n10_is_gap(self, tmp_path: Path) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            - [ ] REQ-003: i18n RTL enforcement everywhere
            """,
        )
        cfg = _config(content_scope=False)
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=cfg,
        )
        assert len(gaps) == 1
        assert gaps[0].requirement_id == "REQ-003"
        assert "scanner is not active" in gaps[0].reason

    def test_design_tokens_present_is_covered(self, tmp_path: Path) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            - [ ] REQ-004: UI design tokens JSON available for frontend
            """,
        )
        (tmp_path / "UI_DESIGN_TOKENS.json").write_text("{}", encoding="utf-8")
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=_config(),
        )
        assert gaps == []

    def test_design_tokens_missing_is_gap(self, tmp_path: Path) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            - [ ] REQ-005: UI design tokens JSON exports for the team
            """,
        )
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=_config(),
        )
        assert len(gaps) == 1
        assert gaps[0].requirement_id == "REQ-005"

    def test_stack_contract_with_verifier_report_is_covered(
        self, tmp_path: Path
    ) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            - [ ] REQ-006: stack contract compliance must be verified
            """,
        )
        report = tmp_path / ".agent-team" / "scaffold_verifier_report.json"
        report.write_text("{}", encoding="utf-8")
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=_config(),
        )
        assert gaps == []

    def test_no_keyword_no_path_is_gap(self, tmp_path: Path) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            - [ ] REQ-007: Users should feel empowered by the experience
            """,
        )
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=_config(),
        )
        assert len(gaps) == 1
        assert "no scanner / auditor surface matched" in gaps[0].reason


class TestMultipleRequirements:
    def test_mixed_coverage(self, tmp_path: Path) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            # M1 requirements
            - [x] REQ-001: Implement apps/api/src/auth/guard.ts
            - [ ] REQ-002: Arabic RTL translation
            - [ ] REQ-003: A general UX improvement
            """,
        )
        cfg = _config(content_scope=False)  # N-10 off → REQ-002 is gap
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=cfg,
        )
        gap_ids = {g.requirement_id for g in gaps}
        # REQ-001 has file path → covered; REQ-002 is i18n w/ N-10 off;
        # REQ-003 has no keyword / path → gap.
        assert gap_ids == {"REQ-002", "REQ-003"}


class TestBuildScopeGapFindings:
    def test_produces_info_severity_findings(self, tmp_path: Path) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(
            req,
            """
            - [ ] REQ-010: unclear requirement
            """,
        )
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=_config(),
        )
        findings = build_scope_gap_findings(gaps)
        assert len(findings) == 1
        f = findings[0]
        assert f["finding_id"] == "AUDIT-SCOPE-GAP-REQ-010"
        assert f["severity"] == "INFO"
        assert f["verdict"] == "UNVERIFIED"
        assert f["source"] == "deterministic"
        assert "auditor / scanner coverage" in f["summary"]


class TestEmptyInputs:
    def test_missing_requirements_file(self, tmp_path: Path) -> None:
        gaps = scan_audit_scope(
            cwd=tmp_path,
            requirements_path=tmp_path / "missing.md",
            config=_config(),
        )
        assert gaps == []

    def test_empty_requirements_file(self, tmp_path: Path) -> None:
        req = tmp_path / ".agent-team" / "REQUIREMENTS.md"
        _write_requirements(req, "")
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req, config=_config(),
        )
        assert gaps == []
