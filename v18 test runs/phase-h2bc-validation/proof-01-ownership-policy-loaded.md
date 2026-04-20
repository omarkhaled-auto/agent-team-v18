# Proof 01 — Ownership Policy Loaded

Date: 2026-04-20

## Goal

Show that the canonical ownership policy is present and that the three H2bc consumers load it through the shared workspace-aware loader.

## Canonical source

- `docs/SCAFFOLD_OWNERSHIP.md`
- Shared loader: `src/agent_team_v15/scaffold_runner.py`
  - `resolve_ownership_contract_path(...)`
  - `load_ownership_contract_from_workspace(...)`
  - `load_ownership_contract(...)`

## Production call chain

- Check C: `src/agent_team_v15/ownership_enforcer.py::_load_scaffold_owned_paths(...)`
- Spec reconciler: `src/agent_team_v15/wave_executor.py::_maybe_run_spec_reconciliation(...)`
- Scaffold verifier: `src/agent_team_v15/wave_executor.py::_maybe_run_scaffold_verifier(...)`

All three paths import and call `load_ownership_contract_from_workspace(...)`.

## Evidence

- The policy file exists and now carries H2bc metadata for REQUIREMENTS-declared deliverables:
  - `docker-compose.yml`
  - `.env.example`
  - `apps/api/.env.example`
  - `apps/api/Dockerfile`
  - `apps/web/.env.example`
  - `apps/web/Dockerfile`
- `tests/test_ownership_contract.py::test_workspace_loader_falls_back_to_repo_contract`
  proves a generated workspace without its own `docs/` still resolves the canonical repo contract.
- `tests/test_ownership_contract.py::test_requirements_deliverables_filter_by_stage`
  proves the parsed contract exposes staged deliverables from the same parser.
- Targeted regression ring passed:
  - `pytest tests/test_n10_content_auditor.py tests/test_prd_mode_convergence.py tests/test_config_v18_loader_gaps.py tests/test_ownership_contract.py tests/test_h1a_ownership_enforcer.py tests/test_h1a_scaffold_verifier.py tests/test_n17_mcp_prefetch.py tests/test_h2bc_regressions.py -q`
  - Result: `146 passed in 1.07s`

## Result

H2bc now resolves ownership policy reads through one shared loader instead of per-consumer ad hoc path handling, and the real policy document is present at the canonical path.
