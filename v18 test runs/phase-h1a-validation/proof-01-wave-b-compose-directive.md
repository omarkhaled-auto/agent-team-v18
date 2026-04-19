# Proof 01 — Wave B compose-wiring directive

## Feature

Phase H1a Item 1: the `[INFRASTRUCTURE WIRING]` directive is inserted into the
body of `build_wave_b_prompt` (Claude path) and mirrored into
`CODEX_WAVE_B_PREAMBLE` + a verification bullet in `CODEX_WAVE_B_SUFFIX`
(Codex path). Because `provider_router._claude_fallback` re-dispatches the raw
`build_wave_b_prompt` return, the body placement is load-bearing for fallback
survival.

## Production call chain

1. `provider_router.dispatch_wave_b_codex` constructs `prompt = build_wave_b_prompt(...)` (Claude body).
2. Codex path wraps: `codex_prompt = wrap_prompt_for_codex("B", prompt)` — prepends `CODEX_WAVE_B_PREAMBLE`, appends `CODEX_WAVE_B_SUFFIX`.
3. Claude-fallback path forwards `prompt` unwrapped, so the directive must survive in the body.

## Fixture

None — the prompt builder is a pure function. Invoked with a minimal
`full_stack` milestone + empty IR through `AgentTeamConfig()` default. Fixture
surface is `scripts/proof_01_render.py` (a thin wrapper around the two
production entry points).

## Command

```bash
python "v18 test runs/phase-h1a-validation/scripts/proof_01_render.py" \
  > "v18 test runs/phase-h1a-validation/proof_01_output.txt"
```

## Salient output (from `proof_01_output.txt`)

### Claude body — `[INFRASTRUCTURE WIRING]` block rendered at lines 135–145

```
  133 | - Do not create a second `main.ts`, `bootstrap()`, `AppModule`, or parallel feature tree.
  134 |
  135 | [INFRASTRUCTURE WIRING]
  136 | - Read the existing `docker-compose.yml` at the repository root BEFORE writing any compose content...
  137 | - If `services.api` already exists in `docker-compose.yml`, PRESERVE the scaffolder's postgres service...
  138 | - If `services.api` does NOT exist, ADD it with these canonical fields and nothing invented:
  139 |     * `build: { context: ./apps/api, dockerfile: Dockerfile }`
  140 |     * `ports:` a single entry of the form `"<PORT>:<PORT>"` where `<PORT>` is the integer the scaffolder wrote to `services.api.environment.PORT`...
  141 |     * `environment` block that includes `DATABASE_URL` composed from the scaffolder's `.env.example` / env template...
  142 |     * `depends_on: { postgres: { condition: service_healthy } }`
  143 |     * A `healthcheck` block whose test hits the Definition-of-Done health endpoint for this milestone...
  144 | - The `api` service entry in `docker-compose.yml` and its `apps/api/Dockerfile` MUST both exist or neither does...
  145 | - If the scaffolder already wrote an `api` service, your job is to EXTEND or ALIGN it, not to overwrite.
  146 |
  147 | [BARREL EXPORTS]
```

Placement is exactly between `[MODULE REGISTRATION]` (line 133) and
`[BARREL EXPORTS]` (line 147), matching the architecture report §1A.

### Codex PREAMBLE — `## Infrastructure Wiring (Compose + env parity)` section

```
## Infrastructure Wiring (Compose + env parity)

The backend service you are building MUST be wired into `docker-compose.yml`
at the repository root. The scaffolder owns that file; respect its canonical
postgres service, credentials, network, and volumes.

- Read the existing `docker-compose.yml` BEFORE writing any compose content.
- If `services.api` already exists, PRESERVE the scaffolder's postgres service...
- If `services.api` does NOT exist, ADD it using these canonical fields and nothing invented:
    * `build: { context: ./apps/api, dockerfile: Dockerfile }`
    * `ports:` a single entry of the form `"<PORT>:<PORT>"` where `<PORT>`
      is the integer the scaffolder wrote to `services.api.environment.PORT`...
    * `environment` block including `DATABASE_URL` composed from the scaffolder's `.env.example`...
    * `depends_on: { postgres: { condition: service_healthy } }`
    * A `healthcheck` block whose test hits the Definition-of-Done health endpoint...
- Rule: the `api` service entry in `docker-compose.yml` and its
  `apps/api/Dockerfile` MUST both exist or neither does...
- Rule: if the scaffolder already wrote an `api` service, your job is to EXTEND or ALIGN it, not to overwrite.
```

### Codex SUFFIX — verification-checklist bullet

```
- [ ] `docker-compose.yml` has an `api` service wired to `apps/api/Dockerfile`; its port, `DATABASE_URL`, `depends_on.postgres.condition: service_healthy`, and healthcheck match the scaffolder-resolved values and the milestone DoD health endpoint. The scaffolder's `postgres` service is untouched.
```

### Summary

```
  Claude body contains [INFRASTRUCTURE WIRING]: True
  Claude body contains signature phrase:        True
  Codex PREAMBLE contains heading:              True
  Codex SUFFIX mentions docker-compose.yml:     True
```

## Interpretation

Both the Claude-path body and the Codex-path wrappers carry the
compose-wiring invariant verbatim. The directive survives the Claude fallback
(body placement), is salient on the Codex agentic loop (PREAMBLE), and
surfaces again as a final-self-audit bullet (SUFFIX). **PASS.**

## Status: PASS
