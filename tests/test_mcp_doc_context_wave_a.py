"""Phase G Slice 5a — mcp_doc_context injection into Wave A prompt.

Pre-fetched Prisma/TypeORM framework idioms surface as a
``<framework_idioms>...</framework_idioms>`` block when
``v18.mcp_doc_context_wave_a_enabled=True`` AND a non-empty
``mcp_doc_context`` is passed through. Flag OFF or empty content → the
block is omitted entirely (byte-identical pre-Phase-G shape).
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_team_v15.agents import build_wave_a_prompt
from agent_team_v15.config import AgentTeamConfig


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(
        id="M1",
        title="Users",
        template="full_stack",
        description="",
        dependencies=[],
        feature_refs=[],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _ir() -> dict[str, object]:
    return {
        "entities": [{"name": "User", "fields": [{"name": "id", "type": "string"}]}],
        "endpoints": [],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [],
    }


def _config(*, flag: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.mcp_doc_context_wave_a_enabled = flag
    return cfg


def test_wave_a_injects_framework_idioms_when_flag_on() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config(flag=True),
        existing_prompt_framework="FRAMEWORK",
        mcp_doc_context="// Prisma schema example\nmodel User { id String @id }",
    )
    assert "<framework_idioms>" in prompt
    assert "</framework_idioms>" in prompt
    assert "Prisma schema example" in prompt
    assert "model User { id String @id }" in prompt


def test_wave_a_omits_framework_idioms_when_flag_off() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config(flag=False),
        existing_prompt_framework="FRAMEWORK",
        mcp_doc_context="// Prisma schema example",
    )
    assert "<framework_idioms>" not in prompt


def test_wave_a_omits_framework_idioms_on_empty_content() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config(flag=True),
        existing_prompt_framework="FRAMEWORK",
        mcp_doc_context="",
    )
    assert "<framework_idioms>" not in prompt


def test_wave_a_omits_framework_idioms_when_context_is_none() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config(flag=True),
        existing_prompt_framework="FRAMEWORK",
        mcp_doc_context=None,
    )
    assert "<framework_idioms>" not in prompt
