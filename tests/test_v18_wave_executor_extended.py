from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import wave_executor as wave_executor_module
from agent_team_v15.wave_executor import WaveResult, execute_milestone_waves


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _milestone(
    milestone_id: str = "milestone-orders",
    *,
    template: str = "full_stack",
    dependencies: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title="Orders",
        template=template,
        description="Orders milestone",
        dependencies=dependencies or [],
        feature_refs=["F-ORDERS"],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


async def _run_waves(
    root: Path,
    *,
    template: str = "full_stack",
    compile_fail_wave: str | None = None,
    on_wave_complete=None,
    build_prompt=None,
) -> tuple[object, list[tuple[str, str]]]:
    milestone = _milestone(template=template)
    sdk_calls: list[tuple[str, str]] = []

    async def _build_prompt(**kwargs: object) -> str:
        if build_prompt is not None:
            return str(await build_prompt(**kwargs))
        return f"wave {kwargs['wave']}"

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        sdk_calls.append((wave, role))
        if role == "wave":
            _write(root / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
        return 1.5

    async def _run_compile_check(*, wave: str = "", **_: object) -> dict[str, object]:
        if wave == compile_fail_wave:
            return {
                "passed": False,
                "iterations": 1,
                "initial_error_count": 1,
                "errors": [{"file": f"src/{wave.lower()}.ts", "line": 1, "message": "broken"}],
            }
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _extract_artifacts(**kwargs: object) -> dict[str, object]:
        return {
            "wave": kwargs["wave"],
            "files_created": list(kwargs.get("files_created", []) or []),
            "files_modified": list(kwargs.get("files_modified", []) or []),
        }

    async def _generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
        milestone_id = getattr(milestone, "id", "milestone-orders")
        current_spec = _write(Path(cwd) / "contracts" / "openapi" / "current.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
        local_spec = _write(Path(cwd) / "contracts" / "openapi" / f"{milestone_id}.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
        return {
            "success": True,
            "milestone_spec_path": str(local_spec),
            "cumulative_spec_path": str(current_spec),
            "client_exports": ["listOrders"],
            "client_manifest": [
                {
                    "symbol": "listOrders",
                    "method": "GET",
                    "path": "/orders",
                    "request_type": "void",
                    "response_type": "Order[]",
                }
            ],
            "breaking_changes": [],
            "endpoints_summary": [{"method": "GET", "path": "/orders"}],
            "files_created": [
                str(local_spec.relative_to(cwd)).replace("\\", "/"),
                str(current_spec.relative_to(cwd)).replace("\\", "/"),
            ],
        }

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={"project_name": "Demo"},
        config=SimpleNamespace(),
        cwd=str(root),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=_extract_artifacts,
        generate_contracts=_generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
        on_wave_complete=on_wave_complete,
    )
    return result, sdk_calls


class TestWaveTemplateRouting:
    @pytest.mark.asyncio
    async def test_full_stack_executes_all_six_waves(self, tmp_path: Path) -> None:
        result, _ = await _run_waves(tmp_path, template="full_stack")
        assert [wave.wave for wave in result.waves] == ["A", "B", "C", "D", "D5", "E"]

    @pytest.mark.asyncio
    async def test_backend_only_skips_wave_d(self, tmp_path: Path) -> None:
        result, _ = await _run_waves(tmp_path, template="backend_only")
        assert [wave.wave for wave in result.waves] == ["A", "B", "C", "E"]

    @pytest.mark.asyncio
    async def test_frontend_only_starts_at_wave_d(self, tmp_path: Path) -> None:
        result, _ = await _run_waves(tmp_path, template="frontend_only")
        assert [wave.wave for wave in result.waves] == ["A", "D", "D5", "E"]

    @pytest.mark.asyncio
    async def test_unknown_template_falls_back_to_full_stack(self, tmp_path: Path) -> None:
        result, _ = await _run_waves(tmp_path, template="mystery_mode")
        assert [wave.wave for wave in result.waves] == ["A", "B", "C", "D", "D5", "E"]


class TestWaveResumeExtended:
    def test_resume_after_wave_a_starts_at_wave_b(self, tmp_path: Path) -> None:
        state_path = tmp_path / ".agent-team" / "STATE.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"wave_progress": {"milestone-orders": {"completed_waves": ["A"]}}}), encoding="utf-8")

        assert wave_executor_module._get_resume_wave("milestone-orders", "full_stack", str(tmp_path)) == "B"

    def test_resume_after_wave_c_starts_at_wave_d(self, tmp_path: Path) -> None:
        state_path = tmp_path / ".agent-team" / "STATE.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"wave_progress": {"milestone-orders": {"completed_waves": ["A", "B", "C"]}}}),
            encoding="utf-8",
        )

        assert wave_executor_module._get_resume_wave("milestone-orders", "full_stack", str(tmp_path)) == "D"

    def test_resume_with_all_complete_returns_last_wave(self, tmp_path: Path) -> None:
        state_path = tmp_path / ".agent-team" / "STATE.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"wave_progress": {"milestone-orders": {"completed_waves": ["A", "B", "C", "D", "D5", "E"]}}}),
            encoding="utf-8",
        )

        assert wave_executor_module._get_resume_wave("milestone-orders", "full_stack", str(tmp_path)) == "E"

    @pytest.mark.asyncio
    async def test_resume_loads_existing_artifacts(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".agent-team"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "STATE.json").write_text(
            json.dumps(
                {
                    "wave_progress": {
                        "milestone-orders": {
                            "completed_waves": ["A", "B", "C"],
                            "wave_artifacts": {
                                "A": str(state_dir / "artifacts" / "milestone-orders-wave-A.json"),
                                "B": str(state_dir / "artifacts" / "milestone-orders-wave-B.json"),
                                "C": str(state_dir / "artifacts" / "milestone-orders-wave-C.json"),
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        artifact_dir = state_dir / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for wave in ("A", "B", "C"):
            (artifact_dir / f"milestone-orders-wave-{wave}.json").write_text(
                json.dumps({"wave": wave, "marker": f"{wave}-artifact"}),
                encoding="utf-8",
            )

        captured: dict[str, dict[str, object]] = {}

        async def _build_prompt(**kwargs: object) -> str:
            captured[str(kwargs["wave"])] = dict(kwargs["wave_artifacts"])
            return f"wave {kwargs['wave']}"

        result, _ = await _run_waves(tmp_path, build_prompt=_build_prompt)

        assert [wave.wave for wave in result.waves] == ["D", "D5", "E"]
        assert set(captured["D"]) == {"A", "B", "C"}
        assert captured["D"]["C"]["marker"] == "C-artifact"


class TestWaveCostAggregation:
    @pytest.mark.asyncio
    async def test_total_cost_sums_all_waves(self, tmp_path: Path) -> None:
        result, _ = await _run_waves(tmp_path, template="full_stack")
        assert result.total_cost == pytest.approx(sum(wave.cost for wave in result.waves))

    @pytest.mark.asyncio
    async def test_wave_c_has_zero_cost(self, tmp_path: Path) -> None:
        result, _ = await _run_waves(tmp_path, template="full_stack")
        wave_c = next(wave for wave in result.waves if wave.wave == "C")
        assert wave_c.cost == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_prompt_builder_receives_cwd_for_live_wave_prompts(self, tmp_path: Path) -> None:
        seen_cwds: list[str] = []

        async def _capture_prompt(**kwargs: object) -> str:
            seen_cwds.append(str(kwargs.get("cwd", "")))
            return f"wave {kwargs['wave']}"

        await _run_waves(tmp_path, template="full_stack", build_prompt=_capture_prompt)

        assert seen_cwds
        assert set(seen_cwds) == {str(tmp_path)}

    @pytest.mark.asyncio
    async def test_wave_d_receives_structured_client_manifest_from_wave_c(self, tmp_path: Path) -> None:
        captured_wave_c_artifact: dict[str, object] = {}

        async def _capture_prompt(**kwargs: object) -> str:
            if kwargs["wave"] == "D":
                captured_wave_c_artifact.update(dict(kwargs["wave_artifacts"]["C"]))
            return f"wave {kwargs['wave']}"

        await _run_waves(tmp_path, template="full_stack", build_prompt=_capture_prompt)

        assert captured_wave_c_artifact["client_exports"] == ["listOrders"]
        manifest = captured_wave_c_artifact["client_manifest"]
        assert isinstance(manifest, list)
        assert manifest[0]["symbol"] == "listOrders"
        assert manifest[0]["response_type"] == "Order[]"

    @pytest.mark.asyncio
    async def test_total_cost_includes_compile_fix_retry_cost(self, tmp_path: Path) -> None:
        milestone = _milestone(template="backend_only")
        compile_attempts = {"A": 0}

        async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
            if role == "wave":
                _write(tmp_path / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
                return 1.5
            return 0.4

        async def _run_compile_check(*, wave: str = "", **_: object) -> dict[str, object]:
            if wave == "A" and compile_attempts["A"] == 0:
                compile_attempts["A"] += 1
                return {
                    "passed": False,
                    "iterations": 1,
                    "initial_error_count": 1,
                    "errors": [{"file": "src/a.ts", "line": 1, "message": "broken"}],
                }
            return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

        async def _generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
            milestone_id = getattr(milestone, "id", "milestone-orders")
            current_spec = _write(Path(cwd) / "contracts" / "openapi" / "current.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
            local_spec = _write(Path(cwd) / "contracts" / "openapi" / f"{milestone_id}.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
            return {
                "success": True,
                "milestone_spec_path": str(local_spec),
                "cumulative_spec_path": str(current_spec),
                "client_exports": ["listOrders"],
                "breaking_changes": [],
                "endpoints_summary": [{"method": "GET", "path": "/orders"}],
                "files_created": [],
            }

        result = await execute_milestone_waves(
            milestone=milestone,
            ir={"project_name": "Demo"},
            config=SimpleNamespace(),
            cwd=str(tmp_path),
            build_wave_prompt=lambda **kwargs: f"wave {kwargs['wave']}",
            execute_sdk_call=_execute_sdk_call,
            run_compile_check=_run_compile_check,
            extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
            generate_contracts=_generate_contracts,
            run_scaffolding=None,
            save_wave_state=None,
        )

        wave_a = next(wave for wave in result.waves if wave.wave == "A")
        assert wave_a.compile_fix_cost == pytest.approx(0.4)
        assert wave_a.cost == pytest.approx(1.9)
        assert result.total_cost == pytest.approx(4.9)

        telemetry = json.loads(
            (tmp_path / ".agent-team" / "telemetry" / f"{milestone.id}-wave-A.json").read_text(encoding="utf-8")
        )
        assert telemetry["sdk_cost_usd"] == pytest.approx(1.9)
        assert telemetry["compile_fix_cost_usd"] == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_total_cost_includes_multiple_compile_fix_retries(self, tmp_path: Path) -> None:
        milestone = _milestone(template="backend_only")
        compile_attempts = {"A": 0}

        async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
            if role == "wave":
                _write(tmp_path / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
                return 1.5
            return 0.25

        async def _run_compile_check(*, wave: str = "", **_: object) -> dict[str, object]:
            if wave == "A" and compile_attempts["A"] < 2:
                compile_attempts["A"] += 1
                return {
                    "passed": False,
                    "iterations": 1,
                    "initial_error_count": 2,
                    "errors": [{"file": "src/a.ts", "line": 1, "message": "broken"}],
                }
            return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

        async def _generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
            milestone_id = getattr(milestone, "id", "milestone-orders")
            current_spec = _write(Path(cwd) / "contracts" / "openapi" / "current.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
            local_spec = _write(Path(cwd) / "contracts" / "openapi" / f"{milestone_id}.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
            return {
                "success": True,
                "milestone_spec_path": str(local_spec),
                "cumulative_spec_path": str(current_spec),
                "client_exports": ["listOrders"],
                "breaking_changes": [],
                "endpoints_summary": [{"method": "GET", "path": "/orders"}],
                "files_created": [],
            }

        result = await execute_milestone_waves(
            milestone=milestone,
            ir={"project_name": "Demo"},
            config=SimpleNamespace(),
            cwd=str(tmp_path),
            build_wave_prompt=lambda **kwargs: f"wave {kwargs['wave']}",
            execute_sdk_call=_execute_sdk_call,
            run_compile_check=_run_compile_check,
            extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
            generate_contracts=_generate_contracts,
            run_scaffolding=None,
            save_wave_state=None,
        )

        wave_a = next(wave for wave in result.waves if wave.wave == "A")
        assert wave_a.compile_iterations == 3
        assert wave_a.compile_fix_cost == pytest.approx(0.5)
        assert wave_a.cost == pytest.approx(2.0)
        assert result.total_cost == pytest.approx(5.0)


class TestCompileFailureHandling:
    @pytest.mark.asyncio
    async def test_compile_failure_aborts_milestone(self, tmp_path: Path) -> None:
        result, _ = await _run_waves(tmp_path, compile_fail_wave="A")
        assert result.success is False
        assert result.error_wave == "A"

    @pytest.mark.asyncio
    async def test_compile_failure_records_error_in_wave_result(self, tmp_path: Path) -> None:
        result, _ = await _run_waves(tmp_path, compile_fail_wave="A")
        assert result.waves[0].error_message.startswith("Compile failed after")
        assert result.waves[0].compile_errors_initial == 1

    @pytest.mark.asyncio
    async def test_compile_failure_on_wave_a_prevents_wave_b(self, tmp_path: Path) -> None:
        result, calls = await _run_waves(tmp_path, compile_fail_wave="A")
        assert [wave.wave for wave in result.waves] == ["A"]
        assert ("A", "compile_fix") in calls
        assert not any(wave == "B" and role == "wave" for wave, role in calls)


class TestCallbackFiring:
    @pytest.mark.asyncio
    async def test_on_wave_complete_called_for_each_wave(self, tmp_path: Path) -> None:
        completed: list[str] = []

        def _on_wave_complete(*, wave: str, **_: object) -> None:
            completed.append(wave)

        await _run_waves(tmp_path, on_wave_complete=_on_wave_complete)

        assert completed == ["A", "B", "C", "D", "D5", "E"]

    @pytest.mark.asyncio
    async def test_on_wave_complete_receives_wave_result(self, tmp_path: Path) -> None:
        received: list[tuple[str, WaveResult]] = []

        def _on_wave_complete(*, wave: str, result: WaveResult, **_: object) -> None:
            received.append((wave, result))

        await _run_waves(tmp_path, on_wave_complete=_on_wave_complete)

        assert [wave for wave, _ in received] == ["A", "B", "C", "D", "D5", "E"]
        assert all(result.wave == wave for wave, result in received)
