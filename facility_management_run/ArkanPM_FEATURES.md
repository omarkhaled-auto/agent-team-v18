# ArkanPM — Feature List

## Platform Overview

ArkanPM is an enterprise-grade property and facilities management platform built for the modern real estate operator. Designed as a multi-tenant SaaS solution, it unifies portfolio oversight, maintenance operations, asset lifecycle management, resident services, and owner transparency into a single, role-aware system.

---

## 1. Multi-Tenant Architecture & Organization Management

**One platform, infinite organizations.** ArkanPM is built from the ground up as a multi-tenant system. Each organization operates in a fully isolated environment — separate data, separate configurations, separate user bases — all running on shared infrastructure with no risk of data leakage.

- **Tenant Provisioning & Lifecycle** — Onboard new organizations with configurable subscription plans (Free, Starter, Professional, Enterprise), resource limits (max users, properties, storage), and lifecycle states (provisioning, active, suspended, archived, terminated).
- **Row-Level Security (RLS)** — PostgreSQL-enforced tenant isolation at the database layer. Every query is automatically scoped to the active tenant, providing defense-in-depth beyond application-level filtering.
- **Tenant-Scoped Configuration** — Each organization can customize system settings across categories: general, notifications, security, and integrations. Sensitive settings are flagged and handled accordingly.
- **Localization & Currency** — Per-tenant timezone, locale, and currency configuration ensures the platform adapts to regional requirements — particularly relevant for UAE-based property operations (AED default currency).

---

## 2. Authentication & Security

**Enterprise-grade security without the enterprise-grade friction.** ArkanPM implements layered security with multiple authentication factors, session management, and granular access control.

- **JWT Token Authentication** — Stateless access tokens (15-minute TTL) paired with rotating refresh tokens (7-day TTL) stored as SHA-256 hashes. Token rotation on every refresh eliminates replay attacks.
- **Multi-Factor Authentication (MFA)** — TOTP-based two-factor authentication with QR code provisioning. Generates 8 single-use backup codes for account recovery. MFA is enforced for all administrator roles — no exceptions.
- **Intelligent Account Lockout** — After 5 failed login attempts, accounts are locked for 15 minutes. No brute-force attack survives this.
- **Password Policy Enforcement** — Minimum 10 characters with complexity requirements (uppercase, lowercase, digit, special character). Password history tracking prevents reuse of the last 5 passwords.
- **Session Limits** — Configurable concurrent session caps (default: 5 for standard users, 10 for admins) prevent unauthorized credential sharing.
- **Tenant Status Guards** — Suspended tenants are automatically restricted to read-only access. Terminated or archived tenants are fully locked out. No manual intervention needed.
- **Secure Password Reset** — Token-based password reset flow with email delivery. The reset endpoint is hardened against email enumeration attacks.

---

## 3. Role-Based & Attribute-Based Access Control (RBAC + ABAC)

**The right people see the right things — automatically.** ArkanPM combines hierarchical role-based access with attribute-based scoping to deliver precise, context-aware authorization.

### Built-in Roles (11 system roles):

| Role | Access Scope |
|------|-------------|
| **Super Admin** | Full platform access across all tenants |
| **Platform Admin** | Platform-level administration |
| **Tenant Admin** | Full access within their organization |
| **Facility Manager** | Cross-building operations management |
| **Building Manager** | Scoped to assigned buildings only |
| **Maintenance Technician** | Work orders and assets in assigned buildings |
| **Inspector** | Inspection creation and execution |
| **Vendor User** | Work orders assigned to their company |
| **Owner** | Portfolio and financial visibility for owned units |
| **Resident** | Self-service requests, bookings, and announcements |
| **Read-Only** | View access across the platform |

- **Custom Roles** — Create organization-specific roles with fine-grained permission matrices across modules (portfolio, assets, maintenance, inspections, vendors, inventory, residents, owners) and actions (create, read, update, delete, manage, approve).
- **Building-Scoped Assignments** — Assign users to specific buildings with temporal scoping (expiration dates on assignments). Building managers automatically inherit access to all resources within their assigned buildings.
- **Attribute-Based Access Control (ABAC)** — Beyond role checks, the ABAC guard evaluates contextual attributes: a building manager querying work orders automatically receives results filtered to their assigned buildings. No configuration needed — it just works.
- **Financial Data Masking** — Technicians and operational staff never see cost fields, purchase prices, or financial data. The API strips sensitive financial information based on the requester's role.
- **Role Hierarchy Enforcement** — Users can only perform actions at or below their hierarchy level. A building manager cannot escalate to tenant admin privileges, even if a permission is misconfigured.

---

## 4. Portfolio & Property Management

**From portfolios to parking spots — every layer of your real estate hierarchy, mapped and managed.**

- **Portfolio Organization** — Group properties into portfolios with custom codes, statuses, and metadata. Ideal for investment groups, fund managers, or operators managing multiple property classes.
- **Property Registry** — Register properties with full detail: type (commercial, residential, mixed-use, industrial), address and coordinates (latitude/longitude), total area, year built, tax ID, and description. Properties link to portfolios and cascade down to buildings.
- **Building Management** — Each building carries its own identity: code, type, floor count, total area, year built, and address. Buildings are the primary organizational unit for operations, maintenance, and access control.
- **Floor & Zone Mapping** — Define floors with level numbers, total and usable area, and floor plan URLs. Subdivide floors into zones (by type and status) for granular space management.
- **Unit Registry** — Track individual units (office, retail, residential, storage, parking, common area) with area, capacity, rent amount, currency, and status history. Unit status flows (available, occupied, under renovation) are tracked as a JSON timeline.
- **Building Amenities** — Catalog amenities (gyms, pools, meeting rooms) with capacity, bookability flags, and operating hours. Amenities integrate directly with the facility booking system.
- **Building Systems** — Register building systems (HVAC, electrical, plumbing, fire safety, elevator, security) with manufacturer details, installation date, service history, and next service date. Systems tie into preventive maintenance scheduling.
- **Property Contacts** — Maintain contact directories per property: owners, managers, emergency contacts, and maintenance personnel — each with primary/secondary designation.

---

## 5. Asset Lifecycle Management

**Every piece of equipment, from acquisition to disposal — tracked, measured, and optimized.**

- **Hierarchical Asset Registry** — Assets support parent-child relationships, enabling you to model complex assemblies (an HVAC system containing compressors, fans, and filters as child assets). Each asset carries a unique code, barcode, and QR code URL.
- **Comprehensive Asset Profiles** — Capture manufacturer, model, serial number, purchase date, purchase price, current value, useful life, salvage value, and depreciation method (straight-line or declining balance). Full-text search across asset names ensures you find what you need instantly.
- **Asset Status State Machine** — Assets move through defined states: active, inactive, in storage, under maintenance, pending disposal, disposed, and transferred. Each transition is validated — no jumping from "disposed" back to "active."
- **Condition Tracking & Assessments** — Score assets on a 0-100 scale with ratings (excellent, good, fair, poor, critical, non-functional). Schedule recurring condition assessments with photo documentation and inspector tracking.
- **Depreciation Calculations** — Automated depreciation records with period-based opening value, depreciation amount, and closing value. Supports straight-line and declining balance methods with full currency tracking.
- **Asset Metering** — Attach meters (runtime hours, cycles, mileage, energy consumption) to assets. Meter readings trigger preventive maintenance when thresholds are breached — condition-based maintenance made simple.
- **Asset Transfers** — Move assets between buildings, floors, and units with a full transfer workflow: initiation, approval, in-transit tracking, and completion. Every transfer records who initiated it, who approved it, and why.
- **Asset Documentation** — Attach manuals, warranty certificates, purchase orders, photos, and inspection reports to any asset. Full file metadata tracking (size, MIME type, uploader).
- **Warranty Tracking per Asset** — Link multiple warranties (manufacturer, extended, service contract) to each asset with provider contacts, policy numbers, costs, and expiration management.
- **Maintenance History** — Every corrective, preventive, inspection, and emergency maintenance event on an asset is recorded with cost, parts used, and work order linkage.
- **Bulk Import** — Upload assets via CSV with error reporting — success and error counts returned per import batch.
- **Hierarchical Categories** — Organize assets in a tree-structured category system with parent-child nesting, custom codes, and icons.
- **Criticality Classification** — Tag assets as low, medium, high, or critical priority to drive maintenance prioritization and spare parts stocking decisions.

---

## 6. Maintenance & Work Order Management

**From a dripping faucet to a full building retrofit — every task tracked from request to resolution.**

### Work Requests

- **Resident & Staff Submissions** — Anyone can submit a maintenance request with title, description, photos, location (building/floor/unit), and priority. Residents are automatically scoped to see only their own requests.
- **Triage Workflow** — Submitted requests move through triage, approval (or rejection with reason), and conversion to full work orders. Each step tracks who acted and when.
- **Emergency Flagging** — Mark requests as emergencies to trigger expedited processing and escalation.
- **Full-Text Search** — Search across request titles and descriptions using PostgreSQL full-text indexing for instant results.

### Work Orders

- **Comprehensive Work Order Lifecycle** — A full state machine: Draft → Open → Assigned → In Progress ↔ On Hold → Completed → Verified → Closed (or Cancelled at any stage). Each transition is recorded in status history with timestamps, actors, and reasons.
- **Seven Work Order Types** — Corrective, preventive, predictive, emergency, inspection, project, and warranty repair. Each type carries its own operational context.
- **Technician Assignment** — Assign work orders to technicians with role tracking. Technicians acknowledge assignments, start work, and log completion — all with timestamps.
- **Interactive Checklists** — Attach multi-item checklists to work orders with five response types: checkbox, text, number, photo, and select. Required items must be completed before the work order can be closed.
- **Parts Management** — Reserve, use, and return spare parts against work orders with quantity tracking and cost calculation. Integrates with inventory to maintain stock accuracy.
- **Cost Tracking** — Break down costs by type: labor, parts, vendor, and other. Each cost entry records quantity, unit cost, total, and who incurred it. Compare estimated vs. actual hours for performance analysis.
- **Comment Threads** — Internal and external comment threads on every work order, with attachment support. Internal notes are hidden from non-privileged users.
- **File Attachments** — Attach photos, documents, and files to work orders with full metadata tracking.
- **Batch Creation** — Create multiple work orders in a single API call for large-scale planned maintenance events.
- **Kanban Board View** — Visualize work orders across status columns with priority color-coding, assignee display, and due date tracking. Switch between table and kanban views instantly.
- **Auto-Numbering** — Work orders receive sequential numbers (WO-2025-00001) automatically — no manual tracking needed.
- **Escalation Engine** — Configure automatic escalation rules triggered by SLA breaches, lack of response, or stale work orders. Escalations can notify users, reassign work, or bump escalation levels (1 through 3). Rules can be scoped to specific buildings, categories, or priorities.

### SLA Management

- **Response & Resolution Timers** — Dual SLA timers track response time (first acknowledgment) and resolution time (work completion) independently. Each timer records start, pause, breach, and completion timestamps.
- **Business Hours Configuration** — SLA timers can operate in business hours mode with configurable business hours per timer, ensuring SLAs don't tick during off-hours.
- **Pause & Resume** — When work orders go on hold, SLA timers pause automatically and resume when work restarts. Total paused duration is tracked separately.
- **Breach Detection** — SLA breaches are flagged in real-time with exact breach timestamps, feeding into escalation rules and dashboard metrics.
- **Priority-Based SLAs** — Each maintenance priority carries default SLA targets: Emergency (1h response), Urgent (4h), High (8h), Medium (24h), Low (48h). Override at the category or individual work order level.

### Preventive Maintenance

- **Flexible Scheduling** — Create PM schedules with nine frequency options: daily, weekly, biweekly, monthly, quarterly, semi-annual, annual, or custom interval (in days). Set lead days for advance work order generation.
- **Multi-Trigger Support** — PM schedules support three trigger types: time-based (calendar), meter-based (equipment readings), and condition-based (assessment thresholds). Triggers can be combined on a single schedule.
- **Template-Based Generation** — Define work order templates with pre-filled checklists, assignments, and estimated hours. Generated work orders inherit the template configuration automatically.
- **Pause & Resume Controls** — Pause active PM schedules during shutdowns or renovations, then resume without losing schedule context.
- **Generation Tracking** — Track when each schedule last generated a work order, how many it has generated in total, and when the next one is due.

---

## 7. Inspection & Compliance Management

**Standardize quality. Prove compliance. Never miss a deadline.**

### Inspection Templates

- **Reusable Template Library** — Create inspection templates for routine checks, safety audits, compliance reviews, condition assessments, move-in inspections, and move-out inspections. Templates are versioned for traceability.
- **Structured Sections & Items** — Templates contain weighted sections, each with scored items. Items support six response types: pass/fail, rating, text, number, photo, and multi-select. Mark items as required to enforce completion.
- **Auto-Create Work Orders on Failure** — Configure template items to automatically generate work orders when they fail inspection, with configurable priority levels. A failed fire extinguisher check creates a high-priority corrective work order — zero manual steps.

### Scheduled Inspections

- **Calendar-Based Scheduling** — Schedule inspections with target dates, due dates, and inspector assignments. Inspections track status from scheduled through in-progress to completed (or cancelled/overdue).
- **Recurring Inspections** — Set up recurring inspections using recurrence rules (RRULE format) with automatic next-occurrence calculation. Monthly fire safety walks, quarterly HVAC checks — set once, run forever.
- **Scope Flexibility** — Schedule inspections at any level: building-wide, floor-specific, unit-level, or asset-targeted.

### Inspection Reports

- **Structured Reporting** — Generate reports with per-item scoring, pass/fail results, photo documentation, and inspector notes. Reports calculate overall scores and results (pass, fail, conditional pass).
- **Review & Approval Workflow** — Reports move through draft → submitted → reviewed → approved/rejected. Reviewers add notes, and rejected reports can be revised and resubmitted.
- **Work Order Linkage** — Failed inspection items link directly to auto-generated work orders for immediate follow-up.

### Compliance Management

- **Regulatory Requirement Registry** — Track compliance requirements across categories: fire safety, health, environmental, building code, and accessibility. Each requirement records the governing authority, required inspection frequency, and applicable buildings.
- **Certificate Management** — Store compliance certificates with certificate numbers, issuing authority, issue dates, expiry dates, and status (active, expired, revoked). Attach certificate files for audit readiness.
- **Automated Due Date Tracking** — The system tracks last inspection dates and calculates next due dates based on required frequency — monthly, quarterly, semi-annual, or annual. Background processors flag overdue inspections automatically.

---

## 8. Vendor & Contract Management

**Find the right vendor. Hold them accountable. Renew or replace — backed by data.**

### Vendor Registry

- **Comprehensive Vendor Profiles** — Register vendors with category classification, tax ID, website, insurance expiry, license details, and status lifecycle (pending approval, approved, active, suspended, blacklisted). Flag underperforming vendors with reasons.
- **Multi-Contact Directory** — Store multiple contacts per vendor with roles, emails, phone numbers, and primary contact designation.
- **Document Vault** — Attach licenses, insurance certificates, compliance documents, and contracts to vendor profiles with expiry date tracking.

### Performance Tracking

- **Quantified Performance Records** — Track vendor performance over defined periods with four scored dimensions: SLA compliance, quality, timeliness, and overall score. Record total work orders, on-time completions, and SLA breaches per period.
- **Per-Work-Order Ratings** — Rate vendors after each completed work order across quality, timeliness, communication, and professionalism. Ratings aggregate into overall vendor scores visible in the vendor directory.
- **Visual Performance Indicators** — The vendor list displays 5-star ratings and SLA compliance progress bars with color-coded thresholds (green ≥90%, orange ≥70%, red <70%). Low-rated vendors (below 2.5 stars) are flagged with a warning icon.

### Service Contracts

- **Contract Lifecycle Management** — Create service contracts with full detail: contract number, type, value, currency, payment terms, start/end dates, scope of work, and terms and conditions. Contracts move through draft, active, expiring, expired, renewed, and terminated states.
- **Renewal Management** — Configure renewal type (manual/auto), notice period in days, and auto-renew flags. Track renewal objections and termination reasons.
- **SLA Terms** — Define measurable SLA terms per contract: metric name, target value, unit, penalty amount, and measurement period. Hold vendors accountable with data.
- **Building Scope** — Contracts can span multiple buildings, recorded as an array of building IDs — flexible enough for campus-wide service agreements.
- **Expiry Monitoring** — Background processors track contract expiration dates and trigger notifications before deadlines hit.

---

## 9. Warranty & Defect Management

**Protect your investments. Claim what you're owed. Track every defect to resolution.**

### Warranty Management

- **Warranty Provider Registry** — Maintain a directory of warranty providers with contact details, addresses, and websites.
- **Warranty Claims Workflow** — Submit claims with title, description, priority (low, medium, high, critical), and linked asset. Claims progress through draft → submitted → under review → approved/rejected → in progress → resolved → closed. Each stage tracks the responsible user and timestamp.
- **Expired Warranty Override** — Submit claims against expired warranties with mandatory justification — because sometimes a 13-month-old compressor failure should still be the manufacturer's problem.
- **Work Order Integration** — Approved warranty claims automatically link to work orders for repair execution, closing the loop between claim and fix.
- **Cost Coverage Tracking** — Record the amount covered by the warranty provider per claim, with currency tracking.

### Defect Management

- **Defect Logging** — Report defects with category, severity, location (building/floor/unit/asset), description, and photo evidence. Each defect receives a unique sequential number.
- **Defect Categories** — Organize defects into categories with default severity levels for consistent classification.
- **Resolution Workflow** — Defects progress through reported → assessed → assigned → in progress → resolved → verified → closed (with a "deferred" option for non-critical items). Each status change is recorded in a full status history.
- **Comment Threads** — Collaborate on defect resolution through comment threads with file attachments.
- **Work Order Linkage** — Link defects to work orders for repair tracking, maintaining traceability from defect discovery through fix.

---

## 10. Inventory & Spare Parts Management

**The right part, in the right warehouse, at the right time.**

### Spare Parts Catalog

- **Comprehensive Part Profiles** — Register spare parts with part numbers, descriptions, unit of measure, unit cost, manufacturer, model number, and images. Flag critical parts that must never run out.
- **Hierarchical Categories** — Organize parts in a tree-structured category system for intuitive navigation and filtering.
- **Supplier Management** — Link multiple suppliers to each part with supplier-specific part numbers, unit costs, lead times, and preferred supplier flags. Compare suppliers at a glance.

### Stock Management

- **Multi-Warehouse Tracking** — Track stock levels across multiple warehouse locations, each linked to specific buildings and floors. Monitor quantity on hand, reserved, and available in real-time.
- **Reorder Intelligence** — Configure reorder points, reorder quantities, and maximum quantities per part per warehouse. When stock drops below the reorder point, the system generates alerts automatically.
- **Transaction Ledger** — Every stock movement is recorded: receipts, issues, returns, adjustments, transfers, and write-offs. Each transaction captures reference type (work order, purchase order, manual), unit cost, and performer.
- **Visual Stock Indicators** — The spare parts list displays color-coded stock health: green (healthy), orange (at reorder point), red (out of stock) — with progress bar visualization.

### Procurement

- **Purchase Request Workflow** — Create purchase requests with itemized line items, vendor selection, and financial summaries (subtotal, tax, total). Requests progress through draft → submitted → approved → ordered → received.
- **Approval Routing** — Requests can require approval before ordering. Track approver, approval timestamp, and rejection reasons.

### Reorder Alerts

- **Automated Low-Stock Alerts** — Background monitoring generates alerts when stock falls below reorder points. Alerts track current quantity, reorder point, suggested reorder quantity, and resolution status (open, acknowledged, ordered, resolved).

---

## 11. Property Operations & Lease Management

**Leases, move-ins, move-outs, meters, and keys — the operational backbone of property management.**

### Lease Management

- **Full Lease Lifecycle** — Create leases with auto-generated numbers (LS-2025-00001), link to units, residents, and owners. Leases progress through draft → pending → active → expired/terminated/renewed.
- **Financial Configuration** — Set monthly rent, security deposit, payment frequency, payment day, currency, total contract value, and rent escalation (rate and frequency). Every financial field uses decimal precision.
- **Lease Renewal** — Renew leases with a single action, creating a new linked lease that inherits configuration from the original. Track the chain of renewals through linked renewal references.
- **Termination Management** — Terminate leases with documented reasons and timestamps. Auto-renew flags and special conditions provide flexibility.
- **Lease Documents** — Attach contracts, addendums, and supporting documents to leases with file metadata tracking.
- **Expiry Monitoring** — Background processors track upcoming lease expirations and trigger notifications, visible on the owner dashboard as "Upcoming Lease Expirations (next 90 days)."

### Move-In / Move-Out Inspections

- **Move-In Checklists** — Conduct structured unit inspections at move-in with area-by-area items, condition ratings (excellent, good, fair, poor, damaged), photo documentation, and inspector notes.
- **Move-Out Checklists** — Compare move-out condition against move-in records. Automatically calculate damage charges, cleaning charges, balance due, and deposit refund amounts.
- **Condition Comparison** — Each move-out checklist item shows the original move-in condition alongside the current condition, with per-item damage cost tracking.

### Key & Access Management

- **Key Handover Tracking** — Record the issuance and return of all access devices: unit keys, mailbox keys, access cards, garage remotes, and fobs. Track key numbers, quantities, conditions, and capture digital signatures.

### Utility Metering

- **Meter Reading Capture** — Record readings for electric, water, gas, steam, and chilled water meters. Track meter numbers, reading values, previous values, consumption calculations, and photo evidence. Scope readings to units or entire buildings.

### Occupancy Analytics

- **Real-Time Occupancy Dashboard** — View organization-wide occupancy statistics: overall rate, total units, occupied units, and vacant units. Drill down to per-building occupancy with color-coded progress bars (green ≥90%, orange ≥70%, red <70%).
- **Historical Occupancy Trends** — 12-month occupancy trend charts show how your portfolio performance evolves over time.
- **Occupancy Records** — Each building's occupancy is recorded by date, enabling historical analysis and trend identification.

---

## 12. Resident Portal & Community Management

**Give residents a front door to their building — digital, instant, and self-service.**

### Resident Dashboard

- **Personalized Home Screen** — Residents log in to a personalized dashboard showing their unit information (unit name, floor, building, property), quick action buttons, and at-a-glance statistics: open requests, upcoming bookings, unread announcements, and active visitor passes.
- **Service Request Submission** — Submit maintenance requests with descriptions, photos, location details, and priority levels. Track request status in real-time from submission through triage, approval, and work order completion.

### Facility Booking

- **Resource Discovery** — Browse bookable facilities (meeting rooms, gyms, pools, BBQ areas, party rooms, parking) with capacity, operating hours, rules, and images.
- **Reservation System** — Book facilities with title, time slots, and attendee counts. Bookings support approval workflows, check-in/check-out tracking, and automatic no-show detection via background processors.
- **Advance Booking Controls** — Configure maximum advance booking days and maximum duration per resource. Rules and operating hours prevent invalid reservations.

### Visitor Management

- **Digital Visitor Passes** — Create visitor passes with guest details (name, email, phone, company), visit purpose, expected arrival/departure times, and vehicle plate numbers. Passes generate unique pass codes for security verification.
- **Pass Lifecycle** — Passes move through pending → approved → checked in → checked out (or expired/cancelled). Building security can verify, approve, and check visitors in and out.

### Announcements

- **Targeted Communication** — Publish announcements with four types (general, maintenance, emergency, event) and four priority levels (low, normal, high, urgent). Target all residents, specific buildings, floors, or individual units.
- **Delivery Tracking** — Track announcement delivery with per-user receipts: delivered, read, and acknowledged timestamps. Know exactly who has seen critical communications.
- **Lifecycle Management** — Announcements move through draft → published → archived with configurable expiration dates.

### Resident Feedback

- **Satisfaction Surveys** — Collect resident feedback across five categories: general, maintenance, security, amenities, and cleanliness. Ratings (1-5) with free-text comments provide actionable insight.
- **Response Tracking** — Staff can respond to feedback with timestamps and responder tracking, closing the feedback loop.

### Resident Directory

- **Comprehensive Profiles** — Register residents with personal details, emergency contacts, ID information (Emirates ID, passport), and unit assignments. Residents can optionally link to user accounts for portal access.
- **Multi-Unit Support** — Residents can be assigned to multiple units with type designations (primary, secondary, authorized) and move-in/move-out date tracking.

---

## 13. Owner Portal

**Transparency for property owners — unit performance, lease status, and financial visibility at a glance.**

- **Owner Dashboard** — Owners see a personalized dashboard with total units owned, occupancy breakdown (occupied vs. vacant with color coding), aggregated monthly income, and upcoming lease expirations within 90 days.
- **Owner Profiles** — Support for individual and company owners with UAE-specific fields: Emirates ID, passport, trade license number, nationality, power of attorney holder details, and banking information (bank name, account number, IBAN).
- **Unit Ownership Records** — Track ownership with full detail: ownership type (freehold, leasehold, usufruct), share percentage, title deed number and date, acquisition details (purchase, inheritance, gift, developer handover), acquisition price, and disposal tracking.
- **Document Access** — Owners access their relevant documents through a dedicated document portal.
- **Maintenance Visibility** — Owners can view work orders related to their owned units.

---

## 14. Document Management System

**Every document, categorized, versioned, and access-controlled.**

- **Hierarchical Category Tree** — Navigate documents through a tree-structured category sidebar with item count badges. Categories support unlimited nesting depth.
- **Entity-Linked Documents** — Attach documents to any entity in the system: properties, buildings, assets, work orders, leases, vendors, and more. The entity type and ID create a universal linking mechanism.
- **Document Versioning** — Every document maintains a version history. Upload new versions with change notes while preserving the complete file lineage. Cold storage paths support long-term archival.
- **Access Control** — Documents carry access levels: public, tenant-wide, building-scoped, or restricted. The system enforces visibility based on the requester's role and scope.
- **Retention Policies** — Classify documents by retention type (compliance, financial, operational, temporary) with configurable expiration dates. Never accidentally delete a compliance document.
- **Access Audit Trail** — Every document view, download, and edit is logged with user ID, action type, and IP address. Full auditability for regulatory requirements.
- **Full-Text Search** — PostgreSQL GIN-indexed full-text search across document titles for instant discovery.
- **Tag System** — Tag documents with custom labels for cross-cutting organization beyond the category tree.

---

## 15. Notification System

**The right message, to the right person, through the right channel, at the right time.**

- **Four Delivery Channels** — In-app notifications, email, SMS, and push notifications. Each channel operates independently with its own delivery tracking.
- **Event-Driven Templates** — Pre-configured notification templates for system events: work order updates, lease milestones, inspection schedules, visitor arrivals, announcements, bookings, and payments. Templates support variable interpolation (e.g., `{{work_order.number}}`, `{{assigned_to.name}}`).
- **User Preference Control** — Users configure which events they want to receive, through which channels, and set quiet hours (start/end times) to prevent disturbances during off-hours.
- **Deduplication** — A 5-minute deduplication window prevents notification spam from rapid system events.
- **Push Token Management** — Register push tokens across platforms (iOS, Android, Web) with device tracking and activity monitoring.
- **Delivery Status Tracking** — Every notification tracks its journey: pending → sent → delivered → read (or failed with error details).
- **Real-Time Updates** — WebSocket gateway delivers in-app notifications in real-time without polling. The header notification bell updates live with unread count.
- **Emergency Override** — Emergency notifications bypass channel preferences and fire across push, email, and SMS simultaneously.

---

## 16. Integration & Webhook Platform

**Connect ArkanPM to your ecosystem — ERP, accounting, BMS, IoT, or custom systems.**

- **Integration Registry** — Configure third-party integrations with six types: ERP, accounting, BMS (Building Management Systems), IoT, Arkan platform, and custom. Each integration carries its own credentials, endpoint URL, sync frequency, and status.
- **Arkan Handover Integration** — Purpose-built integration for Arkan platform handover records (defects, snags, warranty items). Handover data is received, processed, and linked to defects or work orders within ArkanPM.
- **Webhook System** — Register webhook endpoints to receive real-time event notifications. Configure event subscriptions, authentication secrets, custom headers, retry counts, and timeout settings.
- **Delivery Guarantees** — Webhook deliveries track HTTP status, response bodies, attempt counts, and next retry timestamps. Failed deliveries retry automatically up to the configured maximum.
- **Integration Logging** — Every integration action is logged with request/response data, status (success, error, warning), error messages, and duration in milliseconds. Debug integration issues with complete visibility.

---

## 17. Audit & Compliance Trail

**Every action recorded. Every change traceable. Every actor accountable.**

- **Comprehensive Audit Logging** — Every create, update, delete, login, and logout action is captured with: user identity, timestamp, entity type, entity ID, IP address, user agent, and arbitrary metadata.
- **Change Differencing** — Update events store both old and new values as JSON, enabling point-in-time comparison. The audit log viewer displays before/after values side-by-side in expandable rows.
- **Filterable Audit Trail** — Filter audit logs by entity type, action, and date range. Paginated results handle even the most active tenants.
- **Soft Delete Tracking** — Deleted records are never truly removed. The `deleted_at` timestamp preserves data integrity and enables recovery, while all queries automatically exclude soft-deleted records.

---

## 18. Dashboard & Analytics

**Real-time operational intelligence, personalized by role.**

- **Role-Adaptive Dashboard** — The main dashboard adapts to the logged-in user's role. Admins see organization-wide metrics. Managers see operational KPIs. Technicians see their assigned work. Residents see their service requests. Owners see their portfolio performance.
- **Key Performance Indicators** — At-a-glance cards display: open work orders, SLA compliance rate, occupancy rate, pending approvals, and overdue inspections.
- **Work Order Trends** — 6-month trend chart comparing open vs. completed work orders, revealing operational momentum.
- **Occupancy by Building** — Color-coded building occupancy visualization highlights underperforming properties instantly.
- **SLA Performance** — Monthly compliance bar chart tracks service level adherence over time.
- **Recent Activity Feed** — Live feed of recent work orders with timestamps keeps managers informed without searching.
- **Quick Actions** — Role-specific quick action buttons surface the most common tasks: create work order, submit request, book facility, schedule inspection.
- **Auto-Refresh** — Dashboard data refreshes every 60 seconds — always current, never stale.

---

## 19. Background Job Processing

**Automated operations that run while you sleep.**

Seven background processors handle time-sensitive operations without manual intervention:

| Processor | Function |
|-----------|----------|
| **PM Generator** | Automatically creates work orders from preventive maintenance schedules when due dates arrive |
| **Overdue Inspection Detector** | Flags inspections that have passed their due dates as overdue |
| **Warranty Expiry Monitor** | Tracks warranty expiration dates and triggers notifications before coverage lapses |
| **Escalation Engine** | Executes escalation rules when SLA breaches or stale work orders are detected |
| **Booking No-Show Handler** | Marks facility bookings as no-shows when check-in windows expire |
| **Lease Expiry Monitor** | Tracks lease expirations and alerts stakeholders before renewal deadlines |
| **Contract Expiry Monitor** | Monitors service contract end dates and triggers renewal workflows |

All processors are backed by BullMQ with Redis persistence, ensuring jobs survive system restarts and execute reliably.

---

## 20. Platform Administration

**Complete control over your platform — users, roles, settings, and tenants.**

- **User Management** — Create, edit, lock, and unlock users. Assign roles via dropdown. View last login timestamps. Enforce password policies at creation time.
- **Role & Permission Matrix** — Visual permission matrix showing all modules and actions. Toggle permissions with checkboxes. System roles are clearly marked and protected from modification.
- **Tenant Management** — Super admins manage all organizations: create tenants, set subscription plans, monitor user counts, and control tenant status.
- **System Settings** — Tabbed configuration interface (General, Notifications, Security, Integrations) with type-aware editing: string inputs, number fields, and boolean toggles. Inline save buttons appear only when values change.
- **Notification Template Editor** — Edit notification templates with a split editor/preview interface. Insert template variables (specific to each event type) with one click. Preview rendered output with sample data before saving.
- **Webhook Configuration** — Register, test, and monitor webhook endpoints from the settings panel.
- **Integration Management** — Configure and monitor third-party integrations from a centralized settings page.

---

## 21. User Interface & Experience

**A modern, responsive interface designed for speed and clarity.**

- **Dual-View Data Tables** — Switch between table view (for detailed analysis) and kanban board (for visual workflow management) on supported pages.
- **Advanced Filtering** — Multi-dimensional filters on every list page: status, priority, category, building, condition, date range, and free-text search. Filters are composable — combine them for precise results.
- **Color-Coded Visual Language** — Consistent color coding across the platform: priority levels, condition ratings, occupancy rates, SLA compliance, and stock levels all use intuitive color scales.
- **Responsive Layout** — Sidebar navigation with role-based menu groups, mobile hamburger menu, and breadcrumb navigation for deep page hierarchies.
- **Real-Time Search** — Search inputs with instant filtering across names, codes, emails, serial numbers, and more.
- **Status Badges** — Contextual status badges with variant-specific colors appear consistently across all modules.
- **Form Validation** — Zod schema-based validation with inline error messages on every form. Complex forms use React Hook Form for performance.
- **Toast Notifications** — Non-blocking toast messages confirm actions, report errors, and surface system events.
- **Empty States** — Helpful empty state messages guide users when no data exists, preventing confusion.
- **Loading States** — Skeleton loaders and spinners maintain layout stability during data fetches.
- **Timeline Views** — Status history timelines on work orders and other entities show the complete lifecycle visually.
- **Progress Bars** — SLA compliance, occupancy rates, and stock levels use progress bars with contextual color thresholds.

---

## Technical Foundation

- **Monorepo Architecture** — NX-managed monorepo with shared type library ensuring type safety between frontend and backend.
- **Next.js 15 + React 19** — Latest-generation frontend framework for server-side rendering, client-side interactivity, and optimal performance.
- **NestJS Backend** — Enterprise Node.js framework providing modular architecture, dependency injection, and decorator-based routing.
- **PostgreSQL + Prisma ORM** — Type-safe database access with 105 data models, full-text search indexes, and row-level security policies.
- **Redis + BullMQ** — In-memory caching and reliable job queue processing for background automation.
- **WebSocket Gateway** — Real-time bidirectional communication for live notifications and updates.
- **Tailwind CSS** — Utility-first styling for consistent, maintainable UI across 96+ pages.
