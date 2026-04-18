"""Scope-aware ``_select_ir_state_machines`` and ``_select_ir_events`` —
pre-emptive sibling of ``tests/test_wave_a_entity_scope.py``.

Same bug class as the entity selector: when ``milestone.feature_refs``
is empty (foundation milestone), both functions fell through to
returning every state machine / event in the IR. This would produce the
same WAVE_A_CONTRACT_CONFLICT.md-style contradiction once the smoke
reaches Wave B — one more round of halt-and-fix avoided by fixing it
now.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_team_v15.agents import _select_ir_events, _select_ir_state_machines
from agent_team_v15.milestone_scope import MilestoneScope


def _milestone(feature_refs: list[str] | None = None) -> Any:
    return SimpleNamespace(
        id="milestone-1",
        feature_refs=feature_refs or [],
        ac_refs=[],
    )


# Minimal IR with 4 state machines (one per entity) and 4 events.
_STATE_MACHINES = [
    {"entity": "User", "name": "user-lifecycle"},
    {"entity": "Project", "name": "project-status"},
    {"entity": "Task", "name": "task-status"},
    {"entity": "Comment", "name": "comment-status"},
]
_EVENTS = [
    {"entity": "User", "name": "user.created"},
    {"entity": "Project", "name": "project.created"},
    {"entity": "Task", "name": "task.assigned"},
    {"entity": "Comment", "name": "comment.posted"},
]


def _ir() -> dict[str, Any]:
    return {
        "entities": [
            {"name": "User"},
            {"name": "Project"},
            {"name": "Task"},
            {"name": "Comment"},
        ],
        "state_machines": list(_STATE_MACHINES),
        "events": list(_EVENTS),
    }


# ---------------------------------------------------------------------------
# state_machines — scope authoritative, legacy preserved
# ---------------------------------------------------------------------------


def test_state_machines_scope_empty_returns_empty() -> None:
    scope = MilestoneScope(milestone_id="milestone-1", allowed_entities=[])
    result = _select_ir_state_machines(
        _ir(), _milestone(), milestone_scope=scope
    )
    assert result == []


def test_state_machines_scope_filters_by_name() -> None:
    scope = MilestoneScope(milestone_id="milestone-3", allowed_entities=["Project"])
    result = _select_ir_state_machines(
        _ir(), _milestone(feature_refs=["F-PROJ"]), milestone_scope=scope
    )
    names = [sm["entity"] for sm in result]
    assert names == ["Project"]


def test_state_machines_scope_case_insensitive() -> None:
    scope = MilestoneScope(milestone_id="milestone-4", allowed_entities=["task"])
    result = _select_ir_state_machines(
        _ir(), _milestone(feature_refs=["F-TASK"]), milestone_scope=scope
    )
    assert len(result) == 1 and result[0]["entity"] == "Task"


def test_state_machines_scope_none_preserves_legacy() -> None:
    """Legacy: feature_refs=[] returns all state machines (pre-fix)."""
    result = _select_ir_state_machines(_ir(), _milestone())
    assert len(result) == 4


def test_state_machines_scope_none_with_feature_refs_filters_legacy() -> None:
    """Legacy filter by entity membership in milestone_entities — Wave B
    call-shape before scope plumbing."""
    # Milestone owns only F-PROJ feature → entity filter drops the other 3.
    ir = _ir()
    # Wire IR entities to owners so _select_ir_entities() legacy path
    # can pick the "Project" entity.
    ir["entities"] = [
        {"name": "User", "owner_feature": "F-AUTH"},
        {"name": "Project", "owner_feature": "F-PROJ"},
        {"name": "Task", "owner_feature": "F-TASK"},
        {"name": "Comment", "owner_feature": "F-COMM"},
    ]
    result = _select_ir_state_machines(ir, _milestone(feature_refs=["F-PROJ"]))
    names = [sm["entity"] for sm in result]
    assert names == ["Project"]


# ---------------------------------------------------------------------------
# events — same contract
# ---------------------------------------------------------------------------


def test_events_scope_empty_returns_empty() -> None:
    scope = MilestoneScope(milestone_id="milestone-1", allowed_entities=[])
    result = _select_ir_events(_ir(), _milestone(), milestone_scope=scope)
    assert result == []


def test_events_scope_filters_by_name() -> None:
    scope = MilestoneScope(milestone_id="milestone-4", allowed_entities=["Task"])
    result = _select_ir_events(
        _ir(), _milestone(feature_refs=["F-TASK"]), milestone_scope=scope
    )
    assert len(result) == 1 and result[0]["entity"] == "Task"


def test_events_scope_case_insensitive() -> None:
    scope = MilestoneScope(milestone_id="milestone-5", allowed_entities=["COMMENT"])
    result = _select_ir_events(
        _ir(), _milestone(feature_refs=["F-COMM"]), milestone_scope=scope
    )
    assert len(result) == 1 and result[0]["entity"] == "Comment"


def test_events_scope_none_preserves_legacy() -> None:
    """Legacy (pre-fix): feature_refs=[] passes every event through the
    `if not feature_refs or ...` short-circuit."""
    result = _select_ir_events(_ir(), _milestone())
    assert len(result) == 4


def test_events_workflows_collection_also_scoped() -> None:
    """Scope filter applies to the ``workflows`` collection as well as
    ``events`` (the function iterates both)."""
    ir = _ir()
    ir["workflows"] = [
        {"entity": "Project", "name": "project.workflow.approval"},
        {"entity": "User", "name": "user.workflow.onboarding"},
    ]
    scope = MilestoneScope(milestone_id="milestone-3", allowed_entities=["Project"])
    result = _select_ir_events(
        ir, _milestone(feature_refs=["F-PROJ"]), milestone_scope=scope
    )
    names = sorted(e.get("name", "") for e in result)
    assert names == ["project.created", "project.workflow.approval"]


# ---------------------------------------------------------------------------
# build_wave_b_prompt integration — scope loaded + threaded
# ---------------------------------------------------------------------------


def test_build_wave_b_prompt_loads_and_passes_scope(tmp_path) -> None:
    """Integration — the live prompt builder must load MilestoneScope
    and pass it to both state_machine + event selectors. Detected via
    the rendered prompt text: for a foundation M1 milestone, the event
    / state-machine blocks must not list M2-M5 entities."""
    from pathlib import Path as _Path

    from agent_team_v15.agents import build_wave_b_prompt

    # Arrange: MASTER_PLAN.json says allowed_entities=[] for milestone-1.
    agent_team = tmp_path / ".agent-team"
    agent_team.mkdir(parents=True)
    (agent_team / "MASTER_PLAN.json").write_text(
        '{"milestones": [{"id": "milestone-1", "description": "Foundation", '
        '"entities": [], "feature_refs": [], "ac_refs": []}]}',
        encoding="utf-8",
    )
    milestones_dir = agent_team / "milestones" / "milestone-1"
    milestones_dir.mkdir(parents=True)
    (milestones_dir / "REQUIREMENTS.md").write_text(
        "# M1\n## Notes\n- No entities — M2-M5 own them.\n",
        encoding="utf-8",
    )

    ir = {
        **_ir(),
        "endpoints": [],
        "business_rules": [],
        "integrations": [],
        "integration_items": [],
        "acceptance_criteria": [],
    }
    milestone = SimpleNamespace(
        id="milestone-1",
        feature_refs=[],
        ac_refs=[],
    )
    prompt = build_wave_b_prompt(
        milestone=milestone,
        ir=ir,
        wave_a_artifact=None,
        dependency_artifacts=None,
        scaffolded_files=[],
        config=SimpleNamespace(
            v18=SimpleNamespace(milestone_scope_enforcement=True)
        ),
        existing_prompt_framework="[Base]",
        cwd=str(tmp_path),
    )

    # The rendered prompt must not contain the state-machine or event
    # entries for any out-of-scope entity. The prompt formatting may
    # use slightly different markers; search for the entity name paired
    # with the state-machine / event naming patterns.
    for out_of_scope_name in ("user-lifecycle", "project-status", "task-status", "comment-status"):
        assert out_of_scope_name not in prompt, (
            f"State machine '{out_of_scope_name}' leaked into Wave B "
            f"prompt for foundation M1. MilestoneScope not applied? "
            f"Prompt excerpt: {prompt[:500]}"
        )
    for out_of_scope_name in ("user.created", "project.created", "task.assigned", "comment.posted"):
        assert out_of_scope_name not in prompt, (
            f"Event '{out_of_scope_name}' leaked into Wave B prompt "
            f"for foundation M1."
        )
