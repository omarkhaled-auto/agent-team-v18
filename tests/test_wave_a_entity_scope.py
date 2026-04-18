"""Wave A entity-list scope regression — ``build-final-smoke-20260418-073251``.

Smoke #3 showed Wave A correctly halting via ``WAVE_A_CONTRACT_CONFLICT.md``
because the prompt body listed all four domain entities (User, Project,
Task, Comment) in ``[ENTITIES TO CREATE FOR THIS MILESTONE]`` even though
the A-09 scope preamble said ``Allowed domain entities for this milestone:
(none — this milestone introduces no business-logic entities)``. The agent
called out the contradiction:

   Side A: [ENTITIES TO CREATE FOR THIS MILESTONE] User, Project, Task, Comment
   Side B: Allowed domain entities for this milestone: (none)

``_select_ir_entities`` ignores the ``MilestoneScope.allowed_entities``
constraint entirely — it filters only by ``milestone.feature_refs``, and
when ``feature_refs`` is empty (foundation milestone), it early-returns
ALL entities in the IR.

These tests pin the bug, pin the fix, and guard against regression.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_team_v15.agents import _select_ir_entities
from agent_team_v15.milestone_scope import MilestoneScope


def _ir(entities: list[dict[str, Any]]) -> dict[str, Any]:
    return {"entities": entities}


def _milestone(feature_refs: list[str] | None = None) -> Any:
    return SimpleNamespace(
        id="milestone-1",
        feature_refs=feature_refs or [],
        ac_refs=[],
    )


_ALL_ENTITIES = [
    {"name": "User", "owner_feature": "F-AUTH"},
    {"name": "Project", "owner_feature": "F-PROJ"},
    {"name": "Task", "owner_feature": "F-TASK"},
    {"name": "Comment", "owner_feature": "F-COMM"},
]


# ---------------------------------------------------------------------------
# Pre-fix behaviour reproduction — the bug
# ---------------------------------------------------------------------------


def test_no_scope_no_feature_refs_returns_all_entities_legacy_behavior() -> None:
    """Legacy (no scope supplied) + empty feature_refs returns every
    entity in the IR. This is the exact bug that produced the smoke #3
    WAVE_A_CONTRACT_CONFLICT.md: M1 has no feature_refs, fallback
    returned User/Project/Task/Comment, Wave A prompt listed them,
    scope preamble said "none" → contradiction."""
    result = _select_ir_entities(_ir(_ALL_ENTITIES), _milestone(feature_refs=[]))
    assert len(result) == 4, (
        "Legacy no-scope path must still return all entities when "
        "feature_refs is empty (backward compatibility); tests below "
        "verify the scope-aware path overrides this correctly."
    )


# ---------------------------------------------------------------------------
# Fixed behaviour contracts
# ---------------------------------------------------------------------------


def test_scope_with_empty_allowed_entities_returns_empty() -> None:
    """Foundation milestone: scope says `allowed_entities=[]`. Result
    must be an empty list, not the 4-entity legacy fallback. This is
    the specific fix for the smoke #3 contract conflict."""
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_entities=[],
    )
    result = _select_ir_entities(
        _ir(_ALL_ENTITIES),
        _milestone(feature_refs=[]),
        milestone_scope=scope,
    )
    assert result == [], (
        f"Foundation milestone with allowed_entities=[] must return "
        f"empty list; got {[e.get('name') for e in result]}"
    )


def test_scope_filters_by_allowed_entity_name() -> None:
    """Scope with a concrete allowed_entities list filters the IR
    down to matching names. Case-insensitive to match the ``lower()``
    normalisation used elsewhere in the codebase."""
    scope = MilestoneScope(
        milestone_id="milestone-3",
        allowed_entities=["Project"],
    )
    result = _select_ir_entities(
        _ir(_ALL_ENTITIES),
        _milestone(feature_refs=["F-PROJ"]),
        milestone_scope=scope,
    )
    names = [e["name"] for e in result]
    assert names == ["Project"], (
        f"Scope allowed_entities=['Project'] must yield only Project; "
        f"got {names}"
    )


def test_scope_allowed_entities_case_insensitive() -> None:
    """Allowed names written in different cases still match."""
    scope = MilestoneScope(
        milestone_id="milestone-3",
        allowed_entities=["project"],  # lowercase
    )
    result = _select_ir_entities(
        _ir(_ALL_ENTITIES),
        _milestone(feature_refs=["F-PROJ"]),
        milestone_scope=scope,
    )
    names = [e["name"] for e in result]
    assert names == ["Project"]


def test_scope_none_preserves_legacy_behavior() -> None:
    """Explicit scope=None must yield the same result as omitting the
    argument — backwards compatibility with call sites that haven't
    been updated yet."""
    result_omitted = _select_ir_entities(
        _ir(_ALL_ENTITIES), _milestone(feature_refs=["F-PROJ"])
    )
    result_none = _select_ir_entities(
        _ir(_ALL_ENTITIES), _milestone(feature_refs=["F-PROJ"]), milestone_scope=None
    )
    assert result_omitted == result_none


def test_scope_with_allowed_entities_but_unrelated_feature_refs() -> None:
    """MilestoneScope is authoritative even when milestone.feature_refs
    disagrees. This mirrors the real failure path — MASTER_PLAN's
    feature_refs for M1 are empty, but scope says "no entities". The
    scope signal must win."""
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_entities=[],
    )
    # Even with feature_refs that would normally match some entities:
    result = _select_ir_entities(
        _ir(_ALL_ENTITIES),
        _milestone(feature_refs=["F-AUTH", "F-PROJ"]),
        milestone_scope=scope,
    )
    assert result == [], (
        "MilestoneScope.allowed_entities=[] must override feature_refs"
        " filtering — scope is authoritative"
    )


# ---------------------------------------------------------------------------
# build_wave_a_prompt integration — the prompt body must NOT list entities
# when the milestone's scope says "none"
# ---------------------------------------------------------------------------


def test_build_wave_a_prompt_no_entity_leak_for_foundation_milestone(
    tmp_path: Path,
) -> None:
    """Integration test — build Wave A prompt against an M1-style
    foundation milestone with MASTER_PLAN.json saying ``entities: []``
    and REQUIREMENTS.md explicitly listing User/Project/Task/Comment
    as Notes-level non-goals. The composed prompt must NOT list any of
    those four entity names in the ``[ENTITIES TO CREATE FOR THIS
    MILESTONE]`` block — otherwise Wave A will halt again via
    WAVE_A_CONTRACT_CONFLICT.md."""
    from agent_team_v15.agents import build_wave_a_prompt

    # Arrange: create a .agent-team/MASTER_PLAN.json with an empty
    # entities list for milestone-1, and a REQUIREMENTS.md with a
    # Notes section listing the four entities as out-of-scope.
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True)
    (agent_team_dir / "MASTER_PLAN.json").write_text(
        '{"milestones": [{"id": "milestone-1", "description": "Platform Foundation", '
        '"entities": [], "feature_refs": [], "ac_refs": []}]}',
        encoding="utf-8",
    )
    milestones_dir = agent_team_dir / "milestones" / "milestone-1"
    milestones_dir.mkdir(parents=True)
    (milestones_dir / "REQUIREMENTS.md").write_text(
        "# Milestone 1: Platform Foundation\n\n"
        "## Notes\n"
        "- No entities, controllers, services, DTOs for User/Project/Task/Comment "
        "— those ship in M2–M5.\n",
        encoding="utf-8",
    )

    # Act: build the Wave A prompt — use realistic field lists so the
    # rendered block matches the smoke's actual output shape, e.g.
    # "- User: id: string, email: string, …".
    ir = {
        "entities": [
            {
                "name": "User",
                "fields": [
                    {"name": "id", "type": "string"},
                    {"name": "email", "type": "string"},
                ],
                "owner_feature": "F-AUTH",
            },
            {
                "name": "Project",
                "fields": [
                    {"name": "id", "type": "string"},
                    {"name": "name", "type": "string"},
                ],
                "owner_feature": "F-PROJ",
            },
            {
                "name": "Task",
                "fields": [{"name": "id", "type": "string"}],
                "owner_feature": "F-TASK",
            },
            {
                "name": "Comment",
                "fields": [{"name": "id", "type": "string"}],
                "owner_feature": "F-COMM",
            },
        ],
        "acceptance_criteria": [],
    }
    milestone = SimpleNamespace(
        id="milestone-1",
        feature_refs=[],
        ac_refs=[],
    )
    prompt = build_wave_a_prompt(
        milestone=milestone,
        ir=ir,
        dependency_artifacts=None,
        scaffolded_files=[],
        config=SimpleNamespace(
            v18=SimpleNamespace(milestone_scope_enforcement=True)
        ),
        existing_prompt_framework="[Base prompt]",
        cwd=str(tmp_path),
    )

    # Assert: the ENTITIES TO CREATE block must not contain any of the
    # four out-of-scope entity names. The block header may still
    # appear — we only need its contents scoped.
    entities_block_start = prompt.find("[ENTITIES TO CREATE FOR THIS MILESTONE]")
    assert entities_block_start >= 0, "Entities block header missing entirely"

    # Take the 2000 chars after the block header — the entity list is
    # rendered within that range by _format_ir_entities.
    entities_block = prompt[entities_block_start : entities_block_start + 2000]

    for forbidden in ("User:", "Project:", "Task:", "Comment:"):
        assert forbidden not in entities_block, (
            f"Foundation milestone M1 prompt leaked entity '{forbidden}' "
            f"into the [ENTITIES TO CREATE] block. This contradicts the "
            f"A-09 MilestoneScope preamble and will trigger "
            f"WAVE_A_CONTRACT_CONFLICT.md (see "
            f"build-final-smoke-20260418-073251). Block excerpt:\n"
            f"{entities_block[:800]}"
        )
