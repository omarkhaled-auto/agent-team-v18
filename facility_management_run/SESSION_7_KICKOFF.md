# SESSION 7 KICKOFF PROMPT

Copy everything below this line and paste it as your first message to Claude Code:

---

Read C:\Projects\ArkanPM\SESSION_6_HANDOFF.md completely before doing anything. Then read C:\Projects\ArkanPM\PLAYWRIGHT_TESTING_MASTER_PLAN.md for the full test plan and absolute rules.

This is Session 7 of comprehensive Playwright UI testing for a NestJS + Prisma + Next.js facility management platform. Sessions 5-6 completed 30 of 33 test suites. You have 3 remaining suites + a final smoke test + 7 known bugs to fix.

---

## YOUR MISSION

Complete ALL remaining work in this order:

1. **Fix the 7 known bugs** documented in SESSION_6_HANDOFF.md (Known Bugs section)
2. **Execute Suite 5** — Move-Out Wizard 7-Step Flow
3. **Execute Suite 12** — Owner Portal
4. **Execute Final Smoke Test** — All Pages Load (4-5 roles, 67+ pages)
5. **Produce a final report** summarizing all 33 suites

---

## ABSOLUTE RULES — ZERO EXCEPTIONS

1. **NEVER type a URL into the browser** except `http://localhost:4201/login` to reach the login page.
2. **NEVER call any API endpoint directly** — no `fetch()`, no `curl`, no Playwright `request.post()`.
3. **NEVER insert into the database** — no Prisma scripts, no SQL, no seed commands.
4. **NEVER use `browser_evaluate()`** to inject JavaScript, manipulate state, or bypass UI.
5. **ALL actions through UI only** — click sidebar links, click buttons, fill inputs, select dropdowns.
6. **ALL verification through snapshots** — `browser_snapshot()` to read what's on screen.
7. **If something doesn't work, THAT IS A BUG** — fix the code, then re-test. Never skip.
8. **Take `browser_snapshot()` after EVERY major action** to verify the result visually.
9. **After backend code changes:** kill node process, rebuild API, restart. See Build Process Notes in handoff.
10. **After frontend code changes:** hot-reload handles it, just refresh the browser page.

## CRITICAL DATA QUALITY RULES

11. **"0" IS NOT A PASS.** If a field shows $0, 0%, 0 items, or any zero value where real data should exist, THAT IS A BUG. Investigate and fix it.
12. **"-" IS NOT A PASS.** If a field shows "-", "N/A", blank, or empty where real data should exist, THAT IS A BUG. Investigate and fix it.
13. **UUIDs ARE NOT A PASS.** If you see a UUID (e.g., `95247720-aed7-4eff-b9e4-ab40ce2dab39`) where a human-readable name should be, THAT IS A BUG. Fix it.
14. **"undefined" IS NOT A PASS.** If any field shows "undefined", "null", or "[object Object]", THAT IS A BUG.
15. **Real data must appear.** When verifying a page, every field must show meaningful, correct data. A page that loads but shows all zeros or all blanks is FAILING, not passing.
16. **Cross-check calculations.** If a form calculates totals, verify the math is correct. If a deposit is $11,000 and damages are $500, the refund should be $10,500 — not $0.
17. **Verify after every create/update.** After creating or modifying data, navigate to the detail or list page and confirm the data persisted correctly with real values.

---

## ENVIRONMENT SETUP

Before starting any tests, verify the environment:

```bash
# Check Docker (PostgreSQL + Redis)
netstat -ano | findstr "5434"  # PostgreSQL
netstat -ano | findstr "6379"  # Redis

# Check API
netstat -ano | findstr "3000"  # API

# Check Frontend
netstat -ano | findstr "4201"  # Frontend
```

If any service is not running, start it:
```bash
docker-compose up -d                          # PostgreSQL + Redis
pnpm -w run build:api && node apps/api/dist/main.js &  # API
cd apps/web && npx next dev --port 4201 &     # Frontend
```

## BUILD PROCESS (CRITICAL — READ THIS)

The Prisma client must exist in TWO locations. After any schema change:
```bash
# 1. Generate Prisma client
cd apps/api && npx prisma generate

# 2. Kill API first (DLL lock)
taskkill //F //PID <api_pid>

# 3. Copy to runtime location
cp -r apps/api/node_modules/.prisma/client/* "node_modules/.pnpm/@prisma+client@6.19.2_prisma@6.19.2_typescript@5.9.3__typescript@5.9.3/node_modules/.prisma/client/"

# 4. Compile (ignore ~7 pre-existing TS errors — JS emits fine)
cd apps/api && npx tsc --noEmit false --outDir dist --rootDir src --declaration false --removeComments true --incremental true --esModuleInterop true --moduleResolution node --module commonjs --target ES2021

# 5. Restart API
node apps/api/dist/main.js &
```

Alternatively, if NX cache is intact: `pnpm -w run build:api` works.

---

## TEST ACCOUNTS

| Role | Email | Password |
|------|-------|----------|
| Super Admin | testadmin@facilityplatform.dev | Admin@12345 |
| Facility Manager | manager@facilityplatform.dev | Admin@12345 |
| Maintenance Tech | tech@facilityplatform.dev | Tech@12345 |
| Inspector | inspector@facilityplatform.dev | Tech@12345 |
| Resident | resident@facilityplatform.dev | Tech@12345 |

## LOGIN PROCEDURE (react-hook-form compatible)

```
1. browser_navigate('http://localhost:4201/login')
2. Wait 2 seconds for full page load
3. browser_snapshot() — verify form visible
4. browser_click(email field ref)
5. browser_type(email, slowly: true)
6. browser_click(password field ref)
7. browser_type(password, slowly: true)
8. browser_click(Sign in button ref)
9. Wait for redirect to /dashboard
10. browser_snapshot() — verify logged in with correct user name
```

If login stops working: `browser_close()` then re-navigate to /login. This fixes stuck browser contexts.

HTML date inputs (type="date") require `browser_fill_form` tool, NOT `browser_type` with pressSequentially.

---

## PHASE 1: FIX THE 7 KNOWN BUGS

Before running any test suites, fix these bugs from Session 6. Each fix must be verified through the UI.

### Bug 1 — `/admin/users` Sidebar Navigation Broken
All sidebar clicks fail on `/admin/users`. Investigate the page source — likely heavy combobox DOM elements breaking Next.js router. Fix or implement a workaround in the component.

### Bug 2 — Purchase Request Detail: Line Items Show "-"
File: `apps/web/src/app/(dashboard)/inventory/purchase-requests/[id]/page.tsx`
The detail page reads items from JSON but field names don't match. The create sends `part_number`, `part_name`, `quantity`, `unit_cost`. Fix the detail page to read these exact field names.

### Bug 3 — Purchase Request "Mark as Received" Needs Receive Form
The `/purchase-requests/{id}/receive` endpoint requires `received_items` array. The UI sends empty body. Either simplify the backend to accept a basic receive action, or add a receive confirmation dialog.

### Bug 4 — Vendor Category Shows "-" on Detail Page
Vendor create dropdown sends category NAME but backend expects `category_id` UUID. Fix the frontend to resolve category name to UUID before sending, using the vendor categories API.

### Bug 5 — Vendor Category Column Blank on List (Seed Data)
Seed vendors lack `category_id`. Update seed data or fix via Bug 4's resolution.

### Bug 6 — Purchase Request Items Count Shows "0 items"
The `items` JSON column data isn't being counted correctly. Verify the JSON structure in the database and fix the frontend count logic.

### Bug 7 — Defect Category Not Linked
Defect create sends category name in metadata but backend needs `category_id`. Fix similar to Bug 4 — resolve name to UUID using the defect categories API.

**After fixing bugs:** Rebuild API, restart, and verify each fix through the browser.

---

## PHASE 2: EXECUTE REMAINING TEST SUITES

### Suite 5 — Move-Out Wizard 7-Step Flow (Manager)

Login as Manager. Navigate to Move-Out via sidebar.

**Steps:**
1. Select lease LSE-2024-001 (or any active lease with completed move-in)
2. Step through ALL 7 wizard steps:
   - Step 1: General Info — set move-out date, select reason
   - Step 2: Room Conditions — set condition for each room via dropdowns (NOT all "Good" — test variety)
   - Step 3: Damage Assessment — ADD at least 2 damage items with costs, verify totals calculate
   - Step 4: Deposit Calculation — verify deposit math (original deposit - damages = refund). **$0 refund when there's a deposit is a BUG**
   - Step 5: Keys Checklist — mark keys as returned
   - Step 6: Meter Readings — enter final readings for each meter
   - Step 7: Review Summary — **EVERY piece of data from steps 1-6 must appear here. Blanks or zeros where data was entered = BUG**
3. Complete the wizard
4. Verify the move-out record was created with all data

### Suite 12 — Owner Portal (Super Admin -> Owner)

1. Login as Super Admin
2. Navigate to Admin Users (use direct navigation if sidebar bug isn't fixed)
3. Create a new user with: email `owner@facilityplatform.dev`, password `Owner@12345`, role `owner`, name `Khalid Al Mansoori`
4. Navigate to Owners page, create an owner record linked to this user
5. Logout, login as the new owner
6. Verify owner sidebar shows ONLY: Owner Home, My Units, My Documents, My Profile
7. Visit each owner page — verify they load with meaningful content (not blank)

### Final Smoke Test — All Pages Load (4-5 Roles)

For EACH role (Manager, Super Admin, Resident, Technician, Owner if created):
1. Login as that role
2. Click every sidebar link one by one
3. `browser_snapshot()` after each navigation
4. Verify: page loads (no crash), no UUIDs where names should be, no blank screens
5. Document any failures

**Page counts:** Manager=34, Super Admin=9, Resident=7, Technician=13, Owner=4

---

## PHASE 3: FINAL REPORT

After all tests complete, create `C:\Projects\ArkanPM\FINAL_TEST_REPORT.md` with:

1. **Overall Results:** X/33 suites passed, X bugs fixed, X remaining issues
2. **Per-Suite Results Table:** Suite #, Name, Session, Result, Notes
3. **Bugs Fixed This Session:** What was broken, what was changed, file paths
4. **Remaining Issues:** Anything that still doesn't work perfectly
5. **Data Quality Verification:** Confirm NO pages show UUIDs, $0 where real values exist, or blank fields for populated data
6. **Recommendations:** Any architectural improvements needed

---

## SUCCESS CRITERIA

The session is successful when:
- [ ] All 7 known bugs are fixed and verified through UI
- [ ] Suite 5 (Move-Out Wizard) passes with correct calculations and no zero/blank data
- [ ] Suite 12 (Owner Portal) passes with owner-specific sidebar and working pages
- [ ] Final Smoke Test passes — all 67+ pages load across all roles without crashes or UUID display
- [ ] No page anywhere in the app shows UUIDs, "undefined", "$0" (where real data exists), or blank fields for populated records
- [ ] Final report is produced at FINAL_TEST_REPORT.md

Execute Phase 1 first (bug fixes). Then Phase 2 (remaining suites). Then Phase 3 (report). Do not skip phases.
