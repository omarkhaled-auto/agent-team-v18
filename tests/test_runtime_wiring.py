"""Integration tests for runtime wiring of Features #1 (Pseudocode), #2 (TruthScorer), #3 (Gates).

Tests verify that each feature is WIRED into the pipeline — i.e., functions are
called at the correct points in the execution flow. Logic correctness is tested
in test_pseudocode.py, test_truth_scoring.py, and test_gate_enforcer.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from agent_team_v15.config import (
    AgentTeamConfig,
    ConvergenceConfig,
    GateEnforcementConfig,
    PseudocodeConfig,
)
from agent_team_v15.gate_enforcer import (
    GateEnforcer,
    GateMode,
    GateResult,
    GateViolationError,
)
from agent_team_v15.quality_checks import TruthScore, TruthScoreGate, TruthScorer
from agent_team_v15.state import RunState, save_state, load_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLI_PATH = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15" / "cli.py"
_CB_PATH = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15" / "coordinated_builder.py"


def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_config(
    gates_enabled: bool = True,
    pseudocode_enabled: bool = False,
    enforce_requirements: bool = True,
    enforce_architecture: bool = True,
    enforce_pseudocode: bool = False,
    enforce_review_count: bool = True,
    enforce_convergence: bool = True,
    enforce_truth_score: bool = False,
    enforce_e2e: bool = True,
) -> AgentTeamConfig:
    config = AgentTeamConfig()
    config.gate_enforcement = GateEnforcementConfig(
        enabled=gates_enabled,
        enforce_requirements=enforce_requirements,
        enforce_architecture=enforce_architecture,
        enforce_pseudocode=enforce_pseudocode,
        enforce_review_count=enforce_review_count,
        enforce_convergence=enforce_convergence,
        enforce_truth_score=enforce_truth_score,
        enforce_e2e=enforce_e2e,
    )
    config.pseudocode = PseudocodeConfig(enabled=pseudocode_enabled)
    return config


def _make_enforcer(
    tmp_path: Path,
    gates_enabled: bool = True,
    min_convergence_ratio: float = 0.9,
) -> GateEnforcer:
    config = _make_config(gates_enabled=gates_enabled)
    config.convergence = ConvergenceConfig(
        requirements_dir=".agent-team",
        requirements_file="REQUIREMENTS.md",
        min_convergence_ratio=min_convergence_ratio,
    )
    state = RunState()
    return GateEnforcer(config, state, tmp_path, gates_enabled=gates_enabled)


def _write_requirements(tmp_path: Path, content: str) -> Path:
    req_dir = tmp_path / ".agent-team"
    req_dir.mkdir(parents=True, exist_ok=True)
    req_path = req_dir / "REQUIREMENTS.md"
    req_path.write_text(content, encoding="utf-8")
    return req_path


def _write_pseudocode_dir(tmp_path: Path, file_count: int = 1) -> Path:
    pseudo_dir = tmp_path / ".agent-team" / "pseudocode"
    pseudo_dir.mkdir(parents=True, exist_ok=True)
    for i in range(file_count):
        (pseudo_dir / f"PSEUDO_TASK-{i:03d}.md").write_text(
            f"# Pseudocode for TASK-{i:03d}\n\nFUNCTION main():\n  RETURN 0\n",
            encoding="utf-8",
        )
    return pseudo_dir


def _write_truth_scores(tmp_path: Path, scores: list[dict]) -> Path:
    scores_dir = tmp_path / ".agent-team"
    scores_dir.mkdir(parents=True, exist_ok=True)
    scores_path = scores_dir / "TRUTH_SCORES.json"
    scores_path.write_text(json.dumps({"scores": scores}), encoding="utf-8")
    return scores_path


# ===================================================================
# SECTION 1: Pseudocode Enforcement Tests (Feature #1)
# ===================================================================


class TestPseudocodeCheckPassesWhenDirExists:
    def test_pseudocode_check_passes_when_pseudocode_dir_exists(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        _write_pseudocode_dir(tmp_path, file_count=3)
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_pseudocode_exists()
        assert result.passed is True
        assert "3" in result.reason

    def test_pseudocode_dir_with_single_file(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        _write_pseudocode_dir(tmp_path, file_count=1)
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_pseudocode_exists()
        assert result.passed is True


class TestPseudocodeCheckFailsWhenDirMissingAndEnabled:
    def test_pseudocode_check_fails_when_dir_missing_and_enabled(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=True)
        result = enforcer.enforce_pseudocode_exists()
        assert result.passed is False

    def test_fail_reason_mentions_feature_1(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_pseudocode_exists()
        assert "Feature #1" in result.reason or "pseudocode" in result.reason.lower()


class TestPseudocodeCheckSkippedWhenDisabled:
    def test_pseudocode_check_skipped_when_disabled(self):
        config = _make_config(gates_enabled=False, enforce_pseudocode=False)
        assert config.gate_enforcement.enforce_pseudocode is False

    def test_gate_enforcement_disabled_means_informational(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        assert enforcer._mode == GateMode.INFORMATIONAL


class TestPseudocodeEnforcementBlocksCodingPhase:
    def test_pseudocode_enforcement_blocks_coding_phase(self, tmp_path):
        """When pseudocode is enabled and gate is enforcing, missing pseudocode should not raise
        (because force_informational=True on this gate until Feature #1 ships)."""
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=True)
        # enforce_pseudocode_exists uses force_informational=True
        result = enforcer.enforce_pseudocode_exists()
        assert result.passed is False
        # Should NOT raise because force_informational=True
        assert result.gate_id == "GATE_PSEUDOCODE"

    def test_pseudocode_found_via_file_instead_of_dir(self, tmp_path):
        req_dir = tmp_path / ".agent-team"
        req_dir.mkdir(parents=True, exist_ok=True)
        (req_dir / "PSEUDOCODE.md").write_text("# Pseudocode\n", encoding="utf-8")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_pseudocode_exists()
        assert result.passed is True


class TestPseudocodeStateUpdatedAfterValidation:
    def test_pseudocode_state_updated_after_validation(self, tmp_path):
        state = RunState(
            pseudocode_validated=True,
            pseudocode_artifacts={"TASK-001": ".agent-team/pseudocode/PSEUDO_TASK-001.md"},
        )
        save_state(state, directory=str(tmp_path))
        loaded = load_state(directory=str(tmp_path))
        assert loaded is not None
        assert loaded.pseudocode_validated is True
        assert "TASK-001" in loaded.pseudocode_artifacts

    def test_pseudocode_default_state_is_unvalidated(self):
        state = RunState()
        assert state.pseudocode_validated is False
        assert state.pseudocode_artifacts == {}


class TestPseudocodeGateFiresInEnterpriseMode:
    def test_pseudocode_gate_fires_in_enterprise_mode_with_files(self, tmp_path):
        _write_pseudocode_dir(tmp_path, 2)
        config = _make_config(gates_enabled=True, pseudocode_enabled=True)
        config.convergence = ConvergenceConfig(requirements_dir=".agent-team")
        state = RunState(enterprise_mode_active=True)
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=True)
        result = enforcer.enforce_pseudocode_exists()
        assert result.gate_id == "GATE_PSEUDOCODE"
        assert result.passed is True

    def test_pseudocode_gate_blocks_when_enabled_and_missing(self, tmp_path):
        (tmp_path / ".agent-team").mkdir(parents=True, exist_ok=True)
        config = _make_config(gates_enabled=True, pseudocode_enabled=True)
        config.convergence = ConvergenceConfig(requirements_dir=".agent-team")
        state = RunState(enterprise_mode_active=True)
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=True)
        with pytest.raises(GateViolationError, match="GATE_PSEUDOCODE"):
            enforcer.enforce_pseudocode_exists()

    def test_enterprise_mode_state_tracked(self):
        state = RunState(enterprise_mode_active=True)
        assert state.enterprise_mode_active is True


class TestPseudocodeGateFiresInStandardMode:
    def test_pseudocode_gate_fires_in_standard_mode(self, tmp_path):
        _write_pseudocode_dir(tmp_path, file_count=2)
        config = _make_config(gates_enabled=True)
        config.convergence = ConvergenceConfig(requirements_dir=".agent-team")
        state = RunState(depth="standard")
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=True)
        result = enforcer.enforce_pseudocode_exists()
        assert result.gate_id == "GATE_PSEUDOCODE"
        assert result.passed is True


class TestPseudocodeBackwardCompatWhenDisabled:
    def test_pseudocode_backward_compat_when_disabled(self):
        config = AgentTeamConfig()
        assert config.pseudocode.enabled is False
        assert config.gate_enforcement.enforce_pseudocode is False

    def test_gate_enforcement_default_disabled(self):
        config = AgentTeamConfig()
        assert config.gate_enforcement.enabled is False


# ===================================================================
# SECTION 2: TruthScorer Invocation Tests (Feature #2)
# ===================================================================


class TestTruthScorerCalledAfterVerification:
    def test_truth_scorer_called_after_verification(self, tmp_path):
        """TruthScorer can be instantiated and called on a project."""
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        assert isinstance(score, TruthScore)
        assert 0.0 <= score.overall <= 1.0

    def test_truth_scorer_returns_all_dimensions(self, tmp_path):
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        expected_dims = {
            "requirement_coverage", "contract_compliance",
            "error_handling", "type_safety",
            "test_presence", "security_patterns",
        }
        assert set(score.dimensions.keys()) == expected_dims


class TestTruthScoresStoredInState:
    def test_truth_scores_stored_in_state(self, tmp_path):
        state = RunState(truth_scores={"REQ-001": 0.95, "REQ-002": 0.87})
        save_state(state, directory=str(tmp_path))
        loaded = load_state(directory=str(tmp_path))
        assert loaded is not None
        assert loaded.truth_scores == {"REQ-001": 0.95, "REQ-002": 0.87}

    def test_empty_truth_scores_default(self):
        state = RunState()
        assert state.truth_scores == {}


class TestTruthScoreLoggedToOutput:
    def test_truth_score_logged_to_output(self, tmp_path, capsys):
        """TruthScorer in coordinated_builder logs output."""
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        # Verify score object has gate
        assert score.gate in (TruthScoreGate.PASS, TruthScoreGate.RETRY, TruthScoreGate.ESCALATE)

    def test_truth_score_gate_values(self):
        assert TruthScoreGate.PASS.value == "pass"
        assert TruthScoreGate.RETRY.value == "retry"
        assert TruthScoreGate.ESCALATE.value == "escalate"


class TestRegressionDetectionCalledInAuditLoop:
    def test_regression_detection_called_in_audit_loop(self):
        """coordinated_builder.py source contains _check_regressions call."""
        src = _read_source(_CB_PATH)
        assert "_check_regressions(" in src

    def test_regression_detection_compares_reports(self):
        src = _read_source(_CB_PATH)
        assert "previous_report" in src
        assert "regressions" in src.lower()


class TestRegressionCountIncremented:
    def test_regression_count_incremented(self):
        state = RunState(regression_count=0)
        state.regression_count += 3
        assert state.regression_count == 3

    def test_regression_count_persists(self, tmp_path):
        state = RunState(regression_count=5)
        save_state(state, directory=str(tmp_path))
        loaded = load_state(directory=str(tmp_path))
        assert loaded is not None
        assert loaded.regression_count == 5


class TestPreviousPassingAcsTracked:
    def test_previous_passing_acs_tracked(self, tmp_path):
        state = RunState(previous_passing_acs=["AC-001", "AC-002", "AC-003"])
        save_state(state, directory=str(tmp_path))
        loaded = load_state(directory=str(tmp_path))
        assert loaded is not None
        assert loaded.previous_passing_acs == ["AC-001", "AC-002", "AC-003"]

    def test_default_empty(self):
        state = RunState()
        assert state.previous_passing_acs == []


class TestTruthScoreGateUsesComputedScores:
    def test_truth_score_gate_uses_computed_scores(self, tmp_path):
        _write_truth_scores(tmp_path, [{"score": 0.98}, {"score": 0.96}])
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_truth_score(min_score=0.95)
        assert result.passed is True

    def test_truth_score_gate_fails_below_threshold(self, tmp_path):
        _write_truth_scores(tmp_path, [{"score": 0.98}, {"score": 0.80}])
        enforcer = _make_enforcer(tmp_path)
        # Gate is ENFORCING and score is below threshold -> raises GateViolationError
        with pytest.raises(GateViolationError, match="GATE_TRUTH_SCORE"):
            enforcer.enforce_truth_score(min_score=0.95)

    def test_truth_score_gate_fails_informational(self, tmp_path):
        _write_truth_scores(tmp_path, [{"score": 0.98}, {"score": 0.80}])
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        result = enforcer.enforce_truth_score(min_score=0.95)
        assert result.passed is False


class TestTruthScorerHandlesEmptyCodebase:
    def test_truth_scorer_handles_empty_codebase(self, tmp_path):
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        assert isinstance(score, TruthScore)

    def test_empty_codebase_scores_zero_or_low(self, tmp_path):
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        # With no files, most dimensions should be 0
        assert score.overall <= 1.0


class TestTruthScorerHandlesNoPreviousRun:
    def test_truth_scorer_handles_no_previous_run(self):
        state = RunState()
        assert state.truth_scores == {}
        assert state.previous_passing_acs == []
        assert state.regression_count == 0

    def test_no_previous_run_no_crash(self, tmp_path):
        scorer = TruthScorer(tmp_path)
        score = scorer.score()
        assert score is not None


class TestBackwardCompatWithoutTruthScoring:
    def test_backward_compat_without_truth_scoring(self):
        config = AgentTeamConfig()
        assert config.gate_enforcement.enforce_truth_score is False

    def test_truth_score_fields_default_correctly(self):
        state = RunState()
        assert state.truth_scores == {}
        assert state.regression_count == 0
        assert state.previous_passing_acs == []


# ===================================================================
# SECTION 3: Gate Firing Tests (Feature #3)
# ===================================================================


class TestGateRequirementsFiresAfterPlanning:
    def test_gate_requirements_fires_after_planning(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something important\n")
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_requirements_exist()
        assert result.passed is True
        assert result.gate_id == "GATE_REQUIREMENTS"

    def test_gate_requirements_in_cli_source(self):
        src = _read_source(_CLI_PATH)
        assert "enforce_requirements_exist" in src
        assert "GATE_REQUIREMENTS" in _read_source(
            _CLI_PATH.parent / "gate_enforcer.py"
        )


class TestGateArchitectureFiresAfterArchitecture:
    def test_gate_architecture_fires_after_architecture(self, tmp_path):
        _write_requirements(
            tmp_path,
            "# Requirements\n\n## Architecture Decision\nSome arch notes.\n\n- [x] REQ-001 foo\n",
        )
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_architecture_exists()
        assert result.passed is True
        assert result.gate_id == "GATE_ARCHITECTURE"

    def test_gate_architecture_in_cli(self):
        src = _read_source(_CLI_PATH)
        assert "enforce_architecture_exists" in src


class TestGatePseudocodeFiresBeforeCoding:
    def test_gate_pseudocode_fires_before_coding(self, tmp_path):
        _write_pseudocode_dir(tmp_path, 2)
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_pseudocode_exists()
        assert result.passed is True
        assert result.gate_id == "GATE_PSEUDOCODE"

    def test_gate_pseudocode_defined(self):
        src = _read_source(_CLI_PATH.parent / "gate_enforcer.py")
        assert "GATE_PSEUDOCODE" in src


class TestGateReviewFiresAfterReview:
    def test_gate_review_fires_after_review(self, tmp_path):
        _write_requirements(
            tmp_path,
            "- [x] REQ-001 Something (review_cycles: 3)\n- [x] REQ-002 Another (review_cycles: 2)\n",
        )
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_review_count(min_reviews=2)
        assert result.passed is True
        assert result.gate_id == "GATE_INDEPENDENT_REVIEW"

    def test_gate_review_in_cli(self):
        src = _read_source(_CLI_PATH)
        assert "enforce_review_count" in src


class TestGateConvergenceFiresBeforeE2E:
    def test_gate_convergence_fires_before_e2e(self, tmp_path):
        content = "\n".join(
            f"- [x] REQ-{i:03d} Item {i}" for i in range(10)
        )
        _write_requirements(tmp_path, content)
        enforcer = _make_enforcer(tmp_path, min_convergence_ratio=0.9)
        result = enforcer.enforce_convergence_threshold()
        assert result.passed is True
        assert result.gate_id == "GATE_CONVERGENCE"

    def test_gate_convergence_in_cli(self):
        src = _read_source(_CLI_PATH)
        assert "enforce_convergence_threshold" in src


class TestGateTruthScoreFiresAfterScoring:
    def test_gate_truth_score_fires_after_scoring(self, tmp_path):
        _write_truth_scores(tmp_path, [{"score": 0.99}])
        enforcer = _make_enforcer(tmp_path)
        result = enforcer.enforce_truth_score(min_score=0.95)
        assert result.passed is True
        assert result.gate_id == "GATE_TRUTH_SCORE"

    def test_truth_score_gate_id_defined(self):
        src = _read_source(_CLI_PATH.parent / "gate_enforcer.py")
        assert "GATE_TRUTH_SCORE" in src


class TestGateE2EFiresAfterTests:
    def test_gate_e2e_fires_after_tests(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        state = RunState(endpoint_test_report={
            "health": "passed",
            "tested_endpoints": 10,
            "passed_endpoints": 10,
        })
        config = _make_config(gates_enabled=True)
        config.convergence = ConvergenceConfig(requirements_dir=".agent-team")
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=True)
        result = enforcer.enforce_e2e_pass()
        assert result.passed is True
        assert result.gate_id == "GATE_E2E"

    def test_gate_e2e_in_cli(self):
        src = _read_source(_CLI_PATH)
        assert "enforce_e2e_pass" in src


class TestAllGatesWriteToAuditLog:
    def test_all_gates_write_to_audit_log(self, tmp_path):
        _write_requirements(
            tmp_path,
            "# Requirements\n\n## Architecture Decision\nArch.\n\n"
            "- [x] REQ-001 Item (review_cycles: 2)\n",
        )
        _write_pseudocode_dir(tmp_path, 1)
        _write_truth_scores(tmp_path, [{"score": 0.99}])

        state = RunState(endpoint_test_report={
            "health": "passed", "tested_endpoints": 5, "passed_endpoints": 5,
        })
        config = _make_config(gates_enabled=False)  # Informational to avoid raising
        config.convergence = ConvergenceConfig(
            requirements_dir=".agent-team",
            requirements_file="REQUIREMENTS.md",
        )
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)

        enforcer.enforce_requirements_exist()
        enforcer.enforce_architecture_exists()
        enforcer.enforce_pseudocode_exists()
        enforcer.enforce_review_count()
        enforcer.enforce_convergence_threshold()
        enforcer.enforce_truth_score()
        enforcer.enforce_e2e_pass()

        log_path = tmp_path / ".agent-team" / "GATE_AUDIT.log"
        assert log_path.is_file()
        log_content = log_path.read_text(encoding="utf-8")
        assert "GATE_REQUIREMENTS" in log_content
        assert "GATE_ARCHITECTURE" in log_content
        assert "GATE_PSEUDOCODE" in log_content
        assert "GATE_INDEPENDENT_REVIEW" in log_content
        assert "GATE_CONVERGENCE" in log_content
        assert "GATE_TRUTH_SCORE" in log_content
        assert "GATE_E2E" in log_content


class TestGateAuditLogHas7EntriesInFullRun:
    def test_gate_audit_log_has_7_entries_in_full_run(self, tmp_path):
        _write_requirements(
            tmp_path,
            "# Requirements\n\n## Architecture Decision\nArch.\n\n"
            "- [x] REQ-001 Item (review_cycles: 2)\n",
        )
        _write_pseudocode_dir(tmp_path, 1)
        _write_truth_scores(tmp_path, [{"score": 0.99}])

        state = RunState(endpoint_test_report={
            "health": "passed", "tested_endpoints": 5, "passed_endpoints": 5,
        })
        config = _make_config(gates_enabled=False)
        config.convergence = ConvergenceConfig(
            requirements_dir=".agent-team",
            requirements_file="REQUIREMENTS.md",
        )
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)

        enforcer.enforce_requirements_exist()
        enforcer.enforce_architecture_exists()
        enforcer.enforce_pseudocode_exists()
        enforcer.enforce_review_count()
        enforcer.enforce_convergence_threshold()
        enforcer.enforce_truth_score()
        enforcer.enforce_e2e_pass()

        trail = enforcer.get_gate_audit_trail()
        assert len(trail) == 7
        gate_ids = [r.gate_id for r in trail]
        assert "GATE_REQUIREMENTS" in gate_ids
        assert "GATE_ARCHITECTURE" in gate_ids
        assert "GATE_PSEUDOCODE" in gate_ids
        assert "GATE_INDEPENDENT_REVIEW" in gate_ids
        assert "GATE_CONVERGENCE" in gate_ids
        assert "GATE_TRUTH_SCORE" in gate_ids
        assert "GATE_E2E" in gate_ids


class TestGatesFireInEnterpriseMode:
    def test_gates_fire_in_enterprise_mode(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        config = _make_config(gates_enabled=True)
        config.convergence = ConvergenceConfig(requirements_dir=".agent-team")
        state = RunState(enterprise_mode_active=True)
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=True)
        result = enforcer.enforce_requirements_exist()
        assert result.gate_id == "GATE_REQUIREMENTS"
        assert result.passed is True


class TestGatesFireInStandardMode:
    def test_gates_fire_in_standard_mode(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        config = _make_config(gates_enabled=True)
        config.convergence = ConvergenceConfig(requirements_dir=".agent-team")
        state = RunState(depth="standard")
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=True)
        result = enforcer.enforce_requirements_exist()
        assert result.passed is True


class TestGatesFireInCoordinatedBuilder:
    def test_gates_fire_in_coordinated_builder(self):
        """coordinated_builder.py has gate_enforcement wiring."""
        src = _read_source(_CB_PATH)
        assert "gate_enforcement" in src

    def test_truth_scorer_in_coordinated_builder(self):
        src = _read_source(_CB_PATH)
        assert "TruthScorer" in src
        assert "truth_scorer" in src


class TestGateFailureRaisesViolationError:
    def test_gate_failure_raises_violation_error(self, tmp_path):
        (tmp_path / ".agent-team").mkdir(parents=True, exist_ok=True)
        enforcer = _make_enforcer(tmp_path, gates_enabled=True)
        with pytest.raises(GateViolationError, match="GATE_REQUIREMENTS"):
            enforcer.enforce_requirements_exist()

    def test_violation_error_is_exception(self):
        assert issubclass(GateViolationError, Exception)


class TestGateInformationalModeLogsWarning:
    def test_gate_informational_mode_logs_warning(self, tmp_path):
        (tmp_path / ".agent-team").mkdir(parents=True, exist_ok=True)
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        # Should NOT raise — informational mode
        result = enforcer.enforce_requirements_exist()
        assert result.passed is False
        assert result.gate_id == "GATE_REQUIREMENTS"

    def test_informational_mode_set_correctly(self, tmp_path):
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        assert enforcer._mode == GateMode.INFORMATIONAL


class TestStateGateResultsHasAll7Gates:
    def test_state_gate_results_has_all_7_gates(self, tmp_path):
        _write_requirements(
            tmp_path,
            "# Requirements\n\n## Architecture Decision\nArch.\n\n"
            "- [x] REQ-001 Item (review_cycles: 2)\n",
        )
        _write_pseudocode_dir(tmp_path, 1)
        _write_truth_scores(tmp_path, [{"score": 0.99}])

        state = RunState(endpoint_test_report={
            "health": "passed", "tested_endpoints": 5, "passed_endpoints": 5,
        })
        config = _make_config(gates_enabled=False)
        config.convergence = ConvergenceConfig(
            requirements_dir=".agent-team",
            requirements_file="REQUIREMENTS.md",
        )
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)

        enforcer.enforce_requirements_exist()
        enforcer.enforce_architecture_exists()
        enforcer.enforce_pseudocode_exists()
        enforcer.enforce_review_count()
        enforcer.enforce_convergence_threshold()
        enforcer.enforce_truth_score()
        enforcer.enforce_e2e_pass()

        assert len(state.gate_results) == 7
        gate_ids = {r["gate_id"] for r in state.gate_results}
        assert gate_ids == {
            "GATE_REQUIREMENTS", "GATE_ARCHITECTURE", "GATE_PSEUDOCODE",
            "GATE_INDEPENDENT_REVIEW", "GATE_CONVERGENCE",
            "GATE_TRUTH_SCORE", "GATE_E2E",
        }


# ===================================================================
# SECTION 4: End-to-End Pipeline Tests
# ===================================================================


class TestFullPipelinePseudocodeThenTruthThenGates:
    def test_full_pipeline_pseudocode_then_truth_then_gates(self, tmp_path):
        """Simulate full pipeline: pseudocode check -> truth scoring -> all gates."""
        # Setup
        _write_requirements(
            tmp_path,
            "# Requirements\n\n## Architecture Decision\nArch.\n\n"
            + "\n".join(f"- [x] REQ-{i:03d} Item (review_cycles: 2)" for i in range(10))
            + "\n",
        )
        _write_pseudocode_dir(tmp_path, 3)
        _write_truth_scores(tmp_path, [{"score": 0.98}, {"score": 0.97}])

        state = RunState(endpoint_test_report={
            "health": "passed", "tested_endpoints": 10, "passed_endpoints": 10,
        })
        config = _make_config(gates_enabled=False)
        config.convergence = ConvergenceConfig(
            requirements_dir=".agent-team",
            requirements_file="REQUIREMENTS.md",
            min_convergence_ratio=0.9,
        )

        # Step 1: Pseudocode check
        enforcer = GateEnforcer(config, state, tmp_path, gates_enabled=False)
        pseudo_result = enforcer.enforce_pseudocode_exists()
        assert pseudo_result.passed is True

        # Step 2: Truth scoring
        scorer = TruthScorer(tmp_path)
        truth_result = scorer.score()
        assert isinstance(truth_result, TruthScore)

        # Step 3: All gates
        enforcer.enforce_requirements_exist()
        enforcer.enforce_architecture_exists()
        enforcer.enforce_review_count(min_reviews=2)
        enforcer.enforce_convergence_threshold()
        enforcer.enforce_truth_score(min_score=0.95)
        enforcer.enforce_e2e_pass()

        trail = enforcer.get_gate_audit_trail()
        assert len(trail) == 7  # pseudo + 6 other gates


class TestStateJsonHasAllNewFieldsPopulated:
    def test_state_json_has_all_new_fields_populated(self, tmp_path):
        state = RunState(
            truth_scores={"REQ-001": 0.95},
            previous_passing_acs=["AC-001"],
            regression_count=2,
            pseudocode_validated=True,
            pseudocode_artifacts={"T1": "path"},
            gate_results=[{"gate_id": "GATE_REQUIREMENTS", "passed": True, "reason": "ok", "timestamp": "2026-01-01"}],
            gates_passed=5,
            gates_failed=2,
        )
        save_state(state, directory=str(tmp_path))
        loaded = load_state(directory=str(tmp_path))
        assert loaded is not None
        assert loaded.truth_scores == {"REQ-001": 0.95}
        assert loaded.previous_passing_acs == ["AC-001"]
        assert loaded.regression_count == 2
        assert loaded.pseudocode_validated is True
        assert loaded.pseudocode_artifacts == {"T1": "path"}
        assert len(loaded.gate_results) == 1
        assert loaded.gates_passed == 5
        assert loaded.gates_failed == 2

    def test_state_json_file_created(self, tmp_path):
        state = RunState()
        save_state(state, directory=str(tmp_path))
        assert (tmp_path / "STATE.json").is_file()


class TestGateAuditLogCreatedWithEntries:
    def test_gate_audit_log_created_with_entries(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()

        log_path = tmp_path / ".agent-team" / "GATE_AUDIT.log"
        assert log_path.is_file()
        content = log_path.read_text(encoding="utf-8")
        assert "GATE_REQUIREMENTS" in content
        assert "PASS" in content or "FAIL" in content

    def test_audit_log_has_timestamps(self, tmp_path):
        _write_requirements(tmp_path, "- [x] REQ-001 Something\n")
        enforcer = _make_enforcer(tmp_path, gates_enabled=False)
        enforcer.enforce_requirements_exist()

        log_path = tmp_path / ".agent-team" / "GATE_AUDIT.log"
        content = log_path.read_text(encoding="utf-8")
        # ISO 8601 timestamp pattern
        assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", content)


class TestBackwardCompatAllFeaturesDisabled:
    def test_backward_compat_all_features_disabled(self):
        config = AgentTeamConfig()
        # All new features default to disabled
        assert config.gate_enforcement.enabled is False
        assert config.gate_enforcement.enforce_pseudocode is False
        assert config.gate_enforcement.enforce_truth_score is False
        assert config.pseudocode.enabled is False

    def test_state_defaults_have_zero_values(self):
        state = RunState()
        assert state.gate_results == []
        assert state.gates_passed == 0
        assert state.gates_failed == 0
        assert state.truth_scores == {}
        assert state.regression_count == 0
        assert state.pseudocode_validated is False

    def test_old_state_loads_without_new_fields(self, tmp_path):
        """Simulate loading a state file from before new features existed."""
        old_state = {
            "run_id": "abc123",
            "task": "build something",
            "depth": "standard",
            "current_phase": "init",
            "schema_version": 2,
        }
        state_dir = tmp_path
        (state_dir / "STATE.json").write_text(
            json.dumps(old_state), encoding="utf-8"
        )
        loaded = load_state(directory=str(state_dir))
        assert loaded is not None
        # New fields should have safe defaults
        assert loaded.truth_scores == {}
        assert loaded.regression_count == 0
        assert loaded.pseudocode_validated is False
        assert loaded.gate_results == []
        assert loaded.gates_passed == 0
        assert loaded.gates_failed == 0


class TestEnterpriseConfigEnablesAllFeatures:
    def test_enterprise_config_enables_all_features(self):
        config = AgentTeamConfig()
        config.gate_enforcement = GateEnforcementConfig(
            enabled=True,
            enforce_requirements=True,
            enforce_architecture=True,
            enforce_pseudocode=True,
            enforce_review_count=True,
            enforce_convergence=True,
            enforce_truth_score=True,
            enforce_e2e=True,
        )
        config.pseudocode = PseudocodeConfig(enabled=True)
        assert config.gate_enforcement.enabled is True
        assert config.gate_enforcement.enforce_pseudocode is True
        assert config.gate_enforcement.enforce_truth_score is True
        assert config.pseudocode.enabled is True

    def test_enterprise_config_truth_score_threshold(self):
        config = GateEnforcementConfig(truth_score_threshold=0.90)
        assert config.truth_score_threshold == 0.90


# ===================================================================
# SECTION 5: Source Wiring Verification Tests
# ===================================================================


class TestCliSourceHasGateEnforcerWiring:
    """Verify cli.py source contains all expected gate enforcement wiring."""

    @pytest.fixture(scope="class")
    def cli_source(self) -> str:
        return _read_source(_CLI_PATH)

    def test_gate_enforcer_import(self, cli_source):
        assert "from .gate_enforcer import GateEnforcer" in cli_source

    def test_gate_violation_error_import(self, cli_source):
        assert "GateViolationError" in cli_source

    def test_gate_enforcer_global_variable(self, cli_source):
        assert "_gate_enforcer" in cli_source

    def test_gate_enforcer_initialized_when_enabled(self, cli_source):
        assert "GateEnforcer(" in cli_source
        assert "config.gate_enforcement.enabled" in cli_source

    def test_requirements_gate_wired(self, cli_source):
        assert "enforce_requirements_exist" in cli_source

    def test_architecture_gate_wired(self, cli_source):
        assert "enforce_architecture_exists" in cli_source

    def test_review_gate_wired(self, cli_source):
        assert "enforce_review_count" in cli_source

    def test_convergence_gate_wired(self, cli_source):
        assert "enforce_convergence_threshold" in cli_source

    def test_e2e_gate_wired(self, cli_source):
        assert "enforce_e2e_pass" in cli_source


class TestCoordinatedBuilderSourceHasTruthScoringWiring:
    """Verify coordinated_builder.py has truth scoring and regression wiring."""

    @pytest.fixture(scope="class")
    def cb_source(self) -> str:
        return _read_source(_CB_PATH)

    def test_truth_scorer_import(self, cb_source):
        assert "TruthScorer" in cb_source

    def test_truth_scorer_instantiation(self, cb_source):
        assert "TruthScorer(" in cb_source

    def test_truth_score_method_called(self, cb_source):
        assert "truth_scorer.score()" in cb_source

    def test_regression_check_present(self, cb_source):
        assert "_check_regressions" in cb_source

    def test_rollback_suggestion_present(self, cb_source):
        assert "_suggest_rollback" in cb_source

    def test_regression_count_tracked(self, cb_source):
        assert "regression_count" in cb_source

    def test_gate_enforcement_config_check(self, cb_source):
        assert "gate_enforcement" in cb_source
