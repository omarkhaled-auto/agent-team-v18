# C-01 — Auditor scores against full PRD, not current milestone scope

**Tracker ID:** C-01
**Source:** Meta-inference across all Bucket B findings; see tracker §4
**Session:** 1 (paired with A-09)
**Size:** M (~150 LOC)
**Risk:** MEDIUM
**Status:** plan

---

## 1. Problem statement

`audit_prompts.py` references `milestone_id` in 3 places (`830`, `901`, `1307`) — all output paths for `WAVE_FINDINGS.json` / Playwright results / etc. None restrict the auditor's **input scope** to the current milestone.

Build-j's M1 audit produced 41 findings. At least 33 are flagging M2–M5 code that per M1 REQUIREMENTS.md shouldn't exist at M1 audit time. The auditor is correct that the code is broken — but it's wrong to count those against M1.

**Evidence:**
- `AUDIT_REPORT.json` `notes` field mentions "entire pages (Task Detail, Team Members, User Profile) are missing" — Task Detail is M4 scope, Team Members + User Profile are M5 scope. The auditor should not evaluate M4/M5 features during M1 audit.
- `fix_candidates` array includes F-002..F-006 etc. which are M2–M5 scope.

## 2. Root cause

`audit_prompts.py` `build_audit_prompt(state, milestone_id)` function (or equivalent) currently passes:
- Full codebase tree to the auditor agents.
- Full `ENDPOINT_CONTRACTS.md` as the acceptance spec.
- Full `REQUIREMENTS.md` with all milestones' ACs.

The auditor then faithfully evaluates the full spec and counts every gap.

## 3. Proposed fix shape

### 3a. Milestone-scoped audit input

Introduce `audit_scope_for_milestone(state, milestone_id)` that returns:
- `requirements_markdown`: the current milestone's REQUIREMENTS.md only.
- `allowed_file_globs`: from the milestone's `Files to Create` tree.
- `allowed_endpoints`: endpoints that belong to current milestone's features (M1 → empty).
- `parent_milestones_summary`: a compressed note of earlier milestones' outputs (so M3 audit knows User/Auth from M2 exists and is trusted).

### 3b. Two-category finding emission

Audit agents emit findings in two categories:
- `in_scope`: findings on files inside `allowed_file_globs` — count toward score.
- `scope_violation`: findings on files OUTSIDE `allowed_file_globs` — one consolidated finding per directory, severity HIGH, message "Files present outside milestone {id} scope: {list}". Does **not** deduct score (don't double-count scope enforcement with A-09).

### 3c. Update `AuditReport` + prompt

- Add `scope` field to `AuditReport` capturing what was audited.
- Audit prompt template explicitly restricts: "Evaluate ONLY files matching these globs: {allowed_file_globs}. Out-of-scope files are separately reported by the scope validator."

### 3d. Audit-time scope conversion

Parse `REQUIREMENTS.md` "Files to Create" tree into globs. For M1: `["package.json", ".env.example", "docker-compose.yml", "apps/api/**", "apps/web/**", "packages/api-client/index.ts"]` but NOT `apps/api/src/auth/**` (beyond the shell), NOT `apps/api/src/projects/**`, etc.

The parser lives in `audit_models.py`.

## 4. Test plan

File: `tests/test_audit_scope.py`

1. **M1 scope has no feature file globs.** Parse M1 REQUIREMENTS.md; assert `allowed_file_globs` excludes `apps/api/src/projects/**`, `apps/api/src/tasks/**`, etc.
2. **M1 scope includes docker-compose + scaffold files.** Assert `docker-compose.yml` and `apps/api/src/main.ts` are in allowed globs.
3. **M3 scope includes Projects files.** Assert M3 allowed globs include `apps/api/src/projects/**`.
4. **Scope-violation findings don't deduct score.** Build an audit with 5 in-scope + 5 out-of-scope findings; assert score reflects 5 findings' worth of deduction, not 10.
5. **Audit prompt excludes out-of-scope files.** Build M1 audit prompt; assert prompt text doesn't reference `projects/`, `tasks/`, `comments/`, `users/` directories as evaluation targets.

Target: 5 new tests, zero regressions in existing audit tests.

## 5. Rollback plan

Feature flag: `config.v18.audit_milestone_scoping: bool = True`. Flip to `False` to restore full-PRD audit behavior.

## 6. Success criteria (no paid smoke required)

- Unit tests pass.
- Static verification: pass build-j's M1 state + audit scope to the new scoped audit; assert the produced prompt's evaluation target list is restricted to ~12 files (the M1 scaffold), not 100+.
- Round-trip: synthesize an AuditReport where all 41 build-j findings are re-evaluated through the new scoping; assert <= 8 findings count toward score (the A-01..A-08 + A-10 items), the rest become scope-violation consolidated notes or are dropped.

## 7. Sequencing notes

- Land with A-09 in Session 1. The two are a pair: A-09 stops producing M2+ content; C-01 stops penalizing M2+ content if it slips through.
- Do NOT couple to Bug #20.
- D-07 (audit schema fix) should land in a separate session; C-01 doesn't change the schema shape, only the prompt context.
