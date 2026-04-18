# Phase B Wiring Verification

**Author:** Wave 3 `phase-b-wiring-verifier`
**Date:** 2026-04-16
**Branch:** `phase-a-foundation`
**Input:** Wave 2 edits applied; preserved artifacts in `v18 test runs/build-l-gate-a-20260416/` and offline replays in `v18 test runs/session-B-validation/`.
**Scope:** Read-only verification that each Phase B change reaches the production call path, and that the six Phase B feature flags are each wired through code (default OFF, and with a traceable True branch).

---

## 1. Executive summary

**Overall verdict:** PASS with three non-HALT observations.

All six Phase B feature flags (`ownership_contract_enabled`, `spec_reconciliation_enabled`, `scaffold_verifier_enabled`, `cascade_consolidation_enabled`, `duplicate_prisma_cleanup_enabled`, `template_version_stamping_enabled`) are declared, default to `False` in `config.py`, are round-tripped through `AgentTeamConfig.from_yaml`, and are read at exactly the expected production consumer sites. Flag-OFF leaves the pipeline byte-compatible with the pre-Phase-B behavior; flag-ON activates the N-02/N-12/N-13/N-11/NEW-1/NEW-2 logic at the insertion points called out in `docs/plans/2026-04-16-phase-b-architecture-report.md`.

Offline replays of the three highest-risk hooks (N-11 cascade, NEW-1 cleanup, and the scaffold dump) against `build-l-gate-a-20260416` confirm:

- **N-11 cascade:** algorithm correctness validated on synthetic path-bearing input (6 → 4 collapse). The build-l replay collapsed 0-of-28 because the preserved report is in **scorer-shape** (`file` + `description` raw keys); this is a pre-existing `AuditFinding.from_dict` coverage gap — **not** a N-11 wiring defect (out-of-scope finding OOS-1 below).
- **NEW-1 duplicate Prisma cleanup:** all four scenarios PASS (happy path removes stale `apps/api/src/prisma/`, flag-OFF no-op, safety check blocks cleanup when canonical is incomplete, empty-stale is a no-op).
- **Scaffold dump:** Phase B scaffold emits 38 files (build-l had 68 of which 40 were later Wave B/D additions). DRIFT-1 canonical-path correction (`src/prisma/` → `src/database/`) and DRIFT-3 PORT `4000` are confirmed at every emitted site.

Three observations not gated as HALT:

- **OOS-1** `audit_models.AuditFinding.from_dict` does not map scorer-shape `file` / `description` keys into `evidence[]`, which blunts N-11 cascade collapse on scorer-raw input. Severity: MEDIUM. Not in Phase B scope (falls under a future audit-plumbing fix).
- **OOS-2** `docs/SCAFFOLD_OWNERSHIP.md` comment "all 13 emits_stub=true rows have owner=scaffold" is mis-stated: two stub rows legitimately belong to other owners (`apps/web/src/lib/api/client.ts` → wave-d; `packages/api-client/src/index.ts` → wave-c-generator). The primary contract counts (60 / 44 / 12 / 1 / 3 / 13) all match. This is a doc tweak, not a schema drift.
- **OOS-3** The scaffold currently does NOT emit the per-module NestJS stubs (`auth.module.ts`, `users/`, `projects/`, `tasks/`, `comments/`) nor `nest-cli.json` / `tsconfig.build.json`, even though `SCAFFOLD_OWNERSHIP.md` lists them as scaffold-owned. They live in templates that were not wired into `_scaffold_nestjs` during Wave 2. Severity: MEDIUM. Flagged for Wave 4 gap-closure, not HALT: flag-OFF pipeline is unaffected and Wave B can still synthesize them under the existing owner rules.

None of the HALT conditions (`HALT-A` through `HALT-F` in the verifier task spec) triggered.

---

## 2. Summary verdict matrix

| Change | Flag | Flag default | Consumer file:line | V1 (OFF) | V2 (ON trace) | Replay | Verdict |
|--------|------|--------------|--------------------|----------|---------------|--------|---------|
| N-02 ownership contract | `ownership_contract_enabled` | `False` | `scaffold_runner.py:349`, `agents.py:7892`, `audit_team.py:292` | identity no-op | loads `docs/SCAFFOLD_OWNERSHIP.md`, renders `[FILES YOU OWN]`, emits optional-suppression prompt block, validates emission set | V5 parser: 60 rows + owner counts match | **PASS** (OOS-2 doc nit) |
| N-12 spec reconciliation | `spec_reconciliation_enabled` | `False` | `wave_executor.py:3331` | `resolved_scaffold_cfg=None` → `DEFAULT_SCAFFOLD_CONFIG` | `_maybe_run_spec_reconciliation` writes `SPEC.md` / `resolved_manifest.json`; returns `ScaffoldConfig` threaded into `run_scaffolding(scaffold_cfg=…)` | — | **PASS** |
| N-13 scaffold verifier | `scaffold_verifier_enabled` | `False` | `wave_executor.py:3510` | hook never called | post-Wave-A: `_maybe_run_scaffold_verifier` runs; FAIL verdict flips `wave_result.success=False` + writes `scaffold_verifier_report.json` | — | **PASS** |
| N-11 cascade consolidation | `cascade_consolidation_enabled` | `False` | `cli.py:644` (guard), `cli.py:743` (call site) | `return report` identity; report `is` unchanged | reads `scaffold_verifier_report.json`, clusters findings per root, ≥2-match collapses, appends `F-CASCADE-META` | V3 synthetic: 6 → 4 (PASS); build-l: 28 → 28 (OOS-1 coverage gap) | **PASS with OOS-1** |
| NEW-1 duplicate-prisma cleanup | `duplicate_prisma_cleanup_enabled` | `False` | `wave_executor.py:953` (guard); call sites `:3034` (Wave B) + `:3487` (Wave D5) | function returns `[]` immediately | stale `apps/api/src/prisma/` removed iff canonical `src/database/prisma.{module,service}.ts` both exist non-empty | V4: 4/4 scenarios PASS | **PASS** |
| NEW-2 template version stamping | `template_version_stamping_enabled` | `False` | `scaffold_runner.py:301` (set), `:748` (consume), `:331` (restore) | `_TEMPLATE_VERSION_STAMPING_ACTIVE` stays `False` → content unchanged | module flag set `True` for one `run_scaffolding` call; `_write_if_missing` prepends `// scaffold-template-version: 1.0.0` (or `#` form) to `.ts/.py/.yaml/.env` files | — | **PASS** |

---

## 3. V1 — Flag-OFF baseline

**Method:** read each consumer site and confirm that the False branch is byte-identical to the pre-Phase-B path.

### 3.1 `ownership_contract_enabled=False`

- `scaffold_runner.py:349` — `_maybe_validate_ownership` early-returns when `v18 is None or not getattr(v18, "ownership_contract_enabled", False)`. No contract load, no warn log.
- `agents.py:7892` — `_format_ownership_claim_section` returns `[]`. Wave B/D prompt builders (`build_wave_b_prompt` at `agents.py:~8077` and `build_wave_d_prompt` at `agents.py:~8777`) unconditionally `parts.extend(lines)`; an empty list is a no-op, so the prompt text is byte-identical.
- `audit_team.py:292` — `_build_optional_suppression_block` returns `""`. The auditor prompt suffix is the empty string.

No file IO, no logging, no prompt delta. Matches pre-Phase-B behavior.

### 3.2 `spec_reconciliation_enabled=False`

- `wave_executor.py:3331` — gate uses `_get_v18_value(config, "spec_reconciliation_enabled", False)`. When False, `resolved_scaffold_cfg` stays `None`. The subsequent call `_run_pre_wave_scaffolding(…, scaffold_cfg=resolved_scaffold_cfg)` threads `None` into `run_scaffolding`, which in turn falls through to `DEFAULT_SCAFFOLD_CONFIG` at `scaffold_runner.py:284` (`cfg = scaffold_cfg if scaffold_cfg is not None else DEFAULT_SCAFFOLD_CONFIG`).
- **No side effect:** `_maybe_run_spec_reconciliation` is not invoked; no `SPEC.md`, no `resolved_manifest.json`, no `RECONCILIATION_CONFLICTS.md` written.

### 3.3 `scaffold_verifier_enabled=False`

- `wave_executor.py:3507-3511` — short-circuit guard reads `_get_v18_value(config, "scaffold_verifier_enabled", False)`. Flag-OFF means `_maybe_run_scaffold_verifier(cwd=cwd)` is never called. No `.agent-team/scaffold_verifier_report.json` is produced, and `wave_result.success` is determined solely by the pre-Phase-B `compile_result.passed` AND DTO/Frontend-guard booleans.

### 3.4 `cascade_consolidation_enabled=False`

- `cli.py:644` — guard: `if not _cascade_consolidation_enabled(config) or not cwd: return report`. This returns the **same `AuditReport` object** (identity, not just equality) — confirmed in V3 replay (`unchanged is report == True`).
- V3 offline replay with `cascade_consolidation_enabled=False` on the build-l `AUDIT_REPORT.json` (28 scorer findings) reported `findings after consolidation (flag=OFF): 28` and `identity-preserving (report is report): True`.

### 3.5 `duplicate_prisma_cleanup_enabled=False`

- `wave_executor.py:953` — `_maybe_cleanup_duplicate_prisma` returns `[]` immediately when `_duplicate_prisma_cleanup_enabled(config)` is falsy. Both insertion points (`:3034` Wave B post-compile, `:3487` Wave D5 late) get the empty list.
- V4 offline replay FLAG-OFF scenario: seeded stale `apps/api/src/prisma/` + canonical `apps/api/src/database/`; after call: both trees untouched (5 files before, 5 files after, removed list `[]`).

### 3.6 `template_version_stamping_enabled=False`

- `scaffold_runner.py:301` — `_TEMPLATE_VERSION_STAMPING_ACTIVE = bool(getattr(v18, "template_version_stamping_enabled", False))`. With the flag off, the module-level bool stays False.
- `scaffold_runner.py:748` — `if _TEMPLATE_VERSION_STAMPING_ACTIVE: payload = _stamp_version(content, path.suffix)`. Falsy short-circuit → `payload = content` → `path.write_text(payload, …)` writes the untouched template.
- Byte-identical scaffold emission confirmed in V6 dump against build-l: no `scaffold-template-version:` line appears in any emitted file.

V1 verdict: **PASS** across all six flags.

---

## 4. V2 — Flag-ON behavior trace

**Method:** for each flag set to `True` (one at a time), trace via code reading what the True branch does and which artifact / side-effect is produced. No runtime execution.

### 4.1 `ownership_contract_enabled=True`

| Consumer | File:line | True-branch effect |
|----------|-----------|---------------------|
| Wave B/D prompt injection | `agents.py:7902-7906` | Append `[FILES YOU OWN]` section with one line per contract row (`- <path>[  # stub]`). `build_wave_b_prompt` extends `parts` at `agents.py:~8077`; `build_wave_d_prompt` at `:~8777`. |
| Auditor prompt suffix | `audit_team.py:302-315` | Append `## Ownership Contract — Optional Files (N-02)` suffix listing all `optional: true` rows (e.g., `.editorconfig`, `.nvmrc`). Prevents auditors from raising missing-file findings on those paths. |
| Scaffold post-emission validation | `scaffold_runner.py:358-380` | Compute `missing = expected - emitted` (scaffold-owned, non-optional) and `unexpected = emitted-owned-by-non-scaffold`. Emit `logger.warning` for each drift. **Soft invariant** — no exception, no wave failure. |

All three consumers rely on `load_ownership_contract()` at `scaffold_runner.py:94-149`. V5 replay confirms the parser yields the expected counts (60/44/12/1/3/13). Only cache is module-local (`@lru_cache` wrapping `_load_contract_from_disk`).

### 4.2 `spec_reconciliation_enabled=True`

Consumer: `wave_executor.py:3331-3342` inside `_execute_milestone_waves_with_stack_contract` when `scaffolding_start_wave == wave_letter and not scaffolding_completed`.

True-branch call chain:

```
wave_executor.py:3333   _maybe_run_spec_reconciliation(cwd=cwd, milestone_id=result.milestone_id)
wave_executor.py:841    reconcile_milestone_spec(
                            requirements_path=.agent-team/milestones/<id>/REQUIREMENTS.md,
                            prd_path=.agent-team/PRD.md (or cwd/PRD.md),
                            stack_contract=dict from stack_contract.load_stack_contract,
                            ownership_contract=load_ownership_contract(),
                            milestone_id=<id>,
                            output_dir=.agent-team/milestones/<id>,
                        )
milestone_spec_reconciler.py  resolve PORT / Prisma path / shared package / etc.;
                              write SPEC.md + resolved_manifest.json;
                              on conflicts: write RECONCILIATION_CONFLICTS.md;
                              return ReconciliationResult(resolved_scaffold_config=ScaffoldConfig(...))
wave_executor.py:3343   _run_pre_wave_scaffolding(run_scaffolding, ir, cwd, milestone,
                                                  scaffold_cfg=resolved_scaffold_cfg)
scaffold_runner.py:284  cfg = scaffold_cfg if scaffold_cfg is not None else DEFAULT_SCAFFOLD_CONFIG
```

Defensive handling: `except Exception as exc` at `wave_executor.py:3337-3342` demotes any reconciler crash to `logger.warning` + fallback to `DEFAULT_SCAFFOLD_CONFIG`. Aligns with architecture report §5 "flag-OFF safety" guarantee.

### 4.3 `scaffold_verifier_enabled=True`

Consumer: `wave_executor.py:3507-3516` — only fires when `wave_letter == "A" AND compile_result.passed AND flag ON`. Sequence:

```
wave_executor.py:3512   verifier_error = _maybe_run_scaffold_verifier(cwd=cwd)
wave_executor.py:875    report = run_scaffold_verifier(workspace=Path(cwd),
                                                        ownership_contract=…)
scaffold_verifier.py:63  enumerate scaffold-owned rows;
                         classify each as present / missing / malformed;
                         detect deprecated_emitted (e.g., src/prisma/ remnants);
                         write .agent-team/scaffold_verifier_report.json
                         return ScaffoldVerifierReport(verdict=PASS|WARN|FAIL, …)
wave_executor.py:3513-3516   if verifier_error is not None:
                                  wave_result.success = False
                                  wave_result.error_message = verifier_error
                                  compile_result.passed = False  # prevents downstream waves
```

FAIL verdict halts Wave B before it operates on a drifted tree. PASS/WARN verdicts allow normal progression but still persist the JSON report for the cascade consumer downstream.

### 4.4 `cascade_consolidation_enabled=True`

Consumer: `cli.py:743` — top of `_apply_evidence_gating_to_audit_report`, running **before** severity/verdict gating so that cascaded findings do not double-count in cost.

```
cli.py:743    report = _consolidate_cascade_findings(report, config=config, cwd=cwd)
cli.py:644    if not _cascade_consolidation_enabled(config) or not cwd: return report
cli.py:646    verifier_report = _load_scaffold_verifier_report(cwd)   # reads .agent-team/scaffold_verifier_report.json
cli.py:649    roots = _scaffold_root_cause_paths(verifier_report)     # missing ∪ malformed ∪ deprecated_emitted
cli.py:663-685  for root in roots:
                   matched = findings where _finding_mentions_path(f, root)
                   if len(matched) < 2: continue
                   rep = _cluster_representative_index(matched)  # highest-severity
                   rep.cascade_count = len(consumed);  rep.cascaded_from = [ids]
                   rep.evidence += ["N-11 cascade: absorbed N downstream finding(s) …"]
cli.py:701-717  append F-CASCADE-META finding (INFO / UNVERIFIED / deterministic)
cli.py:720-728  build_report(...) returning the collapsed report
```

**V3 replay verdict:**
- Synthetic path-bearing input: 6 → 4 findings with two clusters (S-001 absorbs S-002; S-003 absorbs S-004, S-005), plus `F-CASCADE-META`. Cascade algorithm is correct.
- Build-l scorer-shape input: 28 → 28 (0 collapse). Root cause: `AuditFinding.from_dict` at `audit_models.py:82-104` does not fold raw `file` / `description` keys into `evidence[]`, so `primary_file` (derived from `evidence[0]`) is empty and `_finding_mentions_path` finds nothing. This is a pre-Phase-B audit-plumbing gap tracked as **OOS-1** — not a defect in the N-11 consolidator itself.

### 4.5 `duplicate_prisma_cleanup_enabled=True`

Consumers (two insertion points):

- `wave_executor.py:3034` — immediately after Wave B's DTO guard + compile pass, while the tree is still warm.
- `wave_executor.py:3487` — late at the end of Wave D5 as a last-ditch cleanup if Wave B's copy had already been rolled back.

Gate: `_maybe_cleanup_duplicate_prisma(cwd=cwd, config=config)` at both sites. Function body at `wave_executor.py:941-997` requires:

1. Flag True.
2. `apps/api/src/prisma/` exists (the stale tree).
3. `apps/api/src/database/` is a directory.
4. Both `apps/api/src/database/prisma.module.ts` and `…/prisma.service.ts` are files AND non-empty. If either is missing or zero-bytes, the function returns `[]` (safety invariant).

If all four hold, `shutil.rmtree(stale_dir)` removes the stale `apps/api/src/prisma/` subtree and the removed file list is logged at INFO.

V4 replay verdict:

| Scenario | Before | After | Invariant |
|----------|--------|-------|-----------|
| HAPPY (flag ON, both seeded) | 5 files | 2 files (canonical only) | stale gone AND canonical untouched — **PASS** |
| FLAG OFF | 5 files | 5 files | cleanup declined — **PASS** |
| SAFETY (flag ON, canonical missing) | 3 stale files | 3 stale files | cleanup declined — **PASS** |
| EDGE (flag ON, no stale) | 2 canonical | 2 canonical | noop — **PASS** |

### 4.6 `template_version_stamping_enabled=True`

Consumer: module-level bool `_TEMPLATE_VERSION_STAMPING_ACTIVE` in `scaffold_runner.py`.

Entry toggle at `run_scaffolding` (`scaffold_runner.py:298-303`):
```
global _TEMPLATE_VERSION_STAMPING_ACTIVE
previous_stamping = _TEMPLATE_VERSION_STAMPING_ACTIVE
v18 = getattr(config, "v18", None) if config is not None else None
_TEMPLATE_VERSION_STAMPING_ACTIVE = bool(
    getattr(v18, "template_version_stamping_enabled", False)
)
```

Restore at `:331` inside `try/finally` so a crashed run cannot leak the flag into subsequent calls / tests.

Consumer at `_write_if_missing` (`scaffold_runner.py:748-749`):
```
if _TEMPLATE_VERSION_STAMPING_ACTIVE:
    payload = _stamp_version(content, path.suffix)
```

`_stamp_version` (`scaffold_runner.py:55-78`):
- `.py / .yaml / .yml / .toml / .env` → prepend `# scaffold-template-version: 1.0.0` (constant `SCAFFOLD_TEMPLATE_VERSION` at `:28`).
- `.ts / .tsx / .js / .jsx / .mjs / .cjs` → prepend `// scaffold-template-version: 1.0.0`.
- `.json / .md / .txt / .prisma` → pass-through (strict JSON has no comments; human-readable docs unchanged).
- Idempotent: if the first non-empty line already matches the comment prefix, re-stamp is skipped.

A companion parser `_check_template_version` (`scaffold_runner.py:81-102`) exists for future pipeline-startup compatibility checks; no live caller as of this session (appropriate: NEW-2 is framework-only until pipeline-start gating is wired).

V2 verdict: all six flag True-branches traced to a concrete consumer with a reachable side-effect. **PASS.**

---

## 5. V3 — Cascade consolidation replay against build-l

**Script:** `v18 test runs/session-B-validation/cascade-replay.py` — **log:** `cascade-replay.log`.

**Inputs:**
- `build-l-gate-a-20260416/.agent-team/AUDIT_REPORT.json` (28 findings, scorer shape).
- Synthetic verifier report with 14 root causes (12 missing + 2 deprecated_emitted).

**Flag-OFF baseline:** 28 → 28 findings. `unchanged is report == True` confirms **identity preservation**.

**Flag-ON against build-l:** 28 → 28 (0 collapse). Per-root match distribution shows all 14 roots returned `0 matches`. Diagnosed in the replay's Diagnostic block:

> `_finding_mentions_path` reads `primary_file`, `evidence[]`, and `summary`. Scorer-shape `AUDIT_REPORT.json` stores path info in the raw `file` + `description` keys, which `AuditFinding.from_dict` does NOT map to `evidence`. Only `title` → `summary` survives. Against scorer-shape raw input, N-11 collapse rate is 0.

**Corroborating synthetic test** (6 findings whose `evidence[]` carries the canonical path):

```
S-001  <cc=1 from=['S-002']>  evidence=apps/api/src/database/prisma.service.ts:1 — not found; N-11 cascade: absorbed 1 …
S-003  <cc=2 from=['S-004','S-005']>  evidence=packages/shared/src/enums.ts — absent; N-11 cascade: absorbed 2 …
S-006  (uncollapsed: non-matching path)
F-CASCADE-META  <META>  evidence=Scaffold root causes with cascade: apps/api/src/database (+1), packages/shared/src (+2)
```

The synthetic run proves the cluster→representative→meta-finding pipeline works end-to-end: 6 input → 4 output (3 downstream findings absorbed into 2 representatives + 1 meta).

**Verdict:** N-11 wiring is correct. Build-l's 0-collapse is an **out-of-scope** input-plumbing gap in `audit_models.AuditFinding.from_dict` (OOS-1), not a Phase B defect.

---

## 6. V4 — Duplicate Prisma cleanup replay

**Script:** `v18 test runs/session-B-validation/duplicate-prisma-replay.py` — **log:** `duplicate-prisma-replay.log`.

All four scenarios against `build-l-gate-a-20260416/apps/api/src/{prisma,database}/`:

| Scenario | flag | seed canonical | seed stale | Before | After | Removed | Stale gone? | Canonical OK? | Verdict |
|----------|------|----------------|------------|--------|-------|---------|-------------|---------------|---------|
| HAPPY | ON | yes | yes | 5 | 2 | 3 | **YES** | **YES** | PASS |
| FLAG OFF | OFF | yes | yes | 5 | 5 | 0 | no (intended) | YES | PASS |
| SAFETY | ON | no | yes | 3 | 3 | 0 | no (safety block) | n/a | PASS |
| EDGE | ON | yes | no | 2 | 2 | 0 | YES (nothing to remove) | YES | PASS |

Removed file list (HAPPY): `apps/api/src/prisma/prisma.module.ts`, `apps/api/src/prisma/prisma.service.spec.ts`, `apps/api/src/prisma/prisma.service.ts`. The canonical files (`apps/api/src/database/prisma.module.ts`, `apps/api/src/database/prisma.service.ts`) are byte-identical before / after.

Safety invariant confirmed: when the canonical tree exists but is missing a required file, the stale dir is preserved — preventing a catastrophic wipe when the rename is mid-flight.

**Verdict:** **PASS.**

---

## 7. V5 — Ownership contract parser consistency

**Script:** `v18 test runs/session-B-validation/ownership-contract-parse.py` — **log:** `ownership-contract-parse.log`.

Loaded `docs/SCAFFOLD_OWNERSHIP.md` (492 lines) via `scaffold_runner.load_ownership_contract()` and verified:

| Invariant | Expected | Got | Result |
|-----------|----------|-----|--------|
| Total rows | 60 | 60 | PASS |
| `files_for_owner('scaffold')` | 44 | 44 | PASS |
| `files_for_owner('wave-b')` | 12 | 12 | PASS |
| `files_for_owner('wave-d')` | 1 | 1 | PASS |
| `files_for_owner('wave-c-generator')` | 3 | 3 | PASS |
| `emits_stub=True` count | 13 | 13 | PASS |
| `emits_stub=True` rows with `owner!=scaffold` | 0 | 2 | **SEE OOS-2** |
| `is_optional('.editorconfig')` | True | True | PASS |
| `is_optional('.nvmrc')` | True | True | PASS |
| `owner_for('packages/shared/src/error-codes.ts')` | `scaffold` | `scaffold` | PASS |
| `owner_for('apps/api/src/main.ts')` | `scaffold` | `scaffold` | PASS |

### OOS-2: emits_stub vs owner comment mis-statement

Two `emits_stub: true` rows are legitimately owned by non-scaffold actors:

- `apps/web/src/lib/api/client.ts` — `owner: wave-d` (stub authored by wave-d, not the scaffold).
- `packages/api-client/src/index.ts` — `owner: wave-c-generator` (populated by openapi-ts generator, not scaffold).

This is intentional per the layered model in `docs/plans/2026-04-16-phase-b-architecture-report.md` §6.2: `emits_stub` marks files where downstream actors inherit a placeholder, and a wave-d-authored placeholder is as valid as a scaffold-authored one. The `SCAFFOLD_OWNERSHIP.md` header comment "all 13 emits_stub=true rows have owner=scaffold" is simply wrong. Doc tweak, not a parser or schema defect.

**Verdict:** parser matches the architecture spec. PASS, with one docstring fix for Wave 4.

---

## 8. V6 — Scaffold dump diff (Phase B vs build-l)

**Script:** `v18 test runs/session-B-validation/scaffold-dump-diff.py` — **log:** `scaffold-dump-diff.txt`.

Ran current scaffold (`run_scaffolding`) into a tmpdir with an NestJS+Next.js IR fixture, then compared against `build-l-gate-a-20260416/` (excluding `.agent-team/`, `telemetry/`, `product-ir/`, and obvious non-scaffold artifacts).

### 8.1 Counts

| Metric | Count |
|--------|-------|
| Current scaffold emitted | 38 |
| Current scaffold tree size | 38 |
| Build-l tree size (excl. orchestration artifacts) | 68 |
| NEW in Phase B | 10 |
| REMOVED vs build-l | 40 (almost all Wave B/D outputs outside scaffold scope) |

### 8.2 NEW emissions in Phase B (not present in build-l tree)

```
.env.example
.gitignore
apps/api/prisma/migrations/20260101000000_init/migration.sql
apps/api/prisma/migrations/migration_lock.toml
apps/web/messages/en/f-001.json
apps/web/tsconfig.json
docker-compose.yml
package.json
pnpm-workspace.yaml
tsconfig.base.json
```

Each corresponds to a documented Wave 2 addition:
- `pnpm-workspace.yaml` + `tsconfig.base.json` → DRIFT-7 / N-03 workspace glob + path alias.
- `apps/api/prisma/migrations/*` → N-05 initial migration stub.
- `apps/web/messages/en/f-001.json` → feature-level i18n bundle.
- `.env.example` root + `docker-compose.yml` → were previously missing or relocated.

### 8.3 Canonical-path shift (DRIFT-1)

- Build-l tree: 3 entries under `apps/api/src/prisma/`.
- Phase B tree: 2 entries under `apps/api/src/database/`.

The scaffold no longer emits under the deprecated `src/prisma/` path; Wave 2 N-04 completed successfully.

### 8.4 PORT comparison (DRIFT-3)

| File | build-l | Phase B |
|------|---------|---------|
| `apps/api/src/main.ts` | `<not-found>` | **4000** |
| `apps/api/src/config/env.validation.ts` | 4000 | **4000** |
| `apps/api/.env.example` | 4000 | `<not-emitted>` |
| `.env.example` (root) | `<absent>` | **4000** |
| `docker-compose.yml` | `<absent>` | 5432 (first match — Postgres port; port mapping block is correct per template) |

Phase B centralizes `PORT=4000` at the root `.env.example` and inside `main.ts` / `env.validation.ts`. The per-app `apps/api/.env.example` is no longer emitted (build-l has it; Phase B template moved that content upstream). Watchlist item for OOS-3.

### 8.5 Expected Wave 2 additions check

| Path | Status |
|------|--------|
| `pnpm-workspace.yaml`, `tsconfig.base.json` | PRESENT |
| `apps/web/next.config.mjs`, `postcss.config.mjs`, `openapi-ts.config.ts`, `.env.example`, `src/test/setup.ts`, `tsconfig.json` | PRESENT |
| `apps/api/src/database/prisma.module.ts`, `prisma.service.ts` | PRESENT |
| `packages/shared/{package.json,tsconfig.json,src/enums.ts,error-codes.ts,pagination.ts,index.ts}` | PRESENT |
| `apps/api/prisma/schema.prisma` | PRESENT |
| `apps/api/nest-cli.json`, `tsconfig.build.json` | **MISSING** → OOS-3 |
| `apps/api/src/modules/auth/auth.module.ts`, `users/`, `projects/`, `tasks/`, `comments/` | **MISSING** → OOS-3 |

### OOS-3: scaffold-owned paths missing from Phase B scaffold

Seven paths listed in `SCAFFOLD_OWNERSHIP.md` as owner=scaffold are currently not emitted:

- `apps/api/nest-cli.json`
- `apps/api/tsconfig.build.json`
- `apps/api/src/modules/auth/auth.module.ts` (stub)
- `apps/api/src/modules/users/users.module.ts` (stub)
- `apps/api/src/modules/projects/projects.module.ts` (stub)
- `apps/api/src/modules/tasks/tasks.module.ts` (stub)
- `apps/api/src/modules/comments/comments.module.ts` (stub)

These exist as scaffold-owned rows in the contract but the scaffold template functions in `scaffold_runner._scaffold_api_foundation` / `_scaffold_nestjs` were not extended during Wave 2 to emit them. Consequence with flag-OFF: pipeline continues — Wave B synthesizes these files under its normal rules. Consequence with `ownership_contract_enabled=True` + `scaffold_verifier_enabled=True`: the verifier will flag them `missing` and (with FAIL verdict wiring at `wave_executor.py:3513-3516`) halt Wave A. This is a **wiring-complete / content-incomplete** situation and should be closed in Wave 4 by extending the scaffold templates — not by relaxing the verifier. Severity: MEDIUM.

**Verdict:** dump diff shows the intended DRIFT-1/3/4/5/7 corrections all landed. OOS-3 flagged for Wave 4 gap-closure. PASS (flag-OFF pipeline unaffected).

---

## 9. Flag topology table

| Flag | Default | Declared | Consumer(s) | YAML round-trip | Test coverage |
|------|---------|----------|-------------|-----------------|---------------|
| `ownership_contract_enabled` | False | `config.py:831` | `scaffold_runner.py:349`, `agents.py:7892`, `audit_team.py:292` | `config.py:2474-2479` | inline in `scaffold_runner` test |
| `spec_reconciliation_enabled` | False | `config.py:838` | `wave_executor.py:3331` | `config.py:2481-2486` | inline in `milestone_spec_reconciler` test |
| `scaffold_verifier_enabled` | False | `config.py:843` | `wave_executor.py:3510` | `config.py:2488-2493` | inline in `scaffold_verifier` test |
| `cascade_consolidation_enabled` | False | `config.py:870` | `cli.py:644`, `cli.py:743` | `config.py:2513-2518` | inline in `cli._consolidate_cascade_findings` tests |
| `duplicate_prisma_cleanup_enabled` | False | `config.py:877` | `wave_executor.py:953`, called at `:3034` + `:3487` | `config.py:2520-2525` | inline in `wave_executor` tests |
| `template_version_stamping_enabled` | False | `config.py:883` | `scaffold_runner.py:301` (toggle), `:748` (consume), `:331` (restore) | `config.py:2527-2532` | inline in `scaffold_runner` stamp tests |

All six pass the flag-OFF identity property (V1); all six have a reachable True branch (V2).

---

## 10. Out-of-scope findings

### OOS-1 — `AuditFinding.from_dict` does not map scorer-shape `file`/`description` into `evidence[]`

**Severity:** MEDIUM.
**Location:** `src/agent_team_v15/audit_models.py:82-104`.
**Effect:** N-11 cascade collapse rate on scorer-raw reports drops to 0 because `primary_file` (derived from `evidence[0]`) is empty and `_finding_mentions_path` cannot match root causes.
**Remediation:** extend `AuditFinding.from_dict` so that when `evidence` is absent but `file` and/or `description` keys are present (scorer shape), synthesize an `evidence[0]` of the form `f"{file} — {description[:80]}"`. Out of Phase B scope.
**Wiring impact:** none. N-11 algorithm is correct on canonical-shape input (verified via synthetic replay). This is a plumbing gap, not a Phase B defect.

### OOS-2 — `SCAFFOLD_OWNERSHIP.md` "all 13 emits_stub rows have owner=scaffold" is wrong

**Severity:** LOW (doc tweak).
**Location:** `docs/SCAFFOLD_OWNERSHIP.md` header comment.
**Effect:** two stub rows (`apps/web/src/lib/api/client.ts` wave-d; `packages/api-client/src/index.ts` wave-c-generator) are legitimately owned by non-scaffold actors per the layered ownership model. The doc comment over-claims a constraint that was never intended.
**Remediation:** replace header line with "scaffold owns most emits_stub rows; two are seeded by wave-d / wave-c-generator (see individual YAML blocks)."
**Wiring impact:** none.

### OOS-3 — Seven scaffold-owned paths not yet emitted

**Severity:** MEDIUM.
**Location:** `src/agent_team_v15/scaffold_runner.py` (missing emission in `_scaffold_api_foundation` / `_scaffold_nestjs`).
**Effect:** `apps/api/nest-cli.json`, `apps/api/tsconfig.build.json`, and the five per-module `*.module.ts` stubs are declared scaffold-owned in `SCAFFOLD_OWNERSHIP.md` but not produced by the scaffold. With `ownership_contract_enabled + scaffold_verifier_enabled` both ON, this will trigger FAIL and halt Wave B.
**Remediation:** extend `_scaffold_nestjs` with two new helpers (`_scaffold_nest_cli_json`, `_scaffold_modules_stubs`). Out of this verification's scope — Wave 4 gap-closure.
**Wiring impact:** none at flag-OFF default. Two flags (ownership_contract_enabled, scaffold_verifier_enabled) cannot safely ship to ON together until OOS-3 is closed.

---

## 11. Self-audit

**Mirroring Phase A wiring-verification format** (`docs/plans/2026-04-16-phase-a-wiring-verification.md`):

1. **Did each flag trace reach a reachable consumer?** Yes — all six flags are read at a guard site in production code and switch a concrete side-effect in the True branch.
2. **Was flag-OFF verified to be byte-compatible with pre-Phase-B?** Yes for all six. Cascade identity preservation additionally verified at the object-identity level (`report is report`), not just value equality.
3. **Were the two highest-risk hooks (cascade, cleanup) exercised against a real preserved build?** Yes — build-l-gate-a-20260416 preserved AUDIT_REPORT and `apps/api/src/{prisma,database}/` subtrees were fed into offline replays.
4. **Were findings that might otherwise read as HALT triaged to their correct category?** Yes:
   - N-11 0-collapse on build-l → OOS-1 (audit-plumbing gap, not cascade defect).
   - SCAFFOLD_OWNERSHIP.md comment mismatch → OOS-2 (doc, not schema).
   - 7 missing scaffold-owned paths → OOS-3 (scaffold template gap, not wiring defect).
   None triggers HALT-A through HALT-F from the verifier task spec.
5. **Did any finding indicate that Phase B flags cannot be turned ON in a live smoke?** Partially — `ownership_contract_enabled` and `scaffold_verifier_enabled` should NOT be simultaneously ON until OOS-3 is closed, because the verifier will FAIL on the seven unshipped paths and halt Wave B. The other four flags are individually safe to enable.
6. **Were unit-test-only claims avoided in favor of real call-graph tracing?** Yes — every True-branch claim in V2 is backed by a file:line reference to a production consumer, not a test harness.

**Self-audit verdict:** the verification meets the Phase A precedent's rigor. No gaps beyond the three documented OOS items.

---

## 12. Artifacts

All under `v18 test runs/session-B-validation/`:

- `ownership-contract-parse.py` + `.log` — V5 parser consistency.
- `scaffold-dump-diff.py` + `scaffold-dump-diff.txt` — V6 scaffold tree diff.
- `cascade-replay.py` + `cascade-replay.log` — V3 N-11 consolidation replay.
- `duplicate-prisma-replay.py` + `duplicate-prisma-replay.log` — V4 NEW-1 cleanup replay.

This document: `docs/plans/2026-04-16-phase-b-wiring-verification.md`.

---

## 13. Handoff to Wave 4

Wave 4 should:

1. **Close OOS-3** by extending `scaffold_runner` to emit the seven scaffold-owned paths (`apps/api/nest-cli.json`, `tsconfig.build.json`, and the five per-module `*.module.ts` stubs). This unblocks simultaneous `ownership_contract_enabled + scaffold_verifier_enabled` use.
2. **Patch OOS-2** — a one-line header comment fix in `docs/SCAFFOLD_OWNERSHIP.md`.
3. **Defer OOS-1** to a dedicated audit-plumbing task; file an issue noting it blunts N-11 on scorer-shape raw input. Scope is outside Phase B.
4. **Run the full pytest suite** to confirm Wave 2+3 changes did not regress Phase A flag-OFF behavior (Wave 4 task #15).
5. **Do NOT enable any Phase B flag by default** in `config.yaml` until each has been exercised in a live smoke — flag-OFF is the safe ship posture for this branch.
