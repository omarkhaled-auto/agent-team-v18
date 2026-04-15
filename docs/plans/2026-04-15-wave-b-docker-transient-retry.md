# Wave B Docker Transient Retry (PR #9)

**Status:** open
**Date:** 2026-04-15
**Reference run:** `v18 test runs/build-h-full-closeout-20260415/` (Wave B `success: false` due to `failed to set up container networking: driver failed` during compose up).

---

## 1. Problem

In `build-h`, Wave B's codex output cleared every code-level gate:

- `turn.completed` cleanly (no orphan-tool wedge),
- 76 files written, compile passed after 3 iterations,
- `stack_contract_violations: []`,
- post-orchestration contract-E2E `16/16 endpoints, FULL CONTRACT COMPLIANCE`.

But `WaveResult.success` was `false` because the surrounding probing scaffold hit a Docker
networking transient at `docker compose up -d`:

```
docker compose up failed: ... Error response from daemon: failed to set up container networking: driver failed p
...
Database truncate failed during DB reset
Warning: Milestone milestone-1 failed: Wave execution failed in B: DB reset/seed failed before Wave B endpoint probing
```

A *later* compose-up in the same run (post-orchestration verification phase) succeeded against
the same compose file. The failure was transient, but it fired at the moment that gates Wave
B's success flag.

This PR makes the Wave B probing scaffold robust against transient Docker daemon failures —
without papering over genuinely broken compose configurations or missing images.

## 2. Scope — exact call sites wrapped

Two boundaries, both inside the Wave B probing path:

1. **`runtime_verification.docker_start` — the `docker compose up -d` call (runtime_verification.py:259-263)**
   This is the literal line that emitted `docker compose up failed: ...` in build-h's
   `BUILD_LOG.txt`. Called twice from `endpoint_prober.start_docker_for_probing` (warm path
   line 717, recovery path line 729).
2. **`endpoint_prober._truncate_tables` — the `docker compose exec ... psql ... TRUNCATE` call (endpoint_prober.py:876-899)**
   Called from `reset_db_and_seed` (line 852). The build-h log shows
   `Database truncate failed during DB reset` immediately after the compose-up daemon error,
   so the truncate path is the second place a daemon-transient can derail Wave B's success
   flag.

Justification for two wraps: a single helper in `runtime_verification` is enough; the truncate
call also routes through `subprocess.run` with `docker compose ...`, so we add the same retry
helper to `_truncate_tables`. Wrapping at `_run_docker` itself (one layer down) would
over-broaden retry semantics to read-only operations like `ps`, `config`, `logs` where retry
is either pointless (`config`) or actively misleading (`ps` returning stale state).

## 3. Retry policy

- Attempts: 3 max.
- Backoff: exponential, **5s → 15s → 45s** (the gap *between* attempts; first attempt has no
  delay).
- Substrings classified **transient** (case-insensitive, matched against the docker stderr):
  - `failed to set up container networking`
  - `driver failed`
  - `error response from daemon`
- Substrings classified **permanent** — never retry:
  - `no such image`
  - `image not found`
  - `invalid compose`
  - `port already allocated`
  - `syntax error`
  - `yaml:` (compose YAML parse errors)
- Mixed signal (substring matches both): permanent wins. Default when no match: permanent
  (don't retry unknown errors — the classifier is intentionally narrow).
- On final exhaustion, surface the original error message verbatim (no rewriting). The caller
  fails Wave B naturally as it does today.

## 4. Logging format

Each retry emits one log line at WARNING level:

```
[Wave B probing] Docker <op> attempt N/3 after transient failure: <error excerpt>
```

`<op>` is `compose up` or `compose exec truncate`. `<error excerpt>` is the first 200
characters of the matching stderr.

A **non-retried** path emits no extra log lines beyond what already exists. A successful first
attempt emits no retry telemetry.

## 5. Explicit non-goals

- **Do NOT retry the entire Wave B**. The scope of this fix is the Docker daemon boundary
  only.
- **Do NOT touch codex invocation** (no changes to `codex_transport`, `provider_router`, or
  `wave_executor`'s SDK call sites).
- **Do NOT touch compile-fix loops**, sub-agent watchdog wraps, or any timeout/budget
  configuration.
- **Do NOT widen the transient classifier** beyond the three listed substrings. Substring
  match is already loose; adding regex or keyword lists risks retrying on genuinely broken
  configs.
- **Do NOT add a global Docker retry decorator** that auto-applies elsewhere. Two specific
  call sites get this; nothing else does.
- **Do NOT bump `milestone_timeout_seconds`** to absorb retry overhead. Worst-case retry adds
  5+15+45 = 65s per affected boundary, which fits inside the existing PR #4 envelope without
  adjustment.

## 6. Tests (TDD)

`tests/test_wave_b_docker_retry.py` — five cases, all written *before* implementation and
verified to fail against current `master`:

1. **Transient-then-success**: docker call fails twice with each of the three transient
   substrings, then succeeds. Assert: probing succeeds, retry logs name attempts 1 and 2 with
   correct backoffs.
2. **Persistent transient**: 3 transient failures in a row. Assert: failure surfaces, original
   error preserved verbatim, exactly 3 attempts in logs.
3. **Non-transient error**: `image not found`. Assert: no retry (1 attempt total),
   immediate failure.
4. **Mixed**: transient → non-transient. Assert: no retry past the non-transient (2 attempts
   total), final error is the non-transient one.
5. **Backoff timing**: `time.sleep` is mocked; assert it was called with `5` then `15` then
   `45` and nothing else.

## 7. Files touched

- `src/agent_team_v15/runtime_verification.py` — add `_retry_docker_op(op, op_name)` helper +
  call from `docker_start` around the `up -d` call.
- `src/agent_team_v15/endpoint_prober.py` — call the same helper from `_truncate_tables`.
- `tests/test_wave_b_docker_retry.py` — new file, 5 tests.
- `docs/plans/2026-04-15-wave-b-docker-transient-retry.md` — this file.

## 8. Validation plan

- Unit: 5 new tests pass; full suite stays green (9989 prior + 5 new = 9994).
- Integration: re-run the integration smoke (`build-i-...-`). If a Docker transient fires
  during Wave B probing, the BUILD_LOG should show
  `[Wave B probing] Docker compose up attempt 2/3 after transient failure: ...` and Wave B
  should clear with `success: true`. If no transient fires, the run looks identical to a clean
  run — that's also fine; the retry path stays cold.
- Disposition: only merge to `integration-2026-04-15-closeout` after the unit suite is green.
  Master merge happens only after the integration smoke meets all 10 of the closeout
  criteria.

## 9. Memory-of-prior-mistakes hooks

- Per `feedback_structural_vs_containment.md`: this fix targets the *layer where the blocking
  call sits* (the Docker subprocess call), not an outer milestone-level timeout. It's a real
  boundary fix, not a containment patch.
- Per `feedback_verification_before_completion.md`: unit tests prove the mechanism; the
  integration smoke is what validates the integration. The PR will be merged into `master`
  only after a stock smoke clears Wave B with the change in place.
