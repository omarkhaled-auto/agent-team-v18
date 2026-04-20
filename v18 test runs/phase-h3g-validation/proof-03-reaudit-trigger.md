# Proof 03 — Re-Audit Trigger

## Objective
Close H3d Bucket D6: when a milestone fails its health gate, the pipeline must
still enter the audit-fix-reaudit loop when the H3g fix flag is enabled.

## Root Cause
- The per-milestone `_run_audit_loop(...)` was correct.
- The failing path was earlier in `cli.py`: the failed health-gate branch marked
  the milestone `FAILED` and `continue`d before the normal per-milestone audit
  block ran.
- The low audit score observed in smoke came from a later one-shot audit path,
  not from the missing per-milestone re-audit loop.

## Implementation Sites
- `src/agent_team_v15/cli.py`
- `src/agent_team_v15/config.py`

## Fix Shape
- Added `v18.reaudit_trigger_fix_enabled` (default `False`).
- Added `_run_failed_milestone_audit_if_enabled(...)`.
- Failed health-gate branch now calls that helper before `continue`.
- Flag off preserves pre-H3g behavior.

## Evidence
- H3g ring:
  - `test_failed_milestone_audit_flag_off_skips_audit_loop`
  - `test_failed_milestone_audit_flag_on_runs_audit_loop`
  - `test_audit_loop_reaudits_low_score_until_healthy`
  - `test_audit_loop_stops_after_first_healthy_cycle`

## Caller Proof
1. Flag off:
   - failed milestone path does not call `_run_audit_loop(...)`
   - behavior stays byte-identical to pre-H3g
2. Flag on:
   - failed milestone path calls `_run_audit_loop(...)`
3. Low-score audit loop:
   - cycle 1 score `52.0`
   - fix round runs
   - cycle 2 score `86.0`
   - loop terminates healthy
4. Healthy cycle 1:
   - loop stops after the first cycle
   - no audit-fix pass is dispatched

## Result
D6 proceeded. The trigger gap was a local orchestration bypass, not an
architectural halt condition.
