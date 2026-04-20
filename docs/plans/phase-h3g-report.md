# Phase H3g — Bucket D Cleanup — Final Report

## Implementation Summary
- D3: live Codex test teardown now tracks spawned app-server subprocesses and
  cleans up new Windows Codex-related PIDs after each live test.
- D4: runtime verifier gained a flag-gated refresh-before-verdict path in
  `runtime_verification.py`.
- D5: total fix cap is now enforced in `runtime_verification.py` with one final
  verification-only pass and `FIX-LOOP-CAP-REACHED` telemetry.
- D6: failed milestone health-gate path now has a flag-gated bridge into the
  per-milestone audit-fix-reaudit loop.

## Coverage Matrix
| Item | Site | Flag | Effect | Verification |
|---|---|---|---|---|
| D3 orphan teardown | `tests/test_codex_appserver_live.py` | none | Live test teardown kills tracked subprocesses and new Windows Codex PIDs | H3g ring, `codex_live`, proof-02 |
| D4 refresh | `src/agent_team_v15/runtime_verification.py` | `runtime_verifier_refresh_enabled` | Final bounded health refresh before verdict | H3g ring, runtime suites, proof-01 |
| D5 cap | `src/agent_team_v15/runtime_verification.py` | none | Stop new fixes at cap, then run one final verification pass | H3g ring, proof-02 |
| D6 re-audit | `src/agent_team_v15/cli.py` | `reaudit_trigger_fix_enabled` | Failed milestones can enter `_run_audit_loop(...)` before early `continue` | H3g ring, proof-03 |

## Test Results
- H3g ring:
  - `12 passed`
  - output: `v18 test runs/phase-h3g-validation/pytest-output-h3g-ring.txt`
- Impacted existing suites:
  - `230 passed`
  - command: `tests/test_runtime_verification.py tests/test_runtime_verification_block.py tests/test_audit_team.py tests/test_audit_upgrade.py`
- Prior rings:
  - `37 passed`
  - output: `v18 test runs/phase-h3g-validation/pytest-output-prior-rings.txt`
- Live Codex:
  - `2 passed, 1 skipped`
  - output: `v18 test runs/phase-h3g-validation/pytest-output-codex-live.txt`
- Full pytest:
  - not run

## Wiring Verification
- Flag references present only in `config.py`, `runtime_verification.py`, and `cli.py`.
- `git diff f4f2a42 -- ...` for preserved H3c/H3d/H3e/H3f files: empty.
- `git diff f4f2a42 -- src/agent_team_v15/wave_executor.py`: empty.
- `git diff f4f2a42 -- src/agent_team_v15/cli.py`: only H3g audit-bridge and runtime refresh plumbing.
- `rg -n "RUNTIME-REFRESH-OK|FIX-LOOP-CAP-REACHED" src tests`: telemetry strings only, no new structured finding IDs.

## Production-Caller Proofs
- `v18 test runs/phase-h3g-validation/proof-01-runtime-verifier-refresh.md`
- `v18 test runs/phase-h3g-validation/proof-02-fix-loop-cap-and-orphan-teardown.md`
- `v18 test runs/phase-h3g-validation/proof-03-reaudit-trigger.md`

## D6 Status
PROCEEDED. Discovery showed a local failed-health-gate bypass, not an
architectural audit-loop gap.

## Combined Smoke Readiness
H3e + H3f + H3g are ready for the combined smoke. H3g flags remain default-off
for backward compatibility:
- `runtime_verifier_refresh_enabled`
- `reaudit_trigger_fix_enabled`

## Verdict
READY FOR COMBINED SMOKE
