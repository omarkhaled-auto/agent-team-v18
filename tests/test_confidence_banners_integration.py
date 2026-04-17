"""Integration test for confidence_banners wiring at audit-loop finalize.

Verifies the stamp-all-reports block that ``_run_audit_loop`` runs
after writing AUDIT_REPORT.json. Because the full loop requires a live
Claude SDK we reproduce the final-block sequence here against a real
.agent-team/ tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.confidence_banners import (
    ConfidenceSignals,
    confidence_banners_enabled,
    stamp_all_reports,
)


def _config(
    *,
    enabled: bool = True,
    evidence_mode: str = "soft_gate",
) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(
        confidence_banners_enabled=enabled,
        evidence_mode=evidence_mode,
    )
    return cfg


def _setup_tree(tmp_path: Path) -> Path:
    agent_dir = tmp_path / ".agent-team"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AUDIT_REPORT.json").write_text(
        json.dumps({"score": 92.0, "findings": []}, indent=2),
        encoding="utf-8",
    )
    (agent_dir / "BUILD_LOG.txt").write_text(
        "2026-04-17 12:00 build start\n",
        encoding="utf-8",
    )
    (agent_dir / "GATE_A_REPORT.md").write_text(
        "# Gate A\n\nBody.\n", encoding="utf-8",
    )
    (agent_dir / "FINAL_RECOVERY_REPORT.md").write_text(
        "# Recovery\n", encoding="utf-8",
    )
    return agent_dir


class TestConfidenceBannersFinalizeWiring:
    def test_flag_on_stamps_all_reports(self, tmp_path: Path) -> None:
        agent_dir = _setup_tree(tmp_path)
        cfg = _config(enabled=True)
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            fix_loop_converged=True,
            runtime_verification_ran=True,
        )
        touched = stamp_all_reports(
            agent_team_dir=agent_dir,
            signals=signals,
            config=cfg,
        )
        assert len(touched) == 4
        assert all(v for v in touched.values())

        # Spot check the output shapes.
        audit = json.loads(
            (agent_dir / "AUDIT_REPORT.json").read_text(encoding="utf-8")
        )
        assert "confidence" in audit
        assert "confidence_reasoning" in audit

        build_log = (agent_dir / "BUILD_LOG.txt").read_text(encoding="utf-8")
        assert build_log.startswith("[CONFIDENCE=")

        gate = (agent_dir / "GATE_A_REPORT.md").read_text(encoding="utf-8")
        assert gate.startswith("## Confidence:")

        recovery = (agent_dir / "FINAL_RECOVERY_REPORT.md").read_text(
            encoding="utf-8",
        )
        assert recovery.startswith("## Confidence:")

    def test_flag_off_is_no_op(self, tmp_path: Path) -> None:
        agent_dir = _setup_tree(tmp_path)
        cfg = _config(enabled=False)
        signals = ConfidenceSignals(evidence_mode="soft_gate")
        touched = stamp_all_reports(
            agent_team_dir=agent_dir,
            signals=signals,
            config=cfg,
        )
        assert touched == {}
        audit = json.loads(
            (agent_dir / "AUDIT_REPORT.json").read_text(encoding="utf-8")
        )
        assert "confidence" not in audit

    def test_signals_derived_from_audit_report_healthy(
        self, tmp_path: Path
    ) -> None:
        """Exercise the same fix_loop_converged heuristic as the wiring.

        When the audit report's score.score >= score_healthy_threshold
        the loop is treated as converged; the reasoning string then
        calls out "fix loop converged".
        """
        agent_dir = _setup_tree(tmp_path)
        cfg = _config(enabled=True)
        signals = ConfidenceSignals(
            evidence_mode=str(cfg.v18.evidence_mode),
            fix_loop_converged=True,
            runtime_verification_ran=False,
        )
        stamp_all_reports(
            agent_team_dir=agent_dir,
            signals=signals,
            config=cfg,
        )
        audit = json.loads(
            (agent_dir / "AUDIT_REPORT.json").read_text(encoding="utf-8")
        )
        assert "fix loop converged" in audit["confidence_reasoning"]

    def test_confidence_banners_flag_accessor(self) -> None:
        assert confidence_banners_enabled(_config(enabled=True)) is True
        assert confidence_banners_enabled(_config(enabled=False)) is False
