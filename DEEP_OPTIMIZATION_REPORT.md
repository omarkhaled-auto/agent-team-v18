# Pipeline Deep Optimization — Report

**Date:** 2026-04-04
**Codebase:** agent-team-v15 (41K lines, 21 source files)
**Tests Before:** 9,249 | **Tests After:** 9,279 (30 new) | **Regressions:** 0

---

## Mission 1A: Prompt Optimization

### Changes Applied

| Prompt Section | Change | Principle | Detail |
|---------------|--------|-----------|--------|
| ORCHESTRATOR top | Added contract-first + min deployment reference | Primacy | "CRITICAL — CONTRACT-FIRST INTEGRATION" + "CRITICAL — MINIMUM DEPLOYMENT" |
| ORCHESTRATOR bottom | Added final verification checklist | Recency | 7-item checklist: REQUIREMENTS.md, review_cycles, contracts, sequencing, agent counts, findings, test co-location |
| CODE_WRITER bottom | Added 4 negative examples | Negative Examples | Contract consumption (wrong unwrap), implementation depth (no error handling), frontend states (missing), test assignment (wrong format) |
| CODE_WRITER bottom | Added final verification checklist | Recency | 6-item "BEFORE SUBMITTING" checklist |
| CODE_REVIEWER bottom | Added final reminder | Recency | Acceptance rate warning (>70% = too lenient), mock data severity |
| CODING_LEAD top | Added agent minimums + contract-first | Primacy | Formula + hard floor before responsibilities |
| REVIEW_LEAD top | Added reviewer minimums + sequence | Primacy | Count + specialized reviewer order |

### Escape Hatches (agents.py)

| Line | Text | Verdict |
|------|------|---------|
| 475 | "(More as needed)" | KEEP — planner scaling context |
| 1292 | "prefer TOP-LEVEL" | KEEP — legitimate design preference |
| 5742 | "modules attempt to integrate" | KEEP — descriptive |
| 6249 | "Do NOT attempt to read" | KEEP — prohibition |

**Zero actionable escape hatches in instruction context.** Prior hardening was effective.

### Prompt Size Audit

| Prompt | Words (est.) | Verdict |
|--------|-------------|---------|
| ORCHESTRATOR_SYSTEM_PROMPT | ~12,111 | WARNING — largest prompt, ~1.5% context window alone |
| CODE_REVIEWER_PROMPT | ~3,188 | OK |
| CODE_WRITER_PROMPT | ~2,814 | OK (increased ~200 with negatives) |
| COMPREHENSIVE_AUDITOR | ~2,575 | OK |
| ARCHITECT_PROMPT | ~1,635 | OK |
| All others | <1,200 each | OK |

---

## Mission 1B: Terminology Unification

| Concept | Variants Found | Action |
|---------|---------------|--------|
| Contract files | `API_CONTRACTS.json` (machine) vs `ENDPOINT_CONTRACTS.md` (human) | Added clarifying note in agents.py Section 14 |
| FindingCategory vs CATEGORY_WEIGHTS | `code_fix`, `security` vs `frontend_backend_wiring`, `security_auth` | **CRITICAL BUG FOUND AND FIXED** — see Mission 3 |
| Category display names | "Frontend-Backend Wiring" vs `frontend_backend_wiring` | Correctly bridged by keyword mapping |
| Weighted score terms | Consistent: `weighted_score` (code), "weighted score" (English) | No change needed |

---

## Mission 2A: Dead Code Inventory

### DEAD (31 items found, verified)

| Item | File | Status | Notes |
|------|------|--------|-------|
| `CODING_DEPT_HEAD_PROMPT` | agents.py | DEAD | 8 department prompts never wired |
| `BACKEND_MANAGER_PROMPT` | agents.py | DEAD | |
| `FRONTEND_MANAGER_PROMPT` | agents.py | DEAD | |
| `INFRA_MANAGER_PROMPT` | agents.py | DEAD | |
| `INTEGRATION_MANAGER_PROMPT` | agents.py | DEAD | |
| `REVIEW_DEPT_HEAD_PROMPT` | agents.py | DEAD | |
| `DOMAIN_REVIEWER_PROMPT` | agents.py | DEAD | |
| `CROSS_CUTTING_REVIEWER_PROMPT` | agents.py | DEAD | |
| `_MOCK_DATA_PATTERNS` | agents.py | DEAD | Private constant never used |
| `_UI_FAIL_RULES` | agents.py | DEAD | Private constant never used |
| `_SEED_DATA_RULES` | agents.py | DEAD | Private constant never used |
| `_ENUM_REGISTRY_RULES` | agents.py | DEAD | Private constant never used |
| `run_contract_import_scan` | quality_checks.py | DEAD | Never imported in production |
| `run_accounting_smoke_test` | quality_checks.py | DEAD | Never imported anywhere |
| `run_testid_coverage_scan` | quality_checks.py | DEAD | Never imported anywhere |
| `run_dockerfile_scan` | quality_checks.py | DEAD | Never imported anywhere |
| `run_sm_endpoint_scan` | quality_checks.py | DEAD | Never imported anywhere |
| `MAX_FIX_ATTEMPTS` | quality_checks.py | DEAD | Never referenced |
| `AUDIT_TOOLS` | audit_agent.py | DEAD | Never referenced |
| `format_pre_run_strategy` | orchestrator_reasoning.py | DEAD | Formatter never called |
| `format_architecture_checkpoint` | orchestrator_reasoning.py | DEAD | Formatter never called |
| `format_convergence_reasoning` | orchestrator_reasoning.py | DEAD | Formatter never called |
| `format_completion_verification` | orchestrator_reasoning.py | DEAD | Formatter never called |
| `AuditError` | coordinated_builder.py | DEAD | Exception never raised |
| `PRDGenerationError` | coordinated_builder.py | DEAD | Exception never raised |
| `HANDOFF_GENERATION_PROMPT` | cli.py | DEAD | Prompt never used |
| `capture_fix_recipe` | pattern_memory.py | DEAD | Wrapper never called |
| `HookHandler` | hooks.py | DEAD | Type alias never referenced |
| `LLM_CONFIDENCE_THRESHOLD` | fix_prd_agent.py | DEAD | Only used as default arg in same file |
| `AuditTeamConfig` | config.py | DEAD | Config class never instantiated |

**Corrections from verification:**
- `CATEGORY_WEIGHTS` — flagged DEAD but **now ACTIVE** (used by my config_agent.py fix)
- `BuilderRunError` — flagged DEAD but **ACTIVE** (raised 3 times in coordinated_builder.py)
- `CoordinatedBuildError` — flagged DEAD but **ACTIVE** (base class for BuilderRunError)

**Total confirmed dead: 29 items** (2 false positives corrected)

**Not removed in this pass** — dead code removal is a separate PR to avoid conflating optimization changes with deletions. Documented for future cleanup.

---

## Mission 2B: Scanner Inventory

### Complete Scanner Classification (59 scanners found)

| Classification | Count | Description |
|----------------|-------|-------------|
| **BLOCKING** | 16 | Output drives STOP/CONTINUE decisions or triggers fix cycles |
| **INFORMATIONAL** | 23 | Output is logged/printed but doesn't affect decisions |
| **ORPHANED** | 10 | Function exists but never called from production code |
| **CONDITIONAL** | 10 | Only runs at certain depths or config settings |

### ORPHANED Scanners (~2,500 lines dead code)

| Scanner | File:Line |
|---------|-----------|
| `run_placeholder_scan` | quality_checks.py:6175 |
| `run_unused_param_scan` | quality_checks.py:6403 |
| `run_state_machine_completeness_scan` | quality_checks.py:6689 |
| `run_business_rule_verification` | quality_checks.py:7028 |
| `run_contract_import_scan` | quality_checks.py:7214 |
| `run_accounting_smoke_test` | quality_checks.py:7375 |
| `run_shortcut_detection_scan` | quality_checks.py:7462 |
| `run_dockerfile_scan` | quality_checks.py:7693 |
| `run_sm_endpoint_scan` | quality_checks.py:7755 |
| `run_testid_coverage_scan` | quality_checks.py:7869 |

### INFORMATIONAL Scanners That SHOULD Be BLOCKING (Theater Gates)

| Scanner | Issue |
|---------|-------|
| `check_implementation_depth` | Finds missing tests, error handling, loading states — only logged |
| `verify_endpoint_contracts` | Finds contract mismatches — only logged |
| `verify_review_integrity` | Finds self-checked requirements — only logged |
| `check_agent_deployment` | Finds under-deployment — only logged |
| `TruthScorer.score` | Produces PASS/RETRY/ESCALATE gate — gate value never checked |
| `compute_quality_score` | Predicts quality on 12000-point scale — never compared to threshold |
| `run_spot_checks` (cli.py path) | Finds anti-patterns — only logged (same scan IS blocking through audit_agent path) |

### Top 5 Scanner Flow Traces (verified)

1. **run_full_audit** → evaluate_stop_conditions → LoopDecision(STOP/CONTINUE) — **FULLY BLOCKING**
2. **verify_task_completion** → 7-phase pipeline → overall pass/fail — **Phases 0-4 BLOCKING, 4.5-7 ADVISORY**
3. **Post-orch scan-fix loops** → scan → fix → rescan (bounded) — **BLOCKING via fix cycle**
4. **GateEnforcer gates** — 7 gates, GATE_AUDIT.log — **CONDITIONAL** (wired at cli.py:6397)
5. **Depth/contract/review/deploy checks** — violations logged, no fix cycle — **INFORMATIONAL (theater)**

---

## Mission 2C: Loop Verification

| Loop | File:Lines | Max Iterations | Enforced By | Can Infinite-Loop? |
|------|-----------|---------------|-------------|-------------------|
| Convergence | coordinated_builder.py:386-690 | 4 (configurable) | evaluate_stop_conditions + max_iterations | **NO** |
| Post-Orch Scans | cli.py:8080-9066 | 1-3 per scan (depth) | for range() | **NO** |
| Audit-Fix Cycle | cli.py:3317-3424 | 2-3 (depth) | for range() + 4 early-exit checks | **NO** |
| Browser Test | coordinated_builder.py:1039-1112 | 3 (2 fix + 1 initial) | for range() | **NO** |
| Milestone | cli.py:1684 | len(milestones) + 3 | while condition + counter | **NO** |

**CRITICAL findings: 0** — All loops have hard Python-enforced termination.

### Non-Critical Observations
1. Gate override can force CONTINUE past STOP, but current_run still increments → max_iterations catches it
2. No per-milestone timeout — hang risk (not infinite-loop) if SDK call blocks
3. `detect_convergence_plateau()` in audit_team.py is advisory-only — not wired into convergence loop
4. Post-orch fix loops silently drop violations when max passes exhausted

---

## Mission 3: Enforcement Hardening

### Critical Bug Fixed

**config_agent.py:285-311 — Weighted Score Stop Condition Was Dead Code**

`FindingCategory` values (`code_fix`, `security`, etc.) were used as `CATEGORY_WEIGHTS` keys, but they don't match (`frontend_backend_wiring`, `prd_ac_compliance`, etc.). All 8 scoring categories got 0.0, score was always 0, >=850 threshold never fired.

**Fix:** `_map_finding_to_scoring_category()` — keyword matching + direct mappings.
**Guards:** Only fires when actionable_count > 0, prior runs exist, 0 critical, 0 high.

### New Enforcement Functions (6)

| Function | Purpose | Wired To |
|----------|---------|----------|
| `_map_finding_to_scoring_category()` | Fix weighted score mapping | config_agent.py |
| `verify_milestone_sequencing()` | Block frontend without contracts | cli.py (milestone dispatch) |
| `verify_contracts_exist()` | Detect missing/thin contracts | cli.py + coordinated_builder.py |
| `detect_pagination_wrapper_mismatch()` | Find {data,meta} vs flat array issues | cli.py + coordinated_builder.py |
| `verify_requirement_granularity()` | Detect coarse requirements | cli.py + coordinated_builder.py |
| `check_test_colocation_quality()` | Find stub/empty test files | cli.py + coordinated_builder.py |

**All 6 wired: YES** | **All 6 tested: YES** (30 tests) | **All verified via grep: YES**

---

## Mission 4: Prompt Test Results

### Per-Prompt Analysis (36 prompts tested)

| Prompt | Words | Clarity | Ambiguities | Contradictions | Missing | Gaming | Escape Hatches | Recap |
|--------|-------|---------|-------------|---------------|---------|--------|---------------|-------|
| ORCHESTRATOR | 12,111 | 3/4 | 11 | 4 | 8 | 6 | 5 | ADDED |
| CODE_WRITER | 2,814 | 4/4 | 3 | 1 | 2 | 3 | 0 | ADDED |
| CODE_REVIEWER | 3,188 | 4/4 | 2 | 1 | 2 | 2 | 0 | ADDED |
| CODING_LEAD | 685 | 3/4 | 2 | 0 | 3 | 1 | 0 | N/A |
| REVIEW_LEAD | 672 | 3/4 | 1 | 0 | 2 | 1 | 0 | N/A |
| PLANNER | 851 | 4/4 | 3 | 0 | 2 | 2 | 0 | MISSING |
| ARCHITECT | 1,635 | 3/4 | 4 | 1 | 3 | 2 | 0 | MISSING |
| COMPREHENSIVE_AUDITOR | 2,575 | 4/4 | 2 | 0 | 1 | 1 | 1 | EXISTS |
| INTERFACE_AUDITOR | 1,591 | 4/4 | 0 | 0 | 1 | 1 | 0 | EXISTS |
| REQ_AUDITOR | 1,770 | 4/4 | 1 | 0 | 1 | 1 | 0 | EXISTS |
| 26 others | <700 each | 3-4/4 | 0-1 each | 0 | 0-1 | 0-1 | 0 | MOSTLY MISSING |

**Totals across all 36 prompts:** 38 ambiguities, 7 contradictions, 47 missing info, 26 gaming vectors, 9 escape hatches.

### Key Contradictions Found

1. **"Be GENEROUS with agent counts" vs "be cost-conscious"** — direct conflict when budget is set
2. **"MANDATORY BLOCKING GATE" that continues on failure** — self-contradicting
3. **40% rejection quota vs honest review** — forces artificial failures when code quality is high
4. **"Backend milestones MAY run in parallel" vs sequential contract updates** — race condition on contracts file

### Top Gaming Vectors

1. **Rubber-stamp review**: Deploy 1 reviewer who marks everything [x]. GATE 5 catches 0-cycle but not shallow single-cycle. **PARTIAL countermeasure.**
2. **Token 40% rejection**: Reject easiest items, pass hard ones. **No countermeasure.**
3. **Empty test files**: Write `describe` blocks with no assertions. **STRONG countermeasure** (checklist rules + new DEPTH-005/006 enforcement).

---

## Test Results

| Metric | Value |
|--------|-------|
| Tests before | 9,249 |
| Tests after | 9,279 |
| New tests | 30 (test_enforcement_hardening.py) |
| Regressions | **0** |
| Skipped | 34 (pre-existing) |
| Collection errors | 1 (pre-existing: test_sdk_cmd_overflow.py) |

---

## Files Modified

| File | Changes |
|------|---------|
| `agents.py` | Prompt optimization: primacy rules, negative examples, final recaps, terminology note |
| `config_agent.py` | Fixed weighted score bug, added `_map_finding_to_scoring_category()`, `_SCORING_CATEGORY_KEYWORDS` |
| `quality_checks.py` | Added 5 enforcement functions: milestone sequencing, contract existence, pagination wrapper, requirement granularity, test co-location |
| `cli.py` | Wired 6 new checks: 5 post-orchestration, 1 milestone dispatch |
| `coordinated_builder.py` | Wired 4 new checks in post-audit quality gates |

## Files Created

| File | Purpose |
|------|---------|
| `tests/test_enforcement_hardening.py` | 30 tests for all new functions |
| `DEEP_OPTIMIZATION_REPORT.md` | This report |

---

## Verdict

**READY FOR NEXT PHASE**

### What Was Fixed (This Session)
- 1 critical bug (weighted score mapping — was dead code)
- 6 enforcement functions added and wired
- 5 prompt sections restructured (primacy, recency, negative examples)
- 30 new tests, 0 regressions

### What Remains (Future Work — Prioritized)

**Priority 1 — Remove Dead Code:**
- 29 confirmed dead items across 8 files (~3,000+ lines)
- 10 orphaned scanner functions (~2,500 lines)
- Separate PR recommended

**Priority 2 — Fix Prompt Contradictions:**
- Remove 40% rejection quota (creates perverse incentive)
- Fix "MANDATORY BLOCKING gate that continues" (L887-891)
- Resolve "GENEROUS vs cost-conscious" (add budget-conditional logic)
- Add parallel backend milestone contract merging guidance

**Priority 3 — Upgrade Informational Scanners to Blocking:**
- `check_implementation_depth` violations should feed fix cycle
- `verify_endpoint_contracts` violations should feed fix cycle
- `verify_review_integrity` violations should block convergence
- `TruthScorer` gate value should drive decisions (not just log)

**Priority 4 — Add Missing Recap Blocks:**
- 26 of 36 prompts lack final recap — add 3-5 line "CRITICAL REMINDERS" to each

**Priority 5 — Add Per-Milestone Timeout:**
- Milestone loop has no SDK call timeout — hang risk if agent blocks
