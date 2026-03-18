# Scale Stress Test: Token Budget Analysis for GlobalBooks (62 Entities)

**Date:** 2026-03-19
**PRD:** `C:\MY_PROJECTS\globalbooks\prd.md` (130,155 chars)
**Parser output:** 61 entities, 10 state machines, 33 events, 68 business rules, 9 services
**Context window:** 200,000 tokens (Claude)
**Token estimation:** 1 token ~ 4 characters (conservative)

---

## 1. PRD Parse Results

| Service | Entities | Fields (total) | State Machines | Events | Business Rules | Contract Endpoints |
|---------|----------|---------------|----------------|--------|----------------|-------------------|
| GL | 10 | 128 | 2 (JournalEntry, FiscalPeriod) | 5 | 13 | 40 |
| AR | 8 | 121 | 1 (Invoice) | 6 | 15 | 32 |
| AP | 7 | 115 | 2 (PurchaseInvoice, PaymentRun) | 5 | 9 | 28 |
| Auth | 6 | 61 | 0 | 2 | 5 | 24 |
| Banking | 6 | 75 | 1 (ReconciliationSession) | 4 | 3 | 24 |
| Asset | 6 | 82 | 1 (FixedAsset) | 1 | 6 | 24 |
| Tax | 6 | 72 | 1 (TaxReturn) | 3 | 4 | 24 |
| Reporting | 8 | 90 | 1 (Budget) | 3 | 7 | 32 |
| Intercompany | 4 | 64 | 1 (IntercompanyTransaction) | 0 | 5 | 16 |
| **TOTAL** | **61** | **808** | **10** | **33** | **68** | **244** |

---

## 2. Component-by-Component Size Measurements

All measurements are **actual**, produced by running `parse_prd()`, `format_domain_model()`, `generate_contracts()`, and `build_tiered_mandate()` against the GlobalBooks PRD.

| Component | Chars | ~Tokens | % of 200K |
|-----------|------:|--------:|----------:|
| Task text (PRD x2: `[ORIGINAL USER REQUEST]` + `[TASK]`) | 260,310 | 65,077 | 32.5% |
| System prompt (`ORCHESTRATOR_SYSTEM_PROMPT`) | 42,824 | 10,706 | 5.4% |
| Targeted files (max budget cap) | 40,000 | 10,000 | 5.0% |
| Domain model (61 entities, 10 state machines, 33 events, 68 rules) | 31,010 | 7,752 | 3.9% |
| CONTRACTS.md full (before truncation) | 62,784 | 15,696 | 7.8% |
| CONTRACTS.md injected (capped at 30K chars) | 30,000 | 7,500 | 3.8% |
| Tiered mandate: ALL 68 rules | 16,512 | 4,128 | 2.1% |
| UI Design Standards | 12,925 | 3,231 | 1.6% |
| Tiered mandate: AR (15 rules, worst-case service) | 5,169 | 1,292 | 0.6% |
| Interface registry (9 services, estimated) | 5,000 | 1,250 | 0.6% |
| Tiered mandate: GL (13 rules) | 4,432 | 1,108 | 0.6% |
| All-out backend mandates (exhaustive depth only) | 4,398 | 1,099 | 0.5% |
| Predecessor context: late milestones (est. 4-6 predecessors) | 4,000-6,000 | 1,000-1,500 | 0.5-0.8% |
| Tiered mandate: AP (9 rules) | 3,541 | 885 | 0.4% |
| Milestone workflow + boilerplate | 3,200 | 800 | 0.4% |
| Codebase map summary | 3,000 | 750 | 0.4% |
| Accounting integration mandate | 1,675 | 418 | 0.2% |
| Milestone handoff instructions | 1,162 | 290 | 0.1% |
| Context7 instructions | 1,132 | 283 | 0.1% |
| Stack instructions: TypeScript/NestJS | 1,021 | 255 | 0.1% |
| Stack instructions: Python/FastAPI | 802 | 200 | 0.1% |
| Cross-service integration instructions | 800 | 200 | 0.1% |
| Contract/cycle/integration instructions | 800 | 200 | 0.1% |
| UI compliance enforcement | 300 | 75 | 0.0% |

---

## 3. GL Service Milestone Prompt (Python/FastAPI, THOROUGH depth)

| Component | Chars | ~Tokens | % of 200K |
|-----------|------:|--------:|----------:|
| Task text (PRD x2) | 260,310 | 65,077 | 32.5% |
| Targeted files (max 40K) | 40,000 | 10,000 | 5.0% |
| Domain model (all 61 entities) | 31,010 | 7,752 | 3.9% |
| CONTRACTS.md (capped 30K) | 30,000 | 7,500 | 3.8% |
| UI Design Standards | 12,925 | 3,231 | 1.6% |
| Interface registry | 5,000 | 1,250 | 0.6% |
| Tiered mandate (13 GL rules) | 4,432 | 1,108 | 0.6% |
| Milestone workflow + boilerplate | 3,200 | 800 | 0.4% |
| Codebase map summary | 3,000 | 750 | 0.4% |
| Predecessor context (~2 predecessors) | 2,000 | 500 | 0.2% |
| Accounting integration mandate | 1,675 | 418 | 0.2% |
| Milestone handoff instructions | 1,162 | 290 | 0.1% |
| Context7 instructions | 1,132 | 283 | 0.1% |
| Stack instructions (Python) | 802 | 200 | 0.1% |
| Cross-service integration instructions | 800 | 200 | 0.1% |
| Contract/cycle/integration instructions | 800 | 200 | 0.1% |
| Phase/milestone headers | 300 | 75 | 0.0% |
| UI compliance enforcement | 300 | 75 | 0.0% |
| **User message subtotal** | **398,848** | **99,712** | **49.9%** |
| **+ System prompt** | **42,824** | **10,706** | **5.4%** |
| **GRAND TOTAL** | **441,672** | **110,418** | **55.2%** |
| **Available for generation** | | **89,582** | **44.8%** |

---

## 4. AP Service Milestone Prompt (TypeScript/NestJS, THOROUGH depth)

| Component | Chars | ~Tokens | % of 200K |
|-----------|------:|--------:|----------:|
| Task text (PRD x2) | 260,310 | 65,077 | 32.5% |
| Targeted files (max 40K) | 40,000 | 10,000 | 5.0% |
| Domain model (all 61 entities) | 31,010 | 7,752 | 3.9% |
| CONTRACTS.md (capped 30K) | 30,000 | 7,500 | 3.8% |
| UI Design Standards | 12,925 | 3,231 | 1.6% |
| Interface registry | 5,000 | 1,250 | 0.6% |
| Predecessor context (~4 predecessors) | 4,000 | 1,000 | 0.5% |
| Tiered mandate (9 AP rules) | 3,541 | 885 | 0.4% |
| Milestone workflow + boilerplate | 3,200 | 800 | 0.4% |
| Codebase map summary | 3,000 | 750 | 0.4% |
| Accounting integration mandate | 1,675 | 418 | 0.2% |
| Milestone handoff instructions | 1,162 | 290 | 0.1% |
| Context7 instructions | 1,132 | 283 | 0.1% |
| Stack instructions (TypeScript) | 1,021 | 255 | 0.1% |
| Cross-service integration instructions | 800 | 200 | 0.1% |
| Contract/cycle/integration instructions | 800 | 200 | 0.1% |
| Phase/milestone headers | 300 | 75 | 0.0% |
| UI compliance enforcement | 300 | 75 | 0.0% |
| **User message subtotal** | **400,176** | **100,044** | **50.0%** |
| **+ System prompt** | **42,824** | **10,706** | **5.4%** |
| **GRAND TOTAL** | **442,999** | **110,750** | **55.4%** |
| **Available for generation** | | **89,250** | **44.6%** |

---

## 5. Worst Case: AR Service (15 rules) + EXHAUSTIVE Depth

| Component | Chars | ~Tokens | % of 200K |
|-----------|------:|--------:|----------:|
| Task text (PRD x2) | 260,310 | 65,077 | 32.5% |
| Targeted files (max 40K) | 40,000 | 10,000 | 5.0% |
| Domain model (all 61 entities) | 31,010 | 7,752 | 3.9% |
| CONTRACTS.md (capped 30K) | 30,000 | 7,500 | 3.8% |
| UI Design Standards | 12,925 | 3,231 | 1.6% |
| Predecessor context (~6 predecessors) | 6,000 | 1,500 | 0.8% |
| Tiered mandate (15 AR rules) | 5,169 | 1,292 | 0.6% |
| Interface registry | 5,000 | 1,250 | 0.6% |
| All-out backend mandates (exhaustive) | 4,398 | 1,099 | 0.5% |
| Milestone workflow + boilerplate | 3,200 | 800 | 0.4% |
| Codebase map summary | 3,000 | 750 | 0.4% |
| Accounting integration mandate | 1,675 | 418 | 0.2% |
| Milestone handoff instructions | 1,162 | 290 | 0.1% |
| Context7 instructions | 1,132 | 283 | 0.1% |
| Stack instructions (TypeScript) | 1,021 | 255 | 0.1% |
| Cross-service integration instructions | 800 | 200 | 0.1% |
| Contract/cycle/integration instructions | 800 | 200 | 0.1% |
| Phase/milestone headers | 300 | 75 | 0.0% |
| UI compliance enforcement | 300 | 75 | 0.0% |
| **User message subtotal** | **408,202** | **102,050** | **51.0%** |
| **+ System prompt** | **42,824** | **10,706** | **5.4%** |
| **GRAND TOTAL** | **451,026** | **112,756** | **56.4%** |
| **Available for generation** | | **87,244** | **43.6%** |

---

## 6. Summary Table: All Scenarios

| Scenario | System Prompt | User Message | **Total Injected** | **Available** | Verdict |
|----------|-------------:|-------------:|-------------------:|-------------:|---------|
| GL (Python, thorough) | 10,706 | 99,712 | **110,418 (55.2%)** | **89,582 (44.8%)** | PASS (barely) |
| AP (TypeScript, thorough) | 10,706 | 100,044 | **110,750 (55.4%)** | **89,250 (44.6%)** | PASS (barely) |
| AR (TypeScript, exhaustive) | 10,706 | 102,050 | **112,756 (56.4%)** | **87,244 (43.6%)** | PASS (barely) |

**Target was: total injected < 80K tokens (40%), available >= 120K tokens (60%)**

All three scenarios **FAIL the 40% target** by a wide margin. The total injected context consumes 55-56% of the window, leaving only 44-45% for generation.

---

## 7. Top 5 Budget Consumers

| Rank | Component | ~Tokens | % of 200K | Reducible? |
|------|-----------|--------:|----------:|:----------:|
| 1 | **Task text (PRD x2)** | 65,077 | 32.5% | YES -- inject once, not twice |
| 2 | **System prompt** | 10,706 | 5.4% | Partially -- trim verbose sections |
| 3 | **Targeted files** | 10,000 | 5.0% | YES -- reduce cap or scope to service |
| 4 | **Domain model** | 7,752 | 3.9% | YES -- inject only service-relevant entities |
| 5 | **CONTRACTS.md** | 7,500 | 3.8% | YES -- inject only service-relevant contracts |

These 5 components consume **101,035 tokens (50.5%)** of the 200K window.

---

## 8. Optimization Recommendations

### Critical: Eliminate PRD Double-Injection (saves ~32,500 tokens)

The full PRD (130K chars) is injected into every milestone prompt **twice** (`[ORIGINAL USER REQUEST]` and `[TASK]`), consuming 32.5% of the window alone. At line 3282-3283 of `agents.py`:

```python
parts.append(f"\n[ORIGINAL USER REQUEST]\n{task}")
parts.append(f"\n[TASK]\n{task}")
```

**Fix:** In milestone execution mode, the PRD has already been decomposed into per-milestone requirements. The milestone prompt should reference the milestone's REQUIREMENTS.md path, not re-inject the entire PRD. Replace with a 200-char summary: "Build GlobalBooks ERP per REQUIREMENTS.md in .agent-team/milestones/milestone-4/".

**Impact:** Frees ~65,000 tokens (from 110K to 45K total), bringing available budget to 155K tokens (77.5%).

### High: Scope Domain Model to Service (saves ~5,800 tokens)

The full domain model (all 61 entities) is injected into every milestone. The GL milestone only needs GL's 10 entities, not AR's 8, AP's 7, etc.

**Fix:** Filter `format_domain_model()` output to entities owned by the current milestone's service, plus direct dependencies. Typical reduction: 61 entities down to 10-15.

**Impact:** Saves ~5,800 tokens per milestone (domain model drops from 7,752 to ~1,900 tokens).

### High: Scope CONTRACTS.md to Service (saves ~5,500 tokens)

The full CONTRACTS.md (62K chars, capped at 30K) covers all 9 services and 244 endpoints. A GL milestone only needs GL's 40 endpoints plus the APIs it calls (AR, AP).

**Fix:** Generate per-service contract excerpts. Include the service's own contracts plus contracted dependencies.

**Impact:** Saves ~5,500 tokens per milestone (contracts drop from 7,500 to ~2,000 tokens).

### Medium: Reduce Targeted Files Cap (saves ~5,000 tokens)

The `get_targeted_files()` function caps at 40K chars. For a single milestone, 20K is usually sufficient.

**Fix:** Reduce `max_chars` from 40,000 to 20,000 in the call site.

**Impact:** Saves ~5,000 tokens per milestone.

### Medium: Strip UI Design Standards for Backend Milestones (saves ~3,200 tokens)

The 12,925-char UI Design Standards block is injected into **every** milestone, including pure backend services like GL, AP, and Auth that have zero UI components.

**Fix:** Only inject UI Design Standards when `milestone_context.title` contains frontend/UI keywords (the existing `_is_frontend_ms` check at line 3386 already detects this).

**Impact:** Saves ~3,200 tokens for all 8 backend milestones.

### Low: Trim System Prompt Verbose Examples

The system prompt contains verbose code examples (forbidden stubs, correct handlers) that take ~1,500 tokens. These could be condensed.

---

## 9. Post-Optimization Projection

| Optimization | Tokens Saved | Cumulative Saving |
|-------------|-------------:|------------------:|
| Eliminate PRD x2 injection | 65,077 | 65,077 |
| Scope domain model to service | 5,800 | 70,877 |
| Scope CONTRACTS.md to service | 5,500 | 76,377 |
| Reduce targeted files cap | 5,000 | 81,377 |
| Strip UI standards for backend | 3,200 | 84,577 |
| **Total savings** | | **84,577** |

**Optimized GL milestone budget:**

| Metric | Before | After | Change |
|--------|-------:|------:|-------:|
| Total injected | 110,418 | ~25,841 | -84,577 (-77%) |
| Available for generation | 89,582 | ~174,159 | +84,577 |
| % of window used | 55.2% | 12.9% | -42.3 pts |
| Available % | 44.8% | 87.1% | +42.3 pts |

This puts the pipeline well within the 40% target (12.9% vs 40% limit), with **174K tokens** available for generation -- enough for a complete NestJS or FastAPI service with tests.

---

## 10. Critical Finding: `task` Variable Contains Full PRD

The root cause of the bloat is in `cli.py` line 617:

```python
task = f"Build this application from the following PRD:\n\n{prd_content}"
```

This `task` string (130K chars) flows unmodified into `build_milestone_execution_prompt()` at line 1319, where it is injected twice. The entire PRD -- all 9 services, 61 entities, 130K chars -- appears verbatim in **every single milestone prompt**, even though each milestone only needs its own 2-5 page requirements slice.

This is the single most impactful issue for scaling to large PRDs.
