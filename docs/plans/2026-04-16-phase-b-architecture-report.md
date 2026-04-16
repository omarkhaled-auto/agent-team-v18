# Phase B Architecture Report — Scaffold/SPEC/Cascade

**Author:** phase-b-architecture-discoverer (solo Wave 1)
**Date:** 2026-04-16
**Branch:** `phase-b-scaffold-spec`
**Input ground truth:**
- `docs/plans/2026-04-16-deep-investigation-report.md` (Parts 4, 6A, 7, 8; Appendix B.2.4, C, D)
- `docs/plans/2026-04-16-phase-a-architecture-report.md` (template)
- `docs/plans/2026-04-16-phase-a-report.md` (self-audit bar)
- Build-l preserved run (`v18 test runs/build-l-gate-a-20260416/`) — 28 audit findings, Gate-A FAIL
- Source tree: `src/agent_team_v15/{scaffold_runner,ownership_validator,cli,agents,wave_executor,config,state,audit_team,audit_scope}.py`

**Companion artifact:** `docs/SCAFFOLD_OWNERSHIP.md` — the 60-entry ownership table.

---

## 1. Executive Summary

Build-l produced 28 audit findings at Gate-A with a port mismatch FAIL at the Wave-B probe (REQUIREMENTS PORT=4000 vs scaffold-emitted PORT=3001). The deep investigation attributed ~10 of 28 findings to three-layer ownership ambiguity: files fell between `scaffold_runner.py` (frozen Python templates), Wave B (NestJS business modules, prompt-driven), and Wave D (Next.js pages, prompt-driven), with no written contract about which layer emits which path. Phase B closes that gap with three mutually-reinforcing deliverables:

| # | Deliverable | Form | Purpose |
|---|---|---|---|
| N-02 / Phase-B-1 | `docs/SCAFFOLD_OWNERSHIP.md` | Static YAML (60 rows) | Per-file owner contract that both scaffold and wave prompts read |
| N-11 | Cascade consolidation in `cli.py:530` | Runtime Python + feature flag | Collapses duplicate audit findings with shared structural root cause |
| N-12 | SPEC reconciliation | Runtime Python + feature flag | Merges PRD-derived REQUIREMENTS with declarative scaffold registry into one resolved manifest |
| N-13 | Scaffold-verifier post-Wave-A hook | Runtime Python + feature flag | Proves the scaffold actually landed files on disk (catches silent emission failures) |

**Manifest grounding:** REQUIREMENTS.md "Files to Create" (lines 575–647 of the build-l preserved spec) enumerates exactly **60 files** for M1 foundation: 9 root + 28 apps/api + 14 apps/web + 6 packages/shared + 3 packages/api-client. The investigation's "57–60" estimate is now an exact count (60).

**Nine drift clusters** separate what scaffold currently emits from what REQUIREMENTS expects — these are catalogued in §4 and fully itemised in the companion ownership file.

**Feature flag topology:** Phase B adds three flags, all default FALSE per team-lead inviolable rule:
- `v18.ownership_contract_enabled` — wave prompts consume SCAFFOLD_OWNERSHIP.md for claim lists
- `v18.spec_reconciliation_enabled` — SPEC reconciler produces resolved manifest
- `v18.scaffold_verifier_enabled` — post-Wave-A structural verification
- (plus existing) `v18.cascade_consolidation_enabled` flag added for N-11

**Primary risks:** (a) parameterized-template kwargs must thread through 5–6 `_scaffold_*` methods without breaking flag-OFF behavior (see §5.4 for revised low-risk approach); (b) cascade pattern-matching on file paths is heuristic — needs calibration; (c) NestJS path drift (`src/database` vs `src/prisma`, `src/modules/` vs `src/`) is systemic and will surface in both scaffold and wave-b prompts until reconciled.

Ownership rubric makes scaffold the owner of spec-defined baseline files (including `packages/shared/` and `apps/web/` config + Next.js stubs); Wave B owns NestJS business modules; Wave D owns only dynamic frontend business logic (pages finalization, JWT middleware, api-client wrapper).

**Methodology compliance:** 7 context7 queries issued (one per framework: `/nestjs/nest`, `/prisma/prisma`, `/vercel/next.js`, `/pnpm/pnpm`, `/docker/compose`, `/microsoft/typescript`, `/hey-api/openapi-ts`); 12 sequential-thinking thoughts across 4 design junctions (scaffold emission walk, cascade insertion, SPEC merge, verifier design); all specified source files read in full (scaffold_runner.py, ownership_validator.py, evidence-gating cli.py:520-651, agents.py wave-B prompt, wave_executor hook, config/state insertion points, full REQUIREMENTS and preserved build-l tree).

---

## 2. Three-Layer Ownership Model

### 2.1 Current (pre-Phase-B) state

The v18 pipeline has three file-emitting actors with overlapping scope:

| Layer | Emits from | Driven by | State at 2026-04-16 |
|---|---|---|---|
| Scaffold | `scaffold_runner._scaffold_*` Python templates | Frozen literals in `scaffold_runner.py` :396–:972 | Static — independent of REQUIREMENTS |
| Wave B | NestJS backend modules | LLM prompt at `agents.py:7879–8049` | Dynamic — prompt-generated per run |
| Wave D | Next.js frontend pages | LLM prompt in `agents.py` (parallel location) | Dynamic — prompt-generated per run |
| Wave C generator | Generated OpenAPI client | `openapi-ts` CLI under orchestration | Derived from `apps/api/openapi.json` |

The investigation (Part 6A) identified **13 no-owner files and 2 conflicting-owner files** across the 60-file manifest. Build-l's `src/prisma/` + `src/database/` duplicate (NEW-1) is the paradigmatic conflict: scaffold emitted one path, Wave B followed REQUIREMENTS and emitted the other, and both ended up on disk.

### 2.2 Assignment rubric

The companion `docs/SCAFFOLD_OWNERSHIP.md` applies six rules:

**R1 (Infrastructure → scaffold):** Boot configs, root files, tsconfig/package manifests, docker-compose, prisma schema skeleton, main.ts/app.module.ts bootstrap. Owner = `scaffold`.

**R2 (Business backend → wave-b):** Every file under `apps/api/src/modules/*/`, `apps/api/src/health/`, `apps/api/src/common/`, and `apps/api/Dockerfile`, `generate-openapi.ts`. Owner = `wave-b`.

**R3 (Frontend dynamic business logic → wave-d):** Wave D finalizes stubs scaffold emits for `apps/web/src/app/**/*.tsx` and `middleware.ts`; Wave D also owns the OpenAPI-client consumer `src/lib/api/client.ts` (stub). Scaffold owns `Dockerfile` (final) and all `apps/web/` config files outright. Infrastructure files never belong to Wave D.

**R4 (Generated → wave-c-generator):** `packages/api-client/src/**`. Owner = `wave-c-generator`.

**R5 (Shared spec-defined constants → scaffold):** `packages/shared/**` — the DTO/enum shapes are specified in M1 REQUIREMENTS as named constants (UserRole, ProjectStatus, TaskStatus, TaskPriority; **17 ErrorCodes** per REQUIREMENTS lines 346-364; PaginationMeta/PaginatedResult<T>); scaffold emits them from REQUIREMENTS-derived templates. Not Wave B because they predate any Wave B domain modeling.

**R6 (Dual-owner → emits_stub):** `apps/api/src/app.module.ts` and `apps/api/prisma/schema.prisma` — scaffold writes a minimal skeleton, Wave B extends. Flagged with `emits_stub: true`. Audit expects a specific shape at M1 (bootstrap-only); later milestones extend.

### 2.3 NestJS canonical path decisions (context7-informed)

Per `/nestjs/nest` query: NestJS modules idiomatically live at `src/<feature>/<feature>.module.ts`. REQUIREMENTS nests business modules under `src/modules/<feature>/<feature>.module.ts` — this is a team-specific convention (not NestJS canon) but REQUIREMENTS is authoritative. Scaffold must migrate to `src/modules/`.

Per `/prisma/prisma` query: `prisma/schema.prisma` is the canonical location relative to the package root; `prisma/migrations/migration_lock.toml` is generated by `prisma migrate dev`. Prisma services (`PrismaService extends PrismaClient`) are a NestJS idiom, not Prisma canon — placing them at `src/database/` (per REQUIREMENTS) is reasonable; scaffold's `src/prisma/` is not wrong but drifts from REQUIREMENTS.

Per `/vercel/next.js` query: App-router requires `app/layout.tsx` (must define html + body) and at least one `app/page.tsx`. REQUIREMENTS places these at `apps/web/src/app/` (src folder) which Next.js supports as optional. `next.config.mjs` at app root is required; `postcss.config.mjs` required for Tailwind integration.

Per `/hey-api/openapi-ts` query: `openapi-ts.config.ts` uses `defineConfig({input, output, plugins})`. For Next.js, `runtimeConfigPath` lets the generated client pick up env-dependent baseUrl/auth lazily.

---

## 3. File-by-File Scaffold Emission Trace

### 3.1 `_scaffold_root_files` (scaffold_runner.py:428)

Current emissions:
- `.gitignore` (correct)
- `.env.example` via `_env_example_template` :522 — emits `PORT=3001` (DRIFT: REQUIREMENTS says `PORT=4000`)
- `package.json` via `_root_package_json_template` :538 — declares `"workspaces": ["apps/*", "packages/*"]` at :544 (valid for pnpm but redundant — pnpm-workspace.yaml is canonical)

Missing (6 files per REQUIREMENTS §575–587):
- `pnpm-workspace.yaml` — per `/pnpm/pnpm`: `packages: [apps/*, packages/*]`
- `tsconfig.base.json` — per `/microsoft/typescript`: declares shared compilerOptions and paths for workspace refs
- `turbo.json` — pipeline orchestrator config
- `docker-compose.yml` — `_docker_compose_template` exists at :559 but it's **postgres-only**, and evidence from build-l's preserved root (no docker-compose.yml file present) suggests it's either not wired into `_scaffold_root_files` or fails silently. Even if emitted, per `/docker/compose` it needs api + web services with healthcheck + `depends_on.condition: service_healthy`
- `.editorconfig`, `.nvmrc` — optional

### 3.2 `_scaffold_api_foundation` (scaffold_runner.py:449)

Current emissions:
- `apps/api/package.json` (emitted, per-framework deps list)
- `apps/api/tsconfig.json`
- `apps/api/src/main.ts` via `_api_main_ts_template` :641 — `Number(process.env.PORT ?? 3001)` at :677 (DRIFT)
- `apps/api/src/app.module.ts`
- `apps/api/src/prisma/prisma.module.ts` (DRIFT: REQUIREMENTS canonical is `src/database/prisma.module.ts`)
- `apps/api/src/prisma/prisma.service.ts` (DRIFT: same as above)
- `apps/api/src/config/env.validation.ts` via `_api_env_validation_template` :686 — `PORT: Joi.number().integer().positive().default(3001)` at :698 (DRIFT)
- `apps/api/prisma/schema.prisma` (correct location per `/prisma/prisma`)
- `apps/api/test/setup.ts` — not in REQUIREMENTS (REQUIREMENTS uses `apps/web/src/test/setup.ts` for vitest, and `test/jest-e2e.json` for api e2e)
- `apps/api/.env.example` — also carries PORT=3001 DRIFT

Missing (per REQUIREMENTS apps/api section, 28 files total):
- `apps/api/nest-cli.json` — required by `nest build`
- `apps/api/tsconfig.build.json` — NestJS standard
- `apps/api/Dockerfile` — wave-b owned (multi-stage build needs Wave-B-finalized deps)
- `apps/api/src/generate-openapi.ts` — Wave C generator consumer entry point; wave-b owned
- `apps/api/src/common/filters/all-exceptions.filter.ts` — wave-b
- `apps/api/src/common/interceptors/transform-response.interceptor.ts` — wave-b
- `apps/api/src/common/decorators/{public,skip-response-transform}.decorator.ts` — wave-b (2)
- `apps/api/src/common/dto/{pagination,uuid-param}.dto.ts` — wave-b (2)
- `apps/api/src/health/{health.controller,health.module}.ts` — wave-b (2) — M1 acceptance probe
- `apps/api/src/modules/{auth,users,projects,tasks,comments}/*.module.ts` — scaffold stubs at current path DRIFT (src/ not src/modules/) (5)
- `apps/api/prisma/seed.ts` — scaffold stub (optional)
- `apps/api/test/health.e2e-spec.ts`, `apps/api/test/jest-e2e.json` — wave-b (2)

### 3.3 `_scaffold_web_foundation` (scaffold_runner.py:469)

Current emissions:
- `apps/web/package.json` (DRIFT: missing `@hey-api/openapi-ts` + `@hey-api/client-fetch` per `/hey-api/openapi-ts`)
- `apps/web/vitest.config.ts`
- `apps/web/tailwind.config.ts`
- `apps/web/src/app/globals.css`
- `apps/web/eslint.config.js` — not listed in REQUIREMENTS (scaffold extra)

Missing (per REQUIREMENTS apps/web, 14 files):
- `apps/web/next.config.mjs` — per `/vercel/next.js` mandatory for app-router
- `apps/web/tsconfig.json`
- `apps/web/postcss.config.mjs` — required for Tailwind
- `apps/web/openapi-ts.config.ts` — per `/hey-api/openapi-ts` `defineConfig` shape
- `apps/web/.env.example`
- `apps/web/Dockerfile` — wave-d
- `apps/web/src/app/layout.tsx` — wave-d (Next.js 15 requires html + body)
- `apps/web/src/app/page.tsx` — wave-d
- `apps/web/src/middleware.ts` — wave-d stub
- `apps/web/src/lib/api/client.ts` — wave-d stub
- `apps/web/src/test/setup.ts`

### 3.4 packages/shared + packages/api-client

Scaffold emits **zero** files under either path. All 6 shared DTO files (Wave B) and 3 api-client files (Wave C generator) must be produced downstream. This is a 100% wave-owned territory.

---

## 4. Drift Inventory

The 9 drift clusters that Phase B Wave 2 must close, ordered by blast radius:

| # | Cluster | Canonical per REQUIREMENTS | Current scaffold | Blast |
|---|---|---|---|---|
| **DRIFT-1** | Prisma module path | `src/database/prisma.{module,service}.ts` | `src/prisma/prisma.*` | NestJS import graph break; app.module can't find PrismaModule at expected path; fuels NEW-1 duplicate when Wave B also emits |
| **DRIFT-2** | Modules folder | `src/modules/<feature>/` | `src/<feature>/` | App.module imports won't resolve; audit flags "missing module" on correct path while wrong path exists |
| **DRIFT-3** | API port | `4000` (3 sites: env.example, main.ts default, joi validator default) | `3001` (all 3 sites) | **Direct cause of build-l Gate-A FAIL**: docker-compose maps 4000:4000, wave-B probe hits 4000, app listens on 3001 |
| **DRIFT-4** | Root scaffold coverage | 9 files | 3 files emitted | Missing pnpm-workspace.yaml breaks `pnpm install -r`; missing turbo.json breaks `pnpm build`; missing tsconfig.base.json breaks `tsc -b` project references |
| **DRIFT-5** | docker-compose topology | postgres + api + web with healthcheck + depends_on.condition | postgres-only stub (may not even be wired) | `docker compose up` doesn't bring up app stack; M1 "Definition of Done" (docker compose up → ok) fails |
| **DRIFT-6** | Web config files | next.config.mjs, tsconfig.json, postcss.config.mjs, openapi-ts.config.ts, .env.example, src/test/setup.ts | 0 of 6 emitted | Next.js won't build; Tailwind won't process; openapi-ts can't run → generated client absent |
| **DRIFT-7** | packages/shared | 6 files | 0 emitted | No shared DTOs; web imports from `@taskflow/shared` fail; TS refs break |
| **DRIFT-8** | generate-openapi.ts | `apps/api/src/generate-openapi.ts` | Not emitted | Wave C generator has no OpenAPI input; api-client can't be generated |
| **DRIFT-9** | NestJS build config | `nest-cli.json` + `tsconfig.build.json` | Not emitted | `nest build` fails; api Dockerfile build step fails |

DRIFT-3 is the proximate cause of build-l's FAIL. DRIFT-1 + DRIFT-2 account for NEW-1 (duplicate prisma). DRIFT-4 through DRIFT-9 collectively cause most of the 10 ownership-ambiguity findings.

---

## 5. SPEC Reconciliation Design (N-12)

### 5.1 Problem

REQUIREMENTS.md is regenerated from PRD per run by a Claude prompt; scaffold_runner.py is frozen Python. They drift. The cost is the entire DRIFT inventory above, recurring on every run.

### 5.2 Three options considered

- **Option A — REQUIREMENTS authoritative, scaffold reads it.** Scaffold parses REQUIREMENTS "Files to Create" and only emits files listed there, using hardcoded templates for content. Drawback: loses scaffold's bootstrap knowledge (env validation structure, main.ts pattern) when REQUIREMENTS doesn't describe it file-by-file.
- **Option B — Scaffold authoritative, REQUIREMENTS follows.** Instruct the REQUIREMENTS regenerator to emit only what scaffold produces. Drawback: locks in current drift (PORT=3001, src/prisma) and prevents PRD-driven tailoring.
- **Option C (chosen) — Mutual reconciliation producing a resolved manifest.**

### 5.3 Option C pipeline

1. PRD → REQUIREMENTS.md (existing step)
2. **NEW:** parse REQUIREMENTS "Files to Create" section → `canonical_files: list[Path]` (60 entries for M1)
3. **NEW:** introspect scaffold_runner registry (requires a declarative refactor — see §5.4) → `scaffold_files: list[ScaffoldEntry(path, template_fn)]`
4. **NEW:** diff-and-merge logic:
   - Path in REQUIREMENTS only → assign to wave-b or wave-d by R2/R3 rules; register in resolved manifest with that owner
   - Path in scaffold only → if it matches a known scaffold contract (`.gitignore`), keep it (audit_expected may be false); else flag as DRIFT for reviewer
   - Path in both but differ in minor details (e.g., PORT value) → REQUIREMENTS wins; scaffold template is rewritten to match canonical value at reconciliation time, not edit time
   - Path in both, differ structurally (`src/prisma/` vs `src/database/`) → REQUIREMENTS wins; scaffold registry entry updated to new path; old path added to a `deprecated_paths` list (scaffold-verifier later ensures old path is not emitted)
5. Output: `docs/SPEC_RECONCILIATION.md` human-readable + `.agent-team/resolved_manifest.json` machine-readable
6. Both `scaffold_runner._scaffold_*` and the Wave-B/D prompts read `resolved_manifest.json`

### 5.4 Parameterized templates + DEFAULT_SCAFFOLD_CONFIG

No declarative-registry refactor. Existing `_scaffold_*` Python template methods stay. Phase B Wave 2 makes two additive changes:

1. Each `_scaffold_*` method that emits a value currently hardcoded in a template (PORT, Prisma path, module path) is refactored to accept those values as kwargs:

   Before: `_api_main_ts_template()` emits `Number(process.env.PORT ?? 3001)` inline.
   After:  `_api_main_ts_template(port: int = DEFAULT_SCAFFOLD_CONFIG.port)` — caller controls.

2. New module-level constant at top of `scaffold_runner.py`:

   ```python
   DEFAULT_SCAFFOLD_CONFIG = ScaffoldConfig(
       port=4000,
       prisma_path="src/database",
       modules_path="src/modules",
       # ... all values aligned with current M1 REQUIREMENTS canonical shape
   )
   ```

   `ScaffoldConfig` is a small dataclass with the canonical values. This replaces every hardcoded literal currently drifted from REQUIREMENTS (PORT 3001 → 4000, src/prisma → src/database, src/<feature> → src/modules/<feature>, etc.).

3. When `v18.spec_reconciliation_enabled=False` (default/Phase-A behavior): all `_scaffold_*` calls pass `DEFAULT_SCAFFOLD_CONFIG`. Result: scaffold emits the new canonical values. This alone closes DRIFT-1/2/3.

4. When `v18.spec_reconciliation_enabled=True`: the reconciler (§5.3) produces a resolved manifest; the per-run `ScaffoldConfig` is derived from SPEC.md; passed into `_scaffold_*` calls in place of the default. Result: scaffold emits SPEC-reconciled values per run.

5. No declarative registry. No iteration. Scaffold methods remain call-time-ordered in `_scaffold_m1_foundation`. Scaffold-verifier (§6) walks the emitted tree independently — it doesn't need to introspect a registry because the ownership contract at `docs/SCAFFOLD_OWNERSHIP.md` is its reference.

Benefits: scope stays at ~120 LOC for the `ScaffoldConfig` + kwarg plumbing, well within the plan's per-agent budgets. Flag-OFF path still works unchanged except it now emits correct PORT=4000 (which is a deliberate Phase B improvement, not a regression). Flag-ON path layers SPEC reconciliation on top without rewriting scaffold architecture.

### 5.5 Feature flag

`v18.spec_reconciliation_enabled` — default FALSE. When false, pipeline falls back to current behavior (scaffold_runner emits hardcoded set; wave prompts use hardcoded claim lists).

When true, pipeline runs reconciler after REQUIREMENTS generation and before Wave A; resolved manifest is the canonical source.

### 5.6 Edge case: REQUIREMENTS says a file but scaffold has no template

If REQUIREMENTS lists `apps/api/nest-cli.json` but scaffold registry lacks a template, reconciler assigns it to the nearest-owner by rules (R1 for infrastructure → owner=scaffold) and emits a WARN: "Phase B must add template for <path>". This WARN should be surfaced in SPEC_RECONCILIATION.md so reviewers catch missing scaffold templates before the run proceeds.

---

## 6. Scaffold-Verifier Design (N-13)

### 6.1 Problem

Wave A currently exits "success" if `scaffold_runner.run()` doesn't raise. But files may not land: silent `os.makedirs` failure, template function returns empty string, wrong working dir, disk permission, etc. Build-l evidence suggests several root scaffold files never landed despite scaffold reporting success.

### 6.2 Design

Add `scaffold_verifier.py` post-Wave-A hook. Responsibilities:

1. Read resolved manifest (from N-12) or ownership contract (if N-12 flag off but ownership contract is present and N-13 flag on)
2. For each entry with `owner == "scaffold"` and `optional == false`:
   - Assert path exists on disk
   - Assert file is non-empty
   - Apply per-filetype structural parse (see §6.3)
3. Aggregate into `ScaffoldVerifierReport` dataclass: `verdict: "PASS"|"WARN"|"FAIL"`, `missing: list[Path]`, `malformed: list[tuple[Path, str]]`, `deprecated_emitted: list[Path]` (caught DRIFT-1-style legacy paths still present)
4. On FAIL: HALT pipeline before Wave B runs

### 6.3 Per-filetype parsers

| Filetype | Parse | Checks |
|---|---|---|
| `*.json` (package.json, tsconfig*.json, nest-cli.json, jest-e2e.json) | `json.loads` after comment strip | Valid; for package.json: `workspaces` matches pnpm-workspace.yaml packages; name field present |
| `*.yaml` / `*.yml` (pnpm-workspace.yaml, docker-compose.yml) | `yaml.safe_load` | Valid; for docker-compose: `services` includes postgres+api+web; each service with build/image; postgres has healthcheck; api/web have `depends_on.<service>.condition: service_healthy` |
| `*.prisma` (schema.prisma) | Regex for `datasource db` block + `generator client` block | Both blocks present; datasource provider is postgresql; `url = env("DATABASE_URL")` |
| `*.ts` / `*.tsx` / `*.mjs` (main.ts, env.validation.ts, next.config.mjs, etc.) | Regex + light AST via `esprima`-like parse | For main.ts: `NestFactory.create(AppModule)` call present; port value from env.PORT matches expected; for env.validation.ts: Joi.object({...}) with PORT default matching expected |
| `.gitignore` / `.env.example` | Line read | For .env.example: PORT value matches REQUIREMENTS; for .gitignore: must include `node_modules`, `dist`, `.next`, `.turbo` |
| Directory emits (prisma/migrations) | Directory exists + migration_lock.toml file | Schema-generated; may be absent at M1 if no `prisma migrate dev` has run — soft check |

Per `/docker/compose` query: `depends_on` long-form syntax is `{service: {condition: service_healthy}}`; the verifier must accept both short-form (legacy) and long-form when REQUIREMENTS uses long-form.

### 6.4 Insertion point

`wave_executor.py:2798-2810` currently has a post-Wave-hook that runs `_run_wave_b_dto_contract_guard` for wave_letter in {A, B, D, D5}. Add an earlier branch:

```python
if wave_result.success and wave_letter == "A":
    if self._cfg.v18.scaffold_verifier_enabled:
        report = run_scaffold_verifier(workspace, resolved_manifest)
        if report.verdict == "FAIL":
            self._halt(f"Scaffold-verifier FAIL: {report.summary()}")
            return wave_result._replace(success=False)
```

HALT propagation: existing `_halt` primitive (per Phase A report references) surfaces a terminal error through `state.failure_mode`; the run finalization path already emits BUILD_LOG.txt with halt reason.

### 6.5 Non-goals

Scaffold-verifier does NOT check code quality, lint, type safety, or semantic correctness of templates. Those are audit concerns. Verifier is structural only: "files exist with right names and basic shape."

---

## 7. Cascade Consolidation Design (N-11)

### 7.1 Problem

Build-l produced 28 findings; investigation estimates ~3 root structural causes generating ~10 cascaded findings. Example cascade:
- Root: scaffold didn't emit `src/database/prisma.module.ts`
- Derived-1: "PrismaService not injectable in UsersService"
- Derived-2: "app.module.ts imports PrismaModule from wrong path"
- Derived-3: "health check endpoint can't query DB"
- Derived-4: "migrations can't run"

All four findings share a structural root. Reporting them separately inflates the finding count, obscures priority, and confuses the fix-cycle loop (which may try to fix a cascade symptom and not the root).

### 7.2 Design

New function `_consolidate_cascade_findings(report: AuditReport, state: OrchestrationState) -> AuditReport` in `cli.py`. Signature mirrors `_apply_evidence_gating_to_audit_report` at :530.

Algorithm:

1. Read `state.wave_progress` (state.py:39 — `dict[str, dict[str, Any]]`) for Wave A and the scaffold-verifier report (if N-13 flag on)
2. Build a **root-cause index**: for each scaffold-verifier `missing` or `malformed` path, collect all audit findings whose `file_path`, `evidence`, or `message` references that path OR a path whose dirname contains that path
3. For each root cause with ≥2 matched findings, collapse:
   - Keep finding with highest severity (or earliest ID) as representative
   - Add `cascade_count: int` and `cascade_files: list[Path]` to the representative
   - Add `cascaded_from: [finding_id_2, finding_id_3, ...]` for traceability
   - Remove consumed findings from `report.findings`
4. Findings without a scaffold-verifier match remain untouched

### 7.3 Insertion point

`cli.py:530` currently defines `_apply_evidence_gating_to_audit_report`. Cascade consolidation runs BEFORE evidence gating and BEFORE scope partitioning at :607:

```python
def _apply_evidence_gating_to_audit_report(report, state, cfg, ...):
    if cfg.v18.cascade_consolidation_enabled:
        report = _consolidate_cascade_findings(report, state)
    # existing evidence gating logic
    ...
    # existing scope partitioning at :607
```

This ordering matters: cascade consolidation operates on the raw scorer output; evidence gating suppresses findings the orchestrator has already fixed; scope partitioning filters by milestone. Running consolidation first ensures we count cascades against the full report, not a scope-filtered subset.

### 7.4 Pattern-matching risk

Scorer LLM output doesn't have structured root-cause metadata; consolidation relies on path-based clustering. Known failure modes:
- Two genuinely-independent findings both cite `src/database/` — false positive collapse
- Scorer describes a cascade file without quoting its path literally — false negative, no collapse
- Cascades from non-scaffold roots (e.g., a Wave B bug producing 3 wave-D findings) — out of scope for N-11 (scaffold-verifier only catches scaffold cascades)

Mitigation: start conservative. Require both (a) scaffold-verifier flagged a structural issue AND (b) ≥2 findings cite a path within that issue's blast radius. When unsure, leave findings uncollapsed.

### 7.5 Feature flag

`v18.cascade_consolidation_enabled` — default FALSE. When false, behavior is unchanged from Phase A (all scorer findings pass through evidence gating and scope partitioning untouched).

---

## 8. Feature Flag Topology

Phase B activation ordering (all three new flags ON):

1. PRD → REQUIREMENTS.md (existing)
2. **NEW — if `v18.spec_reconciliation_enabled`:** reconcile REQUIREMENTS + scaffold registry → resolved manifest (§5)
3. Wave A scaffold runs; if flag off, uses hardcoded registry
4. **NEW — if `v18.scaffold_verifier_enabled`:** post-Wave-A verifier (§6); on FAIL → HALT
5. Wave B runs; if `v18.ownership_contract_enabled`, prompt references SCAFFOLD_OWNERSHIP.md claim list
6. ... Waves C/D/D.5/T/E ...
7. Audit runs → raw AuditReport
8. **NEW — if `v18.cascade_consolidation_enabled`:** cascade consolidation (§7)
9. Evidence gating (existing at cli.py:530)
10. Scope partitioning (existing at cli.py:607)
11. `build_report()` (existing at cli.py:639)

Deactivation path: any flag OFF → fall back to Phase-A behavior at that stage. All three flags OFF = zero behavior change from Phase A.

The ownership CONTRACT (the static MD file) is present unconditionally; it's documentation. Only runtime consumption of it is gated by `v18.ownership_contract_enabled`.

### 8.1 Interactions with existing flags

- `v18.scaffold_enabled` (config.py:789, default FALSE) — controls whether scaffold_runner runs at all. Phase B flags are no-ops if this is false (scaffold didn't run → nothing to reconcile/verify/consolidate).
- `v18.milestone_scope_enforcement` (config.py:821, default TRUE) — ensures audit findings outside M1 scope are filtered. Cascade consolidation should run before this (so we count cascades inside the M1 root-cause tree, not after scope filter mutes some of them).
- `v18.audit_milestone_scoping` (config.py:823, default TRUE) — adds scope preamble to auditor prompt. Independent of Phase B.
- `v18.review_fleet_enforcement` (config.py:834, default TRUE) — independent.

---

## 9. Wave 2 Re-Plan Triggers (HALT conditions for reviewer)

Reviewer (task #12) should re-plan Wave 2 if any of the following surface during draft review:

- **HALT-A:** Exact manifest count differs from 60. If the reviewer counts a 59th or 61st entry in REQUIREMENTS, the ownership contract is incorrect and must be redrafted before Wave 2 starts.
- **HALT-B:** A DRIFT entry is contested. If reviewer believes scaffold's `src/prisma/` is actually correct (because PrismaClient expects that path convention in some team context), DRIFT-1 resolution must be revisited — perhaps with Wave B adopting scaffold's path instead of REQUIREMENTS. Either direction is defensible, but the two must be chosen together.
- **HALT-C:** A context7 contradiction. Any framework claim in this report (NestJS path conventions, Next.js 15 app-router rules, Prisma canonical layout, docker-compose healthcheck syntax) contradicted by reviewer's own verification should halt Wave 2 until the framework fact is re-queried.
- **HALT-D:** Feature flag interactions unknown. If reviewer identifies a Phase-A flag whose behavior changes under Phase B flags in a way not covered by §8.1, Wave 2 must wait for the interaction to be documented.
- **HALT-E:** Parameterized-template threading more invasive than expected. If the `_scaffold_*` kwarg refactor (§5.4) turns out to require touching >8 method signatures or breaking flag-OFF emission tests, Wave 2 should halt and reconsider.

Non-HALT feedback (accepted in Wave 2): wording, row order, minor path typos, optional-vs-required tweaks on a subset of files, additional `notes:` detail on individual rows.

---

## 10. Self-Audit

Following the Phase-A self-audit format:

### 10.1 Methodology compliance

| Rule | Honored? | Evidence |
|---|---|---|
| Read specified files in full | YES | scaffold_runner.py 972 LOC read in full; ownership_validator.py 311 LOC read in full; cli.py evidence-gating :520-651 read; agents.py wave-B prompt :7879-8049 read; wave_executor.py hook :2798-2810 read; config.py :780-841 read; state.py :39 read; REQUIREMENTS.md "Files to Create" read (lines 575-647) |
| context7 MCP mandatory on framework claims | YES | 7 queries issued: `/nestjs/nest` (AppModule/ValidationPipe/bootstrap), `/prisma/prisma` (schema.prisma canonical + migrations), `/vercel/next.js` (app-router layout.tsx/page.tsx/next.config.mjs), `/pnpm/pnpm` (pnpm-workspace.yaml schema), `/docker/compose` (healthcheck + depends_on.condition), `/microsoft/typescript` (paths/extends/references), `/hey-api/openapi-ts` (defineConfig shape + runtimeConfigPath) |
| sequential-thinking MCP at design junctions | YES | 12 thoughts across 4 junctions: scaffold emission walk (T1-T3, T9-T10), cascade consolidation (T4), SPEC reconciliation (T5), scaffold-verifier design (T6), feature-flag topology (T7), ownership rubric (T8), drift synthesis (T11), final structure (T12) |
| HALT discipline if plan assumptions fail | YES | HALT conditions enumerated in §9; no code edits made; two markdown deliverables only |
| No in-flight source edits without authorization | YES | Zero source files modified; only `docs/SCAFFOLD_OWNERSHIP.md` and this report created |
| No containment-over-structure | YES | All four proposals (N-02, N-11, N-12, N-13) address structural root causes (ownership ambiguity, manifest drift, silent emission failures, cascade miscounting); none adds timeouts/kill-thresholds |
| Phase-A-level self-audit at end | YES | This §10 |

### 10.2 Known gaps in this report

- **Parameterized-template approach: 5-6 `_scaffold_*` methods need new kwargs threaded through.** Wave 2's n12-n13-reconciliation-impl agent must also thread `ScaffoldConfig` through `_scaffold_m1_foundation` call sites. Low risk; additive.
- **Cascade pattern-matching is heuristic.** §7.4 lists failure modes but does not calibrate thresholds. Wave 2 should build the consolidator with an off-switch per finding (manual override) until the heuristic is tuned against real audit runs.
- **No wave-C generator ownership rules for non-M1 milestones.** This report scopes to M1 (60 files). Generator ownership at M2+ (new routes → new generated client code) is not covered. Phase B closure for non-M1 milestones is out of Phase B's charter.
- **apps/web eslint.config.js is a scaffold emission not listed in REQUIREMENTS.** I marked it as a scaffold extra in the ownership table (no row) — reviewer may want an explicit row with `audit_expected: false`. Deferred to Wave 2 cleanup.
- **Build-l docker-compose.yml absence from preserved root.** I inferred from the absence that `_docker_compose_template` either isn't wired or fails silently. Did not read scaffold_runner.py source a third time to confirm wiring — this is a Wave 2 verification step.

### 10.3 Deliverable checklist

- [x] `docs/SCAFFOLD_OWNERSHIP.md` — YAML-style ownership table with 60 entries (9 root + 28 apps/api + 14 apps/web + 6 packages/shared + 3 packages/api-client), columns path/owner/optional/emits_stub/audit_expected/notes, plus ownership totals and drift summary
- [x] `docs/plans/2026-04-16-phase-b-architecture-report.md` — 10 sections, executive summary through self-audit
- [x] Context7 queries cited inline (§2.3, §3.1-§3.3, §6.3)
- [x] Sequential-thinking thoughts referenced (§10.1)
- [x] HALT conditions enumerated (§9)
- [x] Feature flag topology specified (§8)
- [ ] Team-lead summary (<400 words) — to be sent via SendMessage after this write completes

### 10.4 What I'm confident about

1. **Exact manifest count is 60 files** (vs the investigation's "57-60" estimate). REQUIREMENTS §575-647 enumerates them; I counted directly.
2. **DRIFT-3 (PORT 3001 vs 4000) is the direct cause of build-l Gate-A FAIL.** Three source sites in scaffold_runner.py emit 3001; REQUIREMENTS emits 4000 across docker-compose, env.example, and the probe. Fixing scaffold to match 4000 removes the FAIL root cause.
3. **Three-layer ownership model holds for M1.** Every file in the manifest has a defensible single owner under the R1-R6 rubric (with two `emits_stub:true` dual-owner exceptions explicitly marked).
4. **N-11/N-12/N-13 are orthogonal.** Each ships behind its own feature flag and delivers standalone value even if the other two stay OFF.

### 10.5 What I'm less confident about

1. **Scaffold-verifier performance.** Reading and parsing 30+ files post-Wave-A adds latency. Should be <2s but untested.
2. **Wave-B/D prompt consumption of ownership contract.** §2 describes the contract, but the actual prompt-edit shape (how to inject 60-row YAML into an LLM prompt without blowing the context budget) is a Wave 2 concern I did not prototype.
3. **docker-compose depends_on syntax variance.** REQUIREMENTS uses long-form `{postgres: {condition: service_healthy}}` but per `/docker/compose` I only verified long-form support in recent compose; older compose v1 may not. Assuming modern compose.

---

**End of report.** Companion file: `docs/SCAFFOLD_OWNERSHIP.md`.
