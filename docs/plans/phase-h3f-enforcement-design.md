# Phase H3f - Enforcement Design

## Goal

Turn `OWNERSHIP-WAVE-A-FORBIDDEN-001` from advisory detection into a real Wave A gate without changing the underlying H1a detector or the H3e redispatch framework.

## Chosen Design

### 1. Keep H1a detector logic intact; change how its findings are consumed

- Preserve `check_wave_a_forbidden_writes()` as the detector of record.
- Add a prompt-facing helper in `ownership_enforcer.py` that loads the scaffold-owned path list from the same ownership contract.
- Do not introduce new pattern IDs.

### 2. Add two new config flags, both default `False`

- `wave_a_ownership_enforcement_enabled: bool = False`
- `wave_a_ownership_contract_injection_enabled: bool = False`

Reason:

- `False` defaults preserve the pre-H3f execution path.
- Separate flags allow investigation of prompt-shaping versus hard enforcement independently.

## Wave Executor Design

### Hook location

Move the Wave A ownership check to run:

1. after H3e's deterministic contract verifier
2. before the Wave A inner loop exits
3. before the outer redispatch planner consumes `wave_result.findings`

### Expected behavior when `wave_a_ownership_enforcement_enabled=False`

- Do not run the new H3f enforcement block.
- Existing `ownership_enforcement_enabled` behavior remains untouched for pre-H3f paths.
- No Wave A failure is caused by H3f.

### Expected behavior when `wave_a_ownership_enforcement_enabled=True`

- Evaluate the union of `wave_result.files_created` and `wave_result.files_modified`.
- Call `check_wave_a_forbidden_writes(...)`.
- Append each returned finding to `wave_result.findings`.
- If at least one ownership finding exists:
  - set `wave_result.success = False`
  - set a Wave A-specific `error_message` mentioning `OWNERSHIP-WAVE-A-FORBIDDEN-001`
- Do **not** directly write new state fields.
- Let the existing H3e redispatch planner inspect the finding codes and schedule a rerun to Wave A.

### Idempotence / H3e interaction

- If H3e contract verifier already failed Wave A, H3f should not overwrite that earlier outcome.
- Practical rule:
  - run H3e verifier first
  - only run H3f ownership enforcement when `wave_result.success` is still `True`
- This gives H3e first claim on the failure reason while still allowing H3f to block Wave A when contract verification passed.

## Prompt Injection Design

### Location

Render the new block in `build_wave_a_prompt()`:

- after the H3e `<stack_contract>` / explicit-values blocks
- before `[WAVE A - SCHEMA / FOUNDATION SPECIALIST]`

### Source of truth

- Add `get_scaffold_owned_paths_for_wave_a_prompt(cwd)` in `ownership_enforcer.py`.
- The helper reads `docs/SCAFFOLD_OWNERSHIP.md` through the same ownership contract parser and returns sorted `owner: scaffold` paths.
- If the contract cannot be loaded, return an empty list and omit the block rather than failing prompt construction.

### Prompt content

The block should:

- state that the scaffolder owns the listed paths
- explicitly say Wave A must not write them
- state that attempts fail the wave with `OWNERSHIP-WAVE-A-FORBIDDEN-001`
- direct Wave A to express schema intent inside `ARCHITECTURE.md` instead of writing scaffold-owned files directly
- instruct Wave A to emit `BLOCKED: Uncertain ownership of <path>.` when unsure

## File Ownership for H3f

Implementation edits should be limited to:

- `src/agent_team_v15/ownership_enforcer.py`
- `src/agent_team_v15/wave_executor.py`
- `src/agent_team_v15/agents.py`
- `src/agent_team_v15/config.py`
- targeted tests and proof/report docs

Explicit non-goals:

- no edit to `docs/SCAFFOLD_OWNERSHIP.md`
- no edit to `scaffold_runner.py`
- no edit to `stack_contract.py`
- no edit to H3e state schema or redispatch planner

## Test Plan

Targeted ring should cover:

1. ownership finding blocks Wave A when H3f enforcement flag is on
2. flag-off behavior remains unchanged
3. non-scaffold paths do not trigger
4. prompt block appears only when the injection flag is on
5. prompt block sources paths from the ownership contract
6. H3e redispatch whitelist still includes `OWNERSHIP-WAVE-A-FORBIDDEN-001`
7. H3e-first ordering / idempotence with contract drift
8. config loader round-trip for both new flags

## Risk Notes

- The detector already emits `HIGH`; the behavior change is the new failure transition in `wave_executor.py`.
- Because H3f runs after H3e verifier, combined first-pass failures can still surface both findings in logs only if ownership enforcement is evaluated while success remains true. The strictest idempotent implementation gives H3e priority and may suppress ownership evaluation when H3e already failed first. That is acceptable for correctness but should be called out in proofs.
- Prompt injection is guidance only; the hard guarantee comes from the executor gate.
