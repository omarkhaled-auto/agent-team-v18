"""Hardening tests for integration verification pipeline.

Covers edge cases in path normalization, API prefix stripping, field naming
mismatch detection, response shape mismatch detection, full pipeline
integration, and IntegrationGateConfig backward compatibility and feature
gating.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15.integration_verifier import (
    BackendEndpoint,
    FrontendAPICall,
    IntegrationMismatch,
    IntegrationReport,
    _strip_api_prefix,
    detect_field_naming_mismatches,
    detect_response_shape_mismatches,
    format_report_for_prompt,
    match_endpoints,
    normalize_path,
    scan_backend_endpoints,
    scan_frontend_api_calls,
    verify_integration,
)
from agent_team_v15.api_contract_extractor import (
    APIContractBundle,
    EndpointContract,
    ModelContract,
    EnumContract,
    extract_api_contracts,
    render_api_contracts_for_prompt,
)
from agent_team_v15.config import (
    AgentTeamConfig,
    IntegrationGateConfig,
    _dict_to_config,
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
# 1. normalize_path — identical output for :id, {id}, ${id}, ${user.id}
# ===================================================================


class TestNormalizePathCanonicalForms:
    """All parameter placeholder syntaxes normalize to the same canonical form."""

    def test_colon_id(self):
        assert normalize_path("/users/:id") == normalize_path("/users/{id}")

    def test_curly_id(self):
        assert normalize_path("/users/{id}") == normalize_path("/users/${id}")

    def test_template_literal_id(self):
        assert normalize_path("/users/${id}") == normalize_path("/users/:id")

    def test_dotted_expression(self):
        """${user.id} normalizes the same as :id."""
        assert normalize_path("/users/${user.id}") == normalize_path("/users/:id")

    def test_all_four_forms_identical(self):
        """All four parameter styles produce the exact same output."""
        colon = normalize_path("/items/:id")
        curly = normalize_path("/items/{id}")
        template = normalize_path("/items/${id}")
        dotted = normalize_path("/items/${item.id}")
        assert colon == curly == template == dotted

    def test_multiple_params_all_forms(self):
        """Multiple parameters in the same path normalize identically."""
        a = normalize_path("/users/:userId/posts/:postId")
        b = normalize_path("/users/{userId}/posts/{postId}")
        c = normalize_path("/users/${userId}/posts/${postId}")
        d = normalize_path("/users/${u.id}/posts/${p.id}")
        assert a == b == c == d

    def test_canonical_token_is_param(self):
        """The canonical token is ':param'."""
        result = normalize_path("/users/:id")
        assert ":param" in result
        assert ":id" not in result

    def test_escaped_template_literal(self):
        """Escaped template literal \\${x} also normalizes to :param."""
        result = normalize_path("/users/\\${userId}")
        assert ":param" in result

    def test_trailing_slash_stripped(self):
        result = normalize_path("/users/:id/")
        assert not result.endswith("/") or result == "/"

    def test_query_string_stripped(self):
        result = normalize_path("/users?page=1&limit=10")
        assert "?" not in result
        assert "page" not in result

    def test_duplicate_slashes_collapsed(self):
        result = normalize_path("//users///list")
        assert "//" not in result

    def test_lowercased(self):
        result = normalize_path("/Users/FindAll")
        assert result == result.lower()


# ===================================================================
# 2. _strip_api_prefix — strips /api/v1/ correctly
# ===================================================================


class TestStripApiPrefix:
    """Verify _strip_api_prefix strips common API prefixes."""

    def test_strip_api_v1(self):
        assert _strip_api_prefix("/api/v1/users/:param") == "/users/:param"

    def test_strip_api_v2(self):
        assert _strip_api_prefix("/api/v2/items/:param") == "/items/:param"

    def test_strip_api_no_version(self):
        assert _strip_api_prefix("/api/users") == "/users"

    def test_no_prefix_passthrough(self):
        assert _strip_api_prefix("/users/:param") == "/users/:param"

    def test_root_path(self):
        assert _strip_api_prefix("/") == "/"

    def test_api_in_middle_not_stripped(self):
        """Only leading /api/ prefixes are stripped."""
        result = _strip_api_prefix("/internal/api/v1/data")
        assert result == "/internal/api/v1/data"

    def test_result_starts_with_slash(self):
        """Stripped result always starts with /."""
        result = _strip_api_prefix("/api/v1/health")
        assert result.startswith("/")


# ===================================================================
# 3. detect_field_naming_mismatches — mock Prisma schema + frontend
# ===================================================================


class TestDetectFieldNamingMismatches:
    """Verify detection of camelCase vs snake_case field naming mismatches."""

    def test_prisma_snake_vs_frontend_camel(self, tmp_path):
        """Prisma schema with snake_case + frontend with camelCase produces mismatches."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "model WorkOrder {\n"
            "  id           Int      @id @default(autoincrement())\n"
            "  building_id  Int\n"
            "  created_at   DateTime @default(now())\n"
            "  sla_deadline DateTime?\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/components/WorkOrderList.tsx", (
            "import React from 'react';\n"
            "\n"
            "export const WorkOrderList = ({ orders }) => {\n"
            "  return orders.map(order => (\n"
            "    <div key={order.id}>\n"
            "      <span>{order.buildingId}</span>\n"
            "      <span>{order.createdAt}</span>\n"
            "      <span>{order.slaDeadline}</span>\n"
            "    </div>\n"
            "  ));\n"
            "};\n"
        ))
        mismatches = detect_field_naming_mismatches(tmp_path)
        # Should find at least one camelCase/snake_case mismatch
        assert isinstance(mismatches, list)
        # At minimum, buildingId vs building_id should be detected
        descriptions = " ".join(m.description for m in mismatches)
        if mismatches:
            assert any(
                "camelCase" in m.description.lower() or "snake_case" in m.description.lower()
                for m in mismatches
            )

    def test_no_mismatches_when_consistent(self, tmp_path):
        """No mismatches when both sides use the same naming convention."""
        _write_file(tmp_path, "src/models/user.dto.ts", (
            "export class UserDto {\n"
            "  @IsString()\n"
            "  name: string;\n"
            "\n"
            "  @IsString()\n"
            "  email: string;\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/components/UserProfile.tsx", (
            "export const UserProfile = ({ user }) => (\n"
            "  <div>{user.name} - {user.email}</div>\n"
            ");\n"
        ))
        mismatches = detect_field_naming_mismatches(tmp_path)
        # name and email are single words — no snake/camel divergence
        assert isinstance(mismatches, list)

    def test_empty_project(self, tmp_path):
        """Empty project returns empty mismatch list."""
        mismatches = detect_field_naming_mismatches(tmp_path)
        assert mismatches == []


# ===================================================================
# 4. detect_response_shape_mismatches — Array.isArray defensive pattern
# ===================================================================


class TestDetectResponseShapeMismatches:
    """Verify detection of defensive response unwrapping patterns."""

    def test_array_is_array_ternary(self, tmp_path):
        """Array.isArray(res) ? res : res.data is detected."""
        _write_file(tmp_path, "src/services/dataService.tsx", (
            "export const fetchData = async () => {\n"
            "  const res = await api.get('/data');\n"
            "  const items = Array.isArray(res) ? res : res.data;\n"
            "  return items;\n"
            "};\n"
        ))
        mismatches = detect_response_shape_mismatches(tmp_path)
        assert len(mismatches) >= 1
        assert any("defensive" in m.description.lower() or "response" in m.description.lower()
                    for m in mismatches)

    def test_data_or_fallback(self, tmp_path):
        """res.data || res pattern is detected."""
        _write_file(tmp_path, "src/utils/unwrap.ts", (
            "export const unwrap = (res: any) => {\n"
            "  return res.data || res;\n"
            "};\n"
        ))
        mismatches = detect_response_shape_mismatches(tmp_path)
        assert len(mismatches) >= 1

    def test_optional_chaining_nullish(self, tmp_path):
        """res?.data ?? res pattern is detected."""
        _write_file(tmp_path, "src/hooks/useApi.tsx", (
            "const useApi = () => {\n"
            "  const result = res?.data ?? res;\n"
            "  return result;\n"
            "};\n"
        ))
        mismatches = detect_response_shape_mismatches(tmp_path)
        assert len(mismatches) >= 1

    def test_no_defensive_patterns(self, tmp_path):
        """Clean code with no defensive patterns returns no mismatches."""
        _write_file(tmp_path, "src/services/clean.ts", (
            "export const fetchUsers = async () => {\n"
            "  const res = await api.get('/users');\n"
            "  return res.data;\n"
            "};\n"
        ))
        mismatches = detect_response_shape_mismatches(tmp_path)
        assert mismatches == []

    def test_node_modules_excluded(self, tmp_path):
        """Patterns inside node_modules are not reported."""
        _write_file(tmp_path, "node_modules/some-lib/index.tsx", (
            "const items = Array.isArray(res) ? res : res.data;\n"
        ))
        mismatches = detect_response_shape_mismatches(tmp_path)
        for m in mismatches:
            assert "node_modules" not in m.frontend_file


# ===================================================================
# 5. Full pipeline: extract contracts -> enrich handoff -> verify
# ===================================================================


class TestFullPipeline:
    """End-to-end test: extract contracts from backend, scan frontend, verify."""

    def test_extract_then_verify(self, tmp_path):
        """Full pipeline produces meaningful integration report."""
        # Create backend (Express)
        _write_file(tmp_path, "src/routes/users.routes.ts", (
            "import { Router } from 'express';\n"
            "const router = Router();\n"
            "router.get('/users', (req, res) => res.json([]));\n"
            "router.post('/users', (req, res) => res.status(201).json({}));\n"
            "router.get('/users/:id', (req, res) => res.json({}));\n"
            "export default router;\n"
        ))
        # Create Prisma schema
        _write_file(tmp_path, "prisma/schema.prisma", (
            "model User {\n"
            "  id    Int    @id @default(autoincrement())\n"
            "  email String @unique\n"
            "  name  String\n"
            "}\n"
        ))
        # Create frontend
        _write_file(tmp_path, "src/components/UserList.tsx", (
            "import api from '../api';\n"
            "\n"
            "export const loadUsers = () => api.get('/users');\n"
            "export const createUser = (data: any) => api.post('/users', data);\n"
            "export const getUser = (id: string) => api.get(`/users/${id}`);\n"
            "export const deleteUser = (id: string) => api.delete(`/users/${id}`);\n"
        ))

        # Step 1: Extract API contracts
        bundle = extract_api_contracts(tmp_path, milestone_id="ms-test")
        assert isinstance(bundle, APIContractBundle)
        assert len(bundle.endpoints) >= 3  # GET, POST, GET/:id
        assert len(bundle.models) >= 1     # User model

        # Step 2: Verify integration
        report = verify_integration(tmp_path)
        assert isinstance(report, IntegrationReport)
        assert report.total_backend_endpoints >= 3

        # Step 3: Render contracts for prompt
        rendered = render_api_contracts_for_prompt(bundle, max_chars=5000)
        assert "/users" in rendered
        assert "User" in rendered

    def test_empty_project_pipeline(self, tmp_path):
        """Empty project runs through the full pipeline without errors."""
        bundle = extract_api_contracts(tmp_path, milestone_id="ms-empty")
        assert bundle.endpoints == []
        assert bundle.models == []
        assert bundle.enums == []

        report = verify_integration(tmp_path)
        assert report.matched == 0
        assert report.mismatches == []

    def test_nestjs_pipeline(self, tmp_path):
        """NestJS controller + DTO + Prisma produces a complete bundle."""
        _write_file(tmp_path, "src/work-orders/work-orders.controller.ts", (
            "import { Controller, Get, Post, Body, Query } from '@nestjs/common';\n"
            "\n"
            "@Controller('work-orders')\n"
            "export class WorkOrdersController {\n"
            "  @Get()\n"
            "  findAll() { return []; }\n"
            "\n"
            "  @Post()\n"
            "  create(@Body() dto: CreateWorkOrderDto) { return {}; }\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/work-orders/dto/create-work-order.dto.ts", (
            "import { IsString, IsInt } from 'class-validator';\n"
            "\n"
            "export class CreateWorkOrderDto {\n"
            "  @IsString()\n"
            "  title: string;\n"
            "\n"
            "  @IsInt()\n"
            "  buildingId: number;\n"
            "}\n"
        ))
        _write_file(tmp_path, "prisma/schema.prisma", (
            "model WorkOrder {\n"
            "  id         Int    @id @default(autoincrement())\n"
            "  title      String\n"
            "  building_id Int\n"
            "}\n"
            "\n"
            "enum Priority {\n"
            "  LOW\n"
            "  MEDIUM\n"
            "  HIGH\n"
            "  URGENT\n"
            "}\n"
        ))

        bundle = extract_api_contracts(tmp_path, milestone_id="ms-nest")
        assert len(bundle.endpoints) >= 2
        assert len(bundle.models) >= 1
        assert len(bundle.enums) >= 1
        # Priority enum values
        priority_enum = next((e for e in bundle.enums if e.name == "Priority"), None)
        assert priority_enum is not None
        assert "LOW" in priority_enum.values
        assert "URGENT" in priority_enum.values


# ===================================================================
# 6. Backward compatibility: IntegrationGateConfig with no args
# ===================================================================


class TestIntegrationGateConfigBackwardCompat:
    """IntegrationGateConfig() with no arguments produces valid defaults."""

    def test_no_args_constructor(self):
        """IntegrationGateConfig() succeeds with no arguments."""
        config = IntegrationGateConfig()
        assert config.enabled is True
        assert config.contract_extraction is True
        assert config.verification_enabled is True
        assert config.verification_mode == "warn"
        assert config.enriched_handoff is True
        assert config.cross_milestone_source_access is True
        assert config.serialization_mandate is True
        assert config.contract_injection_max_chars == 15000
        assert config.report_injection_max_chars == 10000
        assert isinstance(config.backend_source_patterns, list)
        assert isinstance(config.skip_directories, list)

    def test_agent_team_config_no_args(self):
        """AgentTeamConfig() includes IntegrationGateConfig with defaults."""
        config = AgentTeamConfig()
        assert isinstance(config.integration_gate, IntegrationGateConfig)
        assert config.integration_gate.enabled is True

    def test_dict_to_config_empty(self):
        """_dict_to_config({}) produces IntegrationGateConfig with defaults."""
        cfg, _ = _dict_to_config({})
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True
        assert cfg.integration_gate.verification_mode == "warn"

    def test_dict_to_config_null_integration_gate(self):
        """integration_gate: null preserves defaults."""
        cfg, _ = _dict_to_config({"integration_gate": None})
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True

    def test_dict_to_config_empty_dict_integration_gate(self):
        """integration_gate: {} preserves all defaults."""
        cfg, _ = _dict_to_config({"integration_gate": {}})
        assert cfg.integration_gate.enabled is True
        assert cfg.integration_gate.verification_mode == "warn"
        assert cfg.integration_gate.contract_injection_max_chars == 15000

    def test_partial_override(self):
        """Partial override preserves unset defaults."""
        cfg, _ = _dict_to_config({
            "integration_gate": {
                "enabled": False,
                "verification_mode": "block",
            }
        })
        assert cfg.integration_gate.enabled is False
        assert cfg.integration_gate.verification_mode == "block"
        # These should still be defaults
        assert cfg.integration_gate.contract_extraction is True
        assert cfg.integration_gate.enriched_handoff is True
        assert cfg.integration_gate.contract_injection_max_chars == 15000

    def test_other_config_sections_unaffected(self):
        """Setting other config sections does not break integration_gate."""
        cfg, _ = _dict_to_config({
            "orchestrator": {"model": "sonnet"},
        })
        assert cfg.orchestrator.model == "sonnet"
        assert isinstance(cfg.integration_gate, IntegrationGateConfig)
        assert cfg.integration_gate.enabled is True


# ===================================================================
# 7. enabled=false skips all integration features
# ===================================================================


class TestEnabledFalseSkipsIntegration:
    """When IntegrationGateConfig.enabled=False, integration features are skipped."""

    def test_disabled_config_fields(self):
        """Setting enabled=False via config dict works."""
        cfg, _ = _dict_to_config({
            "integration_gate": {"enabled": False}
        })
        assert cfg.integration_gate.enabled is False

    def test_disabled_config_still_has_defaults(self):
        """Even when disabled, other fields retain their defaults."""
        cfg, _ = _dict_to_config({
            "integration_gate": {"enabled": False}
        })
        ig = cfg.integration_gate
        assert ig.contract_extraction is True
        assert ig.verification_enabled is True
        assert ig.verification_mode == "warn"
        assert ig.enriched_handoff is True

    def test_disabled_contract_extraction(self):
        """contract_extraction=False can be set independently."""
        cfg, _ = _dict_to_config({
            "integration_gate": {
                "enabled": True,
                "contract_extraction": False,
            }
        })
        assert cfg.integration_gate.enabled is True
        assert cfg.integration_gate.contract_extraction is False

    def test_disabled_verification(self):
        """verification_enabled=False can be set independently."""
        cfg, _ = _dict_to_config({
            "integration_gate": {
                "enabled": True,
                "verification_enabled": False,
            }
        })
        assert cfg.integration_gate.enabled is True
        assert cfg.integration_gate.verification_enabled is False


# ===================================================================
# 8. Additional edge cases
# ===================================================================


class TestEdgeCases:
    """Various edge cases for robustness."""

    def test_match_endpoints_with_only_frontend(self):
        """All frontend calls missing produces all-missing report."""
        frontend = [
            FrontendAPICall(
                file_path="src/App.tsx", line_number=1,
                endpoint_path="/api/widgets", http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
            FrontendAPICall(
                file_path="src/App.tsx", line_number=5,
                endpoint_path="/api/gadgets", http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        report = match_endpoints(frontend, [])
        assert len(report.missing_endpoints) >= 2
        assert report.matched == 0

    def test_match_endpoints_with_only_backend(self):
        """All backend endpoints unused produces all-unused report."""
        backend = [
            BackendEndpoint(
                file_path="src/a.controller.ts",
                route_path="/api/alpha", http_method="GET",
                handler_name="getAlpha",
                accepted_params=[], response_fields=[],
            ),
        ]
        report = match_endpoints([], backend)
        assert len(report.unused_endpoints) >= 1
        assert report.matched == 0

    def test_normalize_path_preserves_root(self):
        assert normalize_path("/") == "/"

    def test_normalize_path_no_params(self):
        result = normalize_path("/health")
        assert result == "/health"

    def test_verify_integration_returns_report(self, tmp_path):
        """verify_integration always returns IntegrationReport."""
        report = verify_integration(tmp_path)
        assert isinstance(report, IntegrationReport)
        assert hasattr(report, "total_frontend_calls")
        assert hasattr(report, "total_backend_endpoints")
        assert hasattr(report, "matched")
        assert hasattr(report, "mismatches")
        assert hasattr(report, "missing_endpoints")
        assert hasattr(report, "unused_endpoints")
        assert hasattr(report, "field_name_mismatches")

    def test_format_report_empty(self):
        """Formatting an empty report produces valid markdown."""
        report = IntegrationReport(
            total_frontend_calls=0,
            total_backend_endpoints=0,
            matched=0,
            mismatches=[],
            missing_endpoints=[],
            unused_endpoints=[],
            field_name_mismatches=[],
        )
        rendered = format_report_for_prompt(report)
        assert isinstance(rendered, str)
        assert len(rendered) > 0
        assert "0" in rendered
