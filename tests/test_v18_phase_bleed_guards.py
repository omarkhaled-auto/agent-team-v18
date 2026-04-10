from __future__ import annotations

import json
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import cli as cli_module
from agent_team_v15 import wave_executor as wave_executor_module
from agent_team_v15.agents import build_wave_e_prompt
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(
        id="milestone-orders",
        title="Orders",
        template="full_stack",
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _prompt() -> str:
    return build_wave_e_prompt(
        milestone=_milestone(),
        ir={"acceptance_criteria": [{"id": "AC-1", "feature": "F-ORDERS", "text": "Show orders"}]},
        wave_artifacts={"A": {"files_created": ["apps/api/src/orders/order.entity.ts"]}},
        config=AgentTeamConfig(),
        existing_prompt_framework="FRAMEWORK_MARKER",
    )


class TestPhaseBleedGuards:
    def test_wave_e_prompt_no_playwright(self) -> None:
        prompt = _prompt()
        assert "Write 2-3 focused Playwright" not in prompt
        assert "npx playwright test" not in prompt

    def test_wave_e_prompt_no_evidence_creation_in_disabled_mode(self) -> None:
        prompt = _prompt()
        assert "produce evidence records" not in prompt.lower()
        assert "evidence_ledger" not in prompt.lower()

    def test_wave_e_prompt_contains_requirements_md(self) -> None:
        prompt = _prompt()
        assert "REQUIREMENTS.md" in prompt
        assert "[x]" in prompt

    def test_wave_e_prompt_contains_tasks_md(self) -> None:
        prompt = _prompt()
        assert "TASKS.md" in prompt

    def test_wave_e_soft_gate_contains_scanners(self) -> None:
        config = AgentTeamConfig()
        config.v18.evidence_mode = "soft_gate"
        config.v18.live_endpoint_check = True
        prompt = build_wave_e_prompt(
            milestone=_milestone(),
            ir={"acceptance_criteria": [{"id": "AC-1", "feature": "F-ORDERS", "text": "Show orders"}]},
            wave_artifacts={"A": {"files_created": ["apps/api/src/orders/order.entity.ts"]}},
            config=config,
            existing_prompt_framework="FRAMEWORK_MARKER",
        )
        assert "[WIRING SCANNER - REQUIRED]" in prompt
        assert "[I18N SCANNER - REQUIRED]" in prompt
        assert "[PLAYWRIGHT TESTS - REQUIRED]" in prompt

    def test_wave_executor_gates_prober_on_live_endpoint_flag(self) -> None:
        source = inspect.getsource(wave_executor_module)
        assert "_live_endpoint_check_enabled" in source
        assert "_run_wave_b_probing" in source

    def test_no_parallel_milestone_code(self) -> None:
        source = inspect.getsource(wave_executor_module)
        assert "asyncio.gather" not in source
        assert "worktree" not in source.lower()

    def test_depth_gating_does_not_auto_enable_phase4_throughput(self) -> None:
        exhaustive = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", exhaustive)
        assert exhaustive.v18.git_isolation is False
        assert exhaustive.v18.max_parallel_milestones == 1

        enterprise = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", enterprise)
        assert enterprise.v18.git_isolation is False
        assert enterprise.v18.max_parallel_milestones == 1

    def test_standard_depth_does_not_auto_enable_wave_execution(self) -> None:
        config = AgentTeamConfig()
        apply_depth_quality_gating("standard", config)

        assert config.v18.planner_mode == "legacy"
        assert cli_module._wave_execution_enabled(config) is False

    def test_thorough_depth_stays_planner_only(self) -> None:
        config = AgentTeamConfig()
        apply_depth_quality_gating("thorough", config)

        assert config.v18.planner_mode == "vertical_slice"
        assert cli_module._wave_execution_enabled(config) is False

    def test_explicit_wave_override_still_enables_wave_execution(self) -> None:
        config = AgentTeamConfig()
        config.v18.execution_mode = "wave"

        assert cli_module._wave_execution_enabled(config) is True

    def test_cli_phase3_wave_mode_cannot_enter_phase4_isolation_path(self) -> None:
        config = AgentTeamConfig()
        config.v18.git_isolation = True
        config.v18.execution_mode = "wave"
        assert cli_module._phase4_parallel_isolation_enabled(config) is False

        config.v18.execution_mode = "phase4_parallel"
        assert cli_module._phase4_parallel_isolation_enabled(config) is True

    @pytest.mark.asyncio
    async def test_wave_e_phase2_tracking_helper_does_not_run_when_evidence_mode_is_active(self, tmp_path: Path) -> None:
        milestone = SimpleNamespace(
            id="milestone-orders",
            title="Orders",
            template="backend_only",
            description="Orders milestone",
            dependencies=[],
            feature_refs=["F-ORDERS"],
            merge_surfaces=[],
            stack_target="NestJS Next.js",
        )
        config = AgentTeamConfig()
        config.v18.execution_mode = "wave"
        config.v18.evidence_mode = "soft_gate"
        config.v18.live_endpoint_check = False

        milestone_dir = tmp_path / ".agent-team" / "milestones" / milestone.id
        milestone_dir.mkdir(parents=True, exist_ok=True)
        (milestone_dir / "REQUIREMENTS.md").write_text(
            "- [ ] REQ-101: Implement orders API.\n",
            encoding="utf-8",
        )
        (milestone_dir / "TASKS.md").write_text(
            "\n".join(
                [
                    "### TASK-001",
                    "Description: Implement orders API.",
                    "Files:",
                    "- src/orders.module.ts",
                    "Status: DONE",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        src_path = tmp_path / "src" / "orders.module.ts"
        src_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.write_text("export const ordersModule = true;\n", encoding="utf-8")

        async def build_prompt(**kwargs):
            return f"wave {kwargs['wave']}"

        async def execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
            if role == "wave":
                src_path.write_text(src_path.read_text(encoding="utf-8") + f"// {wave}\n", encoding="utf-8")
            return 1.0

        async def run_compile_check(**_: object) -> dict[str, object]:
            return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

        async def generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
            milestone_id = getattr(milestone, "id", "milestone-orders")
            current_spec = tmp_path / "contracts" / "openapi" / "current.json"
            current_spec.parent.mkdir(parents=True, exist_ok=True)
            current_spec.write_text(json.dumps({"paths": {"/orders": {"get": {}}}}), encoding="utf-8")
            local_spec = tmp_path / "contracts" / "openapi" / f"{milestone_id}.json"
            local_spec.write_text(json.dumps({"paths": {"/orders": {"get": {}}}}), encoding="utf-8")
            return {
                "success": True,
                "milestone_spec_path": str(local_spec),
                "cumulative_spec_path": str(current_spec),
                "client_exports": ["listOrders"],
                "breaking_changes": [],
                "endpoints_summary": [{"method": "GET", "path": "/orders"}],
                "files_created": [],
            }

        result = await wave_executor_module.execute_milestone_waves(
            milestone=milestone,
            ir={},
            config=config,
            cwd=str(tmp_path),
            build_wave_prompt=build_prompt,
            execute_sdk_call=execute_sdk_call,
            run_compile_check=run_compile_check,
            extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
            generate_contracts=generate_contracts,
            run_scaffolding=None,
            save_wave_state=None,
        )

        assert result.success is True
        requirements = (milestone_dir / "REQUIREMENTS.md").read_text(encoding="utf-8")
        tasks = (milestone_dir / "TASKS.md").read_text(encoding="utf-8")
        assert "- [ ] REQ-101: Implement orders API." in requirements
        assert "(review_cycles:" not in requirements
        assert "Status: DONE" in tasks
