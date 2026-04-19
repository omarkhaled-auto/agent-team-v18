# A-09 — Wave D/B over-build M2–M5 features during M1 execution

**Tracker ID:** A-09
**Source:** F-019 (HIGH) + structural inference across all Bucket B findings
**Session:** 1 (paired with C-01)
**Size:** L (~350 LOC)
**Risk:** MEDIUM
**Status:** plan

---

## 1. Problem statement

Build-j M1 executed and produced a complete M2–M5 feature set: full auth/projects/tasks/comments/users NestJS modules, Prisma entities for all four models, Next.js pages for Projects/ProjectDetail, and a generated API client with functions for every endpoint. The M1 REQUIREMENTS.md explicitly says:

- "No feature business logic in this milestone."
- "JWT module is wired but has no strategies — strategies are added in M2."
- "next-intl locale files start empty — keys are added in M2-M5."
- Prisma schema "with only the `datasource` and `generator` blocks (entity models added per-milestone)."

Wave B and Wave D both produced content outside this scope. The audit then scored the output against the full PRD and returned 0/1000 with 41 findings — 33 of which are flagging out-of-scope code.

**Evidence:**
- `v18 test runs/build-j-closeout-sonnet-20260415/apps/api/prisma/schema.prisma` — contains User, Project, Task, Comment entities (M2–M5 scope).
- `v18 test runs/build-j-closeout-sonnet-20260415/apps/api/src/` — contains `auth/`, `projects/`, `tasks/`, `comments/`, `users/` modules with full controllers + services.
- `v18 test runs/build-j-closeout-sonnet-20260415/apps/web/src/components/projects/project-detail-page.tsx` — M3 feature page.
- `AUDIT_REPORT.json` F-019 verbatim: "M1 scope violation — all M2-M5 features implemented in milestone 1".

## 2. Root cause (verified by grep)

`wave_executor.py` constructs wave prompts by reading the full PRD-derived IR and the full milestone list, not a milestone-scoped slice. `audit_prompts.py` has 3 `milestone_id` references — all used as output path components, not as scope filters (see tracker C-01 for the audit side).

Wave prompt construction passes:
- The complete IR (all entities, all features across all milestones).
- The full `ENDPOINT_CONTRACTS.md` (all 20 endpoints across M2–M5).
- The full `REQUIREMENTS.md` (all milestones).

When the model sees "here's the full spec, generate a milestone-1 backend", it generates everything it can see.

## 3. Proposed fix shape

Three pieces:

### 3a. Milestone-scoped wave prompt context (`wave_executor.py`)

Introduce `MilestoneScope` dataclass that filters IR and spec before wave prompts are built:

```python
@dataclass
class MilestoneScope:
    milestone_id: str
    allowed_entities: list[str]          # e.g. [] for M1, ["User"] for M2, ["Project"] for M3
    allowed_feature_refs: list[str]       # F-PROJ-*, F-TASK-*, etc.
    allowed_ac_refs: list[str]
    allowed_file_globs: list[str]         # derived from REQUIREMENTS.md "Files to Create" tree
    description: str                      # milestone-specific description ONLY
    forbidden_content: list[str]          # explicit don't-generate list ("no feature business logic", etc.)
```

Populate from `MASTER_PLAN.json` + the milestone's `REQUIREMENTS.md`. Pass to every wave's prompt builder.

Wave prompt builders (in `wave_executor.py` + `codex_prompts.py`) must accept and honor this scope — the prompt template becomes:

```
You are the {Wave} specialist for milestone {id}: {description}.
Scope — ONLY produce files matching these globs:
{allowed_file_globs}
Scope — DO NOT produce:
{forbidden_content}
```

### 3b. Pre-prompt IR/spec filter

A `scope_filter.py` module that takes `ir` + `MilestoneScope` and returns a scope-restricted IR view:
- Entities filtered to `allowed_entities` (empty list for M1 → no entities passed).
- Endpoints filtered to endpoints that belong to current milestone's features.
- Translations filtered to current milestone's namespaces only.

### 3c. Post-wave out-of-scope validator

After each wave completes, scan `files_created` against `scope.allowed_file_globs`. Files outside the allowed globs become `scope_violation` findings on `WaveResult`. This is what catches regressions if the prompt filter drifts.

```python
@dataclass
class WaveResult:
    ...
    scope_violations: list[str]  # file paths outside allowed globs
```

Optionally: on scope violation, delete the out-of-scope files before persisting them (aggressive). Start non-aggressive (just flag) to avoid destructive side effects.

## 4. Test plan

File: `tests/test_wave_scope_filter.py`

1. **M1 scope filter excludes feature entities.** Build a `MilestoneScope` for M1 using the stock PRD; assert `allowed_entities == []`, `allowed_feature_refs == []`, `allowed_ac_refs == []`.
2. **M3 scope filter includes only Projects entities.** Assert M3 scope includes `Project` and excludes `Task`, `Comment`, `User`.
3. **Wave B prompt does not reference out-of-scope feature names.** Build M1 wave B prompt; assert prompt text does NOT contain "Task", "Kanban", "Comment" (as entity/feature names; case-sensitive + whole-word).
4. **Wave D prompt for M1 does not reference feature pages.** Assert M1 Wave D prompt doesn't mention "Task Detail", "Kanban", "Team Members", "User Profile".
5. **Post-wave validator catches out-of-scope files.** Feed a fake `files_created` list with an M3 file during M1; assert `scope_violations` non-empty.
6. **Post-wave validator ignores allowed files.** Feed `files_created` with only M1 scaffold files; assert `scope_violations == []`.

File: `tests/test_scope_filter_integration.py`

7. **End-to-end: M1 prompt construction produces only scaffold output.** Mock the wave executor with a canned model that echoes the prompt; assert no M2–M5 feature content appears in the constructed prompt.

Target: 7 new tests, zero regressions.

## 5. Rollback plan

If the scope filter breaks a milestone (Wave D can't produce required scaffold because the filter over-trims), add a feature flag `config.v18.milestone_scope_enforcement: bool = True`. Flipping to `False` restores the old full-PRD-context behavior. One-line config revert, no code rollback needed.

## 6. Success criteria (no paid smoke required)

- All 7 unit tests above pass.
- Static verification: run the wave prompt builder against the build-j PRD with M1 scope; capture the prompt text; assert the captured prompt excludes M2–M5 entity names and Task/Kanban/Team/User feature references.
- Manual sanity: feed the captured M1 prompt to a dry-run of the codex prompt composer; confirm no references to M2+ content leak through.

Paid smoke (Gate A in tracker) proves the end-to-end behavior, but unit tests + static verification are sufficient to declare the mechanism correct.

## 7. Sequencing notes

- **Land in the same PR (or same session) as C-01** — auditor-side scope fix. Without C-01, the auditor still penalizes M1 for "Task Detail page missing" even after A-09 stops generating it (which is correct — it shouldn't exist yet, but the auditor shouldn't flag its absence at M1 audit).
- Do not couple to Bug #20. A-09 is a pre-codex change (affects prompt construction), independent of transport.
