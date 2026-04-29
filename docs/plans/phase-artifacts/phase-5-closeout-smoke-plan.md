# Phase 5 closeout-smoke plan (operator-authorised execution)

**Plan status:** APPROVED 2026-04-29 by approver, Option B with staging. Plan approval ≠ spend authorization. Each stage release requires EXPLICIT separate operator authorization for the smokes' API spend; no smoke fires without that release.
**Source HEAD plan was approved against:** `34bab7a` (final Phase 5.9 source). Smokes pin to this SHA or a descendant; document any drift.
**Plan reference:** `docs/plans/2026-04-28-phase-5-quality-milestone.md` §L + §O.4 (rows O.4.5-O.4.16 are the row-level acceptance contracts).
**Hard rule:** capstone (Smoke 3) only fires AFTER every Stage 2 row is reviewed + approved. The capstone is stability proof, NOT a substitute for any deferred decision smoke.

## Required evidence labels per smoke (mandatory)

Every smoke landing memo MUST record:

* `head` — exact commit SHA the smoke ran against (must be `34bab7a` or a descendant; document any drift + diff range).
* `strict_mode` — `ON` or `OFF` for `tsc_strict_check_enabled`. Mandatory because §M.M11 calibration depends on the delta and §K.2 evaluator must not conflate.
* `prd_input_name` — file path / canonical name of the PRD used.
* `run_dir` — `v18 test runs/<run-id>/` absolute path.
* `state_terminal_status_per_milestone` — STATE.json `milestone_progress[<id>].status` for every milestone (including post-split halves).
* `master_plan_json` — verbatim post-run shape (snapshot the file).
* `audit_quality_artifacts` — `AUDIT_REPORT.json` per milestone + `_anchor/_complete/_quality.json` per COMPLETE/DEGRADED milestone.
* `phase_5_8a_diagnostics` — `PHASE_5_8A_DIAGNOSTIC.json` per milestone (where applicable; record with `strict_mode` field).
* `cost_budget_outcome` — total $ spent, any `cost_cap_reached` events, `_cumulative_wedge_budget` final value.

Smokes that fail to record the labels are NOT acceptable evidence; re-run required.

---

## Stage 1 — natural pair + auditor spot-check ($60-120)

Plan-approved. Stage 1 release REQUIRES explicit operator spend authorization before any smoke fires. Once released and complete, Stage 2 remains BLOCKED until Stage 1 review approves the row-level evidence.

### Smoke 1A — M1+M2 production-default (`strict=ON`)
* **PRD:** the canonical M1+M2 PRD used through Phase 5 development.
* **Config:** `tsc_strict_check_enabled=True` (production default); no fault injection; no special CLI overrides.
* **Cost:** $30-60.
* **Closure rows folded:** 5.2 AC5 (canonical AUDIT_REPORT.json path); 5.3 implicit (quality-debt fields populate); 5.4 AC6 (`audit_fix_rounds > 0` observation); 5.5 AC7 (`_anchor/_complete/_quality.json` shape); 5.6 AC5/AC5a/AC8 (strict-tsc gate runs); 5.9 AC3 (M1's 15 ACs → `milestone-1-a` (8) + `milestone-1-b` (7)) + §O.4.15.
* **Acceptance:** all milestones reach COMPLETE or DEGRADED (with documented reason); split-shape on disk matches Phase 5.9 expected; quality sidecar present on every captured anchor.

### Smoke 1B — M1+M2 calibration companion (`strict=OFF`)
* **PRD:** EXACTLY THE SAME PRD as 1A (delta must be apples-to-apples).
* **Config:** `tsc_strict_check_enabled=False` (the §M.M11 calibration companion).
* **Cost:** $30-60.
* **Closure rows folded:** §M.M11 calibration delta vs 1A only.
* **DO NOT count toward §K.2.** The strict=OFF run produces diagnostics, but the §K.2 evaluator must not aggregate it with strict=ON evidence as identical (per approver constraint).
* **Acceptance:** delta computation against 1A:
  * <10% additional wave-fails → strict-default-on is safe (current behaviour holds).
  * 10-25% → surface to user; user decides default policy.
  * >25% → ship strict-default-OFF with 2-week opt-in period (Phase 5.6 §M.M11 plan-of-record).

### §M.M13 auditor-precision spot-check (Stage 1 gating)
* Pick 5 random findings from 1A's `AUDIT_REPORT.json`.
* Manually verify each against actual code (true positive vs false positive).
* Record precision in the smoke landing memo (`stage1_precision: <pct>`).
* **Stage 2 GATE:** median precision must be ≥70% across the spot-check. Below that, Stage 2 is BLOCKED pending auditor-prompt improvements.

### Stage 1 review (operator) before Stage 2 release
1. Smokes 1A + 1B both produced complete evidence labels.
2. Phase 5.9 split shape verified on disk.
3. §M.M11 delta computed + categorised.
4. §M.M13 spot-check ≥70%.
5. No regression vs §0.6 wide-net baseline (4 pre-existing failures only).

---

## Stage 2 — fault-injection + K.2 batch + synthetic ($150-825)

Released only after Stage 1 review. Three parallel tracks; can run concurrently if harness supports concurrent run-dirs.

### Smoke 2A — Phase 5.7 fault-injection bundle ($30-105)

Combine O.4.5-O.4.11 into the fewest well-designed injections. Closure-blocking per approver.

#### 2A.i — Bootstrap-wedge respawn injection (M1 only, $15-35)
* **Injection:** monkeypatch Claude SDK callback to stall >60s on first call for ONE Wave dispatch (Wave A is simplest; could also target audit-dispatch sub-agent for sub-agent eligibility coverage).
* **Closure rows:** O.4.5 (bootstrap-wedge respawn observed), O.4.7 (`stderr_tail` field present), O.4.9 (no retry-budget increment), O.4.11 (sub-agent eligibility — if injected on a sub-agent dispatch class).
* **Acceptance:** `hang_reports/wave-<X>-<ts>.json` has `timeout_kind=="bootstrap"`; BUILD_LOG carries the `bootstrap-wedge respawn N/3` log line; outer wave-retry counter unchanged across the respawn event.

#### 2A.ii — Cumulative-cap halt (M1 only, $15-35)
* **Injection:** `--cumulative-wedge-cap 2` + injected pipe-pauses on every dispatch.
* **Closure rows:** O.4.8 (cap halt with `failure_reason=sdk_pipe_environment_unstable` + `EXIT_CODE=2`).
* **Acceptance:** STATE.json shows `status=FAILED`, `failure_reason=sdk_pipe_environment_unstable`, `_cumulative_wedge_budget=2`; `EXIT_CODE.txt` = `2`; BUILD_LOG carries `Cumulative wedge cap (2) reached`.

#### 2A.iii — Productive-tool-idle replay (fixture or live M3, $0-35)
* **Option A (fixture, $0):** Replay BUILD_LOG `2088-2148` shape from `m1-hardening-smoke-20260428-112339`; assert hang report `tool_call_idle_timeout_seconds==1200`.
* **Option B (live M3, $15-35):** run M3 with stalled commandExecution; observe productive-tool-idle fires at 1200s before `codex_timeout_seconds=5400`.
* **Closure rows:** O.4.6.

#### 2A.iv — Provider-routed Codex no-counter (incidental in 2A.i or 2A.ii)
* No separate run. Verify `_cumulative_wedge_budget` does NOT increment for Codex Wave B/D paths in 2A.i/2A.ii's STATE.json.
* **Closure rows:** O.4.10.

### Smoke 2B — Phase 5.8a §K.2 sequential batch ($90-600)

* **PRD:** canonical M1+M2.
* **Strict mode:** ON (production default; runs count toward §K.2 decision).
* **Sequence:** up to 10 sequential M1+M2 smokes. Stop-early predicate: 3 distinct DTOs sharing same `divergence_class` across the batch → stop, ship Phase 5.8b path; else continue to 10-cap → close R-#42 via Wave A spec-quality investment.
* **Closure rows per smoke:** O.4.12 (per-milestone `PHASE_5_8A_DIAGNOSTIC.json`), O.4.13 (`[CROSS-PACKAGE-DIAG]` log line per Wave C run).
* **Closure row at batch level:** O.4.14 (§K.2 decision evidence).
* **Cost ranges:** stop at smoke #3 → $90; stop at smoke #5 → $150-300; full 10-cap → $300-600.

### §K.2 evaluator session (after 2B batch completes, $0-15)
* Read every smoke's per-milestone `PHASE_5_8A_DIAGNOSTIC.json`.
* Apply `cross_package_diagnostic.k2_decision_gate_satisfied(per_milestone_diagnostics, correlated_threshold=3)`.
* Filter: count strict=ON runs only (default policy per approver constraint #1).
* Write `PHASE_5_8A_DIAGNOSTIC_SUMMARY.md` with the outcome:
  * **Outcome A** (3+ correlated divergences before/at 10-cap): Phase 5.8b ships full `cross_package_contract.py`. Triggers ~$60-120 implementer + 1 smoke ($30-60); MUST land BEFORE capstone.
  * **Outcome B** (<3 after 10): close R-#42 via Wave A spec-quality investment. That's a Phase 6+ scope decision, NOT blocking capstone.

### Smoke 2C — Phase 5.9 6-milestone synthetic ($30-60)
* **PRD:** synthetic 30-AC PRD distributed across 6 milestones (5 ACs each).
* **Closure rows:** §O.4.16 (no auto-split; backward-compat AC4).
* **Acceptance:** `MASTER_PLAN.json` shows 6 milestones each ≤10 ACs; no `_phase_5_9_split_source/` subdir anywhere; BUILD_LOG does NOT contain `Phase 5.9 §L: auto-split applied` line.

### Stage 2 review (operator) before capstone release
1. All O.4.5-O.4.11 rows checked from 2A.
2. O.4.12, O.4.13 checked per 2B smoke; O.4.14 §K.2 decision recorded.
3. O.4.16 checked from 2C.
4. If §K.2 Outcome A: Phase 5.8b shipped + smoked clean before capstone.
5. No regression in any prior phase's evidence rows (cross-check Stage 1 evidence didn't drift).

---

## Capstone — v5 end-to-end stability proof ($30-60)

Released only after Stage 2 review.

### Smoke 3 — final M1+M2 production-default
* **PRD:** canonical M1+M2.
* **Config:** production defaults (`strict=ON`); no fault injection; no special CLI overrides.
* **Purpose:** prove the integrated v5 stack runs clean end-to-end; no regressions from prior smokes' state mutations or any 5.8b landing.
* **Acceptance:**
  * Every milestone reaches COMPLETE or DEGRADED (no FAILED).
  * Auditor precision spot-check ≥70% (matches Stage 1 baseline).
  * `cost_outcome` within budget (no `cost_cap_reached`).
  * No new findings vs Stage 1 1A (or, if new, all justified by intervening 5.8b shipment).

---

## Cost summary

| Stage | Floor | Ceiling |
|---|---|---|
| Stage 1 (1A + 1B + spot-check) | $60 | $120 |
| Stage 2A (fault-injection bundle) | $30 | $105 |
| Stage 2B (§K.2 batch) | $90 | $600 |
| §K.2 evaluator session | $0 | $15 |
| Stage 2C (6-milestone synthetic) | $30 | $60 |
| 5.8b implementer + smoke (if Outcome A) | $0 | $180 |
| Capstone | $30 | $60 |
| **Total** | **$240** | **$1140** |

---

## What Claude can do (free, before/between operator-authorised smokes)

* Author scripts for Stage 2A fault injection (monkeypatching helpers, pipe-pause injection).
* Author the §K.2 evaluator session script + `PHASE_5_8A_DIAGNOSTIC_SUMMARY.md` template.
* Run fixture-replay variants of any smoke that has fixture coverage (e.g., 2A.iii Option A).
* Re-run unit fixtures against new HEAD if drift is suspected.
* Author the 5.8b implementation if §K.2 Outcome A triggers (separate session per existing Phase 5.8 brief).

## What Claude cannot do

* Trigger any live smoke — operator-authorised, billed against operator's account.
* Approve Stage 1 → Stage 2 transition or Stage 2 → Capstone transition. Operator review gates each transition.
* Bypass the evidence label discipline. If a smoke landing memo is missing required labels, the smoke does not count toward closure.

---

## Pointers

* **Plan §L + §O.4 row contracts:** `docs/plans/2026-04-28-phase-5-quality-milestone.md`
* **Phase 5.9 source:** `src/agent_team_v15/milestone_manager.py:651-1006` (split helpers)
* **Phase 5.8a diagnostic source:** `src/agent_team_v15/cross_package_diagnostic.py`
* **Phase 5.7 watchdog source:** `src/agent_team_v15/wave_executor.py` (bootstrap-wedge plumbing)
* **Phase 5.6 unified gate:** `src/agent_team_v15/unified_build_gate.py`
* **Phase 5.5 Quality Contract:** `src/agent_team_v15/quality_contract.py`
* **Phase 5.5 state-invariants:** `src/agent_team_v15/state_invariants.py`
* **Per-phase landing memos:** `docs/plans/phase-artifacts/phase-5-{1..9}-landing.md`

Final v5 closeout is claimable when Stage 1 + Stage 2 + Capstone are all reviewed + approved against the row-level evidence contracts above.
