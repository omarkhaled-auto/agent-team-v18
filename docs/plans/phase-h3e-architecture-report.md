# Phase H3e Architecture Report

Date: 2026-04-20

## Scope Note

I did not find a local copy of an H3e phase brief in the workspace or preserved run artifacts. This report is grounded in the current source tree plus the preserved smoke snapshot under `v18 test runs/phase-h3d-validation-smoke-20260420-135742/`.

## Summary

The current code path does not match the likely H3e intent in three important ways:

1. `STACK_CONTRACT` is persisted and loaded as JSON today, even though `V18Config.contract_mode` still defaults to `"markdown"`.
2. The preserved smoke `STACK_CONTRACT.json` is semantically empty, so contract existence is not the same thing as contract usefulness.
3. A scaffold verifier failure halts the milestone in memory, but that failure is not persisted as `wave_progress[<milestone>].failed_wave`, which leaves resume and recovery logic blind.

The highest-risk behavior is the resume path: if an operator resumes after a scaffold failure, the current wave executor can advance to Wave B without rerunning the scaffold verifier.

## Code Reality

| Reality | Evidence | Architectural implication |
|---|---|---|
| Runtime stack-contract storage is JSON | `src/agent_team_v15/stack_contract.py:519-547`, `src/agent_team_v15/cli.py:1712-1730`, `src/agent_team_v15/cli.py:3900-3917` | The effective contract transport is `.agent-team/STACK_CONTRACT.json`, not markdown. |
| Config label still says markdown | `src/agent_team_v15/config.py:770-779` | `contract_mode` is now descriptive drift, not runtime truth. |
| Prompt consumers render markdown from JSON | `src/agent_team_v15/agents.py:8230-8237`, `src/agent_team_v15/agents.py:8287-8291`, `src/agent_team_v15/agents.py:8367-8375` | Markdown is a presentation layer over JSON-backed state. |
| Preserved smoke contract is effectively empty | `v18 test runs/phase-h3d-validation-smoke-20260420-135742/cwd-snapshot-at-halt-20260420-151407/.agent-team/STACK_CONTRACT.json` | Contract-driven recovery cannot assume the contract is populated even when the file exists. |
| Scaffold verifier is sidecar-based | `src/agent_team_v15/wave_executor.py:1040-1129` | The authoritative scaffold failure evidence lives in `scaffold_verifier_report.json`. |
| Scaffold halt is not written to `failed_wave` | `src/agent_team_v15/cli.py:1735-1782`, `src/agent_team_v15/wave_executor.py:4493-4507`, preserved `STATE.json` | Downstream logic keyed to `failed_wave` cannot reason about scaffold failures. |
| Resume selects next wave from `completed_waves` only | `src/agent_team_v15/wave_executor.py:454-464` | Resume logic does not account for a failed scaffold guard. |
| Existing scaffold artifact suppresses scaffold rerun | `src/agent_team_v15/wave_executor.py:4380-4394`, `src/agent_team_v15/wave_executor.py:4518-4527` | Resume can skip straight to B on a verifier-failed tree. |

## Actual Control Flow

### 1. Contract derivation and persistence

- Phase 1.5 resolves the stack contract in `src/agent_team_v15/cli.py:3900-3917`.
- Persistence is always `.agent-team/STACK_CONTRACT.json` via `src/agent_team_v15/stack_contract.py:519-527`.
- Reload also prefers the JSON file over embedded state via `src/agent_team_v15/stack_contract.py:530-547`.
- Prompt builders then format that JSON contract back into a markdown block for Wave A via `src/agent_team_v15/agents.py:8230-8237`.

H3e implication: any design that talks about a markdown stack contract is stale. The runtime reality is "JSON persisted, markdown rendered from JSON."

### 2. Scaffold gate and failure path

- The milestone wave executor runs scaffolding before code-producing waves in `src/agent_team_v15/wave_executor.py:4415-4470`.
- It immediately runs `_maybe_run_scaffold_verifier(...)` in `src/agent_team_v15/wave_executor.py:4483-4492`.
- On verifier failure, it creates a synthetic failing `WaveResult(wave="SCAFFOLD")`, sets `result.success = False`, sets `result.error_wave = "SCAFFOLD"`, and breaks in `src/agent_team_v15/wave_executor.py:4493-4507`.

The preserved smoke verifier report confirms this exact path. The sidecar contains `SCAFFOLD-PORT-002` and says the expected port was `3001` while the scaffolded files all emitted `4000`.

### 3. State persistence gap

- The generic wave-state writer already supports `failed_wave` at `src/agent_team_v15/cli.py:1773-1779`.
- The normal dispatched-wave loop calls that writer after each wave at `src/agent_team_v15/wave_executor.py:4274-4281`.
- The scaffold failure path breaks before that callback is used for `SCAFFOLD`.

Result: the preserved `STATE.json` records `failed_milestones: ["milestone-1"]`, but `wave_progress["milestone-1"]` only lists completed `A` and `A5`, with no `failed_wave`.

### 4. Resume hazard

- Resume wave selection only asks "what is the first wave not in `completed_waves`?" in `src/agent_team_v15/wave_executor.py:454-464`.
- If `A` and `A5` are complete, the answer is `Scaffold`.
- But when the preserved scaffold artifact exists, `scaffolding_completed` becomes true in `src/agent_team_v15/wave_executor.py:4380-4386`.
- The `"Scaffold"` slot is then skipped unconditionally by `src/agent_team_v15/wave_executor.py:4526-4527`.

That means a resumed run can advance to Wave B without rerunning scaffold or the verifier. This is the most important H3e architectural defect.

## Insertion Map

### A. Persist scaffold failure where it actually occurs

- Primary insertion point: `src/agent_team_v15/wave_executor.py:4493-4507`
- Recommendation: when `verifier_error is not None`, call the existing `save_wave_state` callback with `wave="SCAFFOLD"` and `status="FAILED"` before breaking.
- Reason: this is the narrowest place where the executor still has the verifier verdict, the scaffold artifact, and the milestone context.

### B. Make resume scaffold-aware instead of artifact-aware only

- Primary insertion points: `src/agent_team_v15/wave_executor.py:454-464`, `src/agent_team_v15/wave_executor.py:4380-4394`, `src/agent_team_v15/wave_executor.py:4518-4527`
- Recommendation: if the last persisted failure is `SCAFFOLD`, or if the last scaffold verifier verdict is `FAIL`, do not skip the scaffold slot just because the scaffold artifact exists.
- Reason: the current "artifact exists => scaffolding is complete" rule is false for verifier-failed scaffolds.

### C. Surface scaffold-specific resume context

- Primary insertion point: `src/agent_team_v15/cli.py:9527-9658`
- Recommendation: add resume-context text for `failed_wave == "SCAFFOLD"` plus the latest verifier summary line from `.agent-team/scaffold_verifier_report.json`.
- Reason: the current generic resume text does not warn the operator that the tree is still verifier-failed.

### D. Treat empty contracts as advisory, not authoritative

- Primary insertion points: `src/agent_team_v15/cli.py:3900-3917`, `src/agent_team_v15/stack_contract.py:530-547`
- Recommendation: detect semantically empty contracts and surface them as "empty/advisory" rather than silently treating file existence as meaningful contract state.
- Reason: the preserved smoke run shows a real `.agent-team/STACK_CONTRACT.json` file with no useful stack data.

## Safest Redispatch Position

The safest H3e redispatch point is the scaffold-verifier boundary, not Wave B. H3e should only make B eligible after:

1. The scaffold failure is persisted as `failed_wave = "SCAFFOLD"`.
2. The verifier report is available to resume/recovery code.
3. A rerun of scaffold verification has passed.

Anything that requeues B before those three conditions are true would let Codex build on top of a tree that the current guard has already declared invalid.
