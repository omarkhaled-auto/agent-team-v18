"""Tests for agent_team.audit_team orchestration logic."""

from __future__ import annotations

import pytest

from agent_team_v15.audit_models import AuditFinding, AuditScore
from agent_team_v15.audit_team import (
    DEPTH_AUDITOR_MAP,
    build_auditor_agent_definitions,
    get_auditors_for_depth,
    should_skip_scan,
    should_terminate_reaudit,
)


# ===================================================================
# get_auditors_for_depth
# ===================================================================

class TestGetAuditorsForDepth:
    def test_quick_returns_empty(self):
        assert get_auditors_for_depth("quick") == []

    def test_standard_returns_three(self):
        result = get_auditors_for_depth("standard")
        assert len(result) == 3
        assert "requirements" in result
        assert "technical" in result
        assert "interface" in result

    def test_thorough_returns_six(self):
        result = get_auditors_for_depth("thorough")
        assert len(result) == 6
        assert "test" in result
        assert "mcp_library" in result
        assert "prd_fidelity" in result

    def test_exhaustive_returns_six(self):
        result = get_auditors_for_depth("exhaustive")
        assert len(result) == 6

    def test_unknown_depth_falls_back_to_standard(self):
        result = get_auditors_for_depth("unknown_depth")
        assert result == get_auditors_for_depth("standard")

    def test_returns_new_list(self):
        r1 = get_auditors_for_depth("thorough")
        r2 = get_auditors_for_depth("thorough")
        assert r1 is not r2
        assert r1 == r2


# ===================================================================
# should_skip_scan
# ===================================================================

class TestShouldSkipScan:
    def test_mock_data_scan_skipped_when_interface_deployed(self):
        assert should_skip_scan("mock_data_scan", ["interface"]) is True

    def test_mock_data_scan_not_skipped_when_interface_absent(self):
        assert should_skip_scan("mock_data_scan", ["requirements"]) is False

    def test_ui_compliance_scan_never_skipped(self):
        # ui_compliance_scan is NOT in the overlap map — SLOP regex scanning
        # is not replicated by the requirements auditor's DESIGN-xxx checks
        assert should_skip_scan("ui_compliance_scan", ["requirements"]) is False
        assert should_skip_scan("ui_compliance_scan", ["requirements", "interface", "technical"]) is False

    def test_api_contract_scan_skipped_when_interface_deployed(self):
        assert should_skip_scan("api_contract_scan", ["interface"]) is True

    def test_sdl_scan_skipped_when_technical_deployed(self):
        assert should_skip_scan("silent_data_loss_scan", ["technical"]) is True

    def test_endpoint_xref_skipped_when_interface_deployed(self):
        assert should_skip_scan("endpoint_xref_scan", ["interface"]) is True

    def test_unknown_scan_never_skipped(self):
        assert should_skip_scan("custom_scan", ["interface", "requirements"]) is False

    def test_empty_auditors_never_skips(self):
        assert should_skip_scan("mock_data_scan", []) is False


# ===================================================================
# should_terminate_reaudit
# ===================================================================

class TestShouldTerminateReaudit:
    def _make_score(self, score: float = 90.0, critical: int = 0) -> AuditScore:
        return AuditScore(
            total_items=10, passed=9, failed=1, partial=0,
            critical_count=critical, high_count=0, medium_count=1,
            low_count=0, info_count=0, score=score, health="degraded",
        )

    def test_healthy_score_terminates(self):
        score = self._make_score(score=95.0, critical=0)
        stop, reason = should_terminate_reaudit(score, None, cycle=1)
        assert stop is True
        assert reason == "healthy"

    def test_max_cycles_terminates(self):
        score = self._make_score(score=50.0)
        stop, reason = should_terminate_reaudit(score, None, cycle=3, max_cycles=3)
        assert stop is True
        assert reason == "max_cycles"

    def test_no_improvement_terminates(self):
        prev = self._make_score(score=60.0)
        curr = self._make_score(score=60.0)
        stop, reason = should_terminate_reaudit(curr, prev, cycle=2)
        assert stop is True
        assert reason == "no_improvement"

    def test_improvement_continues(self):
        prev = self._make_score(score=60.0)
        curr = self._make_score(score=70.0)
        stop, reason = should_terminate_reaudit(curr, prev, cycle=2)
        assert stop is False

    def test_first_cycle_no_previous(self):
        score = self._make_score(score=50.0)
        stop, reason = should_terminate_reaudit(score, None, cycle=1)
        assert stop is False

    def test_critical_prevents_healthy(self):
        score = self._make_score(score=95.0, critical=1)
        stop, reason = should_terminate_reaudit(score, None, cycle=1)
        assert stop is False

    def test_regression_terminates(self):
        prev = self._make_score(score=80.0)
        curr = self._make_score(score=60.0)  # Dropped by 20 points
        stop, reason = should_terminate_reaudit(curr, prev, cycle=2)
        assert stop is True
        assert reason == "regression"

    def test_small_drop_is_no_improvement(self):
        # A 5-point drop is not regression (>10 needed) but IS no_improvement
        prev = self._make_score(score=80.0)
        curr = self._make_score(score=75.0)  # Dropped by only 5 points
        stop, reason = should_terminate_reaudit(curr, prev, cycle=2)
        assert stop is True
        assert reason == "no_improvement"

    def test_score_just_above_regression_threshold(self):
        # 9-point drop: not regression (needs >10), but is no_improvement
        prev = self._make_score(score=80.0)
        curr = self._make_score(score=71.0)
        stop, reason = should_terminate_reaudit(curr, prev, cycle=2)
        assert stop is True
        assert reason == "no_improvement"  # Not "regression" since drop <= 10


# ===================================================================
# build_auditor_agent_definitions
# ===================================================================

class TestBuildAuditorAgentDefinitions:
    def test_returns_all_auditors_plus_scorer(self):
        auditors = ["requirements", "technical", "interface", "test", "mcp_library"]
        agents = build_auditor_agent_definitions(auditors)
        assert "audit-requirements" in agents
        assert "audit-technical" in agents
        assert "audit-interface" in agents
        assert "audit-test" in agents
        assert "audit-mcp-library" in agents
        assert "audit-scorer" in agents

    def test_scorer_always_included(self):
        agents = build_auditor_agent_definitions(["requirements"])
        assert "audit-scorer" in agents

    def test_test_auditor_has_bash(self):
        agents = build_auditor_agent_definitions(["test"])
        assert "Bash" in agents["audit-test"]["tools"]

    def test_requirements_auditor_no_bash(self):
        agents = build_auditor_agent_definitions(["requirements"])
        assert "Bash" not in agents["audit-requirements"]["tools"]

    def test_task_text_injected_into_requirements(self):
        agents = build_auditor_agent_definitions(["requirements"], task_text="Build a login page")
        assert "[ORIGINAL USER REQUEST]" in agents["audit-requirements"]["prompt"]
        assert "Build a login page" in agents["audit-requirements"]["prompt"]

    def test_task_text_not_in_technical(self):
        agents = build_auditor_agent_definitions(["technical"], task_text="Build a login page")
        assert "Build a login page" not in agents["audit-technical"]["prompt"]

    def test_unknown_auditor_skipped(self):
        agents = build_auditor_agent_definitions(["unknown_auditor"])
        assert "audit-unknown-auditor" not in agents
        assert "audit-scorer" in agents

    def test_empty_auditor_list_still_has_scorer(self):
        agents = build_auditor_agent_definitions([])
        assert len(agents) == 2  # scorer + comprehensive
        assert "audit-scorer" in agents

    def test_agent_model_is_opus(self):
        agents = build_auditor_agent_definitions(["requirements"])
        assert agents["audit-requirements"]["model"] == "opus"

    def test_standard_depth_agents(self):
        auditors = get_auditors_for_depth("standard")
        agents = build_auditor_agent_definitions(auditors)
        # 3 auditors + scorer + comprehensive = 5
        assert len(agents) == 5

    def test_requirements_path_injected(self):
        agents = build_auditor_agent_definitions(
            ["requirements"], requirements_path=".agent-team/REQUIREMENTS.md",
        )
        prompt = agents["audit-requirements"]["prompt"]
        assert ".agent-team/REQUIREMENTS.md" in prompt
        assert "{requirements_path}" not in prompt

    def test_requirements_path_in_all_auditors(self):
        agents = build_auditor_agent_definitions(
            ["requirements", "technical", "interface", "test", "mcp_library"],
            requirements_path=".agent-team/REQUIREMENTS.md",
        )
        for key, agent_def in agents.items():
            if key == "audit-scorer":
                continue
            assert "{requirements_path}" not in agent_def["prompt"], (
                f"{key} still has unformatted {{requirements_path}}"
            )

    def test_prd_fidelity_included_when_prd_path_provided(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"], prd_path="docs/PRD.md",
        )
        assert "audit-prd-fidelity" in agents
        assert "docs/PRD.md" in agents["audit-prd-fidelity"]["prompt"]
        assert "{prd_path}" not in agents["audit-prd-fidelity"]["prompt"]

    def test_prd_fidelity_skipped_when_no_prd_path(self):
        agents = build_auditor_agent_definitions(["prd_fidelity"])
        assert "audit-prd-fidelity" not in agents
        assert "audit-scorer" in agents

    def test_prd_fidelity_no_bash(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"], prd_path="docs/PRD.md",
        )
        assert "Bash" not in agents["audit-prd-fidelity"]["tools"]

    def test_prd_fidelity_with_requirements_path(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            requirements_path=".agent-team/REQUIREMENTS.md",
            prd_path="docs/PRD.md",
        )
        prompt = agents["audit-prd-fidelity"]["prompt"]
        assert ".agent-team/REQUIREMENTS.md" in prompt
        assert "docs/PRD.md" in prompt
        assert "{requirements_path}" not in prompt
        assert "{prd_path}" not in prompt

    def test_thorough_depth_skips_prd_fidelity_without_prd(self):
        auditors = get_auditors_for_depth("thorough")
        assert "prd_fidelity" in auditors
        agents = build_auditor_agent_definitions(auditors)
        # prd_fidelity should be skipped (no prd_path), leaving 5 + scorer + comprehensive = 7
        assert "audit-prd-fidelity" not in agents
        assert len(agents) == 7  # 5 auditors + scorer + comprehensive

    def test_thorough_depth_includes_prd_fidelity_with_prd(self):
        auditors = get_auditors_for_depth("thorough")
        agents = build_auditor_agent_definitions(auditors, prd_path="docs/PRD.md")
        # prd_fidelity should be included, giving 6 + scorer + comprehensive = 8
        assert "audit-prd-fidelity" in agents
        assert len(agents) == 8  # 6 auditors + scorer + comprehensive


# ===================================================================
# DEPTH_AUDITOR_MAP consistency
# ===================================================================

class TestDepthAuditorMap:
    def test_all_standard_depths_present(self):
        for depth in ("quick", "standard", "thorough", "exhaustive", "enterprise"):
            assert depth in DEPTH_AUDITOR_MAP

    def test_quick_is_empty(self):
        assert DEPTH_AUDITOR_MAP["quick"] == []

    def test_standard_is_subset_of_thorough(self):
        standard = set(DEPTH_AUDITOR_MAP["standard"])
        thorough = set(DEPTH_AUDITOR_MAP["thorough"])
        assert standard.issubset(thorough)

    def test_thorough_equals_exhaustive(self):
        assert set(DEPTH_AUDITOR_MAP["thorough"]) == set(DEPTH_AUDITOR_MAP["exhaustive"])
