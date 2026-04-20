# Phase H3e Recovery Path Map

Date: 2026-04-20

## Observed Path In The Preserved H3d Smoke

1. Phase 1.5 persisted `.agent-team/STACK_CONTRACT.json`, but the preserved file is semantically empty.
2. Wave A and Wave A5 completed and were persisted in `STATE.json`.
3. Scaffolding ran and wrote `.agent-team/artifacts/milestone-1-wave-SCAFFOLD.json`.
4. The scaffold verifier wrote `.agent-team/scaffold_verifier_report.json` with `SCAFFOLD-PORT-002` and `expected PORT=3001 ... found ... 4000`.
5. `wave_executor` halted the milestone in memory with `result.error_wave = "SCAFFOLD"` at `src/agent_team_v15/wave_executor.py:4493-4507`.
6. `STATE.json` did not persist `failed_wave = "SCAFFOLD"` because the scaffold-failure path never called the generic failed-wave writer in `src/agent_team_v15/cli.py:1735-1782`.
7. Same-run recovery stayed in audit/review/debug territory. The preserved `FIX_CYCLE_LOG.md` shows `review_recovery` and a later database-default-value fix, but no same-run wave redispatch.

## Evidence Map

| Artifact | Observed state | Recovery implication |
|---|---|---|
| `.agent-team/STACK_CONTRACT.json` | All major fields blank, arrays empty | Contract existence cannot drive automatic repair. |
| `.agent-team/scaffold_verifier_report.json` | `verdict: FAIL`, `SCAFFOLD-PORT-002`, expected `3001`, found `4000` | This is the authoritative scaffold failure record. |
| `.agent-team/artifacts/milestone-1-wave-SCAFFOLD.json` | Scaffolded file list was persisted | Resume can recover scaffold outputs without rerunning scaffolding from scratch. |
| `.agent-team/STATE.json` | `completed_waves = ["A", "A5"]`, no `failed_wave` | Resume/recovery code cannot tell that scaffold already failed. |
| `.agent-team/FIX_CYCLE_LOG.md` | Review-only recovery documented; no wave redispatch | Current recovery is diagnosis-heavy, not redispatch-heavy. |

## Current Redispatch Risk

The current resume path is not safe for scaffold failures.

- `_get_resume_wave(...)` returns the first wave not listed in `completed_waves` at `src/agent_team_v15/wave_executor.py:454-464`.
- After `A` and `A5`, that next wave is `Scaffold`.
- But if the scaffold artifact already exists, `scaffolding_completed` is true at `src/agent_team_v15/wave_executor.py:4380-4386`.
- The `"Scaffold"` slot is then skipped by `src/agent_team_v15/wave_executor.py:4526-4527`.

Net effect: a resumed run can fall through to Wave B without rerunning the scaffold verifier. That is not a valid recovery boundary.

## Redispatch Options

### Option 1: Directly redispatch Wave B

Reject this option.

- It bypasses the existing scaffold guard.
- It trusts a tree that the verifier already rejected.
- It depends on the operator noticing that `STATE.json` omitted `failed_wave`.

### Option 2: Same-run auto-fix then Wave B

Not safe as the first H3e move.

- The current run does not persist enough scaffold failure state for bounded automation.
- The preserved stack contract is too weak to act as a repair oracle.
- Same-run repair would mix failure classification, mutation, and wave scheduling in one jump.

### Option 3: Redispatch from the scaffold-verifier boundary

This is the safest option and the H3e recommendation.

Flow:

1. Persist `failed_wave = "SCAFFOLD"` at the actual failure site in `src/agent_team_v15/wave_executor.py:4493-4507`.
2. Persist or reference the latest scaffold verifier report from the same boundary.
3. On resume, re-enter the scaffold slot instead of skipping it when the last scaffold verdict was `FAIL`.
4. Apply only deterministic or explicitly approved remediation for the reported verifier code.
5. Rerun the scaffold verifier.
6. Only promote to Wave B after verifier `PASS`.

This preserves the existing guard contract: Wave B never runs on a verifier-failed scaffold.

## Concrete Insertion Points

### 1. Write scaffold failure into state

- `src/agent_team_v15/wave_executor.py:4493-4507`
- Action: invoke `save_wave_state(..., wave="SCAFFOLD", status="FAILED")` before `break`.

### 2. Preserve verifier provenance for resume

- `src/agent_team_v15/wave_executor.py:1100-1123`
- Action: keep the existing sidecar write, then store its path in state artifacts or in the `SCAFFOLD` wave artifact metadata.

### 3. Make resume consult failure state

- `src/agent_team_v15/wave_executor.py:454-464`
- Action: teach `_get_resume_wave(...)` to honor `failed_wave` before falling back to "first incomplete wave".

### 4. Stop skipping failed scaffold slots

- `src/agent_team_v15/wave_executor.py:4380-4394`
- `src/agent_team_v15/wave_executor.py:4518-4527`
- Action: treat `scaffolding_completed` and `scaffold_verifier_passed` as separate facts. Existing artifact plus failed verifier must not imply "safe to continue".

### 5. Tell the operator what will happen on resume

- `src/agent_team_v15/cli.py:9527-9658`
- Action: add scaffold-specific resume instructions so `agent-team resume` does not default to generic convergence guidance.

## Safest-Option Recommendation

H3e should not "resume pipeline from M1 Wave B" as an automated action. The safest redispatch is:

- Persist the scaffold failure.
- Re-enter at the scaffold-verifier boundary.
- Require verifier `PASS` before B.

This is safer than direct B redispatch because it reuses the guard the system already has, instead of trying to recover by ignoring it.
