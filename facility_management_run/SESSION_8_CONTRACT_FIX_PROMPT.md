# SESSION 8 — Fix All 96 Frontend-Backend Contract Mismatches

Read these files completely before doing anything:
- `C:\Projects\ArkanPM\CONTRACT_AUDIT_REPORT.md` — the full audit with all 96 mismatches
- `C:\Projects\ArkanPM\SESSION_6_HANDOFF.md` — build process notes (CRITICAL for rebuilding API)
- `C:\Projects\ArkanPM\FINAL_TEST_REPORT.md` — current test status (33/33 suites passing)

---

## CONTEXT

Sessions 5-7 completed comprehensive Playwright UI testing: 33/33 test suites pass, 68 pages load across 5 roles. A 10-agent audit team then found **96 frontend-backend contract mismatches** across the entire codebase. Your job is to fix ALL of them without breaking anything that currently works.

This is a NestJS + Prisma + Next.js monorepo at `C:\Projects\ArkanPM`.

---

## ABSOLUTE RULES — ZERO REGRESSIONS

1. **NEVER delete existing functionality.** Every feature that works today must still work after your changes.
2. **NEVER change a working API response shape** without updating every frontend consumer. If you add fields, that's fine. If you rename or remove fields, you MUST update all frontend pages that read them.
3. **NEVER remove Prisma includes** that already exist. You may ADD includes, never remove.
4. **NEVER change the Prisma schema** unless absolutely required (adding a relation annotation is OK, removing/renaming columns is NOT).
5. **After ALL backend changes:** rebuild API using the build process below, restart, and verify the API starts without errors.
6. **After ALL changes are complete:** run the smoke test — login as Manager, visit Dashboard, Work Orders, Assets, Vendors, Purchase Requests, and verify no regressions (no new crashes, no new blank fields, no new UUIDs).
7. **Test incrementally.** After each phase, rebuild and verify before moving to the next phase.
8. **Coordinate file edits.** Two agents must NEVER edit the same file simultaneously. Use task dependencies to prevent conflicts.

---

## BUILD PROCESS (CRITICAL)

The Prisma client must exist in TWO locations. After any backend/schema change:

```bash
# 1. Generate Prisma client (only if schema changed)
cd apps/api && npx prisma generate

# 2. Kill API first (DLL lock)
taskkill //F //PID <api_pid>

# 3. Copy to runtime location (only if schema changed)
cp -r apps/api/node_modules/.prisma/client/* "node_modules/.pnpm/@prisma+client@6.19.2_prisma@6.19.2_typescript@5.9.3__typescript@5.9.3/node_modules/.prisma/client/"

# 4. Compile
cd apps/api && npx tsc --noEmit false --outDir dist --rootDir src --declaration false --removeComments true --incremental true --esModuleInterop true --moduleResolution node --module commonjs --target ES2021

# 5. Verify ZERO TypeScript errors (Session 7 achieved this — maintain it)

# 6. Restart API
node apps/api/dist/main.js &
```

Frontend changes hot-reload automatically.

---

## YOUR MISSION

Deploy an **agent team of 10 agents** to fix all 96 mismatches in 5 coordinated phases. Each phase must complete and be verified before the next begins.

### TEAM STRUCTURE

Create a team called `contract-fix` with these 10 agents:

| # | Agent Name | Type | Phase | Responsibility |
|---|-----------|------|-------|----------------|
| 1 | `interceptor-agent` | general-purpose | 1 | Create the NestJS response serialization interceptor (snake_case → camelCase) and query param normalizer |
| 2 | `maintenance-fixer` | general-purpose | 2 | Fix all 12 Maintenance module mismatches (Prisma includes, field mapping) |
| 3 | `inspection-fixer` | general-purpose | 2 | Fix all 8 Inspection module mismatches (template includes, building relations) |
| 4 | `warranty-fixer` | general-purpose | 2 | Fix all 8 Warranty module mismatches (reported_by_user, severity values) |
| 5 | `inventory-fixer` | general-purpose | 2 | Fix all 9 Inventory module mismatches (items count, category, stock relations) |
| 6 | `vendor-fixer` | general-purpose | 2 | Fix all 11 Vendor module mismatches (SLA config, company_name, contacts) |
| 7 | `portfolio-fixer` | general-purpose | 2 | Fix all 12 Portfolio+Assets mismatches (property/building/unit relations) |
| 8 | `resident-fixer` | general-purpose | 3 | Create 6 missing endpoints + fix 5 field mismatches in Resident module |
| 9 | `admin-fixer` | general-purpose | 4 | Fix all 13 Admin mismatches (roles permissions, audit logs, tenants, settings) |
| 10 | `propertyops-crosscut-fixer` | general-purpose | 2 | Fix 3 PropertyOps + 9 Owner/Dashboard/Cross-cutting mismatches |

---

## PHASE 1: Response Interceptor (Agent 1 only, all others wait)

**Why first:** This single change fixes ~38 of 96 issues (snake_case → camelCase conversion). Every subsequent agent benefits from this.

**Agent 1 (`interceptor-agent`) tasks:**

### Task 1.1: Create CamelCase Response Interceptor
Create `apps/api/src/common/interceptors/camelcase-response.interceptor.ts`:
- NestJS interceptor that recursively converts all snake_case keys in response objects to camelCase
- Must handle: nested objects, arrays of objects, null/undefined, Date objects (pass through), Decimal objects (convert to number)
- Must NOT convert keys inside JSON columns (items, metadata) — these are user data
- Register globally in `app.module.ts`

### Task 1.2: Create Query Param Normalizer
Create `apps/api/src/common/middleware/query-normalizer.middleware.ts`:
- NestJS middleware that converts camelCase query params to snake_case
- Maps: `priority` → `priority_id`, `buildingId` → `building_id`, `category` → `category_id`, `warehouse` → `warehouse_id`, `stockLevel` → `low_stock`, `entity` → `entity_type`, `dateFrom` → `from`, `dateTo` → `to`
- Register globally in `app.module.ts`

### Task 1.3: Update Frontend to Remove Defensive Fallbacks
After the interceptor is deployed, update the frontend `api.ts` or individual pages to:
- Remove `Array.isArray(res) ? res : res.data || []` patterns where the interceptor now normalizes
- **DO NOT remove these yet** — only remove after Phase 2 confirms everything works
- For now, just verify the interceptor doesn't break existing pages

### IMPORTANT CONSTRAINT FOR TASK 1:
The interceptor must NOT change the response wrapper structure. If an endpoint returns `{ data: [...], meta: {...} }`, the interceptor converts field names INSIDE data items, but keeps `data` and `meta` as top-level keys. If an endpoint returns a bare object, the interceptor converts its keys.

**After Phase 1:** Rebuild API, restart, verify Dashboard loads with all KPIs still showing correct values.

---

## PHASE 2: Prisma Include Fixes (Agents 2-7 in parallel, Agent 10)

**These 7 agents work in parallel** — each owns different backend service files, no conflicts.

**CRITICAL RULE:** Each agent edits ONLY their module's files. No agent touches another agent's files.

### Agent 2 (`maintenance-fixer`) — 12 fixes
Files to edit:
- `apps/api/src/maintenance/work-order.service.ts` — add building, asset includes to findById; standardize assignee structure
- `apps/api/src/maintenance/work-order.controller.ts` — accept both `priority` and `priority_id` query params  
- `apps/api/src/maintenance/work-request.service.ts` — accept both `buildingId` and `building_id`; guarantee enrichment fields
- `apps/api/src/maintenance/pm-schedule.service.ts` — ensure asset include is consistent
- `apps/web/src/app/(dashboard)/maintenance/work-orders/page.tsx` — update param to `priority_id`
- `apps/web/src/app/(dashboard)/maintenance/work-requests/page.tsx` — update param to `building_id`

### Agent 3 (`inspection-fixer`) — 8 fixes
Files to edit:
- `apps/api/src/inspection/scheduled-inspection.service.ts` — add template.sections.items include to findById; add building include
- `apps/api/src/inspection/inspection-report.service.ts` — add building include to scheduled_inspection; add inspector include
- `apps/api/src/inspection/compliance.service.ts` — add requirement include to certificates
- Frontend inspection pages — standardize sort_order field usage

### Agent 4 (`warranty-fixer`) — 8 fixes
Files to edit:
- `apps/api/src/warranty/defect.service.ts` — verify reported_by_user in findAll (may already be fixed from Session 6)
- `apps/web/src/app/(dashboard)/warranties/defects/page.tsx` — remove major/minor severity badge options
- `apps/web/src/app/(dashboard)/warranties/claims/[id]/page.tsx` — fix provider field access

### Agent 5 (`inventory-fixer`) — 9 fixes
Files to edit:
- `apps/api/src/inventory/purchase-request.service.ts` — add vendor include to findById
- `apps/api/src/inventory/stock-level.service.ts` — add spare_part.category nested include
- `apps/api/src/inventory/spare-part.controller.ts` — accept `category` as alias for `category_id`
- `apps/api/src/inventory/stock-level.controller.ts` — accept `warehouse` as alias for `warehouse_id`
- Frontend pages — update filter param names if not handled by middleware

### Agent 6 (`vendor-fixer`) — 11 fixes
Files to edit:
- `apps/api/src/vendor/vendor.service.ts` — add contacts include to findAll for performance page
- `apps/api/src/vendor/service-contract.service.ts` — standardize SLA field names in response
- Frontend vendor pages — remove company_name references, use name consistently

### Agent 7 (`portfolio-fixer`) — 12 fixes
Files to edit:
- `apps/api/src/portfolio/portfolio.service.ts` — add property include to buildings, floor/building include to units, _count aggregations
- `apps/api/src/asset/asset.service.ts` — add category, building includes to findAll and findById
- Frontend portfolio pages — update field access after includes are added

### Agent 10 (`propertyops-crosscut-fixer`) — 12 fixes
Files to edit:
- `apps/api/src/property-ops/lease.service.ts` — standardize response wrapping
- `apps/api/src/owner/` — fix owner units response, profile nesting
- `apps/web/src/app/(dashboard)/dashboard/page.tsx` — update field access for camelCase after interceptor
- `apps/web/src/lib/auth-context.tsx` — handle roles[] array properly

**After Phase 2:** Rebuild API, restart, verify all modules load correctly. Each agent should verify their module's pages in the browser before marking complete.

---

## PHASE 3: Missing Endpoints (Agent 8)

### Agent 8 (`resident-fixer`) — 11 fixes
Create these new endpoints:
1. `GET /resident/dashboard` — aggregate data from work-requests, bookings, announcements
2. `GET /facility-resources` — list bookable facility resources
3. `GET /facility-resources/:id/availability` — return time slots
4. `GET /resident/profile` — return resident profile with notification preferences
5. `PATCH /resident/profile` — update profile fields
6. `PATCH /resident/profile/notifications` — update notification preferences

Also fix:
7. Status history field naming (statusHistory vs status_history)
8. Status history item shape (status vs to_status)
9. Announcement response handling
10. Field naming inconsistencies
11. published_at field guarantee

Files to create/edit:
- `apps/api/src/resident/resident.controller.ts` — add new endpoints
- `apps/api/src/resident/resident.service.ts` — add new service methods
- `apps/api/src/facility-booking/facility-resource.controller.ts` — add list + availability
- Frontend resident pages — update field access

**After Phase 3:** Rebuild API, restart, login as Resident and verify all pages load.

---

## PHASE 4: Admin Deep Fixes (Agent 9)

### Agent 9 (`admin-fixer`) — 13 fixes
The Admin module has the most complex mismatches:

1. **Role permissions contract** — Backend expects permissionId UUID, frontend sends module/action. Fix: add a backend endpoint that accepts module+action and resolves to permissionId internally.
2. **Role response shape** — Flatten role_permissions join table into a `permissions` array on the role response.
3. **Tenant create** — Accept `plan` as alias for `subscription_plan` in DTO.
4. **Tenant list** — Add `_count: { users: true }` to findAll.
5. **Settings type** — Derive `type` from value typeof in response.
6. **Audit log fields** — After interceptor, verify camelCase conversion handles all 7 fields.
7. **Audit log filters** — Verify query normalizer handles entity/dateFrom/dateTo.
8. **Audit log userName** — Flatten user object into userName string in response.
9. **PATCH /users/:id/roles** — Either create this endpoint or change frontend to use POST.

Files to edit:
- `apps/api/src/role/role.service.ts` — flatten permissions in response
- `apps/api/src/role/role.controller.ts` — add module+action permission endpoint
- `apps/api/src/tenant/tenant.service.ts` — add _count, accept plan alias
- `apps/api/src/system-settings/system-settings.service.ts` — add type derivation
- `apps/api/src/audit/audit.service.ts` — flatten user to userName
- `apps/api/src/user/user.controller.ts` — add PATCH roles endpoint or fix frontend
- Frontend admin pages — update after backend fixes

**After Phase 4:** Rebuild API, restart, login as Super Admin and verify all admin pages.

---

## PHASE 5: Final Verification (Team Lead)

After all agents complete:
1. Rebuild API one final time
2. Verify ZERO TypeScript errors
3. Run full smoke test: login as each role (Manager, Super Admin, Resident, Technician, Owner), visit every sidebar page
4. Verify Dashboard KPIs still show real data (16 WOs, 100% SLA, 45% occupancy, etc.)
5. Spot-check key detail pages: Work Order detail, Purchase Request detail, Vendor detail, Lease detail
6. Verify no UUIDs, no "undefined", no "-" where real data should appear
7. Produce `SESSION_8_HANDOFF.md` with all changes documented

---

## TASK DEPENDENCY GRAPH

```
Phase 1 (interceptor-agent)
    ↓ (must complete before Phase 2 starts)
Phase 2 (maintenance, inspection, warranty, inventory, vendor, portfolio, propertyops — ALL IN PARALLEL)
    ↓ (all must complete before Phase 3)
Phase 3 (resident-fixer)
    ↓ 
Phase 4 (admin-fixer)
    ↓
Phase 5 (team-lead verification)
```

**IMPORTANT:** Phase 2 agents CAN run in parallel because they edit different files. But Phase 1 MUST complete first because the interceptor changes how all responses are serialized, and every subsequent fix depends on knowing whether fields are already camelCase.

---

## ENVIRONMENT

```bash
# Check all services are running
netstat -ano | findstr "5434"  # PostgreSQL
netstat -ano | findstr "6379"  # Redis
netstat -ano | findstr "3000"  # API
netstat -ano | findstr "4201"  # Frontend

# If not running:
docker-compose up -d
cd apps/api && npx prisma generate
# (full build process above)
node apps/api/dist/main.js &
cd apps/web && npx next dev --port 4201 &
```

## TEST ACCOUNTS

| Role | Email | Password |
|------|-------|----------|
| Super Admin | testadmin@facilityplatform.dev | Admin@12345 |
| Facility Manager | manager@facilityplatform.dev | Admin@12345 |
| Maintenance Tech | tech@facilityplatform.dev | Tech@12345 |
| Resident | resident@facilityplatform.dev | Tech@12345 |
| Owner | owner@facilityplatform.dev | Owner@12345! |

---

## SUCCESS CRITERIA

The session is successful when:
- [ ] All 96 contract mismatches are fixed
- [ ] API compiles with ZERO TypeScript errors
- [ ] All 68 pages load across all 5 roles (no regressions)
- [ ] Dashboard KPIs still show real values (Open WOs: 16, SLA: 100%, Occupancy: 45%)
- [ ] No page shows UUIDs where names should appear
- [ ] No page shows "undefined", null, or "-" where real data exists
- [ ] No query filter silently fails
- [ ] All 6 missing endpoints are created and functional
- [ ] SESSION_8_HANDOFF.md is produced documenting every change

Execute Phase 1 first. Wait for completion. Then Phase 2 (parallel). Then Phase 3. Then Phase 4. Then Phase 5 (verification). Do not skip phases.
