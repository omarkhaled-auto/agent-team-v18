# Phase H3c Hypothesis (a) Design

## Goal

Reduce the chance that Codex reads a zero-entity/infrastructure milestone as "no work" and returns a success-shaped response without writing files.

## Constraints

- Flag-off behavior must stay byte-identical.
- `provider_router.py` does not pass config into `wrap_prompt_for_codex(...)`, so the Codex wrapper cannot consult `config.v18` directly.
- The deliverables count must come from existing repo data, not a new regex over prose.

## Source Of Truth For Deliverables

Use the existing helper chain:

- [`_extract_wave_b_scaffold_deliverables`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8445>)
- [`_format_wave_b_scaffold_deliverables_block`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/agents.py:8472>)

That helper already combines requirements text with `docs/SCAFFOLD_OWNERSHIP.md` rows marked as `requirements_deliverable` and `required_by in {scaffold, wave-b}`. It is the safest available source for a real file-count and file list.

## Proposed Implementation

### 1. Body-level promotion in `agents.py`

When `v18.codex_wave_b_prompt_hardening_enabled` is on:

- compute `deliverables = _extract_wave_b_scaffold_deliverables(requirements_text, cwd=cwd)`
- inject a new block before `[MILESTONE REQUIREMENTS]`:

```text
[DELIVERABLES - N REQUIREMENTS-DECLARED FILES MUST EXIST AFTER THIS WAVE]
- file-a
- file-b
...

[INFRASTRUCTURE MILESTONE CLARIFICATION]
Acceptance Criteria: 0 means no user-facing ACs, not zero file production.
Wave B is complete only when the requirements-declared deliverable files above
exist on disk in the active tree.
```

- add a deterministic marker line, for example:

```text
<codex_wave_b_write_contract files="N">
```

This marker exists only when the flag is on.

### 2. Wrapper-level hardening in `codex_prompts.py`

Add a small helper that detects the marker block in the raw prompt text. If the marker is absent, `wrap_prompt_for_codex(...)` stays byte-identical. If the marker is present for Wave B:

- prepend an extra `<tool_persistence>` block to the normal Wave B preamble
- append a count-verification reminder before the existing suffix

The dynamic wrapper text should say, in substance:

- write tools are required
- read/search/command tools do not count as completion
- returning success with zero writes is failure
- use `BLOCKED:` if the scope is truly impossible

### 3. Keep the existing hardener content intact

The existing AUD-009/010/012/013/016/018/020/023 blocks in both the body and the Codex preamble remain untouched. H3c only adds a new block around them.

## Tests

- `build_wave_b_prompt` with the flag on includes the promoted deliverables/count block.
- The same call with the flag off omits the new block.
- `wrap_prompt_for_codex("B", prompt)` with the marker present includes the `<tool_persistence>` block and count reminder.
- `wrap_prompt_for_codex("B", prompt)` without the marker remains byte-identical to the previous structure.
- Placeholder safety: rendered prompt contains no unsubstituted `{...}` markers.

## Risks

- The ownership contract may not enumerate every prose-only deliverable in every future milestone. For H3c that is acceptable because the goal is to break the "zero work" mental model with a real file count, not to perfectly serialize the entire requirements prose.
