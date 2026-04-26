from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_team_v15.stack_contract import (
    StackContract,
    builtin_stack_contracts,
    derive_stack_contract,
    extract_stack_contract_port_literals,
    format_stack_contract_for_prompt,
    is_resolved_stack_contract,
    load_stack_contract,
    validate_wave_against_stack_contract,
    write_stack_contract,
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


def test_blank_and_ports_only_stack_contracts_are_unresolved() -> None:
    assert is_resolved_stack_contract(StackContract()) is False
    assert is_resolved_stack_contract(
        {
            "backend_framework": "",
            "frontend_framework": "",
            "orm": "",
            "database": "",
            "package_manager": "",
            "monorepo_layout": "",
            "backend_path_prefix": "",
            "frontend_path_prefix": "",
            "required_file_patterns": [],
            "required_imports": [],
            "forbidden_file_patterns": [],
            "forbidden_imports": [],
            "forbidden_decorators": [],
            "ports": [3000, 3080, 5432],
            "confidence": "high",
        }
    ) is False


def test_smoke_style_inputs_derive_explicit_m1_stack_contract() -> None:
    requirements = """
# Milestone 1 - Platform Foundation
- Stack-Target: nestjs+nextjs

## In-Scope Deliverables
- Monorepo layout: `apps/api` (NestJS), `apps/web` (Next.js App Router),
  `packages/api-client` (generated TypeScript client), `prisma/`.
- `package.json` and `pnpm-workspace.yaml` at root.
- `prisma/schema.prisma` pointing at PostgreSQL.

## Merge Surfaces
`package.json`, `pnpm-workspace.yaml`, `apps/api/src/app.module.ts`,
`apps/api/src/main.ts`, `apps/web/next.config.mjs`,
`apps/web/src/app/layout.tsx`, `locales/en/common.json`,
`locales/ar/common.json`, `prisma/schema.prisma`, `docker-compose.yml`,
`.env.example`.
"""
    contract = derive_stack_contract(
        prd_text="Build a full-stack platform.",
        master_plan_text="Milestone 1 platform foundation for NestJS and Next.js.",
        tech_stack=[],
        milestone_requirements=requirements,
    )

    assert contract.backend_framework == "nestjs"
    assert contract.frontend_framework == "nextjs"
    assert contract.orm == "prisma"
    assert contract.database == "postgresql"
    assert contract.package_manager == "pnpm"
    assert contract.monorepo_layout == "apps"
    assert contract.backend_path_prefix == "apps/api/"
    assert contract.frontend_path_prefix == "apps/web/"
    assert contract.confidence == "explicit"
    assert is_resolved_stack_contract(contract) is True


def test_stack_contract_prompt_does_not_emit_literal_none_must_rules() -> None:
    prompt = format_stack_contract_for_prompt(StackContract(backend_framework="nestjs"))

    assert "['(none)']" not in prompt
    assert "Create at least one file matching: ['(none)']" not in prompt
    assert "Use at least one import from: ['(none)']" not in prompt
    assert "Required file patterns: none declared" in prompt
    assert "Required imports: none declared" in prompt


def test_pnpm_slash_npm_workspace_and_db_port_do_not_become_api_port() -> None:
    requirements = """
# Milestone 1: Platform Foundation
- Stack-Target: nestjs+nextjs

## Deliverables
- pnpm/npm workspace with `apps/api`, `apps/web`, `packages/api-client` (generated), `prisma/`, `locales/`.
- `docker-compose.yml` defining postgres (port 5432 mapped), api, web services.
- `prisma/schema.prisma` pointing at PostgreSQL.
"""

    contract = derive_stack_contract(
        prd_text="Build a task management app.",
        master_plan_text="Platform foundation for NestJS and Next.js.",
        tech_stack=[],
        milestone_requirements=requirements,
    )
    ports = extract_stack_contract_port_literals(contract)

    assert contract.package_manager == "pnpm"
    assert contract.backend_framework == "nestjs"
    assert contract.frontend_framework == "nextjs"
    assert contract.orm == "prisma"
    assert contract.database == "postgresql"
    assert contract.api_port is None
    assert contract.port is None
    assert contract.ports == [5432]
    assert ports == {"ports": [5432]}


def test_pnpm_script_command_beats_parenthetical_npm_run() -> None:
    requirements = """
# Milestone 1: Platform Foundation
- Stack-Target: nestjs+nextjs

## Generated API Client Pipeline
- Script `pnpm generate:client` (or `npm run`) runs the NestJS app in schema-only mode.
- `pnpm generate:client` produces `apps/web/src/api/generated/` with no compile errors.
"""

    contract = derive_stack_contract(
        prd_text="TaskFlow stack: NestJS + Next.js + PostgreSQL + Prisma ORM.",
        master_plan_text="Scaffold a monorepo with apps/api and apps/web.",
        tech_stack=[],
        milestone_requirements=requirements,
    )

    assert contract.package_manager == "pnpm"


def test_api_validation_limits_and_reporter_words_do_not_become_ports() -> None:
    requirements = """
# Milestone 1: Platform Foundation
- Stack-Target: nestjs+nextjs

## Generated API Client Pipeline
- Script `pnpm generate:client` (or `npm run`) runs the NestJS app in schema-only mode.

# Milestone 4: Tasks Core
- `description` string, optional, **<= 2000** chars
- `reporter_id` FK -> `User.id`, required
- `POST /api/projects/:projectId/tasks` sets `reporter_id = req.user.id`.
- **AC-TSK-001** - `POST /api/projects/:projectId/tasks` creates a task. Rejects title > 200 or description > 2000 with translated validation errors.
"""

    contract = derive_stack_contract(
        prd_text="TaskFlow stack: NestJS + Next.js + PostgreSQL + Prisma ORM.",
        master_plan_text="Scaffold a monorepo with apps/api and apps/web.",
        tech_stack=[],
        milestone_requirements=requirements,
    )
    ports = extract_stack_contract_port_literals(contract)

    assert contract.package_manager == "pnpm"
    assert contract.port is None
    assert contract.api_port is None
    assert contract.web_port is None
    assert 2000 not in contract.ports
    assert ports == {}


def test_nest_next_apps_defaults_to_pnpm_and_reads_service_shorthand_ports() -> None:
    requirements = """
# Milestone 1: Platform Foundation
- Stack-Target: nestjs+nextjs

## Deliverables
- Running `npm run dev` starts Postgres (via docker-compose), NestJS on
  `:3000/api`, Next.js on `:3080`.
- `docker-compose.yml` with a PostgreSQL 16 service on host port 5432.
- `npm run api:openapi` produces a valid OpenAPI 3 JSON.
"""

    contract = derive_stack_contract(
        prd_text="TaskFlow stack: NestJS + Next.js App Router + PostgreSQL + Prisma ORM.",
        master_plan_text="Monorepo layout with apps/api and apps/web.",
        tech_stack=[],
        milestone_requirements=requirements,
    )
    ports = extract_stack_contract_port_literals(contract)

    assert contract.package_manager == "pnpm"
    assert contract.port == 3000
    assert contract.api_port == 3000
    assert contract.web_port == 3080
    assert contract.ports == [3000, 3080, 5432]
    assert ports == {"api_port": 3000, "port": 3000, "ports": [3000, 3080, 5432], "web_port": 3080}


def test_infrastructure_template_slots_are_authoritative_over_stale_requirements_ports(
    tmp_path: Path,
) -> None:
    contract = StackContract(
        backend_framework="nestjs",
        frontend_framework="nextjs",
        package_manager="pnpm",
        port=3000,
        api_port=3000,
        web_port=3080,
        ports=[3000, 3080, 5432],
        infrastructure_template={
            "name": "pnpm_monorepo",
            "version": "2.0.0",
            "slots": {
                "api_port": 4000,
                "web_port": 3000,
                "postgres_port": 5432,
            },
        },
    )
    write_stack_contract(tmp_path, contract)
    _write(
        tmp_path / ".agent-team" / "milestones" / "milestone-1" / "REQUIREMENTS.md",
        "API listens at http://localhost:3000/api and web at http://localhost:3080.\n",
    )

    reloaded = load_stack_contract(tmp_path)

    assert reloaded is not None
    assert reloaded.api_port == 4000
    assert reloaded.port == 4000
    assert reloaded.web_port == 3000
    assert reloaded.ports == [3000, 4000, 5432]
    assert 3080 not in reloaded.ports


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


def test_root_prisma_schema_is_layout_exempt_for_stack_path_001(tmp_path: Path) -> None:
    """Smoke ``m1-hardening-smoke-20260425-201449`` Wave A wrote
    ``prisma/schema.prisma`` per the milestone's required-file pattern,
    STACK-PATH-001 rejected it for being outside ``apps/api/* | apps/web/*``,
    and the retry produced WAVE_A_CONTRACT_CONFLICT.md naming the
    impossible "must be under apps/api/* AND must match prisma/schema\\.prisma$"
    pair. Root ``prisma/`` is now in ``_EXEMPT_SHARED_PREFIXES``.
    """
    registry = builtin_stack_contracts()
    contract = registry[("nestjs", "prisma")]
    contract.monorepo_layout = "apps"
    contract.backend_path_prefix = "apps/api/"
    contract.frontend_path_prefix = "apps/web/"

    _write(tmp_path / "prisma" / "schema.prisma", "generator client { provider = \"prisma-client-js\" }\n")
    _write(
        tmp_path / "apps" / "api" / "src" / "prisma" / "prisma.service.ts",
        "import { PrismaClient } from '@prisma/client';\n",
    )

    violations = validate_wave_against_stack_contract(
        _wave_output(
            "prisma/schema.prisma",
            "apps/api/src/prisma/prisma.service.ts",
        ),
        contract,
        tmp_path,
    )

    path_violations = [v for v in violations if v.code == "STACK-PATH-001"]
    assert path_violations == [], (
        "Root prisma/schema.prisma must not trigger STACK-PATH-001 — it is "
        "the canonical Prisma location and a required-file-pattern entry "
        f"in the stack contract. Got: {path_violations}"
    )


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
