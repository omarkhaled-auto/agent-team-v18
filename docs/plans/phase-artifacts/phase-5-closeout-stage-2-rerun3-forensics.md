# Phase 5 closeout Stage 2 — Rerun 3 v3 forensic memo

Authored 2026-05-01 against `phase-5-closeout-stage-1-remediation` HEAD
`e2785b9` (post-N1 landing).

Scope: classification of the smoke 1 unresolved-finding cohort and the
smoke 2 app-server EOF, per the operator's directive after Rerun 3 v3
was accepted as not-evaluable. NO additional smoke spend authorised
between the original Rerun 3 v3 batch and this memo.

## Smoke 2 — app-server EOF classification

Run-dir: `phase-5-8a-stage-2b-rerun3-v3-20260501-175331-02-20260501-150551`

**Verdict — abnormal terminal-turn EOF, not a post-orphan wedge and
not whole-host instability.** The app-server stdout closed before
`turn/completed` arrived; the 85927d2 propagation translated this
into the canonical `CodexTerminalTurnError` → wave-fail path with
correct `error_context`. The post-EOF `killpg SIGTERM` at `19:20:57`
is the routine `_execute_once` finally cleanup.

### Evidence trail

| Time (local) | Source | Event |
|---|---|---|
| 19:17:10 | BUILD_LOG | Codex CLI v0.125.0 dispatched, app-server initialised |
| 19:17:12 | BUILD_LOG | Thread + Turn started; `[ORPHAN-MONITOR]` armed (timeout=300s, interval=60s) |
| 19:20:47 | BUILD_LOG | `[ORPHAN-MONITOR] cancelled … polls=3 orphan_events=0` ← cancellation in finally (see below); does NOT prove turn-completed |
| 19:20:57 | BUILD_LOG | Wave executor logs `Codex turn <unknown>@thread <unknown> ended without turn/completed: app-server stdout EOF — subprocess exited`; `[APP-SERVER-TEARDOWN] killpg SIGTERM for tracked PID 950388 (process group)` |
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

### Why "abnormal terminal-turn EOF" rather than "natural turn end"

* `src/agent_team_v15/codex_appserver.py:1836` shows `monitor_task.cancel()`
  runs in a `finally` after `_wait_for_turn_completion`. Cancellation
  fires on BOTH the success path and the error path (EOF, exception,
  watchdog raise). `[ORPHAN-MONITOR] cancelled` therefore does NOT
  prove the turn returned successfully — only that
  `_wait_for_turn_completion` exited (one way or another) and the
  finally ran.
* The wave-executor log at 19:20:57 explicitly classifies this turn
  as "ended without `turn/completed`: app-server stdout EOF —
  subprocess exited". That is the `CodexTerminalTurnError` path
  closed in 85927d2 (typed terminal-turn error → wave-fail with
  canonical hang-report evidence). The classification matches the
  Phase 5 closeout `§M.M5` follow-up plumbing exactly.
* The captured Wave B protocol log
  (`.agent-team/codex-captures/milestone-1-wave-B-protocol.log`) ends
  after active events; there is no `turn/completed` notification.

### Why this is not a post-orphan wedge

* `orphan_events=0` after `polls=3` ⇒ the orphan-monitor never
  observed a stale tool. The watchdog's
  `codex_orphan_observed` signal was never emitted to the wave
  executor; Phase 5.7 §M.M5 productive-tool-idle predicates were
  never armed. The wedge class this fix targeted (post-orphan-monitor
  Codex stall) was NOT what closed smoke 2.

### Why this is not whole-host instability

* The orchestrator continued running for ≈25 minutes AFTER the EOF
  + app-server teardown — recovery passes, truth-score evaluation,
  post-orchestration verification, skill-update hooks all completed
  normally. Whole-host instability would have terminated the
  orchestrator process alongside its Codex subprocess; only the
  Codex subprocess exited.
* No host-side OOM / kernel / GNOME-session collapse evidence in
  `dmesg` window for that interval; the killpg call at 19:20:57 came
  from the orchestrator's own `_perform_app_server_teardown` path
  (`codex_appserver.py:714` ← `transport.close()` ← `client.close()`
  ← `_execute_once` finally `codex_appserver.py:1932`), which fires
  on every terminal-turn outcome.

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

### Real Codex output defects — 15 canonical groups

These are the 15 deduped real-defect groups that the audit team
correctly identified. Three port-3001 surface manifestations
(docker-compose collision, `STACK_CONTRACT.json` self-inconsistency,
web-app hardcode) collapse into the single root-cause group
`port-collision-3001` — Codex chose `3001` for both the api and web
services across every surface they appear on. The two
`createRequire`-loaded modules (`PrismaService`, `PasswordHashingService`)
collapse into `createrequire-pattern`. After those merges the table
below enumerates exactly 15 canonical groups.

| # | Group | Severity | Defect | Surface manifestations folded in |
|---|---|---|---|---|
| 1 | duplicate-prisma-tree | CRITICAL | Both `prisma/schema.prisma` and `apps/api/prisma/schema.prisma` exist; migrations diverge | also surfaces as duplicate `seed.ts` `main`/`day` functions in `GATE_FINDINGS.json` (derivative of the same root cause) |
| 2 | port-collision-3001 | CRITICAL | Codex chose `3001` for both api and web services across every surface | `docker-compose.yml` web+api both → `3001`; `STACK_CONTRACT.json` `api_port=web_port=3001`; web-app code hardcoded to `3001`; orchestrator port spec said `4000`/`3000`. One root cause, three surfaces |
| 3 | frontend-foundation-missing | CRITICAL | i18n locales, AuthProvider, UI primitives directory all absent | post-orchestration `Module file not found` violations (33 paths) corroborate |
| 4 | tailwind-tokens | HIGH | Tailwind config does not consume `UI_DESIGN_TOKENS.json` | `GATE_FINDINGS.json` "hardcoded hex color" rows are derivative of this |
| 5 | frontend-i18n-missing | HIGH | `next-intl` declared but `en/`, `ar/` locale folders do not exist | distinct from group 3 — covers the i18n wiring pieces (locale folders, middleware, switcher) |
| 6 | bcrypt-missing-from-package-json | HIGH | `bcrypt` required at runtime, not declared in `apps/api/package.json` | distinct from group 12 (`createRequire`); this is the dependency-declaration miss, group 12 is the loader-shape miss |
| 7 | request-normalization-middleware | MEDIUM | Silent snake_case → camelCase rewrite contradicts contract | — |
| 8 | validation-pipe-config | MEDIUM | `main.ts` ValidationPipe omits `transformOptions.enableImplicitConversion` | — |
| 9 | helmet-not-wired | MEDIUM | `helmet` in dependencies but never imported / wired | — |
| 10 | env-example-missing-port-vars | MEDIUM | `.env.example` missing `PORT_API` / `PORT_WEB` | distinct from group 2 — this is about the env-var declaration itself, not the chosen value |
| 11 | hardcoded-taskflow-string | MEDIUM | `page.tsx` renders literal "TaskFlow" violating i18n anti-pattern | `GATE_FINDINGS.json` hardcoded-JSX row is the same |
| 12 | createrequire-pattern | LOW | Runtime `createRequire` trick instead of standard import | both `PrismaService` and `PasswordHashingService` use the same anti-pattern (one canonical group, two call sites) |
| 13 | jwt-expires-in-cast | LOW | `signOptions.expiresIn` cast through `as JwtExpiresIn` defeats class-validator | — |
| 14 | next-public-api-url-prefix | LOW | `NEXT_PUBLIC_API_URL` carries `/api` prefix while requirements declare bare host | — |
| 15 | priority-enum-drift | LOW | `Priority` (Prisma) vs `TaskPriority` (`packages/shared`) naming drift | — |

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
* **15 canonical real Codex output defects** (CRITICAL/HIGH/MEDIUM/LOW
  spread, enumerated in the table above) — these are independent of
  N1 and confirm Codex Wave B is producing consistently incomplete
  output for this PRD/scope. The DB-004 validator-false-positive that
  the audit-fix loop chased (`FIX_CYCLE_LOG.md` Cycle 1 + 2 declined;
  enum-value @default syntax) is a SEPARATE concern that consumed
  audit-fix budget without fixing any of the 15 real defects.
* **3 derivative findings** that disappear once Wave B succeeds.
* **5 false-positives** rooted in scope-confusion between the M1-
  foundation contract and the auditor's whole-product expectations.
* **1 borderline** that should be re-classified as a real defect once
  the AppModule import is grepped.

15 + 3 + 5 + 1 = 24 deduped groups; this matches STATE.json's
`unresolved_findings_count=23` within the orchestrator's exact dedup
tolerance (the borderline AppModule wiring row may or may not
collapse into `frontend-foundation-missing` depending on the dedup
key the orchestrator chose).

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
