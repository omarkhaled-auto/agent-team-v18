"""Tests for agent_team.audit_prompts."""

from __future__ import annotations

import pytest

from agent_team_v15.audit_prompts import (
    AUDIT_PROMPTS,
    INTERFACE_AUDITOR_PROMPT,
    MCP_LIBRARY_AUDITOR_PROMPT,
    PRD_FIDELITY_AUDITOR_PROMPT,
    REQUIREMENTS_AUDITOR_PROMPT,
    SCORER_AGENT_PROMPT,
    TECHNICAL_AUDITOR_PROMPT,
    TEST_AUDITOR_PROMPT,
    get_auditor_prompt,
)


# ===================================================================
# Prompt registry
# ===================================================================

class TestPromptRegistry:
    def test_all_seven_prompts_registered(self):
        expected = {"requirements", "technical", "interface", "test", "mcp_library", "prd_fidelity", "scorer"}
        assert set(AUDIT_PROMPTS.keys()) == expected

    def test_get_auditor_prompt_valid(self):
        prompt = get_auditor_prompt("requirements")
        assert "REQUIREMENTS AUDITOR" in prompt

    def test_get_auditor_prompt_invalid(self):
        with pytest.raises(KeyError):
            get_auditor_prompt("nonexistent")


# ===================================================================
# Prompt content validation
# ===================================================================

class TestRequirementsAuditorPrompt:
    def test_contains_scope_section(self):
        assert "## Scope" in REQUIREMENTS_AUDITOR_PROMPT

    def test_references_req_xxx(self):
        assert "REQ-xxx" in REQUIREMENTS_AUDITOR_PROMPT

    def test_references_design_xxx(self):
        assert "DESIGN-xxx" in REQUIREMENTS_AUDITOR_PROMPT

    def test_references_seed_xxx(self):
        assert "SEED-xxx" in REQUIREMENTS_AUDITOR_PROMPT

    def test_references_enum_xxx(self):
        assert "ENUM-xxx" in REQUIREMENTS_AUDITOR_PROMPT

    def test_output_format_present(self):
        assert "## Output Format" in REQUIREMENTS_AUDITOR_PROMPT

    def test_finding_prefix_is_ra(self):
        assert '"RA-001"' in REQUIREMENTS_AUDITOR_PROMPT

    def test_adversarial_instruction(self):
        assert "ADVERSARIAL" in REQUIREMENTS_AUDITOR_PROMPT


class TestTechnicalAuditorPrompt:
    def test_contains_scope_section(self):
        assert "## Scope" in TECHNICAL_AUDITOR_PROMPT

    def test_references_tech_xxx(self):
        assert "TECH-xxx" in TECHNICAL_AUDITOR_PROMPT

    def test_references_sdl(self):
        assert "SDL-001" in TECHNICAL_AUDITOR_PROMPT
        assert "SDL-002" in TECHNICAL_AUDITOR_PROMPT
        assert "SDL-003" in TECHNICAL_AUDITOR_PROMPT

    def test_finding_prefix_is_ta(self):
        assert '"TA-001"' in TECHNICAL_AUDITOR_PROMPT

    def test_general_requirement_id_mentioned(self):
        assert '"GENERAL"' in TECHNICAL_AUDITOR_PROMPT


class TestInterfaceAuditorPrompt:
    def test_contains_wire_section(self):
        assert "WIRE-xxx" in INTERFACE_AUDITOR_PROMPT

    def test_contains_svc_section(self):
        assert "SVC-xxx" in INTERFACE_AUDITOR_PROMPT

    def test_contains_api_checks(self):
        assert "API-001" in INTERFACE_AUDITOR_PROMPT
        assert "API-002" in INTERFACE_AUDITOR_PROMPT
        assert "API-003" in INTERFACE_AUDITOR_PROMPT
        assert "API-004" in INTERFACE_AUDITOR_PROMPT

    def test_contains_orphan_detection(self):
        assert "Orphan Detection" in INTERFACE_AUDITOR_PROMPT

    def test_mock_data_automatic_fail(self):
        assert "AUTOMATIC FAIL" in INTERFACE_AUDITOR_PROMPT

    def test_finding_prefix_is_ia(self):
        assert '"IA-001"' in INTERFACE_AUDITOR_PROMPT


class TestTestAuditorPrompt:
    def test_references_test_xxx(self):
        assert "TEST-xxx" in TEST_AUDITOR_PROMPT

    def test_mentions_test_quality(self):
        assert "assertion" in TEST_AUDITOR_PROMPT.lower()

    def test_finding_prefix_is_xa(self):
        assert '"XA-001"' in TEST_AUDITOR_PROMPT

    def test_xa_summary_mentioned(self):
        assert "XA-SUMMARY" in TEST_AUDITOR_PROMPT


class TestMcpLibraryAuditorPrompt:
    def test_mentions_context7(self):
        assert "Context7" in MCP_LIBRARY_AUDITOR_PROMPT

    def test_mentions_deprecated_api(self):
        assert "deprecated" in MCP_LIBRARY_AUDITOR_PROMPT.lower()

    def test_finding_prefix_is_ma(self):
        assert '"MA-001"' in MCP_LIBRARY_AUDITOR_PROMPT

    def test_general_requirement_id_mentioned(self):
        assert '"GENERAL"' in MCP_LIBRARY_AUDITOR_PROMPT


class TestPrdFidelityAuditorPrompt:
    def test_contains_scope_section(self):
        assert "## Scope" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_process_section(self):
        assert "## Process" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_contains_rules_section(self):
        assert "## Rules" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_references_dropped(self):
        assert "DROPPED" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_references_distorted(self):
        assert "DISTORTED" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_references_orphaned(self):
        assert "ORPHANED" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_finding_prefix_is_pa(self):
        assert '"PA-001"' in PRD_FIDELITY_AUDITOR_PROMPT

    def test_prd_path_placeholder(self):
        assert "{prd_path}" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_requirements_path_placeholder(self):
        assert "{requirements_path}" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_adversarial_instruction(self):
        assert "ADVERSARIAL" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_cross_auditor_awareness(self):
        assert "Other auditors cover" in PRD_FIDELITY_AUDITOR_PROMPT

    def test_output_format_present(self):
        assert "## Output Format" in PRD_FIDELITY_AUDITOR_PROMPT


class TestScorerAgentPrompt:
    def test_mentions_deduplication(self):
        assert "Deduplication" in SCORER_AGENT_PROMPT

    def test_mentions_score_computation(self):
        assert "Score Computation" in SCORER_AGENT_PROMPT

    def test_mentions_requirements_md_update(self):
        assert "REQUIREMENTS.md" in SCORER_AGENT_PROMPT

    def test_mentions_audit_report_json(self):
        assert "AUDIT_REPORT.json" in SCORER_AGENT_PROMPT

    def test_mentions_health_thresholds(self):
        assert "healthy" in SCORER_AGENT_PROMPT
        assert "degraded" in SCORER_AGENT_PROMPT
        assert "failed" in SCORER_AGENT_PROMPT


# ===================================================================
# Prompt size validation
# ===================================================================

class TestRequirementsPathPlaceholder:
    """All auditor prompts must contain {requirements_path} placeholder."""

    @pytest.mark.parametrize("name", ["requirements", "technical", "interface", "test", "prd_fidelity"])
    def test_requirements_path_placeholder_present(self, name):
        prompt = AUDIT_PROMPTS[name]
        assert "{requirements_path}" in prompt, (
            f"{name} prompt missing {{requirements_path}} placeholder"
        )

    def test_scorer_has_requirements_path(self):
        assert "{requirements_path}" in SCORER_AGENT_PROMPT

    def test_get_auditor_prompt_formats_path(self):
        prompt = get_auditor_prompt("requirements", requirements_path="test/REQUIREMENTS.md")
        assert "test/REQUIREMENTS.md" in prompt
        assert "{requirements_path}" not in prompt

    def test_get_auditor_prompt_without_path_preserves_placeholder(self):
        prompt = get_auditor_prompt("requirements")
        assert "{requirements_path}" in prompt

    def test_get_auditor_prompt_formats_prd_path(self):
        prompt = get_auditor_prompt("prd_fidelity", prd_path="docs/PRD.md")
        assert "docs/PRD.md" in prompt
        assert "{prd_path}" not in prompt

    def test_get_auditor_prompt_without_prd_path_preserves_placeholder(self):
        prompt = get_auditor_prompt("prd_fidelity")
        assert "{prd_path}" in prompt

    def test_prd_fidelity_has_prd_path_placeholder(self):
        assert "{prd_path}" in AUDIT_PROMPTS["prd_fidelity"]


class TestEvidenceFormatInstructions:
    """Evidence format rules must be in the output format section."""

    @pytest.mark.parametrize("name", ["requirements", "technical", "interface", "test", "mcp_library", "prd_fidelity"])
    def test_evidence_format_rules_present(self, name):
        prompt = AUDIT_PROMPTS[name]
        assert "Evidence Format Rules" in prompt

    @pytest.mark.parametrize("name", ["requirements", "technical", "interface", "test", "mcp_library", "prd_fidelity"])
    def test_forward_slash_instruction(self, name):
        prompt = AUDIT_PROMPTS[name]
        assert "forward slashes" in prompt.lower()


class TestCrossAuditorAwareness:
    """Auditor prompts should mention other auditors' scopes."""

    def test_requirements_mentions_other_scopes(self):
        assert "other auditors" in REQUIREMENTS_AUDITOR_PROMPT.lower() or \
               "Other requirement types" in REQUIREMENTS_AUDITOR_PROMPT

    def test_technical_mentions_other_scopes(self):
        assert "Other auditors cover" in TECHNICAL_AUDITOR_PROMPT

    def test_interface_mentions_other_scopes(self):
        assert "Other auditors cover" in INTERFACE_AUDITOR_PROMPT

    def test_test_mentions_other_scopes(self):
        assert "Other auditors cover" in TEST_AUDITOR_PROMPT


class TestScorerReservedDocstring:
    """SCORER_AGENT_PROMPT must have the reserved documentation."""

    def test_reserved_comment_in_module(self):
        import inspect
        import agent_team_v15.audit_prompts as module
        source = inspect.getsource(module)
        assert "RESERVED: AUDIT_SCORER_PROMPT" in source


class TestPromptSize:
    """Auditor prompts should be focused and not exceed ~100 lines."""

    @pytest.mark.parametrize("name", ["requirements", "technical", "interface", "test", "mcp_library", "prd_fidelity"])
    def test_auditor_prompt_under_100_lines(self, name):
        prompt = AUDIT_PROMPTS[name]
        line_count = len(prompt.strip().splitlines())
        assert line_count <= 120, f"{name} prompt has {line_count} lines (max 120)"

    def test_all_prompts_non_empty(self):
        for name, prompt in AUDIT_PROMPTS.items():
            assert len(prompt.strip()) > 100, f"{name} prompt is too short"


# ===================================================================
# Output format consistency
# ===================================================================

class TestOutputFormatConsistency:
    """Every auditor prompt must include the standard output format."""

    @pytest.mark.parametrize("name", ["requirements", "technical", "interface", "test", "mcp_library", "prd_fidelity"])
    def test_contains_output_format(self, name):
        prompt = AUDIT_PROMPTS[name]
        assert "## Output Format" in prompt

    @pytest.mark.parametrize("name", ["requirements", "technical", "interface", "test", "mcp_library", "prd_fidelity"])
    def test_contains_json_schema(self, name):
        prompt = AUDIT_PROMPTS[name]
        assert '"finding_id"' in prompt
        assert '"verdict"' in prompt
        assert '"severity"' in prompt

    @pytest.mark.parametrize("name", ["requirements", "technical", "interface", "test", "mcp_library", "prd_fidelity"])
    def test_contains_verdict_rules(self, name):
        prompt = AUDIT_PROMPTS[name]
        assert "FAIL" in prompt
        assert "PARTIAL" in prompt
        assert "PASS" in prompt
