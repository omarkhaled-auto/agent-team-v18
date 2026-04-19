# V18 Builder Reliability Tracker — 2026-04-15

**Owner:** Integration / Builder reliability  
**Source:** `v18 test runs/build-j-closeout-sonnet-20260415/FINAL_VALIDATION_REPORT.md` + `AUDIT_REPORT.json` (41 findings) + `CONTRACT_E2E_RESULTS.md` (77 violations) + §10 Tier-1 blocker list.  
**Integration branch:** `integration-2026-04-15-closeout` @ `98cba17` (PRs #3–#12 open against master @ `89f460b`).  
**Scope of this tracker:** Every finding classified into exactly one bucket (A/B/C/D), sized, dependency-graphed, and ordered into an executable session plan. No code changes in this session.

> **Triage ground-truth:** M1's REQUIREMENTS.md explicitly says **"No feature business logic in this milestone"**, lists no `AC-*` refs (only file-path merge surfaces), and defines 7 narrow startup-check ACs (npm install, docker-compose up, `dev:api` on 3001, `dev:web` on 3000, `prisma migrate dev`, empty `jest`, empty `vitest`). Most of the 41 audit findings flag M2–M5 code the builder erroneously produced during M1 execution. The correct remediation is mostly **not** to fix the generated code — it's to (a) stop the builder from over-building outside-milestone content, and (b) scope the auditor to the current milestone.

---

## 1. Status at a glance

| Metric | Value |
|---|---|
| Total items classified | **71** |
| Bucket A — Actionable M1 bugs | **10** |
| Bucket B — Deferred to M2+ | **40** (33 audit findings + 7 contract root-causes) |
| Bucket C — Auditor-scope bugs | **1** |
| Bucket D — Builder defects | **20** |
| Tier-1 M1-blockers (§10 + §4) | **6** (all map onto Bucket A/D) |
| Estimated total PRs | **~22** |
| Estimated total sessions | **13** (inclusive of smoke gates) |
| Items resolved by Bug #20 | **2** (materially) + **3** (indirectly) |

| Bucket | CRITICAL | HIGH | MEDIUM | LOW | INFO |
|---|---|---|---|---|---|
| A | 1 | 1 | 6 | 2 | 0 |
| B | 6 | 12 | 12 | 3 | 1 |
| C | — | 1 | — | — | — |
| D | — | 7 | 9 | 4 | — |

| Risk | Count |
|---|---|
| HIGH | 3 |
| MEDIUM | 9 |
| LOW | 19 |

---

## 2. Bucket A — Actionable M1 bugs (10)

### A-01 — docker-compose.yml missing at project root
- **Source:** F-007 (CRITICAL, infrastructure)
- **Evidence:** `build-j/docker-compose.yml` (absent); `FINAL_VALIDATION_REPORT.md` §4.1 ("no compose file was found under C:\smoke\clean"); `RUNTIME_VERIFICATION.md` "No docker-compose file found — runtime verification skipped"
- **Root cause:** Wave B (backend) was responsible for emitting `docker-compose.yml` but did not. Not in scaffold_runner's deterministic output set — only in wave-prompt instructions.
- **Fix shape:** Add `docker-compose.yml` to deterministic scaffold output (`scaffold_runner.py`'s backend scaffold section). Template: PostgreSQL service, port 5432, named volume, healthcheck.
- **Test shape:** Integration test that runs `run_scaffolding` against a fresh temp dir for a NestJS milestone, asserts `docker-compose.yml` exists with a `services.postgres` block with expected port + healthcheck keys.
- **PRs:** 1. **LOC:** S (~40). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** A-02, A-03, A-04, A-07, A-08.
- **Bug #20 overlap:** None.

### A-02 — Backend default port is 8080, must be 3001
- **Source:** F-023 (MEDIUM, wiring; flagged 3× by auditors)
- **Evidence:** `apps/api/src/config/env.validation.ts:5` (`PORT` default 8080); M1 REQUIREMENTS.md explicit AC "`npm run dev:api` starts NestJS on port 3001"
- **Root cause:** Wave B prompt doesn't pin `PORT=3001` default, and ConfigModule template defaults to 8080.
- **Fix shape:** Update Wave B backend prompt + `scaffold_runner._scaffold_nestjs` to emit env validation with `PORT: Joi.number().default(3001)` (or equivalent zod/ConfigModule). Also set `.env.example` `PORT=3001`.
- **Test shape:** Static-analysis test that loads the scaffolded `env.validation.ts`, parses the default, asserts 3001.
- **PRs:** 1. **LOC:** S (~20). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** A-01, A-03, A-04, A-07, A-08.
- **Bug #20 overlap:** None.

### A-03 — PrismaService uses deprecated `beforeExit` shutdown hook
- **Source:** F-033 (MEDIUM, wiring)
- **Evidence:** `apps/api/src/prisma/prisma.service.ts:25`
- **Root cause:** Template uses the legacy `this.$on('beforeExit', ...)` pattern that Prisma 5+ deprecated; current idiom is `enableShutdownHooks(app: INestApplication) { process.on('beforeExit', ...) }` on the app lifecycle side, or the new library hook in Prisma 5.
- **Fix shape:** Update Wave B PrismaService template to the current Prisma 5 pattern (application-lifecycle shutdown hook in `main.ts`, not `$on('beforeExit')` on PrismaService).
- **Test shape:** Static-analysis test that scans the emitted `prisma.service.ts` for the deprecated `$on('beforeExit'` pattern and asserts absence.
- **PRs:** 1. **LOC:** S (~15). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** A-01, A-02, A-04, A-07, A-08.
- **Bug #20 overlap:** None.

### A-04 — i18n config includes unexpected `id` locale
- **Source:** F-026 (MEDIUM, prd_compliance; flagged 2×)
- **Evidence:** `apps/web/src/i18n.ts:1` includes `'id'` (Indonesian); M1 spec says only `en`, `ar`
- **Root cause:** Wave D frontend prompt or scaffold default includes `'id'` in the locale array — possibly a mis-templated default from an earlier product pattern.
- **Fix shape:** Update Wave D frontend prompt + `_scaffold_i18n` template to use `['en', 'ar']` only, driven from the milestone locale list in `ir.i18n`.
- **Test shape:** Static-analysis test against emitted `i18n.ts` — assert exact locale array matches milestone spec.
- **PRs:** 1. **LOC:** S (~10). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** A-01, A-02, A-03, A-07, A-08.
- **Bug #20 overlap:** None.

### A-05 — Validation pipe converts all input keys to snake_case before validation
- **Source:** F-035 (MEDIUM, wiring)
- **Evidence:** `apps/api/src/common/pipes/validation.pipe.ts:19` — `normalizeInput()` converts camelCase→snake_case unconditionally
- **Root cause:** Undocumented normalization that breaks camelCase DTO validation. Likely an over-generalized "handle clients sending either case" template that doesn't match the contract (which uses camelCase for request bodies, per `CONTRACT_E2E_RESULTS.md`).
- **Fix shape:** **INVESTIGATE** first. If intentional for snake_case ingestion: document it. If not: remove the normalization, have DTOs use camelCase directly, let class-transformer handle mapping.
- **Test shape:** Integration test against a real camelCase payload — assert it reaches the controller unchanged and passes class-validator.
- **PRs:** 1. **LOC:** S (~30). **Risk:** MEDIUM (touches every incoming HTTP request).
- **Dependencies:** None.
- **Parallelizable with:** A-01, A-02, A-03, A-04.
- **Bug #20 overlap:** None.

### A-06 — RTL baseline: physical CSS properties instead of logical properties
- **Source:** F-027 (MEDIUM, wiring); related: G-07 "off-grid spacing values"
- **Evidence:** `apps/web/src/components/layout/app-shell.tsx:46` (px-*/py-* usage); M1 spec: "All CSS spacing/layout must use CSS logical properties from the start — this is enforced at the globals.css level"
- **Root cause:** **INVESTIGATE.** The flagged file (`app-shell.tsx`) is M3+ scope that shouldn't exist in M1 — but the M1 baseline itself may also have been wrong if Wave D produced the app-shell. Need to verify whether `globals.css` + `tailwind.config.ts` actually enforce logical properties or just document them.
- **Fix shape:** Ensure `globals.css` + `tailwind.config.ts` templates ship with logical-property utilities + a lint rule (or pre-commit check) that blocks physical `px-*`/`py-*` in committed code.
- **Test shape:** Static-analysis test that scans scaffolded CSS/tailwind config for logical-property baseline; plus a lint rule configured in the tailwind/prettier setup.
- **PRs:** 1. **LOC:** M (~60). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** A-01..A-05, A-07, A-08.
- **Bug #20 overlap:** None.

### A-07 — Vitest not installed/runnable in scaffolded frontend
- **Source:** §8 gate finding "`'vitest' is not recognized as an internal or external command`"
- **Evidence:** `FINAL_VALIDATION_REPORT.md` §8 item 4
- **Root cause:** Generated `apps/web/package.json` is missing `vitest` (or `@testing-library/react`) in `devDependencies`, OR the scaffold doesn't include `npm install` during scaffold verification. M1 spec explicitly requires `npm run test:web` to pass with empty suite.
- **Fix shape:** Update Wave D scaffold template `package.json` devDeps to include `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`. Add scaffold post-install step that verifies `npx vitest --version` succeeds.
- **Test shape:** Scaffold integration test that runs `npm install` + `npx vitest --version` against the scaffolded tree.
- **PRs:** 1. **LOC:** S (~25). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** A-01..A-06, A-08.
- **Bug #20 overlap:** None.

### A-08 — `.env` present in scaffold + missing from `.gitignore`; no `.gitignore` at root
- **Source:** §8 gate findings 5 (`.env` not in `.gitignore`) + 6 ("missing `.gitignore`")
- **Evidence:** `GATE_FINDINGS.json`; security scan
- **Root cause:** Scaffold does not emit a root-level `.gitignore`. `.env.example` is correct, but committed `.env` (if present) leaks.
- **Fix shape:** Add `.gitignore` to scaffold deterministic output: `node_modules/`, `.next/`, `dist/`, `.env`, `.env.local`, `coverage/`, `.turbo/`, `apps/*/node_modules/`, `apps/*/dist/`. Remove any committed `.env` from the scaffolded tree; only `.env.example` stays.
- **Test shape:** Scaffold integration test that asserts `.gitignore` exists at root and contains `.env` + `node_modules`; asserts no `.env` file is emitted.
- **PRs:** 1. **LOC:** S (~20). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** A-01..A-07.
- **Bug #20 overlap:** None.

### A-09 — Wave D (and Wave B) over-build M2–M5 features during M1 execution
- **Source:** F-019 (HIGH, prd_compliance) — audit flagged it; underlying root-cause is a builder defect (filed here as the actionable half)
- **Evidence:** `apps/api/src` contains full projects/tasks/comments/users modules in M1's output; `apps/web/src/app/[locale]/projects/` contains project detail pages; `prisma/schema.prisma` has all four entities. M1 REQUIREMENTS.md says "JWT module is wired but has no strategies — strategies are added in M2" and "entity models added per-milestone."
- **Root cause:** Wave B and Wave D prompts are keyed off the full PRD, not the current milestone's narrow spec. `wave_executor.py` passes full-PRD context instead of milestone-filtered context.
- **Fix shape:** In `wave_executor.py` wave prompt construction, filter `ir` / `feature_refs` / `ac_refs` to the current milestone. For M1 (infrastructure) waves, pass the restricted REQUIREMENTS.md section — no Project/Task/Comment/User entities, no feature pages. Add a post-wave validator that flags files outside the `Files to Create` list.
- **Test shape:** Unit test on prompt construction — assert M1 wave prompt does NOT contain M2–M5 feature names (Project, Task, Comment, User), entity references, or out-of-scope acceptance criteria.
- **PRs:** 2 (prompt filter + post-wave out-of-scope validator). **LOC:** L (~350). **Risk:** MEDIUM (touches wave prompt core).
- **Dependencies:** None (but upstream of virtually every Bucket B finding).
- **Parallelizable with:** A-01..A-08 (but not C-01 — same layer).
- **Bug #20 overlap:** None directly, but resolving A-09 dramatically reduces the codex-path workload in M1, which reduces orphan-tool-wedge exposure.

### A-10 — Wave D compile-fix budget exhausts at 3 attempts; fallback produces code that doesn't compile
- **Source:** §4.2 quoted failure "Compile failed after 3 attempt(s)" at `wave_executor.py:2779/3195`; §10 item 2
- **Evidence:** `milestone-1-wave-D.json` `compile_iterations: 3`, `compile_passed: false`, `error: "Compile failed after 3 attempt(s)"`; fallback produced 47 files via Claude but still didn't stabilize
- **Root cause:** **INVESTIGATE.** Two candidate causes: (1) 3 iterations is too few when the model has to triage a large file tree from scratch after fallback; (2) the compile-fix prompt is too narrow (errors-in → diff-out) when the real issue is structural (e.g., missing dependencies, misconfigured paths) and iteration N can't see prior fixes' side effects. Need to read `compile_profiles.py` and the compile-fix prompt to confirm.
- **Fix shape:** After investigation, most likely: (a) bump iteration budget to 5 for post-fallback waves, (b) change compile-fix prompt to include a "structural review" step that looks at `package.json` + `tsconfig` before attempting to diff individual files, (c) on final failure, persist the last compile error set so operators can see what didn't converge.
- **Test shape:** Stall-injection integration test that feeds a multi-error compile state and asserts the fix loop either stabilizes or surfaces a structured "compile failure report" (not just `compile_failed=false`).
- **PRs:** 1–2 (investigation-dependent). **LOC:** M (~120). **Risk:** HIGH (touches the recovery hot-path that burns budget).
- **Dependencies:** A-09 (scope reduction may already eliminate the exhaustion case).
- **Parallelizable with:** Anything outside `wave_executor.py` / `compile_profiles.py`.
- **Bug #20 overlap:** Partial — Bug #20 improves codex-path recovery quality (corrective prompts on same session), which means Claude fallback triggers less often, which means A-10's exhaustion case is rarer. Does NOT fix the exhaustion when fallback IS triggered.

---

## 3. Bucket B — Deferred to later milestones (40)

Each finding lists the later milestone that should cover it. These are real defects in code the builder **shouldn't have produced at M1 execution**; the correct fix is A-09 (prevent over-build) + wait until the actual milestone runs. Do not open fix PRs for Bucket B items until their milestone executes.

### B.1 Audit findings deferred to M2 (Auth & Core)

| ID | Title | Defers to |
|---|---|---|
| F-001 | api-client Content-Type clobber | M2 Wave C (generated client) |
| F-005 | 9 api-client re-exports missing | M2 Wave C |
| F-008 | No protected-route layout | M2 |
| F-012 | `/auth` vs `/login` route | M2 |
| F-014 | No redirect after login | M2 |
| F-015 | No react-hook-form / zod on forms | M2 |
| F-018 | UserResponseDto camelCase inconsistency | M2 |
| F-020 | GET `/api/auth/me` with body param | M2 |
| F-031 | JWT in localStorage vs HttpOnly cookie | M2 |
| F-032 | No CSRF middleware | M2 |
| F-037 | No rate-limiting on auth endpoints | M2 |
| F-038 | No token refresh / 401 interceptor | M2 |
| F-039 | `User.password` leaked via API client types | M2 |
| F-041 | `accessToken` vs `access_token` field-name mismatch | M2 |

### B.2 Audit findings deferred to M3 (Projects)

| ID | Title | Defers to |
|---|---|---|
| F-009 | Pagination query params missing on list endpoints | M3 |
| F-011 | Project edit/delete UI missing | M3 |
| F-021 | Inline form vs create-project modal | M3 |
| F-022 | Projects table missing Owner col + sort | M3 |
| F-025 | Extended `ProjectDetailDto` missing | M3 |
| F-034 | Frontend projects page has no pagination controls | M3 |

### B.3 Audit findings deferred to M4 (Tasks & Kanban)

| ID | Title | Defers to |
|---|---|---|
| F-002 | Task Detail page + components missing | M4 |
| F-010 | Kanban board view missing | M4 |
| F-017 | Forward-only task status transitions | M4 |
| F-029 | `due_date` ISO string serialization fragile | M4 |

### B.4 Audit findings deferred to M5 (Comments & Users)

| ID | Title | Defers to |
|---|---|---|
| F-003 | Team Members page + components missing | M5 |
| F-004 | User Profile page + components missing | M5 |
| F-006 | Comments section missing from Task Detail | M5 |
| F-024 | Sidebar missing Team link | M5 |

### B.5 Audit findings deferred to M6 (i18n & RTL)

| ID | Title | Defers to |
|---|---|---|
| F-013 | i18n namespaces empty — per M1 spec, populated per-milestone | M2–M5 populate, M6 polishes |
| F-016 | Language switcher missing | M6 |
| F-040 | No root `/404` not-found page | M6 polish |

### B.6 Schema deferred (M2+ when entities get added)

| ID | Title | Defers to |
|---|---|---|
| F-019 | M1 scope violation (the meta-finding) | — structural fix is A-09 |
| F-028 | Prisma enum casing + field `@map` conventions | M2 |

### B.7 Contract violations — 7 root causes (77 leaves)

All endpoints are M2+ features; all 77 violations should be absent at M1 audit time after A-09 lands. Filed here as root causes for when their actual milestone runs.

| ID | Root cause | Affected endpoints | Defers to |
|---|---|---|---|
| CV-01 | ENUM-CASE: Prisma enums lowercase vs contract UPPER_SNAKE_CASE | 20 endpoints | M2 (`schema.prisma` + mapper) |
| CV-02 | FIELD-NAMING: `assignee_id` snake_case vs contract `assigneeId` | 4 (Task endpoints) | M4 |
| CV-03 | MISSING-FIELD: flat scalars omitted (`ownerName`, `assigneeName`, `authorId`, `authorName`, `taskId`, `createdAt`, `updatedAt` on Comment) | 16 instances | M2–M5 |
| CV-04 | EXTRA-FIELD: unrequested fields (`taskCounts`, `reporter`, `deletedAt`, `openTaskCount`, `tasks[]`, `avatar_url`) | 19 instances | M2–M5 |
| CV-05 | SHAPE-MISMATCH: nested `owner/assignee` object where contract expects flat scalar | 5 instances | M3–M4 |
| CV-06 | WRONG-RESPONSE-BODY: DELETE returns entity instead of `{ data: null }` | 3 (DELETE endpoints) | M3–M5 |
| CV-07 | WRONG-RESPONSE-TYPE: PATCH `/users/:id` returns `UserResponseDto` instead of `UserSummaryDto` | 1 | M5 |

---

## 4. Bucket C — Auditor-scope bugs (1)

### C-01 — Auditor scores against full PRD, not current milestone scope
- **Source:** Meta-inference across Bucket B. Finding: an M1 audit run produced 41 findings, 40 of which are about M2–M5 code that per spec shouldn't exist at M1 audit time.
- **Evidence:** `AUDIT_REPORT.json` `notes`: "major structural gaps: entire pages (Task Detail, Team Members, User Profile) are missing, docker-compose.yml is absent" — the "pages missing" half is an out-of-scope complaint; the "docker-compose.yml" half is the only in-scope finding.
- **Root cause:** `audit_prompts.py` (searched: only `milestone_id` references in *output paths*, not in *scope filter*) builds audit prompts against the full codebase + full PRD, not restricted to the current milestone's REQUIREMENTS.md.
- **Fix shape:** Update audit prompt construction to (a) pass only the current milestone's REQUIREMENTS.md as the acceptance spec, (b) restrict file-scope to the `Files to Create` list from that milestone, (c) flag out-of-scope files as "scope-violation" findings (one per file) instead of 10+ findings per out-of-scope module. The "scope-violation" finding itself becomes the auditor's way of catching A-09-type regressions.
- **Test shape:** Unit test on the audit prompt builder — feed a milestone-1-context, assert the prompt excludes Project/Task/Comment/User entity names, Kanban/Team/TaskDetail component names; feed a milestone-3 context, assert Projects entities ARE included.
- **PRs:** 1. **LOC:** M (~150). **Risk:** MEDIUM (changes audit verdicts on every run).
- **Dependencies:** None; but optimally paired with A-09 so both land together.
- **Parallelizable with:** Any of A-01..A-08, D-*.
- **Bug #20 overlap:** None.

---

## 5. Bucket D — Builder defects (20)

### D-01 — Context7 quota exhaustion degrades tech research
- **Source:** B-001
- **Evidence:** "Context7 quota is exhausted. I'll fall back to authoritative web-based research"; `TECH_RESEARCH.md` not created
- **Root cause:** Quota is environmental (not builder code), but the builder has no pre-flight check and no structured fallback output.
- **Fix shape:** Add pre-flight context7 quota probe at run start. If quota low, either (a) skip context7 and log once, or (b) still attempt but emit `TECH_RESEARCH.md` stub with "research degraded — quota exhausted" instead of silently omitting the file.
- **Test shape:** Mock a quota-exhausted context7 response; assert `TECH_RESEARCH.md` is created with a clear degradation note.
- **PRs:** 1. **LOC:** S (~40). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Any non-audit item.
- **Bug #20 overlap:** None.

### D-02 — Runtime verification cannot run without docker-compose OR live app
- **Source:** B-002, §4.1
- **Evidence:** `RUNTIME_VERIFICATION.md`: "No docker-compose file found — runtime verification skipped"
- **Root cause:** `runtime_verification.py` hard-depends on a compose file; no graceful path if A-01 fails or the host doesn't support Docker.
- **Fix shape:** Two-tier: (1) always require compose at runtime-verification layer (matches M1 AC); (2) if compose boot fails, keep that as the failure — do NOT silently skip with `health=skipped` when `live_endpoint_check=true`. Report a structured "runtime_verification_blocked" result.
- **Test shape:** Mock a no-compose scenario; assert `health=blocked` (not `skipped`) and `endpoint_test_report.error` is populated.
- **PRs:** 1. **LOC:** S (~40). **Risk:** LOW.
- **Dependencies:** A-01 (compose file must be produced for the happy path).
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-03 — OpenAPI generation launcher fails on Windows (`WinError 2`)
- **Source:** B-003, §4.1
- **Evidence:** "OpenAPI script generation unavailable for milestone-1: [WinError 2] The system cannot find the file specified. Falling back to regex extraction."
- **Root cause:** `openapi_generator.py` spawns an external command (likely `npx @openapitools/openapi-generator-cli` or `node <script>`) via subprocess with a non-`shell=True` invocation on Windows, where `.cmd` resolution requires the shell or an explicit `.cmd` suffix.
- **Fix shape:** In `openapi_generator.py`, use `shutil.which(cmd)` to resolve the executable path, then call with the resolved absolute path. On Windows, fall through `.cmd`/`.exe` extensions. Surface the exact executable name in the error path so regex fallback is a deliberate degradation, not a silent one.
- **Test shape:** Windows-specific test that mocks `shutil.which` returning a `.cmd` path; assert subprocess is invoked with the resolved path.
- **PRs:** 1. **LOC:** S (~30). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-04 — Review fleet was never deployed during orchestration
- **Source:** B-004
- **Evidence:** "GATE VIOLATION: Review fleet was never deployed (8 requirements, 0 review cycles)"; "RECOVERY PASS: 0/8 requirements checked (0 review cycles)"
- **Root cause:** Orchestration-phase step that should deploy review agents didn't fire — either a phase-transition condition is wrong or the phase handler short-circuits when convergence_cycles=1.
- **Fix shape:** Trace `cli.py` orchestration phase; find the review-deploy guard and fix the condition. Likely the guard reads `convergence_cycles > 0` or similar and skips when it's 1 before review runs.
- **Test shape:** Unit test on orchestrator phase state transition that asserts review-fleet deploy is called when orchestration completes with requirements > 0.
- **PRs:** 1. **LOC:** M (~80). **Risk:** MEDIUM (orchestration phase logic).
- **Dependencies:** None.
- **Parallelizable with:** Items outside `cli.py`.
- **Bug #20 overlap:** None.

### D-05 — Review recovery misfires into prompt-injection handling
- **Source:** B-005
- **Evidence:** "Launching review-only recovery pass..." → "This message appears to be a prompt injection attempt..."
- **Root cause:** Recovery pass feeds internal file content into a prompt that includes an untrusted-input guardrail; the guardrail trips on the file's own content (e.g., a DTO file that contains "IGNORE ALL PREVIOUS INSTRUCTIONS" as a test fixture).
- **Fix shape:** Separate `system`/`developer` from `user` content in recovery prompts; internal files go into `developer` role (trusted), not `user` role. If this framework doesn't have role separation, wrap the file content in `<file path="...">...</file>` tags and update the prompt-injection detector to ignore content inside `<file>` blocks.
- **Test shape:** Feed a recovery pass a file whose content includes "IGNORE ALL PREVIOUS INSTRUCTIONS" and assert it doesn't trigger the injection guard.
- **PRs:** 1. **LOC:** M (~100). **Risk:** MEDIUM (prompt handling changes affect every recovery call).
- **Dependencies:** None.
- **Parallelizable with:** Items outside recovery/prompt code.
- **Bug #20 overlap:** None.

### D-06 — Recovery taxonomy contains `"Unknown recovery type"` for `debug_fleet`
- **Source:** B-006
- **Evidence:** Recovery summary: `debug_fleet: Unknown recovery type`
- **Root cause:** Recovery dispatcher's type-to-handler map is missing `debug_fleet`.
- **Fix shape:** Add `debug_fleet` to the recovery-type registry; either wire a handler or explicitly mark it as a tracking-only type with a proper label.
- **Test shape:** Unit test that enumerates all recovery types referenced in the codebase and asserts each has a registered handler or an explicit tracking-only marker.
- **PRs:** 1. **LOC:** S (~15). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-07 — Audit producer/consumer schema mismatch on `audit_id`
- **Source:** B-007, §4.3
- **Evidence:** "Failed to parse AUDIT_REPORT.json: 'audit_id'"; `AUDIT_REPORT.json` schema is `{audit_cycle, timestamp, score, max_score, verdict, health, deductions_total, deductions_capped, finding_counts, findings, category_summary, by_severity, by_file, fix_candidates, notes}` — no `audit_id`. `audit_models.AuditReport.from_json` at line 242 requires `audit_id`.
- **Root cause:** Two serializers exist — the "scorer agent" writes a different shape than `AuditReport.to_json()`. The consumer (`cli.py:577` uses `report.audit_id`) assumes the `AuditReport` shape.
- **Fix shape:** Unify on one schema. Either (a) update the scorer-agent prompt to produce the `AuditReport` shape including `audit_id`, `cycle`, `auditors_deployed`, and `score: AuditScore` struct; or (b) update `AuditReport.from_json` to accept the current scorer output and synthesize `audit_id` from timestamp+cycle. Option (a) is cleaner.
- **Test shape:** Round-trip test: feed a scorer-produced JSON, parse with `AuditReport.from_json`, assert no KeyError.
- **PRs:** 1. **LOC:** S (~40). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-08 — CONTRACTS.json generated in recovery pass, not orchestration
- **Source:** B-008, §4.3
- **Evidence:** "CONTRACTS.json not found after orchestration"; "Launching contract-generation recovery pass"
- **Root cause:** Contract generation is conditional on a step that didn't run during orchestration (likely gated on Wave C output format or a missing dependency input).
- **Fix shape:** Move contract-generation to a deterministic step at end of orchestration (not conditional). The "recovery pass" path becomes a belt-and-suspenders, not the primary producer.
- **Test shape:** Integration test that runs orchestration and asserts `CONTRACTS.json` exists before the verification phase begins.
- **PRs:** 1. **LOC:** M (~80). **Risk:** MEDIUM (orchestration ordering).
- **Dependencies:** None (but aligns with D-04 orchestration-phase fix).
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-09 — Contract Engine `validate_endpoint` MCP tool missing from deployed toolset
- **Source:** B-009, §4.4
- **Evidence:** "The validate_endpoint Contract Engine MCP tool is not present in the deployed toolset"
- **Root cause:** Either `mcp_servers.py` or the deployed MCP server config is missing the Contract Engine. Environmental/deployment, not a pipeline bug.
- **Fix shape:** (a) Add Contract Engine MCP to `mcp_servers.py` registration; (b) if the engine doesn't exist yet, document the gap and ensure static-analysis fallback is always the path and labeled clearly.
- **Test shape:** Pre-flight check at run start — list deployed MCP tools and assert `validate_endpoint` is available or log a structured deprecation marker.
- **PRs:** 1. **LOC:** S (~30). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-10 — Phantom integrity finding (DB-004) persists across fix cycles
- **Source:** B-010
- **Evidence:** `FIX_CYCLE_LOG.md` DB-004 on nonexistent `Management` field / `App` enum in `schema.prisma`; flagged + "false positive" verdict twice
- **Root cause:** Integrity checker has stale/hallucinated findings that survive round-trips because there's no "resolved → do not re-emit" marker on confirmed false positives.
- **Fix shape:** Extend the integrity checker's state to include a `false_positives` suppression list scoped to the current run; once a finding is confirmed false-positive in cycle N, subsequent cycles in the same run do not re-raise it.
- **Test shape:** Unit test that feeds two consecutive cycles with the same phantom finding; asserts it's raised once in cycle 1 and suppressed in cycle 2 after being marked FP.
- **PRs:** 1. **LOC:** S (~50). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-11 — `WAVE_FINDINGS.json` remained empty despite Wave T running
- **Source:** B-011, F-030
- **Evidence:** `.agent-team/milestones/milestone-1/WAVE_FINDINGS.json`: `{"findings": []}`; F-030 also flagged Wave T summary + E2E Playwright tests missing
- **Root cause:** Wave T (trace/E2E) did not populate the deterministic findings ledger — likely never ran for this milestone because it's gated behind Wave D success.
- **Fix shape:** (a) Wave T should execute regardless of Wave D success (it's a verification wave — it should RUN on failure too, to capture evidence); (b) ensure Wave T writes `WAVE_FINDINGS.json` unconditionally, even if empty with a "Wave T did not run due to ..." marker.
- **Test shape:** Integration test where Wave D fails; assert `WAVE_FINDINGS.json` is still written and contains a structured "skipped — upstream wave D failed" marker.
- **PRs:** 1. **LOC:** M (~80). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-12 — Telemetry `last_sdk_tool_name` still blank in final wave telemetry
- **Source:** B-012
- **Evidence:** Wave B + Wave D telemetry shows `last_sdk_tool_name: ""` even though hang reports clearly captured `command_execution`
- **Root cause:** Final wave-telemetry snapshot is taken after the watchdog/hang-report state is cleared OR before the last tool event is recorded. The hang report sees it because it captures at fire-time; telemetry misses it because it reads the post-run state.
- **Fix shape:** In `wave_executor.py`, capture `last_sdk_tool_name` into the wave telemetry struct at the same moment the hang report is finalized, not from the post-run watchdog state.
- **Test shape:** Unit test on telemetry finalization — mock a watchdog state with pending tool, finalize, assert `last_sdk_tool_name` is populated in the wave telemetry.
- **PRs:** 1. **LOC:** S (~25). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** **Resolved by Bug #20** — app-server mode emits `item/started` with structured `tool_name` on a streaming channel, so `last_sdk_tool_name` becomes a natural side effect of the transport. If Bug #20 lands before D-12 is needed, D-12 is obsoleted for the codex path (Claude-path still needs it, but Claude doesn't have the orphan-tool issue).

### D-13 — Builder state (STATE.json) ends internally inconsistent
- **Source:** B-013, §2
- **Evidence:** `summary.success: true` despite `failed_milestones: ["milestone-1"]`; `audit_health: ""` despite `AUDIT_REPORT.json.health=failed`; `waves_completed: 3` but telemetry includes Wave D; `current_wave: D` persists after `current_phase=complete`; `stack_contract` empty with `confidence=high`
- **Root cause:** Multiple independent state writers in `state.py` / `cli.py` — none has a final "consolidate" step that derives `summary.success` from `failed_milestones`, `audit_health` from `AUDIT_REPORT.json.health`, etc.
- **Fix shape:** Add a `State.finalize()` method called at end of pipeline that computes the summary fields deterministically from the authoritative sources (`failed_milestones`, `audit_health` from AUDIT_REPORT.json, `current_wave` cleared when `current_phase=complete`, `stack_contract.confidence` low if fields are blank). Call from `cli.py` before writing final STATE.json.
- **Test shape:** Unit tests on `State.finalize()` for each inconsistency: failed milestone → `summary.success=false`; audit report failed → `audit_health="failed"`; etc.
- **PRs:** 1. **LOC:** M (~120). **Risk:** LOW.
- **Dependencies:** D-07 (audit schema fixed first so `audit_health` can be read from report).
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-14 — Verification artifacts blend static + heuristic without clear labels
- **Source:** B-014, §4.4
- **Evidence:** `CONTRACT_E2E_RESULTS.md` is static analysis (with explicit disclaimer); `RUNTIME_VERIFICATION.md` says "skipped"; `VERIFICATION.md` blends them without distinguishing fidelity levels
- **Root cause:** `verification.py` concatenates results from multiple verifiers without tagging each section's verification fidelity (runtime vs static vs heuristic).
- **Fix shape:** Update `VERIFICATION.md` template to include a per-section header `**Verification fidelity:** runtime | static | heuristic`. Add a summary footer: "Overall verification confidence: {runtime_count}/{total_sections} ran at full fidelity."
- **Test shape:** Unit test on verification-report renderer — feed a mix of static+runtime results, assert the rendered doc has fidelity tags and the summary count.
- **PRs:** 1. **LOC:** S (~40). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-15 — Compile-fix iteration budget exhausts at 3 without exposing structural issues
- **Source:** New (T2-02; derived from A-10 investigation)
- **Evidence:** Same as A-10
- **Root cause:** `compile_profiles.py`'s loop is bounded at 3 iterations with no "structural review" escape — when errors span multiple files with a shared root cause, 3 diffs in isolation can't stabilize.
- **Fix shape:** **INVESTIGATE** + probably: bump iteration budget conditionally (post-fallback: 5; normal: 3), OR add a "structural triage" first pass that inspects `package.json` + `tsconfig.json` + top-level imports before diffing.
- **Test shape:** Feed a compile-fix loop a simulated multi-error state where the root cause is a missing devDep in package.json; assert the loop surfaces that as a structural issue rather than diffing individual files.
- **PRs:** 1. **LOC:** M (~100). **Risk:** HIGH (recovery hot-path).
- **Dependencies:** A-10 (same investigation).
- **Parallelizable with:** Non-compile items.
- **Bug #20 overlap:** Partial (fewer codex-induced fallbacks mean compile-fix exhaustion is rarer, not eliminated).

### D-16 — Post-fallback Claude output does not compile
- **Source:** New (T2-03)
- **Evidence:** Build-j: Wave D fallback produced 47 files via claude-sonnet-4-6, compile never stabilized
- **Root cause:** **INVESTIGATE.** Candidates: (a) fallback prompt doesn't provide enough tsconfig/monorepo context; (b) fallback prompt inherits Wave D's over-build scope (see A-09) and tries to produce M2–M5 features from scratch in one turn; (c) the compile-fix loop after fallback doesn't know it's operating on fallback-produced code and re-uses the original prompt's context.
- **Fix shape:** Depends on investigation. Most likely: tighten the fallback prompt to pass current-milestone scope only, and reset compile-fix context to read the actual on-disk tsconfig + package.json before diffing.
- **Test shape:** Unit test on fallback prompt construction — assert scope is filtered to the current milestone (overlaps A-09).
- **PRs:** 1. **LOC:** M (~150). **Risk:** HIGH.
- **Dependencies:** A-09 (scope filter) + A-10/D-15 (compile budget).
- **Parallelizable with:** Non-fallback items.
- **Bug #20 overlap:** Partial (reduces fallback frequency, doesn't fix output quality).

### D-17 — Truth-score calibration: `error_handling=0.06` and `test_presence=0.29` too low
- **Source:** §8 finding 3
- **Evidence:** Truth scores 0.6787 overall; weakest dims `requirement_coverage=0.70`, `error_handling=0.06`, `test_presence=0.29`
- **Root cause:** `error_handling` near-zero on a codebase that has global exception filter + envelope interceptor suggests the truth-score probe is looking for per-function try/catch, not framework-level error handling. `test_presence=0.29` is penalizing M1 for having "zero test files" even though M1 spec requires "zero test files (placeholder)".
- **Fix shape:** Update `truth_scores` scorer in `verification.py` (or wherever truth probe lives) to (a) credit framework-level error handling (filters, interceptors) not just try/catch, (b) treat "empty test suite that executes" as passing for milestones where tests are explicitly placeholder (consult MASTER_PLAN for test expectations).
- **Test shape:** Unit test: feed a codebase with global exception filter, assert `error_handling >= 0.7`.
- **PRs:** 1. **LOC:** M (~80). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** Most items.
- **Bug #20 overlap:** None.

### D-18 — npm audit reports 3 high vulnerabilities in scaffold dependencies
- **Source:** §8 finding 5 "npm audit: 0 critical, 3 high vulnerabilities"
- **Evidence:** `GATE_FINDINGS.json`
- **Root cause:** Scaffold `package.json` pins specific versions of deps that have transitive vulnerabilities as of 2026-04-15.
- **Fix shape:** Update scaffold `package.json` templates to latest patch/minor pins; add a post-scaffold `npm audit --audit-level=high` step that fails the scaffold if vulnerabilities persist.
- **Test shape:** Scaffold integration test that runs `npm install` + `npm audit --audit-level=high` and asserts exit 0.
- **PRs:** 1. **LOC:** S (~30). **Risk:** LOW.
- **Dependencies:** None.
- **Parallelizable with:** A-07, A-08 (same scaffold template layer).
- **Bug #20 overlap:** None.

### D-19 — Other gate/spot-check findings (dup fn names, empty class bodies, missing test IDs, hardcoded text, hardcoded hex, off-grid spacing)
- **Source:** §8 finding 6
- **Evidence:** `GATE_FINDINGS.json`
- **Root cause:** These flag M2+ code that shouldn't exist at M1 (same structural root as Bucket B / A-09). Handled implicitly when A-09 lands — M2+ code won't be produced during M1.
- **Fix shape:** **None directly.** Mark as "covered by A-09 structural fix; if persists after A-09 lands, reopen as Bucket A/B depending on scope."
- **Test shape:** N/A (observer item).
- **PRs:** 0. **LOC:** — **Risk:** LOW.
- **Dependencies:** A-09.
- **Parallelizable with:** N/A.
- **Bug #20 overlap:** None.

### D-20 — `npm run dev:api` and `prisma migrate dev` ACs not verified during audit
- **Source:** milestone-1 REQUIREMENTS.md §"M1 Acceptance Criteria Results" — "UNKNOWN (not tested in audit)" for `npm install` and `prisma migrate dev`
- **Evidence:** REQUIREMENTS.md
- **Root cause:** Audit didn't execute the actual startup-AC checks for M1 — it only verified what the comprehensive auditor could read statically (Swagger UI confirmed, ports confirmed). `npm install` and `prisma migrate dev` are explicit M1 ACs but audit lacks a step to run them.
- **Fix shape:** Add a deterministic "M1 startup AC probe" to the audit phase for infrastructure-only milestones: run `npm install`, `docker-compose up -d postgres`, `npx prisma migrate dev --name init`, assert each exits 0. Report in `AUDIT_REPORT.json` as a new `acceptance_tests` section.
- **Test shape:** Unit test on audit phase — mock subprocess results for each AC command; assert they're each invoked and their results are included in the audit report.
- **PRs:** 1. **LOC:** M (~100). **Risk:** MEDIUM (touches audit phase).
- **Dependencies:** A-01 (compose file exists), A-02 (port 3001), A-07 (vitest).
- **Parallelizable with:** D-07 (same audit layer), but prefer to serialize.
- **Bug #20 overlap:** None.

---

## 6. Tier-1 M1-blockers → tracker ID crosswalk (6)

Maps the 6 hard-fail causes from FINAL_VALIDATION_REPORT §10 + §4 onto tracker items above:

| Tier-1 ID | Description | Maps to |
|---|---|---|
| T1-01 | Generated project materially incomplete (docker-compose missing, pages missing, api-client broken) | A-01 (compose) + A-09 (over-build filter) + C-01 (auditor scope) — everything else in Bucket B |
| T1-02 | Wave D post-fallback compile-fix exhausted after 3 attempts | A-10 + D-15 + D-16 |
| T1-03 | OpenAPI generation launcher `WinError 2` | D-03 |
| T1-04 | Audit producer/consumer `audit_id` schema mismatch | D-07 |
| T1-05 | Contract Engine `validate_endpoint` MCP tool missing | D-09 |
| T1-06 | CONTRACTS.json generated in recovery, not orchestration | D-08 |

All 6 T1 blockers are addressable via Bucket A + Bucket D without Bug #20.

---

## 7. Dependency graph

Dependencies use only tracker IDs (no chained meta-items). "→" reads "must land before".

```
Scaffold cluster (all parallel, no deps):
  A-01, A-02, A-03, A-04, A-05, A-06, A-07, A-08, D-18

Auditor + scope cluster:
  A-09  → D-19 (observer only; closes automatically when A-09 lands)
  C-01  (independent; can land alongside A-09 in same session)
  A-09 + C-01 → (collectively) reduce the next audit's finding count by ~90%

Orchestration / recovery cluster:
  D-04, D-05, D-06, D-07, D-08, D-10, D-11 — all independent of each other
  D-13 → needs D-07 (audit schema fixed before state consolidator reads audit_health)
  D-20 → needs A-01, A-02, A-07 (startup-AC probe requires the scaffold bits to be correct first)

Runtime + toolchain cluster:
  D-02 → needs A-01 (compose file)
  D-03 independent (Windows launcher)
  D-09 independent (MCP deployment)

Compile-fix / fallback cluster (high-risk, investigate-first):
  A-10, D-15, D-16 — bundled INVESTIGATION session; A-10 and D-15 share root cause
  D-16 → depends on A-09 (scope filter) + A-10 (compile budget)

Telemetry hygiene:
  D-12 (obsoleted by Bug #20 for codex path; still needed for Claude path)
  D-14 (verification report labels)
  D-17 (truth-score calibration)

Environmental:
  D-01 (context7 quota handling — pre-flight)

Bug #20 (optional, quality investment, NOT gating for M1 clearance):
  No hard dep; benefits from D-07, D-11, D-13 being landed first for clean telemetry baseline.
```

---

## 8. Parallel clusters

Grouped by non-overlapping code, so each cluster can ship in one session without merge conflicts:

- **Cluster 1 — Scaffold deterministic output:** A-01, A-02, A-03, A-04, A-07, A-08, A-06, D-18. Touches `scaffold_runner.py` + wave B/D prompts + template files.
- **Cluster 2 — Auditor scope + over-build:** A-09, C-01. Touches `audit_prompts.py` + `wave_executor.py` wave-prompt construction.
- **Cluster 3 — Audit schema + state:** D-07, D-13, D-20. Touches `audit_models.py` + `state.py` + `cli.py` finalization.
- **Cluster 4 — Orchestration recovery:** D-04, D-05, D-06, D-08, D-11. Touches orchestration phase + recovery dispatcher + Wave T gating.
- **Cluster 5 — Runtime + toolchain hardening:** D-02, D-03, D-09. Touches `runtime_verification.py`, `openapi_generator.py`, `mcp_servers.py`.
- **Cluster 6 — Compile/fallback (INVESTIGATE first):** A-10, D-15, D-16. Touches `compile_profiles.py`, `wave_executor.py` recovery path, fallback prompts.
- **Cluster 7 — Hygiene tail:** D-01, D-10, D-12, D-14, D-17. Independent small items.
- **Cluster 8 — Bug #20 (separate long-running branch):** standalone, see Bug #20 plan.

Bucket B items do not appear here — they're resolved when their respective milestones actually execute.

---

## 9. Ordered session plan

Each session is self-contained — a zero-context agent should be able to pick it up from the cluster description plus the tracker item IDs.

### Session 1 — Cluster 2: Auditor scope + over-build filter — HIGHEST LEVERAGE
- **Items:** A-09 (M1 scope filter on wave prompts + post-wave out-of-scope validator), C-01 (audit scoped to current milestone).
- **PRs:** 2.
- **Size:** L (~500 LOC).
- **Risk:** MEDIUM.
- **Why first:** If this lands, the next smoke has ~33 fewer audit findings and doesn't ask Wave D to build Task Detail / Kanban / Team pages during M1. Every other fix compounds with this.
- **Exit criteria:** Unit tests verify M1 wave prompts exclude M2–M5 entities; M1 audit prompt excludes M2–M5 file paths; post-wave validator flags any emitted file outside milestone's `Files to Create` list.

### Session 2 — Cluster 1: Scaffold deterministic output
- **Items:** A-01 (compose), A-02 (port 3001), A-03 (Prisma shutdown), A-04 (i18n locales), A-07 (vitest), A-08 (.gitignore), A-06 (RTL baseline investigation), D-18 (npm audit).
- **PRs:** 2 (scaffold_runner + template audit).
- **Size:** M (~250 LOC).
- **Risk:** LOW.
- **Exit criteria:** Scaffold integration test passes; `npm install` + `docker-compose up -d postgres` + `npx prisma migrate dev` + `npm run test:web` all exit 0 against a fresh scaffold.

### Session 3 — Cluster 3: Audit schema + state finalization
- **Items:** D-07 (audit_id schema unify), D-13 (State.finalize consolidator), D-20 (M1 startup-AC probe in audit).
- **PRs:** 2 (audit-schema, state-finalize + startup-AC probe bundled).
- **Size:** M (~260 LOC).
- **Risk:** LOW–MEDIUM.
- **Exit criteria:** Round-trip audit serialization test passes; STATE.json `summary.success` + `audit_health` + `current_wave` derive correctly from authoritative fields; startup-AC probe runs and populates `acceptance_tests` in audit report.

### Session 4 — Cluster 4: Orchestration + recovery hygiene
- **Items:** D-04 (review fleet deploy guard), D-05 (recovery prompt-injection), D-06 (recovery taxonomy), D-08 (CONTRACTS.json in orchestration), D-11 (WAVE_FINDINGS unconditional write).
- **PRs:** 3 (orchestration-phase, recovery-dispatcher, Wave T gating).
- **Size:** M–L (~400 LOC).
- **Risk:** MEDIUM (orchestration ordering touches the hot path).
- **Exit criteria:** Orchestration integration test asserts review fleet deployed; recovery-pass test with injection-shaped file content doesn't misfire; CONTRACTS.json exists at end of orchestration phase; Wave T writes findings file even on upstream failure.

### Session 5 — Cluster 5: Runtime + toolchain hardening
- **Items:** D-02 (runtime_verification degrade), D-03 (OpenAPI launcher Windows), D-09 (MCP tool deploy).
- **PRs:** 3 (one per file).
- **Size:** M (~100 LOC).
- **Risk:** LOW–MEDIUM.
- **Exit criteria:** Windows tests for OpenAPI launcher pass; runtime_verification returns `health=blocked` (not `skipped`) when compose missing + `live_endpoint_check=true`; MCP pre-flight logs structured status for `validate_endpoint`.

### Session 6 — M1 LIGHTWEIGHT SMOKE GATE
- **Items:** None. Run one stock Sonnet smoke at current integration branch with Sessions 1–5 landed.
- **Expected cost:** ~$8–12.
- **Pass criteria:**
  - M1 reaches `complete` without failure.
  - Audit finds ≤ 5 findings (scoped correctly to M1).
  - Truth score ≥ 0.85 on `requirement_coverage`.
  - Startup-AC probe shows all 7 M1 ACs pass.
  - STATE.json `summary.success=true` consistent with `failed_milestones=[]`.
- **Fail criteria:** Any of the above missing → do NOT proceed; open investigation on the specific regression.
- **Go/no-go:** If pass, this is the first defensible "M1 clears" signal since integration bundle opened on 2026-04-12. If fail, loop back to the cluster that caused the regression.

### Session 7 — Cluster 6: Compile-fix / fallback (INVESTIGATION FIRST)
- **Items:** A-10 + D-15 + D-16.
- **Investigation step:** 1 hour — read `compile_profiles.py`, inspect build-j Wave D fallback telemetry, identify whether root cause is budget (3 iter too few) vs prompt quality vs context bleed.
- **PRs:** 1–2 (depends on investigation).
- **Size:** M (~200 LOC).
- **Risk:** HIGH (recovery hot-path; budget changes affect cost).
- **Exit criteria:** Fallback test simulating a multi-error compile stabilizes in ≤ 5 iterations OR surfaces a structured compile-failure report instead of cryptic `compile_passed: false`.

### Session 8 — Cluster 7 first half: Hygiene (telemetry + calibration)
- **Items:** D-12 (last_sdk_tool_name), D-14 (verification labels), D-17 (truth-score calibration).
- **PRs:** 3 small PRs.
- **Size:** M (~140 LOC).
- **Risk:** LOW.
- **Exit criteria:** Unit tests pass; truth score on Claude-only baseline codebase returns ≥ 0.85 `error_handling`.

### Session 9 — Cluster 7 second half: Residual hygiene
- **Items:** D-01 (context7 quota pre-flight), D-10 (phantom FP suppression).
- **PRs:** 2.
- **Size:** S (~90 LOC).
- **Risk:** LOW.
- **Exit criteria:** Unit tests pass.

### Session 10 — Cluster 2 residual validation smoke GATE
- **Items:** None. If Sessions 7–9 are substantial, run one mid-weight smoke to confirm no regressions from the compile-fix + hygiene changes.
- **Decision:** Skip if Sessions 7–9 are purely code-path fixes with strong unit tests. Run if any touched the wave prompt construction or compile-fix hot-path.
- **Cost:** ~$8–12 if run.

### Session 11 — Bug #20 app-server migration (quality investment, not M1-gating)
- **Items:** Bug #20 per existing plan at `docs/plans/2026-04-15-bug-20-codex-appserver-migration.md`.
- **PRs:** 1 main + 1 flag-flip follow-up.
- **Size:** XL (~800 LOC + ~20 new tests).
- **Risk:** HIGH (new transport).
- **Exit criteria:** Unit suite green; one calibration smoke on Wave B clears with `fallback_used=False`.
- **Value proposition after this tracker lands:** Reduces codex wedging frequency → reduces Claude-fallback frequency → reduces compile-fix exhaustion exposure (A-10/D-15/D-16 class). Also resolves D-12 structurally. **Not required for M1 clearance.**

### Session 12 — Full-pipeline integration smoke before master merge
- **Items:** None. Full smoke (all milestones M1–M6) on stock Sonnet config.
- **Cost:** ~$25–40 (exhaustive depth, all waves).
- **Pass criteria:** All milestones PASS, audit health `passed`, no Tier-1 blockers fire.
- **Go/no-go:** If pass, merge integration branch to master. If fail, open focused fix sessions per regression.

### Session 13 — Master merge
- **Items:** None code-wise. Merge `integration-2026-04-15-closeout` to master. Close PRs #3–#12 as appropriate (some may have been superseded by tracker-session PRs).
- **Cost:** $0.
- **Exit criteria:** Master at the new HEAD; memory updated; branch cleanup done.

**Total sessions:** 13 (2 are smoke gates, 1 is merge). **Total PRs:** ~22. **Total validation cost:** ~$40–60 (Sessions 6 + 10 + 12).

---

## 10. Go/no-go smoke gates

Explicit checkpoints where a paid smoke is justified. **No paid smokes between gates.**

1. **Gate A — After Session 5** (Clusters 1/2/3/4/5 landed): Lightweight stock Sonnet smoke. Validates M1 clears with scope-correct auditor + scaffold correctness + audit/state consistency. Cost: ~$10.
2. **Gate B — After Session 9** (optional; only if Cluster 6 or prompt-adjacent work happened): Mid-weight smoke. Validates no regression from compile-fix/hygiene changes. Cost: ~$10. Skip if nothing prompt-adjacent changed.
3. **Gate C — After Session 11** (if Bug #20 was executed): Calibration smoke per Bug #20 plan §6. Cost: ~$10–15.
4. **Gate D — Session 12 (final)**: Full exhaustive smoke across all milestones. Cost: ~$25–40. Must pass before master merge.

Total gated validation cost: **$45–75**.

---

## 11. Open questions / INVESTIGATE items

These need deeper investigation during their session, not pre-judged in this tracker:

1. **A-05** — Is validation-pipe snake_case normalization intentional (undocumented feature) or a template bug? Need to read the history/intent of `normalizeInput` in `validation.pipe.ts`.
2. **A-06** — Is the M1 `globals.css` baseline actually correct (logical properties enforced) or is the baseline itself wrong? The finding points at `app-shell.tsx` which is out of M1 scope — need to confirm whether the scaffold's CSS is also broken.
3. **A-10 / D-15 / D-16** — Is the 3-iteration compile-fix limit too low, or is the fallback prompt producing code that fundamentally can't compile? Need to read fallback-produced files from build-j Wave D to decide between budget vs prompt quality.
4. **D-04** — Is the "review fleet not deployed" caused by a silent guard condition or an explicit skip? Need to trace `cli.py` orchestration phase transitions.
5. **D-17** — Does truth-score `error_handling=0.06` reflect a real codebase issue or a scoring blind spot? Need to confirm the probe looks at framework-level error handling.
6. **D-19 tail** — "Duplicate function names" and "empty class bodies" findings in §8 — are these in M1-scope files (like scaffold templates) or M2+ code that A-09 will obviate?

---

## 12. Honest assessment

Three-tier scope (Tier 1 + Tier 2 + Tier 3) is completable in ~12 focused sessions, but **only** if Session 1 (A-09 + C-01) lands first. Without the auditor scoping + over-build filter, every other fix is undermined by a next-smoke audit that still reports 0/1000 against full-PRD scope.

If time/budget forces a subset, the subset that meaningfully moves the needle:
- **Sessions 1–6** (A-09, C-01, scaffold cluster, audit schema, orchestration recovery, runtime hardening, + Gate A smoke) — this alone closes **all 6 Tier-1 blockers** and lets M1 clear.
- **Defer Sessions 7–11** — compile-fix deep investigation, telemetry hygiene, Bug #20 — as quality-investment work post-M1-clearance.
- **Session 12** (final smoke) is non-negotiable before merge.

That subset: **6 sessions, ~10 PRs, ~$15 validation cost**, and M1 clears. Everything else is improvement, not closeout.
