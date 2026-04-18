"""Close the A-09 selector-scope bug class — `endpoints`, `acceptance
criteria`, `business_rules` sibling of prior entity / state_machines /
events PRs. Ensures every ``_select_ir_*`` in ``agents.py`` that feeds
wave prompts respects ``MilestoneScope`` when one is provided.

Plus a structural guard that no scope-aware selector can drift back to
an "empty scope returns everything" fallback.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_team_v15.agents import (
    _load_milestone_scope_for_prompt,
    _select_ir_acceptance_criteria,
    _select_ir_business_rules,
    _select_ir_endpoints,
)
from agent_team_v15.milestone_scope import MilestoneScope


def _milestone(
    feature_refs: list[str] | None = None,
    ac_refs: list[str] | None = None,
    title: str = "Milestone",
) -> Any:
    return SimpleNamespace(
        id="milestone-1",
        title=title,
        feature_refs=feature_refs or [],
        ac_refs=ac_refs or [],
    )


_ENDPOINTS = [
    {"method": "POST", "path": "/api/auth/login", "owner_feature": "F-AUTH"},
    {"method": "GET", "path": "/api/projects", "owner_feature": "F-PROJ"},
    {"method": "GET", "path": "/api/tasks", "owner_feature": "F-TASK"},
    {"method": "GET", "path": "/api/comments", "owner_feature": "F-COMM"},
]
_ACS = [
    {"id": "AC-AUTH-001", "feature": "F-AUTH", "text": "User can log in"},
    {"id": "AC-PROJ-001", "feature": "F-PROJ", "text": "User can create project"},
    {"id": "AC-TASK-001", "feature": "F-TASK", "text": "User can create task"},
    {"id": "AC-COMM-001", "feature": "F-COMM", "text": "User can post comment"},
]
_RULES = [
    {"id": "BR-001", "service": "users", "text": "Email unique per user"},
    {"id": "BR-002", "service": "projects", "text": "Owner cannot be null"},
    {"id": "BR-003", "service": "tasks", "text": "Status transitions restricted"},
    {"id": "BR-004", "service": "comments", "text": "Text non-empty"},
]


def _ir() -> dict[str, Any]:
    return {
        "endpoints": list(_ENDPOINTS),
        "acceptance_criteria": list(_ACS),
        "business_rules": list(_RULES),
        "entities": [
            {"name": "User"}, {"name": "Project"}, {"name": "Task"}, {"name": "Comment"}
        ],
    }


# ---------------------------------------------------------------------------
# _select_ir_endpoints
# ---------------------------------------------------------------------------


def test_endpoints_scope_empty_returns_empty() -> None:
    scope = MilestoneScope(milestone_id="milestone-1", allowed_feature_refs=[])
    assert _select_ir_endpoints(_ir(), _milestone(), milestone_scope=scope) == []


def test_endpoints_scope_filters_by_feature_ref() -> None:
    scope = MilestoneScope(milestone_id="milestone-3", allowed_feature_refs=["F-PROJ"])
    result = _select_ir_endpoints(
        _ir(), _milestone(feature_refs=["F-PROJ"]), milestone_scope=scope
    )
    paths = [e["path"] for e in result]
    assert paths == ["/api/projects"]


def test_endpoints_scope_case_insensitive_normalisation() -> None:
    """allowed_feature_refs match the same normaliser the legacy path
    uses (lowercase, whitespace-trimmed)."""
    scope = MilestoneScope(
        milestone_id="milestone-4", allowed_feature_refs=["f-task"]
    )
    result = _select_ir_endpoints(
        _ir(), _milestone(feature_refs=["F-TASK"]), milestone_scope=scope
    )
    assert len(result) == 1 and result[0]["path"] == "/api/tasks"


def test_endpoints_scope_none_preserves_legacy_return_all_for_empty_refs() -> None:
    """Legacy: feature_refs=[] on milestone → returns ALL endpoints
    (the bug-in-plain-view pattern). Preserved for backward compat."""
    assert len(_select_ir_endpoints(_ir(), _milestone())) == 4


# ---------------------------------------------------------------------------
# _select_ir_acceptance_criteria
# ---------------------------------------------------------------------------


def test_acs_scope_empty_returns_empty() -> None:
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_ac_refs=[],
        allowed_feature_refs=[],
    )
    assert _select_ir_acceptance_criteria(_ir(), _milestone(), milestone_scope=scope) == []


def test_acs_scope_by_ac_ref() -> None:
    scope = MilestoneScope(
        milestone_id="milestone-3",
        allowed_ac_refs=["AC-PROJ-001"],
    )
    result = _select_ir_acceptance_criteria(
        _ir(), _milestone(ac_refs=["AC-PROJ-001"]), milestone_scope=scope
    )
    assert len(result) == 1 and result[0]["id"] == "AC-PROJ-001"


def test_acs_scope_by_feature_ref() -> None:
    """Entity-less AC still resolves via feature match."""
    scope = MilestoneScope(
        milestone_id="milestone-4", allowed_feature_refs=["F-TASK"]
    )
    result = _select_ir_acceptance_criteria(
        _ir(), _milestone(feature_refs=["F-TASK"]), milestone_scope=scope
    )
    assert len(result) == 1 and result[0]["id"] == "AC-TASK-001"


def test_acs_scope_none_preserves_legacy_full_return_bug() -> None:
    """Legacy bug (now guarded by scope): empty ac_refs + empty
    feature_refs on milestone → returns ALL ACs. Must not regress
    until callers have migrated. This test fails loudly if someone
    flips the legacy default — prompting them to migrate callers
    first."""
    result = _select_ir_acceptance_criteria(_ir(), _milestone())
    assert len(result) == 4


# ---------------------------------------------------------------------------
# _select_ir_business_rules
# ---------------------------------------------------------------------------


def test_business_rules_scope_empty_returns_empty() -> None:
    scope = MilestoneScope(milestone_id="milestone-1", allowed_entities=[])
    assert _select_ir_business_rules(_ir(), _milestone(), milestone_scope=scope) == []


def test_business_rules_scope_by_entity_service() -> None:
    """Rule's ``service`` field matched case-insensitively against
    allowed_entities — e.g. service="tasks" matches allowed "Task"."""
    scope = MilestoneScope(milestone_id="milestone-4", allowed_entities=["Tasks"])
    result = _select_ir_business_rules(
        _ir(), _milestone(), milestone_scope=scope
    )
    assert len(result) == 1 and result[0]["id"] == "BR-003"


def test_business_rules_scope_by_entity_field() -> None:
    """Rule's ``entity`` field (alternative to ``service``) also matches."""
    ir = {
        "business_rules": [
            {"id": "BR-X", "entity": "User", "text": "…"},
            {"id": "BR-Y", "entity": "Project", "text": "…"},
        ]
    }
    scope = MilestoneScope(milestone_id="milestone-2", allowed_entities=["User"])
    result = _select_ir_business_rules(ir, _milestone(), milestone_scope=scope)
    assert len(result) == 1 and result[0]["id"] == "BR-X"


def test_business_rules_scope_none_preserves_legacy() -> None:
    """Legacy: no service_hint → returns all rules."""
    result = _select_ir_business_rules(_ir(), _milestone())
    assert len(result) == 4


# ---------------------------------------------------------------------------
# Shared scope-loader helper
# ---------------------------------------------------------------------------


def test_scope_loader_returns_none_when_cwd_missing() -> None:
    assert _load_milestone_scope_for_prompt(_milestone(), None) is None


def test_scope_loader_returns_none_when_master_plan_missing(tmp_path: Path) -> None:
    """Best-effort contract: missing MASTER_PLAN.json must return None,
    not raise, so callers can fall through to legacy selector
    behaviour in early-build / test scenarios."""
    # tmp_path has no .agent-team/ layout
    result = _load_milestone_scope_for_prompt(_milestone(), str(tmp_path))
    assert result is None


def test_scope_loader_returns_scope_when_artefacts_present(tmp_path: Path) -> None:
    """Successful scope load returns a populated MilestoneScope.

    Note: ``MASTER_PLAN.json`` emitted by the orchestrator today carries
    ``feature_refs`` and ``ac_refs`` but does NOT emit an explicit
    ``entities`` key — the MasterPlanMilestone dataclass schema has no
    ``entities`` field. This is a known gap documented in the PR body:
    ``MilestoneScope.allowed_entities`` is always ``[]`` for every
    milestone today. For M1 foundation milestones that is the correct
    answer (no entities); for M2-M5 it is structurally wrong and a
    follow-up PR will derive entities from feature_refs by consulting
    the IR. Test asserts current-reality to pass cleanly and avoid
    blocking this PR on an orthogonal data-loading fix.
    """
    agent_team = tmp_path / ".agent-team"
    agent_team.mkdir(parents=True)
    (agent_team / "MASTER_PLAN.json").write_text(
        '{"milestones": [{"id": "milestone-1", "description": "Foundation", '
        '"feature_refs": ["F-AUTH"], '
        '"ac_refs": ["AC-AUTH-001"]}]}',
        encoding="utf-8",
    )
    milestones_dir = agent_team / "milestones" / "milestone-1"
    milestones_dir.mkdir(parents=True)
    (milestones_dir / "REQUIREMENTS.md").write_text("# M1\n", encoding="utf-8")

    scope = _load_milestone_scope_for_prompt(_milestone(), str(tmp_path))
    assert scope is not None
    assert scope.milestone_id == "milestone-1"
    assert "F-AUTH" in scope.allowed_feature_refs
    assert "AC-AUTH-001" in scope.allowed_ac_refs
    # allowed_entities intentionally empty today — see docstring.
    assert scope.allowed_entities == []


# ---------------------------------------------------------------------------
# Structural invariant — no scope-aware selector silently returns "all"
# on empty allowed_* lists
# ---------------------------------------------------------------------------


_AGENTS_PY = (
    Path(__file__).resolve().parents[1] / "src" / "agent_team_v15" / "agents.py"
)


def test_all_scope_aware_selectors_honour_empty_scope_semantics() -> None:
    """Grep-based guard: every ``_select_ir_*`` function that accepts
    ``milestone_scope`` must have a branch keyed on
    ``if milestone_scope is not None`` so the scope-authoritative path
    is distinct from the legacy fallback. Drift detection for future
    refactors."""
    text = _AGENTS_PY.read_text(encoding="utf-8")
    scope_aware = re.findall(
        r"^def (_select_ir_[a-z_]+)\([^)]*milestone_scope",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert len(scope_aware) >= 5, (
        f"Expected >=5 scope-aware selectors (entities, endpoints, "
        f"acceptance_criteria, business_rules, state_machines, events); "
        f"found {len(scope_aware)}: {scope_aware}"
    )
    for fn_name in scope_aware:
        body_start = text.index(f"def {fn_name}(")
        # next top-level def
        next_def = text.find("\ndef ", body_start + 1)
        body = text[body_start : next_def if next_def > 0 else None]
        assert "if milestone_scope is not None" in body, (
            f"{fn_name} accepts milestone_scope but lacks the "
            f"``if milestone_scope is not None:`` branch — it won't "
            f"enforce scope-authoritative semantics. Scope-empty would "
            f"silently return everything (the class of bug this PR closes)."
        )


def test_all_scope_aware_selector_legacy_paths_still_reachable() -> None:
    """Mirror guard: every scope-aware selector still has its legacy
    fallback (no ``return`` as the only statement inside the scope
    branch followed by the legacy code). Ensures ``scope=None``
    callers keep working."""
    text = _AGENTS_PY.read_text(encoding="utf-8")
    for fn_name in (
        "_select_ir_entities",
        "_select_ir_endpoints",
        "_select_ir_acceptance_criteria",
        "_select_ir_business_rules",
        "_select_ir_state_machines",
        "_select_ir_events",
    ):
        body_start = text.index(f"def {fn_name}(")
        next_def = text.find("\ndef ", body_start + 1)
        body = text[body_start : next_def if next_def > 0 else None]
        # Legacy fallback should mention feature_refs OR service_hint —
        # something pre-A-09. If neither appears, the legacy path has
        # been dropped.
        has_legacy = (
            "feature_refs" in body
            or "service_hint" in body
            or "ac_refs" in body
        )
        assert has_legacy, (
            f"{fn_name} appears to have lost its legacy fallback "
            f"(no mention of feature_refs / service_hint / ac_refs "
            f"in the body). Callers passing milestone_scope=None will "
            f"break."
        )
