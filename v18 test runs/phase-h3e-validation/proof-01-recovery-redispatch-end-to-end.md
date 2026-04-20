# Proof 01 — Recovery Redispatch End to End

## Harness

- Runtime entry: `agent_team_v15.wave_executor.execute_milestone_waves`
- Reused test helper: `tests.test_h3e_wave_redispatch._run_backend_only`
- Command shape: temporary workspace + actual state persistence under `.agent-team/STATE.json`

Observed console emission during the successful redispatch case:

```text
[REDISPATCH] milestone-orders: SCAFFOLD -> A (attempt 1/1; codes: SCAFFOLD-PORT-002)
```

Observed console emission when the cap is exhausted:

```text
[REDISPATCH] milestone-orders: cap reached for A after 1/1 attempt(s) (from SCAFFOLD; codes: SCAFFOLD-PORT-002)
RECOVERY-REDISPATCH-002: milestone=milestone-orders from=SCAFFOLD target=A attempts=1/1 codes=['SCAFFOLD-PORT-002']
```

## Observed payload

```json
{
  "redispatch_success": {
    "result_success": true,
    "result_error_wave": "",
    "waves": ["A", "B", "C", "E"],
    "a_wave_runs": 2,
    "scaffold_runs": 2,
    "redispatch_attempts": {"milestone-orders:A": 1},
    "failed_wave": null,
    "completed_waves": ["A", "B", "C", "E"],
    "redispatch_history": [
      {
        "event": "scheduled",
        "from_wave": "SCAFFOLD",
        "target_wave": "A",
        "trigger_codes": ["SCAFFOLD-PORT-002"],
        "attempt": 1,
        "max_attempts": 1
      }
    ]
  },
  "redispatch_cap": {
    "result_success": false,
    "result_error_wave": "SCAFFOLD",
    "waves": ["A", "SCAFFOLD"],
    "a_wave_runs": 2,
    "scaffold_runs": 2,
    "redispatch_attempts": {"milestone-orders:A": 1},
    "failed_wave": "SCAFFOLD",
    "completed_waves": ["A"],
    "redispatch_history": [
      {
        "event": "scheduled",
        "trigger_codes": ["SCAFFOLD-PORT-002"],
        "attempt": 1,
        "max_attempts": 1
      },
      {
        "event": "cap_reached",
        "trigger_codes": ["SCAFFOLD-PORT-002"],
        "attempts_used": 1,
        "max_attempts": 1
      }
    ]
  },
  "redispatch_disabled": {
    "result_success": false,
    "result_error_wave": "SCAFFOLD",
    "waves": ["A", "SCAFFOLD"],
    "a_wave_runs": 1,
    "scaffold_runs": 1,
    "redispatch_attempts": {},
    "failed_wave": "SCAFFOLD",
    "completed_waves": ["A"],
    "redispatch_history": []
  }
}
```

## Conclusion

- Eligible scaffold findings now rewind execution to Wave A instead of leaving the milestone terminally failed.
- The attempt counter persists in `STATE.json` as `wave_redispatch_attempts`.
- The hard cap is enforced deterministically.
- With the feature flag off, failure propagation stays on the legacy path.
