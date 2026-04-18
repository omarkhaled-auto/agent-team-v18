"""Regression: M1 NestJS scaffolder must emit the 3 files smoke #5 caught
as MISSING — ``apps/api/tsconfig.json``, ``apps/api/.env.example``,
``apps/api/src/app.module.ts``.

The scaffold verifier (firing at the scaffolder boundary post PR #29)
reported these three files MISSING in build-final-smoke-20260418-181933,
even though every prior structural fix had landed cleanly. The
ownership contract (``docs/SCAFFOLD_OWNERSHIP.md``) declared all three
as ``owner: scaffold, optional: false`` — the scaffolder's templates
tuple just didn't include them.

Tests:
1. Each of the 3 files appears in the scaffolder output for an
   M1-shaped milestone with no entities.
2. The contents are non-empty and structurally sensible (key tokens
   present — extends base, ConfigModule, PORT line).
3. Scaffolder remains idempotent on re-run for these 3 files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.scaffold_runner import (
    DEFAULT_SCAFFOLD_CONFIG,
    run_scaffolding,
)


_M1_API_FOUNDATION_FILES = (
    "apps/api/tsconfig.json",
    "apps/api/.env.example",
    "apps/api/src/app.module.ts",
)


def _write_ir(tmp_path: Path, payload: dict) -> Path:
    ir_path = tmp_path / "product.ir.json"
    ir_path.write_text(json.dumps(payload), encoding="utf-8")
    return ir_path


def _m1_no_entities_ir(tmp_path: Path) -> Path:
    return _write_ir(
        tmp_path,
        {
            "stack_target": {"backend": "NestJS", "frontend": "Next.js"},
            "entities": [],
            "i18n": {"locales": ["en"]},
        },
    )


# ---------------------------------------------------------------------------
# All three files emitted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("expected_path", _M1_API_FOUNDATION_FILES)
def test_m1_api_foundation_file_emitted(tmp_path: Path, expected_path: str) -> None:
    ir_path = _m1_no_entities_ir(tmp_path)
    created = set(run_scaffolding(ir_path, tmp_path, "milestone-1", ["F-001"]))
    assert expected_path in created, (
        f"Scaffolder did not emit {expected_path!r} for an M1 NestJS "
        f"milestone — the smoke-#5 verifier gap is back. Created files: "
        f"{sorted(created)}"
    )
    assert (tmp_path / expected_path).is_file()


# ---------------------------------------------------------------------------
# Content sanity — keys the verifier cannot check but a real build needs
# ---------------------------------------------------------------------------


def test_api_tsconfig_extends_root_base(tmp_path: Path) -> None:
    """``apps/api/tsconfig.json`` must extend ``../../tsconfig.base.json``
    so workspace path aliases (``@taskflow/shared``, ``@taskflow/api-client``)
    resolve. Without the extends, NestJS imports across packages break."""
    ir_path = _m1_no_entities_ir(tmp_path)
    run_scaffolding(ir_path, tmp_path, "milestone-1", ["F-001"])
    text = (tmp_path / "apps/api/tsconfig.json").read_text(encoding="utf-8")
    assert '"extends": "../../tsconfig.base.json"' in text
    # NestJS DI requires both decorator flags.
    assert '"experimentalDecorators": true' in text
    assert '"emitDecoratorMetadata": true' in text


def test_api_env_example_carries_port_and_database_url(tmp_path: Path) -> None:
    """``apps/api/.env.example`` must declare PORT (matching ScaffoldConfig)
    and DATABASE_URL — both required by the env validation schema."""
    ir_path = _m1_no_entities_ir(tmp_path)
    run_scaffolding(ir_path, tmp_path, "milestone-1", ["F-001"])
    text = (tmp_path / "apps/api/.env.example").read_text(encoding="utf-8")
    assert f"PORT={DEFAULT_SCAFFOLD_CONFIG.port}" in text
    assert "DATABASE_URL=" in text
    assert "JWT_SECRET=" in text


def test_app_module_stub_imports_prisma_and_config(tmp_path: Path) -> None:
    """``app.module.ts`` is the M1 stub — ``main.ts`` imports it via
    ``./app.module``, so the file must define an exported ``AppModule``
    class wired to ConfigModule + PrismaModule (the foundation pieces
    the scaffolder also emits). Wave B extends this in later milestones."""
    ir_path = _m1_no_entities_ir(tmp_path)
    run_scaffolding(ir_path, tmp_path, "milestone-1", ["F-001"])
    text = (tmp_path / "apps/api/src/app.module.ts").read_text(encoding="utf-8")
    assert "export class AppModule" in text
    assert "ConfigModule" in text
    assert "PrismaModule" in text
    assert "envValidationSchema" in text
    # Wave-B-extends marker comment.
    assert "Wave B" in text


# ---------------------------------------------------------------------------
# Idempotence — re-running the scaffolder must not re-emit
# ---------------------------------------------------------------------------


def test_m1_api_foundation_idempotent_on_rerun(tmp_path: Path) -> None:
    """Second invocation must skip the 3 new files (already present)."""
    ir_path = _m1_no_entities_ir(tmp_path)

    first = set(run_scaffolding(ir_path, tmp_path, "milestone-1", ["F-001"]))
    second = set(run_scaffolding(ir_path, tmp_path, "milestone-1", ["F-001"]))

    for expected in _M1_API_FOUNDATION_FILES:
        assert expected in first
        # `_write_if_missing` returns None when the file already exists,
        # so the re-run set should NOT re-list it.
        assert expected not in second, (
            f"{expected} re-emitted on second run — scaffolder is not "
            f"idempotent for the new templates."
        )
