# Agent-Team Builder Perfection Plan — Exhaustive Implementation

> **Target:** Transform the builder from 66% (EVS audit) to 88%+ on the same build.
> **Codebase:** `C:\MY_PROJECTS\agent-team-v15\`
> **Plan:** `BUILDER_PERFECTION_PLAN.md` (9 phases, 1,103 lines)
> **Constraint:** ZERO regressions on the existing 459-test suite.

---

## Agent Team Structure — Parallel Execution

You MUST execute this implementation using a coordinated agent team. Create a team and spawn
the following agents. Maximize parallelism where possible.

### Team Composition (9 agents)

| Agent Name | Type | Role |
|------------|------|------|
| `architect` | `superpowers:code-reviewer` | Phase 1 — Read entire codebase, map every file the plan touches, produce ARCHITECTURE_REPORT.md with exact insertion points |
| `bug-fixer` | `general-purpose` | Phase 2A — Fix all 8 bugs from Phase 1 of the plan (pattern_memory, cli, quality_checks, audit_agent, skills, browser_test_agent, recipe log) |
| `prompt-engineer` | `general-purpose` | Phase 2B — Implement Phases 2, 3, 9 (atomic requirements, implementation depth checklists, language hardening) — all changes in agents.py prompts |
| `contract-architect` | `general-purpose` | Phase 2C — Implement Phase 4 (contract-first integration protocol) — the KEYSTONE change. ENDPOINT_CONTRACTS.md generation, blocking gate, frontend code-writer instructions |
| `review-engineer` | `general-purpose` | Phase 2D — Implement Phase 5 (review overhaul) — specialized reviewer roles, review checklists, implementation depth gate in quality_checks.py |
| `convergence-engineer` | `general-purpose` | Phase 2E — Implement Phases 6, 6.5 (convergence improvements, agent count enforcement) — truth scoring, weighted scoring, fix PRD prioritization, agent scaling config |
| `audit-engineer` | `general-purpose` | Phase 2F — Implement Phase 7 (audit overhaul) — replace auditor prompts with 2000-4000 word methodology, AC extraction regex, comprehensive auditor |
| `fix-prd-engineer` | `general-purpose` | Phase 2G — Implement Phase 8 (fix PRD overhaul) — before/after code diffs, response shape corrections, scoped prioritization, contract references, regression guards |
| `test-engineer` | `general-purpose` | Phase 3 — Write ALL tests for every change, run full suite, diagnose and fix failures, iterate until green |

### Coordination Flow

```
Wave 1 (solo): architect reads entire codebase
    │
    Produces: ARCHITECTURE_REPORT.md (every file, function, insertion point the plan touches)
    │
Wave 2 (parallel — 7 agents simultaneously):
    │
    ├── bug-fixer: 8 bug fixes (pattern_memory.py, cli.py, quality_checks.py, audit_agent.py, skills.py, browser_test_agent.py)
    ├── prompt-engineer: agents.py prompt changes (Phases 2, 3, 9)
    ├── contract-architect: contract-first integration (Phase 4) — agents.py + new quality checks
    ├── review-engineer: review overhaul (Phase 5) — agents.py + quality_checks.py
    ├── convergence-engineer: convergence + agent counts (Phases 6, 6.5) — quality_checks.py + config.py + audit_agent.py + fix_prd_agent.py
    ├── audit-engineer: audit methodology (Phase 7) — NEW audit_prompts.py + audit_agent.py
    └── fix-prd-engineer: fix PRD precision (Phase 8) — fix_prd_agent.py
    │
    All 7 read ARCHITECTURE_REPORT.md first. File scopes DO NOT OVERLAP (see Critical Rules below).
    │
Wave 3 (solo): test-engineer writes + runs all tests
    │
Wave 4 (sequential): test-engineer runs full suite, fixes failures, iterates until green
    │
Wave 5: You (team lead) collect all results → produce final report
```

### Agent Instructions

- **You are team lead.** Create tasks in the task list for each agent. Assign via TaskUpdate.
- **architect runs first and alone.** It must finish before anyone else starts. Its report is the single source of truth for integration points.
- **All 7 Wave 2 agents run simultaneously.** They work on DIFFERENT files so no conflicts (see file ownership below).
- **test-engineer waits for ALL Wave 2 agents** before starting. It receives all implementation details and writes tests.
- **After Wave 3 completes,** test-engineer runs `pytest tests/ -v --tb=short` and iterates on failures until all pass.
- **Shut down all agents** after Wave 4 completes. Collect results and write the final report yourself.

### Critical Rules — File Ownership (NO CONFLICTS)

Each Wave 2 agent OWNS specific files. NO other agent may modify these files.

| Agent | Files OWNED (can create/edit) | Files READ-ONLY |
|-------|-------------------------------|-----------------|
| `bug-fixer` | `pattern_memory.py`, `cli.py` (verification path only), `skills.py`, `browser_test_agent.py`, `verification.py` (contract path only) | All others |
| `prompt-engineer` | `agents.py` — ONLY sections: planner prompt, code-writer prompt, orchestrator milestone sequencing, coding-lead prompt, language hardening (Phase 9 replacements) | All others |
| `contract-architect` | `agents.py` — ONLY sections: NEW Section 16 (contract-first protocol), code-writer contract instructions, coding-lead contract gate. Also: NEW file `contract_generator.py` if needed | All others |
| `review-engineer` | `agents.py` — ONLY sections: review-lead prompt, code-reviewer prompt. Also: `quality_checks.py` — ONLY functions: `check_implementation_depth()`, `verify_review_integrity()` | All others |
| `convergence-engineer` | `quality_checks.py` — ONLY functions: truth scoring, weighted scoring, `check_agent_deployment()`. Also: `config.py` — agent scaling config, enterprise depth overrides. Also: `fix_prd_agent.py` — prioritization logic, MAX_FINDINGS. Also: `audit_agent.py` — AC extraction regex ONLY | All others |
| `audit-engineer` | EXISTING file: `audit_prompts.py` (REPLACE all auditor methodology prompts — file already exists with short prompts). Also: `audit_agent.py` — ONLY: prompt loading, comprehensive auditor integration, tech-stack-aware prompt selection. Also: `audit_team.py` — ONLY if prompt loading changes require it | All others |
| `fix-prd-engineer` | `fix_prd_agent.py` — ONLY: `_build_bounded_contexts()`, fix item formatting, before/after code generation, contract references, regression guards | All others |

**CONFLICT RESOLUTION for agents.py:** Three agents modify `agents.py` but in DIFFERENT sections. The architect MUST map exact line ranges for each section so agents don't collide. If two agents need to touch the same function, the architect must designate ONE owner and have the other agent write their changes to a separate file that the owner integrates.

**CONFLICT RESOLUTION for quality_checks.py:** Two agents modify this file but in DIFFERENT functions. The architect MUST map which functions belong to which agent.

**CONFLICT RESOLUTION for audit_agent.py:** Two agents modify this file. convergence-engineer owns AC extraction regex ONLY. audit-engineer owns everything else in this file.

**CONFLICT RESOLUTION for fix_prd_agent.py:** Two agents modify this file. convergence-engineer owns prioritization/MAX_FINDINGS. fix-prd-engineer owns formatting/content generation.

---

# Builder Perfection Plan — Implementation Specification

## Background — Why This Exists

The EVS Customer Portal was built by the v16 pipeline and scored 660/1000 (66%) on a comprehensive audit. The audit revealed a devastating pattern: **88% backend architecture but 34% frontend-backend wiring.** The builder produced a correct backend and a plausible-looking frontend that were completely disconnected from each other.

### Failure 1: Systematic Response Shape Mismatch
The backend consistently returns `{data: [...], meta: {page, limit, total, totalPages}}`. The frontend consistently expects flat arrays. 13 out of 13 data endpoints have mismatched response shapes. Every list page renders empty. Root cause: the frontend was built from PRD descriptions, not from actual backend responses. No shared type contract existed between layers.

### Failure 2: Field Naming Convention Mismatch
The backend uses `license_plate`, `amount_total`, `payment_state`, `sender_type`. The frontend uses `plate`, `total`, `status`, `fromCustomer`. Neither side adapted to the other. 21 field name mismatches across the application. Root cause: no `ENDPOINT_CONTRACTS.md` was generated from the backend for the frontend to consume.

### Failure 3: Request Shape Mismatch
8 write endpoints have mismatched request bodies. Frontend sends `{content}` but backend reads `body`. Frontend sends `{score, feedback}` but backend expects `{nps_score, experience_rating, service_factor, comment}`. Frontend omits required fields (`make`, `model` on vehicle creation). Root cause: frontend code-writers never read the backend DTOs.

### Failure 4: Shallow Implementation Depth
15,192 total LOC with only 14 test files. Services have no error handling. Frontend pages have no loading/error/empty states. Rate limiting is global instead of per-endpoint. Admin JWT uses wrong algorithm with hardcoded secret. Root cause: requirements are too coarse (one checkbox covers 30 files), code-writers lack implementation checklists, reviewers skim instead of verifying depth.

### Failure 5: Audit System Missed Everything
The builder's own audit scored the build much higher than the manual audit. The auditor prompts are 50 lines of vague instructions. The manual audit prompt was 4,000 words of explicit methodology. Same model, 10x different thoroughness. Root cause: audit methodology prompts are inadequate.

## What We're Building

9 phases of improvements to the builder pipeline. No new infrastructure — the existing modules just need correct instructions, proper gates, and thorough enforcement.

**Category A: Bug Fixes (8 items)**
Independent code fixes in pattern_memory.py, cli.py, quality_checks.py, audit_agent.py, skills.py, browser_test_agent.py. Each is a specific code change.

**Category B: Prompt Engineering (3 phases — Phases 2, 3, 9)**
Changes to agents.py: atomic requirement decomposition rules, implementation depth checklists, milestone sequencing, co-located test rules, enterprise depth scaling, language hardening (should→MUST), quantified expectations.

**Category C: Contract-First Integration (Phase 4 — THE KEYSTONE)**
The single highest-impact change. After backend milestones complete, an integration agent generates `ENDPOINT_CONTRACTS.md` from actual controllers. Frontend milestones are BLOCKED until contracts exist. Frontend code-writers receive exact contract entries. Violation = automatic review failure.

**Category D: Review & Quality Gates (Phases 5, 6, 6.5)**
Specialized reviewers (backend API, integration, test coverage, UI completeness), review checklists per requirement type, implementation depth gate in Python, truth scoring fixes, weighted category scoring, agent count enforcement with Python verification.

**Category E: Audit & Fix Overhaul (Phases 7, 8)**
Replace 50-line auditor prompts with 2000-4000 word methodology prompts. Add AC extraction for table formats. Add comprehensive cross-cutting auditor. Fix PRDs include exact before/after code diffs, full type definitions, contract references, regression guards, impact-based prioritization.

---

## PHASE 1: ARCHITECTURE DISCOVERY (architect)

Before implementing ANYTHING, the architect must read the codebase and produce
ARCHITECTURE_REPORT.md answering these questions:

### 1A: agents.py Prompt Map
- Read `src/agent_team_v15/agents.py` end to end
- This file is ~3000-5000 lines. It contains ALL agent prompts.
- Document the EXACT line ranges for EVERY prompt section:
  - ORCHESTRATOR_SYSTEM_PROMPT: lines X-Y
  - TEAM_ORCHESTRATOR_SYSTEM_PROMPT: lines X-Y
  - PLANNER prompt section: lines X-Y
  - CODING_LEAD_PROMPT: lines X-Y
  - CODE_WRITER_PROMPT: lines X-Y
  - REVIEW_LEAD_PROMPT: lines X-Y
  - CODE_REVIEWER_PROMPT: lines X-Y
  - ARCHITECTURE_LEAD_PROMPT: lines X-Y
  - Every other prompt section with name and line range
- For each prompt: document what instructions currently exist for:
  - Requirement granularity (atomic vs coarse)
  - Implementation depth expectations
  - Test co-location rules
  - Contract/integration references
  - Review checklists
  - Language strength ("should" vs "MUST")
- Count every instance of "should", "try to", "consider", "may", "if possible", "recommended", "Be thorough" — document the line number of each

### 1B: quality_checks.py Function Map
- Read `src/agent_team_v15/quality_checks.py` end to end
- Document every function: name, line range, what it does, what it returns
- Specifically identify:
  - `_score_contract_compliance()` — current implementation, what it checks
  - Truth scoring function — what dimensions it computes, how
  - Any existing depth/deployment checks
- Document WHERE new functions should be inserted (alphabetical? end of file? grouped by category?)

### 1C: config.py Structure
- Read `src/agent_team_v15/config.py` end to end
- Document all dataclass configurations
- Document `apply_depth_quality_gating()` — what each depth level sets
- Document the enterprise section specifically — what's already there, what's missing from the plan
- Identify WHERE AgentScalingConfig should be added
- Identify WHERE thought budget overrides should go

### 1D: audit_agent.py Architecture
- Read `src/agent_team_v15/audit_agent.py` end to end
- Document AC extraction: what regex patterns exist, what they match, what they miss
- Document finding generation: how deterministic vs LLM findings are created
- Document deduplication: what exists currently (if anything)
- Document prompt loading: how auditor prompts are currently injected
- Identify WHERE new comprehensive auditor integrates
- Identify WHERE tech-stack-aware prompt selection should go

### 1E: fix_prd_agent.py Architecture
- Read `src/agent_team_v15/fix_prd_agent.py` end to end
- Document `_build_bounded_contexts()`: how fix items are currently formatted
- Document `filter_findings_for_fix()`: current prioritization logic
- Document MAX_FINDINGS_PER_FIX_CYCLE: current value and where it's set
- Identify WHERE before/after code diffs should be generated
- Identify WHERE contract references should be injected
- Identify WHERE regression guards should be added

### 1F: pattern_memory.py Bug Location
- Read `src/agent_team_v15/pattern_memory.py`
- Find `get_fix_recipes()` (~line 483)
- Document the EXACT bug: how `words` vs `words[:5]` creates parameter count mismatch
- Document the EXACT fix
- Find "Snapshot cap reached" log message — document where the loop is and how to add the `_snapshot_cap_warned` flag

### 1G: cli.py Verification Path Bug
- Read `src/agent_team_v15/cli.py` (~line 6916) and `verification.py`
- Document where CONTRACTS.json is WRITTEN (by contract generator)
- Document where CONTRACTS.json is READ (by verification scanner)
- Document the PATH MISMATCH between write and read

### 1H: Existing Test Suite
- Run `pytest tests/ -v --tb=short 2>&1 | tail -50`
- Document: total tests, passing, failing, test file names
- This is the REGRESSION BASELINE — these exact counts must be preserved

### 1I: File Conflict Map
- For `agents.py`: map exact line ranges that each Wave 2 agent will modify. Ensure ZERO overlap.
- For `quality_checks.py`: map exact functions that each agent owns
- For `audit_agent.py`: map exact sections for convergence-engineer vs audit-engineer
- For `fix_prd_agent.py`: map exact sections for convergence-engineer vs fix-prd-engineer

### Output
ARCHITECTURE_REPORT.md in the project root with all findings, exact file locations,
exact function names, exact line ranges, exact integration points, and the file conflict map.
This is the blueprint for Wave 2.

---

## PHASE 2A: BUG FIXES (bug-fixer)

Read ARCHITECTURE_REPORT.md first. Fix all 8 bugs EXACTLY as specified in the plan.

### Bug 1: pattern_memory.py SQL parameter binding
**What's broken:** `get_fix_recipes()` builds N WHERE clauses from `words` but params from `words[:5]`, creating N params for N clauses but then appending `limit` as param N+1. If `len(words) > 5`, clauses > params.
**Fix:** Build clauses from `words[:5]` (not `words`), ensuring clause count matches param count. Then append `limit`.
**Test:** Call `get_fix_recipes()` with a 10-word query — should not throw "incorrect number of bindings."

### Bug 2: cli.py contract verification path
**What's broken:** Verification scanner looks for CONTRACTS.json at wrong path.
**Fix:** Use `Path(cwd) / ".agent-team" / "CONTRACTS.json"` in both write and read locations.
**Test:** After fix, verification should find and parse CONTRACTS.json if it exists.

### Bug 3: quality_checks.py contract compliance scoring
**What's broken:** When verification is skipped (due to Bug 2), contract_compliance scores 0.0.
**Fix:** `_score_contract_compliance()` loads CONTRACTS.json directly and validates against actual controller files.
**Test:** With a valid CONTRACTS.json, score should be > 0.0.

### Bug 4: audit_agent.py AC extraction regex
**What's broken:** Only matches `AC-N:` format. Misses table rows, dash-prefixed, GIVEN/WHEN/THEN.
**Fix:** Add patterns for: `| AC-XXX-NNN |` (table), `- AC-XXX-NNN:` (dash), `GIVEN...WHEN...THEN`, section bullets under `## Features`.
**Test:** Extract ACs from the EVS PRD format — should find 119 (not 0).

### Bug 5: audit_agent.py finding deduplication
**What's broken:** `_cross_cutting_review()` duplicates preliminary findings. Finding count grows between runs.
**Fix:** After merging all findings, dedup by `(file_path, category, title_similarity > 80%)`. Keep higher severity.
**Test:** Run audit twice — finding count should stabilize, not grow.

### Bug 6: skills.py float attribute crash
**What's broken:** A truth score (float) is accessed with `.get()` (dict method).
**Fix:** Add `isinstance(value, dict)` check before `.get()` call.
**Test:** Skill update with float truth score should not crash.

### Bug 7: browser_test_agent.py extraction failure
**What's broken:** Extracts 0 journeys and 0 page routes from PRD/codebase.
**Fix:** Investigate extraction regex. Handle `## Features` sections as workflow sources. Handle Next.js App Router page discovery.
**Test:** Extract from EVS PRD — should find >0 journeys and >0 routes.

### Bug 8: pattern_memory.py log spam
**What's broken:** "Snapshot cap reached (50 files)" printed 300+ times.
**Fix:** Add class-level `_snapshot_cap_warned = False` flag. Print once, set True.
**Test:** Run with >50 files — message appears exactly once.

---

## PHASE 2B: PROMPT ENGINEERING (prompt-engineer)

Read ARCHITECTURE_REPORT.md first. Modify agents.py in the EXACT sections identified by the architect.

### Item 1: Atomic Requirement Decomposition (Plan Phase 2.1)

**Inject into:** The planner prompt section of agents.py (exact lines from ARCHITECTURE_REPORT.md)

Add the complete "Requirement Granularity Rules" block from the plan. This includes:
- BAD vs GOOD examples showing coarse vs atomic requirements
- Frontend requirements must specify: file, API endpoint (method, path, request, response), UI states (loading, error, empty, success), validation, navigation
- Backend requirements must specify: file, DTO fields with validators, service method with error cases, test file with ≥3 cases
- Minimum requirement counts: 5-15 per PRD feature, 1 per entity, 1 per API endpoint, 1 per frontend page

### Item 2: Milestone Sequencing (Plan Phase 2.2)

**Inject into:** The orchestrator prompt section — workflow execution or milestone planning area

Add the complete milestone sequencing rules:
1. FOUNDATION milestone (scaffolds, schema, config, Docker)
2. Backend milestones (one per domain, update ENDPOINT_CONTRACTS.md after each)
3. CONTRACT FREEZE gate (blocking — frontend cannot start without contracts)
4. Frontend milestones (built FROM frozen contracts)
5. INTEGRATION VERIFICATION (cross-layer review)
6. QUALITY & POLISH

### Item 3: Planner PRD Reading Depth (Plan Phase 2.3)

**Inject into:** Planner prompt section

Add: "Read the ENTIRE feature section including ALL acceptance criteria. Each AC becomes AT LEAST one requirement. Complex ACs become 2-3. For each AC, determine backend endpoint, frontend page, and test."

### Item 4: Implementation Depth Checklists (Plan Phase 3.1)

**Inject into:** CODE_WRITER_PROMPT section

Add the COMPLETE implementation checklists:
- Backend service method checklist (7 items: validation, auth, null handling, try/catch, logging, return type, transactions)
- Backend controller checklist (5 items: decorators, params, pagination, response shape, error codes)
- Frontend page checklist (6 items: loading, error, empty, success, validation, navigation)
- Test file checklist (6 items: 3 cases per method, happy path, error path, edge case, no pending, real assertions)
- "Missing ANY checklist item = the task is NOT complete"

### Item 5: Test Co-Location Rule (Plan Phase 3.2)

**Inject into:** ORCHESTRATOR_SYSTEM_PROMPT (milestone decomposition) AND CODING_LEAD_PROMPT (task assignment)

Add: "Tests are NOT a separate milestone. Every implementation task includes its test. TASK-042: Implement AuthService + AuthService tests. The task is COMPLETE only when BOTH files exist."

Minimum test counts: service (N methods × 3), controller (1 integration per endpoint), guard (2 cases), utility (3 per function).

### Item 6: Enterprise Depth Scaling (Plan Phase 3.3)

**Inject into:** CODE_WRITER_PROMPT section

Add: "At ENTERPRISE depth: EVERY service method gets error handling, EVERY endpoint gets pagination, EVERY UI component gets all 5 states, EVERY feature gets ≥5 test cases per method. Do NOT cut corners."

### Item 7: Language Hardening (Plan Phase 9.1)

**Apply to:** EVERY prompt section in agents.py

Global find-and-replace with context awareness:
- "should" (in rules/requirements) → "MUST"
- "try to" → "MUST"
- "consider" → "document EXACTLY"
- "may add" → "MUST add"
- "recommended" → "MANDATORY"
- "Be thorough" → specific number (e.g., "Produce minimum 5 findings")
- "if possible" → remove entirely

Add quantified expectations:
- "Reviews must be thorough" → "Reviewers MUST reject ≥40% of items on first pass"
- "comprehensive security audit" → "Check ALL 15 OWASP categories; document pass/fail on each"

**WARNING:** Do NOT blindly replace every "should" — some are in explanatory text, not rules. Only replace "should" that appears in instructions, requirements, or rules that an agent might interpret as optional.

---

## PHASE 2C: CONTRACT-FIRST INTEGRATION (contract-architect) — THE KEYSTONE

Read ARCHITECTURE_REPORT.md first. This is the single highest-impact change.

### Item 1: Add Section 16 to ORCHESTRATOR_SYSTEM_PROMPT

**Inject into:** agents.py — ORCHESTRATOR_SYSTEM_PROMPT, as a new numbered section

Add the complete "CONTRACT-FIRST INTEGRATION PROTOCOL" from the plan:
1. After ALL backend milestones: deploy INTEGRATION AGENT to read every controller and generate ENDPOINT_CONTRACTS.md
2. Contract is FROZEN — any backend change requires contract update
3. BLOCKING GATE — frontend milestones CANNOT start until contracts exist
4. Frontend coding tasks MUST include relevant contract entries

Include the example contract format and example task assignment format from the plan.

### Item 2: Add Contract Instructions to CODE_WRITER_PROMPT

**Inject into:** agents.py — CODE_WRITER_PROMPT section (coordinate with prompt-engineer for non-overlapping insertion point)

Add the "CONTRACT CONSUMPTION RULES" from the plan:
1. Read ENDPOINT_CONTRACTS.md first
2. Find the endpoint your code will call
3. Use EXACTLY the field names from the contract
4. Unwrap pagination wrappers as documented
5. Create TypeScript interfaces matching contract response shapes
6. If contracts don't exist, report BLOCKED
7. Violation = AUTOMATIC REVIEW FAILURE

### Item 3: Add Integration Gate to CODING_LEAD_PROMPT

**Inject into:** agents.py — CODING_LEAD_PROMPT section

Add: "Frontend task assignments MUST include the relevant contract entries. Copy the exact contract block for each endpoint the page will call. The code-writer receives: task description + contract entries + file to create."

### Item 4: Add Contract Verification to quality_checks.py

**Create function:** `verify_endpoint_contracts(cwd: Path) -> list[str]`

This function:
1. Reads `ENDPOINT_CONTRACTS.md`
2. For each contract entry, finds the corresponding frontend API call
3. Verifies field names match
4. Returns violations for mismatches

**NOTE:** Coordinate with review-engineer who also adds functions to quality_checks.py. Use the file conflict map from ARCHITECTURE_REPORT.md.

---

## PHASE 2D: REVIEW OVERHAUL (review-engineer)

Read ARCHITECTURE_REPORT.md first.

### Item 1: Specialized Reviewer Roles (Plan Phase 5.1)

**Inject into:** agents.py — REVIEW_LEAD_PROMPT section

Replace generic reviewer deployment with specialized sequence:
1. BACKEND API REVIEWER — verifies DTO validation, error handling, auth guard, pagination, test file per endpoint
2. INTEGRATION REVIEWER — verifies every frontend API call against ENDPOINT_CONTRACTS.md
3. TEST COVERAGE REVIEWER — verifies .spec.ts exists per service, ≥3 cases per method, no pending tests
4. UI COMPLETENESS REVIEWER — verifies loading/error/empty/success states, form validation, navigation per page

### Item 2: Review Checklists (Plan Phase 5.2)

**Inject into:** agents.py — CODE_REVIEWER_PROMPT section

Add the three specific checklists:
- Backend Endpoint Requirement checklist (7 items)
- Frontend Page Requirement checklist (7 items)
- Test Requirement checklist (6 items)
"ALL must pass. Missing ANY item = [ ] FAIL"

### Item 3: Implementation Depth Gate in Python (Plan Phase 5.3)

**Create function in quality_checks.py:** `check_implementation_depth(cwd: Path) -> list[str]`

This function:
- DEPTH-001: Every `.service.ts` must have `.service.spec.ts`
- DEPTH-002: Every service must have at least one try/catch
- DEPTH-003: Every `page.tsx` must have a loading state
- DEPTH-004: Every `page.tsx` must have error handling

### Item 4: Review Integrity Gate in Python (Plan Phase 5.4 / 9.4)

**Create function in quality_checks.py:** `verify_review_integrity(cwd: Path) -> list[str]`

Check: every `[x]` item in REQUIREMENTS.md must have `review_cycles >= 1`. Checked items with review_cycles=0 indicate implementers marking their own work complete.

---

## PHASE 2E: CONVERGENCE & AGENT SCALING (convergence-engineer)

Read ARCHITECTURE_REPORT.md first.

### Item 1: Fix Truth Scoring (Plan Phase 6.1)

**Modify in quality_checks.py:** `_score_contract_compliance()` and related truth scoring functions

Make each dimension compute from real static analysis:
- `contract_compliance`: Count frontend API calls matching ENDPOINT_CONTRACTS.md entries
- `test_presence`: Count (service files with .spec.ts) / (total service files)
- `error_handling`: Count (service methods with try/catch) / (total service methods)

### Item 2: Weighted Category Scoring (Plan Phase 6.3)

**Add to quality_checks.py or audit_agent.py:**

```python
CATEGORY_WEIGHTS = {
    "frontend_backend_wiring": 200,
    "prd_ac_compliance": 200,
    "entity_database": 100,
    "business_logic": 150,
    "frontend_quality": 100,
    "backend_architecture": 100,
    "security_auth": 75,
    "infrastructure": 75,
}
# Total: 1000 points. Stop condition: >= 850
```

### Item 3: AC Extraction Regex (Plan Phase 6.4)

**Modify in audit_agent.py:** AC extraction section ONLY

Add regex for table-based ACs: `| AC-XXX-NNN | description |`
This is a TARGETED change — do not modify other parts of audit_agent.py.

### Item 4: Agent Count Enforcement (Plan Phase 6.5)

**Add to config.py:** `AgentScalingConfig` dataclass

```python
@dataclass
class AgentScalingConfig:
    max_requirements_per_coder: int = 15
    max_requirements_per_reviewer: int = 25
    max_requirements_per_tester: int = 20
    enforce_minimum_counts: bool = True
```

**Add to agents.py** (coordinate with prompt-engineer): agent deployment rules in CODING_LEAD_PROMPT and REVIEW_LEAD_PROMPT with hard minimums for enterprise depth.

**Add to quality_checks.py:** `check_agent_deployment(cwd: Path, depth: str) -> list[str]` — verifies phase leads deployed minimum agent counts by analyzing TASKS.md assignees and REQUIREMENTS.md reviewer IDs.

### Item 5: Fix PRD Prioritization (Plan Phase 6.2 + 8.3)

**Modify in fix_prd_agent.py:** `filter_findings_for_fix()` — change prioritization from severity-only to impact-based:
1. WIRING fixes first (unblock frontend)
2. AUTH fixes second (unblock authenticated flows)
3. MISSING features third
4. Error handling / tests last

Add category impact ordering alongside severity.

### Item 6: Enterprise Config Overrides (Plan Phase 9.2 + 9.3)

**Modify in config.py:** `apply_depth_quality_gating()` enterprise section

Add all max quality overrides from the plan: min_test_count=10, max_cycles=25, score_healthy_threshold=95.0, thought budgets 2x (20/25/25/20/20).

---

## PHASE 2F: AUDIT METHODOLOGY OVERHAUL (audit-engineer)

Read ARCHITECTURE_REPORT.md first.

### Item 1: Overhaul audit_prompts.py

**IMPORTANT:** `src/agent_team_v15/audit_prompts.py` ALREADY EXISTS with 6 auditor prompts (~50 lines each). You are REPLACING the existing short prompts with comprehensive 2000-4000 word methodology prompts. Read the existing file first to understand the current structure and `_FINDING_OUTPUT_FORMAT` template, then rewrite each prompt in-place.

This file contains the replacement auditor methodology prompts. Each prompt is 2000-4000 words of explicit methodology.

**INTERFACE_AUDITOR_PROMPT** (~2000 words):
- Step 1: Extract ALL frontend API calls (grep patterns provided)
- Step 2: Extract ALL backend controller routes (grep patterns provided)
- Step 3: Build complete route mapping table (every row mandatory)
- Step 4: Request shape verification for every write endpoint
- Step 5: Response shape verification — THE MOST CRITICAL CHECK (trace controller → service → return value)
- Scoring formula

**REQUIREMENTS_AUDITOR_PROMPT** (~2000 words):
- Read ORIGINAL PRD (not just REQUIREMENTS.md)
- Extract ALL ACs from all format types (tables, bullets, GIVEN/WHEN/THEN)
- For each AC: read AC text, find implementation in backend AND frontend, determine PASS/PARTIAL/FAIL
- Per-feature tables with every AC getting a row
- Scoring formula

**COMPREHENSIVE_AUDITOR_PROMPT** (~3000-4000 words):
- Covers all 8 categories from the audit methodology
- Runs AFTER specialized auditors as a final quality gate
- Produces the final scorecard with the 1000-point scale

### Item 2: Make Auditor Prompts Tech-Stack Aware

**Modify in audit_agent.py:** prompt loading section

Add `get_auditor_prompt(auditor_type: str, tech_stack: list[str]) -> str` that injects stack-specific checks:
- NestJS project → add: decorators, guards, DTOs, module structure checks
- Flutter project → add: Riverpod state, GoRouter, Widget test checks
- Stripe project → add: webhook verification, idempotency checks
- Next.js project → add: App Router, server components, 'use client' usage checks

### Item 3: Integrate Comprehensive Auditor

**Modify in audit_agent.py:** main audit flow

After specialized auditors run, deploy the comprehensive auditor as a final gate. Its output becomes the definitive score that drives the stop condition.

---

## PHASE 2G: FIX PRD PRECISION (fix-prd-engineer)

Read ARCHITECTURE_REPORT.md first.

### Item 1: Before/After Code Diffs (Plan Phase 8.1)

**Modify in fix_prd_agent.py:** `_build_bounded_contexts()` — fix item formatting

Each fix item must include:
- File path and line number
- Current code (exact snippet)
- Required change (exact replacement code)
- Why the change is needed
- Verification step

Use the exact format from the plan (the chat `content` → `body` example and the repairs list response shape example).

### Item 2: Response Shape Corrections with Type Definitions (Plan Phase 8.2)

For response shape mismatches, fix items must include:
- The FULL backend response type (traced from controller → service → return)
- The FULL corrected frontend TypeScript interface
- The unwrapping code for pagination wrappers

### Item 3: Contract References in Fix Items (Plan Phase 8.4)

Each wiring fix must include the relevant ENDPOINT_CONTRACTS.md entry:
```
CONTRACT REFERENCE: GET /api/v1/repairs
Response 200: { data: RepairOrder[], meta: PaginationMeta }
```

### Item 4: Regression Guards (Plan Phase 8.5)

Each fix item specifies what MUST NOT break:
- List of endpoints that must still return 200
- List of test files that must still pass
- Specific behaviors that must be preserved

---

## PHASE 3: WRITE EXHAUSTIVE TESTS (test-engineer)

After ALL Wave 2 agents complete, write tests covering:

### Bug Fix Tests (8 tests)
- pattern_memory: 10-word query doesn't crash SQL
- cli: verification finds CONTRACTS.json at correct path
- quality_checks: contract compliance scores >0 with valid CONTRACTS.json
- audit_agent: AC extraction finds 119 ACs from EVS PRD format
- audit_agent: finding deduplication prevents count growth
- skills: float truth score doesn't crash skill update
- browser_test_agent: extraction finds >0 journeys from EVS PRD
- pattern_memory: snapshot cap message appears exactly once

### Prompt Content Tests (5 tests)
- agents.py: planner prompt contains "Requirement Granularity Rules"
- agents.py: code-writer prompt contains implementation checklists (all 4)
- agents.py: orchestrator prompt contains "CONTRACT-FIRST INTEGRATION PROTOCOL"
- agents.py: coding-lead prompt contains "Agent Deployment Rules"
- agents.py: zero instances of "should" in rule/requirement context (language hardening)

### Quality Gate Tests (6 tests)
- check_implementation_depth: detects missing .spec.ts files
- check_implementation_depth: detects missing error handling
- check_implementation_depth: detects missing loading states
- verify_review_integrity: detects [x] items with review_cycles=0
- verify_endpoint_contracts: detects field name mismatches
- check_agent_deployment: detects under-deployment of coding agents

### Config Tests (3 tests)
- AgentScalingConfig: default values correct
- Enterprise depth: all max quality overrides applied
- Enterprise depth: thought budgets are 2x defaults

### Audit Tests (4 tests)
- audit_prompts.py: INTERFACE_AUDITOR_PROMPT > 1500 words
- audit_prompts.py: REQUIREMENTS_AUDITOR_PROMPT > 1500 words
- audit_prompts.py: COMPREHENSIVE_AUDITOR_PROMPT > 2500 words
- Tech-stack-aware prompt includes NestJS checks for NestJS project

### Fix PRD Tests (3 tests)
- Fix item includes before/after code blocks
- Fix items prioritized: WIRING > AUTH > MISSING > QUALITY
- Fix items include regression guard section

### Regression Tests
- Run the FULL existing test suite — zero new failures
- All 459 existing tests still pass
- All imports resolve correctly across all modified files

---

## PHASE 4: RUN ALL TESTS AND FIX FAILURES

```bash
pytest tests/ -v --tb=short 2>&1
```

- ALL new tests must pass
- ALL existing 459 tests must pass
- Zero regressions
- If any test fails, diagnose the root cause, fix the CODE not the test (unless the test expectation is provably wrong), and re-run
- Iterate until fully green

---

## PHASE 5: FINAL REPORT

After all phases complete, produce:

```markdown
# Builder Perfection Plan — Implementation Report

## Summary
| Phase | Items | Implemented | Tests |
|-------|-------|-------------|-------|
| Phase 1: Bug Fixes | 8 | ?/8 | ?/8 |
| Phase 2: Atomic Requirements | 3 items | ?/3 | ?/? |
| Phase 3: Implementation Depth | 3 items | ?/3 | ?/? |
| Phase 4: Contract-First | 4 items | ?/4 | ?/? |
| Phase 5: Review Overhaul | 4 items | ?/4 | ?/? |
| Phase 6: Convergence | 6 items | ?/6 | ?/? |
| Phase 6.5: Agent Counts | 4 items | ?/4 | ?/? |
| Phase 7: Audit Overhaul | 3 items | ?/3 | ?/? |
| Phase 8: Fix PRD | 4 items | ?/4 | ?/? |
| Phase 9: Language Hardening | 4 items | ?/4 | ?/? |

## Files Modified
| File | Lines Changed | Agent | Phase |
|------|--------------|-------|-------|
| agents.py | +??? | prompt-engineer, contract-architect, review-engineer, convergence-engineer | 2,3,4,5,6.5,9 |
| quality_checks.py | +??? | bug-fixer, review-engineer, convergence-engineer, contract-architect | 1,4,5,6 |
| config.py | +??? | convergence-engineer | 6,6.5,9 |
| audit_agent.py | +??? | bug-fixer, convergence-engineer, audit-engineer | 1,6,7 |
| fix_prd_agent.py | +??? | convergence-engineer, fix-prd-engineer | 6,8 |
| pattern_memory.py | +??? | bug-fixer | 1 |
| cli.py | +??? | bug-fixer | 1 |
| skills.py | +??? | bug-fixer | 1 |
| browser_test_agent.py | +??? | bug-fixer | 1 |
| audit_prompts.py (NEW) | +??? | audit-engineer | 7 |

## Test Results
- New tests written: ?
- Total tests (existing + new): ?
- All passing: YES/NO
- Regressions: 0

## Key Changes Summary
### Contract-First Integration (Keystone)
[What was added, how it works, where it lives]

### Prompt Changes
[Word counts before/after for key prompts, "should" count before/after]

### Quality Gates Added
[List of new Python enforcement functions]

### Audit Methodology
[Word counts for new auditor prompts, coverage]

## Expected Impact on EVS Rebuild
| Category | v16 Score | Expected v17 | Why |
|----------|----------|-------------|-----|
| Frontend-Backend Wiring | 34% | 90%+ | Contract-first prevents all response shape and field name mismatches |
| PRD AC Compliance | 60% | 85%+ | Atomic requirements ensure every AC becomes code |
| Entity & Database | 93% | 95%+ | Already strong, minor improvements |
| Business Logic | 81% | 90%+ | Implementation checklists enforce depth |
| Frontend Quality | 68% | 85%+ | 5-state checklist on every page |
| Backend Architecture | 88% | 92%+ | Already strong, test co-location adds depth |
| Security & Auth | 64% | 80%+ | Language hardening + enterprise config |
| Infrastructure | 73% | 85%+ | Depth gate catches missing tests/error handling |
| **TOTAL** | **66%** | **88%+** | |

## Verdict
SHIP IT / NEEDS FIXES / CRITICAL ISSUES
```

---

## Execution Rules

1. **ARCHITECTURE FIRST** — architect MUST finish before anyone implements anything
2. **FOLLOW EXISTING PATTERNS** — Every function, config field, prompt section, and test must follow the exact patterns already in the codebase. Consistency over creativity.
3. **READ BEFORE YOU WRITE** — Read every file before modifying it. Read ARCHITECTURE_REPORT.md before every change.
4. **FIX THE APP NOT THE TEST** — When a test fails, fix the source code unless the test is wrong
5. **NO SHORTCUTS** — All 9 phases, all items within each phase. Nothing skipped.
6. **VERIFY IN SOURCE** — Do not trust this prompt for exact line numbers. Read the actual codebase. The plan references approximate line numbers that may have shifted.
7. **FILE OWNERSHIP IS SACRED** — If you are the prompt-engineer, you CANNOT modify quality_checks.py. If you are the review-engineer, you CANNOT modify pattern_memory.py. The conflict map exists to prevent merge disasters.
8. **COORDINATE agents.py CHANGES** — Three agents modify agents.py in different sections. Each agent MUST stay within their assigned line ranges. If an agent needs to add content that might shift line numbers for another agent, add it at the END of their section, not the beginning.
9. **459 TESTS MUST STILL PASS** — This is the non-negotiable regression check. Run after EVERY phase, not just at the end.
10. **THE PLAN IS THE SPEC** — The BUILDER_PERFECTION_PLAN.md is the source of truth for WHAT to implement. This prompt is the spec for HOW to implement it. When in doubt, read the plan.
11. **LANGUAGE HARDENING IS SURGICAL** — Don't blindly replace "should" everywhere. Only replace it in contexts where an agent might interpret it as optional. "This should work" in a comment is fine. "Agents should test their code" in an instruction is not — that becomes "Agents MUST test their code."
12. **AUDIT PROMPTS MUST BE LONG** — The interface auditor prompt must be >1500 words. The comprehensive auditor must be >2500 words. Short audit prompts produce shallow audits. This is proven by the EVS results.
