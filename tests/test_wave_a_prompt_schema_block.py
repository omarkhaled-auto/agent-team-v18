"""Phase H1b — Wave A prompt schema-block rendering tests.

Verifies ``_render_wave_a_schema_block`` + its callsite in
``build_wave_a_prompt`` behave as documented:

* Flag OFF → no ``[ARCHITECTURE.md SCHEMA]`` block.
* Flag ON + ``architecture_md_enabled`` ON → block fully rendered.
* Flag ON + ``architecture_md_enabled`` OFF → silent no-op.
* STRUCTURAL: the rendered block has no fabricated ``{placeholder}`` /
  ``${VAR}`` residues (anti-pattern #4).
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest

from agent_team_v15 import wave_a_schema
from agent_team_v15.agents import _render_wave_a_schema_block, build_wave_a_prompt
from agent_team_v15.config import AgentTeamConfig


def _milestone(mid: str = "milestone-3") -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        title="Orders",
        template="full_stack",
        description="orders milestone",
        dependencies=[],
        feature_refs=[],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _ir() -> dict[str, Any]:
    return {
        "entities": [{"name": "Order", "fields": [{"name": "id", "type": "string"}]}],
        "endpoints": [],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [],
    }


def _cfg(*, schema_on: bool, arch_on: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a_schema_enforcement_enabled = schema_on
    cfg.v18.architecture_md_enabled = arch_on
    return cfg


# ---------------------------------------------------------------------------
# Helper-level rendering
# ---------------------------------------------------------------------------


def test_render_returns_list_of_lines() -> None:
    lines = _render_wave_a_schema_block("milestone-1")
    assert isinstance(lines, list) and lines
    assert all(isinstance(l, str) for l in lines)


def test_rendered_body_enumerates_allowed_sections() -> None:
    body = "\n".join(_render_wave_a_schema_block("milestone-1"))
    for canonical in wave_a_schema.ALLOWED_SECTIONS:
        assert canonical in body, (
            f"Canonical section {canonical!r} not listed in rendered block"
        )


def test_rendered_body_enumerates_disallow_reasons() -> None:
    body = "\n".join(_render_wave_a_schema_block("milestone-1"))
    for _, reason_code, _ in wave_a_schema.DISALLOWED_SECTION_REASONS:
        assert reason_code in body


def test_rendered_body_enumerates_allowed_references() -> None:
    body = "\n".join(_render_wave_a_schema_block("milestone-1"))
    for ref in wave_a_schema.ALLOWED_REFERENCES:
        assert ref in body


def test_rendered_body_mentions_pattern_ids() -> None:
    body = "\n".join(_render_wave_a_schema_block("milestone-1"))
    assert wave_a_schema.PATTERN_UNDECLARED_REFERENCE in body


# ---------------------------------------------------------------------------
# Wiring via build_wave_a_prompt
# ---------------------------------------------------------------------------


def test_block_absent_when_schema_flag_off() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_cfg(schema_on=False, arch_on=True),
        existing_prompt_framework="FRAMEWORK",
    )
    assert "[ARCHITECTURE.md SCHEMA" not in prompt


def test_block_present_when_both_flags_on() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_cfg(schema_on=True, arch_on=True),
        existing_prompt_framework="FRAMEWORK",
    )
    assert "[ARCHITECTURE.md SCHEMA" in prompt


def test_block_absent_when_architecture_md_disabled() -> None:
    """Schema flag ON but architecture_md_enabled OFF → silent no-op."""
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_cfg(schema_on=True, arch_on=False),
        existing_prompt_framework="FRAMEWORK",
    )
    assert "[ARCHITECTURE.md SCHEMA" not in prompt


# ---------------------------------------------------------------------------
# STRUCTURAL anti-pattern #4: no fabricated placeholders in rendered body
# ---------------------------------------------------------------------------


_BRACE_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_DOLLAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

# Legitimate sentinel tokens allowed in the rendered prompt (they are the
# documented reference vocabulary, not unsubstituted placeholders).
_KNOWN_SAFE_TOKENS = set(wave_a_schema.ALLOWED_REFERENCES)


def _extract_rendered_schema_block(prompt: str) -> str:
    marker = "[ARCHITECTURE.md SCHEMA"
    idx = prompt.find(marker)
    assert idx != -1, "[ARCHITECTURE.md SCHEMA not found in prompt"
    # Take from marker to end of prompt — adequately covers the block.
    return prompt[idx:]


def test_rendered_block_has_no_unsubstituted_placeholders() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(mid="milestone-7"),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=["apps/api/src/main.ts"],
        config=_cfg(schema_on=True, arch_on=True),
        existing_prompt_framework="FRAMEWORK",
    )
    block = _extract_rendered_schema_block(prompt)

    # Any ``{var}`` token inside the schema block must either be a
    # legitimate reference the schema teaches (e.g. ``{scaffolded_files}``)
    # or MUST NOT appear at all.
    for m in _BRACE_PATTERN.finditer(block):
        token = m.group(1)
        assert token in _KNOWN_SAFE_TOKENS, (
            f"Unsubstituted placeholder {{{token}}} leaked into rendered "
            f"schema block. Anti-pattern #4 triggered."
        )

    # No ``${VAR}`` shell-style placeholder should ever appear in the
    # rendered schema teaching block.
    dollar_matches = _DOLLAR_PATTERN.findall(block)
    assert not dollar_matches, (
        f"Shell-style ${{VAR}} placeholders leaked into rendered schema "
        f"block: {dollar_matches!r}"
    )


def test_rendered_block_interpolates_milestone_id() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(mid="milestone-9"),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=_cfg(schema_on=True, arch_on=True),
        existing_prompt_framework="FRAMEWORK",
    )
    block = _extract_rendered_schema_block(prompt)
    # Path anchor: "`.agent-team/milestone-{mid}/ARCHITECTURE.md`" — must
    # contain the literal milestone id, not a placeholder.
    assert ".agent-team/milestone-milestone-9/ARCHITECTURE.md" in block
