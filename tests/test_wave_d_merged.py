"""Phase G Slice 3 — merged Wave D prompt + IMMUTABLE verbatim + renames.

``build_wave_d_prompt(..., merged=True)`` combines functional +polish in a
single Claude pass. It preserves the LOCKED IMMUTABLE
``packages/api-client/`` rule verbatim (no paraphrase, no removal),
renames D.5's ``[CODEX OUTPUT TOPOGRAPHY]`` to ``[EXPECTED FILE LAYOUT]``
and ``[PRESERVE FOR WAVE T AND WAVE E]`` to
``[TEST ANCHOR CONTRACT - preserved for Wave T / E]``, and drops the
Codex-autonomy directives (Claude doesn't need them).
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_team_v15.agents import build_wave_d_prompt
from agent_team_v15.config import AgentTeamConfig


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(
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


def _ir() -> dict[str, object]:
    return {
        "entities": [],
        "endpoints": [
            {"method": "GET", "path": "/orders", "owner_feature": "F", "description": ""}
        ],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [
            {"id": "AC-1", "feature": "F", "text": "List orders"}
        ],
    }


def _prompt_merged() -> str:
    return build_wave_d_prompt(
        milestone=_milestone(),
        ir=_ir(),
        wave_c_artifact=None,
        scaffolded_files=[],
        config=AgentTeamConfig(),
        existing_prompt_framework="FRAMEWORK",
        merged=True,
    )


def _prompt_legacy() -> str:
    return build_wave_d_prompt(
        milestone=_milestone(),
        ir=_ir(),
        wave_c_artifact=None,
        scaffolded_files=[],
        config=AgentTeamConfig(),
        existing_prompt_framework="FRAMEWORK",
        merged=False,
    )


def test_merged_prompt_banner_present() -> None:
    prompt = _prompt_merged()
    assert "[WAVE D - FRONTEND SPECIALIST (merged functional + polish)]" in prompt


def test_merged_prompt_preserves_immutable_api_client_rule_verbatim() -> None:
    """LOCKED rule — every byte must appear exactly (packages/api-client/*
    is the frozen Wave C deliverable; never edited by Wave D)."""
    prompt = _prompt_merged()
    # The exact sentence tree from the LOCKED block.
    assert "Do NOT edit, refactor, or add files under `packages/api-client/*`" in prompt
    assert "frozen Wave C deliverable" in prompt
    # The counterpart in the RULES section preserves the "one-shot" guard.
    assert "MUST import from `packages/api-client/`" in prompt


def test_merged_prompt_renames_expected_file_layout() -> None:
    """Slice 3: rename ``[CODEX OUTPUT TOPOGRAPHY]`` to ``[EXPECTED FILE LAYOUT]``
    since the merged Wave D targets Claude, not Codex."""
    prompt = _prompt_merged()
    # Old banner is gone.
    assert "[CODEX OUTPUT TOPOGRAPHY]" not in prompt


def test_merged_prompt_drops_codex_autonomy_directives() -> None:
    """Claude doesn't need "Do not ask for confirmation" style directives in
    the merged body — they're native to Claude's default behaviour."""
    prompt = _prompt_merged()
    # Legacy Codex-style line is absent in merged path.
    assert "Do not ask for confirmation. Do not produce an upfront plan." not in prompt


def test_merged_prompt_single_turn_scope_mentioned() -> None:
    """The merged prompt explicitly tells Claude to complete both functional
    AND polish in a single rollout."""
    prompt = _prompt_merged()
    assert "functional" in prompt.lower()
    assert "polish" in prompt.lower()
    # "same turn" or "single pass" is stated somewhere in the merged preamble.
    assert "same turn" in prompt.lower() or "single pass" in prompt.lower()


def test_legacy_prompt_still_distinguishable() -> None:
    """Merged=False still produces the legacy banner (byte-different from merged)."""
    merged = _prompt_merged()
    legacy = _prompt_legacy()
    assert merged != legacy
    assert "[WAVE D - FRONTEND SPECIALIST]" in legacy
    assert "(merged functional + polish)" not in legacy
