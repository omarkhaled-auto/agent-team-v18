# Session 2 Execute — Scaffold deterministic output cluster (A-01/02/03/04/05/06/07/08 + D-18)

**Tracker session:** Session 2 in `docs/plans/2026-04-15-builder-reliability-tracker.md` §9.
**Cluster:** Cluster 1 (scaffold deterministic output).
**Why this session:** Session 1 stopped the builder over-building. Session 2 ensures what IS built at M1 is correct — docker-compose present, port 3001, vitest runnable, `.gitignore`, etc. These are the narrow M1 ACs. Gate A smoke in Session 6 won't pass without them.
**Paired items:** 9 items, 2 PRs. 7 are template fixes with known shape; 2 are INVESTIGATE-first (A-05 validation-pipe, A-06 RTL baseline).

---

## 0. Mandatory reading (in order)

1. `docs/plans/2026-04-15-builder-reliability-tracker.md` §2 (Bucket A items A-01..A-08), §5 (D-18), §9 (Session 2).
2. Per-item plans — quick passes:
   - `docs/plans/2026-04-15-a-06-rtl-logical-properties-baseline.md`
   - No dedicated plans for A-01/02/03/04/05/07/08/D-18 — they're S-sized, tracker entries are the full spec. See tracker §2 / §5.
3. `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/milestones/milestone-1/REQUIREMENTS.md` — M1's narrow scope. The scaffold must satisfy its 7 startup ACs.
4. `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/feedback_structural_vs_containment.md` — all fixes here are structural (deterministic scaffold emission), not containment.
5. `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/feedback_verification_before_completion.md` — static file-content assertions are the evidence path; do NOT run `npm install`, `docker compose up`, or any paid/time-intensive command.
6. `src/agent_team_v15/scaffold_runner.py` — read the whole file. 359 lines. Know `_scaffold_nestjs`, `_scaffold_nestjs_support_files`, `_scaffold_nextjs_pages`, `_scaffold_i18n` before you touch them.
7. `tests/test_scaffold_runner.py` — mirror its test style for new assertions.

---

## 1. Goal

Two PRs against `integration-2026-04-15-closeout` (current HEAD `73a9997`):

- **PR A — Scaffold template fixes (7 items)**: A-01 docker-compose.yml, A-02 port 3001, A-03 Prisma shutdown hook, A-04 i18n locales en+ar only, A-07 vitest devDeps, A-08 `.gitignore` + no committed `.env`, D-18 devDep pins for npm-audit cleanliness.
- **PR B — INVESTIGATE items (2)**: A-05 validation-pipe snake_case normalization, A-06 RTL baseline. Investigation findings documented in the PR body; code changes only if evidence supports them.

No merges, no paid smokes. Unit tests + static-content verification only. Feature flags only where a change could plausibly regress something; default-on; tests cover both branches.

---

## 2. Branch + worktree

```
git fetch origin
git worktree add ../agent-team-v18-session-02 integration-2026-04-15-closeout
cd ../agent-team-v18-session-02
git checkout -b session-02-scaffold-cluster
```

One branch, two commits (one per PR). Both PRs target `integration-2026-04-15-closeout`.

---

## 3. Execution order — TDD throughout

### Phase 1 — PR A: deterministic scaffold template fixes

Tests first in `tests/test_scaffold_runner.py` (extend existing) and/or a new `tests/test_scaffold_m1_correctness.py`. All tests must fail before implementation; pass after.

#### A-01 — docker-compose.yml deterministic emission

- **Test first:** after `run_scaffolding(...)` on a NestJS milestone, `project_root/docker-compose.yml` exists. Parse as YAML; assert `services.postgres.image` starts with `postgres:`; assert `services.postgres.ports` contains `"5432:5432"`; assert `services.postgres.volumes` contains a named volume reference (not bind mount); assert `services.postgres.healthcheck.test` is set and uses `pg_isready`.
- **Implement:** add `_scaffold_docker_compose(project_root)` in `scaffold_runner.py`. Emit a template with the four assertions above. Call it from `_scaffold_nestjs_support_files` (or equivalent entry — the call site must run on every NestJS milestone). Do NOT remove the docker-compose references in Wave B / infra-agent prompts in `agents.py:4399..4514` — scaffold emits a valid base; Wave B may extend or replace as needed.
- **Template contents (exact):**
  ```yaml
  services:
    postgres:
      image: postgres:16-alpine
      ports:
        - "5432:5432"
      environment:
        POSTGRES_USER: ${POSTGRES_USER:-postgres}
        POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
        POSTGRES_DB: ${POSTGRES_DB:-app}
      volumes:
        - postgres_data:/var/lib/postgresql/data
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-app}"]
        interval: 10s
        timeout: 5s
        retries: 5

  volumes:
    postgres_data:
  ```

#### A-02 — Backend default port 3001 (not 8080)

- **Test first:** parse the emitted `apps/api/src/config/env.validation.ts` (or whichever module the scaffold writes the env schema in); assert the `PORT` default is 3001. If the scaffold doesn't currently emit this file, the test fails on the file not existing — that's fine, the fix creates it.
- **Implement:** two possible sources for the 8080 default: (a) `scaffold_runner.py` has a template that emits env.validation.ts; (b) Wave B agent prompt in `agents.py` instructs the default. Investigate. Whichever emits it, change the default to 3001 AND update `.env.example` emission to set `PORT=3001`. Keep the scaffolded value source-of-truth: prompts should say "scaffold provides PORT=3001 default; do not change." A single-source template is the structural answer.

#### A-03 — PrismaService shutdown hook

- **Test first:** the scaffolded `apps/api/src/prisma/prisma.service.ts` does NOT contain `this.$on('beforeExit'` anywhere; it DOES register a shutdown hook via a Prisma-5-current pattern (either `enableShutdownHooks(app)` helper on the app lifecycle side, or `process.on('beforeExit')` inside the service — but not the deprecated `$on` form).
- **Implement:** update `_scaffold_nestjs_support_files` or the PrismaService template wherever it lives. Use the pattern recommended in current Prisma docs (verify via context7 `/prisma/prisma` if the right shape isn't obvious — this is exactly the context7 use case). One approach:
  - `prisma.service.ts` implements `OnModuleInit` and calls `await this.$connect()`.
  - `main.ts` scaffold template registers `process.on('beforeExit', async () => app.close())` OR `app.enableShutdownHooks()` if NestJS provides it for the Prisma 5 pattern.
- Do not carry the deprecated `$on('beforeExit')` path forward even behind a flag.

#### A-04 — i18n locales: en + ar only

- **Test first:** scaffolded `apps/web/src/i18n.ts` (or `messages/` + `i18n` config) lists exactly `['en', 'ar']` as locales. No `'id'`, no defaults from other milestones.
- **Implement:** `_scaffold_i18n` currently reads `ir["i18n"]["locales"]`. The `id` locale came from somewhere upstream in the IR — investigate whether the IR has `id` baked in, or if the template has a hardcoded default. Fix at the source. If the IR is the source: that's outside scaffold_runner's layer — add a filter in `_scaffold_i18n` that intersects `ir.i18n.locales` with `{en, ar}` unless the milestone spec explicitly requests others. Emit the filtered list. This is defensive against upstream IR drift.
- **Note:** do NOT add `ar.json` or `en.json` content — per M1 spec, messages files start empty (`{}`). Scaffold emits empty JSON objects in `messages/`; keys populate per-milestone starting M2.

#### A-07 — Vitest runnable in scaffolded frontend

- **Test first:** parse the scaffolded `apps/web/package.json`; assert `devDependencies.vitest`, `devDependencies["@testing-library/react"]`, `devDependencies["@testing-library/jest-dom"]`, `devDependencies.jsdom` are all present (exact version pins below). Assert `scripts["test:web"]` exists at root `package.json` and runs vitest.
- **Implement:** add vitest + testing-library + jsdom to the scaffold template for `apps/web/package.json`. Use these pins (stable as of 2026-04 — verify via context7 `/vitest-dev/vitest` if you want the absolute latest, but pin explicitly):
  ```json
  {
    "devDependencies": {
      "vitest": "^2.1.0",
      "@testing-library/react": "^16.1.0",
      "@testing-library/jest-dom": "^6.6.0",
      "jsdom": "^25.0.0"
    }
  }
  ```
  - Also emit `apps/web/vitest.config.ts` at scaffold time (M1 REQUIREMENTS.md lists it under "Files to Create").
- **Do NOT** run `npm install` in the test. Static JSON parse of `package.json` is the assertion.

#### A-08 — `.gitignore` at root + no committed `.env`

- **Test first:** scaffolded tree has `.gitignore` at project root containing at minimum `node_modules/`, `.next/`, `dist/`, `.env`, `.env.local`, `coverage/`, `.turbo/`, `apps/*/node_modules/`, `apps/*/dist/`. Assert scaffolded tree does NOT contain a committed `.env` file (only `.env.example` is allowed).
- **Implement:** add `_scaffold_gitignore(project_root)` in `scaffold_runner.py`. Called unconditionally. Emit `.env.example` (if not already) with documented vars; do NOT emit `.env`.

#### D-18 — npm audit: 3 high vulnerabilities in scaffold deps

- **Test first:** (static-only — do NOT run `npm audit`.) Parse the scaffolded `package.json`(s) and assert none of the dependencies pin to versions on a known-vulnerable list. Keep the list narrow — the tracker says "3 high vulns" per build-j; investigate which packages by inspecting build-j's `package-lock.json` at `v18 test runs/build-j-closeout-sonnet-20260415/package-lock.json` and cross-referencing with publicly known CVEs (via context7 if you want the current advisory shape, or a static known-bad-version list inlined in the test).
- **Implement:** bump the affected deps to the minimum non-vulnerable patch/minor. Add a comment in the scaffold template citing the CVE/advisory so future readers know why the version is pinned there. If the three vulns are in transitive deps of Next.js / NestJS, the fix is bumping those top-level packages to the patch level that ships clean.
- **Accept:** if investigation reveals the three vulns are in test-only tooling (e.g., eslint plugins) and upgrading is non-trivial, document it in the PR body + add a known-vulnerable-ok allowlist entry rather than chasing zero. Don't spend more than 30 minutes on this one.

---

### Phase 1 exit — before committing PR A

- `pytest tests/test_scaffold_runner.py tests/test_scaffold_m1_correctness.py -v` — all pass (green count reported in PR body).
- **Static scaffold verification:** write a one-off script under `v18 test runs/session-02-validation/build_m1_scaffold.py` that runs `run_scaffolding(...)` against the build-j IR (`v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/product-ir/`) into a temp dir. Capture the resulting file tree + contents of the changed files (docker-compose.yml, env.validation.ts, prisma.service.ts, i18n.ts, web/package.json, .gitignore). Save a dump to `v18 test runs/session-02-validation/phase1-scaffold-dump.txt`.
- Manually eyeball the dump: all 7 fixes visible, no regressions to other scaffold output.
- **Commit subject:** `feat(scaffold): deterministic M1 template correctness (A-01/02/03/04/07/08 + D-18)`. Body lists each tracker ID fixed with a one-line summary.

---

### Phase 2 — PR B: INVESTIGATE items (A-05 + A-06)

Investigation first, code only if evidence supports.

#### A-05 — Validation pipe snake_case normalization

- **Investigation step:**
  1. Read `apps/api/src/common/pipes/validation.pipe.ts` emitted by build-j (`v18 test runs/build-j-closeout-sonnet-20260415/apps/api/src/common/pipes/validation.pipe.ts`). Identify exactly what `normalizeInput()` does.
  2. Cross-reference against `ENDPOINT_CONTRACTS.md` / `CONTRACT_E2E_RESULTS.md` root-causes CV-02 (FIELD-NAMING `assignee_id` vs `assigneeId`) and CV-03 (MISSING-FIELD for camelCase names). If the pipe converts incoming camelCase → snake_case, requests matching the contract's camelCase shape fail class-validator because the DTOs expect either camelCase or snake_case consistently.
  3. Git blame `validation.pipe.ts` in the scaffold template origin (likely `scaffold_runner.py` or `agents.py`) — is the normalization an old feature-request, or template drift?
  4. Write a 200-word investigation note into `v18 test runs/session-02-validation/a05-investigation.md`.
- **Decision tree:**
  - If investigation shows the normalization is **incompatible with the contract's camelCase request bodies**: remove the normalization. The pipe becomes a pass-through `class-validator` + `class-transformer` standard NestJS pipe with `whitelist: true`, `forbidNonWhitelisted: true`, `transform: true` — no custom key rewriting. Tests: emit the scaffolded pipe, parse the source, assert `normalizeInput` is absent and the standard options are present.
  - If investigation shows the normalization was intentional and downstream DTOs rely on snake_case field access: this is a deeper contract misalignment; document the gap in the investigation note, flag CV-02/CV-03 as requiring Session 3+ follow-up, and DO NOT ship a half-fix.
- **Most likely outcome (~90%):** remove the normalization. Commit fix + tests.

#### A-06 — RTL baseline: logical CSS properties

- **Investigation step:**
  1. Read `apps/web/src/styles/globals.css` from build-j. Determine if logical-property utilities (`ps-*`, `pe-*`, `ms-*`, `me-*`) are enabled via Tailwind config.
  2. Read `apps/web/tailwind.config.ts` from build-j. Check `corePlugins`, any preset, any plugins like `@tailwindcss/forms` that might enable or disable logical utilities.
  3. Compare to the A-06 plan §3 branches: Branch A (baseline correct, lint rule only needed) vs Branch B (baseline needs work).
  4. Write a 200-word investigation note into `v18 test runs/session-02-validation/a06-investigation.md`.
- **Decision tree:**
  - **Branch A (baseline correct):** add a deterministic lint rule in the scaffolded `apps/web/eslint.config.js` (or `.eslintrc`) that disallows Tailwind's physical spacing utilities (`px-*`, `py-*`, `mx-*`, `my-*`, `pl-*`, `pr-*`, `pt-*`, `pb-*`, `ml-*`, `mr-*`, `mt-*`, `mb-*`). Add a comment in `globals.css` template pointing at the rule. Tests: scaffolded `eslint.config.js` present; contains the blocking rule.
  - **Branch B (baseline broken):** update `_scaffold_nextjs_pages` Tailwind template to enable logical-property utilities + emit `globals.css` with `html { direction: var(--dir); }` scaffolding. Include the lint rule from Branch A.
- **Do NOT run ESLint in tests.** Static config content assertion only.

---

### Phase 2 exit — before committing PR B

- Both investigation notes in `v18 test runs/session-02-validation/` populated.
- `pytest` on whatever new tests the investigations motivated (likely 2-4 tests).
- **Commit subject:** `feat(scaffold): validation pipe + RTL baseline investigations (A-05 + A-06)`. Body summarizes each investigation's finding and the chosen branch.

---

## 4. Hard constraints

- **No paid smokes.** Unit tests + static content verification only.
- **No `npm install`, no `docker compose up`, no `npx <anything>` in tests.** Parse files as text/JSON/YAML and assert properties. Running real installs/containers is slow, flaky, and not required.
- **No merges.** Push branch + open 2 PRs against `integration-2026-04-15-closeout`. Reviewer (next conversation turn) merges.
- **Do NOT touch files outside scaffold + test layer.** Specifically forbidden:
  - `src/agent_team_v15/wave_executor.py`
  - `src/agent_team_v15/codex_transport.py`
  - `src/agent_team_v15/provider_router.py`
  - `src/agent_team_v15/audit_team.py`
  - `src/agent_team_v15/audit_prompts.py`
  - `src/agent_team_v15/audit_scope.py`
  - `src/agent_team_v15/milestone_scope.py`
  - `src/agent_team_v15/scope_filter.py`
  - The compile-fix / fallback paths.
- **Do NOT change Wave B/D prompts in `agents.py` to remove mentions of `docker-compose.yml` or port values.** Scaffold emits a correct base; leave prompts to do their own thing (add/modify). Co-designing scaffold + prompts together is a separate session if evidence shows drift.
- **Do NOT change config.yaml defaults or add new v18 flags** unless a fix genuinely needs to be toggleable (unlikely for deterministic template fixes).
- **Do NOT run the full suite.** Targeted pytest for changed paths — see §5 below.

---

## 5. Guardrail checks before pushing each PR

Before `git push`:
- Commit diff `git diff integration-2026-04-15-closeout...HEAD --stat` shows changes **only** in:
  - **PR A (Phase 1 commit):**
    - `src/agent_team_v15/scaffold_runner.py` (modified)
    - `tests/test_scaffold_runner.py` (modified — extend existing)
    - `tests/test_scaffold_m1_correctness.py` (new) — if used
  - **PR B (Phase 2 commit):**
    - `src/agent_team_v15/scaffold_runner.py` (modified) — only if A-05/A-06 fix lives here
    - `tests/test_scaffold_validation_pipe.py` (new)
    - `tests/test_scaffold_rtl_baseline.py` (new)
  - Nothing in audit layer, nothing in wave executor, nothing in codex transport.
- Investigation notes committed under `v18 test runs/session-02-validation/` — these are evidence artefacts, not code, safe to commit.

**Targeted pytest (not full suite):**

```
pytest tests/test_scaffold_runner.py \
       tests/test_scaffold_m1_correctness.py \
       tests/test_scaffold_validation_pipe.py \
       tests/test_scaffold_rtl_baseline.py \
       tests/test_wave_scope_filter.py \
       tests/test_audit_scope.py \
       tests/test_audit_scope_wiring.py \
       -v
```

Wave-scope / audit-scope included as regression guard — scaffold changes shouldn't affect them, but a quick sanity check catches surprises.

---

## 6. Reporting back

When both PRs are open, reply in the conversation with a single structured message:

```
## Session 2 execution report

### PRs
- PR A (Phase 1 — scaffold template fixes): <url>
- PR B (Phase 2 — A-05 + A-06 investigations): <url>

### Tests
- tests/test_scaffold_runner.py: <N>/<N> pass
- tests/test_scaffold_m1_correctness.py (new): <N>/<N> pass
- tests/test_scaffold_validation_pipe.py (new): <N>/<N> pass (or skipped if investigation chose no-fix)
- tests/test_scaffold_rtl_baseline.py (new): <N>/<N> pass
- Targeted cluster (pytest command above): <N> passed, 0 failed

### Static verification
- Phase 1 scaffold dump: v18 test runs/session-02-validation/phase1-scaffold-dump.txt
  - docker-compose.yml: present, postgres service + healthcheck
  - PORT default: 3001
  - prisma.service.ts: no $on('beforeExit') pattern
  - i18n locales: ['en', 'ar']
  - web/package.json devDependencies: vitest + testing-library + jsdom present
  - .gitignore: present, covers .env + node_modules
  - package.json pins: all in non-vulnerable range (or allowlist documented)
- A-05 investigation: v18 test runs/session-02-validation/a05-investigation.md (decision: <remove | keep | deeper-gap>)
- A-06 investigation: v18 test runs/session-02-validation/a06-investigation.md (decision: <Branch A | Branch B>)

### Deviations from plan
<one paragraph: anything the investigations uncovered that changed the plan's expected outcome>

### Files changed
<git diff --stat output, grouped by PR>

### Blockers encountered
<either "none" or a structured list>
```

If an investigation reveals the fix is larger than the plan authorized (e.g., A-05 turns out to need changes across multiple files or a contract-layer fix), **stop and report**. Do NOT ship partial work. Do NOT widen scope unilaterally.

---

## 7. What "done" looks like

- Two PRs open against `integration-2026-04-15-closeout`.
- All targeted tests pass (per §5 command).
- Scaffold dump + both investigation notes captured under `v18 test runs/session-02-validation/`.
- Phase 1 delivers 7 deterministic fixes; Phase 2 delivers A-05/A-06 decisions with code iff evidence supports.
- No code outside scaffold + test layer.
- No running of `npm`/`docker`/`npx` in test paths.
- Report posted matching §6 template.

The reviewer (next turn) will diff both PRs against the tracker + per-item plans, verify static artefacts, and either merge or request changes.
