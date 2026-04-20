# Proof 03 — `ownership_policy_required=False` Keeps Graceful Skip

Date: 2026-04-20

## Goal

Show that the legacy warn-and-skip behavior is preserved when the policy is missing but fail-loud mode is not enabled.

## Evidence

- Check C graceful skip:
  - `tests/test_h1a_ownership_enforcer.py::test_wave_a_missing_contract_skips_gracefully`
- Spec reconciler graceful skip:
  - `tests/test_h2bc_regressions.py::test_spec_reconciliation_skips_when_policy_missing_and_not_required`
- Scaffold verifier graceful skip:
  - `tests/test_h2bc_regressions.py::test_scaffold_verifier_skips_when_policy_missing_and_not_required`
- Post-fix targeted rerun:
  - `pytest tests/test_h2bc_regressions.py tests/test_walker_sweep_complete.py -q`
  - Result: `9 passed in 0.32s`

## Observed behavior

- No exception is raised.
- The consumer returns `None` / empty findings.
- A warning is emitted that the ownership contract could not be loaded.

## Result

H2bc adds fail-loud mode without regressing the existing graceful behavior when the new flag stays at its default `False`.
