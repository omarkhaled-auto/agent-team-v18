from __future__ import annotations

import json
from pathlib import Path

from agent_team_v15.agents import (
    build_adapter_instructions,
    build_decomposition_prompt,
    build_milestone_execution_prompt,
)
from agent_team_v15.config import AgentTeamConfig, _dict_to_config, apply_depth_quality_gating
from agent_team_v15.milestone_manager import (
    MasterPlanMilestone,
    MilestoneContext,
    generate_master_plan_json,
    parse_master_plan,
)
from agent_team_v15.state import RunState, load_state, save_state


V18_PLAN = """# MASTER PLAN: EVS
Generated: 2026-04-08

## Milestone 5: Quotation Approval
- ID: milestone-5
- Status: PENDING
- Dependencies: milestone-3
- Template: full_stack
- Parallel-Group: A
- Features: F-003, F-004
- Merge-Surfaces: package.json, app.module.ts
- Stack-Target: nestjs+nextjs
- Complexity-Estimate: service_count: 1, page_count: 2
- Description: Complete quotation approval vertical slice
"""


class TestV18Config:
    def test_defaults_are_vertical_slice(self) -> None:
        # V18.1 Fix 3: vertical-slice is the only planner mode and is the default.
        # V18.2: evidence_mode="record_only" by default — records accumulate
        # but do NOT affect scoring. live_endpoint_check=True by default with
        # a graceful Docker-missing skip. Only "disabled" suppresses records.
        cfg = AgentTeamConfig()
        assert cfg.v18.planner_mode == "vertical_slice"
        assert cfg.v18.execution_mode == "single_call"
        assert cfg.v18.evidence_mode == "record_only"
        assert cfg.v18.live_endpoint_check is True
        assert cfg.v18.scaffold_enabled is False

    def test_standard_uses_vertical_slice(self) -> None:
        # V18.1 Fix 3: standard depth no longer falls back to legacy phasing —
        # vertical-slice is always on. Other V18 flags stay conservative.
        # V18.2: standard inherits the new record_only/live_endpoint_check=True
        # defaults (no depth preset downgrades them).
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg)
        assert cfg.v18.planner_mode == "vertical_slice"
        assert cfg.v18.execution_mode == "single_call"
        assert cfg.v18.evidence_mode == "record_only"
        assert cfg.v18.live_endpoint_check is True
        assert cfg.v18.git_isolation is False

    def test_thorough_enables_vertical_slice_only(self) -> None:
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("thorough", cfg)
        assert cfg.v18.planner_mode == "vertical_slice"
        assert cfg.v18.execution_mode == "single_call"
        # V18.2: thorough keeps record_only (no downgrade). exhaustive+ upgrades to soft_gate.
        assert cfg.v18.evidence_mode == "record_only"

    def test_explicit_v18_overrides_activate_later_phases(self) -> None:
        cfg, overrides = _dict_to_config(
            {
                "v18": {
                    "planner_mode": "vertical_slice",
                    "execution_mode": "wave",
                    "contract_mode": "openapi",
                    "evidence_mode": "soft_gate",
                    "live_endpoint_check": True,
                    "openapi_generation": True,
                }
            }
        )

        apply_depth_quality_gating("standard", cfg, overrides)

        assert cfg.v18.planner_mode == "vertical_slice"
        assert cfg.v18.execution_mode == "wave"
        assert cfg.v18.contract_mode == "openapi"
        assert cfg.v18.evidence_mode == "soft_gate"
        assert cfg.v18.live_endpoint_check is True
        assert cfg.v18.openapi_generation is True

    def test_enterprise_does_not_auto_enable_phase4_throughput(self) -> None:
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", cfg)
        assert cfg.v18.git_isolation is False
        assert cfg.v18.max_parallel_milestones == 1
        assert cfg.v18.scaffold_enabled is True

    def test_user_overrides_preserved(self) -> None:
        # V18.1 Fix 3: the value is still retained for backward compat even
        # though it is functionally deprecated — the planner itself always
        # uses vertical-slice phasing regardless. The depth preset must not
        # override the user-provided value.
        cfg, overrides = _dict_to_config({"v18": {"planner_mode": "legacy"}})
        apply_depth_quality_gating("enterprise", cfg, overrides)
        assert cfg.v18.planner_mode == "legacy"


class TestV18State:
    def test_schema_v3_round_trip(self, tmp_path: Path) -> None:
        state = RunState(
            task="build app",
            v18_config={"planner_mode": "vertical_slice"},
            wave_progress={
                "milestone-5": {
                    "current_wave": "B",
                    "completed_waves": ["A"],
                    "wave_artifacts": {"A": ".agent-team/artifacts/milestone-5-wave-A.json"},
                }
            },
        )

        save_state(state, str(tmp_path))
        loaded = load_state(str(tmp_path))

        assert loaded is not None
        assert loaded.schema_version == 3
        assert loaded.v18_config["planner_mode"] == "vertical_slice"
        assert loaded.wave_progress["milestone-5"]["current_wave"] == "B"

    def test_load_schema_v2_defaults_new_fields(self, tmp_path: Path) -> None:
        state_path = tmp_path / "STATE.json"
        state_path.write_text(
            json.dumps(
                {
                    "run_id": "r1",
                    "task": "legacy",
                    "schema_version": 2,
                    "current_phase": "orchestration",
                    "completed_phases": [],
                    "artifacts": {},
                    "milestone_progress": {},
                }
            ),
            encoding="utf-8",
        )

        loaded = load_state(str(tmp_path))
        assert loaded is not None
        assert loaded.schema_version == 3
        assert loaded.v18_config == {}
        assert loaded.wave_progress == {}


class TestV18MilestoneMetadata:
    def test_parse_v18_fields(self) -> None:
        plan = parse_master_plan(V18_PLAN)
        milestone = plan.milestones[0]

        assert milestone.template == "full_stack"
        assert milestone.parallel_group == "A"
        assert milestone.feature_refs == ["F-003", "F-004"]
        assert milestone.merge_surfaces == ["package.json", "app.module.ts"]
        assert milestone.stack_target == "nestjs+nextjs"
        assert milestone.complexity_estimate == {"service_count": 1, "page_count": 2}

    def test_generate_master_plan_json(self, tmp_path: Path) -> None:
        milestones = [
            MasterPlanMilestone(
                id="milestone-5",
                title="Quotation Approval",
                dependencies=["milestone-3"],
                template="full_stack",
                parallel_group="A",
                merge_surfaces=["package.json"],
                feature_refs=["F-003"],
                ac_refs=["AC-3"],
                stack_target="nestjs+nextjs",
                complexity_estimate={"service_count": 1},
            )
        ]

        output_path = tmp_path / "MASTER_PLAN.json"
        generate_master_plan_json(milestones, output_path)
        data = json.loads(output_path.read_text(encoding="utf-8"))

        assert data["schema_version"] == 1
        assert data["milestones"][0]["template"] == "full_stack"
        assert data["milestones"][0]["feature_refs"] == ["F-003"]
        assert data["milestones"][0]["complexity_estimate"] == {"service_count": 1}


class TestVerticalSlicePlanner:
    def test_default_prompt_is_vertical_slice(self) -> None:
        # V18.1 Fix 3: vertical-slice is the only planner. The legacy 5-phase
        # template is retained in the source as _LEGACY_PHASING for reference
        # only and is never injected into a generated prompt.
        cfg = AgentTeamConfig()
        prompt = build_decomposition_prompt("Build app", "standard", cfg)
        assert "VERTICAL SLICE MODE" in prompt
        assert "PHASE A: FOUNDATION" not in prompt
        assert "PHASE B: DOMAIN MODULES" not in prompt

    def test_vertical_slice_prompt_switches_when_enabled(self) -> None:
        cfg = AgentTeamConfig()
        cfg.v18.planner_mode = "vertical_slice"
        prompt = build_decomposition_prompt(
            "Build app",
            "thorough",
            cfg,
            v18_config=cfg.v18,
        )
        assert "VERTICAL SLICE MODE" in prompt
        assert "Parallel-Group" in prompt
        assert "STOP after creating the plan" in prompt

    def test_vertical_slice_prompt_uses_config_v18_by_default(self) -> None:
        cfg = AgentTeamConfig()
        cfg.v18.planner_mode = "vertical_slice"
        prompt = build_decomposition_prompt("Build app", "exhaustive", cfg)
        assert "VERTICAL SLICE MODE" in prompt
        assert "DO NOT create separate \"Backend\", \"Frontend\", or \"Testing\" milestones." in prompt

    def test_chunked_vertical_slice_prompt_keeps_vertical_slice_metadata(self) -> None:
        cfg = AgentTeamConfig()
        cfg.v18.planner_mode = "vertical_slice"
        prompt = build_decomposition_prompt(
            task="Build app",
            depth="exhaustive",
            config=cfg,
            prd_chunks=[{"file": ".agent-team/prd-chunks/feature-a.md", "focus": "feature a", "name": "feature-a"}],
            prd_index={"feature-a": {"heading": "Feature A", "size_bytes": 123}},
            v18_config=cfg.v18,
        )
        assert "VERTICAL SLICE MODE" in prompt
        assert "Template: full_stack" in prompt
        assert "Parallel-Group: A" in prompt


class TestAdapterPromptInjection:
    def test_build_adapter_instructions_empty(self) -> None:
        assert build_adapter_instructions([]) == ""

    def test_build_adapter_instructions_contains_interface_details(self) -> None:
        instructions = build_adapter_instructions(
            [{"vendor": "Stripe", "type": "payment", "port_name": "IPaymentProvider"}]
        )
        assert "stripe.port.ts" in instructions
        assert "stripe.adapter.ts" in instructions
        assert "stripe.simulator.ts" in instructions
        assert "IPaymentProvider" in instructions

    def test_adapter_instructions_only_injected_for_foundation_vertical_slice(self, tmp_path: Path) -> None:
        integrations_dir = tmp_path / ".agent-team" / "product-ir"
        integrations_dir.mkdir(parents=True, exist_ok=True)
        (integrations_dir / "integrations.ir.json").write_text(
            json.dumps(
                [{"vendor": "Stripe", "type": "payment", "port_name": "IPaymentProvider"}]
            ),
            encoding="utf-8",
        )

        cfg = AgentTeamConfig()
        cfg.v18.planner_mode = "vertical_slice"
        foundation_prompt = build_milestone_execution_prompt(
            task="Build portal with NestJS backend",
            depth="thorough",
            config=cfg,
            milestone_context=MilestoneContext(
                milestone_id="milestone-1",
                title="Platform Foundation",
                requirements_path="req.md",
            ),
            cwd=str(tmp_path),
        )
        later_prompt = build_milestone_execution_prompt(
            task="Build portal with NestJS backend",
            depth="thorough",
            config=cfg,
            milestone_context=MilestoneContext(
                milestone_id="milestone-2",
                title="Auth",
                requirements_path="req.md",
            ),
            cwd=str(tmp_path),
        )

        assert "stripe.port.ts" in foundation_prompt
        assert "IPaymentProvider" in foundation_prompt
        assert "stripe.port.ts" not in later_prompt
