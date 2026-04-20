# Proof 02 — `ownership_policy_required=True` Enforces Fail-Loud Mode

Date: 2026-04-20

## Goal

Show that a missing ownership policy becomes a hard failure when `v18.ownership_policy_required=True`.

## Enforcement path

- Error type: `src/agent_team_v15/scaffold_runner.py::OwnershipPolicyMissingError`
- Builder helper: `src/agent_team_v15/scaffold_runner.py::_build_missing_ownership_policy_error(...)`
- Consumer re-raise sites:
  - `ownership_enforcer.py`
  - `wave_executor.py::_maybe_run_spec_reconciliation(...)`
  - `wave_executor.py::_maybe_run_scaffold_verifier(...)`

## Evidence

- Check C fail-loud regression:
  - `tests/test_h1a_ownership_enforcer.py::test_wave_a_missing_contract_raises_when_policy_required`
- Spec reconciler fail-loud regression:
  - `tests/test_h2bc_regressions.py::test_spec_reconciliation_raises_when_policy_required_and_contract_missing`
- Scaffold verifier fail-loud regression:
  - `tests/test_h2bc_regressions.py::test_scaffold_verifier_raises_when_policy_required_and_contract_missing`
- Supplemental targeted rerun after filling the graceful-skip matrix:
  - `pytest tests/test_h2bc_regressions.py tests/test_walker_sweep_complete.py -q`
  - Result: `9 passed in 0.32s`

## Result

When the flag is on, all three ownership-policy consumers raise `OwnershipPolicyMissingError` instead of silently warning and continuing.
