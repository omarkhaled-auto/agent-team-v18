"""Phase H3f ownership enforcement ring.

Focused coverage for Wave A ownership contract wiring:
- contract sourcing for scaffold-owned paths
- prompt injection presence / absence / ordering
- detection-only versus hard-fail behavior
- redispatch integration for OWNERSHIP-WAVE-A-FORBIDDEN-001
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.agents import build_wave_a_prompt
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.ownership_enforcer import (
    check_wave_a_forbidden_writes,
    get_scaffold_owned_paths_for_wave_a_prompt,
)
from agent_team_v15.state import RunState, load_state, save_state
from agent_team_v15.wave_executor import (
    _WAVE_REDISPATCH_TARGET_BY_FINDING_CODE,
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


def _ownership_contract_markdown() -> str:
    return (
        "# Scaffold Ownership Contract\n\n"
        "```yaml\n"
        "- path: package.json\n"
        "  owner: scaffold\n"
        "  optional: false\n"
        "\n"
        "- path: docker-compose.yml\n"
        "  owner: scaffold\n"
        "  optional: false\n"
        "\n"
        "- path: apps\\web\\src\\future.tsx\n"
        "  owner: scaffold\n"
        "  optional: false\n"
        "\n"
        "- path: apps/api/Dockerfile\n"
        "  owner: wave-b\n"
        "  optional: false\n"
        "```\n"
    )


def _write_workspace_contract(tmp_path: Path) -> Path:
    contract_path = tmp_path / "docs" / "SCAFFOLD_OWNERSHIP.md"
    _write(contract_path, _ownership_contract_markdown())
    return contract_path


def _config(
    *,
    ownership_enforcement_enabled: bool = False,
    wave_a_ownership_enforcement_enabled: bool = False,
    wave_a_ownership_contract_injection_enabled: bool = False,
    wave_a_contract_injection_enabled: bool = False,
    wave_a_contract_verifier_enabled: bool = False,
    recovery_wave_redispatch_enabled: bool = False,
    recovery_wave_redispatch_max_attempts: int = 2,
) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.execution_mode = "wave"
    cfg.v18.scaffold_enabled = True
    cfg.v18.scaffold_verifier_enabled = True
    cfg.v18.wave_a5_enabled = False
    cfg.v18.wave_t_enabled = False
    cfg.v18.wave_t5_enabled = False
    cfg.v18.live_endpoint_check = False
    cfg.v18.ownership_enforcement_enabled = ownership_enforcement_enabled
    cfg.v18.wave_a_ownership_enforcement_enabled = wave_a_ownership_enforcement_enabled
    cfg.v18.wave_a_ownership_contract_injection_enabled = (
        wave_a_ownership_contract_injection_enabled
    )
    cfg.v18.wave_a_contract_injection_enabled = wave_a_contract_injection_enabled
    cfg.v18.wave_a_contract_verifier_enabled = wave_a_contract_verifier_enabled
    cfg.v18.recovery_wave_redispatch_enabled = recovery_wave_redispatch_enabled
    cfg.v18.recovery_wave_redispatch_max_attempts = recovery_wave_redispatch_max_attempts
    return cfg


def _save_wave_state_for_test(
    cwd: str,
    milestone_id: str,
    wave: str,
    status: str,
    artifact_path: str | None = None,
) -> None:
    state_dir = Path(cwd) / ".agent-team"
    state = load_state(str(state_dir)) or RunState(task="h3f-ownership-enforcement")
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


def _seed_product_ir(tmp_path: Path) -> None:
    _write(
        tmp_path / ".agent-team" / "product-ir" / "product.ir.json",
        json.dumps({"project_name": "Demo"}),
    )


async def _run_ownership_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ownership_enforcement_enabled: bool,
    wave_a_ownership_enforcement_enabled: bool,
    wave_a_ownership_contract_injection_enabled: bool = False,
    wave_a_contract_injection_enabled: bool = False,
    wave_a_contract_verifier_enabled: bool = False,
    recovery_wave_redispatch_enabled: bool = False,
    recovery_wave_redispatch_max_attempts: int = 2,
    stack_contract: dict[str, object] | None = None,
    wave_a_attempt_outputs: list[dict[str, str]] | None = None,
) -> tuple[object, list[str], list[tuple[str, str]], list[tuple[str, str]], RunState]:
    _seed_product_ir(tmp_path)
    _write_workspace_contract(tmp_path)

    cfg = _config(
        ownership_enforcement_enabled=ownership_enforcement_enabled,
        wave_a_ownership_enforcement_enabled=wave_a_ownership_enforcement_enabled,
        wave_a_ownership_contract_injection_enabled=wave_a_ownership_contract_injection_enabled,
        wave_a_contract_injection_enabled=wave_a_contract_injection_enabled,
        wave_a_contract_verifier_enabled=wave_a_contract_verifier_enabled,
        recovery_wave_redispatch_enabled=recovery_wave_redispatch_enabled,
        recovery_wave_redispatch_max_attempts=recovery_wave_redispatch_max_attempts,
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
    prompt_texts: list[str] = []
    sdk_calls: list[tuple[str, str]] = []
    wave_a_runs = {"count": 0}
    attempt_outputs = wave_a_attempt_outputs or [
        {
            "docker-compose.yml": (
                "services:\n  api:\n    ports:\n      - \"3001:3001\"\n"
            ),
        }
    ]

    async def _run_scaffolding(**_kwargs):
        return []

    async def _build_prompt(**kwargs):
        if kwargs["wave"] == "A":
            prompt = build_wave_a_prompt(
                milestone=kwargs["milestone"],
                ir={"project_name": "Demo"},
                dependency_artifacts=kwargs["dependency_artifacts"],
                scaffolded_files=kwargs["scaffolded_files"],
                config=kwargs["config"],
                existing_prompt_framework="FRAMEWORK\n",
                cwd=kwargs["cwd"],
                stack_contract=kwargs.get("stack_contract"),
                stack_contract_rejection_context=str(
                    kwargs.get("stack_contract_rejection_context", "") or ""
                ),
            )
            prompt_texts.append(prompt)
            prompt_contexts.append(
                (
                    str(kwargs["wave"]),
                    str(kwargs.get("stack_contract_rejection_context", "") or ""),
                )
            )
            return prompt
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
            attempt_index = wave_a_runs["count"]
            wave_a_runs["count"] += 1
            outputs = attempt_outputs[min(attempt_index, len(attempt_outputs) - 1)]
            for rel_path, content in outputs.items():
                _write(tmp_path / rel_path, content)
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
        stack_contract=stack_contract,
    )
    state = load_state(str(tmp_path / ".agent-team"))
    assert state is not None
    return result, prompt_texts, prompt_contexts, sdk_calls, state


def test_scaffold_owned_paths_are_sourced_from_workspace_contract(
    tmp_path: Path,
) -> None:
    _write_workspace_contract(tmp_path)

    paths = get_scaffold_owned_paths_for_wave_a_prompt(tmp_path)

    assert paths == [
        "apps/web/src/future.tsx",
        "docker-compose.yml",
        "package.json",
    ]


def test_wave_a_prompt_omits_ownership_block_when_flag_off(tmp_path: Path) -> None:
    _write_workspace_contract(tmp_path)

    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir={"project_name": "Demo"},
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config(
            wave_a_contract_injection_enabled=True,
            wave_a_ownership_contract_injection_enabled=False,
        ),
        existing_prompt_framework="FRAMEWORK\n",
        cwd=str(tmp_path),
        stack_contract=_stack_contract(api_port=3001),
    )

    assert "[WAVE A EXPLICIT CONTRACT VALUES]" in prompt
    assert "<ownership_contract>" not in prompt
    assert "Scaffold-owned paths (you CANNOT write to these):" not in prompt


def test_wave_a_prompt_injects_ownership_block_after_explicit_values(
    tmp_path: Path,
) -> None:
    _write_workspace_contract(tmp_path)

    prompt = build_wave_a_prompt(
        milestone=_milestone(),
        ir={"project_name": "Demo"},
        dependency_artifacts={},
        scaffolded_files=[],
        config=_config(
            wave_a_contract_injection_enabled=True,
            wave_a_ownership_contract_injection_enabled=True,
        ),
        existing_prompt_framework="FRAMEWORK\n",
        cwd=str(tmp_path),
        stack_contract=_stack_contract(api_port=3001),
    )

    assert "[WAVE A EXPLICIT CONTRACT VALUES]" in prompt
    assert "<ownership_contract>" in prompt
    assert prompt.index("[WAVE A EXPLICIT CONTRACT VALUES]") < prompt.index(
        "<ownership_contract>"
    ) < prompt.index("[WAVE A - SCHEMA / FOUNDATION SPECIALIST]")

    lines = prompt.splitlines()
    start = lines.index("<ownership_contract>")
    end = lines.index("</ownership_contract>")
    bullet_lines = [line for line in lines[start:end] if line.startswith("- ")]
    assert bullet_lines == [
        "- apps/web/src/future.tsx",
        "- docker-compose.yml",
        "- package.json",
    ]


def test_detector_sets_blocks_wave_only_when_h3f_gate_is_enabled(
    tmp_path: Path,
) -> None:
    _write_workspace_contract(tmp_path)

    detection_only = check_wave_a_forbidden_writes(
        tmp_path,
        ["docker-compose.yml"],
        milestone_id="milestone-orders",
        config=_config(ownership_enforcement_enabled=True),
    )
    hard_fail = check_wave_a_forbidden_writes(
        tmp_path,
        ["docker-compose.yml"],
        milestone_id="milestone-orders",
        config=_config(wave_a_ownership_enforcement_enabled=True),
    )

    assert len(detection_only) == 1
    assert detection_only[0].blocks_wave is False
    assert len(hard_fail) == 1
    assert hard_fail[0].blocks_wave is True


def test_ownership_finding_code_is_whitelisted_for_wave_a_redispatch() -> None:
    assert _WAVE_REDISPATCH_TARGET_BY_FINDING_CODE["OWNERSHIP-WAVE-A-FORBIDDEN-001"] == "A"


@pytest.mark.asyncio
async def test_wave_a_ownership_check_reports_but_does_not_fail_when_hard_fail_flag_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _prompt_texts, _prompt_contexts, _sdk_calls, state = await _run_ownership_flow(
        tmp_path,
        monkeypatch,
        ownership_enforcement_enabled=True,
        wave_a_ownership_enforcement_enabled=False,
    )

    progress = state.wave_progress["milestone-orders"]
    wave_a = next(wave for wave in result.waves if wave.wave == "A")

    assert result.success is True
    assert wave_a.success is True
    assert any(f.code == "OWNERSHIP-WAVE-A-FORBIDDEN-001" for f in wave_a.findings)
    assert wave_a.error_message == ""
    assert state.wave_redispatch_attempts == {}
    assert "redispatch_history" not in progress


@pytest.mark.asyncio
async def test_wave_a_ownership_hard_fail_redispatches_with_rejection_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, prompt_texts, prompt_contexts, sdk_calls, state = await _run_ownership_flow(
        tmp_path,
        monkeypatch,
        ownership_enforcement_enabled=True,
        wave_a_ownership_enforcement_enabled=True,
        wave_a_ownership_contract_injection_enabled=True,
        wave_a_contract_injection_enabled=True,
        recovery_wave_redispatch_enabled=True,
        recovery_wave_redispatch_max_attempts=2,
        stack_contract=_stack_contract(api_port=3001),
        wave_a_attempt_outputs=[
            {
                "docker-compose.yml": (
                    "services:\n  api:\n    ports:\n      - \"3001:3001\"\n"
                ),
            },
            {},
        ],
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
    assert history[0]["trigger_codes"] == ["OWNERSHIP-WAVE-A-FORBIDDEN-001"]
    assert len(prompt_texts) == 2
    assert "[WAVE A EXPLICIT CONTRACT VALUES]" in prompt_texts[1]
    assert "<ownership_contract>" in prompt_texts[1]
    assert wave_a_contexts[0] == ""
    assert "OWNERSHIP-WAVE-A-FORBIDDEN-001" in wave_a_contexts[1]
    assert not (tmp_path / "docker-compose.yml").exists()


@pytest.mark.asyncio
async def test_h3e_contract_drift_and_h3f_ownership_gate_coexist_on_first_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, prompt_texts, prompt_contexts, sdk_calls, state = await _run_ownership_flow(
        tmp_path,
        monkeypatch,
        ownership_enforcement_enabled=True,
        wave_a_ownership_enforcement_enabled=True,
        wave_a_ownership_contract_injection_enabled=True,
        wave_a_contract_injection_enabled=True,
        wave_a_contract_verifier_enabled=True,
        recovery_wave_redispatch_enabled=True,
        recovery_wave_redispatch_max_attempts=2,
        stack_contract=_stack_contract(api_port=3001),
        wave_a_attempt_outputs=[
            {
                "docker-compose.yml": (
                    "services:\n  api:\n    ports:\n      - \"4000:4000\"\n"
                ),
            },
            {},
        ],
    )

    progress = state.wave_progress["milestone-orders"]
    history = progress["redispatch_history"]
    wave_a_contexts = [context for wave, context in prompt_contexts if wave == "A"]

    assert result.success is True
    assert sum(1 for wave, role in sdk_calls if wave == "A" and role == "wave") == 2
    assert history[0]["trigger_codes"] == [
        "OWNERSHIP-WAVE-A-FORBIDDEN-001",
        "WAVE-A-CONTRACT-DRIFT-001",
    ]
    assert len(prompt_texts) == 2
    assert "[WAVE A EXPLICIT CONTRACT VALUES]" in prompt_texts[1]
    assert "<ownership_contract>" in prompt_texts[1]
    assert "OWNERSHIP-WAVE-A-FORBIDDEN-001" in wave_a_contexts[1]
    assert "WAVE-A-CONTRACT-DRIFT-001" in wave_a_contexts[1]
    assert not (tmp_path / "docker-compose.yml").exists()
