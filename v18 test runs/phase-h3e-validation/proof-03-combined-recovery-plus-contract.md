# Proof 03 — Combined Recovery Plus Contract

## Harness

- Runtime entry: `agent_team_v15.wave_executor.execute_milestone_waves`
- Reused integration helper: `tests.test_h3e_contract_guard._run_contract_redispatch_flow`
- Flags enabled in the harness:
  - `recovery_wave_redispatch_enabled=True`
  - `recovery_wave_redispatch_max_attempts=2`
  - `wave_a_contract_verifier_enabled=True`

The harness simulates:

1. Contract says API port `3001`
2. First Wave A write uses `4000`
3. Deterministic verifier emits `WAVE-A-CONTRACT-DRIFT-001`
4. Redispatch rewinds to Wave A
5. Second Wave A write uses `3001`
6. Scaffold and downstream waves proceed

Observed console emission:

```text
[REDISPATCH] milestone-orders: A -> A (attempt 1/2; codes: WAVE-A-CONTRACT-DRIFT-001)
```

## Observed payload

```json
{
  "result_success": true,
  "waves": ["A", "B", "C", "E"],
  "a_wave_runs": 2,
  "redispatch_attempts": {"milestone-orders:A": 1},
  "redispatch_history": [
    {
      "event": "scheduled",
      "from_wave": "A",
      "target_wave": "A",
      "trigger_codes": ["WAVE-A-CONTRACT-DRIFT-001"],
      "attempt": 1,
      "max_attempts": 2
    }
  ],
  "wave_a_prompt_contexts": [
    "",
    "- [WAVE-A-CONTRACT-DRIFT-001] apps/api/src/main.ts sets process.env.PORT fallback=4000, but the stack contract requires API port 3001.\n- [WAVE-A-CONTRACT-DRIFT-001] apps/api/.env.example sets PORT=4000, but the stack contract requires API port 3001."
  ],
  "completed_waves": ["A", "B", "C", "E"]
}
```

## Conclusion

- Bug A and Bug B now compose into a self-healing loop.
- The first failing A pass is rejected before scaffold.
- The second A pass receives structured rejection context and completes cleanly.
- The milestone then proceeds beyond the prior H3d termination point.
