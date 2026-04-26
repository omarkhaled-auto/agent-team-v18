"""V18.2 Wave T (comprehensive test wave) tests.

Wave T sits between Wave D.5 and Wave E. Claude writes exhaustive backend
+ frontend tests whose purpose is to VERIFY the code is correct — never
weakened to pass.

Core principle (embedded verbatim in the prompt):
    "tests verify code, code doesn't dictate tests"

Wave T ALWAYS routes to Claude (never Codex).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import wave_executor as wave_executor_module
from agent_team_v15.agents import (
    WAVE_T_CORE_PRINCIPLE,
    build_wave_prompt,
    build_wave_t_fix_prompt,
    build_wave_t_prompt,
)
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_executor import (
    WaveFinding,
    WaveResult,
    _execute_wave_t,
    _wave_sequence,
    _wave_t_enabled,
    _wave_t_max_fix_iterations,
)


FRAMEWORK_MARKER = "FRAMEWORK_MARKER"


def _milestone(template: str = "full_stack", milestone_id: str = "milestone-T") -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title="Orders",
        template=template,
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _ir() -> dict[str, object]:
    return {
        "acceptance_criteria": [
            {"id": "AC-1", "feature": "F-ORDERS", "text": "Show orders list"}
        ]
    }


# ---------------------------------------------------------------------------
# Wave sequences
# ---------------------------------------------------------------------------


class TestWaveTSequences:
    def test_wave_t_in_all_sequences(self) -> None:
        """Wave T present in full_stack, backend_only, and frontend_only (default on)."""
        cfg = AgentTeamConfig()
        for template in ("full_stack", "backend_only", "frontend_only"):
            waves = _wave_sequence(template, cfg)
            assert "T" in waves, f"template={template}"

    def test_wave_t_immediately_before_wave_e(self) -> None:
        cfg = AgentTeamConfig()
        for template in ("full_stack", "backend_only", "frontend_only"):
            waves = _wave_sequence(template, cfg)
            assert waves.index("T") + 1 == waves.index("E"), f"template={template}"

    def test_wave_t_disabled_skips_to_wave_e(self) -> None:
        """wave_t_enabled=False skips T; pipeline goes D5 → E."""
        cfg = AgentTeamConfig()
        cfg.v18.wave_t_enabled = False
        for template in ("full_stack", "backend_only", "frontend_only"):
            assert "T" not in _wave_sequence(template, cfg), f"template={template}"


# ---------------------------------------------------------------------------
# Prompt content
# ---------------------------------------------------------------------------


class TestWaveTPromptContent:
    def test_prompt_includes_core_principle_verbatim(self) -> None:
        prompt = build_wave_t_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )
        assert WAVE_T_CORE_PRINCIPLE in prompt

    def test_prompt_never_weaken_assertions(self) -> None:
        """Prompt contains 'NEVER weaken an assertion to make a test pass'."""
        prompt = build_wave_t_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )
        assert "NEVER weaken an assertion to make a test pass" in prompt
        assert "NEVER mock away real behavior" in prompt
        assert "NEVER skip a test" in prompt
        assert "NEVER change an expected value" in prompt
        assert "The test is the specification" in prompt

    def test_prompt_backend_only_omits_frontend_section(self) -> None:
        prompt = build_wave_t_prompt(
            milestone=_milestone(template="backend_only"),
            ir=_ir(),
            wave_artifacts={},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )
        assert "[BACKEND TEST INVENTORY]" in prompt
        assert "[FRONTEND TEST INVENTORY]" not in prompt

    def test_prompt_frontend_only_omits_backend_section(self) -> None:
        prompt = build_wave_t_prompt(
            milestone=_milestone(template="frontend_only"),
            ir=_ir(),
            wave_artifacts={},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )
        assert "[FRONTEND TEST INVENTORY]" in prompt
        assert "[BACKEND TEST INVENTORY]" not in prompt

    def test_prompt_includes_test_framework_and_location(self) -> None:
        prompt = build_wave_t_prompt(
            milestone=_milestone(),
            ir=_ir(),
            wave_artifacts={},
            config=AgentTeamConfig(),
            existing_prompt_framework=FRAMEWORK_MARKER,
        )
        assert "Jest" in prompt
        assert "apps/api/src/**/*.spec.ts" in prompt
        assert "apps/web/src/**/*.test.tsx" in prompt

    def test_dispatcher_routes_wave_t(self) -> None:
        prompt = build_wave_prompt(
            wave="T",
            milestone=_milestone(),
            wave_artifacts={},
            dependency_artifacts={},
            ir=_ir(),
            config=AgentTeamConfig(),
            scaffolded_files=[],
        )
        assert "[WAVE T - COMPREHENSIVE TEST WAVE]" in prompt
        assert "NEVER weaken an assertion" in prompt


class TestWaveTFixPrompt:
    def test_fix_prompt_includes_core_principle(self) -> None:
        fp = build_wave_t_fix_prompt(
            milestone=_milestone(),
            failures=[{"file": "x.spec.ts", "test": "t1", "message": "bad"}],
            iteration=0,
            max_iterations=2,
        )
        assert WAVE_T_CORE_PRINCIPLE in fp
        assert "NEVER weaken" in fp

    def test_fix_prompt_shows_iteration_counter(self) -> None:
        fp = build_wave_t_fix_prompt(
            milestone=_milestone(),
            failures=[],
            iteration=1,
            max_iterations=2,
        )
        assert "ITERATION 2/2" in fp

    def test_fix_prompt_stop_criterion_for_structural(self) -> None:
        fp = build_wave_t_fix_prompt(
            milestone=_milestone(),
            failures=[],
            iteration=0,
            max_iterations=2,
        )
        assert "STRUCTURAL" in fp
        assert "STOP" in fp


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


class TestWaveTConfigHelpers:
    def test_wave_t_enabled_default_true(self) -> None:
        assert _wave_t_enabled(AgentTeamConfig()) is True

    def test_wave_t_enabled_explicit_false(self) -> None:
        cfg = AgentTeamConfig()
        cfg.v18.wave_t_enabled = False
        assert _wave_t_enabled(cfg) is False

    def test_wave_t_max_fix_iterations_default_2(self) -> None:
        assert _wave_t_max_fix_iterations(AgentTeamConfig()) == 2

    def test_wave_t_max_fix_iterations_user_override(self) -> None:
        cfg = AgentTeamConfig()
        cfg.v18.wave_t_max_fix_iterations = 5
        assert _wave_t_max_fix_iterations(cfg) == 5

    def test_wave_t_max_fix_iterations_handles_negative(self) -> None:
        cfg = AgentTeamConfig()
        cfg.v18.wave_t_max_fix_iterations = -1
        assert _wave_t_max_fix_iterations(cfg) == 0


# ---------------------------------------------------------------------------
# Handler routing + telemetry
# ---------------------------------------------------------------------------


class TestWaveTHandler:
    @pytest.mark.asyncio
    async def test_wave_t_always_routes_to_claude(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wave T provider is always 'claude' regardless of provider_map."""

        async def build_prompt(**kwargs: object) -> str:
            return f"wave {kwargs['wave']}"

        async def execute_sdk_call(**_kwargs: object) -> float:
            return 1.0

        async def run_compile_check(**_kwargs: object) -> dict[str, object]:
            return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

        result = await _execute_wave_t(
            execute_sdk_call=execute_sdk_call,
            build_wave_prompt=build_prompt,
            run_compile_check=run_compile_check,
            milestone=_milestone(),
            ir=_ir(),
            config=AgentTeamConfig(),
            cwd=str(tmp_path),
            template="full_stack",
            wave_artifacts={},
            dependency_artifacts={},
            scaffolded_files=[],
        )

        assert result.wave == "T"
        assert result.provider == "claude"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_wave_t_counts_written_tests(self, tmp_path: Path) -> None:
        """Wave T telemetry records tests_written from checkpoint diff."""

        async def build_prompt(**kwargs: object) -> str:
            return f"wave {kwargs['wave']}"

        async def execute_sdk_call(**_kwargs: object) -> float:
            # Simulate Claude writing two test files during Wave T.
            (tmp_path / "apps" / "api" / "src").mkdir(parents=True, exist_ok=True)
            (tmp_path / "apps" / "api" / "src" / "orders.service.spec.ts").write_text(
                "describe('orders', () => { it('passes', () => { expect(1).toBe(1); }); });\n",
                encoding="utf-8",
            )
            (tmp_path / "apps" / "web" / "src").mkdir(parents=True, exist_ok=True)
            (tmp_path / "apps" / "web" / "src" / "OrdersPage.test.tsx").write_text(
                "test('renders', () => { expect(true).toBe(true); });\n",
                encoding="utf-8",
            )
            return 1.0

        async def run_compile_check(**_kwargs: object) -> dict[str, object]:
            return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

        result = await _execute_wave_t(
            execute_sdk_call=execute_sdk_call,
            build_wave_prompt=build_prompt,
            run_compile_check=run_compile_check,
            milestone=_milestone(),
            ir=_ir(),
            config=AgentTeamConfig(),
            cwd=str(tmp_path),
            template="full_stack",
            wave_artifacts={},
            dependency_artifacts={},
            scaffolded_files=[],
        )

        assert result.tests_written == 2

    @pytest.mark.asyncio
    async def test_wave_t_fix_loop_max_iterations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fix loop stops after wave_t_max_fix_iterations iterations."""

        fix_iterations_observed: list[int] = []

        async def build_prompt(**kwargs: object) -> str:
            return f"wave {kwargs['wave']}"

        async def execute_sdk_call(*, role: str = "wave", **_kwargs: object) -> float:
            if role == "test_fix":
                fix_iterations_observed.append(1)
            return 1.0

        async def run_compile_check(**_kwargs: object) -> dict[str, object]:
            return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

        # Simulate persistent test failures by stubbing _run_node_tests.
        async def _fake_node_tests(cwd: str, subdir: str, timeout: float):
            return True, 0, 3, "3 failed"

        monkeypatch.setattr(wave_executor_module, "_run_node_tests", _fake_node_tests)

        cfg = AgentTeamConfig()
        cfg.v18.wave_t_max_fix_iterations = 2

        result = await _execute_wave_t(
            execute_sdk_call=execute_sdk_call,
            build_wave_prompt=build_prompt,
            run_compile_check=run_compile_check,
            milestone=_milestone(),
            ir=_ir(),
            config=cfg,
            cwd=str(tmp_path),
            template="full_stack",
            wave_artifacts={},
            dependency_artifacts={},
            scaffolded_files=[],
        )

        assert result.fix_iterations == 2
        assert len(fix_iterations_observed) == 2
        assert result.tests_failed_final > 0
        # Remaining failures must be logged as a TEST-FAIL finding.
        assert any(f.code == "TEST-FAIL" for f in result.findings)
        assert result.structural_findings_logged == 1

    @pytest.mark.asyncio
    async def test_wave_t_logs_structural_findings_not_fixes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Structural app bugs (persistent failures) become TEST-FAIL findings."""

        async def build_prompt(**kwargs: object) -> str:
            return f"wave {kwargs['wave']}"

        async def execute_sdk_call(**_kwargs: object) -> float:
            return 1.0

        async def run_compile_check(**_kwargs: object) -> dict[str, object]:
            return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

        async def _fake_node_tests(cwd: str, subdir: str, timeout: float):
            # Simulate failures that never resolve — Wave T should give up
            # after max_iterations and log a TEST-FAIL finding.
            return True, 5, 2, "2 failed"

        monkeypatch.setattr(wave_executor_module, "_run_node_tests", _fake_node_tests)

        result = await _execute_wave_t(
            execute_sdk_call=execute_sdk_call,
            build_wave_prompt=build_prompt,
            run_compile_check=run_compile_check,
            milestone=_milestone(),
            ir=_ir(),
            config=AgentTeamConfig(),
            cwd=str(tmp_path),
            template="full_stack",
            wave_artifacts={},
            dependency_artifacts={},
            scaffolded_files=[],
        )

        # Wave T does NOT fail the milestone even when tests still fail —
        # it logs findings instead.
        assert result.success is True
        assert result.structural_findings_logged == 1
        codes = [f.code for f in result.findings]
        assert "TEST-FAIL" in codes

    @pytest.mark.asyncio
    async def test_wave_t_checkpoint_rollback_on_compile_break(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wave T rolls back if fix iterations break compilation."""

        async def build_prompt(**kwargs: object) -> str:
            return f"wave {kwargs['wave']}"

        async def execute_sdk_call(*, role: str = "wave", cwd: str, **_kwargs: object) -> float:
            if role == "wave":
                # Claude writes a test file.
                (tmp_path / "src").mkdir(parents=True, exist_ok=True)
                (tmp_path / "src" / "a.spec.ts").write_text("// test\n", encoding="utf-8")
            else:  # test_fix — writes broken code
                (tmp_path / "src" / "broken.ts").write_text("syntax error!!\n", encoding="utf-8")
            return 1.0

        compile_call_count = {"n": 0}

        async def run_compile_check(**_kwargs: object) -> dict[str, object]:
            compile_call_count["n"] += 1
            # Fail compile so Wave T triggers rollback.
            return {
                "passed": False,
                "iterations": 1,
                "initial_error_count": 1,
                "errors": [{"file": "src/broken.ts", "line": 1, "message": "broken"}],
            }

        async def _fake_node_tests(cwd: str, subdir: str, timeout: float):
            return True, 0, 1, "1 failed"

        monkeypatch.setattr(wave_executor_module, "_run_node_tests", _fake_node_tests)

        cfg = AgentTeamConfig()
        cfg.v18.wave_t_max_fix_iterations = 1

        result = await _execute_wave_t(
            execute_sdk_call=execute_sdk_call,
            build_wave_prompt=build_prompt,
            run_compile_check=run_compile_check,
            milestone=_milestone(),
            ir=_ir(),
            config=cfg,
            cwd=str(tmp_path),
            template="full_stack",
            wave_artifacts={},
            dependency_artifacts={},
            scaffolded_files=[],
        )

        assert result.rolled_back is True
        # The broken file introduced during the fix iteration must be gone.
        assert not (tmp_path / "src" / "broken.ts").exists()
        # A WAVE-T-ROLLBACK finding must be logged.
        assert any(f.code == "WAVE-T-ROLLBACK" for f in result.findings)

    @pytest.mark.asyncio
    async def test_wave_t_disabled_skips_to_wave_e(self, tmp_path: Path) -> None:
        """When wave_t_enabled=False, the sequence goes D5 → E directly."""
        cfg = AgentTeamConfig()
        cfg.v18.wave_t_enabled = False
        for template in ("full_stack", "backend_only", "frontend_only"):
            waves = _wave_sequence(template, cfg)
            assert "T" not in waves
            if "D5" in waves and "E" in waves:
                assert waves.index("D5") + 1 == waves.index("E")


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


class TestWaveTTelemetry:
    def test_wave_result_has_wave_t_fields(self) -> None:
        """WaveResult exposes Wave T telemetry fields."""
        r = WaveResult(wave="T")
        for field_name in (
            "tests_written",
            "tests_passed_initial",
            "tests_failed_initial",
            "tests_passed_final",
            "tests_failed_final",
            "fix_iterations",
            "app_code_fixes",
            "test_code_fixes",
            "structural_findings_logged",
        ):
            assert hasattr(r, field_name), f"missing: {field_name}"

    def test_save_wave_telemetry_includes_wave_t_fields(self, tmp_path: Path) -> None:
        result = WaveResult(
            wave="T",
            tests_written=24,
            tests_passed_initial=18,
            tests_failed_initial=6,
            tests_passed_final=23,
            tests_failed_final=1,
            fix_iterations=2,
            app_code_fixes=3,
            test_code_fixes=2,
            structural_findings_logged=1,
            scope_violations=["apps/api/src/main.ts"],
            wave_t_summary={"tests_written": {"backend": 1, "frontend": 1, "total": 2}},
            wave_t_summary_path=".agent-team/milestones/M1/WAVE_T_SUMMARY.json",
            timestamp="2026-04-12T00:00:00+00:00",
        )
        result.findings.append(
            WaveFinding(code="TEST-FAIL", severity="HIGH", file="", line=0, message="1 failing")
        )

        wave_executor_module.save_wave_telemetry(result, str(tmp_path), milestone_id="M1")

        telemetry_path = tmp_path / ".agent-team" / "telemetry" / "M1-wave-T.json"
        assert telemetry_path.is_file()

        payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
        assert payload["wave"] == "T"
        assert payload["tests_written"] == 24
        assert payload["fix_iterations"] == 2
        assert payload["app_code_fixes"] == 3
        assert payload["structural_findings_logged"] == 1
        assert payload["scope_violations"] == ["apps/api/src/main.ts"]
        assert payload["wave_t_summary"]["tests_written"]["total"] == 2
        assert payload["wave_t_summary_path"].endswith("WAVE_T_SUMMARY.json")
        assert any(f["code"] == "TEST-FAIL" for f in payload["findings"])
