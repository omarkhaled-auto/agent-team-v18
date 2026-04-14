from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.stack_contract import builtin_stack_contracts
from agent_team_v15.wave_executor import execute_milestone_waves


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _milestone(template: str = "backend_only") -> SimpleNamespace:
    return SimpleNamespace(
        id="milestone-orders",
        title="Orders",
        template=template,
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _stack_contract(*, confidence: str = "explicit") -> dict[str, object]:
    contract = builtin_stack_contracts()[("nestjs", "prisma")]
    contract.frontend_framework = "nextjs"
    contract.database = "postgresql"
    contract.monorepo_layout = "apps"
    contract.backend_path_prefix = "apps/api/"
    contract.frontend_path_prefix = "apps/web/"
    contract.confidence = confidence
    return contract.to_dict()


async def _run_backend_only(
    root: Path,
    *,
    wave_handler,
    confidence: str = "explicit",
) -> tuple[object, list[dict[str, object]], list[tuple[str, str, str]]]:
    prompt_records: list[dict[str, object]] = []
    sdk_calls: list[tuple[str, str, str]] = []
    milestone = _milestone(template="backend_only")

    async def _build_prompt(**kwargs: object) -> str:
        wave = str(kwargs["wave"])
        contract = dict(kwargs.get("stack_contract") or {})
        rejection = str(kwargs.get("stack_contract_rejection_context", "") or "")
        lines = [f"wave {wave}"]
        if contract:
            lines.extend(
                [
                    "=== STACK CONTRACT (NON-NEGOTIABLE) ===",
                    f"ORM: {contract.get('orm', '')}",
                    f"Backend: {contract.get('backend_framework', '')}",
                ]
            )
        if rejection:
            lines.extend(["PRIOR ATTEMPT REJECTED:", rejection])
        prompt = "\n".join(lines)
        prompt_records.append(
            {
                "wave": wave,
                "prompt": prompt,
                "rejection": rejection,
                "stack_contract": contract,
            }
        )
        return prompt

    async def _execute_sdk_call(*, prompt: str, wave: str, role: str = "wave", **_: object) -> float:
        sdk_calls.append((wave, role, prompt))
        if role == "wave":
            await wave_handler(root, wave, prompt)
        return 1.0

    async def _run_compile_check(**_: object) -> dict[str, object]:
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
        on_wave_complete=None,
        stack_contract=_stack_contract(confidence=confidence),
    )
    return result, prompt_records, sdk_calls


async def _clean_prisma_wave_output(root: Path, wave: str, prompt: str) -> None:
    if wave == "A":
        assert "=== STACK CONTRACT (NON-NEGOTIABLE) ===" in prompt
        _write(root / "apps" / "api" / "prisma" / "schema.prisma", "generator client { provider = \"prisma-client-js\" }\n")
        _write(
            root / "apps" / "api" / "src" / "prisma" / "prisma.service.ts",
            "import { PrismaClient } from '@prisma/client';\nexport const prisma = new PrismaClient();\n",
        )
    elif wave == "B":
        _write(root / "apps" / "api" / "src" / "orders" / "orders.service.ts", "export const orders = true;\n")


@pytest.mark.asyncio
async def test_wave_a_clean_output_passes_without_retry(tmp_path: Path) -> None:
    result, prompt_records, sdk_calls = await _run_backend_only(
        tmp_path,
        wave_handler=_clean_prisma_wave_output,
    )

    wave_a = next(wave for wave in result.waves if wave.wave == "A")
    assert result.success is True
    assert wave_a.stack_contract_retry_count == 0
    assert wave_a.stack_contract_violations == []
    assert sum(1 for wave, role, _ in sdk_calls if wave == "A" and role == "wave") == 1
    assert any(record["wave"] == "A" and "=== STACK CONTRACT (NON-NEGOTIABLE) ===" in str(record["prompt"]) for record in prompt_records)


@pytest.mark.asyncio
async def test_wave_a_forbidden_file_triggers_rollback_and_one_retry(tmp_path: Path) -> None:
    async def _handler(root: Path, wave: str, prompt: str) -> None:
        if wave != "A":
            await _clean_prisma_wave_output(root, wave, prompt)
            return
        if "PRIOR ATTEMPT REJECTED:" in prompt:
            await _clean_prisma_wave_output(root, wave, prompt)
            return
        _write(root / "apps" / "api" / "src" / "users" / "user.entity.ts", "@Entity()\nexport class User {}\n")

    result, prompt_records, sdk_calls = await _run_backend_only(tmp_path, wave_handler=_handler)

    wave_a = next(wave for wave in result.waves if wave.wave == "A")
    assert result.success is True
    assert wave_a.stack_contract_retry_count == 1
    assert sum(1 for wave, role, _ in sdk_calls if wave == "A" and role == "wave") == 2
    assert any(record["wave"] == "A" and record["rejection"] for record in prompt_records)
    assert not (tmp_path / "apps" / "api" / "src" / "users" / "user.entity.ts").exists()


@pytest.mark.asyncio
async def test_wave_a_persistent_violation_fails_with_telemetry(tmp_path: Path) -> None:
    async def _handler(root: Path, wave: str, prompt: str) -> None:
        if wave == "A":
            _write(root / "apps" / "api" / "src" / "users" / "user.entity.ts", "@Entity()\nexport class User {}\n")

    result, _, sdk_calls = await _run_backend_only(tmp_path, wave_handler=_handler)

    wave_a = next(wave for wave in result.waves if wave.wave == "A")
    telemetry = json.loads(
        (tmp_path / ".agent-team" / "telemetry" / "milestone-orders-wave-A.json").read_text(encoding="utf-8")
    )

    assert result.success is False
    assert result.error_wave == "A"
    assert wave_a.stack_contract_retry_count == 1
    assert wave_a.stack_contract_violations
    assert telemetry["stack_contract_retry_count"] == 1
    assert telemetry["stack_contract_violations"]
    assert sum(1 for wave, role, _ in sdk_calls if wave == "A" and role == "wave") == 2


@pytest.mark.asyncio
async def test_wave_b_violation_is_advisory_without_retry(tmp_path: Path) -> None:
    async def _handler(root: Path, wave: str, prompt: str) -> None:
        if wave == "A":
            await _clean_prisma_wave_output(root, wave, prompt)
        elif wave == "B":
            _write(
                root / "apps" / "api" / "src" / "orders" / "orders.service.ts",
                "import { TypeOrmModule } from '@nestjs/typeorm';\nexport const orders = true;\n",
            )

    result, _, sdk_calls = await _run_backend_only(tmp_path, wave_handler=_handler)

    wave_b = next(wave for wave in result.waves if wave.wave == "B")
    assert result.success is True
    assert sum(1 for wave, role, _ in sdk_calls if wave == "B" and role == "wave") == 1
    assert any(finding.code == "STACK-IMPORT-001" for finding in wave_b.findings)
    assert any(v["code"] == "STACK-IMPORT-001" for v in wave_b.stack_contract_violations)
    assert (tmp_path / "apps" / "api" / "src" / "orders" / "orders.service.ts").exists()


@pytest.mark.asyncio
async def test_low_confidence_contract_runs_in_advisory_mode(tmp_path: Path) -> None:
    async def _handler(root: Path, wave: str, prompt: str) -> None:
        if wave == "A":
            _write(root / "apps" / "api" / "src" / "users" / "user.entity.ts", "@Entity()\nexport class User {}\n")

    result, _, sdk_calls = await _run_backend_only(
        tmp_path,
        wave_handler=_handler,
        confidence="low",
    )

    wave_a = next(wave for wave in result.waves if wave.wave == "A")
    assert result.success is True
    assert wave_a.stack_contract_retry_count == 0
    assert any(finding.code == "STACK-FILE-001" for finding in wave_a.findings)
    assert sum(1 for wave, role, _ in sdk_calls if wave == "A" and role == "wave") == 1


@pytest.mark.asyncio
async def test_wave_a_contract_conflict_file_fails_loudly(tmp_path: Path) -> None:
    async def _handler(root: Path, wave: str, prompt: str) -> None:
        if wave == "A":
            _write(
                root / "WAVE_A_CONTRACT_CONFLICT.md",
                "Requirements demand TypeORM entities but the stack contract requires Prisma.\n",
            )

    result, _, _ = await _run_backend_only(tmp_path, wave_handler=_handler)

    wave_a = next(wave for wave in result.waves if wave.wave == "A")
    assert result.success is False
    assert result.error_wave == "A"
    assert "WAVE_A_CONTRACT_CONFLICT.md" in wave_a.error_message
    assert "stack contract requires Prisma" in wave_a.error_message
