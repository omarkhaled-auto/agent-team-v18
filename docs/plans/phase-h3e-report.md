# Phase H3e — Recovery Re-Dispatch + Contract Pre-Write Guard — Final Report (Pre-Smoke)

## Implementation Summary

- Bug A: added local wave redispatch for eligible recoverable findings inside `wave_executor.py`
- Bug B: added explicit Wave A contract values in the prompt and a deterministic post-Wave-A contract verifier
- Practical guardrail: when spec reconciliation is absent, scaffolding can now inherit explicit contract port literals before writing files
- Contract source in this codebase is `.agent-team/STACK_CONTRACT.json`
- New config flags, all default `False` except `recovery_wave_redispatch_max_attempts=2`:
  - `recovery_wave_redispatch_enabled`
  - `recovery_wave_redispatch_max_attempts`
  - `wave_a_contract_injection_enabled`
  - `wave_a_contract_verifier_enabled`
- New finding / logger codes:
  - `WAVE-A-CONTRACT-DRIFT-001`
  - `RECOVERY-REDISPATCH-001`
  - `RECOVERY-REDISPATCH-002`

Tracked working-tree delta vs `e798967`:

- Source: 1,387 insertions / 13 deletions across `agents.py`, `cli.py`, `config.py`, `scaffold_runner.py`, `stack_contract.py`, `state.py`, `wave_executor.py`
- Tests: 19 tracked insertions plus new H3e test files
- Docs: new H3e discovery docs, proof docs, and this report

## Coverage Matrix

| Fix | Site | Flag | Pattern IDs | Verification |
|---|---|---|---|---|
| Recovery redispatch | `wave_executor.py`, `state.py`, `cli.py`, `config.py` | `recovery_wave_redispatch_enabled` | `RECOVERY-REDISPATCH-001`, `RECOVERY-REDISPATCH-002` | H3e ring, proof-01, proof-03 |
| Wave A explicit contract values | `agents.py`, `stack_contract.py`, `config.py` | `wave_a_contract_injection_enabled` | n/a | H3e ring, proof-02 |
| Wave A contract verifier | `wave_executor.py`, `stack_contract.py`, `config.py` | `wave_a_contract_verifier_enabled` | `WAVE-A-CONTRACT-DRIFT-001` | H3e ring, proof-02, proof-03 |
| Scaffold pre-write contract fallback | `scaffold_runner.py`, `wave_executor.py` | `wave_a_contract_verifier_enabled` | n/a | H3e ring, proof-02 |

## Test Results

- H3e-focused ring: `135 passed in 14.60s`
  - Output: `v18 test runs/phase-h3e-validation/pytest-output-h3e-ring.txt`
- Prior preserved rings: `61 passed in 0.63s`
  - Output: `v18 test runs/phase-h3e-validation/pytest-output-prior-rings.txt`
- `codex_live`: `2 passed, 1 skipped, 11278 deselected in 39.62s`
  - Output: `v18 test runs/phase-h3e-validation/pytest-output-codex-live.txt`
- Full pytest: not run by design

## Wiring Verification

- Flag gating present in `config.py`, `agents.py`, and `wave_executor.py`
- `RunState.wave_redispatch_attempts` round-trips through persistence
- H3e pattern IDs are only present in implementation and H3e test sites
- Prior-phase preservation check on:
  - `provider_router.py`
  - `codex_cli.py`
  - `constitution_templates.py`
  - `codex_transport.py`
  - `ownership_enforcer.py`
  - `spec_reconciler.py`
  - `scaffold_verifier.py`
  - `docs/SCAFFOLD_OWNERSHIP.md`
  - `codex_captures.py`
  - `codex_prompts.py`
  - `codex_appserver.py`
  - `tests/test_codex_dispatch_captures.py`
  - `tests/test_phase_h3c_wave_b_fixes.py`
  - `tests/test_phase_h3d_sandbox_fix.py`
- Result: empty diff vs `e798967`

## Production-Caller Proofs

- `v18 test runs/phase-h3e-validation/proof-01-recovery-redispatch-end-to-end.md`
- `v18 test runs/phase-h3e-validation/proof-02-contract-injection-and-verifier.md`
- `v18 test runs/phase-h3e-validation/proof-03-combined-recovery-plus-contract.md`

## Pending

- Paid validation smoke in a fresh observer session with:
  - `recovery_wave_redispatch_enabled: true`
  - `wave_a_contract_injection_enabled: true`
  - `wave_a_contract_verifier_enabled: true`

## Predicted Outcome

- If Wave A honors the explicit contract block on the first pass, scaffold should write contracted literals and Wave B should dispatch immediately.
- If Wave A still drifts on the first pass, the deterministic verifier now fails that pass before scaffold, redispatches to Wave A, and replays with structured rejection context.
- The primary H3e success criterion remains unchanged: scaffold completes successfully and Wave B dispatches.

## Verdict

READY FOR VALIDATION SMOKE
