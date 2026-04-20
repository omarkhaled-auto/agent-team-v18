# Proof 03 - Combined H3e And H3f Integration

## Scope

Show that H3e remains first in the Wave A failure chain and that H3f cleanly
coexists with the existing redispatch planner.

## Structural Evidence

Ordering in `wave_executor.py`:

- H3e contract verifier hook: `src/agent_team_v15/wave_executor.py:5939`
- H3f ownership enforcement hook: `src/agent_team_v15/wave_executor.py:5984`

Redispatch whitelist:

- `src/agent_team_v15/wave_executor.py:416` maps
  `OWNERSHIP-WAVE-A-FORBIDDEN-001 -> "A"`

## Pytest Evidence

Relevant tests:

- `tests/test_h3f_ownership_enforcement.py::test_h3e_contract_drift_and_h3f_ownership_gate_coexist_on_first_pass`
- `tests/test_h3e_contract_guard.py::test_wave_a_contract_drift_redispatches_back_to_wave_a`

Observed H3f/H3e combined behavior:

- first Wave A attempt writes a scaffold-owned contract-drift file
- H3e emits `WAVE-A-CONTRACT-DRIFT-001`
- H3f emits `OWNERSHIP-WAVE-A-FORBIDDEN-001`
- redispatch history records both trigger codes on the same scheduled rerun
- second Wave A attempt runs clean
- pipeline proceeds successfully

Observed preserved H3e ring behavior:

```text
29 passed in 0.98s
```

Observed H3f ring behavior:

```text
37 passed in 0.51s
```

Output files:

- `v18 test runs/phase-h3f-validation/pytest-output-h3f-ring.txt`
- `v18 test runs/phase-h3f-validation/pytest-output-prior-rings.txt`

## Conclusion

H3f is additive to H3e:

- H3e still evaluates first
- H3f adds ownership failure + rollback cleanup
- existing redispatch infrastructure handles the rerun without new state fields
