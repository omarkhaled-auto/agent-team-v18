# Phase H3c - Four Hypothesis Fixes - Final Report (Pre-Smoke)

## Implementation Summary

- Implemented four H3c hypothesis responses:
  - prompt hardening in `agents.py` + `codex_prompts.py`
  - cwd verification in `codex_appserver.py` with `cli.py` plumbing into `CodexConfig`
  - post-success flush wait in `provider_router.py`
  - checkpoint verification via synthetic tracker tests plus additive checkpoint-diff capture output in `codex_captures.py`
- Added five net-new V18 flags, all defaulting to `False`:
  - `codex_wave_b_prompt_hardening_enabled`
  - `codex_cwd_propagation_check_enabled`
  - `codex_flush_wait_enabled`
  - `codex_flush_wait_seconds`
  - `checkpoint_tracker_hardening_enabled`
- Added one net-new pattern ID:
  - `CODEX-CWD-MISMATCH-001`
- Preserved fallback behavior in `provider_router.py`; H3c only adds logic around the existing checkpoint-diff decision point.
- Preserved H3a prompt/protocol/response capture formats and added one new additive artifact:
  - `.agent-team/codex-captures/milestone-<id>-wave-<letter>-checkpoint-diff.json`
- Approximate H3c change volume:
  - source: 314 changed lines
  - tests: 680 added or updated lines
  - docs/proofs/report: 531 new lines

## Coverage Matrix Per Hypothesis

| Hypothesis | Fix Location | Flag | Pattern ID | Expected Signal In Smoke |
|---|---|---|---|---|
| (a) prompt | `agents.py`, `codex_prompts.py` | `codex_wave_b_prompt_hardening_enabled` | — | prompt capture contains `<tool_persistence>` and Wave B produces write-tool activity |
| (b) cwd | `codex_appserver.py` plus `cli.py` plumbing | `codex_cwd_propagation_check_enabled` | `CODEX-CWD-MISMATCH-001` | mismatch warning if app-server cwd diverges from orchestrator cwd |
| (c) flush | `provider_router.py` | `codex_flush_wait_enabled`, `codex_flush_wait_seconds` | — | checkpoint happens after configured wait on successful Codex dispatch |
| (d) tracker | `wave_executor.py`, `codex_captures.py`, `provider_router.py` | `checkpoint_tracker_hardening_enabled` | — | checkpoint-diff capture exposes pre/post manifests and diff lists |

## Test Results

- Focused H3c ring:
  - `pytest tests/test_phase_h3c_wave_b_fixes.py tests/test_bug20_codex_appserver.py tests/test_config_v18_loader_gaps.py tests/test_codex_dispatch_captures.py -q`
  - `41 passed in 0.53s`
- Prompt and provider adjacency ring:
  - `pytest tests/test_provider_routing.py tests/test_architecture_injection.py tests/test_h1a_wave_b_prompt_compose_directive.py tests/test_n09_wave_b_prompt_hardeners.py tests/test_n17_mcp_prefetch.py tests/test_v18_specialist_prompts.py tests/test_wave_b_selector_scope.py -q`
  - `233 passed in 4.73s`
- Additional router/transport regression ring:
  - `pytest tests/test_provider_router_fallback.py tests/test_transport_selector.py tests/test_claude_provider_model_telemetry.py tests/test_v18_artifact_store_extended.py -q`
  - `28 passed in 4.52s`
- Proof-targeted reruns:
  - prompt hardening slice: `3 passed, 4 deselected`
  - cwd verification slice: `4 passed, 5 deselected`
  - flush/capture/integration slice: `4 passed, 3 deselected`
  - final H3c test file after synthetic tracker and flush-off additions: `9 passed in 0.30s`
- Full default suite:
  - `pytest tests/ -q`
  - `11217 passed, 35 skipped, 1 deselected, 16 warnings in 550.73s (0:09:10)`
- `codex_live`:
  - `pytest tests/ -q -m codex_live`
  - `1 passed, 1 skipped, 11251 deselected in 18.71s`

## Wiring Verification

### 4A - Flag Gating

- `config.py` declares all five H3c flags with defaults of `False`.
- `tests/test_config_v18_loader_gaps.py` now covers bool round-trips for the four boolean flags and float round-trip for `codex_flush_wait_seconds`.
- Prompt hardening, cwd verification, and flush wait are all guarded at their insertion points.
- `checkpoint_tracker_hardening_enabled` remains reserved because H3c did not reproduce a tracker defect that justified a speculative code-path change.

### 4B - File-Scope Separation

Observed source changes are confined to:

- `src/agent_team_v15/agents.py`
- `src/agent_team_v15/cli.py`
- `src/agent_team_v15/codex_appserver.py`
- `src/agent_team_v15/codex_captures.py`
- `src/agent_team_v15/codex_prompts.py`
- `src/agent_team_v15/config.py`
- `src/agent_team_v15/provider_router.py`

Observed test/doc additions and updates are confined to:

- `tests/test_bug20_codex_appserver.py`
- `tests/test_config_v18_loader_gaps.py`
- `tests/test_phase_h3c_wave_b_fixes.py`
- `tests/test_walker_sweep_complete.py`
- `docs/plans/phase-h3c-*.md`
- `v18 test runs/phase-h3c-validation/*.md`

Note:

- `cli.py` is the only shared-plumbing exception to the original hypothesis ownership table. It was required to carry the cwd-check flag into the `CodexConfig` object used by the app-server transport.

### 4C - Prior-Phase Preservation

- No diffs against H2a-owned runtime files:
  - `src/agent_team_v15/codex_cli.py`
  - `src/agent_team_v15/constitution_templates.py`
  - `src/agent_team_v15/codex_transport.py`
- No diffs against H2bc-owned runtime files:
  - `src/agent_team_v15/ownership_enforcer.py`
  - `src/agent_team_v15/spec_reconciler.py`
  - `src/agent_team_v15/scaffold_verifier.py`
  - `src/agent_team_v15/scaffold_runner.py`
  - `docs/SCAFFOLD_OWNERSHIP.md`
- H3a live/capture tests remained untouched except for extending `tests/test_bug20_codex_appserver.py` with H3c cwd-verification coverage.

### 4D - Fallback Preservation

- `provider_router.py` still performs post-dispatch checkpoint diffing and still routes to Claude fallback when the diff is empty.
- H3c only adds:
  - optional wait before post-checkpoint creation
  - optional checkpoint-diff capture emission after diff creation

### 4E - No Module Globals

- No mutable module-level cross-run state was introduced in the H3c-owned runtime files.

### 4F - Pattern ID Uniqueness

- Only one H3c pattern ID was added: `CODEX-CWD-MISMATCH-001`.
- No collisions with prior pattern IDs were found in the changed source and test surfaces.

### 4G - Injection Variable Validity

- Wave B prompt rendering tests assert the count-based write contract resolves to concrete values.
- No `{unsubstituted}` placeholders are left in the rendered hardening block path.

## Production-Caller Proofs

- `v18 test runs/phase-h3c-validation/proof-01-hypothesis-a-prompt-hardening.md`
- `v18 test runs/phase-h3c-validation/proof-02-hypothesis-b-cwd-propagation.md`
- `v18 test runs/phase-h3c-validation/proof-03-hypothesis-c-flush-wait.md`
- `v18 test runs/phase-h3c-validation/proof-04-hypothesis-d-checkpoint-verification.md`
- `v18 test runs/phase-h3c-validation/proof-05-integration-all-four-flags-on.md`

## Pending: Paid Validation Smoke

Not run in this implementation session.

The intended Wave 8 smoke configuration remains:

- `codex_capture_enabled: true`
- `codex_wave_b_prompt_hardening_enabled: true`
- `codex_cwd_propagation_check_enabled: true`
- `codex_flush_wait_enabled: true`
- `codex_flush_wait_seconds: 0.5`
- `checkpoint_tracker_hardening_enabled: true`

## Verdict

READY FOR VALIDATION SMOKE.

Key caveat:

- Hypothesis (d) did not expose a real tracker defect. H3c therefore ships stronger verification and better smoke-time checkpoint observability, while leaving `checkpoint_tracker_hardening_enabled` reserved for a future targeted fix if the paid smoke reveals an actual tracker bug.
