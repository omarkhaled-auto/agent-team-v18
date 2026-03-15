# V16 Integration Review

**Date:** 2026-03-15
**Codebase:** `C:\MY_PROJECTS\agent-team-v15\`
**Reviewer:** Claude Opus 4.6 (automated)

---

## Pipeline Flow Verification

### Phase 0.8: PRD Analysis

| Phase | Feature | Wired In? | Config Flag | Default | File:Line | Issues |
|-------|---------|-----------|-------------|---------|-----------|--------|
| 0.8 | `parse_prd()` call | YES | None (gated by `prd_path` presence) | Always runs when PRD provided | `cli.py:5210` | **BLOCKER**: uses `prd_path` variable which is never defined in `main()` scope. Should be `args.prd`. See Issue #1. |
| 0.8 | `format_domain_model()` call | YES | None | n/a | `cli.py:5213` | Same scope issue as above. |
| 0.8 | Resume re-parse path | YES | None | n/a | `cli.py:5225-5233` | Same `prd_path` undefined variable bug. |

### Phase 1: Decomposition (v16 features)

| Phase | Feature | Wired In? | Config Flag | Default | File:Line | Issues |
|-------|---------|-----------|-------------|---------|-----------|--------|
| 1 | `domain_model_text` in `build_decomposition_prompt()` | YES | None (always injected if non-empty) | n/a | `agents.py:2797,2838-2845` + `cli.py:999,1033` | Clean. Correctly injected into decomposition prompt. |
| 1 | `_ACCOUNTING_INTEGRATION_MANDATE` in decomposition | YES | None (auto-detected from task text) | n/a | `agents.py:2847-2849` | Clean. Fires when `_is_accounting_prd()` detects 3+ keywords. |
| 1 | `check_context_budget()` in decomposition | YES | None (always runs) | threshold=0.25 | `agents.py:2936` | Clean. Warns to stderr if >25% of 200K context used. |

### Phase 2: Milestone Execution (v16 features)

| Phase | Feature | Wired In? | Config Flag | Default | File:Line | Issues |
|-------|---------|-----------|-------------|---------|-----------|--------|
| 2 | `domain_model_text` in `build_milestone_execution_prompt()` | YES | None | n/a | `agents.py:2954,2990-2997` + `cli.py:1312` | Clean. |
| 2 | `get_stack_instructions()` / `detect_stack_from_text()` | YES | None (auto-detected from task) | n/a | `agents.py:3000-3002` | Clean. Detects python/typescript/angular/react from task text. **WARNING**: Only fires if task text mentions framework names explicitly. PRDs with implicit stack choices (e.g., "FastAPI" in tech section, not in task text) may miss this. See Issue #5. |
| 2 | `_ALL_OUT_BACKEND_MANDATES` / `_ALL_OUT_FRONTEND_MANDATES` | YES | None (depth-gated) | Injected at exhaustive depth, backend-only at thorough | `agents.py:3172-3186` | Clean. Frontend vs backend detected from milestone title keywords. |
| 2 | `_ACCOUNTING_INTEGRATION_MANDATE` in milestone | YES | None (auto-detected) | n/a | `agents.py:3188-3190` | Clean. |
| 2 | `check_context_budget()` in milestone | YES | None | threshold=0.25 | `agents.py:3220-3221` | Clean. |

### System Prompt (v16 features)

| Phase | Feature | Wired In? | Config Flag | Default | File:Line | Issues |
|-------|---------|-----------|-------------|---------|-----------|--------|
| sys | SECTION 3a: Stub Handler Prohibition | YES | None (always in system prompt) | n/a | `agents.py:289-333` | Clean. In ORCHESTRATOR_SYSTEM_PROMPT at position 11602. |
| sys | SECTION 9: Cross-Service Standards | YES | None (always in system prompt) | n/a | `agents.py:749-834` | Clean. In ORCHESTRATOR_SYSTEM_PROMPT at position 37418. |

### Post-Orchestration Scans (v16 features)

| Phase | Feature | Wired In? | Config Flag | Default | File:Line | Issues |
|-------|---------|-----------|-------------|---------|-----------|--------|
| post | `run_handler_completeness_scan()` | YES | `post_orchestration_scans.handler_completeness_scan` | `True` (disabled at quick depth) | `cli.py:6765-6810` | Works but see Issue #2 re: `prd_path` on line 6791. |
| post | `_run_stub_completion()` fix agent | YES | `post_orchestration_scans.max_scan_fix_passes` | `1` | `cli.py:2278-2357` + `cli.py:6786` | Works but `prd_path` reference on 6791 will crash. |
| post | `run_entity_coverage_scan()` | YES | None (gated by `_parsed_prd.entities` being non-empty) | n/a | `cli.py:6815-6846` | Clean. No dedicated config flag -- always runs if PRD was parsed. |
| post | `run_cross_service_scan()` | **NO** | None defined | n/a | **NOT CALLED** | DEAD CODE. Defined in `quality_checks.py:5169` but never called from cli.py. See Issue #3. |
| post | `run_api_completeness_scan()` | **NO** | None defined | n/a | **NOT CALLED** | DEAD CODE. Defined in `quality_checks.py:5022` but never called from cli.py. See Issue #3. |
| post | `is_fixable_violation()` / `filter_fixable_violations()` | **NO** | None | n/a | **NOT CALLED** | DEAD CODE in pipeline. Defined at `quality_checks.py:179,251` with tests, but zero call sites in cli.py. See Issue #4. |
| post | `classify_violation()` | **NO** | None | n/a | **NOT CALLED** | DEAD CODE. Defined at `quality_checks.py:209` with tests, never called from cli.py. |
| post | `track_fix_attempt()` / `get_persistent_violations()` / `filter_non_persistent()` | **NO** | None | n/a | **NOT CALLED** | DEAD CODE. Defined at `quality_checks.py:304,314,326`, never called from cli.py. |
| post | `dockerfile_templates.py` module | **NO** | None | n/a | **NOT IMPORTED** | DEAD CODE. Entire module has zero imports from cli.py or agents.py. Only imported in test file. See Issue #3. |

---

## Dead Code Check

| Function/Module | Has Call Site in cli.py? | Where Defined | Where Called |
|----------------|------------------------|---------------|-------------|
| `run_handler_completeness_scan()` | YES | `quality_checks.py:~line in scan functions` | `cli.py:6767-6770` |
| `run_entity_coverage_scan()` | YES | `quality_checks.py` | `cli.py:6817-6821` |
| `run_cross_service_scan()` | **NO** | `quality_checks.py:5169` | Tests only (`test_quality_checks.py:963-1003`) |
| `run_api_completeness_scan()` | **NO** | `quality_checks.py:5022` | Tests only (`test_quality_checks.py:1018-1057`) |
| `classify_violation()` | **NO** | `quality_checks.py:209` | Tests only |
| `track_fix_attempt()` | **NO** | `quality_checks.py:304` | Tests only |
| `get_persistent_violations()` | **NO** | `quality_checks.py:314` | Tests only |
| `filter_non_persistent()` | **NO** | `quality_checks.py:326` | Tests only |
| `filter_fixable_violations()` | **NO** | `quality_checks.py:251` | Tests only (docstring example) |
| `is_fixable_violation()` | **NO** | `quality_checks.py:179` | Only called internally by `filter_fixable_violations()` and `classify_violation()` (also dead) |
| `reset_fix_signatures()` | **NO** | `quality_checks.py:281` | Tests only |
| `dockerfile_templates.py` (entire module) | **NO** | `src/agent_team_v15/dockerfile_templates.py` | Tests only (`test_dockerfile_templates.py:7`) |
| `format_dockerfile_reference()` | **NO** | `dockerfile_templates.py:217` | Not called anywhere outside tests |

---

## PRD Parser Results (GlobalBooks)

- **PRD size:** 130,155 chars
- **Entities:** 61/62 (excellent coverage)
- **State machines:** 1/~10+ (poor -- only Invoice detected, despite 22 entities having status fields)
- **Events:** 33/~36 (good coverage)
- **Technology hints:** `{'language': 'Python', 'framework': 'FastAPI', 'database': 'PostgreSQL'}` (correct)
- **Domain model text:** 18,505 chars (~4,626 tokens)

### Notable Findings

The state machine extractor found only 1 state machine (Invoice: 3 states, 2 transitions) despite the PRD having at least 22 entities with status/state fields including JournalEntry, FiscalPeriod, CreditMemo, Payment, PurchaseInvoice, PaymentRun, etc. The extraction strategies appear to only capture explicitly listed state-transition diagrams (arrow notation or prose transitions), not status enum definitions.

This is a **known gap** (documented in MEMORY.md as "A5" and similar items from super-team parser work). The entity extraction (61 entities) and event extraction (33 events) are solid.

---

## System Prompt Size

| Component | Chars | Estimated Tokens |
|-----------|-------|------------------|
| System prompt (ORCHESTRATOR_SYSTEM_PROMPT) | 42,496 | ~10,624 |
| Decomposition prompt (exhaustive, no PRD) | 2,520 | ~630 |
| Milestone prompt (exhaustive, accounting task) | 25,287 | ~6,321 |
| Milestone prompt (exhaustive, FastAPI+NestJS+Angular) | 27,619 | ~6,905 |

### Section Presence in Milestone Prompt

| Section | Present? | Notes |
|---------|----------|-------|
| STUB HANDLER PROHIBITION | Only in system prompt | This is correct -- system prompt is always injected |
| SECTION 9: Cross-Service Standards | Only in system prompt | Correct -- no need to duplicate in user prompt |
| MANDATORY DELIVERABLES (all-out mandates) | YES (exhaustive depth) | Found at position 19215 |
| ACCOUNTING SYSTEM INTEGRATION MANDATE | YES (when detected) | Found at position 23615 |
| FRAMEWORK INSTRUCTIONS | YES (when frameworks detected) | Auto-detected from task text |

**Context budget assessment**: System prompt (~10.6K tokens) + milestone prompt (~6.3K tokens) = ~16.9K tokens total. This is ~8.5% of the 200K context window, well within the 25% warning threshold.

---

## Config Defaults

| Field | Default Value | Enabled at Exhaustive? | Notes |
|-------|--------------|----------------------|-------|
| `post_orchestration_scans.handler_completeness_scan` | `True` | YES (disabled only at quick depth) | v16 STUB-001 detection |
| `post_orchestration_scans.max_scan_fix_passes` | `1` | YES (disabled at quick: 0) | Controls fix loop iterations |
| No dedicated `entity_coverage_scan` config | n/a | Always runs if `_parsed_prd.entities` non-empty | Gated by code, not config |
| No dedicated `cross_service_scan` config | n/a | n/a | **NOT WIRED** -- dead code |
| No dedicated `api_completeness_scan` config | n/a | n/a | **NOT WIRED** -- dead code |

---

## Test Results

- **Total tests collected:** 6,726
- **Passed:** 6,714
- **Failed:** 7
- **Skipped:** 5

### v16-Specific Test Results

- `test_agents.py`: All passed
- `test_config.py`: All passed
- `test_quality_checks.py`: All passed
- `test_dockerfile_templates.py`: All passed
- `test_prd_parser.py`: All passed (27 tests)
- **Total v16 tests:** 709 passed, 0 failed

### Failing Tests (pre-existing, not v16-specific)

All 7 failures are in `test_cli.py` and are caused by the same root cause:

```
NameError: name 'prd_path' is not defined
```

at `cli.py:5208` in the `main()` function. The Phase 0.8 PRD Analysis code uses `prd_path` which was never assigned in `main()` scope. The correct variable is `args.prd`.

Failing tests:
1. `test_prd_forces_exhaustive`
2. `test_interview_doc_scope_detected`
3. `test_complex_scope_forces_exhaustive`
4. `test_design_ref_deduplication`
5. `test_no_interview_skips_interview`
6. `test_complex_interview_passes_scope_to_prompt`
7. `test_prd_and_interview_doc_clears_prd`

---

## Issues Found

### Issue #1 (BLOCKER): `prd_path` undefined in `main()` -- Phase 0.8 crashes

**Severity:** BLOCKER
**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\cli.py`
**Lines:** 5208, 5211, 5225, 5229, 6791

Phase 0.8 PRD Analysis (lines 5208-5233) uses the variable `prd_path` which is never assigned in the `main()` function. The code should use `args.prd` instead. This causes `NameError` for any run that reaches Phase 0.8 (i.e., any `--prd` run that also goes through interview/design extraction phases first).

The same bug exists at line 6791 in the stub completion handler where `prd_path=prd_path if prd_path else None` will crash.

**Fix:** Replace all three occurrences:
- Line 5208: `if prd_path and` -> `if args.prd and`
- Line 5211: `prd_content = Path(prd_path).read_text(...)` -> `prd_content = Path(args.prd).read_text(...)`
- Line 5225: `elif prd_path and` -> `elif args.prd and`
- Line 5229: `prd_content = Path(prd_path).read_text(...)` -> `prd_content = Path(args.prd).read_text(...)`
- Line 6791: `prd_path=prd_path if prd_path else None` -> `prd_path=getattr(args, "prd", None)`

### Issue #2 (BLOCKER): 7 test failures from Issue #1

**Severity:** BLOCKER (derivative of Issue #1)
**File:** `C:\MY_PROJECTS\agent-team-v15\tests\test_cli.py`

7 CLI tests fail with `NameError: name 'prd_path' is not defined`. All are caused by Issue #1. Fixing Issue #1 will resolve all 7 failures.

### Issue #3 (WARNING): 3 v16 scan functions + 1 module are dead code

**Severity:** WARNING
**Files:**
- `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\quality_checks.py` (functions at lines 5022, 5169)
- `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\dockerfile_templates.py` (entire module)

The following are defined and tested but never called from the pipeline:
1. `run_cross_service_scan()` -- Detects cross-service HTTP call patterns. Tests exist but no cli.py call site.
2. `run_api_completeness_scan()` -- Detects incomplete API handlers (missing validation, auth, error handling). Tests exist but no cli.py call site.
3. `dockerfile_templates.py` / `format_dockerfile_reference()` -- Provides reference Dockerfile templates. No import from cli.py or agents.py.

**Action:** Wire these into the post-orchestration scan section of `cli.py` (after the handler completeness scan at line ~6810), add config flags to `PostOrchestrationScanConfig`, and add depth-gating. Alternatively, document them as "future work" and accept they are not yet active.

### Issue #4 (WARNING): Fix-loop intelligence functions are dead code

**Severity:** WARNING
**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\quality_checks.py`

The v16 fix-loop intelligence system is fully implemented and tested but has zero call sites in cli.py:
- `classify_violation()` (line 209) -- classifies violations into FIXABLE_CODE/FIXABLE_LOGIC/UNFIXABLE_INFRA/UNFIXABLE_ARCH
- `filter_fixable_violations()` (line 251) -- filters to fixable-only + detects repeats
- `track_fix_attempt()` (line 304) -- records fix attempts per violation
- `get_persistent_violations()` (line 314) -- finds violations that exceeded MAX_FIX_ATTEMPTS
- `filter_non_persistent()` (line 326) -- excludes persistent violations before fix pass
- `reset_fix_signatures()` (line 281) -- clears state at run start
- `is_fixable_violation()` (line 179) -- checks if a violation is fixable vs infrastructure

The existing fix loops in cli.py (mock data, handler completeness, XREF, etc.) do NOT use these functions. They use simple violation-count-based loops with hardcoded max passes via `config.post_orchestration_scans.max_scan_fix_passes`.

**Action:** Integrate these functions into the existing fix loops. At minimum:
1. Call `reset_fix_signatures()` at the start of `main()`
2. Use `filter_fixable_violations()` instead of raw violation lists in fix loops
3. Call `track_fix_attempt()` after each fix pass
4. Use `filter_non_persistent()` to skip perpetually-failing violations

### Issue #5 (INFO): Stack detection only works on task text, not PRD content

**Severity:** INFO
**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\agents.py` line 3000

`get_stack_instructions()` calls `detect_stack_from_text(task)` where `task` is the task text passed to `build_milestone_execution_prompt()`. For PRD mode, this is typically `"Build this application from the following PRD:\n\n{prd_content}"` which includes the full PRD text. So this actually DOES work for PRDs -- the full PRD content is in the task string. No action needed.

### Issue #6 (INFO): State machine extraction misses most entities with status fields

**Severity:** INFO
**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\prd_parser.py`

The PRD parser found 61 entities and 22 entities with status/state fields in the GlobalBooks PRD, but only extracted 1 state machine (Invoice: 3 states, 2 transitions). The extraction strategies appear to only capture explicitly listed state-transition arrow notation or prose transitions, not status enum definitions or status field declarations.

This is a known gap. The entity extraction provides the entity names, and the orchestrator system prompt (SECTION 9) instructs agents to implement VALID_TRANSITIONS for every entity with a status field. The missing state machines mean agents won't get pre-extracted transition lists, but they will still be required to implement them.

**Action:** Consider adding a "status field -> state machine inference" strategy to `prd_parser.py` that generates state machines from status enum definitions. Low priority -- the system prompt mandates handle this as a safety net.

### Issue #7 (INFO): No config flag for entity_coverage_scan

**Severity:** INFO
**File:** `C:\MY_PROJECTS\agent-team-v15\src\agent_team_v15\cli.py` line 6815

The entity coverage scan has no dedicated config flag. It is gated only by `_parsed_prd and _parsed_prd.entities`. This means it cannot be independently disabled via YAML config. This is acceptable since it only runs when a PRD was successfully parsed and has zero cost (pure static analysis), but adding a config flag would be consistent with other scans.

---

## Verdict

### NEEDS FIXES

**Blocking issues:**
- Issue #1: `prd_path` undefined in `main()` -- 5 lines need changing to `args.prd`
- Issue #2: 7 test failures (derivative of #1)

**After fixing Issue #1, the pipeline will be functional.** The dead code (Issues #3 and #4) represents planned features that are implemented and tested but not yet wired into the pipeline. They are not blocking but should be wired in before a production release to get full value from the v16 quality gates.

### Summary of What IS Wired

| Feature | Status |
|---------|--------|
| Stub handler prohibition (system prompt) | WORKING |
| Cross-service standards (system prompt SECTION 9) | WORKING |
| PRD parser (parse_prd, format_domain_model) | WORKING (after Issue #1 fix) |
| Domain model injection into decomposition prompt | WORKING |
| Domain model injection into milestone prompt | WORKING |
| Stack-specific framework instructions | WORKING |
| All-out backend/frontend mandates (depth-gated) | WORKING |
| Accounting integration mandate (auto-detected) | WORKING |
| Handler completeness scan (STUB-001) | WORKING (after Issue #1 fix) |
| Stub completion fix agent | WORKING (after Issue #1 fix) |
| Entity coverage scan | WORKING (after Issue #1 fix) |
| Context budget monitoring | WORKING |
| handler_completeness_scan config flag + depth gating | WORKING |

### Summary of What is NOT Wired

| Feature | Status |
|---------|--------|
| `run_cross_service_scan()` | DEAD CODE -- needs cli.py call site |
| `run_api_completeness_scan()` | DEAD CODE -- needs cli.py call site |
| Fix-loop intelligence (classify, track, filter) | DEAD CODE -- needs cli.py integration |
| `dockerfile_templates.py` / `format_dockerfile_reference()` | DEAD CODE -- needs import from agents.py or cli.py |
