from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.state import RunState, load_state, save_state
from agent_team_v15 import wave_executor as wave_executor_module
from agent_team_v15.wave_executor import execute_milestone_waves


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(
        id="milestone-orders",
        title="Orders",
        template="backend_only",
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _config(*, redispatch_enabled: bool, max_attempts: int) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.execution_mode = "wave"
    cfg.v18.scaffold_enabled = True
    cfg.v18.scaffold_verifier_enabled = True
    cfg.v18.wave_a5_enabled = False
    cfg.v18.wave_t_enabled = False
    cfg.v18.wave_t5_enabled = False
    cfg.v18.live_endpoint_check = False
    cfg.v18.recovery_wave_redispatch_enabled = redispatch_enabled
    cfg.v18.recovery_wave_redispatch_max_attempts = max_attempts
    return cfg


def _save_wave_state_for_test(
    cwd: str,
    milestone_id: str,
    wave: str,
    status: str,
    artifact_path: str | None = None,
) -> None:
    state_dir = Path(cwd) / ".agent-team"
    state = load_state(str(state_dir)) or RunState(task="wave-redispatch-test")
    progress = state.wave_progress.setdefault(
        milestone_id,
        {
            "current_wave": wave,
            "completed_waves": [],
            "wave_artifacts": {},
        },
    )
    progress["current_wave"] = wave
    progress.setdefault("completed_waves", [])
    progress.setdefault("wave_artifacts", {})
    if artifact_path:
        progress["wave_artifacts"][wave] = artifact_path
    if status == "COMPLETE" and wave not in progress["completed_waves"]:
        progress["completed_waves"].append(wave)
    elif status == "FAILED":
        progress["failed_wave"] = wave
    elif status == "IN_PROGRESS":
        progress.pop("failed_wave", None)
    if status == "COMPLETE":
        progress.pop("failed_wave", None)
    save_state(state, directory=str(state_dir))


async def _run_backend_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    verifier_failures: list[bool],
    redispatch_enabled: bool,
    max_attempts: int,
) -> tuple[object, list[tuple[str, str]], dict[str, int]]:
    _write(
        tmp_path / ".agent-team" / "product-ir" / "product.ir.json",
        json.dumps({"project_name": "Demo"}),
    )

    monkeypatch.setattr(wave_executor_module, "_run_post_wave_e_scans", lambda *_args, **_kwargs: [])

    async def _no_node_tests(*_args, **_kwargs):
        return False, 0, 0, ""

    async def _no_playwright_tests(*_args, **_kwargs):
        return False, 0, 0, ""

    monkeypatch.setattr(wave_executor_module, "_run_node_tests", _no_node_tests)
    monkeypatch.setattr(wave_executor_module, "_run_playwright_tests", _no_playwright_tests)

    verifier_state = {"count": 0}

    def _fake_scaffold_verifier(*, cwd: str, **_kwargs) -> str | None:
        index = verifier_state["count"]
        verifier_state["count"] += 1
        should_fail = verifier_failures[index] if index < len(verifier_failures) else verifier_failures[-1]
        report_path = Path(cwd) / ".agent-team" / "scaffold_verifier_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        if should_fail:
            report_path.write_text(
                json.dumps(
                    {
                        "verdict": "FAIL",
                        "summary_lines": [
                            "SCAFFOLD-PORT-002 PORT_INCONSISTENCY expected 3080 got 3000",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return "Scaffold-verifier FAIL: SCAFFOLD-PORT-002 PORT_INCONSISTENCY"
        report_path.write_text(
            json.dumps({"verdict": "PASS", "summary_lines": []}),
            encoding="utf-8",
        )
        return None

    monkeypatch.setattr(
        wave_executor_module,
        "_maybe_run_scaffold_verifier",
        _fake_scaffold_verifier,
    )

    scaffold_calls = {"count": 0}
    sdk_calls: list[tuple[str, str]] = []

    async def _run_scaffolding(**kwargs: object) -> list[str]:
        scaffold_calls["count"] += 1
        project_root = Path(kwargs["project_root"])
        _write(project_root / "docker-compose.yml", "services:\n  api:\n    ports:\n      - \"3000:3000\"\n")
        return ["docker-compose.yml"]

    async def _build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_kwargs: object) -> float:
        sdk_calls.append((wave, role))
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
        return 1.0

    async def _run_compile_check(**_kwargs: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _extract_artifacts(**kwargs: object) -> dict[str, object]:
        return {
            "wave": kwargs["wave"],
            "files_created": list(kwargs.get("files_created", []) or []),
            "files_modified": list(kwargs.get("files_modified", []) or []),
        }

    async def _generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
        milestone_id = getattr(milestone, "id", "milestone-orders")
        current_spec = _write(
            Path(cwd) / "contracts" / "openapi" / "current.json",
            json.dumps({"paths": {"/orders": {"get": {}}}}),
        )
        local_spec = _write(
            Path(cwd) / "contracts" / "openapi" / f"{milestone_id}.json",
            json.dumps({"paths": {"/orders": {"get": {}}}}),
        )
        return {
            "success": True,
            "milestone_spec_path": str(local_spec),
            "cumulative_spec_path": str(current_spec),
            "client_exports": ["listOrders"],
            "client_manifest": [],
            "breaking_changes": [],
            "endpoints_summary": [{"method": "GET", "path": "/orders"}],
            "files_created": [
                str(local_spec.relative_to(cwd)).replace("\\", "/"),
                str(current_spec.relative_to(cwd)).replace("\\", "/"),
            ],
        }

    result = await execute_milestone_waves(
        milestone=_milestone(),
        ir={"project_name": "Demo"},
        config=_config(
            redispatch_enabled=redispatch_enabled,
            max_attempts=max_attempts,
        ),
        cwd=str(tmp_path),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=_extract_artifacts,
        generate_contracts=_generate_contracts,
        run_scaffolding=_run_scaffolding,
        save_wave_state=lambda **kwargs: _save_wave_state_for_test(str(tmp_path), **kwargs),
        on_wave_complete=None,
    )
    return result, sdk_calls, scaffold_calls


@pytest.mark.asyncio
async def test_scaffold_failure_persists_failed_wave_when_redispatch_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, sdk_calls, scaffold_calls = await _run_backend_only(
        tmp_path,
        monkeypatch,
        verifier_failures=[True],
        redispatch_enabled=False,
        max_attempts=1,
    )

    state = load_state(str(tmp_path / ".agent-team"))
    assert state is not None
    progress = state.wave_progress["milestone-orders"]

    assert result.success is False
    assert result.error_wave == "SCAFFOLD"
    assert sum(1 for wave, role in sdk_calls if wave == "A" and role == "wave") == 1
    assert scaffold_calls["count"] == 1
    assert progress["failed_wave"] == "SCAFFOLD"
    assert progress["completed_waves"] == ["A"]
    assert state.wave_redispatch_attempts == {}


@pytest.mark.asyncio
async def test_scaffold_port_failure_redispatches_back_to_wave_a_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, sdk_calls, scaffold_calls = await _run_backend_only(
        tmp_path,
        monkeypatch,
        verifier_failures=[True, False],
        redispatch_enabled=True,
        max_attempts=1,
    )

    state = load_state(str(tmp_path / ".agent-team"))
    assert state is not None
    progress = state.wave_progress["milestone-orders"]
    history = progress["redispatch_history"]

    assert result.success is True
    assert [wave.wave for wave in result.waves] == ["A", "B", "C", "E"]
    assert sum(1 for wave, role in sdk_calls if wave == "A" and role == "wave") == 2
    assert scaffold_calls["count"] == 2
    assert state.wave_redispatch_attempts == {"milestone-orders:A": 1}
    assert progress["completed_waves"] == ["A", "B", "C", "E"]
    assert "failed_wave" not in progress
    assert len(history) == 1
    assert history[0]["event"] == "scheduled"
    assert history[0]["target_wave"] == "A"
    assert history[0]["trigger_codes"] == ["SCAFFOLD-PORT-002"]


@pytest.mark.asyncio
async def test_scaffold_redispatch_stops_at_hard_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, sdk_calls, scaffold_calls = await _run_backend_only(
        tmp_path,
        monkeypatch,
        verifier_failures=[True, True],
        redispatch_enabled=True,
        max_attempts=1,
    )

    state = load_state(str(tmp_path / ".agent-team"))
    assert state is not None
    progress = state.wave_progress["milestone-orders"]
    history = progress["redispatch_history"]

    assert result.success is False
    assert result.error_wave == "SCAFFOLD"
    assert sum(1 for wave, role in sdk_calls if wave == "A" and role == "wave") == 2
    assert scaffold_calls["count"] == 2
    assert state.wave_redispatch_attempts == {"milestone-orders:A": 1}
    assert progress["failed_wave"] == "SCAFFOLD"
    assert progress["completed_waves"] == ["A"]
    assert [event["event"] for event in history] == ["scheduled", "cap_reached"]
