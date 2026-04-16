"""N-11 cascade suppression — tests for cli._consolidate_cascade_findings.

Covers the 5 inline scenarios specified in the Wave 3 team-lead brief:

1. flag-OFF returns the report byte-equal to the input;
2. flag-ON with no scaffold_verifier_report.json on disk returns unchanged;
3. flag-ON with only a single-finding "cluster" returns unchanged;
4. flag-ON with ≥2 findings sharing a root cause collapses them correctly;
5. offline replay against a synthetic scaffold-verifier result derived from
   ``v18 test runs/build-l-gate-a-20260416/.agent-team/AUDIT_REPORT.json``
   shows that cascade reduction occurs on a real-world fixture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agent_team_v15.audit_models import AuditFinding, AuditScore, AuditReport, build_report
from agent_team_v15.cli import _consolidate_cascade_findings
from agent_team_v15.config import AgentTeamConfig, V18Config


def _make_report(findings: list[AuditFinding]) -> AuditReport:
    return build_report(
        audit_id="AR-TEST",
        cycle=1,
        auditors_deployed=["scorer"],
        findings=findings,
    )


def _config(*, cascade_enabled: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(cascade_consolidation_enabled=cascade_enabled)
    return cfg


def _finding(
    fid: str,
    *,
    evidence: list[str] | None = None,
    summary: str = "",
    severity: str = "HIGH",
    requirement_id: str = "AC-01",
    verdict: str = "FAIL",
) -> AuditFinding:
    return AuditFinding(
        finding_id=fid,
        auditor="scorer",
        requirement_id=requirement_id,
        verdict=verdict,
        severity=severity,
        summary=summary,
        evidence=evidence or [],
    )


def _write_verifier_report(cwd: Path, missing: list[str], malformed: list[list] | None = None) -> None:
    dst = cwd / ".agent-team" / "scaffold_verifier_report.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "verdict": "FAIL",
        "missing": missing,
        "malformed": malformed or [],
        "deprecated_emitted": [],
        "summary_lines": [],
    }
    dst.write_text(json.dumps(payload), encoding="utf-8")


class TestCascadeSuppressionFlagOff:
    def test_flag_off_returns_report_unchanged(self, tmp_path: Path) -> None:
        cfg = _config(cascade_enabled=False)
        _write_verifier_report(tmp_path, ["apps/api/src/main.ts"])
        findings = [
            _finding("F-1", evidence=["apps/api/src/main.ts:10"]),
            _finding("F-2", evidence=["apps/api/src/main.ts:20"], requirement_id="AC-02"),
        ]
        report = _make_report(findings)

        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))

        assert result is report, "Flag-OFF must be a no-op (same object)"
        assert [f.finding_id for f in result.findings] == ["F-1", "F-2"]
        # No cascade metadata present
        assert all(f.cascade_count == 0 for f in result.findings)


class TestCascadeSuppressionFlagOnNoVerifier:
    def test_flag_on_no_verifier_report_returns_unchanged(self, tmp_path: Path) -> None:
        cfg = _config(cascade_enabled=True)
        # no verifier report written
        findings = [
            _finding("F-1", evidence=["apps/api/src/main.ts:10"]),
            _finding("F-2", evidence=["apps/api/src/main.ts:20"]),
        ]
        report = _make_report(findings)

        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))

        assert result is report, "Missing verifier report must be a no-op"


class TestCascadeSuppressionSingletonCluster:
    def test_flag_on_single_finding_cluster_no_collapse(self, tmp_path: Path) -> None:
        cfg = _config(cascade_enabled=True)
        _write_verifier_report(tmp_path, ["apps/api/src/main.ts"])
        findings = [
            _finding("F-1", evidence=["apps/api/src/main.ts:10"]),
            _finding("F-2", evidence=["apps/web/app/page.tsx:5"], requirement_id="AC-02"),
        ]
        report = _make_report(findings)

        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))

        # Both findings preserved, no cascade metadata, no meta-finding.
        finding_ids = {f.finding_id for f in result.findings}
        assert {"F-1", "F-2"} <= finding_ids
        assert "F-CASCADE-META" not in finding_ids
        for f in result.findings:
            assert f.cascade_count == 0


class TestCascadeSuppressionMultiFindingCluster:
    def test_flag_on_two_findings_share_root_cause_collapses(self, tmp_path: Path) -> None:
        cfg = _config(cascade_enabled=True)
        _write_verifier_report(tmp_path, ["apps/api/src/main.ts"])
        findings = [
            _finding(
                "F-1",
                evidence=["apps/api/src/main.ts:10"],
                severity="HIGH",
                requirement_id="AC-01",
                summary="NestFactory.create missing",
            ),
            _finding(
                "F-2",
                evidence=["apps/api/src/main.ts:20"],
                severity="CRITICAL",
                requirement_id="AC-02",
                summary="server never starts",
            ),
            _finding(
                "F-3",
                evidence=["apps/api/src/main.ts:30"],
                severity="MEDIUM",
                requirement_id="AC-03",
                summary="bootstrap fails",
            ),
            _finding(
                "F-4",
                evidence=["apps/web/app/page.tsx:5"],
                severity="HIGH",
                requirement_id="AC-04",
                summary="unrelated frontend issue",
            ),
        ]
        report = _make_report(findings)

        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))

        finding_ids = [f.finding_id for f in result.findings]
        # The CRITICAL finding F-2 should be representative (outranks HIGH/MEDIUM)
        assert "F-2" in finding_ids, "CRITICAL representative should survive"
        # The unrelated finding F-4 should survive untouched
        assert "F-4" in finding_ids
        # F-1 and F-3 (consumed) should NOT appear
        assert "F-1" not in finding_ids
        assert "F-3" not in finding_ids
        # Meta-finding exists
        assert "F-CASCADE-META" in finding_ids

        representative = next(f for f in result.findings if f.finding_id == "F-2")
        assert representative.cascade_count == 2
        assert set(representative.cascaded_from) == {"F-1", "F-3"}
        # Evidence annotation appended
        assert any("N-11 cascade" in ev for ev in representative.evidence)


class TestCascadeSuppressionBuildLReplay:
    """Offline replay using a synthetic scaffold-verifier result similar to
    what build-l-gate-a-20260416 would have produced. We don't require the
    actual build artifacts — we synthesize a comparable fixture so the test
    is hermetic and independent of external state.
    """

    def test_build_l_style_replay_reduces_finding_count(self, tmp_path: Path) -> None:
        cfg = _config(cascade_enabled=True)
        _write_verifier_report(
            tmp_path,
            missing=[
                "apps/api/src/database/prisma.module.ts",
                "apps/api/src/database/prisma.service.ts",
            ],
            malformed=[
                ["apps/api/src/main.ts", "missing NestFactory.create"],
            ],
        )

        # Synthesize 7 downstream findings: 3 referencing prisma.module.ts,
        # 2 referencing prisma.service.ts, 1 referencing main.ts, and 1
        # unrelated frontend finding — mirroring a build-l-style fanout
        # where structural scaffold errors cascade into many downstream
        # surface complaints.
        findings = [
            _finding("F-10", evidence=["apps/api/src/database/prisma.module.ts:1"], requirement_id="AC-M1", severity="HIGH"),
            _finding("F-11", evidence=["apps/api/src/database/prisma.module.ts:2"], requirement_id="AC-M2", severity="MEDIUM"),
            _finding("F-12", evidence=["apps/api/src/database/prisma.module.ts:3"], requirement_id="AC-M3", severity="CRITICAL"),
            _finding("F-20", evidence=["apps/api/src/database/prisma.service.ts:1"], requirement_id="AC-S1", severity="HIGH"),
            _finding("F-21", evidence=["apps/api/src/database/prisma.service.ts:2"], requirement_id="AC-S2", severity="MEDIUM"),
            _finding("F-30", evidence=["apps/api/src/main.ts:1"], requirement_id="AC-X1", severity="HIGH"),
            _finding("F-99", evidence=["apps/web/app/page.tsx:1"], requirement_id="AC-UI", severity="LOW"),
        ]
        report = _make_report(findings)
        original_count = len(report.findings)

        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))

        finding_ids = [f.finding_id for f in result.findings]
        # Representatives for prisma.module.ts cluster: CRITICAL F-12 wins.
        # Representatives for prisma.service.ts cluster: HIGH F-20 wins.
        # main.ts had only F-30 → singleton, no collapse.
        # F-99 untouched.
        assert "F-12" in finding_ids
        assert "F-20" in finding_ids
        assert "F-30" in finding_ids
        assert "F-99" in finding_ids
        assert "F-CASCADE-META" in finding_ids
        # Consumed findings absent
        for fid in ("F-10", "F-11", "F-21"):
            assert fid not in finding_ids, f"consumed finding {fid} must not survive"

        # Net reduction: 7 downstream → 4 surviving representatives/singletons
        # + 1 meta-finding = 5 total (vs. 7 original).
        assert len(result.findings) < original_count, (
            "cascade consolidation must reduce finding count"
        )
