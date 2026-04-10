# Builder Perfection Plan — v16 → v17

**Goal:** A builder that produces COMPLETE, FULLY-WIRED applications at whatever cost/time needed. 50-200K LOC, every domain complete, every frontend call matching every backend endpoint, every service method tested.

**Root Cause:** The builder's infrastructure is enterprise-grade but its INSTRUCTIONS are shallow and its GATES don't enforce integration. The EVS build scored 88% backend architecture but 34% frontend-backend wiring — the backend and frontend were built as parallel independent streams that never verified integration.

**Approach:** Fix bugs first, then fix instructions (prompts), then add missing gates. No new infrastructure needed — the existing enterprise departments, phase leads, contract engine, and audit system just need to be USED CORRECTLY.

---

## PHASE 1: BUG FIXES (8 bugs)

These are independent, can be parallelized, and unblock everything else.

### 1.1 — pattern_memory.py: SQL parameter binding

**File:** `src/agent_team_v15/pattern_memory.py`
**Function:** `get_fix_recipes()` (~line 483)
**Bug:** Fuzzy match fallback builds N WHERE clauses (`LIKE ?`) from words but appends `limit` as an extra param, giving N+1 params for N placeholders.
**Fix:** Build the full query string with both WHERE and LIMIT placeholders counted together. The LIMIT `?` placeholder must be included in the total count.
```python
# Before (broken):
clauses = " OR ".join("finding_description LIKE ?" for _ in words)
params = [f"%{w}%" for w in words[:5]]
params.append(limit)
rows = self._conn.execute(
    f"SELECT * FROM fix_recipes WHERE {clauses} ORDER BY success_count DESC LIMIT ?",
    params
)

# After (fixed):
clauses = " OR ".join("finding_description LIKE ?" for _ in words)
params: list[Any] = [f"%{w}%" for w in words[:5]]
params.append(limit)  # This is param N+1, for the LIMIT ? which is placeholder N+1
# The query now has len(words[:5]) + 1 placeholders, matching len(params)
```
Actually the issue is that `words` may have more items than `words[:5]` — the clauses are built from ALL words but params only from first 5. **Fix:** Build clauses from `words[:5]` not `words`.
**Impact:** Unblocks cross-run learning. Currently 200+ errors per run.

### 1.2 — cli.py: Contract verification path resolution

**File:** `src/agent_team_v15/cli.py` (~line 6916) and `src/agent_team_v15/verification.py`
**Bug:** Verification scanner looks for `CONTRACTS.json` using a constructed path that doesn't match where the contract generator writes it (`.agent-team/CONTRACTS.json`).
**Fix:** Ensure the verification module uses the same path the contract generator writes to: `Path(cwd) / ".agent-team" / "CONTRACTS.json"`. Check both `cli.py` where the verification is invoked and `verification.py` where the registry loads the file.
**Impact:** Unblocks contract compliance scoring (currently always 0%).

### 1.3 — quality_checks.py: Truth scoring contract_compliance

**File:** `src/agent_team_v15/quality_checks.py` (~line 291)
**Bug:** When contract verification is skipped (due to bug 1.2), `contract_compliance` scores 0.0 instead of computing from the actual CONTRACTS.json that exists.
**Fix:** Make `_score_contract_compliance()` load and validate CONTRACTS.json directly (not depend on the verification registry). If the file exists, compare declared endpoints against actual controller files.
**Impact:** Truth score becomes meaningful (currently stuck at 0.593).

### 1.4 — audit_agent.py: AC extraction regex expansion

**File:** `src/agent_team_v15/audit_agent.py` (~line 377-398)
**Bug:** Four regex patterns only match `AC-N:` format. Many PRDs use different formats (bulleted lists, requirement tables, GIVEN/WHEN/THEN, numbered items without AC prefix).
**Fix:** Add additional patterns:
- `| AC-XXX-NNN |` — table row format (like the EVS PRD uses)
- `- AC-XXX-NNN:` — dash-prefixed with feature prefix
- `GIVEN ... WHEN ... THEN` — BDD format
- `| Status |` followed by PASS/FAIL rows — audit table format
- Fallback: if no AC pattern matches, extract section headers under `## Features` and treat each sub-bullet as an AC
**Impact:** Audit score goes from 0/0 to actual pass/fail counts.

### 1.5 — audit_agent.py: Finding deduplication

**File:** `src/agent_team_v15/audit_agent.py` (~line 1485)
**Bug:** `_cross_cutting_review()` (LLM-based) produces findings that duplicate preliminary findings. Findings are merged without dedup.
**Fix:** After merging `all_findings = deterministic + preliminary + cross_findings`, run a dedup pass that compares findings by `(file_path, category, title_similarity)`. If two findings reference the same file and have >80% title similarity, keep only the one with higher severity.
**Impact:** Finding count stops growing between runs (286 → 310 → should stay stable or decrease).

### 1.6 — skills.py: Float attribute crash

**File:** `src/agent_team_v15/skills.py` (search for `.get()` calls on potentially float values)
**Bug:** `Skill update skipped: 'float' object has no attribute 'get'` — a truth score (float) is being accessed as a dict.
**Fix:** Add type check before `.get()` call: `if isinstance(value, dict): value.get(...)`.
**Impact:** Self-learning skills system works across runs.

### 1.7 — Browser test extraction

**File:** `src/agent_team_v15/browser_test_agent.py` (search for journey/workflow extraction)
**Bug:** `Extracted 0 journeys + 0 feature workflows from PRD` and `Discovered 0 page routes from codebase`.
**Fix:** Investigate why the PRD parser returns 0 journeys. Likely the extraction regex doesn't match the EVS PRD format. May need to handle `## Features` sections as workflow sources.
**Impact:** Browser testing actually runs instead of being skipped.

### 1.8 — Recipe snapshot log spam

**File:** `src/agent_team_v15/pattern_memory.py` (search for "Snapshot cap reached")
**Bug:** `[RECIPE] Snapshot cap reached (50 files)` printed 300+ times, floods output.
**Fix:** Print the message once per run, not once per file. Use a class-level flag `_snapshot_cap_warned`.
**Impact:** Build output becomes readable.

---

## PHASE 2: ATOMIC REQUIREMENTS

**Problem:** Requirements like "TypeORM entities with correct types" cover 30 files in one checkbox. Reviewers mark [x] when files exist, not when implementation is deep.

### 2.1 — Update planner prompt for atomic decomposition

**File:** `src/agent_team_v15/agents.py` — planner agent prompt section
**Change:** Add requirement decomposition rules:

```
## Requirement Granularity Rules

EVERY requirement MUST be ATOMIC — verifiable against a SINGLE file or a SINGLE behavior.

BAD (too coarse):
  - [ ] REQ-M1-005: TypeORM entities with correct types, constraints, indexes

GOOD (atomic):
  - [ ] REQ-M1-005a: Customer entity (src/backend/src/entities/customer.entity.ts) — 13 fields: id UUID PK, email unique not-null, phone unique not-null E.164, phone_raw not-null, name not-null, odoo_partner_id nullable int unique, email_verified default false, status enum(UNVERIFIED,VERIFIED,LINKED,DEACTIVATED) default UNVERIFIED, match_confidence decimal nullable, match_method nullable, language_preference default 'en', created_at auto, updated_at auto
  - [ ] REQ-M1-005b: Session entity (src/backend/src/entities/session.entity.ts) — 8 fields: ...

For FRONTEND requirements, each requirement MUST specify:
  1. The file to create/modify
  2. The API endpoint it calls (method, path, request fields, response fields)
  3. Required UI states: loading, error, empty, success
  4. Input validation rules
  5. Navigation behavior

For BACKEND requirements, each requirement MUST specify:
  1. The file to create/modify
  2. The DTO fields with validators
  3. The service method with expected error cases
  4. The test file that must accompany it (co-located, ≥3 test cases)

MINIMUM REQUIREMENT COUNT:
  - Per PRD feature: 5-15 atomic requirements (not 1-3)
  - Per entity: 1 requirement per entity file
  - Per API endpoint: 1 requirement for controller+service+DTO, 1 for the test
  - Per frontend page: 1 requirement per page with all 5 states specified
```

### 2.2 — Update orchestrator milestone decomposition

**File:** `src/agent_team_v15/agents.py` — ORCHESTRATOR_SYSTEM_PROMPT, Section 7 (Workflow Execution)
**Change:** Add milestone sequencing rules:

```
## Milestone Sequencing (MANDATORY for PRD builds)

Milestones MUST follow this order:

1. FOUNDATION: Project scaffolds, database schema, config, Docker
   - Tests: Schema validation, seed data verification
   
2-N. BACKEND MILESTONES (one per domain): Each backend domain is its OWN milestone
   - Each milestone produces: services + controllers + DTOs + tests
   - Tests are CO-LOCATED, not deferred (each service file gets its .spec.ts)
   - After EACH backend milestone: update ENDPOINT_CONTRACTS.md with exact shapes
   
N+1. CONTRACT FREEZE: Integration agent reads ALL controllers, generates complete ENDPOINT_CONTRACTS.md
   - This is a BLOCKING GATE — frontend milestones CANNOT start until contracts are frozen
   - The contract includes: method, path, auth, request body (field names + types), response body (exact JSON shape with pagination wrapper if applicable), error responses
   
N+2. FRONTEND MILESTONES: Each frontend page/screen is built FROM the frozen contracts
   - Code-writer MUST read ENDPOINT_CONTRACTS.md before writing ANY API call
   - Frontend types/interfaces MUST match contract field names EXACTLY
   - Each page implements: loading state, error state, empty state, success state, form validation
   
N+3. INTEGRATION VERIFICATION: Dedicated cross-layer review
   - For EVERY frontend API call: verify method, path, request fields, response fields against ENDPOINT_CONTRACTS.md
   - ANY mismatch = HARD FAILURE, returned to coding-lead
   
N+4. QUALITY & POLISH: Additional tests, security audit, UI compliance, performance
```

### 2.3 — Planner must read FULL PRD features, not just section headers

**File:** `src/agent_team_v15/agents.py` — planner prompt
**Change:** Add instruction:

```
When decomposing a PRD feature into requirements:
1. Read the ENTIRE feature section including ALL acceptance criteria
2. Each AC becomes AT LEAST one requirement (complex ACs become 2-3 requirements)
3. For each AC, determine: what backend endpoint is needed, what frontend page consumes it, what test verifies it
4. Create requirements for ALL three layers (backend, frontend, test) for each AC
5. If the PRD specifies specific field names, include them VERBATIM in the requirement
6. If the PRD specifies specific behavior (rate limits, validation rules, error messages), include them VERBATIM
```

---

## PHASE 3: IMPLEMENTATION DEPTH

**Problem:** Code-writers produce happy-path-only implementations. "Implement COMPLETE solutions" is vague.

### 3.1 — Add implementation checklists to code-writer prompt

**File:** `src/agent_team_v15/agents.py` — CODE_WRITER_PROMPT
**Change:** Add concrete checklists:

```
## Implementation Depth Checklists (MANDATORY)

### For every BACKEND SERVICE METHOD you write:
  □ Input validation via DTO (class-validator decorators on every field)
  □ Authorization check (guard applied, ownership verified for customer data)
  □ Null/not-found handling (NotFoundException for missing entities)
  □ Try/catch with typed NestJS exceptions (BadRequestException, ConflictException, etc.)
  □ Structured logging (this.logger.log/warn/error with context)
  □ Explicit return type (DTO or typed object, NEVER `any`)
  □ Transaction wrapping for multi-entity writes (queryRunner or @Transaction)

### For every BACKEND CONTROLLER ENDPOINT you write:
  □ All decorators: @Get/@Post/@Put/@Delete, @UseGuards, @HttpCode, @ApiTags
  □ Parameter extraction with types: @Param('id', ParseUUIDPipe), @Query with defaults
  □ Pagination support where applicable (page: number = 1, limit: number = 20)
  □ Consistent response shape: { data: T, meta?: { page, limit, total, totalPages } }
  □ Error responses with correct HTTP status codes

### For every FRONTEND PAGE/SCREEN you write:
  □ LOADING state: spinner or skeleton while data fetches
  □ ERROR state: user-visible error message with retry button
  □ EMPTY state: "No items" message when data array is empty
  □ SUCCESS state: actual data rendered with correct field names FROM CONTRACT
  □ Form validation with error messages on EVERY required field (if page has forms)
  □ Navigation: back button, breadcrumbs, or sidebar highlight

### For every TEST FILE you write:
  □ At least 3 test cases per public method being tested
  □ Happy path test (valid input → expected output)
  □ Error path test (invalid input → correct exception)
  □ Edge case test (empty input, boundary values, null fields)
  □ NO pending tests (no empty it() blocks, no it.skip)
  □ Real assertions (expect().toBe/toEqual/toThrow), not just "no error thrown"

Missing ANY checklist item = the task is NOT complete. The reviewer WILL reject it.
```

### 3.2 — Co-locate tests with implementation

**File:** `src/agent_team_v15/agents.py` — ORCHESTRATOR_SYSTEM_PROMPT (milestone decomposition), CODING_LEAD_PROMPT (task assignment)
**Change:** 

```
## Test Co-location Rule (MANDATORY)

Tests are NOT a separate milestone. Every implementation task includes its test:

TASK-042: Implement AuthService + AuthService tests
  Files: auth.service.ts, auth.service.spec.ts
  The task is COMPLETE only when BOTH files exist.

The coding-lead MUST pair every service file with its .spec.ts in the same task assignment.
The reviewer MUST reject any service file that doesn't have a corresponding .spec.ts.

Minimum test counts by file type:
  - Service file (N public methods): N × 3 test cases minimum
  - Controller file: 1 integration test per endpoint (supertest)
  - Guard/middleware: 2 test cases (allowed + denied)
  - Utility function: 3 test cases per function (happy + error + edge)
```

### 3.3 — Depth scaling by enterprise level

**File:** `src/agent_team_v15/agents.py` — CODE_WRITER_PROMPT
**Change:** Add depth-aware instructions:

```
## Depth-Scaled Implementation

At ENTERPRISE depth (the current build):
  - EVERY service method gets error handling (no exceptions)
  - EVERY endpoint gets pagination (even if "probably won't need it")
  - EVERY UI component gets all 5 states
  - EVERY feature gets ≥5 test cases per method
  - Error messages are user-friendly and i18n-ready
  - Logging covers every branch (happy path, error path, edge case)
  - Input validation is comprehensive (min/max lengths, format checks, enum ranges)

Do NOT cut corners to "finish faster." At enterprise depth, thoroughness > speed.
```

---

## PHASE 4: CONTRACT-FIRST INTEGRATION (The Keystone)

**Problem:** Frontend built independently from backend → 34% wiring score, 13/13 response shape mismatches, 8 request mismatches. This is the single highest-impact fix.

### 4.1 — Add ENDPOINT_CONTRACTS.md generation

**File:** `src/agent_team_v15/agents.py` — add new section to orchestrator prompt, add contract generation instructions to coding-lead/architecture-lead

**New section in ORCHESTRATOR_SYSTEM_PROMPT:**

```
============================================================
SECTION 16: CONTRACT-FIRST INTEGRATION PROTOCOL
============================================================

After ALL backend milestones are complete (all controllers, services, DTOs implemented):

1. Deploy an INTEGRATION AGENT with this task:
   "Read EVERY controller file in the backend. For EACH endpoint, document:
    - HTTP method and full path (including /api/v1 prefix if applicable)
    - Auth requirement (none, jwt-customer, jwt-admin, role-specific)
    - Request: query params (name, type, required?), body fields (name, type, required?, validators)
    - Response 2xx: EXACT JSON structure including pagination wrapper if used
    - Response 4xx/5xx: status code and error shape
    Write the result to .agent-team/ENDPOINT_CONTRACTS.md"

2. This contract document is FROZEN. If the backend changes an endpoint, the contract MUST be updated.

3. The contract is a BLOCKING GATE for frontend milestones:
   - Frontend coding tasks CANNOT be assigned until ENDPOINT_CONTRACTS.md exists
   - Every frontend API call MUST reference a specific contract entry
   - The coding-lead MUST include the relevant contract entries in each frontend task assignment

4. Frontend code-writers receive contract entries in their task:
   "TASK-078: Implement RepairListPage
    CONTRACT: GET /api/v1/repairs
    Auth: JWT (customer)
    Query: { page?: number (default 1), limit?: number (default 20), state?: string }
    Response 200: {
      data: Array<{ id: string, name: string, state: string, status_label: string,
                    vehicle: { license_plate: string, model_name: string },
                    advisor_name: string | null }>,
      meta: { page: number, limit: number, total: number, totalPages: number }
    }
    → Frontend MUST:
    - Use field names EXACTLY as shown (name, not reference; state, not status)
    - Unwrap the {data, meta} pagination wrapper
    - Pass page/limit query params for pagination
    - Type the response interface to match this shape"
```

### 4.2 — Add integration review as mandatory phase

**File:** `src/agent_team_v15/agents.py` — REVIEW_LEAD_PROMPT, add integration review sub-phase

**Add to review-lead prompt:**

```
## Integration Review (MANDATORY after frontend milestones)

After frontend coding is complete, deploy an INTEGRATION REVIEWER with this specific task:

For EVERY file that makes an API call (service files, page files with fetch/axios):
1. Extract the API call: method, URL, request body fields, response field access
2. Open ENDPOINT_CONTRACTS.md and find the matching endpoint
3. Verify EXACT match on:
   □ HTTP method (GET vs POST vs PUT vs DELETE)
   □ URL path (including param names)
   □ Request body field names and types
   □ Response field names accessed (check every .field access against contract)
   □ Pagination handling (does frontend unwrap {data, meta} if contract specifies it?)
   □ Error handling (does frontend handle the documented error status codes?)
4. For ANY mismatch: mark the requirement as [ ] FAIL with:
   - File and line number
   - What frontend sends/reads
   - What the contract specifies
   - Exact fix needed

This review is NON-NEGOTIABLE. Even if all other requirements are [x], the build is NOT COMPLETE
until integration review passes with ZERO mismatches.
```

### 4.3 — Update frontend code-writer to be contract-aware

**File:** `src/agent_team_v15/agents.py` — CODE_WRITER_PROMPT
**Change:** Add contract compliance section:

```
## API Contract Compliance (MANDATORY for frontend files)

Before writing ANY file that makes an API call:
1. Read .agent-team/ENDPOINT_CONTRACTS.md
2. Find the endpoint your code will call
3. Use EXACTLY the field names from the contract — not aliases, not renames
4. If the contract specifies a pagination wrapper ({data: [...], meta: {...}}):
   - Your code MUST unwrap it: `const { data, meta } = await response.json()`
   - Display data from `data`, pagination from `meta`
5. If the contract specifies snake_case field names (e.g., `license_plate`):
   - Use snake_case in your TypeScript interface: `license_plate: string`
   - OR create a mapping layer that converts, but DOCUMENT IT
6. Create a TypeScript interface that EXACTLY matches the contract response shape

If ENDPOINT_CONTRACTS.md doesn't exist yet, DO NOT GUESS. Report BLOCKED and wait.

VIOLATION: Using a field name not in the contract = AUTOMATIC REVIEW FAILURE.
```

---

## PHASE 5: REVIEW OVERHAUL

**Problem:** 200+ requirements reviewed by 2-4 agents who skim. Existence checks pass but depth checks don't.

### 5.1 — Specialized reviewer roles

**File:** `src/agent_team_v15/agents.py` — REVIEW_LEAD_PROMPT
**Change:** Instead of deploying generic code-reviewers, deploy specialized reviewers:

```
## Specialized Review Deployment

Deploy these reviewers IN SEQUENCE (not all at once):

1. BACKEND API REVIEWER (reviews backend controllers + services):
   For each endpoint: verify DTO validation, error handling, auth guard, pagination, test file exists
   
2. INTEGRATION REVIEWER (reviews frontend-backend contract alignment):
   For each frontend API call: verify against ENDPOINT_CONTRACTS.md (method, path, fields, response shape)
   
3. TEST COVERAGE REVIEWER (reviews test files):
   For each service: verify .spec.ts exists, has ≥3 cases per method, no pending tests, real assertions
   
4. UI COMPLETENESS REVIEWER (reviews frontend pages):
   For each page: verify loading/error/empty/success states, form validation, navigation

Each reviewer marks requirements in their domain. A requirement is [x] ONLY if ALL applicable reviewers approve it.
```

### 5.2 — Review checklists per requirement type

**File:** `src/agent_team_v15/agents.py` — CODE_REVIEWER_PROMPT
**Change:** Add specific checklists:

```
## Review Checklists (MANDATORY — check EVERY item)

### Backend Endpoint Requirement:
  □ Controller exists with correct HTTP method + path
  □ Auth guard applied (@UseGuards)
  □ DTO has all required fields with class-validator decorators
  □ Service method has try/catch with typed exceptions
  □ Null/not-found handled (NotFoundException)
  □ Return type is explicit (not any)
  □ .spec.ts exists with ≥3 test cases
  → ALL must pass. Missing ANY item = [ ] FAIL

### Frontend Page Requirement:
  □ Page renders data from correct API endpoint
  □ API call uses EXACT method + path + fields from ENDPOINT_CONTRACTS.md
  □ Response shape correctly unwrapped (pagination, field names)
  □ Loading state with spinner/skeleton
  □ Error state with user-visible message
  □ Empty state when data is empty
  □ Form validation on all required fields (if applicable)
  → ALL must pass. Missing ANY item = [ ] FAIL

### Test Requirement:
  □ Test file exists and imports the correct service/component
  □ ≥3 test cases per public method
  □ Happy path test with expect().toBe/toEqual
  □ Error path test with expect().toThrow or expect(response.status).toBe(4xx)
  □ Edge case test (empty input, boundary values)
  □ NO empty it() blocks or it.skip
  → ALL must pass. Missing ANY item = [ ] FAIL

A requirement with review_cycles >= 1 but no checklist verification = REVIEWER FAILURE.
The orchestrator will re-deploy review if checklists are not evidenced.
```

### 5.3 — Add implementation depth gate (Python enforcement)

**File:** `src/agent_team_v15/quality_checks.py` — add new depth validation functions
**Change:** Add post-orchestration checks that BLOCK convergence:

```python
def check_implementation_depth(cwd: Path) -> list[str]:
    """Check minimum implementation depth. Returns list of violations."""
    violations = []
    
    # 1. Test co-location: every .service.ts should have .service.spec.ts
    service_files = list(cwd.rglob("*.service.ts"))
    for sf in service_files:
        if sf.name.endswith(".spec.ts"):
            continue
        spec = sf.with_suffix("").with_suffix(".spec.ts")
        if not spec.exists():
            violations.append(f"DEPTH-001: Missing test file for {sf.relative_to(cwd)}")
    
    # 2. Error handling: every service should have at least one try/catch
    for sf in service_files:
        if sf.name.endswith(".spec.ts"):
            continue
        content = sf.read_text()
        if "try {" not in content and "try{" not in content:
            violations.append(f"DEPTH-002: No error handling in {sf.relative_to(cwd)}")
    
    # 3. Frontend states: every page.tsx should have loading + error handling
    page_files = list(cwd.rglob("page.tsx"))
    for pf in page_files:
        content = pf.read_text()
        has_loading = "loading" in content.lower() or "spinner" in content.lower() or "skeleton" in content.lower()
        has_error = "error" in content.lower() or "catch" in content.lower()
        if not has_loading:
            violations.append(f"DEPTH-003: No loading state in {pf.relative_to(cwd)}")
        if not has_error:
            violations.append(f"DEPTH-004: No error handling in {pf.relative_to(cwd)}")
    
    return violations
```

---

## PHASE 6: CONVERGENCE & AUDIT IMPROVEMENTS

### 6.1 — Fix truth scoring dimensions

**File:** `src/agent_team_v15/quality_checks.py`
**Change:** Make each dimension compute from real static analysis:

- `contract_compliance`: Count frontend API calls that match ENDPOINT_CONTRACTS.md entries (field-level)
- `test_presence`: Count (service files with .spec.ts) / (total service files), weighted by test case count
- `error_handling`: Count (service methods with try/catch) / (total service methods)
- These are all file-system scans, no LLM needed

### 6.2 — Smarter fix PRD generation

**File:** `src/agent_team_v15/fix_prd_agent.py`
**Change:** Fix PRDs should:
1. Be PRIORITIZED: wiring fixes first (unblock all frontend), then error handling, then tests
2. Include EXACT code snippets showing what to change (not just descriptions)
3. Be LIMITED to 20 findings per run (fix them completely rather than 83 findings shallowly)
4. NEVER include findings that can't be verified by the scanner (avoid ghost fixes)

### 6.3 — Weighted category scoring

**File:** `src/agent_team_v15/quality_checks.py` or `src/agent_team_v15/audit_agent.py`
**Change:** Implement Omar's audit scoring model:

```python
CATEGORY_WEIGHTS = {
    "frontend_backend_wiring": 200,  # 20% — THE most important
    "prd_ac_compliance": 200,        # 20%
    "entity_database": 100,          # 10%
    "business_logic": 150,           # 15%
    "frontend_quality": 100,         # 10%
    "backend_architecture": 100,     # 10%
    "security_auth": 75,             # 7.5%
    "infrastructure": 75,            # 7.5%
}
# Total: 1000 points
# Stop condition: weighted score >= 850/1000 (85%)
```

### 6.4 — AC extraction from tables

**File:** `src/agent_team_v15/audit_agent.py`
**Change:** Add regex pattern for table-based ACs (like EVS PRD format):
```python
# Match: | AC-XXX-NNN | description | ... |
re.compile(r"\|\s*AC-([A-Z]+-\d+)\s*\|\s*(.+?)\s*\|", re.MULTILINE)
```

---

## IMPLEMENTATION ORDER

```
Day 1:  Phase 1 (bug fixes) — 8 independent fixes, parallelize
Day 2:  Phase 2 (atomic requirements) — planner + orchestrator prompt changes  
Day 3:  Phase 3 (implementation depth) — code-writer + test strategy changes
Day 4:  Phase 4 (contract-first integration) — THE keystone change
Day 5:  Phase 5 (review overhaul) — specialized reviewers + checklists + depth gate
Day 6:  Phase 6 (convergence) — truth scoring + fix PRD + weighted scoring
Day 7:  End-to-end test — rebuild EVS Customer Portal, target 85%+ score
```

---

## PHASE 6.5: AGENT COUNT ENFORCEMENT — More Agents, Less Work Per Agent

**Problem:** Enterprise depth says "coding: 8-15 agents, review: 5-10 agents" but this is passed as GUIDANCE, not a mandate. Phase leads routinely deploy 3-4 agents instead of 8-15, because coordinating many agents is harder. Result: each agent handles 50-60 requirements and rushes through them.

**The math:** 200 requirements ÷ 3 code-writers = 67 requirements per writer. That's IMPOSSIBLE to do deeply. Even at 15 writers, it's 13 per writer — much more manageable. The same applies to review: 200 requirements ÷ 2 reviewers = 100 each (skim city). With 10 reviewers, it's 20 each (actually thorough).

### 6.5.1 — Enforce MINIMUM agent counts per phase lead

**File:** `src/agent_team_v15/agents.py` — CODING_LEAD_PROMPT, REVIEW_LEAD_PROMPT
**Change:** Add hard minimums, not suggestions:

```
## Agent Deployment Rules (MANDATORY)

You MUST deploy AT LEAST the minimum number of sub-agents for this depth level.
This is NOT a suggestion — it is a HARD REQUIREMENT enforced by the system.

Current depth: ENTERPRISE
  Coding sub-agents: MINIMUM 8, recommended 12-15
  Review sub-agents: MINIMUM 5, recommended 8-10
  Testing sub-agents: MINIMUM 3, recommended 5

### Work Distribution Rule
NO single code-writer should be assigned more than 15 requirements.
NO single reviewer should be assigned more than 25 requirements.

If you have 200 requirements and deploy 5 code-writers, each gets 40 — TOO MANY.
Deploy 15 code-writers so each gets ~13 — CORRECT.

If you have 200 requirements and deploy 3 reviewers, each gets 67 — TOO MANY.
Deploy 10 reviewers so each gets 20 — CORRECT.

### Scoping Per Agent
Each code-writer gets a FOCUSED scope:
  - "You are assigned to: auth module (auth.service.ts, auth.controller.ts, auth.guard.ts, auth.service.spec.ts)"
  - NOT "You are assigned to: auth, sync, payments, chat, notifications" (too much)

Each reviewer gets a FOCUSED scope:
  - "You review: REQ-M3-001 through REQ-M3-015 (auth module, 15 requirements)"
  - NOT "You review: all 200 requirements" (impossible to be thorough)
```

### 6.5.2 — Update orchestrator prompt to enforce deployment counts

**File:** `src/agent_team_v15/agents.py` — ORCHESTRATOR_SYSTEM_PROMPT / TEAM_ORCHESTRATOR_SYSTEM_PROMPT
**Change:** Make fleet scaling a GATE, not guidance:

```
## Fleet Scaling (MANDATORY — system enforced)

GATE 7 — MINIMUM DEPLOYMENT: You MUST instruct each phase lead to deploy
at least the MINIMUM number of sub-agents. If a phase lead deploys fewer,
RE-INSTRUCT it with explicit count requirements.

The system will check post-orchestration: if coding deployed fewer than
MIN agents for the depth level, a recovery pass will be triggered.

At ENTERPRISE depth with 100+ requirements:
  - Coding: deploy 1 code-writer per 10-15 requirements (minimum 8 writers)
  - Review: deploy 1 reviewer per 15-25 requirements (minimum 5 reviewers)
  - Testing: deploy 1 test-writer per 20-30 requirements (minimum 3 writers)
  
If the project has 200 requirements, deploy ~15 code-writers, ~10 reviewers, ~7 test-writers.
This is MORE expensive but produces DEEP implementations. Cost is NOT a constraint at enterprise depth.
```

### 6.5.3 — Add MAX REQUIREMENTS PER AGENT config

**File:** `src/agent_team_v15/config.py` — add to AgentTeamConfig
**Change:** Add configurable limits:

```python
@dataclass
class AgentScalingConfig:
    max_requirements_per_coder: int = 15      # Force more coders if exceeded
    max_requirements_per_reviewer: int = 25    # Force more reviewers if exceeded
    max_requirements_per_tester: int = 20      # Force more testers if exceeded
    enforce_minimum_counts: bool = True         # Hard-fail if phase lead under-deploys
```

The coding-lead and review-lead prompts should compute: `num_agents = max(min_agents, ceil(total_requirements / max_per_agent))`. This is DYNAMIC scaling — more requirements = more agents automatically.

### 6.5.4 — Python enforcement of agent deployment

**File:** `src/agent_team_v15/quality_checks.py` — add deployment verification
**Change:** After orchestration completes, check whether phase leads actually deployed enough agents. This can be inferred from TASKS.md (how many task assignees exist) and REQUIREMENTS.md (how many unique reviewer IDs appear in the Review Log).

```python
def check_agent_deployment(cwd: Path, depth: str) -> list[str]:
    """Verify phase leads deployed minimum agent counts."""
    violations = []
    min_counts = DEPTH_AGENT_COUNTS[depth]
    
    # Check coding deployment from TASKS.md
    tasks_path = cwd / ".agent-team" / "TASKS.md"
    if tasks_path.exists():
        content = tasks_path.read_text()
        assignees = set(re.findall(r"Assigned to:\s*(\S+)", content))
        min_coders = min_counts["coding"][0]
        if len(assignees) < min_coders:
            violations.append(
                f"DEPLOY-001: Coding phase deployed {len(assignees)} agents, "
                f"minimum for {depth} depth is {min_coders}"
            )
    
    # Check review deployment from REQUIREMENTS.md Review Log
    reqs_path = cwd / ".agent-team" / "REQUIREMENTS.md"
    if reqs_path.exists():
        content = reqs_path.read_text()
        reviewers = set(re.findall(r"\|\s*\d+\s*\|\s*(\S+)\s*\|", content))
        min_reviewers = min_counts["review"][0]
        if len(reviewers) < min_reviewers:
            violations.append(
                f"DEPLOY-002: Review phase deployed {len(reviewers)} reviewers, "
                f"minimum for {depth} depth is {min_reviewers}"
            )
    
    return violations
```

---

## PHASE 7: AUDIT OVERHAUL — Methodology-Driven Auditors

**Problem:** The builder's auditor prompts are ~50 lines of vague instructions ("verify the URL path matches"). Omar's manual audit prompt was ~4,000 words of explicit methodology with exact commands, exact table formats, exact scoring rubrics — and produced a 10x more thorough result (found 21 wiring issues the builder's audit missed).

**Root cause:** The difference between "audit the codebase" and a 20-page audit methodology manual. Same model (Opus 4.6 1M context), drastically different output.

### 7.1 — Replace INTERFACE_AUDITOR_PROMPT with exhaustive wiring methodology

**File:** `src/agent_team_v15/audit_prompts.py` — INTERFACE_AUDITOR_PROMPT
**Change:** Replace the current ~50-line prompt with a ~2000-word methodology that mirrors Omar's Category 1:

```
## INTERFACE AUDITOR — Exhaustive Frontend-Backend Wiring Verification

### Step 1: Extract ALL Frontend API Calls
Use Glob and Grep to find EVERY fetch/axios/API call in the frontend:
- Search for: fetch(, axios., api., /api/v1, useSWR(, useQuery( in all .ts/.tsx/.dart files
- Build a COMPLETE list. Do NOT sample. Do NOT skip admin routes.

### Step 2: Extract ALL Backend Controller Routes  
Use Glob and Grep to find EVERY controller endpoint:
- Search for: @Get, @Post, @Put, @Patch, @Delete in all .controller.ts files
- Include the full path (controller prefix + route decorator)

### Step 3: Build the Route Mapping Table (EVERY ROW MANDATORY)
For EACH frontend API call, produce a row:

| # | Frontend File:Line | Method | URL | Backend Controller.Method | Match? | Issue |
|---|---|---|---|---|---|---|

This table will have 40-100+ rows. That is expected. EVERY API call gets a row.
Score: (matching routes / total routes)

### Step 4: Request Shape Verification (EVERY write endpoint)
For EACH POST/PUT/PATCH/DELETE call:
- Read the frontend code: what fields does it send?
- Read the backend DTO: what fields does it expect (with validators)?
- Compare FIELD BY FIELD: name match? type match? required/optional match?

| Endpoint | Frontend Sends (fields) | Backend DTO (fields) | Match? | Mismatches |
|---|---|---|---|---|

### Step 5: Response Shape Verification (THE MOST CRITICAL CHECK)
For EACH data-fetching endpoint:
- Read the frontend code: what fields does it ACCESS from the response? (look for .field, destructuring, interface definitions)
- Read the backend service: what does the endpoint ACTUALLY return? (trace from controller → service → return value)
- Compare FIELD BY FIELD:
  - Is the response wrapped in {data, meta} or flat?
  - Does frontend expect .reference but backend returns .name?
  - Does frontend expect .status but backend returns .state?
  - Does frontend expect a flat array but backend returns paginated {data: [...], meta: {...}}?
  - Does frontend use camelCase but backend returns snake_case?

| Page | Frontend Accesses | Backend Returns | Match? | Mismatches |
|---|---|---|---|---|

### Step 6: Auth Wiring Verification
- [ ] Frontend sends JWT in Authorization header for every authenticated request
- [ ] Backend guard reads from same location
- [ ] Token refresh on 401 works (detect 401, call refresh, retry)
- [ ] Logout clears tokens on both sides
- [ ] Protected pages redirect to login when no token
- [ ] Admin auth is separate from customer auth
- [ ] Admin guards protect admin routes

### Scoring
- Route existence: 50 × (matching / total)
- Request shapes: 50 × (matching / total write calls)
- Response shapes: 50 × (correct field access / total checked)
- Auth wiring: 50 × (passing checks / 7)
- Total: out of 200 points
```

### 7.2 — Replace REQUIREMENTS_AUDITOR_PROMPT with PRD-first methodology

**File:** `src/agent_team_v15/audit_prompts.py` — REQUIREMENTS_AUDITOR_PROMPT
**Change:** The auditor should check the ORIGINAL PRD acceptance criteria directly — not just REQ-xxx items from REQUIREMENTS.md (which may be incomplete).

```
## REQUIREMENTS AUDITOR — PRD Acceptance Criteria Compliance

### Source of Truth
Read the ORIGINAL PRD file (path provided in task).
Do NOT rely solely on REQUIREMENTS.md — the planner may have omitted ACs.

### Process
For EACH feature section in the PRD:
1. Extract ALL acceptance criteria (AC-xxx items, bullet points, GIVEN/WHEN/THEN, table rows)
2. For EACH acceptance criterion:
   a. Read the AC text carefully — note specific values, field names, behavior
   b. Find the implementation in backend AND frontend code
   c. Determine: PASS (fully implemented), PARTIAL (partially), FAIL (not implemented)
   d. Record evidence: exact file path, line number, what was found vs what was expected

### Output: Per-Feature Tables (EVERY AC gets a row)

### F-001: [Feature Name] (?/? ACs)

| AC | Description | Status | Evidence |
|---|---|---|---|
| AC-XXX-001 | ... | PASS/PARTIAL/FAIL | file:line — what was found |

### Scoring
200 × (PASS_count + 0.5 × PARTIAL_count) / (total ACs - N/A count)
```

### 7.3 — Add COMPREHENSIVE_AUDITOR for cross-cutting verification

**File:** `src/agent_team_v15/audit_prompts.py` — new prompt
**Purpose:** A single auditor that does the COMPLETE audit (like Omar's prompt) as a final quality gate after all specialized auditors run. This catches anything the specialized auditors missed.

This prompt should be ~3000-4000 words and cover all 8 categories from Omar's audit methodology. It runs AFTER the specialized auditors and produces the final scorecard.

### 7.4 — Make auditor prompts scale with context

**File:** `src/agent_team_v15/audit_prompts.py` and `audit_team.py`
**Change:** The current auditor prompts are static. They should be DYNAMIC based on the project:

- For a NestJS+Next.js project: inject NestJS-specific checks (decorators, guards, DTOs)
- For a Flutter project: inject Flutter-specific checks (Riverpod state, GoRouter, Widget tests)
- For a project with Stripe: inject payment-specific checks (webhook verification, idempotency)

The `get_auditor_prompt()` function already accepts parameters — extend it to accept `tech_stack` and inject relevant methodology sections.

---

## PHASE 8: FIX PRD OVERHAUL — Precision Fix Instructions

**Problem:** The builder's fix PRDs are vague. The EVS fix_prd_run2.md had 83 findings listed as brief descriptions. The fix agents received instructions like "Field 'odoo_partner_id' on model 'Customer' looks like a foreign key but has no @relation annotation" — but no exact code showing WHAT to change, WHERE to change it, and HOW.

The result: fix iterations barely improved anything (truth score 0.593 → 0.594 across 3 fix runs). The fix agents didn't know what to do with vague instructions.

### 8.1 — Fix PRD must include EXACT before/after code

**File:** `src/agent_team_v15/fix_prd_agent.py` — `_build_bounded_contexts()`
**Change:** Each fix item must include:

```markdown
**FIX-001: Chat message field name mismatch** [SEVERITY: CRITICAL]

**File:** `src/web/src/lib/api.ts`
**Line:** 437-439

**Current code:**
```typescript
async sendMessage(repairId: string, content: string) {
  return this.post(`/repairs/${repairId}/messages`, { content });
}
```

**Required change:**
```typescript
async sendMessage(repairId: string, body: string) {
  return this.post(`/repairs/${repairId}/messages`, { body });
}
```

**Why:** Backend ChatController uses `@Body('body')` decorator — reads the `body` field from request. Frontend sends `content` which arrives as undefined.

**Verification:** After fix, send a chat message and verify backend receives non-null body field.
```

This is the difference between "field name mismatch" and a precise diff the agent can apply.

### 8.2 — Fix PRD must include response shape corrections with FULL type definitions

For response shape mismatches (the #1 problem from the EVS build):

```markdown
**FIX-007: Repairs list response shape mismatch** [SEVERITY: CRITICAL]

**File:** `src/web/src/app/[locale]/(portal)/repairs/page.tsx`
**Lines:** 28-35

**Current code (WRONG — expects flat array):**
```typescript
const repairs: RepairOrder[] = await api.repairs.list();
repairs.map(r => <div>{r.reference} - {r.status}</div>)
```

**Backend actually returns (from RepairController.listRepairs):**
```json
{
  "data": [
    { "id": "uuid", "name": "RO/2026/0123", "state": "under_repair", "status_label": "In Workshop", ... }
  ],
  "meta": { "page": 1, "limit": 20, "total": 45, "totalPages": 3 }
}
```

**Required change:**
```typescript
interface RepairListResponse {
  data: Array<{
    id: string;
    name: string;           // NOT "reference"
    state: string;          // NOT "status"  
    status_label: string;
    vehicle: {
      license_plate: string;  // NOT "plate"
      model_name: string;     // NOT "make"
    };
    advisor_name: string | null;
  }>;
  meta: { page: number; limit: number; total: number; totalPages: number };
}

const response: RepairListResponse = await api.repairs.list();
const repairs = response.data;  // Unwrap pagination
repairs.map(r => <div>{r.name} - {r.status_label}</div>)
// Also implement pagination using response.meta
```

**Verification:** Load repairs page, verify list renders with correct field values, pagination controls work.
```

### 8.3 — Fix PRD must be SCOPED and PRIORITIZED

**File:** `src/agent_team_v15/fix_prd_agent.py` — `filter_findings_for_fix()`
**Change:** Current MAX_FINDINGS_PER_FIX_CYCLE = 20. This is fine, but the prioritization must be:

1. **WIRING fixes first** (response shape mismatches, request field mismatches) — these unblock ALL frontend
2. **Auth fixes second** (JWT algorithm mismatch, token field names) — these unblock ALL authenticated flows
3. **Missing features third** (NPS survey page, offline mode) — these add functionality
4. **Error handling / tests last** — these improve quality but don't unblock anything

The current priority is by severity (CRITICAL > HIGH > MEDIUM). But a MEDIUM wiring fix has more IMPACT than a HIGH code quality issue. Add an impact-based secondary sort:

```python
_CATEGORY_IMPACT = {
    FindingCategory.INTEGRATION_MISMATCH: 0,   # Highest impact — unblocks frontend
    FindingCategory.CONTRACT_VIOLATION: 1,
    FindingCategory.MISSING_FEATURE: 2,
    FindingCategory.CODE_FIX: 3,
    FindingCategory.TEST_MISSING: 4,
    FindingCategory.STYLE: 5,                   # Lowest impact
}
```

### 8.4 — Fix PRD must reference ENDPOINT_CONTRACTS.md

When the fix PRD addresses wiring issues, it should include the relevant contract entry:

```markdown
**CONTRACT REFERENCE (from ENDPOINT_CONTRACTS.md):**
```
GET /api/v1/repairs
Auth: JWT (customer)
Response 200: { data: RepairOrder[], meta: PaginationMeta }
```
The frontend MUST match this contract EXACTLY. Do not invent field names.
```

### 8.5 — Fix PRD must include regression guards

For each fix, specify what MUST NOT break:

```markdown
**Regression guard:** After modifying api.ts, verify that:
- [ ] Auth login still works (test: POST /auth/magic-link → 200)
- [ ] Dashboard still loads (test: GET /dashboard → 200)
- [ ] All 14 existing test files still pass
```

---

## IMPLEMENTATION ORDER (Updated)

## PHASE 9: LANGUAGE & CONFIG HARDENING — Eliminate Escape Hatches

**Problem:** Agent prompts use "should", "try to", "consider", "may", "if possible" ~40+ times. Under pressure, agents treat these as "skip if inconvenient." Config defaults cap quality with conservative limits (min_test_count=0, pass_rate_gate=0.7, thought_budgets=8-12).

### 9.1 — Replace ALL vague language in agent prompts

**File:** `src/agent_team_v15/agents.py` — EVERY prompt section
**Change:** Global find-and-replace with context-aware upgrades:

| Find | Replace With | Context |
|------|-------------|---------|
| "should" (in rules/requirements) | "MUST" | "Quality violations should be fixed" → "Quality violations MUST be fixed before convergence" |
| "try to" | "MUST" | "Test your fixes if possible" → "MUST test all fixes; document test evidence" |
| "consider" | "document EXACTLY" | "consider how this connects" → "document EXACTLY which modules/endpoints this depends on" |
| "may add" | "MUST add" | "Researchers may add new requirements" → "MUST add a requirement for every research finding" |
| "recommended" | "MANDATORY" | "recommended for NestJS" → "MANDATORY for NestJS projects" |
| "Be thorough" | specific number | "Be thorough" → "Produce minimum 5 findings per research query" |
| "if possible" | remove entirely | "Test if possible" → "Test" |

Also add QUANTIFIED expectations where currently vague:
- "Reviews must be thorough" → "Reviewers MUST reject ≥40% of items on first pass; if acceptance rate >70% on first pass, review is insufficient"
- "Be HARSH" → "Mark FAIL on ANY item missing: error handling, tests, or loading states"
- "comprehensive security audit" → "Check ALL 15 OWASP categories; document pass/fail on each"

### 9.2 — Create "max quality" config profile for enterprise depth

**File:** `src/agent_team_v15/config.py` — `apply_depth_quality_gating()` enterprise section
**Change:** When depth=enterprise, auto-apply all maximum quality settings:

```python
elif depth == "enterprise":
    # ... existing enterprise gates ...
    
    # MAX QUALITY OVERRIDES (enterprise = no compromises)
    _gate("verification.min_test_count", 10, config.verification, "min_test_count")
    _gate("convergence.max_cycles", 25, config.convergence, "max_cycles")
    _gate("convergence.escalation_threshold", 6, config.convergence, "escalation_threshold")
    _gate("audit_team.score_healthy_threshold", 95.0, config.audit_team, "score_healthy_threshold")
    _gate("audit_team.score_degraded_threshold", 85.0, config.audit_team, "score_degraded_threshold")
    _gate("audit_team.fix_severity_threshold", "LOW", config.audit_team, "fix_severity_threshold")
    _gate("audit_team.max_reaudit_cycles", 5, config.audit_team, "max_reaudit_cycles")
    _gate("pseudocode.enabled", True, config.pseudocode, "enabled")
    _gate("pseudocode.edge_case_minimum", 5, config.pseudocode, "edge_case_minimum")
    _gate("e2e_testing.max_fix_retries", 8, config.e2e_testing, "max_fix_retries")
    _gate("browser_testing.max_fix_retries", 8, config.browser_testing, "max_fix_retries")
    _gate("browser_testing.e2e_pass_rate_gate", 0.95, config.browser_testing, "e2e_pass_rate_gate")
    _gate("post_orchestration_scans.max_scan_fix_passes", 5, config.post_orchestration_scans, "max_scan_fix_passes")
    _gate("tracking_documents.coverage_completeness_gate", 0.95, config.tracking_documents, "coverage_completeness_gate")
    _gate("tech_research.max_queries_per_tech", 8, config.tech_research, "max_queries_per_tech")
    _gate("tech_research.max_expanded_queries", 6, config.tech_research, "max_expanded_queries")
    _gate("runtime_verification.startup_timeout_s", 180, config.runtime_verification, "startup_timeout_s")
    _gate("runtime_verification.max_fix_rounds_per_service", 5, config.runtime_verification, "max_fix_rounds_per_service")
    _gate("runtime_verification.max_total_fix_rounds", 10, config.runtime_verification, "max_total_fix_rounds")
    _gate("runtime_verification.max_fix_budget_usd", 300.0, config.runtime_verification, "max_fix_budget_usd")
    _gate("integration_gate.blocking_mode", True, config.integration_gate, "blocking_mode")
```

### 9.3 — Raise Sequential Thinking budgets at enterprise depth

**File:** `src/agent_team_v15/config.py` — OrchestratorSTConfig
**Change:** Enterprise thought budgets should be 2x the defaults:

```python
# Enterprise-specific thought budgets (override in apply_depth_quality_gating)
if depth == "enterprise":
    config.orchestrator_st.thought_budgets = {
        1: 20,   # Pre-run strategy (was 8)
        2: 25,   # Architecture checkpoint (was 10)
        3: 25,   # Convergence reasoning (was 12)
        4: 20,   # Completion verification (was 8)
        5: 20,   # Pseudocode review (was 8)
    }
```

### 9.4 — Enforce GATE 1 and GATE 3 in Python (not just prompts)

**File:** `src/agent_team_v15/quality_checks.py` or `cli.py`
**Change:** Add post-orchestration verification:

```python
def verify_review_integrity(cwd: Path) -> list[str]:
    """Verify GATE 1 (only reviewers mark [x]) and GATE 3 (review_cycles incremented)."""
    violations = []
    reqs_path = cwd / ".agent-team" / "REQUIREMENTS.md"
    if not reqs_path.exists():
        return violations
    
    content = reqs_path.read_text()
    
    # Check: every [x] item must have review_cycles >= 1
    checked_items = re.findall(r"- \[x\] (REQ-\S+).*?(review_cycles:\s*(\d+))?", content)
    for item_id, _, cycles in checked_items:
        if not cycles or int(cycles) < 1:
            violations.append(f"GATE-001: {item_id} marked [x] but review_cycles=0 — no reviewer verified it")
    
    return violations
```

---

## IMPLEMENTATION ORDER (Final)

```
Day 1:   Phase 1 (bug fixes) — 8 independent fixes, parallelize
Day 2:   Phase 2 (atomic requirements) — planner + orchestrator prompt changes
Day 3:   Phase 3 (implementation depth) — code-writer + test co-location
Day 4:   Phase 4 (contract-first integration) — THE keystone change
Day 5:   Phase 5 (review overhaul) — specialized reviewers + checklists
         Phase 6 (convergence) — truth scoring + weighted scoring
Day 6:   Phase 6.5 (agent counts) — minimum agents, max reqs per agent
         Phase 7 (audit overhaul) — 2000-4000 word methodology prompts
Day 7:   Phase 8 (fix PRD overhaul) — precise before/after, contract refs
         Phase 9 (language & config hardening) — eliminate escape hatches, max quality defaults
Day 8-9: End-to-end test — rebuild EVS Customer Portal, target 88%+ score
```

---

## EXPECTED OUTCOME

After these changes, the EVS Customer Portal rebuild should produce:

| Category | Before (v16) | Target (v17) |
|----------|-------------|-------------|
| Frontend-Backend Wiring | 34% | **90%+** |
| PRD AC Compliance | 60% | **85%+** |
| Entity & Database | 93% | **95%+** |
| Business Logic | 81% | **90%+** |
| Frontend Quality | 68% | **85%+** |
| Backend Architecture | 88% | **92%+** |
| Security & Auth | 64% | **80%+** |
| Infrastructure | 73% | **85%+** |
| **TOTAL** | **66%** | **88%+** |

The app should have:
- 40-60K+ LOC (vs 19K)
- 80+ test files (vs 14)
- 0 response shape mismatches (vs 13)
- 0 request shape mismatches (vs 8)
- Every service method with error handling
- Every frontend page with all 5 states
- Complete ENDPOINT_CONTRACTS.md verified against both layers

Cost estimate: $150-300 (vs $71 for a 66% result). Worth it.
