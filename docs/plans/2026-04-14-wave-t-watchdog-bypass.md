# Bug #10 partial regression: SDK watchdog bypassed in Wave T and multiple sub-agent fix loops

**Status:** open, discovered mid-run on 2026-04-14 smoke test
**Severity:** HIGH — single biggest cost driver (wastes whole runs on silent hangs)
**Observed during:** `build-d-rerun`, Wave T stalled >50 min with no progress, no watchdog fire, no hang evidence

## 1. The concrete hang

At 10:34 today the log shows Wave T writing test files ("setting up jest config for the web app"). Nothing since. As of 11:25:

- BUILD_LOG.txt unchanged for ~50 min
- 0 node.exe processes started today (all 64 node procs visible on the box are orphans from the 2026-04-13 run)
- Main Python PID 37540 is idle (working set paged from ~131 MB down to ~16 MB, total CPU time 22s accumulated since launch)
- `.agent-team/telemetry/milestone-1-wave-T.json` not written
- No `wave_watchdog_fired_at`, no `hang_report_path`, no retry

Wave T's Claude SDK call is sitting on a blocked network/stream read with no upper bound.

## 2. Root cause

Wave T has its own bespoke executor `_execute_wave_t` in `wave_executor.py:1249-1460+`. Its initial SDK call at **line 1298-1306**:

```python
cost = await _invoke(
    execute_sdk_call,
    prompt=str(prompt or ""),
    wave="T", milestone=milestone, config=config, cwd=cwd, role="wave",
)
```

uses plain `_invoke(...)` instead of `_invoke_wave_sdk_with_watchdog(...)`. The generic wave path at line 1642 wraps SDK calls with the watchdog (30-min idle timeout + retry-once). **Wave T bypasses it entirely.**

Bug #10's ratification note (`78907b8`) is incomplete: the watchdog landed for the generic path, but the wave-specific path `_execute_wave_t` (and several sub-agent fix loops — see below) were missed.

Wave D5 did not regress because D5 uses the generic path (`_execute_wave_sdk`), which is properly wrapped.

## 3. Additional unprotected SDK invocations (untouched territory)

Audited all `_invoke(execute_sdk_call, ...)` call sites in `wave_executor.py`:

| Line | Role | Context | Watchdog? |
|------|------|---------|-----------|
| 1190 | `probe_fix` | Wave B DB-probe failure retry — calls SDK to fix broken probes | NO |
| **1298** | `wave` | **Wave T initial SDK call (today's hang)** | NO |
| 1360 | `test_fix` | Wave T fix-loop iteration — re-invokes SDK per failing test | NO |
| 1778 | `compile_fix` | Generic compile-fix sub-agent — invoked from every wave's compile loop | NO |
| 1853 | `compile_fix` | Wave B DTO-contract violation fix sub-agent | NO |
| 1962 | `compile_fix` | Wave D frontend-hallucination fix sub-agent | NO |

Six unprotected SDK call sites. Five of them are fix sub-agents that can be called repeatedly from within an otherwise-protected wave, extending the effective hang window well past the 30-minute idle budget the top-level watchdog implies. In the worst case a compile-fix sub-agent can hang indefinitely inside a wave whose outer watchdog has already been satisfied by prior progress.

## 4. Additional risks worth auditing (not exhaustively verified)

- **`cli.py` direct `ClaudeSDKClient.query(...)` calls** (lines 1557, 1608, 1794, 2087, 2130, 2270, 2483, 2520, 3113, and more): none of these appear to have `asyncio.wait_for` wrappers or an equivalent idle timeout. This covers the PRD decomposition phase, tech research phase, milestone prompt loops, and retry paths. Worth auditing individually against the hang pattern — any one of them could silently stall Phase 1/1.5.
- **Audit loop** (`_run_audit_loop` at `cli.py:5505`): the auditor runs additional SDK calls through its own path; those should also be watchdog-wrapped before M1 audit runs in future builds.
- **`_run_node_tests` in `_execute_wave_t`** (line 1324, 1326): has `timeout=120.0`. 2 minutes is fine for a unit suite but short if a future wave adds e2e/playwright runs here. Not the hang source today (the hang is upstream of any subprocess call) but will become one if e2e is ever routed through this path without raising the timeout.

## 5. Proposed fix

Two complementary changes:

### 5.1. Wrap every SDK sub-agent invocation

Introduce a helper (name TBD, e.g. `_invoke_sdk_sub_agent_with_watchdog`) that mirrors `_invoke_wave_sdk_with_watchdog` but is parametrized by role and a shorter idle timeout (e.g. `config.v18.sub_agent_idle_timeout_seconds`, default 600s). Replace the six `_invoke(execute_sdk_call, ...)` call sites enumerated in Section 3. Propagate `WaveWatchdogTimeoutError` the same way line 1657 does — emit a hang report, mark the sub-agent attempt failed, and let the caller decide whether to retry or fail the wave.

### 5.2. Add a hard outer wave budget as a safety net

Even with per-SDK-call watchdogs, a wave that keeps making quick progress messages can run forever. Add a hard `wave_total_timeout_seconds` (default ~45 min per wave for M1-ish milestones) that cancels the whole wave regardless of per-call progress. This is a belt-and-suspenders guard against the "watchdog sees progress but wave never terminates" failure mode.

## 6. Verification after the fix

1. Unit: stub `execute_sdk_call` to `await asyncio.Future()` (never returns) and assert each wrapped site raises `WaveWatchdogTimeoutError` inside the configured timeout. One test per call site.
2. Integration: launch a fresh smoke build with `sub_agent_idle_timeout_seconds=60`; inject a single failing test to force the Wave T fix loop and confirm the sub-agent watchdog fires and retries once.
3. Regression: rerun D5 to confirm the generic-path watchdog still works and wasn't accidentally broken by the refactor.

## 7. Operational note for today's run

Per Section 10 of the smoke-test handoff: do not edit source during the run. Today's run will be killed at the 80-min-silent mark per Section 5. Artifacts through Wave D5 will be preserved. This bug is the cause of the run being killed, and Wave T/E/audit checklist items will remain unverified for this session.

Without this fix, every smoke-test run remains vulnerable to the same class of silent hang on any of the six sites above. This is the single biggest driver of wasted test budget.

## 8. Implementation notes

- `src/agent_team_v15/wave_executor.py` now wraps the six audited SDK sub-agent sites with `_invoke_sdk_sub_agent_with_watchdog(...)` at lines 1268 (`probe_fix`), 1398 (Wave T initial `role="wave"` call), 1488 (`test_fix`), 1933 (generic `compile_fix`), 2020 (Wave B DTO-contract `compile_fix`), and 2135 (Wave D frontend-hallucination `compile_fix`).
- The new helper lives at `wave_executor.py:826` and uses `config.v18.sub_agent_idle_timeout_seconds` (default `600`) without internal retry. Generic wave watchdog behavior remains unchanged at `_invoke_wave_sdk_with_watchdog(...)`.
- The hard outer wave timeout uses `config.v18.wave_total_timeout_seconds` (default `2700`) via `_execute_single_milestone_wave(...)` at `wave_executor.py:2196`, called from `_execute_milestone_waves_with_stack_contract(...)` at `wave_executor.py:3101`. This is a deliberate deviation from the plan wording: on the current branch `execute_milestone_waves(...)` returns early to `_execute_milestone_waves_with_stack_contract(...)`, so the old block after that return is dead code and was not modified.
- Timeout handling decisions follow the plan shape:
  - Wave T initial timeout now fails Wave T, records `WAVE-T-TIMEOUT`, and writes a hang report.
  - Wave B `probe_fix` timeout now fails probing, records `PROBE-FIX-TIMEOUT`, and writes a hang report.
  - Wave T `test_fix` and the three `compile_fix` loops now log timed-out attempts, write hang reports, and fall through to their existing bounded retry / still-failing paths without retrying inside the sub-agent helper.
- `src/agent_team_v15/cli.py` audit results for the requested direct `ClaudeSDKClient.query(...)` sites:
  - Wrapped with `asyncio.wait_for(..., timeout=sub_agent_idle_timeout_seconds)`: current lines 1565, 1619, 1808, 2104, 2150, 2293, 2509, 2549.
  - Already time-bounded and left unchanged: current line 3146 (`ms_prompt`) because `_execute_milestone_sdk()` is already wrapped by `asyncio.wait_for(..., timeout=milestone_timeout)` at line 3254.
