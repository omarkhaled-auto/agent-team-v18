from __future__ import annotations

import json
from pathlib import Path

from agent_team_v15.scaffold_runner import (
    run_scaffolding,
    _scaffold_i18n,
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
            "apps/api/package.json",
            "apps/api/src/main.ts",
            "apps/api/src/config/env.validation.ts",
            "apps/api/src/prisma/prisma.service.ts",
            "apps/api/src/prisma/prisma.module.ts",
            "apps/api/src/common/pipes/validation.pipe.ts",
            "apps/web/package.json",
            "apps/web/vitest.config.ts",
            "apps/web/tailwind.config.ts",
            "apps/web/src/styles/globals.css",
            "apps/web/eslint.config.js",
            "apps/web/messages/en/f-001.json",
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
