# Proof 01 — Runtime Verifier Refresh

## Objective
Close H3d Bucket D4: prevent the final runtime verdict from consuming stale
container health immediately after the last Docker fix pass.

## Implementation Site
- `src/agent_team_v15/runtime_verification.py`

## Fix Shape
- Added flag-gated refresh window:
  - `v18.runtime_verifier_refresh_enabled`
  - `v18.runtime_verifier_refresh_attempts`
  - `v18.runtime_verifier_refresh_interval_seconds`
- When the main runtime loop exits with unhealthy services, the verifier now
  performs a bounded re-poll before the CLI tautology guard reads the report.
- Flag off preserves the legacy single-read behavior.

## Evidence
- H3g ring:
  - `tests/test_h3g_bucket_d_cleanup.py::test_runtime_refresh_flag_off_keeps_single_read`
  - `tests/test_h3g_bucket_d_cleanup.py::test_refresh_container_health_retries_until_healthy`
  - `tests/test_h3g_bucket_d_cleanup.py::test_refresh_container_health_returns_last_unhealthy_status`
- Existing runtime-verification suites:
  - `pytest tests/test_runtime_verification.py tests/test_runtime_verification_block.py tests/test_audit_team.py tests/test_audit_upgrade.py -q --tb=short`
  - Result: `230 passed`

## Caller Proof
1. Flag off:
   - `run_runtime_verification(...)` returns the original unhealthy/stale view.
   - `_refresh_container_health(...)` is not called.
2. Flag on with delayed health:
   - `_refresh_container_health(...)` polls until the third attempt.
   - Returned status is the healthy third snapshot, not the stale first snapshot.
3. Flag on with genuine failure:
   - `_refresh_container_health(...)` returns the last unhealthy snapshot after the bounded retry window.
   - Failure reporting remains intact.

## Result
D4 proceeded. The exact stale-read window from the H3d smoke is now closed when
the H3g refresh flag is enabled.
