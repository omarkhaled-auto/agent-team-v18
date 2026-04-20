# Phase H3g Discovery - D4 Runtime Verifier Staleness

## Verdict

Proceed. No HALT.

## Landmarks

- `src/agent_team_v15/runtime_verification.py:946-1215`
- `src/agent_team_v15/runtime_verification.py:363-452`
- `src/agent_team_v15/cli.py:172-271`
- `src/agent_team_v15/cli.py:14369-14435`

## Runtime Verifier Path

- Phase 6 calls `run_runtime_verification()` from `cli.py:14338-14352`.
- The H1a tautology guard reads the returned `RuntimeReport` via `_runtime_tautology_finding()` at `cli.py:172-271`.
- The finding is emitted from `cli.py:14414-14435`.

## Root Cause

- `run_runtime_verification()` tracks fix attempts through `FixTracker`.
- The outer loop can stop at the top of an iteration when `tracker.total_rounds_exceeded` is true (`runtime_verification.py:1080-1084`).
- That break happens before another `docker_start()` / `_check_container_health()` pass.
- The final `RuntimeReport.services_status` can therefore describe the state before the most recent fix took effect.
- `_runtime_tautology_finding()` trusts that stale `RuntimeReport` and reports healthy services as unhealthy.

## Observed Race Window

- `docker_start()` does poll health, but only for the start pass that already happened (`runtime_verification.py:393-407`).
- If the last allowed fix modifies Docker or app startup behavior and the loop exits on the cap before another start/check cycle, the final verdict uses pre-fix status.
- This matches the smoke: services were healthy at the end, but the guard still emitted `RUNTIME-TAUTOLOGY-001`.

## Recommended Fix Shape

Add a flag-gated final refresh window inside `runtime_verification.py`, before the report is consumed:

- `runtime_verifier_refresh_enabled: bool = False`
- `runtime_verifier_refresh_attempts: int = 5`
- `runtime_verifier_refresh_interval_seconds: float = 3.0`

Behavior when flag is on:

1. After the fix loop ends, poll `_check_container_health()` up to `N` times.
2. Update `report.services_status`, `services_healthy`, and `services_total` on each attempt.
3. Return early if all critical services are healthy.
4. If never healthy, keep the last observed status.

Behavior when flag is off stays byte-identical.
