# Phase H1b — ARCHITECTURE.md Allowlist Evidence

> Branch: `phase-h1b-wave-a-architecture-md-schema` cut from `integration-2026-04-15-closeout` @ `d2ce167` (post-h1a).
> Author: `discovery-agent` (Wave 1).
> Companion: `phase-h1b-architecture-report.md`, `phase-h1b-discovery-citations.md`.
> This file is **load-bearing** for schema-agent (Wave 2A). It defines the exact allowlist, disallow-list, rejection reasons, and ALLOWED_REFERENCES set.

---

## 1. Historical evidence set

Pulled 5 per-milestone `ARCHITECTURE.md` files from preserved smokes under `v18 test runs/build-final-smoke-*/.agent-team/milestone-milestone-1/ARCHITECTURE.md`. All M1 — M2 runs were not preserved because smokes never got past M1. Selected to span content sizes (81→167 lines) and outcomes (drift vs restrained).

| # | Smoke | Lines | Character |
|---|---|---|---|
| a | `build-final-smoke-20260419-043133` | **132** | **Smoke #11 — the PORT drift file** (invents `process.env.PORT ?? 8080` while DoD requires 3080). |
| b | `build-final-smoke-20260418-221709` | 167 | **Worst drift** — fabricates the full M2-M6 domain schema inside M1. |
| c | `build-final-smoke-20260418-041514` | 136 | Moderate drift — invents cascade-rule table for future milestones. |
| d | `build-final-smoke-20260418-054004` | 113 | Restrained — sticks to seams + intent. |
| e | `build-final-smoke-20260418-170309` | **81** | **Most restrained** — the model of what a good handoff looks like. |

M2+ ARCHITECTURE.md files are not available on disk — no smoke ever completed past M1. Cross-milestone section-stability cannot be empirically verified from preserved runs; the allowlist is derived from M1 evidence alone. Schema-agent should treat the schema as M1-first and add M2+-only sections (e.g. `## Migrations`, `## Entities`, `## Relationships`) as CONDITIONAL rows in the schema — required when the IR for the milestone has non-empty entities, disallowed otherwise. This is covered in the allowlist below.

---

## 2. Section inventory (per file, exact emitted H2 names)

### File (a) — smoke #11, `build-final-smoke-20260419-043133`, 132 lines

| Section H2 | Notes |
|---|---|
| Scope recap | 1-sentence milestone intent; names "Zero ACs, zero entities." |
| What Wave A produced | Lists 3 files (schema.prisma, docker-compose.yml, docker-compose.test.yml). Invented compose details (host 5432, volume `taskflow_postgres_data`) — partially accurate, partially freehand. |
| Seams Wave B (backend scaffold) must populate | Lists main.ts, app.module.ts, prisma.module.ts, health.controller.ts, global pipes/filters/interceptors, pagination DTO, Swagger. **DRIFT:** `main.ts` listed as `process.env.PORT ?? 8080` while DoD mandates 3080. |
| Seams Wave D (frontend scaffold) must populate | Lists middleware.ts, layout.tsx, nav.ts, shell components, UI primitives, format.ts, api.ts, locale files. |
| Design-token contract (Wave D) | **FREEHAND:** 10 color values, font stack, space unit, shadow values — all invented inline. Duplicates `UI_DESIGN_TOKENS.json` emitted by Slice 4c. |
| Seams Wave T (tests) must populate | Lists backend Jest config, Vitest bootstrap, Playwright config, root scripts. |
| Seams Wave E (scanner/finalization) must enforce | Lists zero hardcoded strings, zero directional CSS, zero console.log, openapi no-diff check. |
| Merge-surface ownership for later milestones | **DUPLICATE:** 9-row ownership table for schema.prisma, compose, compose.test, app.module.ts, nav.ts, layout.tsx, locale files, package.json, openapi.json. Duplicates `docs/SCAFFOLD_OWNERSHIP.md`. |
| Open questions / carry-forward | 3 bullets (no M1 migration, no Redis, password hash M2 deferred). |

### File (b) — `build-final-smoke-20260418-221709`, 167 lines

| Section H2 | Notes |
|---|---|
| Stack (authoritative for this milestone) | **DRIFT:** Wave A declares itself stack authority. Duplicates stack contract (Slice 1c's `StackContract`). |
| Schema summary (delivered by Wave A) | **WORST DRIFT:** 4-row table of User/Project/Task/Comment with fields, PKs, soft-delete. **M1 has zero entities.** Pure hallucination of M2-M6 schema inside M1's handoff. |
| Enums | **DRIFT:** UserRole/ProjectStatus/TaskStatus/TaskPriority enums — all M2+ future content. |
| Relationships | **DRIFT:** 6 FK relations — all M2+ future content. |
| Indexes (with rationale) | **DRIFT:** 9 index specs — all for entities that don't exist in M1. |
| Migration plan | Speculative future-migration list. Actual migrations live in `apps/api/prisma/migrations/` (git-tracked). |
| Seed-runner seam | Worth keeping as sub-bullet under Wave B seams, not as own H2. |
| Backend service seams (owned by Wave B) | Matches "Seams Wave B" pattern — ALLOW. |
| Frontend seams (owned by Wave D) | Matches "Seams Wave D" pattern — ALLOW. |
| Out-of-scope for M1 (strict) | **DUPLICATE:** of `MilestoneScope.allowed_file_globs` / REQUIREMENTS.md out-of-scope block. |
| Open questions punted to Wave B / architect | ALLOW. |

### File (c) — `build-final-smoke-20260418-041514`, 136 lines

| Section H2 | Notes |
|---|---|
| Scope recap | ALLOW. |
| Entity inventory — this milestone | Table showing `(none)` for M1 — useful explicit-zero declaration. |
| Deferred entities (documented for cross-milestone traceability) | **DRIFT:** Lists M2-M5 entities and reasons. Cross-milestone context Wave B does not need — it has its own MilestoneScope (A-09). |
| Schema file layout | Tree diagram — useful. |
| Migrations | Says "none in M1" — legitimate signal. |
| Indexes / constraints | Says "none in M1" + convention list — half-legit (conventions are useful), half-drift (future-milestone conventions belong in schema contract, not handoff). |
| Cascade-rule placeholder table | **DRIFT:** 5-row table of future cascades (M3-M5). Pure speculation. |
| Service-layer seams Wave B populates | ALLOW (matches Seams Wave B pattern). |
| Frontend seams Wave D populates | ALLOW. |
| Open questions | ALLOW. |

### File (d) — `build-final-smoke-20260418-054004`, 113 lines

| Section H2 | Notes |
|---|---|
| Intent | ALLOW (= Scope recap alias). |
| What Wave A produced | ALLOW. |
| Why no entities here | Useful M1-specific zero-declaration; can fold into Scope recap. |
| Seams Wave B will populate | ALLOW. |
| Seams Wave D will populate | ALLOW. |
| Seams Wave T will populate | ALLOW. |
| Seams Wave E will populate (integration / DoD) | ALLOW. |
| Forbidden in this milestone (enforced by scope validator) | **DUPLICATE:** of `MilestoneScope.allowed_file_globs`. |
| Open questions | ALLOW. |

### File (e) — `build-final-smoke-20260418-170309`, 81 lines

| Section H2 | Notes |
|---|---|
| Intent | ALLOW. |
| What Wave A produced | ALLOW. |
| Seams Wave B / D / T / E will populate | ALLOW (single table variant of the four Seams sections — schema should accept EITHER one merged table OR four separate sections). |
| Contracts Wave B must honor | Worth examining — ALLOW as sub-section of Seams Wave B (substantive guidance). |
| Fields, indexes, cascades — intentionally empty | ALLOW — explicit-zero declaration pattern for foundation milestones. |
| Open questions | ALLOW. |

---

## 3. Downstream consumption evidence

The `<architecture>` XML injection helper `_load_per_milestone_architecture_block` (at `src/agent_team_v15/agents.py:8051-8083`) reads the WHOLE per-milestone ARCHITECTURE.md file and wraps it in `<architecture>...</architecture>`. Consumers at:
- Wave B: `agents.py:8407-8421`
- Wave D: `agents.py:9274-9278` (and the merged-D path)
- Wave T: `agents.py:8929-8934`
- Wave E: `agents.py:8664-8667`

Consumers use the whole block — they do NOT parse individual sections. So "consumed downstream" = "downstream prompts carry this text into the SDK turn, relying on the model to read it." That is a soft consumption — drift in sections Wave B doesn't actually need still costs context budget and can mislead downstream decisions. The allowlist therefore prunes non-load-bearing sections not only for drift prevention but for context-budget hygiene.

No grep hits in wave_executor.py or agents.py parsing `## Seams`, `## Design-token`, `## Stack`, or any other H2 — confirming the file is read as one XML payload, not section-indexed.

---

## 4. ALLOWLIST — sections the schema MUST permit

Each surviving section (a) appeared in 3+ files, (b) is reasonably consumed by downstream waves as context, and (c) does not duplicate a deterministic artifact.

| # | Section (H2) | Required? | Notes |
|---|---|---|---|
| 1 | `## Scope recap` *(aliases: `## Intent`)* | REQUIRED | One short paragraph. Must mention milestone id explicitly. |
| 2 | `## What Wave A produced` | REQUIRED | Bullet list or table of files Wave A created in this milestone. Paths MUST be in ALLOWED_REFERENCES (see §6). |
| 3 | `## Seams Wave B must populate` *(alias: `## Seams Wave B will populate`, `## Backend service seams (owned by Wave B)`, `## Service-layer seams Wave B populates`)* | REQUIRED | Bullet list of file paths Wave B must create, with a 1-line description per file. Paths MUST be in the ownership contract (`docs/SCAFFOLD_OWNERSHIP.md`) or in scope per `MilestoneScope`. |
| 4 | `## Seams Wave D must populate` *(alias variants)* | CONDITIONAL — REQUIRED when milestone template ∈ `{full_stack, frontend_only}`, absent when `backend_only`. | Same shape as Wave B seams. |
| 5 | `## Seams Wave T must populate` *(alias variants)* | REQUIRED | Same shape. |
| 6 | `## Seams Wave E must populate` *(alias: `## Seams Wave E must enforce`)* | REQUIRED | Same shape. |
| 7 | `## Fields, indexes, cascades` *(alias: `## Entities`, `## Relationships`, `## Migrations`)* | CONDITIONAL — REQUIRED when milestone's IR has ≥1 entity in scope; for foundation milestones (empty-entity scope), MAY be an explicit-zero declaration ("intentionally empty", "none in M1"). | The schema must accept either rich body (when entities present) or empty-declaration (when not). Key test: **if IR reports 0 entities, an inline fabricated entity table is a FAIL**. |
| 8 | `## Open questions` *(alias: `## Open questions / carry-forward`, `## Open questions punted to Wave B / architect`)* | REQUIRED (may be empty with "none") | Bullet list or "None." sentence. Useful for M2+ where Wave A encounters real decisions to flag forward. |

Section aliases: the schema validator should recognize the aliases listed above as the SAME section. Do NOT require the exact string "Scope recap" — allow "Intent" and "Scope" too. Use a case-insensitive startswith match plus a small synonym table.

**Section count: 8 distinct sections (6 always-required + 2 conditional). Well above the 3-section HALT threshold — no HALT.**

---

## 5. DISALLOW-LIST — sections the schema MUST reject

Each rejection carries a **named reason** written as the exact message the validator should emit to Wave A so the model learns WHY.

| # | Section (H2) | Why rejected | Exact validator rejection message |
|---|---|---|---|
| A | `## Design-token contract` *(or any H2 mentioning "design token" / "CSS variable" / "color palette")* | Duplicates deterministic artifact `.agent-team/UI_DESIGN_TOKENS.json` (Phase G Slice 4c). Observed in smoke #11 emitting 10 invented hex values freehand. | `"Design tokens live in .agent-team/UI_DESIGN_TOKENS.json (Phase G Slice 4c). Do not duplicate tokens in the architecture handoff. Reference the JSON file by path instead."` |
| B | `## Merge-surface ownership matrix` *(or any H2 containing "ownership" / "merge surface" / "who writes what")* | Duplicates deterministic artifact `docs/SCAFFOLD_OWNERSHIP.md`. | `"Ownership is defined in docs/SCAFFOLD_OWNERSHIP.md. Do not write a matrix here — reference that file if needed."` |
| C | `## Stack` *(or any H2 starting with "Stack", "Technology stack", "Tech stack")* | Duplicates the stack contract (resolved via Slice 1c and injected separately into Wave B/D as `[STACK CONTRACT]`). Wave A is not the authority for stack decisions. | `"Stack is owned by the stack contract (.agent-team/STACK_CONTRACT.json, injected as [STACK CONTRACT]). Wave A must not redeclare stack here."` |
| D | `## Deferred entities` / `## Future milestones` / any H2 listing other milestones' entities | Cross-milestone context Wave B does not consume — Wave B operates under MilestoneScope (A-09). Creates drift risk when future-milestone assumptions conflict with later Wave A runs. | `"Do not describe future milestones. Wave B/D/T/E of this milestone only consume their own MilestoneScope. Future-milestone context belongs in MASTER_PLAN.md, not the architecture handoff."` |
| E | `## Out-of-scope` / `## Forbidden in this milestone` | Duplicates `MilestoneScope.allowed_file_globs` and REQUIREMENTS.md's out-of-scope block. The MilestoneScope enforcer is deterministic — Wave A's restating of it is noise. | `"Out-of-scope guardrails live in MilestoneScope (A-09) and REQUIREMENTS.md. Do not restate them here."` |
| F | `## Cascade-rule placeholder table` / any speculative cascade/relation table for entities not in this milestone's IR | Pure speculation. When the real milestone writes the entity, the actual FK is emitted in `schema.prisma`. | `"Cascade rules live in apps/api/prisma/schema.prisma as Prisma relations. Do not speculate about FK rules for entities this milestone does not introduce."` |
| G | `## Schema summary` / `## Entity inventory` **when** the section body contains a table of entities AND the milestone IR has zero entities in scope | Hallucination. | `"This milestone's IR has zero entities in scope — an entity/schema table is a hallucination. Use an explicit-zero declaration instead (e.g. 'Fields, indexes, cascades — intentionally empty')."` |
| H | `## Seed-runner seam` as a top-level H2 | Fine as sub-bullet under `## Seams Wave B must populate`. Separating it invites duplication and diverges from the seams-by-wave layout. | `"Seed-runner details belong as a bullet inside '## Seams Wave B must populate'. Do not give it its own H2 — the seams sections are the single anchor for downstream waves."` |
| I | `## Migration plan` as a forward-looking speculation (listing future migrations by name) | Real migrations live in `apps/api/prisma/migrations/`. Handoff should only document migration files THIS Wave A produced (in `## What Wave A produced`). | `"Document only migrations this Wave A produced (under '## What Wave A produced'). Future migration names are speculative — the real migration file will be generated by the owning milestone's Wave A via 'prisma migrate dev'."` |
| J | Any H2 that restates the milestone's REQUIREMENTS.md (e.g. `## Requirements`, `## Definition of Done`) | REQUIREMENTS.md is injected separately. | `"REQUIREMENTS.md is injected into downstream prompts separately. Do not restate requirements or the Definition of Done here."` |

---

## 6. ALLOWED_REFERENCES — the reference-containment set

Derived from the Wave A prompt body injection variables (`src/agent_team_v15/agents.py:8132-8332`). These are the values Wave A has evidence for; anything outside this set is a fabricated reference.

The schema validator should check: for every file path, port number, URL, entity name, relation name, or magic constant cited in Wave A's ARCHITECTURE.md output, assert it is derivable from:

| # | Source | Extraction |
|---|---|---|
| 1 | `scaffolded_files` (list[str] passed in) | Every file path mentioned in `## What Wave A produced` or `## Seams Wave B/D/T/E` MUST either (a) appear in `scaffolded_files`, OR (b) be a scaffold-owned path in `docs/SCAFFOLD_OWNERSHIP.md`, OR (c) be an entity file Wave A itself wrote in this run (accessible via `wave_result.files_created`/`files_modified` — schema validator runs after Wave A completes). |
| 2 | `ir.entities` filtered by `milestone_scope` (the `_select_ir_entities(...)` output at `agents.py:8167`) | Every entity name in `## Entities` / `## Schema` table MUST appear in the selected-entity list for this milestone. If `_select_ir_entities` returned empty, NO entity names are allowed — empty schema + explicit-zero declaration only. |
| 3 | `acceptance_criteria` from `_select_ir_acceptance_criteria` at `agents.py:8168` | AC IDs like `FR-FOUND-004` or `BR-GEN-009` cited in the handoff MUST exist in this selected AC list. |
| 4 | `backend_context` (entity_example_path, repository_example_path, api_root) from `_build_backend_codebase_context` at `agents.py:8171` | Example file paths in `## Seams` MUST either be (a) the entity_example_path / repository_example_path verbatim, OR (b) derived from the `api_root` prefix (e.g. `apps/api/src/<anything>` when `api_root=apps/api/src`). |
| 5 | `stack_contract` object (when present) | Port numbers, database driver strings, framework names (NestJS 11, Prisma 5, etc.) MUST match the stack contract values. **Smoke #11's `PORT ?? 8080` is a violation**: stack contract resolved 3080 from DoD, handoff invented 8080. |
| 6 | `milestone.id` | Section `## Scope recap` MUST mention this exact milestone id. |
| 7 | `cumulative_arch_block` content (from repo-root ARCHITECTURE.md) | References to prior-milestone entities/decisions MUST appear verbatim in the cumulative block — no invented cross-milestone details. |
| 8 | `dependency_artifacts` (wave A output from predecessor milestones, loaded at call site) | References to predecessor-milestone files MUST come from this dict. |

Violations outside the set are emitted as `WAVE-A-SCHEMA-REFERENCE-001` rejection findings during the Wave 2A validator. Message template: `"Wave A handoff references <TOKEN> which is not in the injection-variable allowlist (source: {entities|acs|scaffold|stack_contract|backend|cumulative|dependency_artifacts}). Cite only values provided to the Wave A prompt."`

---

## 7. Cross-milestone section stability

Empirically unverifiable — no smoke completed past M1. Schema-agent must therefore:
- Treat the 6-always-required + 2-conditional allowlist as M1-first.
- For M2+, CONDITIONAL-REQUIRED section `## Entities` / `## Migrations` / `## Relationships` *becomes* required whenever the IR (scoped) reports ≥1 entity. The validator should flip the conditional on `_select_ir_entities(ir, milestone, milestone_scope) != []`.
- Frontend-only / backend-only templates flip `## Seams Wave D` / `## Seams Wave B` conditionally (per `WAVE_SEQUENCES` at `wave_executor.py:311-315`).

---

## 8. HALT check

Sections surviving the allowlist filter: **8** (6 always-required + 2 conditional). Above the 3-section threshold. **No HALT.**

No missing files, no unreadable data, no ambiguity on downstream consumption. Proceed to schema-agent (Wave 2A).
