"""Tests for quality validators (cross-layer consistency checks).

Aligned with architect spec: uses Violation from quality_checks.py,
run_*_scan function names, and ENUM/AUTH/SHAPE/SOFTDEL/QUERY/INFRA check IDs.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from agent_team_v15.quality_checks import Violation
from agent_team_v15.quality_validators import (
    run_quality_validators,
    run_enum_registry_scan,
    run_auth_flow_scan,
    run_response_shape_scan,
    run_soft_delete_scan,
    run_infrastructure_scan,
    _normalize_auth_path,
    _port_names_related,
    _get_soft_delete_models_fallback,
    _get_schema_enums_fallback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


PRISMA_SCHEMA_WITH_SOFT_DELETE = """\
model User {
  id         String   @id @default(uuid())
  email      String   @unique
  name       String
  deleted_at DateTime?
  created_at DateTime @default(now())
}

model Post {
  id         String   @id @default(uuid())
  title      String
  content    String
  deleted_at DateTime?
}

model Comment {
  id      String @id @default(uuid())
  text    String
}
"""

PRISMA_SCHEMA_WITH_ENUMS = """\
enum Role {
  super_admin
  facility_manager
  maintenance_tech
  resident
}

enum WorkOrderStatus {
  draft
  assigned
  in_progress
  completed
  cancelled
}

model User {
  id    String @id
  role  Role   @default("resident")
  name  String
}
"""


# ===========================================================================
# 1. SoftDelete Tests (SOFTDEL-001, SOFTDEL-002, QUERY-001)
# ===========================================================================

class TestSoftDeleteModelExtraction:
    def test_extracts_models_with_deleted_at(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        models = _get_soft_delete_models_fallback(tmp_path)
        assert "User" in models
        assert "Post" in models

    def test_excludes_models_without_deleted_at(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        models = _get_soft_delete_models_fallback(tmp_path)
        assert "Comment" not in models

    def test_includes_camel_case_variant(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        models = _get_soft_delete_models_fallback(tmp_path)
        assert "user" in models
        assert "post" in models

    def test_empty_schema(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", "")
        models = _get_soft_delete_models_fallback(tmp_path)
        assert models == set()

    def test_no_schema_file(self, tmp_path):
        models = _get_soft_delete_models_fallback(tmp_path)
        assert models == set()


class TestSoftDeleteScan:
    def test_detects_unfiltered_findmany(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "src" / "user.service.ts", """\
import { Injectable } from '@nestjs/common';

@Injectable()
export class UserService {
  async findAll() {
    return this.prisma.user.findMany({
      where: { active: true },
    });
  }
}
""")
        findings = run_soft_delete_scan(tmp_path)
        checks = {f.check for f in findings}
        assert "SOFTDEL-001" in checks

    def test_passes_with_deleted_at_filter(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "src" / "user.service.ts", """\
@Injectable()
export class UserService {
  async findAll() {
    return this.prisma.user.findMany({
      where: { deleted_at: null, active: true },
    });
  }
}
""")
        findings = run_soft_delete_scan(tmp_path)
        softdel001_query = [f for f in findings
                            if f.check == "SOFTDEL-001" and "findMany" in f.message]
        assert len(softdel001_query) == 0

    def test_detects_missing_middleware(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        findings = run_soft_delete_scan(tmp_path)
        softdel001 = [f for f in findings if f.check == "SOFTDEL-001"]
        assert len(softdel001) >= 1

    def test_skips_without_prisma_schema(self, tmp_path):
        _write(tmp_path / "src" / "user.service.ts", """\
export class UserService {
  async findAll() {
    return this.prisma.user.findMany();
  }
}
""")
        findings = run_soft_delete_scan(tmp_path)
        assert findings == []

    def test_detects_findFirst_missing_filter(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "src" / "post.service.ts", """\
@Injectable()
export class PostService {
  async findOne(id: string) {
    return this.prisma.post.findFirst({
      where: { id },
    });
  }
}
""")
        findings = run_soft_delete_scan(tmp_path)
        softdel001_query = [f for f in findings
                            if f.check == "SOFTDEL-001" and "findFirst" in f.message]
        assert len(softdel001_query) >= 1

    def test_ignores_model_without_soft_delete(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "src" / "comment.service.ts", """\
@Injectable()
export class CommentService {
  async findAll() {
    return this.prisma.comment.findMany();
  }
}
""")
        findings = run_soft_delete_scan(tmp_path)
        softdel001_query = [f for f in findings
                            if f.check == "SOFTDEL-001" and "comment" in f.message.lower()]
        assert len(softdel001_query) == 0

    def test_middleware_suppresses_per_query_checks(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "src" / "prisma.middleware.ts", """\
prisma.$use(async (params, next) => {
  if (params.action === 'findMany') {
    params.args.where = { ...params.args.where, deleted_at: null };
  }
  return next(params);
});
""")
        _write(tmp_path / "src" / "user.service.ts", """\
@Injectable()
export class UserService {
  async findAll() {
    return this.prisma.user.findMany({});
  }
}
""")
        findings = run_soft_delete_scan(tmp_path)
        # With global middleware, per-query SOFTDEL-001 should not fire
        softdel001_query = [f for f in findings
                            if f.check == "SOFTDEL-001" and "findMany" in f.message]
        assert len(softdel001_query) == 0

    def test_detects_prisma_any_cast(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "src" / "user.service.ts", """\
@Injectable()
export class UserService {
  async rawQuery() {
    return (this.prisma as any).$queryRaw`SELECT * FROM user`;
  }
}
""")
        findings = run_soft_delete_scan(tmp_path)
        query001 = [f for f in findings if f.check == "QUERY-001"]
        assert len(query001) >= 1

    def test_detects_filter_after_paginated_query(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "src" / "user.service.ts", """\
@Injectable()
export class UserService {
  async findPaginated() {
    const items = await this.prisma.user.findMany({
      skip: 0,
      take: 10,
    });
    return items.filter(i => i.active);
  }
}
""")
        findings = run_soft_delete_scan(tmp_path)
        softdel002 = [f for f in findings if f.check == "SOFTDEL-002"
                       and "pagination" in f.message.lower()]
        assert len(softdel002) >= 1

    def test_returns_violation_instances(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        findings = run_soft_delete_scan(tmp_path)
        for f in findings:
            assert isinstance(f, Violation)


# ===========================================================================
# 2. EnumRegistryValidator Tests (ENUM-001, ENUM-002, ENUM-003)
# ===========================================================================

class TestEnumRegistryExtraction:
    def test_extracts_enum_values(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_ENUMS)
        enums = _get_schema_enums_fallback(tmp_path)
        assert "Role" in enums
        assert "super_admin" in enums["Role"]
        assert "maintenance_tech" in enums["Role"]

    def test_extracts_multiple_enums(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_ENUMS)
        enums = _get_schema_enums_fallback(tmp_path)
        assert "WorkOrderStatus" in enums
        assert "draft" in enums["WorkOrderStatus"]

    def test_empty_schema(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", "")
        enums = _get_schema_enums_fallback(tmp_path)
        assert enums == {}


class TestEnumRegistryScan:
    def test_detects_role_mismatch(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_ENUMS)
        _write(tmp_path / "prisma" / "seed.ts", """\
const roles = [
  { name: 'Super Admin', code: 'super_admin' },
  { name: 'Facility Manager', code: 'facility_manager' },
  { name: 'Maintenance Tech', code: 'maintenance_tech' },
  { name: 'Resident', code: 'resident' },
];
""")
        _write(tmp_path / "src" / "stock.controller.ts", """\
@Controller('stock')
export class StockController {
  @Get()
  @Roles('technician')
  findAll() {}
}
""")
        findings = run_enum_registry_scan(tmp_path)
        enum001 = [f for f in findings if f.check == "ENUM-001"]
        assert len(enum001) >= 1
        assert "technician" in enum001[0].message

    def test_passes_matching_roles(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_ENUMS)
        _write(tmp_path / "prisma" / "seed.ts", """\
const roles = [
  { code: 'super_admin' },
  { code: 'facility_manager' },
];
""")
        _write(tmp_path / "src" / "user.controller.ts", """\
@Controller('users')
export class UserController {
  @Get()
  @Roles('super_admin', 'facility_manager')
  findAll() {}
}
""")
        findings = run_enum_registry_scan(tmp_path)
        enum001 = [f for f in findings if f.check == "ENUM-001"]
        assert len(enum001) == 0

    def test_detects_status_enum_mismatch(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_ENUMS)
        _write(tmp_path / "src" / "pages" / "work-orders.tsx", """\
const statuses: string[] = ['draft', 'assigned', 'in_progress', 'completed', 'cancelled', 'archived'];
""")
        findings = run_enum_registry_scan(tmp_path)
        enum002 = [f for f in findings if f.check == "ENUM-002"]
        assert len(enum002) >= 1

    def test_no_mismatch_when_values_match(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_ENUMS)
        _write(tmp_path / "src" / "pages" / "orders.tsx", """\
const statusOptions = ['draft', 'assigned', 'in_progress', 'completed', 'cancelled'];
""")
        findings = run_enum_registry_scan(tmp_path)
        enum002 = [f for f in findings if f.check == "ENUM-002"]
        assert len(enum002) == 0

    def test_skips_without_seed_files(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_ENUMS)
        _write(tmp_path / "src" / "user.controller.ts", """\
@Roles('some_role')
findAll() {}
""")
        findings = run_enum_registry_scan(tmp_path)
        enum001 = [f for f in findings if f.check == "ENUM-001"]
        assert len(enum001) == 0  # No seed data to compare against

    def test_finding_severity_is_error(self, tmp_path):
        _write(tmp_path / "prisma" / "seed.ts", "const roles = [{ code: 'admin' }];")
        _write(tmp_path / "src" / "x.controller.ts", "@Roles('nonexistent')\nfindAll() {}")
        findings = run_enum_registry_scan(tmp_path)
        enum001 = [f for f in findings if f.check == "ENUM-001"]
        for f in enum001:
            assert f.severity == "critical"

    def test_multiple_mismatched_roles(self, tmp_path):
        _write(tmp_path / "prisma" / "seed.ts", "const roles = [{ code: 'admin' }];")
        _write(tmp_path / "src" / "a.controller.ts", """\
@Roles('technician')
findAll() {}
@Roles('inspector')
findOne() {}
""")
        findings = run_enum_registry_scan(tmp_path)
        enum001 = [f for f in findings if f.check == "ENUM-001"]
        roles_found = {f.message for f in enum001}
        found_text = " ".join(roles_found)
        assert "technician" in found_text
        assert "inspector" in found_text

    def test_returns_violation_instances(self, tmp_path):
        _write(tmp_path / "prisma" / "seed.ts", "const roles = [{ code: 'admin' }];")
        _write(tmp_path / "src" / "x.controller.ts", "@Roles('bogus')\nfindAll() {}")
        findings = run_enum_registry_scan(tmp_path)
        for f in findings:
            assert isinstance(f, Violation)


# ===========================================================================
# 3. ResponseShape Tests (SHAPE-001, SHAPE-002, SHAPE-003)
# ===========================================================================

class TestResponseShapeScan:
    def test_detects_case_fallback(self, tmp_path):
        """SHAPE-001: camelCase || snake_case pattern."""
        _write(tmp_path / "src" / "pages" / "users.tsx", """\
const name = firstName || first_name;
""")
        findings = run_response_shape_scan(tmp_path)
        shape001 = [f for f in findings if f.check == "SHAPE-001"]
        assert len(shape001) >= 1

    def test_detects_defensive_array_check(self, tmp_path):
        """SHAPE-002: Array.isArray defensive check."""
        _write(tmp_path / "src" / "pages" / "users.tsx", """\
const fetchUsers = async () => {
  const res = await api.get('/users');
  const data = Array.isArray(res) ? res : res.data;
  setUsers(data);
};
""")
        findings = run_response_shape_scan(tmp_path)
        shape002 = [f for f in findings if f.check == "SHAPE-002"]
        assert len(shape002) >= 1

    def test_detects_data_fallback_pattern(self, tmp_path):
        """SHAPE-002: .data || [] fallback."""
        _write(tmp_path / "src" / "pages" / "orders.tsx", """\
const orders = response.data || [];
""")
        findings = run_response_shape_scan(tmp_path)
        shape002 = [f for f in findings if f.check == "SHAPE-002"]
        assert len(shape002) >= 1

    def test_detects_data_nullish_coalesce(self, tmp_path):
        """SHAPE-002: .data ?? [] fallback."""
        _write(tmp_path / "src" / "pages" / "list.tsx", """\
const items = response.data ?? [];
""")
        findings = run_response_shape_scan(tmp_path)
        shape002 = [f for f in findings if f.check == "SHAPE-002"]
        assert len(shape002) >= 1

    def test_detects_bare_array_return(self, tmp_path):
        """SHAPE-003: Bare array return from list endpoint."""
        _write(tmp_path / "src" / "user.controller.ts", """\
@Controller('users')
export class UserController {
  @Get()
  async findAll() {
    const items = await this.prisma.user.findMany({});
    return items;
  }
}
""")
        findings = run_response_shape_scan(tmp_path)
        shape003 = [f for f in findings if f.check == "SHAPE-003"]
        assert len(shape003) >= 1

    def test_passes_wrapped_response(self, tmp_path):
        _write(tmp_path / "src" / "user.controller.ts", """\
@Controller('users')
export class UserController {
  @Get()
  async findAll() {
    const items = await this.prisma.user.findMany({});
    return { data: items, meta: { total: items.length } };
  }
}
""")
        findings = run_response_shape_scan(tmp_path)
        shape003 = [f for f in findings if f.check == "SHAPE-003"]
        assert len(shape003) == 0

    def test_no_finding_for_normal_response(self, tmp_path):
        _write(tmp_path / "src" / "pages" / "dashboard.tsx", """\
const { data } = await api.get('/stats');
setStats(data);
""")
        findings = run_response_shape_scan(tmp_path)
        shape002 = [f for f in findings if f.check == "SHAPE-002"]
        assert len(shape002) == 0

    def test_detects_silent_catch(self, tmp_path):
        """SHAPE-004: catch block with only console.error, no error state."""
        _write(tmp_path / "src" / "pages" / "users.tsx", """\
const fetchUsers = async () => {
  try {
    const res = await api.get('/users');
    setUsers(res.data);
  } catch (err) {
    console.error('Failed to fetch', err);
  }
};
""")
        findings = run_response_shape_scan(tmp_path)
        shape004 = [f for f in findings if f.check == "SHAPE-004"]
        assert len(shape004) >= 1

    def test_silent_catch_passes_with_error_state(self, tmp_path):
        """SHAPE-004: catch block with setError should NOT fire."""
        _write(tmp_path / "src" / "pages" / "users.tsx", """\
const fetchUsers = async () => {
  try {
    const res = await api.get('/users');
    setUsers(res.data);
  } catch (err) {
    console.error('Failed to fetch', err);
    setError('Failed to load users');
  }
};
""")
        findings = run_response_shape_scan(tmp_path)
        shape004 = [f for f in findings if f.check == "SHAPE-004"]
        assert len(shape004) == 0

    def test_silent_catch_passes_with_toast(self, tmp_path):
        """SHAPE-004: catch block with toast should NOT fire."""
        _write(tmp_path / "src" / "pages" / "orders.tsx", """\
try {
  await api.post('/orders', data);
} catch (error) {
  console.log(error);
  toast.error('Order failed');
}
""")
        findings = run_response_shape_scan(tmp_path)
        shape004 = [f for f in findings if f.check == "SHAPE-004"]
        assert len(shape004) == 0

    def test_no_catch_no_shape004(self, tmp_path):
        """SHAPE-004: No catch block at all should not fire."""
        _write(tmp_path / "src" / "pages" / "simple.tsx", """\
const data = await api.get('/items');
setItems(data);
""")
        findings = run_response_shape_scan(tmp_path)
        shape004 = [f for f in findings if f.check == "SHAPE-004"]
        assert len(shape004) == 0

    def test_empty_project_no_findings(self, tmp_path):
        findings = run_response_shape_scan(tmp_path)
        assert findings == []

    def test_returns_violation_instances(self, tmp_path):
        _write(tmp_path / "src" / "pages" / "x.tsx", """\
const data = Array.isArray(res) ? res : res.data;
""")
        findings = run_response_shape_scan(tmp_path)
        for f in findings:
            assert isinstance(f, Violation)


# ===========================================================================
# 4. AuthFlow Tests (AUTH-001, AUTH-002, AUTH-003, AUTH-004)
# ===========================================================================

class TestNormalizeAuthPath:
    def test_strips_slashes(self):
        assert _normalize_auth_path("/auth/login/") == "auth/login"

    def test_lowercases(self):
        assert _normalize_auth_path("/Auth/Login") == "auth/login"

    def test_replaces_params(self):
        assert _normalize_auth_path("/auth/:userId/verify") == "auth/:id/verify"
        assert _normalize_auth_path("/auth/{id}/verify") == "auth/:id/verify"


class TestAuthFlowScan:
    def test_detects_missing_backend_auth_endpoint(self, tmp_path):
        _write(tmp_path / "src" / "pages" / "login.tsx", """\
const login = async (email: string, password: string) => {
  const res = await api.post('/auth/login', { email, password });
  return res.data;
};
const verifyMfa = async (code: string) => {
  const res = await api.post('/auth/mfa/verify', { code });
  return res.data;
};
""")
        _write(tmp_path / "src" / "auth.controller.ts", """\
@Controller('auth')
export class AuthController {
  @Post('login')
  async login() {}
}
""")
        findings = run_auth_flow_scan(tmp_path)
        auth001 = [f for f in findings if f.check == "AUTH-001"]
        assert len(auth001) >= 1
        assert any("mfa/verify" in f.message for f in auth001)

    def test_passes_matching_auth_endpoints(self, tmp_path):
        _write(tmp_path / "src" / "pages" / "login.tsx", """\
const login = async () => {
  await api.post('/auth/login', {});
};
""")
        _write(tmp_path / "src" / "auth.controller.ts", """\
@Post('auth/login')
async login() {}
""")
        findings = run_auth_flow_scan(tmp_path)
        auth001 = [f for f in findings if f.check == "AUTH-001"]
        assert len(auth001) == 0

    def test_detects_frontend_mfa_without_backend(self, tmp_path):
        _write(tmp_path / "src" / "pages" / "mfa.tsx", """\
const MfaPage = () => {
  const [otpCode, setOtpCode] = useState('');
  const verifyMfa = async () => {};
  return <div>MFA Verification</div>;
};
""")
        _write(tmp_path / "src" / "auth.controller.ts", """\
@Controller('auth')
export class AuthController {
  @Post('login')
  async login() {}
}
""")
        findings = run_auth_flow_scan(tmp_path)
        auth002 = [f for f in findings if f.check == "AUTH-002"]
        assert len(auth002) >= 1

    def test_detects_backend_mfa_without_frontend(self, tmp_path):
        """Backend has MFA routes but no frontend MFA pages."""
        _write(tmp_path / "src" / "pages" / "login.tsx", """\
const login = async () => {
  await api.post('/auth/login', {});
};
""")
        _write(tmp_path / "src" / "auth.controller.ts", """\
@Controller('auth')
export class AuthController {
  @Post('login')
  async login() {}

  @Post('mfa/verify')
  async verifyMfa() {}

  generateTotpSecret() {}
}
""")
        findings = run_auth_flow_scan(tmp_path)
        auth002 = [f for f in findings if f.check == "AUTH-002"]
        assert len(auth002) >= 1

    def test_detects_frontend_refresh_without_backend(self, tmp_path):
        _write(tmp_path / "src" / "lib" / "auth.ts", """\
export const refreshToken = async () => {
  const token = localStorage.getItem('refreshToken');
  const res = await api.post('/auth/refresh', { refresh_token: token });
  return res.data;
};
""")
        _write(tmp_path / "src" / "auth.controller.ts", """\
@Controller('auth')
export class AuthController {
  @Post('login')
  async login() {}
}
""")
        findings = run_auth_flow_scan(tmp_path)
        auth003 = [f for f in findings if f.check == "AUTH-003"]
        assert len(auth003) >= 1

    def test_detects_backend_refresh_without_frontend(self, tmp_path):
        _write(tmp_path / "src" / "pages" / "login.tsx", """\
const login = async () => { await api.post('/auth/login', {}); };
""")
        _write(tmp_path / "src" / "auth.controller.ts", """\
@Controller('auth')
export class AuthController {
  @Post('login')
  async login() {}

  @Post('refresh-token')
  async refreshToken() {}
}
""")
        findings = run_auth_flow_scan(tmp_path)
        auth003 = [f for f in findings if f.check == "AUTH-003"]
        assert len(auth003) >= 1

    def test_detects_cors_localhost(self, tmp_path):
        """AUTH-004: CORS origin with localhost."""
        _write(tmp_path / "src" / "app.module.ts", """\
app.enableCors({ origin: 'http://localhost:3000' });
""")
        findings = run_auth_flow_scan(tmp_path)
        auth004 = [f for f in findings if f.check == "AUTH-004"]
        assert len(auth004) >= 1

    def test_detects_localstorage_token(self, tmp_path):
        """AUTH-004: Token stored in localStorage."""
        _write(tmp_path / "src" / "pages" / "login.tsx", """\
const handleLogin = async () => {
  const { token } = await api.post('/auth/login', creds);
  localStorage.setItem('token', token);
};
""")
        findings = run_auth_flow_scan(tmp_path)
        auth004 = [f for f in findings if f.check == "AUTH-004"]
        assert len(auth004) >= 1

    def test_empty_project_no_findings(self, tmp_path):
        findings = run_auth_flow_scan(tmp_path)
        assert findings == []

    def test_returns_violation_instances(self, tmp_path):
        _write(tmp_path / "src" / "pages" / "login.tsx", """\
await api.post('/auth/login', {});
const mfaSetup = true;
""")
        _write(tmp_path / "src" / "auth.controller.ts", """\
@Post('auth/login')
async login() {}
""")
        findings = run_auth_flow_scan(tmp_path)
        for f in findings:
            assert isinstance(f, Violation)


# ===========================================================================
# 5. Infrastructure Tests (INFRA-001..008)
# ===========================================================================

class TestPortNamesRelated:
    def test_port_match(self):
        assert _port_names_related("PORT", "package.json:PORT") is True

    def test_backend_port_match(self):
        assert _port_names_related("BACKEND_PORT", "backend:PORT") is True

    def test_unrelated(self):
        assert _port_names_related("DATABASE_URL", "package.json:PORT") is False


class TestInfrastructureScan:
    def test_detects_port_mismatch(self, tmp_path):
        _write(tmp_path / ".env", "PORT=3000\n")
        _write(tmp_path / "package.json",
               '{\n  "scripts": {\n    "dev": "next dev --port 4200"\n  }\n}\n')
        findings = run_infrastructure_scan(tmp_path)
        infra001 = [f for f in findings if f.check == "INFRA-001"]
        for f in infra001:
            assert f.severity == "critical"

    def test_no_port_mismatch_when_matching(self, tmp_path):
        _write(tmp_path / ".env", "PORT=3000\n")
        _write(tmp_path / "package.json",
               '{\n  "scripts": {\n    "dev": "next dev -p 3000"\n  }\n}\n')
        findings = run_infrastructure_scan(tmp_path)
        infra001 = [f for f in findings if f.check == "INFRA-001"]
        # Should not flag port mismatch since 3000 == 3000
        assert len(infra001) == 0

    def test_detects_conflicting_next_configs(self, tmp_path):
        _write(tmp_path / "next.config.js", "module.exports = {};")
        _write(tmp_path / "next.config.ts", "export default {};")
        findings = run_infrastructure_scan(tmp_path)
        infra002 = [f for f in findings if f.check == "INFRA-002"]
        assert len(infra002) >= 1
        assert "next.config" in infra002[0].message

    def test_detects_conflicting_vite_configs(self, tmp_path):
        _write(tmp_path / "vite.config.js", "export default {};")
        _write(tmp_path / "vite.config.ts", "export default {};")
        findings = run_infrastructure_scan(tmp_path)
        infra002 = [f for f in findings if f.check == "INFRA-002"]
        assert len(infra002) >= 1

    def test_no_conflict_single_config(self, tmp_path):
        _write(tmp_path / "next.config.js", "module.exports = {};")
        findings = run_infrastructure_scan(tmp_path)
        infra002 = [f for f in findings if f.check == "INFRA-002"]
        assert len(infra002) == 0

    def test_detects_missing_test_exclude_in_tsconfig(self, tmp_path):
        _write(tmp_path / "tsconfig.json", json.dumps({
            "compilerOptions": {"target": "ES2020"},
            "exclude": ["node_modules", "dist"],
        }))
        (tmp_path / "e2e").mkdir()
        findings = run_infrastructure_scan(tmp_path)
        infra003 = [f for f in findings if f.check == "INFRA-003"]
        assert len(infra003) >= 1

    def test_passes_when_tests_excluded(self, tmp_path):
        _write(tmp_path / "tsconfig.json", json.dumps({
            "compilerOptions": {"target": "ES2020"},
            "exclude": ["node_modules", "dist", "e2e", "__tests__"],
        }))
        (tmp_path / "e2e").mkdir()
        findings = run_infrastructure_scan(tmp_path)
        infra003 = [f for f in findings if f.check == "INFRA-003"]
        assert len(infra003) == 0

    def test_detects_no_exclude_with_test_dirs(self, tmp_path):
        _write(tmp_path / "tsconfig.json", json.dumps({
            "compilerOptions": {"target": "ES2020"},
        }))
        (tmp_path / "__tests__").mkdir()
        findings = run_infrastructure_scan(tmp_path)
        infra003 = [f for f in findings if f.check == "INFRA-003"]
        assert len(infra003) >= 1

    def test_no_finding_without_tsconfig(self, tmp_path):
        findings = run_infrastructure_scan(tmp_path)
        infra003 = [f for f in findings if f.check == "INFRA-003"]
        assert len(infra003) == 0

    def test_detects_docker_missing_restart(self, tmp_path):
        """INFRA-004: Docker service missing restart policy."""
        _write(tmp_path / "docker-compose.yml", """\
services:
  app:
    image: node:18
    ports:
      - "3000:3000"
""")
        findings = run_infrastructure_scan(tmp_path)
        infra004 = [f for f in findings if f.check == "INFRA-004"]
        assert len(infra004) >= 1
        assert "app" in infra004[0].message

    def test_detects_docker_missing_healthcheck(self, tmp_path):
        """INFRA-005: Docker service missing healthcheck."""
        _write(tmp_path / "docker-compose.yml", """\
services:
  db:
    image: postgres:15
    restart: unless-stopped
""")
        findings = run_infrastructure_scan(tmp_path)
        infra005 = [f for f in findings if f.check == "INFRA-005"]
        assert len(infra005) >= 1
        assert "db" in infra005[0].message

    def test_docker_passes_with_restart_and_healthcheck(self, tmp_path):
        _write(tmp_path / "docker-compose.yml", """\
services:
  app:
    image: node:18
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000"]
""")
        findings = run_infrastructure_scan(tmp_path)
        infra004 = [f for f in findings if f.check == "INFRA-004"]
        infra005 = [f for f in findings if f.check == "INFRA-005"]
        assert len(infra004) == 0
        assert len(infra005) == 0

    def test_detects_forroutes_star_wildcard(self, tmp_path):
        _write(tmp_path / "apps" / "api" / "src" / "app.module.ts", """\
import { MiddlewareConsumer, Module, NestModule } from '@nestjs/common';

@Module({})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer) {
    consumer.apply(RequestNormalizationMiddleware).forRoutes('*');
  }
}
""")
        findings = run_infrastructure_scan(tmp_path)
        infra007 = [f for f in findings if f.check == "INFRA-007"]
        assert len(infra007) >= 1
        assert "forRoutes" in infra007[0].message

    def test_detects_route_decorator_trailing_star(self, tmp_path):
        _write(tmp_path / "apps" / "api" / "src" / "users.controller.ts", """\
import { Controller, Get } from '@nestjs/common';

@Controller('users/*')
export class UsersController {
  @Get('details/*')
  findAll() {
    return [];
  }
}
""")
        findings = run_infrastructure_scan(tmp_path)
        infra007 = [f for f in findings if f.check == "INFRA-007"]
        assert len(infra007) >= 1

    def test_named_wildcards_do_not_trigger_infra007(self, tmp_path):
        _write(tmp_path / "apps" / "api" / "src" / "app.module.ts", """\
import { MiddlewareConsumer, Module, NestModule } from '@nestjs/common';

@Module({})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer) {
    consumer.apply(RequestNormalizationMiddleware).forRoutes('{*splat}');
  }
}
""")
        _write(tmp_path / "apps" / "api" / "src" / "users.controller.ts", """\
import { Controller, Get } from '@nestjs/common';

@Controller('users/{*splat}')
export class UsersController {
  @Get('details/*splat')
  findAll() {
    return [];
  }
}
""")
        findings = run_infrastructure_scan(tmp_path)
        infra007 = [f for f in findings if f.check == "INFRA-007"]
        assert infra007 == []

    def test_detects_req_query_reassignment(self, tmp_path):
        _write(tmp_path / "apps" / "api" / "src" / "common" / "middleware" / "request-normalization.middleware.ts", """\
import { Injectable, type NestMiddleware } from '@nestjs/common';

@Injectable()
export class RequestNormalizationMiddleware implements NestMiddleware {
  use(req: { query: unknown }, _res: unknown, next: () => void): void {
    req.query = this.normalizeValue(req.query);
    next();
  }

  private normalizeValue(value: unknown): unknown {
    return value;
  }
}
""")
        findings = run_infrastructure_scan(tmp_path)
        infra008 = [f for f in findings if f.check == "INFRA-008"]
        assert len(infra008) >= 1
        assert "req.query" in infra008[0].message

    def test_in_place_query_normalization_does_not_trigger_infra008(self, tmp_path):
        _write(tmp_path / "apps" / "api" / "src" / "common" / "middleware" / "request-normalization.middleware.ts", """\
import { Injectable, type NestMiddleware } from '@nestjs/common';

@Injectable()
export class RequestNormalizationMiddleware implements NestMiddleware {
  use(req: { query: unknown }, _res: unknown, next: () => void): void {
    this.normalizeValue(req.query);
    next();
  }

  private normalizeValue(value: unknown): unknown {
    return value;
  }
}
""")
        findings = run_infrastructure_scan(tmp_path)
        infra008 = [f for f in findings if f.check == "INFRA-008"]
        assert infra008 == []

    def test_empty_project_no_findings(self, tmp_path):
        findings = run_infrastructure_scan(tmp_path)
        assert findings == []


# ===========================================================================
# 6. Main Entry Point Tests
# ===========================================================================

class TestRunQualityValidators:
    def test_empty_project_returns_empty(self, tmp_path):
        findings = run_quality_validators(tmp_path)
        assert findings == []

    def test_runs_all_validators(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "src" / "user.service.ts", """\
@Injectable()
export class UserService {
  async findAll() {
    return this.prisma.user.findMany({});
  }
}
""")
        findings = run_quality_validators(tmp_path)
        assert len(findings) >= 1
        for f in findings:
            assert isinstance(f, Violation)

    def test_filter_by_check_id(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "src" / "user.service.ts", """\
@Injectable()
export class UserService {
  async findAll() {
    return this.prisma.user.findMany({});
  }
}
""")
        findings = run_quality_validators(tmp_path, checks=["SOFTDEL-001"])
        for f in findings:
            assert f.check == "SOFTDEL-001"

    def test_filter_by_category(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        findings = run_quality_validators(tmp_path, checks=["soft-delete"])
        for f in findings:
            assert f.check.startswith("SOFTDEL-") or f.check.startswith("QUERY-")

    def test_results_sorted_by_severity(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        _write(tmp_path / "prisma" / "seed.ts", "const roles = [{ code: 'admin' }];")
        _write(tmp_path / "src" / "x.controller.ts", "@Roles('bogus')\nfindAll() {}")
        _write(tmp_path / "src" / "user.service.ts", """\
@Injectable()
export class UserService {
  async findAll() {
    return this.prisma.user.findMany({});
  }
}
""")
        findings = run_quality_validators(tmp_path)
        severity_order = {"error": 0, "warning": 1, "info": 2}
        for i in range(1, len(findings)):
            prev = severity_order.get(findings[i - 1].severity, 99)
            curr = severity_order.get(findings[i].severity, 99)
            assert prev <= curr or findings[i - 1].file_path <= findings[i].file_path

    def test_returns_violation_instances(self, tmp_path):
        _write(tmp_path / "prisma" / "schema.prisma", PRISMA_SCHEMA_WITH_SOFT_DELETE)
        findings = run_quality_validators(tmp_path)
        for f in findings:
            assert isinstance(f, Violation)
            assert hasattr(f, "check")
            assert hasattr(f, "message")
            assert hasattr(f, "file_path")
            assert hasattr(f, "line")
            assert hasattr(f, "severity")
