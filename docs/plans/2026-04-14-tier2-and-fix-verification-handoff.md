# Handoff — Implement Bug #9 Tier 2 + Verify All Prior Fixes + Full Test Suite

> **Target session:** fresh Claude Code session on the `agent-team-v18-codex` repo.
>
> **Precondition:** commit `063b009` is the HEAD. It landed: Bug #9 Tier 1 (ORM-aware NestJS/TypeScript prompt generation), Bug #10 (Wave D/D.5 watchdog + hang reports), Bug #5 (PRD decomposition artifact recovery into `--cwd`), Bug #11 (frontend hallucination guards for locale unions + Google Font subsets), and Bug #8 (deterministic scaffolding of `scripts/generate-openapi.ts`). Baseline smoke-test commit was `51a7409`.
>
> **Do not run the smoke test.** A separate re-run brief exists at `docs/plans/2026-04-14-smoke-test-rerun-handoff.md`. Your job is to prepare the code so that re-run is maximally likely to pass.

---

## Your three jobs (in order)

1. **Implement Bug #9 Tier 2 completely.** Defense-in-depth on top of the Tier 1 prompt fix already landed.
2. **Review every prior fix in `063b009`.** Read each diff. Confirm it does what its plan said it would. Flag any regressions or half-implementations.
3. **Run the full test suite** (not just touched areas). Every test. Produce a matrix of pass/fail/skip with evidence.

Do **not** touch the smoke-test PRD, config, or run directories. Do **not** launch the smoke-test build.

---

## 1. Implement Bug #9 Tier 2

### Source of truth

`docs/plans/2026-04-13-stack-contract-enforcement-plan.md` — the "**TIER 2 — Defense-in-depth safeguards**" section. Follow the plan exactly. Every acceptance criterion in the Tier 2 sub-list must be satisfied. If you disagree with something in the plan, write your objection in the final verification report rather than silently changing the design.

### Components to deliver

1. **`StackContract` dataclass** with the exact fields listed in the plan (backend_framework, frontend_framework, orm, database, monorepo_layout, backend_path_prefix, frontend_path_prefix, forbidden_file_patterns, forbidden_imports, forbidden_decorators, required_file_patterns, required_imports, derived_from, confidence). Serializable to/from dict for STATE.json persistence. Location suggestion: a new `src/agent_team_v15/stack_contract.py` (decide yourself whether this lives standalone or in `product_ir.py` — coordinate with the ongoing product-IR redesign at `docs/plans/2026-04-13-product-ir-integration-redesign-plan.md`).

2. **Builtin contract registry** — at least the 8 contracts from the plan's matrix: NestJS+Prisma, NestJS+TypeORM, NestJS+Drizzle, Express+Prisma, Fastify+Prisma, Django+Django-ORM, Spring+JPA, ASP.NET+EFCore. Each entry fully specifies forbidden/required patterns (e.g., NestJS+Prisma must list `r".*\.entity\.ts$"` as forbidden and `r"prisma/schema\.prisma$"` as required).

3. **`derive_stack_contract(prd_text, master_plan_text, tech_stack, milestone_requirements)`** — resolves a contract with the confidence ladder (explicit → high → medium → low). Explicit + high trigger hard-block behavior; medium + low trigger advisory-only warnings. Sources signal from PRD parsing, MASTER_PLAN's Merge-Surfaces line, and `tech_research.detect_tech_stack()`.

4. **`validate_wave_against_stack_contract(wave_output, contract, project_root)`** — deterministic scanner returning `list[StackViolation]`. Violation codes per the plan: STACK-FILE-001/002, STACK-IMPORT-001/002, STACK-DECORATOR-001, STACK-PATH-001. Follow the shape of `quality_checks.run_dto_contract_scan` so the wave_executor integration is familiar.

5. **Wave executor integration** (`src/agent_team_v15/wave_executor.py`):
   - **Post-Wave-A:** run validator. On CRITICAL violations, roll back Wave A's files, retry ONCE with the violation list appended to the prompt (`"PRIOR ATTEMPT REJECTED:\n<violation list>"`). If the retry also fails, mark the wave/milestone failed with `stack_contract_violations` populated in telemetry.
   - **Post-Wave-B and Post-Wave-D:** run validator in **advisory mode** — write findings, do NOT block. Code is too expensive to roll back after Wave B/D.
   - Wave count retries via `stack_contract_retry_count` in telemetry.

6. **`WAVE_A_CONTRACT_CONFLICT.md` escape hatch** — if Wave A's agent thinks the spec is internally inconsistent (can't satisfy the contract because requirements contradict it), it writes this file and the wave fails loudly. If the file exists after Wave A, treat it as hard fail with a clear error message quoting the file's contents. Do NOT allow the wave to "succeed" when this file is present.

7. **`RunState.stack_contract`** — add the field to `src/agent_team_v15/state.py`. Serialize on every save. Deserialize on resume. The contract is derived once (during Phase 1 / 1.5) and reused for every milestone in the run.

8. **Telemetry** — every per-wave telemetry JSON gains:
   - `stack_contract_violations: list[dict]`
   - `stack_contract_retry_count: int`
   - `stack_contract: dict` (a copy of the resolved contract for that wave)

   Preserve backward compatibility with existing telemetry readers (add fields; do not rename or remove existing ones).

### Tests required (must pass before you consider Tier 2 done)

- `tests/test_stack_contract.py` (new file):
  - Every builtin contract loads from the registry without error
  - `derive_stack_contract` returns `confidence="explicit"` when PRD names both framework and ORM
  - `derive_stack_contract` returns `confidence="low"` when neither is named
  - `validate_wave_against_stack_contract` flags a TypeORM `.entity.ts` file as STACK-FILE-001 when contract says Prisma
  - `validate_wave_against_stack_contract` flags `@nestjs/typeorm` import as STACK-IMPORT-001 when contract says Prisma
  - `validate_wave_against_stack_contract` flags missing `prisma/schema.prisma` as STACK-FILE-002 when contract requires it
  - Symmetric tests for NestJS+TypeORM contract (forbidden: `prisma/schema.prisma`, required: `*.entity.ts`)
  - Advisory-mode vs block-mode returns the same violations but the caller reacts differently (test via fake wave_executor hook)
  - `WAVE_A_CONTRACT_CONFLICT.md` presence fails the wave

- `tests/test_wave_executor_stack.py` (new or extend existing):
  - Wave A with a clean output passes through validator without retry
  - Wave A with a forbidden file triggers rollback + one retry
  - Second retry producing the same violation marks the wave failed with correct telemetry
  - Wave B violation writes findings but does not roll back or retry

- 3 distinct stack pairs must have working end-to-end tests: NestJS+Prisma, Express+Drizzle, Django+Django-ORM. Use fixture mocks — no real LLM calls.

### Non-goals (don't do these)

- Don't change which waves run on which provider (Wave A stays Claude, B/D stay Codex, etc.)
- Don't change the wave pipeline structure (A → B → C → D → D.5 → T → E → audit)
- Don't change the Schema Handoff format
- Don't add new stack contracts beyond the 8 in the plan (the matrix was chosen deliberately — extensions go in follow-up PRs as empirical need emerges)
- Don't rewrite `quality_checks.run_dto_contract_scan` — mirror its pattern, don't refactor it

---

## 2. Review every prior fix in `063b009`

Git baseline is `51a7409` (smoke-test baseline) and the fix set is `063b009`. Diff the two:
```bash
git diff 51a7409..063b009 -- src/agent_team_v15/
```

For every file modified, verify each of these:

| Fix | Claimed file(s) | Verify |
|---|---|---|
| **#1** path resolve | `src/agent_team_v15/compile_profiles.py` | 5 sites use `str(path.resolve())` instead of `str(path)`. Test: construct a relative `--cwd`, verify all `--project` args in emitted commands are absolute |
| **#2** dep-prose filter | `src/agent_team_v15/milestone_manager.py` | `_parse_deps` has a milestone-ID regex filter after normalization. Test: `_parse_deps("- Description: Scaffold, M1, Next.js web app")` returns `["milestone-1"]` with warnings for dropped prose |
| **#4a** AUDIT_REPORT path | `src/agent_team_v15/cli.py` (~line 4736) | `integration_audit_dir = str(req_dir)` (not `req_dir / ".agent-team"`). Test: verify integration audit writes to `<cwd>/.agent-team/AUDIT_REPORT.json` not `<cwd>/.agent-team/.agent-team/...` |
| **#4b** finding_id schema | `src/agent_team_v15/audit_models.py` | `AuditFinding.from_dict` accepts both `finding_id` and `id` keys, both `summary` and `title`, both `remediation` and `fix_action`. Test: both schema shapes parse correctly; empty dict produces safe defaults |
| **#5** PRD-vs-cwd recovery | (check what file they touched per 063b009) | Artifacts written to PRD's dir get moved/copied into `<cwd>/.agent-team/` before the plan-validation check. Test: split-layout build (PRD at /A, cwd at /B) produces MASTER_PLAN.md at /B/.agent-team/ |
| **#6** CLAUDECODE pop | `src/agent_team_v15/cli.py` `main()` | First line of `main()` is `os.environ.pop("CLAUDECODE", None)`. Test: subprocess spawn doesn't inherit the var |
| **#7** operationId dedup | `src/agent_team_v15/openapi_generator.py` (~1057) | `_unique_operation_name` called with a shared `_used_op_names` set. Test: 3 handlers named "create" across different routes produce 3 distinct operationIds |
| **#8** OpenAPI scaffold | `src/agent_team_v15/scaffold_runner.py` | NestJS scaffold drops `scripts/generate-openapi.ts` + `tsx` devDep + `@nestjs/swagger`. Test: scaffold a fake NestJS project, assert the script + deps exist |
| **#9 Tier 1** stack prompt | `src/agent_team_v15/agents.py` | `_STACK_INSTRUCTIONS` replaced with builder functions parametrized on ORM + layout. Test: `get_stack_instructions(text, orm="prisma")` returns content with `@prisma/client` and NOT `@nestjs/typeorm`; inverse for `orm="typeorm"` |
| **#10** Wave D/D.5 watchdog | `src/agent_team_v15/wave_executor.py` | Per-wave timeout with heartbeat file, kills subprocess + writes hang report on timeout. Test: mock a hanging SDK call, verify watchdog fires and produces hang report JSON |
| **#11** frontend hallucinations | `src/agent_team_v15/quality_checks.py` | New scanners: `LOCALE-HALLUCINATE-001` (locale not in PRD), `FONT-SUBSET-001` (invalid Google Font subset). Test: `locale as 'en' \| 'ar' \| 'id'` flagged when PRD says en+ar only; `Inter({ subsets: ['arabic'] })` flagged |

For each row: **either** confirm the fix is present AND tested AND behaviorally correct, **or** file a specific gap (e.g., "fix #8 is present but only covers `.ts`, not `.js` or `.mjs`"). Document gaps in your final report — do not silently fix them in this session (it blurs the review-vs-implement boundary).

### Review methodology

For each modified file:
1. `git show 063b009:<file>` or `git diff 51a7409..063b009 -- <file>`
2. Read the relevant plan in `docs/plans/` — map every requirement in the plan's **Acceptance Criteria** to a line in the diff
3. Run the corresponding test(s) in isolation to confirm they actually exercise the fix (`pytest -v tests/<file> -k <test>`)
4. Spot-check with a manual case if the test doesn't cover a specific scenario

### What to flag

- **Missing coverage** — fix claims to do X but test doesn't verify X
- **Partial implementation** — fix solves one case but misses a listed sibling case
- **Accidental breakage** — fix touches unrelated code paths (e.g., a typo introduced in a different function)
- **Plan deviation** — fix implements something different from what the plan spec'd (not necessarily wrong, but worth flagging)
- **Dead code** — helpers added but never called

---

## 3. Run the full test suite

The partial runs in `063b009`'s commit message covered touched areas plus a few extras. For this review, run the complete suite.

```bash
# Full suite, verbose output, capture for the report
pytest tests/ -v 2>&1 | tee /tmp/full_test_run.log

# Also run with coverage so gaps are visible
pytest tests/ --cov=src/agent_team_v15 --cov-report=term-missing 2>&1 | tee /tmp/coverage.log

# Isolated targeted runs for the bug-fix areas (for the matrix)
pytest tests/test_compile_profiles.py -v
pytest tests/test_milestone_manager.py -v
pytest tests/test_audit_models.py -v
pytest tests/test_openapi_generator.py -v
pytest tests/test_agents.py -v
pytest tests/test_scaffold_runner.py -v
pytest tests/test_quality_checks.py -v
pytest tests/test_wave_executor_extended.py -v  # or whatever Wave D watchdog test file is
pytest tests/test_stack_contract.py -v          # your NEW Tier 2 tests
```

### Allowed exceptions

- Tests marked `@pytest.mark.integration` or `@pytest.mark.e2e` may require real API keys — skip if credentials unavailable, but note which were skipped
- Existing pre-baseline failures (unrelated to any of our fixes) — note but don't fix
- The commit message mentions "existing coroutine warnings" in the CLI test slice — warnings are OK; failures are not

### Forbidden

- Do NOT skip tests you don't understand. Investigate.
- Do NOT mark tests as `@pytest.mark.skip` to make a suite green. If a test legitimately needs to be skipped, add a reason and link it to a specific plan/bug number.
- Do NOT modify existing tests to make them pass without documenting why.

---

## 4. Produce the verification report

Save to `docs/plans/2026-04-14-tier2-and-fix-verification-report.md`. Include:

### Sections

1. **TL;DR** — one paragraph: did Tier 2 land cleanly? Did all 11 prior fixes check out? Full suite pass/fail count?
2. **Tier 2 implementation summary** — files added/modified, LOC, test coverage percentage for new code, any deviations from the plan with justification
3. **Fix-review matrix** — one row per fix from the table in Section 2 above. Columns: `Fix # | File(s) | Present? | Behaviorally correct? | Test coverage? | Notes/Gaps`
4. **Test suite results** — full counts (N passed, N failed, N skipped, N errored), failing tests with short root-cause analysis, coverage percentage by module with focus on modified files
5. **Risks identified** — anything that might bite the smoke test re-run. Examples: "Tier 2's retry budget is 1 but Wave A prompt-drift may need 2" or "Bug #10 watchdog timeout is 30 min but Wave D.5 has been observed running 15+ min in healthy cases — may false-positive"
6. **Recommended smoke test re-run posture** — given your findings, should the smoke test proceed? If yes, any adjustments to the re-run brief at `docs/plans/2026-04-14-smoke-test-rerun-handoff.md`?

### Format guidance

- Every claim backed by file:line references or test names
- Every gap flagged gets a specific follow-up (file a new plan or a specific commit request — don't leave "should probably be fixed somehow")
- Keep it structured; the user will skim first, read depth second

---

## 5. Guardrails

- **Work on a branch.** Don't commit directly to master. Use a feature branch like `bug-9-tier-2-stack-contract-validator`.
- **Commit cadence:** one logical commit per component. Suggested split:
  1. `feat(stack-contract): add StackContract dataclass + builtin registry`
  2. `feat(stack-contract): add derive_stack_contract with confidence ladder`
  3. `feat(stack-contract): add validate_wave_against_stack_contract scanner`
  4. `feat(wave-executor): integrate stack-contract validator with retry policy`
  5. `feat(state): persist stack_contract in RunState`
  6. `feat(telemetry): emit stack_contract_violations per wave`
  7. `test: StackContract validator + wave executor integration`
  8. Optional cleanup commits
- **Never skip hooks** (`--no-verify`, `--no-gpg-sign`). If a hook fails, investigate.
- **Don't touch the worktree's unrelated changes** noted in 063b009's message: `src/agent_team_v15/product_ir.py`, `tests/test_product_ir.py`, `tests/test_v18_stage1.py`, `docs/run-artifact*`. Those are in flight from another workstream.
- **Don't re-implement prior fixes.** Review only. Gaps get reported, not fixed silently.
- **Don't launch the smoke test.** That's a separate session's job.

---

## 6. Success criteria for this session

- [ ] All 11 fixes present in `063b009` reviewed against their plans with a matrix row each
- [ ] Tier 2 implemented completely per the plan's "TIER 2" acceptance-criteria list (every checkbox in that list ticked)
- [ ] `tests/test_stack_contract.py` (and any sibling new test files) added with ≥80% coverage of new code
- [ ] Full `pytest tests/` run completed with results captured; suite is green OR failures are individually analyzed and linked to plans
- [ ] Verification report saved at `docs/plans/2026-04-14-tier2-and-fix-verification-report.md`
- [ ] Branch pushed with clean commit history, ready for review
- [ ] The smoke-test re-run brief (`docs/plans/2026-04-14-smoke-test-rerun-handoff.md`) either validated as still accurate or flagged for updates based on your findings

---

## 7. If stuck

1. Read `docs/plans/2026-04-13-v18-smoke-test-bugs-index.md` — the master index of every bug and its status
2. Read the specific bug's plan document in `docs/plans/` — each has a "⚠️ NOTE TO THE IMPLEMENTING AGENT" with investigation steps
3. Read `v18 test runs/build-c-hardened-clean/FINAL_COMPARISON_REPORT.md` — yesterday's ground-truth on what healthy build behavior looks like
4. Read the Tier 2 section of `docs/plans/2026-04-13-stack-contract-enforcement-plan.md` — it's the spec, not just documentation

If still stuck after those four, report to the user with: what you tried, what you expected, what happened, and what specifically confuses you. Don't guess.

---

## 8. Don't do these

- Don't "improve" Tier 1. Tier 1 is landed and working. Tier 2 is layered on top.
- Don't add builtin stack contracts beyond the 8 in the plan's matrix. (Go, Rust, Kotlin, etc. are out of scope until real smoke tests demand them.)
- Don't turn advisory Wave B/D validation into blocking. The plan explicitly says advisory, because rolling back 70 Wave B files costs too much.
- Don't add retries beyond the single retry the plan specifies. Hallucinated second retries are where costs spiral.
- Don't ship Tier 2 without its tests. The whole value of Tier 2 is automated enforcement — untested enforcement is theater.

Write the report. Push the branch. Tag the user.
