"""Exhaustive tests for the PRD Fidelity Auditor (6th auditor).

Covers:
- audit_models.py: AUDITOR_NAMES, AUDITOR_PREFIXES include prd_fidelity/PA
- audit_prompts.py: PRD_FIDELITY_AUDITOR_PROMPT content, registry, get_auditor_prompt prd_path
- audit_team.py: DEPTH_AUDITOR_MAP, build_auditor_agent_definitions prd_path gating
- Integration: finding format, fix dispatch, dedup, scoring compatibility
"""

from __future__ import annotations

import re

import pytest

from agent_team_v15.audit_models import (
    AUDITOR_NAMES,
    AUDITOR_PREFIXES,
    AuditFinding,
    AuditScore,
    build_report,
    deduplicate_findings,
    group_findings_into_fix_tasks,
)
from agent_team_v15.audit_prompts import (
    AUDIT_PROMPTS,
    PRD_FIDELITY_AUDITOR_PROMPT,
    get_auditor_prompt,
)
from agent_team_v15.audit_team import (
    DEPTH_AUDITOR_MAP,
    build_auditor_agent_definitions,
    get_auditors_for_depth,
    should_skip_scan,
    should_terminate_reaudit,
)


# ===================================================================
# Helpers
# ===================================================================

def _make_prd_finding(
    finding_id: str = "PA-001",
    requirement_id: str = "PRD-DROPPED-001",
    verdict: str = "FAIL",
    severity: str = "HIGH",
    summary: str = "Requirement dropped from PRD",
    evidence: list[str] | None = None,
    confidence: float = 0.9,
) -> AuditFinding:
    return AuditFinding(
        finding_id=finding_id,
        auditor="prd_fidelity",
        requirement_id=requirement_id,
        verdict=verdict,
        severity=severity,
        summary=summary,
        evidence=evidence if evidence is not None else ["prd.md:42 -- requirement present in PRD but absent from REQUIREMENTS.md"],
        remediation="Add requirement to REQUIREMENTS.md",
        confidence=confidence,
    )


def _make_other_finding(
    finding_id: str = "RA-001",
    auditor: str = "requirements",
    requirement_id: str = "REQ-001",
    verdict: str = "FAIL",
    severity: str = "HIGH",
    evidence: list[str] | None = None,
) -> AuditFinding:
    return AuditFinding(
        finding_id=finding_id,
        auditor=auditor,
        requirement_id=requirement_id,
        verdict=verdict,
        severity=severity,
        summary="Other finding",
        evidence=evidence or ["src/foo.py:10 -- issue"],
        remediation="Fix it",
        confidence=0.9,
    )


# ===================================================================
# 1. AUDITOR_NAMES and AUDITOR_PREFIXES
# ===================================================================

class TestAuditorRegistration:
    """Verify prd_fidelity is properly registered in audit_models."""

    def test_prd_fidelity_in_auditor_names(self):
        assert "prd_fidelity" in AUDITOR_NAMES

    def test_auditor_names_has_six_entries(self):
        assert len(AUDITOR_NAMES) == 6

    def test_prd_fidelity_prefix_is_pa(self):
        assert AUDITOR_PREFIXES["prd_fidelity"] == "PA"

    def test_all_names_have_prefixes(self):
        for name in AUDITOR_NAMES:
            assert name in AUDITOR_PREFIXES, f"{name} missing from AUDITOR_PREFIXES"

    def test_all_prefixes_unique(self):
        prefixes = list(AUDITOR_PREFIXES.values())
        assert len(prefixes) == len(set(prefixes)), "Duplicate prefix found"

    def test_pa_prefix_not_used_by_others(self):
        for name, prefix in AUDITOR_PREFIXES.items():
            if name != "prd_fidelity":
                assert prefix != "PA", f"{name} shares PA prefix with prd_fidelity"

    def test_prd_fidelity_position_is_last(self):
        assert AUDITOR_NAMES[-1] == "prd_fidelity"

    def test_original_five_auditors_preserved(self):
        original = ("requirements", "technical", "interface", "test", "mcp_library")
        for name in original:
            assert name in AUDITOR_NAMES


# ===================================================================
# 2. PRD_FIDELITY_AUDITOR_PROMPT content
# ===================================================================

class TestPrdFidelityPromptContent:
    """Verify PRD_FIDELITY_AUDITOR_PROMPT has all required sections."""

    def test_prompt_is_non_empty(self):
        assert len(PRD_FIDELITY_AUDITOR_PROMPT.strip()) > 200

    def test_prompt_under_120_lines(self):
        line_count = len(PRD_FIDELITY_AUDITOR_PROMPT.strip().splitlines())
        assert line_count <= 120, f"PRD fidelity prompt has {line_count} lines (max 120)"

    def test_contains_prd_path_placeholder(self):
        assert "{prd_path}" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_requirements_path_placeholder(self):
        assert "{requirements_path}" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_scope_section(self):
        assert "## Scope" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_output_format(self):
        assert "## Output Format" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_dropped_detection(self):
        assert "DROPPED" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_distorted_detection(self):
        assert "DISTORTED" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_orphaned_detection(self):
        assert "ORPHANED" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_adversarial_instruction(self):
        assert "ADVERSARIAL" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_finding_prefix_is_pa(self):
        assert '"PA-001"' in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_evidence_format_rules(self):
        assert "Evidence Format Rules" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_forward_slash_instruction(self):
        assert "forward slashes" in PRD_FIDELITY_AUDITOR_PROMPT.lower()

    def test_contains_json_schema(self):
        assert '"finding_id"' in PRD_FIDELITY_AUDITOR_PROMPT
        assert '"verdict"' in PRD_FIDELITY_AUDITOR_PROMPT
        assert '"severity"' in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_verdict_rules(self):
        assert "FAIL" in PRD_FIDELITY_AUDITOR_PROMPT
        assert "PARTIAL" in PRD_FIDELITY_AUDITOR_PROMPT
        assert "PASS" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_mentions_other_auditor_scopes(self):
        assert "Other auditors cover" in PRD_FIDELITY_AUDITOR_PROMPT or \
               "other auditors" in PRD_FIDELITY_AUDITOR_PROMPT.lower()

    def test_mentions_phase1_prd_to_requirements(self):
        assert "Phase 1" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_mentions_phase2_requirements_to_prd(self):
        assert "Phase 2" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_mentions_prd_dropped_nnn_id_format(self):
        assert "PRD-DROPPED" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_no_mcp_tool_references(self):
        """PRD Fidelity auditor should NOT reference MCP tools (uses Read/Grep only)."""
        mcp_refs = re.findall(r"mcp__[\w-]+__[\w-]+", PRD_FIDELITY_AUDITOR_PROMPT)
        assert mcp_refs == [], f"Unexpected MCP tool references: {mcp_refs}"


# ===================================================================
# 3. AUDIT_PROMPTS registry
# ===================================================================

class TestPromptRegistry:
    """Verify prd_fidelity is in AUDIT_PROMPTS and registry is consistent."""

    def test_prd_fidelity_in_registry(self):
        assert "prd_fidelity" in AUDIT_PROMPTS

    def test_registry_has_seven_entries(self):
        # 6 auditors + scorer + comprehensive = 8
        assert len(AUDIT_PROMPTS) == 8

    def test_all_auditor_names_in_registry(self):
        for name in AUDITOR_NAMES:
            assert name in AUDIT_PROMPTS, f"{name} missing from AUDIT_PROMPTS"

    def test_scorer_in_registry(self):
        assert "scorer" in AUDIT_PROMPTS


# ===================================================================
# 4. get_auditor_prompt with prd_path
# ===================================================================

class TestGetAuditorPromptPrdPath:
    """Verify get_auditor_prompt handles prd_path parameter."""

    def test_prd_path_replaces_placeholder(self):
        prompt = get_auditor_prompt("prd_fidelity", prd_path="docs/PRD.md")
        assert "docs/PRD.md" in prompt
        assert "{prd_path}" not in prompt

    def test_requirements_path_replaces_placeholder(self):
        prompt = get_auditor_prompt(
            "prd_fidelity",
            requirements_path=".agent-team/REQUIREMENTS.md",
            prd_path="docs/PRD.md",
        )
        assert ".agent-team/REQUIREMENTS.md" in prompt
        assert "{requirements_path}" not in prompt

    def test_both_paths_replaced(self):
        prompt = get_auditor_prompt(
            "prd_fidelity",
            requirements_path="reqs.md",
            prd_path="prd.md",
        )
        assert "{prd_path}" not in prompt
        assert "{requirements_path}" not in prompt

    def test_without_prd_path_preserves_placeholder(self):
        prompt = get_auditor_prompt("prd_fidelity")
        assert "{prd_path}" in prompt

    def test_without_requirements_path_preserves_placeholder(self):
        prompt = get_auditor_prompt("prd_fidelity")
        assert "{requirements_path}" in prompt

    def test_prd_path_has_no_effect_on_other_auditors(self):
        """prd_path should only affect prd_fidelity prompt."""
        prompt = get_auditor_prompt("requirements", prd_path="prd.md")
        assert "{prd_path}" not in prompt or "prd.md" in prompt
        # The requirements auditor shouldn't have prd_path placeholder at all
        raw_prompt = AUDIT_PROMPTS["requirements"]
        assert "{prd_path}" not in raw_prompt

    def test_invalid_auditor_raises_key_error(self):
        with pytest.raises(KeyError):
            get_auditor_prompt("nonexistent", prd_path="prd.md")


# ===================================================================
# 5. DEPTH_AUDITOR_MAP includes prd_fidelity
# ===================================================================

class TestDepthGatingPrdFidelity:
    """Verify prd_fidelity appears in correct depth tiers."""

    def test_quick_excludes_prd_fidelity(self):
        auditors = get_auditors_for_depth("quick")
        assert "prd_fidelity" not in auditors

    def test_standard_excludes_prd_fidelity(self):
        auditors = get_auditors_for_depth("standard")
        assert "prd_fidelity" not in auditors

    def test_thorough_includes_prd_fidelity(self):
        auditors = get_auditors_for_depth("thorough")
        assert "prd_fidelity" in auditors

    def test_exhaustive_includes_prd_fidelity(self):
        auditors = get_auditors_for_depth("exhaustive")
        assert "prd_fidelity" in auditors

    def test_thorough_has_six_auditors(self):
        auditors = get_auditors_for_depth("thorough")
        assert len(auditors) == 6

    def test_exhaustive_has_six_auditors(self):
        auditors = get_auditors_for_depth("exhaustive")
        assert len(auditors) == 6

    def test_standard_still_has_three(self):
        auditors = get_auditors_for_depth("standard")
        assert len(auditors) == 3

    def test_map_uses_auditor_names(self):
        """DEPTH_AUDITOR_MAP thorough/exhaustive should auto-inherit from AUDITOR_NAMES."""
        thorough = set(DEPTH_AUDITOR_MAP["thorough"])
        names = set(AUDITOR_NAMES)
        assert thorough == names


# ===================================================================
# 6. build_auditor_agent_definitions with prd_path
# ===================================================================

class TestBuildAuditorAgentDefinitionsPrdPath:
    """Verify prd_fidelity gating in build_auditor_agent_definitions."""

    def test_prd_fidelity_included_when_prd_path_provided(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path="docs/PRD.md",
        )
        assert "audit-prd-fidelity" in agents

    def test_prd_fidelity_excluded_when_no_prd_path(self):
        agents = build_auditor_agent_definitions(["prd_fidelity"])
        assert "audit-prd-fidelity" not in agents

    def test_prd_fidelity_excluded_when_prd_path_none(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path=None,
        )
        assert "audit-prd-fidelity" not in agents

    def test_prd_fidelity_excluded_when_prd_path_empty(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path="",
        )
        assert "audit-prd-fidelity" not in agents

    def test_other_auditors_unaffected_by_prd_path(self):
        agents = build_auditor_agent_definitions(
            ["requirements", "technical"],
            prd_path="docs/PRD.md",
        )
        assert "audit-requirements" in agents
        assert "audit-technical" in agents

    def test_full_auditor_list_with_prd(self):
        all_auditors = list(AUDITOR_NAMES)
        agents = build_auditor_agent_definitions(
            all_auditors,
            requirements_path=".agent-team/REQUIREMENTS.md",
            prd_path="docs/PRD.md",
        )
        # 6 auditors + scorer + comprehensive = 8
        assert len(agents) == 8
        assert "audit-prd-fidelity" in agents
        assert "audit-scorer" in agents

    def test_full_auditor_list_without_prd(self):
        all_auditors = list(AUDITOR_NAMES)
        agents = build_auditor_agent_definitions(
            all_auditors,
            requirements_path=".agent-team/REQUIREMENTS.md",
        )
        # 5 auditors + scorer + comprehensive = 7 (prd_fidelity skipped)
        assert len(agents) == 7
        assert "audit-prd-fidelity" not in agents
        assert "audit-scorer" in agents

    def test_prd_path_injected_into_prompt(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path="docs/PRD.md",
            requirements_path=".agent-team/REQUIREMENTS.md",
        )
        prompt = agents["audit-prd-fidelity"]["prompt"]
        assert "docs/PRD.md" in prompt
        assert "{prd_path}" not in prompt

    def test_requirements_path_injected_into_prd_fidelity(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path="docs/PRD.md",
            requirements_path=".agent-team/REQUIREMENTS.md",
        )
        prompt = agents["audit-prd-fidelity"]["prompt"]
        assert ".agent-team/REQUIREMENTS.md" in prompt
        assert "{requirements_path}" not in prompt

    def test_agent_key_uses_hyphens(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path="docs/PRD.md",
        )
        assert "audit-prd-fidelity" in agents
        assert "audit_prd_fidelity" not in agents

    def test_prd_fidelity_model_is_opus(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path="docs/PRD.md",
        )
        assert agents["audit-prd-fidelity"]["model"] == "opus"

    def test_prd_fidelity_tools_no_bash(self):
        """PRD fidelity auditor should NOT have Bash (read-only analysis)."""
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path="docs/PRD.md",
        )
        assert "Bash" not in agents["audit-prd-fidelity"]["tools"]

    def test_prd_fidelity_has_read_glob_grep(self):
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path="docs/PRD.md",
        )
        tools = agents["audit-prd-fidelity"]["tools"]
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools

    def test_scorer_still_included_when_prd_fidelity_skipped(self):
        agents = build_auditor_agent_definitions(["prd_fidelity"])
        assert "audit-scorer" in agents
        assert len(agents) == 2  # scorer + comprehensive

    def test_task_text_not_in_prd_fidelity(self):
        """task_text injection should only go to requirements auditor."""
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            task_text="Build a login page",
            prd_path="docs/PRD.md",
        )
        assert "Build a login page" not in agents["audit-prd-fidelity"]["prompt"]


# ===================================================================
# 7. AuditFinding compatibility with prd_fidelity
# ===================================================================

class TestPrdFidelityFindingFormat:
    """Verify PA-prefixed findings work with all audit_models functions."""

    def test_finding_creation(self):
        f = _make_prd_finding()
        assert f.finding_id == "PA-001"
        assert f.auditor == "prd_fidelity"

    def test_finding_to_dict_roundtrip(self):
        f = _make_prd_finding()
        d = f.to_dict()
        f2 = AuditFinding.from_dict(d)
        assert f2.finding_id == "PA-001"
        assert f2.auditor == "prd_fidelity"

    def test_prd_dropped_requirement_id(self):
        f = _make_prd_finding(requirement_id="PRD-DROPPED-003")
        assert f.requirement_id == "PRD-DROPPED-003"

    def test_primary_file_from_prd_evidence(self):
        f = _make_prd_finding(evidence=["prd.md:42 -- requirement dropped"])
        assert f.primary_file == "prd.md"

    def test_primary_file_from_requirements_evidence(self):
        f = _make_prd_finding(evidence=[".agent-team/REQUIREMENTS.md:10 -- orphaned"])
        assert f.primary_file == ".agent-team/REQUIREMENTS.md"


# ===================================================================
# 8. Scoring compatibility
# ===================================================================

class TestPrdFidelityScoringCompatibility:
    """Verify PA findings integrate with AuditScore.compute."""

    def test_single_pa_fail_score(self):
        findings = [_make_prd_finding(verdict="FAIL")]
        score = AuditScore.compute(findings)
        assert score.total_items == 1
        assert score.failed == 1
        assert score.score == 0.0

    def test_single_pa_pass_score(self):
        findings = [_make_prd_finding(verdict="PASS", severity="INFO")]
        score = AuditScore.compute(findings)
        assert score.total_items == 1
        assert score.passed == 1
        assert score.score == 100.0

    def test_mixed_auditor_findings(self):
        findings = [
            _make_other_finding(requirement_id="REQ-001", verdict="PASS", severity="INFO"),
            _make_prd_finding(requirement_id="PRD-DROPPED-001", verdict="FAIL"),
            _make_other_finding(
                finding_id="TA-001", auditor="technical",
                requirement_id="TECH-001", verdict="PASS", severity="INFO",
            ),
        ]
        score = AuditScore.compute(findings)
        assert score.total_items == 3
        assert score.passed == 2
        assert score.failed == 1

    def test_prd_findings_in_severity_counts(self):
        findings = [
            _make_prd_finding(finding_id="PA-001", severity="HIGH"),
            _make_prd_finding(finding_id="PA-002", severity="MEDIUM", requirement_id="PRD-DROPPED-002"),
            _make_prd_finding(finding_id="PA-003", severity="LOW", requirement_id="PRD-DROPPED-003"),
        ]
        score = AuditScore.compute(findings)
        assert score.high_count == 1
        assert score.medium_count == 1
        assert score.low_count == 1


# ===================================================================
# 9. Deduplication compatibility
# ===================================================================

class TestPrdFidelityDeduplication:
    """Verify PA findings work with deduplicate_findings."""

    def test_pa_findings_dedup_same_req(self):
        findings = [
            _make_prd_finding(finding_id="PA-001", requirement_id="PRD-DROPPED-001", confidence=0.7),
            _make_prd_finding(finding_id="PA-002", requirement_id="PRD-DROPPED-001", confidence=0.9),
        ]
        result = deduplicate_findings(findings)
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_pa_and_ra_different_req_no_dedup(self):
        findings = [
            _make_prd_finding(requirement_id="PRD-DROPPED-001"),
            _make_other_finding(requirement_id="REQ-001"),
        ]
        result = deduplicate_findings(findings)
        assert len(result) == 2

    def test_pa_general_findings_not_deduped(self):
        findings = [
            _make_prd_finding(finding_id="PA-001", requirement_id="GENERAL"),
            _make_prd_finding(finding_id="PA-002", requirement_id="GENERAL"),
        ]
        result = deduplicate_findings(findings)
        assert len(result) == 2


# ===================================================================
# 10. Fix task grouping compatibility
# ===================================================================

class TestPrdFidelityFixTasks:
    """Verify PA findings work with group_findings_into_fix_tasks."""

    def test_prd_fail_creates_fix_task(self):
        findings = [
            _make_prd_finding(verdict="FAIL", severity="HIGH",
                              evidence=["prd.md:10 -- dropped requirement"]),
        ]
        report = build_report("test-prd", 1, ["prd_fidelity"], findings)
        tasks = group_findings_into_fix_tasks(report)
        assert len(tasks) == 1

    def test_prd_pass_no_fix_task(self):
        findings = [
            _make_prd_finding(verdict="PASS", severity="INFO"),
        ]
        report = build_report("test-prd", 1, ["prd_fidelity"], findings)
        tasks = group_findings_into_fix_tasks(report)
        assert len(tasks) == 0

    def test_mixed_pa_and_ra_fix_tasks(self):
        findings = [
            _make_prd_finding(verdict="FAIL", severity="HIGH",
                              evidence=["prd.md:10 -- dropped"]),
            _make_other_finding(verdict="FAIL", severity="CRITICAL",
                                evidence=["src/app.ts:20 -- issue"]),
        ]
        report = build_report("test-mixed", 1, ["prd_fidelity", "requirements"], findings)
        tasks = group_findings_into_fix_tasks(report)
        assert len(tasks) == 2


# ===================================================================
# 11. Report integration
# ===================================================================

class TestPrdFidelityReportIntegration:
    """Verify PA findings in full report flow."""

    def test_report_with_prd_fidelity_auditor(self):
        findings = [
            _make_prd_finding(verdict="FAIL"),
            _make_other_finding(verdict="PASS", severity="INFO"),
        ]
        report = build_report("test-prd-report", 1, ["prd_fidelity", "requirements"], findings)
        assert len(report.findings) == 2
        assert "prd_fidelity" in report.auditors_deployed

    def test_report_by_severity_includes_pa(self):
        findings = [
            _make_prd_finding(severity="HIGH"),
        ]
        report = build_report("test-sev", 1, ["prd_fidelity"], findings)
        assert "HIGH" in report.by_severity
        assert len(report.by_severity["HIGH"]) == 1

    def test_report_json_roundtrip_with_pa_findings(self):
        findings = [
            _make_prd_finding(),
            _make_other_finding(),
        ]
        report = build_report("test-rt", 1, ["prd_fidelity", "requirements"], findings)
        from agent_team_v15.audit_models import AuditReport
        json_str = report.to_json()
        report2 = AuditReport.from_json(json_str)
        assert len(report2.findings) == 2
        pa_findings = [f for f in report2.findings if f.auditor == "prd_fidelity"]
        assert len(pa_findings) == 1
        assert pa_findings[0].finding_id == "PA-001"


# ===================================================================
# 12. should_terminate_reaudit with PA findings
# ===================================================================

class TestPrdFidelityReauditTermination:
    """Verify reaudit logic works with PA-enriched scores."""

    def _make_score(self, score: float = 90.0, critical: int = 0) -> AuditScore:
        return AuditScore(
            total_items=10, passed=9, failed=1, partial=0,
            critical_count=critical, high_count=0, medium_count=1,
            low_count=0, info_count=0, score=score, health="degraded",
        )

    def test_healthy_score_with_pa_findings_terminates(self):
        score = self._make_score(score=95.0)
        stop, reason = should_terminate_reaudit(score, None, cycle=1)
        assert stop is True
        assert reason == "healthy"


# ===================================================================
# 13. Regression: existing auditor count tests
# ===================================================================

class TestRegressionExistingAuditors:
    """Verify original 5 auditors are intact after adding 6th."""

    def test_requirements_still_in_names(self):
        assert "requirements" in AUDITOR_NAMES

    def test_technical_still_in_names(self):
        assert "technical" in AUDITOR_NAMES

    def test_interface_still_in_names(self):
        assert "interface" in AUDITOR_NAMES

    def test_test_still_in_names(self):
        assert "test" in AUDITOR_NAMES

    def test_mcp_library_still_in_names(self):
        assert "mcp_library" in AUDITOR_NAMES

    def test_standard_depth_unchanged(self):
        auditors = get_auditors_for_depth("standard")
        assert set(auditors) == {"requirements", "technical", "interface"}

    def test_quick_depth_unchanged(self):
        auditors = get_auditors_for_depth("quick")
        assert auditors == []

    def test_build_definitions_original_auditors_unaffected(self):
        agents = build_auditor_agent_definitions(
            ["requirements", "technical", "interface"],
            requirements_path=".agent-team/REQUIREMENTS.md",
        )
        assert "audit-requirements" in agents
        assert "audit-technical" in agents
        assert "audit-interface" in agents
        assert "audit-scorer" in agents
        assert len(agents) == 5  # 3 auditors + scorer + comprehensive

    def test_all_original_prefixes_preserved(self):
        assert AUDITOR_PREFIXES["requirements"] == "RA"
        assert AUDITOR_PREFIXES["technical"] == "TA"
        assert AUDITOR_PREFIXES["interface"] == "IA"
        assert AUDITOR_PREFIXES["test"] == "XA"
        assert AUDITOR_PREFIXES["mcp_library"] == "MA"


# ===================================================================
# 14. Edge cases
# ===================================================================

class TestPrdFidelityEdgeCases:
    """Edge cases specific to PRD fidelity auditor."""

    def test_empty_prd_path_treated_as_no_prd(self):
        """Empty string prd_path should behave like None."""
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path="",
        )
        assert "audit-prd-fidelity" not in agents

    def test_prd_fidelity_with_only_scorer(self):
        """When prd_fidelity is skipped, only scorer remains."""
        agents = build_auditor_agent_definitions(
            ["prd_fidelity"],
            prd_path=None,
        )
        assert len(agents) == 2  # scorer + comprehensive
        assert "audit-scorer" in agents

    def test_multiple_dropped_findings(self):
        """Multiple DROPPED findings should all be independently scored."""
        findings = [
            _make_prd_finding(finding_id=f"PA-{i:03d}", requirement_id=f"PRD-DROPPED-{i:03d}")
            for i in range(5)
        ]
        score = AuditScore.compute(findings)
        assert score.total_items == 5
        assert score.failed == 5

    def test_distorted_as_partial(self):
        """DISTORTED findings should use PARTIAL verdict."""
        f = _make_prd_finding(
            finding_id="PA-010",
            requirement_id="REQ-DESIGN-001",
            verdict="PARTIAL",
            severity="MEDIUM",
            summary="Acceptance criteria materially changed",
        )
        findings = [f]
        score = AuditScore.compute(findings)
        assert score.partial == 1

    def test_orphaned_as_low_severity(self):
        """ORPHANED findings with LOW severity are acceptable."""
        f = _make_prd_finding(
            finding_id="PA-020",
            requirement_id="REQ-EXTRA-001",
            verdict="FAIL",
            severity="LOW",
            summary="Requirement has no PRD basis",
        )
        findings = [f]
        score = AuditScore.compute(findings)
        assert score.low_count == 1
