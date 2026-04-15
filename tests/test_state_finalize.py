"""Tests for ``RunState.finalize`` (D-13).

Validates the reconciliation rules that ``finalize`` applies at end-of-
pipeline: ``summary.success`` derived from ``failed_milestones``,
``audit_health`` sourced from ``AUDIT_REPORT.json``, ``current_wave``
cleared when ``current_phase == "complete"``, ``stack_contract.confidence``
forced to ``"low"`` when the contract struct is empty, and
``gate_results`` loaded from ``GATE_FINDINGS.json`` when present.
Idempotence is covered by test 7.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

from agent_team_v15.state import RunState


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _write_audit_report(agent_team_dir: Path, health: str = "failed", cycle: int = 1) -> Path:
    """Write a minimal scorer-shaped AUDIT_REPORT.json for finalize to read."""
    report = {
        "audit_cycle": cycle,
        "timestamp": "2026-04-15T18:00:00.000Z",
        "score": 0,
        "max_score": 1000,
        "verdict": "FAIL",
        "health": health,
        "findings": [],
    }
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    path = agent_team_dir / "AUDIT_REPORT.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _write_gate_findings(agent_team_dir: Path, findings: list[dict]) -> Path:
    """Write GATE_FINDINGS.json in the real (list-at-root) shape from build-j."""
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    path = agent_team_dir / "GATE_FINDINGS.json"
    path.write_text(json.dumps(findings), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests (plan §4, 7 tests)
# ---------------------------------------------------------------------------

class TestStateFinalize:

    def test_failed_milestone_success_false(self):
        """Plan §4 test 1: a failed milestone makes summary.success False."""
        state = RunState(task="x")
        state.failed_milestones = ["milestone-1"]
        state.finalize()
        assert state.summary["success"] is False

    def test_audit_report_present_populates_health(self, tmp_path):
        """Plan §4 test 2: AUDIT_REPORT.json with health=failed populates
        ``audit_health`` via D-07's permissive AuditReport reader."""
        agent_team_dir = tmp_path / ".agent-team"
        _write_audit_report(agent_team_dir, health="failed")
        state = RunState(task="x")
        state.finalize(agent_team_dir=agent_team_dir)
        assert state.audit_health == "failed"

    def test_current_phase_complete_clears_current_wave(self):
        """Plan §4 test 3: ``current_phase == "complete"`` pops
        ``current_wave`` from every ``wave_progress`` entry."""
        state = RunState(task="x")
        state.current_phase = "complete"
        state.wave_progress = {
            "milestone-1": {"current_wave": "D", "current_phase": "complete"},
            "milestone-2": {"current_wave": "B", "current_phase": "complete"},
        }
        state.finalize()
        for ms_entry in state.wave_progress.values():
            assert "current_wave" not in ms_entry

    def test_empty_stack_contract_confidence_low(self):
        """Plan §4 test 4: empty stack_contract -> confidence="low"."""
        state = RunState(task="x")
        state.stack_contract = {"confidence": "high"}  # caller optimistically high
        state.finalize()
        assert state.stack_contract["confidence"] == "low"

    def test_populated_stack_contract_confidence_preserved(self):
        """Plan §4 test 5: populated stack_contract preserves caller-set
        confidence (finalize does not overwrite a real contract's value)."""
        state = RunState(task="x")
        state.stack_contract = {
            "backend_framework": "nestjs",
            "frontend_framework": "next",
            "confidence": "high",
        }
        state.finalize()
        assert state.stack_contract["confidence"] == "high"

    def test_gate_findings_loaded(self, tmp_path):
        """Plan §4 test 6: GATE_FINDINGS.json contents become
        ``state.gate_results`` (build-j uses list-at-root shape)."""
        agent_team_dir = tmp_path / ".agent-team"
        findings = [
            {
                "gate": "spot_check",
                "check": "E2E-006",
                "message": "Placeholder text in UI component",
                "file_path": "apps/web/src/components/ui/input.tsx",
                "severity": "error",
            },
            {
                "gate": "spot_check",
                "check": "PROJ-001",
                "message": "Missing .gitignore",
                "file_path": ".gitignore",
                "severity": "error",
            },
        ]
        _write_gate_findings(agent_team_dir, findings)
        state = RunState(task="x")
        state.finalize(agent_team_dir=agent_team_dir)
        assert state.gate_results == findings

    def test_finalize_idempotent(self, tmp_path):
        """Plan §4 test 7: calling finalize() twice produces identical
        output. Exercises every reconciliation path (audit, gate, phase
        clear, contract, success) to catch any monotonic drift."""
        agent_team_dir = tmp_path / ".agent-team"
        _write_audit_report(agent_team_dir, health="degraded")
        _write_gate_findings(agent_team_dir, [{"gate": "x", "severity": "warn"}])
        state = RunState(task="x")
        state.failed_milestones = ["milestone-1"]
        state.current_phase = "complete"
        state.wave_progress = {
            "milestone-1": {"current_wave": "D", "current_phase": "complete"}
        }
        state.stack_contract = {"confidence": "high"}  # empty struct -> will flip to low

        state.finalize(agent_team_dir=agent_team_dir)
        snapshot = copy.deepcopy(asdict(state))
        state.finalize(agent_team_dir=agent_team_dir)
        assert asdict(state) == snapshot
