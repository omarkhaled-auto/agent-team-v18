# Phase D Architecture Report — Tracker Cleanup

**Date:** 2026-04-17
**Branch:** `phase-d-tracker-cleanup` (based on integration HEAD `a7db3e8`)
**Discoverer:** team-lead (Wave 1 architecture discovery)

---

## 1. A-10 Structural Analysis (HIGH RISK)

### Current Compile-Fix Loop Shape

**Function:** `_run_wave_compile` at `wave_executor.py:2517-2596`
**Iteration cap:** Hardcoded `range(3)` at line 2531
**Exhaustion behavior:** Returns `CompileCheckResult(passed=False, iterations=3)` at line 2591

### Loop Mechanics

```
for iteration in range(3):          # line 2531
    raw_result = await run_compile_check(...)  # line 2532
    compile_result = _coerce_compile_result(raw_result)
    
    if compile_result.passed:       # line 2549
        return compile_result       # SUCCESS — exit
    
    if execute_sdk_call is None or iteration >= 2:  # line 2555
        return compile_result       # EXHAUSTED — give up on last iteration
    
    fix_prompt = _build_compile_fix_prompt(...)   # line 2561
    fix_cost_delta = await _invoke_sdk_sub_agent_with_watchdog(...)  # line 2564
```

### Fix Prompt Shape

**Function:** `_build_compile_fix_prompt` at `wave_executor.py:2235-2258`

The prompt contains ONLY:
- Phase header (`[PHASE: WAVE {letter} COMPILE FIX]`)
- Milestone ID/title
- Current errors (up to 20)
- Generic instructions ("Fix ALL compile errors. Read each file before editing.")

**Missing from the prompt:**
- No history from previous iterations
- No structural context (package.json deps, tsconfig paths)
- No A-09 scope constraint

### Root Cause of Exhaustion

**Multiple candidates confirmed by code analysis:**

1. **Cap too low (Candidate 1):** 3 iterations is insufficient for 47-file Claude fallback output. Each iteration fixes some errors but introduces new ones from unresolved structural dependencies.

2. **No inter-iteration history (NOT context bleed — the opposite):** Each iteration sees only CURRENT errors. If iteration N fixes file A but breaks file B, iteration N+1 sees file B's error but doesn't know file A was just fixed — potentially reverting it.

3. **No structural triage (Candidate 3 — PRIMARY):** The loop goes straight to per-file diffs without checking whether the root cause is structural (missing deps in package.json, invalid tsconfig paths). Per-file diffs CANNOT fix missing `@types/react` in package.json.

4. **No fallback output completeness check (Candidate 4):** After Claude fallback produces output, there's no verification that required config files exist (next.config.ts, tsconfig.json, package.json).

### D-15 Structural Triage Design

**Insert point:** Before the `for iteration in range(...)` loop at `wave_executor.py:2531`

**New function:** `_run_structural_triage(cwd, wave_letter, milestone)` — returns `list[str]` of structural issues found.

**Triage checks:**
1. `package.json` exists and has valid JSON. Missing deps referenced by imports → add them.
2. `tsconfig.json` exists with valid `paths` and `include`. Invalid paths → fix.
3. Required config files present (framework-specific: `next.config.ts` for Next.js, etc.)

**If structural issues found:** Build a structural-fix prompt (different from per-file compile-fix prompt) and invoke the sub-agent ONCE before entering the per-file loop. This prevents wasting 3 iterations on per-file patches when the root cause is a missing tsconfig path.

### A-10 Iteration Improvements

1. **Configurable cap:** Add `fallback_compile_fix_max_iterations` parameter to `_run_wave_compile`. Default: 5 when `fallback_used=True` (caller passes), 3 otherwise.
2. **Per-iteration error tracking:** Track `error_count_per_iteration: list[int]` to detect progress/plateau.
3. **Iteration context in prompt:** Enhance `_build_compile_fix_prompt` to accept optional `previous_error_count: int` and `iteration_number: int`. Include one-line summary: "Iteration 2/5. Previous iteration had 12 errors, now 8. Focus on remaining errors."

### D-16 Post-Fallback Quality

A-09 scope filter (Phase A) adds a scope preamble to Wave B/D prompts. The COMPILE-FIX prompt is a DIFFERENT prompt — it's built by `_build_compile_fix_prompt`, not by the wave prompt builder. A-09 doesn't constrain it.

**Fix:** When building the compile-fix prompt, if fallback was used, prepend the milestone's scope filter (from A-09's `_get_scope_preamble` or equivalent). This focuses the fix sub-agent on in-scope files only.

### Recommended Fix Approach

```python
async def _run_wave_compile(
    run_compile_check, execute_sdk_call,
    wave_letter, template, config, cwd, milestone,
    *,
    fallback_used: bool = False,       # NEW
) -> CompileCheckResult:
    
    # D-15: Structural triage BEFORE per-file loop
    structural_issues = _detect_structural_issues(cwd, wave_letter)
    if structural_issues and execute_sdk_call is not None:
        await _fix_structural_issues(execute_sdk_call, structural_issues, ...)
    
    # A-10: Configurable cap
    max_iterations = 5 if fallback_used else 3
    error_counts: list[int] = []
    
    for iteration in range(max_iterations):
        raw_result = await run_compile_check(...)
        compile_result = _coerce_compile_result(raw_result)
        error_counts.append(len(compile_result.errors))
        
        if compile_result.passed:
            compile_result.iterations = iteration + 1
            return compile_result
        
        if execute_sdk_call is None or iteration >= max_iterations - 1:
            compile_result.iterations = iteration + 1
            return compile_result
        
        # A-10: Enhanced prompt with iteration context
        fix_prompt = _build_compile_fix_prompt(
            compile_result.errors, wave_letter, milestone,
            iteration=iteration,
            max_iterations=max_iterations,
            previous_error_count=error_counts[-2] if len(error_counts) > 1 else None,
        )
        await _invoke_sdk_sub_agent_with_watchdog(...)
```

### Risk Assessment

- **What could go wrong:** Structural triage misidentifies a valid package.json as broken (false positive structural fix).
- **Mitigation:** Structural triage is advisory — it suggests fixes, doesn't delete files. The compile check AFTER structural fix verifies improvement.
- **Cost impact:** Extra iteration capacity (3→5 for fallback) costs more API calls. But failing at 3 and retrying the entire wave is MORE expensive.

### Acceptance Test Design

- Compile-fix loop with a deliberately-broken scaffold (missing `@types/react` in package.json) → structural triage detects and fixes BEFORE per-file loop.
- Compile-fix runs 5 iterations without exhaustion cascade.
- Each iteration prompt includes error count context.

---

## 2. D-12 Telemetry Design — Claude-path `last_sdk_tool_name`

### Current Capture Mechanism

**File:** `wave_executor.py:184-201` — `_WaveWatchdogState.record_progress()`

```python
def record_progress(self, *, message_type="", tool_name="", ...):
    ...
    if tool_name is not None:
        self.last_tool_name = str(tool_name or "")  # line 201
```

**Bug:** Every call to `record_progress` with `tool_name=""` (the default) RESETS `last_tool_name` to empty string. When a wave ends with a text response (AssistantMessage with TextBlock), the final `record_progress` call overwrites the tool name captured during the earlier ToolUseBlock.

### Evidence Chain

1. `cli.py:951-953` — LOCAL state correctly captures tool name via `_sdk_tool_name(msg)`
2. `cli.py:957` — `_emit_progress("assistant_message")` calls wave callback WITHOUT tool_name
3. `cli.py:963` — `_emit_progress("tool_use", block.name)` DOES pass tool name
4. But subsequent `_emit_progress("assistant_text")` at line 960 and `_emit_progress("result_message")` at line 967 pass NO tool_name → reset to ""

### Fix

**File:** `wave_executor.py:200-201`

Change:
```python
if tool_name is not None:
    self.last_tool_name = str(tool_name or "")
```

To:
```python
if tool_name:
    self.last_tool_name = str(tool_name)
```

This ensures `last_tool_name` retains the last NON-EMPTY value. Non-tool messages don't clear it. The tool name persists from the last `tool_use` event through subsequent text/result messages.

**Scope:** 1 line change. No behavioral change except telemetry accuracy.

**Note:** Obsoleted for Codex path by Bug #20. Only Claude path needs this.

---

## 3. D-17 Calibration Table

### Current Calibration Values

**File:** `quality_checks.py:219-226` — `TruthScorer.DIMENSION_WEIGHTS`

| Dimension | Weight |
|-----------|--------|
| requirement_coverage | 0.25 |
| contract_compliance | 0.20 |
| error_handling | 0.15 |
| type_safety | 0.15 |
| test_presence | 0.15 |
| security_patterns | 0.10 |

### error_handling Recalibration (was ~0.06 on NestJS builds)

**Scorer location:** `quality_checks.py:377-458` — `_score_error_handling()`

**Problem:** The scorer counts per-method `try/catch` in service files (lines 414-434). NestJS uses a global `AllExceptionsFilter` registered at app level — individual service methods DON'T need try/catch because the framework catches and handles errors globally. Result: scorer finds 0 try/catch per method → score near-zero.

**Fix:** Before per-method scanning, check if the project uses a global exception filter pattern. Search source files for:
- `AllExceptionsFilter` or `ExceptionFilter`
- `app.useGlobalFilters`
- `@UseFilters` at module/controller level
- `APP_FILTER` provider token

When detected: set a framework baseline of 0.7 for the service_score component, then only penalize methods that should have EXPLICIT handling despite the global filter (e.g., transaction methods).

Implementation: add ~15 lines at the top of `_score_error_handling()` to detect the global filter pattern and apply the baseline.

### test_presence Recalibration (was ~0.29 on M1)

**Scorer location:** `quality_checks.py:481-532` — `_score_test_presence()`

**Problem:** M1 milestones produce scaffolded service files but zero test files (spec says "empty placeholder, no feature logic yet"). The scorer penalizes 0 test coverage even when tests are explicitly not expected.

**Fix:** Add a `min_test_score` parameter to `TruthScorer.score()` (default 0.0). When the caller (milestone wave execution) knows tests are not expected for this milestone (M1 scaffold phase), pass `min_test_score=0.5`. The `_score_test_presence` result gets floored at this value.

Alternative (self-contained in scorer): if `source_count > 0` and `test_count == 0` and the average source file is < 50 lines (placeholder-sized), apply a 0.5 floor — don't penalize empty scaffolds.

**Preferred approach:** Self-contained heuristic in `_score_test_presence` — no caller changes needed:
```python
if not self._test_files and self._source_only:
    avg_size = sum(len(self._read_file(f)) for f in self._source_only[:20]) / max(len(self._source_only[:20]), 1)
    if avg_size < 2000:  # ~50 lines of scaffold code
        return 0.5  # Placeholder files — don't penalize missing tests
```

---

## 4. D-01 Graceful Degradation Design

### Current State

- `run_mcp_preflight` at `mcp_servers.py:429-482` checks `validate_endpoint` and `codebase_intelligence` — NOT context7
- `_prefetch_framework_idioms` at `cli.py:1753-1854` already handles context7 failure gracefully (returns "" on exception, line 1851-1854)
- No TECH_RESEARCH.md stub emitted on failure
- No wave prompt warning when context7 is unavailable

### Fix Design

1. **Extend `run_mcp_preflight`** (mcp_servers.py:449-460) — add context7 to the tools dict:
   ```python
   context7_cfg = config.mcp_servers.get("context7")
   tools["context7"] = {
       "provider": "context7",
       "available": bool(context7_cfg and context7_cfg.enabled),
       "reason": "" if (context7_cfg and context7_cfg.enabled) else "disabled_in_config",
   }
   ```

2. **Emit TECH_RESEARCH.md stub** — in `_prefetch_framework_idioms` exception handler (cli.py:1851-1854), when the fetch fails, write a stub file:
   ```python
   except Exception as exc:
       if log:
           log(f"N-17: Framework idiom pre-fetch failed (non-fatal): {exc}")
       # D-01: Emit TECH_RESEARCH.md stub for downstream visibility
       _emit_tech_research_stub(cwd, str(exc))
       return ""
   ```

3. **Wave prompt warning** — in `_build_wave_prompt` (cli.py:1857), when `mcp_doc_context` is empty and context7 was expected (Wave B/D), add a note:
   ```
   [NOTE: Framework idiom documentation unavailable — context7 pre-fetch failed.
   Use your best judgment based on known patterns. Flag uncertain decisions for review.]
   ```

4. **N-17 prefetch degradation** — already handled (returns "" on failure). Confirmed at cli.py:1851-1854.

### Files to Modify

- `mcp_servers.py:449-460` — add context7 to preflight tools dict (~8 LOC)
- `cli.py:1851-1854` — add stub emission on failure (~15 LOC)
- `cli.py:1857+` — add empty-context7 warning in wave prompt builder (~10 LOC)

---

## 5. D-10 FP Suppression Design

### DB-004 Finding

**File:** `quality_checks.py:3776-3834` — `detect_missing_defaults_and_nullable()`

DB-004 flags boolean/enum properties without explicit defaults in C# entity files. It's a deterministic regex-based check. Pattern IDs: DB-004 (missing default), DB-005 (nullable without null check).

**Phantom behavior:** DB-004 re-fires on every audit cycle even after the fix sub-agent addresses the finding, because:
1. The fix may not remove the exact regex match (e.g., fixes the logic but doesn't add `= false;`)
2. Or the finding is legitimately a false positive (the property has a database default)

### Existing Infrastructure

**File:** `audit_models.py:431-572`
- `FalsePositive` dataclass (finding_id, reason, suppressed_by, timestamp)
- `filter_false_positives()` function — filters by finding_id only
- No fingerprint beyond finding_id
- No auto-suppression for fixed findings
- No per-run tracking

### Fix Design

1. **Extend FalsePositive** with fingerprint fields:
   ```python
   file_path: str = ""
   line_range: tuple[int, int] = (0, 0)
   ```

2. **Add auto-suppression function:**
   ```python
   def build_cycle_suppression_set(
       previous_findings: list[AuditFinding],
       current_fixes: list[str],  # finding_ids that were fix-attempted
   ) -> list[FalsePositive]:
   ```
   For each `fix_applied` finding from the previous cycle, create a `FalsePositive` with `suppressed_by="auto"` and the finding's file_path + line_range fingerprint.

3. **Enhance `filter_false_positives`** to support fingerprint matching:
   ```python
   def filter_false_positives(findings, suppressions):
       suppressed_ids = {fp.finding_id for fp in suppressions}
       suppressed_fingerprints = {
           (fp.finding_id, fp.file_path, fp.line_range)
           for fp in suppressions if fp.file_path
       }
       return [
           f for f in findings
           if f.finding_id not in suppressed_ids
           and (f.finding_id, getattr(f, 'file_path', ''), ...) not in suppressed_fingerprints
       ]
   ```

4. **Safety:** suppression set is PER-RUN only. Fresh run = fresh set. Never persisted.

### Files to Modify

- `audit_models.py:434-462` — extend FalsePositive (~5 LOC)
- `audit_models.py:566-572` — enhance filter_false_positives (~10 LOC)
- New function `build_cycle_suppression_set` in audit_models.py (~20 LOC)

---

## 6. File Edit Coordination Map

| Agent | Primary Files | Lines | Overlap Check |
|-------|--------------|-------|---------------|
| a10-d15-d16 | wave_executor.py:2235-2258, 2517-2596 | ~150 LOC | NO overlap |
| d12 | wave_executor.py:200-201 | ~2 LOC | NO overlap (line 200 vs 2517+) |
| d17 | quality_checks.py:377-458, 481-532 | ~60 LOC | NO overlap |
| d01 | mcp_servers.py:449-460; cli.py:1851-1857+ | ~35 LOC | NO overlap |
| d10 | audit_models.py:434-572 | ~35 LOC | NO overlap |

**Confirmed: ZERO file overlaps between Wave 2 agents.**

A-10 and D-12 both touch `wave_executor.py` but at completely different locations (lines 200 vs 2235+). No risk of merge conflict.

---

## 7. Self-Audit

- A-10 investigation doc read fully before analysis
- All 5 items have exact file:line targets
- No file overlaps between Wave 2 agents
- Root causes are structural, not band-aid fixes
- D-14 confirmed DONE in Phase C (skipped)
- Risk properly assessed: A-10 HIGH, everything else LOW
