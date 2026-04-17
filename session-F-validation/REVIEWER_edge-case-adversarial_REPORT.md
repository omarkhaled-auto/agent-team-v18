# Phase F — Edge Case Adversarial Reviewer Report

> Task #6 deliverable. Mid-flight halt triggered on CRITICAL F-EDGE-001.
> No fixes deployed pending team-lead authorization because F-EDGE-001
> is a structural wiring change spanning multiple files, not a single
> guard/typed-except.
>
> Areas reviewed (in priority order from the task brief): Area 11
> (budget removal), Area 2 (flag combinations), Area 10 (multi-milestone
> accumulation), Area 7 (restart idempotence), Area 8 (malformed scorer
> output), Area 9 (disk-full partial writes), Area 3 (wave-failure
> permutations), Area 1 (empty inputs on new Phase F modules). Areas 4
> (context7), 5 (codex app-server), and 6 (SDK expiry) have no
> Phase-F-specific attack surface — the Phase F modules are deterministic
> and offline; their call sites (currently none — see F-EDGE-001) would
> also be offline-safe.

---

## F-EDGE-001: All 4 Phase F modules are dead code — feature flags default True but pipeline never invokes them

**Severity:** CRITICAL
**Area:** flag combinations + Phase F wiring
**Scenario:** User runs a full smoke with Phase F defaults (all 4 new flags True). Expectation from `SWEEPER_REPORT.md` Touches 2–5 is that `wave_b_sanitizer` runs after Wave B, `audit_scope_scanner` runs before the audit, `confidence_banners.stamp_all_reports` stamps every artefact at end-of-run, and `infra_detector.detect_runtime_infra` feeds probe URL assembly. None of this actually happens.
**File:line where it breaks:**
- `src/agent_team_v15/wave_b_sanitizer.py:238` `sanitize_wave_b_outputs` — no production import
- `src/agent_team_v15/confidence_banners.py:257` `stamp_all_reports` — no production import
- `src/agent_team_v15/audit_scope_scanner.py:199` `scan_audit_scope` — no production import
- `src/agent_team_v15/infra_detector.py:167` `detect_runtime_infra` — no production import
- `src/agent_team_v15/infra_detector.py:241` `build_probe_url` — no production import

Evidence: Grepping the `src/agent_team_v15/` tree for every export of each module returns matches ONLY from the module file itself and the corresponding `tests/test_*.py`. No call site in `cli.py`, `wave_executor.py`, `audit_team.py`, `coordinated_builder.py`, `endpoint_prober.py`, or any other orchestrator.
**Current behavior:** `v18.wave_b_output_sanitization_enabled=True`, `v18.confidence_banners_enabled=True`, `v18.audit_scope_completeness_enabled=True`, `v18.runtime_infra_detection_enabled=True` — all default True at `src/agent_team_v15/config.py:911-943`. Zero production call sites. 10,530/0 pytest passes because the tests call the functions directly. In a real smoke run the four features are inert; the operator sees no `AUDIT-SCOPE-GAP-*`, no `N-19-ORPHAN-*`, no `[CONFIDENCE=...]` banner, no probe URL honoring `setGlobalPrefix`.
**Expected behavior:** Per `docs/PHASE_F_ARCHITECTURE_CONTEXT.md` lines 130-140 and `SWEEPER_REPORT.md` §2 Touches 2-5, the four modules should be wired into the pipeline call sites for the default configuration. The flag should gate behavior, not gate a function that is never called.
**Proposed fix:**
1. `wave_b_sanitizer`: in `wave_executor.py`, post-Wave-B phase, call `sanitize_wave_b_outputs(cwd=cwd, contract=load_ownership_contract(cwd), wave_b_files=emitted_files, config=config)` and feed `build_orphan_findings(report)` into the audit payload. Flag check is inside the function.
2. `confidence_banners`: in `cli.py` end-of-run (after `_run_audit_loop` returns for the final milestone and after `BUILD_LOG.txt` is sealed) call `stamp_all_reports(agent_team_dir=agent_team_dir, signals=build_confidence_signals_from_state(state), config=config)`.
3. `audit_scope_scanner`: in `_run_audit_loop` before the first cycle's scorer dispatch, call `scan_audit_scope(cwd=cwd, requirements_path=requirements_path, config=config)` and `build_scope_gap_findings(gaps)` — merge into the initial findings set.
4. `infra_detector`: in `endpoint_prober._detect_app_url` (or its caller in wave_executor) call `detect_runtime_infra(project_root, config=config)` and use `build_probe_url(app_url, route, infra=infra)` when assembling probe URLs.

Also: add an integration test for each call site that asserts the production path actually invokes the module (not just the module's behavior in isolation). The current tests pass with the module unwired.
**Fix status:** NOT DEPLOYED (mid-flight halt). Requires team-lead authorization because the fix is a multi-file wiring change that touches `wave_executor.py`, `cli.py`, `endpoint_prober.py`, and adds integration tests. This is beyond the scope of an adversarial-fixer single-guard patch.

---

## F-EDGE-002: N-11 Wave D cascade globalises a per-milestone failure and mis-attributes healthy milestones' findings

**Severity:** HIGH
**Area:** multi-milestone accumulation + wave failure permutations
**Scenario:** Run M1-M6. M2 fails Wave D (sets `state.wave_progress["M2"]["failed_wave"] = "D"`). M3-M6 proceed and M1 was already healthy. At M4's audit, `_consolidate_cascade_findings` is called; it invokes `_load_wave_d_failure_roots(cwd)` which scans EVERY milestone's wave_progress. As long as ANY milestone has `failed_wave == "D"`, the function returns `["apps/web", "packages/api-client"]` GLOBALLY. M4's audit report then collapses any finding mentioning `apps/web/` (which might legitimately reference M1's healthy web output) into an "upstream Wave D" cascade meta-finding.
**File:line where it breaks:** `src/agent_team_v15/cli.py:626-668` (`_load_wave_d_failure_roots`). Specifically the loop at line 651-657 OR-joins across all milestones without scoping to the current milestone.
**Current behavior:** Any historical Wave D failure in any milestone persists as a cascade root FOREVER (until state is reset), silently collapsing legitimate findings that happen to reference `apps/web` or `packages/api-client` in unrelated, healthy milestones. Operators see phantom cascades blaming Wave D on milestones where Wave D never ran.
**Expected behavior:** Cascade roots should be scoped to the current milestone's `failed_wave`. When consolidating findings for M4's audit, we should only treat `apps/web` as a cascade root if M4 (or the milestone actually failing) has `failed_wave == "D"` — not merely that some earlier milestone did.
**Proposed fix:** Accept a `milestone_id` parameter in `_load_wave_d_failure_roots` and only return roots when `state.wave_progress.get(milestone_id, {}).get("failed_wave") == "D"`. Update the caller `_consolidate_cascade_findings` (cli.py:671) to thread the active milestone id through. For aggregate reports that are genuinely cross-milestone, keep the any-milestone behavior but mark the cascade meta-finding with the specific milestone(s) that failed.
**Fix status:** NOT DEPLOYED (queued for adversarial-fixer).

---

## F-EDGE-003: Malformed scorer output with `findings` as dict silently drops entire AuditReport

**Severity:** HIGH
**Area:** malformed scorer output
**Scenario:** Scorer LLM drifts and emits `{"findings": {"0": {...}, "1": {...}}, ...}` (dict of findings, keyed by index) instead of `{"findings": [{...}, {...}]}`. Caller reads AUDIT_REPORT.json and calls `AuditReport.from_json(raw)`.
**File:line where it breaks:** `src/agent_team_v15/audit_models.py:326`:
```python
findings = [AuditFinding.from_dict(f) for f in data.get("findings", [])]
```
When `data["findings"]` is a dict, Python iterates the dict's KEYS (strings "0", "1"). `AuditFinding.from_dict("0")` then calls `"0".get("finding_id")` → AttributeError. Propagates out of `from_json`.
**Current behavior:** AttributeError not caught inside `from_json`. Callers of `from_json` (cli.py:6456 inside `_run_audit_loop`, coordinated_builder, test code) handle `Exception` broadly at the outer level (the audit-loop resume guard at cli.py:6471 catches but treats as "no prior report"). The EFFECT is: every cycle silently restarts from cycle 1 without surfacing the fact that the scorer produced malformed JSON.
**Expected behavior:** `from_json` should raise a typed `ScorerShapeError` (or at minimum validate `isinstance(data.get("findings"), list)`) so the caller can log/surface the drift and trigger a rescorer dispatch, not silently retry.
**Proposed fix:** At `audit_models.py:326`, add:
```python
raw_findings = data.get("findings", [])
if not isinstance(raw_findings, list):
    raise ValueError(
        f"AuditReport.findings must be a list, got {type(raw_findings).__name__}. "
        "Scorer returned a malformed schema."
    )
findings = [AuditFinding.from_dict(f) for f in raw_findings if isinstance(f, dict)]
```
Same shape check for `data.get("auditors_deployed", [])` and `data.get("fix_candidates", [])`.
**Fix status:** NOT DEPLOYED (queued for adversarial-fixer).

---

## F-EDGE-004: wave_b_sanitizer consumer scan is O(N*M) — revisits workspace per orphan, no reuse

**Severity:** MEDIUM
**Area:** disk I/O scaling + multi-milestone accumulation
**Scenario:** By M6, the workspace has 5-10k TS/JS files. Wave B emits 5 orphans in a single milestone. The sanitizer calls `_scan_for_consumers(workspace, rel)` once per orphan. Each call at `wave_b_sanitizer.py:189` does `for candidate in workspace.rglob(glob_pat):` over each of 6 globs, re-reading every TS/JS file for every orphan. 5 orphans × 6 globs × 5000 files × text read = 150k file reads per milestone.
**File:line where it breaks:** `src/agent_team_v15/wave_b_sanitizer.py:186-222` — `_scan_for_consumers` has no indexing / caching / batching. Each call is independent.
**Current behavior:** On a post-M6 project this scan can take minutes, dominating post-Wave-B time. Dormant today because F-EDGE-001 (sanitizer not wired into pipeline), but as soon as it's wired the scaling is O(orphans × workspace_files).
**Expected behavior:** Build a single index of all TS/JS imports once per sanitizer invocation, then check each orphan against the index in O(orphans) time.
**Proposed fix:** Refactor `_scan_for_consumers` into two phases: (a) `_build_import_index(workspace)` returns `dict[specifier -> list[consumer_path]]` built once; (b) per-orphan lookup is a dict access. Cache the index on `SanitizationReport` for sequential orphan checks.
**Fix status:** NOT DEPLOYED (queued; may be deferred since F-EDGE-001 must be resolved first).

---

## F-EDGE-005: confidence_banners.stamp_all_reports clobbers prior milestones' banners with later milestone's signals

**Severity:** MEDIUM
**Area:** multi-milestone accumulation + restart idempotence
**Scenario:** M1 converges, `stamp_all_reports` runs, M1's `milestones/M1/AUDIT_REPORT.json` gets `confidence=CONFIDENT`. M2 runs, plateaus. Per `stamp_all_reports` semantics at `confidence_banners.py:280-285`, the loop `for audit_json in list(root.glob("AUDIT_REPORT.json")) + list(root.glob("milestones/*/AUDIT_REPORT.json"))` re-writes M1's report with M2's signals. M1's banner now says `confidence=LOW` even though M1 was healthy.
**File:line where it breaks:** `src/agent_team_v15/confidence_banners.py:257-309` (`stamp_all_reports`). The function accepts a single `ConfidenceSignals` and broadcasts it to every found artefact.
**Current behavior:** Dormant (F-EDGE-001 umbrella — not called). Once wired, this would silently corrupt per-milestone trust signals.
**Expected behavior:** Derive signals per-milestone (from each milestone's own STATE subset / fix-loop status) and stamp each artefact with its own confidence. The top-level AUDIT_REPORT.json gets an aggregate.
**Proposed fix:** Change signature: `stamp_all_reports(agent_team_dir, *, signals_for_path: Callable[[Path], ConfidenceSignals], config)`. Caller supplies a function that produces the right signals for a given report path.
**Fix status:** NOT DEPLOYED (queued; depends on F-EDGE-001 resolution).

---

## F-EDGE-006: Audit loop plateau detection fails on exact-3.0 oscillation

**Severity:** MEDIUM
**Area:** budget removal (what actually bounds the loop now)
**Scenario:** Fix loop oscillates scores 92 → 89 → 92 → 89 → 92 with exact 3.0-point swings. Rollback-on-regression at cli.py:6604 only triggers on drop of MORE than 1 below best (`current_score_val < best_score - 1`). Plateau check at cli.py:6621 requires BOTH `delta_prev < 3.0` AND `delta_prev2 < 3.0`. An exact 3.0 delta fails the `< 3.0` check. Loop runs to `max_cycles`.
**File:line where it breaks:** `src/agent_team_v15/cli.py:6618-6628`.
**Current behavior:** With `max_reaudit_cycles = 3` (default), this is only 3 cycles max. But budget removal mean no upstream cap if the cycle budget is ever raised by a user config. The structural weakness remains.
**Expected behavior:** Use `<=` rather than `<`, OR track a boolean "oscillating between two scores" over 4+ data points.
**Proposed fix:** Change cli.py:6621 to `if delta_prev <= 3.0 and delta_prev2 <= 3.0:`. Additionally, add an oscillation check: if `len(previous_scores) >= 4` and `previous_scores[-1] == previous_scores[-3]` and `previous_scores[-2] == previous_scores[-4]`, break with `print_info("Score oscillation detected")`.
**Fix status:** NOT DEPLOYED (queued for adversarial-fixer).

---

## F-EDGE-007: Disk-full partial-write of AUDIT_REPORT.json causes silent stale-report reuse on next restart

**Severity:** MEDIUM
**Area:** disk full + restart scenarios
**Scenario:** Disk fills mid-execution of `_run_audit_loop`. At cli.py:6651, `report_path.write_text(current_report.to_json(), encoding="utf-8")` fails with OSError. The `except Exception` at 6652 logs a warning but the function returns the in-memory `current_report` and `total_cost`. Caller proceeds as if audit succeeded. Next run (after disk is cleared): resume guard at cli.py:6454 reads the OLD (stale or partially-written) AUDIT_REPORT.json — if it was truncated, `from_json` raises, caught at 6471 which quietly "resumes from cycle 1" — the prior run's ENTIRE audit cost is lost and the loop re-runs.
**File:line where it breaks:** `src/agent_team_v15/cli.py:6648-6653` and `cli.py:6454-6479` (resume guard).
**Current behavior:** Silent data loss + hidden double-spending on retries. Operator sees "Audit succeeded" at end of first run but the persisted state is wrong.
**Expected behavior:** Write to a sibling temp file first, then atomic rename. On write failure, either fail loudly or at minimum stamp a `incomplete: true` marker the resume guard respects.
**Proposed fix:** At cli.py:6651, replace with:
```python
tmp = report_path.with_suffix(".json.tmp")
try:
    tmp.write_text(current_report.to_json(), encoding="utf-8")
    tmp.replace(report_path)
except OSError as exc:
    print_warning(f"AUDIT_REPORT.json write FAILED: {exc}")
    # Leave old report in place if any; surface via return contract.
    return current_report, total_cost  # consider raising instead
```
**Fix status:** NOT DEPLOYED (queued for adversarial-fixer).

---

## F-EDGE-008: LoopState accepts `max_iterations=0 / negative / None` with no validation — halts immediately or raises TypeError

**Severity:** MEDIUM
**Area:** budget removal edge cases (what remains as a bound)
**Scenario:** Operator overrides `max_iterations` in PRD/config. If they set 0 (perhaps thinking "disabled"), every audit cycle immediately hits `state.current_run >= 0 == True` at config_agent.py:495 → STOP on first cycle before fix. If they set negative, same. If an old state.json had `max_iterations: null`, `state.current_run >= None` raises TypeError (Python 3).
**File:line where it breaks:** `src/agent_team_v15/config_agent.py:70` (`max_iterations: int = 4` — no validation) and `config_agent.py:495` (the comparison).
**Current behavior:** Coerces any invalid value into a silently-broken termination decision or a crash.
**Expected behavior:** Validate at `LoopState.__post_init__` (or in `from_dict`) that `max_iterations >= 1`; raise `ValueError` with actionable message.
**Proposed fix:** Add `__post_init__` to `LoopState`:
```python
def __post_init__(self):
    if not isinstance(self.max_iterations, int) or self.max_iterations < 1:
        raise ValueError(
            f"LoopState.max_iterations must be >= 1, got {self.max_iterations!r}"
        )
```
**Fix status:** NOT DEPLOYED (queued for adversarial-fixer).

---

## F-EDGE-009: audit_scope_scanner silently returns zero gaps on empty or misformatted REQUIREMENTS.md

**Severity:** LOW
**Area:** empty/minimal inputs (Area 1)
**Scenario:** User writes REQUIREMENTS.md with requirements NOT in the `- [ ] REQ-NNN:` checkbox form. Perhaps `* REQ-001: ...` or `1. REQ-001: ...` or the file is completely empty. `_parse_requirements_md` at audit_scope_scanner.py:76 returns `[]` and `scan_audit_scope` returns `[]` → operator sees no gaps reported when in reality EVERY requirement is uncovered.
**File:line where it breaks:** `src/agent_team_v15/audit_scope_scanner.py:73-99` (regex anchored to `^-\s*\[[ xX]\]` dash-bracket form).
**Current behavior:** Silent pass — scanner reports zero gaps on a file whose entire format it does not recognize.
**Expected behavior:** If the file exists but parser finds zero requirement rows, emit an `AUDIT-SCOPE-PARSE` INFO finding indicating the scanner could not parse any requirement lines.
**Proposed fix:** In `scan_audit_scope` after `requirements = _parse_requirements_md(req_path)`, if `req_path.is_file()` but `len(requirements) == 0`, emit a single parse-failure `ScopeGap`:
```python
if req_path.is_file() and not requirements:
    return [ScopeGap(
        requirement_id="AUDIT-SCOPE-PARSE-FAIL",
        title="REQUIREMENTS.md present but no REQ-/AC- rows parsed",
        checked_against=["parser"],
        reason=f"_parse_requirements_md found zero rows in {req_path}. "
               "Expected format '- [ ] REQ-NNN: ...' or '- [ ] AC-NNN: ...'.",
    )]
```
**Fix status:** NOT DEPLOYED (queued; dormant under F-EDGE-001 umbrella).

---

## F-EDGE-010: infra_detector JWT audience scan is unbounded per module

**Severity:** LOW
**Area:** empty inputs + scaling
**Scenario:** Large M2+ project with 10k+ `.ts` files under `apps/api/src`. `_jwt_audience_from_modules` at infra_detector.py:151 does `for ts_file in api_src.rglob("*.ts"):` with a substring check `if "Jwt" not in text and "jwt" not in text: continue` — but still READS every TS file into memory via `_read_text(ts_file)` before the substring skip.
**File:line where it breaks:** `src/agent_team_v15/infra_detector.py:151-163`.
**Current behavior:** Reads full text of every TS file, then skips non-JWT files. O(total TS file size) per call regardless of how many files actually contain JWT.
**Expected behavior:** Limit to files matching `*module.ts` / `*.module.ts` (per the docstring targeting NestJS modules), or read only the first 4 KB to substring-check for "Jwt".
**Proposed fix:**
```python
for ts_file in api_src.rglob("*module.ts"):  # narrow scope to NestJS modules
    try:
        text = ts_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    if "jwt" not in text.lower():
        continue
    ...
```
**Fix status:** NOT DEPLOYED (queued; dormant under F-EDGE-001 umbrella).

---

## F-EDGE-011: coordinated_builder `while True` outer loop has no emergency brake when config is malformed

**Severity:** LOW
**Area:** budget removal (residual bound)
**Scenario:** Budget CAP gone. Outer loop at `coordinated_builder.py:587` is `while True`. Breaks come only via `config_agent.evaluate_stop_conditions` returning `STOP`. If `LoopState.from_dict` succeeds with `max_iterations=None` (not validated — see F-EDGE-008), the `state.current_run >= state.max_iterations` comparison raises TypeError INSIDE `evaluate_stop_conditions`, which is caught somewhere upstream as a generic exception — but the effect is the `while True` may go around once more. In practice other stop conditions would catch it (zero actionable / convergence), but the loop has no circuit-breaker for "10 iterations without any STOP decision returned".
**File:line where it breaks:** `src/agent_team_v15/coordinated_builder.py:587` (`while True`) + no structural safety rail independent of `LoopDecision`.
**Current behavior:** Bounded in happy path; dangerous if `evaluate_stop_conditions` itself becomes buggy (no defense in depth).
**Expected behavior:** Add `_MAX_OUTER_ITERATIONS = 50` structural safety rail independent of config.
**Proposed fix:**
```python
_MAX_OUTER_ITERATIONS = 50  # defense in depth regardless of LoopState.max_iterations
iteration_count = 0
while True:
    iteration_count += 1
    if iteration_count > _MAX_OUTER_ITERATIONS:
        _log(f"FATAL SAFETY RAIL: outer loop exceeded {_MAX_OUTER_ITERATIONS}")
        state.status = "failed"
        state.stop_reason = f"SAFETY_RAIL: outer loop exceeded {_MAX_OUTER_ITERATIONS}"
        state.save(agent_team_dir)
        return _build_result(state, last_report, state.stop_reason)
    ...
```
**Fix status:** NOT DEPLOYED (queued; low priority).

---

# Summary

| ID | Severity | Area | Dormancy |
| --- | --- | --- | --- |
| F-EDGE-001 | CRITICAL | wiring / flag combinations | ACTIVE — all Phase F features are non-functional |
| F-EDGE-002 | HIGH | multi-milestone + wave failure | ACTIVE — N-11 cascade is wired |
| F-EDGE-003 | HIGH | malformed scorer | ACTIVE — any scorer can trigger |
| F-EDGE-004 | MEDIUM | scaling | dormant (depends on F-EDGE-001) |
| F-EDGE-005 | MEDIUM | multi-milestone | dormant (depends on F-EDGE-001) |
| F-EDGE-006 | MEDIUM | budget removal / plateau | ACTIVE |
| F-EDGE-007 | MEDIUM | disk full / restart | ACTIVE |
| F-EDGE-008 | MEDIUM | budget removal | ACTIVE |
| F-EDGE-009 | LOW | empty inputs | dormant (depends on F-EDGE-001) |
| F-EDGE-010 | LOW | scaling | dormant (depends on F-EDGE-001) |
| F-EDGE-011 | LOW | budget removal | ACTIVE (defense in depth) |

## Halt Justification

F-EDGE-001 is a structural wiring gap: the entire set of Phase F Touches 2-5 is inert. Fixing it requires modifying `cli.py`, `wave_executor.py`, `endpoint_prober.py`, and adding integration tests that assert the call sites. This is well beyond a single-guard fix and needs team-lead direction on:

1. Whether F-EDGE-001 should be closed IN Phase F (before production smoke), or documented and deferred to a follow-up phase with flags defaulted False.
2. Whether active-impact findings F-EDGE-002/003/006/007/008/011 should be fixed now (they don't depend on wiring Phase F modules and are within adversarial-fixer scope).
3. The right ordering — fixing F-EDGE-005 in isolation is wasted work if F-EDGE-001 is punted.

I deployed no fixers. Status of Task #6: review complete, fixes pending authorization.

_End of report._
