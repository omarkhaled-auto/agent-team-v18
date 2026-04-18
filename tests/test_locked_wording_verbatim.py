"""Phase G — LOCKED wording verbatim + isolation guard.

Three blocks are LOCKED in the V18 codebase. They must appear byte-
identical everywhere they're referenced, and they MUST NOT be
duplicated into the project-convention files (CLAUDE.md / AGENTS.md
templates) — that would over-constrain Claude at the wrong layer
(per Wave 1c §4.4).

The three LOCKED blocks are:

1. ``cli._ANTI_BAND_AID_FIX_RULES`` — the "FIX MODE - ROOT CAUSE ONLY"
   banner used by both the Claude fix prompt and the Codex compile-fix
   prompt. sha256 prefix: ``6c3d540096ff2ed0``.
2. ``agents.WAVE_T_CORE_PRINCIPLE`` — the "code is wrong, not the test"
   principle used by Wave T + test-fix iteration prompts.
3. The IMMUTABLE rule (``packages/api-client/*`` is the frozen Wave C
   deliverable) appearing inside the Wave D / Wave D.5 prompt bodies.

This module is the canary: any edit to the canonical source text (even a
whitespace change) fails this test so the author has to decide whether
they really meant to re-baseline the LOCKED material.
"""

from __future__ import annotations

import hashlib

from agent_team_v15 import constitution_templates as _ct
from agent_team_v15.agents import (
    WAVE_T_CORE_PRINCIPLE,
    build_wave_d_prompt,
)
from agent_team_v15.cli import _ANTI_BAND_AID_FIX_RULES
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.codex_fix_prompts import build_codex_compile_fix_prompt


# ---------------------------------------------------------------------------
# 1. Pinned sha256 prefixes — the bytes are frozen.
# ---------------------------------------------------------------------------


ANTI_BAND_AID_SHA256_PREFIX = "6c3d540096ff2ed0"
WAVE_T_CORE_PRINCIPLE_SHA256_PREFIX = "44e0fec87e6225f3"


def _prefix(blob: str) -> str:
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def test_anti_band_aid_sha256_prefix_matches_pinned() -> None:
    assert _prefix(_ANTI_BAND_AID_FIX_RULES) == ANTI_BAND_AID_SHA256_PREFIX


def test_wave_t_core_principle_sha256_prefix_matches_pinned() -> None:
    assert _prefix(WAVE_T_CORE_PRINCIPLE) == WAVE_T_CORE_PRINCIPLE_SHA256_PREFIX


# ---------------------------------------------------------------------------
# 2. Content sentinels — a subset of load-bearing phrases that must stay.
# ---------------------------------------------------------------------------


def test_anti_band_aid_contains_load_bearing_phrases() -> None:
    for phrase in (
        "[FIX MODE - ROOT CAUSE ONLY]",
        "Surface patches are FORBIDDEN",
        "BANNED:",
        "REQUIRED approach:",
        "STRUCTURAL note",
    ):
        assert phrase in _ANTI_BAND_AID_FIX_RULES, f"Missing {phrase!r}"


def test_wave_t_core_principle_contains_load_bearing_phrases() -> None:
    for phrase in (
        "THE CODE IS WRONG",
        "NEVER weaken an assertion",
        "NEVER mock away real behavior",
        "The test is the specification",
    ):
        assert phrase in WAVE_T_CORE_PRINCIPLE, f"Missing {phrase!r}"


# ---------------------------------------------------------------------------
# 3. IMMUTABLE rule present verbatim inside the Wave D prompt body.
# ---------------------------------------------------------------------------


def test_wave_d_prompt_carries_immutable_api_client_rule_verbatim() -> None:
    from types import SimpleNamespace

    milestone = SimpleNamespace(
        id="M1",
        title="Orders",
        template="full_stack",
        description="",
        dependencies=[],
        feature_refs=[],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )
    ir = {
        "entities": [],
        "endpoints": [],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [],
    }
    for merged in (True, False):
        prompt = build_wave_d_prompt(
            milestone=milestone,
            ir=ir,
            wave_c_artifact=None,
            scaffolded_files=[],
            config=AgentTeamConfig(),
            existing_prompt_framework="FRAMEWORK",
            merged=merged,
        )
        # The EXACT LOCKED sentence tree.
        assert (
            "Do NOT edit, refactor, or add files under `packages/api-client/*`"
            in prompt
        )
        assert "frozen Wave C deliverable" in prompt


# ---------------------------------------------------------------------------
# 4. Isolation — LOCKED wording MUST NOT leak into CLAUDE.md / AGENTS.md.
# ---------------------------------------------------------------------------


def test_locked_wording_not_duplicated_into_claude_md_template() -> None:
    rendered = _ct.render_claude_md()
    for sentinel in (
        "[FIX MODE - ROOT CAUSE ONLY]",
        "Surface patches are FORBIDDEN",
        "NEVER weaken an assertion",
        "THE CODE IS WRONG",
    ):
        assert sentinel not in rendered, (
            f"LOCKED sentinel leaked into CLAUDE.md template: {sentinel!r}"
        )


def test_locked_wording_not_duplicated_into_agents_md_template() -> None:
    rendered = _ct.render_agents_md()
    for sentinel in (
        "[FIX MODE - ROOT CAUSE ONLY]",
        "Surface patches are FORBIDDEN",
        "NEVER weaken an assertion",
        "THE CODE IS WRONG",
    ):
        assert sentinel not in rendered, (
            f"LOCKED sentinel leaked into AGENTS.md template: {sentinel!r}"
        )


# ---------------------------------------------------------------------------
# 5. Codex compile-fix shell carries the LOCKED block byte-identical.
# ---------------------------------------------------------------------------


def test_codex_compile_fix_prompt_inlines_anti_band_aid_verbatim() -> None:
    prompt = build_codex_compile_fix_prompt(
        errors=[],
        wave_letter="B",
        milestone_id="M1",
        milestone_title="Users",
        iteration=0,
        max_iterations=3,
        previous_error_count=None,
        current_error_count=0,
        build_command="",
        anti_band_aid_rules=_ANTI_BAND_AID_FIX_RULES,
    )
    assert _ANTI_BAND_AID_FIX_RULES in prompt
