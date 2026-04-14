"""Regression for files_created undercount when compile-fix sub-agent writes files.

Bug: post-wave checkpoint was sealed *before* the compile-fix sub-agent ran, so
files written by the compile-fix loop never appeared in `wave_result.files_created`
or `wave_result.files_modified`. Telemetry showed `files_created: 1` for Wave D
in build-d-rerun-20260414 despite ~30 files on disk.

Fix: re-snap the checkpoint after the compile-fix / DTO / frontend-hallucination
guard block, before extract_artifacts consumes the file list.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.wave_executor import execute_milestone_waves


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _milestone(template: str = "full_stack") -> SimpleNamespace:
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


@pytest.mark.asyncio
async def test_files_created_includes_compile_fix_writes(tmp_path: Path) -> None:
    """The compile-fix sub-agent's writes must appear in wave_result.files_created."""
    fix_call_count = {"n": 0}
    compile_calls_per_wave: dict[str, int] = {}

    async def _build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}-primary.ts",
                   f"export const {wave.lower()}_primary = true;\n")
        elif role == "compile_fix":
            fix_call_count["n"] += 1
            for i in range(10):
                _write(tmp_path / "src" / f"{wave.lower()}-fix-{i}.ts",
                       f"export const {wave.lower()}_fix_{i} = true;\n")
        return 1.0

    async def _run_compile_check(*, wave: str = "", **_: object) -> dict[str, object]:
        compile_calls_per_wave[wave] = compile_calls_per_wave.get(wave, 0) + 1
        if wave == "B" and compile_calls_per_wave[wave] == 1:
            return {
                "passed": False,
                "iterations": 1,
                "initial_error_count": 1,
                "errors": [{"file": f"src/{wave.lower()}-primary.ts", "line": 1,
                            "message": "broken"}],
            }
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    result = await execute_milestone_waves(
        milestone=_milestone(template="backend_only"),
        ir={"project_name": "Demo"},
        config=SimpleNamespace(),
        cwd=str(tmp_path),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=None,
        generate_contracts=None,
        run_scaffolding=None,
        save_wave_state=None,
    )

    wave_b = next(w for w in result.waves if w.wave == "B")
    assert fix_call_count["n"] == 1, "compile-fix sub-agent should have run once"

    expected_files = {"src/b-primary.ts"} | {f"src/b-fix-{i}.ts" for i in range(10)}
    actual_files = {f.replace("\\", "/") for f in wave_b.files_created}
    assert actual_files >= expected_files, (
        f"files_created missing compile-fix writes. "
        f"Expected ≥ {sorted(expected_files)}, got {sorted(actual_files)}"
    )


@pytest.mark.asyncio
async def test_files_created_does_not_include_pre_existing_files(tmp_path: Path) -> None:
    """Baseline files (created before the wave) must not appear in files_created."""
    _write(tmp_path / "src" / "preexisting.ts", "export const pre = true;\n")

    async def _build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}-primary.ts",
                   f"export const {wave.lower()} = true;\n")
        return 1.0

    async def _run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    result = await execute_milestone_waves(
        milestone=_milestone(template="backend_only"),
        ir={"project_name": "Demo"},
        config=SimpleNamespace(),
        cwd=str(tmp_path),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=None,
        generate_contracts=None,
        run_scaffolding=None,
        save_wave_state=None,
    )

    wave_a = next(w for w in result.waves if w.wave == "A")
    actual_files = {f.replace("\\", "/") for f in wave_a.files_created}
    assert "src/preexisting.ts" not in actual_files, (
        "baseline file leaked into files_created"
    )
