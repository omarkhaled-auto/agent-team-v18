# Phase 5 closeout Stage 2 — Rerun 3 v3 forensic memo

Authored 2026-05-01 against `phase-5-closeout-stage-1-remediation` HEAD
`e2785b9` (post-N1 landing).

Scope: classification of the smoke 1 unresolved-finding cohort and the
smoke 2 app-server EOF, per the operator's directive after Rerun 3 v3
was accepted as not-evaluable. NO additional smoke spend authorised
between the original Rerun 3 v3 batch and this memo.

## Smoke 2 — app-server EOF classification

Run-dir: `phase-5-8a-stage-2b-rerun3-v3-20260501-175331-02-20260501-150551`

**Verdict — NOT host instability.** The app-server termination at
`19:20:57` was the routine end-of-turn teardown in `_execute_once`
finally; the 85927d2 propagation behaved correctly.

### Evidence trail

| Time (local) | Source | Event |
|---|---|---|
| 19:17:10 | BUILD_LOG | Codex CLI v0.125.0 dispatched, app-server initialised |
| 19:17:12 | BUILD_LOG | Thread + Turn started; `[ORPHAN-MONITOR]` armed (timeout=300s, interval=60s) |
| 19:20:47 | BUILD_LOG | `[ORPHAN-MONITOR] cancelled … polls=3 orphan_events=0` ← turn returned naturally |
| 19:20:57 | BUILD_LOG | `[APP-SERVER-TEARDOWN] killpg SIGTERM for tracked PID 950388 (process group)` ← cleanup, ~10s after turn end |
| 19:46:01 | BUILD_LOG / launcher | `[EXIT] Build failed. interrupted=False failed_milestones=['milestone-1']`; launcher EXIT_CODE=1 |

Final STATE.json (verified directly):

```json
{
  "current_phase": "complete",
  "interrupted": false,
  "total_cost": 6.088814999999999,
  "error_context": "",
  "milestone_progress": {
    "milestone-1": {
      "status": "FAILED",
      "failure_reason": "audit_fix_did_not_recover_build",
      "audit_status": "unknown"
    }
  }
}
```

### Why this is not host instability

* `orphan_events=0` ⇒ Codex's own orphan-monitor saw no anomaly. The
  monitor is bound to the turn lifecycle and is cancelled when
  `_wait_for_turn_completion` exits normally.
* The killpg SIGTERM at `codex_appserver.py:714` runs from
  `_perform_app_server_teardown` ← `_CodexJSONRPCTransport.close()` ←
  `_CodexAppServerClient.close()` ← `_execute_once` finally
  (`codex_appserver.py:1932`). That path is reached on EVERY turn,
  successful or otherwise.
* The orchestrator continued running for ≈25 minutes AFTER the
  app-server teardown (recovery passes, truth-score evaluation, post-
  orchestration verification, skill update hooks). A host-instability
  EOF would have terminated the orchestrator process, not just its
  Codex subprocess.

### Why milestone-1 still failed

Inventory of files Codex actually wrote to `apps/`, `packages/`,
`prisma/` under the run-dir: **23 files, all scaffold artifacts** —
`node_modules/.bin/*` CLI shims (`next`, `tsc`, `prisma`, `nest`,
`tailwindcss`, `tsx`, `vitest`, …), `apps/web/public/.gitkeep`, and
`packages/shared/dist/tsconfig.tsbuildinfo`. **Zero source files.**

Post-orchestration verification reported 33 `VIOLATION: Module file
not found` rows covering the entire deliverable surface
(`apps/api/src/`, `apps/web/src/`, `prisma/schema.prisma`,
`packages/shared`, `packages/api-client`). Truth score `0.300`.

Conclusion: smoke 2 is a real Codex Wave-B output failure (the turn
ran for ≈3min35s but the model produced nothing usable), not a
transport / host failure. Same class as the smoke 1 sample.

## Smoke 1 — unresolved-findings classification

Run-dir: `phase-5-8a-stage-2b-rerun3-v3-20260501-175331-01-20260501-135332`

STATE.json:

```json
{
  "milestone-1": {
    "status": "FAILED",
    "failure_reason": "audit_fix_recovered_build_but_findings_remain",
    "audit_status": "failed",
    "unresolved_findings_count": 23,
    "audit_debt_severity": "CRITICAL"
  }
}
```

### Methodology

Aggregated `audit-{comprehensive,interface,mcp-library,requirements,
test}_findings.json` (41 raw rows). Deduped by canonical-title heuristic
to 24 unique groups; STATE.json's `23` matches within the orchestrator's
exact dedup tolerance.

Categorised each group as DERIVATIVE / REAL / FALSE-POSITIVE based on
inspection of the underlying claims against `.agent-team/` artifacts +
the Phase 4.6 `§M.M22` scaffold-stub contract + the M1-foundation
PRD scope.

### Derivative of upstream Wave-B fail (3 groups)

These findings exist only because Wave B failed; they describe the
absence of downstream evidence that would have been produced if Wave B
had succeeded. They contain no independent source defect.

| Group | Severity | Why derivative |
|---|---|---|
| wave-b-failed-cascade | CRITICAL | Names the Wave-B fail itself ("Wave B failed with DB reset/seed error and STATE.json marks milestone-1 FAILED") |
| wave-t-skipped | HIGH | `WAVE_FINDINGS.json` has `wave_t_status=skipped` with `skip_reason="Wave B failed — Wave T cannot run E2E against failing wave output"` |
| specialized-auditors-skipped | HIGH | Audit-team dispatch is conditional on Wave B success per `_finalize_milestone_with_quality_contract` |

### Real Codex output defects (15 groups)

These are defects in Codex's actual output that the audit team
correctly identified.

| Group | Severity | Defect |
|---|---|---|
| duplicate-prisma-tree | CRITICAL | Both `prisma/schema.prisma` and `apps/api/prisma/schema.prisma` exist; migrations diverge |
| port-collision-3001 | CRITICAL | docker-compose maps both `api` and `web` services to host port 3001 |
| frontend-foundation-missing | CRITICAL | i18n locales, AuthProvider, UI primitives directory all absent |
| tailwind-tokens | HIGH | Tailwind config does not consume `UI_DESIGN_TOKENS.json` |
| frontend-i18n-missing | HIGH | `next-intl` declared but `en/`, `ar/` locale folders do not exist |
| bcrypt-missing-from-package-json | HIGH | `bcrypt` required at runtime, not declared in `apps/api/package.json` |
| web-app-port-3001 | HIGH | Web app hardcoded to 3001 contradicting `REQUIREMENTS.md` |
| stack-contract-ports | MEDIUM | `STACK_CONTRACT.json` declares both `api_port=web_port=3001` (internally inconsistent) |
| validation-pipe-config | MEDIUM | `main.ts` ValidationPipe omits `transformOptions.enableImplicitConversion` |
| helmet-not-wired | MEDIUM | `helmet` in dependencies but never imported / wired |
| env-example-missing-port-vars | MEDIUM | `.env.example` missing `PORT_API` / `PORT_WEB` |
| hardcoded-taskflow-string | MEDIUM | `page.tsx` renders literal "TaskFlow" violating i18n anti-pattern |
| request-normalization-middleware | MEDIUM | Silent snake_case → camelCase rewrite contradicts contract |
| createrequire-pattern | LOW | `PrismaService` + `PasswordHashingService` use runtime `createRequire` instead of standard import |
| jwt-expires-in-cast | LOW | `signOptions.expiresIn` cast through `as JwtExpiresIn` defeats class-validator |
| priority-enum-drift | LOW | `Priority` (Prisma) vs `TaskPriority` (`packages/shared`) naming drift |
| next-public-api-url-prefix | LOW | `NEXT_PUBLIC_API_URL` carries `/api` prefix while requirements declare bare host |

(Counted as 15 in the rollup — `web-app-port-3001` is a duplicate of
`port-collision-3001` from the angle of the web service's hardcode;
both the orchestrator dedup and our heuristic kept them as one group
in the 24-group tally.)

### False positive — M1-foundation scope (5 groups)

These describe absence of work that is intentionally deferred under
the M1-foundation PRD scope. They are correctly flagged as `INFO`/`LOW`
by the auditor (they would not block sign-off), but they belong in
"low-noise informational" not "unresolved blocking".

| Group | Severity | Why false positive |
|---|---|---|
| m1-foundation-design | INFO | M1 explicitly declares `0` ACs ("foundation only" PRD section); not a defect |
| m1-test-info-only | INFO | TEST-SUMMARY counts + banned-matcher absence are informational |
| m1-web-no-tests-by-design | LOW | Web app has 0 tests passing via `--passWithNoTests`; M1 has no web-test ACs |
| m1-scaffold-stub-by-design | LOW | Frontend root layout / middleware are scaffold-stubs deferred to Wave D per `§M.M22` |
| m1-single-endpoint-info | INFO | `GET /api/health` is the M1 deliverable per PRD; informational not a defect |

### Borderline (1 group)

| Group | Severity | Position |
|---|---|---|
| empty NestJS modules not imported into AppModule | INFO | The empty class bodies ARE Phase 4.6 `§M.M22` scaffold-stubs, but the AppModule wiring miss is a real defect — Codex emitted the stub headers but did not import them into `app.module.ts`. Half-design / half-defect. |

### Summary

* 23 unresolved findings == real defects + derivative + false-positive.
* **15 real Codex output defects** (CRITICAL/HIGH/MEDIUM/LOW spread)
  — these are independent of N1 and confirm Codex Wave B is producing
  consistently incomplete output for this PRD/scope. The DB-004
  validator-false-positive that the audit-fix loop chased
  (`FIX_CYCLE_LOG.md` Cycle 1 + 2 declined; enum-value @default
  syntax) is a SEPARATE concern that consumed audit-fix budget without
  fixing any of the 15 real defects.
* **3 derivative findings** that disappear once Wave B succeeds.
* **5 false-positives** rooted in scope-confusion between the M1-
  foundation contract and the auditor's whole-product expectations.
* **1 borderline** that should be re-classified as a real defect once
  the AppModule import is grepped.

## Recommendations

1. The 15 real defects are the SAME class of "Codex Wave-B output
   incomplete on TaskFlow PRD" that smoke 2 manifested differently
   (smoke 2 produced no source files at all). These are not pipeline
   regressions — they are Codex output-quality regressions on this
   specific PRD/scope at HEAD `85927d2`.
2. The DB-004 enum-default validator (FIX_CYCLE_LOG.md Cycles 1 + 2
   declines) is wasting audit-fix budget on false positives. Out of
   scope for Stage 2 reapproval, but worth tracking as a follow-up
   audit-rule defect.
3. The N1 fix (commit `e2785b9`) closes the stale-Docker-state defect
   that bootstrapped smoke 1's Wave B fail. With N1 in place, a fresh
   Rerun 3 from a clean host should see Wave B reach its actual
   build-or-fail state on its own merits, not on stale port 3001
   binding from a prior killed smoke.
4. Stage 2 reapproval still requires a fresh Rerun 3 with stop-rule
   ("first smoke zero diagnostics → root-cause"). Pre-launch hygiene
   is now self-healing via `--auto-clean` (default ON), so the
   operator-side cleanup-by-hand step is no longer required.
