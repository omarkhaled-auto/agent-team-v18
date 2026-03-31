"""Tests for agent_team.api_contract_extractor — endpoint/model extraction and serialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.api_contract_extractor import (
    APIContractBundle,
    EndpointContract,
    EnumContract,
    ModelContract,
    detect_naming_convention,
    extract_api_contracts,
    extract_dto_fields,
    extract_express_endpoints,
    extract_isin_enums,
    extract_nestjs_endpoints,
    extract_prisma_enums,
    extract_prisma_models,
    load_api_contracts,
    render_api_contracts_for_prompt,
    save_api_contracts,
)


# ===================================================================
# Helpers
# ===================================================================

def _write_file(base: Path, relative: str, content: str) -> Path:
    """Create a file under *base* and return its Path."""
    p = base / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ===================================================================
# 1. NestJS Controller Parsing
# ===================================================================


class TestNestJSParsing:
    """Verify NestJS @Controller / @Get / @Post decorator extraction."""

    def test_basic_controller_get(self, tmp_path):
        """A simple @Controller with one @Get endpoint."""
        _write_file(tmp_path, "src/users/users.controller.ts", (
            "import { Controller, Get } from '@nestjs/common';\n"
            "\n"
            "@Controller('users')\n"
            "export class UsersController {\n"
            "  @Get()\n"
            "  findAll() {\n"
            "    return [];\n"
            "  }\n"
            "}\n"
        ))
        endpoints = extract_nestjs_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "users" in ep.path
        assert ep.method.upper() == "GET"

    def test_controller_with_post(self, tmp_path):
        """A @Controller with a @Post endpoint."""
        _write_file(tmp_path, "src/auth/auth.controller.ts", (
            "import { Controller, Post, Body } from '@nestjs/common';\n"
            "\n"
            "@Controller('auth')\n"
            "export class AuthController {\n"
            "  @Post('login')\n"
            "  login(@Body() dto: LoginDto) {\n"
            "    return { token: 'abc' };\n"
            "  }\n"
            "}\n"
        ))
        endpoints = extract_nestjs_endpoints(tmp_path)
        assert len(endpoints) >= 1
        post_eps = [e for e in endpoints if e.method.upper() == "POST"]
        assert len(post_eps) >= 1
        assert "login" in post_eps[0].path

    def test_controller_with_multiple_methods(self, tmp_path):
        """A single controller with GET, POST, PUT, DELETE."""
        _write_file(tmp_path, "src/items/items.controller.ts", (
            "import { Controller, Get, Post, Put, Delete, Param, Body } from '@nestjs/common';\n"
            "\n"
            "@Controller('items')\n"
            "export class ItemsController {\n"
            "  @Get()\n"
            "  findAll() { return []; }\n"
            "\n"
            "  @Get(':id')\n"
            "  findOne(@Param('id') id: string) { return {}; }\n"
            "\n"
            "  @Post()\n"
            "  create(@Body() dto: any) { return {}; }\n"
            "\n"
            "  @Put(':id')\n"
            "  update(@Param('id') id: string, @Body() dto: any) { return {}; }\n"
            "\n"
            "  @Delete(':id')\n"
            "  remove(@Param('id') id: string) { return {}; }\n"
            "}\n"
        ))
        endpoints = extract_nestjs_endpoints(tmp_path)
        methods = {e.method.upper() for e in endpoints}
        assert "GET" in methods
        assert "POST" in methods

    def test_controller_file_recorded(self, tmp_path):
        """EndpointContract.controller_file is set to the source file path."""
        _write_file(tmp_path, "src/cats/cats.controller.ts", (
            "@Controller('cats')\n"
            "export class CatsController {\n"
            "  @Get()\n"
            "  findAll() { return []; }\n"
            "}\n"
        ))
        endpoints = extract_nestjs_endpoints(tmp_path)
        assert len(endpoints) >= 1
        assert "cats.controller.ts" in endpoints[0].controller_file

    def test_no_controllers_in_project(self, tmp_path):
        """Empty list when project has no .controller.ts files."""
        _write_file(tmp_path, "src/index.ts", "console.log('hello');")
        endpoints = extract_nestjs_endpoints(tmp_path)
        assert endpoints == []


# ===================================================================
# 2. Express Route Parsing
# ===================================================================


class TestExpressParsing:
    """Verify Express router.get/post pattern extraction."""

    def test_basic_router_get(self, tmp_path):
        """router.get('/users', handler) is extracted."""
        _write_file(tmp_path, "src/routes/users.routes.ts", (
            "import { Router } from 'express';\n"
            "const router = Router();\n"
            "\n"
            "router.get('/users', (req, res) => {\n"
            "  res.json([]);\n"
            "});\n"
            "\n"
            "export default router;\n"
        ))
        endpoints = extract_express_endpoints(tmp_path)
        assert len(endpoints) >= 1
        assert endpoints[0].method.upper() == "GET"
        assert "users" in endpoints[0].path

    def test_router_post(self, tmp_path):
        """router.post('/users', handler) is extracted."""
        _write_file(tmp_path, "src/routes/users.routes.ts", (
            "const router = require('express').Router();\n"
            "\n"
            "router.post('/users', (req, res) => {\n"
            "  res.status(201).json({});\n"
            "});\n"
            "\n"
            "module.exports = router;\n"
        ))
        endpoints = extract_express_endpoints(tmp_path)
        post_eps = [e for e in endpoints if e.method.upper() == "POST"]
        assert len(post_eps) >= 1

    def test_multiple_routes_in_file(self, tmp_path):
        """Multiple router.{method} calls in a single file."""
        _write_file(tmp_path, "src/routes/api.router.ts", (
            "import { Router } from 'express';\n"
            "const router = Router();\n"
            "\n"
            "router.get('/health', (req, res) => res.json({ok: true}));\n"
            "router.post('/login', (req, res) => res.json({token: 'x'}));\n"
            "router.delete('/session', (req, res) => res.sendStatus(204));\n"
            "\n"
            "export default router;\n"
        ))
        endpoints = extract_express_endpoints(tmp_path)
        assert len(endpoints) >= 2

    def test_no_express_routes(self, tmp_path):
        """Empty list when no Express route files exist."""
        _write_file(tmp_path, "src/index.ts", "console.log('no routes');")
        endpoints = extract_express_endpoints(tmp_path)
        assert endpoints == []


# ===================================================================
# 3. DTO Field Parsing
# ===================================================================


class TestDTOFieldParsing:
    """Verify DTO (Data Transfer Object) field extraction."""

    def test_basic_dto(self, tmp_path):
        """A class with class-validator decorators has its fields extracted."""
        _write_file(tmp_path, "src/users/dto/create-user.dto.ts", (
            "import { IsString, IsEmail, IsOptional } from 'class-validator';\n"
            "\n"
            "export class CreateUserDto {\n"
            "  @IsString()\n"
            "  name: string;\n"
            "\n"
            "  @IsEmail()\n"
            "  email: string;\n"
            "\n"
            "  @IsOptional()\n"
            "  @IsString()\n"
            "  bio?: string;\n"
            "}\n"
        ))
        fields = extract_dto_fields(tmp_path)
        assert isinstance(fields, dict)
        # At least one DTO class should be found
        assert len(fields) >= 1

    def test_multiple_dtos_in_file(self, tmp_path):
        """Multiple DTO classes in a single file."""
        _write_file(tmp_path, "src/auth/dto/auth.dto.ts", (
            "import { IsString } from 'class-validator';\n"
            "\n"
            "export class LoginDto {\n"
            "  @IsString()\n"
            "  username: string;\n"
            "\n"
            "  @IsString()\n"
            "  password: string;\n"
            "}\n"
            "\n"
            "export class RegisterDto {\n"
            "  @IsString()\n"
            "  username: string;\n"
            "\n"
            "  @IsString()\n"
            "  password: string;\n"
            "\n"
            "  @IsString()\n"
            "  email: string;\n"
            "}\n"
        ))
        fields = extract_dto_fields(tmp_path)
        assert len(fields) >= 2

    def test_no_dto_files(self, tmp_path):
        """Empty dict when no DTO files exist."""
        _write_file(tmp_path, "src/index.ts", "console.log('no dtos');")
        fields = extract_dto_fields(tmp_path)
        assert isinstance(fields, dict)
        assert len(fields) == 0


# ===================================================================
# 4. Prisma Model Parsing
# ===================================================================


class TestPrismaModelParsing:
    """Verify Prisma schema model extraction."""

    def test_basic_model(self, tmp_path):
        """A simple Prisma model with scalar fields."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "generator client {\n"
            "  provider = \"prisma-client-js\"\n"
            "}\n"
            "\n"
            "datasource db {\n"
            "  provider = \"postgresql\"\n"
            "  url      = env(\"DATABASE_URL\")\n"
            "}\n"
            "\n"
            "model User {\n"
            "  id        Int      @id @default(autoincrement())\n"
            "  email     String   @unique\n"
            "  name      String?\n"
            "  createdAt DateTime @default(now())\n"
            "}\n"
        ))
        models = extract_prisma_models(tmp_path)
        assert len(models) >= 1
        user_models = [m for m in models if m.name == "User"]
        assert len(user_models) == 1
        assert len(user_models[0].fields) >= 3

    def test_multiple_models(self, tmp_path):
        """Multiple models in a single schema file."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "model User {\n"
            "  id    Int    @id @default(autoincrement())\n"
            "  email String @unique\n"
            "  posts Post[]\n"
            "}\n"
            "\n"
            "model Post {\n"
            "  id       Int    @id @default(autoincrement())\n"
            "  title    String\n"
            "  content  String?\n"
            "  authorId Int\n"
            "  author   User   @relation(fields: [authorId], references: [id])\n"
            "}\n"
        ))
        models = extract_prisma_models(tmp_path)
        names = {m.name for m in models}
        assert "User" in names
        assert "Post" in names

    def test_no_prisma_schema(self, tmp_path):
        """Empty list when no schema.prisma exists."""
        _write_file(tmp_path, "src/index.ts", "console.log('no prisma');")
        models = extract_prisma_models(tmp_path)
        assert models == []


# ===================================================================
# 5. Prisma Enum Parsing
# ===================================================================


class TestPrismaEnumParsing:
    """Verify Prisma schema enum extraction."""

    def test_basic_enum(self, tmp_path):
        """A simple Prisma enum."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "enum Role {\n"
            "  USER\n"
            "  ADMIN\n"
            "  MODERATOR\n"
            "}\n"
        ))
        enums = extract_prisma_enums(tmp_path)
        assert len(enums) >= 1
        role_enums = [e for e in enums if e.name == "Role"]
        assert len(role_enums) == 1
        assert "USER" in role_enums[0].values
        assert "ADMIN" in role_enums[0].values
        assert "MODERATOR" in role_enums[0].values

    def test_multiple_enums(self, tmp_path):
        """Multiple enums in a single schema file."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "enum Role {\n"
            "  USER\n"
            "  ADMIN\n"
            "}\n"
            "\n"
            "enum Status {\n"
            "  ACTIVE\n"
            "  INACTIVE\n"
            "  SUSPENDED\n"
            "}\n"
        ))
        enums = extract_prisma_enums(tmp_path)
        names = {e.name for e in enums}
        assert "Role" in names
        assert "Status" in names

    def test_no_prisma_schema_for_enums(self, tmp_path):
        """Empty list when no schema.prisma exists."""
        models = extract_prisma_enums(tmp_path)
        assert models == []


# ===================================================================
# 5b. @IsIn() Validator Enum Extraction
# ===================================================================


class TestIsInEnumExtraction:
    """Verify @IsIn([...]) validator values are extracted as functional enums."""

    def test_basic_isin_extraction(self, tmp_path):
        """A DTO with @IsIn decorator has its values extracted as an enum."""
        _write_file(tmp_path, "src/work-orders/dto/create-work-order.dto.ts", (
            "import { IsString, IsIn } from 'class-validator';\n"
            "\n"
            "export class CreateWorkOrderDto {\n"
            "  @IsIn(['corrective', 'preventive', 'emergency', 'inspection'])\n"
            "  type!: string;\n"
            "\n"
            "  @IsString()\n"
            "  description!: string;\n"
            "}\n"
        ))
        enums = extract_isin_enums(tmp_path)
        assert len(enums) >= 1
        type_enums = [e for e in enums if e.name == "type"]
        assert len(type_enums) == 1
        assert "corrective" in type_enums[0].values
        assert "preventive" in type_enums[0].values
        assert "emergency" in type_enums[0].values
        assert "inspection" in type_enums[0].values

    def test_multiple_isin_in_single_file(self, tmp_path):
        """Multiple @IsIn decorators in a single DTO file."""
        _write_file(tmp_path, "src/escalations/dto/create-escalation.dto.ts", (
            "import { IsIn, IsString } from 'class-validator';\n"
            "\n"
            "export class CreateEscalationDto {\n"
            "  @IsIn(['sla_breach', 'no_response', 'stale'])\n"
            "  trigger_type!: string;\n"
            "\n"
            "  @IsIn(['low', 'medium', 'high', 'critical'])\n"
            "  priority!: string;\n"
            "}\n"
        ))
        enums = extract_isin_enums(tmp_path)
        assert len(enums) >= 2
        names = {e.name for e in enums}
        assert "trigger_type" in names
        assert "priority" in names
        # Check values
        trigger = [e for e in enums if e.name == "trigger_type"][0]
        assert "sla_breach" in trigger.values
        priority = [e for e in enums if e.name == "priority"][0]
        assert "critical" in priority.values

    def test_isin_with_double_quotes(self, tmp_path):
        """@IsIn with double-quoted strings."""
        _write_file(tmp_path, "src/assets/dto/create-asset.dto.ts", (
            "import { IsIn } from 'class-validator';\n"
            "\n"
            "export class CreateAssetDto {\n"
            '  @IsIn(["active", "inactive", "disposed"])\n'
            "  status!: string;\n"
            "}\n"
        ))
        enums = extract_isin_enums(tmp_path)
        assert len(enums) >= 1
        status_enum = [e for e in enums if e.name == "status"][0]
        assert status_enum.values == ["active", "inactive", "disposed"]

    def test_isin_with_stacked_decorators(self, tmp_path):
        """@IsIn combined with other decorators before the field."""
        _write_file(tmp_path, "src/tasks/dto/update-task.dto.ts", (
            "import { IsIn, IsOptional, IsString } from 'class-validator';\n"
            "\n"
            "export class UpdateTaskDto {\n"
            "  @IsOptional()\n"
            "  @IsIn(['pending', 'in_progress', 'completed', 'cancelled'])\n"
            "  status?: string;\n"
            "}\n"
        ))
        enums = extract_isin_enums(tmp_path)
        assert len(enums) >= 1
        assert enums[0].name == "status"
        assert "pending" in enums[0].values

    def test_isin_integrated_in_extract_api_contracts(self, tmp_path):
        """@IsIn enums appear in the bundle from extract_api_contracts."""
        _write_file(tmp_path, "src/wo/dto/create.dto.ts", (
            "import { IsIn } from 'class-validator';\n"
            "\n"
            "export class CreateDto {\n"
            "  @IsIn(['corrective', 'preventive'])\n"
            "  type!: string;\n"
            "}\n"
        ))
        bundle = extract_api_contracts(tmp_path, milestone_id="ms-1")
        enum_names = {e.name for e in bundle.enums}
        assert "type" in enum_names

    def test_no_isin_decorators(self, tmp_path):
        """Empty list when no @IsIn decorators exist."""
        _write_file(tmp_path, "src/users/dto/create-user.dto.ts", (
            "import { IsString } from 'class-validator';\n"
            "\n"
            "export class CreateUserDto {\n"
            "  @IsString()\n"
            "  name!: string;\n"
            "}\n"
        ))
        enums = extract_isin_enums(tmp_path)
        assert enums == []

    def test_isin_empty_project(self, tmp_path):
        """Empty list for an empty project directory."""
        enums = extract_isin_enums(tmp_path)
        assert enums == []


# ===================================================================
# 6. Naming Convention Detection
# ===================================================================


class TestNamingConventionDetection:
    """Verify detect_naming_convention identifies snake_case vs camelCase."""

    def test_snake_case_fields(self):
        """Endpoints and models with snake_case fields are detected."""
        endpoints = [
            EndpointContract(
                path="/users",
                method="GET",
                handler_name="findAll",
                controller_file="users.controller.ts",
                request_params=[],
                request_body_fields=[{"name": "user_name"}, {"name": "first_name"}],
                response_fields=[{"name": "user_id"}, {"name": "created_at"}],
                response_type="User",
            ),
        ]
        models = [
            ModelContract(name="User", fields=[{"name": "user_id"}, {"name": "first_name"}, {"name": "last_name"}]),
        ]
        convention = detect_naming_convention(endpoints, models)
        assert convention == "snake_case"

    def test_camel_case_fields(self):
        """Endpoints and models with camelCase fields are detected."""
        endpoints = [
            EndpointContract(
                path="/users",
                method="GET",
                handler_name="findAll",
                controller_file="users.controller.ts",
                request_params=[],
                request_body_fields=[{"name": "userName"}, {"name": "firstName"}],
                response_fields=[{"name": "userId"}, {"name": "createdAt"}],
                response_type="User",
            ),
        ]
        models = [
            ModelContract(name="User", fields=[{"name": "userId"}, {"name": "firstName"}, {"name": "lastName"}]),
        ]
        convention = detect_naming_convention(endpoints, models)
        assert convention == "camelCase"

    def test_empty_inputs(self):
        """Empty endpoints and models return a reasonable default."""
        convention = detect_naming_convention([], [])
        assert isinstance(convention, str)
        assert len(convention) > 0

    def test_mixed_convention(self):
        """Mixed naming still returns one of the valid convention strings."""
        endpoints = [
            EndpointContract(
                path="/api",
                method="GET",
                handler_name="get",
                controller_file="c.ts",
                request_params=[],
                request_body_fields=[{"name": "user_name"}, {"name": "lastName"}],
                response_fields=[{"name": "created_at"}, {"name": "updatedAt"}],
                response_type="Mixed",
            ),
        ]
        models = []
        convention = detect_naming_convention(endpoints, models)
        assert convention in ("snake_case", "camelCase", "mixed", "unknown")


# ===================================================================
# 7. JSON Round-Trip (save / load)
# ===================================================================


class TestJSONRoundTrip:
    """Verify APIContractBundle serialization and deserialization."""

    def _make_bundle(self) -> APIContractBundle:
        """Create a representative bundle for testing."""
        return APIContractBundle(
            version="1.0",
            extracted_from_milestone="milestone-1",
            endpoints=[
                EndpointContract(
                    path="/users",
                    method="GET",
                    handler_name="findAll",
                    controller_file="users.controller.ts",
                    request_params=["limit", "offset"],
                    request_body_fields=[],
                    response_fields=["id", "name", "email"],
                    response_type="User[]",
                ),
                EndpointContract(
                    path="/users",
                    method="POST",
                    handler_name="create",
                    controller_file="users.controller.ts",
                    request_params=[],
                    request_body_fields=["name", "email"],
                    response_fields=["id", "name", "email"],
                    response_type="User",
                ),
            ],
            models=[
                ModelContract(name="User", fields=["id", "name", "email", "createdAt"]),
            ],
            enums=[
                EnumContract(name="Role", values=["USER", "ADMIN"]),
            ],
            field_naming_convention="camelCase",
        )

    def test_save_load_roundtrip(self, tmp_path):
        """A populated bundle survives a save-then-load cycle."""
        bundle = self._make_bundle()
        path = tmp_path / "contracts.json"
        save_api_contracts(bundle, path)
        loaded = load_api_contracts(path)

        assert loaded is not None
        assert loaded.version == bundle.version
        assert loaded.extracted_from_milestone == bundle.extracted_from_milestone
        assert len(loaded.endpoints) == len(bundle.endpoints)
        assert len(loaded.models) == len(bundle.models)
        assert len(loaded.enums) == len(bundle.enums)
        assert loaded.field_naming_convention == bundle.field_naming_convention

    def test_endpoint_data_preserved(self, tmp_path):
        """Individual endpoint fields survive round-trip."""
        bundle = self._make_bundle()
        path = tmp_path / "contracts.json"
        save_api_contracts(bundle, path)
        loaded = load_api_contracts(path)

        ep = loaded.endpoints[0]
        assert ep.path == "/users"
        assert ep.method == "GET"
        assert ep.handler_name == "findAll"
        assert "limit" in ep.request_params

    def test_model_data_preserved(self, tmp_path):
        """Model fields survive round-trip."""
        bundle = self._make_bundle()
        path = tmp_path / "contracts.json"
        save_api_contracts(bundle, path)
        loaded = load_api_contracts(path)

        model = loaded.models[0]
        assert model.name == "User"
        assert "email" in model.fields

    def test_enum_data_preserved(self, tmp_path):
        """Enum values survive round-trip."""
        bundle = self._make_bundle()
        path = tmp_path / "contracts.json"
        save_api_contracts(bundle, path)
        loaded = load_api_contracts(path)

        enum = loaded.enums[0]
        assert enum.name == "Role"
        assert "USER" in enum.values
        assert "ADMIN" in enum.values

    def test_saved_file_is_valid_json(self, tmp_path):
        """The saved file is valid JSON and can be parsed by the stdlib."""
        bundle = self._make_bundle()
        path = tmp_path / "contracts.json"
        save_api_contracts(bundle, path)

        raw = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)

    def test_load_nonexistent_returns_none(self, tmp_path):
        """Loading a non-existent file returns None."""
        path = tmp_path / "nonexistent" / "contracts.json"
        result = load_api_contracts(path)
        assert result is None


# ===================================================================
# 8. Prompt Rendering
# ===================================================================


class TestPromptRendering:
    """Verify render_api_contracts_for_prompt output."""

    def _make_bundle(self) -> APIContractBundle:
        return APIContractBundle(
            version="1.0",
            extracted_from_milestone="milestone-1",
            endpoints=[
                EndpointContract(
                    path="/users",
                    method="GET",
                    handler_name="findAll",
                    controller_file="users.controller.ts",
                    request_params=[],
                    request_body_fields=[],
                    response_fields=[{"name": "id"}, {"name": "name"}],
                    response_type="User[]",
                ),
            ],
            models=[
                ModelContract(name="User", fields=[{"name": "id"}, {"name": "name"}]),
            ],
            enums=[],
            field_naming_convention="camelCase",
        )

    def test_renders_string(self):
        """The rendered output is a non-empty string."""
        bundle = self._make_bundle()
        rendered = render_api_contracts_for_prompt(bundle, max_chars=5000)
        assert isinstance(rendered, str)
        assert len(rendered) > 0

    def test_contains_endpoint_info(self):
        """The rendered output mentions the endpoint path."""
        bundle = self._make_bundle()
        rendered = render_api_contracts_for_prompt(bundle, max_chars=5000)
        assert "/users" in rendered

    def test_contains_model_info(self):
        """The rendered output mentions the model name."""
        bundle = self._make_bundle()
        rendered = render_api_contracts_for_prompt(bundle, max_chars=5000)
        assert "User" in rendered

    def test_respects_max_chars(self):
        """Output is truncated to stay within max_chars."""
        bundle = self._make_bundle()
        max_chars = 50
        rendered = render_api_contracts_for_prompt(bundle, max_chars=max_chars)
        assert len(rendered) <= max_chars + 100  # allow small overflow for truncation marker

    def test_large_bundle_truncated(self):
        """A large bundle gets truncated properly."""
        endpoints = [
            EndpointContract(
                path=f"/resource-{i}",
                method="GET",
                handler_name=f"handler_{i}",
                controller_file=f"controller_{i}.ts",
                request_params=[f"param_{j}" for j in range(10)],
                request_body_fields=[{"name": f"field_{j}"} for j in range(10)],
                response_fields=[{"name": f"resp_{j}"} for j in range(10)],
                response_type=f"Type{i}",
            )
            for i in range(100)
        ]
        bundle = APIContractBundle(
            version="1.0",
            extracted_from_milestone="ms-1",
            endpoints=endpoints,
            models=[],
            enums=[],
            field_naming_convention="camelCase",
        )
        rendered = render_api_contracts_for_prompt(bundle, max_chars=500)
        assert len(rendered) <= 600  # allow small overflow


# ===================================================================
# 9. Empty Project
# ===================================================================


class TestEmptyProject:
    """Graceful handling of empty project directories."""

    def test_extract_api_contracts_empty(self, tmp_path):
        """extract_api_contracts returns a valid bundle with empty lists."""
        bundle = extract_api_contracts(tmp_path, milestone_id="ms-1")
        assert isinstance(bundle, APIContractBundle)
        assert bundle.endpoints == []
        assert bundle.models == []
        assert bundle.enums == []

    def test_nestjs_empty(self, tmp_path):
        endpoints = extract_nestjs_endpoints(tmp_path)
        assert endpoints == []

    def test_express_empty(self, tmp_path):
        endpoints = extract_express_endpoints(tmp_path)
        assert endpoints == []

    def test_dto_fields_empty(self, tmp_path):
        fields = extract_dto_fields(tmp_path)
        assert isinstance(fields, dict)
        assert len(fields) == 0

    def test_prisma_models_empty(self, tmp_path):
        models = extract_prisma_models(tmp_path)
        assert models == []

    def test_prisma_enums_empty(self, tmp_path):
        enums = extract_prisma_enums(tmp_path)
        assert enums == []


# ===================================================================
# 10. Missing / Non-existent Paths
# ===================================================================


class TestMissingPaths:
    """Verify graceful handling of non-existent paths."""

    def test_load_missing_file(self, tmp_path):
        """Loading from a non-existent path returns None."""
        path = tmp_path / "does_not_exist" / "contracts.json"
        result = load_api_contracts(path)
        assert result is None

    def test_extract_from_nonexistent_root(self, tmp_path):
        """Extraction from a non-existent root returns empty results."""
        fake_root = tmp_path / "no_such_project"
        bundle = extract_api_contracts(fake_root, milestone_id="ms-1")
        assert isinstance(bundle, APIContractBundle)
        assert bundle.endpoints == []

    def test_prisma_models_nonexistent_root(self, tmp_path):
        fake_root = tmp_path / "no_such_project"
        models = extract_prisma_models(fake_root)
        assert models == []

    def test_prisma_enums_nonexistent_root(self, tmp_path):
        fake_root = tmp_path / "no_such_project"
        enums = extract_prisma_enums(fake_root)
        assert enums == []


# ===================================================================
# 11. EndpointContract / ModelContract / EnumContract Dataclass Tests
# ===================================================================


class TestDataclassConstruction:
    """Verify dataclass fields and construction."""

    def test_endpoint_contract_fields(self):
        ep = EndpointContract(
            path="/test",
            method="GET",
            handler_name="testHandler",
            controller_file="test.controller.ts",
            request_params=["id"],
            request_body_fields=["name"],
            response_fields=["result"],
            response_type="TestResponse",
        )
        assert ep.path == "/test"
        assert ep.method == "GET"
        assert ep.handler_name == "testHandler"
        assert ep.controller_file == "test.controller.ts"
        assert ep.request_params == ["id"]
        assert ep.request_body_fields == ["name"]
        assert ep.response_fields == ["result"]
        assert ep.response_type == "TestResponse"

    def test_model_contract_fields(self):
        model = ModelContract(name="User", fields=["id", "email"])
        assert model.name == "User"
        assert model.fields == ["id", "email"]

    def test_enum_contract_fields(self):
        enum = EnumContract(name="Status", values=["ACTIVE", "INACTIVE"])
        assert enum.name == "Status"
        assert enum.values == ["ACTIVE", "INACTIVE"]

    def test_api_contract_bundle_fields(self):
        bundle = APIContractBundle(
            version="1.0",
            extracted_from_milestone="ms-1",
            endpoints=[],
            models=[],
            enums=[],
            field_naming_convention="camelCase",
        )
        assert bundle.version == "1.0"
        assert bundle.extracted_from_milestone == "ms-1"
        assert bundle.field_naming_convention == "camelCase"
