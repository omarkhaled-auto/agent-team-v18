# Phase H3f - Architecture Discovery Report

## Branch / Baseline

- Branch: `phase-h3f-ownership-enforcement`
- Base commit: `6b6573d` (`integration-2026-04-15-closeout`)
- Discovery scope: H1a ownership detector, H3e redispatch path, Wave A prompt injection site

## Sources Read

- `v18 test runs/phase-h3d-validation-smoke-20260420-135742/H3D_SMOKE_REPORT.md`
- `docs/plans/phase-h3e-report.md`
- `docs/SCAFFOLD_OWNERSHIP.md`
- `src/agent_team_v15/ownership_enforcer.py`
- `src/agent_team_v15/wave_executor.py`
- `src/agent_team_v15/agents.py`
- `src/agent_team_v15/config.py`
- `tests/test_h1a_ownership_enforcer.py`
- `tests/test_h3e_wave_redispatch.py`
- `tests/test_h3e_contract_guard.py`

## Discovery Summary

### 1. H1a ownership detection is implemented and load-bearing on detection only

- Detector entrypoint: `check_wave_a_forbidden_writes()` at `src/agent_team_v15/ownership_enforcer.py:339`.
- Contract loader path: `_load_scaffold_owned_paths()` at `src/agent_team_v15/ownership_enforcer.py:207`.
- Data source: `load_ownership_contract_from_workspace(cwd)` from `scaffold_runner`, filtered to `row.owner == "scaffold"`.
- Path normalization: `_normalize_rel()` at `src/agent_team_v15/ownership_enforcer.py:246` converts backslashes to `/` and strips leading `./`, so workspace-relative Windows paths normalize correctly.
- Current finding shape: `Finding(code, severity, file, message)` dataclass at `src/agent_team_v15/ownership_enforcer.py:135`.
- Current severity for `OWNERSHIP-WAVE-A-FORBIDDEN-001`: already `HIGH` in the detector, not `WARN`.

### 2. The enforcement gap is in `wave_executor.py`, not the detector

- Current Wave A ownership hook: `src/agent_team_v15/wave_executor.py:5770-5809` (call at line 5792).
- Current behavior:
  - Runs only when `v18.ownership_enforcement_enabled=True`.
  - Calls `check_wave_a_forbidden_writes(...)`.
  - Converts returned `Finding` objects into `WaveFinding` entries on `wave_result.findings`.
  - Does **not** set `wave_result.success = False`.
  - Does **not** set a Wave A-specific `error_message`.
  - Does **not** persist `failed_wave = "A"` directly.
- Result: the detector fires, but the pipeline continues as long as nothing else fails first.

### 3. H3e already has the redispatch machinery H3f needs

- Redispatch code map: `_WAVE_REDISPATCH_TARGET_BY_FINDING_CODE` at `src/agent_team_v15/wave_executor.py:414`.
- Existing whitelist already includes:
  - `WAVE-A-CONTRACT-DRIFT-001 -> A`
  - `OWNERSHIP-WAVE-A-FORBIDDEN-001 -> A`
  - scaffold failure codes back to `A`
- Redispatch planner: `_plan_wave_redispatch()` at `src/agent_team_v15/wave_executor.py:708`.
- State persistence helpers:
  - `_persist_failed_wave_marker()` at `src/agent_team_v15/wave_executor.py:579`
  - `_schedule_wave_redispatch()` at `src/agent_team_v15/wave_executor.py:642`
- Important behavior:
  - When redispatch is scheduled, `failed_wave` is cleared and `wave_redispatch_attempts` is incremented.
  - When no redispatch occurs, the normal failure path persists `failed_wave` for the failed wave.

### 4. Current H3e contract verifier ordering is after the existing ownership append-only hook

- Existing Wave A order inside the inner `while True` loop:
  1. ownership findings appended: `wave_executor.py:5770-5809`
  2. H1b schema gate: `wave_executor.py:5810-5842`
  3. stack-contract validator / retry: `wave_executor.py:5844-5924`
  4. H3e deterministic contract verifier: `wave_executor.py:5926-5939`
- This is the opposite of the H3f requested order.
- H3f must move ownership enforcement so it runs **after** the H3e contract verifier block and before the loop `break`.

### 5. The Wave A prompt insertion point is straightforward

- Prompt builder: `build_wave_a_prompt()` at `src/agent_team_v15/agents.py:8217`.
- Existing H3e contract injection:
  - `stack_contract_block` assembled near `agents.py:8236-8258`
  - inserted into `parts` immediately after `existing_prompt_framework` at `agents.py:8295-8304`
- Recommended H3f placement:
  - add the new `<ownership_contract>` block after the H3e stack-contract block(s)
  - before the `[WAVE A - SCHEMA / FOUNDATION SPECIALIST]` header at `agents.py:8319`
- Reason: both are structural pre-write constraints for Wave A, and this keeps the new contract adjacent to the existing H3e contract guidance.

## Ownership Table Verification

- `docs/SCAFFOLD_OWNERSHIP.md:268` marks `apps/api/prisma/schema.prisma` as `owner: scaffold`.
- `docs/SCAFFOLD_OWNERSHIP.md:275` marks `apps/api/prisma/seed.ts` as `owner: scaffold`.
- `docs/SCAFFOLD_OWNERSHIP.md:74`, `124`, `133`, `335`, `344` also mark `docker-compose.yml`, both `.env.example` files, and both Dockerfiles as scaffold-owned.
- `docs/SCAFFOLD_OWNERSHIP.md:486-489` explicitly says `schema.prisma` and `seed.ts` are scaffold-owned stubs that later waves extend.

## HALT Check

- No HALT condition found.
- `docs/SCAFFOLD_OWNERSHIP.md` is internally consistent for the H3f target paths.
- `ownership_enforcer.py` is implemented, not stubbed.
- `OWNERSHIP-WAVE-A-FORBIDDEN-001` is already eligible for H3e redispatch.
- The required change is additive consumption / prompt hardening, not a redesign.

## Implementation Implications

- Do not change `docs/SCAFFOLD_OWNERSHIP.md`.
- Do not change `load_ownership_contract()` parsing behavior.
- Do not add a new pattern ID.
- Add two new H3f flags, both default `False`.
- Source prompt paths from the ownership contract instead of hardcoding them.
- Enforce failure in `wave_executor.py` after H3e contract verification so H3e remains first in the convergence chain.
