# Agent Team v15 — Upgrade Plan

**Date:** 2026-04-01
**Goal:** Prevent all 62 audit findings (12 CRITICAL, 22 HIGH, 17 MEDIUM, 11 LOW) from recurring in future builds.
**Source:** `C:\Projects\ArkanPM\CODEBASE_AUDIT_REPORT.md` (1623 lines, 62 findings across 7 root cause categories)
**Constraint:** 7,491 existing tests — ZERO regressions allowed.
**Companion docs:** `ROOT_CAUSE_MAP.md` (finding-to-builder-gap mapping), `BUILDER_ARCHITECTURE_MAP.md` (pipeline injection points)

---

## Key Insight from Root Cause Analysis

**88.7% of findings (55/62) have rules already written in the builder's prompts/standards but ZERO automated enforcement.** The systemic failure is not missing rules — it is the gap between rules and scanners. Only 18/62 findings (29.0%) have even partial automated checks. Zero findings have complete blocking enforcement.

**Top 5 highest-impact fixes** (covers 75.8% of all findings):
1. Change integration verifier default from "warn" to "block" (18 ROUTE findings)
2. Add Prisma schema scanner (10 SCHEMA findings)
3. Add soft-delete query scanner (5 QUERY findings)
4. Add route convention decision mandate to architect prompt (4 findings)
5. Add automated enum cross-reference scan (6 ENUM findings)

---

## Pipeline Injection Points (from Architecture Map)

All new code plugs into established patterns at documented injection points:

| ID | Location | Type | Risk | Used By |
|----|----------|------|------|---------|
| A1 | cli.py:1816 (after UI compliance, before health gate) | Per-milestone scan | LOW | schema_validator, quality_validators |
| A2 | cli.py:1965 (after integration gate, before audit) | Cross-milestone validation | LOW | route_enforcer |
| B1 | cli.py:7545 (after handler completeness scan) | Post-orchestration scan | **LOWEST** | All new quality_validators scans |
| B2 | cli.py:7621 (after API completeness, before runtime) | Post-orchestration scan | LOW | infrastructure_validator |
| C | cli.py (module-level async functions) | Fix pass functions | LOW | Fix functions for each new scan |
| D | cli.py:5800 (after design extraction, before orchestration) | Pre-flight gate | MEDIUM | infrastructure_validator (pre-flight) |
| E4 | agents.py:848 (end of Section 9) | Prompt standards | LOW | Query correctness, build hygiene |
| E5 | agents.py:898 (end of Section 10) | Serialization mandate | LOW | Serialization verification |
| E6 | agents.py:998+ (new Section 11 subsections) | Integration protocol | LOW | Route convention, enum, auth |
| F | agents.py:2719 (agent definitions) | Agent prompts | MEDIUM | code_quality_standards additions |
| G1 | config.py:295-309 (PostOrchestrationScanConfig) | Config flags | LOW | All new scan toggles |

---

## Table of Contents

1. [Implementation Order](#implementation-order)
2. [Category 1: Route Mismatch Prevention](#category-1-route-mismatch-prevention)
3. [Category 2: Enum/Role Consistency](#category-2-enumrole-consistency)
4. [Category 3: Auth Flow Divergence](#category-3-auth-flow-divergence)
5. [Category 4: Schema Integrity](#category-4-schema-integrity)
6. [Category 5: Serialization/Response Shape](#category-5-serializationresponse-shape)
7. [Category 6: Soft-Delete/Query Correctness](#category-6-soft-deletequery-correctness)
8. [Category 7: Build/Infrastructure](#category-7-buildinfrastructure)
9. [New Modules to Create](#new-modules-to-create)
10. [Existing Modules to Modify](#existing-modules-to-modify)
11. [Agent Assignment Matrix](#agent-assignment-matrix)

---

## Implementation Order

Ordered by: lowest risk first, highest bug-prevention reward, dependency chain.

| Phase | What | Risk | Prevents | Assigned To |
|-------|------|------|----------|-------------|
| 1 | `schema_validator.py` (new module) | LOW (additive) | H-01, H-02, C-05, C-06, H-21 | schema-validator-dev |
| 2 | `quality_validators.py` (new module) | LOW (additive) | C-01, H-03, H-11, H-12, C-06, C-07, C-08, H-21 | quality-gate-dev |
| 3 | Route enforcement in `integration_verifier.py` | MEDIUM (modifies existing) | C-02..C-04, C-09..C-12, H-16, H-17, M-15 | route-enforcer-dev |
| 4 | Prompt engineering in `agents.py` | MEDIUM (modifies existing) | ALL categories (preventive) | prompt-engineer |
| 5 | Pipeline wiring in `cli.py` + `config.py` | MEDIUM (modifies existing) | ALL categories (enforcement) | pipeline-integrator |

---

## Category 1: Route Mismatch Prevention

**Findings:** C-02, C-03, C-04, C-09, C-10, C-11, C-12, H-10, H-16, H-17, M-15, M-17, L-11 (18 findings per ROOT_CAUSE_MAP.md — largest single category at 29.0%)
**Root cause:** Frontend uses nested routes (`/buildings/:id/floors`) but backend registers top-level routes (`/floors`). Also: missing endpoints, singular/plural mismatches, wrong action path names, query parameter mismatches.
**Why the builder failed:** SVC-xxx wiring map is architect-generated with no machine verification; no nested-vs-top-level convention decision; integration verifier runs post-hoc in "warn" mode (never blocks); API_CONTRACTS.json extraction happens between milestones but is not enforced as a compile-time contract.

### 1A. Upgrade `integration_verifier.py` — Route Pattern Enforcement

**File:** `src/agent_team_v15/integration_verifier.py`
**What to modify:** Add a new `RoutePatternEnforcer` class after the existing `IntegrationReport` dataclass (~line 220).

#### New class: `RoutePatternEnforcer`

```python
@dataclass
class RoutePatternViolation:
    """A specific route pattern violation."""
    violation_type: str   # "nested_without_backend" | "missing_endpoint" | "path_mismatch" | "plural_mismatch"
    frontend_path: str    # The path the frontend calls
    backend_path: str | None  # The closest backend match (or None)
    frontend_file: str    # Source file:line
    severity: str         # "CRITICAL" | "HIGH"
    suggestion: str       # Actionable fix suggestion

class RoutePatternEnforcer:
    """Detects nested-vs-top-level route mismatches and missing endpoints."""

    # Common nested patterns that should map to top-level controllers
    NESTED_ROUTE_PATTERNS: list[tuple[re.Pattern, str]] = [
        # /parents/:id/children -> /children with parent_id in body/query
        (re.compile(r'/(\w+)/:[^/]+/(\w+)'), 'nested_resource'),
        # /parents/:id/children/:childId -> /children/:id
        (re.compile(r'/(\w+)/:[^/]+/(\w+)/:[^/]+'), 'nested_resource_with_id'),
    ]
```

**Inputs:**
- `frontend_calls: list[FrontendCall]` — already parsed by existing `_parse_frontend_calls()`
- `backend_endpoints: list[BackendEndpoint]` — already parsed by existing `_parse_backend_endpoints()`

**Outputs:**
- `list[RoutePatternViolation]` — violations with severity and fix suggestions

**Logic:**
1. For each frontend call, normalize the path (strip param segments to `:param`).
2. Check if the normalized frontend path matches ANY backend endpoint (method + path).
3. If no exact match, check if the frontend uses a nested pattern (`/parent/:id/child`) while the backend has a top-level equivalent (`/child`).
4. For nested-vs-top-level mismatches: flag as CRITICAL with suggestion "Frontend uses nested route `X`, but backend only has top-level `Y`. Either add a nested route alias on the backend controller, or change the frontend to call `Y` with parent_id as a query parameter."
5. For missing endpoints (no match at all): flag as CRITICAL with suggestion "Frontend calls `METHOD /path` but no backend endpoint exists. Add the endpoint or remove the frontend call."
6. For plural/singular mismatches (e.g., `/checklist` vs `/checklists`): flag as HIGH with suggestion.

**Integration point:** Called from within existing `verify_integration()` function at **injection point A2** (cli.py:1965), results merged into `IntegrationReport.mismatches`. Also wired into post-orchestration at **injection point B1** (cli.py:7545).

#### Modify: `verify_integration()` function

Add a call to `RoutePatternEnforcer.check()` after the existing mismatch detection, appending any new violations to the report. The enforcer runs as an additional layer — it does NOT replace the existing fuzzy matching.

#### Modify: Severity escalation for route mismatches

Currently `integration_verifier.py` assigns severity based on heuristics. Add a rule: **any frontend call to a path with 2+ segments that has no backend match AND matches a nested pattern gets auto-escalated to CRITICAL**.

#### NEW: Pre-coding integration gate (ROOT_CAUSE_MAP fix #13)

At **injection point D** (cli.py:5800, before orchestration starts), add a pre-flight check that verifies every SVC-xxx wiring entry in REQUIREMENTS.md has a matching backend endpoint in API_CONTRACTS.json. This catches route mismatches BEFORE the frontend coding fleet starts, not after.

### 1B. New prompt section in `agents.py` — Route Convention Mandate

**File:** `src/agent_team_v15/agents.py`
**Where:** New subsection inside SECTION 11 (FRONTEND-BACKEND INTEGRATION PROTOCOL), after line ~998.

**New prompt text (verbatim):**

```
### Route Convention Enforcement (MANDATORY)

When the backend uses CONTROLLER-PER-RESOURCE routing (e.g., NestJS @Controller('floors')):
1. The ARCHITECT must document the EXACT route table in REQUIREMENTS.md, listing every
   endpoint path that the frontend will call.
2. Frontend code-writers MUST call the EXACT paths from the route table — never construct
   nested routes like `/buildings/:id/floors` unless the route table explicitly lists them.
3. If a resource is a child of another (floors belong to buildings), the architect MUST
   decide ONE convention and document it:
   - Option A: Top-level with query filter: `GET /floors?building_id=:id`
   - Option B: Nested route alias: `GET /buildings/:id/floors` (backend adds a sub-route)
   Both are valid, but mixing them is NOT. The route table is the source of truth.
4. The code reviewer MUST cross-reference every frontend API call against the route table.
   Any call to a path NOT in the route table is an AUTOMATIC review failure.
5. For write operations (POST/PATCH/DELETE), the route table MUST specify whether the
   parent ID goes in the URL path or request body. Frontend and backend MUST agree.

Violations detected by the integration verifier:
- ROUTE-001: Frontend calls nested route, backend only has top-level (CRITICAL)
- ROUTE-002: Frontend calls endpoint that does not exist (CRITICAL)
- ROUTE-003: Singular/plural path segment mismatch (HIGH)
- ROUTE-004: Frontend uses different action path than backend (HIGH)
```

**Risk level:** MEDIUM (modifies prompt — could affect agent behavior)
**Prevents findings:** C-02, C-03, C-04, C-09, C-10, C-11, C-12, H-16, H-17, M-15

---

## Category 2: Enum/Role Consistency

**Findings:** C-01, H-09, H-14, H-21, L-08, L-09 (5 findings per ROOT_CAUSE_MAP.md at 8.1%, but H-21 alone covers 94 occurrences)
**Root cause:** No single source of truth for role names, status values, or enum-like strings. `technician` vs `maintenance_tech` is the poster child, but 94+ magic-string fields have the same structural problem.
**Why the builder failed:** Enum Registry is an LLM-generated document with no automated enforcement; seed data is never cross-referenced against guard decorators or frontend queries; no shared constants file enforcement.

### 2A. New validator in `quality_validators.py` — Enum Registry Validator

**File:** `src/agent_team_v15/quality_validators.py` (NEW)
**Class:** `EnumRegistryValidator`

**Inputs:**
- `project_root: Path`
- `scan_scope: ScanScope | None` (reuse from quality_checks.py)

**Outputs:**
- `list[Violation]` using existing `Violation` dataclass from `quality_checks.py`

**Logic — Phase 1: Extract canonical enum values from schema:**
1. Find Prisma schema file (`schema.prisma`) or TypeORM entity files.
2. For each `String @default("value") // val1, val2, val3` pattern in Prisma: extract the field name, model name, and list of valid values from the comment.
3. For each `enum FooStatus { ... }` block: extract the enum name and values.
4. Build a registry: `dict[str, dict[str, list[str]]]` keyed by `model_name.field_name` -> list of valid values.

**Logic — Phase 2: Cross-reference frontend and backend usage:**
1. Scan frontend files for hardcoded string arrays that look like enum values (e.g., `['draft', 'submitted', 'approved']`).
2. Scan backend controller/service files for `@Roles('...')` decorators and role string comparisons.
3. For each usage, check if the value exists in the registry.
4. Flag violations:
   - `ENUM-001`: Frontend uses enum value not in schema registry (e.g., `'technician'` when schema has `'maintenance_tech'`).
   - `ENUM-002`: Backend `@Roles()` decorator uses value not in seed data roles.
   - `ENUM-003`: Magic string field with no enum/CHECK constraint and no comment documenting valid values.

**Violation codes and severities:**
| Code | Severity | Description |
|------|----------|-------------|
| ENUM-001 | error | Frontend enum value not in schema |
| ENUM-002 | error | Backend role/enum value not in schema or seed |
| ENUM-003 | warning | Magic string pseudo-enum without DB constraint |

**Integration point:** Called as a post-orchestration scan in `cli.py`, alongside existing `run_mock_data_scan()`.

### 2B. New prompt section in `agents.py` — Role/Enum Single Source of Truth

**File:** `src/agent_team_v15/agents.py`
**Where:** New subsection inside SECTION 11, after the Route Convention section.

**New prompt text:**

```
### Enum/Role Single Source of Truth (MANDATORY)

Every status, type, role, or categorical string field MUST have exactly ONE canonical
definition. The authority chain is: Database schema > Backend constants > Frontend constants.

Rules:
1. The ARCHITECT must produce an Enum Registry table in REQUIREMENTS.md listing EVERY
   enum/status/role field with its canonical values. This already exists in Section 11
   but is often incomplete — the architect MUST derive values from the Prisma schema
   comments or enum blocks, NOT from assumptions.
2. Backend code MUST define role names as constants (e.g., `const ROLES = { ... }` or a
   TypeScript enum), never as bare strings in decorators.
3. Frontend code MUST import status/role values from a shared constants file, never
   hardcode strings like 'technician' or 'draft' in page components.
4. The DB seed file is the AUTHORITY for role codes. If the seed uses 'maintenance_tech',
   ALL backend decorators and frontend references MUST use 'maintenance_tech'.
5. The code reviewer MUST verify that every @Roles() decorator value and every frontend
   status string appears in the Enum Registry.

Violations:
- ROLE-001: Role string in @Roles() decorator not found in seed data (CRITICAL)
- ROLE-002: Frontend references role/status string not in Enum Registry (CRITICAL)
- ROLE-003: Enum field uses raw strings instead of shared constant (HIGH)
```

**Risk level:** MEDIUM
**Prevents findings:** C-01, H-09, H-14, H-21

---

## Category 3: Auth Flow Divergence

**Findings:** C-08, H-13, M-05, L-04, L-05, L-06 (6 findings per ROOT_CAUSE_MAP.md at 9.7%)
**Root cause:** Frontend implements challenge-token MFA flow, backend implements inline-MFA flow. Also: missing profile fields (avatarUrl), CORS defaults to localhost, JWT doesn't validate roles against DB, localStorage token storage.
**Why the builder failed:** Auth flow treated as just another set of endpoints, not a special multi-step protocol; no auth profile shape contract; security config rules are prescriptive but never verified (no scan for .env port consistency, CORS env var usage, or localStorage token patterns).

### 3A. New validator in `quality_validators.py` — Auth Flow Validator

**File:** `src/agent_team_v15/quality_validators.py` (NEW)
**Class:** `AuthFlowValidator`

**Inputs:**
- `project_root: Path`

**Outputs:**
- `list[Violation]`

**Logic:**
1. Find the frontend auth context/service file (pattern: `auth-context.tsx`, `auth.service.ts`, `auth-provider.tsx`, `useAuth.ts`).
2. Find the backend auth controller and service (pattern: `auth.controller.ts`, `auth.service.ts`).
3. Extract the auth flow steps from each side:
   - Frontend: sequence of API calls made during login/MFA (`POST /auth/login`, `POST /auth/mfa/verify`, expected response fields like `mfaToken`, `requiresMfa`, `accessToken`).
   - Backend: endpoints defined, request parameters expected, response shapes returned.
4. Compare the flows:
   - Does frontend expect a field that backend doesn't return? (e.g., `mfaToken`)
   - Does backend expect a parameter that frontend doesn't send? (e.g., `mfaCode` inline)
   - Does frontend call an endpoint as unauthenticated that backend protects with `@UseGuards(JwtAuthGuard)`?
5. Flag violations:
   - `AUTH-001`: Frontend expects response field that backend does not return (CRITICAL)
   - `AUTH-002`: Backend requires request parameter that frontend does not send (CRITICAL)
   - `AUTH-003`: Frontend calls protected endpoint without authentication token (CRITICAL)
   - `AUTH-004`: MFA flow state machine mismatch — different number of steps (CRITICAL)

**Integration point:** Called during integration verification phase in `cli.py`, only when both auth frontend and auth backend files are detected.

### 3B. New prompt section in `agents.py` — Auth Flow Contract

**File:** `src/agent_team_v15/agents.py`
**Where:** New subsection inside SECTION 11.

**New prompt text:**

```
### Authentication Flow Contract (MANDATORY)

The auth flow is the MOST CRITICAL integration point. Frontend and backend MUST implement
the EXACT SAME authentication state machine.

Rules:
1. The ARCHITECT must document the COMPLETE auth flow as a state machine in REQUIREMENTS.md:
   - Step 1: What the frontend sends, what the backend returns
   - Step 2: (if MFA) What the frontend sends, what the backend returns
   - Token storage: where tokens go (localStorage, sessionStorage, httpOnly cookie)
   - Token refresh: how expired tokens are refreshed
2. The auth flow MUST be implemented in the FOUNDATION milestone, not split across milestones.
3. Frontend and backend auth code MUST agree on:
   - Response field names (e.g., `accessToken` vs `access_token` vs `token`)
   - Whether MFA verification requires an existing JWT or a challenge token
   - What HTTP status codes are returned for each error state
4. The code reviewer MUST trace the COMPLETE login flow end-to-end:
   a. Frontend sends credentials -> Backend validates -> Response shape matches frontend expectation
   b. If MFA: Frontend sends MFA code -> Backend verifies -> Token issuance matches frontend expectation
   c. Frontend stores token -> Subsequent API calls include token -> Backend validates token
5. Any mismatch = CRITICAL review failure.

Violations:
- AUTH-001: Frontend expects field backend doesn't return (CRITICAL)
- AUTH-002: Backend requires param frontend doesn't send (CRITICAL)
- AUTH-003: Frontend calls guarded endpoint without token (CRITICAL)
```

**Risk level:** MEDIUM
**Prevents findings:** C-08

---

## Category 4: Schema Integrity

**Findings:** C-05, H-01, H-02, H-21, M-01, M-06, M-12, M-13, M-16, L-01, L-02 (12 findings per ROOT_CAUSE_MAP.md at 19.4% — second largest category)
**Root cause:** No automated schema validation — cascade rules, relation annotations, type defaults, and index coverage are never checked.
**Why the builder failed:** Schema standards are comprehensive prose mandates with ZERO automated scanners in quality_checks.py. No `_check_prisma_relations()`, no `_check_prisma_cascades()`, no `_check_prisma_indexes()`. Soft-delete middleware is mandated but never verified. No Prisma-specific schema validation phase in verification.py. Tenant isolation mandated but not structurally verified.

### 4A. New module: `schema_validator.py`

**File:** `src/agent_team_v15/schema_validator.py` (NEW — ~400-600 lines)

#### Class: `PrismaSchemaValidator`

**Inputs:**
- `project_root: Path`
- `schema_path: Path | None` (auto-detect if None: glob for `**/schema.prisma`)

**Outputs:**
- `SchemaValidationReport` dataclass:

```python
@dataclass
class SchemaViolation:
    code: str          # "SCHEMA-001" through "SCHEMA-010"
    severity: str      # "error" | "warning"
    model: str         # Prisma model name
    field: str         # Field name
    line: int          # Line number in schema file
    message: str       # Human-readable description
    suggestion: str    # Actionable fix

@dataclass
class SchemaValidationReport:
    violations: list[SchemaViolation]
    models_checked: int
    relations_checked: int
    passed: bool       # True if zero error-severity violations
```

**Validation rules (each a method on the class):**

| Rule | Code | Severity | What it checks |
|------|------|----------|---------------|
| Missing cascade | SCHEMA-001 | error | Every `@relation` with a FK field that points to a parent model MUST have `onDelete: Cascade` or `onDelete: SetNull`. Flag if missing. |
| Missing @relation | SCHEMA-002 | error | Every field ending in `_id` that is NOT part of an `@@id` or `@@unique` MUST have a corresponding `@relation` annotation on a companion field. |
| Invalid UUID default | SCHEMA-003 | error | No `@default("")` on UUID/String FK fields. Valid defaults: `@default(uuid())`, `@default(cuid())`, or make field optional (`String?`). |
| Missing index on FK | SCHEMA-004 | warning | Every FK field (`_id` suffix with `@relation`) should have an `@@index`. |
| Soft-delete without middleware | SCHEMA-005 | warning | If >50% of models have `deleted_at DateTime?`, flag if no Prisma middleware file exists that filters by `deleted_at`. |
| Magic string pseudo-enum | SCHEMA-006 | warning | `String @default("value")` with a comment listing valid values — suggest using Prisma `enum` or adding a `CHECK` constraint. |
| Type inconsistency | SCHEMA-007 | warning | Financial fields (`cost`, `price`, `amount`, `total`) using different `@db.Decimal` precisions within the same schema. |
| Tenant isolation gap | SCHEMA-008 | error | Models with `tenant_id` field that is nullable (`String?`) when other models use non-nullable `String`. |
| Self-referential missing relation | SCHEMA-009 | warning | Field ending in `_id` that references the same model (e.g., `parent_asset_id` on Asset) without `@relation`. |
| Missing unique constraint | SCHEMA-010 | warning | Multi-tenant models missing `@@unique([tenant_id, ...])` for fields that should be unique per tenant. |

**Parsing approach:**
1. Read the schema file as text.
2. Parse model blocks: `model Name { ... }` — extract model name, fields, annotations.
3. For each field, extract: name, type, optional (`?`), default, `@relation` args, `@db.*` annotations.
4. Build a model graph: map of model name -> list of fields, and relation graph (parent -> children).
5. Apply each validation rule against the parsed model graph.

**Error handling:**
- If no schema file found: return empty report with a warning-level violation `SCHEMA-000: No Prisma schema found`.
- If schema has syntax errors: return empty report with error `SCHEMA-000: Schema parse error at line N`.
- Never crash the pipeline — always return a report.

#### Class: `TypeORMSchemaValidator`

Same interface as `PrismaSchemaValidator` but parses TypeORM entity decorators (`@Entity()`, `@Column()`, `@ManyToOne()`, etc.). Lower priority — implement after Prisma validator works.

**Integration point:** Called as a pipeline gate in `cli.py` during the verification phase, after build check but before test run. Blocking on error-severity violations.

**Risk level:** LOW (purely additive new module)
**Prevents findings:** H-01, H-02, C-05, C-06 (field reference), H-21, M-01, M-06, M-12, M-13, L-01, L-02

---

## Category 5: Serialization/Response Shape

**Findings:** H-11, H-12, M-07, M-09, L-07, L-10 (5 findings per ROOT_CAUSE_MAP.md at 8.1%)
**Root cause:** CamelCaseResponseInterceptor doesn't transform all responses; some list endpoints return bare arrays instead of `{data, meta}` wrapper; response fields are not validated.
**Why the builder failed:** Serialization interceptor was created but is incomplete/buggy (50+ fallbacks prove it); response wrapping has no structural enforcement; field-name mismatch detection is post-hoc and non-blocking ("warn" mode).

### 5A. New validator in `quality_validators.py` — Response Shape Validator

**File:** `src/agent_team_v15/quality_validators.py` (NEW)
**Class:** `ResponseShapeValidator`

**Inputs:**
- `project_root: Path`
- `scan_scope: ScanScope | None`

**Outputs:**
- `list[Violation]`

**Logic:**

**Rule 1: Detect field name fallback patterns (SHAPE-001)**
1. Scan all frontend `.tsx`, `.ts` files (excluding node_modules, .next).
2. Regex: `(\w+)\s*\|\|\s*(\w+)` where one side is camelCase and the other is snake_case for the same conceptual field.
3. Also detect: `item\.(\w+)\s*\?\?\s*item\.(\w+)` (nullish coalescing fallback).
4. Each match = violation `SHAPE-001: Field name fallback pattern detected — frontend accesses both '{camelCase}' and '{snake_case}'. The serialization interceptor should make one convention sufficient.`
5. Severity: warning (indicates the interceptor isn't working, but the fallback prevents runtime crash).

**Rule 2: Detect defensive array extraction (SHAPE-002)**
1. Scan frontend files.
2. Regex: `Array\.isArray\(\w+\)\s*\?\s*\w+\s*:\s*\w+\.(?:data|results?)` or `Array\.isArray\(\w+\)\s*\?\s*\w+\s*:\s*\w+\?\.data\s*\?\?\s*\[\]`
3. Each match = violation `SHAPE-002: Defensive array extraction pattern — list response shape is inconsistent. All list endpoints should return {data, meta}.`
4. Severity: warning.

**Rule 3: Detect missing response fields (SHAPE-003)**
1. Cross-reference frontend field access (from integration_verifier's response field parser) against backend service return shapes.
2. If frontend accesses `user.avatarUrl` but the backend auth profile response doesn't include `avatarUrl` (or `avatar_url`): flag as `SHAPE-003: Frontend expects field 'avatarUrl' but backend response does not include it.`
3. Severity: error.

**Integration point:** Post-orchestration scan alongside existing scans.

### 5B. Upgrade prompt in `agents.py` — Strengthen Section 10 & 11

**File:** `src/agent_team_v15/agents.py`
**Where:** Append to end of SECTION 10 (Serialization Convention Mandate, ~line 920) and SECTION 11 (Response Wrapping Convention, ~line 940).

**Additions to Section 10:**

```
### Serialization Verification Checklist (MANDATORY for reviewers)
Before marking any milestone complete, the reviewer MUST verify:
1. The CamelCaseResponseInterceptor (or equivalent) is registered globally
2. It transforms ALL of these:
   - Top-level response keys
   - Nested object keys (e.g., `building.building_name` -> `building.buildingName`)
   - Array element keys
   - Pagination meta keys
3. NO frontend file contains `fieldName || field_name` fallback patterns
4. If fallbacks are found, the interceptor is BROKEN — fix the interceptor, don't add fallbacks
```

**Additions to Section 11 (Response Wrapping):**

```
### Response Shape Enforcement
The code reviewer MUST verify:
1. EVERY list endpoint returns `{ data: T[], meta: { total, page, limit, totalPages } }`
2. NO list endpoint returns a bare array `[...]`
3. NO frontend code uses `Array.isArray(res) ? res : res.data` — this pattern indicates
   inconsistent backend response shapes and MUST be fixed at the source
4. The frontend has a typed API client that enforces the response shape:
   ```typescript
   interface PaginatedResponse<T> { data: T[]; meta: { total: number; page: number; limit: number; totalPages: number; } }
   ```
```

**Risk level:** MEDIUM
**Prevents findings:** H-11, H-12, H-13

---

## Category 6: Soft-Delete/Query Correctness

**Findings:** C-06, C-07, H-03, H-04, H-05, H-06, H-07, H-08, M-02, M-03, M-04, M-08, M-14, L-03 (10 findings per ROOT_CAUSE_MAP.md at 16.1%)
**Root cause:** No enforcement that queries on soft-deletable models include `deleted_at: null`; no check that field names in `where`/`include` clauses actually exist on the model.
**Why the builder failed:** Soft-delete is in Tier 3 ("IF CONTEXT BUDGET PERMITS") meaning it gets deprioritized; Prisma query correctness is never statically analyzed; `(this.prisma as any)` casts in 6+ services suppress TypeScript type checking; no post-pagination filter detector; no `prisma validate` in verification pipeline.

### 6A. New validator in `quality_validators.py` — Soft-Delete Query Validator

**File:** `src/agent_team_v15/quality_validators.py` (NEW)
**Class:** `SoftDeleteValidator`

**Inputs:**
- `project_root: Path`
- `schema_models: dict` (output from `PrismaSchemaValidator.parse()` — list of models and their fields)

**Outputs:**
- `list[Violation]`

**Logic:**

**Step 1: Identify soft-deletable models**
1. From the parsed schema, find all models that have a `deleted_at` field (type `DateTime?`).
2. Build a set: `soft_deletable_models: set[str]`.

**Step 2: Scan service files for queries missing the filter**
1. Find all backend `.service.ts` files.
2. For each file, find Prisma query calls: `this.prisma.modelName.findMany(`, `this.prisma.modelName.findFirst(`, `this.prisma.modelName.findUnique(`, `this.prisma.modelName.count(`.
3. Extract the model name from the call (e.g., `this.prisma.workRequest.findMany` -> `WorkRequest`).
4. If the model is in `soft_deletable_models`, check if the query's `where` clause includes `deleted_at: null`.
5. If not: violation `SOFTDEL-001: Query on soft-deletable model '{model}' in {file}:{line} does not filter by deleted_at: null. Deleted records will appear in results.` Severity: error.

**Step 3: Detect invalid field references in where/include**
1. For each Prisma query call, extract field names from `where: { ... }` and `include: { ... }` clauses.
2. Cross-reference against the parsed schema model's fields.
3. If a field is referenced that doesn't exist on the model: violation `SOFTDEL-002: Query references field '{field}' on model '{model}' in {file}:{line}, but this field does not exist in the schema.` Severity: error.

**Step 4: Detect `(this.prisma as any)` type casts**
1. Regex: `\(this\.prisma\s+as\s+any\)` or `(this.prisma as any)`.
2. Each match: violation `QUERY-001: Prisma client cast to 'any' bypasses type safety in {file}:{line}. This hides schema mismatches.` Severity: warning.

**Integration point:** Called as a post-orchestration scan. Requires schema_validator output (model metadata).

### 6B. New prompt section in `agents.py` — Query Correctness Rules

**File:** `src/agent_team_v15/agents.py`
**Where:** New subsection inside SECTION 9 (Cross-Service Implementation Standards), after the Database & Migration Standards block (~line 827).

**New prompt text:**

```
### Query Correctness Rules (MANDATORY)

Soft-Delete Enforcement:
1. If the schema uses soft-delete (deleted_at DateTime?), EVERY query on soft-deletable
   models MUST include `where: { deleted_at: null }` — no exceptions.
2. The FOUNDATION milestone MUST implement a Prisma middleware that auto-adds this filter:
   ```typescript
   prisma.$use(async (params, next) => {
     if (['findMany', 'findFirst', 'count'].includes(params.action)) {
       if (params.model && softDeletableModels.has(params.model)) {
         params.args.where = { ...params.args.where, deleted_at: null };
       }
     }
     return next(params);
   });
   ```
3. Code-writers MUST NOT cast `this.prisma as any` to bypass TypeScript type checking.
   If a Prisma query type error occurs, the fix is in the schema or the query, not the cast.

Field Reference Validation:
4. Every field in a `where`, `include`, `select`, or `orderBy` clause MUST exist on the
   target Prisma model. If TypeScript flags a field as unknown, DO NOT suppress it — fix it.
5. When including relations, verify the relation name matches the schema (e.g., `warranty`
   not `provider` if `provider` is a plain field, not a relation).
6. Invalid UUID fallbacks: NEVER use magic strings like `'no-match'` as UUID substitutes.
   Throw BadRequestException("Invalid {parameter}") instead.
```

**Risk level:** MEDIUM
**Prevents findings:** H-03, C-06, C-07, H-04, H-05, H-06, H-07, M-02, M-03, M-04, M-14

---

## Category 7: Build/Infrastructure

**Findings:** H-15, H-18, H-19, H-20, H-22, M-10, M-11 (6 findings per ROOT_CAUSE_MAP.md at 9.7%)
**Root cause:** No pre-flight checks for port consistency, build health, migration status, or test suite status.
**Why the builder failed:** Build verification doesn't catch tsconfig scope issues; migration status (`prisma migrate status`) is not verified; test failures may not block completion; silent error handling (H-15) has standard FRONT-014 but no quality_checks.py pattern; deployment scans are advisory-only (non-blocking).

### 7A. New validator in `quality_validators.py` — Infrastructure Validator

**File:** `src/agent_team_v15/quality_validators.py` (NEW)
**Class:** `InfrastructureValidator`

**Inputs:**
- `project_root: Path`

**Outputs:**
- `list[Violation]`

**Logic:**

**Rule 1: Port consistency (INFRA-001)**
1. Find `.env` files and extract port numbers (pattern: `PORT=\d+`, `FRONTEND_URL=.*:(\d+)`).
2. Find `package.json` files and extract dev server ports (pattern: `--port (\d+)`, `PORT=(\d+)`).
3. Find `docker-compose.yml` and extract port mappings.
4. If any two sources disagree on the same service's port: violation `INFRA-001: Port mismatch — .env says {port1} but package.json says {port2}.` Severity: error.

**Rule 2: Build config conflicts (INFRA-002)**
1. Check for duplicate config files: `next.config.js` AND `next.config.ts`, `tsconfig.json` with no exclusions for test directories.
2. If both `.js` and `.ts` config files exist for the same tool: violation `INFRA-002: Conflicting config files — both {file1} and {file2} exist.` Severity: error.

**Rule 3: TypeScript compilation scope (INFRA-003)**
1. Parse `tsconfig.json` files.
2. If `include` is `["**/*.ts"]` or similar broad pattern, and no `exclude` for `e2e/`, `test/`, `__tests__/`: check if those directories exist and contain imports not in dependencies.
3. Violation: `INFRA-003: tsconfig includes {dir} which imports {package} not in dependencies.` Severity: error.

**Rule 4: Docker health (INFRA-004)**
1. Parse `docker-compose.yml`.
2. If any service lacks `restart:` policy: violation `INFRA-004: Service '{name}' has no restart policy.` Severity: warning.
3. If any service lacks `healthcheck:`: violation `INFRA-005: Service '{name}' has no health check.` Severity: warning.

**Integration point:** Runs once at pipeline start (before milestone loop) as a pre-flight check.

### 7B. New prompt section in `agents.py` — Build Hygiene Rules

**File:** `src/agent_team_v15/agents.py`
**Where:** Append to SECTION 9 after the Dockerfile Standards block (~line 837).

**New prompt text:**

```
### Build Hygiene Rules (MANDATORY)

1. Port Consistency: Every port number MUST be defined in ONE place (.env) and referenced
   elsewhere. If package.json has `--port 4200`, then `.env` MUST have `FRONTEND_URL=...4200`.
2. Config File Uniqueness: Only ONE config file per tool. If `next.config.ts` exists, delete
   `next.config.js`. If `vite.config.ts` exists, delete `vite.config.js`.
3. TypeScript Compilation Scope: `tsconfig.json` MUST exclude test/e2e directories that
   import devDependencies. Add `"exclude": ["e2e", "**/*.spec.ts"]` as appropriate.
4. Migration Freshness: The FOUNDATION milestone MUST run `prisma migrate deploy` (or
   equivalent) and verify all migrations are applied. No unapplied migrations allowed.
5. Test Suite Health: If existing tests fail before any code changes, document them in
   REQUIREMENTS.md as known failures. Do NOT allow the overall test failure count to increase.
```

**Risk level:** LOW
**Prevents findings:** H-18, H-19, H-20, H-22, M-05, M-11

---

## New Modules to Create

### Module 1: `src/agent_team_v15/schema_validator.py`

**Purpose:** Prisma/TypeORM schema integrity checker.
**Size estimate:** 400-600 lines.
**Classes:**
- `PrismaSchemaParser` — parses `schema.prisma` into a model graph
- `PrismaSchemaValidator` — applies validation rules against the model graph
- `TypeORMSchemaValidator` — same for TypeORM entities (lower priority)
- `SchemaViolation`, `SchemaValidationReport` — result dataclasses

**Dependencies:** stdlib only (re, pathlib, dataclasses). Reuses `Violation` from `quality_checks.py` for the pipeline-facing output, but uses its own `SchemaViolation` internally for richer data.

**Public API:**
```python
def validate_prisma_schema(project_root: Path) -> SchemaValidationReport:
    """Find and validate the Prisma schema. Returns report with violations."""

def get_schema_models(project_root: Path) -> dict[str, ModelInfo]:
    """Parse schema and return model metadata (fields, relations, types).
    Used by other validators (SoftDeleteValidator, EnumRegistryValidator)."""
```

**Test plan:**
- Unit tests with inline schema strings (no file I/O).
- Test each rule individually with a minimal failing schema.
- Test the parser with the ArkanPM schema as an integration test.
- Target: 25-35 tests.

---

### Module 2: `src/agent_team_v15/quality_validators.py`

**Purpose:** Centralized validators for soft-delete, enum registry, response shape, auth flow, and infrastructure checks.
**Size estimate:** 600-900 lines.
**Classes:**
- `EnumRegistryValidator` — cross-checks enum values across schema/backend/frontend (Category 2)
- `AuthFlowValidator` — verifies frontend and backend auth flows match (Category 3)
- `ResponseShapeValidator` — detects field fallback patterns and inconsistent response shapes (Category 5)
- `SoftDeleteValidator` — ensures queries filter by deleted_at on soft-deletable models (Category 6)
- `InfrastructureValidator` — port consistency, config conflicts, build health (Category 7)

**Dependencies:** stdlib only. Imports `Violation`, `ScanScope` from `quality_checks.py`. Imports `get_schema_models` from `schema_validator.py`.

**Public API (one function per validator, matching existing scan function signatures):**
```python
def run_enum_registry_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
def run_auth_flow_scan(project_root: Path) -> list[Violation]:
def run_response_shape_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
def run_soft_delete_scan(project_root: Path, scope: ScanScope | None = None) -> list[Violation]:
def run_infrastructure_scan(project_root: Path) -> list[Violation]:
```

**Test plan:**
- Unit tests per validator with fixture files (small .ts/.prisma snippets).
- Each validator: 10-15 tests (happy path, each violation type, edge cases).
- Target: 50-75 tests total.

---

## Existing Modules to Modify

### 1. `agents.py` — New Prompt Sections

**Changes:**
| Location | What | Section Reference |
|----------|------|-------------------|
| After line ~998 (end of Section 11) | Route Convention Enforcement block | Category 1, 1B |
| After Route Convention block | Enum/Role Single Source of Truth block | Category 2, 2B |
| After Enum/Role block | Authentication Flow Contract block | Category 3, 3B |
| After line ~827 (Section 9, after DB standards) | Query Correctness Rules block | Category 6, 6B |
| After line ~837 (Section 9, after Dockerfile) | Build Hygiene Rules block | Category 7, 7B |
| After line ~920 (end of Section 10) | Serialization Verification Checklist | Category 5, 5B |
| After line ~940 (Section 11, Response Wrapping) | Response Shape Enforcement block | Category 5, 5B |

**Estimated added lines:** ~150 lines of prompt text.
**Risk:** MEDIUM — prompt changes affect all agent behavior. Each section must be tested with a dry-run build to verify no regression in existing quality checks.

### 2. `cli.py` — Wire New Validators as Pipeline Gates

**Changes:**

#### 2a. Pre-flight infrastructure check (runs ONCE before milestone loop)

**Location:** In `_run_pipeline()` or equivalent, before the milestone iteration begins (~line 1800 area, before `for milestone in milestones:`).

```python
# Pre-flight infrastructure checks
from .quality_validators import run_infrastructure_scan
infra_violations = run_infrastructure_scan(project_root)
infra_errors = [v for v in infra_violations if v.severity == "error"]
if infra_errors:
    for v in infra_errors:
        print_warning(f"[{v.check}] {v.message} at {v.file_path}:{v.line}")
    if config.verification.blocking:
        print_error(f"Pre-flight: {len(infra_errors)} infrastructure errors. Fix before proceeding.")
        # Don't abort — log and continue (infrastructure issues are often env-specific)
```

#### 2b. Schema validation gate (runs ONCE after foundation milestone)

**Location:** After the first milestone completes (or after any milestone that creates/modifies `schema.prisma`).

```python
# Schema validation gate
from .schema_validator import validate_prisma_schema
schema_report = validate_prisma_schema(project_root)
if not schema_report.passed:
    schema_errors = [v for v in schema_report.violations if v.severity == "error"]
    for v in schema_errors:
        print_warning(f"[{v.code}] {v.message} in {v.model}.{v.field} (line {v.line})")
    if config.integration_gate.verification_mode == "block":
        # Block milestone completion
        milestone.status = "FAILED"
```

#### 2c. Post-orchestration scans (runs after each milestone)

**Location:** In the post-orchestration scan section (~line 6717-7125 area), alongside existing scans.

Add calls to:
- `run_enum_registry_scan()` — after `run_api_contract_scan()`
- `run_response_shape_scan()` — after `run_endpoint_xref_scan()`
- `run_soft_delete_scan()` — after `run_relationship_scan()`
- `run_auth_flow_scan()` — after integration verification, only on auth-related milestones

Each follows the existing pattern:
```python
if config.post_orchestration_scans.enum_registry_scan:  # new config field
    from .quality_validators import run_enum_registry_scan
    enum_violations = run_enum_registry_scan(project_root, scope=scan_scope)
    if enum_violations:
        # ... same reporting pattern as existing scans ...
```

#### 2d. Integration verifier upgrade to blocking gate

**Location:** Integration verification section (~line 1900-1965).

**Change:** Default `verification_mode` from `"warn"` to `"block"` for fullstack milestones. Add route pattern enforcement results to the blocking criteria.

```python
# In the integration verification block, after line 1915:
from .integration_verifier import RoutePatternEnforcer
route_violations = RoutePatternEnforcer(
    integration_report.frontend_calls,
    integration_report.backend_endpoints,
).check()
critical_route = [v for v in route_violations if v.severity == "CRITICAL"]
if critical_route:
    high_severity.extend(...)  # Add to existing high_severity list
```

### 3. `config.py` — New Configuration Dataclasses

**Changes to `PostOrchestrationScanConfig`:**

Add these fields after `handler_completeness_scan` (line ~307):

```python
@dataclass
class PostOrchestrationScanConfig:
    # ... existing fields ...
    enum_registry_scan: bool = True        # ENUM-001/002/003 validation
    response_shape_scan: bool = True       # SHAPE-001/002/003 validation
    soft_delete_scan: bool = True          # SOFTDEL-001/002 validation
    auth_flow_scan: bool = True            # AUTH-001/002/003/004 validation
    infrastructure_scan: bool = True       # INFRA-001 through INFRA-005
    schema_validation: bool = True         # SCHEMA-001 through SCHEMA-010
```

**Changes to `IntegrationGateConfig`:**

Change default `verification_mode` from `"warn"` to `"block"`:

```python
verification_mode: str = "block"  # Changed from "warn" — route mismatches are now blocking
```

Add new field:

```python
route_pattern_enforcement: bool = True  # Enable nested-vs-top-level route detection
```

**Changes to `AgentTeamConfig`:**

No structural changes needed — the new scan config fields are added to existing dataclasses.

### 4. `integration_verifier.py` — Route Pattern Enforcement

**Changes:**
- Add `RoutePatternViolation` dataclass (~10 lines)
- Add `RoutePatternEnforcer` class (~100-150 lines)
- Modify `verify_integration()` to call the enforcer (~10 lines)
- Add nested-vs-top-level detection regex patterns (~15 lines)
- Add severity escalation rule for unmatched nested routes (~5 lines)

**Total added lines:** ~180-190 lines.

### 5. `code_quality_standards.py` — New Standards

**Changes:** Add new standards blocks for each error category.

**Add to BACKEND_STANDARDS (after BACK-005, ~line 150):**

```python
**BACK-006: Missing Soft-Delete Filter**
- NEVER query a soft-deletable model (has deleted_at field) without filtering by deleted_at: null.
- FIX: Add { deleted_at: null } to every where clause, or use Prisma middleware for auto-filtering.

**BACK-007: Invalid Field Reference**
- NEVER reference a field in where/include/select that doesn't exist on the Prisma model.
- FIX: Check the schema. If TypeScript flags the field, the field doesn't exist — fix the query.

**BACK-008: Prisma Type Safety Bypass**
- NEVER cast `this.prisma as any` to suppress type errors.
- FIX: Fix the underlying type error. If the model doesn't have the field, update the schema or query.

**BACK-009: Magic String UUID Fallback**
- NEVER use non-UUID strings like 'no-match' as ID placeholders in queries.
- FIX: Throw BadRequestException with a descriptive error message.

**BACK-010: Inconsistent Response Wrapper**
- NEVER return bare arrays from list endpoints in some controllers and {data, meta} in others.
- FIX: Use a consistent pagination wrapper for ALL list endpoints.
```

**Add to FRONTEND_STANDARDS (after FRONT-021, ~line 102):**

```python
**FRONT-022: Field Name Fallback Pattern**
- NEVER write `item.fieldName || item.field_name` as a defensive pattern.
- This indicates the serialization interceptor is broken. FIX the interceptor.

**FRONT-023: Defensive Array Extraction**
- NEVER write `Array.isArray(res) ? res : res.data || []` for list responses.
- This indicates inconsistent backend response shapes. FIX the backend.

**FRONT-024: Hardcoded Route Construction**
- NEVER construct nested API routes like `/buildings/${id}/floors` unless the route table explicitly lists them.
- FIX: Use the route table from REQUIREMENTS.md. If the endpoint is top-level, call it as top-level.
```

---

## Agent Assignment Matrix

| Agent | Primary Module | Files to Create/Modify | Depends On |
|-------|---------------|----------------------|------------|
| **schema-validator-dev** | `schema_validator.py` | Create `schema_validator.py` + tests | Nothing (start immediately) |
| **quality-gate-dev** | `quality_validators.py` | Create `quality_validators.py` + tests | schema_validator.py (for model metadata) |
| **route-enforcer-dev** | `integration_verifier.py` | Modify `integration_verifier.py` + tests | Nothing (start immediately) |
| **prompt-engineer** | `agents.py`, `code_quality_standards.py` | Modify both files | Nothing (start immediately) |
| **pipeline-integrator** | `cli.py`, `config.py` | Modify both files | ALL other agents (runs last) |

### Dependency Graph

```
schema-validator-dev ─────┐
                          ├──> pipeline-integrator
route-enforcer-dev ───────┤
                          │
prompt-engineer ──────────┤
                          │
quality-gate-dev ─────────┘
       │
       └── depends on schema-validator-dev (for get_schema_models)
```

### Parallel Work

- **Phase A (parallel):** schema-validator-dev, route-enforcer-dev, and prompt-engineer all start immediately.
- **Phase B (after schema-validator-dev):** quality-gate-dev starts once `get_schema_models()` API is available.
- **Phase C (after all others):** pipeline-integrator wires everything into cli.py and config.py.

---

## Violation Code Reference

| Code | Category | Severity | Description |
|------|----------|----------|-------------|
| ROUTE-001 | 1 | CRITICAL | Frontend calls nested route, backend only has top-level |
| ROUTE-002 | 1 | CRITICAL | Frontend calls endpoint that does not exist |
| ROUTE-003 | 1 | HIGH | Singular/plural path segment mismatch |
| ROUTE-004 | 1 | HIGH | Frontend uses different action path than backend |
| ENUM-001 | 2 | error | Frontend enum value not in schema |
| ENUM-002 | 2 | error | Backend role/enum value not in schema or seed |
| ENUM-003 | 2 | warning | Magic string pseudo-enum without DB constraint |
| ROLE-001 | 2 | CRITICAL | Role in @Roles() not found in seed data |
| ROLE-002 | 2 | CRITICAL | Frontend role/status string not in Enum Registry |
| ROLE-003 | 2 | HIGH | Enum field uses raw strings instead of shared constant |
| AUTH-001 | 3 | CRITICAL | Frontend expects field backend doesn't return |
| AUTH-002 | 3 | CRITICAL | Backend requires param frontend doesn't send |
| AUTH-003 | 3 | CRITICAL | Frontend calls guarded endpoint without token |
| AUTH-004 | 3 | CRITICAL | MFA flow state machine mismatch |
| SCHEMA-001 | 4 | error | Missing onDelete cascade on parent-child relation |
| SCHEMA-002 | 4 | error | FK field (_id) without @relation annotation |
| SCHEMA-003 | 4 | error | Invalid default on UUID FK field |
| SCHEMA-004 | 4 | warning | Missing index on FK field |
| SCHEMA-005 | 4 | warning | Soft-delete without global middleware |
| SCHEMA-006 | 4 | warning | Magic string pseudo-enum without constraint |
| SCHEMA-007 | 4 | warning | Inconsistent decimal precision |
| SCHEMA-008 | 4 | error | Nullable tenant_id (isolation gap) |
| SCHEMA-009 | 4 | warning | Self-referential field without @relation |
| SCHEMA-010 | 4 | warning | Missing unique constraint per tenant |
| SHAPE-001 | 5 | warning | Field name fallback pattern in frontend |
| SHAPE-002 | 5 | warning | Defensive array extraction pattern |
| SHAPE-003 | 5 | error | Frontend expects field backend doesn't return |
| SOFTDEL-001 | 6 | error | Query on soft-deletable model missing deleted_at filter |
| SOFTDEL-002 | 6 | error | Query references non-existent field |
| QUERY-001 | 6 | warning | Prisma client cast to `any` |
| INFRA-001 | 7 | error | Port mismatch between config sources |
| INFRA-002 | 7 | error | Conflicting config files |
| INFRA-003 | 7 | error | tsconfig includes files with missing dependencies |
| INFRA-004 | 7 | warning | Docker service missing restart policy |
| INFRA-005 | 7 | warning | Docker service missing health check |

---

## Findings Coverage Matrix

Every finding from the audit report is prevented by at least one upgrade:

| Finding | Severity | Prevented By |
|---------|----------|-------------|
| C-01 | CRITICAL | ENUM-001, ENUM-002, ROLE-001, prompt Section 11 |
| C-02 | CRITICAL | ROUTE-002, prompt Section 11 route table |
| C-03 | CRITICAL | ROUTE-002, prompt Section 11 route table |
| C-04 | CRITICAL | ROUTE-001, route pattern enforcer |
| C-05 | CRITICAL | SCHEMA-003 |
| C-06 | CRITICAL | SOFTDEL-002, SCHEMA-001 |
| C-07 | CRITICAL | SOFTDEL-002 |
| C-08 | CRITICAL | AUTH-001..004, prompt auth flow contract |
| C-09 | CRITICAL | ROUTE-001, route pattern enforcer |
| C-10 | CRITICAL | ROUTE-001, route pattern enforcer |
| C-11 | CRITICAL | ROUTE-002 |
| C-12 | CRITICAL | ROUTE-002 |
| H-01 | HIGH | SCHEMA-001 |
| H-02 | HIGH | SCHEMA-002 |
| H-03 | HIGH | SOFTDEL-001 |
| H-04 | HIGH | SOFTDEL-002, prompt query correctness |
| H-05 | HIGH | BACK-009, prompt query correctness |
| H-06 | HIGH | SOFTDEL-002 |
| H-07 | HIGH | SOFTDEL-002 |
| H-08 | HIGH | BACK-001 (existing) |
| H-09 | HIGH | ENUM-001, ROLE-002 |
| H-10 | HIGH | Existing integration_verifier query param check |
| H-11 | HIGH | SHAPE-001, FRONT-022, prompt Section 10 |
| H-12 | HIGH | SHAPE-002, FRONT-023, BACK-010, prompt Section 11 |
| H-13 | HIGH | SHAPE-003 |
| H-14 | HIGH | ENUM-003, ROLE-003, prompt enum registry |
| H-15 | HIGH | FRONT-014 (existing) |
| H-16 | HIGH | ROUTE-002 |
| H-17 | HIGH | ROUTE-004 |
| H-18 | HIGH | INFRA-001 |
| H-19 | HIGH | INFRA-002, INFRA-003 |
| H-20 | HIGH | Prompt build hygiene (migration freshness) |
| H-21 | HIGH | SCHEMA-006, ENUM-003 |
| H-22 | HIGH | Prompt build hygiene (test suite health) |
| M-01 | MEDIUM | SCHEMA-004 |
| M-02 | MEDIUM | Prompt query correctness |
| M-03 | MEDIUM | SOFTDEL-001 |
| M-04 | MEDIUM | SOFTDEL-001 |
| M-05 | MEDIUM | INFRA-001 (CORS port check) |
| M-06 | MEDIUM | SCHEMA-008, SCHEMA-010 |
| M-07 | MEDIUM | Prompt frontend standards (caching) |
| M-08 | MEDIUM | Prompt backend standards (transactions) |
| M-09 | MEDIUM | SHAPE-003, prompt response shape |
| M-10 | MEDIUM | Out of scope (runtime feature, not build-time) |
| M-11 | MEDIUM | INFRA-004, INFRA-005 |
| M-12 | MEDIUM | SCHEMA-009 |
| M-13 | MEDIUM | SCHEMA-005 |
| M-14 | MEDIUM | QUERY-001, BACK-008 |
| M-15 | MEDIUM | ROUTE-003, existing integration_verifier |
| M-16 | MEDIUM | Out of scope (business decision, not code defect) |
| M-17 | MEDIUM | FRONT-024, prompt route convention |
| L-01 | LOW | SCHEMA-007 |
| L-02 | LOW | SCHEMA-007 |
| L-03 | LOW | Prompt query correctness |
| L-04 | LOW | Out of scope (runtime security enhancement) |
| L-05 | LOW | Prompt backend standards |
| L-06 | LOW | Prompt auth flow contract |
| L-07 | LOW | Prompt frontend standards |
| L-08 | LOW | Prompt frontend standards |
| L-09 | LOW | Prompt frontend standards |
| L-10 | LOW | BACK-005 (existing) |
| L-11 | LOW | Prompt frontend standards |

**Coverage:** 59/62 findings have automated prevention. 3 findings (M-10, M-16, L-04) are runtime features or business decisions outside the builder's scope.

---

## Additional Fixes from Root Cause Analysis

These items were identified in ROOT_CAUSE_MAP.md Priority 2 and fill gaps not covered by the original 7-category plan.

### Additional Fix 1: Add `prisma validate` and `prisma migrate status` to verification.py

**File:** `src/agent_team_v15/verification.py`
**Location:** New Phase 1.25, after contract check (Phase 1) and before build check (Phase 1.5).
**Logic:** Run `npx prisma validate` and `npx prisma migrate status` as subprocess calls. Parse output for errors.
**Prevents:** C-05, C-06, C-07, H-20
**Assigned to:** pipeline-integrator (additive to verification pipeline)

### Additional Fix 2: Add silent-catch detector to quality_checks.py

**File:** `src/agent_team_v15/quality_checks.py`
**Location:** Add as a new check within `run_spot_checks()`, pattern `FRONT-025`.
**Regex:** `catch\s*\([^)]*\)\s*\{[^}]*console\.(error|log)\s*\([^}]*\}` where the catch block ONLY contains console logging and no state-setting (no `setError`, `setState`, `toast`, `notification`).
**Prevents:** H-15 (silent error handling on 39+ pages)
**Assigned to:** quality-gate-dev (add to existing spot checks)

### Additional Fix 3: Add post-pagination filter detector to quality_checks.py

**File:** `src/agent_team_v15/quality_checks.py`
**Location:** Add as `BACK-011` in spot checks.
**Regex:** Detect `.filter(` or `.map(` calls immediately after a variable assigned from a Prisma query that used `skip`/`take` parameters.
**Prevents:** H-04
**Assigned to:** quality-gate-dev

### Additional Fix 4: Promote soft-delete from Tier 3 to Tier 2 in tiered mandate

**File:** `src/agent_team_v15/agents.py`
**Location:** In the depth-based tiered mandate section (if it exists as conditional prompt text), move soft-delete rules from Tier 3 ("IF CONTEXT BUDGET PERMITS") to Tier 2 (always included for standard+ builds).
**Prevents:** H-03, M-03, M-04, M-13 (4 findings)
**Assigned to:** prompt-engineer

### Additional Fix 5: Add localStorage token scanner to quality_checks.py

**File:** `src/agent_team_v15/quality_checks.py`
**Location:** Add as `FRONT-026` in spot checks.
**Regex:** `localStorage\.(setItem|getItem)\s*\(\s*['"](?:token|accessToken|refreshToken|jwt|auth)['"]`
**Prevents:** L-06
**Assigned to:** quality-gate-dev

### Additional Fix 6: Add pre-coding integration gate to cli.py

**File:** `src/agent_team_v15/cli.py`
**Location:** Injection point D (cli.py:5800) — before orchestration for frontend milestones.
**Logic:** Before the frontend coding fleet starts, verify every SVC-xxx entry in REQUIREMENTS.md has a matching backend endpoint in API_CONTRACTS.json. If mismatches found, inject them as mandatory TODO items into the coding fleet's context.
**Prevents:** All ROUTE findings (preventive, catches issues before code is written)
**Assigned to:** pipeline-integrator

---

## Testing Strategy

All new code must include tests. Target: 75-110 new tests across both modules.

| Module | Test File | Test Count | What's Tested |
|--------|-----------|------------|---------------|
| schema_validator.py | test_schema_validator.py | 25-35 | Each SCHEMA-xxx rule with passing/failing schema snippets |
| quality_validators.py | test_quality_validators.py | 50-75 | Each validator class, each violation type, edge cases |

Existing test suite (7,491 tests) MUST continue to pass. Run full suite after every change to cli.py, config.py, and agents.py.
