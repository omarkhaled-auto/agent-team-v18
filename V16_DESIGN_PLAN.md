# Agent-Team V16 Design Plan

> **Author:** Claude Architect | **Date:** 2026-03-15 | **Status:** DRAFT FOR REVIEW
> **Based on:** Full investigation of agent-team-v15 (38 source files, 7363-line cli.py), super-team orchestrator (120+ source files), and 4 production builds (GlobalBooks standalone, GlobalBooks super-team, SupplyForge, LedgerPro)

---

## Executive Summary

The v15 standalone builder scored **10,300/12,000** on GlobalBooks — beating the super-team orchestrator's **8,275/12,000** — while producing 74K LOC across 9 services with working subledger→GL integration. The super-team lost because it couldn't wire services together. But the standalone builder still lost **1,700 points** primarily from:

1. **21 stub event handlers** (IC + GL event handlers that log-only) → Check 9, 10 penalties
2. **No audit middleware auto-capture** on Python services → Check 11 penalty
3. **Frontend mock data service** residuals → Check reliability concern
4. **Missing quality gate enforcement** — no automated post-build checks ran

The v16 upgrade focuses on closing these gaps by surgically importing the super-team's best ideas (structured context injection, quality enforcement, cross-service standards) while preserving the standalone builder's core advantage: **single-context integration.**

---

## Table of Contents

1. [Current V15 Pipeline Analysis](#1-current-v15-pipeline-analysis)
2. [Build Results Evidence](#2-build-results-evidence)
3. [What to Bring from Super-Team](#3-what-to-bring-from-super-team)
4. [What to Improve in the Builder](#4-what-to-improve-in-the-builder)
5. [What to Build New](#5-what-to-build-new)
6. [What NOT to Bring](#6-what-not-to-bring)
7. [Implementation Phases](#7-implementation-phases)
8. [Expected Impact](#8-expected-impact)

---

## 1. Current V15 Pipeline Analysis

### 1A. Complete Phase Sequence

The v15 pipeline (`cli.py:4386 main()` → `cli.py:911 _run_prd_milestones()`) executes in this order:

```
┌─────────────────────────────────────────────────────┐
│ PHASE 0: INITIALIZATION                              │
│  • CLI arg parsing (_parse_args, line 3572)          │
│  • Config loading (config.py, 591 lines)             │
│  • Depth detection (auto/keyword/flag)               │
│  • Claude CLI auth check                             │
│  • Backend selection (SDK API vs CLI subprocess)     │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 0.5: INTERVIEW (if enabled)                    │
│  • Interactive PRD Q&A (interviewer.py)              │
│  • Constraint extraction (prohibitions, requirements)│
│  • Scope detection (single-file → enterprise)        │
│  • Design reference URL extraction                   │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 0.7: CODEBASE MAP (if enabled)                 │
│  • Static file tree scan (codebase_map.py)          │
│  • Import dependency analysis                        │
│  • Framework detection                               │
│  • Summary injection into prompts                    │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 1: DECOMPOSITION                               │
│  • Large PRD chunking (prd_chunking.py, 80KB+)     │
│  • Orchestrator session creates MASTER_PLAN.md       │
│  • Auto-fixes h3/h4 headers to h2                    │
│  • Validates milestone count                         │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 1.5: TECH RESEARCH (if enabled)                │
│  • Detect tech stack from PRD + master plan          │
│  • Query Context7 for docs/best practices            │
│  • Up to 8 techs × 4 queries each                   │
│  • Research summary injected into milestone prompts  │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 2: MILESTONE EXECUTION LOOP                    │
│  For each milestone (dependency order):              │
│  ┌─────────────────────────────────────────────────┐│
│  │ 2a. Build predecessor context + handoff data    ││
│  │ 2b. Per-milestone tech research queries         ││
│  │ 2c. Build milestone-scoped prompt               ││
│  │ 2d. Fresh Claude SDK session executes milestone ││
│  │     (convergence loop inside the session)       ││
│  │ 2e. Convergence health check                    ││
│  │ 2f. Review recovery loop (if health < threshold)││
│  │ 2g. Milestone handoff document generation       ││
│  │ 2h. Wiring verification + fix loop              ││
│  │ 2i. Per-milestone audit (if enabled)            ││
│  │ 2j. Post-milestone quality scans:               ││
│  │     • Mock data scan → fix pass                 ││
│  │     • UI compliance scan → fix pass             ││
│  │ 2k. Mark milestone COMPLETE/DEGRADED/FAILED     ││
│  └─────────────────────────────────────────────────┘│
│  • Re-read MASTER_PLAN.md (agent may have modified) │
│  • Re-assert completed statuses                      │
│  • Compute rollup health                             │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 3: POST-ORCHESTRATION SCANS (quality_checks.py)│
│  • Mock data scan → fix pass                         │
│  • UI compliance scan → fix pass                     │
│  • API contract scan → fix pass                      │
│  • Silent data loss scan → fix pass                  │
│  • Endpoint cross-reference scan → fix pass          │
│  • Contract compliance scan → fix pass               │
│  • Database scans (ORM, defaults, relationships)     │
│  • Integrity scans (deployment, assets, PRD recon)   │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 4: E2E TESTING (if enabled)                    │
│  • Backend API E2E tests                             │
│  • Frontend Playwright E2E tests                     │
│  • Fix-rerun cycles (up to 5)                        │
│  • Browser testing via Playwright MCP (if enabled)   │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ PHASE 5: INTEGRATION AUDIT                           │
│  • Cross-milestone interface audit                   │
│  • Final convergence aggregation                     │
│  • Cost summary and completion report                │
└─────────────────────────────────────────────────────┘
```

### 1B. Key Configuration Surface

**File:** `config.py` (591 lines of dataclasses)

| Config Section | Key Parameters | Default | Impact |
|---|---|---|---|
| `orchestrator` | model=opus, max_turns=500, max_budget_usd=None | — | Session limits |
| `convergence` | max_cycles=10, min_ratio=0.9, recovery=0.8 | — | Convergence strictness |
| `milestone` | enabled=False, health_gate=True, wiring_check=True | — | PRD mode behavior |
| `post_orchestration_scans` | mock/ui/contract/sdl/xref scans, max_fix_passes=1 | All enabled | Post-build quality |
| `audit_team` | enabled=False, max_reaudit=3, severity=MEDIUM | — | Deep review |
| `e2e_testing` | enabled=False, max_fix=5 | — | Runtime testing |
| `tech_research` | enabled=True, max_techs=8, max_queries=4 | — | Context7 research |
| `quality` | production_defaults=True, craft_review=True | — | Code quality |

### 1C. Prompt Architecture

The builder sends prompts to Claude SDK sessions via three prompt builders (`agents.py`, 2863 lines):

1. **`ORCHESTRATOR_SYSTEM_PROMPT`** (lines 27-1914) — 1,887 lines of system prompt defining:
   - Requirements document protocol (REQUIREMENTS.md lifecycle)
   - Depth detection and fleet scaling
   - Convergence loop with 5 hard gates
   - Escalation protocol
   - Agent definitions (planner, researcher, architect, code-writer, reviewer, etc.)
   - Production readiness requirements
   - Code quality standards (injected from `code_quality_standards.py`)

2. **`build_decomposition_prompt()`** (line 2303) — Creates MASTER_PLAN.md

3. **`build_milestone_execution_prompt()`** (line 2441) — Per-milestone execution with:
   - Predecessor context and handoff data
   - Tech research injection
   - UI standards and design reference
   - Mandatory 9-step workflow (TASKS.md creation → coding → review → testing)
   - Contract specification instructions
   - Integration verification for milestones with predecessors

### 1D. Quality Mechanisms Already in V15

**File:** `quality_checks.py` (4,385 lines, 12 scan functions)

| Scan | Code | What It Checks |
|---|---|---|
| `run_spot_checks` | FRONT-001..021, BACK-001..015, SLOP-001..010 | Anti-patterns in source files |
| `run_mock_data_scan` | MOCK-001..004 | Hardcoded/fake data in service files |
| `run_ui_compliance_scan` | UI-FAIL-001..007 | UI standards violations |
| `run_deployment_scan` | DEPLOY-001..006 | Docker/nginx port/env/CORS mismatches |
| `run_asset_scan` | ASSET-001..003 | Broken asset/import references |
| `run_dual_orm_scan` | DUAL-ORM-001..003 | ORM/raw-query type mismatches |
| `run_default_value_scan` | DEFAULT-001..003 | Missing defaults, unsafe nullables |
| `run_relationship_scan` | REL-001..003 | Incomplete ORM relationship config |
| `run_silent_data_loss_scan` | SDL-001 | CQRS persistence verification |
| `run_api_contract_scan` | CONTRACT-001..004 | Response/event schema mismatches |
| `run_endpoint_xref_scan` | XREF-001 | Frontend-backend endpoint cross-reference |
| `run_e2e_quality_scan` | E2E-001..005 | E2E test quality |

**Other quality mechanisms:**
- `verification.py` — Progressive verification pipeline (lint, type-check, tests, build, security)
- `wiring.py` — Cross-milestone wiring verification
- `audit_team.py` — 5 parallel specialized auditors (requirements, technical, interface, test, library)
- `contract_scanner.py` — Static contract compliance checking
- `tracking_documents.py` — E2E coverage matrix, fix cycle log, milestone handoff

### 1E. What the Builder Does NOT Have

1. **No structured entity/state-machine/event pre-parsing** — The raw PRD text is passed to Claude, which must extract entities itself during the decomposition phase
2. **No cross-service standards injection** — No JWT, event, env var, error response, or Dockerfile templates
3. **No Dockerfile/docker-compose generation** — Claude generates these ad-hoc per milestone
4. **No domain model extraction** — No formal entity↔service mapping
5. **No event handler completeness enforcement** — Stubs pass quality scans
6. **No post-build fix loop with violation awareness** — Scans run, fix passes fire, but there's no intelligence about WHICH violations are fixable vs structural

---

## 2. Build Results Evidence

### 2A. GlobalBooks Standalone (Build B) — 10,300/12,000

**Source:** `HEAD_TO_HEAD_COMPARISON.md`

| Check | Score | Gap | Root Cause |
|---|---|---|---|
| 1. Double-Entry | 900 | 100 | Minor — accounts not validated for existence |
| 2. Fiscal Period | 900 | 100 | Minor — no period re-open |
| 3. Multi-Currency FX | 750 | 250 | No dedicated FX rate service |
| 4. CoA Hierarchy | 850 | 150 | Minor hierarchy gaps |
| 5. AP 3-Way Matching | 800 | 200 | Tolerance logic but no receipt matching UI |
| 6. State Machines | 850 | 150 | All present, minor coverage gaps |
| 7. Depreciation | 900 | 100 | 4 methods, correct formulas, GL posting |
| 8. Bank Reconciliation | 850 | 150 | Auto-matching + session, missing advanced rules |
| 9. IC Mirror Entries | 800 | 200 | Real SQL journals but event handlers stubbed |
| 10. Subledger→GL | 850 | 150 | 4/5 paths working, IC events still stubbed |
| 11. Audit Trail | 900 | 100 | DB-level RLS, manual Python calls (no middleware) |
| 12. Multi-Tenant | 950 | 50 | RLS on 46 tables, near-perfect |
| **TOTAL** | **10,300** | **1,700** | |

**Where the 1,700 points were lost:**
- **500 pts** — IC event handlers stubbed (Checks 9, 10 combined)
- **250 pts** — No FX rate service (Check 3)
- **200 pts** — Incomplete AP matching flows (Check 5)
- **200 pts** — Minor state machine coverage gaps (Checks 1, 4, 6)
- **150 pts** — No audit middleware on Python services (Check 11)
- **150 pts** — Bank reconciliation advanced features (Check 8)
- **250 pts** — Miscellaneous smaller gaps across checks

**Key structural findings:**
- **19/20 milestones completed** (milestone-1 was skipped/incomplete)
- **0.93 convergence ratio**, 164/176 requirements checked
- **$280.79 total cost**
- **78 test files** (49 .py + 29 .ts)
- **2 shared libraries** (Python `globalbooks_common` + TypeScript `shared/typescript`)
- **18 SQL migration files** with RLS policies on 46 tables
- **4/5 subledger→GL paths working** (AR, AP, Asset, IC via HTTP; GL events stubbed)

### 2B. GlobalBooks Super-Team (Build A) — 8,275/12,000

**Key failures:**
- **0/5 subledger→GL paths working** — All GL event subscribers are `logger.info()` stubs
- **IC mirror journals use `uuid.uuid4()` fake IDs** — Not real GL entries
- **No RLS** — Application-level tenant filtering only
- **Depreciation math bug** — Declining balance rate calculated wrong
- **Quality gate FAILED with 409 violations** (105 missing auth, 200 logging, 44 Docker)
- **Fix passes achieved 2.2% resolution** — Structural issues unfixable by patch agents

### 2C. Recurring Patterns Across All Builds

From SupplyForge (score 8,287/10,000), LedgerPro (6/6 services, 0/6 Docker), and GlobalBooks:

| Pattern | Frequency | Cause |
|---|---|---|
| **Stub event handlers** | Every build | Claude logs events instead of implementing business logic |
| **Missing Dockerfiles/health checks** | LedgerPro, SupplyForge | No template or enforcement |
| **Docker build failures (missing lockfiles)** | Every orchestrated build | No `npm install` / `pip freeze` step |
| **Frontend mock data residuals** | GlobalBooks standalone | Services created before backends, fall back to mocks |
| **Incomplete IC/cross-domain logic** | Every build | Hardest integration paths left for last, run out of context |
| **Quality gate infinite loops** | SupplyForge, LedgerPro | Unfixable violations (Docker, infra) treated as fixable |

---

## 3. What to Bring from Super-Team

### 3.1 Cross-Service Standards Injection (MUST-HAVE)

**Source:** `super-team/src/super_orchestrator/cross_service_standards.py` (939 lines)

**What it is:** 14 detailed standards covering JWT auth, event architecture, env vars, error responses, testing, Dockerfiles, database/migrations, state machines, handler completeness, frontend UX, business logic depth, API versioning, security, and Swagger.

**Why it helps:** The standalone builder's 21 stub handlers exist because Claude wasn't told "every event handler MUST perform a real action — log-only stubs are forbidden." The `HANDLER_COMPLETENESS_STANDARD` (line 659) and `EVENT_STANDARD` (line 137) explicitly address this with code examples and prohibition rules.

The `DOCKERFILE_STANDARD` (line 503) provides exact multi-stage Dockerfile templates for Python and TypeScript services — addressing LedgerPro's missing Dockerfile problem.

**Evidence:** Build A's stub handlers prove that even when Claude subscribes to events, it defaults to `logger.info()` without explicit prohibition. Build B partially avoided this because the single-context builder could see both the publisher and subscriber, but still produced 21 stubs for IC/GL events where the integration was more complex.

**How to integrate:** Inject a curated subset of these standards into the orchestrator system prompt (`ORCHESTRATOR_SYSTEM_PROMPT` in `agents.py`). Specifically:

1. **Add to system prompt directly** (not per-milestone — these are universal):
   - `HANDLER_COMPLETENESS_STANDARD` (adapted: remove cross-service references, keep the enforcement rules)
   - `EVENT_STANDARD` event handler section only (the prohibition of log-only stubs)
   - `BUSINESS_LOGIC_STANDARD` (entirely applicable)
   - `STATE_MACHINE_STANDARD` (code patterns already exist but enforcement text is stronger here)
   - `DOCKERFILE_STANDARD` (template patterns — the builder already knows Docker but lacks exact templates)
   - `TESTING_STANDARD` (minimum test categories per framework)
   - `ERROR_RESPONSE_STANDARD` (consistent error shapes)

2. **Skip** (not applicable to single-builder):
   - `JWT_STANDARD` — Only relevant when multiple services need to agree on JWT claims. In a single builder, Claude already creates consistent JWT handling.
   - `ENV_VAR_STANDARD` — Same reasoning; naming consistency is natural in single-context.
   - `API_VERSIONING_STANDARD` — The builder already uses `/api/` prefix patterns.
   - `FRONTEND_NO_BACKEND_STANDARD` — Not applicable (builder creates both frontend and backend).

**Estimated token cost:** ~3,000 tokens added to system prompt (~2% of 128K context window). Acceptable.

**Risk:** Prompt bloat. Mitigated by only injecting the 7 most impactful standards (not all 14).

**Priority:** P0 — Quick win, highest impact per effort.

### 3.2 Structured Entity/State-Machine/Event Pre-Parsing (MUST-HAVE)

**Source:** `super-team/src/architect/services/prd_parser.py` (9 extraction strategies), `domain_modeler.py`

**What it is:** The super-team PRD parser uses 9 strategies to extract:
- **Entities** with fields, types, required/optional, descriptions
- **State machines** with states, initial state, transitions, triggers
- **Events** with source service, payload schema, subscribers
- **Relationships** (HAS_MANY, BELONGS_TO, OWNS)

**Why it helps:** Currently, the v15 builder passes the raw PRD to Claude during decomposition. Claude must:
1. Read the entire PRD (often 60-130KB)
2. Mentally extract entities, state machines, events
3. Create milestones that cover all of them
4. Hope that each milestone session remembers the entity schema details

This is error-prone. The GlobalBooks PRD has **62 entities** and **10 state machines** — Claude's decomposition may miss entities or produce milestones with incomplete entity coverage.

A structured pre-parse would:
- Extract all 62 entities with exact field lists into a JSON/Markdown structure
- Map each entity to its owning service/domain
- Provide each milestone session with the exact entity schemas it needs to implement
- Ensure no entity is forgotten

**Evidence:** The super-team's PRD parser correctly extracted 35 entities from the SupplyForge PRD (66.6KB). Build B's standalone builder created all 9 services but missed some entity fields and state machine transitions — a structured injection would have prevented this.

**How to integrate:**

1. **New file: `prd_parser.py`** — Port the core extraction logic from super-team's `prd_parser.py`. Strip the MCP server integration, keep the regex strategies. Target: 300-400 lines.

2. **New pipeline phase: "Phase 0.8: PRD Analysis"** — Runs after codebase map, before decomposition:
   ```
   entities = parse_entities(prd_text)
   state_machines = parse_state_machines(prd_text)
   events = parse_events(prd_text)
   domain_model = build_domain_model(entities, state_machines, events)
   ```

3. **Inject into decomposition prompt** — The decomposition prompt gets a structured appendix:
   ```markdown
   ## PRD Analysis: Extracted Domain Model

   ### Entities (62 found)
   1. JournalEntry: id(UUID), entry_number(str), ...
   2. JournalLine: id(UUID), journal_entry_id(UUID), ...
   ...

   ### State Machines (10 found)
   1. Invoice: DRAFT→SENT→PAID→VOIDED
   2. PurchaseOrder: DRAFT→SUBMITTED→APPROVED→...
   ...

   ### Events (36 found)
   1. ar.invoice.created: published by AR service
   2. ap.payment.completed: published by AP service
   ...
   ```

4. **Inject into per-milestone prompts** — Each milestone gets only the entities/SMs/events relevant to its scope.

**Risk:** Parser may miss entities from non-standard PRD formats. Mitigated by including the raw PRD as fallback.

**Priority:** P0 — Critical for entity coverage completeness.

### 3.3 Stack-Specific Framework Instructions (SHOULD-HAVE)

**Source:** `super-team/src/super_orchestrator/pipeline.py` lines 1533-1736, `_STACK_INSTRUCTIONS` dict

**What it is:** Detailed framework-specific instructions for:
- **Python/FastAPI** — Dependencies, async DB connection, Alembic setup, project structure, testing patterns, migrations
- **TypeScript/NestJS** — Dependencies, DI patterns, DB connection, health endpoint, port config, testing, migrations
- **Frontend/Angular** — Standalone components, routing, forms, interceptors, Dockerfile
- **C#/.NET** — Clean Architecture structure, NuGet packages, EF Core, CQRS with MediatR

**Why it helps:** The standalone builder currently relies on Claude's training knowledge for framework setup. This mostly works, but produces inconsistencies:
- Some services use `synchronize: true` in TypeORM (should be `false`)
- Some services miss health endpoints
- Alembic setup is sometimes skipped in favor of `Base.metadata.create_all()`
- Port configuration varies between 3000 and 8080

**Evidence:** The super-team's stack instructions were developed specifically to fix recurring Docker/build failures across LedgerPro and SupplyForge.

**How to integrate:** Add a new function in `agents.py`:

```python
def _get_stack_instructions(prd_text: str) -> str:
    """Detect tech stack from PRD and return framework instructions."""
    # Detect based on keywords in PRD (Python/FastAPI, NestJS, Angular, etc.)
    # Return relevant instruction block
```

Inject into the decomposition prompt so MASTER_PLAN.md reflects correct framework patterns, and into each milestone prompt.

**Risk:** Medium. Could bloat prompt if multiple stacks are used. Mitigate by detecting the primary stack per service/milestone.

**Priority:** P1 — Important for Docker/build reliability.

### 3.4 Post-Build Validator Checks (SHOULD-HAVE)

**Source:** `super-team/src/super_orchestrator/post_build_validator.py` (14 check categories)

**What it is:** Cross-service validation checks:
1. JWT consistency (all services use same algorithm and claim names)
2. Event channel consistency (publishers and subscribers match)
3. Test existence (every service has test files)
4. Migration existence (every service has DB migrations)
5. Frontend-backend leak detection (no Python files in frontend)
6. Dockerfile health check patterns
7. Test quality (no trivial tests)
8. Handler completeness (no log-only stubs)
9. Event handler quality (handlers do real work)
10. API completeness (CRUD endpoints for all entities)
11. Security basics (auth decorators on mutation endpoints)
12. Error response consistency
13. Database quality (schema naming, indexes)
14. Environment variable consistency

**Why it helps:** The v15 builder already has 12 scan functions in `quality_checks.py`, but they're **pattern-matching scanners** — they check for anti-patterns in existing code. The post-build validator checks for **completeness** — things that should exist but don't.

The key addition is **handler completeness checking** (#8, #9). This would catch the 21 stub handlers that Build B produced.

**How to integrate:** Add 3-4 new scan functions to `quality_checks.py`:

```python
def run_handler_completeness_scan(project_root: Path) -> list[Violation]:
    """Detect event handlers that are log-only stubs."""
    # Scan for handler functions that only contain logger.info/console.log
    # Flag as HANDLER-001: "Event handler {name} appears to be a stub (log-only)"

def run_api_completeness_scan(project_root: Path) -> list[Violation]:
    """Detect entities missing CRUD endpoints."""
    # Cross-reference entity models with route handlers
    # Flag entities without list/get/create/update endpoints

def run_test_completeness_scan(project_root: Path) -> list[Violation]:
    """Detect services with no or trivial tests."""
    # Check each service directory for test files
    # Flag services with 0 test files or only trivial assertions
```

Wire these into the post-orchestration scan phase in `cli.py`.

**Risk:** Low — additive, non-breaking.

**Priority:** P1 — Catches the biggest quality gap (stub handlers).

### 3.5 Quality Gate Layer 3 Scanners (NICE-TO-HAVE)

**Source:** `super-team/src/quality_gate/layer3_system_level.py`, `security_scanner.py`, `observability_checker.py`, `docker_security.py`

**What it is:** Three concurrent scanners:
- **SecurityScanner** — JWT security, CORS config, secret detection (SEC-*, CORS-*, SEC-SECRET-*)
- **ObservabilityChecker** — Structured logging, sensitive log data, request-ID propagation (LOG-*, TRACE-*, HEALTH-*)
- **DockerSecurityScanner** — Dockerfile security best practices (DOCKER-*)

**Why it helps:** Build A had 409 violations including 105 missing auth decorators and 200 logging issues. The v15 builder's `run_spot_checks()` already covers many of these (BACK-001 through BACK-015 include auth and logging checks), but the super-team's scanners are more comprehensive, particularly for:
- Secret detection in committed files
- Docker security (non-root user, no secrets in Dockerfile, proper .dockerignore)
- CORS misconfiguration

**How to integrate:** Port the most valuable check patterns into existing `quality_checks.py` scan functions rather than importing the full Layer 3 engine. Specifically:
- Add secret detection patterns to `run_spot_checks()`
- Add Docker security patterns to `run_deployment_scan()`
- Add structured logging checks to existing BACK-xxx checks

**Risk:** Low — extends existing scans.

**Priority:** P2 — Nice to have, diminishing returns.

---

## 4. What to Improve in the Builder

### 4.1 Stub Handler Elimination Protocol (MUST-HAVE)

**Problem:** The #1 quality gap across all builds is stub event handlers. Claude subscribes to events, creates handler functions, but implements them as `logger.info()` stubs. In GlobalBooks Build B, 21 handlers were stubs.

**Root cause analysis:** The builder creates milestones in dependency order. Early milestones create the event infrastructure (publisher + subscriber skeleton). Later milestones are supposed to implement the handler business logic. But:
1. The handler was already "created" by an earlier milestone
2. The later milestone doesn't know it needs to flesh out the handler
3. No quality check flags log-only handlers

**Solution — Three-pronged approach:**

**A. Prevention (prompt-level):** Add explicit prohibition to `ORCHESTRATOR_SYSTEM_PROMPT`:

```markdown
## STUB HANDLER PROHIBITION (ZERO-TOLERANCE)

When you create an event subscriber or handler function:
- It MUST perform a REAL business action (DB write, state change, HTTP call)
- It MUST NOT be a log-only stub: `logger.info("received event")` is FORBIDDEN
- If you don't know what the handler should do, READ the PRD section for that domain
- If the handler genuinely has no business logic, DO NOT subscribe to the event

DETECTION: The system will scan all handler/subscriber files after each milestone.
Any function that ONLY contains logging statements will be flagged as a violation
and a fix pass will be triggered.
```

**B. Detection (scan-level):** New scan function `run_handler_completeness_scan()` in `quality_checks.py`:

```python
def run_handler_completeness_scan(project_root: Path) -> list[Violation]:
    """Detect event handler functions that are log-only stubs.

    Scans all Python and TypeScript files for functions matching handler patterns
    (handle_*, on_*, *Handler, *Subscriber) and checks if their body contains
    only logging statements.
    """
    # Pattern: function body is exclusively logger.info/console.log/this.logger.*
    # Heuristic: count non-logging, non-comment lines in function body
    # If 0 business lines → STUB-001 violation
```

**C. Remediation (fix pass):** Wire `run_handler_completeness_scan` into the post-milestone scan loop (existing pattern in `cli.py` lines 1556-1609). On violation detection, trigger a targeted fix pass with the handler file path and the relevant PRD section.

**Files to modify:**
- `agents.py` — Add stub prohibition to system prompt (~20 lines)
- `quality_checks.py` — Add `run_handler_completeness_scan()` (~100 lines)
- `cli.py` — Wire into post-milestone scan loop (~30 lines)
- `config.py` — Add `handler_completeness_scan: bool = True` to `PostOrchestrationScanConfig` (~2 lines)

**Priority:** P0 — Directly addresses 500+ lost points.

### 4.2 Entity Coverage Verification (MUST-HAVE)

**Problem:** With 62 entities in GlobalBooks, some may be partially implemented or missed entirely. There's no check that verifies "entity X from the PRD has a corresponding model, CRUD endpoints, and tests."

**Solution:** After PRD pre-parsing (Section 3.2) extracts the entity list, add a post-build verification that cross-references:
- Parsed entities from PRD → ORM models in source code
- ORM models → route handlers (CRUD coverage)
- Route handlers → test files (test coverage)

**Implementation:**

```python
def run_entity_coverage_scan(
    project_root: Path,
    parsed_entities: list[dict],
) -> list[Violation]:
    """Verify all PRD entities have models, endpoints, and tests."""
    # For each parsed entity:
    #   1. Search for class/model definition matching entity name
    #   2. Search for CRUD route handlers referencing the model
    #   3. Search for test files covering the entity
    # Report: ENTITY-001 (missing model), ENTITY-002 (missing routes), ENTITY-003 (missing tests)
```

**Files to modify:**
- `quality_checks.py` — Add `run_entity_coverage_scan()` (~150 lines)
- `cli.py` — Wire into post-orchestration scans, pass parsed entities from Phase 0.8

**Priority:** P0 — Ensures completeness.

### 4.3 Milestone-Level Entity Assignment (MUST-HAVE)

**Problem:** The decomposition prompt doesn't tell Claude which entities belong to which milestone. Claude must figure this out from the PRD, leading to:
- Entities split across milestones inconsistently
- Related entities in different milestones without explicit dependency
- Entity fields defined differently in different milestones

**Solution:** After PRD pre-parsing produces the entity/service map, inject entity assignments into the decomposition prompt:

```markdown
## Entity Assignment Guide

When creating milestones, assign these entities to their owning domains:

### GL Domain (suggested: 1-2 milestones)
- JournalEntry: 12 fields, state machine (DRAFT→POSTED→VOIDED)
- JournalLine: 8 fields
- ChartOfAccounts: 10 fields, hierarchy (parent_id)
- FiscalPeriod: 6 fields, state machine (OPEN→SOFT_CLOSE→CLOSED)

### AR Domain (suggested: 1-2 milestones)
- Invoice: 15 fields, state machine (DRAFT→SENT→PAID→VOIDED)
- InvoiceLine: 8 fields
- Customer: 12 fields
...
```

This gives Claude a clear blueprint for milestone decomposition.

**Files to modify:**
- `agents.py` `build_decomposition_prompt()` — Add entity assignment section (~30 lines)
- New `prd_parser.py` — Entity extraction produces domain groupings

**Priority:** P0 — Critical for decomposition quality.

### 4.4 GL Integration Verification (SHOULD-HAVE)

**Problem:** The defining gap between Build A and Build B was GL integration. Build B scored 850/1000 on Subledger→GL because it created real HTTP calls from AR/AP/Asset to GL. Build A scored 125/1000 because all GL handlers were stubs.

For an accounting system, this is the most critical integration path.

**Solution:** Domain-specific integration verification for accounting PRDs. After detecting an accounting/ERP domain:

1. **During decomposition:** Add explicit integration requirements:
   ```markdown
   ## INTEGRATION MANDATE (Accounting Systems)

   The following subledger→GL integration paths MUST be implemented as
   working code (HTTP calls or direct service calls), NOT event-only stubs:

   1. AR Invoice Approval → GL Journal Entry (debit Receivable, credit Revenue)
   2. AP Invoice Approval → GL Journal Entry (debit Expense, credit Payable)
   3. AP Payment → GL Journal Entry (debit Payable, credit Cash)
   4. Asset Depreciation → GL Journal Entry (debit Depreciation Expense, credit Accumulated)
   5. IC Transaction → Two GL Journal Entries (one per subsidiary)
   ```

2. **During post-build scan:** Check for GL client/HTTP calls in AR, AP, Asset, IC services.

**How to integrate:** This is domain-specific, so implement as a conditional injection when the PRD contains accounting keywords (GL, journal entry, subledger, chart of accounts, trial balance).

**Files to modify:**
- `agents.py` — Add accounting integration mandate (conditional, ~40 lines)
- `quality_checks.py` — Add `run_gl_integration_scan()` for accounting PRDs (~80 lines)

**Priority:** P1 — High value for accounting domain, lower value for other domains.

### 4.5 Fix Pass Intelligence (SHOULD-HAVE)

**Problem:** The current fix pass pattern is:
1. Scan finds violations
2. Fix agent receives violation list
3. Fix agent attempts to fix
4. Re-scan
5. If violations remain, report as warning

This lacks intelligence about:
- **Which violations are fixable** (code-level issues) vs **unfixable** (architectural issues, missing data)
- **Repeated violations** — same violation appearing in multiple fix passes
- **Fix regression** — fix pass introduces new violations

**Solution:** Port the super-team's fix loop intelligence from `integrator/fix_loop.py`:

1. **Violation classification:** Classify each violation as:
   - `FIXABLE_CODE` — Missing import, wrong field name, missing validation
   - `FIXABLE_LOGIC` — Stub handler needing business logic
   - `UNFIXABLE_INFRA` — Missing Docker build dependency, lockfile issue
   - `UNFIXABLE_ARCH` — Architectural issue requiring redesign

2. **Fix attempt tracking:** Track which violations have been attempted across fix passes. After 2 attempts on the same violation, classify as `UNFIXABLE_PERSISTENT`.

3. **Stop condition:** Stop fix loops when only `UNFIXABLE_*` violations remain.

**Files to modify:**
- `quality_checks.py` — Add `classify_violation()` function (~50 lines)
- `cli.py` — Enhance fix pass loop with classification and tracking (~60 lines)

**Priority:** P1 — Prevents wasted compute on unfixable issues.

### 4.6 Context Window Budget Management (SHOULD-HAVE)

**Problem:** Adding all v16 injections increases prompt size significantly.

**Measured budget** (actual character counts from source files):

| Component | Chars | Tokens (~) | Source |
|---|---|---|---|
| `ORCHESTRATOR_SYSTEM_PROMPT` | 35,245 | 8,811 | `agents.py` |
| `code_quality_standards.py` (FRONTEND + BACKEND) | 33,149 | 8,287 | `code_quality_standards.py` |
| `ui_standards.py` | 14,164 | 3,541 | `ui_standards.py` |
| **Current v15 total** | **82,558** | **~20,639** | **10.3% of 200K** |
| + Selected 9 cross-service standards | +21,658 | +5,414 | Phase 1.4 |
| + All-out backend mandates | +5,340 | +1,335 | Phase 1.7 |
| + All-out frontend mandates | +2,829 | +707 | Phase 1.7 |
| + Stack instructions (per-milestone) | +11,803 | +2,950 | Phase 2.5 |
| **V16 total** | **~124,188** | **~31,045** | **15.5% of 200K** |

**Verdict: Budget is NOT a concern.** 15.5% of 200K context leaves 84.5% (~169K tokens) for code generation. Even the largest PRD (GlobalBooks at 129KB ≈ 32K tokens) leaves 137K tokens for code.

**Solution:** Add a lightweight budget check that logs a warning if prompt exceeds 25% of context window:

```python
def check_context_budget(prompt: str, threshold: float = 0.25) -> bool:
    est_tokens = len(prompt) // 4
    ratio = est_tokens / 200_000
    if ratio > threshold:
        print_warning(f"Prompt uses ~{ratio:.0%} of context ({est_tokens} est. tokens)")
    return ratio <= threshold
```

**Files to modify:**
- `agents.py` — Add budget check before sending prompts (~20 lines)

**Priority:** P2 — Preventive measure.

---

## 5. What to Build New

### 5.1 Post-Build Stub Completion Agent (MUST-HAVE)

**Problem:** Even with stub prohibition in prompts, some stubs may persist. A dedicated post-build phase should find and complete them.

**What it does:**
1. Run `run_handler_completeness_scan()` after all milestones complete
2. For each stub handler, extract:
   - The event type it subscribes to
   - The service it's in
   - The PRD section describing what should happen when this event occurs
3. Deploy a targeted Claude session to implement each stub handler with real business logic

**Implementation:**

```python
async def _run_stub_completion(
    cwd: str,
    config: AgentTeamConfig,
    stub_violations: list[Violation],
    prd_text: str,
    task: str,
    constraints: list | None = None,
    depth: str = "standard",
) -> float:
    """Complete stub event handlers with real business logic."""
    if not stub_violations:
        return 0.0

    # Group stubs by service
    stubs_by_service: dict[str, list[Violation]] = {}
    for v in stub_violations:
        svc = _detect_service_from_path(v.file_path)
        stubs_by_service.setdefault(svc, []).append(v)

    # Build targeted prompt for each service's stubs
    for svc, stubs in stubs_by_service.items():
        prompt = _build_stub_completion_prompt(svc, stubs, prd_text)
        # Execute via Claude SDK session
        ...
```

**Files to modify:**
- `cli.py` — Add `_run_stub_completion()` function (~80 lines)
- `cli.py` — Wire into post-orchestration phase, after scans and before E2E (~15 lines)

**Priority:** P0 — Directly eliminates the biggest quality gap.

### 5.2 Integration Verification Phase (SHOULD-HAVE)

**Problem:** The builder checks wiring between milestones (files imported, routes registered) but doesn't verify **behavioral integration** — that calling Service A's endpoint actually triggers the correct behavior in Service B.

**What it does:**
1. After all milestones complete, extract all cross-service call paths:
   - HTTP client calls between services
   - Event publish → subscribe pairs
   - Shared library usage
2. For each call path, verify:
   - The called endpoint exists and has matching request/response schema
   - The event subscriber exists and handles the event
   - The shared library functions are actually imported and used

**Implementation:** Extend `run_endpoint_xref_scan()` (already exists, 187 lines) with:
- Cross-service HTTP client → endpoint matching
- Event publisher → subscriber channel matching
- Shared library import → usage verification

**Files to modify:**
- `quality_checks.py` — Extend `run_endpoint_xref_scan()` (~100 additional lines)

**Priority:** P1.

### 5.3 Dockerfile Template Generation (NICE-TO-HAVE)

**Problem:** Dockerfiles are generated ad-hoc by Claude per milestone. Quality varies, and Docker build failures are a recurring issue (missing `package-lock.json`, wrong ports, no health checks).

**What it does:** After detecting the tech stack per service (from the PRD pre-parse), generate Dockerfile templates that Claude can use as starting points.

**Implementation:** Port `_STACK_INSTRUCTIONS` Dockerfile patterns from super-team pipeline and generate actual Dockerfile files (not just prompt instructions):

```python
def generate_dockerfile_template(
    service_id: str,
    stack: str,  # "python" | "typescript" | "frontend" | "dotnet"
    port: int = 8080,
) -> str:
    """Generate a production-ready Dockerfile template."""
    templates = {
        "python": PYTHON_DOCKERFILE_TEMPLATE,
        "typescript": TYPESCRIPT_DOCKERFILE_TEMPLATE,
        "frontend": FRONTEND_DOCKERFILE_TEMPLATE,
    }
    return templates.get(stack, templates["python"]).format(
        service_id=service_id, port=port,
    )
```

**Files to modify:**
- New file: `dockerfile_templates.py` (~100 lines)
- `cli.py` — Generate templates after decomposition, before milestone execution (~20 lines)

**Priority:** P2 — Helpful but Claude usually gets Dockerfiles right with prompt instructions.

---

## 6. What NOT to Bring

### 6.1 Multi-Service Orchestration Engine

The entire super-team architecture of running parallel builder subprocesses, managing builder configs, tracking per-service convergence, and handling stall recovery is **not applicable**. The standalone builder's single-context approach is its primary advantage.

**Specifically exclude:**
- `pipeline.py` subprocess management (`_run_single_builder()`, stall detection, pipe deadlock fixes)
- `state_machine.py` orchestrator states (architect → contracts → builders → integration → quality_gate)
- `integrator/compose_generator.py` multi-service docker-compose generation
- `integrator/docker_orchestrator.py` per-service Docker builds
- `integrator/service_discovery.py` runtime service mesh

### 6.2 Quality Gate Layer 1 (Per-Service Build Results)

The 4-layer quality gate engine (`gate_engine.py`) evaluates per-service builder results (pass rate, convergence). Since v16 has a single builder, not multiple, this layer has no inputs.

### 6.3 Quality Gate Layer 2 (Contract Compliance)

The contract compliance layer checks inter-service contracts generated by the orchestrator's contract engine. The standalone builder doesn't generate formal inter-service contracts because it builds everything in one context. The `contract_scanner.py` and `contracts.py` in v15 already provide contract-level checking within the build.

### 6.4 Quality Gate Layer 4 (Adversarial)

The adversarial layer (`layer4_adversarial.py`) uses Graph RAG for deep pattern detection. This requires the entire Graph RAG infrastructure (knowledge graph, indexer, MCP server) which is heavy. The v15 builder's existing `audit_team.py` with 5 specialized auditors provides similar depth without the infrastructure.

### 6.5 MCP Server Infrastructure

The super-team runs 4 MCP servers (architect, contract_engine, codebase_intelligence, graph_rag) for 29 tools. This is orchestrator infrastructure that the standalone builder doesn't need — Claude Code already has file system access and can do the analysis inline.

### 6.6 Cross-Service Contract Registration

The `contract_engine/` module (10 tools for contract registration, validation, breaking change detection) is designed for multi-builder coordination. Not applicable.

### 6.7 Frontend-Specific Backend Warnings

`FRONTEND_NO_BACKEND_STANDARD` warns frontend builders not to create Python files. In the standalone builder, Claude creates both frontend and backend — this warning would cause confusion.

---

## 7. Implementation Phases

### Phase 1: Quick Wins + Fix Intelligence + Mandates (2-3 days, ~750 lines of code)

| # | Task | Files | Lines | Impact |
|---|---|---|---|---|
| 1.1 | Add stub handler prohibition to system prompt | `agents.py` | ~30 | Prevents stubs at source |
| 1.2 | Add `run_handler_completeness_scan()` | `quality_checks.py` | ~100 | Detects remaining stubs |
| 1.3 | Wire handler scan into post-milestone loop | `cli.py`, `config.py` | ~35 | Auto-triggers fix pass |
| 1.4 | Inject curated cross-service standards into system prompt | `agents.py` | ~200 | Better business logic, testing, error handling |
| 1.5 | Add entity coverage scan (`run_entity_coverage_scan`) | `quality_checks.py` | ~150 | Catches missing entities |
| **1.6** | **Add fix loop intelligence (unfixable classifier + repeat detection)** | **`quality_checks.py` + `cli.py`** | **~135** | **Saves $5-15/build, stops infinite loops** |
| **1.7** | **Inject all-out mandates (backend + frontend)** | **`agents.py`** | **~200** | **Increases output depth: bulk ops, audit trail, import/export, dashboards** |
| **1.8** | **Port battle-tested Dockerfile templates** | **New `dockerfile_templates.py` + `agents.py`** | **~180** | **Fixes 6 critical Docker gaps** |

**Expected impact:** +400-500 points on GlobalBooks (closes stub handler gap, improves test coverage mandate, eliminates Docker failures, increases implementation depth).

#### 1.6 Detail: Fix Loop Intelligence

Port from `super-team/src/super_orchestrator/pipeline.py` lines 5463-5542.

**New functions in `quality_checks.py`:**

```python
# Unfixable violation classification
_UNFIXABLE_PREFIXES = ("DEPLOY-", "ASSET-")

_UNFIXABLE_MESSAGE_PATTERNS = [
    "docker", "dockerfile", "no such file or directory",
    "npm run build", "package-lock.json", "requirements.txt not found",
    "nginx.conf",
]

def is_fixable_violation(v: Violation) -> bool:
    """Returns False for infrastructure/Docker/untargetable violations."""
    if any(v.check.startswith(pfx) for pfx in _UNFIXABLE_PREFIXES):
        return False
    msg_lower = v.message.lower()
    if any(pat in msg_lower for pat in _UNFIXABLE_MESSAGE_PATTERNS):
        return False
    return True

def get_violation_signature(violations: list[Violation]) -> frozenset:
    """Hashable signature for repeat detection between fix passes."""
    return frozenset(
        (v.check, v.file_path, v.message[:50])
        for v in violations
    )

# Module-level signature cache for cross-pass tracking
_previous_signatures: dict[str, frozenset] = {}
```

**Changes to each scan→fix loop in `cli.py`** (11 loops, ~5 lines each):

```python
# Before dispatching fix agent, add:
from .quality_checks import is_fixable_violation, get_violation_signature, _previous_signatures

fixable = [v for v in violations if is_fixable_violation(v)]
if not fixable:
    print_info(f"All {len(violations)} violations are unfixable (infrastructure). Skipping fix pass.")
    break

sig = get_violation_signature(fixable)
if sig == _previous_signatures.get(scan_name):
    print_info(f"Same violations as previous pass. Fix loop not making progress. Stopping.")
    break
_previous_signatures[scan_name] = sig
```

**Estimated: ~80 lines in `quality_checks.py` + ~55 lines across 11 loops in `cli.py`**

#### 1.7 Detail: All-Out Mandates Injection

**Discovery:** `_ALL_OUT_BACKEND_MANDATES` (5,340 chars, ~1,335 tokens) and `_ALL_OUT_FRONTEND_MANDATES` (2,829 chars, ~707 tokens) exist in the super-team's `all-out` git worktree at `.worktrees/all-out/src/super_orchestrator/pipeline.py` lines 1650-1824.

**What they add beyond current v15 standards:**

| Mandate | Current v15 | All-Out Addition |
|---|---|---|
| Entity CRUD | Basic CRUD via orchestrator prompt | Bulk ops, soft delete, import/export (CSV/JSON) |
| Audit trail | Mentioned in prompt | Explicit schema: entity_type, entity_id, action, changes (JSONB before/after), ip_address |
| Validation | "validate input" | Minimum 5 business rules per entity, 422 with field-level details |
| Data quality | Not mentioned | Optimistic locking via version field, DB-level unique constraints |
| State machines | VALID_TRANSITIONS pattern | Separate `state_transition_log` table, event per transition, guard conditions |
| Event handlers | "implement handler" | **Explicit: "REAL business logic — not console.log stubs"**, idempotency guards, retry logic |
| Testing | "write tests" | **Minimum 20 test files**, specific categories (unit, integration, state machine, tenant isolation, auth, pagination, soft delete) |
| Logging | "use logging" | Structured logging, correlation ID propagation, log every request/transition/event |
| Caching | Not mentioned | Redis caching on list endpoints (60s TTL), config data (300s TTL) |
| Admin | Not mentioned | `/admin/stats` and `/admin/health/deep` endpoints |
| Frontend lists | "create list page" | DataTable, server-side pagination, bulk selection, export button, loading/empty/error states |
| Frontend detail | "create detail page" | Related entities, state timeline, audit trail tab, action buttons |
| Frontend forms | "create form" | FormArray for nested items, async validation, calculated fields, unsaved changes guard |
| Dashboard | Not mentioned | KPI cards, Chart.js charts, activity feed, auto-refresh, quick actions |

**Context budget impact:**
- Current v15 total: ~20,639 tokens (10.3% of 200K)
- + Selected 9 cross-service standards (1.4): ~5,414 tokens
- + All-out backend mandate (1.7): ~1,335 tokens
- + All-out frontend mandate (1.7): ~707 tokens
- + Stack instructions (from Phase 2): ~2,950 tokens
- **New total: ~31,045 tokens (15.5% of 200K)** — leaves 84.5% for code generation

**Injection approach:** Add `_ALL_OUT_BACKEND_MANDATES` and `_ALL_OUT_FRONTEND_MANDATES` as constants in `agents.py`. Inject into `build_milestone_execution_prompt()` conditionally based on depth:
- `exhaustive` depth: Always inject (maximizes output)
- `thorough` depth: Inject backend mandates only (skip frontend mandates to save tokens)
- `standard`/`quick` depth: Skip (too much context for smaller tasks)

**Files to modify:** `agents.py` (+200 lines for mandate constants + injection logic)

#### 1.8 Detail: Dockerfile Template Porting

**Evidence from comparison** (full report: `C:\MY_PROJECTS\dockerfile-comparison-20260315.md`):

6 critical/important gaps found in builder-generated Dockerfiles:

| Gap | Severity | Fix |
|---|---|---|
| Frontend missing HEALTHCHECK | CRITICAL | Add to template |
| HEALTHCHECK `start-period` 40s (should be 90s) | CRITICAL | Use battle-tested 90s |
| `curl` for healthcheck (should use urllib/wget) | IMPORTANT | Zero-dep stdlib check |
| Hardcoded Angular dist path | CRITICAL | Dynamic detection pattern |
| `localhost` in HEALTHCHECK (should be 127.0.0.1) | IMPORTANT | Always use IPv4 literal |
| Missing lockfile safety net | CRITICAL | Pre-build lockfile check |

**Best-of-both-worlds Dockerfile templates** (merge standalone's security with super-team's reliability):

New file `dockerfile_templates.py`:

```python
PYTHON_DOCKERFILE = '''\
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \\
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
'''

TYPESCRIPT_DOCKERFILE = '''\
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \\
  CMD wget -qO- http://127.0.0.1:8080/health || exit 1
CMD ["node", "dist/main"]
'''

FRONTEND_DOCKERFILE = '''\
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:stable-alpine
# Auto-detect build output (Angular 17+, React, Vue/Vite)
COPY --from=builder /app/dist/ /tmp/dist/
COPY --from=builder /app/build/ /tmp/build/
RUN if ls /tmp/dist/*/browser/ >/dev/null 2>&1; then \\
      cp -r /tmp/dist/*/browser/* /usr/share/nginx/html/; \\
    elif [ -d /tmp/build ]; then \\
      cp -r /tmp/build/* /usr/share/nginx/html/; \\
    elif [ -d /tmp/dist ]; then \\
      cp -r /tmp/dist/* /usr/share/nginx/html/; \\
    fi && rm -rf /tmp/dist /tmp/build
# SPA routing
RUN printf "server {\\n  listen 80;\\n  location / {\\n    root /usr/share/nginx/html;\\n    try_files \\$uri \\$uri/ /index.html;\\n  }\\n}\\n" > /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \\
  CMD wget -qO- http://127.0.0.1:80/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
'''
```

**Injection:** Add Dockerfile template text to `DOCKERFILE_STANDARD` in the cross-service standards injection (1.4). Also inject into `build_milestone_execution_prompt()` when the milestone involves infrastructure/Docker setup.

**Files:** New `dockerfile_templates.py` (~150 lines), `agents.py` (+30 lines for injection)

### Phase 2: Structured PRD Analysis (2-3 days, ~800 lines of code)

| # | Task | Files | Lines | Impact |
|---|---|---|---|---|
| 2.1 | Create `prd_parser.py` with entity/SM/event extraction | New file | ~400 | Structured domain model |
| 2.2 | Add Phase 0.8 PRD Analysis to pipeline | `cli.py` | ~50 | Pre-parse before decomposition |
| 2.3 | Inject entity assignments into decomposition prompt | `agents.py` | ~40 | Better milestone scoping |
| 2.4 | Inject entity schemas into per-milestone prompts | `agents.py` | ~30 | Precise entity implementation |
| 2.5 | Add stack-specific framework instructions | `agents.py` | ~200 | Better Docker/framework patterns |
| 2.6 | Wire entity list to post-build entity coverage scan | `cli.py` | ~20 | Cross-reference verification |

**Expected impact:** +200-300 points on GlobalBooks (better entity coverage, fewer missed fields/SMs).

### Phase 3: Post-Build Intelligence (2-3 days, ~600 lines of code)

| # | Task | Files | Lines | Impact |
|---|---|---|---|---|
| 3.1 | Add stub completion agent (`_run_stub_completion()`) | `cli.py` | ~120 | Completes remaining stubs |
| 3.2 | Add violation classification system | `quality_checks.py` | ~80 | Smart fix loop |
| 3.3 | Add fix attempt tracking with stop conditions | `cli.py` | ~80 | Prevents wasted compute |
| 3.4 | Extend endpoint XREF with cross-service call verification | `quality_checks.py` | ~100 | Integration verification |
| 3.5 | Add domain-specific integration mandates (accounting) | `agents.py` | ~60 | GL integration enforcement |
| 3.6 | Add API completeness scan | `quality_checks.py` | ~80 | CRUD coverage verification |
| 3.7 | Context window budget monitoring | `agents.py` | ~30 | Prevents prompt overflow |

**Expected impact:** +200-300 points on GlobalBooks (stub completion, better fix passes, integration verification).

### Phase 4: Polish & Optimization (1-2 days, ~200 lines)

| # | Task | Files | Lines | Impact |
|---|---|---|---|---|
| 4.1 | Dockerfile template generation | New file `dockerfile_templates.py` | ~100 | Consistent Dockerfiles |
| 4.2 | Port additional Layer 3 security checks | `quality_checks.py` | ~60 | Secret detection, Docker security |
| 4.3 | Add test completeness scan | `quality_checks.py` | ~50 | Catches services with no tests |

**Expected impact:** +50-100 points (diminishing returns, but improves production readiness).

---

## 8. Expected Impact

### Score Projections (GlobalBooks PRD)

| Phase | Projected Score | Delta | Confidence |
|---|---|---|---|
| **Current v15** | 10,300/12,000 | — | Measured |
| **After Phase 1** | 10,700-10,900 | +400-600 | High |
| **After Phase 2** | 10,900-11,200 | +200-300 | Medium-High |
| **After Phase 3** | 11,100-11,500 | +200-300 | Medium |
| **After Phase 4** | 11,200-11,600 | +50-100 | Medium |
| **Target** | **11,200+/12,000** | **+900+** | — |

Phase 1's higher impact (+400-600, up from +300-400) reflects the three additions:
- Fix loop intelligence saves wasted compute and enables more effective fix passes
- All-out mandates increase implementation depth (bulk ops, audit trail, testing minimums)
- Dockerfile templates eliminate 6 critical Docker gaps that cascade into integration failures

### What Closes Each Gap

| Gap (from Section 2A) | Points Lost | Phase Fix | Expected Recovery |
|---|---|---|---|
| IC event handlers stubbed | ~500 | Phase 1 (prohibition + scan) + Phase 3 (stub completion) | 400-450 |
| No FX rate service | ~250 | Phase 2 (entity injection ensures FX entity) | 100-150 |
| Incomplete AP matching | ~200 | Phase 2 (entity/SM injection) | 100-150 |
| State machine coverage gaps | ~200 | Phase 2 (SM injection with exact transitions) | 150-180 |
| No audit middleware (Python) | ~150 | Phase 1 (testing/handler standards) | 50-100 |
| Bank reconciliation gaps | ~150 | Phase 2 (entity injection) | 50-100 |
| Miscellaneous | ~250 | All phases | 100-150 |

### Cost Impact

The v16 additions should have minimal cost impact:
- **Phase 0.8 PRD Analysis:** ~0 additional LLM cost (pure regex parsing)
- **Standards injection:** ~3,000 tokens added per session (negligible)
- **Post-build scans:** ~0 additional LLM cost (regex scans)
- **Stub completion agent:** ~$5-15 per build (1-3 targeted sessions)
- **Fix pass intelligence:** Saves cost by stopping unfixable loops earlier

**Estimated total cost delta:** +$5-15 per build, with potential savings from smarter fix loops.

### LOC Impact

The v16 additions should increase output LOC:
- **Stub completion:** +500-1000 LOC (real handler implementations)
- **Entity coverage:** +200-500 LOC (missing entity endpoints/tests)
- **Better framework instructions:** Neutral (same LOC, better quality)

---

## Appendix A: File Modification Summary

| File | Current Lines | Estimated Changes | Type |
|---|---|---|---|
| `agents.py` | 2,863 | +600-700 lines | Standards injection, entity injection, all-out mandates, Dockerfile templates, stack instructions |
| `quality_checks.py` | 4,385 | +580-680 lines | 4 new scan functions + fix loop intelligence |
| `cli.py` | 7,363 | +255-355 lines | PRD analysis phase, stub completion, fix loop guards (11 loops × 5 lines) |
| `config.py` | 591 | +20-30 lines | New scan config flags |
| New: `prd_parser.py` | 0 | ~400 lines | Entity/SM/event extraction |
| New: `dockerfile_templates.py` | 0 | ~150 lines | Battle-tested framework templates |
| **Total** | 15,202 | **~2,000-2,300 lines** | |

## Appendix B: Key Function Signatures

```python
# prd_parser.py
def parse_entities(prd_text: str) -> list[dict]:
    """Extract entities with fields, types, relationships."""

def parse_state_machines(prd_text: str) -> list[dict]:
    """Extract state machines with states, transitions, triggers."""

def parse_events(prd_text: str) -> list[dict]:
    """Extract events with source, payload, subscribers."""

def build_domain_model(entities, state_machines, events) -> dict:
    """Build unified domain model with entity→service mapping."""

# quality_checks.py
def run_handler_completeness_scan(project_root: Path) -> list[Violation]:
    """Detect log-only stub handlers."""

def run_entity_coverage_scan(project_root: Path, parsed_entities: list[dict]) -> list[Violation]:
    """Verify PRD entities have models, endpoints, tests."""

def run_api_completeness_scan(project_root: Path) -> list[Violation]:
    """Verify CRUD endpoint coverage for all entities."""

def run_test_completeness_scan(project_root: Path) -> list[Violation]:
    """Verify test file existence and quality per service."""

def classify_violation(v: Violation) -> str:
    """Classify violation as FIXABLE_CODE/FIXABLE_LOGIC/UNFIXABLE_INFRA/UNFIXABLE_ARCH."""

# cli.py
async def _run_prd_analysis(prd_text: str, config: AgentTeamConfig) -> dict:
    """Phase 0.8: Extract structured domain model from PRD."""

async def _run_stub_completion(cwd, config, stubs, prd_text, task, ...) -> float:
    """Complete stub event handlers with real business logic."""
```

## Appendix C: Cross-Service Standards to Inject (Exact Text References)

Standards to inject from `super-team/src/super_orchestrator/cross_service_standards.py`:

| Standard | Lines | Tokens (~) | Inject Into |
|---|---|---|---|
| `HANDLER_COMPLETENESS_STANDARD` | 659-697 | ~500 | System prompt |
| `EVENT_STANDARD` (handler section only) | 253-370 | ~800 | System prompt |
| `BUSINESS_LOGIC_STANDARD` | 755-783 | ~400 | System prompt |
| `STATE_MACHINE_STANDARD` | 593-653 | ~600 | System prompt |
| `TESTING_STANDARD` | 451-497 | ~600 | System prompt |
| `ERROR_RESPONSE_STANDARD` | 408-445 | ~400 | System prompt |
| `DOCKERFILE_STANDARD` | 503-555 | ~500 | Per-milestone prompt (conditional) |
| **Total** | | **~3,800** | ~2% of context |

---

*This plan is based on direct investigation of 38 v15 source files, 120+ super-team source files, the complete GlobalBooks head-to-head comparison, and build artifacts from 4 production runs. Every recommendation cites specific files, functions, and evidence.*

---

## Appendix D: Additional Findings from Deep Investigation

### D.1 Actual Stub Count is 22, Not 21

The deep code analysis reveals **22 total stub handlers** in GlobalBooks standalone (not 21 as stated in HEAD_TO_HEAD_COMPARISON.md):

| Service | Stubs | Events Subscribed |
|---|---|---|
| GL (Python) | 2 | ic_transaction_initiated, ic_elimination_generated |
| IC (Python) | 4 | period_closed, year_end_closed, exchange_rate_updated, asset_transferred |
| Banking (Python) | 5 | ar_payment_applied, ar_invoice_paid, ap_payment_run_completed/failed, period_closed |
| Tax (Python) | 4 | ar_invoice_sent, ap_invoice_approved, ar_credit_memo_issued, period_closed |
| AR (TypeScript) | 1 | gl.period.closed |
| AP (TypeScript) | 1 | gl.period.closed |
| Asset (TypeScript) | 1 | gl.period.closed |
| Reporting (TypeScript) | 4 | asset_depreciation_posted, asset_disposed, ic_elimination_generated, gl.period.closed |

**Pattern:** Every handler subscribes to the correct channel, parses the envelope, logs the payload — then stops. Comments describe intended behavior but no code implements it.

### D.2 Idempotency Infrastructure Exists But Is Never Wired

The `IdempotencyService` class exists in shared libraries (both Python and TypeScript), the `processed_events` database table exists with proper schema (event_id + consumer_service unique constraint), but **no handler ever calls `isProcessed()` or `markProcessed()`**. This means even if stubs were completed, they'd lack duplicate protection.

**V16 action:** When completing stubs, the stub completion agent must also wire idempotency calls.

### D.3 PRD Parser Has 9 Extraction Strategies (Not 8)

The super-team's `prd_parser.py` (2,607 lines) has these extraction strategies in priority order:

0. **Authoritative Entity Table** — Short-circuits if 3+ entities found in a Markdown table with "Entity" + "Owning Service/Fields/Referenced By" columns
1. **Markdown Tables** — Entity-listing and field-level tables
2. **Heading + Bullet Lists** — `### EntityName` followed by `- field: type` bullets
3. **Sentence/Prose** — "The system manages Entity which has field1, field2"
4. **Data Model Section** — Scoped re-run of strategies 1+2 within `## Data Model` sections
5. **Terse/Inline** — "entities: X, Y, Z" or parenthetical lists
6-8. **State Machine Detection** — 5 sub-strategies including arrow notation, prose transitions, and `**Transitions:**` section parsing (Strategy 9 in code)

**Entity filter lists are extensive:**
- `_SECTION_KEYWORDS`: 70+ terms (overview, requirements, architecture, etc.)
- `_GENERIC_SINGLE_WORDS`: 40+ terms (data, status, type, etc.)
- `_HEADING_SUFFIXES`: 30+ PascalCase suffixes (Service, Endpoint, Pipeline, etc.)

### D.4 Cross-Service Standards: 14 Constants, Not 15 Sections

The `cross_service_standards.py` has 14 named constants + 2 frontend-only additions:

| # | Constant | Tokens (~) | Universally Applicable? |
|---|---|---|---|
| 1 | `JWT_STANDARD` | 1,200 | Partially (single-builder JWT is already consistent) |
| 2 | `EVENT_STANDARD` | 1,500 | **YES** — handler prohibition is critical |
| 3 | `ENV_VAR_STANDARD` | 400 | No (single-builder consistency automatic) |
| 4 | `ERROR_RESPONSE_STANDARD` | 400 | YES |
| 5 | `TESTING_STANDARD` | 600 | YES |
| 6 | `DOCKERFILE_STANDARD` | 500 | YES |
| 7 | `DATABASE_STANDARD` | 500 | YES (migration/locking patterns) |
| 8 | `STATE_MACHINE_STANDARD` | 600 | YES |
| 9 | `HANDLER_COMPLETENESS_STANDARD` | 500 | YES |
| 10 | `FRONTEND_UX_STANDARD` | 400 | YES (frontend only) |
| 11 | `BUSINESS_LOGIC_STANDARD` | 400 | **YES** — service layer separation |
| 12 | `API_VERSIONING_STANDARD` | 200 | Partially |
| 13 | `SECURITY_STANDARD` | 400 | YES |
| 14 | `SWAGGER_STANDARD` | 300 | Partially |
| — | `FRONTEND_NO_BACKEND_STANDARD` | 200 | No (not applicable to single builder) |

**Revised injection recommendation:** Inject standards 2, 4, 5, 6, 7, 8, 9, 11, 13 (~4,400 tokens). Skip JWT (1), ENV (3), API_VERSIONING (12), SWAGGER (14), FRONTEND_NO_BACKEND.

### D.5 Recurring Patterns Across ALL 4 Builds

From SupplyForge audit, LedgerPro observations, GlobalBooks comparison, and Bayan analysis:

| Pattern | Frequency | Root Cause | V16 Fix Phase |
|---|---|---|---|
| Event handler stubs | 4/4 builds | Convergence counts subscription as "done" | Phase 1 (prohibition + scan) |
| Docker integration failures | 3/4 builds | All-or-nothing compose, missing lockfiles | Phase 2 (Dockerfile templates) |
| State machine inconsistencies | 3/4 builds | No structured SM injection, 400 vs 409 | Phase 2 (SM extraction + injection) |
| Missing test files for some services | 3/4 builds | No enforcement scan | Phase 1 (test completeness scan) |
| Security decorators missing globally | 3/4 builds | No global auth mandate | Phase 1 (security standard injection) |
| Frontend mock data residuals | 2/4 builds | Frontend milestones before backend | Phase 1 (existing mock scan, already in v15) |

### D.6 Super-Team Post-Build Validator: Most Useful Checks

The `post_build_validator.py` runs 14 checks. The most valuable for v16 (not already in v15's `quality_checks.py`):

1. **`check_event_handler_quality()`** — Scans for handlers with DB operations vs log-only. This is the exact check needed for stub detection.
2. **`check_handler_completeness()`** — Verifies route handlers have input validation, error handling, tenant_id filtering.
3. **`check_test_quality()`** — Checks test files have ≥3 test cases, ≥3 assertions, <50% trivial.
4. **`check_api_completeness()`** — Verifies ≥5 endpoints per service with pagination.

These 4 checks should be ported to `quality_checks.py` as new scan functions.

### D.7 Fix Loop Intelligence from Super-Team

The super-team's `_is_fixable_violation()` function (pipeline.py lines 5463-5502) classifies violations:

**Unfixable prefixes:** `INTEGRATION-`, `INFRA-`, `DOCKER-`, `BUILD-NOSRC`, `L2-INTEGRATION-FAIL`

**Unfixable message patterns:** "docker compose", "docker build", "failed to solve", "dockerfile", "no such file or directory", "npm run build", "failed to start services", "no running services"

**Repeated violation detection:** Creates frozenset signature of `(code, service, message[:50])` tuples. If identical to previous pass → exits immediately ("fixes are not making progress").

This exact logic should be ported to v16's fix pass loop in `cli.py`.
