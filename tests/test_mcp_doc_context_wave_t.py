"""Phase G Slice 5b — mcp_doc_context injection into Wave T prompt.

Pre-fetched Jest/Vitest/Playwright idioms surface as a
``<framework_idioms>`` block when
``v18.mcp_doc_context_wave_t_enabled=True`` AND a non-empty
``mcp_doc_context`` is passed through. Flag OFF or empty content → omitted.
``WAVE_T_CORE_PRINCIPLE`` is LOCKED and untouched by this injection.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_team_v15.agents import WAVE_T_CORE_PRINCIPLE, build_wave_t_prompt
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
        "entities": [],
        "endpoints": [],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [],
    }


def _config(*, flag: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.mcp_doc_context_wave_t_enabled = flag
    return cfg


def test_wave_t_injects_framework_idioms_when_flag_on() -> None:
    prompt = build_wave_t_prompt(
        milestone=_milestone(),
        ir=_ir(),
        wave_artifacts={},
        config=_config(flag=True),
        existing_prompt_framework="FRAMEWORK",
        mcp_doc_context="// Jest describe/test idiom\ndescribe('x', () => { test('y', () => {}) })",
    )
    assert "<framework_idioms>" in prompt
    assert "Jest describe/test idiom" in prompt


def test_wave_t_omits_framework_idioms_when_flag_off() -> None:
    prompt = build_wave_t_prompt(
        milestone=_milestone(),
        ir=_ir(),
        wave_artifacts={},
        config=_config(flag=False),
        existing_prompt_framework="FRAMEWORK",
        mcp_doc_context="// some context",
    )
    assert "<framework_idioms>" not in prompt


def test_wave_t_omits_framework_idioms_on_empty_content() -> None:
    prompt = build_wave_t_prompt(
        milestone=_milestone(),
        ir=_ir(),
        wave_artifacts={},
        config=_config(flag=True),
        existing_prompt_framework="FRAMEWORK",
        mcp_doc_context="",
    )
    assert "<framework_idioms>" not in prompt


def test_wave_t_preserves_locked_core_principle_verbatim() -> None:
    """WAVE_T_CORE_PRINCIPLE is LOCKED (agents.py:8374-8388). mcp_doc_context
    injection MUST NOT paraphrase or drop the principle."""
    prompt = build_wave_t_prompt(
        milestone=_milestone(),
        ir=_ir(),
        wave_artifacts={},
        config=_config(flag=True),
        existing_prompt_framework="FRAMEWORK",
        mcp_doc_context="// idiom",
    )
    assert WAVE_T_CORE_PRINCIPLE in prompt
