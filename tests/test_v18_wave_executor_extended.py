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


def test_wave_watchdog_state_has_claude_peek_fields():
    from agent_team_v15.wave_executor import _WaveWatchdogState

    state = _WaveWatchdogState()
    assert state.peek_schedule is None
    assert state.peek_log == []
    assert state.last_peek_monotonic == 0.0
    assert state.peek_count == 0
    assert state.seen_files == set()


def test_wave_watchdog_state_rejects_codex_fields():
    """Architecture guard: codex_* fields must live on _OrphanWatchdog."""
    from agent_team_v15.wave_executor import _WaveWatchdogState

    state = _WaveWatchdogState()
    assert not hasattr(state, "codex_last_plan")
    assert not hasattr(state, "codex_latest_diff")


def test_wave_watchdog_peek_log_accumulates():
    from agent_team_v15.wave_executor import PeekResult, _WaveWatchdogState

    state = _WaveWatchdogState()
    state.peek_log.append(
        PeekResult(file_path="a.ts", wave="A", verdict="ok", message="r1")
    )
    state.peek_log.append(
        PeekResult(file_path="b.ts", wave="A", verdict="issue", message="r2")
    )
    assert len(state.peek_log) == 2
    assert state.peek_log[-1].verdict == "issue"


def test_detect_new_peek_triggers_returns_new_and_modified(tmp_path):
    from agent_team_v15.wave_executor import (
        _capture_file_fingerprints,
        _detect_new_peek_triggers,
    )

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("x", encoding="utf-8")
    baseline = _capture_file_fingerprints(str(tmp_path))
    (tmp_path / "src" / "a.ts").write_text("xx", encoding="utf-8")
    (tmp_path / "src" / "b.ts").write_text("y", encoding="utf-8")
    triggers = _detect_new_peek_triggers(str(tmp_path), baseline, set(), 0.0)
    assert any(t.endswith("a.ts") for t in triggers)
    assert any(t.endswith("b.ts") for t in triggers)


def test_should_fire_time_based_peek_respects_budget():
    import time

    from agent_team_v15.wave_executor import (
        _should_fire_time_based_peek,
    )

    last_peek_monotonic = time.monotonic() - 2.0
    assert _should_fire_time_based_peek(last_peek_monotonic, 1.0, 0, 2) is True
    assert _should_fire_time_based_peek(last_peek_monotonic, 1.0, 2, 2) is False


def test_should_fire_time_based_peek_interval_elapsed():
    from agent_team_v15.wave_executor import _should_fire_time_based_peek
    import time as _t
    assert _should_fire_time_based_peek(_t.monotonic() - 120.0, 60.0, 0, 5) is True


def test_should_fire_time_based_peek_interval_not_elapsed():
    from agent_team_v15.wave_executor import _should_fire_time_based_peek
    import time as _t
    assert _should_fire_time_based_peek(_t.monotonic() - 10.0, 60.0, 0, 5) is False


def test_should_fire_time_based_peek_budget_exhausted():
    from agent_team_v15.wave_executor import _should_fire_time_based_peek
    import time as _t
    assert _should_fire_time_based_peek(_t.monotonic() - 120.0, 60.0, 5, 5) is False


def test_should_fire_time_based_peek_zero_interval():
    from agent_team_v15.wave_executor import _should_fire_time_based_peek
    import time as _t
    assert _should_fire_time_based_peek(_t.monotonic() - 120.0, 0.0, 0, 5) is False


@pytest.mark.asyncio
async def test_wave_watchdog_runs_peek_after_wait_returns_pending(monkeypatch, tmp_path):
    import asyncio

    from agent_team_v15.config import ObserverConfig
    from agent_team_v15.wave_executor import (
        PeekResult,
        _invoke_wave_sdk_with_watchdog,
    )

    calls: list[str] = []

    async def _fake_run_peek_call(
        *,
        cwd: str,
        file_path: str,
        schedule: object,
        log_only: bool,
        model: str,
        confidence_threshold: float,
        max_tokens: int = 512,
    ) -> PeekResult:
        calls.append(file_path)
        return PeekResult(file_path=file_path, wave="A", verdict="ok", log_only=log_only)

    monkeypatch.setattr(
        "agent_team_v15.observer_peek.run_peek_call",
        _fake_run_peek_call,
    )
    monkeypatch.setattr(
        wave_executor_module,
        "_wave_watchdog_poll_seconds",
        lambda _config: 0.01,
    )
    monkeypatch.setattr(
        wave_executor_module,
        "_wave_idle_timeout_seconds",
        lambda _config: 5,
    )

    async def _execute_sdk_call(**_: object) -> float:
        _write(tmp_path / "src" / "peek-target.ts", "export const x = true;\n")
        await asyncio.sleep(0.05)
        return 0.25

    cfg = SimpleNamespace(
        observer=ObserverConfig(
            enabled=True,
            log_only=True,
            max_peeks_per_wave=2,
            time_based_interval_seconds=999.0,
            peek_timeout_seconds=0.2,
            peek_settle_seconds=0.0,
        )
    )

    cost, state = await _invoke_wave_sdk_with_watchdog(
        execute_sdk_call=_execute_sdk_call,
        prompt="build",
        wave_letter="A",
        config=cfg,
        cwd=str(tmp_path),
        milestone=_milestone(),
        observer_config=cfg.observer,
        requirements_text="- [ ] src/peek-target.ts\n",
    )

    assert cost == pytest.approx(0.25)
    assert calls == ["src/peek-target.ts"]
    assert len(state.peek_log) == 1


@pytest.mark.asyncio
async def test_wave_watchdog_time_based_peek_selects_newest_unpeeked_trigger(
    monkeypatch,
    tmp_path,
):
    import os
    import time

    from agent_team_v15.config import ObserverConfig
    from agent_team_v15.wave_executor import (
        PeekResult,
        PeekSchedule,
        _WaveWatchdogState,
        _capture_file_fingerprints,
        _run_wave_observer_peek,
    )

    old_file = _write(tmp_path / "src" / "old.ts", "export const old = true;\n")
    new_file = _write(tmp_path / "src" / "new.ts", "export const new = true;\n")
    now = time.time()
    os.utime(old_file, (now - 20.0, now - 20.0))
    os.utime(new_file, (now - 5.0, now - 5.0))
    baseline = _capture_file_fingerprints(str(tmp_path))

    state = _WaveWatchdogState()
    state.peek_schedule = PeekSchedule(
        wave="A",
        trigger_files=["src/old.ts", "src/new.ts"],
    )
    state.last_peek_monotonic = time.monotonic() - 120.0
    cfg = ObserverConfig(
        enabled=True,
        log_only=True,
        max_peeks_per_wave=5,
        time_based_interval_seconds=60.0,
        peek_timeout_seconds=0.2,
        peek_settle_seconds=0.0,
    )
    calls: list[str] = []

    async def _fake_run_peek_call(
        *,
        cwd: str,
        file_path: str,
        schedule: object,
        log_only: bool,
        model: str,
        confidence_threshold: float,
        max_tokens: int = 512,
    ) -> PeekResult:
        calls.append(file_path)
        return PeekResult(file_path=file_path, wave="A", verdict="ok", log_only=log_only)

    monkeypatch.setattr(
        "agent_team_v15.observer_peek.run_peek_call",
        _fake_run_peek_call,
    )

    await _run_wave_observer_peek(
        state=state,
        observer_config=cfg,
        cwd=str(tmp_path),
        baseline_fingerprints=baseline,
        wave_letter="A",
    )

    assert calls == ["src/new.ts"]
    assert [result.file_path for result in state.peek_log] == ["src/new.ts"]


@pytest.mark.asyncio
async def test_provider_wave_watchdog_runs_peek_for_routed_claude(monkeypatch, tmp_path):
    import asyncio

    from agent_team_v15.config import ObserverConfig
    from agent_team_v15.wave_executor import (
        PeekResult,
        _invoke_provider_wave_with_watchdog,
    )

    calls: list[str] = []

    async def _fake_run_peek_call(
        *,
        cwd: str,
        file_path: str,
        schedule: object,
        log_only: bool,
        model: str,
        confidence_threshold: float,
        max_tokens: int = 512,
    ) -> PeekResult:
        calls.append(file_path)
        return PeekResult(file_path=file_path, wave="B", verdict="ok", log_only=log_only)

    async def _fake_execute_wave_with_provider(**_: object) -> dict[str, object]:
        _write(tmp_path / "src" / "routed-peek.ts", "export const x = true;\n")
        await asyncio.sleep(0.05)
        return {"provider": "claude", "cost": 0.5}

    monkeypatch.setattr(
        "agent_team_v15.observer_peek.run_peek_call",
        _fake_run_peek_call,
    )
    monkeypatch.setattr(
        "agent_team_v15.provider_router.execute_wave_with_provider",
        _fake_execute_wave_with_provider,
    )
    monkeypatch.setattr(
        wave_executor_module,
        "_wave_watchdog_poll_seconds",
        lambda _config: 0.01,
    )
    monkeypatch.setattr(
        wave_executor_module,
        "_wave_idle_timeout_seconds",
        lambda _config: 5,
    )

    cfg = SimpleNamespace(
        observer=ObserverConfig(
            enabled=True,
            log_only=True,
            max_peeks_per_wave=2,
            time_based_interval_seconds=999.0,
            peek_timeout_seconds=0.2,
            peek_settle_seconds=0.0,
        )
    )

    meta, state = await _invoke_provider_wave_with_watchdog(
        execute_sdk_call=lambda **_: 0.0,
        prompt="build",
        wave_letter="B",
        config=cfg,
        cwd=str(tmp_path),
        milestone=_milestone(),
        provider_routing={
            "provider_map": SimpleNamespace(provider_for=lambda _wave: "claude")
        },
        observer_config=cfg.observer,
        requirements_text="- [ ] src/routed-peek.ts\n",
    )

    assert meta["provider"] == "claude"
    assert calls == ["src/routed-peek.ts"]
    assert len(state.peek_log) == 1


@pytest.mark.asyncio
async def test_provider_router_forwards_observer_kwargs_to_codex(monkeypatch, tmp_path):
    from agent_team_v15.config import ObserverConfig
    from agent_team_v15.provider_router import WaveProviderMap, execute_wave_with_provider

    captured: dict[str, object] = {}
    observer_config = ObserverConfig(enabled=True)
    milestone = _milestone()
    req_path = tmp_path / ".agent-team" / "milestones" / milestone.id / "REQUIREMENTS.md"
    req_path.parent.mkdir(parents=True)
    req_path.write_text("REQ-TEXT", encoding="utf-8")

    async def _fake_execute_codex(
        prompt: str,
        cwd: str,
        config: object,
        codex_home: Path,
        *,
        progress_callback=None,
        observer_config=None,
        requirements_text: str = "",
        wave_letter: str = "",
    ) -> SimpleNamespace:
        captured["observer_config"] = observer_config
        captured["requirements_text"] = requirements_text
        captured["wave_letter"] = wave_letter
        return SimpleNamespace(
            success=True,
            cost_usd=0.0,
            model="gpt-test",
            retry_count=0,
            input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
        )

    async def _noop_normalize_code_style(cwd: str, changed_files: list[str]) -> None:
        return None

    def _checkpoint_create(label: str, cwd: str) -> SimpleNamespace:
        return SimpleNamespace(file_manifest=[])

    def _checkpoint_diff(before: object, after: object) -> SimpleNamespace:
        return SimpleNamespace(created=["src/codex.ts"], modified=[], deleted=[])

    async def _claude_callback(**_: object) -> float:
        return 0.0

    monkeypatch.setattr(
        "agent_team_v15.provider_router._normalize_code_style",
        _noop_normalize_code_style,
    )

    result = await execute_wave_with_provider(
        wave_letter="B",
        prompt="PROMPT-FALLBACK",
        cwd=str(tmp_path),
        config=SimpleNamespace(observer=observer_config),
        provider_map=WaveProviderMap(),
        claude_callback=_claude_callback,
        claude_callback_kwargs={"milestone": milestone},
        codex_transport_module=SimpleNamespace(
            execute_codex=_fake_execute_codex,
            is_codex_available=lambda: True,
        ),
        codex_config=SimpleNamespace(),
        codex_home=tmp_path,
        checkpoint_create=_checkpoint_create,
        checkpoint_diff=_checkpoint_diff,
    )

    assert result["provider"] == "codex"
    assert captured["observer_config"] is observer_config
    assert captured["requirements_text"] == "REQ-TEXT"
    assert captured["wave_letter"] == "B"


def test_orphan_watchdog_has_observer_fields():
    from agent_team_v15.codex_appserver import _OrphanWatchdog

    w = _OrphanWatchdog()
    assert hasattr(w, "observer_config")
    assert hasattr(w, "requirements_text")
    assert hasattr(w, "wave_letter")
    assert hasattr(w, "codex_last_plan")
    assert hasattr(w, "codex_latest_diff")
    assert w.codex_last_plan == []
    assert w.codex_latest_diff == ""


def test_orphan_watchdog_accepts_observer_config_kwarg():
    from agent_team_v15.codex_appserver import _OrphanWatchdog
    from agent_team_v15.config import ObserverConfig

    cfg = ObserverConfig()
    w = _OrphanWatchdog(
        observer_config=cfg,
        requirements_text="req",
        wave_letter="B",
    )
    assert w.observer_config is cfg
    assert w.requirements_text == "req"
    assert w.wave_letter == "B"


def test_wave_watchdog_state_does_not_have_codex_fields():
    """Arch invariant: codex_* fields must not leak to _WaveWatchdogState."""
    from agent_team_v15.wave_executor import _WaveWatchdogState

    s = _WaveWatchdogState()
    assert not hasattr(s, "codex_last_plan")
    assert not hasattr(s, "codex_latest_diff")


# ---------------------------------------------------------------------------
# Issue #12 — Wave B in-wave self-verify integration
# ---------------------------------------------------------------------------


def _rv_cfg(
    *,
    enabled: bool = True,
    max_retries: int = 2,
    compose_autorepair: bool = True,
    build_timeout_s: int = 600,
) -> SimpleNamespace:
    return SimpleNamespace(
        wave_b_self_verify_enabled=enabled,
        wave_b_self_verify_max_retries=max_retries,
        compose_autorepair=compose_autorepair,
        build_timeout_s=build_timeout_s,
    )


def _install_passing_acceptance(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    from agent_team_v15 import wave_b_self_verify as wbsv

    seen: list[Path] = []

    def _fake(
        cwd: Path,
        *,
        autorepair: bool = True,
        timeout_seconds: int = 600,
        narrow_services: bool = True,
        stack_contract: dict | None = None,
        **_phase_4_2_kwargs: object,
    ):
        seen.append(Path(cwd))
        return wbsv.WaveBVerifyResult(passed=True)

    monkeypatch.setattr(wbsv, "run_wave_b_acceptance_test", _fake)
    return seen


def _install_scripted_acceptance(
    monkeypatch: pytest.MonkeyPatch, outcomes
) -> list[int]:
    """``outcomes`` is a list of bools. Each call pops the next — True=pass."""
    from agent_team_v15 import wave_b_self_verify as wbsv
    from agent_team_v15.compose_sanity import Violation
    from agent_team_v15.runtime_verification import BuildResult

    calls: list[int] = []
    remaining = list(outcomes)

    def _fake(
        cwd: Path,
        *,
        autorepair: bool = True,
        timeout_seconds: int = 600,
        narrow_services: bool = True,
        stack_contract: dict | None = None,
        **_phase_4_2_kwargs: object,
    ):
        calls.append(len(calls))
        if not remaining:
            return wbsv.WaveBVerifyResult(passed=True)
        passed = remaining.pop(0)
        if passed:
            return wbsv.WaveBVerifyResult(passed=True)
        failure = BuildResult(
            service="api", success=False, error="boom", duration_s=0.1,
        )
        return wbsv.WaveBVerifyResult(
            passed=False,
            violations=[],
            build_failures=[failure],
            error_summary="boom",
            retry_prompt_suffix="<previous_attempt_failed>boom</previous_attempt_failed>",
        )

    monkeypatch.setattr(wbsv, "run_wave_b_acceptance_test", _fake)
    return calls


@pytest.mark.asyncio
async def test_wave_b_self_verify_enabled_triggers_acceptance_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_passing_acceptance(monkeypatch)

    async def _build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    sdk_calls: list[str] = []

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        sdk_calls.append(wave)
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}.ts", "export {};\n")
        return 1.0

    async def _run_compile_check(**_: object) -> dict:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _extract(**_kwargs: object) -> dict:
        return {}

    async def _gen_contracts(*, cwd: str, milestone: object) -> dict:
        (Path(cwd) / "contracts" / "openapi").mkdir(parents=True, exist_ok=True)
        return {"success": True}

    cfg = SimpleNamespace(runtime_verification=_rv_cfg(enabled=True, max_retries=2))
    result = await execute_milestone_waves(
        milestone=_milestone(template="full_stack"),
        ir={"project_name": "Demo"},
        config=cfg,
        cwd=str(tmp_path),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=_extract,
        generate_contracts=_gen_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    wave_b = next(w for w in result.waves if w.wave == "B")
    assert wave_b.success is True
    assert len(seen) == 1
    assert seen[0].resolve() == Path(tmp_path).resolve()


@pytest.mark.asyncio
async def test_wave_b_self_verify_fail_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # First call: fail. Second call (after re-dispatch): pass.
    calls = _install_scripted_acceptance(monkeypatch, [False, True])

    dispatches: list[str] = []

    async def _build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']} ORIGINAL"

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        dispatches.append(wave)
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}.ts", "export {};\n")
        return 1.0

    async def _run_compile_check(**_: object) -> dict:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _extract(**_kwargs: object) -> dict:
        return {}

    async def _gen_contracts(*, cwd: str, milestone: object) -> dict:
        (Path(cwd) / "contracts" / "openapi").mkdir(parents=True, exist_ok=True)
        return {"success": True}

    # Spy on _execute_wave_sdk to capture the retry prompt.
    augmented_prompts: list[str] = []
    original_execute_wave_sdk = wave_executor_module._execute_wave_sdk

    async def _spy_execute_wave_sdk(**kwargs):
        if kwargs.get("wave_letter") == "B":
            augmented_prompts.append(kwargs.get("prompt", ""))
        return await original_execute_wave_sdk(**kwargs)

    monkeypatch.setattr(wave_executor_module, "_execute_wave_sdk", _spy_execute_wave_sdk)

    cfg = SimpleNamespace(runtime_verification=_rv_cfg(enabled=True, max_retries=2))
    result = await execute_milestone_waves(
        milestone=_milestone(template="full_stack"),
        ir={"project_name": "Demo"},
        config=cfg,
        cwd=str(tmp_path),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=_extract,
        generate_contracts=_gen_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    wave_b = next(w for w in result.waves if w.wave == "B")
    assert wave_b.success is True
    # 2 acceptance-test invocations (fail, then pass).
    assert len(calls) == 2
    # 2 Wave B dispatches: initial + 1 retry.
    b_dispatches = [w for w in dispatches if w == "B"]
    assert len(b_dispatches) == 2
    # The retry prompt carries the original + error suffix.
    assert augmented_prompts, "expected at least one Wave B _execute_wave_sdk call"
    retry_prompt = augmented_prompts[-1]
    assert "ORIGINAL" in retry_prompt
    assert "<previous_attempt_failed>" in retry_prompt
    # A single self-verify-failed finding is recorded for the failed attempt.
    sv_findings = [
        f for f in wave_b.findings
        if getattr(f, "code", "") == "WAVE-B-SELF-VERIFY"
    ]
    assert len(sv_findings) == 1


@pytest.mark.asyncio
async def test_wave_b_self_verify_exhausts_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every acceptance attempt fails.
    calls = _install_scripted_acceptance(monkeypatch, [False, False, False])

    async def _build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}.ts", "export {};\n")
        return 1.0

    async def _run_compile_check(**_: object) -> dict:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _extract(**_kwargs: object) -> dict:
        return {}

    async def _gen_contracts(*, cwd: str, milestone: object) -> dict:
        (Path(cwd) / "contracts" / "openapi").mkdir(parents=True, exist_ok=True)
        return {"success": True}

    cfg = SimpleNamespace(runtime_verification=_rv_cfg(enabled=True, max_retries=2))
    result = await execute_milestone_waves(
        milestone=_milestone(template="full_stack"),
        ir={"project_name": "Demo"},
        config=cfg,
        cwd=str(tmp_path),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=_extract,
        generate_contracts=_gen_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    wave_b = next(w for w in result.waves if w.wave == "B")
    # Exhausted all (max_retries + 1) attempts → wave marked failed.
    assert wave_b.success is False
    assert len(calls) == 3
    assert "self-verify failed" in (wave_b.error_message or "")
    # All three failures recorded as findings.
    sv_findings = [
        f for f in wave_b.findings
        if getattr(f, "code", "") == "WAVE-B-SELF-VERIFY"
    ]
    assert len(sv_findings) == 3


@pytest.mark.asyncio
async def test_wave_b_self_verify_disabled_skips_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_passing_acceptance(monkeypatch)

    async def _build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}.ts", "export {};\n")
        return 1.0

    async def _run_compile_check(**_: object) -> dict:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _extract(**_kwargs: object) -> dict:
        return {}

    async def _gen_contracts(*, cwd: str, milestone: object) -> dict:
        (Path(cwd) / "contracts" / "openapi").mkdir(parents=True, exist_ok=True)
        return {"success": True}

    cfg = SimpleNamespace(runtime_verification=_rv_cfg(enabled=False))
    await execute_milestone_waves(
        milestone=_milestone(template="full_stack"),
        ir={"project_name": "Demo"},
        config=cfg,
        cwd=str(tmp_path),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=_extract,
        generate_contracts=_gen_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    # Flag disabled → helper should never be called.
    assert seen == []
