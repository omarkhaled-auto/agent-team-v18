# V16 Quality Enforcement Upgrade — Design Document

> **Date:** 2026-03-17 | **Status:** IMPLEMENTED | **Scope:** 9 components, 1,697 new lines (source) + 52 new tests, 5 files | **Target:** Accounting quality 10,000 → 11,200+
>
> **Implementation Results:**
> - 218 tests passing (166 baseline + 52 new), zero regressions
> - Validated against real GlobalBooks v16 build: placeholder scan catches the EXACT AP matching stub at line 385, business rule verification flags 75 missing operations, 59 business rules extracted from PRD
> - Files modified: quality_checks.py (+819), prd_parser.py (+449), agents.py (+293), contract_verifier.py (+136)

---

## Executive Summary

V16 doubled output (74K → 126K LOC), halved stubs (22 → 4), added contracts, mandates, interface registry. The accounting quality score went **DOWN** from 10,300 to 10,000.

**Root cause in one sentence:** The pipeline's generic mandates consumed the builder's attention budget on infrastructure boilerplate while systematic information loss stripped domain-specific business rules from the PRD before they reached the builder.

The fix: Extract business rules from the PRD and use them to **replace** generic mandates with domain-specific mandates (prevention) and **verify** implementation correctness against expected behavior (detection). Substitute, don't add.

---

## Root Cause Analysis

### Failure 1: AP 3-Way Matching — 400/1000 (down from 800 in v15)

**What the builder did:**
```typescript
// purchase-invoice.service.ts lines 346-422
const tolerancePercent = dto.tolerancePercent ?? 1;  // ACCEPTED, NEVER USED

if (!invoice.poNumber) {
  invoice.matchStatus = 'no_po';
} else if (!invoice.goodsReceiptRef) {
  invoice.matchStatus = 'partial_match';
} else {
  const hasAllLineRefs = (invoice.lines ?? []).every(
    (line) => line.poLineRef && line.receiptLineRef,
  );
  if (hasAllLineRefs) {
    // In production, amounts would be compared against PO/receipt data
    invoice.matchStatus = 'full_match';
  } else {
    invoice.matchStatus = 'partial_match';
  }
}
```
Only checks if string reference fields exist. Zero numerical comparison. `tolerancePercent` used only in a log message.

**What it should have done (v15 had this working):**
```typescript
// v15: globalbooks-standalone purchase-invoice.service.ts lines 237-302
const tolerance = body.tolerance ?? 0.02;
const invoiceTotal = parseFloat(invoice.totalAmount);

// Compare invoice total vs PO total within tolerance
if (body.po_total !== 0 && Math.abs(invoiceTotal - body.po_total) / body.po_total > tolerance) {
  errors.push(`Invoice total (${invoiceTotal}) differs from PO total...`);
}

// Compare invoice quantity vs receipt quantity within tolerance
const qtyDiff = Math.abs(invoiceTotalQty - body.receipt_qty);
if (body.receipt_qty !== 0 && qtyDiff / body.receipt_qty > tolerance) {
  errors.push(`Invoice quantity differs from receipt quantity...`);
}
```

**Why the pipeline didn't catch it:**
| Stage | What Happened | Gap |
|-------|--------------|-----|
| PRD | Specifies exact formula in 7 locations ("PO qty × unit_price = invoice amount ± tolerance") | N/A — PRD is correct |
| PRD Parser | Extracted PurchaseInvoice entity + state machine transitions | **Discarded guard conditions.** Guard "3-way match passes" became a bare transition with no formula |
| CONTRACTS.md | Generated from parsed output | **Omitted match endpoint entirely.** No `PATCH /purchase-invoices/{id}/match` |
| All-out mandate | Demanded 15 infrastructure features per entity | **Zero mention of 3-way matching or tolerance.** Created priority: bulk ops > domain logic |
| REQUIREMENTS.md | Had REQ-004 with 7 sub-items about matching | All checkboxes marked `[x]` (complete) despite being a stub. **No verification mechanism** |
| Handler scan | Only checks files named handler/subscriber/consumer/listener/event | **Skipped purchase-invoice.service.ts** — filename doesn't match |
| Contract verifier | Checked endpoint path existence only | **Confirmed endpoint exists, didn't check logic** |
| API scan | Counted route methods (≥2 = pass) | **Counted the match route as complete. Never read function body** |

**Root cause:** Information loss (guard conditions stripped by parser) + priority inversion (mandates louder than PRD) + existence-only quality gates.

**Why v15 was better:** No mandates. The builder's entire context budget went to implementing PRD-specified domain logic. Without 15 infrastructure demands per entity, the builder had the "attention" to implement the actual comparison algorithm.

---

### Failure 2: Contract Client Non-Adoption

**What happened:** Pipeline generated typed clients in `contracts/typescript/` (10 files with proper interfaces and methods). All TypeScript services (AR, AP, Assets, Reporting) used raw `fetch()` instead. 10 call sites across 4 services, all identical inline pattern.

**Evidence — every GL call looks like this:**
```typescript
const headers: Record<string, string> = { 'Content-Type': 'application/json' };
if (token) { headers['Authorization'] = `Bearer ${token}`; }
const response = await fetch(`${this.glServiceUrl}/journal-entries`, {
  method: 'POST', headers, body: JSON.stringify(journalEntryData),
});
```

**Why:** Three compounding failures:
1. **Prompt problem (root cause):** No milestone REQUIREMENTS.md or TASKS.md mentions the generated clients. Milestone 7 (Assets) explicitly says "Uses `fetch()` pattern matching AP/AR services" — codifying raw fetch as THE sanctioned pattern.
2. **Path problem:** No tsconfig path alias to `contracts/typescript/`. Files sit 2 directories above service source. No package.json reference, no symlink.
3. **Sequence problem:** Contract clients generated before builders run, but MILESTONE_HANDOFF.md (which builders read) describes WHAT to call but not HOW (no import instructions).

The IC Python service also wrote its own purpose-built client (not the generated one) because the generic CRUD wrapper didn't have the specific methods it needed.

---

### Failure 3: Subledger→GL Integration — 850 (no improvement despite contracts)

**Integration status across 4 subledgers:**

| Subledger | Creates GL Journal? | Correct Accounts? | Journal Posted? | Runtime Success? |
|-----------|--------------------|--------------------|-----------------|-----------------|
| AR → GL | Yes (raw fetch) | Mostly — uses taxCodeId as GL account ID (WILL 422) | No — draft forever | FAILS (bad account_id) |
| AP → GL | Yes (raw fetch) | Mostly — tax lumped into expense | No — draft forever | Works but no GL impact |
| Assets → GL | Yes (raw fetch) | Correct (DR depreciation, CR accumulated) | No — draft forever | Works but no GL impact |
| IC → GL | Yes (httpx client) | WRONG field names (account_code vs account_id, journal_date vs entry_date) | No — draft forever | FAILS (422 validation) |

**Effective working count: 0 of 4.** None produce posted GL journals. 2 of 4 will fail at runtime.

**Why contracts didn't help:**
1. CONTRACTS.md specifies entity schemas and endpoint paths but NOT accounting rules (which accounts to DR/CR per event)
2. GL service creates all journals as `draft` — no auto-post for system-originated journals
3. Without explicit account mapping, each builder invented its own approach (AR uses UUIDs, IC uses string names)

---

### Failure 4: 4 Remaining Stubs

| Stub | Service | File | What It Does | What It Should Do |
|------|---------|------|-------------|-------------------|
| `gl.period.closed` handler | Banking | main.py:110 | `logger.info("gl_period_closed_received")` | Prevent reconciliation in closed periods, freeze pending sessions |
| `gl.exchange_rate.updated` handler | Banking | main.py:115 | `logger.info("gl_exchange_rate_updated_received")` | Recalculate foreign-currency cash positions |
| Missing event subscriptions | IC | main.py | Zero event subscriptions | Should consume: gl.period.closed, gl.exchange_rate.updated, asset.transferred |
| Missing event subscriptions | Tax | main.py | Zero event subscriptions | Should consume: gl.period.closed, gl.exchange_rate.updated |

**Why not caught:** Handler completeness scan requires filenames to contain "handler", "subscriber", "consumer", "listener", or "event". All 4 stubs are in `main.py` files — skipped by the filename filter.

---

### Failure 5: Missing Entities (1 definitive + field gaps)

| Entity | Status | Details |
|--------|--------|---------|
| ApprovalWorkflow | **MISSING** | PRD defines parent entity for approval chains. Only ApprovalStep exists with dangling `workflowId` FK. No entity, controller, or module. |
| AuditLog | Misplaced | In shared/ infrastructure, not Auth service (PRD assigns to Auth) |
| Budget | Incomplete | Missing `department` and `version` fields that PRD specifies |

The audit report's "56/62" was inflated. Actual: 61/62 entity files exist, 1 truly missing.

---

### Failure 6: 2 Partial State Machines

**TaxReturn** (Tax Service) — Dead-end flows:
```
Implemented:  preparing → draft → submitted → accepted → amended
Missing:      submitted → draft (authority_rejects)
              amended → submitted (user_resubmits)
```
Tax returns rejected by authority have NO path back. Amended returns CANNOT be resubmitted. The amendment/rejection flow is completely broken.

**PaymentRun** (AP Service) — Terminal failure:
```
Implemented:  created → approved → processing → completed|failed
Missing:      failed → created (user_retries)
```
Failed payment runs are terminal. Cannot retry — must recreate from scratch. In a financial system where bank rejections are routine, this is a critical gap.

Additional minor gaps across 6 other state machines (Invoice AR missing write-off paths, PurchaseInvoice missing bypass/reject, FixedAsset missing impairment reversal, etc.).

---

## The Three Meta-Root-Causes

### Meta-Root-Cause 1: Information Loss in the PRD-to-Builder Chain

```
PRD (100% of business rules)
  ↓ PRD Parser — extracts entities, fields, states, transitions
  ↓ LOSES: guard conditions, validation formulas, accounting rules,
  ↓        matching algorithms, computation logic, acceptance criteria
  ↓
Parsed Output (~40% — structure only)
  ↓ Contract Generation — adds API shapes
  ↓ LOSES: nothing new, but doesn't ADD the lost business rules
  ↓
CONTRACTS.md (structure + API shapes, still no business rules)
  ↓ Milestone Prompt Generation
  ↓
Builder sees: entity schema + CRUD endpoints + generic mandates
Builder DOESN'T see: "compare PO qty × unit_price vs invoice amount within tolerance"
```

The richest part of the PRD — the domain logic specifications — is systematically stripped away before reaching the builder.

### Meta-Root-Cause 2: Priority Inversion from Mandates (Attention Budget Starvation)

The all-out backend mandate demands **per entity:** full CRUD, bulk operations, audit trail, 5+ business rules, optimistic locking, import/export, state machine with history, event publishing/subscribing with idempotency, 20+ test files, error handling middleware, structured logging, OpenAPI docs.

This creates an explicit priority signal: the builder spends its context window implementing bulk operations for PurchaseInvoice instead of the 3-way matching algorithm. The mandates are **LOUD** (explicit checklist, applies to every entity). The PRD's domain logic is **QUIET** (embedded in prose, specific to one entity).

**V15 had no mandates.** The builder's entire attention went to the PRD. The simpler pipeline paradoxically produced BETTER domain logic because it didn't distract the builder.

### Meta-Root-Cause 3: Existence-Only Quality Gates

Every quality scan asks "does X exist?" — none ask "does X do the right thing?"

| Scan | Checks | Doesn't Check |
|------|--------|--------------|
| Handler completeness | Is there a handler function? (in handler-named files only) | Does the handler do real work? Is it in main.py? |
| Entity coverage | Is there an ORM model class? | Does it have all required fields? |
| Contract verifier | Is there an endpoint at this path? | Does the endpoint implement the contract's logic? |
| API completeness | Are there ≥2 route methods? Is there pagination? | Is the business logic correct? Are there stubs? |
| Requirement checkboxes | Builder marks items `[x]` | Nobody verifies the checkbox claims |

The pipeline is a **structural/existence checker**, not a **semantic/correctness checker**.

---

## The Solution: Extract-Prioritize-Verify

### Architecture Overview

```
                    ┌─────────────────────────┐
                    │   PRD (full spec)        │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  LAYER 1: EXTRACTION     │
                    │  Business Rules Extractor │
                    │  (prd_parser.py +200)     │
                    └──────┬────────────┬──────┘
                           │            │
              ┌────────────▼──┐    ┌───▼──────────────┐
              │ LAYER 2:      │    │ LAYER 3:          │
              │ PREVENTION    │    │ DETECTION         │
              │               │    │                   │
              │ Domain Logic  │    │ Placeholder Scan  │
              │ Mandate       │    │ Unused Param Scan │
              │ (agents.py)   │    │ Handler Fix       │
              │               │    │ SM Completeness   │
              │ Contract      │    │ Rule Verification │
              │ Wiring        │    │ Import Verification│
              │ (generation)  │    │ (quality_checks.py)│
              └──────┬────────┘    └───┬──────────────┘
                     │                 │
                     ▼                 ▼
              Builder gets         Scans include
              specific rules       expected logic
              as TOP priority      for fix agent
```

**Key principle: EXTRACT ONCE, USE TWICE.** Business rules flow from the PRD through extraction into both the builder's input (mandate) and the scanner's expected output (verification target).

**Key strategy: SUBSTITUTE, DON'T ADD.** Replace generic mandate content with domain-specific content. Same context budget, higher signal-to-noise ratio.

---

### Component 1: Business Rules Extractor (LAYER 1)

**File:** `prd_parser.py` — new function `extract_business_rules()`
**Lines:** ~200
**Purpose:** Extract domain-specific business rules that the current parser discards

**Extraction strategies:**

1. **Guard conditions** from state machine sections:
   - Pattern: text after "guard:", "when:", "if:", "condition:" in transition definitions
   - Example: "guard: 3-way match passes with PO qty × unit_price = invoice amount" → `{entity: "PurchaseInvoice", transition: "received→matched", type: "validation", formula: "abs(po_qty * unit_price - invoice_amount) / invoice_amount <= tolerance"}`

2. **Business flow steps** from workflow sections:
   - Pattern: "System performs X", "calculates Y", "validates Z", "creates W with DR/CR"
   - Sections: "Order-to-Cash Flow", "Procure-to-Pay Flow", etc.
   - Example: "System performs 3-way matching: PO qty × unit_price vs goods receipt qty vs invoice amount" → validation rule for AP

3. **Acceptance criteria:**
   - Pattern: "Acceptance Criterion N: <testable statement>"
   - Example: "AP purchase invoice 3-way matching validates against PO and goods receipt" → rule mapped to AP service

4. **GL integration rules** from flow sections:
   - Pattern: "create journal entry", "DR/CR", "debit/credit", "post to GL"
   - Example: "When invoice approved → create GL journal: DR expense CR accounts payable" → integration rule

**Output per rule:**
```python
@dataclass
class BusinessRule:
    id: str              # "BR-AP-001"
    service: str         # "ap"
    entity: str          # "PurchaseInvoice"
    rule_type: str       # "validation" | "computation" | "integration" | "guard"
    description: str     # Human-readable summary
    required_params: list[str]  # ["po_qty", "unit_price", "tolerance_percent"]
    required_operations: list[str]  # ["multiplication", "comparison", "abs"]
    expected_patterns: list[str]  # Regex patterns that SHOULD appear in implementation
    anti_patterns: list[str]      # Regex patterns that should NOT appear (stubs)
    source_line: int     # PRD line number for traceability
```

---

### Component 2: Domain Logic Mandate (LAYER 2 — Prevention)

**File:** `agents.py` — modify mandate injection
**Lines:** ~100 (50 modified + 50 new)
**Purpose:** Replace generic mandates with tiered, domain-specific mandates

**Current mandate structure (single tier, generic):**
```
ALL_OUT_BACKEND_MANDATES:
  For EVERY entity: bulk CRUD, audit trail, 5+ business rules, optimistic locking,
  import/export, state machine history, events, 20+ test files, logging, OpenAPI...
```

**Proposed mandate structure (three tiers, service-specific):**
```
## TIER 1: DOMAIN LOGIC — MUST IMPLEMENT (BLOCKING)
[Auto-generated from extracted BusinessRules for THIS service]

### BR-AP-001: 3-Way Matching
The match() function MUST:
1. Accept PO line data (qty, unit_price), receipt data (received_qty), tolerance_percent (default 0.02)
2. For each invoice line: calculate amount_variance = abs(po_qty * unit_price - invoice_amount) / (po_qty * unit_price)
3. If variance > tolerance_percent → line FAILS match
4. Return per-line: {po_match: bool, receipt_match: bool, amount_match: bool, variances: {...}}

DO NOT:
- Check only for string field existence
- Accept tolerancePercent without using it in numerical comparison
- Write "in production, this would..." comments

### BR-AP-002: GL Journal on Approval
[...]

## TIER 2: STANDARD IMPLEMENTATION (EXPECTED)
- Full CRUD for all entities
- State machine with all transitions from PRD (including reverse/retry flows)
- Event publishing for state transitions
- Input validation and error handling

## TIER 3: INFRASTRUCTURE (IF CONTEXT BUDGET PERMITS)
- Bulk operations
- Import/export endpoints
- Audit trail interceptors
- 20+ test files per entity
```

**Token budget:** The tiered mandate should use FEWER tokens than the current flat mandate because:
- Tier 1 is service-specific (only rules relevant to THIS milestone)
- Tier 3 is explicitly optional (builder can skip it)
- The current mandate repeats the same 15 items for every entity; the new one is targeted

---

### Component 3: Contract Client Wiring (LAYER 2 — Prevention)

**File:** Contract generation phase code
**Lines:** ~100
**Purpose:** Make generated clients discoverable and importable

**Changes:**

**3A: Client placement** — Generate service-specific clients INSIDE service directories:
```
services/ar/src/clients/gl-client.ts    # Only methods AR needs
services/ap/src/clients/gl-client.ts    # Only methods AP needs
services/assets/src/clients/gl-client.ts # Only methods Assets needs
```
Each client is tailored to the consuming service's needs (not a generic CRUD wrapper).

**3B: Import instructions** — Add to each milestone's REQUIREMENTS.md:
```markdown
### Cross-Service Clients (AUTO-GENERATED — IMPORT THESE)
Generated typed clients in src/clients/:
- gl-client.ts: createJournalEntry(input: CreateJournalEntryInput): Promise<JournalEntry>
IMPORT these instead of writing raw fetch() calls. They include typed interfaces, auth headers, and error handling.
```

**3C: Path configuration** — Add tsconfig path alias during contract generation:
```json
{ "paths": { "@clients/*": ["./src/clients/*"] } }
```

---

### Component 4: Placeholder Comment Scanner (LAYER 3 — Detection)

**File:** `quality_checks.py` — new function `run_placeholder_scan()`
**Lines:** ~40
**Severity:** CRITICAL (blocks quality gate)

**Patterns detected:**
```python
PLACEHOLDER_PATTERNS = [
    r"[Ii]n production",           # "In production, amounts would be compared"
    r"would be (compared|calculated|validated|implemented)",
    r"TODO:\s*implement",
    r"FIXME:\s*implement",
    r"placeholder\s*(implementation|logic)",
    r"stub\s*(implementation|handler)",
    r"not yet implemented",
    r"to be implemented",
    r"mock (implementation|data|response)",
]
```

**Scope:** ALL source files (*.ts, *.py, *.js), excluding node_modules, __pycache__, test files, README/docs.

**Output format (enriched with business rule if available):**
```
PLACEHOLDER-001 [CRITICAL]: services/ap/src/services/purchase-invoice.service.ts:385
  FOUND: "In production, amounts would be compared against PO/receipt data"
  IN FUNCTION: match()
  EXPECTED LOGIC (BR-AP-001): Compare PO qty × unit_price vs invoice amount within configurable tolerance
  The fix must implement numerical comparison, not string field existence checks.
```

---

### Component 5: Unused Parameter Detector (LAYER 3 — Detection)

**File:** `quality_checks.py` — new function `run_unused_param_scan()`
**Lines:** ~80
**Severity:** HIGH

**Detection logic:**
1. Extract function signatures (regex for `function name(params)` / `def name(params):` / `async name(params)`)
2. For each parameter, search the function body for usage
3. Usage classification:
   - **Real usage:** parameter appears in assignment, conditional, arithmetic, return, function call argument
   - **Log-only usage:** parameter appears only in `logger.*()`, `console.*()`, template literals in log calls
   - **No usage:** parameter doesn't appear in body at all
4. Flag if parameter has ZERO real usage (log-only or absent)

**Example output:**
```
UNUSED-PARAM-001 [HIGH]: services/ap/src/services/purchase-invoice.service.ts:match()
  Parameter 'tolerancePercent' is accepted but never used in business logic.
  Found only in: logger.info(`tolerance: ${tolerancePercent}%`) at line 407
  This parameter should be used in numerical comparison per BR-AP-001.
```

---

### Component 6: Handler Filename Filter Fix (LAYER 3 — Detection)

**File:** `quality_checks.py` — modify `run_handler_completeness_scan()` at line ~1732
**Lines:** 5 lines modified
**Severity:** Inherits existing scan severity

**Current filter (line 1732-1738):**
```python
HANDLER_FILE_PATTERNS = ["handler", "subscriber", "consumer", "listener", "event"]
```

**Fix — add:**
```python
HANDLER_FILE_PATTERNS = [
    "handler", "subscriber", "consumer", "listener", "event",
    "main.py", "app.py",  # Python entry points with event subscriptions
]
```

Also add a separate check for Python `main.py` files: scan for `@app.on_event`, `subscribe(`, `bus.subscribe(` patterns to find inline event handlers that aren't in dedicated files.

---

### Component 7: State Machine Completeness Scanner (LAYER 3 — Detection)

**File:** `quality_checks.py` — new function `run_state_machine_completeness_scan()`
**Lines:** ~80
**Severity:** HIGH for dead-end transitions (reverse/retry missing), WARNING for optional missing transitions

**Logic:**
1. Input: Parsed PRD state machines (entity name, list of {from_state, to_state, trigger})
2. For each state machine, find the code's VALID_TRANSITIONS or equivalent:
   - Python: `VALID_TRANSITIONS = {` or `STATUS_TRANSITIONS = {`
   - TypeScript: `VALID_TRANSITIONS` or `private readonly transitions`
3. Compare sets:
   - **Missing from code but in PRD:** Report each missing transition
   - **Extra in code but not in PRD:** Report as INFO (acceptable deviations)
4. Classify missing transitions:
   - If the missing transition is a **reverse flow** (reject, revert, retry, rollback): severity HIGH — creates dead-end state
   - If the missing transition is a **forward flow** (approve, complete): severity WARNING

**Example output:**
```
SM-001 [HIGH]: services/tax/app/services/tax_return_service.py TaxReturn
  MISSING REVERSE TRANSITION: submitted → draft (authority_rejects)
  Creates dead-end: rejected tax returns have no correction path.

SM-002 [HIGH]: services/ap/src/services/payment-run.service.ts PaymentRun
  MISSING RETRY TRANSITION: failed → created (user_retries)
  Creates dead-end: failed payment runs cannot be retried.
```

---

### Component 8: Business Rule Verification Scanner (LAYER 3 — Detection)

**File:** `quality_checks.py` — new function `run_business_rule_verification()`
**Lines:** ~150
**Severity:** CRITICAL

**This is the most important detection component.** For each extracted business rule:

1. **Locate the implementing function:**
   - Match by endpoint (service + path + method from CONTRACTS.md)
   - Match by entity name + operation keyword (e.g., "PurchaseInvoice" + "match")
   - If not found: CRITICAL — "No implementation found for BR-AP-001"

2. **Check function body for required operations:**
   ```python
   OPERATION_PATTERNS = {
       "multiplication": [r"\*", r"multiply"],
       "comparison": [r"[<>]=?", r"Math\.abs", r"abs\(", r"tolerance", r"threshold"],
       "http_call": [r"fetch\(", r"axios\.", r"httpx\.", r"\.post\(", r"\.get\("],
       "db_write": [r"\.save\(", r"\.create\(", r"\.insert\(", r"\.execute\("],
       "conditional": [r"\bif\b", r"\bswitch\b", r"\?"],
   }
   ```
   For each business rule, check that the function contains ALL required operations.

   Example for BR-AP-001 (3-way matching):
   - required_operations: ["multiplication", "comparison"]
   - Check: Does match() contain `*` AND (`Math.abs` OR `abs(`) AND (`tolerance` OR `threshold`)?
   - If missing multiplication: CRITICAL — "match() does not perform multiplication — likely checking field existence instead of comparing amounts"

3. **Check for anti-patterns:**
   ```python
   ANTI_PATTERNS = {
       "stub_comment": [r"[Ii]n production", r"would be (compared|calculated)"],
       "field_existence_only": [r"^\s*if\s*\(\s*!?\w+\.\w+\s*\)"],  # Simple truthy check
   }
   ```

**Example output:**
```
RULE-001 [CRITICAL]: services/ap/src/services/purchase-invoice.service.ts:match()
  Business Rule: BR-AP-001 (3-Way Matching)
  MISSING OPERATIONS: multiplication (no * operator in function body)
  MISSING OPERATIONS: comparison (no Math.abs or tolerance comparison found)
  ANTI-PATTERN DETECTED: stub_comment at line 385 ("In production, amounts would be compared")
  ANTI-PATTERN DETECTED: field_existence_only at lines 370-380 (checking !invoice.poNumber, truthy only)

  EXPECTED: Function should contain:
  - Multiplication: po_qty * unit_price
  - Absolute value: Math.abs(expected - actual)
  - Tolerance comparison: variance > tolerancePercent
  - Per-line iteration with variance calculation

  FIX SPECIFICATION: Implement numerical 3-way comparison per BR-AP-001.
  Accept PO data + receipt data + tolerance. Return per-line match results with variances.
```

---

### Component 9: Contract Import Verification (LAYER 3 — Detection)

**File:** `contract_verifier.py` — new function `verify_client_imports()`
**Lines:** ~60
**Severity:** WARNING

**Logic:**
1. For each service, determine which other services it should call (from CONTRACTS.md cross-service dependencies)
2. Search the service's source files for:
   - **Generated client imports:** `import.*from.*clients/` or `from.*clients.*import`
   - **Raw fetch/axios calls:** `fetch(\`.*other-service` or `axios.*other-service-url`
3. If raw fetch is found without generated client import: WARNING
4. If neither is found (no cross-service call at all): HIGH — integration missing

**Example output:**
```
IMPORT-001 [WARNING]: services/ar/src/services/invoice.service.ts
  Calls GL service via raw fetch() at line 521
  Generated client available at: src/clients/gl-client.ts
  Recommendation: Import GlClient for type safety and consistent error handling

IMPORT-002 [WARNING]: services/ap/src/services/purchase-invoice.service.ts
  Calls GL service via raw fetch() at line 721
  Same recommendation
```

---

## Implementation Plan

### Phase 1: Quick Wins (ship immediately, ~125 lines)

| # | Component | File | Lines | Failure Fixed |
|---|-----------|------|-------|--------------|
| 1 | Placeholder comment scan | quality_checks.py | +40 | Catches "in production" stub in AP matching |
| 2 | Unused parameter detector | quality_checks.py | +80 | Catches tolerancePercent never used |
| 3 | Handler filename filter fix | quality_checks.py | ~5 modified | Catches Banking main.py stubs |

**Test:** Re-run quality checks against globalbooks-v16 build output. Verify:
- Placeholder scan flags purchase-invoice.service.ts:385
- Unused param scan flags tolerancePercent in match()
- Handler scan now finds 2 stubs in banking/main.py

### Phase 2: Structural Fixes (~340 lines)

| # | Component | File | Lines | Failure Fixed |
|---|-----------|------|-------|--------------|
| 4 | State machine completeness | quality_checks.py | +80 | Catches TaxReturn + PaymentRun dead-ends |
| 5 | Domain logic mandate | agents.py | ~100 | Prevents priority inversion |
| 6 | Contract import verification | contract_verifier.py | +60 | Detects raw fetch vs generated client |
| 7 | Contract client wiring | contract generation code | +100 | Places clients inside service dirs |

**Test:** Run against globalbooks PRD. Verify:
- SM scan flags 2 missing reverse transitions
- Mandate generates AP-specific rules mentioning 3-way matching formula
- Contract verifier flags 10 raw fetch calls across AR/AP/Assets

### Phase 3: Strategic Investment (~350 lines)

| # | Component | File | Lines | Failure Fixed |
|---|-----------|------|-------|--------------|
| 8 | Business rules extractor | prd_parser.py | +200 | Enables data-driven mandates + verification |
| 9 | Business rule verification | quality_checks.py | +150 | Semantic check against expected logic |

**Test:** Run extractor on globalbooks PRD. Verify:
- Extracts ≥5 business rules for AP service (including 3-way matching)
- Extracts GL integration rules for each subledger
- Rule verification scan would flag match() as CRITICAL

---

## Projected Impact

| Dimension | Current Score | After Phase 1 | After Phase 2 | After Phase 3 |
|-----------|--------------|---------------|---------------|---------------|
| AP 3-way matching | 400/1000 | 400 (detected, not prevented) | 800+ (mandate prevents stub) | 900+ (verified correct) |
| Subledger→GL | 850/1000 | 850 | 870 (contract wiring helps) | 900 (GL rules in mandate) |
| Contract adoption | low | low | improved (wiring + verification) | high (verified) |
| Remaining stubs | 4 | 2 (handler fix catches 2) | 0 (mandate + all scans) | 0 |
| Missing entities | 56/62 | 56/62 | 60/62 (mandate includes all) | 61/62 |
| Partial state machines | 8/10 | 8/10 | 10/10 (SM scan + mandate) | 10/10 |
| **Total quality** | **~10,000** | **~10,200** | **~10,800** | **~11,200+** |

---

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Domain logic mandate increases context pressure | HIGH | SUBSTITUTE, don't add. Replace Tier 3 (bulk/audit/export) with "if context permits" to free budget for Tier 1. Measure token count before/after — target neutral or fewer. |
| Business rules extractor misinterprets PRD | MEDIUM | Conservative extraction: only extract when entity name + action keyword both match. Log all extractions for human review. |
| Placeholder scan false positives | LOW | Restrict to implementation files only (exclude README, docs, comments in test descriptions). Require proximity to function body. |
| Unused parameter scan flags destructured/spread params | LOW | Track through assignments. Only flag if parameter appears exclusively in log contexts. |
| Rule verification too strict | MEDIUM | Check for PRESENCE of operation types, not exact code patterns. "Function contains multiplication AND comparison" not "function contains `Math.abs(a - b) / b`". |
| Fix agent still can't implement correct logic | MEDIUM | Enriched scan output includes the EXPECTED LOGIC from the business rule — fix agent gets a specification, not just "fix this stub". |

---

## Files to Modify

| File | Changes | Lines |
|------|---------|-------|
| `src/agent_team_v15/prd_parser.py` | Add `extract_business_rules()` function with 4 extraction strategies | +200 |
| `src/agent_team_v15/agents.py` | Restructure mandate injection: 3-tier system, service-specific Tier 1 from business rules, Tier 3 as optional | +50 new, ~50 modified |
| `src/agent_team_v15/quality_checks.py` | Add 5 new scan functions: placeholder, unused params, SM completeness, rule verification; fix handler filename filter | +390 new, ~5 modified |
| `src/agent_team_v15/contract_verifier.py` | Add `verify_client_imports()` function | +60 |
| Contract generation code (location TBD) | Generate service-specific clients inside service dirs; add import instructions to milestone prompts | +100 |

**Total: ~815 new lines + ~55 modified lines across 5 files**

---

## Appendix A: The Attention Budget Insight

V15 (simple pipeline, no mandates) produced BETTER domain logic than V16 (complex pipeline, heavy mandates). This is not a bug in the mandates — it's a fundamental property of LLM builders.

An LLM builder has a fixed attention budget. Every instruction added to the prompt reduces the attention available for other instructions. Generic mandates (same 15 features for every entity) are easy to comply with (template-based) but consume attention that could be spent on domain-specific logic (requires understanding the PRD).

The solution is not "remove mandates" (they produce useful infrastructure) or "add more mandates" (increases context pressure). The solution is **SUBSTITUTE generic instructions with specific ones**:

- **Before:** "Implement bulk CRUD + audit trail + export + import + optimistic locking + ... for PurchaseInvoice" (generic, applies to any entity)
- **After:** "Implement 3-way matching with tolerance comparison for PurchaseInvoice. The match() function must compare PO qty × unit_price vs invoice amount. DO NOT check only for string field existence." (specific, applies only to AP)

Same token budget. Higher signal-to-noise ratio. The builder's attention goes to the right place.

## Appendix B: Why "Add More Scans" Is Necessary but Insufficient

Scans run AFTER the builder has already made its decisions. By the time a scan detects that matching is a stub, the builder has already consumed its context window. The fix agent then has to implement the logic with LESS context than the original builder.

This is why prevention (mandate restructuring) is more valuable than detection (new scans). But detection is still necessary as a safety net:
- The builder might ignore the mandate
- The mandate might be unclear for a specific rule
- Edge cases the mandate doesn't cover

The optimal system has BOTH: prevention reduces the number of issues that reach detection, and detection catches whatever prevention misses. The business rules extractor powers both layers from the same data source.

## Appendix C: The "In Production" Anti-Pattern

The comment "In production, amounts would be compared against PO/receipt data with the configurable tolerance percentage" is the most informative failure artifact in the entire build. It tells us:

1. **The builder KNEW what to do.** It understood the requirement.
2. **The builder CHOSE not to do it.** It wrote the comment instead of the code.
3. **The builder had a reason.** It was prioritizing something else (likely mandate-demanded features).
4. **No quality gate caught this.** The comment survived all scans.

This single comment is the Rosetta Stone of the v16 quality regression. The builder acknowledged the requirement, deferred it, and no scan was designed to catch deferred requirements. The placeholder comment scanner (Component 4) makes this anti-pattern detectable. The domain logic mandate (Component 2) makes it preventable.
