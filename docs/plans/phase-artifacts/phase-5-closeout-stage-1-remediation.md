# Phase 5 closeout-smoke Stage 1 — remediation memo

**Status:** Source / docs / scripts / tests landed. Reviewer round 1 returned four blocking findings; all four are addressed in this revision. **No live smoke launched. Stage 1 remains unclosed until clean 1A + 1B rerun on this same HEAD or a descendant.**

## Reviewer round 1 — closure log

| Blocker | Verdict against evidence | Fix |
|---|---|---|
| #1 — watcher signals positive PID; bypasses launcher trap; existing test only direct-SIGTERMs the launcher | **Confirmed** — `kill -TERM "${AGENT_TEAM_PID}"` (positive) only kills the orchestrator, leaving Codex CLI / docker / npm grandchildren reparented to init | Watcher now sends `kill -TERM "-${AGENT_TEAM_PID}"` (negative = process group). New test `test_watcher_plus_launcher_end_to_end_reaps_child_and_grandchild` spawns watcher + launcher together with a dummy `agent-team-v15` that backgrounds a `sleep 600` grandchild and **no trap**, then asserts both child + grandchild are reaped post-watcher-fire (proves OS-level PG signaling, not in-bash cleanup) |
| #2 — `_finalize_milestone_with_quality_contract` saw outer `audit_report=None`; `audit_findings_path` stayed empty on DEGRADED per-role-fallback routes; reviewer reproduced with a no-spend MEDIUM file | **Confirmed** — the round-1 fix only reassigned `_evaluate_quality_contract`'s local; the resolver's outer `audit_report` parameter stayed None, so its `audit_findings_path` block was skipped (violates §B / §M.M8 evidence requirement for DEGRADED + sidecar) | Lifted the per-role aggregation to the **top of the resolver** (before `_evaluate_quality_contract` is called) — outer `audit_report` becomes the synthesized report; resolver's path block then resolves. When the report carries the synthesized marker (`extras["phase_5_closeout_per_role_fallback"]`), `audit_findings_path` points at the **audit_dir** (where the role files live), not the canonical AUDIT_REPORT.json path (which doesn't exist on disk in this case). New test `test_per_role_fallback_populates_audit_findings_path_via_finalize_resolver` locks the contract |
| #3 — claim that per-role rows are "FAIL-shape only" is false; INFO + missing-verdict rows in the on-disk shape (`audit-interface_findings.json:151` — "Health endpoint contract verified PASS", `fix_action="No action — passing"`) get default-FAIL'd; INFO-only file routes DEGRADED | **Confirmed** — across the 1A run-dir's 6 role files, **all 97 findings omit the verdict field** (verified via `grep -c '"verdict"' audit-*_findings.json`); the 17 INFO rows are explicitly passing-confirmation findings. Pre-fix aggregator treated every row as FAIL | `_aggregate_per_role_findings` now normalizes rows to PASS when verdict is missing AND severity == "INFO" (auditor convention for "verified passing"). Explicit verdict on the row always wins (auditor's intent — including an explicit `"FAIL"` at INFO severity, which still counts). Three new tests lock the matrix: INFO-only → COMPLETE/clean; mixed INFO + MEDIUM → DEGRADED with count == MEDIUM rows only; INFO + explicit `verdict="FAIL"` → still counts |
| #4 — re-prep recipe copies `v18 test runs/taskflow-smoke-test-config.yaml`; that path doesn't exist; the config lives at `v18 test runs/configs/taskflow-smoke-test-config.yaml` | **Confirmed** by `ls "v18 test runs/configs/"` — the canonical config is in the `configs/` subdir | Memo's prep recipe corrected; explicit note appended that the prior path was wrong |

**Test delta from round 1 → round 2:** +6 new tests (4 INFO-normalization + audit_findings_path + watcher PG static + end-to-end watcher+launcher). 421 pass across the targeted Phase 5 sweep (up from 415 in round 1).

## Reviewer round 2 — closure log

| Blocker | Verdict against evidence | Fix |
|---|---|---|
| Round 2 — natural-completion site at `cli.py:6721-6723` (render_quality_summary) and `cli.py:6767-6769` (_phase_4_6_capture_anchor_on_complete) hardcoded `<req_dir>/milestones/<id>/.agent-team/AUDIT_REPORT.json`; resolver-resolved path on STATE.json was ignored. On the per-role fallback route, the file does not exist on disk → console + `_quality.json` sidecar both pointed at a missing file, breaking §M.M2 Rule 2 (sidecar must mirror STATE.json) | **Confirmed** by source inspection at the two cited lines | After ``_finalize_milestone_with_quality_contract`` returns, the natural-completion site now reads ``audit_findings_path`` back from ``_current_state.milestone_progress[milestone.id]`` into a local ``_resolved_audit_findings_path`` variable (cli.py:6669-6675 init + 6709-6725 read-back) and threads that single value into both ``render_quality_summary`` (cli.py:6739) and ``_phase_4_6_capture_anchor_on_complete`` (cli.py:6791) — eliminating the canonical-path literal at both sites. Phase 4.5 reconciliation site (cli.py:5863-5887) was already correct (it reads from `_rec_entry`); only the natural-completion site needed the fix. Two new tests: behavioural ``test_natural_completion_per_role_fallback_quality_sidecar_points_to_audit_dir`` simulates the resolver → capture sequence end-to-end and asserts the sidecar's ``audit_findings_path`` matches the audit_dir (NOT the missing canonical path); static-source ``test_cli_natural_completion_threads_audit_findings_path_from_state_static`` locks the cli.py epilogue against any future regression that re-introduces a hardcoded canonical path between the Quality Summary anchor and the Phase 4.6 capture anchor |

**Test delta from round 2 → round 3:** +2 new tests (behavioural + static). **423 pass** across the targeted Phase 5 sweep (up from 421 in round 2).

**HEAD at remediation start:** `adffc22`
**HEAD at remediation end (working tree, pre-commit):** `adffc22` + uncommitted changes in:

```
M src/agent_team_v15/quality_contract.py
M src/agent_team_v15/wave_executor.py
M tests/test_pipeline_upgrade_phase5_5.py
M tests/test_pipeline_upgrade_phase5_7.py
?? scripts/phase_5_closeout/stage_1_prep.py
?? tests/test_phase_5_closeout_stage_1_prep.py
?? docs/plans/phase-artifacts/phase-5-closeout-stage-1-remediation.md   (this file)
```

`.claude/settings.local.json` was already dirty pre-remediation (unrelated).

**Source-of-truth artifacts driving the remediation:**

* Plan §O.4 + §M.M — `docs/plans/2026-04-28-phase-5-quality-milestone.md`
* Closeout plan — `docs/plans/phase-artifacts/phase-5-closeout-smoke-plan.md`
* Stage 1A findings memo — `docs/plans/phase-artifacts/phase-5-closeout-stage-1-1a-findings.md`
* Stage 1A run-dir (read-only evidence) — `v18 test runs/phase-5-closeout-stage-1-1a-strict-on-smoke-20260430-103941/`

**Methodology:** every memo claim was verified against the actual run-dir artifacts and source modules before any change. The findings memo was treated as untrusted; only claims with on-disk or in-source corroboration drove fixes. TDD throughout — failing tests first, then implementation, then full targeted-suite re-run.

---

## Finding-by-finding closure table

| # | Memo claim | Verdict | Closure |
|---|---|---|---|
| 1 | Operational: `watcher.log` written under run-dir contaminates Wave B scope detector | **CONFIRMED real defect** (operator-supplied harness) | **Fixed** — `scripts/phase_5_closeout/stage_1_prep.py::render_watcher_script` writes to `/tmp/watcher-<run_id>.log` by default; `LOG_DIR` overridable; lint test forbids run-dir patterns |
| 2 | Operational: launcher records `$$` (bash PID) into `AGENT_TEAM_PID.txt` — SIGTERM orphans Python child | **CONFIRMED real defect** | **Fixed** — `render_launcher_script` spawns child via `set -m` + `&`, records `$!` (real child PID), traps `TERM`/`INT`/`HUP`, forwards via `kill -<sig> -<pgid>`, waits, writes `EXIT_CODE.txt`; integration test using a `sleep 60` dummy proves SIGTERM propagates and the child is reaped |
| 3 | Source: orphan-tool hang report payload missing `item_id` / `tool_name` / `cumulative_wedges_so_far` | **PARTIAL real defect** — top-level orphan-tool fields and read-only cumulative counter were genuinely absent | **Fixed** — `_write_hang_report` now surfaces `orphan_tool_id` + `orphan_tool_name` at top-level when `timeout_kind == "orphan-tool"`; the three non-bootstrap call sites in `wave_executor.py` (`_invoke_wave_sdk_with_watchdog`, `_invoke_provider_wave_with_watchdog`, `_invoke_sdk_sub_agent_with_watchdog`) now pass `cumulative_wedges_so_far=_get_cumulative_wedge_count()` (read-only — does NOT invoke the bootstrap-wedge callback, preserving §O.4.10's "Codex paths do not increment counter" contract) |
| 3' | Source: `idle_at` / `agent_phase` / `last_progress_event` empty | **NOT a defect** — these are not contracted fields | **Documented** — `payload.role` covers agent-phase grouping (§O.4.11 contract); `last_sdk_message_type` + `recent_sdk_events[]` cover progress event context; `last_progress_at` already present (memo's `idle_at` was a memo-side alias, not a source contract) |
| 3'' | Source: `stderr_tail == ""` on orphan-tool reports | **NOT a defect** — that is the as-shipped §O.4.7 contract | **Documented** — direct-SDK paths emit `stderr_tail==""` because there is no subprocess stderr to capture (in-process Anthropic SDK over the Python process's own stdin/stdout/stderr); the `stderr_tail` field IS always emitted (default `""`); only team-mode subprocesses populate non-empty values |
| 4 | Source: `_quality.json` reports `audit_status="unknown"` / `unresolved_findings_count=0` despite role files showing 13 CRITICAL + 32 HIGH on disk | **CONFIRMED real defect** | **Fixed** — `_evaluate_quality_contract` now falls back to per-role aggregation when `audit_report is None` AND `cwd + milestone_id` are supplied AND `audit-*_findings.json` files exist on disk. New helper `_aggregate_per_role_findings` synthesizes a minimal `AuditReport` from role files (verdict defaults to `FAIL` per `AuditFinding.from_dict`); contract then routes per §H.3 (CRITICAL/HIGH → FAILED). `_finalize_milestone_with_quality_contract` flows the values into STATE.json so §M.M2 Rule 2 stays consistent on the subsequent `_capture_milestone_anchor_on_complete` write |
| **A1** | O.4.1 `audit_output_guard_decisions.jsonl` not found | **DOCUMENTED non-defect** | The guard's JSONL append at `audit_output_path_guard.py:120-165` fires on PreToolUse hook decisions for write tools. The audit dispatch wedged on tier-2 orphan-tool wedge (M1 22s pending Read/Glob/Agent; M2 45s) before any auditor's Write fired — no decision-log entries to write. Guard is wired correctly (`cli.py:7424` threads `audit_output_root=audit_dir`). Re-run on a clean smoke that completes the audit Write phase will produce the JSONL |
| **A2** | STATE.json `total_cost: 0.0` despite ~$6.96 Codex spend | **NON-DEFECT (operational symptom)** | Per-wave costs accumulate correctly (telemetry: `milestone-1-wave-B.json::sdk_cost_usd: 4.275306`; `milestone-2-wave-B.json::sdk_cost_usd: 2.342951`). `RunState.total_cost` is persisted at the post-orchestration handler. SIGTERM at 11:40:39 killed the bash launcher mid-cycle; Python child orphaned (defect 2 above) and never reached the `total_cost` flush. **Root cause is operational defect 2**, not a source-level cost-tracking bug — closing the launcher fix closes this on the next clean smoke |
| **A3** | M2 `milestone_progress` lacks `audit_status` field | **DOCUMENTED non-defect (truncated mid-update)** | M2 entered Phase 4.5 lift cycle; SIGTERM landed mid-recovery. The Phase 5.3 quality-debt fields write through `_finalize_milestone_with_quality_contract` post-recovery; SIGTERM truncated before that resolver call fired. Expected behaviour for a SIGTERM mid-cycle |
| **A4** | `audit_fix_rounds: 0` for both milestones despite cycle dispatch | **NON-DEFECT (operational symptom)** | The increment fires on `_run_audit_loop` cycle entry (cli.py:9698-9700) with a `save_state` flush. The orphan-tool wedge intercepted the dispatch BEFORE the increment-and-save completed; STATE.json never received the new value. Same root cause as A2 — closes once the launcher is signal-safe and the audit loop runs to completion |
| **A5** | No canonical `AUDIT_REPORT.json`; only per-role `audit-*_findings.json` | **DOCUMENTED non-defect** | Per Plan §O.4.4: `AUDIT_REPORT.json` is the scorer-aggregated artifact written AFTER all auditor roles finish. The orphan-tool wedge interrupted both M1 and M2 before aggregation. Per-role files DID write (proves the auditors fired), aggregation did not. Expected for SIGTERM mid-audit. **The Finding 4 fix surfaces the per-role data through the Quality Contract even when AUDIT_REPORT.json is absent** — see remediation #4 |
| **A6** | Auditor's CRITICAL FINDING-001 cites stale STATE during Phase 4.5 recovery | **DOCUMENTED non-defect** | Auditors snapshot STATE.json at audit dispatch time. Phase 4.5 lift subsequently flipped FAILED → COMPLETE; the auditor's snapshot was correct at read-time but stale at lift-time. By design — the auditor reports point-in-time. **The Finding 4 fix means the post-lift sidecar now reflects post-lift truth: per-role findings populate the sidecar via the resolver, so the operator-visible quality posture matches the actual milestone state** |
| **A7** | Phase 5.9 active split not exercised (M1=8 ACs, passive ≤10) | **DOCUMENTED non-defect (passive-satisfied)** | §O.4.15 acceptance is "every milestone ≤ 10 ACs"; passive satisfaction is acceptable. Active split demonstration (15 → 8/7 redistribution) belongs to the §O.4.16 6-milestone synthetic smoke (Stage 2C). Closeout-evidence guidance updated: see "Closeout-evidence guidance updates" below |
| **A8** | Phase 5.8a `strict_mode` diagnostic not exercised because Wave C never ran | **DOCUMENTED coverage gap** | Phase 4.5 lift short-circuited Wave B → COMPLETE without running Wave C. The `strict_mode` field threading patch on `PHASE_5_8A_DIAGNOSTIC.json` (the entire reason `adffc22` exists) requires Wave C to execute. Closeout-evidence guidance updated: any Stage 1 claim of `adffc22` strict_mode coverage requires evidence that Wave C ran for at least one milestone |

---

## Source / scripts / tests changed

### Source

* `src/agent_team_v15/wave_executor.py`
  * `_write_hang_report` (~line 3936): when `timeout_kind == "orphan-tool"`, surface `orphan_tool_id` + `orphan_tool_name` at the payload top-level from the `WaveWatchdogTimeoutError` exception attributes.
  * `_invoke_wave_sdk_with_watchdog` non-bootstrap branch (~line 4634): pass `cumulative_wedges_so_far=_get_cumulative_wedge_count()` to `_write_hang_report`.
  * `_invoke_provider_wave_with_watchdog` non-bootstrap branch (~line 4805): same.
  * `_invoke_sdk_sub_agent_with_watchdog` non-bootstrap branch (~line 4927): same.
* `src/agent_team_v15/quality_contract.py`
  * New helper `_aggregate_per_role_findings(cwd, milestone_id) -> AuditReport | None` (~line 110): scans `<cwd>/.agent-team/milestones/<id>/.agent-team/audit-*_findings.json`, builds a synthetic `AuditReport` from the per-role rows. Returns `None` when no role files exist (sentinel-skip preserved). **Reviewer #3** — INFO + missing-verdict rows normalize to `verdict="PASS"` (auditor-convention "verified passing"); explicit verdict on the row always wins.
  * `_evaluate_quality_contract` (~line 188): when `audit_report is None` AND `cwd + milestone_id` are supplied, try the per-role fallback before returning the sentinel (direct callers benefit).
  * **Reviewer #2** — `_finalize_milestone_with_quality_contract` (~line 510): same fallback lifted to the top of the resolver so the OUTER `audit_report` becomes the synthesized report and `audit_findings_path` resolves on the DEGRADED/FAILED route.
  * **Reviewer #2** — `_finalize_milestone_with_quality_contract` `audit_findings_path` block (~line 460): when `audit_report.extras["phase_5_closeout_per_role_fallback"]` is set, point at the **audit_dir** (`<cwd>/.agent-team/milestones/<id>/.agent-team/`); else canonical `AUDIT_REPORT.json` path (existing behavior).
* `scripts/phase_5_closeout/stage_1_prep.py`
  * **Reviewer #1** — watcher fires `kill -TERM "-${AGENT_TEAM_PID}"` (negative PID = process group), reaping the orchestrator + every subprocess in the PG together. Pre-fix used positive PID, which left grandchildren orphaned.

### Scripts

* `scripts/phase_5_closeout/stage_1_prep.py` (new)
  * `WATCHER_LOG_DIR_DEFAULT = "/tmp"`
  * `resolve_watcher_milestone_targets(master_plan_path, *, bound_to_first_two_logical_milestones=True)` — split-aware target resolver. `[milestone-1-a, milestone-1-b, milestone-2]` for split shape; `[milestone-1, milestone-2]` for unsplit; `[milestone-1, milestone-2]` fallback for missing/malformed plan.
  * `render_watcher_script(*, run_dir, master_plan_path=None, log_dir="/tmp", poll_seconds=30, target_resolver_python="python3")` — emits a watcher script that logs OUTSIDE the run-dir and resolves milestone targets dynamically per poll iteration.
  * `render_launcher_script(*, run_dir, repo_root, venv_activate, prd_filename="PRD.md", config_filename="config.yaml", depth="exhaustive", milestone_cost_cap_usd=20, cumulative_wedge_cap=10, stage_label="Stage 1", extra_cli_args=None)` — emits a signal-safe launcher (`set -m` job control, child PID recorded, traps for TERM/INT/HUP, PG forward, wait, EXIT_CODE.txt write).

### Tests (TDD-first; all green at HEAD-with-remediation)

* `tests/test_pipeline_upgrade_phase5_7.py` — 7 new tests:
  * `test_orphan_tool_hang_report_surfaces_top_level_orphan_tool_id_and_name`
  * `test_orphan_tool_hang_report_includes_cumulative_wedges_so_far_when_supplied`
  * `test_orphan_tool_hang_report_omits_orphan_fields_for_other_timeout_kinds`
  * `test_invoke_wave_sdk_orphan_path_passes_cumulative_wedges_so_far_static`
  * `test_invoke_provider_wave_orphan_path_passes_cumulative_wedges_so_far_static`
  * `test_invoke_sdk_sub_agent_orphan_path_passes_cumulative_wedges_so_far_static`
  * `test_orphan_tool_hang_report_read_does_not_invoke_bootstrap_callback`
* `tests/test_pipeline_upgrade_phase5_5.py` — 10 new tests:
  * `test_per_role_fallback_routes_critical_findings_to_failed_when_audit_report_absent`
  * `test_per_role_fallback_routes_low_medium_only_to_degraded`
  * `test_per_role_fallback_no_op_when_no_role_files_exist`
  * `test_per_role_fallback_no_op_when_cwd_not_supplied`
  * `test_per_role_fallback_aggregates_findings_across_multiple_role_files`
  * `test_per_role_fallback_treats_info_rows_as_passing` (**reviewer #3**)
  * `test_per_role_fallback_mixed_info_and_medium_filters_info_only` (**reviewer #3**)
  * `test_per_role_fallback_explicit_fail_verdict_on_info_severity_still_counts` (**reviewer #3**)
  * `test_per_role_fallback_populates_audit_findings_path_via_finalize_resolver` (**reviewer #2**)
  * `test_per_role_fallback_populates_quality_sidecar_via_finalize_resolver`
* `tests/test_phase_5_closeout_stage_1_prep.py` (new) — 16 tests:
  * Watcher template log-path discipline + dynamic resolver presence
  * Launcher template PID-recording + trap presence + monitor-mode + extras-threading + no-exec
  * Split-aware target resolver (4 cases)
  * **Integration** — real bash spawn of the rendered launcher with a `sleep 60` dummy `agent-team-v15`; SIGTERM the launcher; verify (a) child PID recorded, (b) child reaped (no orphan), (c) `EXIT_CODE.txt` written with signal-aware non-zero code
  * **Reviewer #1 lint** — `test_watcher_template_signals_child_process_group_not_bare_pid` asserts the rendered watcher kills the negative PID (PG), not the bare positive PID.
  * **Reviewer #1 end-to-end** — `test_watcher_plus_launcher_end_to_end_reaps_child_and_grandchild` spawns watcher + launcher together with a dummy `agent-team-v15` that backgrounds a `sleep 600` grandchild and **no trap** (so the test exercises OS-level PG signaling, not in-bash cleanup); asserts both child + grandchild are reaped post-watcher-fire.

---

## Tests run + results

```
$ uv run pytest \
    tests/test_pipeline_upgrade_phase5_7.py \
    tests/test_codex_orphan_tool_tracking.py \
    tests/test_pipeline_upgrade_phase5_5.py \
    tests/test_state_invariants.py \
    tests/test_phase_5_closeout_harness.py \
    tests/test_pipeline_upgrade_phase5_9.py \
    tests/test_cross_package_contract_diagnostics.py \
    tests/test_phase_5_closeout_stage_1_prep.py \
    tests/test_pipeline_upgrade_phase5_1.py \
    tests/test_pipeline_upgrade_phase5_2.py \
    tests/test_pipeline_upgrade_phase5_3.py \
    tests/test_pipeline_upgrade_phase5_4.py \
    tests/test_pipeline_upgrade_phase5_6.py \
    -p no:cacheprovider

============================= 421 passed in 15.89s =============================
```

(Round 1 baseline was 415; the +6 delta is reviewer-blocker test additions.)

The user-named target sweep (the 7 files in the dispatch prompt) is a strict subset of the 13 files above — every Phase 5 sub-phase test file is included for the regression check. Nothing skipped, no broad/full suite needed.

---

## Closeout-evidence guidance updates (apply to Stage 1 1A + 1B)

These rule out memo-side false positives that would otherwise mark a clean re-run as failing closure.

* **§O.4.7 stderr_tail.** `stderr_tail == ""` on orphan-tool / direct-SDK reports IS the contract. Reviewers must check that `stderr_tail` KEY is present (default empty) and that `len <= 4096`. Non-empty content is only expected on team-mode subprocess wedges (`payload.role == "wave"` AND `timeout_kind in {"orphan-tool", "tool-call-idle", "wave-idle"}`).
* **§O.4.10 cumulative_wedges_so_far on Codex paths.** Now emitted on every non-bootstrap hang report (read-only). Reviewers verify the field is present on Codex/orphan-tool reports AND that `STATE.json::_cumulative_wedge_budget` did NOT increment in lockstep with these wedges (only bootstrap wedges should bump the counter).
* **§O.4.15 active vs passive split.** Stage 1 acceptance is satisfied passively when every milestone has `≤ 10` ACs in MASTER_PLAN.json. Active split demonstration (15 → 8/7 redistribution) is **not required for Stage 1 closure**; it belongs to the Stage 2C §O.4.16 6-milestone synthetic.
* **§O.4.12 / §O.4.13 strict_mode diagnostic.** When Phase 4.5 lift short-circuits the wave sequence at Wave B (lift recovers FAILED → COMPLETE without running Wave C), the per-milestone `PHASE_5_8A_DIAGNOSTIC.json` artifact is **not produced** — the diagnostic only fires inside Wave C. Stage 1 is not blocked on this absence; the strict_mode threading patch (the reason `adffc22` exists) is exercised by any Wave C run, and Stage 2B's §K.2 batch is the canonical strict-mode coverage path. **Operator: do not claim `adffc22` strict_mode coverage from a smoke whose Wave C never executed.**
* **Audit-cycle interruption shape.** When SIGTERM lands mid-audit-cycle (orphan-tool wedge or operator-induced terminate-after-M1+M2 pattern), expect: (a) STATE.json `total_cost` may be 0; (b) `audit_fix_rounds` may be 0; (c) `audit_status` may be absent on the milestone whose audit cycle was interrupted; (d) no canonical `AUDIT_REPORT.json` for that milestone. These are **operational symptoms of the SIGTERM, not source defects**, and they resolve on the next clean smoke that runs to natural completion. The Finding 4 fix means the captured `_quality.json` sidecar nonetheless surfaces the per-role audit findings if any role files were written before the interrupt.

---

## Clean 1A / 1B re-prep instruction (no smokes launched)

**Do NOT launch a smoke from this memo.** What follows is the prep recipe — operator authorises spend separately.

### 1. Prepare a fresh run-dir

```bash
RUN_ID="phase-5-closeout-stage-1-1a-strict-on-smoke-$(date +%Y%m%d-%H%M%S)"
mkdir -p "v18 test runs/${RUN_ID}"
RUN_DIR="$(pwd)/v18 test runs/${RUN_ID}"

# Canonical PRD + config (md5 bd18686839c513f8538b2ad5b0e92cba — same as
# landmark `m1-hardening-smoke-20260428-112339`).
cp v18\ test\ runs/TASKFLOW_MINI_PRD.md "${RUN_DIR}/PRD.md"
cp v18\ test\ runs/configs/taskflow-smoke-test-config.yaml "${RUN_DIR}/config.yaml"
```

(The canonical config lives under `v18 test runs/configs/`. A previous
revision of this memo pointed at the run-dir root path; that path
does not exist and would break the prep recipe if followed.)

### 2. Render the watcher + launcher from the templates

```bash
python3 - <<PY
from pathlib import Path
import os
from scripts.phase_5_closeout.stage_1_prep import (
    render_watcher_script,
    render_launcher_script,
)

run_dir = Path(os.environ["RUN_DIR"])
repo_root = Path("/home/omar/projects/agent-team-v18-codex")
venv_activate = repo_root / ".venv" / "bin" / "activate"

(run_dir / "watcher.sh").write_text(render_watcher_script(
    run_dir=str(run_dir),
), encoding="utf-8")
(run_dir / "watcher.sh").chmod(0o755)

(run_dir / "launcher.sh").write_text(render_launcher_script(
    run_dir=str(run_dir),
    repo_root=str(repo_root),
    venv_activate=str(venv_activate),
    stage_label="Stage 1A strict=ON",
    # 1B variant overrides config.yaml to set tsc_strict_check_enabled=False;
    # for 1A use the production default config (no override).
), encoding="utf-8")
(run_dir / "launcher.sh").chmod(0o755)
PY
```

For **1B**, swap `Stage 1A strict=ON` for `Stage 1B strict=OFF` and copy a `config.yaml` whose `runtime_verification.tsc_strict_check_enabled` is `false`. Otherwise identical inputs to 1A — the §M.M11 calibration delta requires apples-to-apples PRD.

### 3. Pre-flight verification

Before either smoke fires:

* `git rev-parse --short HEAD` matches the dispatch pin (this remediation lands at `adffc22` + the changes in this memo; commit + push to a remediation branch and pin BOTH 1A and 1B to that descendant SHA).
* `git status --short` is clean (or only `.claude/settings.local.json`).
* `uv run pytest tests/test_pipeline_upgrade_phase5_5.py tests/test_pipeline_upgrade_phase5_7.py tests/test_phase_5_closeout_stage_1_prep.py -p no:cacheprovider` is green.
* `python3 -c "from agent_team_v15 import wave_executor, quality_contract, cli; from scripts.phase_5_closeout import stage_1_prep"` imports cleanly.
* Host docker has target ports 5432/5433/3080/4000 free; only the per-watcher-log clean-up: `ls /tmp/watcher-* 2>/dev/null` to see whether a stale watcher log from a previous run exists at the same name (override `log_dir` if it does).
* Stale `.codex` files in repo root: `ls /home/omar/projects/agent-team-v18-codex/.codex 2>&1` — if a stale empty `.codex` exists from a prior run, decide whether it's expected for this smoke before launching (Phase 4.7 §O.4.31 sentinel).

### 4. Launch sequence (operator-only — separate spend authorization)

```bash
cd "${RUN_DIR}"
nohup ./launcher.sh > launcher.out 2> launcher.err &
LAUNCHER_PID=$!
echo "${LAUNCHER_PID}" > LAUNCHER_PID.txt
echo "[harness] launcher.sh PID=${LAUNCHER_PID}; waiting for AGENT_TEAM_PID.txt …"
# Watcher tracks the agent-team-v15 child PID + STATE.json; when M1+M2
# (or split halves of M1 + M2) reach terminal status, watcher SIGTERMs
# the launcher, which forwards to the child PG and writes EXIT_CODE.txt.
nohup ./watcher.sh > watcher.out 2> watcher.err &
WATCHER_PID=$!
echo "${WATCHER_PID}" > WATCHER_PID.txt
echo "[harness] watcher.sh PID=${WATCHER_PID}; logs at /tmp/watcher-${RUN_ID}.log"
```

### 5. Post-run capture (after SIGTERM lands and EXIT_CODE.txt exists)

For each smoke (1A then 1B), preserve at minimum:

* `BUILD_LOG.txt` (whole file)
* `EXIT_CODE.txt` + `AGENT_TEAM_PID.txt` + `LAUNCHER_PID.txt` + `WATCHER_PID.txt`
* `.agent-team/STATE.json` snapshot at SIGTERM time
* `.agent-team/MASTER_PLAN.json`
* `.agent-team/milestones/milestone-{1,2}{-a,-b,}/.agent-team/audit-*_findings.json` (whichever shape the planner emitted)
* `.agent-team/milestones/milestone-{1,2}{-a,-b,}/.agent-team/audit_output_guard_decisions.jsonl` (per §O.4.1)
* `.agent-team/milestones/milestone-{1,2}{-a,-b,}/_anchor/_complete/_quality.json` (per §O.4.3 / §M.M8 — now post-fix populated with real per-role data when AUDIT_REPORT.json absent)
* `.agent-team/hang_reports/*.json`
* `.agent-team/telemetry/milestone-*-wave-*.json`
* `/tmp/watcher-${RUN_ID}.log` (verify it is OUTSIDE the run-dir)

### 6. Compute the §M.M11 calibration delta + §M.M13 spot-check

After both 1A and 1B preserve cleanly:

* §M.M11: compare initial wave-fail rate at `tsc_strict_check_enabled=True` (1A) vs `False` (1B). Now meaningful — no watcher.log contamination.
* §M.M13: sample 5 random findings from 1A's per-role audit files OR `AUDIT_REPORT.json` (when present); manually verify each against actual code. Record precision; threshold is ≥ 0.70 for Stage 2 release.

---

## Residual gaps + open thread for the operator review

* **Phase 4.5 lift × Quality Contract semantic change.** The Finding 4 fix means a Phase 4.5 lift recovery on a milestone with CRITICAL/HIGH per-role findings now routes to FAILED (not COMPLETE). This is the §H.3 Quality Contract's stated behaviour, but it is a **behavioral change** to the Phase 4.5 lift path: pre-fix, lift recovered to COMPLETE/degraded with hidden quality debt; post-fix, lift recovers to FAILED with explicit quality-debt fields. Operators expecting the prior "lift always lands COMPLETE/degraded" semantics must update their dashboards / triage rules. The 1A run-dir's M1 (13 CRITICAL + 32 HIGH per-role) would have landed FAILED under the post-fix contract, not COMPLETE.
* **Anomalies A2 + A4 (`total_cost: 0`, `audit_fix_rounds: 0`)** are tied to the SIGTERM-truncation operational defect; they will be revisited on the first clean 1A re-run. If they recur on a smoke that completed naturally (no operator-induced SIGTERM), that's a new source-level signal worth chasing.
* **§K.2 strict_mode coverage** continues to require Wave C execution. If 1B also short-circuits at Phase 4.5 lift (no Wave C), Stage 1 closes without strict_mode coverage and Stage 2B's §K.2 batch is the only path to that evidence. This is the trade-off captured in §M.M11 / §M.M7.
* **Untouched contracts (verified preserved):** Phase 5.1 score normalization, Phase 5.2 audit paths / output guard, Phase 5.3 quality-debt fields, Phase 5.4 audit-fix rounds + workspace rollback, Phase 5.5 Quality Contract single resolver + `_quality.json` sidecar shape, Phase 5.6 unified strict build gate, Phase 5.7 watchdog 4-tier semantics + cumulative-wedge counter, Phase 5.8a advisory diagnostic schema, Phase 5.9 AC cap + auto-split. 415 tests across these surfaces all green.

---

## Final statement

**No live smoke launched.** **Stage 1 remains unclosed until clean 1A + 1B rerun on this same HEAD or descendant.** Recommended next actions for operator:

1. Review this memo + the diff (5 files modified, 2 created).
2. Commit on a remediation branch.
3. Pin Stage 1A + Stage 1B re-runs to the remediation HEAD.
4. Authorise Stage 1 spend (separate envelope from the plan approval).
5. Re-run 1A + 1B back-to-back with the rendered watcher + launcher.
6. Compute §M.M11 delta + §M.M13 spot-check on the clean evidence.
