from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_team_v15.stack_contract import (
    builtin_stack_contracts,
    derive_stack_contract,
    validate_wave_against_stack_contract,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _wave_output(*paths: str) -> SimpleNamespace:
    return SimpleNamespace(files_created=list(paths), files_modified=[])


def test_builtin_registry_contains_required_contracts() -> None:
    registry = builtin_stack_contracts()

    assert ("nestjs", "prisma") in registry
    assert ("nestjs", "typeorm") in registry
    assert ("nestjs", "drizzle") in registry
    assert ("express", "prisma") in registry
    assert ("fastify", "prisma") in registry
    assert ("django", "django-orm") in registry
    assert ("spring", "jpa") in registry
    assert ("aspnet", "ef-core") in registry


def test_derive_stack_contract_is_explicit_when_prd_names_framework_and_orm() -> None:
    contract = derive_stack_contract(
        "Build a NestJS backend with Prisma ORM and PostgreSQL.",
        "Merge-Surfaces: apps/api/src/app.module.ts, apps/web/src/app/layout.tsx",
        tech_stack=[],
        milestone_requirements="Backend lives in apps/api.",
    )

    assert contract.backend_framework == "nestjs"
    assert contract.orm == "prisma"
    assert contract.confidence == "explicit"


def test_derive_stack_contract_is_low_when_stack_is_only_inferred() -> None:
    tech_stack = [
        {"name": "NestJS", "category": "backend_framework"},
        {"name": "Prisma", "category": "orm"},
    ]

    contract = derive_stack_contract(
        "Build the platform.",
        "Milestone 1 foundation work.",
        tech_stack=tech_stack,
        milestone_requirements="Implement the service layer.",
    )

    assert contract.backend_framework == "nestjs"
    assert contract.orm == "prisma"
    assert contract.confidence == "low"


def test_validate_prisma_contract_flags_typeorm_entity_file(tmp_path: Path) -> None:
    registry = builtin_stack_contracts()
    contract = registry[("nestjs", "prisma")]
    contract.monorepo_layout = "apps"
    contract.backend_path_prefix = "apps/api/"
    contract.frontend_path_prefix = "apps/web/"

    _write(tmp_path / "apps" / "api" / "src" / "users" / "user.entity.ts", "@Entity()\nexport class User {}\n")
    _write(
        tmp_path / "apps" / "api" / "src" / "prisma" / "prisma.service.ts",
        "import { PrismaClient } from '@prisma/client';\nexport const prisma = new PrismaClient();\n",
    )
    _write(tmp_path / "apps" / "api" / "prisma" / "schema.prisma", "generator client { provider = \"prisma-client-js\" }\n")

    violations = validate_wave_against_stack_contract(
        _wave_output(
            "apps/api/src/users/user.entity.ts",
            "apps/api/src/prisma/prisma.service.ts",
            "apps/api/prisma/schema.prisma",
        ),
        contract,
        tmp_path,
    )

    assert any(v.code == "STACK-FILE-001" for v in violations)


def test_validate_prisma_contract_flags_forbidden_import(tmp_path: Path) -> None:
    registry = builtin_stack_contracts()
    contract = registry[("nestjs", "prisma")]
    contract.monorepo_layout = "apps"
    contract.backend_path_prefix = "apps/api/"
    contract.frontend_path_prefix = "apps/web/"

    _write(
        tmp_path / "apps" / "api" / "src" / "orders" / "orders.module.ts",
        "import { TypeOrmModule } from '@nestjs/typeorm';\n",
    )
    _write(tmp_path / "apps" / "api" / "prisma" / "schema.prisma", "generator client { provider = \"prisma-client-js\" }\n")
    _write(
        tmp_path / "apps" / "api" / "src" / "prisma" / "prisma.service.ts",
        "import { PrismaClient } from '@prisma/client';\n",
    )

    violations = validate_wave_against_stack_contract(
        _wave_output(
            "apps/api/src/orders/orders.module.ts",
            "apps/api/prisma/schema.prisma",
            "apps/api/src/prisma/prisma.service.ts",
        ),
        contract,
        tmp_path,
    )

    assert any(v.code == "STACK-IMPORT-001" and v.actual == "@nestjs/typeorm" for v in violations)


def test_validate_prisma_contract_flags_missing_required_schema(tmp_path: Path) -> None:
    registry = builtin_stack_contracts()
    contract = registry[("nestjs", "prisma")]
    contract.monorepo_layout = "apps"
    contract.backend_path_prefix = "apps/api/"
    contract.frontend_path_prefix = "apps/web/"

    _write(
        tmp_path / "apps" / "api" / "src" / "orders" / "orders.module.ts",
        "import { PrismaClient } from '@prisma/client';\n",
    )

    violations = validate_wave_against_stack_contract(
        _wave_output("apps/api/src/orders/orders.module.ts"),
        contract,
        tmp_path,
    )

    assert any(v.code == "STACK-FILE-002" for v in violations)


def test_validate_typeorm_contract_flags_prisma_schema_as_forbidden(tmp_path: Path) -> None:
    registry = builtin_stack_contracts()
    contract = registry[("nestjs", "typeorm")]
    contract.monorepo_layout = "apps"
    contract.backend_path_prefix = "apps/api/"
    contract.frontend_path_prefix = "apps/web/"

    _write(tmp_path / "apps" / "api" / "prisma" / "schema.prisma", "generator client { provider = \"prisma-client-js\" }\n")
    _write(
        tmp_path / "apps" / "api" / "src" / "users" / "user.entity.ts",
        "import { Entity } from 'typeorm';\n@Entity()\nexport class User {}\n",
    )

    violations = validate_wave_against_stack_contract(
        _wave_output("apps/api/prisma/schema.prisma", "apps/api/src/users/user.entity.ts"),
        contract,
        tmp_path,
    )

    assert any(v.code == "STACK-FILE-001" and v.actual == "apps/api/prisma/schema.prisma" for v in violations)


def test_validate_typeorm_contract_requires_entity_files(tmp_path: Path) -> None:
    contract = builtin_stack_contracts()[("nestjs", "typeorm")]
    contract.monorepo_layout = "apps"
    contract.backend_path_prefix = "apps/api/"
    contract.frontend_path_prefix = "apps/web/"

    _write(
        tmp_path / "apps" / "api" / "src" / "bootstrap.ts",
        "import { TypeOrmModule } from '@nestjs/typeorm';\n",
    )

    violations = validate_wave_against_stack_contract(
        _wave_output("apps/api/src/bootstrap.ts"),
        contract,
        tmp_path,
    )

    assert any(v.code == "STACK-FILE-002" for v in violations)


def test_express_drizzle_contract_accepts_clean_wave_output(tmp_path: Path) -> None:
    contract = derive_stack_contract(
        "Build an Express API using Drizzle ORM and Postgres.",
        "Single repo layout.",
        tech_stack=[],
        milestone_requirements="Create the database schema and migrations.",
    )

    _write(
        tmp_path / "src" / "db" / "schema.ts",
        "import { pgTable } from 'drizzle-orm/pg-core';\nexport const users = pgTable('users', {});\n",
    )
    _write(tmp_path / "drizzle" / "0001_init.sql", "-- drizzle migration\n")

    violations = validate_wave_against_stack_contract(
        _wave_output("src/db/schema.ts", "drizzle/0001_init.sql"),
        contract,
        tmp_path,
    )

    assert contract.backend_framework == "express"
    assert contract.orm == "drizzle"
    assert contract.confidence == "explicit"
    assert violations == []


def test_django_contract_accepts_clean_wave_output(tmp_path: Path) -> None:
    contract = derive_stack_contract(
        "Build a Django backend with the Django ORM.",
        "Single repo layout.",
        tech_stack=[],
        milestone_requirements="Create models for the milestone entities.",
    )

    _write(tmp_path / "manage.py", "print('manage')\n")
    _write(
        tmp_path / "orders" / "models.py",
        "from django.db import models\nclass Order(models.Model):\n    pass\n",
    )

    violations = validate_wave_against_stack_contract(
        _wave_output("manage.py", "orders/models.py"),
        contract,
        tmp_path,
    )

    assert contract.backend_framework == "django"
    assert contract.orm == "django-orm"
    assert violations == []
