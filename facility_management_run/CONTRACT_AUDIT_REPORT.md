# Frontend-Backend Contract Audit Report

**Date:** 2026-03-31
**Method:** 10-agent parallel audit team, each covering one module
**Scope:** Every frontend page vs every backend controller/service in the ArkanPM codebase

---

## EXECUTIVE SUMMARY

| Metric | Count |
|--------|-------|
| **Total Mismatches Found** | **96** |
| HIGH severity | 45 |
| MEDIUM severity | 43 |
| LOW severity | 8 |
| Modules audited | 10 |
| Missing endpoints | 6 |

---

## RESULTS BY MODULE

| # | Module | Agent | HIGH | MED | LOW | Total |
|---|--------|-------|------|-----|-----|-------|
| 1 | Maintenance (WOs, WRs, PM) | maintenance-auditor | 8 | 3 | 1 | **12** |
| 2 | Inspections (templates, reports, compliance) | inspection-auditor | 4 | 3 | 1 | **8** |
| 3 | Warranties (warranties, claims, defects) | warranty-auditor | 2 | 4 | 2 | **8** |
| 4 | Inventory (PRs, parts, stock, warehouses) | inventory-auditor | 3 | 4 | 2 | **9** |
| 5 | Vendors (vendors, contracts, categories) | vendor-auditor | 4 | 7 | 0 | **11** |
| 6 | Property Ops (leases, move-in/out, keys) | propertyops-auditor | 3 | 0 | 0 | **3** |
| 7 | Portfolio + Assets (properties, buildings, units) | portfolio-auditor | 8 | 3 | 1 | **12** |
| 8 | Resident (requests, bookings, visitors) | resident-auditor | 2 | 9 | 0 | **11** |
| 9 | Admin (users, roles, tenants, settings, audit) | admin-auditor | 8 | 5 | 0 | **13** |
| 10 | Owner + Dashboard + Cross-cutting | crosscutting-auditor | 3 | 5 | 1 | **9** |
| | **TOTALS** | | **45** | **43** | **8** | **96** |

---

## TOP 5 SYSTEMIC PATTERNS

### Pattern 1: Query Parameter Name Mismatches (SILENT FILTER FAILURES)
**Impact:** Filters do nothing — user selects a filter, no results change
**Count:** ~8 instances across Maintenance, Inventory, Vendors, Admin

| Frontend Sends | Backend Expects | Module |
|----------------|-----------------|--------|
| `priority` | `priority_id` | Maintenance WOs |
| `buildingId` | `building_id` | Maintenance WRs |
| `category` | `category_id` | Inventory Spare Parts |
| `warehouse` | `warehouse_id` | Inventory Stock |
| `stockLevel` | `low_stock` | Inventory Stock |
| `category` | `category_id` | Vendor list |
| `entity` | `entity_type` | Admin Audit Logs |
| `dateFrom`/`dateTo` | `from`/`to` | Admin Audit Logs |

**Fix:** Create a query parameter normalization middleware or fix each frontend call.

---

### Pattern 2: Missing Prisma Relation Includes (UUIDs / blanks in UI)
**Impact:** Frontend shows "-", UUID, or blank where a name should appear
**Count:** ~20 instances across all modules

Key missing includes:
- **Maintenance WO detail:** missing `building`, `asset` relations
- **Portfolio buildings list:** missing `property` relation
- **Portfolio units list:** missing `floor` with nested `building` relation
- **Asset list/detail:** missing `category`, `building` relations
- **Inspection reports:** missing `building` in `scheduled_inspection` relation
- **Inspection execute:** missing `template.sections.items` nested include
- **Compliance certificates:** missing `requirement` relation
- **Stock levels:** missing `spare_part.category` nested include
- **Admin tenants:** missing `_count: { users: true }`
- **Admin roles:** missing flattened `permissions` (returns join table instead)

**Fix:** Add Prisma `include` clauses to each service's `findAll`/`findById` methods.

---

### Pattern 3: snake_case vs camelCase Field Naming (Entire API)
**Impact:** Frontend reads `undefined` for every mismatched field
**Count:** ~15 instances, worst in Admin Audit Logs (7 fields all mismatched)

Examples:
- Backend: `sla_compliance` / Frontend: `slaCompliance`
- Backend: `is_system` / Frontend: `isSystem`
- Backend: `created_at` / Frontend: `timestamp`
- Backend: `entity_type` / Frontend: `entity`
- Backend: `old_values` / Frontend: `oldValues`
- Backend: `file_type` / Frontend: `fileType`

**Fix:** Either add a response serialization interceptor that converts snake_case to camelCase, or standardize frontend to use snake_case consistently.

---

### Pattern 4: Response Wrapping Inconsistency (`{data, meta}` vs bare object)
**Impact:** Frontend needs defensive `res.data ?? res` everywhere, fragile code
**Count:** System-wide, affects every module

Current behavior:
- List endpoints: return `{ data: [], meta: { total, page, limit, totalPages } }` (mostly)
- Detail endpoints: return bare object (no wrapper)
- Category endpoints: return bare array (no pagination)
- Dashboard endpoints: return bare object with custom shape
- Sub-resource endpoints: inconsistent (some wrap, some don't)

Frontend coping pattern: `const raw = Array.isArray(res) ? res : res.data || [];`

**Fix:** Standardize: list endpoints always return `{data, meta}`, single-resource returns bare object, document the convention.

---

### Pattern 5: Missing Backend Endpoints (Frontend calls to nowhere)
**Impact:** Pages fail to load or features don't work
**Count:** 6 missing endpoints

| Missing Endpoint | Module | Frontend File |
|-----------------|--------|---------------|
| `GET /resident/dashboard` | Resident | `resident/page.tsx` |
| `GET /facility-resources` | Resident | `resident/bookings/page.tsx` |
| `GET /facility-resources/:id/availability` | Resident | `resident/bookings/page.tsx` |
| `GET /resident/profile` | Resident | `resident/profile/page.tsx` |
| `PATCH /resident/profile` | Resident | `resident/profile/page.tsx` |
| `GET /document-categories` | Documents | `documents/page.tsx` |

**Fix:** Implement these endpoints in the respective backend modules.

---

## ALL 96 MISMATCHES BY MODULE

### MODULE 1: MAINTENANCE (12 mismatches)

| # | Severity | Issue | Frontend | Backend |
|---|----------|-------|----------|---------|
| 1 | HIGH | Priority filter param: `priority` vs `priority_id` | work-orders/page.tsx:84 | work-order.controller.ts:437 |
| 2 | HIGH | Inconsistent assignee structure (list vs detail) | work-orders/[id]/page.tsx:202 | work-order.service.ts:174 |
| 3 | HIGH | Missing building & asset relations in WO detail | work-orders/[id]/page.tsx:172 | work-order.service.ts:161 |
| 4 | HIGH | Incomplete asset data in PM schedules list | pm-schedules/page.tsx:49 | pm-schedule.service.ts:54 |
| 5 | HIGH | Inconsistent parts response format | work-orders/[id]/page.tsx:232 | work-order.service.ts:1184 |
| 6 | HIGH | Missing user object in comments | work-orders/[id]/page.tsx:256 | work-order.service.ts:1020 |
| 7 | HIGH | Incomplete enrichment in WR detail | work-requests/[id]/page.tsx:13 | work-request.service.ts:82 |
| 8 | HIGH | Building ID param: `buildingId` vs `building_id` | work-requests/page.tsx:81 | work-request.service.ts:205 |
| 9 | MED | Priority missing `color` field | work-orders/page.tsx:106 | work-order.service.ts:120 |
| 10 | MED | Comments response structure ambiguity | work-orders/[id]/page.tsx:257 | work-order.service.ts:1028 |
| 11 | MED | Duplicate asset field representation | pm-schedules/page.tsx:49 | pm-schedule.service.ts:61 |
| 12 | LOW | Interface naming confusion (WorkRequestAPI) | work-requests/page.tsx:12 | N/A |

### MODULE 2: INSPECTIONS (8 mismatches)

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | Template sections/items missing in scheduled inspection detail |
| 2 | HIGH | Building/inspector enriched manually instead of Prisma includes |
| 3 | HIGH | Building missing from inspection reports scheduled_inspection |
| 4 | HIGH | Compliance certificates missing requirement relation |
| 5 | MED | Inspector name missing from report response |
| 6 | MED | sort_order vs order field naming |
| 7 | LOW | Building fetched separately (extra API call) |
| 8 | MED | Inconsistent pagination structure |

### MODULE 3: WARRANTIES (8 mismatches)

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | reported_by_user not in defect list findAll |
| 2 | HIGH | Defect list missing reported_by_user include |
| 3 | MED | Warranty provider field type (string vs object) |
| 4 | MED | Missing /asset-warranties GET endpoint |
| 5 | MED | Status history changed_by_user inconsistent |
| 6 | MED | Severity values: major/minor in UI, not in backend |
| 7 | LOW | claim_amount fragile multi-field fallback |
| 8 | LOW | reported_at optional vs auto-default unclear |

### MODULE 4: INVENTORY (9 mismatches)

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | Purchase request items _count missing from backend |
| 2 | HIGH | Items JSON serialization ambiguity (string vs array) |
| 3 | HIGH | User UUID resolution field name inconsistency |
| 4 | MED | Spare parts: `category` vs `category_id` filter param |
| 5 | MED | Stock level: `warehouse`/`stockLevel` vs `warehouse_id`/`low_stock` |
| 6 | MED | Stock level missing spare_part.category relation |
| 7 | MED | Reorder alert enrichment fields lack type safety |
| 8 | LOW | Warehouse computed fields missing |
| 9 | LOW | Purchase request missing vendor relation in detail |

### MODULE 5: VENDORS (11 mismatches)

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | Vendor list filter: `category` vs `category_id` |
| 2 | HIGH | SLA config missing computed fields (current_value, is_compliant) |
| 3 | HIGH | Performance page: `company_name` doesn't exist, contacts not included |
| 4 | HIGH | Categories endpoint response format inconsistency |
| 5 | MED | sla_compliance snake_case vs slaCompliance camelCase |
| 6 | MED | Contract detail: vendor_name vs vendor.name |
| 7 | MED | Contract detail: scope_of_work fallback unnecessary |
| 8 | MED | Contract SLA field names: metric_name vs metric, target_value vs target |
| 9 | MED | Vendor detail category defensive access pattern |
| 10 | MED | Contract list: company_name vs name |
| 11 | MED | Contract detail response wrapper inconsistency |

### MODULE 6: PROPERTY OPS (3 mismatches)

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | Lease detail response wrapping (bare vs {data}) |
| 2 | HIGH | Response wrapping pattern inconsistency across all endpoints |
| 3 | MED | Document uploaded_at vs created_at field |

### MODULE 7: PORTFOLIO + ASSETS (12 mismatches)

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | Properties list missing buildingsCount |
| 2 | HIGH | Buildings list missing property name, floor/unit counts |
| 3 | HIGH | Building detail missing property_name, total_units |
| 4 | HIGH | Units list missing floorName, buildingName, rent |
| 5 | HIGH | Unit detail missing floor/building names, allowed_transitions |
| 6 | HIGH | Assets list missing category/building nested objects |
| 7 | HIGH | Asset detail missing category/building/floor/unit relations |
| 8 | HIGH | Asset create category response wrapper inconsistency |
| 9 | MED | Building detail floors missing zones/units_count |
| 10 | MED | Unit detail sub-resource endpoints not verified |
| 11 | MED | Asset transfer endpoint contract not verified |
| 12 | LOW | Property portfolio_id integration incomplete |

### MODULE 8: RESIDENT (11 mismatches)

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | Status history field: `statusHistory` vs `status_history` |
| 2 | HIGH | Status history item shape: `status` vs `to_status` |
| 3 | MED | Announcements response wrapping inconsistency |
| 4 | MED | **Missing endpoint:** GET /resident/dashboard |
| 5 | MED | Inconsistent field names across request/booking/announcement |
| 6 | MED | **Missing endpoint:** GET /facility-resources |
| 7 | MED | **Missing endpoint:** GET /facility-resources/:id/availability |
| 8 | MED | **Missing endpoint:** GET /resident/profile |
| 9 | MED | **Missing endpoint:** PATCH /resident/profile |
| 10 | MED | **Missing endpoint:** PATCH /resident/profile/notifications |
| 11 | MED | Announcement published_at not guaranteed in response |

### MODULE 9: ADMIN (13 mismatches)

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | PATCH /users/:id/roles endpoint doesn't exist |
| 2 | HIGH | Role permissions: module/action vs permissionId contract broken |
| 3 | HIGH | Role isSystem: `is_system` vs `isSystem` |
| 4 | HIGH | Role permissions: join table vs flat array |
| 5 | HIGH | Tenant create: `plan` vs `subscription_plan` |
| 6 | HIGH | Tenant list missing usersCount |
| 7 | HIGH | Settings missing `type` field for input rendering |
| 8 | HIGH | Audit log ALL fields snake_case vs camelCase (7 fields) |
| 9 | MED | Role permissionCount missing |
| 10 | MED | Audit log filter params: entity/dateFrom vs entity_type/from |
| 11 | MED | Audit log userName: bare string vs nested user object |
| 12 | MED | Audit log timestamp: string vs DateTime type |
| 13 | MED | User role assignment naming inconsistency |

### MODULE 10: OWNER + DASHBOARD + CROSS-CUTTING (9 mismatches)

| # | Severity | Issue |
|---|----------|-------|
| 1 | HIGH | Auth user shape: JWT roles[] array vs user.role string |
| 2 | HIGH | Response wrapper inconsistency (system-wide) |
| 3 | HIGH | Owner units response wrapping |
| 4 | MED | Document field names snake_case vs camelCase |
| 5 | MED | Dashboard pagination: /maintenance-dashboard bare vs /work-orders wrapped |
| 6 | MED | Owner profile nesting inconsistency |
| 7 | MED | Missing /document-categories endpoint |
| 8 | MED | Pagination meta incomplete (missing page/limit/totalPages) |
| 9 | LOW | Error response shape undocumented |

---

## RECOMMENDED FIX PRIORITY

### Phase 1: Quick Wins (fix 30+ issues at once)
1. **Response serialization interceptor** — Add a NestJS interceptor that converts all snake_case response fields to camelCase. Fixes Pattern 3 across the entire API.
2. **Query param normalization** — Accept both camelCase and snake_case query params. Fixes Pattern 1 (8 instances).

### Phase 2: Missing Relations (fix 20+ issues)
3. **Bulk Prisma include audit** — For each service's `findAll` and `findById`, add the relation includes that the frontend expects. One PR per module.

### Phase 3: Missing Endpoints (fix 6 issues)
4. **Resident module endpoints** — Create the 5 missing resident endpoints.
5. **Document categories endpoint** — Create GET /document-categories.

### Phase 4: Contract Standardization
6. **Response wrapper convention** — Document and enforce: lists return `{data, meta}`, details return bare object.
7. **Shared TypeScript types** — Create a shared `@arkanpm/types` package with response interfaces used by both frontend and backend.

### Phase 5: Admin Module Deep Fix
8. **Role permissions contract** — Redesign the permission toggle API (module/action vs UUID).
9. **Audit log field alignment** — Fix all 7 field name mismatches.
10. **Settings type field** — Add type inference to system settings response.

---

## ESTIMATED EFFORT

| Phase | Issues Fixed | Effort |
|-------|------------|--------|
| Phase 1 (interceptor + param normalization) | ~38 | 1 session |
| Phase 2 (Prisma includes) | ~20 | 1-2 sessions |
| Phase 3 (missing endpoints) | 6 | 1 session |
| Phase 4 (standardization) | ~15 | 1 session |
| Phase 5 (admin deep fix) | ~10 | 1 session |
| **Total** | **~96** | **5-6 sessions** |
