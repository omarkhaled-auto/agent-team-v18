# Wave 3 close memo - Codex appserver stability

**Date:** 2026-05-04
**Parent branch:** `phase-5-closeout-stage-1-remediation`
**Wave 3 start HEAD:** `7c1a85a`
**Wave 3 source tips:** B7 `311e257`, B8 `ac97a71`, B11 `806a7a3`
**Wave 3 scope:** B7, B8, B11 only.

---

## Outcome

Wave 3 source is merged onto the parent branch at `806a7a3` with linear history. The wave closed the Codex appserver instrumentation, repeated-EOF, and early-preflight blockers. No paid smokes were run, and no master merge occurred.

The approval gate is failure-name stability against immutable Wave 2 baseline `7c1a85a`: the post-B11 integrated sweep introduced **0 new failure nodeids** and removed **0 baseline failure nodeids**.

---

## Final Wave 3 Commit Chain

```
806a7a3 feat: add codex appserver preflight
826d3a7 docs: record Wave 3 B8 status
ac97a71 fix(codex): classify repeated appserver EOF as unstable
7c2d8da docs: record Wave 3 B7 status
311e257 fix(codex): harden appserver EOF diagnostics (B7)
```

---

## Items Closed

| Item | Final integrated tip | Reviewer/tester state | Test delta / proof |
|---|---|---|---|
| **B7** | `311e257` | Internal reviewer PASS; tester PASS; outside reviewer NOT-FLAGGED | Stderr ring bounded at 200, `RUST_BACKTRACE=1` and `RUST_LOG=info` ship together, `close()` drains stderr before cancellation with bounded `asyncio.wait_for(..., timeout=2.0)`, and EOF diagnostics add the three requested sub-classifications while parent-keyed consumers still match. |
| **B8** | `ac97a71` | Internal reviewer PASS after corrective rounds; tester PASS; outside reviewer NOT-FLAGGED | Retry-exhausted stdout EOF raises `CodexAppserverUnstableError`, a `CodexTerminalTurnError` subclass with `repeated_eof=True`; provider/wave/CLI catch-boundaries preserve `failure_reason="codex_appserver_unstable"` + exit 2. |
| **B11** | `806a7a3` | Internal reviewer PASS after corrective rounds; tester PASS; outside reviewer NOT-FLAGGED | New `_preflight_codex_appserver()` performs bounded startup/protocol preflight once per client/session and maps startup, initialize, dispatch, timeout, and turn failures to `CodexAppserverPreflightError` and `failure_reason="codex_appserver_preflight_failed"` + exit 2. |

---

## Reviewer Iterations

| Item | Internal/outside reviewer result | Corrective notes |
|---|---|---|
| **B7** | PASS / NOT-FLAGGED | Landed as one atomic commit with all four required sub-fixes and tests. |
| **B8** | PASS after R5 / NOT-FLAGGED | Corrective rounds closed catch-boundary completeness, parallel executor swallowing, CLI override failure-reason handling, and the R5 parallel-state halt gap by threading `milestone_id` through the typed exception. |
| **B11** | PASS after R3 / NOT-FLAGGED | R2 wrapped `client.start()` and `CodexDispatchError` failures into the preflight typed boundary. R3 updated legacy fake clients to model the new preflight turn without weakening EOF diagnostic or refined-interrupt assertions. |

The B11 rebase onto the B7+B8 parent had one conflict in `cli.py`'s terminal transport classifier. The resolved integrated code preserves B11's `codex_appserver_preflight_failed` classification first, then B8's `contains_transport_stdout_eof_classification(text)` generalized EOF/subtype classifier. Post-merge focused and full sweeps passed the Wave 3 gates, and the outside reviewer returned `OUTSIDE_REVIEW_B11_INTEGRATION_NOT_FLAGGED` on the conflict-resolution surface.

---

## Verification

Focused integrated B7+B8+B11 slice:

```
PYTHONPATH=src uv run pytest -q tests/test_bug20_codex_appserver.py tests/test_codex_dispatch_captures.py tests/test_b8_codex_appserver_unstable.py tests/test_b11_codex_appserver_preflight.py tests/test_h3h_interrupt_msg.py tests/test_phase_5_8_o_4_8_cap_halt_state.py tests/test_phase_5_8_codex_terminal_turn_propagation.py tests/test_provider_routing.py tests/test_v18_phase4_throughput.py::test_execute_parallel_group_limits_concurrency_and_merges_successes tests/test_v18_phase4_throughput.py::test_execute_parallel_group_merges_successful_worktrees_when_one_fails tests/test_v18_phase4_throughput.py::test_run_prd_milestones_uses_git_isolation_path_even_when_parallel_limit_is_one tests/test_pipeline_upgrade_phase5_4.py::test_phase_4_5_detector_recognizes_compile_repair_transport_eof
```

Result: `239 passed in 4.64s`.

Static and compile locks:

```
uv run python -m py_compile src/agent_team_v15/codex_appserver.py src/agent_team_v15/provider_router.py src/agent_team_v15/wave_executor.py src/agent_team_v15/cli.py src/agent_team_v15/parallel_executor.py src/agent_team_v15/codex_captures.py
git diff --check HEAD -- src/agent_team_v15/codex_appserver.py src/agent_team_v15/provider_router.py src/agent_team_v15/wave_executor.py src/agent_team_v15/cli.py src/agent_team_v15/parallel_executor.py src/agent_team_v15/codex_captures.py tests/test_bug20_codex_appserver.py tests/test_codex_dispatch_captures.py tests/test_b8_codex_appserver_unstable.py tests/test_b11_codex_appserver_preflight.py tests/test_h3h_interrupt_msg.py tests/test_phase_5_8_o_4_8_cap_halt_state.py tests/test_phase_5_8_codex_terminal_turn_propagation.py tests/test_provider_routing.py
```

Results: both clean.

Integrated parent sweep:

```
PYTHONPATH=src uv run pytest -q > /tmp/wave3-integrated-b11-806a7a3-pytest.log 2>&1
```

Result: `34 failed, 12707 passed, 46 skipped, 2 deselected, 18 warnings in 411.84s`.

Failure-name comparison:

- Baseline failures: `/tmp/wave2-final-7c1a85a-failures.txt` (34 nodeids)
- Current failures: `/tmp/wave3-integrated-b11-806a7a3-failures.txt` (34 nodeids)
- New failures: `/tmp/wave3-integrated-b11-806a7a3-new-failures.txt` (0)
- Removed failures: `/tmp/wave3-integrated-b11-806a7a3-removed-failures.txt` (0)

---

## Bug-Reproduction Proofs

| Item | Proof shape |
|---|---|
| **B7** | Tests assert the new stderr ring size and env keys, the drain-before-cancel ordering, the three EOF diagnostic subtypes, and parent-keyed classification compatibility. Reverting the corresponding B7 source changes breaks those assertions. |
| **B8** | Red tests before final source showed retry-exhausted EOF did not raise `CodexAppserverUnstableError`, subclass/discriminator locks were absent, catch boundaries collapsed the typed halt to generic wave failures, and parallel-state halt handling skipped milestone finalization. Final focused and full sweeps passed after R5. |
| **B11** | Red tests before R2 showed startup failure and `CodexDispatchError` escaped the typed preflight path. Red tests before R3 showed legacy fakes failed on the new preflight lifecycle. Final tests cover pass, timeout, initialize error, startup error, dispatch wrapping, provider surfacing, CLI exit 2, and once-per-session caching. |

---

## Harness And Coordination Notes

- Wave 3 preserved independent source branches off `7c1a85a`: `wave-3-b7`, `wave-3-b8`, `wave-3-b11`.
- Each item shipped source and tests together in one atomic branch commit; B8 and B11 corrective rounds were amended/squashed into their item commit before merge.
- Outside-reviewer NOT-FLAGGED was the merge gate for each item. B11 also received a post-rebase integration sanity check for the B8/B11 classifier conflict: `OUTSIDE_REVIEW_B11_INTEGRATION_NOT_FLAGGED`.
- Worktree remains dirty only with unrelated local residue, notably `.claude/settings.local.json` and untracked run artifacts. Wave 3 evidence is scoped to committed source/doc paths.
- No containment fixes, paid smokes, `--no-verify`, master merge, force-push, or broad staging were used.
