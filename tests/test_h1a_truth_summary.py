"""Phase H1a Item 7 — TRUTH summary BUILD_LOG panel.

The ``_format_truth_summary_block`` helper emits the 3-line panel:

    TRUTH SCORE: <overall>
    GATE: <gate> (threshold 0.95 PASS / 0.80 RETRY / below ESCALATE)
    PER-DIMENSION: <dim=value, dim=value, ...>

When TRUTH_SCORES.json is missing or unreadable, falls back to the
in-memory ``TruthScore`` object when supplied, otherwise emits a
``TRUTH SCORE: not_computed`` block.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.cli import _format_truth_summary_block


def _write_truth(path: Path, overall: float, gate: str, dims: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "overall": overall,
        "gate": gate,
        "passed": gate == "pass",
        "dimensions": dims,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_disk_truth_score_with_escalate_gate(tmp_path: Path) -> None:
    path = tmp_path / "TRUTH_SCORES.json"
    dims = {
        "requirements": 0.9,
        "contracts": 0.8,
        "evidence": 0.7,
        "routing": 0.85,
        "recovery": 0.6,
        "quality": 0.5,
    }
    _write_truth(path, overall=0.548, gate="escalate", dims=dims)
    lines = _format_truth_summary_block(path)

    assert any(l.startswith("TRUTH SCORE:") and "0.548" in l for l in lines)
    assert any(l.startswith("GATE: ESCALATE") for l in lines)
    per = next(l for l in lines if l.startswith("PER-DIMENSION:"))
    # All 6 dimensions formatted with 2-decimal precision.
    for name in dims:
        assert f"{name}=" in per


def test_disk_missing_emits_not_computed(tmp_path: Path) -> None:
    path = tmp_path / "missing-TRUTH_SCORES.json"
    lines = _format_truth_summary_block(path)
    assert any(l == "TRUTH SCORE: not_computed" for l in lines)
    assert any(l.startswith("GATE: not_computed") for l in lines)


def test_disk_missing_falls_back_to_in_memory_score(tmp_path: Path) -> None:
    path = tmp_path / "missing-TRUTH_SCORES.json"
    fallback = SimpleNamespace(
        overall=0.72,
        gate="retry",
        passed=False,
        dimensions={"requirements": 0.8, "evidence": 0.6},
    )
    lines = _format_truth_summary_block(path, fallback_score=fallback)
    assert any("0.720" in l for l in lines)
    assert any(l.startswith("GATE: RETRY") for l in lines)
    per = next(l for l in lines if l.startswith("PER-DIMENSION:"))
    assert "requirements=0.80" in per
    assert "evidence=0.60" in per


def test_pass_gate_threshold_note_present(tmp_path: Path) -> None:
    path = tmp_path / "TRUTH_SCORES.json"
    _write_truth(path, overall=0.98, gate="pass", dims={"requirements": 1.0})
    lines = _format_truth_summary_block(path)
    gate_line = next(l for l in lines if l.startswith("GATE:"))
    assert "PASS" in gate_line
    assert "0.95" in gate_line  # threshold note visible


def test_all_six_canonical_dimensions_displayed(tmp_path: Path) -> None:
    path = tmp_path / "TRUTH_SCORES.json"
    dims = {
        "requirements": 0.91,
        "contracts": 0.82,
        "evidence": 0.73,
        "routing": 0.84,
        "recovery": 0.65,
        "quality": 0.56,
    }
    _write_truth(path, overall=0.75, gate="retry", dims=dims)
    lines = _format_truth_summary_block(path)
    per = next(l for l in lines if l.startswith("PER-DIMENSION:"))
    assert "requirements=0.91" in per
    assert "contracts=0.82" in per
    assert "evidence=0.73" in per
    assert "routing=0.84" in per
    assert "recovery=0.65" in per
    assert "quality=0.56" in per


def test_malformed_json_falls_back_to_not_computed(tmp_path: Path) -> None:
    path = tmp_path / "TRUTH_SCORES.json"
    path.write_text("{not valid json", encoding="utf-8")
    lines = _format_truth_summary_block(path)
    assert any(l == "TRUTH SCORE: not_computed" for l in lines)


def test_no_dimensions_reported_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "TRUTH_SCORES.json"
    _write_truth(path, overall=0.5, gate="escalate", dims={})
    lines = _format_truth_summary_block(path)
    per = next(l for l in lines if l.startswith("PER-DIMENSION:"))
    assert "no dimensions recorded" in per
