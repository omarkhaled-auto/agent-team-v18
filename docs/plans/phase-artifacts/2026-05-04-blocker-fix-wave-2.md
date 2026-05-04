# Wave 2 close memo - B6 Docker/TypeScript parity

**Date:** 2026-05-04
**Parent branch:** `phase-5-closeout-stage-1-remediation`
**Wave 2 branch:** `wave-2-b6`
**Wave 2 start HEAD:** `8ded3b9`
**Wave 2 source tip:** `fbbe2e2`
**Wave 2 scope:** B6 only, split into B6a + B6b + B6c.

---

## Outcome

Wave 2 B6 source is merged onto the parent branch at `fbbe2e2` with linear history and no master merge. No paid smokes were run inside the initiative.

The approval gate is failure-name stability against the Wave 1 integrated baseline: the post-merge sweep at `fbbe2e2` has zero new failure names vs `/tmp/wave1-cleanup-integrated-pytest.log`.

---

## Final Wave 2 Commit Chain

```
fbbe2e2 fix(build): self-verify via Compose lint target (B6c)
3b137a9 fix(build): add full-scope Docker lint stages (B6b)
363ac35 fix(build): sanitize BuildKit-prefixed tsc stderr (B6a)
```

---

## Items Closed

| Item | Final tip | Reviewer/tester state | Test delta / proof |
|---|---|---|---|
| **B6a** | `363ac35` | Internal reviewer PASS; tester PASS_WITH_BASELINE_REDS | BuildKit progress-prefix sanitizer applied before TypeScript parsing; 4 parser regressions added. |
| **B6b** | `3b137a9` | Internal reviewer PASS; tester PASS_WITH_BASELINE_REDS | API/web Dockerfile lint stages use `tsconfig.json`; production build stages preserved. |
| **B6c** | `fbbe2e2` | Internal reviewer PASS after 2 corrective rounds; tester PASS_WITH_BASELINE_REDS | Wave B/D 5.6c now uses Compose `build.target: lint`; mandatory Docker integration proof covers `.spec.ts` strict error through live Wave B self-verify. |

---

## Reviewer Iterations

| Sub-fix | Internal reviewer result | Corrective notes |
|---|---|---|
| **B6a** | PASS | Reviewer accepted `retry_feedback.py` as the live Docker retry-payload parser path. |
| **B6b** | PASS | One pre-review correction folded into B6b: API lint stage now runs Prisma generate before `tsc`. |
| **B6c** | REJECT → PASS → PASS | Round 1 caught a live-path gap: BuildKit TypeScript diagnostics can land on stdout while `docker_build()` preserved only stderr. `fbbe2e2` combines stdout+stderr for failed builds and strengthens the integration test to exercise `docker_build()` and `run_wave_b_acceptance_test()`. Round 3 was test-only: update `test_wave_b_self_verify_env_skip.py` for the new `parallel=False` call shape. |

Outside reviewer verdict: **NOT-FLAGGED** on integrated `8ded3b9..fbbe2e2`.

---

## Verification

Targeted B6c integrated slice:

```
PYTHONPATH=src uv run pytest tests/test_pipeline_upgrade_phase5_6.py tests/templates/test_pnpm_monorepo_render.py tests/test_runtime_verification.py tests/wave_executor/test_wave_b_self_verify.py tests/test_pipeline_upgrade_phase4_1.py tests/test_b5_wave_d_scaffold_stub_sanity.py tests/templates/test_pnpm_monorepo_lint_target_integration.py -q
```

Result: `165 passed`.

Additional locks:

```
PYTHONPATH=src uv run pytest tests/test_pipeline_upgrade_phase4_2.py -q
PYTHONPATH=src uv run pytest tests/test_b3_b12_capture_metadata_forensics.py -k 'cumulative_wedges_so_far or all_outer_hang_report_sites_thread' -q
git diff --check 8ded3b9..fbbe2e2
```

Results: `40 passed`; `1 passed, 20 deselected`; diff-check clean.

Integrated parent sweep:

```
PYTHONPATH=src uv run pytest tests -q 2>&1 | tee /tmp/wave2-integrated-fbbe2e2-pytest.log
```

Result: `34 failed, 12669 passed, 46 skipped, 2 deselected, 20 warnings in 397.96s`.

Failure-name comparison:

- Baseline file: `/tmp/wave1-cleanup-integrated-pytest.log`
- Current failures: `/tmp/wave2-integrated-fbbe2e2-failures.txt`
- Baseline failures: `/tmp/wave1-cleanup-integrated-failures.txt`
- New failures vs baseline: **0**
- Disappeared failures vs baseline: **0**

---

## Bug-Reproduction Proofs

| Sub-fix | Proof shape |
|---|---|
| **B6a** | Parser tests failed on pre-fix input with BuildKit `#<step> <ts>` prefixes, then passed after sanitizer. Required prefixed/plain/mixed/multiline cases are in `tests/test_pipeline_upgrade_phase4_2.py`. |
| **B6b** | Dockerfile snapshot tests failed before lint stages existed; API Prisma-before-TSC test failed before lint-stage Prisma generate was added. Both pass at `3b137a9`. |
| **B6c** | Red tests initially showed missing 5.6c Compose build, missing Compose `target: lint`, and missing production-path `tsc_failures`. Reviewer round 1 found stdout BuildKit diagnostics dropped by `docker_build()`. Final proof in `tests/templates/test_pnpm_monorepo_lint_target_integration.py` runs direct `docker compose build api`, then verifies `docker_build()` and real Wave B self-verify populate `TS2322` from a `.spec.ts` strict error. |

---

## Harness And Coordination Notes

- TeamCreate is not available in this Codex toolset; Wave 2 used named Codex subagents matching the required roles (`impl-b6`, internal reviewer, tester, outside reviewer) and kept one implementer lane for the three sub-fixes.
- `impl-b6` timed out during B6c scope check; the orchestrator closed that lane and completed B6c locally to avoid unobserved edits.
- Worktree remains dirty only with unrelated pre-existing residue, notably `.claude/settings.local.json` and untracked run artifacts. B6 evidence is scoped to commit boundary `8ded3b9..fbbe2e2`.
- No containment changes were introduced. No `docker compose build --target` command path was added. No master merge occurred.
