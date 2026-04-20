# Proof 01 - Hypothesis (a) Prompt Hardening

## Scope

Prompt hardening for Codex Wave B lives in:

- `src/agent_team_v15/agents.py`
- `src/agent_team_v15/codex_prompts.py`

The implementation adds a Wave B-only write contract marker, promotes the deliverables block ahead of the requirements framing, and expands the wrapped Codex prompt with a `<tool_persistence>` section plus count-based completion language.

## Verification

Command:

```text
pytest tests/test_phase_h3c_wave_b_fixes.py -q -k "flag_on_promotes_deliverables_and_emits_write_contract or flag_on_wrap_adds_tool_persistence_and_count_verification or flag_off_keeps_marker_and_tool_persistence_absent"
```

Result:

```text
3 passed, 4 deselected in 0.20s
```

## Evidence

- `test_flag_on_promotes_deliverables_and_emits_write_contract`
  - renders a real Wave B prompt against a workspace-local `REQUIREMENTS.md`
  - asserts the prompt now contains `<codex_wave_b_write_contract files="3">`
  - asserts the prompt contains `[DELIVERABLES - 3 REQUIREMENTS-DECLARED FILES MUST EXIST AFTER THIS WAVE]`
  - proves the deliverables list is promoted into the main Wave B body
- `test_flag_on_wrap_adds_tool_persistence_and_count_verification`
  - wraps the rendered Wave B prompt for Codex
  - asserts the wrapped prompt contains `<tool_persistence>`
  - asserts the wrapped prompt contains the count-verification block tied to the extracted file count
- `test_flag_off_keeps_marker_and_tool_persistence_absent`
  - renders the same fixture with the flag disabled
  - asserts the raw prompt has no write-contract marker
  - asserts the wrapped prompt has no `<tool_persistence>`

## Verdict

Hypothesis (a) is implemented and independently gated by `v18.codex_wave_b_prompt_hardening_enabled`.

Flag ON:

- Wave B prompt contains the deliverables-first write contract
- Codex wrapper contains explicit tool-persistence instructions

Flag OFF:

- the new marker is absent
- the new wrapper content is absent
- Wave B prompt generation remains on the pre-H3c path
