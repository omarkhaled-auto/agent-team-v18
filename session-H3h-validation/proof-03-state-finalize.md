# Proof 03: STATE-FINALIZE-INVARIANT-001 / -002

## Original Smoke Failure

Combined-smoke evidence:

- `STATE-final.json`
  - `failed_wave = B`
  - `completed_waves = "A"`
  - `summary.success = False`
  - `error_context = STATE.json invariant violation: summary.success=True but interrupted=False, failed_milestones=['milestone-1'] (expected success=False). Likely cause: finalize() was not called or threw silently. See cli.py:13491-13498.`
- `launch.log:623-624`
  - the orchestration log also surfaced the same invariant failure during closeout

## Source Change

Primary source updates:

- `src/agent_team_v15/cli.py:1785-1792`
  - `_save_wave_state()` now finalizes before write when the flag is on
- `src/agent_team_v15/cli.py:1831-1837`
  - `_save_isolated_wave_state()` now finalizes before write when the flag is on
- `src/agent_team_v15/cli.py:1840-1863`
  - new helpers `_state_finalize_invariant_enabled(...)` and `_finalize_state_before_save(...)`
- `src/agent_team_v15/cli.py:5155-5164`
  - timeout path finalizes before save
- `src/agent_team_v15/cli.py:5180-5188`
  - keyboard interrupt path finalizes before save
- `src/agent_team_v15/cli.py:5206-5215`
  - exception path finalizes before save
- `src/agent_team_v15/cli.py:12442-12450`
  - post-orchestration save finalizes before save
- `src/agent_team_v15/state.py:543-551`
  - `save_state()` adds a second flag-gated finalize safety net
- `src/agent_team_v15/state.py:609-621`
  - invariant raise is preserved
- `src/agent_team_v15/config.py:987-991, 2899-2905`
  - new flag: `state_finalize_invariant_enforcement_enabled`

Diff excerpt:

```diff
+ if _state_finalize_invariant_enabled(_current_state):
+     _finalize_state_before_save(
+         _current_state,
+         agent_team_dir=req_dir.parent / ".agent-team",
+         context="milestone exception STATE.json write",
+     )
+ save_state(_current_state, directory=str(req_dir.parent / ".agent-team"))
```

## Production-Caller Proof

Invocation:

```text
pytest tests/test_h3h_state_finalize.py::test_save_wave_state_replays_wave_a_success_then_wave_b_failure_without_invariant tests/test_h3h_state_finalize.py::test_save_state_preserves_legacy_invariant_raise_when_flag_off -v --tb=short
```

Output:

```text
tests/test_h3h_state_finalize.py::test_save_wave_state_replays_wave_a_success_then_wave_b_failure_without_invariant PASSED
tests/test_h3h_state_finalize.py::test_save_state_preserves_legacy_invariant_raise_when_flag_off PASSED
============================== 2 passed in 0.76s ==============================
```

What this proves:

- the Wave A complete -> Wave B failed write sequence now persists a clean `summary.success=False` state when the flag is on
- the legacy invariant raise is still reachable when the flag is off

## Flag-Off Verification

`test_save_state_preserves_legacy_invariant_raise_when_flag_off` keeps the old failure mode reachable by asserting `StateInvariantError` is still raised when a poisoned summary is written without the H3h flag.
