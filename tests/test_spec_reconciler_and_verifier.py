"""N-12 + N-13 (Phase B) tests: ScaffoldConfig, reconciler, verifier."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from agent_team_v15.scaffold_runner import (
    DEFAULT_SCAFFOLD_CONFIG,
    FileOwnership,
    OwnershipContract,
    ScaffoldConfig,
    load_ownership_contract,
)
from agent_team_v15.milestone_spec_reconciler import reconcile_milestone_spec
from agent_team_v15.scaffold_verifier import run_scaffold_verifier


# ---------------------------------------------------------------------------
# ScaffoldConfig dataclass
# ---------------------------------------------------------------------------


class TestScaffoldConfig:
    def test_defaults_match_canonical_m1_values(self) -> None:
        cfg = ScaffoldConfig()
        assert cfg.port == 4000
        assert cfg.prisma_path == "src/database"
        assert cfg.modules_path == "src/modules"
        assert cfg.api_prefix == "api"

    def test_instance_is_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            DEFAULT_SCAFFOLD_CONFIG.port = 5000  # type: ignore[misc]

    def test_custom_values_compose(self) -> None:
        cfg = ScaffoldConfig(port=5000, prisma_path="src/db")
        assert cfg.port == 5000
        assert cfg.prisma_path == "src/db"
        assert cfg.modules_path == "src/modules"  # default untouched


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------


def _write_requirements(tmp_path: Path, body: str) -> Path:
    req = tmp_path / "REQUIREMENTS.md"
    req.write_text(body, encoding="utf-8")
    return req


class TestReconciler:
    def test_no_conflict_when_sources_agree(self, tmp_path: Path) -> None:
        """REQUIREMENTS PORT=4000 + no PRD -> no conflicts, port=4000 from REQUIREMENTS."""
        req = _write_requirements(
            tmp_path,
            "# M1\nsome text\n\nPORT=4000\napps/api/src/database/prisma.service.ts\n",
        )
        contract = OwnershipContract(files=tuple())
        result = reconcile_milestone_spec(
            requirements_path=req,
            prd_path=None,
            stack_contract=None,
            ownership_contract=contract,
            milestone_id="milestone-1",
            output_dir=tmp_path,
        )
        assert not result.has_conflicts
        assert result.resolved_scaffold_config.port == 4000
        assert result.sources["port"] == "REQUIREMENTS.md"
        assert (tmp_path / "SPEC.md").is_file()
        assert (tmp_path / "resolved_manifest.json").is_file()
        assert not (tmp_path / "RECONCILIATION_CONFLICTS.md").exists()

    def test_explicit_conflict_between_requirements_and_prd(self, tmp_path: Path) -> None:
        """REQUIREMENTS PORT=4000 vs PRD PORT=5000 -> conflict recorded, REQUIREMENTS wins."""
        req = _write_requirements(tmp_path, "PORT=4000\n")
        prd = tmp_path / "PRD.md"
        prd.write_text("The service listens on PORT=5000\n", encoding="utf-8")
        contract = OwnershipContract(files=tuple())
        result = reconcile_milestone_spec(
            requirements_path=req,
            prd_path=prd,
            stack_contract=None,
            ownership_contract=contract,
            milestone_id="milestone-1",
            output_dir=tmp_path,
        )
        assert result.has_conflicts
        assert any(c.section == "port" for c in result.conflicts)
        assert result.resolved_scaffold_config.port == 4000
        assert result.recovery_type() == "reconciliation_arbitration_required"
        assert (tmp_path / "RECONCILIATION_CONFLICTS.md").is_file()

    def test_absent_prd_does_not_create_conflict(self, tmp_path: Path) -> None:
        """REQUIREMENTS PORT=4000 + PRD silent on PORT -> no conflict."""
        req = _write_requirements(tmp_path, "PORT=4000\n")
        prd = tmp_path / "PRD.md"
        prd.write_text("# PRD\nArbitrary PRD body, no port mentioned.\n", encoding="utf-8")
        contract = OwnershipContract(files=tuple())
        result = reconcile_milestone_spec(
            requirements_path=req,
            prd_path=prd,
            stack_contract=None,
            ownership_contract=contract,
        )
        assert not result.has_conflicts

    def test_fall_back_to_defaults_when_all_silent(self, tmp_path: Path) -> None:
        req = _write_requirements(tmp_path, "# silent spec\n")
        result = reconcile_milestone_spec(
            requirements_path=req,
            prd_path=None,
            stack_contract=None,
            ownership_contract=OwnershipContract(files=tuple()),
        )
        assert result.resolved_scaffold_config.port == DEFAULT_SCAFFOLD_CONFIG.port
        assert result.sources["port"] == "default"


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


def _minimal_scaffold(workspace: Path, *, port: int = 4000) -> None:
    (workspace / "apps" / "api" / "src" / "config").mkdir(parents=True, exist_ok=True)
    (workspace / "apps" / "api" / "src" / "main.ts").write_text(
        "import { NestFactory } from '@nestjs/core';\n"
        "import { AppModule } from './app.module';\n"
        "async function bootstrap(){\n"
        "  const app = await NestFactory.create(AppModule);\n"
        f"  const port = Number(process.env.PORT ?? {port});\n"
        "  await app.listen(port);\n"
        "}\n",
        encoding="utf-8",
    )
    (workspace / "apps" / "api" / "src" / "config" / "env.validation.ts").write_text(
        "import * as Joi from 'joi';\n"
        "export const envValidationSchema = Joi.object({\n"
        f"  PORT: Joi.number().default({port}),\n"
        "});\n",
        encoding="utf-8",
    )
    (workspace / ".env.example").write_text(f"PORT={port}\n", encoding="utf-8")
    (workspace / ".gitignore").write_text(
        "node_modules\ndist\n.next\n.turbo\n", encoding="utf-8"
    )
    (workspace / "package.json").write_text(
        json.dumps({"name": "app", "workspaces": ["apps/*", "packages/*"]}) + "\n",
        encoding="utf-8",
    )


class TestScaffoldVerifier:
    def test_pass_on_minimal_scaffold(self, tmp_path: Path) -> None:
        _minimal_scaffold(tmp_path, port=4000)
        contract = OwnershipContract(
            files=(
                FileOwnership(path="apps/api/src/main.ts", owner="scaffold", optional=False),
                FileOwnership(
                    path="apps/api/src/config/env.validation.ts",
                    owner="scaffold",
                    optional=False,
                ),
                FileOwnership(path=".env.example", owner="scaffold", optional=False),
                FileOwnership(path=".gitignore", owner="scaffold", optional=False),
                FileOwnership(path="package.json", owner="scaffold", optional=False),
            )
        )
        report = run_scaffold_verifier(tmp_path, contract, ScaffoldConfig(port=4000))
        assert report.verdict == "PASS", report.summary()

    def test_fail_on_missing_required_file(self, tmp_path: Path) -> None:
        _minimal_scaffold(tmp_path, port=4000)
        # Remove one required file
        (tmp_path / "apps" / "api" / "src" / "main.ts").unlink()
        contract = OwnershipContract(
            files=(
                FileOwnership(path="apps/api/src/main.ts", owner="scaffold", optional=False),
                FileOwnership(path=".env.example", owner="scaffold", optional=False),
                FileOwnership(path=".gitignore", owner="scaffold", optional=False),
                FileOwnership(path="package.json", owner="scaffold", optional=False),
            )
        )
        report = run_scaffold_verifier(tmp_path, contract, ScaffoldConfig(port=4000))
        assert report.verdict == "FAIL"
        assert any(
            str(p).endswith("main.ts") for p in report.missing
        ), f"main.ts missing from report: {[str(p) for p in report.missing]}"

    def test_fail_on_port_drift_between_files(self, tmp_path: Path) -> None:
        _minimal_scaffold(tmp_path, port=4000)
        # Introduce drift: rewrite main.ts with a different port.
        (tmp_path / "apps" / "api" / "src" / "main.ts").write_text(
            "import { NestFactory } from '@nestjs/core';\n"
            "import { AppModule } from './app.module';\n"
            "async function bootstrap(){\n"
            "  const app = await NestFactory.create(AppModule);\n"
            "  const port = Number(process.env.PORT ?? 3001);\n"
            "  await app.listen(port);\n"
            "}\n",
            encoding="utf-8",
        )
        contract = OwnershipContract(
            files=(
                FileOwnership(path="apps/api/src/main.ts", owner="scaffold", optional=False),
                FileOwnership(path=".env.example", owner="scaffold", optional=False),
            )
        )
        report = run_scaffold_verifier(tmp_path, contract, ScaffoldConfig(port=4000))
        assert report.verdict == "FAIL"
        assert any("PORT" in s for s in report.summary_lines)

    def test_warn_on_deprecated_path_emitted(self, tmp_path: Path) -> None:
        _minimal_scaffold(tmp_path, port=4000)
        # Simulate DRIFT-1 regression: old src/prisma/ still present.
        deprecated = tmp_path / "apps" / "api" / "src" / "prisma"
        deprecated.mkdir(parents=True)
        (deprecated / "prisma.service.ts").write_text("// legacy\n", encoding="utf-8")
        contract = OwnershipContract(
            files=(
                FileOwnership(path="apps/api/src/main.ts", owner="scaffold", optional=False),
                FileOwnership(path=".env.example", owner="scaffold", optional=False),
                FileOwnership(path=".gitignore", owner="scaffold", optional=False),
                FileOwnership(path="package.json", owner="scaffold", optional=False),
            )
        )
        report = run_scaffold_verifier(tmp_path, contract, ScaffoldConfig(port=4000))
        assert report.verdict == "WARN"
        assert report.deprecated_emitted


# ---------------------------------------------------------------------------
# Integration: real ownership contract parses + default ScaffoldConfig agrees
# ---------------------------------------------------------------------------


class TestReconcilerIntegration:
    def test_default_scaffold_config_port_matches_requirements_sample(self, tmp_path: Path) -> None:
        """Sanity: DEFAULT_SCAFFOLD_CONFIG.port == 4000 aligns with canonical M1 spec."""
        contract = load_ownership_contract()
        req = _write_requirements(tmp_path, "PORT=4000\n")
        result = reconcile_milestone_spec(
            requirements_path=req,
            prd_path=None,
            stack_contract=None,
            ownership_contract=contract,
        )
        assert result.resolved_scaffold_config.port == DEFAULT_SCAFFOLD_CONFIG.port
