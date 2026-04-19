# Session 1 Execute — A-09 + C-01 (Wave scope filter + Auditor milestone scoping)

**Tracker session:** Session 1 in `docs/plans/2026-04-15-builder-reliability-tracker.md` §9.
**Why this session:** Highest-leverage item in the whole tracker. Lands before any other work because every other audit verdict depends on correct scope.
**Paired items:** A-09 (wave prompts stop over-building) + C-01 (auditor scopes to current milestone). Must ship together — without either, the other is undermined.

---

## 0. Mandatory reading (in order)

1. `docs/plans/2026-04-15-builder-reliability-tracker.md` — whole file, but especially §2 (A-09), §4 (C-01), §9 (Session 1), §12 (honest assessment).
2. `docs/plans/2026-04-15-a-09-wave-scope-filter.md` — A-09 detail (fix shape, test plan, rollback).
3. `docs/plans/2026-04-15-c-01-auditor-milestone-scope.md` — C-01 detail.
4. `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/feedback_structural_vs_containment.md` — governing rule for this work. A-09 + C-01 are both **structural** fixes. Do not ship containment.
5. `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/feedback_verification_before_completion.md` — do not claim "done" without the listed verification outputs.
6. `~/.claude/projects/C--Projects-agent-team-v18-codex/memory/project_v18_hardened_builder_state.md` — pipeline architecture ground truth.
7. `v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/milestones/milestone-1/REQUIREMENTS.md` — this is the scope ground truth for M1. Your scope filter must honour it exactly.

---

## 1. Goal

Two PRs, both against `integration-2026-04-15-closeout` (NOT master):

- **PR A — A-09:** Milestone-scoped wave prompts + post-wave out-of-scope validator.
- **PR B — C-01:** Milestone-scoped auditor prompts + scope-violation finding category.

**Acceptance for the session:** Both PRs open, unit tests green, static-verification artefacts captured. No paid smoke. No merges to master. No merges to integration branch yet — that happens after the reviewer approves in the next turn of this conversation.

---

## 2. Branch + worktree

Current integration branch is `integration-2026-04-15-closeout` @ `98cba17`. Do **not** branch from master.

```
git fetch origin
git worktree add ../agent-team-v18-session-01 integration-2026-04-15-closeout
cd ../agent-team-v18-session-01
git checkout -b session-01-scope-filter
```

Two commits on this branch. Push. Open two PRs.

---

## 3. Execution order — strict TDD

### Phase 1: A-09

1. **Write failing tests first.** Create `tests/test_wave_scope_filter.py` with the 7 tests listed in plan §4 of `2026-04-15-a-09-wave-scope-filter.md`. Run `pytest tests/test_wave_scope_filter.py` — all 7 must fail.
2. **Create `src/agent_team_v15/milestone_scope.py`** with the `MilestoneScope` dataclass and a `build_scope_for_milestone(master_plan, milestone_id, requirements_md_path) -> MilestoneScope` factory.
3. **Create `src/agent_team_v15/scope_filter.py`** with `filter_ir_to_scope(ir, scope) -> FilteredIR` and glob-matching helpers.
4. **Update `src/agent_team_v15/wave_executor.py`** — wave prompt builders accept `MilestoneScope` and apply it. Keep the signature change backward-compatible behind a feature flag.
5. **Update `src/agent_team_v15/codex_prompts.py`** the same way.
6. **Add `scope_violations: list[str]` to `WaveResult`** in `wave_executor.py` + the post-wave validator that scans `files_created` against `scope.allowed_file_globs`. Non-destructive: flag only, do not delete.
7. **Feature flag:** Add `milestone_scope_enforcement: bool = True` to `config.v18` in `config.py`. When `False`, wave prompt builder falls through to pre-fix behaviour. Tests cover both branches.
8. **Run `pytest tests/test_wave_scope_filter.py`** — all 7 pass.
9. **Run full suite `pytest -x`** — no new failures against the existing suite.
10. **Static verification:** write a one-off script (or REPL snippet) that builds an M1 Wave D prompt from the build-j stock IR (`v18 test runs/build-j-closeout-sonnet-20260415/.agent-team/`). Capture the prompt text. Grep for forbidden strings: `Task Detail`, `Kanban`, `Team Members`, `User Profile`, `Project entity`, `Comment entity`. **Assert zero matches.** Save the captured prompt + grep transcript to `v18 test runs/session-01-validation/a09-m1-waved-prompt.txt` and `v18 test runs/session-01-validation/a09-grep-transcript.txt`.
11. **Commit** with subject `feat(wave-executor): milestone-scoped wave prompts + out-of-scope validator (A-09)`. Body references tracker ID and per-item plan path.

### Phase 2: C-01

1. **Write failing tests first.** Create `tests/test_audit_scope.py` with the 5 tests listed in plan §4 of `2026-04-15-c-01-auditor-milestone-scope.md`. Run — all 5 fail.
2. **Add `audit_scope_for_milestone(state, milestone_id) -> AuditScope`** in `src/agent_team_v15/audit_models.py` (or a new `src/agent_team_v15/audit_scope.py` — your call, keep it one file).
3. **Add `parse_files_to_create(requirements_md: str) -> list[str]`** — parses the "Files to Create" tree in `REQUIREMENTS.md` into glob patterns.
4. **Update `src/agent_team_v15/audit_prompts.py`** to consume `AuditScope` when building audit prompts. M1 audit prompt evaluates only files matching scope globs; out-of-scope files are consolidated into a single `scope_violation` finding per directory.
5. **Extend `AuditReport`** in `src/agent_team_v15/audit_models.py` with a `scope` field capturing what was audited.
6. **Add a `scope_violation` finding category** that does **not** deduct score. Severity HIGH, one finding per out-of-scope directory.
7. **Feature flag:** Add `audit_milestone_scoping: bool = True` to `config.v18`. Tests cover both branches.
8. **Run `pytest tests/test_audit_scope.py`** — all 5 pass.
9. **Run full suite `pytest -x`** — no new failures.
10. **Static verification:** build the M1 audit prompt from build-j stock state. Count the files listed in the evaluation target. **Assert ≤ 15 files** (M1 scaffold list is ~12). Save captured prompt + count to `v18 test runs/session-01-validation/c01-m1-audit-prompt.txt` and `v18 test runs/session-01-validation/c01-file-count.txt`.
11. **Round-trip test:** re-score build-j's 41 findings through the new scoped auditor. Count how many remain `in_scope` vs `scope_violation`. Expected: ≤ 8 in_scope (matches Bucket A items), ~33 scope_violation. Save result to `v18 test runs/session-01-validation/c01-rescoring-transcript.txt`.
12. **Commit** with subject `feat(audit): milestone-scoped audit prompts + scope_violation category (C-01)`. Body references tracker ID and per-item plan path.

---

## 4. Hard constraints

- **No paid smokes.** Unit tests + static verification only.
- **No merges.** Push branch + open 2 PRs against `integration-2026-04-15-closeout`. Do **not** merge them. The reviewer (next turn of the conversation) will.
- **No code beyond A-09 + C-01 scope.** Do not fix Bucket B findings. Do not touch `codex_transport.py`, `provider_router.py`, wave watchdog, compile-fix loop, or scaffold templates — those are other sessions.
- **No changes to existing prompts outside the scope-filter layer.** You are adding a filter; you are not rewording instructions.
- **No behaviour changes when feature flag is `False`.** Pre-fix callers must still work. The flag default is `True` but tests cover both.
- **Do not change codex invocation or app-server plans.** Bug #20 is a separate track.
- **Do not create documentation files other than PR bodies.** The tracker + per-item plans are already the design docs.
- **Do not amend existing commits on the integration branch.** Only add new commits on `session-01-scope-filter`.

---

## 5. Guardrail checks before pushing

Before `git push`:
- `pytest -x` exits 0.
- Both commits have descriptive messages (structure in §3, step 11 of each phase).
- `git diff integration-2026-04-15-closeout...HEAD --stat` shows changes **only** in:
  - `src/agent_team_v15/milestone_scope.py` (new)
  - `src/agent_team_v15/scope_filter.py` (new)
  - `src/agent_team_v15/wave_executor.py` (modified, surgical)
  - `src/agent_team_v15/codex_prompts.py` (modified, surgical)
  - `src/agent_team_v15/audit_scope.py` (new, or `audit_models.py` modified)
  - `src/agent_team_v15/audit_prompts.py` (modified, surgical)
  - `src/agent_team_v15/audit_models.py` (modified for AuditReport.scope + scope_violation)
  - `src/agent_team_v15/config.py` (modified — two flags)
  - `tests/test_wave_scope_filter.py` (new)
  - `tests/test_audit_scope.py` (new)
- Nothing unrelated: no scaffold template edits, no codex changes, no plan-file edits.

If the diff touches anything else, stop and report.

---

## 6. Reporting back

When both PRs are open, reply in the conversation with a single structured message:

```
## Session 1 execution report

### PRs
- PR A (A-09): <url>
- PR B (C-01): <url>

### Tests
- tests/test_wave_scope_filter.py: 7/7 pass
- tests/test_audit_scope.py: 5/5 pass
- Full suite (pytest -x): <N> passed, <M> skipped, 0 failed

### Static verification
- A-09 M1 Wave D prompt grep: <paste transcript>
- C-01 M1 audit prompt file count: <N>
- C-01 build-j re-scoring: <X> in_scope, <Y> scope_violation (expected: <=8 / ~33)

### Deviations from plan
<one paragraph: anything the plans predicted that turned out different, e.g., INVESTIGATE items that resolved unexpectedly>

### Files changed
<git diff --stat output>

### Blockers encountered
<either "none" or a structured list>
```

If you hit a blocker you can't resolve within the session constraints, stop and report — do NOT push partial work, do NOT merge anything, do NOT widen scope.

---

## 7. What "done" looks like

- Two PRs open against `integration-2026-04-15-closeout`.
- All 12 new unit tests pass; full suite green.
- Both static-verification artefact sets captured under `v18 test runs/session-01-validation/`.
- Feature flags default on; tests cover off-branch too.
- No paid API calls beyond unit test fixtures.
- Report posted in the conversation matching the template in §6.

The reviewer will then diff both PRs against the tracker + per-item plans, verify static-verification artefacts, and decide to merge or request changes. Do not merge yourself.
