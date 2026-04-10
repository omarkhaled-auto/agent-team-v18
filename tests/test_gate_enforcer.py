"""Tests for Automated Checkpoint Gates (Feature #3)."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from agent_team_v15.gate_enforcer import (
    GateEnforcer,
    GateMode,
    GateResult,
    GateViolationError,
)
from agent_team_v15.config import AgentTeamConfig, ConvergenceConfig
from agent_team_v15.state import RunState, save_state, load_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_enforcer(
    tmp_path: Path,
    gates_enabled: bool = True,
    min_convergence_ratio: float = 0.9,
) -> GateEnforcer:
    """Create a GateEnforcer rooted at tmp_path/.agent-team."""
    config = AgentTeamConfig()
    config.convergence = ConvergenceConfig(
        requirements_dir=".agent-team",
        requirements_file="REQUIREMENTS.md",
        min_convergence_ratio=min_convergence_ratio,
    )
    state = RunState()
    return GateEnforcer(config, state, tmp_path, gates_enabled=gates_enabled)


def _write_requirements(tmp_path: Path, content: str) -> Path:
    """Write REQUIREMENTS.md inside tmp_path/.agent-team/."""
    req_dir = tmp_path / ".agent-team"
    req_dir.mkdir(parents=True, exist_ok=True)
    req_path = req_dir / "REQUIREMENTS.md"
    req_path.write_text(content, encoding="utf-8")
    return req_path


# ---------------------------------------------------------------------------
# GateResult and GateViolationError basics
# ---------------------------------------------------------------------------

class TestGateResultBasics:
    def test_create_with_all_fields(self):
        result = GateResult(
            gate_id="GATE_TEST",
            gate_name="Test Gate",
            passed=True,
            reason="All checks passed",
            details={"key": "value"},
        )
        assert result.gate_id == "GATE_TEST"
        assert result.gate_name == "Test Gate"
        assert result.passed is True
        assert result.reason == "All checks passed"
        assert result.details == {"key": "value"}
        assert result.timestamp != ""

    def test_auto_timestamp(self):
        r1 = GateResult(gate_id="G1", gate_name="G", passed=True, reason="ok")
        assert r1.timestamp != ""
        assert "T" in r1.timestamp  # ISO 8601 format

    def test_explicit_timestamp_preserved(self):
        result = GateResult(
            gate_id="G1", gate_name="G", passed=True, reason="ok",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert result.timestamp == "2026-01-01T00:00:00+00:00"


class TestGateViolationError:
    def test_is_exception_subclass(self):
        assert issubclass(GateViolationError, Exception)

    def test_message_format(self):
        err = GateViolationError("GATE_REQUIREMENTS FAILED: file missing")
        assert "GATE_REQUIREMENTS" in str(err)
        assert "file missing" in str(err)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(GateViolationError, match="GATE_TEST"):
            raise GateViolationError("GATE_TEST FAILED: reason")


# ---------------------------------------------------------------------------
# GateEnforcer initialization
# ---------------------------------------------------------------------------

class TestGateEnforcerInit:
    def test_creates_with_valid_config_and_state(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=True)
        assert enforcer._mode == GateMode.ENFORCING

    def test_default_mode_informational_when_disabled(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        assert enforcer._mode == GateMode.INFORMATIONAL

    def test_mode_enforcing_when_enabled(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=True)
        assert enforcer._mode == GateMode.ENFORCING

    def test_empty_audit_trail_on_init(self, tmp_path):
        enforcer = _make_enforcer(tmp_path)
        assert enforcer.get_gate_audit_trail() == []


# ---------------------------------------------------------------------------
# GATE_REQUIREMENTS
# ---------------------------------------------------------------------------

class TestGateRequirements:
    def test_passes_when_file_exists_with_req_item(self, tmp_path):
        _write_requirements(tmp_path, "- [ ] REQ-001 Some requirement\n")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_requirements_exist()
        assert result.passed is True
        assert result.gate_id == "GATE_REQUIREMENTS"

    def test_passes_with_checked_req_item(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Done\n- [ ] TECH-002 Pending\n")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_requirements_exist()
        assert result.passed is True
        assert result.details["item_count"] == 2

    def test_fails_when_file_missing(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        result = enforcer.enforce_requirements_exist()
        assert result.passed is False
        assert "not found" in result.reason

    def test_fails_when_file_empty_zero_items(self, tmp_path):
        _write_requirements(tmp_path, "# Requirements\nNo items here.\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        result = enforcer.enforce_requirements_exist()
        assert result.passed is False
        assert "0 requirement items" in result.reason

    def test_informational_mode_logs_but_no_raise(self, tmp_path):
        # No REQUIREMENTS.md => fails, but informational mode should not raise
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        result = enforcer.enforce_requirements_exist()
        assert result.passed is False
        # No exception raised — test passes if we reach here

    def test_enforcing_mode_raises_on_failure(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=True)
        with pytest.raises(GateViolationError, match="GATE_REQUIREMENTS"):
            enforcer.enforce_requirements_exist()

    def test_recognizes_multiple_prefixes(self, tmp_path):
        content = (
            "- [ ] TECH-001 Tech item\n"
            "- [ ] INT-001 Integration item\n"
            "- [ ] WIRE-001 Wireframe item\n"
            "- [ ] SVC-001 Service item\n"
            "- [ ] DESIGN-001 Design item\n"
        )
        _write_requirements(tmp_path, content)
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_requirements_exist()
        assert result.passed is True
        assert result.details["item_count"] == 5


# ---------------------------------------------------------------------------
# GATE_ARCHITECTURE
# ---------------------------------------------------------------------------

class TestGateArchitecture:
    def test_passes_with_architecture_decision_heading(self, tmp_path):
        _write_requirements(tmp_path, "## Architecture Decision\nSome content\n")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_architecture_exists()
        assert result.passed is True
        assert result.details["has_architecture_decision"] is True

    def test_fails_without_architecture_section(self, tmp_path):
        _write_requirements(tmp_path, "# Requirements\n- [ ] REQ-001 stuff\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        result = enforcer.enforce_architecture_exists()
        assert result.passed is False
        assert "No Architecture Decision" in result.reason

    def test_passes_with_integration_roadmap(self, tmp_path):
        _write_requirements(tmp_path, "## Integration Roadmap\nSome roadmap\n")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_architecture_exists()
        assert result.passed is True
        assert result.details["has_integration_roadmap"] is True

    def test_fails_when_file_missing(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        result = enforcer.enforce_architecture_exists()
        assert result.passed is False
        assert "not found" in result.reason

    def test_enforcing_raises_on_failure(self, tmp_path):
        _write_requirements(tmp_path, "# No arch section\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=True)
        with pytest.raises(GateViolationError, match="GATE_ARCHITECTURE"):
            enforcer.enforce_architecture_exists()


# ---------------------------------------------------------------------------
# GATE_CONVERGENCE
# ---------------------------------------------------------------------------

class TestGateConvergence:
    def test_passes_above_threshold(self, tmp_path):
        # 19/20 = 95% checked, threshold 0.9
        lines = ["- [x] REQ-%03d item\n" % i for i in range(1, 20)]
        lines.append("- [ ] REQ-020 item\n")
        _write_requirements(tmp_path, "".join(lines))
        enforcer = _make_enforcer(tmp_path, min_convergence_ratio=0.9)
        result = enforcer.enforce_convergence_threshold()
        assert result.passed is True
        assert result.details["ratio"] >= 0.9

    def test_fails_below_threshold(self, tmp_path):
        # 5/10 = 50% checked, threshold 0.9
        lines = ["- [x] REQ-%03d item\n" % i for i in range(1, 6)]
        lines += ["- [ ] REQ-%03d item\n" % i for i in range(6, 11)]
        _write_requirements(tmp_path, "".join(lines))
        enforcer = _make_enforcer(tmp_path, gates_enabled=False, min_convergence_ratio=0.9)
        result = enforcer.enforce_convergence_threshold()
        assert result.passed is False
        assert result.details["ratio"] == 0.5

    def test_zero_items_vacuously_true(self, tmp_path):
        _write_requirements(tmp_path, "# Empty requirements doc\n")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_convergence_threshold()
        assert result.passed is True
        assert "vacuously true" in result.reason

    def test_uses_min_convergence_ratio_from_config(self, tmp_path):
        # 7/10 = 70%, threshold set to 0.6 — should pass
        lines = ["- [x] REQ-%03d item\n" % i for i in range(1, 8)]
        lines += ["- [ ] REQ-%03d item\n" % i for i in range(8, 11)]
        _write_requirements(tmp_path, "".join(lines))
        enforcer = _make_enforcer(tmp_path, min_convergence_ratio=0.6)
        result = enforcer.enforce_convergence_threshold()
        assert result.passed is True

    def test_enforcing_raises_on_failure(self, tmp_path):
        lines = ["- [ ] REQ-%03d item\n" % i for i in range(1, 11)]
        _write_requirements(tmp_path, "".join(lines))
        enforcer = _make_enforcer(tmp_path, gates_enabled=True, min_convergence_ratio=0.9)
        with pytest.raises(GateViolationError, match="GATE_CONVERGENCE"):
            enforcer.enforce_convergence_threshold()


# ---------------------------------------------------------------------------
# GATE_E2E
# ---------------------------------------------------------------------------

class TestGateE2E:
    def test_passes_when_health_passed(self, tmp_path):
        config = AgentTeamConfig()
        state = RunState(endpoint_test_report={
            "health": "passed",
            "tested_endpoints": 10,
            "passed_endpoints": 10,
        })
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=True)
        result = enforcer.enforce_e2e_pass()
        assert result.passed is True

    def test_fails_when_health_failed(self, tmp_path):
        config = AgentTeamConfig()
        state = RunState(endpoint_test_report={
            "health": "failed",
            "tested_endpoints": 10,
            "passed_endpoints": 5,
        })
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)
        result = enforcer.enforce_e2e_pass()
        assert result.passed is False

    def test_fails_when_no_report(self, tmp_path):
        config = AgentTeamConfig()
        state = RunState()  # no endpoint_test_report
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)
        result = enforcer.enforce_e2e_pass()
        assert result.passed is False
        assert "No E2E test report" in result.reason

    def test_enforcing_raises_on_failure(self, tmp_path):
        config = AgentTeamConfig()
        state = RunState(endpoint_test_report={
            "health": "failed",
            "tested_endpoints": 5,
            "passed_endpoints": 2,
        })
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=True)
        with pytest.raises(GateViolationError, match="GATE_E2E"):
            enforcer.enforce_e2e_pass()


# ---------------------------------------------------------------------------
# GATE_PSEUDOCODE and GATE_TRUTH_SCORE (force_informational)
# ---------------------------------------------------------------------------

class TestGatePseudocode:
    def test_force_informational_never_raises(self, tmp_path):
        """GATE_PSEUDOCODE uses force_informational — should never raise even in enforcing mode."""
        enforcer = _make_enforcer(tmp_path, gates_enabled=True)
        # No pseudocode dir or file — fails but force_informational
        result = enforcer.enforce_pseudocode_exists()
        assert result.passed is False
        # Should NOT raise — test passes if we reach here

    def test_passes_with_pseudocode_directory(self, tmp_path):
        pseudo_dir = tmp_path / ".agent-team" / "pseudocode"
        pseudo_dir.mkdir(parents=True)
        (pseudo_dir / "PSEUDO_TASK-001.md").write_text("pseudocode here")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_pseudocode_exists()
        assert result.passed is True

    def test_passes_with_pseudocode_file(self, tmp_path):
        req_dir = tmp_path / ".agent-team"
        req_dir.mkdir(parents=True)
        (req_dir / "PSEUDOCODE.md").write_text("# Pseudocode\n")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_pseudocode_exists()
        assert result.passed is True


class TestGateTruthScore:
    def test_force_informational_never_raises_when_missing(self, tmp_path):
        """GATE_TRUTH_SCORE uses force_informational when file missing."""
        enforcer = _make_enforcer(tmp_path, gates_enabled=True)
        result = enforcer.enforce_truth_score()
        assert result.passed is False
        # Should NOT raise — test passes if we reach here

    def test_passes_when_all_scores_above_threshold(self, tmp_path):
        req_dir = tmp_path / ".agent-team"
        req_dir.mkdir(parents=True)
        scores_data = {"scores": [{"score": 0.98}, {"score": 0.96}]}
        (req_dir / "TRUTH_SCORES.json").write_text(json.dumps(scores_data))
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_truth_score(min_score=0.95)
        assert result.passed is True

    def test_fails_when_score_below_threshold(self, tmp_path):
        req_dir = tmp_path / ".agent-team"
        req_dir.mkdir(parents=True)
        scores_data = {"scores": [{"score": 0.98}, {"score": 0.80}]}
        (req_dir / "TRUTH_SCORES.json").write_text(json.dumps(scores_data))
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        result = enforcer.enforce_truth_score(min_score=0.95)
        assert result.passed is False

    def test_vacuously_true_with_empty_scores(self, tmp_path):
        req_dir = tmp_path / ".agent-team"
        req_dir.mkdir(parents=True)
        (req_dir / "TRUTH_SCORES.json").write_text(json.dumps({"scores": []}))
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_truth_score()
        assert result.passed is True


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

class TestAuditTrail:
    def test_get_gate_audit_trail_returns_list(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        trail = enforcer.get_gate_audit_trail()
        assert isinstance(trail, list)
        assert len(trail) == 0

    def test_each_check_adds_to_trail(self, tmp_path):
        _write_requirements(tmp_path, "- [ ] REQ-001 item\n## Architecture Decision\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()
        enforcer.enforce_architecture_exists()
        trail = enforcer.get_gate_audit_trail()
        assert len(trail) == 2
        assert trail[0].gate_id == "GATE_REQUIREMENTS"
        assert trail[1].gate_id == "GATE_ARCHITECTURE"

    def test_trail_contains_gate_results(self, tmp_path):
        _write_requirements(tmp_path, "- [ ] REQ-001 item\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()
        trail = enforcer.get_gate_audit_trail()
        assert all(isinstance(r, GateResult) for r in trail)

    def test_audit_log_file_written(self, tmp_path):
        _write_requirements(tmp_path, "- [ ] REQ-001 item\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()
        log_path = tmp_path / ".agent-team" / "GATE_AUDIT.log"
        assert log_path.is_file()
        content = log_path.read_text(encoding="utf-8")
        assert "GATE_REQUIREMENTS" in content
        assert "PASS" in content

    def test_audit_log_appends_multiple_entries(self, tmp_path):
        _write_requirements(tmp_path, "- [ ] REQ-001 item\n## Architecture Decision\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()
        enforcer.enforce_architecture_exists()
        log_path = tmp_path / ".agent-team" / "GATE_AUDIT.log"
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_trail_is_copy_not_reference(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        trail = enforcer.get_gate_audit_trail()
        trail.append(GateResult(gate_id="FAKE", gate_name="F", passed=True, reason="x"))
        assert len(enforcer.get_gate_audit_trail()) == 0


# ---------------------------------------------------------------------------
# State integration
# ---------------------------------------------------------------------------

class TestStateIntegration:
    def test_gate_results_populated_in_state(self, tmp_path):
        _write_requirements(tmp_path, "- [ ] REQ-001 item\n")
        config = AgentTeamConfig()
        state = RunState()
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()
        assert len(state.gate_results) == 1
        assert state.gate_results[0]["gate_id"] == "GATE_REQUIREMENTS"
        assert state.gate_results[0]["passed"] is True

    def test_gates_passed_counter_increments(self, tmp_path):
        _write_requirements(tmp_path, "- [ ] REQ-001 item\n## Architecture Decision\n")
        config = AgentTeamConfig()
        state = RunState()
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()
        enforcer.enforce_architecture_exists()
        assert state.gates_passed == 2

    def test_gates_failed_counter_increments(self, tmp_path):
        config = AgentTeamConfig()
        state = RunState()
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()  # fails — no file
        assert state.gates_failed == 1

    def test_mixed_pass_fail_counters(self, tmp_path):
        _write_requirements(tmp_path, "- [ ] REQ-001 item\n")  # No arch section
        config = AgentTeamConfig()
        state = RunState()
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()    # passes
        enforcer.enforce_architecture_exists()   # fails
        assert state.gates_passed == 1
        assert state.gates_failed == 1
        assert len(state.gate_results) == 2


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_old_state_json_without_gate_fields_loads(self, tmp_path):
        """State JSON from before Feature #3 should load with default gate fields."""
        state_file = tmp_path / "STATE.json"
        old_data = {"run_id": "test123", "task": "test", "schema_version": 2}
        state_file.write_text(json.dumps(old_data))
        loaded = load_state(directory=str(tmp_path))
        assert loaded is not None
        assert loaded.gate_results == []
        assert loaded.gates_passed == 0
        assert loaded.gates_failed == 0

    def test_gates_disabled_never_raises(self, tmp_path):
        """When gates_enabled=False, no exceptions should ever be raised."""
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        # All of these should fail but never raise
        enforcer.enforce_requirements_exist()
        enforcer.enforce_architecture_exists()
        enforcer.enforce_convergence_threshold()
        enforcer.enforce_pseudocode_exists()
        enforcer.enforce_truth_score()
        # E2E needs state with no report
        config = AgentTeamConfig()
        state = RunState()
        e2e_enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)
        e2e_enforcer.enforce_e2e_pass()
        # If we reach here, no exception was raised

    def test_state_roundtrip_with_gate_fields(self, tmp_path):
        state = RunState(
            gate_results=[{"gate_id": "GATE_TEST", "passed": True, "reason": "ok", "timestamp": "t"}],
            gates_passed=1,
            gates_failed=0,
        )
        save_state(state, directory=str(tmp_path))
        loaded = load_state(directory=str(tmp_path))
        assert loaded is not None
        assert len(loaded.gate_results) == 1
        assert loaded.gates_passed == 1
        assert loaded.gates_failed == 0
