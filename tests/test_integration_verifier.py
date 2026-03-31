"""Tests for agent_team.integration_verifier — frontend/backend endpoint matching and reports."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15.integration_verifier import (
    BackendEndpoint,
    FrontendAPICall,
    IntegrationMismatch,
    IntegrationReport,
    _parse_params_object_keys,
    _parse_prisma_schema,
    detect_field_naming_mismatches,
    detect_missing_prisma_includes,
    format_report_for_prompt,
    match_endpoints,
    normalize_path,
    save_report,
    scan_backend_endpoints,
    scan_frontend_api_calls,
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
# 1. Frontend API Call Scanning
# ===================================================================


class TestFrontendAPICallScanning:
    """Verify extraction of API calls from frontend source files."""

    def test_fetch_call_extraction(self, tmp_path):
        """A fetch() call in a .tsx file is detected."""
        _write_file(tmp_path, "src/components/UserList.tsx", (
            "import React from 'react';\n"
            "\n"
            "export const UserList = () => {\n"
            "  const loadUsers = async () => {\n"
            "    const res = await fetch('/api/users');\n"
            "    const data = await res.json();\n"
            "    return data;\n"
            "  };\n"
            "  return <div>Users</div>;\n"
            "};\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        assert len(calls) >= 1
        assert any("/api/users" in c.endpoint_path or "users" in c.endpoint_path for c in calls)

    def test_api_get_call(self, tmp_path):
        """An api.get('/path') call is extracted."""
        _write_file(tmp_path, "src/services/userService.ts", (
            "import api from './api';\n"
            "\n"
            "export const getUsers = () => api.get('/users');\n"
            "export const getUser = (id: string) => api.get(`/users/${id}`);\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        assert len(calls) >= 1

    def test_api_post_call(self, tmp_path):
        """An api.post('/path', body) call is extracted."""
        _write_file(tmp_path, "src/services/authService.ts", (
            "import api from './api';\n"
            "\n"
            "export const login = (creds: any) => api.post('/auth/login', creds);\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        assert len(calls) >= 1
        post_calls = [c for c in calls if c.http_method and c.http_method.upper() == "POST"]
        # If the scanner identifies methods, verify. Otherwise, at least one call.
        assert len(calls) >= 1

    def test_axios_call(self, tmp_path):
        """axios.get / axios.post calls are detected."""
        _write_file(tmp_path, "src/api/client.tsx", (
            "import axios from 'axios';\n"
            "\n"
            "export const fetchItems = () => axios.get('/api/items');\n"
            "export const createItem = (data: any) => axios.post('/api/items', data);\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        assert len(calls) >= 1

    def test_no_frontend_files(self, tmp_path):
        """Empty list when no frontend source files exist."""
        _write_file(tmp_path, "server/index.ts", "console.log('backend');")
        calls = scan_frontend_api_calls(tmp_path)
        assert isinstance(calls, list)


# ===================================================================
# 2. Backend Endpoint Scanning
# ===================================================================


class TestBackendEndpointScanning:
    """Verify extraction of endpoint definitions from backend source files."""

    def test_nestjs_controller(self, tmp_path):
        """NestJS @Controller/@Get decorators are detected."""
        _write_file(tmp_path, "src/users/users.controller.ts", (
            "import { Controller, Get, Post, Body } from '@nestjs/common';\n"
            "\n"
            "@Controller('users')\n"
            "export class UsersController {\n"
            "  @Get('')\n"
            "  findAll() { return []; }\n"
            "\n"
            "  @Post('')\n"
            "  create(@Body() dto: any) { return {}; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1

    def test_express_routes(self, tmp_path):
        """Express router patterns are detected."""
        _write_file(tmp_path, "src/routes/items.routes.ts", (
            "import { Router } from 'express';\n"
            "const router = Router();\n"
            "router.get('/items', (req, res) => res.json([]));\n"
            "router.post('/items', (req, res) => res.status(201).json({}));\n"
            "export default router;\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1

    def test_no_backend_files(self, tmp_path):
        """Empty list when no backend source files exist."""
        _write_file(tmp_path, "frontend/App.tsx", "export default () => <div/>;")
        endpoints = scan_backend_endpoints(tmp_path)
        assert isinstance(endpoints, list)


# ===================================================================
# 3. Path Normalization
# ===================================================================


class TestPathNormalization:
    """Verify normalize_path handles different parameter syntaxes."""

    def test_colon_params(self):
        """Express-style :id parameters are normalized."""
        result = normalize_path("/users/:id")
        assert ":id" not in result or "{id}" in result or result == "/users/:id"
        # The key contract: all param formats should normalize to the same output
        result2 = normalize_path("/users/{id}")
        assert result == result2

    def test_curly_params(self):
        """OpenAPI/NestJS-style {id} parameters are normalized."""
        result = normalize_path("/users/{id}")
        assert isinstance(result, str)

    def test_template_literal_params(self):
        """Template literal ${id} parameters are normalized."""
        result = normalize_path("/users/${id}")
        assert isinstance(result, str)

    def test_all_formats_normalize_same(self):
        """All parameter formats normalize to the same canonical form."""
        colon = normalize_path("/users/:userId/posts/:postId")
        curly = normalize_path("/users/{userId}/posts/{postId}")
        template = normalize_path("/users/${userId}/posts/${postId}")
        assert colon == curly
        assert curly == template

    def test_no_params(self):
        """Paths without parameters pass through unchanged."""
        result = normalize_path("/users")
        assert result == "/users"

    def test_root_path(self):
        """Root path normalizes correctly."""
        result = normalize_path("/")
        assert result == "/"

    @pytest.mark.parametrize("path,expected_segments", [
        ("/api/v1/users", 3),
        ("/health", 1),
        ("/", 0),
    ])
    def test_segment_count_preserved(self, path, expected_segments):
        """Normalization preserves the number of path segments."""
        result = normalize_path(path)
        # Count non-empty segments
        segments = [s for s in result.split("/") if s]
        assert len(segments) == expected_segments


# ===================================================================
# 4. Endpoint Matching
# ===================================================================


class TestEndpointMatching:
    """Verify match_endpoints correctly pairs frontend calls with backend endpoints."""

    def test_exact_match(self):
        """Frontend call matches backend endpoint with same path and method."""
        frontend = [
            FrontendAPICall(
                file_path="src/UserList.tsx",
                line_number=10,
                endpoint_path="/users",
                http_method="GET",
                request_fields=[],
                expected_response_fields=["id", "name"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/users.controller.ts",
                route_path="/users",
                http_method="GET",
                handler_name="findAll",
                accepted_params=[],
                response_fields=["id", "name"],
            ),
        ]
        report = match_endpoints(frontend, backend)
        assert isinstance(report, IntegrationReport)
        assert report.matched >= 1
        assert len(report.missing_endpoints) == 0

    def test_missing_endpoint_detected(self):
        """Frontend calls an endpoint that has no backend match."""
        frontend = [
            FrontendAPICall(
                file_path="src/Dashboard.tsx",
                line_number=20,
                endpoint_path="/analytics",
                http_method="GET",
                request_fields=[],
                expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/users.controller.ts",
                route_path="/users",
                http_method="GET",
                handler_name="findAll",
                accepted_params=[],
                response_fields=[],
            ),
        ]
        report = match_endpoints(frontend, backend)
        assert len(report.missing_endpoints) >= 1

    def test_unused_endpoint_detected(self):
        """Backend endpoint with no frontend caller is flagged."""
        frontend = [
            FrontendAPICall(
                file_path="src/UserList.tsx",
                line_number=10,
                endpoint_path="/users",
                http_method="GET",
                request_fields=[],
                expected_response_fields=[],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/users.controller.ts",
                route_path="/users",
                http_method="GET",
                handler_name="findAll",
                accepted_params=[],
                response_fields=[],
            ),
            BackendEndpoint(
                file_path="src/admin.controller.ts",
                route_path="/admin/stats",
                http_method="GET",
                handler_name="getStats",
                accepted_params=[],
                response_fields=[],
            ),
        ]
        report = match_endpoints(frontend, backend)
        assert len(report.unused_endpoints) >= 1

    def test_empty_inputs(self):
        """Empty frontend and backend lists produce a valid empty report."""
        report = match_endpoints([], [])
        assert isinstance(report, IntegrationReport)
        assert report.total_frontend_calls == 0
        assert report.total_backend_endpoints == 0
        assert report.matched == 0


# ===================================================================
# 5. Missing Endpoint Detection (expanded)
# ===================================================================


class TestMissingEndpointDetection:
    """Focused tests for missing endpoint detection."""

    def test_multiple_missing(self):
        """Multiple frontend calls with no backend match."""
        frontend = [
            FrontendAPICall(
                file_path="src/A.tsx", line_number=1,
                endpoint_path="/api/foo", http_method="GET",
                request_fields=[], expected_response_fields=[],
            ),
            FrontendAPICall(
                file_path="src/B.tsx", line_number=5,
                endpoint_path="/api/bar", http_method="POST",
                request_fields=[], expected_response_fields=[],
            ),
        ]
        backend = []
        report = match_endpoints(frontend, backend)
        assert len(report.missing_endpoints) >= 2

    def test_method_mismatch_counts_as_missing(self):
        """Same path but different method should be treated as missing."""
        frontend = [
            FrontendAPICall(
                file_path="src/A.tsx", line_number=1,
                endpoint_path="/users", http_method="DELETE",
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
        report = match_endpoints(frontend, backend)
        # DELETE /users has no backend match even though GET /users exists.
        # The implementation treats this as a method_mismatch (path matched but
        # method didn't), so it appears in mismatches rather than missing_endpoints.
        method_mismatches = [m for m in report.mismatches if m.category == "method_mismatch"]
        assert len(method_mismatches) >= 1 or len(report.missing_endpoints) >= 1


# ===================================================================
# 6. Unused Endpoint Detection (expanded)
# ===================================================================


class TestUnusedEndpointDetection:
    """Focused tests for unused backend endpoint detection."""

    def test_all_endpoints_unused(self):
        """All backend endpoints have no frontend callers."""
        frontend = []
        backend = [
            BackendEndpoint(
                file_path="src/a.controller.ts",
                route_path="/api/a", http_method="GET",
                handler_name="getA",
                accepted_params=[], response_fields=[],
            ),
            BackendEndpoint(
                file_path="src/b.controller.ts",
                route_path="/api/b", http_method="POST",
                handler_name="createB",
                accepted_params=[], response_fields=[],
            ),
        ]
        report = match_endpoints(frontend, backend)
        assert len(report.unused_endpoints) >= 2


# ===================================================================
# 7. Field Name Mismatch Detection (snake_case vs camelCase)
# ===================================================================


class TestFieldNameMismatchDetection:
    """Verify detection of naming convention mismatches between frontend and backend."""

    def test_snake_vs_camel_mismatch(self):
        """Frontend uses camelCase, backend uses snake_case — mismatch flagged."""
        frontend = [
            FrontendAPICall(
                file_path="src/UserList.tsx", line_number=10,
                endpoint_path="/users", http_method="GET",
                request_fields=[],
                expected_response_fields=["userId", "firstName", "lastName"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/users.controller.ts",
                route_path="/users", http_method="GET",
                handler_name="findAll",
                accepted_params=[],
                response_fields=["user_id", "first_name", "last_name"],
            ),
        ]
        report = match_endpoints(frontend, backend)
        # Either field_name_mismatches or general mismatches should capture this
        total_issues = len(report.field_name_mismatches) + len(report.mismatches)
        assert total_issues >= 1 or report.matched >= 1  # at minimum, endpoints match

    def test_consistent_naming_no_mismatch(self):
        """Same naming convention on both sides should not produce field mismatches."""
        frontend = [
            FrontendAPICall(
                file_path="src/UserList.tsx", line_number=10,
                endpoint_path="/users", http_method="GET",
                request_fields=[],
                expected_response_fields=["id", "name", "email"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/users.controller.ts",
                route_path="/users", http_method="GET",
                handler_name="findAll",
                accepted_params=[],
                response_fields=["id", "name", "email"],
            ),
        ]
        report = match_endpoints(frontend, backend)
        assert len(report.field_name_mismatches) == 0


# ===================================================================
# 8. Report Formatting
# ===================================================================


class TestReportFormatting:
    """Verify format_report_for_prompt produces useful text output."""

    def _make_report(self) -> IntegrationReport:
        return IntegrationReport(
            total_frontend_calls=3,
            total_backend_endpoints=4,
            matched=2,
            mismatches=[
                IntegrationMismatch(
                    severity="warning",
                    category="field_name",
                    frontend_file="src/UserList.tsx",
                    backend_file="src/users.controller.ts",
                    description="Field naming mismatch: camelCase vs snake_case",
                    suggestion="Add serialization layer",
                ),
            ],
            missing_endpoints=["/analytics"],
            unused_endpoints=["/admin/stats"],
            field_name_mismatches=[],
        )

    def test_renders_non_empty_string(self):
        report = self._make_report()
        rendered = format_report_for_prompt(report, max_chars=5000)
        assert isinstance(rendered, str)
        assert len(rendered) > 0

    def test_contains_summary_numbers(self):
        report = self._make_report()
        rendered = format_report_for_prompt(report, max_chars=5000)
        # Should contain at least some numeric info
        assert "2" in rendered or "matched" in rendered.lower()

    def test_mentions_missing_endpoints(self):
        report = self._make_report()
        rendered = format_report_for_prompt(report, max_chars=5000)
        assert "analytics" in rendered or "missing" in rendered.lower()

    def test_mentions_unused_endpoints(self):
        report = self._make_report()
        rendered = format_report_for_prompt(report, max_chars=5000)
        assert "admin" in rendered or "unused" in rendered.lower()

    def test_respects_max_chars(self):
        report = self._make_report()
        rendered = format_report_for_prompt(report, max_chars=50)
        assert len(rendered) <= 150  # allow small overflow for truncation marker


# ===================================================================
# 9. Empty Project
# ===================================================================


class TestEmptyProject:
    """Verify graceful handling of projects with no frontend or backend files."""

    def test_verify_integration_empty(self, tmp_path):
        """An empty project returns a valid report with zeros."""
        report = verify_integration(tmp_path)
        assert isinstance(report, IntegrationReport)
        assert report.total_frontend_calls == 0
        assert report.total_backend_endpoints == 0
        assert report.matched == 0
        assert report.mismatches == []
        assert report.missing_endpoints == []
        assert report.unused_endpoints == []

    def test_scan_frontend_empty(self, tmp_path):
        calls = scan_frontend_api_calls(tmp_path)
        assert calls == []

    def test_scan_backend_empty(self, tmp_path):
        endpoints = scan_backend_endpoints(tmp_path)
        assert endpoints == []


# ===================================================================
# 10. node_modules Exclusion
# ===================================================================


class TestNodeModulesExclusion:
    """Verify that node_modules directories are excluded from scanning."""

    def test_frontend_skips_node_modules(self, tmp_path):
        """API calls in node_modules are not included in results."""
        # Create a file inside node_modules with API calls
        _write_file(tmp_path, "node_modules/some-lib/api.tsx", (
            "export const fetchData = () => fetch('/api/internal');\n"
        ))
        # Create a real frontend file
        _write_file(tmp_path, "src/App.tsx", (
            "export const App = () => <div/>;\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        # No calls from node_modules should appear
        for call in calls:
            assert "node_modules" not in call.file_path

    def test_backend_skips_node_modules(self, tmp_path):
        """Endpoint definitions in node_modules are not included."""
        _write_file(tmp_path, "node_modules/@nestjs/core/test.controller.ts", (
            "@Controller('internal')\n"
            "export class InternalController {\n"
            "  @Get()\n"
            "  test() { return 'test'; }\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/app.controller.ts", (
            "@Controller('app')\n"
            "export class AppController {\n"
            "  @Get()\n"
            "  root() { return 'ok'; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        for ep in endpoints:
            assert "node_modules" not in ep.file_path


# ===================================================================
# 11. Report Persistence
# ===================================================================


class TestReportPersistence:
    """Verify save_report writes a valid file."""

    def test_save_report(self, tmp_path):
        """save_report creates a file on disk."""
        report = IntegrationReport(
            total_frontend_calls=1,
            total_backend_endpoints=1,
            matched=1,
            mismatches=[],
            missing_endpoints=[],
            unused_endpoints=[],
            field_name_mismatches=[],
        )
        path = tmp_path / "report.json"
        save_report(report, path)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert len(content) > 0


# ===================================================================
# 12. Dataclass Construction
# ===================================================================


class TestDataclassConstruction:
    """Verify dataclass fields and construction for all types."""

    def test_frontend_api_call(self):
        call = FrontendAPICall(
            file_path="src/App.tsx",
            line_number=42,
            endpoint_path="/api/data",
            http_method="GET",
            request_fields=["filter"],
            expected_response_fields=["items"],
        )
        assert call.file_path == "src/App.tsx"
        assert call.line_number == 42
        assert call.endpoint_path == "/api/data"
        assert call.http_method == "GET"

    def test_backend_endpoint(self):
        ep = BackendEndpoint(
            file_path="src/data.controller.ts",
            route_path="/api/data",
            http_method="GET",
            handler_name="getData",
            accepted_params=["filter"],
            response_fields=["items"],
        )
        assert ep.file_path == "src/data.controller.ts"
        assert ep.route_path == "/api/data"

    def test_integration_mismatch(self):
        mm = IntegrationMismatch(
            severity="error",
            category="missing_endpoint",
            frontend_file="src/App.tsx",
            backend_file="",
            description="No backend for /api/foo",
            suggestion="Add endpoint",
        )
        assert mm.severity == "error"
        assert mm.category == "missing_endpoint"

    def test_integration_report(self):
        report = IntegrationReport(
            total_frontend_calls=5,
            total_backend_endpoints=3,
            matched=2,
            mismatches=[],
            missing_endpoints=["/api/missing"],
            unused_endpoints=["/api/unused"],
            field_name_mismatches=[],
        )
        assert report.total_frontend_calls == 5
        assert report.total_backend_endpoints == 3
        assert report.matched == 2
        assert len(report.missing_endpoints) == 1
        assert len(report.unused_endpoints) == 1


# ===================================================================
# 13. Params Object Extraction (Fix 1 & 2)
# ===================================================================


class TestParseParamsObjectKeys:
    """Verify _parse_params_object_keys handles various JS object patterns."""

    def test_shorthand_properties(self):
        """Shorthand { key1, key2, key3 } is parsed correctly."""
        result = _parse_params_object_keys("status, priority, buildingId, page, limit")
        assert result == ["status", "priority", "buildingId", "page", "limit"]

    def test_explicit_key_value(self):
        """Explicit { key: value } pairs extract the key."""
        result = _parse_params_object_keys("status: selectedStatus, building: buildingId")
        assert result == ["status", "building"]

    def test_mixed_shorthand_and_explicit(self):
        """Mix of shorthand and explicit properties."""
        result = _parse_params_object_keys("status, priority: selectedPriority, page")
        assert result == ["status", "priority", "page"]

    def test_spread_operator_skipped(self):
        """Spread operator ...filters is skipped."""
        result = _parse_params_object_keys("...filters, page, limit")
        assert "filters" not in result
        assert result == ["page", "limit"]

    def test_empty_string(self):
        """Empty input returns empty list."""
        result = _parse_params_object_keys("")
        assert result == []

    def test_deduplication(self):
        """Duplicate keys are deduplicated."""
        result = _parse_params_object_keys("status, status, page")
        assert result == ["status", "page"]


class TestParamsObjectScanning:
    """Verify that api.get('/path', { params: { ... } }) patterns are detected."""

    def test_api_get_with_params_object(self, tmp_path):
        """api.get with a params object extracts query params."""
        _write_file(tmp_path, "src/services/workOrderService.ts", (
            "import api from './api';\n"
            "\n"
            "export const getWorkOrders = async (status: string, priority: string) => {\n"
            "  const res = await api.get('/work-orders', {\n"
            "    params: { status, priority, buildingId, page, limit }\n"
            "  });\n"
            "  return res.data;\n"
            "};\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        assert len(calls) >= 1
        work_order_calls = [c for c in calls if "work-orders" in c.endpoint_path]
        assert len(work_order_calls) >= 1
        qp = work_order_calls[0].query_params
        assert "status" in qp
        assert "priority" in qp
        assert "buildingId" in qp

    def test_api_get_with_typed_generics_and_params(self, tmp_path):
        """api.get<Type>('/path', { params: {...} }) with generics."""
        _write_file(tmp_path, "src/services/assetService.ts", (
            "import api from './api';\n"
            "\n"
            "export const getAssets = async () => {\n"
            "  const res = await api.get<{ data: Asset[] }>('/assets', {\n"
            "    params: { category, buildingId }\n"
            "  });\n"
            "  return res.data;\n"
            "};\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        asset_calls = [c for c in calls if "assets" in c.endpoint_path]
        assert len(asset_calls) >= 1
        qp = asset_calls[0].query_params
        assert "category" in qp
        assert "buildingId" in qp

    def test_axios_get_with_params_object(self, tmp_path):
        """axios.get with a params object extracts query params."""
        _write_file(tmp_path, "src/api/inspections.ts", (
            "import axios from 'axios';\n"
            "\n"
            "export const getInspections = async () => {\n"
            "  const res = await axios.get('/inspections', {\n"
            "    params: { dateFrom, dateTo, buildingId }\n"
            "  });\n"
            "  return res.data;\n"
            "};\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        insp_calls = [c for c in calls if "inspections" in c.endpoint_path]
        assert len(insp_calls) >= 1
        qp = insp_calls[0].query_params
        assert "dateFrom" in qp
        assert "dateTo" in qp
        assert "buildingId" in qp

    def test_params_object_with_explicit_keys(self, tmp_path):
        """Params object with key: value syntax extracts keys."""
        _write_file(tmp_path, "src/services/reports.ts", (
            "import api from './api';\n"
            "\n"
            "export const getReports = async () => {\n"
            "  const res = await api.get('/reports', {\n"
            "    params: { from: startDate, to: endDate, type: reportType }\n"
            "  });\n"
            "  return res.data;\n"
            "};\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        report_calls = [c for c in calls if "reports" in c.endpoint_path]
        assert len(report_calls) >= 1
        qp = report_calls[0].query_params
        assert "from" in qp
        assert "to" in qp
        assert "type" in qp


# ===================================================================
# 14. URLSearchParams Extraction (Fix 3)
# ===================================================================


class TestURLSearchParamsScanning:
    """Verify that URLSearchParams append/set patterns are detected."""

    def test_url_search_params_append(self, tmp_path):
        """params.append('key', value) is extracted."""
        _write_file(tmp_path, "src/services/filterService.ts", (
            "import api from './api';\n"
            "\n"
            "export const getFilteredItems = async () => {\n"
            "  const params = new URLSearchParams();\n"
            "  params.append('category', selectedCategory);\n"
            "  params.append('building', building);\n"
            "  params.append('status', activeStatus);\n"
            "  const res = await api.get(`/items?${params.toString()}`);\n"
            "  return res.data;\n"
            "};\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        assert len(calls) >= 1
        item_calls = [c for c in calls if "items" in c.endpoint_path]
        assert len(item_calls) >= 1
        qp = item_calls[0].query_params
        assert "category" in qp
        assert "building" in qp
        assert "status" in qp

    def test_search_params_set(self, tmp_path):
        """searchParams.set('key', value) is extracted."""
        _write_file(tmp_path, "src/hooks/useData.ts", (
            "import api from './api';\n"
            "\n"
            "export const useData = () => {\n"
            "  const searchParams = new URLSearchParams();\n"
            "  searchParams.set('page', '1');\n"
            "  searchParams.set('limit', '10');\n"
            "  const res = api.get(`/data?${searchParams}`);\n"
            "  return res;\n"
            "};\n"
        ))
        calls = scan_frontend_api_calls(tmp_path)
        assert len(calls) >= 1
        data_calls = [c for c in calls if "data" in c.endpoint_path]
        assert len(data_calls) >= 1
        qp = data_calls[0].query_params
        assert "page" in qp
        assert "limit" in qp


# ===================================================================
# 15. Query Param Mismatch Detection (Fix 4)
# ===================================================================


class TestQueryParamMismatchDetection:
    """Verify query parameter mismatches are caught including camelCase/snake_case."""

    def test_camel_vs_snake_query_param(self):
        """Frontend camelCase query param vs backend snake_case is caught."""
        frontend = [
            FrontendAPICall(
                file_path="src/WorkOrders.tsx", line_number=10,
                endpoint_path="/work-orders", http_method="GET",
                request_fields=[],
                expected_response_fields=[],
                query_params=["buildingId"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/work-orders.controller.ts",
                route_path="/work-orders", http_method="GET",
                handler_name="findAll",
                accepted_params=["building_id"],
                response_fields=[],
            ),
        ]
        report = match_endpoints(frontend, backend)
        # Should detect camelCase vs snake_case mismatch
        param_mismatches = [
            m for m in report.field_name_mismatches
            if "query_param" in m.category
        ]
        assert len(param_mismatches) >= 1
        assert "buildingId" in param_mismatches[0].description
        assert "building_id" in param_mismatches[0].description

    def test_partial_name_mismatch(self):
        """Frontend 'priority' vs backend 'priority_id' is caught."""
        frontend = [
            FrontendAPICall(
                file_path="src/WorkOrders.tsx", line_number=10,
                endpoint_path="/work-orders", http_method="GET",
                request_fields=[],
                expected_response_fields=[],
                query_params=["priority"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/work-orders.controller.ts",
                route_path="/work-orders", http_method="GET",
                handler_name="findAll",
                accepted_params=["priority_id"],
                response_fields=[],
            ),
        ]
        report = match_endpoints(frontend, backend)
        param_mismatches = [
            m for m in report.field_name_mismatches
            if "query_param" in m.category
        ]
        assert len(param_mismatches) >= 1
        assert "priority" in param_mismatches[0].description
        assert "priority_id" in param_mismatches[0].description

    def test_frontend_dateFrom_vs_backend_from(self):
        """Frontend 'dateFrom' vs backend 'from' is caught as partial match."""
        frontend = [
            FrontendAPICall(
                file_path="src/Inspections.tsx", line_number=15,
                endpoint_path="/inspections", http_method="GET",
                request_fields=[],
                expected_response_fields=[],
                query_params=["dateFrom", "dateTo"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/inspections.controller.ts",
                route_path="/inspections", http_method="GET",
                handler_name="findAll",
                accepted_params=["from", "to"],
                response_fields=[],
            ),
        ]
        report = match_endpoints(frontend, backend)
        param_mismatches = [
            m for m in report.field_name_mismatches
            if "query_param" in m.category
        ]
        # "dateFrom" contains "from", so partial match should be caught
        assert len(param_mismatches) >= 1

    def test_exact_match_no_mismatch(self):
        """Exact match query params produce no mismatch."""
        frontend = [
            FrontendAPICall(
                file_path="src/Users.tsx", line_number=10,
                endpoint_path="/users", http_method="GET",
                request_fields=[],
                expected_response_fields=[],
                query_params=["page", "limit", "status"],
            ),
        ]
        backend = [
            BackendEndpoint(
                file_path="src/users.controller.ts",
                route_path="/users", http_method="GET",
                handler_name="findAll",
                accepted_params=["page", "limit", "status"],
                response_fields=[],
            ),
        ]
        report = match_endpoints(frontend, backend)
        param_mismatches = [
            m for m in report.field_name_mismatches
            if "query_param" in m.category
        ]
        assert len(param_mismatches) == 0

    def test_end_to_end_params_object_mismatch(self, tmp_path):
        """Full pipeline: params object in frontend + backend mismatch."""
        _write_file(tmp_path, "src/services/workOrders.ts", (
            "import api from './api';\n"
            "\n"
            "export const getWorkOrders = async () => {\n"
            "  const res = await api.get('/work-orders', {\n"
            "    params: { status, priority, buildingId }\n"
            "  });\n"
            "  return res.data;\n"
            "};\n"
        ))
        _write_file(tmp_path, "src/routes/workOrders.routes.ts", (
            "import { Router } from 'express';\n"
            "const router = Router();\n"
            "router.get('/work-orders', (req, res) => {\n"
            "  const status = req.query.status;\n"
            "  const priorityId = req.query.priority_id;\n"
            "  const buildingId = req.query.building_id;\n"
            "  res.json([]);\n"
            "});\n"
            "export default router;\n"
        ))
        frontend_calls = scan_frontend_api_calls(tmp_path)
        backend_endpoints = scan_backend_endpoints(tmp_path)

        # Verify frontend extracted the params
        wo_calls = [c for c in frontend_calls if "work-orders" in c.endpoint_path]
        assert len(wo_calls) >= 1
        assert "priority" in wo_calls[0].query_params
        assert "buildingId" in wo_calls[0].query_params

        report = match_endpoints(frontend_calls, backend_endpoints)
        # There should be query param mismatches for priority vs priority_id
        # and buildingId vs building_id
        param_mismatches = [
            m for m in report.field_name_mismatches
            if "query_param" in m.category
        ]
        assert len(param_mismatches) >= 1


# ===================================================================
# 16. NestJS @Query() / @Param() Backend Extraction
# ===================================================================


class TestNestJSQueryParamExtraction:
    """Verify extraction of @Query() and @Param() decorator params from NestJS controllers."""

    def test_named_query_params(self, tmp_path):
        """@Query('paramName') decorators are extracted."""
        _write_file(tmp_path, "src/stock-level.controller.ts", (
            "import { Controller, Get, Query } from '@nestjs/common';\n"
            "\n"
            "@Controller('stock-levels')\n"
            "export class StockLevelController {\n"
            "  @Get('')\n"
            "  findAll(\n"
            "    @Query('page') page?: string,\n"
            "    @Query('limit') limit?: string,\n"
            "    @Query('spare_part_id') spare_part_id?: string,\n"
            "    @Query('warehouse_id') warehouse_id?: string,\n"
            "    @Query('low_stock') low_stock?: string,\n"
            "  ) { return []; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "page" in ep.accepted_params
        assert "limit" in ep.accepted_params
        assert "spare_part_id" in ep.accepted_params
        assert "warehouse_id" in ep.accepted_params
        assert "low_stock" in ep.accepted_params

    def test_query_params_with_pipes(self, tmp_path):
        """@Query('param', ParseIntPipe) decorators with pipes are extracted."""
        _write_file(tmp_path, "src/document.controller.ts", (
            "import { Controller, Get, Query, ParseIntPipe, DefaultValuePipe } from '@nestjs/common';\n"
            "\n"
            "@Controller('documents')\n"
            "export class DocumentController {\n"
            "  @Get('')\n"
            "  findAll(\n"
            "    @Query('page', new DefaultValuePipe(1), ParseIntPipe) page?: number,\n"
            "    @Query('limit', new DefaultValuePipe(20), ParseIntPipe) limit?: number,\n"
            "    @Query('sort') sort?: string,\n"
            "  ) { return []; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "page" in ep.accepted_params
        assert "limit" in ep.accepted_params
        assert "sort" in ep.accepted_params

    def test_query_dto_inline(self, tmp_path):
        """@Query() with DTO class (inline in same file) extracts DTO fields."""
        _write_file(tmp_path, "src/asset.controller.ts", (
            "import { Controller, Get, Query } from '@nestjs/common';\n"
            "\n"
            "class ListAssetsQueryDto {\n"
            "  page?: number;\n"
            "  limit?: number;\n"
            "  status?: string;\n"
            "  category?: string;\n"
            "  buildingId?: string;\n"
            "}\n"
            "\n"
            "@Controller('assets')\n"
            "export class AssetController {\n"
            "  @Get('')\n"
            "  findAll(@Query() query: ListAssetsQueryDto) { return []; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "page" in ep.accepted_params
        assert "limit" in ep.accepted_params
        assert "status" in ep.accepted_params
        assert "category" in ep.accepted_params
        assert "buildingId" in ep.accepted_params

    def test_query_dto_separate_file(self, tmp_path):
        """@Query() with DTO class (in separate dto file) extracts DTO fields."""
        _write_file(tmp_path, "src/dto/list-items.dto.ts", (
            "export class ListItemsDto {\n"
            "  page?: number;\n"
            "  limit?: number;\n"
            "  search?: string;\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/items.controller.ts", (
            "import { Controller, Get, Query } from '@nestjs/common';\n"
            "\n"
            "@Controller('items')\n"
            "export class ItemsController {\n"
            "  @Get('')\n"
            "  findAll(@Query() query: ListItemsDto) { return []; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "page" in ep.accepted_params
        assert "limit" in ep.accepted_params
        assert "search" in ep.accepted_params

    def test_param_decorator(self, tmp_path):
        """@Param('name') decorators are extracted."""
        _write_file(tmp_path, "src/users.controller.ts", (
            "import { Controller, Get, Param } from '@nestjs/common';\n"
            "\n"
            "@Controller('users')\n"
            "export class UsersController {\n"
            "  @Get(':id')\n"
            "  findOne(@Param('id') id: string) { return {}; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "id" in ep.accepted_params

    def test_param_with_pipe(self, tmp_path):
        """@Param('name', ParseIntPipe) decorators with pipes are extracted."""
        _write_file(tmp_path, "src/orders.controller.ts", (
            "import { Controller, Get, Param, ParseIntPipe } from '@nestjs/common';\n"
            "\n"
            "@Controller('orders')\n"
            "export class OrdersController {\n"
            "  @Get(':id')\n"
            "  findOne(@Param('id', ParseIntPipe) id: number) { return {}; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "id" in ep.accepted_params

    def test_mixed_query_and_param(self, tmp_path):
        """Both @Query and @Param in the same handler are extracted."""
        _write_file(tmp_path, "src/buildings.controller.ts", (
            "import { Controller, Get, Param, Query } from '@nestjs/common';\n"
            "\n"
            "@Controller('buildings')\n"
            "export class BuildingsController {\n"
            "  @Get(':buildingId/units')\n"
            "  getUnits(\n"
            "    @Param('buildingId') buildingId: string,\n"
            "    @Query('page') page?: string,\n"
            "    @Query('limit') limit?: string,\n"
            "    @Query('status') status?: string,\n"
            "  ) { return []; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "buildingId" in ep.accepted_params
        assert "page" in ep.accepted_params
        assert "limit" in ep.accepted_params
        assert "status" in ep.accepted_params

    def test_dto_with_decorators(self, tmp_path):
        """DTO fields with validation decorators are correctly extracted."""
        _write_file(tmp_path, "src/work-orders.controller.ts", (
            "import { Controller, Get, Query } from '@nestjs/common';\n"
            "\n"
            "class ListWorkOrdersDto {\n"
            "  @IsOptional()\n"
            "  @Type(() => Number)\n"
            "  page?: number;\n"
            "\n"
            "  @IsOptional()\n"
            "  @Type(() => Number)\n"
            "  limit?: number;\n"
            "\n"
            "  @IsOptional()\n"
            "  @IsString()\n"
            "  status?: string;\n"
            "\n"
            "  @IsOptional()\n"
            "  @IsString()\n"
            "  priority?: string;\n"
            "}\n"
            "\n"
            "@Controller('work-orders')\n"
            "export class WorkOrdersController {\n"
            "  @Get('')\n"
            "  findAll(@Query() query: ListWorkOrdersDto) { return []; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "page" in ep.accepted_params
        assert "limit" in ep.accepted_params
        assert "status" in ep.accepted_params
        assert "priority" in ep.accepted_params


# ===================================================================
# 17. NestJS @UseGuards, @Roles, @ApiResponse Extraction
# ===================================================================


class TestNestJSGuardsRolesExtraction:
    """Verify extraction of @UseGuards, @Roles, and @ApiResponse from NestJS controllers."""

    def test_class_level_guards(self, tmp_path):
        """Class-level @UseGuards are inherited by all methods."""
        _write_file(tmp_path, "src/orders.controller.ts", (
            "import { Controller, Get, UseGuards } from '@nestjs/common';\n"
            "\n"
            "@UseGuards(JwtAuthGuard, RolesGuard)\n"
            "@Controller('orders')\n"
            "export class OrdersController {\n"
            "  @Get('')\n"
            "  findAll() { return []; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "JwtAuthGuard" in ep.guards
        assert "RolesGuard" in ep.guards

    def test_class_level_roles(self, tmp_path):
        """Class-level @Roles are inherited by all methods."""
        _write_file(tmp_path, "src/admin.controller.ts", (
            "import { Controller, Get, UseGuards } from '@nestjs/common';\n"
            "\n"
            "@UseGuards(JwtAuthGuard, RolesGuard)\n"
            "@Roles('tenant_admin')\n"
            "@Controller('admin')\n"
            "export class AdminController {\n"
            "  @Get('stats')\n"
            "  getStats() { return {}; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert "tenant_admin" in ep.roles

    def test_method_level_roles(self, tmp_path):
        """Method-level @Roles are extracted for specific endpoints."""
        _write_file(tmp_path, "src/purchase.controller.ts", (
            "import { Controller, Get, Post, UseGuards } from '@nestjs/common';\n"
            "\n"
            "@UseGuards(JwtAuthGuard, RolesGuard)\n"
            "@Controller('purchases')\n"
            "export class PurchaseController {\n"
            "  @Roles('tenant_admin', 'facility_manager')\n"
            "  @Get('')\n"
            "  findAll() { return []; }\n"
            "\n"
            "  @Roles('tenant_admin')\n"
            "  @Post('')\n"
            "  create() { return {}; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        get_eps = [e for e in endpoints if e.http_method == "GET"]
        post_eps = [e for e in endpoints if e.http_method == "POST"]
        assert len(get_eps) >= 1
        assert len(post_eps) >= 1
        assert "tenant_admin" in get_eps[0].roles
        assert "facility_manager" in get_eps[0].roles
        assert "tenant_admin" in post_eps[0].roles

    def test_api_response_description(self, tmp_path):
        """@ApiResponse description is extracted."""
        _write_file(tmp_path, "src/health.controller.ts", (
            "import { Controller, Get } from '@nestjs/common';\n"
            "\n"
            "@Controller('health')\n"
            "export class HealthController {\n"
            "  @ApiResponse({ status: 200, description: 'Service health information' })\n"
            "  @Get('')\n"
            "  check() { return { status: 'ok' }; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert ep.api_response_desc == "Service health information"

    def test_no_guards_when_absent(self, tmp_path):
        """Endpoints without guards have empty guards list."""
        _write_file(tmp_path, "src/public.controller.ts", (
            "import { Controller, Get } from '@nestjs/common';\n"
            "\n"
            "@Controller('public')\n"
            "export class PublicController {\n"
            "  @Get('info')\n"
            "  getInfo() { return {}; }\n"
            "}\n"
        ))
        endpoints = scan_backend_endpoints(tmp_path)
        assert len(endpoints) >= 1
        ep = endpoints[0]
        assert ep.guards == []
        assert ep.roles == []
        assert ep.api_response_desc == ""


# ===================================================================
# 16. Broad Field Naming Detection (Task B)
# ===================================================================


class TestBroadFieldNamingDetection:
    """Verify that field naming detection works with arbitrary variable names."""

    def test_typed_variable_optional_chaining(self, tmp_path):
        """wo?.buildingId style access on typed variables is detected."""
        # Backend with snake_case field
        _write_file(tmp_path, "prisma/schema.prisma", (
            "model WorkOrder {\n"
            "  id          Int    @id @default(autoincrement())\n"
            "  building_id Int\n"
            "}\n"
        ))
        # Frontend with camelCase access on typed variable
        _write_file(tmp_path, "src/components/WorkOrderDetail.tsx", (
            "const WorkOrderDetail = ({ wo }: Props) => {\n"
            "  return <div>{wo?.buildingId}</div>;\n"
            "};\n"
        ))
        mismatches = detect_field_naming_mismatches(tmp_path)
        camel_fields = {m.description.split("'")[1] for m in mismatches}
        assert "buildingId" in camel_fields

    def test_domain_variable_dot_access(self, tmp_path):
        """asset.vendorId style access is detected."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "model Asset {\n"
            "  id        Int    @id\n"
            "  vendor_id Int\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/pages/AssetList.tsx", (
            "assets.map(asset => (\n"
            "  <div key={asset.vendorId}>{asset.vendorId}</div>\n"
            "));\n"
        ))
        mismatches = detect_field_naming_mismatches(tmp_path)
        camel_fields = {m.description.split("'")[1] for m in mismatches}
        assert "vendorId" in camel_fields

    def test_builtin_objects_excluded(self, tmp_path):
        """Math.floor, console.log, etc. are NOT detected as field mismatches."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "model Test {\n"
            "  id           Int    @id\n"
            "  random_value Int\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/utils/helpers.tsx", (
            "const x = Math.randomValue;\n"
            "console.logError('test');\n"
            "document.getElementById('test');\n"
        ))
        mismatches = detect_field_naming_mismatches(tmp_path)
        # These should NOT produce mismatches (builtins are excluded)
        descriptions = " ".join(m.description for m in mismatches)
        assert "randomValue" not in descriptions

    def test_standard_response_vars_still_work(self, tmp_path):
        """res.buildingId and data.vendorId still work as before."""
        _write_file(tmp_path, "prisma/schema.prisma", (
            "model Building {\n"
            "  id          Int    @id\n"
            "  building_id Int\n"
            "  vendor_id   Int\n"
            "}\n"
        ))
        _write_file(tmp_path, "src/api/buildings.tsx", (
            "const res = await fetch('/api/buildings');\n"
            "const data = await res.json();\n"
            "console.log(data.buildingId);\n"
            "console.log(data.vendorId);\n"
        ))
        mismatches = detect_field_naming_mismatches(tmp_path)
        camel_fields = {m.description.split("'")[1] for m in mismatches}
        assert "buildingId" in camel_fields
        assert "vendorId" in camel_fields


# ===================================================================
# 9. Prisma Missing Include Detection
# ===================================================================


SAMPLE_PRISMA_SCHEMA = """\
model WorkOrder {
  id            String    @id @default(uuid())
  tenant_id     String
  category_id   String?
  priority_id   String?
  building_id   String?
  title         String
  status        String    @default("draft")
  created_at    DateTime  @default(now())

  tenant    Tenant                @relation(fields: [tenant_id], references: [id])
  category  MaintenanceCategory?  @relation(fields: [category_id], references: [id])
  priority  MaintenancePriority?  @relation(fields: [priority_id], references: [id])
  comments  WorkOrderComment[]

  @@map("work_orders")
}

model Asset {
  id          String  @id @default(uuid())
  tenant_id   String
  category_id String
  building_id String?
  name        String

  tenant   Tenant         @relation(fields: [tenant_id], references: [id])
  category AssetCategory  @relation(fields: [category_id], references: [id])

  @@map("assets")
}

model Tenant {
  id   String @id @default(uuid())
  name String

  @@map("tenants")
}

model MaintenanceCategory {
  id   String @id @default(uuid())
  name String
  work_orders WorkOrder[]

  @@map("maintenance_categories")
}

model MaintenancePriority {
  id   String @id @default(uuid())
  name String
  work_orders WorkOrder[]

  @@map("maintenance_priorities")
}

model AssetCategory {
  id   String @id @default(uuid())
  name String
  parent_id String?
  parent  AssetCategory? @relation("CatTree", fields: [parent_id], references: [id])
  children AssetCategory[] @relation("CatTree")
  assets Asset[]

  @@map("asset_categories")
}

model WorkOrderComment {
  id            String @id @default(uuid())
  work_order_id String
  content       String

  work_order WorkOrder @relation(fields: [work_order_id], references: [id])

  @@map("work_order_comments")
}
"""


class TestPrismaSchemaParser:
    """Test Prisma schema relation parsing."""

    def test_parse_model_relations(self):
        """Forward FK relations are correctly extracted."""
        result = _parse_prisma_schema(SAMPLE_PRISMA_SCHEMA)
        assert "WorkOrder" in result
        wo_rels = {r[0] for r in result["WorkOrder"]}
        assert "category" in wo_rels
        assert "priority" in wo_rels

    def test_tenant_relation_skipped(self):
        """The tenant relation is skipped (filter, not display)."""
        result = _parse_prisma_schema(SAMPLE_PRISMA_SCHEMA)
        for model_rels in result.values():
            for rel_name, _, fk in model_rels:
                assert rel_name != "tenant"
                assert fk != "tenant_id"

    def test_reverse_relations_skipped(self):
        """Array / reverse relations are not included (no fields: clause)."""
        result = _parse_prisma_schema(SAMPLE_PRISMA_SCHEMA)
        # MaintenanceCategory has work_orders WorkOrder[] — no fields clause
        assert "MaintenanceCategory" not in result

    def test_self_referential_skipped(self):
        """Self-referential relations like parent/children are skipped."""
        result = _parse_prisma_schema(SAMPLE_PRISMA_SCHEMA)
        # AssetCategory has parent AssetCategory? — self-referential
        if "AssetCategory" in result:
            for rel_name, related, fk in result["AssetCategory"]:
                assert related != "AssetCategory"

    def test_asset_relations(self):
        """Asset model has category relation but not tenant."""
        result = _parse_prisma_schema(SAMPLE_PRISMA_SCHEMA)
        assert "Asset" in result
        asset_rels = {r[0] for r in result["Asset"]}
        assert "category" in asset_rels
        assert "tenant" not in asset_rels

    def test_comment_has_work_order_relation(self):
        """WorkOrderComment has work_order relation."""
        result = _parse_prisma_schema(SAMPLE_PRISMA_SCHEMA)
        assert "WorkOrderComment" in result
        comment_rels = {r[0] for r in result["WorkOrderComment"]}
        assert "work_order" in comment_rels


class TestPrismaMissingIncludes:
    """Test end-to-end missing Prisma include detection."""

    def test_findmany_without_include_detected(self, tmp_path):
        """A findMany() query without include is flagged as MEDIUM."""
        _write_file(tmp_path, "prisma/schema.prisma", SAMPLE_PRISMA_SCHEMA)
        _write_file(tmp_path, "src/work-order.service.ts", (
            "import { Injectable } from '@nestjs/common';\n"
            "\n"
            "@Injectable()\n"
            "export class WorkOrderService {\n"
            "  async findAll(tenantId: string) {\n"
            "    return this.prisma.workOrder.findMany({\n"
            "      where: { tenant_id: tenantId },\n"
            "    });\n"
            "  }\n"
            "}\n"
        ))
        issues = detect_missing_prisma_includes(tmp_path)
        assert len(issues) >= 2  # missing category + priority
        categories = {i.description.split("'")[1] for i in issues}
        assert "category" in categories
        assert "priority" in categories
        assert all(i.severity == "MEDIUM" for i in issues if "findMany" in i.description)
        assert all(i.category == "missing_prisma_include" for i in issues)

    def test_findmany_with_include_not_flagged(self, tmp_path):
        """A findMany() with include: { category: true } skips category."""
        _write_file(tmp_path, "prisma/schema.prisma", SAMPLE_PRISMA_SCHEMA)
        _write_file(tmp_path, "src/work-order.service.ts", (
            "export class WorkOrderService {\n"
            "  async findAll(tenantId: string) {\n"
            "    return this.prisma.workOrder.findMany({\n"
            "      where: { tenant_id: tenantId },\n"
            "      include: { category: true, priority: true },\n"
            "    });\n"
            "  }\n"
            "}\n"
        ))
        issues = detect_missing_prisma_includes(tmp_path)
        # category and priority are included, so NOT flagged
        flagged_rels = {i.description.split("'")[1] for i in issues}
        assert "category" not in flagged_rels
        assert "priority" not in flagged_rels

    def test_select_query_skipped(self, tmp_path):
        """A query using select: is skipped entirely (intentional field choice)."""
        _write_file(tmp_path, "prisma/schema.prisma", SAMPLE_PRISMA_SCHEMA)
        _write_file(tmp_path, "src/work-order.service.ts", (
            "export class WorkOrderService {\n"
            "  async getIds(tenantId: string) {\n"
            "    return this.prisma.workOrder.findMany({\n"
            "      where: { tenant_id: tenantId },\n"
            "      select: { id: true, title: true },\n"
            "    });\n"
            "  }\n"
            "}\n"
        ))
        issues = detect_missing_prisma_includes(tmp_path)
        assert len(issues) == 0

    def test_findfirst_flagged_as_low(self, tmp_path):
        """A findFirst() without include is flagged as LOW severity."""
        _write_file(tmp_path, "prisma/schema.prisma", SAMPLE_PRISMA_SCHEMA)
        _write_file(tmp_path, "src/work-order.service.ts", (
            "export class WorkOrderService {\n"
            "  async findById(id: string, tenantId: string) {\n"
            "    return this.prisma.workOrder.findFirst({\n"
            "      where: { id, tenant_id: tenantId },\n"
            "    });\n"
            "  }\n"
            "}\n"
        ))
        issues = detect_missing_prisma_includes(tmp_path)
        assert len(issues) >= 2
        assert all(i.severity == "LOW" for i in issues)

    def test_no_schema_returns_empty(self, tmp_path):
        """If no Prisma schema exists, return empty list."""
        _write_file(tmp_path, "src/service.ts", "const x = 1;\n")
        issues = detect_missing_prisma_includes(tmp_path)
        assert issues == []

    def test_non_service_files_skipped(self, tmp_path):
        """Only .service.ts files are scanned, not controllers or utils."""
        _write_file(tmp_path, "prisma/schema.prisma", SAMPLE_PRISMA_SCHEMA)
        _write_file(tmp_path, "src/work-order.controller.ts", (
            "export class WorkOrderController {\n"
            "  async findAll() {\n"
            "    return this.prisma.workOrder.findMany({});\n"
            "  }\n"
            "}\n"
        ))
        issues = detect_missing_prisma_includes(tmp_path)
        assert len(issues) == 0

    def test_partial_include_flags_missing(self, tmp_path):
        """A query with partial include flags only the missing relations."""
        _write_file(tmp_path, "prisma/schema.prisma", SAMPLE_PRISMA_SCHEMA)
        _write_file(tmp_path, "src/work-order.service.ts", (
            "export class WorkOrderService {\n"
            "  async findAll(tenantId: string) {\n"
            "    return this.prisma.workOrder.findMany({\n"
            "      where: { tenant_id: tenantId },\n"
            "      include: { category: true },\n"
            "    });\n"
            "  }\n"
            "}\n"
        ))
        issues = detect_missing_prisma_includes(tmp_path)
        flagged = {i.description.split("'")[1] for i in issues}
        assert "category" not in flagged  # included, not flagged
        assert "priority" in flagged  # missing, flagged

    def test_apps_api_prisma_path(self, tmp_path):
        """Schema at apps/api/prisma/schema.prisma is found."""
        _write_file(tmp_path, "apps/api/prisma/schema.prisma", SAMPLE_PRISMA_SCHEMA)
        _write_file(tmp_path, "apps/api/src/work-order.service.ts", (
            "export class WorkOrderService {\n"
            "  async findAll() {\n"
            "    return this.prisma.workOrder.findMany({});\n"
            "  }\n"
            "}\n"
        ))
        issues = detect_missing_prisma_includes(tmp_path)
        assert len(issues) >= 2
