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


# ===========================================================================
# Phase F: Wave D failure cascade extension
# ===========================================================================


def _write_wave_d_failed_state(cwd: Path, *, milestone_id: str = "milestone-1") -> None:
    """Persist a minimal STATE.json with ``failed_wave == "D"`` for one milestone."""
    from agent_team_v15.state import RunState, save_state

    state = RunState()
    state.wave_progress[milestone_id] = {
        "current_wave": "D",
        "completed_waves": ["A", "B", "C"],
        "wave_artifacts": {},
        "failed_wave": "D",
    }
    state_dir = cwd / ".agent-team"
    state_dir.mkdir(parents=True, exist_ok=True)
    save_state(state, directory=str(state_dir))


class TestCascadeSuppressionWaveDFailure:
    """Phase F: Wave D failure cascades absorb downstream D.5/T/E symptoms."""

    def test_flag_on_no_state_no_cascade(self, tmp_path: Path) -> None:
        """Flag on but no STATE.json → no Wave D cascade, existing behavior."""
        cfg = _config(cascade_enabled=True)
        findings = [
            _finding("F-1", evidence=["apps/web/app/page.tsx:1"]),
            _finding("F-2", evidence=["apps/web/app/page.tsx:2"]),
        ]
        report = _make_report(findings)
        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))
        # No STATE.json → returns unchanged; no meta-finding.
        assert all(f.cascade_count == 0 for f in result.findings)

    def test_flag_on_state_but_wave_d_not_failed(self, tmp_path: Path) -> None:
        """When Wave D is COMPLETE (not failed), no Wave D cascade."""
        from agent_team_v15.state import RunState, save_state

        state = RunState()
        state.wave_progress["milestone-1"] = {
            "current_wave": "D",
            "completed_waves": ["A", "B", "C", "D"],
            "wave_artifacts": {},
        }
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir(parents=True, exist_ok=True)
        save_state(state, directory=str(state_dir))

        cfg = _config(cascade_enabled=True)
        findings = [
            _finding("F-1", evidence=["apps/web/app/page.tsx:1"]),
            _finding("F-2", evidence=["apps/web/app/page.tsx:2"]),
        ]
        report = _make_report(findings)
        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))
        assert all(f.cascade_count == 0 for f in result.findings)

    def test_wave_d_failure_collapses_web_app_findings(self, tmp_path: Path) -> None:
        """Wave D failure + >=2 web app findings → collapse under apps/web root."""
        _write_wave_d_failed_state(tmp_path)
        cfg = _config(cascade_enabled=True)
        findings = [
            _finding("F-1", requirement_id="AC-W1", evidence=["apps/web/app/(dashboard)/page.tsx:12"], severity="HIGH"),
            _finding("F-2", requirement_id="AC-W2", evidence=["apps/web/app/(dashboard)/layout.tsx:5"], severity="CRITICAL"),
            _finding("F-3", requirement_id="AC-W3", evidence=["apps/web/components/Card.tsx:30"], severity="MEDIUM"),
            _finding("F-99", requirement_id="AC-API", evidence=["apps/api/src/main.ts:1"], severity="HIGH"),
        ]
        report = _make_report(findings)
        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))
        ids = [f.finding_id for f in result.findings]
        # CRITICAL F-2 wins as representative for apps/web cluster.
        assert "F-2" in ids
        assert "F-99" in ids  # unrelated apps/api finding untouched
        assert "F-CASCADE-META" in ids
        # Consumed F-1 and F-3 must be absent.
        assert "F-1" not in ids
        assert "F-3" not in ids

    def test_wave_d_failure_collapses_api_client_findings(self, tmp_path: Path) -> None:
        """Wave D failure also absorbs packages/api-client findings."""
        _write_wave_d_failed_state(tmp_path)
        cfg = _config(cascade_enabled=True)
        findings = [
            _finding("F-10", requirement_id="AC-AC1", evidence=["packages/api-client/src/index.ts:1"], severity="HIGH"),
            _finding("F-11", requirement_id="AC-AC2", evidence=["packages/api-client/src/types.ts:3"], severity="HIGH"),
        ]
        report = _make_report(findings)
        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))
        ids = [f.finding_id for f in result.findings]
        # Exactly one representative + meta-finding.
        assert sum(1 for i in ids if i in ("F-10", "F-11")) == 1
        assert "F-CASCADE-META" in ids
        # Remediation message should reference Wave D.
        meta = next(f for f in result.findings if f.finding_id == "F-CASCADE-META")
        assert "Wave D" in meta.remediation

    def test_wave_d_cascade_note_labels_root_kind(self, tmp_path: Path) -> None:
        """Cascade note on representative records the root is Wave D."""
        _write_wave_d_failed_state(tmp_path)
        cfg = _config(cascade_enabled=True)
        findings = [
            _finding("F-1", requirement_id="AC-W1", evidence=["apps/web/app/layout.tsx:5"], severity="CRITICAL"),
            _finding("F-2", requirement_id="AC-W2", evidence=["apps/web/components/Button.tsx:3"], severity="HIGH"),
        ]
        report = _make_report(findings)
        result = _consolidate_cascade_findings(report, config=cfg, cwd=str(tmp_path))
        representative = next(f for f in result.findings if f.finding_id == "F-1")
        assert representative.cascade_count == 1
        assert any("Wave D root cause" in ev for ev in representative.evidence)


# ===========================================================================
# F-EDGE-002 regression: Wave D cascade must be scoped to current milestone
# ===========================================================================


class TestWaveDCascadePerMilestoneScope:
    """F-EDGE-002: Wave D cascade is per-milestone, not global.

    Previously, if ANY milestone's ``wave_progress`` had
    ``failed_wave == "D"``, the cascade absorbed EVERY milestone's
    findings mentioning ``apps/web`` or ``packages/api-client``. This
    caused false positives in multi-milestone runs: M2's audit (M2's
    Wave D succeeded) inherited cascade collapses from M1's Wave D
    failure.
    """

    @staticmethod
    def _write_two_milestone_state(cwd: Path) -> None:
        from agent_team_v15.state import RunState, save_state

        state = RunState()
        state.wave_progress["milestone-1"] = {
            "current_wave": "D",
            "completed_waves": ["A", "B", "C"],
            "wave_artifacts": {},
            "failed_wave": "D",
        }
        state.wave_progress["milestone-2"] = {
            "current_wave": "E",
            "completed_waves": ["A", "B", "C", "D"],
            "wave_artifacts": {},
        }
        state_dir = cwd / ".agent-team"
        state_dir.mkdir(parents=True, exist_ok=True)
        save_state(state, directory=str(state_dir))

    def test_m2_findings_not_collapsed_when_only_m1_wave_d_failed(
        self, tmp_path: Path
    ) -> None:
        self._write_two_milestone_state(tmp_path)
        cfg = _config(cascade_enabled=True)
        findings = [
            _finding(
                "F-1",
                requirement_id="AC-M2-W1",
                evidence=["apps/web/app/page.tsx:1"],
                severity="HIGH",
            ),
            _finding(
                "F-2",
                requirement_id="AC-M2-W2",
                evidence=["apps/web/app/layout.tsx:2"],
                severity="HIGH",
            ),
        ]
        report = _make_report(findings)
        # Auditing milestone-2 — its Wave D did NOT fail. Cascade must
        # NOT collapse the web app findings for this milestone.
        result = _consolidate_cascade_findings(
            report, config=cfg, cwd=str(tmp_path), milestone_id="milestone-2"
        )
        assert all(f.cascade_count == 0 for f in result.findings)
        ids = {f.finding_id for f in result.findings}
        assert "F-1" in ids
        assert "F-2" in ids
        assert "F-CASCADE-META" not in ids

    def test_m1_findings_do_collapse_when_m1_wave_d_failed(
        self, tmp_path: Path
    ) -> None:
        self._write_two_milestone_state(tmp_path)
        cfg = _config(cascade_enabled=True)
        findings = [
            _finding(
                "F-1",
                requirement_id="AC-M1-W1",
                evidence=["apps/web/app/page.tsx:1"],
                severity="HIGH",
            ),
            _finding(
                "F-2",
                requirement_id="AC-M1-W2",
                evidence=["apps/web/app/layout.tsx:2"],
                severity="CRITICAL",
            ),
        ]
        report = _make_report(findings)
        # Auditing milestone-1 — its Wave D failed, cascade active.
        result = _consolidate_cascade_findings(
            report, config=cfg, cwd=str(tmp_path), milestone_id="milestone-1"
        )
        ids = {f.finding_id for f in result.findings}
        assert "F-CASCADE-META" in ids
        # CRITICAL F-2 wins as representative.
        assert "F-2" in ids
        assert "F-1" not in ids

    def test_no_milestone_id_falls_back_to_global(
        self, tmp_path: Path
    ) -> None:
        """Legacy callers without a milestone id still see global cascade."""
        self._write_two_milestone_state(tmp_path)
        cfg = _config(cascade_enabled=True)
        findings = [
            _finding(
                "F-1",
                requirement_id="AC-W1",
                evidence=["apps/web/app/page.tsx:1"],
                severity="HIGH",
            ),
            _finding(
                "F-2",
                requirement_id="AC-W2",
                evidence=["apps/web/app/layout.tsx:2"],
                severity="CRITICAL",
            ),
        ]
        report = _make_report(findings)
        # milestone_id omitted → legacy fallback: ANY milestone with
        # failed_wave="D" triggers the cascade.
        result = _consolidate_cascade_findings(
            report, config=cfg, cwd=str(tmp_path)
        )
        ids = {f.finding_id for f in result.findings}
        assert "F-CASCADE-META" in ids
