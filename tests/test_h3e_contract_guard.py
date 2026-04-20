from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.agents import build_wave_a_prompt
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.state import RunState, load_state, save_state
from agent_team_v15.scaffold_runner import scaffold_config_from_stack_contract
from agent_team_v15.wave_executor import (
    _run_wave_a_contract_verifier,
    execute_milestone_waves,
)


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
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS",
    )


def _ir() -> dict[str, object]:
    return {
        "project_name": "Demo",
        "entities": [{"name": "Order", "fields": [{"name": "id", "type": "string"}]}],
        "endpoints": [{"method": "GET", "path": "/orders", "owner_feature": "F-ORDERS"}],
        "business_rules": [],
        "integrations": [],
        "acceptance_criteria": [],
    }


def _stack_contract(*, api_port: int = 3001, api_prefix: str | None = None) -> dict[str, object]:
    contract: dict[str, object] = {
        "backend_framework": "nestjs",
        "orm": "prisma",
        "database": "postgresql",
        "monorepo_layout": "apps",
        "backend_path_prefix": "apps/api/",
        "port": api_port,
        "api_port": api_port,
        "ports": [api_port],
        "dod": {"port": api_port},
        "confidence": "explicit",
    }
    if api_prefix is not None:
        contract["api_prefix"] = api_prefix
    return contract


def _save_wave_state_for_test(
    cwd: str,
    milestone_id: str,
    wave: str,
    status: str,
    artifact_path: str | None = None,
) -> None:
    state_dir = Path(cwd) / ".agent-team"
    state = load_state(str(state_dir)) or RunState(task="h3e-contract-guard")
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


def test_wave_a_prompt_includes_explicit_contract_values_when_flag_enabled() -> None:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a_contract_injection_enabled = True

    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=cfg,
        existing_prompt_framework="FRAMEWORK\n",
        stack_contract=_stack_contract(api_port=3001),
    )

    assert "[WAVE A EXPLICIT CONTRACT VALUES]" in prompt
    assert "- API port: 3001" in prompt
    assert "- DoD port anchor: 3001" in prompt
    assert "- Allowed concrete port literals: [3001]" in prompt


def test_wave_a_prompt_omits_explicit_contract_values_when_flag_disabled() -> None:
    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir=_ir(),
        dependency_artifacts={},
        scaffolded_files=[],
        config=AgentTeamConfig(),
        existing_prompt_framework="FRAMEWORK\n",
        stack_contract=_stack_contract(api_port=3001),
    )

    assert "[WAVE A EXPLICIT CONTRACT VALUES]" not in prompt
    assert "=== STACK CONTRACT (NON-NEGOTIABLE) ===" in prompt


def test_scaffold_config_from_stack_contract_uses_api_port_literals() -> None:
    cfg = scaffold_config_from_stack_contract(
        _stack_contract(api_port=3001, api_prefix="v1")
    )

    assert cfg is not None
    assert cfg.port == 3001
    assert cfg.api_prefix == "v1"


def test_wave_a_contract_verifier_flags_port_drift_in_main_ts_and_compose(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "apps" / "api" / "src" / "main.ts",
        "const port = process.env.PORT ?? 4000;\nawait app.listen(port);\n",
    )
    _write(
        tmp_path / "docker-compose.yml",
        "services:\n  api:\n    ports:\n      - \"4000:4000\"\n",
    )

    findings = _run_wave_a_contract_verifier(
        cwd=str(tmp_path),
        stack_contract=_stack_contract(api_port=3001),
    )

    assert [finding.code for finding in findings] == [
        "WAVE-A-CONTRACT-DRIFT-001",
        "WAVE-A-CONTRACT-DRIFT-001",
    ]
    assert {finding.file for finding in findings} == {
        "apps/api/src/main.ts",
        "docker-compose.yml",
    }
    assert all("3001" in finding.message for finding in findings)


def test_wave_a_contract_verifier_accepts_matching_ports(tmp_path: Path) -> None:
    _write(
        tmp_path / "apps" / "api" / "src" / "main.ts",
        "const port = process.env.PORT ?? 3001;\nawait app.listen(port);\n",
    )
    _write(
        tmp_path / "apps" / "api" / ".env.example",
        "PORT=3001\n",
    )
    _write(
        tmp_path / "docker-compose.yml",
        "services:\n  api:\n    ports:\n      - \"3001:3001\"\n",
    )

    findings = _run_wave_a_contract_verifier(
        cwd=str(tmp_path),
        stack_contract=_stack_contract(api_port=3001),
    )

    assert findings == []


async def _run_contract_redispatch_flow(
    tmp_path: Path,
    monkeypatch,
) -> tuple[object, list[tuple[str, str]], list[tuple[str, str]], RunState]:
    cfg = AgentTeamConfig()
    cfg.v18.execution_mode = "wave"
    cfg.v18.scaffold_enabled = True
    cfg.v18.scaffold_verifier_enabled = True
    cfg.v18.wave_a5_enabled = False
    cfg.v18.wave_t_enabled = False
    cfg.v18.wave_t5_enabled = False
    cfg.v18.live_endpoint_check = False
    cfg.v18.recovery_wave_redispatch_enabled = True
    cfg.v18.recovery_wave_redispatch_max_attempts = 2
    cfg.v18.wave_a_contract_verifier_enabled = True

    _write(
        tmp_path / ".agent-team" / "product-ir" / "product.ir.json",
        "{\"project_name\": \"Demo\"}",
    )

    monkeypatch.setattr(
        "agent_team_v15.wave_executor._run_post_wave_e_scans",
        lambda *_args, **_kwargs: [],
    )

    async def _no_node_tests(*_args, **_kwargs):
        return False, 0, 0, ""

    async def _no_playwright_tests(*_args, **_kwargs):
        return False, 0, 0, ""

    monkeypatch.setattr("agent_team_v15.wave_executor._run_node_tests", _no_node_tests)
    monkeypatch.setattr(
        "agent_team_v15.wave_executor._run_playwright_tests",
        _no_playwright_tests,
    )
    monkeypatch.setattr(
        "agent_team_v15.wave_executor._maybe_run_scaffold_verifier",
        lambda **_kwargs: None,
    )

    prompt_contexts: list[tuple[str, str]] = []
    sdk_calls: list[tuple[str, str]] = []
    wave_a_runs = {"count": 0}

    async def _run_scaffolding(**kwargs):
        project_root = Path(kwargs["project_root"])
        _write(
            project_root / "docker-compose.yml",
            "services:\n  api:\n    ports:\n      - \"3001:3001\"\n",
        )
        return ["docker-compose.yml"]

    async def _build_prompt(**kwargs):
        prompt_contexts.append(
            (
                str(kwargs["wave"]),
                str(kwargs.get("stack_contract_rejection_context", "") or ""),
            )
        )
        return f"wave {kwargs['wave']}"

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_kwargs):
        sdk_calls.append((wave, role))
        if role == "wave" and wave == "A":
            wave_a_runs["count"] += 1
            port = 4000 if wave_a_runs["count"] == 1 else 3001
            _write(
                tmp_path / "apps" / "api" / "src" / "main.ts",
                f"const port = process.env.PORT ?? {port};\nawait app.listen(port);\n",
            )
            _write(
                tmp_path / "apps" / "api" / ".env.example",
                f"PORT={port}\n",
            )
        elif role == "wave":
            _write(
                tmp_path / "src" / f"{wave.lower()}.ts",
                f"export const {wave.lower()} = true;\n",
            )
        return 1.0

    async def _run_compile_check(**_kwargs):
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _extract_artifacts(**kwargs):
        return {
            "wave": kwargs["wave"],
            "files_created": list(kwargs.get("files_created", []) or []),
            "files_modified": list(kwargs.get("files_modified", []) or []),
        }

    async def _generate_contracts(*, cwd: str, milestone: object):
        milestone_id = getattr(milestone, "id", "milestone-orders")
        current_spec = _write(
            Path(cwd) / "contracts" / "openapi" / "current.json",
            "{\"paths\": {\"/orders\": {\"get\": {}}}}",
        )
        local_spec = _write(
            Path(cwd) / "contracts" / "openapi" / f"{milestone_id}.json",
            "{\"paths\": {\"/orders\": {\"get\": {}}}}",
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
        ir=_ir(),
        config=cfg,
        cwd=str(tmp_path),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=_extract_artifacts,
        generate_contracts=_generate_contracts,
        run_scaffolding=_run_scaffolding,
        save_wave_state=lambda **kwargs: _save_wave_state_for_test(str(tmp_path), **kwargs),
        on_wave_complete=None,
        stack_contract=_stack_contract(api_port=3001),
    )
    state = load_state(str(tmp_path / ".agent-team"))
    assert state is not None
    return result, prompt_contexts, sdk_calls, state


@pytest.mark.asyncio
async def test_wave_a_contract_drift_redispatches_back_to_wave_a(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result, prompt_contexts, sdk_calls, state = await _run_contract_redispatch_flow(
        tmp_path,
        monkeypatch,
    )

    progress = state.wave_progress["milestone-orders"]
    history = progress["redispatch_history"]
    wave_a_contexts = [context for wave, context in prompt_contexts if wave == "A"]

    assert result.success is True
    assert [wave.wave for wave in result.waves] == ["A", "B", "C", "E"]
    assert sum(1 for wave, role in sdk_calls if wave == "A" and role == "wave") == 2
    assert state.wave_redispatch_attempts == {"milestone-orders:A": 1}
    assert progress["completed_waves"] == ["A", "B", "C", "E"]
    assert [event["event"] for event in history] == ["scheduled"]
    assert history[0]["trigger_codes"] == ["WAVE-A-CONTRACT-DRIFT-001"]
    assert wave_a_contexts[0] == ""
    assert "WAVE-A-CONTRACT-DRIFT-001" in wave_a_contexts[1]
