# Post-Gate-A Deep-Investigation Handoff — V18 Builder

**Generated:** 2026-04-16, after build-l-gate-a-20260416 (FAIL by design of D-02 v2).
**Purpose:** Complete, exhaustive state dump for a deep-thinking investigation session. Every open closeout item, every build-l finding, every root-cause hypothesis, every gap between "pipeline machinery fixed" and "pipeline one-shots a working app."
**Consumer:** a deep investigation / planning session that will synthesize this into a next-phase plan. Do not use this doc to start writing code. It's a map, not an instruction set.
**Integration HEAD:** `8ed55a4` on `integration-2026-04-15-closeout`.
**Pending PR:** #25 (session-6-fixes-d02-d03) — D-02 v2 + D-03 v2, validated in build-l, awaiting reviewer merge.

---

## 0. Why this document exists

Six closeout sessions (Sessions 1–5 + Session 6 smoke) fixed the builder's machinery — wave scope filtering, audit milestone-scoping, scaffold correctness, audit schema permissive read, state finalization, orchestration + recovery hygiene, runtime toolchain hardening, D-02 v2 (structural block-vs-skip), D-03 v2 (local-bin resolution). Those fixes landed correctly; unit-test coverage is broad; static verification captured at every session under `v18 test runs/session-0N-validation/`.

Build-l was the first paid smoke of the closeout. It **failed M1 at Wave B with a scaffold-vs-prober port mismatch the fixes correctly surfaced**. Audit produced 28 findings. The machinery is now truthful; the *generated output* and *several latent issues in the pipeline architecture itself* are where the next phase of work lives.

This handoff consolidates:
1. What was completed and merged.
2. What was deferred from the tracker (Sessions 7–13 and pending wiring).
3. Every finding from build-l, categorized by root cause.
4. Latent issues newly surfaced in build-l that were not in the original tracker.
5. Architectural root-cause analysis — "what is actually killing the pipeline."
6. Missing pieces for one-shot enterprise app generation.

The pipeline design *is* sound. The structural fixes landed. The potential is real. The remaining gaps are specific and enumerable; this document enumerates them.

---

## 1. Closeout status at handoff

### 1.1 Merged to `integration-2026-04-15-closeout`

| Session | PRs | Items | Landed |
|---|---|---|---|
| 1 | #13, #14 | A-09 (wave scope filter), C-01 (audit milestone-scoping) | `f23ddad`, `73a9997` |
| 2 | #15, #16 | A-01 (docker-compose), A-02 (port 3001), A-03 (Prisma shutdown), A-04 (i18n locales), A-07 (vitest), A-08 (.gitignore + .env), D-18 (npm audit pins), A-05 investigation (validation pipe baseline), A-06 investigation (RTL baseline) | `bcc9daf`, `12941c3` |
| 3 | #17, #18 | D-07 (audit permissive `from_json`), D-13 (`State.finalize()`), D-20 (M1 startup-AC probe), D-07 fix-up (fix_candidates coercion) | `7dec1c8`, `4898d02` |
| 4 | #19, #20, #21 | D-04 (review-fleet invariant), D-08 (CONTRACTS.json primary producer), D-05 (recovery prompt role isolation), D-06 (recovery taxonomy), D-11 (Wave T findings unconditional) | `089cd14`, `52edd97`, `11f7cda` |
| 5 | #22, #23, #24 | D-02 v1 (runtime `blocked` vs `skipped`), D-03 v1 (OpenAPI launcher Windows), D-09 (MCP pre-flight + labeled fallback) | `71d208a`, `a5ba9fa`, `8ed55a4` |

### 1.2 Pending at handoff

| PR | Branch | Content | Status |
|---|---|---|---|
| #25 | `session-6-fixes-d02-d03` | D-02 v2 (structural `infra_missing` flag + host-port diagnostic), D-03 v2 (workspace-walk local-bin resolution) | Open, validated in build-l, pending reviewer diff approval |

### 1.3 Feature flags introduced across sessions

All default `True`, tests cover both branches. Operators can flip any to `False` in `config.yaml` to restore pre-closeout behaviour:

- `v18.milestone_scope_enforcement` (Session 1 A-09) — wave prompt scope preamble.
- `v18.audit_milestone_scoping` (Session 1 C-01) — audit prompt scope preamble.
- `v18.review_fleet_enforcement` (Session 4 D-04) — post-recovery invariant raises vs warns.
- `v18.recovery_prompt_isolation` (Session 4 D-05) — recovery prompt role separation.
- `v18.m1_startup_probe` (Session 3 D-20) — execute startup-AC probes at audit time.

### 1.4 Validation artefact trail

Every session preserved static-verification outputs:

- `v18 test runs/session-01-validation/` — A-09 + C-01 prompt greps, build-j re-scoring transcript (28 out-of-scope → 13 scope_violation consolidations).
- `v18 test runs/session-02-validation/` — scaffold dump + A-05/A-06 investigation notes.
- `v18 test runs/session-03-validation/` — build-j AUDIT_REPORT.json round-trip transcript + schema divergence map.
- `v18 test runs/session-04-validation/` — D-04/D-05/D-08 investigation notes.
- `v18 test runs/session-05-validation/` — D-09 investigation (MCP deployable absent → Branch B labeling chosen).
- `v18 test runs/build-l-gate-a-20260416/` — first end-to-end integration signal. See §4.

---

## 2. Open deferred sessions (from the reliability tracker)

Sessions 7–13 from `docs/plans/2026-04-15-builder-reliability-tracker.md` §9. None run. All still open. Items listed inline with their tracker IDs.

### 2.1 Session 7 — Compile-fix + fallback (HIGH risk)

Investigation-first session. Per `2026-04-15-a-10-compile-fix-budget-investigation.md` + tracker §5.

- **A-10** — Wave D compile-fix budget exhausts at 3 attempts; fallback produces code that doesn't compile. *Observed in build-j's Wave D; build-l didn't reach Wave D so this is unverified in current state.* Candidates: iteration cap too low on fallback path, iteration context bleed, structural misfit (missing deps), incomplete fallback output.
- **D-15** — Compile-fix loop lacks structural triage pass. Should inspect `package.json`/`tsconfig.json`/top-level configs before entering per-file diff loop.
- **D-16** — Post-fallback Claude output quality. Depends on A-09 (scope filter, now landed) + A-10 (budget). May be partially resolved by A-09 narrowing the scope the fallback has to produce.

**Est. size:** M, ~200 LOC. **Risk:** HIGH — recovery hot-path, budget changes affect cost.

### 2.2 Session 8 — Telemetry + calibration hygiene (LOW risk)

- **D-12** — Codex `last_sdk_tool_name` still blank in final wave telemetry despite hang reports showing tool name correctly. Finalize-timing bug. Bug #20 (codex app-server) would obsolete this for codex path; still needed for Claude path.
- **D-14** — Verification artefacts blend static + heuristic without fidelity labels. D-09's fidelity-header helper landed (but un-wired — see §3.3) is a precedent; D-14 generalizes it across all verification outputs.
- **D-17** — Truth-score calibration: `error_handling=0.06` on a codebase with global exception filter (probe counts per-function try/catch, misses framework-level patterns); `test_presence=0.29` on M1 (penalizes "zero test files" even when milestone spec requires empty placeholder).

**Est. size:** M, ~140 LOC. **Risk:** LOW — no hot-path touches.

### 2.3 Session 9 — Residual hygiene (LOW risk)

- **D-01** — Context7 quota pre-flight. Environmental (quota is external) but builder should pre-probe + gracefully degrade with a structured `TECH_RESEARCH.md` stub instead of silent omission.
- **D-10** — Phantom integrity finding (DB-004 in build-j re-raised across fix cycles). Integrity checker needs a per-run false-positive suppression list.

**Est. size:** S, ~90 LOC. **Risk:** LOW.

### 2.4 Session 10 — Optional validation smoke gate (skippable)

Run only if Sessions 7–9 touched wave prompts or compile-fix hot-path. Otherwise skip.

### 2.5 Session 11 — Bug #20 codex app-server migration

Per `docs/plans/2026-04-15-bug-20-codex-appserver-migration.md`. Structural transport replacement. Materially resolves D-12 (last_sdk_tool_name natural via `item/started` streaming events); indirectly reduces pressure on A-10/D-15/D-16 by lowering Claude-fallback frequency. **Explicitly NOT a gate for M1 clearance** per the tracker's Bug #20 plan §11.

**Est. size:** XL (~800 LOC + 20 tests). **Risk:** HIGH — new transport layer. Quality investment, not closeout-critical.

### 2.6 Session 12 — Full-pipeline integration smoke (Gate D)

Full exhaustive smoke across M1–M6 on stock Sonnet config. Required before any master merge. **Cost:** ~$25–40. **Gate criteria:** all milestones PASS, audit health `passed`, no Tier-1 blockers fire.

### 2.7 Session 13 — Master merge

Merge `integration-2026-04-15-closeout` to `master`. No code changes. Closes PRs #3–#12 + #25 as appropriate.

---

## 3. Pending wiring from closed sessions (technical debt)

Items where the mechanism landed but the production wiring is incomplete. Flagged in the session-approval reviews but deferred to keep session scope tight.

### 3.1 D-02 v2 consumer-side fail-loud upgrade

**Status:** partially wired — existing `cli.py:12759` pattern `if health not in ("passed", "skipped"): recovery_types.append(...)` will catch the new `"blocked"` value and trigger recovery, which is better than silent skip. But there's no *explicit* consumer that halts the pipeline with a legible "blocked" diagnostic when infrastructure is present but app-level health fails. Build-l proved the Wave B `(success=False, reason, [])` path works — but the cli-layer consumers don't know that `blocked` is a distinguished value. Upgrade path: one-line consumer update to raise a structured `RuntimeBlockedError` that halts the milestone instead of triggering a generic `e2e_backend_fix` recovery.

### 3.2 D-09 MCP pre-flight call site

**Status:** helpers defined in `mcp_servers.py` (`run_mcp_preflight`, `ensure_contract_e2e_fidelity_header`), zero production callers. Dead code until wired. Build-l didn't exercise this path because no `contract_verifier` code path called either helper. Session 5 explicitly banned `cli.py` edits for PR #24 to keep the PR small; wiring is a 2-call-site addition (pipeline startup + CONTRACT_E2E_RESULTS.md writer).

### 3.3 D-14 verification-artefact fidelity labels (not yet started)

Session 8 item. Generalization of D-09's fidelity-header approach across all verification outputs: `RUNTIME_VERIFICATION.md`, `VERIFICATION.md`, `CONTRACT_E2E_RESULTS.md`, `GATE_FINDINGS.json`. Each should carry an explicit fidelity tag (runtime | static | heuristic) so downstream operators can tell at a glance how much weight to put on the report.

### 3.4 C-01 scope field population in production AUDIT_REPORT.json

**Status: LATENT BUG.** C-01 landed `scope: dict[str, Any] = field(default_factory=dict)` on `AuditReport` + `_apply_evidence_gating_to_audit_report` populates it. But build-l's `AUDIT_REPORT.json` parses with `scope = ABSENT` (i.e., `{}`). The scorer-agent's write path (via the LLM scorer sub-agent writing raw JSON) does NOT populate the scope field — only the cli-side `build_report(...)` call in `_apply_evidence_gating_to_audit_report` would, and that consolidation step runs on a report that has already been persisted by the scorer without the field. **The scope-populated report is overwritten or not re-persisted.** This is a subtle bug that invalidates the "audit report carries scope context for downstream consumers" promise of C-01. The scope-scoped *prompts* still fire (via `build_auditor_agent_definitions`) — the scope context is IN the auditor's prompt — but the *persisted report* doesn't carry it.

---

## 4. Build-l findings — complete catalogue

**Run slug:** `build-l-gate-a-20260416`. **Cost:** $8.37. **Duration:** ~70 min wall clock (killed at ~T+70min). **Exit:** M1 FAILED at Wave B probe phase. **Auditor output:** 28 canonical findings.

### 4.1 Pipeline state at kill

From `.agent-team/STATE.json`:

- `current_phase: orchestration` — pipeline was still in post-orchestration hooks at kill.
- `failed_milestones: ["milestone-1"]`
- `wave_progress.milestone-1: {completed_waves: ["A"], failed_wave: "B", current_wave: "B"}` — Wave A cleared, Wave B failed, C/D/T/E never ran.
- `waves_completed: 1`
- `summary.success: True` ⚠️ **inconsistent with failed_milestones — D-13 State.finalize did not fire because pipeline was killed before the final reconciliation pass.** Not a D-13 bug; a kill-side effect.
- `audit_health: ""` — empty string despite `AUDIT_REPORT.json` existing. D-13 finalize didn't run.
- `audit_score: 0.0` — not the 40/1000 from AUDIT_REPORT.json.
- `gate_results: []` — empty.
- `truth_scores: {}` — empty; truth scoring never ran (post-audit phase never reached).

### 4.2 All 28 findings, by category

Category labels from the audit JSON (not the tracker's Bucket A/B/C/D taxonomy). Ordered by severity then ID.

#### Critical (5)

| ID | Title | Category | Root cause class |
|---|---|---|---|
| AUD-001 | `packages/` workspace directory entirely missing (shared + api-client) | completeness | **Scaffold gap** — Session 2's scaffold emits only `packages/api-client/index.ts`, not `packages/shared`. Workspace structure incomplete. |
| AUD-002 | `apps/web` has no Next.js source (layout, page, middleware, client, test setup) | completeness | **Cascade** — Wave D never ran; blocked after Wave B failure. |
| AUD-005 | No Prisma migration files exist | completeness | **Scaffold gap** — Session 2 emits `schema.prisma` but not `prisma/migrations/<timestamp>_init/migration.sql` + `migration_lock.toml`. |
| AUD-021 | Wave B health probe targeted unconfigured port `:3080` and failed | environment | **Primary failure cause** — scaffold/PRD/prober port three-way mismatch. |
| AUD-028 | Milestone-1 Definition of Done is unachievable with the current codebase | interface | **Meta-finding** — auditor's rollup conclusion; not a distinct actionable. |

#### High (12)

| ID | Title | Category | Root cause class |
|---|---|---|---|
| AUD-003 | `apps/web/package.json` missing required runtime/dev dependencies | infrastructure | **Cascade** — Wave D never ran. |
| AUD-004 | `apps/web/package.json` missing `api:generate`/`prebuild`/`predev` scripts | infrastructure | **Cascade** — Wave D never ran. |
| AUD-006 | `apps/api/.env.example` and `apps/web/.env.example` missing | infrastructure | **Scaffold gap** — Session 2 emits root-level `.env.example` with PORT=3001; does NOT emit per-app `.env.example` files. |
| AUD-007 | `docker-compose.yml` missing web service | infrastructure | **Scaffold gap** — Session 2 A-01 adds postgres only; `apps/api` and `apps/web` services not scaffolded. |
| AUD-008 | `docker-compose` api service lacks dev volume mounts | infrastructure | **Scaffold gap** — as above; api service not scaffolded. |
| AUD-009 | `AllExceptionsFilter` registered twice (`main.ts` and `AppModule` providers) | correctness | **Wave B LLM bug** — spec calls for single registration; LLM double-registered. |
| AUD-010 | `main.ts` uses `configService.getOrThrow` for CORS_ORIGIN (spec uses `.get`) | correctness | **Wave B LLM spec drift** — small API choice difference from spec. |
| AUD-011 | PrismaModule/PrismaService at `src/prisma` instead of `src/database` | correctness | **Scaffold vs spec mismatch** — Session 2 A-03 scaffold emits at `src/prisma` (matches M1 REQUIREMENTS.md's own file tree); stock PRD specifies `src/database`. **Spec conflict between M1 REQUIREMENTS.md and PRD.** |
| AUD-012 | `apps/api/package.json` missing `bcrypt` dependency | infrastructure | **Wave B LLM bug** — M1 spec says "JWT module shell, no strategies"; bcrypt unnecessary for shell, but auditor expects it. Audit-spec divergence. |
| AUD-020 | `TransformResponseInterceptor` uses URL-prefix skip instead of decorator | correctness | **Wave B LLM bug** — implementation choice differs from spec. |
| AUD-022 | Web-side vitest setup file missing; jest-dom matchers unavailable | tests | **Scaffold gap** — Session 2 A-07 emits `vitest.config.ts` but NOT `apps/web/vitest.setup.ts` importing jest-dom matchers. |
| AUD-026 | Wave T skipped — no Playwright/supertest smoke coverage | tests | **Cascade** — Wave T blocked after Wave B failure. |

#### Medium (8)

| ID | Title | Category | Root cause class |
|---|---|---|---|
| AUD-013 | `AllExceptionsFilter` uses bare string literals instead of `ErrorCodes` constants | correctness | **Wave B LLM quality** — code-quality divergence from spec's ErrorCodes pattern. |
| AUD-014 | `PaginatedResult` and `PaginationMeta` defined in `apps/api` instead of `packages/shared` | correctness | **Workspace ownership** — shared types should live in `packages/shared`; packages/shared doesn't exist (see AUD-001), so Wave B put them in apps/api. |
| AUD-016 | `PaginatedResult` `@ApiProperty` uses type `Object` for items array | correctness | **Wave B LLM quality** — Swagger typing imprecise. |
| AUD-017 | `PORT` and `NODE_ENV` use Joi defaults instead of being required | configuration | **Spec drift** — Session 2 A-02 scaffold sets Joi defaults (`.default(3001)`); PRD/audit expects `.required()`. |
| AUD-018 | `generate-openapi.ts` does not apply global pipes/filters/interceptors before `createDocument` | configuration | **Wave B LLM bug** — spec requires globals applied before Swagger document creation. |
| AUD-019 | `apps/api/Dockerfile` is single-stage dev-only (`CMD start:dev`) | infrastructure | **Scaffold gap or Wave B** — Session 2 didn't emit Dockerfiles; Wave B emitted a dev-only one. |
| AUD-023 | Health e2e test overrides `PrismaService` with `jest.fn()` (no real boot) | tests | **Wave B LLM quality** — mock instead of integration test. |
| AUD-027 | Root `package.json` lacks prisma ergonomics scripts | configuration | **Scaffold gap** — Session 2 A-01 scaffold's root `package.json` missing `db:migrate`/`db:seed`/etc. shortcuts. |

#### Low (3)

| ID | Title | Category | Root cause class |
|---|---|---|---|
| AUD-015 | `env.validation.ts` does not validate `JWT_EXPIRES_IN` format | configuration | **Scaffold incompleteness** — Session 2 A-02 validates a subset of env vars. |
| AUD-024 | `.editorconfig` and `.nvmrc` not confirmed at repo root | configuration | **Scaffold gap** — Session 2 A-08 emits `.gitignore` but not `.editorconfig`/`.nvmrc`. |
| AUD-025 | `turbo.json` `generate:client` task missing `dependsOn build` | configuration | **Scaffold gap** — Session 2 doesn't emit `turbo.json` at all; whatever wrote it didn't wire task deps correctly. |

### 4.3 Taxonomy collapse

The 28 findings are not 28 independent bugs. Collapsing by root-cause class:

| Class | Count | Resolution path |
|---|---|---|
| **Cascade** (Wave B failed → Wave C/D/T/E never ran → auditor flags absent output) | 5 (AUD-002, AUD-003, AUD-004, AUD-022-partial, AUD-026) | Fix the primary Wave B failure; cascade findings vanish automatically. |
| **Scaffold gap** (Session 2 scaffold emits a subset of expected files) | 9 (AUD-001, AUD-005, AUD-006, AUD-007, AUD-008, AUD-015, AUD-022, AUD-024, AUD-025, AUD-027) | Extend scaffold templates. See §6 new tracker items N-02/N-03/N-05/N-06/N-07. |
| **Wave B LLM bug / spec drift** (generated code doesn't match spec) | 8 (AUD-009, AUD-010, AUD-012, AUD-013, AUD-014, AUD-016, AUD-018, AUD-020, AUD-023) | Either prompt improvements or audit-fix loop (iterate on audit findings, dispatch fix agents). See §5.3 + §6 N-08/N-09/N-10. |
| **Primary infrastructure bug** (scaffold/PRD/prober port mismatch) | 1 (AUD-021) | See §6 N-01. Critical blocker. |
| **Scaffold-vs-spec conflict** (Session 2 followed M1 REQUIREMENTS.md, PRD expects something else) | 2 (AUD-011, AUD-017) | Reconcile M1 REQUIREMENTS.md with PRD. See §6 N-02. |
| **Meta-finding** (auditor rollup) | 1 (AUD-028) | Not actionable directly. |
| **Dockerfile ownership** (scaffold doesn't emit, Wave B emits wrong) | 1 (AUD-019) | Decide ownership. See §6 N-02. |

Actionable-distinct-bugs count: **~17**, not 28. Reduces the triage cost considerably but still indicates real work.

### 4.4 Observed during build-l (not counted as findings)

- **D-02 v2 fired correctly.** The entire reason we saw "Wave B live endpoint check misconfigured" is that D-02 v2's structural `infra_missing=False` path returned `(success=False, reason, [])` from `_run_wave_b_probing` instead of silently skipping.
- **D-03 v2 un-exercised.** Wave C never ran (blocked after B), so OpenAPI generation launcher fix didn't fire. Validated in unit tests only; no smoke evidence yet.
- **D-09 un-exercised.** MCP helpers defined but unused (see §3.2). Build-l's `CONTRACT_E2E_RESULTS.md` was never written (no Wave C/D) — no fidelity header to miss.
- **D-13 State.finalize() didn't run.** Kill interrupted the pipeline before final reconciliation. Not a bug; a kill artefact. But means STATE.json is internally inconsistent in ways Session 3 was supposed to fix.
- **C-01 scope field not in AUDIT_REPORT.json** (see §3.4). The audit ran; the scope-scoped prompt was fed in; the resulting report parses without a `scope` key. Latent bug — C-01's persistence pipeline has a gap.
- **A-09 wave scope filter landed in the Wave B prompt.** No evidence of over-build at Wave B (code produced is narrowly M1-scoped). Scope filter working as intended at the prompt layer.

---

## 5. Root-cause analysis — what is actually killing the pipeline

Moving from "findings" to "why the findings exist." This section is the heart of the deep-investigation handoff.

### 5.1 Three-layer ownership ambiguity (the biggest structural gap)

**The pipeline has three distinct code-producing layers that each *partially* own M1 output:**

1. **`scaffold_runner.py` — deterministic Python templates.** Emits minimal skeleton files before any LLM waves run: `docker-compose.yml` (postgres only), root `package.json`, `.gitignore`, `apps/api/src/main.ts` stub, `apps/api/src/prisma/prisma.service.ts`, `apps/web/package.json` with vitest devDeps, etc. Session 2 fixed this layer.

2. **Wave B (backend LLM codegen).** Reads the milestone-scoped prompt + whatever scaffold emitted + the PRD, produces a complete NestJS app. In build-l: 43 files touched. Session 1 A-09 filters the scope this layer is told to produce.

3. **Wave D (frontend LLM codegen).** Same pattern for `apps/web/`. Never exercised in build-l.

4. **Auditor fleet.** Reads the final output and compares against M1 REQUIREMENTS.md + the PRD. Produces findings. Session 1 C-01 scopes what the auditor evaluates.

**The problem:** the three layers do NOT agree on who emits what. Examples from build-l:

- `packages/shared` — scaffold doesn't emit it, Wave B doesn't emit it, auditor expects it. (AUD-001)
- `prisma/migrations/` — scaffold emits `schema.prisma` only, Wave B could emit migrations but doesn't always, auditor expects init migration. (AUD-005)
- `apps/api/.env.example` — scaffold emits root `.env.example`, auditor expects a per-app file too. (AUD-006)
- `docker-compose.yml` web + api services — scaffold emits postgres only, Wave B extends or not, auditor expects all three. (AUD-007, AUD-008)
- `apps/web/vitest.setup.ts` — scaffold emits config, not setup file; Wave D would emit setup; Wave D didn't run; auditor flags it. (AUD-022)
- `turbo.json` — nobody owns it; neither scaffold nor Wave B emits it with the right shape. (AUD-025)
- `.editorconfig` / `.nvmrc` — nobody owns these. (AUD-024)
- Dockerfiles — scaffold doesn't emit, Wave B emits a dev-only one, auditor expects multi-stage. (AUD-019)

**Why this is the root cause:** the audit's *expectation* is a superset of what any single layer produces. The scaffold+Wave-B+Wave-D combined output is *also* a superset — but a *different* superset. The Venn diagram of "scaffold produces" ∩ "Wave B produces" ∩ "auditor expects" has gaps.

**What this needs:** a single canonical ownership table. For every file the auditor expects, explicitly assign an owner: scaffold OR Wave-specific OR "optional, don't flag." Then the missing-file findings collapse to either (a) a scaffold extension task or (b) a Wave prompt addition or (c) an audit expectation softening.

### 5.2 Spec ambiguity between M1 REQUIREMENTS.md and the PRD

**Observed conflicts:**

- **Prisma module location.** M1 REQUIREMENTS.md's "Files to Create" tree says `apps/api/src/prisma/prisma.module.ts` + `.service.ts`. The stock PRD (TASKFLOW_MINI_PRD) apparently says `src/database`. Session 2 A-03 followed the file tree (src/prisma). Audit flags it (AUD-011).
- **Backend port.** M1 REQUIREMENTS.md + Session 2 A-02 = `:3001`. The stock PRD apparently says `:4000`. `endpoint_prober._detect_app_url` defaults to `:3080` (legacy). Three different values in the same pipeline. AUD-021 is the runtime consequence.
- **Env validation strictness.** M1 REQUIREMENTS.md + scaffold = Joi defaults. PRD expects `.required()` for PORT/NODE_ENV. (AUD-017)
- **Optional vs mandatory deps.** M1 REQUIREMENTS.md says "JWT module shell, no strategies." PRD-derived audit flags `bcrypt` missing (AUD-012) because downstream milestones will need it — but M1 doesn't.

**Why this is the root cause of a second class of findings:** the audit evaluates against a composed spec (M1 REQUIREMENTS.md + PRD + conventions), but no single artefact is the *normative* source. If M1 REQUIREMENTS.md is authoritative, Session 2's scaffold is correct and the audit is wrong. If the PRD is authoritative, Session 2 followed the wrong file. If both are "partial specs that the auditor reconciles on the fly," then the reconciliation is opaque and non-deterministic.

**What this needs:** a spec-reconciliation step at milestone entry. Produce a single `.agent-team/milestones/<id>/SPEC.md` that merges M1 REQUIREMENTS.md + PRD excerpts into *one* authoritative spec. Scaffold + Wave prompts + auditor all read from that single doc. Conflicts get resolved at reconciliation time, not at audit time.

### 5.3 No iterative audit → fix → re-audit loop

**Observed behaviour:** Build-l (and build-j before it) produced an AUDIT_REPORT.json with 28 findings and then exited. Zero fix cycles attempted.

**Why this matters:** ~8 of build-l's 28 findings are small Wave-B LLM bugs (AUD-009, AUD-010, AUD-012, AUD-013, AUD-014, AUD-016, AUD-018, AUD-020). Each of these is the kind of mistake a focused fix agent could resolve in one pass: "remove the duplicate registration," "change `getOrThrow` to `.get`," "add bcrypt to deps." A single audit → dispatch → re-audit cycle probably clears half the findings. Two cycles probably clears most.

Instead, the audit produces `fix_candidates` (list of finding indices flagged for auto-fix). Build-l's fix_candidates is populated — but Session 4 + build-j evidence shows the fix-dispatch path in `cli.py` (around line 5539 `group_findings_into_fix_tasks`) rarely actually runs for per-finding remediation. It runs for very specific recovery types (`contract_generation`, `review_recovery`, `mock_data_fix`, etc.) but not for generic audit findings.

**Why this is the root cause of a third class:** a sizable share of build-l's findings could be automatically resolved. The pipeline has the data (fix_candidates, per-finding `fix_action` strings) but doesn't close the loop. An auto-fix-on-audit cycle is a missing primitive.

**What this needs:** a new pipeline phase between `audit` and `complete`: `audit_fix_iteration`. For each CRITICAL/HIGH finding with a concrete `fix_action`, dispatch a targeted code-modification agent. Re-audit. Repeat until (a) all findings resolved, (b) max iterations reached, or (c) no progress across two consecutive iterations. Session 4 D-04 added a review-fleet invariant; this is analogous but broader.

### 5.4 No prompt-validation step after wave output

**Observed behaviour:** Wave B reads the prompt (which now includes A-09's scope preamble), produces 43 files, compile-fix clears, probing blocks, done. There's no check that the produced files *match the scope the prompt specified*.

**A-09's post-wave validator** (`files_outside_scope(files_created, scope)` in `wave_executor.py`) flags files outside allowed globs as `scope_violations` — that's a step in the right direction. But A-09 only validates file *paths*, not file *contents*. A Wave B that produces `apps/api/src/main.ts` with a triple-nested router and a hardcoded admin user passes A-09's check (file is in scope) even though the content violates M1's "no feature business logic" directive.

**Why this is a root cause:** content-level scope enforcement is absent. Wave B can produce code that's technically inside the allowed path globs but semantically outside the milestone scope. A-09 catches over-build (files), C-01 catches audit over-scope (finding target), but nothing catches Wave B producing M2-scope *logic* inside M1-scope *files*.

**What this needs:** a post-wave content auditor. Small, focused: read each Wave-B-produced file, confirm its contents match the scope's forbidden-content directives from the milestone REQUIREMENTS.md. Overlaps with §5.3's auto-fix loop.

### 5.5 Scaffold doesn't probe its own output before waves run

**Observed behaviour:** `scaffold_runner.run_scaffolding(...)` emits files. Wave B then starts from that state. No step validates "is this a runnable monorepo?" between scaffold and Wave B.

**Consequences:**
- `npm install` failures from bad scaffold `package.json` surface only during Wave B compile-fix.
- Missing `packages/shared` in scaffold surfaces only at audit time.
- Invalid `docker-compose.yml` shape surfaces only at probe time.

**What this needs:** a scaffold-self-verification step. After scaffold emission, parse + validate `package.json` (workspace globs match actual directories), `tsconfig.json` (paths resolve), `docker-compose.yml` (YAML valid, services reference real images), `prisma/schema.prisma` (parseable). Fail fast at a scaffold-level gate before Wave B spends tokens.

### 5.6 `endpoint_prober` port detection is hardcoded/stale

**Observed behaviour in build-l:** `endpoint_prober._detect_app_url` returned `http://localhost:3080`. Wave B emitted an API on `:4000`. Probe polled `:3080` for 60s, nothing answered, Wave B blocked.

**Why `:3080`:** legacy default from an earlier TaskFlow run where the PRD specified `:3080`. The value got baked in; no follow-up made it configurable from scaffold output.

**The real fix** (N-01 below): `_detect_app_url` should read, in order:
1. `apps/api/.env` / `.env.example` for `PORT=<n>`.
2. `apps/api/package.json` scripts for a `--port <n>` arg.
3. `apps/api/src/main.ts` AST for `.listen(<n>)` calls.
4. `docker-compose.yml` `services.api.ports` mapping.
5. Fall back to `:3080` (warn loudly).

### 5.7 Partial wiring of Session-landed features into production

**§3.1 – §3.4 above documents four instances where a session's mechanism landed but the production wiring didn't.** This is a systemic risk: the unit-test pass signal lies about end-to-end coverage. Closed sessions carry ghost work that looks complete but isn't exercised on the hot path.

**What this needs:** a per-session "production-caller proof" artefact — not a unit test, but a small script under `v18 test runs/session-0N-validation/` that builds the production call chain with a mock SDK and asserts the feature actually fires. Session 1 had this for A-09 (captured the M1 Wave D prompt) and C-01 partial (wiring re-scoring). Later sessions dropped the practice; bring it back.

### 5.8 Auditor is a true-positive generator, but `fix_candidates` flows nowhere

Ties into §5.3. The audit currently *identifies* problems and *names* them in `fix_action` fields. It does not *dispatch* remediation for generic findings. The only auto-remediation paths that fire are the explicit recovery types in `display.py:type_hints` — `contract_generation`, `review_recovery`, `mock_data_fix`, `ui_compliance_fix`, etc. Most audit findings don't map to any of those.

**What this needs:** a generic audit-finding-to-fix-agent dispatcher. Given a finding with a `fix_action` string and a `location` path, spawn a one-shot fix agent with a tight prompt ("Fix this specific issue at this specific location"). Audit-scorer triggers this for all CRITICAL/HIGH findings before declaring FAIL.

### 5.9 Stock PRD is not a valid closeout PRD

**Observed behaviour:** the stock `TASKFLOW_MINI_PRD.md` was chosen as the smoke test because it's relatively small (~4 entities). But its content appears to specify:
- `:4000` for the API port (mismatches M1's `:3001`).
- `src/database` for Prisma (mismatches M1's `src/prisma`).
- A full projects/tasks/comments/users feature set spread across M2–M5.

**Why this matters:** a smoke PRD should ideally TEST the closeout machinery, not introduce its own spec conflicts. Build-l's failure involves both pipeline bugs (port prober) AND PRD-vs-REQUIREMENTS conflicts that have nothing to do with the closeout.

**What this needs:** either (a) a smoke PRD specifically curated to match M1 REQUIREMENTS.md exactly (remove M2-M5 spec content, pin port to 3001, pin prisma to src/prisma), or (b) accept that the stock PRD tests a harder "real-world" case and adjust auditor expectations to honor PRD-level overrides.

---

## 6. New tracker items (surfaced in build-l + root-cause analysis)

Candidate new tracker entries, to be sized and prioritized in the deep-investigation session. IDs prefixed `N-` to distinguish from the original tracker's A-/B-/C-/D-/F-/CV- IDs.

### N-01 — `endpoint_prober._detect_app_url` port resolution — CRITICAL

**Blocks:** all future Gate A smoke attempts with the stock PRD (including build-m).
**Fix shape:** read port from `apps/api/.env.example`, `apps/api/package.json` scripts, `apps/api/src/main.ts` AST (`app.listen(<n>)`), `docker-compose.yml` api service port mapping, in that order. Fall back to legacy `:3080` with a loud warning.
**Est. size:** S (~60 LOC + 4 tests). **Risk:** LOW (one file, narrow change).

### N-02 — Scaffold ↔ Wave ↔ Audit file-ownership contract — HIGH

**Blocks:** ~9 of build-l's 28 findings (all "scaffold gap" class).
**Fix shape:** produce `docs/SCAFFOLD_OWNERSHIP.md` listing every file M1 REQUIREMENTS.md + PRD expects, with an explicit owner label. Update scaffold to emit its assigned files; update Wave B/D prompts to know what they own; update auditor's expectation set to honor the contract.
**Est. size:** M–L (investigation + scaffold additions + prompt edits + test updates). **Risk:** MEDIUM (touches three layers simultaneously).

### N-03 — `packages/shared` scaffold emission — HIGH

**Blocks:** AUD-001 (CRITICAL) + AUD-014 (MEDIUM).
**Fix shape:** extend Session 2's `_scaffold_m1_foundation` to emit `packages/shared/index.ts` + `package.json` + `tsconfig.json` with baseline types (`PaginatedResult`, `PaginationMeta`, `UserRoleEnum`, etc.). Workspace manifests updated.
**Est. size:** S–M (~100 LOC + tests).

### N-04 — Prisma module location spec-vs-scaffold reconciliation — HIGH

**Blocks:** AUD-011.
**Fix shape:** decide canonical location (`src/database` per PRD convention, or `src/prisma` per NestJS convention and M1 REQUIREMENTS.md). Update both scaffold template and M1 REQUIREMENTS.md to match. Wave B prompt reminder.
**Est. size:** S (~20 LOC + spec update).

### N-05 — Prisma initial migration scaffold — HIGH

**Blocks:** AUD-005 (CRITICAL).
**Fix shape:** Session 2 scaffold emits `prisma/migrations/<fixed_timestamp>_init/migration.sql` with initial schema migration + `migration_lock.toml`. Or delegates this to Wave A explicitly.
**Est. size:** S (~40 LOC + test).

### N-06 — Web scaffold completeness — HIGH

**Blocks:** AUD-022 partial (vitest setup), AUD-003/004 when Wave D fails similarly in future runs.
**Fix shape:** Session 2 scaffold emits minimum Next.js tree: `apps/web/src/app/layout.tsx` stub, `apps/web/src/app/page.tsx` stub, `apps/web/src/middleware.ts`, `apps/web/vitest.setup.ts` with `@testing-library/jest-dom` import. Wave D extends these.
**Est. size:** M (~150 LOC + tests).

### N-07 — Full docker-compose scaffold (api + web services) — HIGH

**Blocks:** AUD-007, AUD-008.
**Fix shape:** Session 2 A-01 currently emits postgres-only compose. Extend to emit api + web services with dev volume mounts, env bindings, `depends_on: postgres`, healthchecks. Plus turbo.json if the scaffold commits to that layout.
**Est. size:** M (~120 LOC + tests).

### N-08 — Audit-fix iteration loop — CRITICAL

**Blocks:** the "28 findings at audit, 0 fix cycles" pattern. This is the single biggest multiplier on pipeline truthfulness.
**Fix shape:** new pipeline phase `audit_fix_iteration` between `audit` and `complete`. For each CRITICAL/HIGH finding with a concrete `fix_action`, dispatch a targeted fix agent with a tight scope (the finding's `location` + `fix_action`). Re-audit. Max 3 iterations. Budget cap per iteration. Flag-gated behind `v18.audit_fix_iteration: bool = False` initially (opt-in) until calibration proves ROI.
**Est. size:** L (~300 LOC + tests + probably config work). **Risk:** MEDIUM–HIGH (spawns sub-agents, needs budget protection).

### N-09 — Wave B prompt quality uplift — MEDIUM

**Blocks:** the 8-finding Wave B LLM-bug cluster (AUD-009, -010, -012, -013, -014, -016, -018, -020).
**Fix shape:** investigation-first. Read build-l's Wave B prompt; cross-reference with the 8 bug-class findings; identify whether each is (a) prompt doesn't stress the correct pattern, (b) prompt stresses it but the model deprioritizes, (c) spec ambiguity. Then targeted prompt edits + possibly context7 lookups for NestJS 11 idioms.
**Est. size:** M (~100 LOC prompt edits + investigation notes). **Risk:** MEDIUM (prompts affect every wave).

### N-10 — Post-wave content auditor — MEDIUM

**Blocks:** future scope-drift inside scope-correct paths (see §5.4).
**Fix shape:** after Wave B/D produces `files_created` that pass A-09's path-scope check, run a content-scope check. Parse the `forbidden_content` directives from milestone REQUIREMENTS.md; scan emitted files for pattern matches (e.g., "no feature business logic" → flag files with controllers that contain business-logic method bodies). Surface as warnings on WaveResult.
**Est. size:** M (~150 LOC + tests). **Risk:** LOW (read-only scan).

### N-11 — Cascade finding suppression — LOW

**Blocks:** audit noise from "Wave X never ran" findings that cascade from a single upstream failure.
**Fix shape:** audit prompt learns about the wave execution state. When `wave_progress[milestone-1].failed_wave == "B"`, suppress findings about "Wave D output missing" / "Wave T never ran" / "Wave E artefacts missing" — consolidate into one "Upstream Wave B failed; downstream waves cascaded" meta-finding.
**Est. size:** S (~40 LOC + test). **Risk:** LOW.

### N-12 — Unified milestone spec reconciliation — MEDIUM

**Blocks:** AUD-011, AUD-017, AUD-021 port, and general spec drift.
**Fix shape:** at milestone entry, produce `.agent-team/milestones/<id>/SPEC.md` that reconciles M1 REQUIREMENTS.md + PRD excerpts into one authoritative spec. Scaffold + Wave prompts + auditor all read from this single doc. Conflicts resolved at reconciliation time (spec-reconciliation agent, deterministic where possible + LLM arbitration for ambiguous cases).
**Est. size:** L (~200 LOC + reconciliation agent). **Risk:** MEDIUM (new phase).

### N-13 — Scaffold self-verification gate — MEDIUM

**Blocks:** bad-scaffold failures that currently surface only at Wave B compile-fix.
**Fix shape:** after scaffold emission, validate `package.json` workspace globs resolve, `tsconfig.json` paths resolve, `docker-compose.yml` is valid YAML with real images, `prisma/schema.prisma` parses. Fail fast at a scaffold-gate before Wave B starts.
**Est. size:** M (~120 LOC + tests). **Risk:** LOW (read-only validation).

### N-14 — Production-caller proof for every session — LOW

**Blocks:** future latent bugs like §3.1 – §3.4 (landed mechanism, dead in production).
**Fix shape:** every session's execute file requires a "production-caller proof" artefact. Not a unit test — a small script with a mock SDK asserting the feature fires on the hot path. Bring back the Session 1 practice.
**Est. size:** XS (per-session addition). **Risk:** NONE (process change).

### N-15 — C-01 scope persistence in AUDIT_REPORT.json — MEDIUM

**Blocks:** C-01's "scope context carried forward to persisted report" promise (currently broken per §3.4).
**Fix shape:** audit the audit-persistence path. Find where the scorer writes the raw JSON. Ensure `AuditReport.scope` field is populated BEFORE persistence, OR add a post-persist scope-injection step. Unit test against build-l's actual AUDIT_REPORT.json shape.
**Est. size:** S (~40 LOC + tests). **Risk:** LOW.

### N-16 — Stock PRD alignment with M1 REQUIREMENTS.md — LOW

**Blocks:** smoke test fidelity.
**Fix shape:** curate a smoke PRD that matches M1 REQUIREMENTS.md spec exactly. Either (a) strip M2-M5 content from the existing TASKFLOW_MINI_PRD.md for M1-only smokes, or (b) create a new `M1_ONLY_SMOKE_PRD.md` for closeout-validation use.
**Est. size:** XS (document work).

---

## 7. What is missing for one-shot enterprise app generation

This is the forward-looking section. The pipeline *design* is sound — V18's wave-based parallel execution, per-milestone scope filtering, audit + recovery loops, deterministic scaffold, provider routing — all sound architecturally. The gaps between "works in theory" and "one-shots a real enterprise app" are:

### 7.1 Closed-loop verification

**Currently:** build → audit → report → done. No closed loop. The audit-fix iteration gap (§5.3, N-08) is the single largest lever.

**What enterprise-one-shot needs:** build → audit → dispatch fix agents for every high-confidence finding → re-audit → re-dispatch → converge. Budget-capped. Calibration data needed: average findings per wave, average fix success rate per finding severity, average iterations to convergence. Build-l data could drive this calibration.

### 7.2 Spec reconciliation before code generation

**Currently:** M1 REQUIREMENTS.md + PRD are consumed separately by different layers. Conflicts surface at audit time when the damage is already done.

**What enterprise-one-shot needs:** a spec reconciliation phase (N-12). Before any code is generated, produce a single authoritative spec per milestone. All layers read from one source. Conflicts get resolved once, up front, where humans can arbitrate.

### 7.3 Ownership contract for every file the audit expects

**Currently:** scaffold_runner, Wave B codegen, Wave D codegen all partially own M1 output. The audit expects the union; the union has gaps.

**What enterprise-one-shot needs:** per-file ownership table (N-02). For every file the audit can flag as "missing," an explicit owner is named. Drives scaffold completeness, Wave prompt content, and audit-expectation calibration.

### 7.4 Content-level scope enforcement (not just path-level)

**Currently:** A-09 enforces file *paths*. Wave B can still produce M2-scope *logic* inside M1-scope file paths.

**What enterprise-one-shot needs:** a post-wave content auditor (N-10) that validates emitted file contents against milestone `forbidden_content` directives. Catches scope drift at the semantic level.

### 7.5 Runtime infrastructure auto-detection

**Currently:** `endpoint_prober._detect_app_url` defaults to `:3080`. Scaffold port 3001. PRD port 4000. Three different values.

**What enterprise-one-shot needs:** single source of truth for infrastructure config, read by every consumer. Port, host, database URL, API prefix — all derived from scaffold output (N-01), never hardcoded. Extends to CORS origins, JWT audiences, etc.

### 7.6 Prompt quality baseline with idiom-verification

**Currently:** Wave B prompt is a long, hand-crafted instruction set. Model adherence is high but not perfect — 8 findings in build-l are small spec drifts.

**What enterprise-one-shot needs:** prompt that explicitly references current-framework idioms (N-09). NestJS 11 patterns via context7 integration at prompt-build time. Model references up-to-date canonical examples, not training-data approximations.

### 7.7 Observability and truthful state

**Currently:** build-l's STATE.json had `summary.success: true` with `failed_milestones: ["milestone-1"]`. Kill-side effect; but even under normal termination, Session 3's D-13 fixes inconsistencies reactively, not proactively.

**What enterprise-one-shot needs:** every state mutation validates its invariants at write time. Impossible state combinations refuse to persist. `summary.success = true` with `failed_milestones` non-empty is a crash, not a warning.

### 7.8 Budget protection at every sub-agent spawn

**Currently:** Wave B, Wave D, fix agents, recovery agents all spawn sub-agents. Budget cap exists at the pipeline level, not per sub-agent-family.

**What enterprise-one-shot needs:** per-family budget caps. If "audit-fix iteration" is allowed max $5 per milestone, the dispatcher enforces that regardless of how many findings exist. If one finding burns $3, the remaining $2 gets split across the rest. Predictable cost ceilings.

### 7.9 Codex path reliability (Bug #20)

**Currently:** Wave B + Wave D route to codex when `provider_map_*: codex`. Codex orphan-tool wedges were the original closeout blocker; PR #11 diagnostics + PR #10 claude fallback make wedges survivable but lossy (session teardown, Claude re-generates from scratch).

**What enterprise-one-shot needs:** codex app-server transport (Bug #20). Turn-level cancellation preserves the session; corrective prompt re-entry continues from previous turn's context. Reduces fallback frequency which in turn reduces compile-fix exhaustion cascade.

### 7.10 The meta-missing-piece: user-facing truthfulness

**Currently:** the pipeline reports "success: true" when M1 failed. Reports fidelity mostly runtime when the Contract Engine is absent and static analysis is used. Reports "health: skipped" when the real answer is "blocked because app isn't listening on the port I'm checking."

**What enterprise-one-shot needs:** every report the operator reads should *lead* with its confidence. "M1 cleared with runtime verification: CONFIDENT." "M1 cleared with only static analysis for endpoints: MEDIUM — consider deploying the Contract Engine MCP for higher fidelity." "M1 FAILED: Wave B could not bind to the expected port." D-14 starts this practice; needs to extend everywhere.

---

## 8. Handoff instructions for the deep-investigation session

### 8.1 Primary inputs to load

1. This document.
2. `docs/plans/2026-04-15-builder-reliability-tracker.md` — original tracker (13 sessions, 71 items). Sessions 1–5 done, 7–13 open.
3. `v18 test runs/build-l-gate-a-20260416/` — full preservation. Especially:
   - `BUILD_LOG.txt` — wave-by-wave execution trace.
   - `.agent-team/AUDIT_REPORT.json` — 28 findings.
   - `.agent-team/STATE.json` — final state at kill.
   - `GATE_A_FAIL_REPORT.md` — §8 report template.
   - `attempted-d02-d03-fixes.patch` — the Session-6 fixes that landed as PR #25.
4. `docs/plans/2026-04-15-bug-20-codex-appserver-migration.md` — for Session 11 background.
5. `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/` — full memory directory. Every feedback + project + reference entry.
6. `v18 test runs/session-0N-validation/` (N = 1..5) — validation artefacts from each closed session.
7. PR #25 diff (unmerged at handoff time) — D-02 v2 + D-03 v2 content.

### 8.2 What the deep-investigation session should produce

A next-phase plan that:

1. **Prioritizes N-items by blocker-unblocker chains.** N-01 unblocks Gate A re-smoke. N-02 unblocks ~9 scaffold-gap findings. N-08 unblocks the truthfulness of every future smoke. Map the chain.

2. **Re-scopes Sessions 7–13 in light of build-l.** Some original items may be obsolete (D-16 "post-fallback Claude output doesn't compile" may be partially resolved by A-09 scope filter; build-l didn't hit compile-fix failure). Some new items may be higher-priority than the originals.

3. **Proposes a new tracker structure.** The original 71-item / 13-session plan was designed before build-l. Post-build-l, the structure should reflect (a) closed items, (b) deferred items still valid, (c) new N-items, (d) items now obsolete. Keep it as a single tracker document.

4. **Addresses the "one-shot enterprise app" vision head-on.** §7 lists 10 missing pieces. For each, either (a) propose a tracker item that closes it, (b) declare it out-of-scope with a rationale, or (c) propose a research investigation. Don't wave-hand.

5. **Respects the memory rules.** `feedback_structural_vs_containment.md`: no containment patches. `feedback_verification_before_completion.md`: no "validated" without end-to-end proof. `feedback_inflight_fixes_need_authorization.md`: no mid-smoke code shipping without the review gate.

6. **Sizes cost/session-count realistically.** Original tracker estimated 13 sessions + $45–75 validation. Build-l burned $8.37 for ~70 minutes of real runtime. Extrapolate from real data, not pre-run estimates.

### 8.3 Known cross-reference traps

- **Session 1 C-01 scope persistence latent bug (§3.4 + N-15).** Easy to miss because unit tests and static verification both pass. Only a real run's AUDIT_REPORT.json exposes it.
- **D-13 State.finalize runs reactively, not at every mutation (§7.7).** Invariant violations can persist during the run even if final state is correct.
- **`fix_candidates` string-ID vs int-index coercion (Session 3 fix-up).** Scorer writes string IDs; permissive reader coerces. But the coercion is silent — if scorer drops a string ID, the coerced int is missing from the list. Double-check by grepping for warnings in build-l's log.
- **PR #25 pending merge.** Every reference to "D-02 v2" and "D-03 v2" in this doc assumes PR #25 lands. If PR #25 is rejected, update the relevant sections.
- **build-k was a different failure mode than build-l.** build-k = FAIL-LAUNCH (stale `.pth`). build-l = FAIL-PROBE (port mismatch). Don't conflate.
- **Stock PRD vs M1 REQUIREMENTS.md conflicts (§5.2, §5.9).** Several build-l findings trace to spec ambiguity, not pipeline bugs. Resolving this is itself a plan decision.

### 8.4 Non-goals for the deep-investigation session

- Do NOT write code.
- Do NOT run smokes.
- Do NOT merge PR #25 (reviewer gate).
- Do NOT implement any N-item during the investigation. Plan only.
- Do NOT modify memory entries (they're calibrated; new ones get added post-investigation).

---

## 9. Summary

Sessions 1–5 + Session 6 smoke fixed the builder's *machinery*. Build-l's 28 findings expose the next layer: the builder produces a coherent but imperfect app on the first try, and has no iteration primitive to converge it. The design is sound. The missing pieces are specific and enumerable (§6 N-01–N-16 and §7.1–7.10).

The deepest single insight from build-l: **the pipeline is now truthful**. Build-j would have FALSE-GREENed; build-l correctly RED-flagged the scaffold port mismatch. That's the closeout's primary deliverable — and it worked.

What's needed next is primarily:
1. **Closing the audit → fix loop (N-08).** Single biggest ROI.
2. **Fixing the three-layer ownership ambiguity (N-02).** Single biggest reducer of audit-surface bugs.
3. **Making the port prober spec-aware (N-01).** Immediate blocker to Gate A clearance.
4. **Merging PR #25.** Unblocks integration.
5. **Deep-investigation session consumes this document and produces the next plan.**

Go.

---

## Appendix A — Complete document index

Every doc the deep-investigation session might need, grouped by role. All paths relative to `C:/Projects/agent-team-v18-codex/`.

### A.1 This handoff

- `docs/plans/2026-04-16-handoff-post-gate-a-deep-investigation.md` — **this file**. Single self-contained brief.

### A.2 Master tracker (source of truth for closeout scope)

- `docs/plans/2026-04-15-builder-reliability-tracker.md` — 689 lines. 71-item / 13-session plan. §1 status table; §2–§5 Buckets A/B/C/D; §6 Tier-1 crosswalk; §7 dependency graph; §8 parallel clusters; §9 ordered session plan; §10 smoke gates; §11 open questions; §12 honest assessment.

### A.3 Per-item plan files (13 M/L/XL tracker items — tracker summary is inline; these have the full spec)

| File | Item | Status |
|---|---|---|
| `docs/plans/2026-04-15-a-06-rtl-logical-properties-baseline.md` | A-06 RTL baseline + ESLint rule | **merged** Session 2 |
| `docs/plans/2026-04-15-a-09-wave-scope-filter.md` | A-09 milestone-scoped wave prompts | **merged** Session 1 |
| `docs/plans/2026-04-15-a-10-compile-fix-budget-investigation.md` | A-10 compile-fix budget + fallback | **open** Session 7 |
| `docs/plans/2026-04-15-c-01-auditor-milestone-scope.md` | C-01 audit milestone-scoping | **merged** Session 1 (latent bug §3.4) |
| `docs/plans/2026-04-15-d-04-review-fleet-deployment.md` | D-04 review-fleet invariant | **merged** Session 4 |
| `docs/plans/2026-04-15-d-05-recovery-prompt-injection-misfire.md` | D-05 recovery role separation | **merged** Session 4 |
| `docs/plans/2026-04-15-d-08-contracts-json-in-orchestration.md` | D-08 CONTRACTS primary producer | **merged** Session 4 |
| `docs/plans/2026-04-15-d-11-wave-t-findings-unconditional.md` | D-11 Wave T skip marker | **merged** Session 4 |
| `docs/plans/2026-04-15-d-13-state-finalize-consolidator.md` | D-13 `State.finalize()` | **merged** Session 3 |
| `docs/plans/2026-04-15-d-15-compile-fix-structural-triage.md` | D-15 structural triage | **open** Session 7 |
| `docs/plans/2026-04-15-d-16-fallback-prompt-scope-quality.md` | D-16 fallback prompt quality | **open** Session 7 |
| `docs/plans/2026-04-15-d-17-truth-score-calibration.md` | D-17 truth-score calibration | **open** Session 8 |
| `docs/plans/2026-04-15-d-20-m1-startup-ac-probe.md` | D-20 startup-AC probe | **merged** Session 3 |

S-sized items (A-01/02/03/04/05/07/08, D-01/02/03/06/07/09/10/12/14/18/19) have no dedicated plan — their spec lives inline in the tracker §2 and §5.

### A.4 Session execute files (kickoff briefs, one per session — include guardrails, deviations, rationale)

| File | Session scope | PRs produced |
|---|---|---|
| `docs/plans/2026-04-15-session-01-execute-a09-c01.md` | A-09 + C-01 | PRs #13, #14 |
| `docs/plans/2026-04-16-session-02-execute-scaffold-cluster.md` | A-01/02/03/04/05/06/07/08 + D-18 | PRs #15, #16 |
| `docs/plans/2026-04-16-session-03-execute-audit-schema-state-finalize.md` | D-07 + D-13 + D-20 | PRs #17, #18 |
| `docs/plans/2026-04-16-session-04-execute-orchestration-recovery.md` | D-04 + D-05 + D-06 + D-08 + D-11 | PRs #19, #20, #21 |
| `docs/plans/2026-04-16-session-05-execute-runtime-toolchain.md` | D-02 v1 + D-03 v1 + D-09 | PRs #22, #23, #24 |
| `docs/plans/2026-04-16-session-06-gate-a-smoke.md` | Paid smoke plan (not code) | build-l run + PR #25 (D-02 v2 + D-03 v2) |

### A.5 Session validation artefacts (agent-captured evidence per session)

Every session committed static-verification outputs. Useful for understanding what the session's agent actually saw and how they reasoned.

- `v18 test runs/session-01-validation/` — A-09 grep transcript, C-01 re-scoring (28 out-of-scope → 13 scope_violation), wired-prompt dumps.
- `v18 test runs/session-02-validation/` — `a05-investigation.md` (validation pipe baseline), `a06-investigation.md` (RTL baseline), `phase1-scaffold-dump.txt` (full scaffold emission), `build_m1_scaffold.py` (the dump driver).
- `v18 test runs/session-03-validation/` — `d07-schema-divergence.md` (9 shape mismatches cataloguèd), `d07-roundtrip-transcript.txt` (build-j AUDIT_REPORT.json parses cleanly with permissive reader), `d20-integration-summary.md` (probe call-site), `roundtrip-buildj-audit.py`.
- `v18 test runs/session-04-validation/` — `d04-investigation.md` (no broken guard — add post-recovery invariant), `d05-investigation.md` (fake `[SYSTEM:]` tag was the actual injection trigger, not file content), `d08-investigation.md` (deterministic static-analysis primary producer).
- `v18 test runs/session-05-validation/` — `d09-investigation.md` (MCP server implementation `src/contract_engine/mcp_server.py` does NOT exist — Branch B labeling chosen).

### A.6 Smoke run preservations (evidence)

**Primary for deep investigation:**

- `v18 test runs/build-l-gate-a-20260416/` — the Gate A smoke result. Contents:
  - `BUILD_LOG.txt` (30 KB) — full wave-by-wave trace.
  - `.agent-team/AUDIT_REPORT.json` (26 KB) — the 28 canonical findings.
  - `.agent-team/STATE.json` — state at kill.
  - `.agent-team/MASTER_PLAN.json`, `STACK_CONTRACT.json`, `REQUIREMENTS.md`, `milestones/*`.
  - `attempted-d02-d03-fixes.patch` (39 KB, 974 lines) — the patch that became PR #25.
  - `GATE_A_FAIL_REPORT.md` — session-6 agent's §8 report.
  - `PRD.md`, `config.yaml` — inputs used.
  - `apps/`, `packages/`, `scripts/` — source trees (node_modules/.next/dist excluded).

**Pre-closeout reference runs (referenced in the handoff):**

- `v18 test runs/build-j-closeout-sonnet-20260415/` — the BASELINE run that produced the 41 findings + 14 builder defects + 77 contract violations + 6 Tier-1 blockers. This seeded the whole tracker. `FINAL_VALIDATION_REPORT.md` is the 652-line analysis.
- `v18 test runs/build-k-gate-a-20260416/` — the FAIL-LAUNCH attempt (.pth stale; $0 consumed). Documents the editable-install lesson that seeded `feedback_verify_editable_install_before_smoke.md`.

**Older historical runs (context for specific bugs referenced in memory):**

- `v18 test runs/build-e-bug12-20260414/` — PR #1 Bug #12 watchdog wraps that was misattributed as a fix (actually caught by pre-existing milestone timeout). Led to `feedback_structural_vs_containment.md`.
- `v18 test runs/build-f-pr2-validation-20260414/` — first PR #2 attempt; surfaced codex-teardown-wedge.
- `v18 test runs/build-g-pr2-phaseB-20260414/` — decisive post-fix run; watchdog fired at 1821s idle, hang report written.
- `v18 test runs/build-h-full-closeout-20260415/` — 2026-04-15 integration smoke of PRs #3–#8.
- `v18 test runs/build-i-full-closeout-retry-20260415/` — retry including PR #9; Wave B wedged twice in one run on orphan tool starts.

### A.7 Memory files (calibration + conventions)

At `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/`:

- `MEMORY.md` — index (lines after 200 truncate, keep concise).
- `feedback_structural_vs_containment.md` — 2026-04-14: don't ship timeouts/kill thresholds in place of root-cause fixes. Cites the Bug #12 series.
- `feedback_verification_before_completion.md` — 2026-04-14: unit tests alone don't validate; end-to-end smoke must fire the fix. Cites PR #1 framing error.
- `feedback_inflight_fixes_need_authorization.md` — 2026-04-16: the Session 6 build-l scope bypass. Don't edit source during smoke prep without reviewer authorization.
- `feedback_verify_editable_install_before_smoke.md` — 2026-04-16: `pip show agent-team-v15` must report the current worktree before any smoke launch.
- `project_v18_hardened_builder_state.md` — pipeline architecture + known open issues snapshot. Updated after every session.
- `reference_v18_test_artifacts.md` — smoke-run conventions (paths, slugs, preservation, stock config + PRD).

### A.8 Pre-closeout bug docs (still relevant)

- `docs/plans/2026-04-15-bug-20-codex-appserver-migration.md` — Session 11 target. Structural codex transport migration. §11 has "Findings this migration resolves" ROI list.
- `docs/plans/2026-04-15-bug-18-codex-orphan-tool-failfast.md` — **SUPERSEDED** by Bug #20. Kept for context.
- `docs/plans/2026-04-15-codex-high-milestone-budget.md` — landed as PR #4 (milestone_timeout_seconds 2700→3600).
- `docs/plans/2026-04-15-wave-b-docker-transient-retry.md` — landed as PR #9.
- `docs/plans/2026-04-14-bug-12-rootcause-postmortem.md` — the post-mortem that seeded `feedback_structural_vs_containment.md`.
- `docs/plans/2026-04-14-bug-2-fix-stranded-on-branch.md` — Bug #2 carry-forward.
- `docs/plans/2026-04-14-provider-routed-wave-watchdog-not-firing-stock-smoke.md` — stock-smoke watchdog-bypass evidence.
- `docs/plans/2026-04-14-tier2-and-fix-verification-report.md` — Tier 2 stack-contract validator (PR #3) verification.
- `docs/plans/2026-04-14-wave-t-watchdog-bypass.md` — Wave T watchdog bypass history.

### A.9 GitHub inputs (not in the filesystem)

- **PR #25** (pending merge): `session-6-fixes-d02-d03` branch. Two commits: `c1030bb` (D-02 v2) and `61dd64d` (D-03 v2). Reviewer diff approval required before merge.
- **PRs #13–#24** (merged): closeout cluster. Merge SHAs referenced in §1.1.

---

## Appendix B — Complete finding catalogue (every finding, every run, every status)

All findings surfaced in any evidence run, with closure status. Cross-indexed so the deep-investigation session doesn't need to re-derive attribution.

### B.1 build-j audit findings (41 — the ones that seeded the tracker)

From `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/AUDIT_REPORT.json`. Status column: what the tracker / completed sessions did with each.

#### B.1.1 CRITICAL (7)

| ID | Title | File | Status |
|---|---|---|---|
| F-001 | api-client Content-Type clobber on authed POST/PATCH | `packages/api-client/index.ts:24` | **DEFERRED to M2 Wave C** (over-build — file shouldn't have content at M1) |
| F-002 | Task Detail page route + component missing | `apps/web/src/app` | **DEFERRED to M4** (feature scope) |
| F-003 | Team Members page route + component missing | `apps/web/src/app` | **DEFERRED to M5** |
| F-004 | User Profile page route + component missing | `apps/web/src/app` | **DEFERRED to M5** |
| F-005 | 9 api-client functions not re-exported | `apps/web/src/lib/api-client.ts` | **DEFERRED to M2 Wave C** |
| F-006 | Comments section missing from Task Detail | `apps/web/src/components` | **DEFERRED to M5** |
| F-007 | `docker-compose.yml` missing | project root | **CLOSED** — Session 2 A-01 merged |

#### B.1.2 HIGH (13)

| ID | Title | File | Status |
|---|---|---|---|
| F-008 | No protected-route layout | `apps/web/src/app/[locale]/projects/page.tsx` | **DEFERRED to M2** |
| F-009 | Pagination query params missing on list endpoints | `packages/api-client/index.ts:115` | **DEFERRED to M3** |
| F-010 | Kanban board view missing | `apps/web/src/components/projects/project-detail-page.tsx:357` | **DEFERRED to M4** |
| F-011 | Project edit/delete UI missing | `apps/web/src/components/projects/project-detail-page.tsx:249` | **DEFERRED to M3** |
| F-012 | Auth route `/auth` vs required `/login` | `apps/web/src/app/[locale]/auth/page.tsx` | **DEFERRED to M2** |
| F-013 | i18n namespaces missing (tasks/comments/team/nav) | `apps/web/messages/en.json` | **DEFERRED** — M1 spec says messages files start empty; populated per milestone |
| F-014 | No redirect after login | `apps/web/src/components/auth/auth-page.tsx:58` | **DEFERRED to M2** |
| F-015 | No react-hook-form / zod on forms | `apps/web/src/components/auth/auth-page.tsx:42` | **DEFERRED to M2+** |
| F-016 | Language switcher missing | `apps/web/src/components/layout/app-shell.tsx:18` | **DEFERRED to M6** |
| F-017 | Task status: forward-only transitions | `apps/web/src/components/projects/project-detail-page.tsx:45` | **DEFERRED to M4** |
| F-018 | UserResponseDto camelCase inconsistency | `apps/api/src/auth/dto/user-response.dto.ts:23` | **DEFERRED to M2** |
| F-019 | M1 scope violation (meta-finding) | `apps/api/src` | **CLOSED** — structural fix is A-09 (Session 1 merged) |
| F-020 | GET `/api/auth/me` with body param | `packages/api-client/index.ts:69` | **DEFERRED to M2** |

#### B.1.3 MEDIUM (16)

| ID | Title | File | Status |
|---|---|---|---|
| F-021 | Inline form vs create-project modal | `apps/web/src/components/projects/projects-page.tsx:232` | **DEFERRED to M3** |
| F-022 | Projects table missing Owner col + sort | `apps/web/src/components/projects/projects-page.tsx:174` | **DEFERRED to M3** |
| F-023 | Backend port default 8080 vs required 3001 | `apps/api/src/config/env.validation.ts:5` | **CLOSED** — Session 2 A-02 merged |
| F-024 | Sidebar missing Team link | `apps/web/src/components/layout/app-shell.tsx:18` | **DEFERRED to M5** |
| F-025 | Extended ProjectDetailDto missing | `apps/web/src/components/projects/project-detail-page.tsx:140` | **DEFERRED to M3** |
| F-026 | i18n includes unexpected `id` locale | `apps/web/src/i18n.ts:1` | **CLOSED** — Session 2 A-04 merged |
| F-027 | RTL uses physical CSS properties | `apps/web/src/components/layout/app-shell.tsx:46` | **CLOSED** — Session 2 A-06 (Branch A: baseline correct, ESLint rule added) |
| F-028 | Prisma enum casing + `@map` conventions | `apps/api/prisma/schema.prisma:20` | **DEFERRED to M2** |
| F-029 | `due_date` ISO string serialization fragile | `apps/web/src/components/projects/project-detail-page.tsx:186` | **DEFERRED to M4** |
| F-030 | Evidence ledger + Wave T summary + E2E tests missing | `.agent-team/milestones/milestone-1/WAVE_FINDINGS.json` | **CLOSED** — Session 4 D-11 (unconditional WAVE_FINDINGS.json write) |
| F-031 | JWT in localStorage vs HttpOnly cookie | `apps/web/src/components/providers/auth-provider.tsx:66` | **DEFERRED to M2** |
| F-032 | No CSRF middleware | `apps/api/src/main.ts:12` | **DEFERRED to M2** |
| F-033 | PrismaService deprecated `$on('beforeExit')` | `apps/api/src/prisma/prisma.service.ts:25` | **CLOSED** — Session 2 A-03 merged |
| F-034 | Frontend projects page no pagination controls | `apps/web/src/components/projects/projects-page.tsx:57` | **DEFERRED to M3** |
| F-035 | Validation pipe snake_case normalization | `apps/api/src/common/pipes/validation.pipe.ts:19` | **PARTIALLY CLOSED** — Session 2 A-05 scaffold-layer clean baseline; DTO/contract reconciliation deferred to Session 3+ (CV-02/CV-03) |
| F-036 | Milestone-1 status FAILED in STATE.json | `.agent-team/STATE.json:78` | **CLOSED** — Session 3 D-13 (State.finalize) |

#### B.1.4 LOW (4)

| ID | Title | File | Status |
|---|---|---|---|
| F-037 | No rate limiting on auth endpoints | `apps/api/src/main.ts:21` | **DEFERRED to M2** |
| F-038 | No token refresh / 401 interceptor | `apps/web/src/components/providers/auth-provider.tsx:105` | **DEFERRED to M2** |
| F-039 | `User.password` exposed in API client types | `packages/api-client/types.ts:51` | **DEFERRED to M2** |
| F-040 | No root 404 route | `apps/web/src/app` | **DEFERRED to M6 polish** |

#### B.1.5 INFO (1)

| ID | Title | File | Status |
|---|---|---|---|
| F-041 | `accessToken` vs `access_token` field mismatch | `packages/api-client/index.ts:58` | **DEFERRED to M2** |

**build-j F-xxx summary:** 41 total → 7 CLOSED by completed sessions + 33 DEFERRED to M2–M6 + 1 partially closed (F-035). Per tracker §12: once M2+ milestones actually execute, the deferred items either get fixed or re-surface as actionable at that milestone's audit.

### B.2 build-j builder defects (B-001 through B-014) → tracker D-xx mapping

From `build-j/FINAL_VALIDATION_REPORT.md` §5. Each mapped to its tracker replacement + closure status.

| Build-j B-ID | Title | Tracker item | Status |
|---|---|---|---|
| B-001 | Context7 quota exhaustion degraded research | D-01 | **OPEN** Session 9 |
| B-002 | Runtime verification couldn't run (no compose, no live app) | D-02 | **CLOSED** (v1 Session 5 + v2 PR #25 pending) |
| B-003 | OpenAPI launcher `WinError 2` on Windows | D-03 | **CLOSED** (v1 Session 5 + v2 PR #25 pending) |
| B-004 | Review fleet never deployed | D-04 | **CLOSED** Session 4 |
| B-005 | Review recovery misfired into prompt-injection handling | D-05 | **CLOSED** Session 4 |
| B-006 | Recovery taxonomy `"Unknown recovery type"` for `debug_fleet` | D-06 | **CLOSED** Session 4 (8 additional hints added beyond debug_fleet — structural fix) |
| B-007 | Audit producer/consumer `audit_id` schema mismatch | D-07 | **CLOSED** Session 3 (+ fix-up for fix_candidates coercion) |
| B-008 | CONTRACTS.json in recovery pass, not orchestration | D-08 | **CLOSED** Session 4 |
| B-009 | Contract Engine `validate_endpoint` MCP tool missing | D-09 | **PARTIAL** Session 5 — helpers landed, production wiring deferred (§3.2) |
| B-010 | Phantom integrity finding (DB-004) across fix cycles | D-10 | **OPEN** Session 9 |
| B-011 | `WAVE_FINDINGS.json` empty despite Wave T running | D-11 / F-030 | **CLOSED** Session 4 |
| B-012 | Telemetry `last_sdk_tool_name` blank in wave telemetry | D-12 | **OPEN** Session 8 (obsoleted for codex path by Bug #20 Session 11) |
| B-013 | STATE.json ends internally inconsistent | D-13 / F-036 | **CLOSED** Session 3 (reactive, not proactive — see §7.7) |
| B-014 | Verification artifacts static + heuristic unlabeled | D-14 | **OPEN** Session 8 |

**build-j B-xxx summary:** 14 total → 9 CLOSED + 1 partially closed (D-09) + 4 OPEN (D-01, D-10, D-12, D-14 — all Session 8/9 scope).

### B.3 build-j contract violations (7 root causes, 77 leaves)

From `build-j/.agent-team/CONTRACT_E2E_RESULTS.md`. 77 endpoint violations rolled up to 7 structural root causes. All currently DEFERRED to M2+ (endpoints don't exist at M1).

| CV-ID | Root cause | Leaves | Affected endpoints | Status |
|---|---|---|---|---|
| CV-01 | ENUM-CASE: Prisma enums lowercase vs contract UPPER_SNAKE_CASE | 20 | all 20 endpoints | **DEFERRED to M2** (`schema.prisma` + mapper) |
| CV-02 | FIELD-NAMING: `assignee_id` snake_case vs contract `assigneeId` | 4 | Task endpoints | **DEFERRED to M4** |
| CV-03 | MISSING-FIELD: flat scalars omitted (`ownerName`, `assigneeName`, `authorId`, `authorName`, `taskId`, `createdAt`, `updatedAt` on Comment) | 16 | M2–M5 endpoints | **DEFERRED to M2–M5** |
| CV-04 | EXTRA-FIELD: unrequested fields (`taskCounts`, `reporter`, `deletedAt`, `openTaskCount`, `tasks[]`, `avatar_url`) | 19 | M2–M5 endpoints | **DEFERRED to M2–M5** |
| CV-05 | SHAPE-MISMATCH: nested owner/assignee object vs contract flat scalar | 5 | M3–M4 endpoints | **DEFERRED to M3–M4** |
| CV-06 | WRONG-RESPONSE-BODY: DELETE returns entity instead of `{ data: null }` | 3 | DELETE endpoints | **DEFERRED to M3–M5** |
| CV-07 | WRONG-RESPONSE-TYPE: PATCH `/users/:id` returns `UserResponseDto` not `UserSummaryDto` | 1 | M5 endpoint | **DEFERRED to M5** |

**build-j CV-xx summary:** 77 violations → 7 root causes → ALL DEFERRED. When M2+ runs, these must be addressed at code-gen time. Session 2 A-05's investigation note flagged CV-02/CV-03 as Session-3+ follow-up; with Gate A redirected, this is now N-04 / downstream work.

### B.4 build-j Tier-1 M1 blockers (T1-01 through T1-06)

From `build-j/FINAL_VALIDATION_REPORT.md` §10. All mapped to tracker items.

| T1-ID | Blocker | Tracker mapping | Status |
|---|---|---|---|
| T1-01 | Generated project materially incomplete (docker-compose, pages, api-client) | A-01 + A-09 + C-01 + Bucket B items | **CLOSED** (Sessions 1+2) |
| T1-02 | Wave D post-fallback compile-fix exhausted 3 attempts | A-10 + D-15 + D-16 | **OPEN** Session 7 |
| T1-03 | OpenAPI launcher `WinError 2` | D-03 | **CLOSED** Session 5 (+ v2 in PR #25) |
| T1-04 | Audit producer/consumer `audit_id` schema mismatch | D-07 | **CLOSED** Session 3 |
| T1-05 | Contract Engine `validate_endpoint` MCP tool missing | D-09 | **PARTIAL** Session 5 (helpers landed, wiring deferred) |
| T1-06 | CONTRACTS.json in recovery, not orchestration | D-08 | **CLOSED** Session 4 |

**build-j T1-xx summary:** 6 total → 4 CLOSED + 1 PARTIAL (T1-05 needs wiring) + 1 OPEN (T1-02 Session 7 compile-fix investigation).

### B.5 build-l audit findings (AUD-001 through AUD-028)

Detailed in §4.2 of this document. Cross-referenced to N-items here for traceability.

| AUD-ID | Severity | Root-cause class | Resolution N-item |
|---|---|---|---|
| AUD-001 | CRITICAL | Scaffold gap — `packages/` directory | **N-03** (packages/shared scaffold emission) |
| AUD-002 | CRITICAL | Cascade (Wave D didn't run) | Resolved by N-01 unblocking Wave B |
| AUD-003 | HIGH | Cascade (Wave D didn't run) | Resolved by N-01 |
| AUD-004 | HIGH | Cascade (Wave D didn't run) | Resolved by N-01 |
| AUD-005 | CRITICAL | Scaffold gap — Prisma migrations | **N-05** (Prisma initial migration scaffold) |
| AUD-006 | HIGH | Scaffold gap — per-app `.env.example` | **N-02** (ownership contract) / **N-06** (web scaffold) |
| AUD-007 | HIGH | Scaffold gap — docker-compose web service | **N-07** (full docker-compose scaffold) |
| AUD-008 | HIGH | Scaffold gap — docker-compose api service | **N-07** |
| AUD-009 | HIGH | Wave B LLM bug — duplicate filter registration | **N-09** (Wave B prompt quality) / **N-08** (audit-fix loop) |
| AUD-010 | HIGH | Wave B spec drift — `getOrThrow` vs `.get` | **N-09** / **N-08** |
| AUD-011 | HIGH | Spec conflict — PrismaModule location | **N-04** (Prisma location reconciliation) / **N-12** (unified SPEC.md) |
| AUD-012 | HIGH | Wave B spec drift — bcrypt dep vs M1 scope | **N-09** + audit-spec reconciliation (**N-12**) |
| AUD-013 | MEDIUM | Wave B LLM quality — bare string literals | **N-09** / **N-08** |
| AUD-014 | MEDIUM | Workspace ownership — PaginatedResult location | **N-03** (packages/shared) |
| AUD-015 | LOW | Scaffold incompleteness — JWT_EXPIRES_IN validation | **N-02** (ownership) + scaffold extension |
| AUD-016 | MEDIUM | Wave B LLM quality — Swagger typing | **N-09** / **N-08** |
| AUD-017 | MEDIUM | Spec drift — Joi defaults vs `.required()` | **N-12** (unified SPEC.md reconciliation) |
| AUD-018 | MEDIUM | Wave B LLM bug — generate-openapi globals | **N-09** / **N-08** |
| AUD-019 | MEDIUM | Dockerfile ownership unclear | **N-02** (ownership contract) |
| AUD-020 | HIGH | Wave B LLM bug — TransformResponseInterceptor skip logic | **N-09** / **N-08** |
| AUD-021 | CRITICAL | Primary infra — port mismatch | **N-01** (endpoint_prober port resolution) — **Gate A blocker** |
| AUD-022 | HIGH | Scaffold gap — vitest setup file | **N-06** (web scaffold completeness) |
| AUD-023 | MEDIUM | Wave B LLM quality — e2e test uses mock | **N-09** / **N-08** |
| AUD-024 | LOW | Scaffold gap — `.editorconfig` / `.nvmrc` | **N-02** (ownership) |
| AUD-025 | LOW | Scaffold gap — `turbo.json` task deps | **N-02** (ownership) |
| AUD-026 | HIGH | Cascade (Wave T didn't run) | Resolved by N-01 |
| AUD-027 | MEDIUM | Scaffold gap — prisma ergonomics scripts | **N-02** (ownership) |
| AUD-028 | CRITICAL | Meta-finding — M1 DoD unachievable | Resolved by stack: N-01 + N-02 + N-03 + N-05 + N-06 + N-07 |

**build-l AUD-xxx summary:** 28 total → 5 cascade (resolved by N-01 unblocking) + 9 scaffold gaps (N-02/03/05/06/07) + 8 Wave B LLM bugs (N-08/N-09) + 1 primary infra (N-01) + 2 spec conflicts (N-04/N-12) + 1 ownership question (N-02) + 1 Dockerfile ownership (N-02) + 1 meta. Actionable-distinct: ~17 after taxonomy collapse.

### B.6 Still-OPEN findings — consolidated punch list

Everything NOT closed by the merged sessions (1–5), organized by expected closure:

#### B.6.1 Gate A blocker (must close before build-m re-smoke)

- **N-01** — `endpoint_prober._detect_app_url` port resolution. Single Gate A blocker. S-sized.

#### B.6.2 PR #25 (D-02 v2 + D-03 v2) pending reviewer merge

- D-02 v2 structural `infra_missing` flag (validated in build-l as correct — blocks instead of silent skip).
- D-03 v2 workspace-walk local-bin resolution (un-exercised in build-l, unit-tested).

#### B.6.3 Latent wiring bugs (§3 of this handoff)

- **§3.1** — D-02 v2 consumer-side fail-loud upgrade. Currently relies on `cli.py:12759` generic pattern.
- **§3.2** — D-09 MCP pre-flight helpers defined but un-wired in production.
- **§3.3** — D-14 verification-artefact fidelity labels (Session 8 item; generalizes D-09 pattern).
- **§3.4 / N-15** — C-01 `AuditReport.scope` field not populated in persisted AUDIT_REPORT.json.

#### B.6.4 Deferred tracker sessions (Sessions 7–13 from original tracker)

- **Session 7** — A-10, D-15, D-16 (compile-fix / fallback, HIGH risk, investigation-first).
- **Session 8** — D-12, D-14, D-17 (hygiene + calibration).
- **Session 9** — D-01, D-10 (context7 quota + phantom FP).
- **Session 10** — optional validation smoke.
- **Session 11** — Bug #20 codex app-server migration.
- **Session 12** — full-pipeline Gate D smoke.
- **Session 13** — master merge.

#### B.6.5 New tracker items from build-l (N-01 through N-16)

- **N-01** CRITICAL — port resolution (Gate A blocker).
- **N-02** HIGH — three-layer ownership contract.
- **N-03** HIGH — `packages/shared` scaffold emission.
- **N-04** HIGH — Prisma module location spec reconciliation.
- **N-05** HIGH — Prisma initial migration scaffold.
- **N-06** HIGH — web scaffold completeness.
- **N-07** HIGH — docker-compose full scaffold (api + web services).
- **N-08** CRITICAL — audit-fix iteration loop (biggest single truthfulness multiplier).
- **N-09** MEDIUM — Wave B prompt quality uplift.
- **N-10** MEDIUM — post-wave content auditor.
- **N-11** LOW — cascade finding suppression.
- **N-12** MEDIUM — unified milestone SPEC.md reconciliation.
- **N-13** MEDIUM — scaffold self-verification gate.
- **N-14** LOW — production-caller proof per session (process).
- **N-15** MEDIUM — C-01 scope persistence in AUDIT_REPORT.json.
- **N-16** LOW — stock PRD alignment with M1 REQUIREMENTS.md.

#### B.6.6 Deferred to later milestones (M2–M6) — not M1 work

From build-j F-xxx list (B.1 above):

- **M2 scope (14 findings):** F-001, F-005, F-008, F-012, F-014, F-015, F-018, F-020, F-028, F-031, F-032, F-037, F-038, F-039, F-041.
- **M3 scope (6 findings):** F-009, F-011, F-021, F-022, F-025, F-034.
- **M4 scope (4 findings):** F-002, F-010, F-017, F-029.
- **M5 scope (4 findings):** F-003, F-004, F-006, F-024.
- **M6 polish (3 findings):** F-013, F-016, F-040.
- **Contract root causes (7 → 77 leaves):** CV-01 through CV-07, all M2+.

These re-surface when their respective milestones execute. Tracker's Bucket B status.

---

### B.7 Grand total by status

| Bucket | Count | Notes |
|---|---|---|
| CLOSED (Sessions 1–5 merged) | ~25 items | A-01/02/03/04/06/07/08/09 + C-01 + D-03/04/05/06/07/08/11/13/18/20 + F-019/023/026/027/030/033/036 — plus Session 2 A-05 partially + Session 3 D-07 fix-up |
| PENDING PR #25 | 2 items | D-02 v2 + D-03 v2 |
| PARTIAL / wiring pending | 4 items | §3.1 / §3.2 / §3.3 / §3.4 (= N-15) |
| OPEN tracker (Sessions 7–13) | ~7 items | D-01, D-10, D-12, D-14, D-17, A-10, D-15, D-16 (Session 7 trio) |
| NEW from build-l (N-01 through N-16) | 16 items | N-01 critical + 15 others ranging HIGH to LOW |
| DEFERRED to M2–M6 | 33 items | F-xxx Bucket B |
| DEFERRED contract root causes | 7 items | CV-01 through CV-07 |

**Actionable for near-term Gate A re-smoke:** N-01 + PR #25 merge = ~2 code changes. That's the minimum to clear the Gate A blocker.

**Actionable for M1-audit-clearance at ≤5 findings:** N-01 + N-02 + N-03 + N-05 + N-06 + N-07 + N-08 + N-12 + N-15 + PR #25 + §3.1/3.2 wiring. That's ~10 items, spread across 3–5 sessions.

**Actionable for full Tiers 1+2+3 closure:** all of the above + Sessions 7–13. ~20 items, 8–10 sessions.

---

## Appendix C — File-by-file "what to read when" guide for the deep-investigation session

Quick reference for the investigator. If you're thinking about X, read Y first.

- **"What's the current state of the closeout?"** → §1 + `docs/plans/2026-04-15-builder-reliability-tracker.md` §1.
- **"What did each session actually ship?"** → A.4 session execute files + the merge SHAs in §1.1 + `git log` on integration.
- **"Why is build-l's fail a win, not a regression?"** → §5 + §4.4 + build-l `GATE_A_FAIL_REPORT.md`.
- **"What are the latent bugs?"** → §3 (four specific wiring gaps) + B.6.3.
- **"What's killing the pipeline structurally?"** → §5 (nine root-cause sub-sections).
- **"What's missing for one-shot enterprise app generation?"** → §7 (ten gaps).
- **"What should the next plan include?"** → §6 (16 new items) + §8.2 (what the investigation session produces).
- **"What was true at each milestone of the journey?"** — read in order: build-j FINAL_VALIDATION_REPORT.md → tracker → session-01..05 validation notes → build-l GATE_A_FAIL_REPORT.md → this handoff.
- **"What are the memory calibrations I must respect?"** → A.7 memory files, especially the four `feedback_*` entries.
- **"What's the ROI of Bug #20 vs everything else?"** → `2026-04-15-bug-20-codex-appserver-migration.md` §11 (Findings this migration resolves) + §2.5 of this handoff.

---

## Appendix D — Change log of this handoff

- **v1** 2026-04-16 — initial handoff (§0–9, ~586 lines).
- **v2** 2026-04-16 — appended Appendix A (complete document index), Appendix B (complete finding catalogue — F-xxx, B-xxx, CV-xx, T1-xx, AUD-xxx, with closure status), Appendix C (file-by-file reading guide), Appendix D (this changelog). Deep-investigation inputs now fully self-contained.
