from __future__ import annotations

import json
from pathlib import Path

from agent_team_v15.scaffold_runner import (
    run_scaffolding,
    _scaffold_i18n,
    _scaffold_packages_shared,
    _to_kebab_case,
    _to_pascal_case,
)


def _write_ir(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "product.ir.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestScaffoldHelpers:
    def test_to_kebab_case(self) -> None:
        assert _to_kebab_case("SyncedSaleOrder") == "synced-sale-order"

    def test_to_pascal_case(self) -> None:
        assert _to_pascal_case("quotation-detail") == "QuotationDetail"

    def test_scaffold_i18n_creates_namespace_files(self, tmp_path: Path) -> None:
        created = _scaffold_i18n(tmp_path, ["F-003"], {"locales": ["en", "ar"]})

        assert sorted(created) == [
            "apps/web/messages/ar/f-003.json",
            "apps/web/messages/en/f-003.json",
        ]


class TestRunScaffolding:
    def test_run_scaffolding_with_no_entities_creates_support_files(self, tmp_path: Path) -> None:
        ir_path = _write_ir(
            tmp_path,
            {
                "stack_target": {"backend": "NestJS", "frontend": "Next.js"},
                "entities": [],
                "i18n": {"locales": ["en"]},
            },
        )

        created = run_scaffolding(ir_path, tmp_path, "milestone-1", ["F-001"])

        # M1 foundation emission (A-01/02/03/05/06/07/08 + D-18) + i18n
        # namespace file + generate-openapi support script. See scaffold_runner
        # `_scaffold_m1_foundation` for the full list.
        expected = {
            ".env.example",
            ".gitignore",
            "docker-compose.yml",
            "package.json",
            "pnpm-workspace.yaml",
            "tsconfig.base.json",
            "apps/api/package.json",
            "apps/api/src/main.ts",
            "apps/api/src/config/env.validation.ts",
            "apps/api/src/database/prisma.service.ts",
            "apps/api/src/database/prisma.module.ts",
            "apps/api/prisma/schema.prisma",
            "apps/api/prisma/migrations/20260101000000_init/migration.sql",
            "apps/api/prisma/migrations/migration_lock.toml",
            "apps/api/src/common/pipes/validation.pipe.ts",
            "apps/web/package.json",
            "apps/web/vitest.config.ts",
            "apps/web/tailwind.config.ts",
            "apps/web/src/styles/globals.css",
            "apps/web/eslint.config.js",
            # N-06: DRIFT-6 closure — 10 new apps/web canonical emissions.
            "apps/web/next.config.mjs",
            "apps/web/tsconfig.json",
            "apps/web/postcss.config.mjs",
            "apps/web/openapi-ts.config.ts",
            "apps/web/.env.example",
            "apps/web/Dockerfile",
            "apps/web/src/app/layout.tsx",
            "apps/web/src/app/page.tsx",
            "apps/web/src/middleware.ts",
            "apps/web/src/test/setup.ts",
            "apps/web/messages/en/f-001.json",
            "packages/shared/package.json",
            "packages/shared/tsconfig.json",
            "packages/shared/src/enums.ts",
            "packages/shared/src/error-codes.ts",
            "packages/shared/src/pagination.ts",
            "packages/shared/src/index.ts",
            "scripts/generate-openapi.ts",
        }
        assert set(created) == expected
        assert (tmp_path / "scripts" / "generate-openapi.ts").is_file()

    def test_run_scaffolding_is_idempotent(self, tmp_path: Path) -> None:
        ir_path = _write_ir(
            tmp_path,
            {
                "stack_target": {"frontend": "Next.js"},
                "entities": [
                    {"name": "Quotation", "owner_feature": "F-003"},
                ],
                "i18n": {"locales": ["en", "ar"]},
            },
        )

        first = run_scaffolding(ir_path, tmp_path, "milestone-3", ["F-003"])
        second = run_scaffolding(ir_path, tmp_path, "milestone-3", ["F-003"])

        assert "apps/web/src/app/[locale]/(protected)/quotation/page.tsx" in first
        assert second == []

    def test_run_scaffolding_module_is_callable_standalone(self, tmp_path: Path) -> None:
        ir_path = _write_ir(
            tmp_path,
            {
                "stack_target": {"backend": "NestJS"},
                "entities": [
                    {"name": "Invoice", "owner_feature": "F-005"},
                ],
                "i18n": {"locales": []},
            },
        )

        created = run_scaffolding(ir_path, tmp_path, "milestone-5", ["F-005"], stack_target="NestJS")

        assert any(path.endswith("invoice.module.ts") for path in created)


class TestScaffoldPackagesShared:
    """N-03: `packages/shared/*` baseline must match M1 REQUIREMENTS verbatim."""

    def test_emits_all_six_files(self, tmp_path: Path) -> None:
        created = _scaffold_packages_shared(tmp_path)
        assert sorted(created) == [
            "packages/shared/package.json",
            "packages/shared/src/enums.ts",
            "packages/shared/src/error-codes.ts",
            "packages/shared/src/index.ts",
            "packages/shared/src/pagination.ts",
            "packages/shared/tsconfig.json",
        ]
        for rel in created:
            assert (tmp_path / rel).is_file()

    def test_enums_match_requirements_verbatim(self, tmp_path: Path) -> None:
        _scaffold_packages_shared(tmp_path)
        enums = (tmp_path / "packages" / "shared" / "src" / "enums.ts").read_text(encoding="utf-8")
        # Four enums, exact identifiers + values per REQUIREMENTS 340-343.
        assert "export enum UserRole { ADMIN = 'ADMIN', MEMBER = 'MEMBER' }" in enums
        assert "export enum ProjectStatus { ACTIVE = 'ACTIVE', ARCHIVED = 'ARCHIVED' }" in enums
        assert "TODO = 'TODO'" in enums and "IN_PROGRESS = 'IN_PROGRESS'" in enums
        assert "IN_REVIEW = 'IN_REVIEW'" in enums and "DONE = 'DONE'" in enums
        assert "LOW = 'LOW'" in enums and "URGENT = 'URGENT'" in enums

    def test_error_codes_match_requirements_verbatim(self, tmp_path: Path) -> None:
        _scaffold_packages_shared(tmp_path)
        codes = (tmp_path / "packages" / "shared" / "src" / "error-codes.ts").read_text(encoding="utf-8")
        expected_keys = [
            "VALIDATION_ERROR", "UNAUTHORIZED", "FORBIDDEN", "NOT_FOUND",
            "CONFLICT", "INTERNAL_ERROR", "PROJECT_NOT_FOUND", "PROJECT_FORBIDDEN",
            "TASK_NOT_FOUND", "TASK_INVALID_TRANSITION", "TASK_TRANSITION_FORBIDDEN",
            "COMMENT_CONTENT_REQUIRED", "USER_NOT_FOUND", "EMAIL_IN_USE",
            "INVALID_CREDENTIALS", "UNAUTHENTICATED", "CANNOT_DELETE_SELF",
        ]
        for key in expected_keys:
            assert f"{key}: '{key}'" in codes, f"missing code {key}"
        assert codes.rstrip().endswith("} as const;")

    def test_pagination_types_match_requirements_verbatim(self, tmp_path: Path) -> None:
        _scaffold_packages_shared(tmp_path)
        pag = (tmp_path / "packages" / "shared" / "src" / "pagination.ts").read_text(encoding="utf-8")
        assert "export interface PaginationMeta { total: number; page: number; limit: number; }" in pag
        assert "export class PaginatedResult<T>" in pag
        assert "public items: T[]" in pag and "public meta: PaginationMeta" in pag

    def test_package_json_declares_taskflow_shared(self, tmp_path: Path) -> None:
        _scaffold_packages_shared(tmp_path)
        raw = (tmp_path / "packages" / "shared" / "package.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["name"] == "@taskflow/shared"
        assert data["private"] is True
        assert data["main"].endswith("src/index.ts")

    def test_tsconfig_is_composite_project(self, tmp_path: Path) -> None:
        _scaffold_packages_shared(tmp_path)
        raw = (tmp_path / "packages" / "shared" / "tsconfig.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["extends"] == "../../tsconfig.base.json"
        assert data["compilerOptions"]["composite"] is True
        assert data["compilerOptions"]["declaration"] is True
        assert data["compilerOptions"]["outDir"] == "./dist"
        assert data["compilerOptions"]["rootDir"] == "./src"

    def test_index_barrel_reexports_all_three(self, tmp_path: Path) -> None:
        _scaffold_packages_shared(tmp_path)
        idx = (tmp_path / "packages" / "shared" / "src" / "index.ts").read_text(encoding="utf-8")
        assert "export * from './enums';" in idx
        assert "export * from './error-codes';" in idx
        assert "export * from './pagination';" in idx

    def test_idempotent(self, tmp_path: Path) -> None:
        first = _scaffold_packages_shared(tmp_path)
        second = _scaffold_packages_shared(tmp_path)
        assert len(first) == 6
        assert second == []
