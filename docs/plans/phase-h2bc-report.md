# Phase H2bc — Ownership Policy + Small Bugs Cluster — Final Report

**Branch:** `phase-h2bc-ownership-and-small-bugs`  
**Date:** 2026-04-20  
**Orchestrator:** Codex GPT-5

## Implementation Summary

- Scope B (ownership):
  - Reused the existing shared ownership parser in `src/agent_team_v15/scaffold_runner.py` instead of introducing a second parser.
  - Added workspace-aware ownership loading with repo-root fallback so generated worktrees can still resolve `docs/SCAFFOLD_OWNERSHIP.md`.
  - Added `v18.ownership_policy_required: bool = False`.
  - Wired fail-loud behavior through Check C, spec reconciliation, and scaffold verifier.
  - Extended the ownership document with `requirements_deliverable` / `required_by` metadata.
  - Added `SCAFFOLD-REQUIREMENTS-MISSING-001` and a post-Wave-B deliverable gate.
- Scope C (small bugs):
  - Fixed the N-10 forbidden-content merge crash.
  - Reconciled convergence parsing with the audit-review-log table format.
  - Persisted `scope` and preserved `acceptance_tests` in the audit report rebuild path.
  - Restored `.agent-team/framework_idioms_cache.json` emission, including no-Context7 fallback cases.
  - Added an explicit Wave B scaffold-deliverables verification block.
- Discovery artifacts written:
  - `docs/plans/phase-h2bc-architecture-report.md`
  - `docs/plans/phase-h2bc-discovery-citations.md`
  - `docs/plans/phase-h2bc-ownership-policy-design.md`
  - `docs/plans/phase-h2bc-small-bugs-triage.md`
- Pattern IDs added: `SCAFFOLD-REQUIREMENTS-MISSING-001`
- Config flags added: `ownership_policy_required` (default `False`)
- Approximate net LOC:
  - Source: `+584 / -56`
  - Tests: `+395 / -7`
  - Docs and proofs: `+767 / -0`

## Coverage Matrix

| Pattern ID | What It Catches | Severity | Conditional On |
|---|---|---|---|
| `SCAFFOLD-REQUIREMENTS-MISSING-001` | REQUIREMENTS-declared deliverable missing from scaffold / Wave B handoff | HIGH | Ownership contract available |

## Smoke #12 Finding Closure Status

| Finding | Title | Status | H2bc Item |
|---|---|---|---|
| 02 | `SCAFFOLD_OWNERSHIP.md` absent caused 3-subsystem skip | ✅ | Scope B Items 1-2 |
| 07 | Wave B missed `apps/api/Dockerfile` | ✅ | Scope B Item 3 + Scope C Item 8 |
| 08 | N-10 scanner crashed with `int.append` | ✅ | Scope C Item 4 |
| 09 | Convergence aggregation returned `0/0` | ✅ | Scope C Item 5 |
| N-15 | `AUDIT_REPORT.json.scope` missing | ✅ | Scope C Item 6 |
| N-17 | Framework idioms cache not emitted | ✅ | Scope C Item 7 |

## Test Results

- Targeted regression ring:
  - `pytest tests/test_n10_content_auditor.py tests/test_prd_mode_convergence.py tests/test_config_v18_loader_gaps.py tests/test_ownership_contract.py tests/test_h1a_ownership_enforcer.py tests/test_h1a_scaffold_verifier.py tests/test_n17_mcp_prefetch.py tests/test_h2bc_regressions.py -q`
  - Result: `146 passed in 1.07s`
- Prompt/wiring ring:
  - `pytest tests/test_ownership_consumer_wiring.py tests/test_h1a_wiring.py tests/test_wave_b_selector_scope.py tests/test_v18_specialist_prompts.py tests/test_architecture_injection.py tests/test_n09_wave_b_prompt_hardeners.py tests/test_wave_d_fallback_provider_neutral.py tests/test_scaffold_verifier_post_scaffold.py -q`
  - Result: `120 passed in 1.23s`
- Additional impacted ring:
  - `pytest tests/test_v18_phase3_verification.py tests/test_v18_phase3_live_smoke.py tests/test_e2e_12_fixes.py -q`
  - Result: `116 passed in 4.62s`
- Structural follow-up:
  - `pytest tests/test_h2bc_regressions.py tests/test_walker_sweep_complete.py -q`
  - Result: `9 passed in 0.32s`
- Full default pytest:
  - `pytest tests/ -v --tb=short`
  - Result: `11193 passed, 35 skipped, 1 deselected, 20 warnings in 482.87s (0:08:02)`
- Codex-live pytest:
  - `pytest tests/ -v -m codex_live --tb=short`
  - Result: `1 passed, 1 skipped, 11225 deselected in 11.86s`

## Wiring Verification

- Three ownership consumers now load via the same shared loader in `scaffold_runner.py`.
- `ownership_policy_required=True` raises `OwnershipPolicyMissingError` for:
  - Check C
  - Spec reconciliation
  - Scaffold verifier
- `ownership_policy_required=False` preserves warn-and-skip behavior for the same three paths.
- REQUIREMENTS-declared deliverable enforcement now lands in two places:
  - scaffold verifier summary emission
  - post-Wave-B structured gate
- `AUDIT_REPORT.json.scope` is rebuilt and preserved on the non-downgrade path.
- Framework idioms cache now writes the expected file even on no-Context7 / failure paths.
- H2a preservation check: no diff in
  - `src/agent_team_v15/codex_appserver.py`
  - `src/agent_team_v15/codex_cli.py`
  - `src/agent_team_v15/constitution_templates.py`
  - `src/agent_team_v15/codex_transport.py`
  - `tests/test_codex_appserver_live.py`
  - `tests/test_bug20_codex_appserver.py`
- Mutable cross-run module globals check on H2bc-owned source files: no violations found.

## Review Pass

- Manual end-of-phase review completed against the merged H2bc diff.
- Independent read-only reviewer pass completed as requested.
  - Result: no concrete findings.
  - Residual risks noted:
    - malformed ownership contracts still warn-and-skip in some paths by design
    - Wave B prompt deliverables fall back to heuristic extraction if the contract is unavailable

## Production-Caller Proofs

- `v18 test runs/phase-h2bc-validation/proof-01-ownership-policy-loaded.md`
- `v18 test runs/phase-h2bc-validation/proof-02-ownership-policy-required-flag-enforces.md`
- `v18 test runs/phase-h2bc-validation/proof-03-ownership-policy-required-false-graceful.md`
- `v18 test runs/phase-h2bc-validation/proof-04-scaffold-requirements-deliverable-check.md`
- `v18 test runs/phase-h2bc-validation/proof-05-n10-scanner-fixed.md`
- `v18 test runs/phase-h2bc-validation/proof-06-convergence-aggregation-fixed.md`
- `v18 test runs/phase-h2bc-validation/proof-07-audit-report-scope-field.md`
- `v18 test runs/phase-h2bc-validation/proof-08-framework-idioms-cache-emitted.md`

## Handoff Notes for H2e

- `ownership_policy_required` should be flipped on in the validation smoke config.
- The ownership contract now resolves correctly from generated worktrees that do not contain their own `docs/` subtree.
- Exit-criteria coverage improved directly for:
  - scope persistence
  - framework idioms cache emission
  - ownership enforcement visibility
  - scaffold deliverable enforcement before live probing
- Decomposer behavior remains intentionally out of scope for H2bc.

## Verdict

`SHIP IT`
