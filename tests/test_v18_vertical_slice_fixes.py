"""Tests for the V18.1 vertical-slice milestone fixes (Fixes 1-6).

Covers:
- Fix 1: validate_plan (cycles, depth, sizing, roots) + compute_execution_order
- Fix 2: planner prompt content (AC-Refs, Stack-Target, sizing rules, no
  complexity_estimate)
- Fix 3: vertical-slice always on (legacy planner_mode values warn but still
  use vertical-slice phasing)
- Fix 4: JSON canonical — load_master_plan_json with .md fallback,
  update_milestone_status_json, generate_master_plan_md, round-trip
- Fix 5: compute_milestone_complexity derived from Product IR (not LLM)
- Fix 6: covered by cli integration semantics; here we verify the ordering
  helper deterministically sorts ready milestones topologically.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.milestone_manager import (
    MasterPlan,
    MasterPlanMilestone,
    PlanValidationResult,
    compute_execution_order,
    compute_milestone_complexity,
    generate_master_plan_json,
    generate_master_plan_md,
    load_master_plan_json,
    parse_master_plan,
    update_milestone_status_json,
    validate_plan,
)
from agent_team_v15 import agents as agents_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _m(
    mid: str,
    *,
    deps: list[str] | None = None,
    ac_refs: list[str] | None = None,
    template: str = "full_stack",
    feature_refs: list[str] | None = None,
    description: str = "",
) -> MasterPlanMilestone:
    return MasterPlanMilestone(
        id=mid,
        title=mid.replace("-", " ").title(),
        dependencies=list(deps or []),
        ac_refs=list(ac_refs or []),
        template=template,
        feature_refs=list(feature_refs or []),
        description=description,
    )


# ---------------------------------------------------------------------------
# Fix 1: validate_plan
# ---------------------------------------------------------------------------


class TestValidatePlan:
    def test_detects_circular_deps(self) -> None:
        """A → B → C → A should produce an error."""
        plan = [
            _m("milestone-1", deps=["milestone-3"]),
            _m("milestone-2", deps=["milestone-1"]),
            _m("milestone-3", deps=["milestone-2"]),
        ]
        result = validate_plan(plan)
        assert not result.valid
        assert any("Circular dependency" in e for e in result.errors)

    def test_detects_self_loop(self) -> None:
        plan = [_m("milestone-1", deps=["milestone-1"])]
        result = validate_plan(plan)
        assert not result.valid
        assert any("Circular" in e for e in result.errors)

    def test_detects_unresolved_deps(self) -> None:
        """Depends on a milestone that doesn't exist → error."""
        plan = [
            _m("milestone-1"),
            _m("milestone-2", deps=["milestone-x"]),
        ]
        result = validate_plan(plan)
        assert not result.valid
        assert any("milestone-x" in e for e in result.errors)

    def test_warns_on_deep_deps(self) -> None:
        """Chain A → B → C → D → E (depth 4) should stay OK; depth 5 warns."""
        deep = [
            _m("milestone-1"),
            _m("milestone-2", deps=["milestone-1"]),
            _m("milestone-3", deps=["milestone-2"]),
            _m("milestone-4", deps=["milestone-3"]),
            _m("milestone-5", deps=["milestone-4"]),
            _m("milestone-6", deps=["milestone-5"]),  # depth 5 → warning
        ]
        result = validate_plan(deep)
        assert result.valid  # depth is only a warning
        assert any("depth" in w and "milestone-6" in w for w in result.warnings)

    def test_warns_on_oversized_milestone(self) -> None:
        plan = [_m("milestone-1", ac_refs=[f"AC-{i}" for i in range(14)])]
        result = validate_plan(plan)
        assert any("maximum recommended" in w for w in result.warnings)

    def test_warns_on_undersized_milestone(self) -> None:
        plan = [_m("milestone-1", ac_refs=["AC-1", "AC-2"])]
        result = validate_plan(plan)
        assert any("minimum recommended" in w for w in result.warnings)

    def test_allows_zero_ac_foundation(self) -> None:
        plan = [_m("milestone-1", ac_refs=[])]
        result = validate_plan(plan)
        # 0 ACs is legal for foundation milestones — no sizing warning
        assert not any("recommended" in w for w in result.warnings)

    def test_requires_root_milestone(self) -> None:
        """All milestones have deps → error (no root)."""
        plan = [
            _m("milestone-1", deps=["milestone-2"]),
            _m("milestone-2", deps=["milestone-1"]),
        ]
        result = validate_plan(plan)
        assert not result.valid
        # Both cycle and no-root errors are acceptable; check the no-root text
        # or the cycle since cycles also implicitly violate root-existence.
        assert any(
            "root" in e.lower() or "circular" in e.lower() for e in result.errors
        )

    def test_empty_plan_is_valid(self) -> None:
        result = validate_plan([])
        assert result.valid
        assert not result.errors

    def test_validation_result_dataclass(self) -> None:
        r = PlanValidationResult()
        assert r.valid is True
        assert r.errors == []
        assert r.warnings == []


# ---------------------------------------------------------------------------
# Fix 1: compute_execution_order
# ---------------------------------------------------------------------------


class TestComputeExecutionOrder:
    def test_topological(self) -> None:
        plan = [
            _m("milestone-1"),
            _m("milestone-2", deps=["milestone-1"]),
            _m("milestone-3", deps=["milestone-1", "milestone-2"]),
        ]
        order = compute_execution_order(plan)
        assert order.index("milestone-1") < order.index("milestone-2")
        assert order.index("milestone-2") < order.index("milestone-3")

    def test_deterministic_same_plan_same_order(self) -> None:
        plan = [
            _m("milestone-2", deps=["milestone-1"]),
            _m("milestone-1"),
            _m("milestone-3", deps=["milestone-1"]),
            _m("milestone-4", deps=["milestone-1"]),
        ]
        order1 = compute_execution_order(plan)
        order2 = compute_execution_order(plan)
        assert order1 == order2

    def test_within_tier_sorted_by_id(self) -> None:
        """M3 and M4 both depend only on M1 → M3 appears before M4."""
        plan = [
            _m("milestone-1"),
            _m("milestone-4", deps=["milestone-1"]),
            _m("milestone-3", deps=["milestone-1"]),
        ]
        order = compute_execution_order(plan)
        assert order == ["milestone-1", "milestone-3", "milestone-4"]

    def test_all_independent_sorted_by_id(self) -> None:
        plan = [_m("milestone-2"), _m("milestone-1"), _m("milestone-3")]
        order = compute_execution_order(plan)
        assert order == ["milestone-1", "milestone-2", "milestone-3"]


# ---------------------------------------------------------------------------
# Fix 4: JSON canonical format
# ---------------------------------------------------------------------------


class TestJsonCanonical:
    def test_load_master_plan_json_reads_all_fields(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        data = {
            "schema_version": 1,
            "generated": "2026-04-12T00:00:00Z",
            "milestones": [
                {
                    "id": "milestone-1",
                    "title": "Foundation",
                    "status": "PENDING",
                    "dependencies": [],
                    "description": "scaffolds",
                    "template": "full_stack",
                    "parallel_group": "",
                    "merge_surfaces": ["package.json"],
                    "feature_refs": ["F-001"],
                    "ac_refs": ["AC-1", "AC-2", "AC-3"],
                    "stack_target": "nestjs+nextjs",
                    "complexity_estimate": {"entity_count": 3},
                },
            ],
        }
        (agent_dir / "MASTER_PLAN.json").write_text(json.dumps(data))
        plan = load_master_plan_json(tmp_path)
        assert len(plan.milestones) == 1
        m = plan.milestones[0]
        assert m.id == "milestone-1"
        assert m.template == "full_stack"
        assert m.merge_surfaces == ["package.json"]
        assert m.feature_refs == ["F-001"]
        assert m.ac_refs == ["AC-1", "AC-2", "AC-3"]
        assert m.stack_target == "nestjs+nextjs"
        assert m.complexity_estimate == {"entity_count": 3}

    def test_load_falls_back_to_md_and_writes_json(self, tmp_path: Path) -> None:
        """No JSON, only .md → parses .md and writes JSON eagerly."""
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        md = """\
# MASTER PLAN: demo
## Milestone 1: Foundation
- ID: milestone-1
- Status: PENDING
- Dependencies: none
- Template: full_stack
"""
        (agent_dir / "MASTER_PLAN.md").write_text(md)
        plan = load_master_plan_json(tmp_path)
        assert len(plan.milestones) == 1
        assert (agent_dir / "MASTER_PLAN.json").is_file()

    def test_load_raises_when_neither_exists(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_master_plan_json(tmp_path)

    def test_update_milestone_status_json(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        generate_master_plan_json(
            [_m("milestone-1", ac_refs=["AC-1", "AC-2", "AC-3"])],
            agent_dir / "MASTER_PLAN.json",
        )
        ok = update_milestone_status_json(tmp_path, "milestone-1", "COMPLETE")
        assert ok
        data = json.loads((agent_dir / "MASTER_PLAN.json").read_text())
        assert data["milestones"][0]["status"] == "COMPLETE"

    def test_update_milestone_status_json_unknown_id(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        generate_master_plan_json([_m("milestone-1")], agent_dir / "MASTER_PLAN.json")
        assert not update_milestone_status_json(tmp_path, "milestone-x", "COMPLETE")

    def test_generate_master_plan_md_from_json(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        generate_master_plan_json(
            [
                _m(
                    "milestone-5",
                    deps=["milestone-1"],
                    ac_refs=["AC-1", "AC-2", "AC-3", "AC-4", "AC-5"],
                    feature_refs=["F-003"],
                    description="Complete quotation approval vertical slice.",
                ),
            ],
            agent_dir / "MASTER_PLAN.json",
        )
        assert generate_master_plan_md(tmp_path) is True
        md = (agent_dir / "MASTER_PLAN.md").read_text()
        assert "## Milestone 5" in md
        assert "- ID: milestone-5" in md
        assert "- Template: full_stack" in md
        assert "- Features: F-003" in md
        assert "- AC-Refs: AC-1, AC-2, AC-3, AC-4, AC-5" in md
        # Round-trip readable by parse_master_plan
        plan = parse_master_plan(md)
        assert plan.milestones[0].id == "milestone-5"
        assert plan.milestones[0].feature_refs == ["F-003"]

    def test_full_plan_lifecycle(self, tmp_path: Path) -> None:
        """Parse .md → validate → compute order → write JSON → load JSON → update status."""
        md = """\
# MASTER PLAN: demo
## Milestone 1: Foundation
- ID: milestone-1
- Status: PENDING
- Dependencies: none
- Template: full_stack

## Milestone 2: Feature
- ID: milestone-2
- Status: PENDING
- Dependencies: milestone-1
- Template: full_stack
- AC-Refs: AC-1, AC-2, AC-3
"""
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir()
        (agent_dir / "MASTER_PLAN.md").write_text(md)

        plan = parse_master_plan(md)
        assert validate_plan(plan.milestones).valid
        order = compute_execution_order(plan.milestones)
        assert order == ["milestone-1", "milestone-2"]

        generate_master_plan_json(plan.milestones, agent_dir / "MASTER_PLAN.json")
        loaded = load_master_plan_json(tmp_path)
        assert [m.id for m in loaded.milestones] == ["milestone-1", "milestone-2"]

        update_milestone_status_json(tmp_path, "milestone-1", "COMPLETE")
        reloaded = load_master_plan_json(tmp_path)
        by_id = {m.id: m for m in reloaded.milestones}
        assert by_id["milestone-1"].status == "COMPLETE"
        assert by_id["milestone-2"].status == "PENDING"


# ---------------------------------------------------------------------------
# Fix 2 + Fix 3: planner prompt content / vertical-slice always on
# ---------------------------------------------------------------------------


class TestPlannerPrompt:
    def _build(self, planner_mode: str = "vertical_slice") -> str:
        cfg = AgentTeamConfig()
        cfg.v18 = V18Config(planner_mode=planner_mode)
        return agents_module.build_decomposition_prompt(
            task="demo task",
            depth="standard",
            config=cfg,
            v18_config=cfg.v18,
        )

    def test_prompt_example_includes_ac_refs(self) -> None:
        prompt = self._build()
        assert "AC-Refs:" in prompt

    def test_prompt_example_includes_stack_target(self) -> None:
        prompt = self._build()
        assert "Stack-Target:" in prompt

    def test_prompt_has_sizing_rules(self) -> None:
        prompt = self._build()
        assert "Minimum: 3 ACs" in prompt
        assert "Maximum: 13 ACs" in prompt

    def test_prompt_does_not_include_complexity_estimate(self) -> None:
        """complexity_estimate is computed by Python; never in the LLM prompt example."""
        prompt = self._build()
        # The prompt may mention the Product IR concept but the example milestone
        # block must NOT request a Complexity-Estimate field.
        assert "- Complexity-Estimate:" not in prompt
        assert "Complexity_Estimate:" not in prompt

    def test_vertical_slice_always_on_even_with_legacy_mode(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """planner_mode=legacy still uses vertical-slice phasing + logs a warning."""
        # Reset the one-shot deprecation flag so we can observe the warning
        agents_module._planner_mode_deprecation_warned = False
        with caplog.at_level(logging.WARNING, logger=agents_module.__name__):
            prompt = self._build(planner_mode="legacy")
        # Vertical-slice markers appear
        assert "VERTICAL SLICE MODE" in prompt
        # Legacy phasing markers DO NOT appear in the prompt
        assert "PHASE A: FOUNDATION" not in prompt
        assert "PHASE B: DOMAIN MODULES" not in prompt
        # Warning was emitted
        assert any(
            "deprecated" in r.getMessage() and "vertical_slice" in r.getMessage()
            for r in caplog.records
        )

    def test_default_planner_mode_is_vertical_slice(self) -> None:
        """V18Config default is vertical_slice (Fix 3)."""
        assert V18Config().planner_mode == "vertical_slice"


# ---------------------------------------------------------------------------
# Fix 5: complexity from IR
# ---------------------------------------------------------------------------


class TestComplexityFromIR:
    def test_has_expected_fields(self) -> None:
        milestone = _m(
            "milestone-5",
            feature_refs=["F-001"],
            description="Quotation approval",
        )
        ir = {
            "entities": [
                {"name": "Quotation", "feature_refs": ["F-001"]},
                {"name": "User", "feature_refs": ["F-002"]},
            ],
            "endpoints": [
                {"entity": "Quotation", "path": "/quotations"},
                {"entity": "Quotation", "path": "/quotations/:id"},
            ],
            "state_machines": [{"entity": "Quotation"}],
            "business_rules": [{"entities": ["Quotation"]}],
        }
        result = compute_milestone_complexity(milestone, ir)
        for key in (
            "entity_count",
            "endpoint_count",
            "state_machine_count",
            "business_rule_count",
            "has_frontend",
            "estimated_loc_range",
        ):
            assert key in result
        assert result["entity_count"] == 1
        assert result["endpoint_count"] == 2
        assert result["state_machine_count"] == 1
        assert result["business_rule_count"] == 1
        assert result["has_frontend"] is True

    def test_description_matches_entity_name(self) -> None:
        """When feature_refs don't match, fall back to description-name matching."""
        milestone = _m(
            "milestone-5",
            description="Manage Invoice workflow",
        )
        ir = {
            "entities": [{"name": "Invoice", "feature_refs": []}],
            "endpoints": [{"entity": "Invoice"}],
            "state_machines": [],
            "business_rules": [],
        }
        result = compute_milestone_complexity(milestone, ir)
        assert result["entity_count"] == 1
        assert result["endpoint_count"] == 1

    def test_empty_ir_yields_zero_counts(self) -> None:
        milestone = _m("milestone-1")
        result = compute_milestone_complexity(milestone, None)
        assert result["entity_count"] == 0
        assert result["endpoint_count"] == 0
        assert result["state_machine_count"] == 0
        assert result["business_rule_count"] == 0

    def test_backend_only_has_no_frontend(self) -> None:
        milestone = _m("milestone-3", template="backend_only")
        result = compute_milestone_complexity(milestone, {})
        assert result["has_frontend"] is False

    def test_frontend_only_has_frontend(self) -> None:
        milestone = _m("milestone-10", template="frontend_only")
        result = compute_milestone_complexity(milestone, {})
        assert result["has_frontend"] is True

    def test_loc_range_reflects_counts(self) -> None:
        """More entities/endpoints → larger LOC range."""
        small = compute_milestone_complexity(
            _m("milestone-small", feature_refs=["F"]),
            {"entities": [{"name": "E1", "feature_refs": ["F"]}], "endpoints": []},
        )
        big = compute_milestone_complexity(
            _m("milestone-big", feature_refs=["F"]),
            {
                "entities": [
                    {"name": f"E{i}", "feature_refs": ["F"]} for i in range(5)
                ],
                "endpoints": [{"entity": f"E{i}"} for i in range(10)],
            },
        )
        # Parse "low-high" strings
        small_high = int(small["estimated_loc_range"].split("-")[1])
        big_high = int(big["estimated_loc_range"].split("-")[1])
        assert big_high > small_high
