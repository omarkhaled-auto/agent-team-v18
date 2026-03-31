# Root Cause Analysis: Frontend-Backend Disconnection in ArkanPM (Facility Management Build)

**Date:** 2026-03-31
**Analyst:** Claude Opus 4.6
**Scope:** Agent Team v15 architecture analysis + ArkanPM build forensics
**Finding:** 96 frontend-backend contract mismatches, 50+ bugs across 40+ files, 8 sessions of manual remediation

---

## EXECUTIVE SUMMARY

The ArkanPM facility management platform was built by the agent-team-v15 system and suffered from a fundamental frontend-backend disconnection: APIs were assumed from both sides, field names diverged (snake_case vs camelCase), endpoint paths were guessed wrong, Prisma relation includes were missing, and response wrapper conventions were inconsistent. A post-build 10-agent audit found **96 contract mismatches** across 10 modules. Fixing these required **8 manual sessions** of Playwright-driven testing and code repair.

The root cause is **not a single bug** but a **structural limitation in the agent team's architecture**: the system decomposes work into milestone-scoped silos where frontend and backend agents operate with insufficient shared contract enforcement at build time.

---

## PART 1: HOW THE AGENT TEAM WORKS (Architecture Analysis)

### 1.1 Orchestration Model

The agent team is controlled by a single **orchestrator** (an LLM given a massive system prompt in `agents.py`, ~3,000+ lines). The orchestrator coordinates specialized sub-agents:

| Agent Role | Purpose |
|---|---|
| planner | Explore codebase, create REQUIREMENTS.md |
| spec-validator | Compare requirements against original user request |
| researcher | Gather external knowledge, library docs |
| architect | Design solution, create Wiring Map, define contracts |
| task-assigner | Decompose requirements into atomic TASKS.md |
| code-writer | Implement assigned tasks (1-3 files each) |
| code-reviewer | Adversarial review, mark items complete |
| debugger | Fix issues found by reviewers |
| test-runner | Write and run tests |
| integration-agent | Wire cross-file connections |
| contract-generator | Generate CONTRACTS.json from architecture |

### 1.2 PRD Mode: Two-Phase Orchestration

For large projects like ArkanPM, the system uses **PRD Mode**:

**Phase 1 — Decomposition:** The orchestrator reads the PRD and creates a `MASTER_PLAN.md` with ordered milestones. Each milestone gets its own `REQUIREMENTS.md`.

**Phase 2 — Milestone Execution:** Each milestone runs in a **fresh orchestrator session** with:
- Its own REQUIREMENTS.md (scoped to that milestone)
- Compressed predecessor summaries (~100-200 tokens per completed milestone)
- An interface registry (function signatures, endpoints, types)
- CONTRACTS.md (cross-module API specs)
- A MILESTONE_HANDOFF.md (documenting interfaces for successors)

### 1.3 Milestone Phasing (v16 Design)

The system prescribes a 5-phase milestone structure:

| Phase | Content |
|---|---|
| A: Foundation | Shared libs, auth, database schema |
| B: Domain Modules | Self-contained module implementation |
| C: Integration Wiring | HTTP client calls, event handlers, cross-cutting |
| D: Frontend | Pages, components, service calls |
| E: Testing | Integration tests, E2E, seed data |

### 1.4 Contract Mechanisms

The system has multiple contract mechanisms designed to prevent disconnection:

1. **CONTRACTS.json** — Module + wiring contracts specifying exported symbols and import relationships
2. **CONTRACTS.md** — Human-readable cross-module API specification
3. **Wiring Map** — Table in REQUIREMENTS.md mapping Source -> Target -> Mechanism
4. **SVC-xxx entries** — Service-to-API wiring map: `Frontend Service.Method -> Backend Endpoint -> HTTP Method -> Request DTO -> Response DTO`
5. **Interface Registry** — JSON file tracking all module signatures, endpoints, events
6. **MILESTONE_HANDOFF.md** — Documents interfaces between milestones
7. **Status/Enum Registry** — Defines exact enum values across DB, backend, frontend

---

## PART 2: FACILITY MANAGEMENT RUN FORENSICS

### 2.1 What Was Built

ArkanPM is an enterprise facility management platform with:
- NestJS + Prisma backend (10+ domain modules)
- Next.js frontend (80+ page.tsx files, 68 navigable pages)
- 5 user roles (Super Admin, Facility Manager, Maintenance Tech, Inspector, Resident, Owner)
- PostgreSQL + Redis infrastructure
- Complex domain: portfolio management, asset lifecycle, work orders, inspections, warranties, inventory, vendor management, property operations, resident services, owner portal

### 2.2 Evidence of Disconnection

**CONTRACT_AUDIT_REPORT.md** (96 mismatches across 10 modules):

| Pattern | Count | Impact |
|---|---|---|
| Query parameter name mismatches | ~8 | Filters silently fail |
| Missing Prisma relation includes | ~20 | UUIDs/blanks shown instead of names |
| snake_case vs camelCase field naming | ~15 | Frontend reads `undefined` |
| Response wrapping inconsistency | System-wide | Fragile defensive code everywhere |
| Missing backend endpoints | 6 | Pages fail to load entirely |

**TESTING_SESSION_HANDOFF.md** (50+ bugs across 40+ files):

Specific examples of assumed APIs:
- Frontend sent `POST /move-in` (didn't exist); backend had `POST /move-in-checklists` + `POST /key-handovers` + `POST /meter-readings`
- Frontend sent `'electricity'`; backend expected `'electric'`
- Frontend sent `'new'` condition; backend expected `'excellent'`
- Frontend used `buildingId`; backend expected `building_id`
- Frontend sent `priority` filter; backend expected `priority_id`
- Frontend called `/warehouse-locations` (404); backend had `/warehouses`
- Frontend called `/occupancy` (404); backend had `/occupancy/dashboard`

### 2.3 Remediation Effort

| Session | Work Done |
|---|---|
| Session 1-2 | Manual testing, discovered 10 bug pattern categories, fixed 50+ bugs in 40+ files |
| Session 3 | 17 UI tests via Playwright, fixed 9 more bugs |
| Session 4 | 12 remaining UI tests via Playwright |
| Session 5 | 22/33 test suites passed, 4 bugs fixed, 17 documented |
| Session 6 | 30/33 suites passed, systemic Prisma relation fix via 4-agent team |
| Session 7 | 33/33 suites passed, 8 bugs fixed, final smoke test passed |
| Session 8 | 10-agent team to fix all 96 contract mismatches from full audit |

**Total remediation: 8 sessions of manual/semi-automated fixing after the initial build.**

---

## PART 3: ROOT CAUSE ANALYSIS

### Root Cause 1: MILESTONE ISOLATION — Fresh Sessions Lose Cross-Milestone Memory

**The single most damaging architectural decision.**

Each milestone executes in a **fresh orchestrator session** (`cli.py` line 1356: `async with ClaudeSDKClient(options=ms_options) as client`). The new session receives:
- A compressed predecessor summary (~100-200 tokens per milestone)
- An interface registry file (if it exists)
- CONTRACTS.md (if it exists)

But it does **NOT** receive:
- The actual source code written by predecessor milestones
- The exact Prisma schema with its include relationships
- The actual response shapes serialized by controllers
- The precise field naming conventions chosen by the backend

**Impact:** When the frontend milestone executes, it has a summary saying "milestone-3 created work order endpoints" but not the actual `WorkOrderService.findAll()` method showing that it returns `building_id` (not `buildingId`) and doesn't include the `building` relation. The frontend code-writer **assumes** field names based on convention, and assumes wrong.

**Evidence from ArkanPM:** The 15 snake_case/camelCase mismatches, the 20 missing Prisma includes, and the 6 missing endpoints are all symptoms of a frontend milestone that could not see the actual backend implementation.

### Root Cause 2: CONTRACTS ARE ASPIRATIONAL, NOT ENFORCED

The system generates multiple contract artifacts (CONTRACTS.json, CONTRACTS.md, SVC-xxx entries, Wiring Map, Interface Registry). However:

1. **Contract generation is LLM-driven, not code-derived.** The `contract_generator.py` generates contracts from the parsed PRD domain model, not from the actual implemented code. It predicts what the API will look like, rather than reflecting what was actually built.

2. **Contract verification is post-hoc, not blocking.** The `contracts.py` verification checks if symbols exist in files, but does not verify:
   - Response DTO field names match what the frontend consumes
   - Query parameter names match between frontend and backend
   - Prisma includes are sufficient for the response shape
   - Enum values are consistent across layers

3. **SVC-xxx entries require exact field schemas but architects produce class names.** The system prompt demands "exact field names and types" in SVC-xxx tables, but in practice the architect agent often produces `TenderListDto` instead of `{ id: string, title: string, status: "draft"|"active" }`. The code-writer then guesses.

4. **No runtime contract verification.** The system has no mechanism to start the backend, call an endpoint, and verify the response shape matches what the frontend expects. Verification is purely static (regex-based symbol presence checks).

### Root Cause 3: THE "EACH MILESTONE IS A FRESH CONTEXT" MODEL PREVENTS ITERATIVE ALIGNMENT

In a human team, when a frontend developer discovers the API returns `building_id` instead of `buildingId`, they either:
(a) Fix their frontend code immediately, or
(b) Ask the backend developer to change the API

In the agent team, this feedback loop does not exist because:
- The backend was built in Milestone B (completed, session ended)
- The frontend is being built in Milestone D (new session)
- The frontend code-writer cannot modify backend files ("Do NOT modify files that belong to completed milestones")
- The code-reviewer can flag mismatches, but has no mechanism to fix the backend
- The debugger can only fix "specific issues documented by reviewers" within the current milestone's scope

**Result:** Mismatches accumulate silently through the build. They are only discovered during manual testing sessions 1-8.

### Root Cause 4: ARCHITECT CREATES CONTRACTS BEFORE IMPLEMENTATION EXISTS

The architecture phase runs **before** any code is written. The architect produces:
- Wiring Map (predicting how files will connect)
- SVC-xxx entries (predicting API contracts)
- Status/Enum Registry (predicting enum values)

But the actual implementation may diverge from these predictions because:
- Code-writers make local decisions (e.g., Prisma naming conventions)
- NestJS serialization defaults produce different field names
- Database schema constraints force different response shapes
- The code-writer for the backend may choose different endpoint paths

**There is no reconciliation step** where someone compares the architect's predictions against the actual implementation and updates the contracts. The contracts become stale the moment the first code-writer makes a locally reasonable but globally inconsistent decision.

### Root Cause 5: NO END-TO-END INTEGRATION TEST DURING BUILD

The system has E2E testing capabilities (`e2e_testing.py`, `browser_testing.py`, `app_lifecycle.py`) but these run **after** all milestones complete, not between milestones. Even the "Integration Verification" step (Section 4, step f2) runs within a milestone session and relies on the code-reviewer reading code, not actually running the frontend against the backend.

If the system had spun up the NestJS server and the Next.js dev server between Phase B (backend) and Phase D (frontend), it would have caught every single one of the 96 mismatches during the build rather than requiring 8 remediation sessions.

### Root Cause 6: RESPONSE SERIALIZATION CONVENTION NOT STANDARDIZED EARLY

A massive class of bugs (snake_case vs camelCase, response wrapping inconsistency) stems from the lack of a **single, early, enforced decision** about response serialization:

- NestJS/Prisma returns snake_case by default
- Frontend JavaScript convention is camelCase
- Some endpoints wrap in `{ data: [], meta: {} }`, others return bare objects
- No global response interceptor was created in the foundation milestone

The system prompt includes framework instructions for NestJS (`agents.py` line 870-884) but does not mandate a camelCase response interceptor or standardized response wrapping. This is a convention that should be established in Phase A (Foundation) and enforced in all subsequent milestones, but the system has no mechanism to enforce it.

### Root Cause 7: PREDECESSOR SUMMARIES ARE TOO COMPRESSED

The `MilestoneCompletionSummary` dataclass contains:
- `milestone_id`, `title`
- `exported_files` (list of file paths)
- `exported_symbols` (list of symbol names)
- `summary_line` (one-line summary)

This is ~100-200 tokens per milestone. For a backend milestone that created 10 controllers with 50 endpoints, the successor milestone receives a list of file names and symbol names, but not:
- The exact HTTP method + path for each endpoint
- The exact response DTO fields
- The Prisma schema with include relationships
- The enum values used in the database

The Interface Registry helps (`interface_registry.py` tracks endpoints with method + path), but it does not capture response shapes or field naming conventions.

---

## PART 4: WHY THE EXISTING SAFEGUARDS FAILED

The agent team has extensive safeguards against disconnection. Here is why each one failed:

| Safeguard | Why It Failed |
|---|---|
| **Wiring Map (WIRE-xxx)** | Verifies structural connections (imports, route registration) but not data shape compatibility |
| **SVC-xxx entries** | Require exact field schemas but architects produce class names; no runtime verification |
| **CONTRACTS.json** | Checks symbol presence in files, not response shape or field naming |
| **Interface Registry** | Tracks function signatures and endpoints but not response DTOs or field conventions |
| **MILESTONE_HANDOFF.md** | Documents interfaces but compression loses the detail needed for exact API matching |
| **Mock Data Scan** | Catches `of()`, `Promise.resolve()`, hardcoded arrays — but a service calling `GET /warehouse-locations` instead of `GET /warehouses` is not mock data, it's a wrong URL |
| **Adversarial Review** | Reviewers check code quality within a milestone but cannot verify cross-milestone API contract alignment without running the actual backend |
| **Status/Enum Registry** | Designed to prevent enum mismatches but requires the architect to produce a complete registry before implementation; implementation may add enums not in the registry |
| **Contract Verification** | `contract_verifier.py` scans for symbol presence (does file X export function Y?) but not whether function Y returns `{ building_id: uuid }` vs `{ buildingId: uuid }` |
| **Endpoint XREF scan** | `XREF-001/002` checks that frontend calls have backend endpoints, but matches on path pattern, not exact field shapes |

**The fundamental gap:** All safeguards verify **structural connectivity** (does module A import from module B?). None verify **data shape compatibility** (does the frontend read `buildingId` when the backend sends `building_id`?).

---

## PART 5: RECOMMENDATIONS

### 5.1 Critical Fix: Cross-Milestone API Contract Snapshots

After each backend milestone completes, the system should:
1. Parse the actual NestJS/FastAPI controllers to extract endpoint definitions
2. Run a lightweight schema extraction that captures exact response field names from DTOs
3. Store these as a machine-readable `API_SNAPSHOT.json` (not compressed summaries)
4. Feed the full snapshot (not just summaries) to all subsequent milestones

### 5.2 Critical Fix: Serialization Convention Gate

Add a mandatory Phase A task: "Create response serialization interceptor (camelCase output, query param normalization)" with contract enforcement that all subsequent milestones use it. This single change would have prevented ~38 of the 96 mismatches.

### 5.3 Critical Fix: Inter-Milestone Integration Testing

Between Phase B (backend) and Phase D (frontend), the system should:
1. Start the backend server
2. Run each documented endpoint from SVC-xxx entries
3. Capture actual response shapes
4. Feed captured shapes (not architect predictions) to the frontend milestone

### 5.4 Important Fix: Frontend Agents Receive Backend Source Files

When a frontend milestone starts, in addition to compressed summaries, it should receive:
- The actual DTO/schema files from the backend (small, ~100 lines each)
- The actual controller files (to see exact endpoint paths and methods)
- The Prisma schema (to understand available relations)

This adds ~5-10K tokens of highly actionable context vs. the current ~200 tokens of compressed summaries.

### 5.5 Important Fix: Post-Milestone Contract Reconciliation

After each milestone completes, add a reconciliation step:
1. Scan implemented code for actual exports, endpoints, response shapes
2. Compare against CONTRACTS.md / SVC-xxx entries
3. Update contracts to reflect reality (not predictions)
4. Log any deviations for the next milestone to consume

---

## CONCLUSION

The ArkanPM build failure was not caused by bad code generation or poor agent prompting. The individual milestones each produced competent, well-structured code. The failure was caused by a **system architecture problem**: milestones execute in isolated sessions with insufficient shared state about the actual (not predicted) API contracts. Each side assumed what the other side would produce, and assumptions diverged on field naming, endpoint paths, enum values, query parameters, and response shapes.

The 96 mismatches and 50+ bugs are all instances of the same root cause: **the frontend was built against predicted API contracts rather than actual API implementations**. The system has extensive machinery for contract prediction (architects, SVC-xxx, Wiring Map, Interface Registry) but no machinery for contract verification at the data-shape level.

The fix is not more contract documents — the system already has 7 different contract mechanisms. The fix is **runtime contract verification**: actually calling the backend endpoints and feeding the real response shapes to the frontend code-writers.
