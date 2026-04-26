# V18 Smoke Test — Master Bug Index (2026-04-13)

> **Source:** TaskFlow PRD smoke-test session, 2026-04-13
>
> **Target repository:** `C:\Projects\agent-team-v18-codex`
>
> **Purpose:** Single source-of-truth index for every bug discovered during today's V18.1 hardened builder smoke testing. Every bug has: (a) symptom, (b) evidence location, (c) fix status (in-tree / plan-only / new), (d) severity.
>
> **Reading order for implementing agents:** This file → individual plan files → the `FINAL_COMPARISON_REPORT.md` → the working-tree diff (`git diff` on modified files).

---

## Status legend

- **✅ FIXED in tree** — patch is in the working tree (uncommitted), verified by syntax parse + behavior test
- **📋 PLAN WRITTEN** — full plan in `docs/plans/`, implementation pending
- **🆕 NEW, NEEDS PLAN** — surfaced today, not yet planned — linked below if addressed in this session
- **⚠️ WORKAROUND ONLY** — non-code workaround in use, root cause not fixed

---

## Index (11 entries — 10 real bugs + 1 misdiagnosis closed)

| # | Bug | Severity | Status | Primary File | Plan / Fix Location |
|---|---|---|---|---|---|
| **1** | Path-with-spaces / relative-cwd double-prefix in tsc compile | CRITICAL (blocked Wave B) | ✅ FIXED in tree | `src/agent_team_v15/compile_profiles.py` | See `in-tree-fixes-summary.md` §1 |
| **2** | Plan validator vs decomposer dep-prose mismatch | HIGH (blocked Phase 2) | ✅ FIXED in tree | `src/agent_team_v15/milestone_manager.py` | See `in-tree-fixes-summary.md` §2 |
| **3** | ~~Scheduler can't bootstrap pre-existing plan~~ **MISDIAGNOSIS** | N/A | N/A — closed | — | Was actually stale `Status: FAILED` from attempt-1; `--reset-failed-milestones` flag already handles this |
| **4a** | AUDIT_REPORT.json written to `.agent-team/.agent-team/` (double-nesting) | MEDIUM (downstream consumers break) | ✅ FIXED in tree | `src/agent_team_v15/cli.py:4736` | See `in-tree-fixes-summary.md` §3 |
| **4b** | `finding_id` schema drift — scorer writes `id`, parser expects `finding_id` | MEDIUM (silent `KeyError` during audit parse) | ✅ FIXED in tree | `src/agent_team_v15/audit_models.py` | See `in-tree-fixes-summary.md` §4 |
| **5** | PRD-vs-cwd location ambiguity — decomposer writes planning artifacts to PRD's dir instead of `--cwd` | HIGH (silent successful "no code" builds) | ⚠️ WORKAROUND ONLY | `src/agent_team_v15/agents.py` (planner prompt) | `2026-04-13-prd-cwd-location-plan.md` |
| **6** | Phase 1.5 nested SDK CLAUDECODE env check crashes the research sub-orchestrator | MEDIUM (Phase 1.5 always failed before this fix) | ✅ FIXED in tree | `src/agent_team_v15/cli.py` `main()` | See `in-tree-fixes-summary.md` §5 |
| **7** | Duplicate `operationId` in OpenAPI extractor (handler names collide across controllers) | CRITICAL (blocked Wave C) | ✅ FIXED in tree | `src/agent_team_v15/openapi_generator.py:1057` | See `in-tree-fixes-summary.md` §6 |
| **8** | OpenAPI generator script (`scripts/generate-openapi.ts`) never scaffolded — Wave C always falls back to regex extraction | LOW-MEDIUM (correct behavior, lower fidelity) | 📋 PLAN WRITTEN | `src/agent_team_v15/scaffold_runner.py`, `src/agent_team_v15/openapi_generator.py` | `2026-04-13-wave-c-openapi-script-scaffold-plan.md` |
| **9** | Hardcoded TypeORM mandate in `_STACK_INSTRUCTIONS` — Wave A obeys a hardcoded instruction regardless of what PRD says | CRITICAL (wrong ORM, wrong layout for most PRDs) | 📋 PLAN WRITTEN (2 tiers) | `src/agent_team_v15/agents.py:1908-1942` + `:1055` | `2026-04-13-stack-contract-enforcement-plan.md` |
| **10** | Wave D.5 SDK call silent hang — no error, no timeout, no telemetry write | HIGH (stops pipeline mid-run indefinitely) | 🆕 PLAN WRITTEN (this session) | `src/agent_team_v15/wave_executor.py` | `2026-04-13-wave-d5-silent-hang-plan.md` |
| **11** | Codex output hallucinations (invalid locale `'id'`, nonexistent Google Font subset `'arabic'`) not caught by any scanner | MEDIUM (runtime/build-time failures post-generation) | 🆕 PLAN WRITTEN (this session) | `src/agent_team_v15/quality_checks.py` + post-Wave-D scanners | `2026-04-13-codex-output-hallucinations-plan.md` |

---

## Related parallel plans (not strictly "bugs" but design changes)

| Plan | Status | Summary |
|---|---|---|
| `2026-04-13-product-ir-integration-redesign-plan.md` | Pre-existing (user-authored) | Product-IR integration model redesign — separates external systems from capabilities/infra/providers |

---

## Recommended implementation order

1. **Commit the in-tree fixes** (Bugs #1, #2, #4a, #4b, #6, #7) — already done, verified, ~30 LOC across 4 files. See `in-tree-fixes-summary.md`. Zero risk, high value — unblocks future builds from the most blocking issues.
2. **Bug #9 Tier 1** (~50 LOC) — parametrize `_STACK_INSTRUCTIONS`. Highest practical impact; every NestJS+Prisma PRD was getting TypeORM until this ships.
3. **Bug #10** — Wave D.5 silent hang. Blocks full-pipeline completion on every current build. Watchdog-based fix (~30-60 LOC).
4. **Bug #5** — PRD-vs-cwd. Low urgency (workaround is stable) but enables more flexible build layouts.
5. **Bug #11** — Codex hallucination scanners. Medium priority; complements existing DTO scanners.
6. **Bug #8** — OpenAPI scaffolded script. Quality improvement, not blocking.
7. **Bug #9 Tier 2** (follow-up PR) — StackContract dataclass + deterministic validator. Defense-in-depth.

---

## Confidence notes

Each bug's severity/status was assigned based on direct empirical evidence captured during the 7 smoke-test attempts on 2026-04-13. Bug #3 is the only entry flagged as misdiagnosis — all others are reproduced from at least one concrete failure with on-disk artifacts preserved at either `v18 test runs/build-c-hardened-attempt-1/` or `v18 test runs/build-c-hardened-clean/`.

Future discoveries during implementation may reveal additional root causes or bugs not caught in this smoke test (e.g., Wave T / Wave E machinery is still uncharted — has never executed end-to-end). Additional plans should be filed as they emerge and linked from this index.
