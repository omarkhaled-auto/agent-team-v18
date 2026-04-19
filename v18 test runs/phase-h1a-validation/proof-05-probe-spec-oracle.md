# Proof 05 — Probe spec-oracle (PROBE-SPEC-DRIFT-001)

## Feature

Phase H1a Item 5: `endpoint_prober._detect_app_url` runs a top-of-function
guard that parses `## Definition of Done` in the milestone's
`REQUIREMENTS.md`, resolves the code-side port via the legacy precedence
chain, and raises `ProbeSpecDriftError` (pattern ID `PROBE-SPEC-DRIFT-001`)
immediately when the two disagree. Fail-fast replaces the legacy 120-second
`_poll_health` timeout that previously swallowed the smoke #11 drift.

This proof is also the **behavioural validation of the Wave 5 bridge fix**:
without `milestone_id` threading from `_run_wave_b_probing` →
`start_docker_for_probing` → `_detect_app_url`, the guard silently no-ops.

## Production call chain

```
_run_wave_b_probing(milestone_id=result.milestone_id)            # wave_executor.py:4865-4872
  → start_docker_for_probing(cwd, config, milestone_id=...)      # endpoint_prober.py:695
    → _detect_app_url(project_root, config, milestone_id=...)    # endpoint_prober.py:1143
      → _milestone_requirements_path(...)                        # :1110
      → parse_dod_port(...)                                      # requirements_parser
      → _resolve_code_side_port(...)                             # :1122
      → raise ProbeSpecDriftError(dod_port, code_port, req_path) # :1161
```

The proof script calls `start_docker_for_probing` directly (the function
that hosts `_detect_app_url`) with `milestone_id="milestone-1"` — this
matches exactly what `_run_wave_b_probing` does after the bridge fix.

## Fixture

`fixtures/proof-05/`:
- `apps/api/src/main.ts` — `app.listen(process.env.PORT ?? 4000)` (code-side port 4000).
- `.env` — `PORT=4000`.
- `.agent-team/milestones/milestone-1/REQUIREMENTS.md` — `## Definition of Done` containing `GET http://localhost:3080/api/health` (DoD port 3080).

## Command

```bash
python "v18 test runs/phase-h1a-validation/scripts/proof_05_probe_oracle.py" \
  > "v18 test runs/phase-h1a-validation/proof_05_output.txt"
```

## Salient output

```
Invoking production call chain with probe_spec_oracle_enabled=True
  fixture: ...fixtures/proof-05
  DoD port from REQUIREMENTS.md: 3080
  Code-side port from main.ts / .env: 4000

ProbeSpecDriftError raised: True
  dod_port:           3080
  code_port:          4000
  requirements_path:  ...REQUIREMENTS.md
  exception message:  PROBE-SPEC-DRIFT-001: DoD port 3080 (from ...REQUIREMENTS.md) does not match code-side port 4000

wall-clock elapsed: 0.000s
  (NOT the 120s legacy poll timeout — fast-fail works)

_run_wave_b_probing.parameters: ['milestone', 'ir', 'config', 'cwd', 'wave_artifacts', 'execute_sdk_call', 'milestone_id']
  milestone_id in signature: True
```

### Summary

```
  PROBE-SPEC-DRIFT-001 raised: True
  dod/code mismatch:           3080 vs 4000
  wall-clock fast-fail (<2s):  True (0.000s)
  milestone_id threaded:       True
```

## Interpretation

The guard fires immediately (sub-millisecond) through the exact call
chain `_run_wave_b_probing` uses in production. The wall-clock budget is
not the 120-second `_poll_health` deadline; the oracle rejects the
mismatch synchronously inside `_detect_app_url` before any I/O happens.
The `milestone_id` kwarg is present on `_run_wave_b_probing`'s signature
(the Wave 5 bridge fix), confirming the guard will actually reach disk
through the live wave-executor call site at `wave_executor.py:4865`.

**PASS.**

## Status: PASS
