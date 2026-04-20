# Proof 07 — `AUDIT_REPORT.json` Persists `scope`

Date: 2026-04-20

## Goal

Show that the audit report keeps milestone scoping data and does not drop `acceptance_tests` during the rebuild path.

## Fix

`src/agent_team_v15/cli.py::_apply_evidence_gating_to_audit_report(...)`
now performs an explicit post-partition rebuild with:

- persisted `scope`
- preserved `extras`
- preserved `acceptance_tests`

This runs even when no evidence downgrade occurs.

## Evidence

- `tests/test_h2bc_regressions.py::test_evidence_gating_persists_scope_without_verdict_downgrade`
  proves:
  - `scope["milestone_id"] == "milestone-orders"`
  - `scope["allowed_file_globs"] == ["src/orders.ts"]`
  - `acceptance_tests` survives the rebuild
- Post-fix targeted rerun:
  - `pytest tests/test_h2bc_regressions.py tests/test_walker_sweep_complete.py -q`
  - Result: `9 passed in 0.32s`

## Result

The scope payload now survives the production report rebuild path and is persisted instead of being dropped on the no-downgrade branch.
