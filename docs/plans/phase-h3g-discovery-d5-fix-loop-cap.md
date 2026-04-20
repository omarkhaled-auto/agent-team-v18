# Phase H3g Discovery - D5 Fix Loop Cap

## Verdict

Proceed. No HALT.

## Landmarks

- `src/agent_team_v15/runtime_verification.py:701-780`
- `src/agent_team_v15/runtime_verification.py:946-1215`
- `src/agent_team_v15/config.py:441`
- `tests/test_runtime_verification.py:382-388`
- `tests/test_runtime_verification.py:553-584`

## Cap Definition

- Config declares:
  - `runtime_verification.max_fix_rounds_per_service`
  - `runtime_verification.max_total_fix_rounds`
  - `runtime_verification.max_fix_budget_usd`
- The fix tracker stores per-service attempts and `_total_rounds` in `runtime_verification.py:701-780`.

## Root Cause

The loop mixes two different counters:

- `fix_round` in `run_runtime_verification()` is the outer loop iteration (`runtime_verification.py:1064`).
- `FixTracker._total_rounds` increments per individual fix attempt (`runtime_verification.py:761-768`).

The break at `runtime_verification.py:1080-1084` checks the per-attempt counter before the next rebuild/restart verification pass. That produces two problems:

1. The loop can stop immediately after consuming the cap on a fix attempt, without verifying whether the last fix worked.
2. The user-visible reporting mixes "rounds" and "attempts", which is why the smoke could describe a cap of 5 while also surfacing 9 applied fixes.

## Recommended Fix Shape

Keep the configured values but align the contract:

1. Treat `max_total_fix_rounds` as a hard cap on total fix attempts.
2. Do not dispatch a new fix when the cap is already exhausted.
3. After the final allowed fix, still permit one bounded verification refresh pass so the report reflects the real end state.
4. Log explicit cap telemetry, e.g. `FIX-LOOP-CAP-REACHED`.

## Budget Note

- Budget is already advisory only.
- Discovery found no reason to change that in H3g.
- The real bug is cap semantics and stale post-cap verification, not budget handling.
