# ArkanPM Testing Session 3 Handoff — Remaining UI Tests

**Created:** 2026-03-30
**Purpose:** Complete all UI tests that Session 3 could not fully verify via Playwright MCP. Every test below MUST be done through the browser UI only — clicking buttons, filling fields, selecting dropdowns. No API calls, no URL typing (except initial login), no database scripts.

---

## What Was Already Completed (Session 3)

Session 3 ran all 17 tests + post-test smoke and fixed 9 bugs. The following were fully confirmed:

- Login/logout for all 4 roles (manager, resident, technician, super admin)
- Full sidebar RBAC for all 4 roles
- Dashboard KPIs for manager and resident
- Work request creation by resident (form fill + submit + verify in list)
- Full work order lifecycle: Assigned → In Progress → Completed → Verified → Closed (with modals, notes, and status timeline)
- Preventive maintenance work order detail
- Inspection template list + schedule a new inspection
- Warranties, warranty claims, and defects pages with data
- Spare parts with real stock levels + search filter
- Purchase requests with resolved user names (was UUIDs, fixed)
- Reorder alert acknowledge
- Warehouses page (was crashing, fixed)
- Stock levels page
- Lease creation via form + lease activation via button
- Full move-in wizard (5 steps: lease select, checklist, key handover, meter readings, review + complete)
- Occupancy dashboard
- Key register with resolved names (was UUIDs, fixed)
- Vendor list, vendor contracts with names
- Vendor performance with names and ratings (was blank, fixed)
- SLA dashboard with metrics
- Facility bookings page loads with 4 facility cards
- Visitor passes page loads with 3 active passes
- Announcements page loads with 3 announcements, author names, priority badges
- Document library page loads with 3 documents
- Resident profile page loads with pre-filled data
- Resident dashboard with unit info, stats, requests, quick actions
- Admin users page with 7 users, roles, lock/edit
- Floors & Zones page (was crashing, fixed)
- Compliance dashboard (was crashing, fixed)
- All 31 pages load without errors

---

## What Was NOT Fully Tested

The items below were NOT confirmed because Playwright MCP button clicks did not trigger React modal state changes. The pages loaded correctly and the buttons exist, but the modal flows were never completed. **A real user clicking these buttons would likely see them work** — but we never confirmed it through Playwright.

Every test below must be done by a human-like click flow. If any modal does NOT open when its button is clicked, THAT IS A BUG — fix it before moving on.

---

## Environment

- **Frontend:** http://localhost:4201
- **API:** port 3000
- **Start API if not running:** `node dist/apps/api/src/main.js` (from project root)
- **Start frontend if not running:** `cd apps/web && npx next dev --port 4201`
- **Playwright MCP:** Configured with Google Chrome

## Accounts

| Role | Email | Password |
|------|-------|----------|
| Facility Manager | manager@facilityplatform.dev | Admin@12345 |
| Resident | resident@facilityplatform.dev | Tech@12345 |
| Super Admin | testadmin@facilityplatform.dev | Admin@12345 |

---

## CRITICAL RULES

1. **Navigate ONLY by clicking sidebar links and buttons.** The ONLY exception is `browser_navigate('http://localhost:4201/login')` to reach the initial login page.
2. **Login by clicking the email field, typing slowly (`slowly: true`), clicking the password field, typing slowly, then clicking Sign In.** The form uses `react-hook-form` which requires real keypress events — `fill()` does NOT work. Use `pressSequentially` (the `slowly: true` parameter).
3. **Take a `browser_snapshot()` after every major action.**
4. **If a button click does nothing** (no modal appears, no state change), try: (a) take a fresh snapshot to get the current ref, (b) click the exact ref from the snapshot, (c) wait 2 seconds, (d) snapshot again. If still nothing, THAT IS A BUG.
5. **After fixing any backend code:** kill the node process, run `pnpm -w run build:api`, then `node dist/apps/api/src/main.js`.
6. **After fixing frontend code:** just refresh the browser page (hot-reload).

---

## LOGIN PROCEDURE (use for every role switch)

```
1. browser_navigate('http://localhost:4201/login')
2. browser_snapshot() — verify login form visible
3. browser_click(ref for email field)
4. browser_type(ref for email field, 'EMAIL_HERE', slowly: true)
5. browser_click(ref for password field)
6. browser_type(ref for password field, 'PASSWORD_HERE', slowly: true)
7. browser_click(ref for "Sign in" button)
8. browser_wait_for(text: 'Welcome back')
9. browser_snapshot() — verify dashboard loaded with correct user name
```

If step 8 times out, the login failed. Check that `slowly: true` was used for both fields.

---

## TEST A: Facility Booking (Resident)

**Login as:** resident@facilityplatform.dev / Tech@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| A.1 | Open Bookings | Click "Bookings" in sidebar | Facility Bookings page with "Available Resources" tab showing 4 facility cards |
| A.2 | Click Book Now | Click "Book Now" button on the first facility card (Fitness Center) | **A booking modal opens** with title "Book Fitness Center" or similar, showing a date picker |
| A.3 | Select a date | In the modal, find a date input or calendar. Pick a date 2+ days from now (e.g., 2026-04-02). Type the date into the date field | Date selected |
| A.4 | Verify time slots | Snapshot the modal | Time slots should appear below the date (e.g., "09:00 - 10:00", "10:00 - 11:00"). If NO slots appear, THAT IS A BUG |
| A.5 | Select a time slot | Click on any time slot | Slot gets highlighted or selected |
| A.6 | Enter purpose | Find a "Purpose" or "Notes" text field in the modal. Type "Team meeting" | Purpose filled |
| A.7 | Confirm booking | Click "Confirm Booking" or "Book" button in the modal | Modal closes. Success toast or redirect |
| A.8 | Check My Bookings | Click "My Bookings" tab | New booking appears with "Pending" or "Confirmed" status and a "Cancel" button |
| A.9 | Cancel booking | Click "Cancel" on the booking | Status changes to "Cancelled" |

**If the modal does NOT open in step A.2:**
- Read `apps/web/src/app/(dashboard)/resident/bookings/page.tsx`
- Find the `Book Now` button's onClick handler
- Check if it sets state to open a modal (e.g., `setBookingModal(true)` or `setSelectedResource(...)`)
- Verify the Modal component is rendered and its `open` prop is tied to that state
- Fix whatever is broken, refresh, and retry

---

## TEST B: Create Visitor Pass (Resident)

**Login as:** resident@facilityplatform.dev / Tech@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| B.1 | Open Visitors | Click "Visitors" in sidebar | Visitor Passes page with Active (3) tab and "Create Pass" button |
| B.2 | Click Create Pass | Click "Create Pass" button (top right) | **A modal opens** with form fields: Visitor Name, Visit Date, Purpose |
| B.3 | Fill visitor name | Type "John Doe" into the Visitor Name field | Name filled |
| B.4 | Fill visit date | Type tomorrow's date (e.g., "2026-04-01") into the Visit Date field | Date filled |
| B.5 | Select purpose | Select "Personal Visit" from Purpose dropdown (or type if it's a text field) | Purpose set |
| B.6 | Submit | Click "Create Pass" button inside the modal | Modal closes. New pass appears in Active tab |
| B.7 | Verify pass | Snapshot | New pass shows "John Doe" with correct date and "Pending" or "Approved" status |

**If the modal does NOT open in step B.2:**
- Read `apps/web/src/app/(dashboard)/resident/visitors/page.tsx`
- Find the "Create Pass" button's onClick and trace the modal state
- Fix and retry

---

## TEST C: View Visitor Pass Code (Resident)

**Login as:** resident@facilityplatform.dev / Tech@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| C.1 | Open Visitors | Click "Visitors" in sidebar | Visitor Passes page |
| C.2 | Click View Code | Click "View Code" button on any pass (e.g., John Smith) | **A modal opens** showing a large pass code (like "VP-003" or "7CG8SL") |
| C.3 | Verify code | Snapshot the modal | Code should NOT be "N/A" or blank. Visitor name and date should appear below the code |
| C.4 | Close modal | Click "Close" or the X button | Modal closes |

**If the modal does NOT open in step C.2:**
- Read `apps/web/src/app/(dashboard)/resident/visitors/page.tsx`
- Find the "View Code" button's onClick handler
- Fix and retry

---

## TEST D: Acknowledge Announcement (Resident)

**Login as:** resident@facilityplatform.dev / Tech@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| D.1 | Open Announcements | Click "Announcements" in sidebar | Announcements page with 3 announcement cards |
| D.2 | Find unacknowledged | Look for an announcement WITHOUT a green "Acknowledged" badge | At least one should exist |
| D.3 | Click Acknowledge | Click "Acknowledge" button on that announcement | Green "Acknowledged" badge appears on the card. No error |
| D.4 | Refresh and verify | Refresh the page (browser_navigate to same URL) | The acknowledged state persists — badge still shows |

**If clicking Acknowledge does nothing or shows an error:**
- Check browser console for API errors
- Read `apps/web/src/app/(dashboard)/resident/announcements/page.tsx`
- Find the acknowledge handler — it likely calls `POST /announcements/{id}/acknowledge`
- Fix and retry

---

## TEST E: Save Resident Profile (Resident)

**Login as:** resident@facilityplatform.dev / Tech@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| E.1 | Open Profile | Click "My Profile" in sidebar | Profile page with Personal Information form |
| E.2 | Verify pre-filled | Snapshot | First Name = "James", Last Name = "Wilson", Email = "resident@facilityplatform.dev", Phone = "+1234567890" |
| E.3 | Clear phone field | Click the Phone field, select all text, delete it | Field empty |
| E.4 | Type new phone | Type "0501234567" into the Phone field | New phone entered |
| E.5 | Click Save | Click "Save Profile" button | Success message "Profile updated successfully" appears (toast or inline) |
| E.6 | Refresh and verify | Refresh the page | Phone field still shows "0501234567" — value persisted |

**If save fails:**
- Check browser console for API error
- The endpoint is `PATCH /resident/profile`
- Check what fields the API expects vs what the form sends
- Fix and retry

---

## TEST F: Toggle Notification Preference (Resident)

**Login as:** resident@facilityplatform.dev / Tech@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| F.1 | Open Profile | Click "My Profile" in sidebar | Profile page |
| F.2 | Scroll to Notification Preferences | Look for the "Notification Preferences" section below Personal Information | Table with Event, Email, SMS, Push columns |
| F.3 | Toggle a preference | Click any toggle/checkbox in the Email/SMS/Push columns | Toggle state changes |
| F.4 | Click Save Preferences | Click "Save Preferences" button | Success message |

---

## TEST G: Move-Out Wizard (Manager)

**Login as:** manager@facilityplatform.dev / Admin@12345

This is the most complex untested flow. The lease created in Session 3 (LS-2026-00002, Unit 201, James Wilson) was activated and moved in. It should be eligible for move-out.

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| G.1 | Open Move-Out | Click "Move-Out" in sidebar under Property Ops | Move-Out Wizard with 7-step stepper |
| G.2 | Step 1: Select lease | Select lease "#LS-2026-00002 - Unit 201 (James Wilson)" from dropdown | Lease selected, security deposit ($10,000) shown |
| G.3 | Click Next | Click "Next" | Step 2: Condition Comparison |
| G.4 | Step 2: Verify | Snapshot | Table with Move-In condition vs Move-Out condition columns. Items from the move-in checklist should appear |
| G.5 | Change conditions | Change a few move-out conditions to "Fair" or "Poor" using the dropdowns | Values update |
| G.6 | Click Next | Click "Next" | Step 3: Damage Assessment |
| G.7 | Step 3: Add damage | Click "Add Damage" button. Fill description = "Scratch on living room floor", room = "Living Room", cost = "200" | Damage item added to list |
| G.8 | Click Next | Click "Next" | Step 4: Deposit Calculation |
| G.9 | Step 4: Verify | Snapshot | Shows: Security Deposit ($10,000) minus Damages ($200) = Refund Amount. Numbers should be reasonable |
| G.10 | Click Next | Click "Next" | Step 5: Key Return |
| G.11 | Step 5: Return keys | Check checkboxes to mark keys as returned | Keys checked off |
| G.12 | Click Next | Click "Next" | Step 6: Final Meters |
| G.13 | Step 6: Fill readings | Enter final meter readings: Electric = 1500, Water = 400, Gas = 100 | Readings filled |
| G.14 | Click Next | Click "Next" | Step 7: Review & Complete |
| G.15 | Step 7: Review | Snapshot | Summary shows all data: lease, conditions changed, damages, deposit calculation, keys returned, meter readings |
| G.16 | Complete | Click "Complete Move-Out" | Success screen: "Move-Out Complete" with deposit refund amount and "Start New Move-Out" button |

**If any step fails:**
- Check browser console for API error
- Read `apps/web/src/app/(dashboard)/property-ops/move-out/page.tsx`
- The move-out wizard mirrors the move-in wizard structure
- Fix and retry

---

## TEST H: Expand Floors in Floors & Zones (Manager)

**Login as:** manager@facilityplatform.dev / Admin@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| H.1 | Open Floors & Zones | Click "Floors & Zones" in sidebar under Portfolio | Page with 3 building cards (Garden Main Building, Tower B - Annex, Tower A - Main) |
| H.2 | Expand Tower A | Click on the "Tower A - Main" text (NOT the "+ Floor" button) | Building card expands to show floors: Ground Floor (L0), Floor 1 (L1), Floor 2 (L2), Floor 3 (L3), Floor 4 (L4), Floor 5 (L5) |
| H.3 | Verify floor data | Snapshot the expanded section | Each floor shows name and level, with "+ Zone", "Edit", "Delete" buttons |
| H.4 | Expand a floor | Click on "Floor 1 (L1)" text | Floor expands to show zones (or "No zones" if none defined) |

**If expanding doesn't work:**
- The click might be hitting the wrong element. Use the exact ref from a snapshot for the building name text, not the card wrapper
- If floors don't appear after expand, check if the API returned floor data

---

## TEST I: Document Upload (Manager)

**Login as:** manager@facilityplatform.dev / Admin@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| I.1 | Open Document Library | Click "Document Library" in sidebar | Document Library page with category sidebar, document table, "Upload Document" button |
| I.2 | Click Upload Document | Click "Upload Document" button | Navigates to upload page with file picker, Category dropdown, Description field, Tags input |
| I.3 | Verify upload form | Snapshot | Form fields visible: File upload area, Title, Category dropdown, Description, Tags |

---

## TEST J: Asset Detail Page (Manager)

**Login as:** manager@facilityplatform.dev / Admin@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| J.1 | Open Assets | Click "Assets" in sidebar | Asset list with 12 assets |
| J.2 | Click an asset | Click on "Rooftop HVAC Unit #1" row (or any asset) | Asset detail page loads |
| J.3 | Verify detail | Snapshot | Shows: name, asset code, category name (NOT UUID), building name (NOT UUID or "-"), status, condition, manufacturer, model, serial number |
| J.4 | Check status actions | Look for status transition buttons | Buttons appropriate to current status (e.g., "Decommission", "Set Under Maintenance") |

**If building name shows "-":**
- This was a known display issue from Session 2. The asset detail page (`assets/[id]/page.tsx`) should be fetching building name via the asset's `building_id`. Check if the lookup is working.

---

## TEST K: Work Request Detail as Resident

**Login as:** resident@facilityplatform.dev / Tech@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| K.1 | Open My Requests | Click "My Requests" in sidebar | Work requests list with 4+ requests |
| K.2 | Click a request | Click on "Bathroom faucet leaking" row | Request detail page loads |
| K.3 | Verify detail | Snapshot | Shows: Request number, title, status badge ("Submitted"), category ("plumbing"), description, created date |

---

## TEST L: Quick Actions on Resident Dashboard

**Login as:** resident@facilityplatform.dev / Tech@12345

| Step | Action | How | Expected Result |
|------|--------|-----|-----------------|
| L.1 | Open Resident Home | Click "Resident Home" in sidebar | Resident dashboard |
| L.2 | Click Submit Request | Click "Submit Request" quick action button | Navigates to /resident/requests/create with the work request form |
| L.3 | Go back | Click "My Requests" in sidebar or browser back | Back to requests or dashboard |
| L.4 | Click Book Facility | Click "Book Facility" quick action button | Navigates to /resident/bookings |
| L.5 | Go back and click Visitor Pass | Click "Create Visitor Pass" quick action button | Navigates to /resident/visitors |

---

## Summary Checklist

- [ ] TEST A: Book a facility (modal opens, select date, select slot, confirm, verify in My Bookings, cancel)
- [ ] TEST B: Create a visitor pass (modal opens, fill form, submit, verify in list)
- [ ] TEST C: View visitor pass code (modal opens, code is NOT "N/A")
- [ ] TEST D: Acknowledge an announcement (badge appears, persists after refresh)
- [ ] TEST E: Save resident profile (phone change persists after refresh)
- [ ] TEST F: Toggle notification preference
- [ ] TEST G: Full move-out wizard (7 steps, complete to success screen)
- [ ] TEST H: Expand building floors in Floors & Zones page
- [ ] TEST I: Document upload form accessible
- [ ] TEST J: Asset detail page shows names not UUIDs
- [ ] TEST K: Work request detail page loads for resident
- [ ] TEST L: Quick action buttons navigate correctly

---

## Files Modified in Session 3

### Frontend (hot-reload, no rebuild needed):
```
apps/web/src/app/(dashboard)/maintenance/work-orders/[id]/page.tsx  — Status Timeline camelCase fix
apps/web/src/app/(dashboard)/inventory/purchase-requests/page.tsx   — UUID→name resolution for requester/approver
apps/web/src/app/(dashboard)/inventory/warehouses/page.tsx          — Safe defaults for undefined fields
apps/web/src/app/(dashboard)/portfolio/floors/page.tsx              — Fetch buildings+floors instead of /buildings/tree
apps/web/src/app/(dashboard)/inspections/compliance/page.tsx        — Client-side stats/categories computation
apps/web/src/app/(dashboard)/property-ops/keys/page.tsx             — UUID→name resolution for unit/resident/staff
apps/web/src/app/(dashboard)/vendors/performance/page.tsx           — Field mapping (name→company_name, email fallback)
```

### Backend (requires rebuild + restart):
```
apps/api/src/property-ops/move-in-checklist.service.ts  — Fixed complete() validation to check key_handovers and meter_readings tables
```

### Database (one-time setup, already done):
```
- Created Resident record for James Wilson (resident@facilityplatform.dev)
- Created resident_units assignment for James Wilson → Unit 101
```

---

## Key Technical Notes

- **react-hook-form login issue:** The login form uses `react-hook-form` with `register()`. Playwright's `fill()` method does NOT trigger React's internal state. You MUST use `slowly: true` (which calls `pressSequentially`) to type character-by-character so input events fire correctly.
- **Modal click issue:** Some React modals set state via `onClick={() => setState(true)}`. Playwright's `click()` on the snapshot ref should work, but if the snapshot ref is stale (page re-rendered), take a fresh snapshot first and use the new ref.
- **API rebuild command:** `pnpm -w run build:api` (from project root). Then restart: `node dist/apps/api/src/main.js`.
- **API runs from project root**, not from `apps/api/`. The dist path is `dist/apps/api/src/main.js` relative to the project root.
- **Token expiry:** JWT tokens expire after 15 minutes. If you get 401 errors mid-test, re-login.

---

*Generated after Session 3 Playwright UI testing. 9 bugs fixed, 31/31 pages loading, 12 modal/interaction flows remaining to verify.*
