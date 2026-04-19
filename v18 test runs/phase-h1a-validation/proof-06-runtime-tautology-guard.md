# Proof 06 — Runtime tautology guard (RUNTIME-TAUTOLOGY-001)

## Feature

Phase H1a Item 6: `cli._runtime_tautology_finding` walks the
docker-compose critical-path graph anchored at `services.api`, identifies
the set of services transitively required for api's health, and flags any
that are missing from the compose file or not healthy in the
runtime-verifier report. Services outside the critical-path closure
(observability sidecars, `postgres_test`, etc.) are informational and do
NOT contribute to the finding.

This closes the smoke #11 hole where runtime verification reported
"1/1 services healthy" because the compose file was postgres-only —
api was never in the denominator.

## Production call chain

1. `cli.py:13882-13916` computes the finding inside the runtime-verification
   emitter, gated on `v18.runtime_tautology_guard_enabled`.
2. `_runtime_tautology_finding(project_root, rv_report, config)` at
   `cli.py:172-271`:
   - Locates compose via `runtime_verification.find_compose_file`.
   - Builds `status_map` from `rv_report.services_status`.
   - Calls `_compose_critical_path(compose_data, api_service_name="api")` to
     compute the transitive `depends_on` closure rooted at api.
   - Walks the closure; returns `RUNTIME-TAUTOLOGY-001: <N>/<M>
     critical-path services healthy (missing or unhealthy: ...)` when any
     are absent or unhealthy.
3. `cli.py:13929, 13933` surface the finding via `print_warning` into
   BUILD_LOG.

The proof script invokes `_runtime_tautology_finding` directly — the same
callable `cli.py:13899` uses.

## Fixture

`fixtures/proof-06/docker-compose.yml`:
- `services.api` with `depends_on.postgres.condition: service_healthy` and
  `ports: ["3080:3080"]`.
- `services.postgres` with a `pg_isready` healthcheck.
- `services.postgres_test` with its own healthcheck (NOT in api's
  `depends_on` closure — it's a sibling for test-runner isolation).

Simulated `rv_report` (matching what `runtime_verification` would emit):
- `postgres` healthy.
- `postgres_test` healthy.
- `api` **absent** from the running services set.

## Command

```bash
python "v18 test runs/phase-h1a-validation/scripts/proof_06_runtime_tautology.py" \
  > "v18 test runs/phase-h1a-validation/proof_06_output.txt"
```

## Salient output

```
Invoking cli._runtime_tautology_finding (production entry point)
  compose: ...fixtures/proof-06/docker-compose.yml
  critical path expected: {api, postgres}
  running services (rv_report): postgres=healthy, postgres_test=healthy, api=absent

finding string: 'RUNTIME-TAUTOLOGY-001: 1/2 critical-path services healthy (missing or unhealthy: api (unhealthy))'
```

### Summary

```
  RUNTIME-TAUTOLOGY-001 emitted:                 True
  finding names api:                             True
  finding does NOT mention postgres_test:        True
```

## Interpretation

The critical-path walk computed `{api, postgres}` from the compose graph
(anchored at api → depends_on.postgres). `postgres` is healthy, api is
not in the running set (`status_map.get("api", False) → False`), yielding
`1/2 healthy`. `postgres_test` — which IS healthy but is outside the
closure — is correctly ignored. The denominator reflects the real
requirement (2 services for api to serve) rather than the compose-total
tautology (3 services were defined) or the runtime-only tautology (2 were
running, therefore healthy).

**PASS.**

## Status: PASS
