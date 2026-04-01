# Root Cause Map: ArkanPM Audit Findings → Builder Gaps

**Generated:** 2026-04-01
**Source:** ArkanPM `CODEBASE_AUDIT_REPORT.md` (62 findings)
**Target:** agent-team-v15 builder system upgrade plan

---

## Table of Contents

1. [Root Cause Categories](#1-root-cause-categories)
2. [Finding-to-Category Mapping](#2-finding-to-category-mapping)
3. [Builder Gap Analysis per Finding](#3-builder-gap-analysis-per-finding)
4. [Builder Gap Score (Module Contribution)](#4-builder-gap-score-module-contribution)
5. [Summary of Required Builder Fixes](#5-summary-of-required-builder-fixes)

---

## 1. Root Cause Categories

| # | Category | Code | Description | Finding Count |
|---|----------|------|-------------|---------------|
| 1 | **Route Mismatch** | ROUTE | Frontend calls an endpoint path that does not match any backend controller route — missing endpoints, nested-vs-top-level disagreements, pluralization errors, path segment differences | 18 |
| 2 | **Enum / Magic-String Inconsistency** | ENUM | Frontend and backend use different string values for the same conceptual constant — role names, status values, query parameter names, field names used as identifiers | 5 |
| 3 | **Auth Flow Divergence** | AUTH | Frontend and backend implement incompatible authentication/authorization contracts — MFA flow mismatch, missing profile fields, guard hierarchy bugs, security config gaps | 6 |
| 4 | **Schema Integrity** | SCHEMA | Prisma/DB schema defects — missing relations, missing cascades, invalid defaults, missing indexes, type inconsistencies, missing enum enforcement, tenant isolation gaps | 12 |
| 5 | **Serialization / Response Shape** | SERIAL | Disagreement on response structure between frontend and backend — camelCase/snake_case field naming, array-vs-{data,meta} wrapping, nested object shapes, pagination metadata location | 5 |
| 6 | **Soft-Delete / Query Correctness** | QUERY | Backend service queries that produce wrong results — missing `deleted_at: null` filters, post-pagination filtering, invalid field references, off-by-one date comparisons, type-unsafe casts | 10 |
| 7 | **Build / Infrastructure** | BUILD | Non-code issues that prevent the app from running — broken compilation, unapplied migrations, failing tests, Docker config, CORS/port mismatches, frontend code quality gaps | 6 |

---

## 2. Finding-to-Category Mapping

### CRITICAL (12 findings)

| ID | Finding | Category | Builder Module(s) Responsible |
|----|---------|----------|-------------------------------|
| C-01 | Role name split: `technician` vs `maintenance_tech` | ENUM | agents.py (Section 11 — Enum Registry), integration_verifier.py |
| C-02 | Missing `PATCH /work-orders/:id/checklist/:itemId` | ROUTE | agents.py (Section 11 — SVC-xxx wiring), api_contract_extractor.py |
| C-03 | Missing `GET /buildings/:id/assets` | ROUTE | agents.py (Section 11 — SVC-xxx wiring), api_contract_extractor.py |
| C-04 | Property contacts route mismatch (nested vs top-level) | ROUTE | agents.py (Section 11 — SVC-xxx wiring), integration_verifier.py |
| C-05 | `warranty_id @default("")` on UUID FK | SCHEMA | agents.py (Section 9 — DB standards), quality_checks.py |
| C-06 | Warehouse service invalid `deleted_at` filter on StockLevel | QUERY | agents.py (Section 9 — soft delete), quality_checks.py |
| C-07 | Warranty claim service wrong field reference in include | QUERY | integration_verifier.py (Prisma include analysis) |
| C-08 | MFA/login flow incompatible between FE and BE | AUTH | agents.py (Section 11 — Integration Protocol), api_contract_extractor.py |
| C-09 | Building amenity/system write routes — nested vs top-level | ROUTE | agents.py (Section 11 — SVC-xxx wiring), integration_verifier.py |
| C-10 | Floor/zone CRUD — nested routes don't exist | ROUTE | agents.py (Section 11 — SVC-xxx wiring), integration_verifier.py |
| C-11 | Unit detail page — 3 subresource routes don't exist | ROUTE | agents.py (Section 11 — SVC-xxx wiring), integration_verifier.py |
| C-12 | Work request attachment upload route doesn't exist | ROUTE | agents.py (Section 11 — SVC-xxx wiring), integration_verifier.py |

### HIGH (22 findings)

| ID | Finding | Category | Builder Module(s) Responsible |
|----|---------|----------|-------------------------------|
| H-01 | 40+ relations missing `onDelete: Cascade` | SCHEMA | agents.py (Section 9 — DB standards), code_quality_standards.py (DB-008) |
| H-02 | 15+ FK fields missing `@relation` definitions | SCHEMA | agents.py (Section 9 — DB standards), code_quality_standards.py (DB-006/008) |
| H-03 | 7 services missing `deleted_at: null` filter | QUERY | agents.py (Section 9 — soft delete mandate), quality_checks.py |
| H-04 | Stock level post-pagination filtering breaks totals | QUERY | agents.py (Section 9 — CRUD standards), code_quality_standards.py |
| H-05 | Work order service invalid UUID fallback `'no-match'` | QUERY | agents.py (Section 9 — error handling), code_quality_standards.py (BACK-018) |
| H-06 | Inspection report missing items relation in include | QUERY | integration_verifier.py (Prisma include analysis) |
| H-07 | Vendor service category filter references non-existent field | QUERY | agents.py (Section 9), quality_checks.py |
| H-08 | Asset service raw SQL injection risk | QUERY | code_quality_standards.py (BACK-001), quality_checks.py (_check_sql_concat) |
| H-09 | Frontend `GET /users?role=technician` returns empty | ENUM | agents.py (Section 11 — Enum Registry), integration_verifier.py |
| H-10 | Audit log date filter params wrong (`dateFrom`/`dateTo` vs `from`/`to`) | ROUTE | agents.py (Section 10 — Query Param Normalization), integration_verifier.py |
| H-11 | 50+ field name fallbacks indicating interceptor inconsistency | SERIAL | agents.py (Section 10 — Serialization Mandate), integration_verifier.py |
| H-12 | Array vs `{data, meta}` response inconsistency | SERIAL | agents.py (Section 11 — Response Wrapping Convention), integration_verifier.py |
| H-13 | Missing `avatarUrl` in auth profile response | AUTH | agents.py (Section 11 — SVC-xxx wiring), api_contract_extractor.py |
| H-14 | Hardcoded enum values without shared constants (10+ types) | ENUM | agents.py (Section 11 — Enum Registry), code_quality_standards.py |
| H-15 | Silent error handling on all 39+ pages | BUILD | code_quality_standards.py (FRONT-014), quality_checks.py |
| H-16 | Work request status-history route doesn't exist | ROUTE | agents.py (Section 11 — SVC-xxx wiring), integration_verifier.py |
| H-17 | Integration test route mismatch (`/test` vs `/test-connection`) | ROUTE | agents.py (Section 11 — SVC-xxx wiring), integration_verifier.py |
| H-18 | FRONTEND_URL port mismatch (4201 vs 4200) | BUILD | agents.py (Section 9 — infrastructure), quality_checks.py (DEPLOY scans) |
| H-19 | Web build broken (Playwright + next.config conflict) | BUILD | verification.py (build phase), quality_checks.py |
| H-20 | Prisma migrations not applied (7-8 unapplied) | BUILD | agents.py (Section 9 — DB/migration standards), verification.py |
| H-21 | 94+ magic string pseudo-enums without DB enforcement | SCHEMA | agents.py (Section 11 — Enum Registry), code_quality_standards.py (DB-001) |
| H-22 | API unit test suite failing (14 suites, 78 tests) | BUILD | verification.py (test phase), agents.py (Section 3d — Progressive Verification) |

### MEDIUM (17 findings)

| ID | Finding | Category | Builder Module(s) Responsible |
|----|---------|----------|-------------------------------|
| M-01 | 8+ missing database indexes | SCHEMA | agents.py (Section 9 — DB standards), code_quality_standards.py (BACK-010) |
| M-02 | Unit service lease date boundary off-by-one | QUERY | agents.py (Section 5 — Adversarial Review) |
| M-03 | Lease service owner lookup missing soft-delete filter | QUERY | agents.py (Section 9 — soft delete), quality_checks.py |
| M-04 | Move-in checklist lease lookup missing soft-delete filter | QUERY | agents.py (Section 9 — soft delete), quality_checks.py |
| M-05 | CORS defaults to localhost:4200 | AUTH | agents.py (Section 9 — Security Requirements), quality_checks.py |
| M-06 | Tenant isolation gaps (nullable tenant_id, missing unique) | SCHEMA | agents.py (Section 9 — DB standards, tenant isolation) |
| M-07 | Repeated `/users` fetch calls without caching | SERIAL | code_quality_standards.py (FRONT-009), agents.py |
| M-08 | Race condition in resident creation flow | QUERY | code_quality_standards.py (BACK-016), agents.py (Section 9) |
| M-09 | Notification status field assumption | SERIAL | agents.py (Section 11 — Enum Registry, response shape) |
| M-10 | No real-time notification updates | BUILD | agents.py (Section 9 — infrastructure) |
| M-11 | Docker missing restart policies and health checks | BUILD | agents.py (Section 9 — Dockerfile Standards), quality_checks.py (DEPLOY) |
| M-12 | Self-referential lease renewal missing @relation | SCHEMA | code_quality_standards.py (DB-006/007), agents.py (Section 9) |
| M-13 | Soft delete without global Prisma middleware | SCHEMA | agents.py (Section 9 — soft delete mandate) |
| M-14 | `(this.prisma as any)` type safety bypasses in 6+ services | QUERY | code_quality_standards.py (FRONT-007/BACK equivalent), quality_checks.py |
| M-15 | Document upload pluralization bug (`property` -> `/propertys`) | ROUTE | integration_verifier.py (path normalization), agents.py (Section 11) |
| M-16 | Hardcoded regional defaults (USD, sqft) for UAE app | SCHEMA | agents.py (Section 1 — Requirements Doc), milestone_manager.py |
| M-17 | Dynamic action URL construction fragile | ROUTE | integration_verifier.py, code_quality_standards.py |

### LOW (11 findings)

| ID | Finding | Category | Builder Module(s) Responsible |
|----|---------|----------|-------------------------------|
| L-01 | Decimal precision inconsistency across financial fields | SCHEMA | agents.py (Section 9 — DB standards) |
| L-02 | `LeaseDocument.file_size` BigInt vs Int inconsistency | SCHEMA | agents.py (Section 9 — DB standards) |
| L-03 | Resident service redundant status + soft delete | QUERY | agents.py (Section 9 — soft delete mandate) |
| L-04 | JWT doesn't validate roles against database | AUTH | agents.py (Section 9 — Security Requirements) |
| L-05 | `forbidNonWhitelisted: false` in validation pipe | AUTH | agents.py (Section 9 — Security Requirements) |
| L-06 | Token storage in localStorage (XSS risk) | AUTH | agents.py (Section 9 — Security), code_quality_standards.py |
| L-07 | Unsafe date parsing without validation | SERIAL | code_quality_standards.py (FRONT standards) |
| L-08 | String concatenation display names without trim | ENUM | code_quality_standards.py (FRONT standards) |
| L-09 | UUID length magic number check | ENUM | code_quality_standards.py (FRONT standards) |
| L-10 | Hardcoded `limit: 100` without server pagination | SERIAL | code_quality_standards.py (BACK-005), agents.py (Section 9) |
| L-11 | Booking notes field duplication | ROUTE | agents.py (Section 5 — Adversarial Review) |

---

## 3. Builder Gap Analysis per Finding

### Category 1: ROUTE — Route Mismatch (18 findings)

**Findings:** C-02, C-03, C-04, C-09, C-10, C-11, C-12, H-10, H-16, H-17, M-15, M-17, L-11, plus the 5 sub-items in C-04/C-09/C-10 counted as part of those findings.

**What the builder HAS:**
- `agents.py` Section 11 mandates a `Service-to-API Wiring Map` (SVC-xxx entries) in REQUIREMENTS.md
- `agents.py` Section 11 tells frontend code-writers to "READ the API contracts before writing any API call" and "use the EXACT endpoint paths from the contracts"
- `agents.py` Section 11 says "Frontend Reviewer Rules: verify it matches API_CONTRACTS.json"
- `integration_verifier.py` post-build static analysis diffs frontend API calls against backend endpoint definitions
- `api_contract_extractor.py` extracts contracts from actual backend code into API_CONTRACTS.json

**WHY it failed — the specific gaps:**

1. **SVC-xxx Wiring Map is architect-generated, not machine-verified at plan time.** The architect agent writes SVC-xxx entries based on the PRD, but there is no automated check that every SVC-xxx entry actually has both a backend endpoint AND a frontend call. The architect can miss endpoints entirely (C-02, C-03, C-11, C-12, H-16) or disagree on nesting convention (C-04, C-09, C-10).

2. **Nested-vs-top-level route convention is never explicitly decided.** The builder has no rule forcing the architect to declare a routing convention (e.g., "all write operations go through top-level controllers; nested routes are read-only shortcuts"). Without this decision, the backend agent uses top-level controllers (NestJS default) while the frontend agent assumes RESTful nesting. This is the single biggest category, causing C-04, C-09, C-10, and contributing to 10+ of the 18 route findings.

3. **Integration verifier runs in "warn" mode by default.** `config.py` sets `verification_mode: str = "warn"`. Even when the verifier detects HIGH-severity missing endpoints, it logs them but does not block the milestone. The default should be "block" for frontend/fullstack milestones.

4. **Integration verifier runs only AFTER the milestone completes.** It is a post-hoc check. By the time it fires, the frontend code-writer has already finished. There is no mid-milestone gate that says "pause — these 8 frontend API calls have no backend match."

5. **API_CONTRACTS.json extraction happens between milestones, not enforced as a compile-time contract.** If the frontend milestone starts before contracts are fully extracted, or if the code-writer ignores the contracts, there is no blocking check.

**Specific fixes needed:**
- Add a **Route Convention Decision** to the architect prompt — force explicit declaration of nested vs top-level for every resource
- Add a **pre-coding integration gate** — before the frontend coding fleet starts, verify every SVC-xxx has a matching backend endpoint in API_CONTRACTS.json
- Change default `verification_mode` from `"warn"` to `"block"` for frontend milestones
- Add a **nested route validator** to `integration_verifier.py` that detects when frontend uses `/parent/:id/child` but backend only has top-level `/child`

---

### Category 2: ENUM — Enum / Magic-String Inconsistency (5 findings)

**Findings:** C-01, H-09, H-14, L-08, L-09

**What the builder HAS:**
- `agents.py` Section 11 mandates an **Enum Value Registry** in the Architecture Decision
- `agents.py` defines ENUM-001/002/003 violations as HARD FAILURE
- `code_quality_standards.py` has FRONT-020 (DTO/Enum Mismatch) and DB Enum/Status Registry rule
- `code_quality_standards.py` has DB-001 (Enum Type Mismatch)

**WHY it failed:**

1. **Enum Registry is an LLM-generated document, with no automated enforcement.** The builder tells the architect to create an Enum Registry, but there is no code in `quality_checks.py` or `integration_verifier.py` that actually parses the Prisma schema's pseudo-enums and cross-references them against frontend string constants. The entire enforcement relies on the LLM reviewer agent catching the mismatch — which it did not for the `technician` vs `maintenance_tech` split.

2. **Seed data is not cross-referenced against guards and frontend queries.** C-01 is a case where the DB seeds `maintenance_tech` but frontend queries for `role=technician`. The builder has no automated scan that compares seed data values against controller guard decorators and frontend filter parameters.

3. **No shared constants enforcement.** The builder tells code-writers to "read the Enum Registry" but has no rule requiring a shared constants file (e.g., `src/shared/constants/statuses.ts`) that both frontend and backend import. Each page hardcodes its own enum values (H-14).

**Specific fixes needed:**
- Add an **automated enum cross-reference scan** to `quality_checks.py` — parse Prisma schema `@default()` comment-enums, compare against frontend hardcoded strings, and compare against seed data values
- Add a **shared constants mandate** to Section 11 — require a single-source-of-truth constants file for every entity with a status/enum field
- Add a **seed-data-vs-guard scan** to `integration_verifier.py` — extract `@Roles()` decorator values and compare against seeded role codes

---

### Category 3: AUTH — Auth Flow Divergence (6 findings)

**Findings:** C-08, H-13, M-05, L-04, L-05, L-06

**What the builder HAS:**
- `agents.py` Section 9 has Security Requirements (rate limiting, input validation, CORS)
- `agents.py` Section 11 SVC-xxx wiring includes auth endpoints
- `code_quality_standards.py` has BACK-006 (IDOR), BACK-007 (Hardcoded Secrets), BACK-009 (Rate Limiting)

**WHY it failed:**

1. **Auth flow is treated as just another set of endpoints, not a special protocol.** C-08 is a case where the frontend implements a challenge-token MFA flow while the backend implements inline-code MFA. The builder's SVC-xxx wiring only checks "does the endpoint exist?" — not "do both sides agree on the multi-step protocol?" Auth flows are multi-step state machines with intermediate tokens, and the builder has no concept of verifying protocol-level compatibility.

2. **No auth profile shape contract.** H-13 is simply the backend not returning `avatarUrl` in the profile response. The builder's API contract extraction captures field names from DTOs, but the auth profile is often a manually-constructed object (not a DTO), so it gets missed.

3. **Security config is prescriptive but not verified.** The builder says "CORS: Read allowed origins from CORS_ORIGINS environment variable" but has no scan that checks `.env` files and `main.ts` CORS config for consistency (M-05, H-18 port mismatch). Similarly, it says "never use localStorage for tokens" (L-06) but `quality_checks.py` has no pattern matching for `localStorage.setItem('token'`.

**Specific fixes needed:**
- Add an **Auth Protocol Verification** section to Section 11 — require the architect to document the full auth flow as a sequence diagram (login -> MFA challenge -> token exchange -> refresh), and the reviewer to verify both sides implement the same sequence
- Add a **security config scanner** to `quality_checks.py` — check `.env` FRONTEND_URL port matches the frontend dev server port, check CORS config references env vars, check token storage strategy
- Add auth profile response to the mandatory SVC-xxx wiring entries

---

### Category 4: SCHEMA — Schema Integrity (12 findings)

**Findings:** C-05, H-01, H-02, H-21, M-01, M-06, M-12, M-13, M-16, L-01, L-02

**What the builder HAS:**
- `agents.py` Section 9 mandates "Foreign key constraints with appropriate ON DELETE behavior" and "Indexes on: tenant_id, created_at, any FK column"
- `agents.py` Section 9 mandates "Soft delete with `deleted_at` timestamp" and "List endpoints exclude soft-deleted by default"
- `code_quality_standards.py` has DB-006 (FK Without Navigation Property), DB-007 (Navigation Property Without Inverse), DB-008 (FK With No Relationship Configuration)
- `code_quality_standards.py` has DB-004 (Missing Default Value)

**WHY it failed:**

1. **Schema standards are prose mandates with ZERO automated enforcement.** The builder tells the code-writer "add onDelete: Cascade to parent-child relations" and "add indexes on FK columns." But `quality_checks.py` has NO scan function for Prisma schema files. There is no `_check_prisma_relations()`, no `_check_prisma_cascades()`, no `_check_prisma_indexes()`. The enforcement is entirely via LLM review — and the reviewer missed 40+ missing cascades and 15+ missing relations.

2. **Soft-delete middleware is mandated but not verified.** The builder says "soft delete with `deleted_at` timestamp" but has no check that a global Prisma middleware actually exists that auto-filters `deleted_at: null`. Without middleware, every service must add the filter manually (M-13), and 7+ services forgot (H-03).

3. **No Prisma schema linter integration.** The builder runs lint, type-check, and tests in `verification.py`, but there is no Prisma-specific schema validation phase that would catch `@default("")` on a UUID FK (C-05), missing `@relation` annotations (H-02), or inconsistent decimal precision (L-01).

4. **Tenant isolation is mandated but not structurally verified.** The builder says "tenant_id column on every entity" but has no scan that checks every model in the Prisma schema actually has `tenant_id` as non-nullable with a unique constraint where needed (M-06).

**Specific fixes needed:**
- Add a **Prisma schema scanner** to `quality_checks.py` with checks for:
  - Every FK field (`_id` suffix) has a `@relation` annotation (catches H-02)
  - Every parent-child relation has `onDelete: Cascade` or explicit `onDelete:` directive (catches H-01)
  - Every model with `deleted_at` field is covered by global middleware (catches M-13)
  - No `@default("")` on fields ending in `_id` (catches C-05)
  - Every model has `tenant_id` as non-nullable (catches M-06)
  - Consistent decimal precision for financial fields (catches L-01)
  - Indexes exist on all FK columns and filter columns (catches M-01)
- Add a **soft-delete middleware verifier** — scan for global Prisma middleware that filters `deleted_at`

---

### Category 5: SERIAL — Serialization / Response Shape (5 findings)

**Findings:** H-11, H-12, M-07, M-09, L-07, L-10

**What the builder HAS:**
- `agents.py` Section 10 (Serialization Convention Mandate) — detailed instructions for CamelCaseInterceptor, QueryNormalizerMiddleware, RequestBody normalization
- `agents.py` Section 11 (Response Wrapping Convention) — explicit `{data, meta}` for lists, bare object for single resources
- `integration_verifier.py` has `detect_field_naming_mismatches()` and `detect_response_shape_mismatches()` functions
- Reviewer fleet instructions say "verify ALL THREE [serialization layers] exist"

**WHY it failed:**

1. **Serialization interceptor was created but is incomplete/buggy.** The audit found the `CamelCaseResponseInterceptor` exists and is registered globally — but 50+ frontend field-name fallbacks prove it does not transform all responses correctly. The builder mandates creating the interceptor but has no test that verifies it actually transforms a sample response. The `integration_verifier.py` detects the fallback patterns after the fact but only as a WARNING.

2. **Response wrapping convention has no structural enforcement.** The builder says "all list endpoints MUST return `{data, meta}`" but there is no scan in `quality_checks.py` that parses NestJS controller return types or service return statements to verify they match the convention. The 10+ pages with `Array.isArray(res) ? res : res.data` (H-12) prove the convention was not followed consistently.

3. **Field-name mismatch detection is post-hoc and non-blocking.** `integration_verifier.py` detects camelCase/snake_case mismatches after the milestone completes, but the default mode is "warn." The 50+ fallback patterns (H-11) were likely detected but not acted on.

**Specific fixes needed:**
- Add a **serialization verification test** mandate — the foundation milestone MUST include a test that sends a known snake_case response through the interceptor and asserts it comes out as camelCase
- Add a **response shape scanner** to `quality_checks.py` — detect NestJS service methods that return bare arrays (not wrapped in `{data, meta}`) for `findAll`/`findMany` methods
- Change field-name mismatch detection to BLOCKING when count exceeds threshold (e.g., >5 mismatches = block)

---

### Category 6: QUERY — Soft-Delete / Query Correctness (10 findings)

**Findings:** C-06, C-07, H-03, H-04, H-05, H-06, H-07, H-08, M-02, M-03, M-04, M-08, M-14, L-03

**What the builder HAS:**
- `agents.py` Section 9 mandates soft-delete filtering, parameterized queries, proper error handling
- `agents.py` Section 3a mandates no stub handlers
- `code_quality_standards.py` has BACK-001 (SQL Injection), BACK-002 (N+1), BACK-016 (Non-transactional writes), BACK-018 (Unvalidated route params)
- `quality_checks.py` has `_check_sql_concat()`, `_check_n_plus_1()`, `_check_transaction_safety()`, `_check_param_validation()`

**WHY it failed:**

1. **Soft-delete is mandated but enforcement is scattered.** The builder mentions soft-delete in THREE places (Section 9 DB standards, Tier 3 infrastructure, all-out mandates) but soft-delete is in Tier 3 ("IF CONTEXT BUDGET PERMITS") in the tiered mandate. This means for non-exhaustive depth builds, soft-delete may be deprioritized. Meanwhile, 92 models have `deleted_at` fields, so the schema creates the expectation — but 7+ services forgot the filter. There is NO automated scan in `quality_checks.py` that detects `prisma.xxx.findMany()` calls missing `where: { deleted_at: null }`.

2. **Prisma query correctness is not statically analyzed.** C-06 (filtering `deleted_at` on a model that lacks the field) and C-07 (selecting a plain field as if it were a relation) are Prisma-specific bugs that would be caught by `prisma validate` or TypeScript strict mode. But `verification.py` does not run `prisma validate` as a phase, and the type-check may be bypassed by `(this.prisma as any)` casts (M-14, found in 6+ services).

3. **Post-pagination filtering is not detected.** H-04 applies filters AFTER Prisma's `skip`/`take`. There is no check in `quality_checks.py` for this anti-pattern (`.filter()` after `.findMany()` with pagination parameters).

4. **`(this.prisma as any)` casts suppress all type checking.** The builder mandates TypeScript strict mode, but 6+ services bypass it with `as any` casts. The existing `_check_ts_any()` in `quality_checks.py` detects `any` usage but these casts appear in backend service files which may not be flagged as critical.

**Specific fixes needed:**
- Promote soft-delete from Tier 3 to Tier 2 (or Tier 1 when model has `deleted_at` field) in the tiered mandate
- Add a **soft-delete query scanner** to `quality_checks.py` — for every `findMany`/`findFirst` call on a model known to have `deleted_at`, verify the `where` clause includes `deleted_at: null`
- Add a **Prisma cast detector** — flag `(this.prisma as any)` as a HIGH-severity violation since it bypasses all schema type safety
- Add a **post-pagination filter detector** — flag `.filter()` / `.map()` calls immediately after Prisma query results that used `skip`/`take`
- Add `prisma validate` to `verification.py` as a schema validation phase

---

### Category 7: BUILD — Build / Infrastructure (6 findings)

**Findings:** H-15, H-18, H-19, H-20, H-22, M-10, M-11

**What the builder HAS:**
- `verification.py` runs build, lint, type-check, and test phases
- `agents.py` Section 9 has Dockerfile Standards (restart, healthcheck, non-root)
- `quality_checks.py` has `run_deployment_scan()` for Docker config issues
- `agents.py` Section 9 mandates meaningful test assertions

**WHY it failed:**

1. **Build verification may not catch tsconfig scope issues.** H-19 (Playwright config pulled into compilation) is a tsconfig `include` pattern bug. The builder runs `tsc` or `next build` but the error message may be about a missing `@playwright/test` package — which the debugger might try to fix by installing the package rather than excluding the file. The builder has no tsconfig-specific scan.

2. **Migration status is not verified.** H-20 (7-8 unapplied migrations) means `prisma migrate status` would report problems, but `verification.py` does not run `prisma migrate status` as a verification phase.

3. **Test failures are logged but may not block completion.** H-22 (78 failing unit tests) suggests the test phase either did not run or did not block. The builder's verification pipeline marks tests as a phase, but if `run_tests: bool = True` is the default and tests are broken, the milestone should fail — unless the test runner was not configured properly for the project.

4. **Silent error handling (H-15) is a code quality issue.** The builder has FRONT-014 (Missing Loading/Error States) but `quality_checks.py` does not have a specific pattern check for `catch (err) { console.error(...) }` without user-facing error display.

5. **Docker and infrastructure checks exist but are advisory.** The builder's `run_deployment_scan()` is non-blocking ("all produce warnings"). Docker missing restart policies (M-11) would be detected but not enforced.

**Specific fixes needed:**
- Add `prisma migrate status` to `verification.py` as a schema phase
- Add a **tsconfig scope validator** — verify that `e2e/` and `test/` directories with external dependencies are excluded from the main tsconfig
- Promote deployment scan from advisory to blocking for CRITICAL items (missing healthcheck, missing restart policy)
- Add a **silent catch detector** to `quality_checks.py` — flag `catch` blocks that only contain `console.error` without setting error state or showing user feedback

---

## 4. Builder Gap Score (Module Contribution)

This measures which builder module is responsible for the most findings. A finding can implicate multiple modules. The "primary responsibility" is the module that SHOULD have prevented the issue if it worked correctly.

### By Builder Module

| Builder Module | Primary Responsibility | % of 62 Findings | Key Gap |
|---------------|----------------------|-------------------|---------|
| **agents.py — Section 11 (Integration Protocol)** | C-01 thru C-04, C-08 thru C-12, H-09, H-10, H-12, H-13, H-14, H-16, H-17, M-07, M-09, M-15, L-11 | **33.9% (21/62)** | Rules exist but are LLM-enforced only; no automated verification at plan or build time |
| **agents.py — Section 9 (Cross-Service Standards)** | C-05, C-06, H-01, H-02, H-03, H-05, H-21, M-01, M-02, M-06, M-08, M-12, M-13, M-16, L-01, L-02, L-03 | **27.4% (17/62)** | DB/schema rules are comprehensive but have ZERO automated scanners in quality_checks.py |
| **integration_verifier.py** | (Same as Section 11 — co-responsible) | **29.0% (18/62)** | Runs post-hoc in "warn" mode; misses nested-vs-top-level patterns; no enum cross-ref; no auth protocol check |
| **quality_checks.py** | H-04, H-06, H-07, H-08, H-15, H-19, M-14, L-07 | **12.9% (8/62)** | Missing: Prisma schema scan, soft-delete query scan, post-pagination filter scan, silent-catch scan |
| **code_quality_standards.py** | H-14, H-15, L-06, L-07, L-08, L-09, L-10 | **11.3% (7/62)** | Standards document exists but many rules lack corresponding automated checks in quality_checks.py |
| **verification.py** | H-19, H-20, H-22, M-11 | **6.5% (4/62)** | Missing: prisma migrate status check, tsconfig scope check; deployment scan is non-blocking |
| **api_contract_extractor.py** | C-02, C-03, C-08, H-13 | **6.5% (4/62)** | Extracts endpoints correctly but does not verify auth flow protocol compatibility or response field completeness |
| **agents.py — Section 10 (Serialization Mandate)** | H-11, H-12, L-10 | **4.8% (3/62)** | Mandate is detailed but has no verification test requirement; interceptor bugs go undetected |
| **agents.py — Section 5 (Adversarial Review)** | M-02, L-11 | **3.2% (2/62)** | Review fleet instructions are thorough but LLM reviewers miss subtle logic bugs (off-by-one, field duplication) |
| **config.py** | (Default configuration) | **29.0% (18/62)** | `verification_mode: "warn"` default means integration verifier does not block on route mismatches |
| **milestone_manager.py** | M-16 | **1.6% (1/62)** | No mechanism to inject domain-specific defaults (e.g., AED currency for UAE project) |

### By Root Cause Category

| Category | Count | % of 62 | Top Builder Gap |
|----------|-------|---------|-----------------|
| ROUTE | 18 | 29.0% | No nested-vs-top-level convention; integration verifier in "warn" mode |
| SCHEMA | 12 | 19.4% | Zero automated Prisma schema scanners |
| QUERY | 10 | 16.1% | No soft-delete query scanner; no Prisma cast detector |
| AUTH | 6 | 9.7% | Auth flow treated as regular endpoints; no protocol verification |
| BUILD | 6 | 9.7% | Missing prisma migrate check; deployment scans non-blocking |
| ENUM | 5 | 8.1% | Enum registry is LLM-doc only; no automated cross-reference |
| SERIAL | 5 | 8.1% | Serialization interceptor not tested; response shape not scanned |

---

## 5. Summary of Required Builder Fixes

### Priority 1: Highest Impact (addresses 47/62 = 75.8% of findings)

| # | Fix | Target Module | Findings Addressed | Effort |
|---|-----|--------------|-------------------|--------|
| 1 | **Change integration verifier default to "block" mode** for frontend/fullstack milestones | `config.py` | 18 ROUTE findings | Config change |
| 2 | **Add Prisma schema scanner** to quality_checks.py (cascades, relations, indexes, defaults, tenant_id) | `quality_checks.py` | C-05, H-01, H-02, H-21, M-01, M-06, M-12, M-13, L-01, L-02 (10) | Medium |
| 3 | **Add soft-delete query scanner** — detect findMany/findFirst missing `deleted_at: null` on models with that field | `quality_checks.py` | C-06, H-03, M-03, M-04, L-03 (5) | Medium |
| 4 | **Add route convention decision mandate** — architect MUST declare nested vs top-level for every resource | `agents.py` Section 11 | C-04, C-09, C-10, M-15 (4) | Prompt change |
| 5 | **Add automated enum cross-reference scan** — parse Prisma schema pseudo-enums vs frontend constants vs seed data | `quality_checks.py` + `integration_verifier.py` | C-01, H-09, H-14, H-21, L-08, L-09 (6) | Medium-High |

### Priority 2: Medium Impact (addresses remaining 15/62 = 24.2%)

| # | Fix | Target Module | Findings Addressed | Effort |
|---|-----|--------------|-------------------|--------|
| 6 | **Add auth protocol verification** — require sequence diagram for auth flows, verify both sides match | `agents.py` Section 11 | C-08, H-13, L-04, L-05, L-06 (5) | Prompt change |
| 7 | **Add prisma validate and migrate status** to verification pipeline | `verification.py` | C-05, C-06, C-07, H-20 (4) | Small |
| 8 | **Add response shape scanner** — detect bare-array returns from findAll methods | `quality_checks.py` | H-12, M-09 (2) | Small |
| 9 | **Add serialization interceptor test mandate** — foundation milestone must include transform test | `agents.py` Section 10 | H-11 (1) | Prompt change |
| 10 | **Add silent-catch detector** and promote FRONT-014 to automated check | `quality_checks.py` | H-15 (1) | Small |
| 11 | **Promote deployment scan to blocking** for critical items | `config.py` + `quality_checks.py` | M-11, H-18 (2) | Config change |
| 12 | **Add Prisma `as any` cast detector** — flag type-safety bypasses as HIGH | `quality_checks.py` | M-14, C-06, C-07 (3) | Small |
| 13 | **Add pre-coding integration gate** — verify SVC-xxx endpoints exist before frontend coding starts | `cli.py` | All ROUTE findings (preventive) | Medium |
| 14 | **Add post-pagination filter detector** | `quality_checks.py` | H-04 (1) | Small |
| 15 | **Promote soft-delete from Tier 3 to Tier 2** in tiered mandate | `agents.py` | H-03, M-03, M-04, M-13 (4) | Prompt change |

---

## Appendix: Cross-Reference Matrix

| Finding ID | Category | Primary Module | Rule Exists? | Automated Check? | Why It Leaked |
|-----------|----------|---------------|-------------|-----------------|---------------|
| C-01 | ENUM | agents.py S11 | YES (Enum Registry) | NO | No scan compares seed data vs guard decorators vs frontend queries |
| C-02 | ROUTE | agents.py S11 | YES (SVC-xxx) | PARTIAL (integration_verifier, warn mode) | Verifier runs post-hoc, non-blocking |
| C-03 | ROUTE | agents.py S11 | YES (SVC-xxx) | PARTIAL (integration_verifier, warn mode) | Verifier runs post-hoc, non-blocking |
| C-04 | ROUTE | agents.py S11 | YES (SVC-xxx) | PARTIAL (integration_verifier, warn mode) | No nested-vs-top-level convention enforcement |
| C-05 | SCHEMA | agents.py S9 | YES (DB standards) | NO | No Prisma schema scanner |
| C-06 | QUERY | agents.py S9 | YES (soft delete) | NO | No query-vs-schema field existence check |
| C-07 | QUERY | integration_verifier | PARTIAL (Prisma include) | PARTIAL (verifier detects some) | Verifier warns but does not block |
| C-08 | AUTH | agents.py S11 | NO (no auth protocol rule) | NO | Auth treated as regular endpoints |
| C-09 | ROUTE | agents.py S11 | YES (SVC-xxx) | PARTIAL (integration_verifier) | No nested-vs-top-level convention |
| C-10 | ROUTE | agents.py S11 | YES (SVC-xxx) | PARTIAL (integration_verifier) | No nested-vs-top-level convention |
| C-11 | ROUTE | agents.py S11 | YES (SVC-xxx) | PARTIAL (integration_verifier) | Verifier runs post-hoc, non-blocking |
| C-12 | ROUTE | agents.py S11 | YES (SVC-xxx) | PARTIAL (integration_verifier) | Verifier runs post-hoc, non-blocking |
| H-01 | SCHEMA | agents.py S9 | YES (FK constraints) | NO | No Prisma cascade scanner |
| H-02 | SCHEMA | agents.py S9 | YES (DB standards) | NO | No Prisma relation scanner |
| H-03 | QUERY | agents.py S9 | YES (soft delete) | NO | No soft-delete query scanner |
| H-04 | QUERY | agents.py S9 | NO (not addressed) | NO | No post-pagination filter detector |
| H-05 | QUERY | agents.py S9 | YES (error handling) | NO | No invalid-fallback detector |
| H-06 | QUERY | integration_verifier | PARTIAL | PARTIAL | Verifier warns but does not block |
| H-07 | QUERY | agents.py S9 | NO (not addressed) | NO | No field-existence validator |
| H-08 | QUERY | code_quality_standards | YES (BACK-001) | PARTIAL (_check_sql_concat) | Check may miss parameterized-but-concatenated patterns |
| H-09 | ENUM | agents.py S11 | YES (Enum Registry) | NO | No seed-data-vs-query cross-reference |
| H-10 | ROUTE | agents.py S10 | YES (Query Param Norm) | PARTIAL (integration_verifier) | Verifier warns but does not block |
| H-11 | SERIAL | agents.py S10 | YES (Serialization) | PARTIAL (integration_verifier) | Interceptor not tested; fallbacks detected as WARNING |
| H-12 | SERIAL | agents.py S11 | YES (Response Wrapping) | PARTIAL (integration_verifier) | No response-shape scanner in quality_checks |
| H-13 | AUTH | agents.py S11 | YES (SVC-xxx) | PARTIAL (api_contract_extractor) | Auth profile not DTO-based; fields missed |
| H-14 | ENUM | agents.py S11 | YES (Enum Registry) | NO | No shared constants enforcement |
| H-15 | BUILD | code_quality_standards | YES (FRONT-014) | NO | No silent-catch detector in quality_checks |
| H-16 | ROUTE | agents.py S11 | YES (SVC-xxx) | PARTIAL (integration_verifier) | Verifier post-hoc, non-blocking |
| H-17 | ROUTE | agents.py S11 | YES (SVC-xxx) | PARTIAL (integration_verifier) | Verifier post-hoc, non-blocking |
| H-18 | BUILD | agents.py S9 | PARTIAL (CORS rule) | PARTIAL (DEPLOY scan) | Deployment scan non-blocking; no port consistency check |
| H-19 | BUILD | verification.py | NO (no tsconfig scan) | PARTIAL (build phase) | Build fails but root cause not diagnosed automatically |
| H-20 | BUILD | agents.py S9 | YES (migration standards) | NO | No `prisma migrate status` in verification pipeline |
| H-21 | SCHEMA | agents.py S11 | YES (Enum Registry) | NO | No automated Prisma pseudo-enum scanner |
| H-22 | BUILD | verification.py | YES (test phase) | PARTIAL (test runner) | Tests may not have run or failures not blocking |
| M-01 | SCHEMA | agents.py S9 | YES (indexes) | NO | No Prisma index scanner |
| M-02 | QUERY | agents.py S5 | YES (review) | NO | LLM reviewer missed off-by-one |
| M-03 | QUERY | agents.py S9 | YES (soft delete) | NO | No soft-delete query scanner |
| M-04 | QUERY | agents.py S9 | YES (soft delete) | NO | No soft-delete query scanner |
| M-05 | AUTH | agents.py S9 | YES (CORS rule) | NO | No env-vs-config consistency check |
| M-06 | SCHEMA | agents.py S9 | YES (tenant_id) | NO | No tenant_id completeness scanner |
| M-07 | SERIAL | code_quality_standards | YES (FRONT-009) | NO | No duplicate-fetch detector |
| M-08 | QUERY | code_quality_standards | YES (BACK-016) | PARTIAL (_check_transaction_safety) | Multi-request sequences (not DB transactions) not caught |
| M-09 | SERIAL | agents.py S11 | YES (Enum Registry) | NO | Field-name assumption not cross-checked |
| M-10 | BUILD | agents.py S9 | NO (no realtime rule) | NO | Feature gap in standards |
| M-11 | BUILD | agents.py S9 | YES (Dockerfile) | PARTIAL (DEPLOY scan) | Deployment scan non-blocking |
| M-12 | SCHEMA | code_quality_standards | YES (DB-006/007) | NO | No self-referential relation scanner |
| M-13 | SCHEMA | agents.py S9 | YES (soft delete) | NO | No middleware existence verifier |
| M-14 | QUERY | code_quality_standards | YES (FRONT-007) | PARTIAL (_check_ts_any) | Backend `as any` not flagged as critical |
| M-15 | ROUTE | integration_verifier | YES (path norm) | PARTIAL | Pluralization logic may not catch `propertys` |
| M-16 | SCHEMA | agents.py S1 | NO (no locale rule) | NO | No domain-specific defaults mechanism |
| M-17 | ROUTE | integration_verifier | NO | NO | Dynamic URL construction not analyzed |
| L-01 | SCHEMA | agents.py S9 | PARTIAL | NO | No decimal precision consistency check |
| L-02 | SCHEMA | agents.py S9 | NO | NO | No cross-model type consistency check |
| L-03 | QUERY | agents.py S9 | YES (soft delete) | NO | No redundant-status-and-delete detector |
| L-04 | AUTH | agents.py S9 | YES (security) | NO | No JWT validation depth check |
| L-05 | AUTH | agents.py S9 | YES (validation) | NO | No validation pipe config scanner |
| L-06 | AUTH | code_quality_standards | PARTIAL | NO | No localStorage token scanner |
| L-07 | SERIAL | code_quality_standards | PARTIAL | NO | No date parsing validator |
| L-08 | ENUM | code_quality_standards | PARTIAL | NO | No trim-after-concatenation check |
| L-09 | ENUM | code_quality_standards | PARTIAL | NO | No magic number detector for UUID checks |
| L-10 | SERIAL | code_quality_standards | YES (BACK-005) | NO | No hardcoded-limit detector |
| L-11 | ROUTE | agents.py S5 | YES (review) | NO | LLM reviewer missed field duplication |

### Key Insight

**The builder's #1 systemic failure is the gap between RULES and ENFORCEMENT:**
- 55 of 62 findings (88.7%) have a relevant rule somewhere in the builder's prompt or standards documents
- Only 18 of 62 findings (29.0%) have even PARTIAL automated enforcement
- 0 of 62 findings have COMPLETE automated enforcement that would block the build

The rules are there. The scanners are not.
