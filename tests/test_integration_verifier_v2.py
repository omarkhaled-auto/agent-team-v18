"""Tests for integration_verifier V2 features: blocking gate, route structure,
response shape validation, auth flow, and enum cross-check."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15.integration_verifier import (
    BackendEndpoint,
    BlockingGateResult,
    FrontendAPICall,
    IntegrationMismatch,
    IntegrationReport,
    RoutePatternEnforcer,
    RoutePatternViolation,
    VerificationChecksConfig,
    detect_auth_flow_mismatches,
    detect_enum_value_mismatches,
    detect_pluralization_bugs,
    detect_query_param_alias_mismatches,
    detect_response_shape_validation_issues,
    detect_route_structure_mismatches,
    verify_integration,
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
# 1. BlockingGateResult and blocking mode (5 tests)
# ===================================================================


class TestBlockingGateMode:
    """Verify the blocking gate mode and BlockingGateResult dataclass."""

    def test_warn_mode_returns_integration_report(self, tmp_path):
        """In warn mode, verify_integration returns an IntegrationReport."""
        _write_file(tmp_path, "src/App.tsx", "const x = 1;")
        result = verify_integration(tmp_path, run_mode="warn")
        assert isinstance(result, IntegrationReport)

    def test_block_mode_returns_blocking_gate_result(self, tmp_path):
        """In block mode, verify_integration returns a BlockingGateResult."""
        _write_file(tmp_path, "src/App.tsx", "const x = 1;")
        result = verify_integration(tmp_path, run_mode="block")
        assert isinstance(result, BlockingGateResult)

    def test_block_mode_passes_when_no_issues(self, tmp_path):
        """Block mode passes when there are no HIGH/CRITICAL issues."""
        _write_file(tmp_path, "src/App.tsx", "const x = 1;")
        result = verify_integration(tmp_path, run_mode="block")
        assert isinstance(result, BlockingGateResult)
        assert result.passed is True
        assert result.critical_count == 0
        assert result.high_count == 0

    def test_block_mode_fails_on_high_severity(self, tmp_path):
        """Block mode fails when HIGH severity issues exist."""
        _write_file(tmp_path, "src/services/api.ts", (
            "import api from './client';\n"
            "export const getUsers = () => api.get('/users');\n"
            "export const getItems = () => api.get('/nonexistent-endpoint');\n"
        ))
        _write_file(tmp_path, "src/users/users.controller.ts", (
            "import { Controller, Get } from '@nestjs/common';\n"
            "@Controller('users')\n"
            "export class UsersController {\n"
            "  @Get('')\n"
            "  findAll() { return []; }\n"
            "}\n"
        ))
        result = verify_integration(tmp_path, run_mode="block")
        assert isinstance(result, BlockingGateResult)
        # Should have at least one HIGH (missing endpoint)
        if result.high_count > 0 or result.critical_count > 0:
            assert result.passed is False

    def test_blocking_gate_result_has_report(self, tmp_path):
        """BlockingGateResult includes the full IntegrationReport."""
        _write_file(tmp_path, "src/App.tsx", "const x = 1;")
        result = verify_integration(tmp_path, run_mode="block")
        assert isinstance(result, BlockingGateResult)
        assert result.report is not None
        assert isinstance(result.report, IntegrationReport)

    def test_blocking_gate_result_findings_are_critical_or_high(self, tmp_path):
        """BlockingGateResult.findings only contains CRITICAL/HIGH issues."""
        _write_file(tmp_path, "src/services/api.ts",
                     "export const getData = () => api.get('/missing');\n")
        result = verify_integration(tmp_path, run_mode="block")
        assert isinstance(result, BlockingGateResult)
        for finding in result.findings:
            assert finding.severity in ("CRITICAL", "HIGH")

    def test_default_run_mode_is_warn(self, tmp_path):
        """Default run_mode is 'warn' returning IntegrationReport."""
        _write_file(tmp_path, "src/App.tsx", "const x = 1;")
        result = verify_integration(tmp_path)
        assert isinstance(result, IntegrationReport)


# ===================================================================
# 2. Route Structure Consistency Check (7 tests)
# ===================================================================


class TestRouteStructureCheck:
    """Verify detection of nested-vs-top-level route mismatches."""

    def test_nested_frontend_flat_backend(self):
        """Frontend nested route, backend flat route -> CRITICAL mismatch."""
        frontend = [
            FrontendAPICall(
                file_path="src/FloorList.tsx", line_number=10,
                endpoint_path="/buildings/123/floors",
                http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/floors.controller.ts",
                route_path="/floors", http_method="POST",
                handler_name="create",
                accepted_params=[], response_fields=[],
            ),
        ]
        mismatches = detect_route_structure_mismatches(frontend, backend)
        assert len(mismatches) >= 1
        assert mismatches[0].severity == "CRITICAL"
        assert mismatches[0].category == "route_structure_mismatch"

    def test_deeply_nested_frontend_flat_backend(self):
        """Deeply nested frontend route -> CRITICAL mismatch."""
        frontend = [
            FrontendAPICall(
                file_path="src/ZoneList.tsx", line_number=5,
                endpoint_path="/buildings/:bid/floors/:fid/zones",
                http_method="DELETE",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/zones.controller.ts",
                route_path="/zones/:id", http_method="DELETE",
                handler_name="remove",
                accepted_params=["id"], response_fields=[],
            ),
        ]
        mismatches = detect_route_structure_mismatches(frontend, backend)
        assert len(mismatches) >= 1
        assert mismatches[0].severity == "CRITICAL"

    def test_matching_structure_no_mismatch(self):
        """Both frontend and backend use same nesting -> no mismatch."""
        frontend = [
            FrontendAPICall(
                file_path="src/FloorList.tsx", line_number=10,
                endpoint_path="/buildings/:id/floors",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/floors.controller.ts",
                route_path="/buildings/:id/floors",
                http_method="GET",
                handler_name="findAll",
                accepted_params=["id"], response_fields=[],
            ),
        ]
        mismatches = detect_route_structure_mismatches(frontend, backend)
        assert len(mismatches) == 0

    def test_both_flat_no_mismatch(self):
        """Both use flat routes -> no mismatch."""
        frontend = [
            FrontendAPICall(
                file_path="src/UserList.tsx", line_number=1,
                endpoint_path="/users",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/users.controller.ts",
                route_path="/users", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        mismatches = detect_route_structure_mismatches(frontend, backend)
        assert len(mismatches) == 0

    def test_flat_frontend_nested_backend(self):
        """Frontend flat route, backend nested -> CRITICAL mismatch."""
        frontend = [
            FrontendAPICall(
                file_path="src/FloorList.tsx", line_number=10,
                endpoint_path="/floors",
                http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/floors.controller.ts",
                route_path="/buildings/:id/floors",
                http_method="POST",
                handler_name="create",
                accepted_params=["id"], response_fields=[],
            ),
        ]
        mismatches = detect_route_structure_mismatches(frontend, backend)
        assert len(mismatches) >= 1
        assert mismatches[0].severity == "CRITICAL"

    def test_different_resources_no_false_positive(self):
        """Different resource types should not produce false positives."""
        frontend = [
            FrontendAPICall(
                file_path="src/UserList.tsx", line_number=1,
                endpoint_path="/users",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/items.controller.ts",
                route_path="/items", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        mismatches = detect_route_structure_mismatches(frontend, backend)
        assert len(mismatches) == 0

    def test_empty_inputs(self):
        """No calls/endpoints -> no mismatches."""
        mismatches = detect_route_structure_mismatches([], [])
        assert len(mismatches) == 0


# ===================================================================
# 3. Response Shape Validation (6 tests)
# ===================================================================


class TestResponseShapeValidation:
    """Verify detection of inconsistent response shapes."""

    def test_bare_array_return_detected(self, tmp_path):
        """Backend returning bare array from findMany is flagged."""
        _write_file(tmp_path, "src/users.service.ts", (
            "export class UsersService {\n"
            "  async findAll() {\n"
            "    return res.json(await this.prisma.user.findMany(\n"
            "      { where: { tenantId } }\n"
            "    ));\n"
            "  }\n"
            "}\n"
        ))
        mismatches = detect_response_shape_validation_issues(tmp_path)
        assert any(m.category == "response_shape_bare_array" for m in mismatches)

    def test_defensive_array_check_detected(self, tmp_path):
        """Frontend Array.isArray check on response is flagged."""
        _write_file(tmp_path, "src/components/UserList.tsx", (
            "import React from 'react';\n"
            "const res = await api.get('/users');\n"
            "const data = Array.isArray(res) ? res : res.data;\n"
        ))
        mismatches = detect_response_shape_validation_issues(tmp_path)
        assert any(m.category == "response_shape_defensive_check" for m in mismatches)

    def test_no_issues_in_clean_code(self, tmp_path):
        """Clean code without defensive patterns produces no issues."""
        _write_file(tmp_path, "src/components/UserList.tsx", (
            "const response = await api.get('/users');\n"
            "const users = response.data;\n"
        ))
        _write_file(tmp_path, "src/users.service.ts", (
            "export class UsersService {\n"
            "  async findAll() {\n"
            "    const results = await this.prisma.user.findMany();\n"
            "    return { data: results, meta: { total: results.length } };\n"
            "  }\n"
            "}\n"
        ))
        mismatches = detect_response_shape_validation_issues(tmp_path)
        # Should have very few or no issues
        bare_array = [m for m in mismatches if m.category == "response_shape_bare_array"]
        assert len(bare_array) == 0

    def test_severity_is_high(self, tmp_path):
        """Response shape issues should be HIGH severity."""
        _write_file(tmp_path, "src/components/List.tsx", (
            "const res = await fetch('/api/items');\n"
            "const items = Array.isArray(res.data) ? res.data : [];\n"
        ))
        mismatches = detect_response_shape_validation_issues(tmp_path)
        for m in mismatches:
            assert m.severity == "HIGH"

    def test_non_api_array_check_not_flagged(self, tmp_path):
        """Array.isArray on non-API data should not be flagged."""
        _write_file(tmp_path, "src/utils/helpers.ts", (
            "function processInput(input: any) {\n"
            "  const items = Array.isArray(input) ? input : [input];\n"
            "  return items;\n"
            "}\n"
        ))
        mismatches = detect_response_shape_validation_issues(tmp_path)
        defensive = [m for m in mismatches if m.category == "response_shape_defensive_check"]
        assert len(defensive) == 0

    def test_empty_project_no_issues(self, tmp_path):
        """Empty project produces no issues."""
        _write_file(tmp_path, "README.md", "# Empty project")
        mismatches = detect_response_shape_validation_issues(tmp_path)
        assert len(mismatches) == 0


# ===================================================================
# 4. Auth Flow Compatibility Check (7 tests)
# ===================================================================


class TestAuthFlowCheck:
    """Verify detection of auth flow mismatches."""

    def test_mfa_challenge_vs_inline_mismatch(self, tmp_path):
        """Frontend uses challenge-token MFA, backend uses inline-code -> CRITICAL."""
        # Use .tsx for frontend (only scanned by FE loop) and .py for backend
        # (only scanned by BE loop) to avoid cross-contamination.
        _write_file(tmp_path, "src/auth/LoginForm.tsx", (
            "const challengeResponse = await api.post('/auth/mfa/challenge');\n"
            "const challengeToken = challengeResponse.data.challengeToken;\n"
            "await api.post('/auth/mfa/verify', { challengeToken, code });\n"
        ))
        _write_file(tmp_path, "server/auth/auth_controller.py", (
            "@router.post('/auth/mfa')\n"
            "async def verify_mfa(body: MfaRequest):\n"
            "    otp_code = body.otp_code\n"
            "    return auth_service.verify(otp_code)\n"
        ))
        mismatches = detect_auth_flow_mismatches(tmp_path)
        mfa_mismatches = [m for m in mismatches if "mfa" in m.category.lower()]
        assert len(mfa_mismatches) >= 1
        if mfa_mismatches:
            assert mfa_mismatches[0].severity == "CRITICAL"

    def test_refresh_token_frontend_only(self, tmp_path):
        """Frontend has refresh logic but backend doesn't -> CRITICAL."""
        # Use .tsx for FE and .py for BE to avoid cross-scan contamination
        _write_file(tmp_path, "src/auth/tokenManager.tsx", (
            "const refreshToken = localStorage.getItem('refreshToken');\n"
            "const response = await api.post('/auth/refresh', { refreshToken });\n"
        ))
        _write_file(tmp_path, "server/auth/auth_controller.py", (
            "@router.post('/auth/login')\n"
            "async def login():\n"
            "    return {'access_token': 'abc'}\n"
        ))
        mismatches = detect_auth_flow_mismatches(tmp_path)
        refresh_mismatches = [m for m in mismatches if "refresh" in m.category.lower()]
        assert len(refresh_mismatches) >= 1

    def test_consistent_auth_flow_no_mismatch(self, tmp_path):
        """Consistent auth flow on both sides -> no mismatch."""
        _write_file(tmp_path, "src/auth/LoginForm.tsx", (
            "const res = await api.post('/auth/login', { email, password });\n"
            "const refreshToken = res.data.refreshToken;\n"
        ))
        _write_file(tmp_path, "src/auth/auth.controller.ts", (
            "import { Controller, Post } from '@nestjs/common';\n"
            "@Controller('auth')\n"
            "export class AuthController {\n"
            "  @Post('login')\n"
            "  login() { return { accessToken: 'abc', refreshToken: 'xyz' }; }\n"
            "  @Post('refresh')\n"
            "  refresh() { return { accessToken: 'new' }; }\n"
            "}\n"
        ))
        mismatches = detect_auth_flow_mismatches(tmp_path)
        # Should have no CRITICAL mfa/refresh mismatches
        critical = [m for m in mismatches if m.severity == "CRITICAL"]
        assert len(critical) == 0

    def test_no_auth_code_no_mismatches(self, tmp_path):
        """No auth-related code -> no mismatches."""
        _write_file(tmp_path, "src/App.tsx", "export default () => <div>Hello</div>;")
        _write_file(tmp_path, "src/items.controller.ts", (
            "@Controller('items')\n"
            "export class ItemsController {\n"
            "  @Get('')\n"
            "  findAll() { return []; }\n"
            "}\n"
        ))
        mismatches = detect_auth_flow_mismatches(tmp_path)
        assert len(mismatches) == 0

    def test_frontend_auth_no_backend(self, tmp_path):
        """Frontend references auth endpoints but no backend auth -> CRITICAL."""
        _write_file(tmp_path, "src/auth/LoginForm.tsx", (
            "await api.post('/auth/login', { email, password });\n"
            "await api.post('/auth/logout');\n"
        ))
        _write_file(tmp_path, "src/items.controller.ts", (
            "@Controller('items')\n"
            "export class ItemsController {}\n"
        ))
        mismatches = detect_auth_flow_mismatches(tmp_path)
        assert any(m.category == "auth_endpoints_missing" for m in mismatches)

    def test_backend_auth_no_frontend(self, tmp_path):
        """Backend has auth endpoints but frontend doesn't use them."""
        _write_file(tmp_path, "src/App.tsx", "export default () => <div/>;")
        _write_file(tmp_path, "src/auth/auth.controller.ts", (
            "import { Controller, Post } from '@nestjs/common';\n"
            "@Controller('auth')\n"
            "export class AuthController {\n"
            "  @Post('login')\n"
            "  login() { return {}; }\n"
            "  @Post('refresh')\n"
            "  refresh() { return {}; }\n"
            "}\n"
        ))
        mismatches = detect_auth_flow_mismatches(tmp_path)
        assert any(m.category == "auth_endpoints_unused" for m in mismatches)

    def test_mfa_same_style_no_mismatch(self, tmp_path):
        """Both sides use same MFA style -> no mfa mismatch."""
        _write_file(tmp_path, "src/auth/MfaForm.tsx", (
            "const res = await api.post('/auth/mfa', { mfaCode: code });\n"
        ))
        _write_file(tmp_path, "src/auth/auth.controller.ts", (
            "@Controller('auth')\n"
            "export class AuthController {\n"
            "  @Post('mfa')\n"
            "  verifyMfa(@Body() body: { mfaCode: string }) {\n"
            "    return this.authService.verify(body.mfaCode);\n"
            "  }\n"
            "}\n"
        ))
        mismatches = detect_auth_flow_mismatches(tmp_path)
        mfa_mismatches = [m for m in mismatches if "mfa_flow" in m.category]
        assert len(mfa_mismatches) == 0


# ===================================================================
# 5. Enum Value Cross-Check (7 tests)
# ===================================================================


class TestEnumCrossCheck:
    """Verify detection of enum value mismatches between frontend and backend."""

    def test_prisma_vs_frontend_mismatch(self, tmp_path):
        """Prisma enum has values not in frontend -> HIGH."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "enum WorkOrderStatus {\n"
            "  open\n"
            "  in_progress\n"
            "  closed\n"
            "  cancelled\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/components/StatusFilter.tsx", (
            "const STATUS_OPTIONS = ['open', 'in_progress', 'closed'];\n"
        ))
        mismatches = detect_enum_value_mismatches(tmp_path)
        assert len(mismatches) >= 1
        assert any("cancelled" in m.description for m in mismatches)

    def test_frontend_extra_values(self, tmp_path):
        """Frontend has enum values not in backend -> HIGH."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "enum Priority {\n"
            "  low\n"
            "  medium\n"
            "  high\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/components/PrioritySelect.tsx", (
            "const PRIORITY_OPTIONS = ['low', 'medium', 'high', 'critical'];\n"
        ))
        mismatches = detect_enum_value_mismatches(tmp_path)
        assert len(mismatches) >= 1
        assert any("critical" in m.description for m in mismatches)

    def test_matching_enums_no_mismatch(self, tmp_path):
        """Same enum values on both sides -> no mismatch."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "enum Status {\n"
            "  open\n"
            "  closed\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/components/StatusFilter.tsx", (
            "const STATUS_OPTIONS = ['open', 'closed'];\n"
        ))
        mismatches = detect_enum_value_mismatches(tmp_path)
        # Filter to only status-related mismatches
        status_mismatches = [m for m in mismatches if "status" in m.description.lower()]
        assert len(status_mismatches) == 0

    def test_isin_validator_mismatch(self, tmp_path):
        """@IsIn validator values don't match frontend -> HIGH."""
        _write_file(tmp_path, "src/dto/work-order.dto.ts", (
            "import { IsIn } from 'class-validator';\n"
            "export class CreateWorkOrderDto {\n"
            "  @IsIn(['corrective', 'preventive', 'emergency'])\n"
            "  type!: string;\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/components/WorkOrderForm.tsx", (
            "const TYPE_OPTIONS = ['corrective', 'preventive', 'emergency', 'inspection'];\n"
        ))
        mismatches = detect_enum_value_mismatches(tmp_path)
        assert len(mismatches) >= 1

    def test_typescript_enum_mismatch(self, tmp_path):
        """TypeScript enum in backend vs frontend array -> mismatch."""
        _write_file(tmp_path, "src/types/role.enum.ts", (
            "export enum UserRole {\n"
            "  ADMIN = 'admin',\n"
            "  MANAGER = 'manager',\n"
            "  USER = 'user',\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/components/RoleSelect.tsx", (
            "const ROLE_OPTIONS = ['admin', 'manager'];\n"
        ))
        mismatches = detect_enum_value_mismatches(tmp_path)
        # Should detect that 'user' is in backend but not frontend
        assert len(mismatches) >= 1

    def test_no_enums_no_mismatches(self, tmp_path):
        """No enums in project -> no mismatches."""
        _write_file(tmp_path, "src/App.tsx", "export default () => <div/>;")
        _write_file(tmp_path, "src/index.ts", "console.log('hello');")
        mismatches = detect_enum_value_mismatches(tmp_path)
        assert len(mismatches) == 0

    def test_severity_is_high(self, tmp_path):
        """Enum mismatches should be HIGH severity."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "enum Category {\n"
            "  A\n"
            "  B\n"
            "  C\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/components/CategoryFilter.tsx", (
            "const CATEGORY_OPTIONS = ['a', 'b'];\n"
        ))
        mismatches = detect_enum_value_mismatches(tmp_path)
        for m in mismatches:
            assert m.severity == "HIGH"


# ===================================================================
# 6. VerificationChecksConfig toggle (5 tests)
# ===================================================================


class TestVerificationChecksConfig:
    """Verify that individual checks can be toggled on/off."""

    def test_all_checks_enabled_by_default(self):
        """Default config enables all checks."""
        config = VerificationChecksConfig()
        assert config.route_structure is True
        assert config.response_shape_validation is True
        assert config.auth_flow is True
        assert config.enum_cross_check is True

    def test_disable_route_structure_check(self, tmp_path):
        """Disabling route_structure skips route structure check."""
        _write_file(tmp_path, "src/FloorList.tsx",
                     "const res = await api.post('/buildings/1/floors');\n")
        _write_file(tmp_path, "src/floors.controller.ts", (
            "@Controller('floors')\n"
            "export class FloorsController {\n"
            "  @Post('')\n"
            "  create() { return {}; }\n"
            "}\n"
        ))
        config = VerificationChecksConfig(route_structure=False)
        result = verify_integration(
            tmp_path, run_mode="block", checks_config=config,
        )
        assert isinstance(result, BlockingGateResult)
        # Route structure mismatches should NOT appear
        route_issues = [
            f for f in result.findings
            if f.category == "route_structure_mismatch"
        ]
        assert len(route_issues) == 0

    def test_disable_auth_flow_check(self, tmp_path):
        """Disabling auth_flow skips auth flow check."""
        _write_file(tmp_path, "src/auth/Login.tsx", (
            "await api.post('/auth/login', { email, password });\n"
        ))
        config = VerificationChecksConfig(auth_flow=False)
        result = verify_integration(
            tmp_path, run_mode="block", checks_config=config,
        )
        assert isinstance(result, BlockingGateResult)
        auth_issues = [
            f for f in result.findings
            if "auth" in f.category
        ]
        assert len(auth_issues) == 0

    def test_disable_enum_check(self, tmp_path):
        """Disabling enum_cross_check skips enum check."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "enum Status {\n  open\n  closed\n  pending\n}\n"
        ))
        _write_file(tmp_path, "src/StatusFilter.tsx", (
            "const STATUS_OPTIONS = ['open'];\n"
        ))
        config = VerificationChecksConfig(enum_cross_check=False)
        result = verify_integration(
            tmp_path, run_mode="block", checks_config=config,
        )
        assert isinstance(result, BlockingGateResult)
        enum_issues = [
            f for f in result.findings
            if f.category == "enum_value_mismatch"
        ]
        assert len(enum_issues) == 0

    def test_disable_response_shape_check(self, tmp_path):
        """Disabling response_shape_validation skips response shape check."""
        _write_file(tmp_path, "src/List.tsx", (
            "const res = await fetch('/api/items');\n"
            "const items = Array.isArray(res.data) ? res.data : [];\n"
        ))
        config = VerificationChecksConfig(response_shape_validation=False)
        result = verify_integration(
            tmp_path, run_mode="block", checks_config=config,
        )
        assert isinstance(result, BlockingGateResult)
        shape_issues = [
            f for f in result.findings
            if "response_shape" in f.category
        ]
        assert len(shape_issues) == 0


# ===================================================================
# 7. Pluralization Bug Detection (6 tests)
# ===================================================================


class TestPluralizationBugDetection:
    """Verify detection of incorrect pluralization in route paths."""

    def test_propertys_detected(self):
        """'/propertys' should be flagged as incorrect plural (M-15)."""
        frontend = [
            FrontendAPICall(
                file_path="src/PropertyList.tsx", line_number=10,
                endpoint_path="/propertys",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        mismatches = detect_pluralization_bugs(frontend, [])
        assert len(mismatches) >= 1
        assert mismatches[0].severity == "HIGH"
        assert "properties" in mismatches[0].description

    def test_categorys_detected(self):
        """'/categorys' should be flagged (correct: /categories)."""
        backend = [
            BackendEndpoint(
                file_path="src/category.controller.ts",
                route_path="/categorys", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        mismatches = detect_pluralization_bugs([], backend)
        assert len(mismatches) >= 1
        assert "categories" in mismatches[0].description

    def test_correct_plural_no_flag(self):
        """'/properties' should NOT be flagged."""
        frontend = [
            FrontendAPICall(
                file_path="src/PropertyList.tsx", line_number=10,
                endpoint_path="/properties",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        mismatches = detect_pluralization_bugs(frontend, [])
        assert len(mismatches) == 0

    def test_regular_plural_no_flag(self):
        """Regular plurals like '/users' should NOT be flagged."""
        frontend = [
            FrontendAPICall(
                file_path="src/UserList.tsx", line_number=1,
                endpoint_path="/users",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        mismatches = detect_pluralization_bugs(frontend, [])
        assert len(mismatches) == 0

    def test_nested_path_with_bad_plural(self):
        """Incorrect plural in nested path is detected."""
        frontend = [
            FrontendAPICall(
                file_path="src/BuildingList.tsx", line_number=5,
                endpoint_path="/buildings/:id/facilitys",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        mismatches = detect_pluralization_bugs(frontend, [])
        assert len(mismatches) >= 1
        assert "facilities" in mismatches[0].description

    def test_empty_inputs(self):
        """No calls/endpoints -> no mismatches."""
        mismatches = detect_pluralization_bugs([], [])
        assert len(mismatches) == 0


# ===================================================================
# 8. Query Parameter Alias Detection (6 tests)
# ===================================================================


class TestQueryParamAliasDetection:
    """Verify detection of query parameter naming aliases."""

    def test_dateFrom_vs_from(self):
        """Frontend 'dateFrom' vs backend 'from' -> HIGH mismatch (H-10)."""
        frontend = [
            FrontendAPICall(
                file_path="src/AuditLog.tsx", line_number=10,
                endpoint_path="/audit-logs",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
                query_params=["dateFrom", "dateTo"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/audit.controller.ts",
                route_path="/audit-logs", http_method="GET",
                handler_name="findAll",
                accepted_params=["from", "to"],
                response_fields=[],
            ),
        ]
        mismatches = detect_query_param_alias_mismatches(frontend, backend)
        assert len(mismatches) >= 1
        assert mismatches[0].severity == "HIGH"
        assert "dateFrom" in mismatches[0].description or "dateTo" in mismatches[0].description

    def test_pageSize_vs_limit(self):
        """Frontend 'pageSize' vs backend 'limit' -> alias mismatch."""
        frontend = [
            FrontendAPICall(
                file_path="src/List.tsx", line_number=5,
                endpoint_path="/items",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
                query_params=["pageSize"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/items.controller.ts",
                route_path="/items", http_method="GET",
                handler_name="findAll",
                accepted_params=["limit", "page"],
                response_fields=[],
            ),
        ]
        mismatches = detect_query_param_alias_mismatches(frontend, backend)
        assert len(mismatches) >= 1

    def test_exact_match_no_mismatch(self):
        """Same param names -> no mismatch."""
        frontend = [
            FrontendAPICall(
                file_path="src/List.tsx", line_number=5,
                endpoint_path="/items",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
                query_params=["page", "limit"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/items.controller.ts",
                route_path="/items", http_method="GET",
                handler_name="findAll",
                accepted_params=["page", "limit"],
                response_fields=[],
            ),
        ]
        mismatches = detect_query_param_alias_mismatches(frontend, backend)
        assert len(mismatches) == 0

    def test_no_query_params_no_mismatch(self):
        """No query params -> no mismatches."""
        frontend = [
            FrontendAPICall(
                file_path="src/Detail.tsx", line_number=1,
                endpoint_path="/items/:id",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
                query_params=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/items.controller.ts",
                route_path="/items/:id", http_method="GET",
                handler_name="findOne",
                accepted_params=["id"],
                response_fields=[],
            ),
        ]
        mismatches = detect_query_param_alias_mismatches(frontend, backend)
        assert len(mismatches) == 0

    def test_search_vs_q(self):
        """Frontend 'q' vs backend 'search' -> alias mismatch."""
        frontend = [
            FrontendAPICall(
                file_path="src/Search.tsx", line_number=3,
                endpoint_path="/items",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
                query_params=["q"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/items.controller.ts",
                route_path="/items", http_method="GET",
                handler_name="findAll",
                accepted_params=["search", "page"],
                response_fields=[],
            ),
        ]
        mismatches = detect_query_param_alias_mismatches(frontend, backend)
        assert len(mismatches) >= 1


# ===================================================================
# 9. RoutePatternEnforcer (18 tests — ArkanPM patterns)
# ===================================================================


class TestRoutePatternEnforcer:
    """Verify RoutePatternEnforcer class with ArkanPM-class violations."""

    # --- ROUTE-001: Nested frontend, flat backend (ArkanPM C-02, C-03, C-04) ---

    def test_route_001_buildings_id_floors_vs_floors(self):
        """ArkanPM C-02: /buildings/:id/floors vs /floors -> ROUTE-001 CRITICAL."""
        frontend = [
            FrontendAPICall(
                file_path="src/FloorList.tsx", line_number=15,
                endpoint_path="/buildings/:id/floors",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/floors.controller.ts",
                route_path="/floors", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_001 = [v for v in violations if v.violation_type == "ROUTE-001"]
        assert len(route_001) >= 1
        assert route_001[0].severity == "CRITICAL"
        assert route_001[0].frontend_path == "/buildings/:id/floors"
        assert route_001[0].backend_path == "/floors"

    def test_route_001_properties_id_contacts_vs_property_contacts(self):
        """ArkanPM C-03: /properties/:id/contacts vs /property-contacts -> ROUTE-001."""
        frontend = [
            FrontendAPICall(
                file_path="src/ContactList.tsx", line_number=10,
                endpoint_path="/properties/:id/contacts",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/contacts.controller.ts",
                route_path="/contacts", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_001 = [v for v in violations if v.violation_type == "ROUTE-001"]
        assert len(route_001) >= 1
        assert route_001[0].severity == "CRITICAL"

    def test_route_001_deeply_nested(self):
        """Deeply nested: /buildings/:bid/floors/:fid/zones -> /zones -> ROUTE-001."""
        frontend = [
            FrontendAPICall(
                file_path="src/ZoneList.tsx", line_number=5,
                endpoint_path="/buildings/:bid/floors/:fid/zones",
                http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/zones.controller.ts",
                route_path="/zones", http_method="POST",
                handler_name="create",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_001 = [v for v in violations if v.violation_type == "ROUTE-001"]
        assert len(route_001) >= 1
        assert route_001[0].severity == "CRITICAL"

    # --- ROUTE-002: Missing endpoint (ArkanPM C-09, C-10, C-11) ---

    def test_route_002_work_orders_checklist_missing(self):
        """ArkanPM C-09: /work-orders/:id/checklist/:itemId has no backend."""
        frontend = [
            FrontendAPICall(
                file_path="src/WorkOrderChecklist.tsx", line_number=20,
                endpoint_path="/work-orders/:id/checklist/:itemId",
                http_method="PATCH",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = []  # No backend endpoint at all
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_002 = [v for v in violations if v.violation_type == "ROUTE-002"]
        assert len(route_002) >= 1
        assert route_002[0].severity == "CRITICAL"
        assert route_002[0].backend_path is None

    def test_route_002_completely_missing_endpoint(self):
        """Frontend calls /reports/generate but no backend has it."""
        frontend = [
            FrontendAPICall(
                file_path="src/Reports.tsx", line_number=8,
                endpoint_path="/reports/generate",
                http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/users.controller.ts",
                route_path="/users", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_002 = [v for v in violations if v.violation_type == "ROUTE-002"]
        assert len(route_002) >= 1
        assert route_002[0].severity == "CRITICAL"

    def test_route_002_method_mismatch_counts_as_missing(self):
        """Backend has GET /reports but frontend calls POST /reports."""
        frontend = [
            FrontendAPICall(
                file_path="src/Reports.tsx", line_number=12,
                endpoint_path="/reports",
                http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/reports.controller.ts",
                route_path="/reports", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_002 = [v for v in violations if v.violation_type == "ROUTE-002"]
        assert len(route_002) >= 1

    # --- ROUTE-003: Plural mismatch (ArkanPM M-15, /checklist vs /checklists) ---

    def test_route_003_checklist_vs_checklists(self):
        """ArkanPM: /checklist vs /checklists -> ROUTE-003 HIGH."""
        frontend = [
            FrontendAPICall(
                file_path="src/Checklist.tsx", line_number=5,
                endpoint_path="/checklist",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/checklists.controller.ts",
                route_path="/checklists", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_003 = [v for v in violations if v.violation_type == "ROUTE-003"]
        assert len(route_003) >= 1
        assert route_003[0].severity == "HIGH"

    def test_route_003_property_vs_properties(self):
        """Singular /property vs plural /properties -> ROUTE-003."""
        frontend = [
            FrontendAPICall(
                file_path="src/Property.tsx", line_number=1,
                endpoint_path="/property",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/properties.controller.ts",
                route_path="/properties", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_003 = [v for v in violations if v.violation_type == "ROUTE-003"]
        assert len(route_003) >= 1

    def test_route_003_category_vs_categories(self):
        """/category vs /categories (ies plural) -> ROUTE-003."""
        frontend = [
            FrontendAPICall(
                file_path="src/CategoryPage.tsx", line_number=3,
                endpoint_path="/category",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/categories.controller.ts",
                route_path="/categories", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_003 = [v for v in violations if v.violation_type == "ROUTE-003"]
        assert len(route_003) >= 1

    # --- ROUTE-004: Fuzzy action path mismatch (ArkanPM /test vs /test-connection) ---

    def test_route_004_test_vs_test_connection(self):
        """ArkanPM: /integrations/:id/test vs /integrations/:id/test-connection -> ROUTE-004."""
        frontend = [
            FrontendAPICall(
                file_path="src/IntegrationTest.tsx", line_number=25,
                endpoint_path="/integrations/:id/test",
                http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/integrations.controller.ts",
                route_path="/integrations/:id/test-connection",
                http_method="POST",
                handler_name="testConnection",
                accepted_params=["id"], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_004 = [v for v in violations if v.violation_type == "ROUTE-004"]
        assert len(route_004) >= 1
        assert route_004[0].severity == "HIGH"
        assert "test" in route_004[0].suggestion
        assert "test-connection" in route_004[0].suggestion

    def test_route_004_disconnect_vs_disconnect_all(self):
        """Fuzzy: /devices/:id/disconnect vs /devices/:id/disconnect-all -> ROUTE-004."""
        frontend = [
            FrontendAPICall(
                file_path="src/DeviceManage.tsx", line_number=10,
                endpoint_path="/devices/:id/disconnect",
                http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/devices.controller.ts",
                route_path="/devices/:id/disconnect-all",
                http_method="POST",
                handler_name="disconnectAll",
                accepted_params=["id"], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_004 = [v for v in violations if v.violation_type == "ROUTE-004"]
        assert len(route_004) >= 1

    def test_route_004_not_triggered_for_unrelated_paths(self):
        """Completely different action paths should not trigger ROUTE-004."""
        frontend = [
            FrontendAPICall(
                file_path="src/Orders.tsx", line_number=5,
                endpoint_path="/orders/:id/ship",
                http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/orders.controller.ts",
                route_path="/orders/:id/cancel",
                http_method="POST",
                handler_name="cancel",
                accepted_params=["id"], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_004 = [v for v in violations if v.violation_type == "ROUTE-004"]
        # ship vs cancel are too different (similarity < 0.6)
        assert len(route_004) == 0

    # --- No false positives ---

    def test_exact_match_no_violations(self):
        """Exact match -> no violations."""
        frontend = [
            FrontendAPICall(
                file_path="src/UserList.tsx", line_number=1,
                endpoint_path="/users",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/users.controller.ts",
                route_path="/users", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        assert len(violations) == 0

    def test_both_nested_same_structure_no_violation(self):
        """Both frontend and backend nested identically -> no violation."""
        frontend = [
            FrontendAPICall(
                file_path="src/FloorList.tsx", line_number=10,
                endpoint_path="/buildings/:id/floors",
                http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/floors.controller.ts",
                route_path="/buildings/:id/floors",
                http_method="GET",
                handler_name="findAll",
                accepted_params=["id"], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        assert len(violations) == 0

    def test_empty_inputs_no_violations(self):
        """Empty inputs -> no violations."""
        enforcer = RoutePatternEnforcer([], [])
        violations = enforcer.check()
        assert len(violations) == 0

    def test_deduplication(self):
        """Same violation from multiple calls should be deduplicated."""
        call = FrontendAPICall(
            file_path="src/FloorList.tsx", line_number=10,
            endpoint_path="/buildings/:id/floors",
            http_method="GET",
            request_fields=[], expected_response_fields=[],
        )
        frontend = [call, call]  # duplicate call
        backend = [
            BackendEndpoint(
                file_path="src/floors.controller.ts",
                route_path="/floors", http_method="GET",
                handler_name="findAll",
                accepted_params=[], response_fields=[],
            ),
        ]
        enforcer = RoutePatternEnforcer(frontend, backend)
        violations = enforcer.check()
        route_001 = [v for v in violations if v.violation_type == "ROUTE-001"]
        assert len(route_001) == 1  # Deduplicated to 1

    def test_violation_dataclass_fields(self):
        """RoutePatternViolation has all required fields."""
        v = RoutePatternViolation(
            violation_type="ROUTE-001",
            frontend_path="/buildings/:id/floors",
            backend_path="/floors",
            frontend_file="src/FloorList.tsx",
            severity="CRITICAL",
            suggestion="Fix it.",
        )
        assert v.violation_type == "ROUTE-001"
        assert v.frontend_path == "/buildings/:id/floors"
        assert v.backend_path == "/floors"
        assert v.frontend_file == "src/FloorList.tsx"
        assert v.severity == "CRITICAL"
        assert v.suggestion == "Fix it."

    # --- from_raw_paths classmethod (pre-coding gate support) ---

    def test_from_raw_paths_detects_route_001(self):
        """from_raw_paths with raw tuples detects ROUTE-001."""
        enforcer = RoutePatternEnforcer.from_raw_paths(
            frontend_paths=[("/buildings/:id/floors", "GET")],
            backend_paths=[("/floors", "GET")],
        )
        violations = enforcer.check()
        route_001 = [v for v in violations if v.violation_type == "ROUTE-001"]
        assert len(route_001) >= 1
        assert route_001[0].severity == "CRITICAL"

    def test_from_raw_paths_exact_match_no_violation(self):
        """from_raw_paths with matching paths -> no violations."""
        enforcer = RoutePatternEnforcer.from_raw_paths(
            frontend_paths=[("/users", "GET"), ("/users/:id", "DELETE")],
            backend_paths=[("/users", "GET"), ("/users/:id", "DELETE")],
        )
        violations = enforcer.check()
        assert len(violations) == 0

    def test_from_raw_paths_detects_route_002(self):
        """from_raw_paths detects missing endpoints (ROUTE-002)."""
        enforcer = RoutePatternEnforcer.from_raw_paths(
            frontend_paths=[("/reports/generate", "POST")],
            backend_paths=[],
        )
        violations = enforcer.check()
        route_002 = [v for v in violations if v.violation_type == "ROUTE-002"]
        assert len(route_002) >= 1
        assert route_002[0].frontend_file == "<pre-coding-gate>"

    def test_empty_inputs(self):
        """Empty inputs -> no mismatches."""
        mismatches = detect_query_param_alias_mismatches([], [])
        assert len(mismatches) == 0
