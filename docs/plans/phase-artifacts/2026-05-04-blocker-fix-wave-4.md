# Wave 4 close memo - operational guards and B9 forward-compat

**Date:** 2026-05-05
**Parent branch:** `phase-5-closeout-stage-1-remediation`
**Wave 4 start HEAD:** `fadf15f`
**Wave 4 source tips:** OP4 `cb0ca1e`, OP5 `2c78835`, OP1 `a344d22`, OP2 `4f590f2`, OP3 `6862e6e`, OP6 `2eeb858`, B9 `6339808`
**Wave 4 scope:** OP1, OP2, OP3, OP4, OP5, OP6, and B9 only.

---

## Outcome

Wave 4 source is merged onto the parent branch at `6339808` with linear history. The locked order was preserved: OP4 -> OP5 -> OP1 -> OP2 -> OP3 -> OP6 -> B9. No paid smokes were run, and no master merge occurred.

The approval gate is failure-nodeid stability across the integrated Wave 4 line. The post-B9 integrated sweep introduced **0 new failure nodeids** and removed **0 baseline failure nodeids** versus the OP6 integrated baseline.

---

## Final Wave 4 Commit Chain

```
6339808 fix(b9): add UserMessage tool result forward-compat branch
8eb81a1 docs: record Wave 4 OP6 status
2eeb858 fix(op6): record Stage 2B clean closeout truth
e8e3014 docs: record Wave 4 OP3 status
6862e6e fix(op3): gate Stage 2B on split validation preflight
cf1c669 docs: record Wave 4 OP2 status
4f590f2 fix(op2): split terminal diagnostic counts
fe0aaf8 docs: record Wave 4 OP1 status
a344d22 fix(op1): add strict Codex CLI version gate
37a1f22 docs: record Wave 4 OP5 status
2c78835 fix: persist state on SIGTERM
b045ee3 docs: record Wave 4 OP4 status
cb0ca1e fix(op4): rename schema validation pass summary
```

---

## Items Closed

| Item | Final integrated tip | Reviewer/tester state | Test delta / proof |
|---|---|---|---|
| **OP4** | `cb0ca1e` | Internal reviewer PASS; tester PASS; outside reviewer NOT-FLAGGED | `Schema: CLEAN` renamed to `Schema validation: PASS`; `_phase_4_5_terminal_transport_failure_reason` remained byte-identical and preflight-first. |
| **OP5** | `2c78835` | Internal reviewer PASS; tester PASS; outside reviewer NOT-FLAGGED | SIGTERM handler sets `interrupted=True`, saves `STATE.json`, exits 143, is re-entrant safe, and contains no unsafe `killpg` path. |
| **OP1** | `a344d22` | Internal reviewer PASS after R4; tester PASS; outside reviewer NOT-FLAGGED | `--strict-codex-cli-version` is default-off; strict drift raises `CodexCliVersionDriftError` through the live PRD/provider path. R4 closed the outer orchestration catch boundary. |
| **OP2** | `4f590f2` | Internal reviewer PASS; tester PASS; outside reviewer NOT-FLAGGED | Stage-2B batch records add `terminal_diagnostic_count` without replacing K.2 diagnostic fields or consumers. |
| **OP3** | `6862e6e` | Internal reviewer PASS after R3; tester PASS; outside reviewer NOT-FLAGGED | Split-validation preflight gates paid milestone entry and Stage-2B preseeded dispatch before launcher rendering; failures write `SPLIT_VALIDATION_PRECONDITION_FAILED.json` and abort before dispatch. |
| **OP6** | `2eeb858` | Internal reviewer PASS after R5; tester PASS; outside reviewer NOT-FLAGGED | Stage-2B batch records write `state_truth.clean_closeout` with AND-joined truth semantics across state evidence, rc, failed milestones, pending milestones, and Gate 7 findings. |
| **B9** | `6339808` | Internal reviewer PASS; tester PASS; outside reviewer NOT-FLAGGED | `_consume_response_stream` now has a forward-compat `UserMessage` branch after `AssistantMessage` and `ResultMessage`; it handles `ToolResultBlock` with debug/progress/orphan-detector completion and does not enable `replay-user-messages`. |

---

## Reviewer Iterations

| Item | Internal/outside reviewer result | Corrective notes |
|---|---|---|
| **OP4** | PASS / NOT-FLAGGED | Rename stayed in the final schema-validation summary surface; static lock preserved the Wave 3 terminal transport classifier. |
| **OP5** | PASS / NOT-FLAGGED | Handler registers `SIGTERM` alongside `SIGINT` and preserves all three required invariants in one re-entrant path. |
| **OP1** | PASS after R4 / NOT-FLAGGED | R4 re-raised `CodexCliVersionDriftError` before the broad outer orchestration interruption catch. Heightened criterion (e) found no adjacent defect. |
| **OP2** | PASS / NOT-FLAGGED | Terminal diagnostics are counted separately from K.2 diagnostics while existing K.2 field names and values remain stable. |
| **OP3** | PASS after R3 / NOT-FLAGGED | R3 fixed authored `MASTER_PLAN.md` metadata precedence so generated JSON cannot mask missing split fields. |
| **OP6** | PASS after R5 / NOT-FLAGGED | Corrective rounds closed nonzero-rc sequencing, missing/invalid state evidence, and R5's passed-gate-audit vs finding-shaped `gate_results` distinction. Heightened criterion (e) found no adjacent defect. |
| **B9** | PASS / NOT-FLAGGED | Branch is forward-compat only: no SDK flag flip, no `extra_args={"replay-user-messages"}` addition, and the existing `AssistantMessage` `ToolResultBlock` path is byte-locked unchanged. |

---

## Verification

Final integrated B9/adjacent slice:

```
PYTHONPATH=src uv run pytest -q tests/test_m1_wave4_b9_user_message_forward_compat.py tests/test_cli_sdk_session_watchdog.py tests/test_bug12_claim_verification.py tests/test_pipeline_upgrade_phase5_7.py
```

Result: `68 passed in 2.92s`.

Static and compile locks:

```
uv run python -m py_compile src/agent_team_v15/cli.py
git diff --check HEAD~1..HEAD
```

Results: both clean.

Integrated parent sweep:

```
PYTHONPATH=src uv run pytest -q 2>&1 | tee /tmp/wave4-b9-integrated-6339808-pytest.log
```

Result: `34 failed, 12786 passed, 46 skipped, 2 deselected, 20 warnings in 423.89s`.

Failure-nodeid comparison:

- Baseline failures: `/tmp/wave4-op6-integrated-2eeb858-failures.nodeids.txt` (34 nodeids)
- Current failures: `/tmp/wave4-b9-integrated-6339808-failures.nodeids.txt` (34 nodeids)
- New failures: `/tmp/wave4-b9-integrated-6339808-new.nodeids.txt` (0)
- Removed failures: `/tmp/wave4-b9-integrated-6339808-removed.nodeids.txt` (0)
- Direct compare: current failure list is byte-identical to the OP6 integrated baseline (`cmp_rc=0`).

---

## Bug-Reproduction Proofs

| Item | Proof shape |
|---|---|
| **OP4** | OP4 tests failed on the pre-fix summary string and codebase old-string scan, then passed after the rename; static hash locked the unrelated terminal transport classifier. |
| **OP5** | OP5 tests failed on the pre-fix missing SIGTERM handler, then passed after adding `interrupted=True`, `save_state`, and `sys.exit(143)` in the registered handler. |
| **OP1** | OP1 tests failed before strict drift raised a typed error through the live PRD/provider path; R4 proof failed before the outer catch re-raised `CodexCliVersionDriftError`, then passed after the catch-boundary fix. |
| **OP2** | OP2 tests failed before `terminal_diagnostic_count` existed and before terminal/K.2 counts were separated, then passed after the Stage-2B aggregation change. |
| **OP3** | OP3 tests failed before split metadata preflight and the authored-MD precedence fix, then passed after the pre-dispatch gate wrote the precondition artifact and aborted. |
| **OP6** | OP6 tests failed before `state_truth.clean_closeout` was written and before missing/invalid state evidence forced false, then passed after the R5 aggregate/per-smoke truth fix. |
| **B9** | Parent plus B9 tests failed `4 failed, 1 passed`; reapplying the B9 source passed `5 passed`. |

---

## Harness And Coordination Notes

- Wave 4 preserved the locked sequential order because the harness `isolation: "worktree"` flag is not actual isolation in this environment.
- Each source item landed as one atomic branch commit with tests in the same commit. Documentation status commits were made separately on the integration branch after each approved merge.
- Outside-reviewer NOT-FLAGGED was the merge gate for every item. OP1 and OP6 triggered heightened criterion (e) scrutiny after round 4; neither introduced adjacent defects.
- Worktree remains dirty only with unrelated local residue, notably `.claude/settings.local.json` and untracked run artifacts. Wave 4 evidence is scoped to committed source/doc paths and `/tmp` verification logs.
- No containment fixes, paid smokes, master merge, force-push, destructive cleanup, or broad staging were used.
