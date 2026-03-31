# SESSION 5 HANDOFF — COMPREHENSIVE BUG FIX & TESTING CONTINUATION

**Created:** 2026-03-31
**Session 5 Completed:** 22 of 33 test suites passed
**Bugs Found:** 4 fixed in-session, 17 documented for follow-up
**Primary Pattern:** Backend API queries missing relation includes → frontend shows UUIDs, blanks, and "-" instead of real data

---

## TABLE OF CONTENTS

1. [Phase 1: Known Fixes (Manual, targeted)](#phase-1-known-fixes)
2. [Phase 2: Systemic Relation Fix (Agent Team)](#phase-2-systemic-relation-fix-agent-team)
3. [Phase 3: Remaining Test Suites](#phase-3-remaining-test-suites)

---

# PHASE 1: KNOWN FIXES

These are precise, surgical fixes with exact file paths, line numbers, and what to change. Execute them sequentially. After ALL Phase 1 fixes, rebuild the API (`pnpm -w run build:api`) and restart the node process.

## Fix 1.1 — Warranty Claim CREATE: Missing POST Fields

**Problem:** The claim creation form collects claim_amount, contact_person, contact_email but DOES NOT send them in the POST body. User fills out 3 fields that silently disappear.

**File:** `apps/web/src/app/(dashboard)/warranties/claims/create/page.tsx`
**Lines:** 56-62

**Current code (lines 56-62):**
```typescript
await api.post('/warranty-claims', {
  title: data.title,
  warranty_id: data.warrantyId,
  asset_id: selectedWarranty?.asset_id || data.warrantyId,
  description: data.description,
  priority: data.priority,
});
```

**Fix — add the 3 missing fields:**
```typescript
await api.post('/warranty-claims', {
  title: data.title,
  warranty_id: data.warrantyId,
  asset_id: selectedWarranty?.asset_id || data.warrantyId,
  description: data.description,
  priority: data.priority,
  claim_amount: data.claimAmount ? Number(data.claimAmount) : undefined,
  contact_person: data.contactPerson || undefined,
  contact_email: data.contactEmail || undefined,
  defect_date: data.defectDate || undefined,
});
```

**Then verify:** The `WarrantyClaimService.create()` in `apps/api/src/warranty/warranty-claim.service.ts` (line 146-160) must accept these fields. Check the `CreateWarrantyClaimDto` — if `claim_amount`, `contact_person`, `contact_email` are not in the DTO, add them.

---

## Fix 1.2 — Defect CREATE: warranty_id in metadata instead of direct field

**Problem:** Defect creation sends `warranty_id` nested inside a `metadata` object instead of as a direct field. The detail page then can't find it.

**File:** `apps/web/src/app/(dashboard)/warranties/defects/create/page.tsx`
**Line:** 55-63

**Current code (approx lines 55-63):**
```typescript
const payload: any = {
  title: data.title,
  asset_id: data.assetId || undefined,
  severity: data.severity,
  location: data.location || undefined,
  date_discovered: data.dateDiscovered || undefined,
  description: data.description,
  metadata: {
    ...(data.warrantyId ? { warranty_id: data.warrantyId } : {}),
  },
};
```

**Fix — send warranty_id as a direct field:**
```typescript
const payload: any = {
  title: data.title,
  asset_id: data.assetId || undefined,
  warranty_id: data.warrantyId || undefined,
  severity: data.severity,
  location: data.location || undefined,
  date_discovered: data.dateDiscovered || undefined,
  description: data.description,
};
```

**Then verify:** Check `CreateDefectDto` in the defect controller — `warranty_id` must be an accepted field. If it's not in the DTO, add it as an `@IsOptional() @IsUUID() warranty_id?: string`.

---

## Fix 1.3 — Defect CREATE: Add Category field to form

**Problem:** The defect list has a "Category" column but the creation form doesn't have a Category input. Seed defects show categories; UI-created ones show "-".

**File:** `apps/web/src/app/(dashboard)/warranties/defects/create/page.tsx`

**What to add:**
1. Add `category` to the zod schema (around line 13-21):
   ```typescript
   category: z.string().optional(),
   ```
2. Add a Category dropdown to the form JSX (after Severity dropdown, around line ~120):
   ```tsx
   <Select
     label="Category"
     value={...}
     onChange={...}
     options={[
       { value: '', label: 'Select category' },
       { value: 'Structural', label: 'Structural' },
       { value: 'MEP Systems', label: 'MEP Systems' },
       { value: 'Finishing', label: 'Finishing' },
       { value: 'Safety', label: 'Safety' },
       { value: 'Electrical', label: 'Electrical' },
       { value: 'Plumbing', label: 'Plumbing' },
     ]}
   />
   ```
3. Include `category` in the POST payload.

---

## Fix 1.4 — Work Order Comments: 401 Unauthorized

**Problem:** `POST /work-orders/{id}/comments` returns 401 for facility_manager role.

**Investigation needed:** The audit found that `work-order.service.ts` lines 1001-1010 has the correct roles list. The issue may be in the **controller decorator** — check `apps/api/src/maintenance/work-order-comment.controller.ts` for the `@Roles()` decorator on the POST endpoint. The `facility_manager` role may be missing there.

**File to check:** `apps/api/src/maintenance/work-order-comment.controller.ts`
**Look for:** The `@Post()` method's `@Roles()` decorator — ensure `facility_manager` is included.

---

## Fix 1.5 — Asset Detail: Fix maintenance-history endpoint path

**Problem:** In my fix for the asset detail sub-tabs, I used `/assets/{id}/work-orders` initially which returned 404. I corrected it to `/assets/{id}/maintenance-history`, but the API endpoint is actually `GET /assets/:assetId/maintenance-history`.

**File:** `apps/web/src/app/(dashboard)/assets/[id]/page.tsx`
**Lines:** ~179-200 (the section I edited in this session)

**Verify:** Ensure the path in the `api.get()` call matches the actual controller route. The current code should already be correct after my fix, but confirm the endpoint works by checking the browser console for 404s on the asset detail page.

---

# PHASE 2: SYSTEMIC RELATION FIX (AGENT TEAM)

This is the biggest category of bugs. The root cause is that **backend API service methods don't include related entity data** when returning responses. The frontend expects resolved names (user names, asset names, warranty providers) but receives raw UUIDs or nothing.

## Prerequisites

Agent teams are **experimental**. Before starting, enable them:

```json
// Add to settings.json OR set as environment variable:
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

Requires Claude Code v2.1.32+. Check with `claude --version`.

## How to Launch the Team

Copy-paste the prompt below into a new Claude Code session. Claude will create the team, spawn teammates, coordinate work, and synthesize results. You stay in control — use **Shift+Down** to cycle through teammates and message them directly.

---

## TEAM LAUNCH PROMPT

Paste this as your first message to Claude Code:

```
Create an agent team to fix a systemic backend wiring issue in this NestJS + Prisma + Next.js facility management app. The root cause: backend API service methods don't include Prisma relation data in their queries, so the frontend receives raw UUIDs and blank fields instead of resolved names.

Read C:\Projects\ArkanPM\SESSION_5_HANDOFF.md for full context. The Phase 2 section has all the details.

Spawn 4 teammates:

1. **schema-architect** — Require plan approval before changes.
   Task: Audit the Prisma schema at apps/api/prisma/schema.prisma. For every service file listed below, check whether the relations needed by the frontend actually exist in the schema. Add any missing relations (e.g., Defect → reported_by_user, DefectStatusHistory → changed_by_user). Then run `npx prisma generate`. DO NOT run migrations — only schema relation annotations.
   
   Known missing schema relations:
   - Defect model: needs `reported_by_user User? @relation("DefectReportedBy", fields: [reported_by], references: [id])` and matching back-relation on User
   - DefectStatusHistory model: needs `changed_by_user User? @relation("DefectStatusChangedBy", fields: [changed_by], references: [id])` and matching back-relation on User  
   - Defect model: check if `warranty_id` field exists with relation to AssetWarranty
   - WarrantyClaim model: verify `claim_amount`, `contact_person`, `contact_email` exist as real columns (not just in metadata JSON)

2. **backend-fixer** — Depends on schema-architect completing.
   Task: Update every backend service `findAll` and `findById` method to include the missing Prisma relations. Also update any DTOs that are missing fields.
   
   Services to fix (with exact locations):
   - apps/api/src/warranty/defect.service.ts — findAll (~line 67) and findById (~line 90): add includes for `asset`, `reported_by_user`, `warranty`, and `changed_by_user` in status_history
   - apps/api/src/warranty/warranty-claim.service.ts — findAll (~line 60) and findById (~line 84): add includes for `warranty` (provider name), `asset`. Also update create method (~line 146) to accept `claim_amount`, `contact_person`, `contact_email` fields, and update CreateWarrantyClaimDto
   - apps/api/src/maintenance/pm-schedule.service.ts — findAll: add include for `asset` relation
   - apps/api/src/inventory/purchase-request.service.ts — findAll: add `_count: { select: { items: true } }` or include items array
   - apps/api/src/vendor/vendor.service.ts — findAll: verify category field is being returned
   
   Follow the CORRECT pattern from apps/api/src/asset/asset.service.ts findById — it includes building, floor, unit, category. Use `select` clauses to limit returned fields and avoid N+1 issues.
   
   After all changes: run `pnpm -w run build:api` and verify 0 errors.

3. **frontend-fixer** — Depends on backend-fixer completing.
   Task: Update every frontend page that displays blank/UUID data to read from the new relation fields returned by the updated backend.
   
   Exact files and lines to fix:
   - apps/web/src/app/(dashboard)/warranties/defects/[id]/page.tsx line 74: change reported_by mapping to use `data.reported_by_user?.first_name + ' ' + data.reported_by_user?.last_name`
   - Same file line 61: change history changed_by to use `h.changed_by_user?.first_name + ' ' + h.changed_by_user?.last_name`
   - Same file line ~80: map warranty_provider from `data.warranty?.provider`
   - apps/web/src/app/(dashboard)/warranties/claims/create/page.tsx lines 56-62: ADD claim_amount, contact_person, contact_email, defect_date to the POST body
   - apps/web/src/app/(dashboard)/warranties/claims/[id]/page.tsx line 71: fix claim_amount mapping
   - Same file lines 72-73: fix contact_person and contact_email mapping
   - Same file line 179: fix warranty_provider to read from `data.warranty?.provider`
   - apps/web/src/app/(dashboard)/warranties/defects/create/page.tsx: move warranty_id from metadata to direct field, add category dropdown
   - apps/web/src/app/(dashboard)/maintenance/pm-schedules/page.tsx line ~49: fix asset name mapping to `s.asset?.name`
   - apps/web/src/app/(dashboard)/inventory/purchase-requests/page.tsx line 81: fix items count to use `r._count?.items ?? r.items?.length ?? 0`
   - apps/web/src/app/(dashboard)/vendors/page.tsx line ~59: fix category mapping

4. **verifier** — Depends on frontend-fixer completing.
   Task: After all fixes are applied, rebuild the API (`pnpm -w run build:api`), restart the node process, and verify every fix through the browser using Playwright MCP. For each check below, navigate via sidebar clicks, take browser_snapshot(), and confirm the data is correct:
   
   Verification checklist:
   - Defect detail page: "Reported By" shows a name not UUID
   - Defect detail page: "Warranty" shows provider name not blank
   - Defect detail page: Activity Timeline shows names not UUIDs
   - Defect create: has Category dropdown
   - Warranty Claim create + detail: Amount persists (not $0), Contact fields persist, Warranty Provider shows
   - PM Schedules list: Asset column shows names not "-"
   - Purchase Requests list: Items column shows actual count not "0 items"
   - Vendors list: Category column shows values not blank
   - Work Order Comments tab: posting a comment as facility_manager succeeds (no 401)

Use Sonnet for teammates 1-3 (code changes). Use Opus for teammate 4 (verification needs deeper reasoning for UI testing).

IMPORTANT: Teammates must NOT edit the same files simultaneously. The schema-architect works on schema.prisma only. The backend-fixer works on apps/api/src/**/*.service.ts and DTO files only. The frontend-fixer works on apps/web/src/**/*.tsx only. The verifier reads only, doesn't edit.

After all 4 teammates complete, synthesize a summary of what changed and any remaining issues.
```

---

## What the Team Does (Detailed Breakdown)

### Teammate 1: schema-architect
**Owns:** `apps/api/prisma/schema.prisma` only
**Plan approval required:** Yes — lead reviews schema changes before they're applied
**Deliverable:** Updated schema with all missing User/Warranty relations + successful `npx prisma generate`

Known schema additions needed:

| Model | Field to Add | Relation |
|---|---|---|
| `Defect` | `reported_by_user` | `User? @relation("DefectReportedBy", fields: [reported_by], references: [id])` |
| `User` | `reported_defects` | `Defect[] @relation("DefectReportedBy")` |
| `DefectStatusHistory` | `changed_by_user` | `User? @relation("DefectStatusChangedBy", fields: [changed_by], references: [id])` |
| `User` | `defect_status_changes` | `DefectStatusHistory[] @relation("DefectStatusChangedBy")` |
| `Defect` | `warranty_id` + `warranty` | Check if exists; add if missing |

### Teammate 2: backend-fixer
**Owns:** `apps/api/src/**/*.service.ts`, `apps/api/src/**/*.dto.ts`
**Blocked until:** schema-architect completes
**Deliverable:** All service methods updated with correct `include` clauses, DTOs updated, API builds with 0 errors

Example fix pattern (defect.service.ts findById):
```typescript
// ADD to include clause:
asset: { select: { id: true, name: true, asset_code: true } },
reported_by_user: { select: { id: true, first_name: true, last_name: true } },
warranty: { select: { id: true, provider: true, type: true } },
status_history: {
  orderBy: { created_at: 'desc' },
  include: { changed_by_user: { select: { id: true, first_name: true, last_name: true } } },
},
```

### Teammate 3: frontend-fixer
**Owns:** `apps/web/src/**/*.tsx`
**Blocked until:** backend-fixer completes
**Deliverable:** All frontend pages updated to read resolved names from API response

Key mapping changes:

| File | Line | Current | Fixed |
|---|---|---|---|
| `defects/[id]/page.tsx` | 74 | `data.reported_by` (UUID) | `` `${data.reported_by_user?.first_name} ${data.reported_by_user?.last_name}`.trim() \|\| '-' `` |
| `defects/[id]/page.tsx` | 61 | `h.changed_by` (UUID) | `` `${h.changed_by_user?.first_name} ${h.changed_by_user?.last_name}`.trim() \|\| h.changed_by `` |
| `claims/create/page.tsx` | 56-62 | Missing 3 POST fields | Add `claim_amount`, `contact_person`, `contact_email` to POST body |
| `claims/[id]/page.tsx` | 71 | `data.cost_covered ?? data.claim_amount ?? 0` | `data.claim_amount ?? 0` |
| `pm-schedules/page.tsx` | ~49 | `s.asset_name` | `s.asset?.name \|\| '-'` |
| `purchase-requests/page.tsx` | 81 | `r.itemsCount ?? 0` | `r._count?.items ?? r.items?.length ?? 0` |

### Teammate 4: verifier
**Owns:** Read-only. Uses Playwright MCP browser tools.
**Blocked until:** frontend-fixer completes
**Model:** Opus (needs deeper reasoning for UI verification)
**Deliverable:** Verification report — pass/fail for each data point

Verification matrix (14 checks):

| # | Page | Field | Expected After Fix |
|---|---|---|---|
| 1 | `/warranties/defects/{id}` | Reported By | "Sarah Chen" (not UUID) |
| 2 | `/warranties/defects/{id}` | Warranty | "CoolTech Manufacturer" (not blank) |
| 3 | `/warranties/defects/{id}` | Timeline entries | User names (not UUIDs) |
| 4 | `/warranties/defects/create` | Category dropdown | Exists with options |
| 5 | `/warranties/claims/{id}` | Warranty Provider | Provider name (not "-") |
| 6 | `/warranties/claims/{id}` | Claim Amount | "$8,500" (not "$0") |
| 7 | `/warranties/claims/{id}` | Contact Person | "Mohammed Al Rashid" (not blank) |
| 8 | `/warranties/claims/{id}` | Contact Email | "m.rashid@cooltech.ae" (not blank) |
| 9 | Create new claim | All fields persist | Create → detail shows all data |
| 10 | `/maintenance/pm-schedules` | Asset column | Asset names (not "-") |
| 11 | `/maintenance/pm-schedules` | Next Due column | Dates (not "-") |
| 12 | `/inventory/purchase-requests` | Items column | "3 items" (not "0 items") |
| 13 | `/vendors` | Category column | "HVAC" etc (not blank) |
| 14 | `/maintenance/work-orders/{id}` | Comments tab | Comment posts successfully (no 401) |

---

## Team Coordination Notes

- **File ownership is strict:** No two teammates edit the same file. Schema → Backend services → Frontend pages → Verification. This prevents merge conflicts.
- **Task dependencies are sequential:** 1 → 2 → 3 → 4. Each teammate is blocked until the prior one finishes.
- **Plan approval on teammate 1 only:** Schema changes are the riskiest (can break everything if wrong). The lead should review before approving.
- **Total estimated teammates:** 4 (3 Sonnet + 1 Opus)
- **Total estimated tasks:** ~20 (5-6 per teammate)
- **Token budget:** High — each teammate has its own context window. Worth it because the alternative is manually fixing 17 bugs one-by-one across 15+ files.

---

# PHASE 3: REMAINING TEST SUITES

After Phase 1 and 2 fixes are complete, continue the Playwright UI testing from where Session 5 left off. Execute suites in this exact order:

## Remaining Suites (11 total + smoke test)

### Suite 19 — Purchase Request + Approval Lifecycle (Manager)
- **Prereq:** Fix 1.1 applied (so amounts work), Phase 2 done (so items count shows)
- Navigate to Purchase Requests → Click "New Request" → Fill form with line items → Submit
- Then: Submit for Approval → Approve → Mark as Ordered → Mark as Received
- **Critical checks:** Line items render with correct totals, status transitions work, approval timeline shows

### Suite 21 — Vendor + Contract Creation (Manager)
- Create vendor "FireGuard Safety Systems" with all fields
- Create vendor contract linked to FireGuard
- **Critical checks:** Vendor detail page shows all fields (not UUIDs), contract shows vendor name (not UUID)

### Suite 22 — Vendor Performance (Manager)
- Click on CoolTech HVAC Services vendor → Check detail page
- **Critical checks:** Company name visible, contact info, specializations. No UUIDs anywhere.

### Suite 5 — Move-Out Wizard 7-Step Flow (Manager)
- **Prereq:** An active lease with completed move-in (LSE-2024-001 or LS-2026-00002)
- Navigate to Move-Out → Select lease → Step through all 7 steps
- **Critical checks:** Each step loads, condition dropdowns work, damage items add/total correctly, deposit math is correct, keys checklist works, meter readings save, review summary shows ALL data, completion succeeds

### Suite 28 — Admin Pages (Super Admin)
- **Login as:** testadmin@facilityplatform.dev / Admin@12345
- Visit: Admin Dashboard, Users, Roles, Tenants, Audit Logs, Settings, Integrations, Webhooks, Notifications
- **Critical checks:** All 9 admin pages load without crashes, user list shows 7+ users with names/roles, role list shows all 11 roles

### Suite 12 — Owner Portal (Super Admin → Owner)
- Create owner user account via Admin Users page
- Create owner record via Owners page (if form exists)
- Login as owner → Test Owner Home, My Units, My Documents, My Profile
- **Critical checks:** Owner sidebar shows only owner-relevant pages, unit ownership details show, profile save works

### Suite 29 — Notification Bell (Manager)
- Login as Manager → Look for bell icon in header → Click it
- **Critical checks:** Bell icon exists, dropdown opens, notifications list renders (or "no notifications" message)

### Suite 30 — Cross-Module Data Flow (Resident → Manager)
- Login as Resident → Create work request "Lobby lights flickering on Floor 2"
- Login as Manager → Navigate to Work Requests → Verify the resident's request appears
- Check Dashboard → Verify KPI cards show non-zero values
- **Critical checks:** Data created by one role appears for another role, dashboard aggregates are accurate

### Suite 31 — Error Handling + Empty States (Manager)
- Work Orders: Filter by status with no results → Verify "No work orders found" empty state
- Assets: Search "ZZZZNONEXISTENT" → Verify "No assets found" empty state
- Spare Parts: Filter by category → Verify filter works without errors
- Warranties: Status filter and expiry filter → Verify both work
- **Critical checks:** No crashes on empty results, meaningful empty state messages, filters reset correctly

### Suite 32 — Data Persistence Verification (Manager)
- Visit each page and verify data created during earlier suites still exists:
  - Assets → "Emergency Lighting Panel #1" (Suite 9)
  - Defects → latest defect (Suite 17)
  - Warranty Claims → latest claim (Suite 18)
  - PM Schedules → 3 schedules (Suite 20)
  - Vendors → 3 vendors (Suite 21)
  - Properties → "Marina Heights" (Suite 24)
  - Buildings → "Marina Tower A" (Suite 24)
  - Inspection Reports → Fire Safety report (Suite 11)

### Final Smoke Test — All Pages Load (4 Roles)

**Manager (34 pages):** Dashboard, Portfolio, Properties, Buildings, Floors & Zones, Units, Assets, Work Requests, Work Orders, PM Schedules, SLA Dashboard, Inspection Templates, Schedule Inspection, Scheduled Inspections, Inspection Reports, Compliance, Warranties, Warranty Claims, Defects, Vendors, Vendor Contracts, Spare Parts, Purchase Requests, Stock Levels, Warehouses, Reorder Alerts, Residents, Owners, Leases, Move-In, Move-Out, Occupancy, Key Register, Document Library

**Super Admin (9 pages):** Admin Dashboard, Tenants, Users, Roles, Settings, Audit Logs, Integrations, Webhooks, Notifications

**Resident (7 pages):** Resident Home, My Requests, Bookings, Visitors, Announcements, My Profile, Document Library

**Owner (4 pages, if created):** Owner Home, My Units, My Documents, My Profile

**Technician (13 pages):** Dashboard, Work Requests, Work Orders, PM Schedules, SLA Dashboard, Inspection Templates, Scheduled Inspections, Inspection Reports, Compliance, Warranties, Warranty Claims, Defects, Document Library

**For each page:** Take `browser_snapshot()`, verify no blank screen/crash, verify no UUIDs where names should be.

---

# ENVIRONMENT SETUP FOR NEXT SESSION

```bash
# 1. Start Docker (PostgreSQL + Redis)
docker-compose up -d

# 2. Verify ports
netstat -ano | findstr "5434"  # PostgreSQL
netstat -ano | findstr "6379"  # Redis

# 3. Build and start API
pnpm -w run build:api
node apps/api/dist/main.js &

# 4. Start frontend
cd apps/web && npx next dev --port 4201 &

# 5. Verify both running
netstat -ano | findstr "3000"  # API
netstat -ano | findstr "4201"  # Frontend
```

## Test Accounts

| Role | Email | Password |
|------|-------|----------|
| Super Admin | testadmin@facilityplatform.dev | Admin@12345 |
| Facility Manager | manager@facilityplatform.dev | Admin@12345 |
| Maintenance Tech | tech@facilityplatform.dev | Tech@12345 |
| Inspector | inspector@facilityplatform.dev | Tech@12345 |
| Resident | resident@facilityplatform.dev | Tech@12345 |

## Login Procedure (react-hook-form compatible)
```
1. browser_navigate('http://localhost:4201/login')
2. browser_click(email field)
3. browser_type(email, slowly: true)
4. browser_click(password field)
5. browser_type(password, slowly: true)
6. browser_click(Sign in button)
7. browser_wait_for(text: 'Welcome')
```

---

# CHANGES MADE IN SESSION 5

## Files Modified (frontend):
1. `apps/web/src/app/(dashboard)/documents/upload/page.tsx` — Changed limit from 200 to 100
2. `apps/web/src/app/(dashboard)/assets/[id]/page.tsx` — Added API calls for all sub-tabs (warranties, maintenance, documents, condition assessments, meters)
3. `apps/web/src/app/(dashboard)/assets/[id]/transfer/page.tsx` — Fixed response mapping for asset data, buildings, floors, units

## Files Modified (backend/seed):
4. `apps/api/prisma/seed.ts` — Updated warranty WRN-HVAC-001 dates from 2020-2025 to 2022-2027 + added update for existing records

## Files NOT modified but NEED changes (Phase 1 & 2):
- `apps/web/src/app/(dashboard)/warranties/claims/create/page.tsx` — Missing POST fields
- `apps/web/src/app/(dashboard)/warranties/defects/create/page.tsx` — warranty_id in metadata, missing category
- `apps/api/src/warranty/defect.service.ts` — Missing relation includes
- `apps/api/src/warranty/warranty-claim.service.ts` — Missing fields + relation includes
- `apps/api/src/maintenance/pm-schedule.service.ts` — Missing asset relation
- `apps/api/src/inventory/purchase-request.service.ts` — Missing items count
- `apps/api/src/vendor/vendor.service.ts` — Missing category field
- `apps/api/prisma/schema.prisma` — Missing user relations on Defect and DefectStatusHistory
