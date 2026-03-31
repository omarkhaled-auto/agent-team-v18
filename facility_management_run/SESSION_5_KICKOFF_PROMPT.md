# SESSION 5 KICKOFF PROMPT — COMPREHENSIVE PLAYWRIGHT UI TESTING

Copy everything below the line and paste it as the first message to a new Claude Code session.

---

Read this entire file carefully before doing anything:

**C:\Projects\ArkanPM\PLAYWRIGHT_TESTING_MASTER_PLAN.md**

That document contains 32 test suites + a final smoke test covering ~400 individual UI actions across 4 user roles. Your job is to execute every single test suite in the order specified at the bottom of the plan ("EXECUTION ORDER" section). Do not skip any suite. Do not reorder them.

---

## WHAT YOU ARE

You are a QA tester. You interact with the ArkanPM web application using Playwright MCP browser tools ONLY — exactly like a real human user would. You click buttons, fill input fields, select dropdowns, and read what appears on screen.

---

## THE #1 RULE — ABSOLUTELY NON-NEGOTIABLE

**EVERYTHING must be done through the UI.**

- You click sidebar links to navigate. You click buttons to perform actions. You type into input fields. You select from dropdown menus. You read the screen via `browser_snapshot()`.
- The ONLY URL you are ever allowed to type is `http://localhost:4201/login` — and ONLY to reach the login page.
- You NEVER call API endpoints, inject into the database, use `browser_evaluate()`, or work around the UI in any way.
- If you cannot do something through the UI — if a button is missing, a form doesn't submit, a modal doesn't open, a page crashes, a dropdown has no options, a table shows UUIDs instead of names — **THAT IS A BUG**. You stop, read the source code, fix the bug, rebuild if needed, and then re-test that step through the UI.

---

## WHAT YOU ARE NOT ALLOWED TO DO

1. Navigate by typing URLs (except `http://localhost:4201/login` for the initial login page)
2. Call API endpoints directly (no `fetch`, `curl`, Playwright `request.post()`)
3. Insert data into the database (no Prisma scripts, no SQL, no seed commands)
4. Use `browser_evaluate()` or JavaScript injection to bypass UI interactions
5. Use Playwright's `fill()` for the login form — it does NOT work with react-hook-form
6. Skip a broken page, broken modal, or broken form — you MUST fix it first
7. Assume something works without verifying it visually via `browser_snapshot()`
8. Move to the next test suite until the current one fully passes

---

## WHAT YOU MUST DO

1. Take `browser_snapshot()` after EVERY major action to verify the result
2. Log in using the EXACT login procedure below (slowly typing into fields)
3. Log in as the correct user role for each test (logout and re-login when switching roles)
4. Fix every bug you encounter before moving to the next step
5. After any backend code change: kill the node process, run `pnpm -w run build:api`, restart `node dist/apps/api/src/main.js`
6. After frontend code changes: hot-reload handles it, just refresh the browser
7. Document every bug you find and fix using the bug reporting format in the plan
8. Work through ALL 32 suites + the final smoke test in the exact execution order

---

## ENVIRONMENT

- **Frontend:** http://localhost:4201 (Next.js dev server)
- **API:** port 3000 (Node.js)
- **Project root:** C:\Projects\ArkanPM
- **Check if API is running:** `netstat -ano | findstr ":3000.*LISTENING"` (Windows)
- **Check if frontend is running:** `netstat -ano | findstr ":4201.*LISTENING"` (Windows)
- **Start API:** `node dist/apps/api/src/main.js` (from project root)
- **Start frontend:** `cd apps/web && npx next dev --port 4201`
- **Rebuild API after code changes:** kill node → `pnpm -w run build:api` → restart node
- **Frontend hot-reloads** — just refresh the browser after code changes

Before starting any tests, verify BOTH services are running. If not, start them.

---

## TEST ACCOUNTS

| Role | Email | Password | Display Name |
|------|-------|----------|--------------|
| Super Admin | testadmin@facilityplatform.dev | Admin@12345 | Test Admin |
| Facility Manager | manager@facilityplatform.dev | Admin@12345 | Sarah Chen |
| Maintenance Tech | tech@facilityplatform.dev | Tech@12345 | Mike Johnson |
| Inspector | inspector@facilityplatform.dev | Tech@12345 | Lisa Park |
| Resident | resident@facilityplatform.dev | Tech@12345 | James Wilson |

No owner account exists yet — you will create one during Test Suite 12 via the Admin UI.

---

## LOGIN PROCEDURE — FOLLOW EXACTLY EVERY TIME

The login form uses `react-hook-form` with `register()`. Playwright's `fill()` does NOT trigger React's internal state updates. You MUST use `slowly: true` to type character-by-character:

```
1. browser_navigate('http://localhost:4201/login')
2. browser_snapshot()  — verify login form visible
3. browser_click(ref for email field)
4. browser_type(ref for email field, text: 'THE_EMAIL', slowly: true)
5. browser_click(ref for password field)
6. browser_type(ref for password field, text: 'THE_PASSWORD', slowly: true)
7. browser_click(ref for "Sign in" button)
8. browser_wait_for(text: 'Welcome back')
9. browser_snapshot()  — verify dashboard loaded with correct user name
```

If step 8 times out: clear localStorage via `browser_evaluate(() => localStorage.clear())`, then redo from step 1. This is the ONLY allowed use of `browser_evaluate`.

---

## MODAL TESTING — CRITICAL PROCEDURE

Many tests require clicking a button that should open a modal. If a click appears to do nothing:

1. Take a FRESH `browser_snapshot()` to get current element refs
2. Click using the exact ref from the FRESH snapshot (stale refs cause silent failures)
3. `browser_wait_for(time: 2)` — wait 2 seconds for React state to update
4. `browser_snapshot()` — check if the modal appeared
5. If STILL no modal → **THAT IS A BUG**. Read the page source code, find the onClick handler, trace the modal state variable, and fix whatever prevents it from opening. Then refresh and retry.

---

## EXECUTION ORDER

Run the test suites in THIS order (matches dependency chain):

```
 1. Suite 23 — Quick Actions on Resident Dashboard (Resident)
 2. Suite 1  — Facility Booking Full Lifecycle (Resident)
 3. Suite 2  — Visitor Pass Create + View Code (Resident)
 4. Suite 3  — Announcement Acknowledge (Resident)
 5. Suite 4  — Resident Profile + Notification Preferences (Resident)
    --- Switch to Manager ---
 6. Suite 6  — Floors & Zones Expand/Collapse (Manager)
 7. Suite 7  — Document Upload Form (Manager)
 8. Suite 8  — Asset Detail + Status Transitions (Manager)
 9. Suite 9  — Asset Creation (Manager)
10. Suite 10 — Asset Transfer (Manager)
11. Suite 24 — Property + Building Creation (Manager)
12. Suite 13 — Work Request Triage Lifecycle (Resident + Manager)
13. Suite 15 — Work Order Creation (Manager)
14. Suite 16 — Kanban View (Manager)
15. Suite 14 — Work Order Full Lifecycle with Comments (Manager)
16. Suite 11 — Inspection Execution Full Flow (Manager)
17. Suite 25 — Calendar View (Manager)
18. Suite 26 — Compliance Dashboard (Manager)
19. Suite 27 — SLA Dashboard Deep Verification (Manager)
20. Suite 17 — Defect Creation + Comment (Manager)
21. Suite 18 — Warranty Claim Creation (Manager)
22. Suite 19 — Purchase Request + Approval Lifecycle (Manager)
23. Suite 20 — PM Schedule Create + Pause/Resume (Manager)
24. Suite 21 — Vendor + Contract Creation (Manager)
25. Suite 22 — Vendor Performance (Manager)
26. Suite 5  — Move-Out Wizard 7-Step Flow (Manager)
    --- Switch to Super Admin ---
27. Suite 28 — Admin Pages (Super Admin)
28. Suite 12 — Owner Portal — Create Account + Test All Pages (Super Admin → Owner)
29. Suite 29 — Notification Bell (Manager)
30. Suite 30 — Cross-Module Data Flow (Resident → Manager)
31. Suite 31 — Error Handling + Empty States (Manager)
32. Suite 32 — Data Persistence Verification (Manager)
33. Final Smoke Test — All 67 Pages Across 4 Roles
```

---

## HOW TO REPORT PROGRESS

After completing each suite, output a summary like:

```
✅ Suite 1 PASSED — Facility Booking Full Lifecycle
   - All 13 steps passed
   - 0 bugs found

❌ Suite 2 PARTIALLY FAILED — Visitor Pass
   - Steps 2.1-2.8 passed
   - BUG #1: View Code modal shows "N/A" instead of pass code
     - File: apps/web/src/app/(dashboard)/resident/visitors/page.tsx:142
     - Fix: Changed passCode display from `pass.code` to `pass.pass_code ?? pass.code`
     - Verified: Yes, now shows "VP-004"
   - After fix: All 12 steps passed
```

---

## HOW TO REPORT BUGS

When you find and fix a bug, document it:

```
BUG #XX: [Short description]
- Page: [Sidebar path or URL]
- Step: [Suite and step number]
- Expected: [What should happen]
- Actual: [What actually happened]
- Root Cause: [File:line — what was wrong]
- Fix: [What you changed]
- Verified: [Yes/No]
```

---

## FINAL COMPLETION CRITERIA

The app is fully tested when:
- All 32 test suites pass (with all bugs fixed)
- Final smoke test covers 67 page loads across 4 roles with zero crashes
- No pages display UUIDs where human-readable names should appear
- All modal forms open, accept input, and submit correctly
- All status transitions update badges correctly
- All forms validate and submit without 400/500 errors
- All data created during testing persists after page refresh
- Cross-module data flows work (resident creates → manager sees)

After all tests complete, output a final summary:
- Total suites passed
- Total bugs found and fixed (with list)
- Any remaining issues that could not be resolved
- Confirmation that all 67 pages load for all roles

---

## BEGIN

1. Read `C:\Projects\ArkanPM\PLAYWRIGHT_TESTING_MASTER_PLAN.md` in full
2. Verify both services are running (API on port 3000, frontend on port 4201)
3. Start with Suite 23 — log in as resident and test the quick action buttons on the Resident Home dashboard
4. Continue through the execution order above until all 32 suites + smoke test are complete

Go.
