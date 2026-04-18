# Phase D Wiring Verification Report

Generated: 2026-04-17

---

## V1: A-10/D-15/D-16 — Compile-fix improvements

### V1.1: `_detect_structural_issues` called BEFORE iteration loop
**PASS** — `wave_executor.py:2628-2629`: Inside `_run_wave_compile`, `_detect_structural_issues(cwd, wave_letter)` is called at line 2629, before the `for iteration in range(max_iterations)` loop at line 2655. The structural fix sub-agent is invoked at lines 2637-2645 when issues are found.

### V1.2: `max_iterations = 5 if fallback_used else 3`
**PASS** — `wave_executor.py:2650`: Exactly `max_iterations = 5 if fallback_used else 3`. The `fallback_used` parameter is declared with default `False` at line 2622.

### V1.3: `_build_compile_fix_prompt` receives `iteration`, `max_iterations`, `previous_error_count`
**PASS** — `wave_executor.py:2690-2695`: The call passes all three kwargs:
```python
fix_prompt = _build_compile_fix_prompt(
    compile_result.errors, wave_letter, milestone,
    iteration=iteration,
    max_iterations=max_iterations,
    previous_error_count=previous_count,
)
```
The function signature at line 2236-2243 declares all three as keyword-only with defaults (`iteration: int = 0`, `max_iterations: int = 3`, `previous_error_count: int | None = None`).

### V1.4: Callers in `execute_milestone_waves` pass `fallback_used=wave_result.fallback_used`
**PASS** — Two call sites in `execute_milestone_waves` pass `fallback_used`:
- `wave_executor.py:3149`: `fallback_used=wave_result.fallback_used` (first execute path, waves A/B/D/D5)
- `wave_executor.py:3605`: `fallback_used=wave_result.fallback_used` (second execute path / multi-loop)

### V1.5: Wave T and guard function callers leave `fallback_used` at default `False`
**PASS** — Verified all non-milestone callers omit `fallback_used`:
- `wave_executor.py:2171-2179`: Wave T caller — no `fallback_used` kwarg, defaults to `False`
- `wave_executor.py:2806-2814`: `_run_wave_b_dto_contract_guard` — no `fallback_used`, defaults to `False`
- `wave_executor.py:2929-2937`: `_run_wave_d_frontend_hallucination_guard` — no `fallback_used`, defaults to `False`

---

## V2: D-12 — Telemetry tool name retention

### V2.1: `record_progress` uses `if tool_name:` (not `if tool_name is not None:`)
**PASS** — `wave_executor.py:201`: The guard is `if tool_name:` which is a truthy check. This correctly filters out empty strings and None.

### V2.2: `record_progress` uses `str(tool_name)` (not `str(tool_name or "")`)
**PASS** — `wave_executor.py:202`: The assignment is `self.last_tool_name = str(tool_name)`. The `str()` call is unconditional within the `if tool_name:` guard, so it always receives a truthy value.

### V2.3: Claude-path callers flow tool_name through to watchdog state
**PASS** — Traced the full flow:
1. `cli.py:963`: `_emit_progress("tool_use", block.name)` passes `block.name` from `ToolUseBlock`
2. `cli.py:919-923`: `_emit_progress` calls `progress_callback(message_type=message_type, tool_name=tool_name)`
3. `wave_executor.py:1317`: `progress_callback=state.record_progress` — the callback IS `_WaveWatchdogState.record_progress`
4. `wave_executor.py:201-202`: `record_progress` stores `str(tool_name)` into `self.last_tool_name`
5. `wave_executor.py:203-209`: The tool_name is also appended to `self.recent_events` for watchdog inspection

The tool name flows end-to-end from Claude SDK `ToolUseBlock.name` through `_emit_progress` -> `progress_callback` -> `record_progress` -> `last_tool_name` + `recent_events`.

---

## V3: D-17 — Truth-score calibration

### V3.1: Global filter detection scans source files for 5 patterns
**PASS** — `quality_checks.py:391-400`:
```python
_global_filter_patterns = (
    "AllExceptionsFilter", "ExceptionFilter",
    "useGlobalFilters", "@UseFilters", "APP_FILTER",
)
```
Exactly 5 patterns. Scans `self._source_only[:100]` files, reads content, checks `any(pat in content for pat in _global_filter_patterns)`.

### V3.2: 0.7 floor applied BEFORE blend logic
**PASS** — `quality_checks.py:467-473`: The `if has_global_filter:` block applies the 0.7 floor to `service_score` or `general_score` at lines 468-473, BEFORE the blend logic at lines 475-480 (`service_score * 0.7 + general_score * 0.3`). Execution order is correct — floor first, blend second.

### V3.3: `_score_test_presence` placeholder scaffold floor (avg_size < 2000 -> return 0.5) BEFORE service file matching
**PASS** — `quality_checks.py:519-523`: The scaffold check is at lines 519-523:
```python
if not self._test_files and self._source_only:
    sample = self._source_only[:20]
    avg_size = sum(len(self._read_file(f)) for f in sample) / max(len(sample), 1)
    if avg_size < 2000:
        return 0.5
```
This is BEFORE the service file matching logic which starts at line 526 (`service_keywords = ...`). The early `return 0.5` short-circuits before service matching runs.

### V3.4: `TruthScorer.score()` calls both dimensions normally
**PASS** — `quality_checks.py:246-253`: `score()` builds a `dimensions` dict calling all 6 scoring methods including:
- `"error_handling": self._score_error_handling()` (line 249)
- `"test_presence": self._score_test_presence()` (line 251)

Both are called unconditionally and passed to `TruthScore.from_dimensions(dimensions)` at line 254.

---

## V4: D-01 — Context7 quota

### V4.1: `run_mcp_preflight` context7 entry with correct fields
**PASS** — `mcp_servers.py:463-469`:
```python
context7_cfg = config.mcp_servers.get("context7")
context7_available = bool(context7_cfg and context7_cfg.enabled)
tools["context7"] = {
    "provider": "context7",
    "available": context7_available,
    "reason": "" if context7_available else "disabled_in_config",
}
```
Has `available` (bool) and `reason` (str) fields. Correctly checks config enablement.

### V4.2: `_prefetch_framework_idioms` exception handler emits TECH_RESEARCH.md stub
**PASS** — `cli.py:1851-1870`: The outer `except Exception as exc:` handler at line 1851:
1. Logs via `log(f"N-17: ...")` at line 1853
2. Writes TECH_RESEARCH.md stub at lines 1855-1869 with content:
   - `"# Tech Research Unavailable\n\n"`
   - `f"Context7 framework idiom pre-fetch failed: {exc}\n\n"`
   - `"Model will use training-data approximations..."`
3. Only writes if `not stub_path.is_file()` (idempotent)

### V4.3: `_build_wave_prompt_with_idioms` — Wave B/D warning injection when mcp_doc_context empty
**PASS** — Two copies verified:
- `cli.py:3779-3784` (worktree path): Checks `if w in ("B", "D") and not kwargs["mcp_doc_context"]:` then injects the warning string starting with `"[NOTE: Framework idiom documentation unavailable..."`.
- `cli.py:4408-4414` (mainline path): Identical logic in `_build_wave_prompt_with_idioms_ml`.

Both copies inject the warning only for waves B and D, only when the prefetch returned empty.

### V4.4: N-17 prefetch returns "" on failure (not an exception)
**PASS** — `cli.py:1870`: The exception handler returns `return ""` at line 1870. Additionally:
- Early return `""` at line 1763 when `mcp_informed_dispatches_enabled` is False
- Early return `""` at line 1768 when no queries for the wave
- Early return `""` at line 1790 when `context7_servers` is empty
- Early return `""` at line 1834 when `doc_text` is empty
- All failure paths return `""`, never raise.

---

## V5: D-10 — FP suppression

### V5.1: `FalsePositive` has `file_path` and `line_range` fields with correct defaults
**PASS** — `audit_models.py:446-447`:
```python
file_path: str = ""
line_range: tuple[int, int] = (0, 0)
```
Both fields present with correct default values.

### V5.2: `to_dict`/`from_dict` round-trip the new fields
**PASS** — `audit_models.py:449-468`:
- `to_dict()` serializes both: `"file_path": self.file_path` and `"line_range": list(self.line_range)` (tuple -> list for JSON)
- `from_dict()` deserializes both: `file_path=data.get("file_path", "")` and `line_range=tuple(data.get("line_range", (0, 0)))` (list -> tuple)
Round-trip is correct with proper type conversion.

### V5.3: `filter_false_positives` handles both ID-only and fingerprinted suppressions
**PASS** — `audit_models.py:579-611`:
- ID-only (manual): Line 590 — `suppressed_ids = {fp.finding_id for fp in suppressions if not fp.file_path}` — suppresses ALL instances of that finding_id
- Fingerprinted (auto): Lines 593-596 — builds `suppressed_fingerprints` set of `(finding_id, file_path, line_range)` tuples for suppressions WITH `file_path`
- Filtering: Lines 598-611 — checks ID-only first (line 600), then fingerprint match (lines 602-609)

### V5.4: `build_cycle_suppression_set` creates `FalsePositive` entries with correct fields
**PASS** — `audit_models.py:634-641`:
```python
suppressions.append(FalsePositive(
    finding_id=finding.finding_id,
    reason=f"Auto-suppressed: fix applied in previous cycle",
    suppressed_by="auto",
    timestamp=...,
    file_path=getattr(finding, "file_path", "") or "",
    line_range=_finding_line_range(finding),
))
```
- `suppressed_by="auto"` — correct
- `file_path` extracted from finding with safe default
- `line_range` uses `_finding_line_range(finding)` — correct

### V5.5: `_finding_line_range` extracts line/end_line with safe defaults
**PASS** — `audit_models.py:572-576`:
```python
def _finding_line_range(finding: AuditFinding) -> tuple[int, int]:
    line = getattr(finding, "line", 0) or 0
    end_line = getattr(finding, "end_line", 0) or line
    return (line, end_line)
```
- Uses `getattr` with default `0` — safe if attribute missing
- Uses `or 0` / `or line` — safe if attribute is None
- Falls back `end_line` to `line` when not set — correct single-line behavior

---

## Summary

| Section | Item | Status |
|---------|------|--------|
| V1 | V1.1 structural triage before loop | PASS |
| V1 | V1.2 iteration cap 5/3 | PASS |
| V1 | V1.3 compile fix prompt kwargs | PASS |
| V1 | V1.4 fallback_used propagation | PASS |
| V1 | V1.5 Wave T/guards default False | PASS |
| V2 | V2.1 tool_name truthy check | PASS |
| V2 | V2.2 str(tool_name) | PASS |
| V2 | V2.3 end-to-end telemetry flow | PASS |
| V3 | V3.1 global filter 5 patterns | PASS |
| V3 | V3.2 0.7 floor before blend | PASS |
| V3 | V3.3 scaffold floor before service | PASS |
| V3 | V3.4 score() calls both dimensions | PASS |
| V4 | V4.1 preflight context7 entry | PASS |
| V4 | V4.2 TECH_RESEARCH.md stub | PASS |
| V4 | V4.3 Wave B/D warning injection | PASS |
| V4 | V4.4 returns "" not exception | PASS |
| V5 | V5.1 FalsePositive fields | PASS |
| V5 | V5.2 to_dict/from_dict round-trip | PASS |
| V5 | V5.3 ID + fingerprint filtering | PASS |
| V5 | V5.4 auto suppression entries | PASS |
| V5 | V5.5 safe line range extraction | PASS |

**Result: 21/21 verification points PASS. No wiring issues found.**
