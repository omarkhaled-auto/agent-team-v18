"""Phase G Slice 4a — Wave A.5 (Codex plan review).

Covers ``wave_a5_t5.build_wave_a5_prompt`` + ``wave_a5_should_skip`` +
``WAVE_A5_OUTPUT_SCHEMA``. The live Codex dispatch is async and requires
the transport to be reachable — tests here exercise the prompt shape,
skip conditions, and schema structure without invoking the network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_a5_t5 import (
    WAVE_A5_OUTPUT_SCHEMA,
    build_wave_a5_prompt,
    wave_a5_should_skip,
)


def _config(*, enabled: bool = True, skip_simple: bool = True) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a5_enabled = enabled
    cfg.v18.wave_a5_skip_simple_milestones = skip_simple
    return cfg


def _milestone(complexity: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        id="M1",
        title="Orders",
        template="full_stack",
        complexity=complexity,
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


def test_output_schema_declares_verdict_enum() -> None:
    schema = WAVE_A5_OUTPUT_SCHEMA
    verdict = schema["properties"]["verdict"]
    assert set(verdict["enum"]) == {"PASS", "FAIL", "UNCERTAIN"}


def test_output_schema_required_keys() -> None:
    schema = WAVE_A5_OUTPUT_SCHEMA
    assert set(schema["required"]) == {"verdict", "findings"}
    assert schema.get("additionalProperties") is False


def test_output_schema_finding_item_shape() -> None:
    finding = WAVE_A5_OUTPUT_SCHEMA["properties"]["findings"]["items"]
    assert set(finding["required"]) == {
        "category",
        "severity",
        "ref",
        "issue",
        "suggested_fix",
    }
    cat = finding["properties"]["category"]["enum"]
    assert "missing_endpoint" in cat
    assert "unrealistic_scope" in cat


# ---------------------------------------------------------------------------
# Prompt shape
# ---------------------------------------------------------------------------


def test_prompt_embeds_output_schema_json_verbatim() -> None:
    prompt = build_wave_a5_prompt(
        plan_text="SEED_PLAN",
        requirements_text="SEED_REQ",
        architecture_text="SEED_ARCH",
    )
    assert "output_schema" in prompt
    # The embedded JSON schema must parse back to the canonical dict.
    snippet_start = prompt.index('{\n  "type": "object"')
    snippet = prompt[snippet_start:]
    # Find the matching closing brace — search for trailing newlines block
    tail = snippet.find("\n\nFinal assistant")
    parsed = json.loads(snippet[:tail])
    assert parsed == WAVE_A5_OUTPUT_SCHEMA


def test_prompt_contains_rules_and_missing_context_gating() -> None:
    prompt = build_wave_a5_prompt(
        plan_text="SEED_PLAN",
        requirements_text="SEED_REQ",
        architecture_text="SEED_ARCH",
    )
    assert "<rules>" in prompt
    assert "<missing_context_gating>" in prompt
    # Inputs surface verbatim inside the XML blocks.
    assert "SEED_PLAN" in prompt
    assert "SEED_REQ" in prompt
    assert "SEED_ARCH" in prompt


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------


def test_skip_when_flag_off() -> None:
    skip, reason = wave_a5_should_skip(
        config=_config(enabled=False),
        milestone=_milestone(),
        template="full_stack",
        plan_text="Order, Customer",
        requirements_text="- AC-1: foo\n- AC-2: bar",
    )
    assert skip is True
    assert "wave_a5_enabled=False" in reason


def test_skip_for_frontend_only_template() -> None:
    skip, reason = wave_a5_should_skip(
        config=_config(),
        milestone=_milestone(),
        template="frontend_only",
        plan_text="Order",
        requirements_text="- AC-1: foo",
    )
    assert skip is True
    assert "frontend_only" in reason


def test_skip_for_simple_complexity() -> None:
    skip, reason = wave_a5_should_skip(
        config=_config(),
        milestone=_milestone(complexity="simple"),
        template="full_stack",
        plan_text="large plan with many entities",
        requirements_text="- AC-1\n- AC-2\n- AC-3\n- AC-4\n- AC-5\n- AC-6\n- AC-7",
    )
    assert skip is True
    assert "simple" in reason


def test_skip_below_entity_and_ac_thresholds() -> None:
    """Standard complexity + tiny plan + tiny AC list → heuristic skip."""
    skip, _ = wave_a5_should_skip(
        config=_config(skip_simple=True),
        milestone=_milestone(complexity="standard"),
        template="full_stack",
        plan_text="",  # 0 entities
        requirements_text="- AC-1: only one AC",  # 1 AC
    )
    assert skip is True


def test_do_not_skip_when_above_thresholds() -> None:
    plan_text = "\n".join(
        f"### Entity{i}" for i in range(1, 6)
    )
    ac_text = "\n".join(f"- AC-{i}: foo" for i in range(1, 8))
    skip, _ = wave_a5_should_skip(
        config=_config(skip_simple=True),
        milestone=_milestone(complexity="standard"),
        template="full_stack",
        plan_text=plan_text,
        requirements_text=ac_text,
    )
    assert skip is False
