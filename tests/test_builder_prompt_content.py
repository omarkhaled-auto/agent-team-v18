"""Tests that Wave 2 mandates were injected into prompts and builder."""

from __future__ import annotations

from pathlib import Path


def test_serialization_mandate_in_comprehensive_prompt():
    from agent_team_v15.audit_prompts import COMPREHENSIVE_AUDITOR_PROMPT
    assert "SERIALIZATION CONVENTION" in COMPREHENSIVE_AUDITOR_PROMPT
    assert "camelCase" in COMPREHENSIVE_AUDITOR_PROMPT
    assert "forbidNonWhitelisted" in COMPREHENSIVE_AUDITOR_PROMPT


def test_serialization_mandate_in_interface_prompt():
    from agent_team_v15.audit_prompts import AUDIT_PROMPTS
    interface_prompt = AUDIT_PROMPTS.get("interface")
    assert interface_prompt is not None
    assert "SERIALIZATION CONVENTION" in interface_prompt


def test_structured_output_in_auditor_prompts():
    from agent_team_v15.audit_prompts import AUDIT_PROMPTS
    # The scorer prompt is special — it collects findings, not produces them.
    auditor_keys = [k for k in AUDIT_PROMPTS if k != "scorer"]
    for key in auditor_keys:
        prompt = AUDIT_PROMPTS[key]
        assert "```findings" in prompt, f"Prompt '{key}' missing findings fence instruction"


def test_infrastructure_deliverables_in_coordinated_builder():
    source = Path("C:/Projects/agent-team-v15/src/agent_team_v15/coordinated_builder.py").read_text(encoding="utf-8")
    assert "_check_infrastructure_deliverables" in source
    assert "Dockerfile" in source
    assert "docker-compose" in source
    assert "migration" in source.lower()


def test_migration_generation_in_coordinated_builder():
    source = Path("C:/Projects/agent-team-v15/src/agent_team_v15/coordinated_builder.py").read_text(encoding="utf-8")
    assert "_run_migration_generation" in source
    assert "typeorm" in source.lower() or "prisma" in source.lower()
