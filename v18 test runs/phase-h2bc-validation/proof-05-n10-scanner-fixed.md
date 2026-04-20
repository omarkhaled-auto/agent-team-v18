# Proof 05 — N-10 Forbidden-Content Scanner Fixed

Date: 2026-04-20

## Goal

Show that the smoke #12 `int.append` crash is removed and the report merge path handles scorer-shaped count maps safely.

## Root cause

The scanner merge path assumed `report.by_severity`, `by_file`, and `by_requirement` already contained index lists. In scorer-shaped reports, those maps can contain integer counts instead, which made `.append(...)` invalid.

## Fix

`src/agent_team_v15/forbidden_content_scanner.py::merge_findings_into_report(...)`
now rebuilds index maps from `report.findings` instead of mutating possibly integer-valued buckets.

## Evidence

- `tests/test_n10_content_auditor.py::TestMergeFindingsIntoReport::test_rebuilds_indices_when_report_uses_scorer_count_maps`
- Included in the targeted regression ring:
  - `pytest tests/test_n10_content_auditor.py tests/test_prd_mode_convergence.py tests/test_config_v18_loader_gaps.py tests/test_ownership_contract.py tests/test_h1a_ownership_enforcer.py tests/test_h1a_scaffold_verifier.py tests/test_n17_mcp_prefetch.py tests/test_h2bc_regressions.py -q`
  - Result: `146 passed in 1.07s`

## Result

The N-10 merge path no longer crashes on scorer-shaped reports and returns rebuilt list-based indices plus stable `fix_candidates`.
