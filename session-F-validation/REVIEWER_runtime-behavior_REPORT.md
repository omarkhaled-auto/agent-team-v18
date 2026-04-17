# Phase F — Runtime Behavior Reviewer Report

**Scope:** Task #4 — deadlock, race, resource leak, silent failure analysis after Phase F sweeper (budget removal + 4 new modules).

**Method:** sequential-thinking traces for every execution path, targeted reads of the four budget-loop sites plus Phase E SDK wiring and Phase F new modules.

## Summary

| Area | Verdict |
| --- | --- |
| Area 8 (budget-removal loops) | **CLEARED** — every loop still has a non-cost structural bound |
| Area 1 (async/await) | CLEARED for Phase F (modules fully sync). 1 HIGH pre-existing Phase E issue flagged (not Phase F) |
| Area 2 (resource cleanup) | 1 MEDIUM SIGINT partial-write finding |
| Area 3 (races) | CLEARED — no parallel write conflicts |
| Area 4 (silent failures) | 1 LOW silent-OSError-on-delete finding |
| Area 5 (Phase E) | 1 HIGH orphan-detected-never-interrupted finding (pre-Phase-F, codex_appserver) |
| Area 6 (Phase D) | Out of scope for this reviewer |
| Area 7 (SIGINT) | Covered by Area 2 |

**Phase-F-introduced issues that would block the production smoke:** none CRITICAL. The two HIGH findings are pre-Phase-F (codex_appserver orphan wiring, pre-existing).

**Budget-removal safety verdict:** every loop documented in `BUDGET_REMOVAL_AUDIT.md` has been traced. Each either iterates a bounded `range(...)` OR exits via a non-cost structural condition (convergence / plateau / max_iterations / per-service attempts / total-rounds). No runaway loop was introduced by the sweeper.

**Cross-cutting Phase F finding (informational, not runtime):** all four new Phase F modules (`infra_detector`, `confidence_banners`, `audit_scope_scanner`, `wave_b_sanitizer`) are not imported from any production call site. From a runtime perspective this means they introduce no risk today, but also zero observable benefit — see F-RT-005 below.

---

## F-RT-001: codex_appserver orphan detected but never interrupted
**Severity:** HIGH
**Area:** async / Phase E (flagged for awareness — Phase F did not introduce it)
**File:line:** `src/agent_team_v15/codex_appserver.py:277-368`, `_execute_turn`

**Execution trace (sequential-thinking step-by-step):**

1. `_execute_turn` opens `AppServerClient` context, calls `client.thread_start`, then enters `while True:` at line 277.
2. Each iteration calls `client.turn_start(...)` then `client.wait_for_turn_completed(turn_id, on_event=...)` at line 299 — **this is a SYNC call inside an async function**, blocking the event loop for the entire turn duration.
3. `_process_streaming_event` (line 400) runs `watchdog.check_orphans()` on every event. When an orphan is found:
   - `watchdog.register_orphan_event(...)` is called (orphan_count++).
   - Comment at line 475-478: "We can't send turn/interrupt from the callback directly — the main execution loop handles it after the turn completes or via a separate watchdog mechanism."
4. There is **no turn/interrupt call anywhere in codex_appserver.py** (verified via grep). The "separate watchdog mechanism" referenced in the comment does not exist.
5. Consequence: if a codex tool hangs, `wait_for_turn_completed` blocks forever. The orphan is recorded but never cancelled. The caller never regains control. No WaveWatchdogTimeoutError is raised from this transport because that lives in the wave_executor path, not the codex path.
6. The `turn_status == "interrupted"` branch at line 330 is effectively dead code: no code path in this file sends `turn/interrupt`, so completed_turn will never have that status unless the codex server itself decides to interrupt.

**Proposed fix:** Either (a) run `client.wait_for_turn_completed` in `asyncio.to_thread` with a concurrent watchdog that calls `client.turn_interrupt(turn_id)` when the watchdog fires, OR (b) supply a custom `on_event` callback that captures a reference to the app-server client and spawns a turn-interrupt task (via `asyncio.get_running_loop().call_soon_threadsafe(...)`).

**Fix status:** NOT FIXED by this reviewer. This is a Phase E legacy issue; the Phase F sweeper did not touch this file. Flagging so Team Lead can decide whether to hand to `runtime-behavior-fixer` or defer to a follow-up.

---

## F-RT-002: stamp_* helpers do non-atomic writes (SIGINT leaves partial files)
**Severity:** MEDIUM
**Area:** SIGINT / cleanup
**File:line:** `src/agent_team_v15/confidence_banners.py:168, 173, 216, 251`

**Execution trace:**

1. Each `stamp_markdown_report`, `stamp_build_log`, `stamp_json_report` writes the new content back via `target.write_text(new_content, encoding="utf-8")`.
2. Python's `Path.write_text` is: `open(path, "w")` (truncates), write, close. There is no temp-file-and-rename step.
3. If `_handle_interrupt` at `cli.py:8182` fires during one of these writes (or the OS kills the process), the file on disk is left in a partial state:
   - `AUDIT_REPORT.json` → invalid JSON (next run will `JSONDecodeError` on load).
   - `BUILD_LOG.txt` → truncated (operator loses history of the final log lines).
4. These stampers are flag-gated to always run when `confidence_banners_enabled=True`, but currently not wired into any call site (see F-RT-005), so the observable risk today is zero. Flagging so that once wired, the atomicity is addressed.

**Proposed fix:** replace `target.write_text(new_content, encoding="utf-8")` with the atomic pattern:
```python
tmp = target.with_suffix(target.suffix + ".tmp")
tmp.write_text(new_content, encoding="utf-8")
os.replace(tmp, target)  # atomic on Windows and POSIX when on same FS
```

**Fix status:** NOT FIXED — deferred. No observable impact in the current smoke because the module is not wired in.

---

## F-RT-003: wave_b_sanitizer silent OSError may mask consumer presence
**Severity:** LOW
**Area:** silent failure
**File:line:** `src/agent_team_v15/wave_b_sanitizer.py:197, 201`

**Execution trace:**

1. `_scan_for_consumers` iterates candidate files. Two silent-swallow points:
   - Line 197: `except OSError: pass` — `candidate.resolve()` fails → skip identity check (minor).
   - Line 201: `except OSError: continue` — file read fails → skip that candidate entirely.
2. If a legitimate consumer file has a transient read failure (locked on Windows, permission error), that file is silently skipped. `samples` stays empty.
3. When called with `remove_orphans=True` (opt-in, default False), the sanitizer will delete the "orphan" because no consumer was found.
4. Net: one bad file read → one real-consumer file missed → legitimate orphan candidate deleted → build breaks on next compile.
5. Risk level is LOW because:
   - `remove_orphans=True` is opt-in and default False.
   - Module is not currently wired (F-RT-005).
   - In real workflows, a transient OSError on a TS file is uncommon.

**Proposed fix:** replace `except OSError: continue` with a conservative "assume consumer present on read failure" — either log the failure and keep scanning, or flag `has_consumers=True` when ANY candidate read fails during scan of this orphan.

**Fix status:** NOT FIXED — deferred. Low severity, module currently dead code.

---

## F-RT-004: `dispatch_fix_agent` uses `asyncio.run()` — must NOT be called from async context
**Severity:** LOW (documentation / contract)
**Area:** async
**File:line:** `src/agent_team_v15/runtime_verification.py:788`

**Execution trace:**

1. `dispatch_fix_agent` is a sync function that internally calls `asyncio.run(_run_fix())` at line 788.
2. If called from a running event loop, Python raises `RuntimeError: asyncio.run() cannot be called from a running event loop`.
3. Traced the call chain: `run_runtime_verification` is sync, and the only call site (`cli.py:13109`) is inside `main()` (line 9713), which is also sync. By the time main() invokes run_runtime_verification, the earlier `asyncio.run(_run_single(...))` has already returned. So the production path is safe.
4. Risk is that a future caller could invoke `run_runtime_verification` from within an async orchestrator (e.g., testing-lead via agent_teams_backend). There is no assertion guarding against this.

**Proposed fix:** add a one-line guard at the top of `dispatch_fix_agent`:
```python
try:
    asyncio.get_running_loop()
    raise RuntimeError(
        "dispatch_fix_agent cannot be called from an async context — "
        "use run_in_executor or restructure caller to release the loop first"
    )
except RuntimeError as e:
    if "no running event loop" not in str(e):
        raise
```

**Fix status:** NOT FIXED — contract is already implicit. Flag so reviewers know the constraint.

---

## F-RT-005: All four Phase F new modules are not wired into any call site
**Severity:** MEDIUM (runtime-neutral now; blocks observable Phase F benefit)
**Area:** silent failure / Phase F integration
**File:line:**
- `src/agent_team_v15/infra_detector.py` — `detect_runtime_infra` / `build_probe_url` not imported anywhere outside the module.
- `src/agent_team_v15/confidence_banners.py` — `stamp_all_reports` / `stamp_*` not imported anywhere outside.
- `src/agent_team_v15/audit_scope_scanner.py` — `ScopeGap` / `build_scope_gap_findings` not imported anywhere outside.
- `src/agent_team_v15/wave_b_sanitizer.py` — `sanitize_wave_b_outputs` not imported anywhere outside.

**Execution trace:**

1. `grep -rn "from .wave_b_sanitizer\|from .confidence_banners\|from .infra_detector\|from .audit_scope_scanner" src/agent_team_v15/` returns **zero matches outside those modules themselves**.
2. `grep -rn "sanitize_wave_b_outputs\|stamp_all_reports\|detect_runtime_infra\|build_probe_url\|build_scope_gap_findings" src/agent_team_v15/` returns only the definitions — no call sites in production code.
3. Flag `v18.runtime_infra_detection_enabled=True` and friends are set in `config.py:929` but no code consults them at runtime, so the True value is never acted on.
4. All four modules have passing unit tests (58 methods total), which is why the post-sweeper pytest count went 10,461 → 10,530 (+69 tests). But unit-test-only coverage does not prove runtime behavior.
5. Runtime impact:
   - **Zero CRITICAL runtime risk today**: the code doesn't run, so it can't hang, leak, or race.
   - **Observable Phase F deliverable is zero**: audit reports won't carry confidence banners, Wave B outputs won't be sanitized, infra detection won't improve probes, audit scope gaps won't be emitted.
   - **Memory: feedback_verification_before_completion.md**: "unit tests aren't enough; end-to-end smoke must actually fire the fix." This is exactly the scenario that memory flags.

**Proposed fix:** the sweeper implementer (Task #1) needs a follow-up patch to wire:
- `stamp_all_reports(...)` at end of `_run_audit_loop` and post-orchestration before writing the final report paths.
- `sanitize_wave_b_outputs(...)` into Wave B completion in `wave_executor.py` (where NEW-1's `_maybe_cleanup_duplicate_prisma` already lives — analogous hook point).
- `detect_runtime_infra(...)` + `build_probe_url(...)` into `endpoint_prober` probe construction.
- `audit_scope_scanner.build_scope_gap_findings(...)` into the audit pipeline before writing AUDIT_REPORT.json.

**Fix status:** NOT FIXED — this is an INTEGRATION finding, not strictly a runtime finding. Out of scope for runtime-behavior-fixer; belongs with integration-boundary reviewer or a follow-up sweeper task. Flagging here because it's the root cause of why my runtime traces for all four modules turned up "no observable risk" — the modules simply aren't running.

---

## Cleared areas (no findings)

- **Area 8 Budget-removal runtime (HIGH PRIORITY, cleared):**
  - `cli.py:_run_audit_loop` — `for cycle in range(start_cycle, max_cycles + 1)` is the structural bound. `max_cycles = config.audit_team.max_reaudit_cycles`. Plateau detection at 6618-6628 and `should_terminate_reaudit` at 6631 are non-cost stop conditions.
  - `coordinated_builder.py:587` — `while True:` exits only via `decision.action == "STOP"` at 1022. `evaluate_stop_conditions` at `config_agent.py:456-504` returns STOP on convergence / zero-actionable / `state.current_run >= state.max_iterations` (default 4). `state.add_run` increments `current_run` on every audit + every fix round, so the max_iterations condition fires within ~4 iterations even if convergence never triggers.
  - `config_agent.py:488-503` — the former Condition 3 (budget STOP) is now just a comment. Condition 4 (max_iterations) is the remaining structural rail. Loop is bounded.
  - `runtime_verification.py:1037` — `for fix_round in range(max_total_fix_rounds + 1)` is the primary bound. `tracker.can_fix(svc)` gives up a service after `max_rounds_per_service=3` attempts, and `tracker.total_rounds_exceeded` at line 1054 fires after 5 total rounds. All structural, non-cost.
- **Area 1 Async/await correctness (Phase F modules):** `infra_detector`, `confidence_banners`, `audit_scope_scanner`, `wave_b_sanitizer` contain zero `async def` / `await` / `asyncio.*` calls. Grep confirmed. No new async mistakes introduced.
- **Area 2 Resource cleanup (Phase E happy path):** `async with ClaudeSDKClient(options=options) as client:` at all 30+ sites in `cli.py` exits the context manager properly. `_cancel_sdk_client` at cli.py:977 handles graceful disconnect. `_consume_response_stream` at cli.py:998 handles `asyncio.wait_for` timeout by cancelling client and raising `WaveWatchdogTimeoutError`. No resource leak introduced by Phase F.
- **Area 3 Race conditions:** no parallel writes to the same file discovered. Phase F modules are called post-phase (one-shot), not concurrently. Wave B sanitizer runs after Wave B's builder exits (per docstring); no race with Wave C.
- **Area 4 Silent failures in Phase F modules:** surveyed. Intentional silent-skip on OSError is acceptable for the read-only detectors (`infra_detector`, `audit_scope_scanner`). One marginal concern noted as F-RT-003 for the sanitizer's delete path.
- **Area 5 Phase E forked sessions:** `_execute_enterprise_role_session` at `cli.py:1217-1252` uses `async with ClaudeSDKClient` properly; session cleanup runs on exit of the context manager even on exception. The parent session is unaffected because each role opens its own client.
- **Area 7 SIGINT handling:** `_handle_interrupt` at `cli.py:8182` is bounded (first warn, second save+exit). Phase F stampers have a theoretical partial-write risk documented as F-RT-002 but are not wired into the current happy path.

## Regression verification

- Budget-removal tests (targeted): `116 passed in 0.41s` on `test_config_agent.py`, `test_coordinated_builder.py`, `test_runtime_verification.py`, `test_phase2_audit_fixes.py`.
- Post-sweeper full run (from `session-F-validation/post-sweeper-pytest.log`): **10,530 passed, 35 skipped, 0 failed** — unchanged.

## Handoff

- No CRITICAL findings — mid-flight halt is NOT required.
- F-RT-001 (HIGH, pre-Phase-F codex_appserver orphan-interrupt wiring) should be triaged by Team Lead for Phase F smoke risk.
- F-RT-005 (MEDIUM, Phase F modules not wired) is effectively a Phase F delivery gap — flag to integration-boundary reviewer and Team Lead.
- All other findings are MEDIUM/LOW and can be deferred.

_End of runtime-behavior report._
