# ArkanPM Testing Session Handoff Document

**Created:** 2026-03-29
**Updated:** 2026-03-29 (Session 2 — code fixes complete, ready for UI testing)
**Purpose:** Guide the next Claude session to complete UI testing across the entire app using Playwright MCP.

---

## Session History

### Session 1 (Manual Testing)
Manually tested Workflows 1-4 by navigating the UI as an end user. Discovered 10 categories of recurring bugs. Fixed issues as found.

### Session 2 (Systematic Code Sweep + Fixes)
Ran a systematic code-level sweep across ALL 80+ page.tsx files and ALL API controllers/services. Found and fixed **50+ bugs** across 40+ files. All fixes applied, API rebuilt, app running. **Phase 1 is 100% complete.**

---

## Environment Setup

- **API:** `node apps/api/dist/apps/api/src/main.js` (port 3000)
- **Web:** `cd apps/web && npx next dev --port 4201` (port 4201, not 4200 — bayan-ui occupies 4200)
- **PostgreSQL:** Docker on port 5434 (not 5432 — bayan-db occupies 5432)
- **Redis:** Docker on port 6379
- **FRONTEND_URL in .env:** `http://localhost:4201` (CORS)
- **Build:** `pnpm run build:api` then restart node process. Frontend hot-reloads.
- After any API code change: kill node, `rm -rf apps/api/dist`, `pnpm run build:api`, restart.
- After frontend-only changes: hot-reload handles it, just refresh the browser.
- **Prisma + pnpm fix:** After `pnpm install` or `prisma generate`, copy generated client to pnpm store:
  ```
  cp -r apps/api/node_modules/.prisma/client/* "node_modules/.pnpm/@prisma+client@6.19.2_prisma@6.19.2_typescript@5.9.3__typescript@5.9.3/node_modules/.prisma/client/"
  ```
- **`.npmrc`:** `shamefully-hoist=true`
- **API tsconfig (`apps/api/tsconfig.json`):** `declaration: false` (required to avoid TS2742 errors with pnpm + Prisma)
- **Playwright MCP:** Configured with Chrome. Available as `playwright` MCP server.

---

## Accounts

| Role | Email | Password |
|------|-------|----------|
| Super Admin | testadmin@facilityplatform.dev | Admin@12345 |
| Facility Manager | manager@facilityplatform.dev | Admin@12345 |
| Maintenance Tech | tech@facilityplatform.dev | Tech@12345 |
| Inspector | inspector@facilityplatform.dev | Tech@12345 |
| Resident | resident@facilityplatform.dev | Tech@12345 |
| Resident 2 | resident2@facilityplatform.dev | Tech@12345 |
| Resident (new) | ahmed@facilityplatform.dev | Resident@123 |

---

## Phase 1 COMPLETED: All Code Fixes Applied

### Summary
50+ bugs fixed across 40+ files. All 10 bug pattern categories addressed globally.

### Frontend Fixes (34 files modified)

#### Move-In Wizard (`property-ops/move-in/page.tsx`)
- **Endpoint:** Changed `POST /move-in` (didn't exist) to proper multi-step: `POST /move-in-checklists` + `POST /key-handovers` + `POST /meter-readings` + `POST /move-in-checklists/:id/complete`
- **Condition enum:** `'new'` changed to `'excellent'` (API: `@IsIn(['excellent','good','fair','poor','damaged'])`)
- **Key type enum:** `'main_door'`/`'mailbox'`/`'parking'`/`'storage'`/`'gate'` changed to `'unit_key'`/`'mailbox_key'`/`'garage_remote'`/`'access_card'`/`'fob'`
- **Meter type:** `'electricity'` changed to `'electric'` (API: `@IsIn(['electric','water','gas','steam','chilled_water'])`)
- **Lease loading:** Added response unwrapping + field mapping (API returns snake_case `unit_id`, `lease_number` etc.)
- **Default condition:** Changed from `'good'` to `'excellent'` for new move-ins

#### Move-Out Wizard (`property-ops/move-out/page.tsx`)
- **Condition enum:** `'new'` to `'excellent'`
- **Meter type:** `'electricity'` to `'electric'`
- **Lease loading:** Safe unwrapping + field mapping from API snake_case
- **Checklist fetch:** Fixed from nonexistent `/move-in/{id}/checklist` to `GET /move-in-checklists?lease_id={id}`

#### Occupancy Dashboard (`property-ops/occupancy/page.tsx`)
- **Endpoint:** `/occupancy` (404) to `/occupancy/dashboard` (correct)
- **Response mapping:** `res.buildings`/`res.overall` mapped to `res.summary.occupancy_rate`/`res.buildings[].building_name`

#### Key Register (`property-ops/keys/page.tsx`)
- **Key type options:** Matched to API enum (`unit_key`, `mailbox_key`, `access_card`, `garage_remote`, `fob`)
- **Query param:** `key_type` changed to `type` (matches API DTO)
- **Search:** Removed unsupported `search` param; added `limit`

#### Asset List (`assets/page.tsx`)
- **Query params:** `buildingId` to `building_id`, `categoryId` to `category_id`

#### Asset Create — Edit Mode (`assets/create/page.tsx`)
- **Field loading:** All camelCase (`categoryId`, `buildingId`, `floorId`, `unitId`, `serialNumber`, `purchaseDate`, `purchasePrice`, `usefulLife`) changed to snake_case with fallbacks

#### Asset Transfer (`assets/[id]/transfer/page.tsx`)
- **Endpoint:** `/assets/${id}/transfer` to `/assets/${id}/transfers` (correct)
- **Field names:** `buildingId`/`floorId`/`unitId` to `to_building_id`/`to_floor_id`/`to_unit_id`

#### Asset Detail (`assets/[id]/page.tsx`)
- **UUID display:** `raw.building_id` (UUID) changed to `raw.building?.name || raw.building_name`; same for floor and unit

#### Asset Categories (`assets/categories/page.tsx`)
- **Field name:** `parentId` to `parent_id` in POST body

#### Warehouse Page (`inventory/warehouses/page.tsx`)
- **Endpoint:** `/warehouse-locations` (404) to `/warehouses` (correct)

#### Reorder Alerts (`inventory/alerts/page.tsx`)
- **HTTP method:** `api.patch(...acknowledge)` to `api.post(...acknowledge)` (API uses POST)

#### Purchase Request Detail (`inventory/purchase-requests/[id]/page.tsx`)
- **Status transitions:** Generic `PATCH /:id/status` replaced with specific endpoints: `POST /submit`, `POST /approve`, `POST /reject`, `POST /order`, `POST /receive`, `POST /cancel`

#### Purchase Request List (`inventory/purchase-requests/page.tsx`)
- **Status filter:** Added missing `'partially_received'` and `'cancelled'` options

#### Visitor Passes (`resident/visitors/page.tsx`)
- **Status filtering:** `'active'` (not a valid status) changed to `['pending', 'approved', 'checked_in']`
- **Response unwrapping:** Safe `Array.isArray(res) ? res : res?.data ?? []`

#### Resident Profile (`resident/profile/page.tsx`)
- **Interface fields:** All camelCase (`firstName`, `lastName`, `emergencyContact`, `emergencyPhone`) changed to snake_case (`first_name`, `last_name`, `emergency_contact_name`, `emergency_contact_phone`)
- **API fetch:** Maps from API response which returns flat profile fields
- **Form inputs:** All `value`/`onChange` updated to use snake_case fields

#### Document Upload (`documents/upload/page.tsx`)
- **Forbidden fields removed:** `storage_path` and `status` (API rejects with `forbidNonWhitelisted`)
- **Tags:** Now properly sent as array from comma-separated input

#### Document Library (`documents/page.tsx`)
- **Field mapping:** Added mapping from snake_case API response (`file_type`, `file_size`, `uploaded_by`, `uploaded_at`, `entity_type`, `entity_name`) to camelCase display fields

#### Warranty List (`warranties/page.tsx`)
- **Status filter:** Added `'expiring_soon'` and `'voided'` options

#### Warranty Claim Detail (`warranties/claims/[id]/page.tsx`)
- **Field name:** `data.claimed_amount` to `data.claim_amount ?? data.claimed_amount`

#### SLA Dashboard (`maintenance/sla/page.tsx`)
- **Endpoint:** Now tries `GET /maintenance-dashboard` first (proper endpoint), falls back to computing from `/work-orders`

#### Notification Preferences (`settings/notifications/page.tsx`)
- **HTTP method:** `api.patch(/notification-preferences/${id})` to `api.post('/notification-preferences', {...})` (API uses POST upsert, no PATCH)

#### Vendor Contracts List (`vendors/contracts/page.tsx`)
- **Field mapping:** Added mapping from snake_case API (`contract_number`, `vendor.company_name`, `start_date`, `end_date`, `contract_value`)

#### Vendor Contracts Create (`vendors/contracts/create/page.tsx`)
- **Response unwrapping:** Safe pattern for vendor dropdown loading

#### Vendor Performance (`vendors/performance/page.tsx`)
- **Response unwrapping:** Safe pattern

#### PM Schedules Create (`maintenance/pm-schedules/create/page.tsx`)
- **Edit loading:** All camelCase fields changed to snake_case with fallbacks (`asset_id`, `start_date`, `end_date`, `lead_days`, `checklist_template`)

#### Bookings Page (`resident/bookings/page.tsx`)
- **Response unwrapping:** Both resources and bookings use safe pattern

#### Announcements Page (`resident/announcements/page.tsx`)
- **Response unwrapping:** Safe pattern

#### Portfolio Pages (5 files)
- `portfolio/page.tsx`, `portfolio/properties/page.tsx`, `portfolio/buildings/page.tsx`, `portfolio/units/page.tsx`, `portfolio/floors/page.tsx` — All fixed with safe response unwrapping

#### Portfolio Create Pages (2 files)
- `portfolio/buildings/create/page.tsx`, `portfolio/properties/create/page.tsx` — Safe response unwrapping for dropdown data

#### Admin Users (`admin/users/page.tsx`)
- **Response unwrapping:** Safe pattern for user list + pagination meta

### Backend Fixes (8 files modified, API rebuilt)

#### Asset Service (`asset/asset.service.ts`)
- **findById:** Added manual lookups for building_name, floor_name, unit_name (Prisma has no relations for these)

#### Lease Service (`property-ops/lease.service.ts`)
- **findAll:** Added unit_name and resident_name enrichment for every lease in list (looks up from unit/resident tables)

#### Reorder Alert Service (`inventory/reorder-alert.service.ts`)
- **findAll:** Added spare_part_name, part_number, and warehouse_name enrichment
- **Warehouse model:** Fixed from `warehouse` (wrong) to `warehouseLocation` (correct Prisma model name)

#### Reorder Alert Controller (`inventory/reorder-alert.controller.ts`)
- **AcknowledgeAlertDto:** Made `acknowledged_by` optional
- **acknowledge endpoint:** Auto-fills `acknowledged_by` from JWT `@CurrentUser('userId')` if not provided

#### Occupancy Service (`property-ops/occupancy.service.ts`)
- **getDashboard:** Added building name enrichment — batch-fetches building names and returns `building_name` alongside `building_id`

#### Resident Portal Controller (`resident/resident-portal.controller.ts`)
- **New endpoint:** `PATCH /resident/profile` with `UpdateResidentProfileDto` (accepts `first_name`, `last_name`, `phone`, `emergency_contact_name`, `emergency_contact_phone`)

#### Resident Portal Service (`resident/resident-portal.service.ts`)
- **getProfile:** Now returns flat top-level fields (`first_name`, `last_name`, `email`, `phone`, `emergency_contact_name`, `emergency_contact_phone`) for direct frontend consumption
- **New method:** `updateProfile()` — updates both resident record and user record

#### Lease Service (`property-ops/lease.service.ts`)
- **findAll enrichment:** Each lease in list now includes resolved `unit_name` and `resident_name`

---

## Phase 2: Playwright UI Testing (NEXT SESSION)

### CRITICAL RULES

1. **NEVER navigate by typing URLs in the browser address bar.** Always click through sidebar links and UI buttons. The ONLY exception is the initial login page.
2. **NEVER insert data directly into the database.** All data must be created through UI forms.
3. **NEVER skip a broken page.** If something is broken, STOP, fix the code, rebuild if backend, then resume testing from where you left off.
4. **ALWAYS rebuild the API after backend changes:** kill node, `rm -rf apps/api/dist`, `pnpm run build:api`, then `cp -r apps/api/node_modules/.prisma/client/* "node_modules/.pnpm/@prisma+client@6.19.2_prisma@6.19.2_typescript@5.9.3__typescript@5.9.3/node_modules/.prisma/client/"`, restart node.
5. **Frontend-only changes hot-reload** — just refresh the browser page after saving.
6. **Test as the correct user role** specified for each workflow. Log out and log back in when switching roles.
7. **Fix along the way.** The goal is a fully working app, not just a test report.
8. **Take a snapshot after each major step** to verify the page rendered correctly.
9. **If a form submission fails**, check the browser console/network tab for the error, fix the code, and retry.

### How to Use Playwright MCP

The Playwright MCP server is configured with Google Chrome. Use these tools:
- `browser_navigate(url)` — only for initial login page
- `browser_snapshot()` — take accessibility snapshot to see page content (USE FREQUENTLY)
- `browser_click(element)` — click sidebar links, buttons, dropdowns
- `browser_type(element, text)` — fill form fields
- `browser_select_option(element, value)` — select dropdown values
- `browser_screenshot()` — take visual screenshot when needed
- `browser_press_key(key)` — press Enter, Tab, etc.

**Workflow for each test:**
1. `browser_snapshot()` to see current state
2. Identify the correct element to interact with
3. Perform the action (click/type/select)
4. `browser_snapshot()` to verify the result
5. If unexpected, investigate and fix

---

### TEST 1: System Bootstrap (Login + Navigation)

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 1.1 | Open login page | `browser_navigate('http://localhost:4201/login')` | Login form visible with email, password fields, "Sign in" button |
| 1.2 | Enter email | Type `manager@facilityplatform.dev` into email field | Email filled |
| 1.3 | Enter password | Type `Admin@12345` into password field | Password filled |
| 1.4 | Click Sign in | Click the "Sign in" button | Redirects to /dashboard. Take snapshot — should show "Welcome back, Sarah" |
| 1.5 | Verify sidebar | Snapshot the page | Sidebar shows: Dashboard, Property Management, Operations, Resources, Property Ops, Documents, Portfolio |
| 1.6 | Click Properties | Click "Properties" under Portfolio in sidebar | Properties page loads with table. Take snapshot — should show 3 properties |
| 1.7 | Click Buildings | Click "Buildings" under Portfolio in sidebar | Buildings page with table. Should show 5 buildings |
| 1.8 | Click Units | Click "Units" under Portfolio in sidebar | Units page with table. Should show 20 units |
| 1.9 | Click Spare Parts | Click "Inventory" then "Spare Parts" in sidebar | Spare parts page. Stock Level column should show colored indicators with actual numbers (NOT all "1") |
| 1.10 | Click Vendors | Click "Vendors" in sidebar | Vendors page loads with table showing 3 vendors |
| 1.11 | Click Assets | Click "Assets" in sidebar | Assets page loads with table of assets |
| 1.12 | Click Dashboard | Click "Dashboard" in sidebar | Dashboard shows KPI cards (Open Work Orders, Occupancy Rate %, etc.) |

---

### TEST 2: Reactive Maintenance (Full Lifecycle)

#### Part A — Resident Submits Work Request

**Logout, then login as:** `resident@facilityplatform.dev` / `Tech@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 2.1 | Login as resident | Fill login form, click Sign in | Dashboard shows "Welcome back, James". Sidebar ONLY shows: Dashboard, Documents, Resident Portal sections |
| 2.2 | Click My Requests | Click "My Requests" in sidebar under Resident Portal | Work requests list page loads |
| 2.3 | Click New Request | Click "New Request" button (top right) | Form appears with Title, Category, Description fields |
| 2.4 | Fill Title | Type "Bathroom faucet leaking" | Title filled |
| 2.5 | Select Category | Select "Plumbing" from Category dropdown | Category selected |
| 2.6 | Fill Description | Type "The bathroom faucet has been dripping constantly for 2 days." | Description filled |
| 2.7 | Submit | Click "Submit Request" button | Redirects to request detail or list. Status shows "submitted" |
| 2.8 | Verify in list | Click "My Requests" in sidebar | New request appears in list with status "Submitted" |

#### Part B — Manager Processes Work Request

**Logout, login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 2.9 | Open Work Orders | Click "Maintenance" then "Work Orders" in sidebar | Work orders list loads |
| 2.10 | Click a work order | Click on any work order row | Detail page shows: title, status badge, priority, description, assignment, SLA Performance, checklist tab, status timeline |

#### Part C — Work Order Status Transitions

| # | Action | How | Expected |
|---|--------|-----|----------|
| 2.11 | Find action button | Snapshot the detail page — look for "Start Work" / "Assign" button | Action button visible in top right area |
| 2.12 | Click Start Work | Click "Start Work" button (if status is "assigned") | Modal opens with Notes textarea and Confirm button |
| 2.13 | Add notes + confirm | Type "Starting repair work", click "Confirm" | Status changes to "in_progress". New buttons: "Put On Hold", "Complete" |
| 2.14 | Click Complete | Click "Complete" button | Modal opens |
| 2.15 | Add notes + confirm | Type "Fixed the leak, replaced washer", click "Confirm" | Status changes to "completed". Button: "Verify" |
| 2.16 | Click Verify | Click "Verify" | Modal, type notes, Confirm | Status "verified". Button: "Close" |
| 2.17 | Click Close | Click "Close" | Modal, Confirm | Status "closed". No more action buttons. Timeline shows all transitions |

---

### TEST 3: Preventive Maintenance

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 3.1 | Open Work Orders | Click "Maintenance" then "Work Orders" in sidebar | List loads |
| 3.2 | Find PM work order | Look through list for type "preventive" | At least one PM work order visible |
| 3.3 | Click PM work order | Click on it | Detail shows Type = "preventive" |
| 3.4 | Click Checklist tab | Click "Checklist" tab | Shows checklist items (or "No checklist items" for older WOs) |

---

### TEST 4: Inspections

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 4.1 | Open Inspections | Click "Inspections" in sidebar | Templates page loads showing inspection templates table |
| 4.2 | Verify templates | Snapshot | At least 1 template visible |
| 4.3 | Click template | Click on a template row | Template detail page with sections |
| 4.4 | Go back, schedule | Click "Schedule Inspection" in sidebar | Scheduling form: Template dropdown, Building dropdown, dates, Notes |
| 4.5 | Select template | Select a template from dropdown | Selected |
| 4.6 | Select building | Select a building from dropdown | Selected |
| 4.7 | Set dates | Set scheduled date to next week, due date to 2 weeks out | Dates filled |
| 4.8 | Add notes | Type "Quarterly safety inspection" | Notes filled |
| 4.9 | Submit | Click "Schedule Inspection" button | Redirects to scheduled inspections list |
| 4.10 | Verify | Snapshot the scheduled inspections page | New inspection visible in list |

---

### TEST 5: Warranty Claims

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 5.1 | Open Warranties | Click "Warranties" in sidebar | Warranties overview page with table |
| 5.2 | Verify table | Snapshot | Columns: Asset, Provider, Type, Policy #, Start Date, End Date, Status |
| 5.3 | Check status badge | Look for "Active" status | Green "Active" badge visible on at least one warranty |
| 5.4 | Test status filter | Change status filter dropdown to "Active" | Table filters to show only active warranties |
| 5.5 | Test "Expiring Soon" filter | Change filter to "Expiring Soon" | Table updates |
| 5.6 | Open Claims | Click "Warranty Claims" in sidebar (or navigate to claims sub-section) | Claims page with table and filters |
| 5.7 | Test claim filter | Change status filter dropdown | Table filters |
| 5.8 | Open Defects | Click "Defects" in sidebar | Defects page loads |
| 5.9 | Verify defects table | Snapshot | Table with columns including severity, status |

---

### TEST 6: Inventory Lifecycle

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 6.1 | Open Spare Parts | Click "Inventory" then "Spare Parts" in sidebar | Spare parts table |
| 6.2 | Verify stock levels | Snapshot | Stock Level column shows real numbers (25, 12, 4) with colored dots + progress bars — NOT "1" for everything |
| 6.3 | Click a spare part | Click on any row | Detail page: part info, stock levels |
| 6.4 | Test search | Go back, type a part name in search bar | Table filters by search term |
| 6.5 | Test category filter | Select a category from dropdown | Table filters by category |
| 6.6 | Open Purchase Requests | Click "Purchase Requests" in sidebar | Purchase requests table |
| 6.7 | Test status filter | Change status filter | Should include: Draft, Submitted, Approved, Rejected, Ordered, Partially Received, Received, Cancelled |
| 6.8 | Open Reorder Alerts | Click "Reorder Alerts" in sidebar | Alerts page with cards OR "All Clear" message |
| 6.9 | Verify alert data | If alerts exist, snapshot | Each alert should show: part name (NOT UUID), warehouse name (NOT UUID), current stock, reorder point |
| 6.10 | Test acknowledge | If unacknowledged alert exists, click "Acknowledge" | Alert gets "Acknowledged" badge, no error |
| 6.11 | Open Stock Levels | Click "Stock Levels" in sidebar | Stock Level Overview page loads |
| 6.12 | Open Warehouses | Click "Warehouses" in sidebar | Warehouses page loads with warehouse cards (name, capacity, status) |

---

### TEST 7: Lease Lifecycle

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

#### Part A — Create and Activate a Lease

| # | Action | How | Expected |
|---|--------|-----|----------|
| 7.1 | Open Leases | Click "Leases" under Property Ops in sidebar | Lease list page with existing leases |
| 7.2 | Click Create Lease | Click "Create Lease" button | Lease creation form |
| 7.3 | Select Unit | Select a unit from dropdown | Unit selected |
| 7.4 | Select Resident | Select a resident from dropdown | Resident selected |
| 7.5 | Select Type | Select "Residential" from Type dropdown | Type selected |
| 7.6 | Set dates | Start = today, End = 1 year from now | Dates filled |
| 7.7 | Set rent | Monthly Rent = 5000, Security Deposit = 10000 | Amounts filled |
| 7.8 | Submit | Click "Create Lease" | Redirects. Lease created with status "draft" |
| 7.9 | Activate | On lease detail, click "Activate" | Confirmation modal |
| 7.10 | Confirm | Click "Confirm" | Status changes to "active" |

#### Part B — Move-In Wizard

| # | Action | How | Expected |
|---|--------|-----|----------|
| 7.11 | Open Move-In | Click "Move-In" under Property Ops in sidebar | Move-In Wizard with 5-step stepper |
| 7.12 | Step 1: Select lease | Select the active lease from dropdown | Lease selected, unit + resident info shown |
| 7.13 | Click Next | Click "Next" button | Step 2: Checklist |
| 7.14 | Step 2: Review items | Snapshot — verify room items with condition dropdowns | Checklist items visible. Conditions should include: Excellent, Good, Fair, Poor, Damaged |
| 7.15 | Change a condition | Change one item's condition dropdown | Value updates |
| 7.16 | Click Next | Click "Next" | Step 3: Key Handover |
| 7.17 | Step 3: Fill key | Verify key type dropdown has: Unit Key, Mailbox Key, etc. Fill key number | Key info filled |
| 7.18 | Click Next | Click "Next" | Step 4: Meter Readings |
| 7.19 | Step 4: Fill readings | Enter values for Electric, Water, Gas | Readings filled |
| 7.20 | Click Next | Click "Next" | Step 5: Review & Complete |
| 7.21 | Step 5: Review | Snapshot — verify summary shows lease, checklist count, keys, meters | All data visible |
| 7.22 | Complete | Click "Complete Move-In" | Success screen: "Move-In Process Completed" with "Start New Move-In" button |

#### Part C — Move-Out Wizard

| # | Action | How | Expected |
|---|--------|-----|----------|
| 7.23 | Open Move-Out | Click "Move-Out" under Property Ops in sidebar | Move-Out Wizard with 7-step stepper |
| 7.24 | Step 1: Select lease | Select the same active lease | Lease selected with security deposit shown |
| 7.25 | Click Next | Click "Next" | Step 2: Condition Comparison |
| 7.26 | Step 2: Compare | Snapshot — table with Move-In vs Move-Out condition columns | Items visible with dropdowns for move-out condition |
| 7.27 | Change conditions | Change a few move-out conditions to "Fair" or "Poor" | Values update |
| 7.28 | Click Next | Click "Next" | Step 3: Damage Assessment |
| 7.29 | Step 3: Add damage | Click "Add Damage", fill description + room + cost | Damage added |
| 7.30 | Click Next | Click "Next" | Step 4: Deposit Calculation |
| 7.31 | Step 4: Verify | Snapshot — shows Security Deposit minus damages minus outstanding = refund | Calculations correct, refund amount shown |
| 7.32 | Click Next | Click "Next" | Step 5: Key Return |
| 7.33 | Step 5: Return keys | Click checkboxes to mark keys as returned | Keys checked |
| 7.34 | Click Next | Click "Next" | Step 6: Final Meters |
| 7.35 | Step 6: Fill readings | Enter final meter readings | Readings filled |
| 7.36 | Click Next | Click "Next" | Step 7: Review & Complete |
| 7.37 | Complete | Click "Complete Move-Out" | Success screen with deposit refund amount and "Start New Move-Out" button |

#### Part D — Verify Other Property Ops Pages

| # | Action | How | Expected |
|---|--------|-----|----------|
| 7.38 | Open Occupancy | Click "Occupancy" under Property Ops | Occupancy dashboard loads with KPI cards (Overall Occupancy %, Total Units, Occupied, Vacant) and building bars |
| 7.39 | Open Key Register | Click "Key Register" under Property Ops | Key register table loads. Key Type filter should show: Unit Key, Mailbox Key, Access Card, Garage Remote, Key Fob |

---

### TEST 8: RBAC (Role-Based Access Control)

#### Test A — Resident Sees Limited Sidebar

**Logout, login as:** `resident@facilityplatform.dev` / `Tech@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 8.1 | Verify sidebar | Snapshot after login | ONLY visible: Dashboard, Documents (Document Library), Resident Portal (Resident Home, My Requests, Bookings, Visitors, Announcements, My Profile) |
| 8.2 | Verify hidden sections | Confirm NOT visible: Admin, Settings, Vendors, Inventory, Property Ops, Portfolio, Assets, Maintenance | None of these should appear |

#### Test B — Technician Sees Operations Only

**Logout, login as:** `tech@facilityplatform.dev` / `Tech@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 8.3 | Verify sidebar | Snapshot | Should see: Dashboard, Operations (Maintenance, Inspections, Warranties), Documents |
| 8.4 | Verify hidden | NOT visible: Admin, Settings, Vendors, Inventory, Property Ops, Resident Portal | None visible |

#### Test C — Manager Sees Most Sections

**Logout, login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 8.5 | Verify sidebar | Snapshot | Dashboard, Property Management, Operations, Resources, Property Ops, Documents, Portfolio |
| 8.6 | Verify hidden | NOT visible: Admin, Settings, Resident Portal | None visible |

#### Test D — Super Admin Sees Everything

**Logout, login as:** `testadmin@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 8.7 | Verify sidebar | Snapshot | ALL sections visible including Admin (Dashboard, Tenants, Users, Roles, Settings, Audit Logs) |
| 8.8 | Open Admin Users | Click Admin > Users | Users management page with user list and "Create User" button |
| 8.9 | Verify user list | Snapshot | Shows users with names, emails, roles |

---

### TEST 9: Notifications

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 9.1 | Check bell icon | Snapshot header area | Bell icon visible (may have count badge) |
| 9.2 | Click bell | Click the bell icon | Notification dropdown or page opens |

---

### TEST 10: SLA Breach & Escalation

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 10.1 | Open work order detail | Click Maintenance > Work Orders, click any WO | Detail page loads |
| 10.2 | Check SLA section | Scroll to SLA Performance section | Two cards: "Response Time" and "Resolution Time" with values or dashes |
| 10.3 | Open SLA Dashboard | Click "SLA Dashboard" in sidebar under Operations | SLA Dashboard loads with KPI cards: Compliance Rate, Total Work Orders, SLA Met, SLA Breached |
| 10.4 | Verify data | Snapshot | Numbers should be reasonable (not all zeros unless no data) |

---

### TEST 11: Facility Booking & Visitors

**Logout, login as:** `resident@facilityplatform.dev` / `Tech@12345`

#### Part A — Book a Facility

| # | Action | How | Expected |
|---|--------|-----|----------|
| 11.1 | Open Bookings | Click "Bookings" in sidebar | "Available Resources" tab with facility cards (Fitness Center, Gym, Conference Room, etc.) |
| 11.2 | Click Book Now | Click "Book Now" on any facility (e.g., Gym) | Booking modal opens with title "Book [Facility Name]" |
| 11.3 | Select date | Pick a date 2+ days from now | Date selected |
| 11.4 | Verify time slots | Snapshot | Hourly slots like "09:00 - 10:00", "10:00 - 11:00" should appear. NOT empty |
| 11.5 | Select time slot | Click on a time slot | Slot highlighted with accent color |
| 11.6 | Enter purpose | Type "Team meeting" | Purpose filled |
| 11.7 | Confirm | Click "Confirm Booking" | Modal closes |
| 11.8 | Check My Bookings | Click "My Bookings" tab | New booking appears with "Pending" or "Confirmed" status and "Cancel" button |
| 11.9 | Cancel booking | Click "Cancel" on the booking | Status changes to "Cancelled" |

#### Part B — Visitor Passes

| # | Action | How | Expected |
|---|--------|-----|----------|
| 11.10 | Open Visitors | Click "Visitors" in sidebar | Visitor Passes page with Active and Past tabs |
| 11.11 | Click Create Pass | Click "Create Pass" button | Modal: Visitor Name, Visit Date, Purpose |
| 11.12 | Fill form | Name = "John Smith", Date = tomorrow, Purpose = "Personal Visit" | Form filled |
| 11.13 | Submit | Click "Create Pass" in modal | Pass created, appears in Active tab |
| 11.14 | View code | Click "View Code" button on the pass | Modal shows a large pass code (e.g., "VP-003" or "7CG8SL") — NOT "N/A" |
| 11.15 | Verify details | Snapshot | Visitor name and date shown below the code |
| 11.16 | Close | Click "Close" | Modal closes |

---

### TEST 12: Documents & Announcements

#### Part A — Announcements (Resident)

**Login as:** `resident@facilityplatform.dev` / `Tech@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 12.1 | Open Announcements | Click "Announcements" in sidebar | Announcement cards visible |
| 12.2 | Verify card content | Snapshot | Each card: title, content, priority badge (normal/high/urgent), date |
| 12.3 | Check author | Look for "By [Name]" | Should show author name (e.g., "By Sarah Chen") — NOT blank |
| 12.4 | Find unacknowledged | Look for announcement without green "Acknowledged" badge | Found one |
| 12.5 | Acknowledge | Click "Acknowledge" button | Green "Acknowledged" badge appears |
| 12.6 | Refresh & verify | Refresh the page | Acknowledged state persists |

#### Part B — Document Library (Manager)

**Logout, login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 12.7 | Open Documents | Click "Document Library" in sidebar | Page with category sidebar on left, document table on right, search bar, "Upload Document" button |
| 12.8 | Click a category | Click any category in left sidebar | Documents filter by that category |
| 12.9 | Click All Documents | Click "All Documents" | Shows all documents again |
| 12.10 | Search | Type a document name in search bar | Table filters by search |
| 12.11 | Upload flow | Click "Upload Document" | Upload page loads with file picker, category dropdown, tags input |

---

### TEST 13: Assets Deep Dive

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 13.1 | Open Assets | Click "Assets" in sidebar | Asset list with table |
| 13.2 | Test building filter | Select a building from filter dropdown | Table filters. No error |
| 13.3 | Test category filter | Select a category from filter dropdown | Table filters |
| 13.4 | Test status filter | Select a status (Active, Inactive, etc.) | Table filters |
| 13.5 | Click an asset | Click on any asset row | Detail page loads |
| 13.6 | Verify detail | Snapshot | Should show: name, code, category name (NOT UUID), building name (NOT UUID), status, condition, manufacturer, model |
| 13.7 | Check status actions | Look for status transition buttons | Buttons appropriate to current status |
| 13.8 | Open Asset Categories | Navigate to asset categories page | Categories tree visible |
| 13.9 | Create category | Fill name + code, click save | Category created. Should use `parent_id` not `parentId` |

---

### TEST 14: Vendors

**Login as:** `manager@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 14.1 | Open Vendors | Click "Vendors" in sidebar | Vendor list with table |
| 14.2 | Click a vendor | Click on any vendor row | Vendor detail page |
| 14.3 | Open Contracts | Click "Vendor Contracts" in sidebar | Contracts table with columns: Contract #, Vendor, Title, Status, Value, Start, End |
| 14.4 | Verify vendor name | Snapshot | Vendor column should show company name (NOT UUID or blank) |
| 14.5 | Open Performance | Click "Vendor Performance" in sidebar | Performance dashboard loads without errors |

---

### TEST 15: Admin Functions (Super Admin)

**Logout, login as:** `testadmin@facilityplatform.dev` / `Admin@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 15.1 | Open Admin Users | Click Admin > Users in sidebar | User list table |
| 15.2 | Verify user data | Snapshot | Shows first name, last name, email, roles for each user |
| 15.3 | Open Roles | Click Admin > Roles | Roles page with role list |
| 15.4 | Open Tenants | Click Admin > Tenants | Tenants page |
| 15.5 | Open Audit Logs | Click Admin > Audit Logs | Audit logs page |
| 15.6 | Open Settings | Click Admin > Settings | Settings page |

---

### TEST 16: Resident Profile

**Logout, login as:** `resident@facilityplatform.dev` / `Tech@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 16.1 | Open Profile | Click "My Profile" in sidebar | Profile page with Personal Information form |
| 16.2 | Verify fields | Snapshot | Fields: First Name, Last Name, Email, Phone, Emergency Contact Name, Emergency Contact Phone |
| 16.3 | Verify pre-filled | Check that first name and last name are pre-filled from API | Names should show (not blank) |
| 16.4 | Edit phone | Change phone to "0501234567" | Phone updated in form |
| 16.5 | Save | Click "Save Profile" | Success message "Profile updated successfully" appears |
| 16.6 | Refresh & verify | Refresh the page | Phone value persists as "0501234567" |
| 16.7 | Notification prefs | Scroll to Notification Preferences section | Table with Email/SMS/Push toggle per event type |
| 16.8 | Toggle a pref | Toggle one notification preference | Value changes |

---

### TEST 17: Resident Dashboard

**Login as:** `resident@facilityplatform.dev` / `Tech@12345`

| # | Action | How | Expected |
|---|--------|-----|----------|
| 17.1 | Open Dashboard | Click "Resident Home" in sidebar | Resident dashboard |
| 17.2 | Verify unit info | Snapshot | Unit info banner shows unit name, floor, building (or "No unit assigned" message) |
| 17.3 | Verify stats | Check stat cards | Open Requests, Upcoming Bookings, Unread Announcements, Active Passes — all show numbers |
| 17.4 | Verify requests | Check Active Service Requests section | Shows recent requests with titles and status badges |
| 17.5 | Verify announcements | Check Recent Announcements section | Shows announcement cards with titles |
| 17.6 | Test quick actions | Click "Submit Request" button | Navigates to request creation form |

---

### POST-TEST: Verify All Fixed Pages Load Without Errors

After completing all workflow tests, do a rapid smoke test — visit each major page and take a snapshot to verify it loads without JavaScript errors:

| Page | Path (click through sidebar) |
|------|-----|
| Dashboard | Dashboard |
| Properties | Portfolio > Properties |
| Buildings | Portfolio > Buildings |
| Units | Portfolio > Units |
| Floors | Portfolio > Floors |
| Work Orders | Maintenance > Work Orders |
| Work Requests | Maintenance > Work Requests |
| PM Schedules | Maintenance > PM Schedules |
| SLA Dashboard | Maintenance > SLA Dashboard |
| Inspection Templates | Inspections > Templates |
| Scheduled Inspections | Inspections > Scheduled |
| Spare Parts | Inventory > Spare Parts |
| Purchase Requests | Inventory > Purchase Requests |
| Stock Levels | Inventory > Stock Levels |
| Warehouses | Inventory > Warehouses |
| Reorder Alerts | Inventory > Reorder Alerts |
| Warranties | Warranties |
| Warranty Claims | Warranties > Claims |
| Defects | Warranties > Defects |
| Leases | Property Ops > Leases |
| Move-In | Property Ops > Move-In |
| Move-Out | Property Ops > Move-Out |
| Occupancy | Property Ops > Occupancy |
| Key Register | Property Ops > Key Register |
| Vendors | Vendors |
| Vendor Contracts | Vendors > Contracts |
| Vendor Performance | Vendors > Performance |
| Assets | Assets |
| Document Library | Documents |
| Admin Users | Admin > Users (super_admin) |
| Admin Roles | Admin > Roles (super_admin) |

For each page: take snapshot, verify content loads (not empty/error), move to next.

---

## Key Technical Notes

- The API uses `ValidationPipe` with `whitelist: true` and `forbidNonWhitelisted: true` — any extra field in a POST/PATCH body causes a 400 error.
- Prisma models use snake_case. The API returns snake_case. The frontend interfaces now match.
- The `@TenantId()` decorator extracts tenant from JWT. The `@CurrentUser('userId')` extracts user ID.
- Role assignment is a separate `POST /users/:id/roles` call with `{ roleId: "<uuid>" }`.
- The `residents` table is separate from `users`. A user with role "resident" needs a corresponding `residents` record AND a `resident_units` assignment.
- The `ResidentUnit` model has NO relation to `Unit` in Prisma schema — must do manual lookups.
- Inspection execution loads template sections client-side.
- The API global prefix is `/api/v1/` — all frontend calls go through `api.ts` which prepends this automatically.
- Playwright MCP is configured to use Google Chrome via `--browser chrome`.

---

## Files Modified in Session 2

### Frontend (40+ files, hot-reload):
```
apps/web/src/app/(dashboard)/property-ops/move-in/page.tsx
apps/web/src/app/(dashboard)/property-ops/move-out/page.tsx
apps/web/src/app/(dashboard)/property-ops/occupancy/page.tsx
apps/web/src/app/(dashboard)/property-ops/keys/page.tsx
apps/web/src/app/(dashboard)/property-ops/leases/create/page.tsx
apps/web/src/app/(dashboard)/assets/page.tsx
apps/web/src/app/(dashboard)/assets/create/page.tsx
apps/web/src/app/(dashboard)/assets/[id]/page.tsx
apps/web/src/app/(dashboard)/assets/[id]/transfer/page.tsx
apps/web/src/app/(dashboard)/assets/categories/page.tsx
apps/web/src/app/(dashboard)/inventory/warehouses/page.tsx
apps/web/src/app/(dashboard)/inventory/alerts/page.tsx
apps/web/src/app/(dashboard)/inventory/purchase-requests/[id]/page.tsx
apps/web/src/app/(dashboard)/inventory/purchase-requests/page.tsx
apps/web/src/app/(dashboard)/resident/visitors/page.tsx
apps/web/src/app/(dashboard)/resident/profile/page.tsx
apps/web/src/app/(dashboard)/resident/bookings/page.tsx
apps/web/src/app/(dashboard)/resident/announcements/page.tsx
apps/web/src/app/(dashboard)/documents/page.tsx
apps/web/src/app/(dashboard)/documents/upload/page.tsx
apps/web/src/app/(dashboard)/warranties/page.tsx
apps/web/src/app/(dashboard)/warranties/claims/[id]/page.tsx
apps/web/src/app/(dashboard)/maintenance/sla/page.tsx
apps/web/src/app/(dashboard)/maintenance/pm-schedules/create/page.tsx
apps/web/src/app/(dashboard)/settings/notifications/page.tsx
apps/web/src/app/(dashboard)/vendors/contracts/page.tsx
apps/web/src/app/(dashboard)/vendors/contracts/create/page.tsx
apps/web/src/app/(dashboard)/vendors/performance/page.tsx
apps/web/src/app/(dashboard)/portfolio/page.tsx
apps/web/src/app/(dashboard)/portfolio/properties/page.tsx
apps/web/src/app/(dashboard)/portfolio/properties/create/page.tsx
apps/web/src/app/(dashboard)/portfolio/buildings/page.tsx
apps/web/src/app/(dashboard)/portfolio/buildings/create/page.tsx
apps/web/src/app/(dashboard)/portfolio/units/page.tsx
apps/web/src/app/(dashboard)/portfolio/floors/page.tsx
apps/web/src/app/(dashboard)/admin/users/page.tsx
```

### Backend (requires rebuild + restart):
```
apps/api/src/asset/asset.service.ts
apps/api/src/property-ops/lease.service.ts
apps/api/src/property-ops/occupancy.service.ts
apps/api/src/inventory/reorder-alert.service.ts
apps/api/src/inventory/reorder-alert.controller.ts
apps/api/src/resident/resident-portal.controller.ts
apps/api/src/resident/resident-portal.service.ts
```

---

*This document was updated after Session 2 code sweep. All Phase 1 fixes are applied. Ready for Phase 2 Playwright UI testing.*
