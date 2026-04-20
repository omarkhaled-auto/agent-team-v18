# Proof 06 — Convergence Aggregation Reads Audit Review Logs

Date: 2026-04-20

## Goal

Show that convergence no longer collapses to `0/0` when `REQUIREMENTS.md` uses the audit review log table format instead of checkbox items.

## Fix

`src/agent_team_v15/milestone_manager.py::MilestoneManager._parse_requirements_counts(...)`
now:

- keeps the legacy checkbox parser
- falls back to parsing the audit review log markdown table
- tracks the latest cycle per requirement
- ignores the `GENERAL` row
- counts `PASS` rows as checked

## Evidence

- `tests/test_prd_mode_convergence.py::TestConvergenceHealthPRDMode::test_audit_review_log_table_counts_latest_verdicts`
- Included in the targeted regression ring:
  - `pytest tests/test_n10_content_auditor.py tests/test_prd_mode_convergence.py tests/test_config_v18_loader_gaps.py tests/test_ownership_contract.py tests/test_h1a_ownership_enforcer.py tests/test_h1a_scaffold_verifier.py tests/test_n17_mcp_prefetch.py tests/test_h2bc_regressions.py -q`
  - Result: `146 passed in 1.07s`

## Result

Fixture convergence now reports non-zero requirement counts from the actual planner/audit-review-log format instead of reading every milestone as `0/0 unknown`.
