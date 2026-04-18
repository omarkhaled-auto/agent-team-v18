"""Phase F §7.10 — confidence banner tests.

Covers:
  * Confidence derivation from ConfidenceSignals (CONFIDENT/MEDIUM/LOW)
  * Idempotent stamping of AUDIT_REPORT.json / BUILD_LOG.txt /
    GATE_*_REPORT.md / *_RECOVERY_REPORT.md
  * Flag-off short-circuit returns empty dict
  * Walk behaviour across the agent-team directory tree
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.confidence_banners import (
    CONFIDENCE_CONFIDENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    ConfidenceSignals,
    derive_confidence,
    stamp_all_reports,
    stamp_build_log,
    stamp_json_report,
    stamp_markdown_report,
)


def _config(*, enabled: bool = True) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(confidence_banners_enabled=enabled)
    return cfg


class TestDeriveConfidence:
    def test_soft_gate_all_signals_good(self) -> None:
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            scanners_run=6,
            scanners_total=6,
            fix_loop_converged=True,
            runtime_verification_ran=True,
        )
        label, reasoning = derive_confidence(signals)
        assert label == CONFIDENCE_CONFIDENT
        assert "soft_gate" in reasoning
        assert "6/6" in reasoning

    def test_record_only_drops_to_medium(self) -> None:
        signals = ConfidenceSignals(
            evidence_mode="record_only",
            scanners_run=6,
            scanners_total=6,
            fix_loop_converged=True,
            runtime_verification_ran=True,
        )
        label, _ = derive_confidence(signals)
        assert label == CONFIDENCE_MEDIUM

    def test_disabled_mode_stays_medium(self) -> None:
        signals = ConfidenceSignals(
            evidence_mode="disabled",
            scanners_run=6,
            scanners_total=6,
            fix_loop_converged=True,
            runtime_verification_ran=True,
        )
        label, _ = derive_confidence(signals)
        assert label == CONFIDENCE_MEDIUM

    def test_plateaued_fix_loop_is_low(self) -> None:
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            scanners_run=6,
            scanners_total=6,
            fix_loop_plateaued=True,
            runtime_verification_ran=True,
        )
        label, _ = derive_confidence(signals)
        assert label == CONFIDENCE_LOW

    def test_few_scanners_ran_is_low(self) -> None:
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            scanners_run=1,
            scanners_total=6,
            fix_loop_converged=True,
            runtime_verification_ran=True,
        )
        label, _ = derive_confidence(signals)
        assert label == CONFIDENCE_LOW


class TestStampJsonReport:
    def test_adds_confidence_field(self, tmp_path: Path) -> None:
        path = tmp_path / "AUDIT_REPORT.json"
        path.write_text(
            json.dumps({"score": 92.0, "findings": []}, indent=2), encoding="utf-8",
        )
        modified = stamp_json_report(
            path, label="MEDIUM", reasoning="record_only; 5/6 ran.",
        )
        assert modified is True
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["confidence"] == "MEDIUM"
        assert data["confidence_reasoning"].startswith("record_only")
        assert data["score"] == 92.0  # preserved

    def test_idempotent_same_label(self, tmp_path: Path) -> None:
        path = tmp_path / "AUDIT_REPORT.json"
        path.write_text(
            json.dumps(
                {"confidence": "MEDIUM", "confidence_reasoning": "x."},
                indent=2,
            ),
            encoding="utf-8",
        )
        modified = stamp_json_report(path, label="MEDIUM", reasoning="x.")
        assert modified is False

    def test_updates_existing_on_label_change(self, tmp_path: Path) -> None:
        path = tmp_path / "AUDIT_REPORT.json"
        path.write_text(
            json.dumps({"confidence": "LOW", "confidence_reasoning": "old"}),
            encoding="utf-8",
        )
        modified = stamp_json_report(
            path, label="CONFIDENT", reasoning="new reasoning."
        )
        assert modified is True
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["confidence"] == "CONFIDENT"
        assert data["confidence_reasoning"] == "new reasoning."

    def test_skips_non_object_json(self, tmp_path: Path) -> None:
        path = tmp_path / "ARR.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        modified = stamp_json_report(path, label="MEDIUM", reasoning="x.")
        assert modified is False

    def test_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        modified = stamp_json_report(path, label="MEDIUM", reasoning="x.")
        assert modified is False


class TestStampMarkdownReport:
    def test_prepends_banner_on_new_file(self, tmp_path: Path) -> None:
        path = tmp_path / "GATE_A_REPORT.md"
        path.write_text("# Gate A\n\nOriginal body.\n", encoding="utf-8")
        modified = stamp_markdown_report(
            path, label="MEDIUM", reasoning="evidence_mode=record_only."
        )
        assert modified is True
        content = path.read_text(encoding="utf-8")
        assert content.startswith("## Confidence: MEDIUM")
        assert "**Reasoning:** evidence_mode=record_only." in content
        assert "# Gate A" in content  # body preserved

    def test_idempotent_same_banner(self, tmp_path: Path) -> None:
        path = tmp_path / "GATE_A_REPORT.md"
        path.write_text("# Gate A\n\nBody.\n", encoding="utf-8")
        stamp_markdown_report(path, label="MEDIUM", reasoning="x.")
        # Second call with same inputs → no change.
        modified = stamp_markdown_report(path, label="MEDIUM", reasoning="x.")
        assert modified is False

    def test_upgrades_label_in_place(self, tmp_path: Path) -> None:
        path = tmp_path / "GATE_A_REPORT.md"
        path.write_text("# Gate A\n\nBody.\n", encoding="utf-8")
        stamp_markdown_report(path, label="MEDIUM", reasoning="original.")
        modified = stamp_markdown_report(
            path, label="CONFIDENT", reasoning="upgraded.",
        )
        assert modified is True
        content = path.read_text(encoding="utf-8")
        # Only one banner line.
        assert content.count("## Confidence:") == 1
        assert "CONFIDENT" in content
        assert "upgraded." in content
        assert "original." not in content


class TestStampBuildLog:
    def test_prepends_header_line(self, tmp_path: Path) -> None:
        path = tmp_path / "BUILD_LOG.txt"
        path.write_text("2026-04-17 12:00 build start\n", encoding="utf-8")
        modified = stamp_build_log(
            path, label="CONFIDENT", reasoning="all signals green."
        )
        assert modified is True
        content = path.read_text(encoding="utf-8")
        assert content.startswith("[CONFIDENCE=CONFIDENT]")
        assert "build start" in content

    def test_idempotent_replaces_existing_header(self, tmp_path: Path) -> None:
        path = tmp_path / "BUILD_LOG.txt"
        path.write_text(
            "[CONFIDENCE=MEDIUM] old reasoning.\n"
            "rest of log\n",
            encoding="utf-8",
        )
        modified = stamp_build_log(
            path, label="CONFIDENT", reasoning="new reasoning."
        )
        assert modified is True
        content = path.read_text(encoding="utf-8")
        # Only one CONFIDENCE line.
        assert content.count("[CONFIDENCE=") == 1
        assert "CONFIDENT" in content


class TestStampAllReports:
    def test_flag_off_returns_empty_dict(self, tmp_path: Path) -> None:
        (tmp_path / "AUDIT_REPORT.json").write_text(
            json.dumps({"score": 90}), encoding="utf-8",
        )
        cfg = _config(enabled=False)
        touched = stamp_all_reports(
            agent_team_dir=tmp_path,
            signals=ConfidenceSignals(evidence_mode="soft_gate"),
            config=cfg,
        )
        assert touched == {}

    def test_stamps_all_reports_in_tree(self, tmp_path: Path) -> None:
        (tmp_path / "AUDIT_REPORT.json").write_text(
            json.dumps({"score": 90}), encoding="utf-8",
        )
        (tmp_path / "BUILD_LOG.txt").write_text("log\n", encoding="utf-8")
        (tmp_path / "GATE_A_REPORT.md").write_text("# A\n", encoding="utf-8")
        (tmp_path / "FINAL_RECOVERY_REPORT.md").write_text(
            "# Recovery\n", encoding="utf-8",
        )
        milestone_dir = tmp_path / "milestones" / "milestone-1"
        milestone_dir.mkdir(parents=True)
        (milestone_dir / "AUDIT_REPORT.json").write_text(
            json.dumps({"score": 88}), encoding="utf-8",
        )
        (milestone_dir / "GATE_B_REPORT.md").write_text("# B\n", encoding="utf-8")

        signals = ConfidenceSignals(
            evidence_mode="record_only",
            scanners_run=5,
            scanners_total=6,
            fix_loop_converged=True,
            runtime_verification_ran=True,
        )
        touched = stamp_all_reports(
            agent_team_dir=tmp_path, signals=signals, config=_config(),
        )
        # All six reports were touched.
        assert len(touched) == 6
        assert all(v for v in touched.values())

        # Spot-check formats.
        audit = json.loads(
            (tmp_path / "AUDIT_REPORT.json").read_text(encoding="utf-8"),
        )
        assert audit["confidence"] == CONFIDENCE_MEDIUM

        gate = (tmp_path / "GATE_A_REPORT.md").read_text(encoding="utf-8")
        assert gate.startswith("## Confidence: MEDIUM")

        build_log = (tmp_path / "BUILD_LOG.txt").read_text(encoding="utf-8")
        assert build_log.startswith("[CONFIDENCE=MEDIUM]")
