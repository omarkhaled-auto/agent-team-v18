# Codex-High Milestone Budget Tuning

**Status:** in-progress (Phase 3b of V18 closeout)
**Date:** 2026-04-15
**Reference runs:** `v18 test runs/build-e-bug12-20260414/`, `v18 test runs/build-g-pr2-phaseB-20260414/`

## 1. The condition

At `depth=exhaustive`, `config.py:1136` sets `milestone.milestone_timeout_seconds = 2700`. The
runtime cancellation envelope at `cli.py:3889` is `wave_execution_timeout_s = _ms_timeout_s * 1.5`,
so M1 has 4050s wall-clock total before the milestone-level `asyncio.wait_for` cancels it
(`cli.py:3963–3981`).

With Wave A (~150s) + Wave B (~2000s under codex-high) + Wave C (~6s) ≈ 2156s consumed before
Wave D starts, Wave D has ~1894s wall-clock to finish. Build-e and build-g both showed Wave D
starting strong but being cut at the milestone-level `wait_for` before D5/T/E could even queue.
Wave D under `codex_reasoning_effort: "high"` regularly takes 25–35 minutes because each codex
SDK turn does 5–15 min of reasoning before tool-use (postmortem §4d).

Net: **the 2700s exhaustive budget was set when claude was the default for all waves; the
provider-routing default of `codex` for Waves B+D moved Wave B alone past the 1350s mark, leaving
no room.**

## 2. Why I considered three options and chose option (a)

### Option (a) — raise `milestone.milestone_timeout_seconds` at exhaustive depth from 2700 → 3600

Effective envelope: 5400s (90 min). Matches the existing enterprise-depth value at
`config.py:1177`. Operationally: M1 now has 90 min total; with the same A+B+C
consumption, Wave D gets ~3244s (~54 min), comfortably above the observed 25–35 min needs.

- Pros: minimal change (one constant), parameterizable test, matches enterprise envelope, no
  cross-cutting risk.
- Cons: containment, not cure. Failures elsewhere now waste up to 5400s instead of 4050s before
  surfacing. Also penalizes `claude`-only exhaustive runs (which don't need the bigger envelope)
  by giving them a longer slow-fail window.
- Mitigation for the cons: per the Section 9 postmortem, the watchdog at sub-agent + wave layer
  fires on idle, not wall-clock — so a *truly stuck* wave still gets caught at the existing
  600s/1800s idle bounds. The wall-clock envelope is the last-resort, not the first.

### Option (b) — split Wave D into D1 (auth/layout/shell) + D2 (feature pages)

The structurally correct fix. Wave D's brief is broad and codex's reasoning cost is roughly
linear in scope. Two smaller briefs each fit inside the current 4050s envelope.

- Cost: substantial. Touches the wave DAG (`wave_executor.py` ordering), prompt builders in
  `agents.py` (D becomes two distinct prompts with overlapping but partitioned scope), audit
  expectations, scaffold expectations, fixture data in tests, telemetry shape, and the
  `_diff_checkpoints` boundaries. Not a one-PR change.
- File this as a follow-up: **Bug #18 — split Wave D scope to D1/D2**.

### Option (c) — adaptive: raise the budget only when codex_reasoning_effort=high

Conditional version of (a). Surfaces the codex-cost dependency in the config layer.

- Cost: small but introduces conditional default logic that's awkward in `_apply_depth_overrides`
  (the helper currently just gates fixed values). Also conflates two settings — codex routing
  *and* reasoning effort — to compute the budget.
- Verdict: marginal benefit over (a) given current configs ship `provider_map_b/d=codex` and
  `codex_reasoning_effort=high` together as the standard exhaustive shape (see
  `v18 test runs/configs/taskflow-smoke-test-config.yaml:29-34`). The conditional buys nothing in
  practice.

## 3. Decision

**Implement option (a):** raise the exhaustive default at `config.py:1136` from 2700 to 3600.

Justification per the user's directive ("if you raise it, the plan file must justify why instead
of fixing scope"):

- Wave D's slowness with codex-high is *legitimate computation*, not pathological behavior. The
  postmortem §4d already established this — codex-high single SDK turns taking 5–15 min of
  reasoning is the documented intended trade-off for higher output quality.
- The existing watchdogs (sub-agent 600s idle, wave 1800s idle, codex transport teardown) all
  cover the *truly stuck* failure modes. The wall-clock envelope is the last resort.
- The structural fix (option b — split scope) is the correct long-term answer but is
  cross-cutting and high-risk for this closeout PR. Filed as Bug #18.
- Containment is acceptable here because the structural cause (codex-high reasoning cost) is
  *intentional* — it's a config the user is paying for. Containment is wrong when it hides a
  bug; it is right when it sizes an envelope to match an intentional cost.

## 4. Implementation

- `src/agent_team_v15/config.py:1136`: change `2700` → `3600`.
- `tests/test_milestone_manager.py` (or wherever the depth-preset test lives): parameterize the
  exhaustive case to expect 3600s.
- Add a regression test that the timeout warning message at `cli.py:4000` prints
  `wave_execution_timeout_s` (1.5× multiplier already applied), not the raw value, so we don't
  re-introduce Bug #15.

## 5. Bug #18 — follow-up

File a separate plan to split Wave D into D1 (auth + layout + shell) and D2 (feature pages).
Acceptance criteria for that work: each sub-wave fits inside 4050s under codex-high; total D1+D2
output matches the current Wave D output; audit findings remain stable; existing wave-D tests
either parameterize for the split or get split too.
