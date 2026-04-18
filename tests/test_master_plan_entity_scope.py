"""``MasterPlanMilestone.entities`` round-trip + heuristic derivation.

Closes the data-loading gap flagged in PR #32: before this PR,
``MilestoneScope.allowed_entities`` was always ``[]`` regardless of the
milestone because ``MasterPlanMilestone`` had no ``entities`` field.
Two code paths now populate it:

1. **Explicit JSON / MD field** — when MASTER_PLAN.json or MASTER_PLAN.md
   carries ``entities: [...]``, it is round-tripped through the
   dataclass.
2. **Description heuristic** — when the field is absent, a regex over
   ``description`` picks up "``Project`` entity", "``Comment`` entities",
   etc. Matches against the current orchestrator output (verified
   against smoke #3 MASTER_PLAN.json).

The derivation is intentionally conservative: no match → empty list.
That keeps M1 foundation correct (no entity phrasing in the
description) while handling M2-M5 where the orchestrator mentions the
entity name directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.milestone_manager import (
    MasterPlan,
    MasterPlanMilestone,
    _derive_entities_from_description,
    _milestone_to_json_dict,
    generate_master_plan_json,
    load_master_plan_json,
)


# ---------------------------------------------------------------------------
# Description heuristic — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Scaffold monorepo (NestJS API + Next.js web), Postgres + Prisma", []),
        (
            "Complete auth flow (register, login, me) with JWT + bcrypt, "
            "User entity and role model, global JWT guard",
            ["User"],
        ),
        ("Project entity and all five project endpoints with owner/admin rules", ["Project"]),
        ("Task entity and six task endpoints including PATCH /status", ["Task"]),
        ("Comment entity and two comment endpoints, threaded comments", ["Comment"]),
        # Multi-entity milestone — each entity named individually
        (
            "User entity and Task entity with full auth + status transitions",
            ["User", "Task"],
        ),
        # Known limitation: shared-plural "X and Y entities" only captures
        # the last entity (the one directly preceding "entities"). The
        # orchestrator in practice names each entity individually (verified
        # against smoke #3), so this edge case does not bite production.
        # Explicit ``entities`` emission in MASTER_PLAN.json is the
        # structural fix when a milestone legitimately owns multiple
        # entities without per-entity phrasing.
        ("Create User and Comment entities in one pass", ["Comment"]),
        # Lowercase shouldn't match
        ("user's tasks are processed by the system", []),
        # Empty
        ("", []),
        # Duplicate in text - dedup preserves first occurrence
        ("Project entity. The Project entity owns…", ["Project"]),
    ],
)
def test_derive_entities_from_description(description: str, expected: list[str]) -> None:
    assert _derive_entities_from_description(description) == expected


# ---------------------------------------------------------------------------
# Dataclass field present
# ---------------------------------------------------------------------------


def test_dataclass_has_entities_field() -> None:
    m = MasterPlanMilestone(id="milestone-1", title="Foundation")
    assert m.entities == []

    m2 = MasterPlanMilestone(id="milestone-2", title="Auth", entities=["User"])
    assert m2.entities == ["User"]


def test_json_serializer_round_trips_entities(tmp_path: Path) -> None:
    milestones = [
        MasterPlanMilestone(id="m-1", title="Foundation"),
        MasterPlanMilestone(id="m-2", title="Auth", entities=["User"]),
        MasterPlanMilestone(id="m-3", title="Projects", entities=["Project", "Team"]),
    ]
    out = tmp_path / "MASTER_PLAN.json"
    generate_master_plan_json(milestones, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    entities_by_id = {m["id"]: m["entities"] for m in data["milestones"]}
    assert entities_by_id == {
        "m-1": [],
        "m-2": ["User"],
        "m-3": ["Project", "Team"],
    }


# ---------------------------------------------------------------------------
# Round-trip through disk
# ---------------------------------------------------------------------------


def test_json_load_preserves_explicit_entities(tmp_path: Path) -> None:
    agent_team = tmp_path / ".agent-team"
    agent_team.mkdir(parents=True)
    (agent_team / "MASTER_PLAN.json").write_text(
        json.dumps(
            {
                "milestones": [
                    {
                        "id": "milestone-2",
                        "title": "Auth",
                        "description": "(description irrelevant when entities explicit)",
                        "entities": ["User"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    plan = load_master_plan_json(tmp_path)
    assert plan.milestones[0].entities == ["User"]


def test_json_load_falls_back_to_description_heuristic(tmp_path: Path) -> None:
    """When JSON has no ``entities`` field, the description heuristic
    populates it at read time — the path that rescues smoke #3's
    legacy MASTER_PLAN.json outputs."""
    agent_team = tmp_path / ".agent-team"
    agent_team.mkdir(parents=True)
    (agent_team / "MASTER_PLAN.json").write_text(
        json.dumps(
            {
                "milestones": [
                    {
                        "id": "milestone-3",
                        "title": "Projects",
                        "description": (
                            "Project entity and all five project endpoints "
                            "with owner/admin rules"
                        ),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    plan = load_master_plan_json(tmp_path)
    assert plan.milestones[0].entities == ["Project"]


def test_json_load_empty_entities_and_no_entity_phrasing(tmp_path: Path) -> None:
    """M1-style foundation: no explicit entities, description is pure
    infrastructure (no "X entity" phrasing). Both fallback paths yield
    an empty list — the correct answer for foundation milestones."""
    agent_team = tmp_path / ".agent-team"
    agent_team.mkdir(parents=True)
    (agent_team / "MASTER_PLAN.json").write_text(
        json.dumps(
            {
                "milestones": [
                    {
                        "id": "milestone-1",
                        "title": "Foundation",
                        "description": "Scaffold monorepo, Docker, Prisma",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    plan = load_master_plan_json(tmp_path)
    assert plan.milestones[0].entities == []


# ---------------------------------------------------------------------------
# Integration against real smoke #3 MASTER_PLAN
# ---------------------------------------------------------------------------


_SMOKE_DIR = (
    Path(__file__).resolve().parents[1]
    / "v18 test runs"
    / "build-final-smoke-20260418-073251"
)


@pytest.mark.skipif(
    not (_SMOKE_DIR / ".agent-team" / "MASTER_PLAN.json").is_file(),
    reason="Preserved smoke dir not present; skipping integration regression",
)
def test_integration_smoke3_master_plan_resolves_all_milestones() -> None:
    """Against the preserved ``build-final-smoke-20260418-073251``
    MASTER_PLAN.json, every milestone's ``entities`` field should now
    resolve to a meaningful list (empty for foundation, single entity
    for feature milestones).

    This is the precise regression guard for the smoke #3 failure:
    before the parser gap was closed, every milestone's
    ``allowed_entities`` was ``[]``, which would cause Wave A for M2-M5
    to halt via WAVE_A_CONTRACT_CONFLICT.md when the milestone's
    legitimate entity (User/Project/Task/Comment) was missing from the
    scoped prompt."""
    plan = load_master_plan_json(_SMOKE_DIR)
    by_id = {m.id: m for m in plan.milestones}

    # M1 correctly foundation — no entities.
    assert by_id["milestone-1"].entities == []
    # M2-M5 each own exactly one of the four core entities.
    assert by_id["milestone-2"].entities == ["User"]
    assert by_id["milestone-3"].entities == ["Project"]
    assert by_id["milestone-4"].entities == ["Task"]
    assert by_id["milestone-5"].entities == ["Comment"]


# ---------------------------------------------------------------------------
# _milestone_to_json_dict sanity
# ---------------------------------------------------------------------------


def test_milestone_to_json_dict_includes_entities() -> None:
    m = MasterPlanMilestone(id="m-1", title="t", entities=["User", "Team"])
    d = _milestone_to_json_dict(m)
    assert d["entities"] == ["User", "Team"]


def test_milestone_to_json_dict_default_entities_empty() -> None:
    m = MasterPlanMilestone(id="m-1", title="t")
    d = _milestone_to_json_dict(m)
    assert d["entities"] == []
