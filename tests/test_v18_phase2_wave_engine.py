from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.agents import build_wave_prompt
from agent_team_v15.artifact_store import extract_wave_artifacts, format_artifacts_for_prompt
from agent_team_v15.compile_profiles import format_compile_errors_for_prompt, get_compile_profile
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.fix_executor import execute_unified_fix_async
from agent_team_v15 import openapi_generator as openapi_generator_module
from agent_team_v15.openapi_generator import generate_openapi_contracts
from agent_team_v15.registry_compiler import compile_registries
from agent_team_v15.wave_executor import WAVE_SEQUENCES, execute_milestone_waves


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _milestone(
    milestone_id: str = "milestone-1",
    *,
    template: str = "full_stack",
    title: str = "Orders",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title=title,
        template=template,
        description=f"{title} milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


@pytest.mark.asyncio
async def test_execute_milestone_waves_runs_all_waves_and_persists_artifacts(tmp_path: Path) -> None:
    root = tmp_path
    milestone = _milestone()
    states: list[tuple[str, str]] = []
    completed: list[str] = []
    sdk_calls: list[tuple[str, str]] = []

    async def build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(*, prompt: str, wave: str, role: str = "wave", **_: object) -> float:
        sdk_calls.append((wave, role))
        if role == "wave":
            _write(root / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = '{prompt}';\n")
        return 1.25

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def extract_artifacts(**kwargs: object) -> dict[str, object]:
        return {
            "wave": kwargs["wave"],
            "files_created": list(kwargs.get("files_created", []) or []),
            "files_modified": list(kwargs.get("files_modified", []) or []),
        }

    async def generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
        milestone_id = getattr(milestone, "id", "milestone-1")
        current_spec = _write(Path(cwd) / "contracts" / "openapi" / "current.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
        local_spec = _write(Path(cwd) / "contracts" / "openapi" / f"{milestone_id}.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
        return {
            "success": True,
            "milestone_spec_path": str(local_spec),
            "cumulative_spec_path": str(current_spec),
            "client_exports": ["getOrders"],
            "breaking_changes": [],
            "endpoints_summary": [{"method": "GET", "path": "/orders"}],
            "files_created": [
                str(local_spec.relative_to(cwd)).replace("\\", "/"),
                str(current_spec.relative_to(cwd)).replace("\\", "/"),
            ],
        }

    def run_scaffolding(**_: object) -> list[str]:
        return ["scaffolded/placeholder.ts"]

    def save_wave_state(*, milestone_id: str, wave: str, status: str, **_: object) -> None:
        states.append((wave, status))
        state_path = root / ".agent-team" / "STATE.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        if not state_path.exists():
            state_path.write_text("{}", encoding="utf-8")

    def on_wave_complete(*, wave: str, **_: object) -> None:
        completed.append(wave)

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={"project_name": "Demo"},
        config=SimpleNamespace(),
        cwd=str(root),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=extract_artifacts,
        generate_contracts=generate_contracts,
        run_scaffolding=run_scaffolding,
        save_wave_state=save_wave_state,
        on_wave_complete=on_wave_complete,
    )

    assert result.success is True
    assert [wave.wave for wave in result.waves] == ["A", "B", "C", "D", "D5", "E"]
    assert result.total_cost == pytest.approx(6.25)
    assert [item for item in sdk_calls if item[1] == "wave"] == [
        ("A", "wave"),
        ("B", "wave"),
        ("D", "wave"),
        ("D5", "wave"),
        ("E", "wave"),
    ]
    assert completed == ["A", "B", "C", "D", "D5", "E"]
    assert ("A", "IN_PROGRESS") in states and ("E", "COMPLETE") in states
    assert (root / ".agent-team" / "artifacts" / "milestone-1-wave-A.json").is_file()
    assert (root / ".agent-team" / "artifacts" / "milestone-1-wave-C.json").is_file()


@pytest.mark.asyncio
async def test_execute_milestone_waves_resume_skips_completed_waves(tmp_path: Path) -> None:
    root = tmp_path
    milestone = _milestone()
    state_dir = root / ".agent-team"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "STATE.json").write_text(
        json.dumps(
            {
                "wave_progress": {
                    milestone.id: {
                        "current_wave": "A",
                        "completed_waves": ["A"],
                        "wave_artifacts": {"A": str(state_dir / "artifacts" / f"{milestone.id}-wave-A.json")},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    artifact_dir = state_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / f"{milestone.id}-wave-A.json").write_text(
        json.dumps({"wave": "A", "entities": [{"name": "Order"}]}),
        encoding="utf-8",
    )

    calls: list[str] = []

    async def build_prompt(**kwargs: object) -> str:
        calls.append(str(kwargs["wave"]))
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            _write(root / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
        return 1.0

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def generate_contracts(**_: object) -> dict[str, object]:
        return {
            "success": True,
            "milestone_spec_path": "",
            "cumulative_spec_path": "",
            "client_exports": [],
            "breaking_changes": [],
            "endpoints_summary": [],
            "files_created": [],
        }

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={},
        config=SimpleNamespace(),
        cwd=str(root),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    assert result.success is True
    assert [wave.wave for wave in result.waves] == ["B", "C", "D", "D5", "E"]
    assert calls == ["B", "D", "D5", "E"]


@pytest.mark.asyncio
async def test_execute_milestone_waves_scaffolding_requires_explicit_wave_mode(tmp_path: Path) -> None:
    milestone = _milestone(template="backend_only")
    product_ir_dir = tmp_path / ".agent-team" / "product-ir"
    product_ir_dir.mkdir(parents=True, exist_ok=True)
    (product_ir_dir / "product.ir.json").write_text(json.dumps({"project_name": "Demo"}), encoding="utf-8")

    scaffold_calls = {"count": 0}

    async def build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
        return 1.0

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def generate_contracts(**_: object) -> dict[str, object]:
        return {
            "success": True,
            "milestone_spec_path": "",
            "cumulative_spec_path": "",
            "client_exports": [],
            "breaking_changes": [],
            "endpoints_summary": [],
            "files_created": [],
        }

    def run_scaffolding(**_: object) -> list[str]:
        scaffold_calls["count"] += 1
        return ["scaffolded/backend.ts"]

    default_config = AgentTeamConfig()
    result = await execute_milestone_waves(
        milestone=milestone,
        ir={"project_name": "Demo"},
        config=default_config,
        cwd=str(tmp_path),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=generate_contracts,
        run_scaffolding=run_scaffolding,
        save_wave_state=None,
    )

    assert result.success is True
    assert scaffold_calls["count"] == 0

    wave_config = AgentTeamConfig()
    wave_config.v18.execution_mode = "wave"
    wave_config.v18.scaffold_enabled = True
    result = await execute_milestone_waves(
        milestone=milestone,
        ir={"project_name": "Demo"},
        config=wave_config,
        cwd=str(tmp_path),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=generate_contracts,
        run_scaffolding=run_scaffolding,
        save_wave_state=None,
    )

    assert result.success is True
    assert scaffold_calls["count"] == 1


@pytest.mark.asyncio
async def test_execute_milestone_waves_scaffolding_runs_between_wave_a_and_wave_b(tmp_path: Path) -> None:
    milestone = _milestone()
    product_ir_dir = tmp_path / ".agent-team" / "product-ir"
    product_ir_dir.mkdir(parents=True, exist_ok=True)
    (product_ir_dir / "product.ir.json").write_text(json.dumps({"project_name": "Demo"}), encoding="utf-8")

    call_order: list[str] = []

    async def build_prompt(**kwargs: object) -> str:
        wave = str(kwargs["wave"])
        call_order.append(f"prompt-{wave}")
        if wave == "A":
            assert kwargs["scaffolded_files"] == []
        if wave == "B":
            assert kwargs["scaffolded_files"] == ["scaffolded/backend.ts"]
        return f"wave {wave}"

    async def execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            call_order.append(f"exec-{wave}")
            _write(tmp_path / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
        return 1.0

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def generate_contracts(**_: object) -> dict[str, object]:
        return {
            "success": True,
            "milestone_spec_path": "",
            "cumulative_spec_path": "",
            "client_exports": [],
            "breaking_changes": [],
            "endpoints_summary": [],
            "files_created": [],
        }

    def run_scaffolding(**_: object) -> list[str]:
        call_order.append("scaffold")
        return ["scaffolded/backend.ts"]

    config = AgentTeamConfig()
    config.v18.execution_mode = "wave"
    config.v18.scaffold_enabled = True

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={"project_name": "Demo"},
        config=config,
        cwd=str(tmp_path),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=generate_contracts,
        run_scaffolding=run_scaffolding,
        save_wave_state=None,
    )

    assert result.success is True
    assert call_order.index("exec-A") < call_order.index("scaffold") < call_order.index("prompt-B")


@pytest.mark.asyncio
async def test_execute_milestone_waves_compile_failure_stops_sequence(tmp_path: Path) -> None:
    root = tmp_path
    milestone = _milestone()
    sdk_calls: list[tuple[str, str]] = []

    async def execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        sdk_calls.append((wave, role))
        return 1.0

    async def run_compile_check(*, wave: str = "", **_: object) -> dict[str, object]:
        if wave == "A":
            return {
                "passed": False,
                "iterations": 1,
                "initial_error_count": 1,
                "errors": [{"file": "src/a.ts", "line": 1, "code": "TS1000", "message": "broken"}],
            }
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={},
        config=SimpleNamespace(),
        cwd=str(root),
        build_wave_prompt=lambda **kwargs: f"wave {kwargs['wave']}",
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=None,
        run_scaffolding=None,
        save_wave_state=None,
    )

    assert result.success is False
    assert result.error_wave == "A"
    assert [wave.wave for wave in result.waves] == ["A"]
    assert ("A", "compile_fix") in sdk_calls
    assert not any(call[0] == "B" and call[1] == "wave" for call in sdk_calls)


@pytest.mark.asyncio
async def test_wave_b_dto_guard_fixes_violations_before_wave_c(tmp_path: Path) -> None:
    root = tmp_path
    milestone = _milestone(template="backend_only")
    _write(
        root / "package.json",
        json.dumps({"dependencies": {"@nestjs/swagger": "^7.0.0"}}),
    )
    sdk_calls: list[tuple[str, str]] = []
    dto_fix_prompts: list[str] = []

    async def execute_sdk_call(*, prompt: str, wave: str, role: str = "wave", cwd: str, **_: object) -> float:
        sdk_calls.append((wave, role))
        dto_path = Path(cwd) / "apps" / "api" / "src" / "orders" / "dto" / "create-order.dto.ts"
        if role == "wave" and wave == "B":
            _write(
                dto_path,
                "export class CreateOrderDto {\n"
                "  customerId: string;\n"
                "}\n",
            )
        elif role == "compile_fix" and wave == "B":
            dto_fix_prompts.append(prompt)
            _write(
                dto_path,
                "import { ApiProperty } from '@nestjs/swagger';\n\n"
                "export class CreateOrderDto {\n"
                "  @ApiProperty({ description: 'Customer identifier' })\n"
                "  customerId: string;\n"
                "}\n",
            )
        return 1.0

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def generate_contracts(**_: object) -> dict[str, object]:
        return {
            "success": True,
            "milestone_spec_path": "",
            "cumulative_spec_path": "",
            "client_exports": [],
            "breaking_changes": [],
            "endpoints_summary": [],
            "files_created": [],
        }

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={},
        config=SimpleNamespace(),
        cwd=str(root),
        build_wave_prompt=lambda **kwargs: f"wave {kwargs['wave']}",
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    assert result.success is True
    assert [wave.wave for wave in result.waves] == ["A", "B", "C", "E"]
    assert dto_fix_prompts
    assert "DTO-PROP-001" in dto_fix_prompts[0]
    assert "create-order.dto.ts" in dto_fix_prompts[0]
    assert sdk_calls.count(("B", "compile_fix")) == 1


@pytest.mark.asyncio
async def test_wave_b_dto_guard_blocks_wave_c_only_after_persistent_failures(tmp_path: Path) -> None:
    root = tmp_path
    milestone = _milestone(template="backend_only")
    _write(
        root / "package.json",
        json.dumps({"dependencies": {"@nestjs/swagger": "^7.0.0"}}),
    )
    compile_fix_prompts: list[str] = []

    async def execute_sdk_call(*, prompt: str, wave: str, role: str = "wave", cwd: str, **_: object) -> float:
        dto_path = Path(cwd) / "apps" / "api" / "src" / "orders" / "dto" / "create-order.dto.ts"
        if role == "wave" and wave == "B":
            _write(
                dto_path,
                "export class CreateOrderDto {\n"
                "  customerId: string;\n"
                "}\n",
            )
        elif role == "compile_fix" and wave == "B":
            compile_fix_prompts.append(prompt)
        return 1.0

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={},
        config=SimpleNamespace(),
        cwd=str(root),
        build_wave_prompt=lambda **kwargs: f"wave {kwargs['wave']}",
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=None,
        run_scaffolding=None,
        save_wave_state=None,
    )

    assert result.success is False
    assert result.error_wave == "B"
    assert [wave.wave for wave in result.waves] == ["A", "B"]
    assert len(compile_fix_prompts) == 2
    assert result.waves[-1].error_message.startswith("Wave B DTO contract guard found")
    assert any(finding.code == "DTO-PROP-001" for finding in result.waves[-1].findings)


def test_compile_profiles_scope_backend_and_frontend_targets(tmp_path: Path) -> None:
    root = tmp_path
    _write(root / "apps" / "api" / "tsconfig.json", "{}")
    _write(root / "apps" / "web" / "tsconfig.json", "{}")
    _write(root / "packages" / "generated-client" / "tsconfig.json", "{}")
    _write(root / "packages" / "shared-contracts" / "tsconfig.json", "{}")

    wave_a = get_compile_profile("A", "full_stack", "NestJS Next.js", root)
    wave_b = get_compile_profile("B", "full_stack", "NestJS Next.js", root)
    wave_d = get_compile_profile("D", "full_stack", "NestJS Next.js", root)
    wave_d5 = get_compile_profile("D5", "full_stack", "NestJS Next.js", root)

    commands_a = [" ".join(cmd) for cmd in wave_a.commands]
    commands_b = [" ".join(cmd) for cmd in wave_b.commands]
    commands_d = [" ".join(cmd) for cmd in wave_d.commands]
    commands_d5 = [" ".join(cmd) for cmd in wave_d5.commands]

    assert any("apps\\api\\tsconfig.json" in cmd or "apps/api/tsconfig.json" in cmd for cmd in commands_a)
    assert not any("apps\\web\\tsconfig.json" in cmd or "apps/web/tsconfig.json" in cmd for cmd in commands_a)
    assert any("shared-contracts" in cmd for cmd in commands_b)
    assert any("apps\\web\\tsconfig.json" in cmd or "apps/web/tsconfig.json" in cmd for cmd in commands_d)
    assert any("generated-client" in cmd for cmd in commands_d)
    assert any("apps\\web\\tsconfig.json" in cmd or "apps/web/tsconfig.json" in cmd for cmd in commands_d5)
    assert any("generated-client" in cmd for cmd in commands_d5)


def test_format_compile_errors_for_prompt_limits_output() -> None:
    errors = [
        {"file": f"src/file_{index}.ts", "line": index, "message": f"error {index}"}
        for index in range(1, 6)
    ]
    rendered = format_compile_errors_for_prompt(errors, max_errors=3)
    assert "src/file_1.ts:1" in rendered
    assert "src/file_4.ts:4" not in rendered
    assert "and 2 more errors" in rendered
    assert "Fix ALL compile errors" in rendered


def test_generate_openapi_contracts_regex_fallback_creates_specs_and_client(tmp_path: Path) -> None:
    root = tmp_path
    milestone = _milestone("milestone-orders")
    _write(root / ".agent-team" / "artifacts" / f"{milestone.id}-wave-B.json", json.dumps({"files_created": ["apps/api/src/orders/orders.module.ts"]}))
    _write(root / "apps" / "api" / "src" / "orders" / "orders.module.ts", "export class OrdersModule {}\n")
    _write(
        root / "apps" / "api" / "src" / "orders" / "orders.controller.ts",
        """
@Controller('orders')
export class OrdersController {
  @Get()
  @ApiResponse({ type: OrderDto })
  list(): Promise<OrderDto> { return {} as Promise<OrderDto>; }

  @Post()
  @ApiResponse({ type: OrderDto })
  create(@Body() body: CreateOrderDto): Promise<OrderDto> { return {} as Promise<OrderDto>; }
}
""".strip()
        + "\n",
    )
    _write(
        root / "apps" / "api" / "src" / "orders" / "order.dto.ts",
        """
export class OrderDto {
  @ApiProperty()
  id: string;
}

export class CreateOrderDto {
  @ApiProperty()
  name: string;
}
""".strip()
        + "\n",
    )

    result = generate_openapi_contracts(str(root), milestone)

    assert result.success is True
    assert Path(result.cumulative_spec_path).is_file()
    assert Path(result.milestone_spec_path).is_file()
    assert (root / "packages" / "api-client" / "index.ts").is_file()
    assert result.client_manifest[0]["symbol"] == result.client_exports[0]
    assert result.client_manifest[0]["method"] == "GET"
    assert result.client_manifest[0]["path"] == "/orders"
    current_spec = json.loads(Path(result.cumulative_spec_path).read_text(encoding="utf-8"))
    assert "/orders" in current_spec["paths"]


def test_generate_openapi_contracts_uses_scaffolded_script_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path
    milestone = _milestone("milestone-orders")
    _write(
        root / ".agent-team" / "artifacts" / f"{milestone.id}-wave-B.json",
        json.dumps({"files_created": ["apps/api/src/orders/orders.module.ts"]}),
    )
    _write(root / "scripts" / "generate-openapi.ts", "console.log('generate');\n")

    def fake_run(
        command: list[str],
        *,
        cwd: str,
        capture_output: bool,
        text: bool,
        timeout: int,
        env: dict[str, str],
    ) -> SimpleNamespace:
        # D-03: argv[0] is now the resolved absolute launcher path
        # (e.g. ``/usr/local/bin/npx`` or ``C:\Program Files\nodejs\npx.CMD``)
        # rather than the bare ``npx`` — the historical bare form produced
        # ``[WinError 2] The system cannot find the file specified`` on
        # Windows. Assert on the basename to stay platform-agnostic.
        argv0 = Path(command[0]).name.lower()
        assert argv0.startswith("npx"), f"expected npx launcher, got {command[0]!r}"
        assert command[1] == "ts-node"
        assert command[2].replace("\\", "/").endswith("scripts/generate-openapi.ts")
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Demo", "version": "1.0.0"},
            "paths": {
                "/orders": {
                    "get": {
                        "operationId": "listOrders",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        contracts_dir = Path(env["OUTPUT_DIR"])
        _write(contracts_dir / "current.json", json.dumps(spec))
        _write(contracts_dir / f"{milestone.id}.json", json.dumps(spec))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(openapi_generator_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        openapi_generator_module,
        "_generate_client_package",
        lambda *_args, **_kwargs: {"success": True, "exports": [], "manifest": [], "files": []},
    )

    result = generate_openapi_contracts(str(root), milestone)

    assert result.success is True
    assert Path(result.cumulative_spec_path).is_file()
    assert Path(result.milestone_spec_path).is_file()


def test_generate_openapi_contracts_fails_on_duplicate_operation_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    milestone = _milestone()
    contracts_dir = root / "contracts" / "openapi"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    current_spec = contracts_dir / "current.json"
    milestone_spec = contracts_dir / f"{milestone.id}.json"
    duplicate_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "paths": {
            "/orders": {"get": {"operationId": "listOrders", "responses": {"200": {"description": "ok"}}}},
            "/api/orders": {"get": {"operationId": "listOrders", "responses": {"200": {"description": "ok"}}}},
        },
    }
    current_spec.write_text(json.dumps(duplicate_spec), encoding="utf-8")
    milestone_spec.write_text(json.dumps(duplicate_spec), encoding="utf-8")

    monkeypatch.setattr(
        openapi_generator_module,
        "_generate_openapi_specs",
        lambda *_args, **_kwargs: {
            "success": True,
            "milestone_spec_path": str(milestone_spec),
            "cumulative_spec_path": str(current_spec),
            "files": [
                str(milestone_spec.relative_to(root)).replace("\\", "/"),
                str(current_spec.relative_to(root)).replace("\\", "/"),
            ],
        },
    )

    result = generate_openapi_contracts(str(root), milestone)

    assert result.success is False
    assert "Duplicate operationId" in result.error_message
    assert result.client_exports == []


def test_extract_wave_artifacts_and_prompt_routing(tmp_path: Path) -> None:
    root = tmp_path
    _write(
        root / "apps" / "api" / "src" / "orders" / "order.entity.ts",
        """
@Entity()
export class Order {
  @PrimaryGeneratedColumn()
  id: string;

  @Column()
  total: number;
}
""".strip()
        + "\n",
    )
    _write(
        root / "apps" / "api" / "src" / "orders" / "orders.service.ts",
        """
@Injectable()
export class OrdersService {
  async list(): Promise<Order[]> { return []; }
}
""".strip()
        + "\n",
    )
    _write(
        root / "apps" / "api" / "src" / "orders" / "orders.controller.ts",
        """
@Controller('orders')
export class OrdersController {
  @Get()
  async list() {}
}
""".strip()
        + "\n",
    )
    _write(
        root / "apps" / "api" / "src" / "orders" / "create-order.dto.ts",
        """
export class CreateOrderDto {
  @ApiProperty()
  name: string;
}
""".strip()
        + "\n",
    )
    _write(root / "packages" / "api-client" / "index.ts", "export async function listOrders() {}\n")
    _write(
        root / "apps" / "web" / "src" / "app" / "orders" / "page.tsx",
        "import { listOrders } from '@project/api-client';\nexport default function OrdersPage() { return null; }\n",
    )

    changed_files = [
        "apps/api/src/orders/order.entity.ts",
        "apps/api/src/orders/orders.service.ts",
        "apps/api/src/orders/orders.controller.ts",
        "apps/api/src/orders/create-order.dto.ts",
        "packages/api-client/index.ts",
        "apps/web/src/app/orders/page.tsx",
    ]

    artifact = extract_wave_artifacts(str(root), "milestone-1", "B", changed_files)

    assert [entity["name"] for entity in artifact["entities"]] == ["Order"]
    assert [service["name"] for service in artifact["services"]] == ["OrdersService"]
    assert [controller["name"] for controller in artifact["controllers"]] == ["OrdersController"]
    assert [dto["name"] for dto in artifact["dtos"]] == ["CreateOrderDto"]
    assert artifact["client_exports"] == ["listOrders"]
    assert artifact["pages"][0]["route"].endswith("/orders")

    routed = format_artifacts_for_prompt(
        {
            "C": {
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
                "endpoints": [{"method": "GET", "path": "/orders"}],
            }
        },
        {},
        "D",
    )
    assert "Wave C Contracts" in routed
    assert "listOrders" in routed
    assert "response: Order[]" in routed


def test_build_wave_prompts_preserve_boundaries() -> None:
    config = AgentTeamConfig()
    milestone = _milestone(title="Orders UI")
    ir = {
        "project_name": "Demo",
        "acceptance_criteria": [{"id": "AC-1", "text": "Show the orders list"}],
        "i18n": {"locales": ["en", "ar"], "rtl_locales": ["ar"]},
    }

    prompt_d = build_wave_prompt(
        wave="D",
        milestone=milestone,
        wave_artifacts={"C": {"client_exports": ["listOrders"], "endpoints": [{"method": "GET", "path": "/orders"}]}},
        dependency_artifacts={},
        ir=ir,
        config=config,
        scaffolded_files=["apps/web/src/app/orders/page.tsx"],
    )
    prompt_e = build_wave_prompt(
        wave="E",
        milestone=milestone,
        wave_artifacts={"A": {"files_created": ["apps/api/src/orders/order.entity.ts"]}},
        dependency_artifacts={},
        ir=ir,
        config=config,
        scaffolded_files=[],
    )
    prompt_d5 = build_wave_prompt(
        wave="D5",
        milestone=milestone,
        wave_artifacts={"D": {"files_created": ["apps/web/src/app/orders/page.tsx"]}},
        dependency_artifacts={},
        ir=ir,
        config=config,
        scaffolded_files=[],
    )

    assert "MUST import from `packages/api-client/` and call the generated functions" in prompt_d
    assert "listOrders" in prompt_d
    assert "Do NOT re-implement HTTP calls with `fetch`/`axios`." in prompt_d
    assert "Do NOT modify data fetching, API calls, state management, form handlers, routing, or TypeScript interfaces." in prompt_d5
    assert "Status: COMPLETE" in prompt_e
    # V18.2 decoupling: wiring/i18n/playwright sections are always emitted for
    # frontend-containing milestones, independent of evidence_mode.
    assert "[PLAYWRIGHT TESTS - REQUIRED]" in prompt_e
    assert "[WIRING SCANNER - REQUIRED]" in prompt_e
    assert "[I18N SCANNER - REQUIRED]" in prompt_e


def test_wave_sequences_include_d5_for_frontend_paths() -> None:
    assert WAVE_SEQUENCES["full_stack"] == ["A", "B", "C", "D", "D5", "E"]
    assert WAVE_SEQUENCES["frontend_only"] == ["A", "D", "D5", "E"]


@pytest.mark.asyncio
async def test_execute_milestone_waves_skips_d5_when_disabled(tmp_path: Path) -> None:
    root = tmp_path
    milestone = _milestone()
    prompt_calls: list[str] = []

    async def build_prompt(**kwargs: object) -> str:
        prompt_calls.append(str(kwargs["wave"]))
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            _write(root / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
        return 1.0

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def generate_contracts(**_: object) -> dict[str, object]:
        return {
            "success": True,
            "milestone_spec_path": "",
            "cumulative_spec_path": "",
            "client_exports": [],
            "breaking_changes": [],
            "endpoints_summary": [],
            "files_created": [],
        }

    config = AgentTeamConfig()
    config.v18.wave_d5_enabled = False

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={},
        config=config,
        cwd=str(root),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    assert result.success is True
    # V18.2: Wave T sits between D5 and E. D5 is disabled here, but T is still on.
    assert [wave.wave for wave in result.waves] == ["A", "B", "C", "D", "T", "E"]
    assert prompt_calls == ["A", "B", "D", "T", "E"]


@pytest.mark.asyncio
async def test_execute_milestone_waves_d5_compile_failure_rolls_back_and_continues(tmp_path: Path) -> None:
    root = tmp_path
    milestone = _milestone(title="Orders UI")

    async def build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(*, wave: str, role: str = "wave", cwd: str, **_: object) -> float:
        if role == "wave":
            _write(Path(cwd) / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
        return 1.0

    async def run_compile_check(*, wave: str = "", **_: object) -> dict[str, object]:
        if wave == "D5":
            return {
                "passed": False,
                "iterations": 1,
                "initial_error_count": 1,
                "errors": [{"file": "src/d5.ts", "line": 1, "code": "TS1000", "message": "broken"}],
            }
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def generate_contracts(**_: object) -> dict[str, object]:
        return {
            "success": True,
            "milestone_spec_path": "",
            "cumulative_spec_path": "",
            "client_exports": [],
            "breaking_changes": [],
            "endpoints_summary": [],
            "files_created": [],
        }

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={},
        config=AgentTeamConfig(),
        cwd=str(root),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    assert result.success is True
    # V18.2: Wave T sits between D5 and E.
    assert [wave.wave for wave in result.waves] == ["A", "B", "C", "D", "D5", "T", "E"]
    d5_result = next(wave for wave in result.waves if wave.wave == "D5")
    assert d5_result.provider == "claude"
    assert d5_result.compile_passed is False
    assert d5_result.rolled_back is True
    assert "restored the pre-D5 checkpoint" in d5_result.error_message
    assert not (root / "src" / "d5.ts").exists()
    assert (root / "src" / "e.ts").is_file()

    telemetry = json.loads(
        (root / ".agent-team" / "telemetry" / f"{milestone.id}-wave-D5.json").read_text(encoding="utf-8")
    )
    assert telemetry["provider"] == "claude"
    assert telemetry["rolled_back"] is True


@pytest.mark.asyncio
async def test_execute_milestone_waves_retries_sdk_timeout_once_and_writes_hang_report(
    tmp_path: Path,
) -> None:
    root = tmp_path
    milestone = _milestone()
    attempts: list[str] = []
    config = AgentTeamConfig()
    config.v18.wave_idle_timeout_seconds = 1
    config.v18.wave_watchdog_poll_seconds = 1
    config.v18.wave_watchdog_max_retries = 1

    async def build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(
        *,
        wave: str,
        role: str = "wave",
        progress_callback=None,
        **_: object,
    ) -> float:
        if role == "wave":
            attempts.append(wave)
            await asyncio.sleep(5)
        return 1.0

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def generate_contracts(**_: object) -> dict[str, object]:
        return {
            "success": True,
            "milestone_spec_path": "",
            "cumulative_spec_path": "",
            "client_exports": [],
            "breaking_changes": [],
            "endpoints_summary": [],
            "files_created": [],
        }

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={},
        config=config,
        cwd=str(root),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    assert result.success is False
    assert result.error_wave == "A"
    assert attempts == ["A", "A"]

    wave_a = result.waves[0]
    assert wave_a.wave_timed_out is True
    assert wave_a.last_sdk_message_type == "sdk_call_started"
    assert wave_a.hang_report_path
    assert Path(wave_a.hang_report_path).is_file()

    telemetry = json.loads(
        (root / ".agent-team" / "telemetry" / f"{milestone.id}-wave-A.json").read_text(encoding="utf-8")
    )
    assert telemetry["wave_timed_out"] is True
    assert telemetry["hang_report_path"]


@pytest.mark.asyncio
async def test_execute_milestone_waves_blocks_d5_on_persistent_frontend_hallucinations(
    tmp_path: Path,
) -> None:
    root = tmp_path
    milestone = _milestone(template="frontend_only", title="Orders UI")
    _write(
        root / "apps" / "web" / "src" / "app" / "orders" / "page.tsx",
        "import { Inter } from 'next/font/google';\n"
        "const inter = Inter({ subsets: ['latin', 'arabic'] });\n"
        "const locale = value as 'en' | 'ar' | 'id';\n"
        "export default function OrdersPage() { return null; }\n",
    )
    compile_fix_roles: list[str] = []

    async def build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(*, role: str = "wave", wave: str, **_: object) -> float:
        compile_fix_roles.append(f"{wave}:{role}")
        return 1.0

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={"i18n": {"locales": ["en", "ar"]}},
        config=AgentTeamConfig(),
        cwd=str(root),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=None,
        run_scaffolding=None,
        save_wave_state=None,
    )

    assert result.success is False
    assert result.error_wave == "D"
    assert [wave.wave for wave in result.waves] == ["A", "D"]
    assert any(entry == "D:compile_fix" for entry in compile_fix_roles)

    wave_d = result.waves[-1]
    assert {finding.code for finding in wave_d.findings} == {
        "FONT-SUBSET-001",
        "LOCALE-HALLUCINATE-001",
    }
    assert "Wave D frontend hallucination guard found 2 persistent violation(s)" in wave_d.error_message


@pytest.mark.asyncio
async def test_execute_unified_fix_async_routes_patch_and_full_without_dropping_full(tmp_path: Path) -> None:
    original_prd = _write(tmp_path / "prd.md", "# Demo\n")
    fix_prd_text = """
## Features

### F-FIX-001: Patchable fix
[EXECUTION_MODE: patch]
#### Files to Modify
- `src/app.ts`

### F-FIX-002: Full fix
[EXECUTION_MODE: full]
#### Files to Modify
- `schema.prisma`

## Regression Guard
- none
""".strip()
    patch_batches: list[list[str]] = []

    async def run_patch_fixes(**kwargs: object) -> float:
        patch_batches.append([feature["mode"] for feature in kwargs["patch_features"]])
        return 1.0

    cost = await execute_unified_fix_async(
        findings=[],
        original_prd_path=original_prd,
        cwd=tmp_path,
        config={},
        run_number=2,
        fix_prd_text=fix_prd_text,
        run_patch_fixes=run_patch_fixes,
    )

    assert cost == pytest.approx(2.0)
    assert patch_batches == [["patch"], ["full"]]


@pytest.mark.asyncio
async def test_execute_unified_fix_async_records_blast_radius_in_log_and_telemetry(tmp_path: Path) -> None:
    original_prd = _write(tmp_path / "prd.md", "# Demo\n")
    fix_prd_text = """
## Features

### F-FIX-001: Orders wiring
[EXECUTION_MODE: patch]
#### Files to Modify
- `src/orders/orders.service.ts`

## Regression Guard
- none
""".strip()

    async def run_patch_fixes(**_kwargs: object) -> float:
        return 1.0

    cost = await execute_unified_fix_async(
        findings=[SimpleNamespace(title="Orders service wiring is broken")],
        original_prd_path=original_prd,
        cwd=tmp_path,
        config=AgentTeamConfig(),
        run_number=3,
        fix_prd_text=fix_prd_text,
        run_patch_fixes=run_patch_fixes,
    )

    assert cost == pytest.approx(1.0)

    fix_log = (tmp_path / ".agent-team" / "FIX_CYCLE_LOG.md").read_text(encoding="utf-8")
    assert "## Unified Fix Pipeline \u2014 Cycle 3" in fix_log
    assert "Execution pipeline:** unified" in fix_log
    assert "Blast radius:** patch" in fix_log
    assert "Dispatch summary:** 1 patch, 0 full" in fix_log

    telemetry = json.loads(
        (tmp_path / ".agent-team" / "telemetry" / "fix-pipeline-run3.json").read_text(encoding="utf-8")
    )
    assert telemetry["pipeline"] == "unified"
    assert telemetry["overall_blast_radius"] == "patch"
    assert telemetry["dispatch_summary"] == "1 patch, 0 full"
    assert telemetry["features"][0]["blast_radius"] == "patch"


def test_compile_registries_merges_deterministically(tmp_path: Path) -> None:
    root = tmp_path
    _write(root / "package.json", json.dumps({"name": "demo", "dependencies": {"react": "18.0.0"}}, indent=2) + "\n")
    _write(
        root / ".agent-team" / "registries" / "m1" / "deps.registry.json",
        json.dumps({"dependencies": {"zod": "^1.0.0", "react": "^19.0.0"}}),
    )
    _write(
        root / ".agent-team" / "registries" / "m2" / "deps.registry.json",
        json.dumps({"dependencies": {"axios": "^1.7.0", "react": "^19.1.0"}}),
    )
    _write(
        root / ".agent-team" / "registries" / "m1" / "modules.registry.json",
        json.dumps({"modules": [{"class_name": "OrdersModule", "path": "./orders/orders.module"}]}),
    )
    _write(
        root / ".agent-team" / "registries" / "m2" / "modules.registry.json",
        json.dumps({"modules": [{"class_name": "UsersModule", "path": "./users/users.module"}]}),
    )

    results = compile_registries(str(root), ["m1", "m2"])

    package_json = json.loads((root / "package.json").read_text(encoding="utf-8"))
    modules_file = (root / "apps" / "api" / "src" / "app.module.ts").read_text(encoding="utf-8")

    assert results["deps"] is True
    assert results["modules"] is True
    assert package_json["dependencies"] == {
        "axios": "^1.7.0",
        "react": "^19.1.0",
        "zod": "^1.0.0",
    }
    assert "OrdersModule" in modules_file
    assert "UsersModule" in modules_file
