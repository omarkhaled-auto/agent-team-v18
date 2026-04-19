# D-04 — Review fleet was never deployed during orchestration

**Tracker ID:** D-04
**Source:** B-004 ("GATE VIOLATION: Review fleet was never deployed (8 requirements, 0 review cycles)")
**Session:** 4
**Size:** M (~80 LOC)
**Risk:** MEDIUM (touches orchestration phase logic)
**Status:** plan

---

## 1. Problem statement

Build-j's orchestration phase completed, but the review-fleet deployment step was skipped entirely. Gate check flagged:
- `GATE VIOLATION: Review fleet was never deployed (8 requirements, 0 review cycles)`
- `RECOVERY PASS: 0/8 requirements checked (0 review cycles)`

Even the recovery pass couldn't execute review cycles — suggesting the review-fleet entry point is broken, not just the orchestration-time trigger.

## 2. Investigation targets

1. `cli.py` orchestration phase — find the review-fleet deploy call. Check the guard condition that precedes it.
2. `coordinated_builder.py` — may own the review loop; check if it has a silent early-exit when `requirements_total > 0` but `convergence_cycles == 1`.
3. `audit_team.py` / `audit_agent.py` — see if review fleet is a separate concept or a mode of audit.
4. `BUILD_LOG.txt` — search for "review" / "review fleet" / "review cycle" log markers to see if any step even attempted the deploy.

## 3. Root cause hypothesis

Most likely: a guard condition like `if state.convergence_cycles > 0 and state.requirements_checked == 0: skip` intended to avoid redundant work when the pipeline has already converged, but firing incorrectly when orchestration is the FIRST pass (convergence_cycles=1, requirements_checked=0 — both conditions true).

## 4. Proposed fix shape

- Trace the exact guard and fix the condition. Most likely: change to `if state.convergence_cycles > 0 and state.requirements_checked >= state.requirements_total: skip`.
- Add a defensive `assert state.requirements_total > 0 → review_cycles > 0` invariant check at end of orchestration, so the gate violation becomes a fail-fast instead of a silent skip.
- Ensure the recovery pass can actually deploy review fleet when it catches the gate violation (the recovery path also showed 0/8 — means recovery couldn't invoke it either).

## 5. Test plan

File: `tests/test_review_fleet_orchestration.py`

1. **Fresh orchestration deploys review fleet.** Mock a state with `requirements_total=8, convergence_cycles=0`; run orchestration; assert review-fleet deploy was called.
2. **Post-convergence orchestration skips redundant review.** Mock state with `requirements_total=8, requirements_checked=8`; assert review deploy is skipped.
3. **Gate check enforces invariant.** Mock a state where orchestration completed with `requirements_total>0 but requirements_checked=0`; assert the gate fails loudly.
4. **Recovery pass can re-invoke review fleet.** Mock a gate violation; trigger recovery; assert review-fleet deploy fires.

Target: 4 tests.

## 6. Rollback plan

Feature flag `config.v18.review_fleet_enforcement: bool = True`. Flip off to restore pre-fix behavior if it's too aggressive.

## 7. Success criteria

- Unit tests pass.
- Gate A smoke (Session 6) shows `review_cycles > 0` in `GATE_FINDINGS.json` for M1.
- No "Review fleet was never deployed" gate violation in build-j's successor runs.

## 8. Sequencing notes

- Land in Session 4 (orchestration cluster) alongside D-05, D-06, D-08, D-11.
- Does not depend on A-09 or C-01 — review fleet runs regardless of milestone scoping.
