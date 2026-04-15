"""Deterministic scaffolding runner for V18.1.

Reads the compiled Product IR and creates predictable file skeletons
that downstream waves can fill in with business logic.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional


def run_scaffolding(
    ir_path: Path,
    project_root: Path,
    milestone_id: str,
    milestone_features: list[str],
    stack_target: Optional[str] = None,
) -> list[str]:
    """Run deterministic scaffolding for a milestone.

    Returns the created file paths relative to *project_root*.
    """
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    stack = stack_target or _detect_stack_from_ir(ir)
    scaffolded_files: list[str] = []

    milestone_entities = [
        entity
        for entity in ir.get("entities", [])
        if _entity_matches_milestone(entity, milestone_id, milestone_features)
    ]

    has_nestjs = "nestjs" in stack.lower()
    has_nextjs = "next" in stack.lower() or "react" in stack.lower()

    # M1 foundation — deterministic across all milestones (idempotent)
    scaffolded_files.extend(
        _scaffold_m1_foundation(
            project_root,
            has_nestjs=has_nestjs,
            has_nextjs=has_nextjs,
        )
    )

    if has_nestjs:
        scaffolded_files.extend(
            _scaffold_nestjs(project_root, milestone_entities, ir)
        )

    if milestone_entities and has_nextjs:
        scaffolded_files.extend(
            _scaffold_nextjs_pages(project_root, milestone_entities, ir)
        )

    if milestone_features and ir.get("i18n", {}).get("locales"):
        scaffolded_files.extend(
            _scaffold_i18n(project_root, milestone_features, ir["i18n"])
        )

    return scaffolded_files


def _detect_stack_from_ir(ir: dict) -> str:
    stack = ir.get("stack_target", {}) or {}
    backend = str(stack.get("backend", "") or "")
    frontend = str(stack.get("frontend", "") or "")
    mobile = str(stack.get("mobile", "") or "")
    parts = [backend, frontend, mobile]
    return " ".join(part for part in parts if part).strip()


def _entity_matches_milestone(
    entity: dict,
    milestone_id: str,
    milestone_features: list[str],
) -> bool:
    owner_feature = str(entity.get("owner_feature", "") or "")
    owner_hint = str(entity.get("owner_milestone_hint", "") or "")
    if owner_hint == milestone_id:
        return True
    if owner_feature and owner_feature in milestone_features:
        return True
    return False


def _scaffold_nestjs(project_root: Path, entities: list[dict], ir: dict) -> list[str]:
    """Generate NestJS module/service/controller shells."""
    scaffolded: list[str] = _scaffold_nestjs_support_files(project_root)
    api_dir = project_root / "apps" / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    if not entities:
        return scaffolded

    if _check_nest_cli(api_dir):
        for entity in entities:
            name = _to_kebab_case(str(entity.get("name", "")))
            if not name:
                continue
            target_paths = [
                api_dir / "src" / name / f"{name}.module.ts",
                api_dir / "src" / name / f"{name}.service.ts",
                api_dir / "src" / name / f"{name}.controller.ts",
            ]
            if all(path.exists() for path in target_paths):
                continue
            if any(path.exists() for path in target_paths):
                scaffolded.extend(
                    _scaffold_nestjs_from_templates(project_root, [entity], ir)
                )
                continue
            try:
                subprocess.run(
                    ["npx", "nest", "generate", "module", name, "--no-spec"],
                    cwd=str(api_dir),
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                subprocess.run(
                    ["npx", "nest", "generate", "service", name, "--no-spec"],
                    cwd=str(api_dir),
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                subprocess.run(
                    ["npx", "nest", "generate", "controller", name, "--no-spec"],
                    cwd=str(api_dir),
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                scaffolded.extend(
                    [
                        _relpath(api_dir / "src" / name / f"{name}.module.ts", project_root),
                        _relpath(api_dir / "src" / name / f"{name}.service.ts", project_root),
                        _relpath(api_dir / "src" / name / f"{name}.controller.ts", project_root),
                    ]
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                scaffolded.extend(
                    _scaffold_nestjs_from_templates(project_root, [entity], ir)
                )
    else:
        scaffolded.extend(_scaffold_nestjs_from_templates(project_root, entities, ir))

    return scaffolded


def _scaffold_nestjs_support_files(project_root: Path) -> list[str]:
    scaffolded: list[str] = []
    scripts_dir = project_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / "generate-openapi.ts"
    if not script_path.exists():
        script_path.write_text(_openapi_generation_script_template(), encoding="utf-8")
        scaffolded.append(_relpath(script_path, project_root))
    return scaffolded


def _scaffold_nestjs_from_templates(
    project_root: Path,
    entities: list[dict],
    ir: dict,
) -> list[str]:
    scaffolded: list[str] = []
    api_dir = project_root / "apps" / "api" / "src"

    for entity in entities:
        name = _to_kebab_case(str(entity.get("name", "")))
        pascal = _to_pascal_case(str(entity.get("name", "")))
        if not name or not pascal:
            continue
        entity_dir = api_dir / name
        entity_dir.mkdir(parents=True, exist_ok=True)

        for suffix, content in (
            ("module.ts", _nestjs_module_template(pascal, name)),
            ("service.ts", _nestjs_service_template(pascal, name)),
            ("controller.ts", _nestjs_controller_template(pascal, name)),
        ):
            file_path = entity_dir / f"{name}.{suffix}"
            if not file_path.exists():
                file_path.write_text(content, encoding="utf-8")
                scaffolded.append(_relpath(file_path, project_root))

    return scaffolded


def _scaffold_nextjs_pages(
    project_root: Path,
    entities: list[dict],
    ir: dict,
) -> list[str]:
    """Generate Next.js page shells with i18n-aware route structure."""
    scaffolded: list[str] = []
    web_dir = project_root / "apps" / "web" / "src" / "app"
    has_i18n = bool(ir.get("i18n", {}).get("locales", []))
    prefix = "[locale]/(protected)" if has_i18n else "(protected)"

    for entity in entities:
        route = _to_kebab_case(str(entity.get("name", "")))
        if not route:
            continue
        page_dir = web_dir / prefix / route
        page_dir.mkdir(parents=True, exist_ok=True)

        list_page = page_dir / "page.tsx"
        if not list_page.exists():
            list_page.write_text(_nextjs_page_template(route, "list", has_i18n), encoding="utf-8")
            scaffolded.append(_relpath(list_page, project_root))

        detail_dir = page_dir / "[id]"
        detail_dir.mkdir(parents=True, exist_ok=True)
        detail_page = detail_dir / "page.tsx"
        if not detail_page.exists():
            detail_page.write_text(_nextjs_page_template(route, "detail", has_i18n), encoding="utf-8")
            scaffolded.append(_relpath(detail_page, project_root))

    return scaffolded


#: A-04 — M1 REQUIREMENTS.md pins locales to en + ar. Filter upstream IR drift
#: (e.g., stray `id` locale leaking in from templates) so scaffold output stays
#: deterministic. Widening requires an explicit tracker decision, not IR drift.
_M1_ALLOWED_LOCALES: frozenset[str] = frozenset({"en", "ar"})


def _scaffold_i18n(project_root: Path, features: list[str], i18n_config: dict) -> list[str]:
    """Create empty i18n namespace files for declared locales.

    Locales are intersected with :data:`_M1_ALLOWED_LOCALES` — the scaffold
    layer is defensive against upstream IR drift that injects locales outside
    the M1 spec (see tracker A-04).
    """
    scaffolded: list[str] = []
    messages_dir = project_root / "apps" / "web" / "messages"

    raw_locales = [str(locale) for locale in i18n_config.get("locales", ["en"])]
    filtered_locales = [
        locale for locale in raw_locales if locale in _M1_ALLOWED_LOCALES
    ]
    if not filtered_locales:
        filtered_locales = ["en"]

    for locale in filtered_locales:
        locale_dir = messages_dir / locale
        locale_dir.mkdir(parents=True, exist_ok=True)
        for feature in features:
            ns_file = locale_dir / f"{_to_kebab_case(str(feature))}.json"
            if not ns_file.exists():
                ns_file.write_text("{}\n", encoding="utf-8")
                scaffolded.append(_relpath(ns_file, project_root))

    return scaffolded


def _check_nest_cli(project_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["npx", "nest", "--version"],
            cwd=str(project_root),
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _relpath(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _to_kebab_case(name: str) -> str:
    import re

    if not name:
        return ""
    s = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _to_pascal_case(s: str) -> str:
    if not s:
        return ""
    return "".join(word.capitalize() for word in s.replace("-", " ").replace("_", " ").split())


def _nestjs_module_template(pascal: str, name: str) -> str:
    return (
        "import { Module } from '@nestjs/common';\n\n"
        "@Module({\n"
        f"  providers: [],\n"
        f"  controllers: [],\n"
        f"  exports: [],\n"
        "})\n"
        f"export class {pascal}Module {{}}\n"
    )


def _nestjs_service_template(pascal: str, name: str) -> str:
    return (
        "import { Injectable } from '@nestjs/common';\n\n"
        "@Injectable()\n"
        f"export class {pascal}Service {{\n"
        f"  // TODO: implement {name} service logic\n"
        "}\n"
    )


def _nestjs_controller_template(pascal: str, name: str) -> str:
    return (
        "import { Controller } from '@nestjs/common';\n\n"
        f"@Controller('{name}')\n"
        f"export class {pascal}Controller {{\n"
        f"  // TODO: implement {name} controller routes\n"
        "}\n"
    )


def _nextjs_page_template(route: str, page_type: str, has_i18n: bool) -> str:
    i18n_import = "import { useTranslations } from 'next-intl';\n" if has_i18n else ""
    t_init = f"  const t = useTranslations('{route}');\n" if has_i18n else ""
    return (
        "'use client';\n\n"
        f"{i18n_import}"
        f"export default function {_to_pascal_case(route)}{_to_pascal_case(page_type)}Page() {{\n"
        f"{t_init}"
        "  return (\n"
        "    <div>\n"
        f"      {{/* TODO: Implement {route} {page_type} */}}\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )


def _openapi_generation_script_template() -> str:
    return (
        "import 'reflect-metadata';\n"
        "import { mkdirSync, writeFileSync } from 'node:fs';\n"
        "import { join, resolve } from 'node:path';\n"
        "import { NestFactory } from '@nestjs/core';\n"
        "import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';\n\n"
        "async function loadAppModule(): Promise<any> {\n"
        "  const candidates = ['../apps/api/src/app.module', '../src/app.module'];\n"
        "  for (const candidate of candidates) {\n"
        "    try {\n"
        "      const moduleRef = await import(candidate);\n"
        "      if (moduleRef?.AppModule) {\n"
        "        return moduleRef.AppModule;\n"
        "      }\n"
        "    } catch {\n"
        "      // Try the next app root.\n"
        "    }\n"
        "  }\n"
        "  throw new Error('Unable to resolve AppModule from apps/api/src/app.module or src/app.module');\n"
        "}\n\n"
        "async function main(): Promise<void> {\n"
        "  const milestoneId = process.env.MILESTONE_ID || 'milestone-unknown';\n"
        "  const outputDir = resolve(process.cwd(), process.env.OUTPUT_DIR || 'contracts/openapi');\n"
        "  mkdirSync(outputDir, { recursive: true });\n"
        "  const AppModule = await loadAppModule();\n"
        "  const app = await NestFactory.create(AppModule, { logger: false });\n"
        "  await app.init();\n"
        "  const document = SwaggerModule.createDocument(\n"
        "    app,\n"
        "    new DocumentBuilder().setTitle('Generated API').setVersion('1.0.0').build(),\n"
        "  );\n"
        "  await app.close();\n"
        "  const serialized = JSON.stringify(document, null, 2);\n"
        "  writeFileSync(join(outputDir, 'current.json'), serialized);\n"
        "  writeFileSync(join(outputDir, `${milestoneId}.json`), serialized);\n"
        "}\n\n"
        "main().catch((error) => {\n"
        "  console.error(error instanceof Error ? error.stack || error.message : String(error));\n"
        "  process.exit(1);\n"
        "});\n"
    )


# ---------------------------------------------------------------------------
# M1 foundation scaffold — tracker IDs A-01 / A-02 / A-03 / A-07 / A-08 / D-18
# ---------------------------------------------------------------------------

def _scaffold_m1_foundation(
    project_root: Path,
    *,
    has_nestjs: bool,
    has_nextjs: bool,
) -> list[str]:
    """Emit the deterministic M1 foundation: root files + backend + frontend bases.

    Idempotent — each helper writes only when the file does not exist, so
    later milestones and wave agents may extend or override. Templates reflect
    `milestones/milestone-1/REQUIREMENTS.md` directly: PORT 3001 baseline,
    Prisma 5 shutdown pattern, vitest + testing-library ready out of the box,
    `.gitignore` covering the expected tooling, docker-compose Postgres.
    """
    scaffolded: list[str] = []
    scaffolded.extend(_scaffold_root_files(project_root))  # A-08, root package.json
    scaffolded.extend(_scaffold_docker_compose(project_root))  # A-01
    if has_nestjs:
        scaffolded.extend(_scaffold_api_foundation(project_root))  # A-02, A-03, D-18
    if has_nextjs:
        scaffolded.extend(_scaffold_web_foundation(project_root))  # A-07, D-18
    return scaffolded


def _write_if_missing(path: Path, content: str, *, project_root: Path) -> Optional[str]:
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return _relpath(path, project_root)


def _scaffold_root_files(project_root: Path) -> list[str]:
    """A-08: `.gitignore` + `.env.example`; plus root `package.json` workspaces manifest."""
    scaffolded: list[str] = []
    for rel, content in (
        (".gitignore", _gitignore_template()),
        (".env.example", _env_example_template()),
        ("package.json", _root_package_json_template()),
    ):
        result = _write_if_missing(project_root / rel, content, project_root=project_root)
        if result is not None:
            scaffolded.append(result)
    return scaffolded


def _scaffold_docker_compose(project_root: Path) -> list[str]:
    """A-01: root `docker-compose.yml` with Postgres + healthcheck + named volume."""
    path = project_root / "docker-compose.yml"
    result = _write_if_missing(path, _docker_compose_template(), project_root=project_root)
    return [result] if result is not None else []


def _scaffold_api_foundation(project_root: Path) -> list[str]:
    """A-02 (PORT default 3001), A-03 (Prisma 5 shutdown hook), D-18 (clean pins)."""
    scaffolded: list[str] = []
    api_src = project_root / "apps" / "api" / "src"
    templates: tuple[tuple[Path, str], ...] = (
        (project_root / "apps" / "api" / "package.json", _api_package_json_template()),
        (api_src / "main.ts", _api_main_ts_template()),
        (api_src / "config" / "env.validation.ts", _api_env_validation_template()),
        (api_src / "prisma" / "prisma.service.ts", _api_prisma_service_template()),
        (api_src / "prisma" / "prisma.module.ts", _api_prisma_module_template()),
    )
    for path, content in templates:
        result = _write_if_missing(path, content, project_root=project_root)
        if result is not None:
            scaffolded.append(result)
    return scaffolded


def _scaffold_web_foundation(project_root: Path) -> list[str]:
    """A-07: vitest + testing-library + jsdom in `apps/web` package.json + vitest.config.ts."""
    scaffolded: list[str] = []
    web_dir = project_root / "apps" / "web"
    templates: tuple[tuple[Path, str], ...] = (
        (web_dir / "package.json", _web_package_json_template()),
        (web_dir / "vitest.config.ts", _web_vitest_config_template()),
    )
    for path, content in templates:
        result = _write_if_missing(path, content, project_root=project_root)
        if result is not None:
            scaffolded.append(result)
    return scaffolded


# --- templates --------------------------------------------------------------

def _gitignore_template() -> str:
    return (
        "# Dependencies\n"
        "node_modules/\n"
        "apps/*/node_modules/\n"
        "packages/*/node_modules/\n"
        "\n"
        "# Build output\n"
        "dist/\n"
        "apps/*/dist/\n"
        "packages/*/dist/\n"
        ".next/\n"
        "apps/*/.next/\n"
        ".turbo/\n"
        "\n"
        "# Test / coverage\n"
        "coverage/\n"
        "apps/*/coverage/\n"
        "\n"
        "# Env — never commit real secrets. Use .env.example as the template.\n"
        ".env\n"
        ".env.local\n"
        ".env.*.local\n"
        "apps/*/.env\n"
        "apps/*/.env.local\n"
        "\n"
        "# Editors\n"
        ".vscode/\n"
        ".idea/\n"
        "*.log\n"
    )


def _env_example_template() -> str:
    # A-02: PORT=3001 is the single source of truth for the M1 dev-api port
    return (
        "# M1 baseline env — copy to .env and fill per environment.\n"
        "NODE_ENV=development\n"
        "PORT=3001\n"
        "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/app?schema=public\n"
        "POSTGRES_USER=postgres\n"
        "POSTGRES_PASSWORD=postgres\n"
        "POSTGRES_DB=app\n"
        "JWT_SECRET=change-me\n"
        "JWT_EXPIRES_IN=3600s\n"
        "FRONTEND_ORIGIN=http://localhost:3000\n"
    )


def _root_package_json_template() -> str:
    return json.dumps(
        {
            "name": "app",
            "version": "1.0.0",
            "private": True,
            "workspaces": ["apps/*", "packages/*"],
            "scripts": {
                "build:api": "npm --workspace apps/api run build",
                "build:web": "npm --workspace apps/web run build",
                "dev:api": "npm --workspace apps/api run start:dev",
                "dev:web": "npm --workspace apps/web run dev",
                "test:api": "npm --workspace apps/api run test",
                "test:web": "npm --workspace apps/web run test",
                "test": "npm run test:api && npm run test:web",
            },
        },
        indent=2,
    ) + "\n"


def _docker_compose_template() -> str:
    # A-01: Postgres service with named volume + pg_isready healthcheck. Wave B
    # may extend this file later (add redis, tweak credentials) but the base
    # must satisfy M1 "docker-compose up" startup AC out of the box.
    return (
        "services:\n"
        "  postgres:\n"
        "    image: postgres:16-alpine\n"
        "    ports:\n"
        '      - "5432:5432"\n'
        "    environment:\n"
        "      POSTGRES_USER: ${POSTGRES_USER:-postgres}\n"
        "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}\n"
        "      POSTGRES_DB: ${POSTGRES_DB:-app}\n"
        "    volumes:\n"
        "      - postgres_data:/var/lib/postgresql/data\n"
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-app}"]\n'
        "      interval: 10s\n"
        "      timeout: 5s\n"
        "      retries: 5\n"
        "\n"
        "volumes:\n"
        "  postgres_data:\n"
    )


def _api_package_json_template() -> str:
    # D-18: dependency pins tracked against npm audit as of 2026-04. Minimum
    # floors (Next 15.1+, NestJS 11+, Prisma 6+) are enforced in
    # tests/test_scaffold_m1_correctness.py::TestD18NonVulnerablePins.
    return json.dumps(
        {
            "name": "api",
            "version": "1.0.0",
            "private": True,
            "scripts": {
                "build": "nest build",
                "start": "node dist/main.js",
                "start:dev": "nest start --watch",
                "test": "jest --runInBand --passWithNoTests",
                "test:watch": "jest --watch",
                "openapi": "ts-node -r tsconfig-paths/register ../../scripts/generate-openapi.ts",
            },
            "prisma": {"seed": "ts-node prisma/seed.ts"},
            "dependencies": {
                "@nestjs/common": "^11.0.0",
                "@nestjs/config": "^4.0.0",
                "@nestjs/core": "^11.0.0",
                "@nestjs/jwt": "^11.0.0",
                "@nestjs/passport": "^11.0.0",
                "@nestjs/platform-express": "^11.0.0",
                "@nestjs/swagger": "^11.0.0",
                "@prisma/client": "^6.0.0",
                "class-transformer": "^0.5.1",
                "class-validator": "^0.14.1",
                "helmet": "^8.0.0",
                "joi": "^17.13.3",
                "passport": "^0.7.0",
                "passport-jwt": "^4.0.1",
                "prisma": "^6.0.0",
                "reflect-metadata": "^0.2.2",
                "rxjs": "^7.8.1",
            },
            "devDependencies": {
                "@nestjs/cli": "^11.0.0",
                "@nestjs/schematics": "^11.0.0",
                "@nestjs/testing": "^11.0.0",
                "@types/jest": "^29.5.14",
                "@types/node": "^22.10.2",
                "@types/passport-jwt": "^4.0.1",
                "jest": "^29.7.0",
                "ts-jest": "^29.2.5",
                "ts-node": "^10.9.2",
                "tsconfig-paths": "^4.2.0",
                "typescript": "^5.7.2",
            },
        },
        indent=2,
    ) + "\n"


def _api_main_ts_template() -> str:
    # A-02: PORT default 3001 (not 8080). env.validation.ts is the canonical
    # source; the fallback here matches it for the case where the env var is
    # unset at boot.
    return (
        "import { Logger, ValidationPipe } from '@nestjs/common';\n"
        "import { NestFactory } from '@nestjs/core';\n"
        "import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';\n"
        "import { AppModule } from './app.module';\n"
        "\n"
        "async function bootstrap(): Promise<void> {\n"
        "  const app = await NestFactory.create(AppModule);\n"
        "  const logger = new Logger('Bootstrap');\n"
        "\n"
        "  app.setGlobalPrefix('api', { exclude: ['health'] });\n"
        "  app.enableCors({\n"
        "    origin: process.env.FRONTEND_ORIGIN,\n"
        "    credentials: true,\n"
        "  });\n"
        "  app.useGlobalPipes(\n"
        "    new ValidationPipe({\n"
        "      whitelist: true,\n"
        "      forbidNonWhitelisted: true,\n"
        "      transform: true,\n"
        "    }),\n"
        "  );\n"
        "\n"
        "  const config = new DocumentBuilder()\n"
        "    .setTitle('API')\n"
        "    .setVersion('1.0.0')\n"
        "    .addBearerAuth()\n"
        "    .build();\n"
        "  const document = SwaggerModule.createDocument(app, config);\n"
        "  SwaggerModule.setup('api/docs', app, document);\n"
        "\n"
        "  // A-02: M1 dev-api port baseline is 3001.\n"
        "  const port = Number(process.env.PORT ?? 3001);\n"
        "  await app.listen(port);\n"
        "  logger.log(`API listening on port ${port}`);\n"
        "}\n"
        "\n"
        "void bootstrap();\n"
    )


def _api_env_validation_template() -> str:
    # A-02: Joi schema with PORT defaulting to 3001.
    return (
        "import * as Joi from 'joi';\n"
        "\n"
        "// A-02: PORT default is 3001 (M1 dev-api port baseline). Do not\n"
        "// change without updating .env.example and apps/api/src/main.ts in\n"
        "// lock step.\n"
        "export const envValidationSchema = Joi.object({\n"
        "  NODE_ENV: Joi.string()\n"
        "    .valid('development', 'test', 'production')\n"
        "    .default('development'),\n"
        "  PORT: Joi.number().integer().positive().default(3001),\n"
        "  DATABASE_URL: Joi.string().uri({ scheme: ['postgres', 'postgresql'] }).required(),\n"
        "  JWT_SECRET: Joi.string().min(16).required(),\n"
        "  JWT_EXPIRES_IN: Joi.string().default('3600s'),\n"
        "  FRONTEND_ORIGIN: Joi.string().uri().default('http://localhost:3000'),\n"
        "});\n"
    )


def _api_prisma_service_template() -> str:
    # A-03: Prisma 5+ removed `$on('beforeExit')` from the library engine. Use
    # the Node process hook instead so `app.close()` triggers on SIGTERM.
    # Verified against Prisma migration guidance (context7 /prisma/prisma).
    return (
        "import { INestApplication, Injectable, OnModuleInit } from '@nestjs/common';\n"
        "import { PrismaClient } from '@prisma/client';\n"
        "\n"
        "@Injectable()\n"
        "export class PrismaService extends PrismaClient implements OnModuleInit {\n"
        "  async onModuleInit(): Promise<void> {\n"
        "    await this.$connect();\n"
        "  }\n"
        "\n"
        "  // A-03: Prisma 5+ no longer emits `beforeExit` via `$on`. Register\n"
        "  // the Node-level hook instead so Nest cleans up on SIGTERM.\n"
        "  async enableShutdownHooks(app: INestApplication): Promise<void> {\n"
        "    process.on('beforeExit', async () => {\n"
        "      await app.close();\n"
        "    });\n"
        "  }\n"
        "}\n"
    )


def _api_prisma_module_template() -> str:
    return (
        "import { Global, Module } from '@nestjs/common';\n"
        "import { PrismaService } from './prisma.service';\n"
        "\n"
        "@Global()\n"
        "@Module({\n"
        "  providers: [PrismaService],\n"
        "  exports: [PrismaService],\n"
        "})\n"
        "export class PrismaModule {}\n"
    )


def _web_package_json_template() -> str:
    # A-07: vitest + testing-library + jsdom pinned deterministically. D-18:
    # floors verified clean against npm advisory data as of 2026-04. Bumping
    # these requires updating the corresponding test assertions in
    # tests/test_scaffold_m1_correctness.py.
    return json.dumps(
        {
            "name": "web",
            "version": "1.0.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start",
                "test": "vitest run --passWithNoTests",
            },
            "dependencies": {
                "next": "^15.1.0",
                "next-intl": "^3.26.5",
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
            },
            "devDependencies": {
                "@testing-library/jest-dom": "^6.6.0",
                "@testing-library/react": "^16.1.0",
                "@types/node": "^22.10.2",
                "@types/react": "^19.0.2",
                "@types/react-dom": "^19.0.2",
                "@vitejs/plugin-react": "^4.3.4",
                "autoprefixer": "^10.4.20",
                "jsdom": "^25.0.0",
                "postcss": "^8.4.49",
                "tailwindcss": "^3.4.17",
                "typescript": "^5.7.2",
                "vitest": "^2.1.0",
            },
        },
        indent=2,
    ) + "\n"


def _web_vitest_config_template() -> str:
    return (
        "import { defineConfig } from 'vitest/config';\n"
        "import react from '@vitejs/plugin-react';\n"
        "\n"
        "export default defineConfig({\n"
        "  plugins: [react()],\n"
        "  test: {\n"
        "    environment: 'jsdom',\n"
        "    globals: true,\n"
        "    css: false,\n"
        "    passWithNoTests: true,\n"
        "  },\n"
        "});\n"
    )
