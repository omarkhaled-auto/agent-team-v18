# Phase H3g Architecture Report

## Scope

H3g closes four Bucket D cleanup items from the H3d smoke:

- D3 orphaned live-test `codex.exe`
- D4 stale runtime verifier verdict
- D5 fix-loop cap enforcement mismatch
- D6 re-audit not firing on failed-milestone path

## Discovery Summary

### D3

- Live tests only rely on `client.close()` teardown.
- On Windows shell launches, descendant `codex.exe` can survive even if the parent process exits cleanly.
- H3g can stay test-only by adding explicit live-test cleanup.

### D4

- The tautology guard reads `RuntimeReport.services_status`.
- The runtime fix loop can stop on the cap before a final health refresh.
- A stale `RuntimeReport` then produces a false `RUNTIME-TAUTOLOGY-001`.

### D5

- The runtime fix loop mixes outer-loop rounds with per-fix attempts.
- Cap enforcement fires on the per-attempt counter but before a final verification pass.
- Reporting also conflates attempts and rounds.

### D6

- The per-milestone audit loop is skipped entirely when the milestone fails the health gate.
- The later low-score audit is a separate one-shot standard/interface audit path.
- The fix belongs in failed-milestone orchestration, not in `should_terminate_reaudit()`.

## Approved Fix Shapes

### D3

- Test-only cleanup in `tests/test_codex_appserver_live.py`
- Unconditional thread archive on teardown
- Windows-only process-tree cleanup fallback for tracked live app-server PIDs

### D4

- Add `runtime_verifier_refresh_enabled`
- Add `runtime_verifier_refresh_attempts`
- Add `runtime_verifier_refresh_interval_seconds`
- Implement final refresh-before-verdict in `runtime_verification.py`
- Flag-off behavior unchanged

### D5

- Enforce the total cap consistently in `runtime_verification.py`
- Keep budget advisory
- Add explicit cap telemetry
- Ensure one final verification pass is still possible after the last allowed fix

### D6

- Add `reaudit_trigger_fix_enabled`
- In the failed-milestone health-gate branch, optionally run `_run_audit_loop()` before `continue`
- Preserve existing behavior when the flag is off

## HALT Review

- D3: no HALT
- D4: no HALT
- D5: no HALT
- D6: no HALT

D6 is a bounded control-flow bug in the failed-milestone path, not an architectural stop condition.
