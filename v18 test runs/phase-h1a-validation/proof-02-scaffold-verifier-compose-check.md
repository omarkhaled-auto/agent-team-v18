# Proof 02 — Scaffold verifier SCAFFOLD-COMPOSE-001

## Feature

Phase H1a Item 2: `scaffold_verifier._check_compose_topology` catches a
`docker-compose.yml` that lacks `services.api` (the smoke #11 silent-pass
hole). Emitted as `SCAFFOLD-COMPOSE-001` in `report.summary_lines` and
persisted to `.agent-team/scaffold_verifier_report.json` for the cascade
consolidator.

## Production call chain

1. `wave_executor._execute_milestone_waves_with_stack_contract:4251` calls
   `_maybe_run_scaffold_verifier(cwd, milestone_scope, scope_aware, milestone_id)`.
2. `_maybe_run_scaffold_verifier` at `wave_executor.py:1030-1109` loads the real
   ownership contract, invokes `run_scaffold_verifier`, and writes the JSON
   report.
3. `run_scaffold_verifier:209-212` calls `_check_compose_topology`; diagnostic
   becomes a `malformed` entry + a `SCAFFOLD-COMPOSE-001 <diag>` summary line.

This proof invokes `_maybe_run_scaffold_verifier` directly (the same
callable wave_executor uses at runtime) against an on-disk fixture.

## Fixture

`fixtures/proof-02/` — minimal workspace with:
- `docker-compose.yml` containing only `services.postgres` (no `services.api`).
- `.agent-team/` placeholder directory.

The ownership contract is NOT fixture-supplied; the verifier loads
`docs/SCAFFOLD_OWNERSHIP.md` from the real repo — this is load-bearing (it is
exactly what production does).

## Command

```bash
python "v18 test runs/phase-h1a-validation/scripts/proof_02_scaffold_verifier.py" \
  > "v18 test runs/phase-h1a-validation/proof_02_output.txt"
```

## Salient output

```
return value: 'Scaffold-verifier FAIL: verdict=FAIL missing=40 malformed=1 deprecated_emitted=0\n...\nSCAFFOLD-COMPOSE-001 docker-compose.yml missing services.api'
report exists: True
verdict: FAIL
...
  SCAFFOLD-COMPOSE-001 docker-compose.yml missing services.api
SCAFFOLD-COMPOSE-001 occurrences: 1
malformed entries:
  ['docker-compose.yml', 'docker-compose.yml missing services.api']
```

### Persisted JSON report (`v18 test runs/phase-h1a-validation/fixtures/proof-02/.agent-team/scaffold_verifier_report.json`)

- `"verdict": "FAIL"`
- `"malformed": [["docker-compose.yml", "docker-compose.yml missing services.api"]]`
- `"summary_lines"` last line: `"SCAFFOLD-COMPOSE-001 docker-compose.yml missing services.api"`

(The 40 `MISSING ...` rows are expected noise — this minimal fixture omits
every scaffold-owned file. The load-bearing signal is the single
`SCAFFOLD-COMPOSE-001` entry; the malformed-count is exactly 1.)

## Interpretation

The topology check fires through the real production dispatch path,
produces the correct `SCAFFOLD-COMPOSE-001` pattern ID, lands in
`malformed`, and is persisted to the report JSON the cascade-consolidator
reads. **PASS.**

## Status: PASS
