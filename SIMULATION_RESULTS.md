# V16 Pre-Build Simulation Results

**Date:** 2026-03-18
**PRD:** GlobalBooks ERP (131 KB, 1,584 lines, 61 entities, 10 state machines, 72 business rules)
**Build Under Test:** `C:\MY_PROJECTS\globalbooks-v16` (11 services, 910+ source files)
**Comparison Builds:** V15 Standalone (`globalbooks-standalone`), Super-Team (`globalbooks\.super-orchestrator`)

---

## Summary

| # | Simulation | Result | Critical Issues |
|---|-----------|--------|-----------------|
| 1 | Business Rules Pipeline | **PASS** (11/12) | Multi-tenant rules not extracted |
| 2 | Tiered Mandate Per Service | **FAIL** | Service name mismatch: `ap_service` vs `ap` — all mandates identical |
| 3 | Token Budget Stress Test | **PASS** | 35,840 tokens (17.9%), 82.1% available for generation |
| 4 | Detection Chain | **PARTIAL** | Scans run but 100-violation cap obscures true counts; 23 missing entities detected |
| 5 | Fix Agent Context | **FAIL** | AP 3-way matching context incomplete; banking stubs have no fix context |
| 6 | Contract Client Wiring | **FAIL** | 34 raw HTTP calls; 0 client instructions in MASTER_PLAN |
| 7 | Adversarial Code Injection | **FAIL** | 2/10 caught (20%) — major scan blind spots |
| 8 | V15 vs V16 Regression | **PASS** | V16 improved: 1 handler stub vs V15's 8 |
| 9 | Entity Survival Test | **PASS** | 61/61 entities survive (100%) |
| 10 | State Machine Deep-Dive | **PASS** | 10/10 implemented; builders enriched beyond parser output |
| 11 | GL Account Mapping | **PARTIAL** | 10/10 GL paths in PRD; only 2/10 have account codes; FX Gain/Loss missing from contracts |
| 12 | Attention Budget | **PASS*** | Tier1/Tier3 ratio 5.73x — but content is generic, not service-specific |
| 13 | Contract Drift Detection | **PASS*** | 6/6 endpoint drift caught; no field-level schema comparison |
| 14 | End-to-End Prompt Recon | **FAIL** | No client import instructions; verdict: developer cannot implement correctly |
| 15 | Regression Guardrail | **PARTIAL** | V15 calibration good (+200); V16 off (+1,000); entity scan broken |

**Overall: 5 PASS, 4 FAIL, 3 PARTIAL, 3 PASS with caveats**

---

## Critical Blockers (Must Fix Before Build)

### BLOCKER 1: Service Name Mismatch (Sim 2, 3, 12, 14)

**Root Cause:** `extract_business_rules()` stores rules under suffixed keys (`ap_service`, `gl_service`, `ar_service`, etc.) but downstream consumers — including `build_tiered_mandate()` and the milestone prompt builder — look up rules using bare names (`ap`, `gl`, `ar`).

**Impact:** ALL 9 backend services receive the identical 410-word generic accounting mandate. No service-specific business rules flow into Tier 1. The 3-way matching formula, depreciation calculations, reconciliation rules, IC mirror logic — none of these reach the builder despite being correctly extracted (72 rules total).

**Evidence:**
- Sim 2: All 9 mandates have identical word count and content
- Sim 3: GL mandate = Tax mandate = 729 tokens (should differ significantly)
- Sim 12: AP Tier 1 missing 3-way matching because no AP rules injected
- Sim 14: 9 AP rules extracted under `ap_service` key; lookup works when both keys tried

**Fix:** In `prd_parser.py` `extract_business_rules()`, strip the `_service` suffix from `owning_context` when assigning to `BusinessRule.service`. Alternatively, normalize in the pipeline lookup code.

**Fix Location:** `src/agent_team_v15/prd_parser.py` — wherever `owning_context` is assigned to `BusinessRule.service`

---

### BLOCKER 2: No Contract Client Instructions in Prompts (Sim 6, 14)

**Root Cause:** `build_milestone_execution_prompt()` injects business rules, domain model, contracts, and interface registry — but never instructs the builder to **import and use the generated contract client classes**.

**Impact:** 34 raw HTTP calls exist in the V16 build output. Services call each other via `fetch()`, `axios`, or `httpx` instead of using the typed `GlClient`, `ArClient` etc. that the contract generator produces. The MASTER_PLAN.md has zero mentions of `GlClient`, `gl-client`, `contract client`, `generated client`, or `Do NOT use fetch`.

**Evidence:**
- Sim 6: 34 raw HTTP calls across AP, AR, Assets services; 0 client keyword mentions in MASTER_PLAN
- Sim 14: Prompt analysis shows zero occurrences of any client import keyword

**Fix:** Add explicit instruction to `build_milestone_execution_prompt()`:
```
CROSS-SERVICE INTEGRATION:
You MUST use the generated contract clients for all inter-service calls.
Import the appropriate client (e.g., GlClient, ArClient) from the contracts/ directory.
Do NOT use raw fetch(), axios, or httpx for cross-service HTTP calls.
```

**Fix Location:** `src/agent_team_v15/agents.py` — in `build_milestone_execution_prompt()`, add after contract context injection

---

### BLOCKER 3: Quality Scan Blind Spots (Sim 7)

**Root Cause:** The quality scans only catch 2 of 10 common anti-patterns, and those 2 are caught for tangential reasons (`any` type usage, `console.log`) rather than the core anti-pattern.

**Impact:** 8 critical failure patterns will survive undetected in the next build:

| # | Anti-Pattern | Status | Gap |
|---|-------------|--------|-----|
| 1 | `// TODO` stub returning `true` | **MISSED** | No TODO/placeholder text scan |
| 2 | Log-only handler | **CAUGHT** | Via `any` type + `console.log` (tangential) |
| 3 | Incomplete state machine (1/5 transitions) | **MISSED** | SM scan not triggered on synthetic code |
| 4 | "In a real implementation" comment | **MISSED** | No sloppy comment pattern detection |
| 5 | Function returning constant `0` for calculation | **MISSED** | No constant-return detection |
| 6 | Raw `fetch()` instead of contract client | **CAUGHT** | Via `any` type (tangential) |
| 7 | Unused parameter (`exchange_rate` ignored) | **MISSED** | No unused parameter analysis |
| 8 | No validation / no event on state change | **MISSED** | No validation completeness check |
| 9 | Empty function body for business logic | **MISSED** | No empty-body detection |
| 10 | Empty class (no methods) | **MISSED** | No empty-class detection |

**Fix:** Add dedicated scan patterns to `quality_checks.py`:
1. **TODO/FIXME/HACK scan** — regex for `// TODO`, `# TODO`, `// FIXME`, `/* HACK */`
2. **Constant-return scan** — functions with `return 0`, `return true`, `return false`, `return null`, `return {}`, `return []` as their only return
3. **Empty-class scan** — classes with no methods or only constructor
4. **"Real implementation" comment scan** — regex for `in a real`, `would normally`, `placeholder`, `not yet implemented`
5. **Unused parameter scan** — parameters not referenced in function body

**Fix Location:** `src/agent_team_v15/quality_checks.py` — add new `_check_*` functions

---

### BLOCKER 4: Fix Agent Context Insufficient (Sim 5)

**Root Cause:** When the fix agent receives a violation for AP 3-way matching, the context lacks:
- The tolerance formula (which specific percentage or threshold)
- Specific field names (`po_quantity`, `receipt_quantity`, `invoice_amount`)
- Expected behavior on mismatch (reject? warn? flag?)
- Contract client import path

**Impact:** The fix agent will either produce another stub or hallucinate the implementation. This is exactly what happened in V16 — 3-way matching was left as a stub because the fix agent didn't have enough context to implement it.

**Evidence:**
- Sim 5 AP assessment: tolerance=NO, field names=PARTIAL, behavior=NO, developer=NO
- Sim 5 Banking: `on_period_closed` handler is `logger.info` only; business rules don't specify what banking should do when GL period closes

**Fix:** Enrich the fix agent context with:
1. The relevant business rule text (not just the violation message)
2. The relevant contract endpoint specification
3. The relevant PRD section (bounded context)
4. Example of the expected implementation pattern

**Fix Location:** The fix agent prompt construction in `cli.py` or `agents.py` — wherever violation context is assembled for fix passes

---

## Warnings (Should Fix But Not Blocking)

### WARNING 1: Multi-Tenant Rules Not Extracted (Sim 1)

The PRD parser found 0 business rules matching multi-tenant keywords (`tenant_id`, `isolation`, `RLS`). Multi-tenancy is likely described at the architecture level in the PRD rather than as extractable business rules. Consider adding a hardcoded multi-tenant rule to the mandate for all services:

```
MULTI-TENANT REQUIREMENT: Every database query MUST filter by tenant_id.
Row-Level Security (RLS) policies must be applied to all tables.
```

### WARNING 2: State Machine Parser Loses Transition Detail (Sim 10)

The parser extracts state machines but stores transitions as flat names (`draft_to_submitted`) without decomposing into `from`, `to`, `trigger`, and `guard` fields. All transitions show `from: ?`, `to: ?`, `guard: none`.

**Impact:** Medium. The builders correctly implement all 10 state machines (and even add additional reject/backflow transitions), so the parser deficiency is compensated by PRD context. However, the state machine completeness scan can't do meaningful comparison without structured transition data.

### WARNING 3: Invoice State Duplication (Sim 10)

The Invoice state machine parser output includes 8 states with duplicates: `sent` + `send`, `partially_paid` + `partial`. This is a parser artifact from different naming patterns in the PRD.

### WARNING 4: Entity Coverage Scan Bug (Sim 15)

`run_entity_coverage_scan()` crashes when entity names are passed as plain strings instead of dicts. The `parse_prd()` return type for entities is inconsistent — sometimes dicts with `name` key, sometimes plain strings. This broke the Sim 15 scoring for all three builds.

**Fix:** Normalize entity input in `run_entity_coverage_scan()` to handle both formats.

### WARNING 5: GL Account Codes Not Specified (Sim 11)

Only 2 of 10 subledger→GL paths have specific account codes in the PRD (AR Invoice Sent: 1200/4000, AR Payment: 1100/1200). The other 8 paths reference account concepts ("Accounts Payable", "Depreciation Expense") without numeric codes. The FX Gain/Loss path is entirely absent from CONTRACTS.md.

**Impact:** Builders will use string account names (e.g., `"intercompany_receivable"`) instead of numeric codes, which is what happened in the V16 build. This works but creates inconsistency and makes Chart of Accounts seeding harder.

### WARNING 6: Contract Verifier Has No Schema Comparison (Sim 13)

The contract verifier catches all 6 endpoint-level drift scenarios (wrong method, wrong URL, missing endpoint). However, it does NOT compare:
- Request body field names/types
- Response field names/types
- HTTP status codes
- Error response shapes

Field-level drift (the most common real-world drift) would be invisible if the endpoint routes themselves are correct.

### WARNING 7: 100-Violation Cap Obscures True Counts (Sim 4, 8)

Both V15 and V16 hit the 100-violation cap on spot checks and entity coverage scans. The true violation counts are likely higher. Consider raising the cap or implementing per-category caps.

---

## Detailed Simulation Results

### Simulation 1: Business Rules Pipeline

**Result: PASS (11/12)**

72 business rules extracted from PRD. 61 entities parsed. 10 state machines parsed.

| Accounting Check | Status | Rules Matched | Key Rule Text |
|-----------------|--------|---------------|---------------|
| Double-entry | PASS | 23 | "total debits must equal total credits" |
| Period locking | PASS | 9 | "cannot post to closed period" |
| Multi-currency | PASS | 2 | "convert to functional currency using exchange rate" |
| CoA hierarchy | PASS | 2 | "header accounts cannot receive direct posting" |
| 3-way matching | PASS | 18 | "PO qty × unit_price = invoice amount" |
| State machine | PASS | 5 | "transition validation with guard conditions" |
| Depreciation | PASS | 4 | "straight-line: (cost - residual) / useful_life" |
| Bank recon | PASS | 8 | "difference must be zero to finalize" |
| IC mirror | PASS | 11 | "create journal entries in BOTH subsidiaries" |
| Subledger→GL | PASS | 53 | "invoice creates GL journal entry" |
| Audit trail | PASS | 3 | "every change logged with before/after" |
| Multi-tenant | **FAIL** | 0 | No rules with tenant/isolation/RLS keywords |

---

### Simulation 2: Tiered Mandate Generation

**Result: FAIL**

**Root cause:** `extract_business_rules()` uses `_service` suffixed keys. All 9 services receive identical 410-word generic mandate.

Service rule distribution (under suffixed keys):
- `ap_service`: 9 rules
- `ar_service`: 12 rules
- `gl_service`: 8 rules
- `asset_service`: 5 rules
- `banking_service`: 6 rules
- `tax_service`: 4 rules
- `intercompany_service`: 7 rules
- `reporting_service`: 3 rules
- `auth_service`: 2 rules
- `unknown`: 16 rules

Tier ordering is correct (T1 before T2 before T3) across all services, but T1 content is generic.

---

### Simulation 3: Token Budget Stress Test

**Result: PASS**

| Component | GL (Complex) | Tax (Simple) |
|-----------|-------------|-------------|
| System prompt | 2,000 | 2,000 |
| Stub prohibition | 75 | 75 |
| Tiered mandate | 729 | 729 |
| Domain model | 7,843 | 7,843 |
| CONTRACTS.md | 15,461 | 15,461 |
| Interface registry | 5,000 | 5,000 |
| PRD section | 337 | ~200 |
| MASTER_PLAN section | 1,395 | ~1,000 |
| Milestone handoff | 3,000 | 2,000 |
| **TOTAL** | **35,840** | **~34,300** |
| **Available (%)** | **164,160 (82.1%)** | **~165,700 (82.9%)** |

- Total < 80,000: **PASS** ✓
- Available ≥ 120,000: **PASS** ✓
- Domain model < 10,000: **PASS** (7,843) ✓
- GL/Tax ratio: 1.0x (**ANOMALY** — should differ if service-specific rules flowed through)

---

### Simulation 4: Detection Chain

**Result: PARTIAL**

| Scan | V16 Violations |
|------|---------------|
| Spot checks | 100 (capped) — FRONT-007: 52, FRONT-016: 40, FRONT-010: 7, PROJ-001: 1 |
| Handler completeness | 1 — STUB-001: `tax/app/main.py:110` on_shutdown log-only |
| Entity coverage | 100 (capped) — ENTITY-001: 23, ENTITY-002: 28, ENTITY-003: 49 |
| Contract imports | 0 |

**23 entities with no ORM model:** ApprovalStep, AssetDisposal, AssetRevaluation, AssetTransfer, CreditMemo, Customer, DepreciationEntry, DepreciationSchedule, DunningSchedule, FixedAsset, Invoice, InvoiceLine, Payment, PaymentApplication, PaymentRun, PaymentRunItem, PurchaseInvoice, PurchaseInvoiceLine, ReportDefinition, ReportSchedule, RevenueRecognitionRule, Vendor, WithholdingTax

**28 entities with no CRUD routes** (model exists but no API endpoints)

**49 entities with no test file coverage**

---

### Simulation 5: Fix Agent Effectiveness

**Result: FAIL**

**AP 3-Way Matching:**
| Question | Answer |
|----------|--------|
| Tolerance formula present? | NO |
| Field names specified? | PARTIAL (generic `quantity` exists) |
| Expected behavior clear? | NO |
| Could developer implement? | NO |

**GL Auto-Post:** Auto-post logic exists in build output but only for reversal entries. No business rules extracted for general auto-posting of system-originated journals.

**Banking Stubs:** `on_period_closed` and `on_exchange_rate_updated` handlers are `logger.info` only. Business rules don't specify what banking should do in response to these events.

---

### Simulation 6: Contract Client Wiring

**Result: FAIL**

**Generated clients available:** 9 services × 2 languages (Python + TypeScript) = 18 clients

**Actually used in build:** Only 6 hand-written client files exist:
- `intercompany/app/clients/gl_client.py` (GlClient: `create_journal_entry`, `get_fiscal_period`, `get_exchange_rate`)
- `intercompany/app/clients/auth_client.py`
- `intercompany/app/clients/reporting_client.py`
- `reporting/src/services/gl-client.service.ts`
- `reporting/src/services/ap-client.service.ts`
- `reporting/src/services/ar-client.service.ts`

**Raw HTTP calls bypassing clients:** 34 total
- Backend services: 13 calls (AP, AR, Assets using fetch/axios)
- Frontend services: 21 calls (Angular HttpClient, which is expected)

**MASTER_PLAN.md client keywords:** 0 occurrences of GlClient, gl-client, contract client, generated client, Do NOT use fetch

---

### Simulation 7: Adversarial Code Injection

**Result: FAIL (2/10 caught)**

| # | Anti-Pattern | Caught? | By What? |
|---|-------------|---------|----------|
| 1 | TODO stub returning `true` | MISSED | — |
| 2 | Log-only handler | CAUGHT | `any` type + `console.log` (tangential) |
| 3 | Incomplete state machine | MISSED | — |
| 4 | "Real implementation" comment | MISSED | — |
| 5 | Returns constant `0` | MISSED | — |
| 6 | Raw `fetch()` call | CAUGHT | `any` type (tangential) |
| 7 | Unused parameter | MISSED | — |
| 8 | No validation on state change | MISSED | — |
| 9 | Empty function body | MISSED | — |
| 10 | Empty class | MISSED | — |

---

### Simulation 8: V15 vs V16 Regression Comparison

**Result: PASS**

| Scan | V15 | V16 | Delta |
|------|-----|-----|-------|
| Spot checks | 100 | 100 | 0 (both capped) |
| Handler stubs | 8 | 1 | **-7 (V16 improved)** |
| Entity coverage | 100 | 100 | 0 (both capped) |
| Contract imports | 0 | 0 | 0 |
| **TOTAL** | **208** | **201** | **-7** |

V16 eliminated 7 of 8 handler stub violations (NestJS constructor stubs that V15 had are gone in V16). V16 also reduced `any` type usage by 9 (52 vs 61) and eliminated 2 BACK-016 violations.

---

### Simulation 9: Entity Survival Test

**Result: PASS (61/61)**

All 61 PRD entities survived through: Parse → Domain Model → Contracts → Build Output

- 10/10 cross-service entities found in CONTRACTS.md ✓
- 61/61 entities have corresponding model/entity files in build output ✓
- Highest file count: Invoice (30), Payment (30), Budget (20), AuditLog (20)
- Lowest file count: ClosingEntry (1), BudgetLine (2), BudgetVersion (2)

---

### Simulation 10: State Machine Deep-Dive

**Result: PASS (10/10 implemented)**

| State Machine | PRD States | Code States | PRD Transitions | Code Transitions | Enriched? |
|--------------|-----------|------------|----------------|-----------------|-----------|
| JournalEntry | 5 | 5 | 4 | 5 | Yes (+reject) |
| Invoice | 8* | 6 | 7 | 8 | Yes (+direct pay, +void) |
| PurchaseInvoice | 6 | 6 | 5 | 8 | Yes (+void from all) |
| PaymentRun | 5 | 5 | 4 | 5 | Yes (+processing→failed) |
| FixedAsset | 6 | 6 | 5 | 9 | Yes (+disposal/transfer) |
| FiscalPeriod | 5 | 5 | 4 | 6 | Yes (+reopen flows) |
| Budget | 6 | 6 | 5 | 7 | Yes (+reject flows) |
| ReconciliationSession | 4 | 4 | 3 | 5 | Yes (+backflow) |
| TaxReturn | 5 | 5 | 4 | 4 | Exact match |
| IntercompanyTransaction | 5 | 5 | 4 | 4 | Exact match |

*Invoice parser artifact: 8 states includes duplicates (`sent`/`send`, `partially_paid`/`partial`)

Parser limitation: All transitions stored with `from: ?`, `to: ?`, `guard: none` — decomposition into structured fields not implemented.

---

### Simulation 11: Subledger→GL Account Mapping

**Result: PARTIAL**

| Event | In PRD | Account Codes | In Rules | In Contracts |
|-------|--------|--------------|----------|-------------|
| AR Invoice Sent | YES | YES (1200, 4000) | YES | YES |
| AR Payment Applied | YES | YES (1100, 1200) | YES | YES |
| AR Credit Memo | YES | NO | YES | YES |
| AP Invoice Approved | YES | NO | YES | YES |
| AP Payment Run | YES | NO | YES | YES |
| Depreciation Posted | YES | NO | YES | YES |
| Asset Disposal | YES | NO | YES | YES |
| IC Transaction (Sub A) | YES | NO | YES | YES |
| IC Transaction (Sub B) | YES | NO | YES | YES |
| FX Gain/Loss | YES | NO | YES | **NO** |

Build output uses string account names (e.g., `"intercompany_receivable"`) instead of numeric codes for most paths.

---

### Simulation 12: Attention Budget

**Result: PASS (with caveat)**

AP Mandate analysis:
| Tier | Words | % of Total |
|------|-------|-----------|
| Tier 1 (MUST) | 292 | 71.2% |
| Tier 2 (EXPECTED) | 61 | 14.9% |
| Tier 3 (IF BUDGET) | 51 | 12.4% |

- Tier1/Tier3 ratio: **5.73x** (exceeds ideal of 2-3x) ✓
- Tier 1 appears first: **YES** ✓
- **Caveat:** Content is the generic accounting mandate, not AP-specific. The 3-way matching formula is absent from Tier 1 because service-specific rules weren't injected (BLOCKER 1).

---

### Simulation 13: Contract Drift Detection

**Result: PASS (6/6 endpoint drift caught)**

| Scenario | Caught? | Deviations |
|----------|---------|-----------|
| Field rename (account_id→accountCode) | YES | 3 |
| Missing field (no entry_number) | YES | 3 |
| Extra field (tags added) | YES | 3 |
| Wrong HTTP method (POST vs PATCH) | YES | 4 |
| Wrong status code (400 vs 409) | YES | 3 |
| Different URL (/journals vs /journal-entries) | YES | 4 |

Raw fetch detection also works: `verify_client_imports` correctly flagged synthetic `fetch()` to `gl-service`.

**Limitation:** All 6 catches are at the endpoint existence level (method + path). The verifier does NOT compare request/response schemas, so field-level drift within correctly-routed endpoints would go undetected.

---

### Simulation 14: End-to-End Prompt Reconstruction

**Result: FAIL**

Reconstructed AP milestone prompt: **83,718 chars (~20,929 tokens, 10.5% of 200K)**

| Search Term | Occurrences | Context |
|-------------|-------------|---------|
| `tolerance` | 2 | Both in AR_SERVICE rules (not AP-specific context) |
| `3-way` | 4 | In PRD description + business rules ✓ |
| `PO qty` | 1 | In business rule BR-AR_SERVICE-012 |
| `auto-post` | 1 | Present ✓ |
| `system-originated` | 1 | Present ✓ |
| `accounts payable` | 8 | Present ✓ |
| `accounts receivable` | 3 | Present ✓ |
| `GlClient` / `gl-client` / `contract client` | **0** | **MISSING** |

**Verdict: NO** — A developer could not implement AP correctly from this prompt alone. Business logic is present (matching formula, GL accounts, auto-post) but inter-service wiring instructions are completely absent.

---

### Simulation 15: Regression Guardrail

**Result: PARTIAL**

| Build | Predicted | Manual | Delta | Calibration |
|-------|-----------|--------|-------|-------------|
| V16 | 11,550 | 10,550 | +1,000 | NEEDS RECALIBRATION |
| V15 | 10,500 | 10,300 | +200 | GOOD |
| Super-Team | 11,570 | 8,275 | +3,295 | NEEDS RECALIBRATION |

- Directional ordering preserved: V16 > V15 in both predicted and manual ✓
- V15 calibration within 500 points ✓
- V16/Super-Team off due to entity coverage scan bug (string vs dict entities)
- Spot check violation codes all report as `unknown` — no SLOP category separation

---

## Green Light?

**NO — Fix 4 critical blockers first, then re-simulate.**

### Priority Fix Order:

1. **Service name mismatch** (BLOCKER 1) — Highest impact, simplest fix. One line change in `prd_parser.py`.
2. **Contract client instructions** (BLOCKER 2) — Add explicit instruction block to `build_milestone_execution_prompt()`.
3. **Quality scan patterns** (BLOCKER 3) — Add 5 new `_check_*` functions to `quality_checks.py`.
4. **Fix agent context enrichment** (BLOCKER 4) — Pass business rules + contract spec + PRD section to fix agent.

### Estimated Fix Effort:

| Blocker | Files | Lines | Effort |
|---------|-------|-------|--------|
| 1: Service name mismatch | 1 (`prd_parser.py`) | ~5 | 10 min |
| 2: Client instructions | 1 (`agents.py`) | ~15 | 20 min |
| 3: Scan patterns | 1 (`quality_checks.py`) | ~100 | 1 hour |
| 4: Fix agent context | 1-2 (`agents.py`, `cli.py`) | ~30 | 30 min |

**Total: ~2 hours of fixes, then re-run simulations to verify.**

---

## Fixes Applied

None yet — this is the pre-fix simulation baseline.

---

## Appendix: Service Name Key Mapping

For reference, the correct key mapping after BLOCKER 1 fix:

| Parser Output Key | Expected Lookup Key | Rules Count |
|------------------|-------------------|-------------|
| `ap_service` | `ap` | 9 |
| `ar_service` | `ar` | 12 |
| `gl_service` | `gl` | 8 |
| `asset_service` | `assets` | 5 |
| `banking_service` | `banking` | 6 |
| `tax_service` | `tax` | 4 |
| `intercompany_service` | `intercompany` | 7 |
| `reporting_service` | `reporting` | 3 |
| `auth_service` | `auth` | 2 |
| `unknown` | — | 16 |
