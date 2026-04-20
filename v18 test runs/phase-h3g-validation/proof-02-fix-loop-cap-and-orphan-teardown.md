# Proof 02 — Fix Loop Cap And Orphan Teardown

## Objective
Close H3d Bucket D3 and D5:
- D3: live Codex tests must not accumulate orphan `codex.exe` processes.
- D5: Phase 6 fix loop must stop dispatching new fixes at the configured cap.

## D3 Implementation Site
- `tests/test_codex_appserver_live.py`

## D3 Fix Shape
- Track app-server subprocesses spawned during live tests.
- On teardown:
  - terminate/wait/kill tracked subprocesses
  - on Windows, snapshot Codex-related PIDs before the test and taskkill only
    the new `node.exe` / `codex.exe` processes introduced during the run

## D3 Evidence
- H3g ring:
  - `test_codex_live_cleanup_terminates_running_process`
  - `test_codex_live_cleanup_falls_back_to_kill_after_timeout`
- Live marker:
  - `pytest tests/ -v -m codex_live --tb=short`
  - Result: `2 passed, 1 skipped`

## D3 Caller Proof
- Pre-rerun Windows Codex-related PID set:
  - `codex.exe` PID `36704`, parent PID `23492`
  - creation date: `20-Apr-26 8:44:36 PM`
- Post-rerun Windows Codex-related PID set:
  - unchanged: only `codex.exe` PID `36704`
- No new Codex-related PIDs remained after the live rerun, so the test run did
  not accumulate an additional orphan.

## D5 Implementation Site
- `src/agent_team_v15/runtime_verification.py`

## D5 Fix Shape
- Treat the total fix cap as a hard stop for new fix dispatches.
- When the last allowed fix is spent, schedule exactly one final
  verification-only pass before stopping.
- Emit `FIX-LOOP-CAP-REACHED` telemetry when the cap is reached.

## D5 Evidence
- H3g ring:
  - `test_fix_loop_runs_final_verification_pass_when_cap_reached`
  - `test_fix_loop_cap_telemetry_emits_when_final_verification_still_unhealthy`

## D5 Caller Proof
1. With `max_total_fix_rounds=1`, the runtime loop dispatches one fix and then
   performs one final verification pass.
2. The final verification pass updates the report state without dispatching a
   second fix.
3. When the final verification pass is still unhealthy, `FIX-LOOP-CAP-REACHED`
   is emitted and the loop stops.

## Result
D3 proceeded and the live test path no longer added a new orphan during the
validation rerun. D5 proceeded and the cap is now enforced in the production
runtime verifier path.
