# SESSION 4 KICKOFF PROMPT

Copy everything below and paste it as the first message to a new Claude Code session.

---

Read these documents carefully and thoroughly before doing anything:

1. C:\Projects\ArkanPM\TESTING_SESSION_3_HANDOFF.md
2. C:\Projects\ArkanPM\ArkanPM_Testing_Guide.md

Your job is to execute all 12 remaining UI tests (Tests A through L) described in the Session 3 handoff document. Use the Playwright MCP server (configured with Google Chrome) to test every single workflow.

## THE #1 RULE — ABSOLUTELY NON-NEGOTIABLE

EVERYTHING must be done through the UI only. You interact with the app exactly like a real user would — clicking buttons, filling input fields, selecting dropdowns, clicking sidebar links. That's it.

- If you can't find a button or link to perform an action → THAT IS A BUG. Fix it by adding the missing button/link to the code.
- If you can't find an input field to enter data → THAT IS A BUG. Fix it by adding the missing field.
- If a page returns a 404 or blank screen → THAT IS A BUG. Fix it by creating the page or fixing the route.
- If a dropdown has no options when it should → THAT IS A BUG. Fix the data loading.
- If a table shows UUIDs instead of names → THAT IS A BUG. Fix the API to return names.
- If a form submits but nothing happens or shows an error → THAT IS A BUG. Fix the endpoint or payload.
- If data you just created doesn't appear in a list → THAT IS A BUG. Fix it.
- If a modal does NOT open when its button is clicked → THAT IS A BUG. Read the page code, find the onClick handler, fix whatever is preventing the modal from opening.
- Every data point the user needs to see MUST be visible. Every action the user needs to take MUST have a clickable UI element.

## You are NOT allowed to

- Navigate by typing URLs in the browser (except the initial login page at http://localhost:4201/login)
- Insert data directly into the database
- Call API endpoints directly to work around UI issues
- Skip a broken page or broken modal — you MUST fix it first, then continue
- Assume something works without verifying it visually through Playwright snapshots
- Use `browser_evaluate()` or JavaScript injection to bypass UI interactions
- Use `fill()` for the login form — it does NOT work with react-hook-form. You MUST use `slowly: true` (which triggers `pressSequentially`)

## You ARE required to

- Take a `browser_snapshot()` after every major action to verify the result
- Log in using the exact login procedure described below (slowly typing into fields)
- Log in as the correct user role for each test (logout and re-login when switching)
- Rebuild the API after any backend code change: kill node → `pnpm -w run build:api` → restart `node dist/apps/api/src/main.js`
- Fix every issue you encounter before moving to the next test step
- Work through ALL 12 tests (A through L) in order

## LOGIN PROCEDURE (CRITICAL — follow exactly)

The login form uses `react-hook-form` with `register()`. Playwright's `fill()` does NOT trigger React's internal state updates. You MUST type slowly:

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

If step 8 times out, login failed. Do NOT try `fill()` or `browser_evaluate()` workarounds. Check that you used `slowly: true` for BOTH fields. If it still fails, try clearing localStorage first via `browser_evaluate(() => localStorage.clear())` and then redo the full login procedure.

## MODAL TESTING PROCEDURE (CRITICAL)

Many tests involve clicking a button that should open a modal. If a click does nothing:

1. Take a FRESH `browser_snapshot()` to get current refs
2. Click using the exact ref from the fresh snapshot
3. `browser_wait_for(time: 2)` — wait 2 seconds
4. `browser_snapshot()` — check if modal appeared
5. If still no modal, THAT IS A BUG. Read the page source code to find the onClick handler, trace the modal state, and fix whatever prevents it from opening.

## Environment

- Frontend: http://localhost:4201 (Next.js dev server)
- API: port 3000 (Node.js)
- Check if API is running: `netstat -ano | grep ":3000.*LISTENING"`
- Check if frontend is running: `netstat -ano | grep ":4201.*LISTENING"`
- Start API if not running: `node dist/apps/api/src/main.js` (from project root C:\Projects\ArkanPM)
- Start frontend if not running: `cd apps/web && npx next dev --port 4201`
- After backend code changes: kill node, `pnpm -w run build:api`, restart node
- After frontend code changes: hot-reload handles it, just refresh the browser

## Accounts

| Role | Email | Password |
|------|-------|----------|
| Facility Manager | manager@facilityplatform.dev | Admin@12345 |
| Resident | resident@facilityplatform.dev | Tech@12345 |
| Super Admin | testadmin@facilityplatform.dev | Admin@12345 |

## The 12 Tests to Execute

### TEST A: Book a Facility (Resident)
Login as resident. Click "Bookings" in sidebar. Click "Book Now" on Fitness Center. Modal must open. Select a date 2+ days from now. Verify time slots appear. Select a slot. Type purpose "Team meeting". Click "Confirm Booking". Click "My Bookings" tab. Verify booking appears. Click "Cancel" on it. Verify status changes to "Cancelled".

### TEST B: Create Visitor Pass (Resident)
Login as resident. Click "Visitors" in sidebar. Click "Create Pass" button. Modal must open. Fill: Name = "John Doe", Date = tomorrow, Purpose = "Personal Visit". Click "Create Pass" in modal. Verify new pass appears in Active tab.

### TEST C: View Visitor Pass Code (Resident)
On Visitors page, click "View Code" on any pass. Modal must open showing a large pass code (NOT "N/A"). Verify visitor name and date below the code. Close the modal.

### TEST D: Acknowledge Announcement (Resident)
Login as resident. Click "Announcements" in sidebar. Find an announcement without "Acknowledged" badge. Click "Acknowledge". Green badge must appear. Refresh the page. Badge must persist.

### TEST E: Save Resident Profile (Resident)
Login as resident. Click "My Profile" in sidebar. Verify fields pre-filled (James, Wilson, email, phone). Clear the phone field. Type "0501234567". Click "Save Profile". Verify success message. Refresh page. Verify phone persisted as "0501234567".

### TEST F: Toggle Notification Preference (Resident)
On Profile page, scroll to Notification Preferences. Click any Email/SMS/Push toggle. Click "Save Preferences". Verify success.

### TEST G: Move-Out Wizard (Manager)
Login as manager. Click "Move-Out" in sidebar. Select lease "#LS-2026-00002 - Unit 201 (James Wilson)". Step through all 7 steps: Lease Select → Condition Comparison (change some to "Fair") → Damage Assessment (add a damage item) → Deposit Calculation (verify math) → Key Return (check boxes) → Final Meters (fill readings) → Review & Complete. Click "Complete Move-Out". Verify success screen with deposit refund amount.

### TEST H: Expand Floors (Manager)
Login as manager. Click "Floors & Zones" in sidebar. Click on "Tower A - Main" building name (NOT the "+ Floor" button). Building should expand showing floors. Verify floor names and levels appear.

### TEST I: Document Upload Form (Manager)
Login as manager. Click "Document Library" in sidebar. Click "Upload Document" button. Verify upload page loads with file picker, Category dropdown, Description field, Tags input.

### TEST J: Asset Detail Page (Manager)
Login as manager. Click "Assets" in sidebar. Click on any asset row. Verify detail page shows: name, asset code, category name (NOT UUID), status, condition. Check for status action buttons.

### TEST K: Work Request Detail (Resident)
Login as resident. Click "My Requests" in sidebar. Click on "Bathroom faucet leaking" row. Verify detail page shows: request number, title, status "Submitted", category "plumbing", description.

### TEST L: Quick Action Navigation (Resident)
Login as resident. Click "Resident Home" in sidebar. Click "Submit Request" quick action → verify navigates to request form. Go back. Click "Book Facility" → verify navigates to bookings page. Go back. Click "Create Visitor Pass" → verify navigates to visitors page.

## After All Tests

When all 12 tests pass, report a final summary:
- Which tests passed
- Which tests required code fixes (and what was fixed)
- Any remaining issues

If ALL 12 pass with no issues, the app is fully tested and ready.

Begin with TEST A — navigate to http://localhost:4201/login, log in as the resident, and start testing.
