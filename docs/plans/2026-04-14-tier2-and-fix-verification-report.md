# 2026-04-14 Tier 2 And Fix Verification Report

## TL;DR

Bug `#9 Tier 2` is implemented and verified functionally, but the repository is not green. The new stack-contract path is present in `src/agent_team_v15/stack_contract.py:87-777`, is persisted through `src/agent_team_v15/state.py:89,359,545` and `src/agent_team_v15/cli.py:816-831,2725-2741`, is injected into Wave A prompts in `src/agent_team_v15/agents.py:7759-7872,8927-8963`, and is enforced in `src/agent_team_v15/wave_executor.py:2417-2751`. Focused Tier 2 tests passed (`108 passed`), but the required full suite and coverage runs both failed in the same place: `tests/test_milestone_manager.py::TestParseDeps::*` now fails five legacy `m-1` shorthand cases because `_parse_deps()` only preserves canonical `milestone-N` and `M1`/`m2` shorthand (`src/agent_team_v15/milestone_manager.py:843-875`). Not all prior fixes in `063b009` check out cleanly: `#2` is a real regression, `#8` is only partially implemented, and several other rows have coverage or plan-deviation gaps.

## Tier 2 Implementation Summary

Files added or modified for Tier 2:

- `src/agent_team_v15/stack_contract.py:87-777` adds `StackContract`, `StackViolation`, builtin registry, synthesis fallback, derivation, persistence helpers, prompt rendering, and deterministic validation.
- `src/agent_team_v15/cli.py:816-831,2725-2741,3192-3200,3800-3808` derives or reloads the contract once, persists it to `.agent-team/STACK_CONTRACT.json`, stores it in `RunState`, and passes it into both milestone-wave execution paths.
- `src/agent_team_v15/state.py:89,359,545` persists `stack_contract` through save/load/resume.
- `src/agent_team_v15/agents.py:7759-7872,8927-8963` injects the contract block twice into Wave A and appends rejection context plus the `WAVE_A_CONTRACT_CONFLICT.md` escape hatch rule.
- `src/agent_team_v15/wave_executor.py:107-109,391-393,2012-2048,2417-2751` adds per-wave contract telemetry, Wave A retry-on-violation, advisory checks for Waves B and D, and loud failure on `WAVE_A_CONTRACT_CONFLICT.md`.
- `docs/stack-contracts.md:3-46` documents the model and validator.
- Tests added or extended: `tests/test_stack_contract.py:23-234`, `tests/test_wave_executor_stack.py:150-261`, `tests/test_v18_specialist_prompts.py:159-189`, `tests/test_state.py:210-224`.

Approximate diff size for this Tier 2 slice is `1850` added lines and `11` deleted lines across code, tests, and docs, based on local diffstat plus the four new-file line counts.

Coverage for the new or directly touched Tier 2 surfaces from the required full coverage run:

- `src/agent_team_v15/stack_contract.py`: `81%`
- `src/agent_team_v15/wave_executor.py`: `85%`
- `src/agent_team_v15/agents.py`: `85%`
- `src/agent_team_v15/state.py`: `97%`
- `src/agent_team_v15/cli.py`: `33%` overall, reflecting the size of the existing CLI module rather than weak Tier 2 spot coverage

Focused Tier 2 verification:

- `pytest tests/test_stack_contract.py tests/test_wave_executor_stack.py tests/test_v18_specialist_prompts.py tests/test_state.py -q`
- Result: `108 passed in 30.66s`

Plan deviations or notable implementation choices:

- The new enforcement path works, but `execute_milestone_waves()` now immediately delegates to `_execute_milestone_waves_with_stack_contract()` and leaves the old body unreachable under `src/agent_team_v15/wave_executor.py:2033-2048`. This is dead-code debt, not a functional failure.
- The plan originally described a strict builtin-only registry plus follow-up additions. The implementation keeps the required builtin matrix and also synthesizes contracts for non-builtin pairs such as `Express + Drizzle` in `src/agent_team_v15/stack_contract.py:311-404`. That is a deliberate extension to satisfy the three-stack test matrix without expanding the builtin registry itself.

## Fix-Review Matrix

| Fix # | File(s) | Present? | Behaviorally correct? | Test coverage? | Notes / Gaps |
| --- | --- | --- | --- | --- | --- |
| `#1` | `src/agent_team_v15/compile_profiles.py` | Yes | Yes | Partial | Absolute path handling is present at `compile_profiles.py:171,290,395,455,480,489`. `tests/test_v18_phase2_wave_engine.py::test_compile_profiles_scope_backend_and_frontend_targets` passed in the focused Wave Engine slice (`5 passed, 17 deselected`), and a manual spot-check with a relative repo-local `--cwd` printed an absolute `--project` path. Gap: the later "add tests" note in `2026-04-13-in-tree-fixes-summary.md` is still open; there is no dedicated `tests/test_compile_profiles.py` coverage for the absolute-path claim. |
| `#2` | `src/agent_team_v15/milestone_manager.py` | Yes | No | Yes, failing | The prose filter is present at `milestone_manager.py:843-875`, and a manual check returned `['milestone-1']` for `- Description: Scaffold, M1, Next.js web app` with warnings for dropped prose. But the fix regressed legacy shorthand handling: `_parse_deps("m-1,m-2,m-3")` now returns `[]`, which breaks five existing tests. Failures are `tests/test_milestone_manager.py::TestParseDeps::test_comma_separated_no_spaces`, `test_extra_whitespace`, `test_trailing_comma`, `test_leading_comma`, and `test_empty_between_commas`. Full suite and focused run both failed here. |
| `#4a` | `src/agent_team_v15/cli.py` | Yes | Likely yes | No direct coverage found | The path fix is present at `cli.py:4895` as `integration_audit_dir = str(req_dir)`. This matches the plan and removes the double `.agent-team` nesting. I did not find an isolated regression test that verifies `AUDIT_REPORT.json` lands at `<cwd>/.agent-team/AUDIT_REPORT.json`; the summary doc also explicitly called this out as not directly tested in the smoke session. |
| `#4b` | `src/agent_team_v15/audit_models.py` | Yes | Yes | Partial | Alias handling is present at `audit_models.py:79,86,88`. `tests/test_audit_models.py -k "from_dict" -q` passed (`3 passed, 56 deselected`). Manual spot-checks also confirmed `AuditFinding.from_dict({"id": ..., "title": ..., "fix_action": ...})` maps into `finding_id`, `summary`, and `remediation`, and `{}` safely defaults to empty strings plus `confidence=1.0` and `source='llm'`. Gap: the current tests do not explicitly exercise the alternate-key alias shape the plan asked for. |
| `#5` | `src/agent_team_v15/agents.py`, `src/agent_team_v15/cli.py` | Yes | Yes | Partial | Prompt-side absolute output anchoring is present at `agents.py:6147-6170`. Recovery from PRD-directory artifacts is present at `cli.py:769-784,2542` and is directly covered by `tests/test_cli.py::TestRecoverDecompositionArtifacts::test_recovers_master_plan_artifacts_from_prd_directory`, which passed (`1 passed, 153 deselected`). Gap: I did not find a test that asserts the prompt itself now names absolute output paths, only the recovery behavior. |
| `#6` | `src/agent_team_v15/cli.py` | Yes | Likely yes | No direct coverage found | The environment scrub is present at `cli.py:8433` with the preceding rationale at `cli.py:8428-8432`. I did not find any direct subprocess inheritance test in the suite. This row remains a code-inspection confirmation rather than a test-backed confirmation. |
| `#7` | `src/agent_team_v15/openapi_generator.py` | Yes | Yes | Partial | Shared-name dedupe is present at `openapi_generator.py:719-745,1057-1062`. `tests/test_v18_phase2_wave_engine.py::test_generate_openapi_contracts_fails_on_duplicate_operation_ids` passed in the focused Wave Engine slice, and a manual spot-check of `_unique_operation_name()` produced `create`, `createUsers`, `createTeams` for repeated `operationId='create'`. Gap: the requested dedicated `tests/test_openapi_generator.py` does not exist, so the exact "three handlers named create" case is covered manually rather than by a named regression test. |
| `#8` | `src/agent_team_v15/scaffold_runner.py` | Partial | Partial | Partial | The script itself is scaffolded at `scaffold_runner.py:142-149`, and `tests/test_scaffold_runner.py -q` passed (`6 passed`). `tests/test_v18_phase2_wave_engine.py::test_generate_openapi_contracts_uses_scaffolded_script_when_present` also passed in the focused Wave Engine slice. But the plan required package/dependency wiring too, and that is missing: the file contains no `package.json`, `tsx`, or dependency mutation logic, and a manual scaffolding spot-check produced `script=True`, `swagger=False`, `tsx=False`. This means `#8` is not fully implemented relative to its plan. |
| `#9 Tier 1` | `src/agent_team_v15/agents.py` | Yes | Yes | Yes, with deviation | ORM-aware prompt behavior exists in `agents.py:1960-2079,2102-2114`. `tests/test_agents.py -k "prisma_research or monorepo" -q` passed (`4 passed, 367 deselected`), and the focused broader suites were green earlier in the session. Plan deviation: instead of the explicit `get_stack_instructions(text, orm, layout)` API described in the plan, the landed code infers ORM/layout from `text + tech_research_content` inside `get_stack_instructions(text, tech_research_content)` at `agents.py:2102-2114`. Behaviorally the Prisma and monorepo cases work, but the interface does not match the original plan verbatim. |
| `#10` | `src/agent_team_v15/config.py`, `src/agent_team_v15/wave_executor.py` | Yes, with deviation | Yes for the implemented design | Yes | Config defaults are present at `config.py:792-794`. Watchdog/hang-report behavior is wired at `wave_executor.py:101-104,156-185,704-766,1639-1658`, and `tests/test_v18_phase2_wave_engine.py::test_execute_milestone_waves_retries_sdk_timeout_once_and_writes_hang_report` passed in the focused Wave Engine slice. Plan deviation: the original plan specified a heartbeat file and explicit subprocess kill on timeout; the landed implementation uses in-memory last-message state and a stream-idle timeout instead. It still writes hang reports and retries once, but it is not the heartbeat-file design the plan described. |
| `#11` | `src/agent_team_v15/quality_checks.py`, `src/agent_team_v15/wave_executor.py` | Yes, narrowed | Yes for the two implemented scanners | Yes | The scanner entry point is `quality_checks.py:5235-5249`; locale and font checks are at `quality_checks.py:5171-5223`. `tests/test_quality_checks.py` covers both known cases (`LOCALE-HALLUCINATE-001` at line `186`, `FONT-SUBSET-001` at line `200`), and the focused Wave Engine slice passed the persistent-violation gate test. Gap versus the original plan: the broader "three additional hallucination classes" follow-up was intentionally not implemented. The current fix is the narrow two-scanner slice only. |

## Test Suite Results

Required full-suite run:

- Command: `pytest tests/ -v`
- Result: `9941 passed, 5 failed, 35 skipped, 0 errors, 8 warnings in 516.78s (0:08:36)`

Required coverage run:

- Command: `pytest tests/ --cov=src/agent_team_v15 --cov-report=term-missing`
- Result: `9941 passed, 5 failed, 35 skipped, 0 errors, 8 warnings in 534.98s (0:08:54)`
- Total coverage: `73%`

Focused verification runs completed in this session:

- `pytest tests/test_stack_contract.py tests/test_wave_executor_stack.py tests/test_v18_specialist_prompts.py tests/test_state.py -q` -> `108 passed in 30.66s`
- `pytest tests/test_v18_phase2_wave_engine.py -k "compile_profiles_scope_backend_and_frontend_targets or generate_openapi_contracts_uses_scaffolded_script_when_present or generate_openapi_contracts_fails_on_duplicate_operation_ids or retries_sdk_timeout_once_and_writes_hang_report or blocks_d5_on_persistent_frontend_hallucinations" -q` -> `5 passed, 17 deselected in 4.27s`
- `pytest tests/test_milestone_manager.py -k "TestParseDeps" -q` -> `5 failed, 9 passed, 117 deselected in 0.43s`
- `pytest tests/test_cli.py -k "RecoverDecompositionArtifacts" -q` -> `1 passed, 153 deselected in 0.16s`
- `pytest tests/test_scaffold_runner.py -q` -> `6 passed in 0.16s`
- `pytest tests/test_audit_models.py -k "from_dict" -q` -> `3 passed, 56 deselected in 0.16s`
- `pytest tests/test_agents.py -k "prisma_research or monorepo" -q` -> `4 passed, 367 deselected in 0.20s`

Failing tests and root cause:

- `tests/test_milestone_manager.py::TestParseDeps::test_comma_separated_no_spaces`
- `tests/test_milestone_manager.py::TestParseDeps::test_extra_whitespace`
- `tests/test_milestone_manager.py::TestParseDeps::test_trailing_comma`
- `tests/test_milestone_manager.py::TestParseDeps::test_leading_comma`
- `tests/test_milestone_manager.py::TestParseDeps::test_empty_between_commas`

Root cause:

- `_parse_deps()` now intentionally filters non-canonical dependency tokens via `_short_form = re.compile(r"^[Mm](\d+)$")` and `_id_form = re.compile(r"^milestone-\d+$")` at `src/agent_team_v15/milestone_manager.py:854-856`, then drops everything else at `:864-873`.
- That fixes the new prose-bullet case, but it also drops historical `m-1` shorthand that the existing test suite still expects. This is a true regression until either the code regains `m-1` compatibility or the test contract is intentionally changed with documentation.

Coverage highlights for modified modules:

- `src/agent_team_v15/stack_contract.py`: `81%`
- `src/agent_team_v15/wave_executor.py`: `85%`
- `src/agent_team_v15/agents.py`: `85%`
- `src/agent_team_v15/state.py`: `97%`
- `src/agent_team_v15/quality_checks.py`: `84%`
- `src/agent_team_v15/scaffold_runner.py`: `83%`
- `src/agent_team_v15/compile_profiles.py`: `39%`
- `src/agent_team_v15/openapi_generator.py`: `66%`
- `src/agent_team_v15/milestone_manager.py`: `85%`
- `src/agent_team_v15/cli.py`: `33%`

Warnings:

- The same pre-existing coroutine warnings noted in earlier targeted runs are still present. They did not turn into failures, but they remain visible in both full-suite and coverage runs.

## Risks Identified

- `#2` is not just a coverage gap; it is an active regression. Any build path or parser consumer still emitting legacy `m-1` shorthand will now fail dependency parsing silently and then fail validation later. This is the main blocker to treating the branch as rerun-ready.
- `#8` remains incomplete relative to its plan. The generated `scripts/generate-openapi.ts` exists, but the scaffold does not add `tsx`, does not add `@nestjs/swagger`, and does not wire a package script. If a generated project lacks those dependencies already, Wave C still depends on fallback behavior rather than the intended primary path.
- `#10` is behaviorally useful but plan-divergent. Because it uses stream-idle state rather than a heartbeat file plus explicit subprocess kill, it may not catch every form of wedged child process the original plan was designed around.
- Tier 2 introduced unreachable legacy code in `wave_executor.py:2050+` because `execute_milestone_waves()` now returns immediately at `:2033-2048`. This did not fail tests, but it increases maintenance and review risk.
- `#4a` and `#6` are still weakly covered. Both appear correct in code, but the suite does not directly assert the repaired behaviors.

Recommended follow-ups:

- File a follow-up against `#2` to restore or explicitly retire legacy `m-1` shorthand with matching test updates.
- File a follow-up against `#8` to add package/dependency wiring and the missing scaffold tests the original plan called for.
- File a cleanup follow-up for the unreachable `wave_executor.py` body.

## Recommended Smoke Test Re-Run Posture

Recommendation: **do not proceed with the smoke-test rerun yet**.

Reasons:

- The required full suite is not green because of the `#2` parser regression.
- `#8` is only partially implemented, so Wave C may still succeed only because fallback extraction remains available.
- The rerun brief at `docs/plans/2026-04-14-smoke-test-rerun-handoff.md` assumes the in-tree smoke fixes are preflight-verified. It should be updated to add a hard prerequisite that the `_parse_deps` regression is resolved or explicitly accepted before launch.

If the rerun must happen before those follow-ups land, update the rerun brief with these caveats:

- Add a preflight item for `tests/test_milestone_manager.py -k TestParseDeps` and stop on failure.
- Add a note that `#8` currently guarantees the scaffolded script file, not the full `package.json` wiring; expect regex fallback to remain the operational safety net.
- Update the `#10` expectation text to match the current implementation: a stream-idle watchdog with hang reports and one retry, not the heartbeat-file design from the original plan.
