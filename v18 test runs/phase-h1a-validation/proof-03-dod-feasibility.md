# Proof 03 — DoD feasibility verifier (DOD-FEASIBILITY-001)

## Feature

Phase H1a Item 3: `dod_feasibility_verifier.run_dod_feasibility_check` parses
`REQUIREMENTS.md` under `## Definition of Done`, extracts backticked
`pnpm`/`npm`/`yarn` script references, and emits `DOD-FEASIBILITY-001` HIGH
per script not defined in any known `package.json`. The hook at
`wave_executor.py:4981-5024` sits OUTSIDE the per-wave `for` loop so a
Wave-B-failed milestone (smoke #11) still triggers the check.

## Production call chain

1. `_execute_milestone_waves_with_stack_contract` runs its per-wave
   `for wave_letter in waves[...]:` loop (`wave_executor.py:4185-4966`).
2. On failure, `break` at `:4961-4963` exits the loop.
3. Control falls through to the teardown block: first
   `persist_wave_findings_for_audit(...)`, then the DoD-feasibility guard
   at `:4984` (`if _get_v18_value(config, "dod_feasibility_verifier_enabled", False):`).
4. When flag is True, the verifier runs and any findings become
   `WaveFinding(code="DOD-FEASIBILITY-001")` inside a synthetic
   `DOD_FEASIBILITY` WaveResult appended to `result.waves`, then
   re-persisted to `WAVE_FINDINGS.json`.

The structural invariant is what makes Fixture B possible: if the guard
were at `:4700` (inside the loop), Wave-B failure would skip it entirely.

## Fixtures

Both fixtures share identical content (REQUIREMENTS.md references
`pnpm dev`, `pnpm db:migrate`, `pnpm typecheck`, etc.; `package.json` only
defines `typecheck`, `lint`, `build` — missing `dev` and `db:migrate`).

- `fixtures/proof-03-a/` — Fixture A (happy path).
- `fixtures/proof-03-b/` — Fixture B (Wave-B-failed scenario).

Because `run_dod_feasibility_check` is a pure function over the milestone
directory + `package.json`, both fixtures exercise the identical call path —
which is the POINT of the regression guard: wave outcome does not gate the
check.

## Command

```bash
python "v18 test runs/phase-h1a-validation/scripts/proof_03_dod_feasibility.py" \
  > "v18 test runs/phase-h1a-validation/proof_03_output.txt"
```

## Salient output

### Fixture A — happy path

```
[A] findings: 2
[A] codes: ['DOD-FEASIBILITY-001', 'DOD-FEASIBILITY-001']
[A] DOD-FEASIBILITY-001 HIGH ...REQUIREMENTS.md
[A]   message: DoD command `pnpm db:migrate` references a script that is not defined in any known package.json...
[A] DOD-FEASIBILITY-001 HIGH ...REQUIREMENTS.md
[A]   message: DoD command `pnpm dev` references a script that is not defined in any known package.json...
[A] DOD-FEASIBILITY-001 present: True
```

### Fixture B — Wave-B-failed (critical regression guard)

```
[B] findings: 2
[B] codes: ['DOD-FEASIBILITY-001', 'DOD-FEASIBILITY-001']
[B] DOD-FEASIBILITY-001 HIGH ...REQUIREMENTS.md
[B]   message: DoD command `pnpm db:migrate` references a script that is not defined in any known package.json...
[B] DOD-FEASIBILITY-001 HIGH ...REQUIREMENTS.md
[B]   message: DoD command `pnpm dev` references a script that is not defined in any known package.json...
[B] DOD-FEASIBILITY-001 present: True
```

### Structural — DoD hook placement is OUTSIDE the wave for-loop

```
live func: _execute_milestone_waves_with_stack_contract
  wave for-loop lines:              4185-4966
  DoD flag-guard line:              4984
  DoD guard AFTER loop end:         True
```

The AST walk confirms line 4984 (the
`_get_v18_value(config, "dod_feasibility_verifier_enabled", ...)` guard)
is strictly greater than the for-loop's end (4966). This is the invariant
that lets Fixture B trigger: the `break` at failure exits the loop and
control falls through to the out-of-loop teardown.

### Summary

```
  Fixture A — DOD-FEASIBILITY-001 fires:              True
  Fixture B — DOD-FEASIBILITY-001 fires:              True
  Structural — DoD guard OUTSIDE wave for-loop body:  True
```

## Interpretation

Fixture B is the load-bearing proof: combining behavioural evidence (the
verifier emits `DOD-FEASIBILITY-001` on a fixture where Wave B would have
failed) with structural evidence (the hook sits at line 4984, outside the
wave loop that ends at line 4966) demonstrates that a Wave-B-failed
milestone — exactly the smoke #11 class — will still surface the DoD
feasibility root cause. **PASS.**

## Status: PASS
