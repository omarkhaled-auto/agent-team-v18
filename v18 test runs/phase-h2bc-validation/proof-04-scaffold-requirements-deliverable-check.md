# Proof 04 — REQUIREMENTS-Declared Deliverable Check Fires

Date: 2026-04-20

## Goal

Show that H2bc detects missing policy-declared deliverables before live probing and emits the structured H2bc finding code.

## New finding

- `SCAFFOLD-REQUIREMENTS-MISSING-001`

## Production path

- Deliverable discovery:
  - `src/agent_team_v15/scaffold_verifier.py::find_missing_requirements_declared_deliverables(...)`
- Verifier summary emission:
  - `src/agent_team_v15/scaffold_verifier.py::run_scaffold_verifier(...)`
- Structured `WaveFinding` bridge:
  - `src/agent_team_v15/wave_executor.py::_scaffold_summary_to_findings(...)`
  - `src/agent_team_v15/wave_executor.py::_requirements_declared_deliverable_findings(...)`
- Post-Wave-B gate:
  - `src/agent_team_v15/wave_executor.py::execute_milestone_waves(...)`

## Evidence

- `tests/test_h1a_scaffold_verifier.py::test_scaffold_verifier_emits_requirements_deliverable_code`
  proves verifier summary emission for a missing `docker-compose.yml`.
- `tests/test_h2bc_regressions.py::test_wave_b_requirements_declared_deliverable_findings_use_contract`
  proves the structured wave-level finding uses `SCAFFOLD-REQUIREMENTS-MISSING-001`
  and resolves `apps/api/Dockerfile` from the ownership contract.
- `tests/test_n17_mcp_prefetch.py::test_wave_b_prompt_includes_scaffold_deliverables_block`
  proves Wave B now gets an explicit deliverables verification block in its prompt.

## Result

The Dockerfile-style gap that escaped smoke #12 is now caught on two fronts:

- Wave B is told to verify the deliverables explicitly.
- The verifier and post-Wave-B gate emit `SCAFFOLD-REQUIREMENTS-MISSING-001` if the file is still absent.
