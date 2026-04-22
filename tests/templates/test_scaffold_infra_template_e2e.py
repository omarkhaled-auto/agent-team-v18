"""Issue #14 hotfix regression: scaffold_generate → template drop end-to-end.

The original Issue #14 PR wired ``_scaffold_infra_template`` but gated it on
``load_stack_contract`` reading an on-disk ``STACK_CONTRACT.json``. At scaffold
time that file is a fresh empty contract (full stack detection runs later in
the pipeline), so the gate always returned False and the template was silently
skipped. This test exercises the full ``scaffold_generate`` entrypoint with a
populated pnpm/nestjs/nextjs stack string and asserts the template files
actually land on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.scaffold_runner import run_scaffolding
from agent_team_v15.stack_contract import load_stack_contract


@pytest.fixture()
def minimal_ir(tmp_path: Path) -> Path:
    ir_path = tmp_path / "PRODUCT_IR.json"
    ir_path.write_text(
        json.dumps(
            {
                "project": {"name": "taskflow-mini"},
                "entities": [
                    {
                        "name": "Task",
                        "fields": [
                            {"name": "id", "type": "uuid"},
                            {"name": "title", "type": "string"},
                        ],
                        "milestones": ["milestone-1"],
                    }
                ],
                "milestones": [{"id": "milestone-1", "features": []}],
            }
        ),
        encoding="utf-8",
    )
    return ir_path


def test_scaffold_drops_infra_template_for_pnpm_nestjs_nextjs(
    tmp_path: Path, minimal_ir: Path
) -> None:
    """Passing a pnpm+nestjs+nextjs stack string must drop the template files."""
    run_scaffolding(
        ir_path=minimal_ir,
        project_root=tmp_path,
        milestone_id="milestone-1",
        milestone_features=[],
        stack_target="nestjs+nextjs+postgres+pnpm",
    )

    # Directive-8 writeback: the STACK_CONTRACT.json must now carry the
    # detection signals + an infrastructure_template payload so wave_executor
    # can inject the <infrastructure_contract> block at runtime.
    stack = load_stack_contract(tmp_path)
    assert stack is not None, "scaffold must have written a StackContract"
    assert stack.backend_framework == "nestjs"
    assert stack.frontend_framework == "nextjs"
    assert stack.package_manager == "pnpm"
    assert stack.infrastructure_template, (
        "template drop must persist infrastructure_template onto the contract "
        "so wave_executor's runtime plumbing can inject <infrastructure_contract>"
    )
    assert stack.infrastructure_template.get("name") == "pnpm_monorepo"

    # Template files must exist on disk.
    assert (tmp_path / "apps" / "api" / "Dockerfile").is_file(), (
        "apps/api/Dockerfile must be dropped by the template hook"
    )
    assert (tmp_path / ".dockerignore").is_file(), (
        ".dockerignore must be dropped by the template hook"
    )


def test_scaffold_skips_template_when_package_manager_is_not_pnpm(
    tmp_path: Path, minimal_ir: Path
) -> None:
    """npm stacks skip the template (parked for a future npm template)."""
    run_scaffolding(
        ir_path=minimal_ir,
        project_root=tmp_path,
        milestone_id="milestone-1",
        milestone_features=[],
        stack_target="nestjs+nextjs+postgres+npm",
    )

    # api Dockerfile is Codex-authored for non-pnpm stacks (no template for them yet).
    assert not (tmp_path / "apps" / "api" / "Dockerfile").is_file()
    # .dockerignore is template-only; absent when template skipped.
    assert not (tmp_path / ".dockerignore").is_file()


def test_scaffold_skips_template_when_stack_lacks_both_frameworks(
    tmp_path: Path, minimal_ir: Path
) -> None:
    """Non-nestjs-nextjs stacks fall through to legacy scaffold path."""
    run_scaffolding(
        ir_path=minimal_ir,
        project_root=tmp_path,
        milestone_id="milestone-1",
        milestone_features=[],
        stack_target="python-fastapi+postgres",
    )

    assert not (tmp_path / "apps" / "api" / "Dockerfile").is_file()
    assert not (tmp_path / ".dockerignore").is_file()


@pytest.fixture()
def r1b1_style_ir(tmp_path: Path) -> Path:
    """IR matching R1B1 smoke M1 shape: stack_target is a dict with only
    backend / frontend / db / mobile, no package_manager token.
    """
    ir_path = tmp_path / "PRODUCT_IR.json"
    ir_path.write_text(
        json.dumps(
            {
                "project": {"name": "taskflow-mini"},
                "stack_target": {
                    "backend": "NestJS",
                    "frontend": "Next.js",
                    "db": "PostgreSQL",
                    "mobile": None,
                },
                "entities": [
                    {
                        "name": "Task",
                        "fields": [
                            {"name": "id", "type": "uuid"},
                            {"name": "title", "type": "string"},
                        ],
                        "milestones": ["milestone-1"],
                    }
                ],
                "milestones": [{"id": "milestone-1", "features": []}],
            }
        ),
        encoding="utf-8",
    )
    return ir_path


def test_scaffold_drops_template_when_ir_omits_package_manager_but_stack_is_nestjs_nextjs(
    tmp_path: Path, r1b1_style_ir: Path
) -> None:
    """Regression for R1B1 smoke M1 (2026-04-22).

    Pre-fix behaviour: the IR carries backend=NestJS, frontend=Next.js,
    db=PostgreSQL, but NO ``pnpm`` token anywhere in the stack_target dict.
    ``_detect_stack_from_ir`` builds a string from backend/frontend/mobile,
    so ``has_pnpm = False``. The Issue #14 hotfix then wrote
    ``package_manager=""`` onto STACK_CONTRACT.json, ``stack_matches_template``
    returned False, and the curated infrastructure template (``.dockerignore``,
    ``apps/api/Dockerfile``) was silently skipped — Codex later authored a
    minimal ``.dockerignore`` from scratch.

    Post-fix: the scaffold commits unconditionally to pnpm for nestjs+nextjs
    (``_scaffold_root_files`` emits ``pnpm-workspace.yaml``), so the
    prepopulate step must default ``package_manager="pnpm"`` when the IR
    omits the token, and the template must actually drop.
    """
    # stack_target omitted → exercise the production ``_detect_stack_from_ir``
    # path that R1B1 hit.
    run_scaffolding(
        ir_path=r1b1_style_ir,
        project_root=tmp_path,
        milestone_id="milestone-1",
        milestone_features=[],
    )

    # Template files must land on disk.
    assert (tmp_path / ".dockerignore").is_file(), (
        "R1B1 regression: .dockerignore must drop when IR omits pnpm token "
        "but scaffold is committing to a pnpm+nestjs+nextjs layout"
    )
    assert (tmp_path / "apps" / "api" / "Dockerfile").is_file(), (
        "R1B1 regression: apps/api/Dockerfile must drop from the template"
    )

    # Content check: the dropped ``.dockerignore`` must be the curated 907-byte
    # template (identifiable by its header comment), NOT a Codex-authored stub.
    dockerignore_text = (tmp_path / ".dockerignore").read_text(encoding="utf-8")
    assert "Curated .dockerignore for pnpm-workspace monorepo" in dockerignore_text, (
        f".dockerignore must match the curated template header, got: "
        f"{dockerignore_text[:120]!r}"
    )

    # Stack contract must reflect the resolved pnpm decision + infrastructure
    # template payload (wrap_prompt_for_codex reads this at Wave B dispatch).
    stack = load_stack_contract(tmp_path)
    assert stack is not None
    assert stack.backend_framework == "nestjs"
    assert stack.frontend_framework == "nextjs"
    assert stack.package_manager == "pnpm", (
        "Prepopulate must default package_manager to pnpm when IR is silent, "
        "because scaffold unconditionally emits pnpm-workspace.yaml"
    )
    assert stack.infrastructure_template.get("name") == "pnpm_monorepo"
