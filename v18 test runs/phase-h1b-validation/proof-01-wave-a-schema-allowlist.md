# proof-01 — Wave A schema allowlist block rendered through `build_wave_a_prompt`

## What this proves

`build_wave_a_prompt` renders the `[ARCHITECTURE.md SCHEMA — STRICT ALLOWLIST]` teaching block into the Wave A prompt when `v18.wave_a_schema_enforcement_enabled=True` AND `v18.architecture_md_enabled=True`. The block lists every allowed section (with required/conditional markers), every disallow rule with the paired named reason code + teaching text, and the eight allowed injection-source labels. The rendered output shows the validator's contract is visible to the LLM BEFORE Wave A writes — the same source of truth the validator will use at gate time (`src/agent_team_v15/wave_a_schema.py` constants).

## Fixture

```python
# tmp/h1b_proof_01.py
from types import SimpleNamespace
from agent_team_v15.agents import build_wave_a_prompt
from agent_team_v15.config import AgentTeamConfig

milestone = SimpleNamespace(
    id="milestone-1",
    title="Users",
    template="full_stack",
    description="proof-01 fixture milestone",
    dependencies=[], feature_refs=[], ac_refs=[], merge_surfaces=[],
    stack_target="NestJS Next.js",
)
ir = {
    "entities": [{"name": "User", "fields": [
        {"name": "id", "type": "string"}, {"name": "email", "type": "string"}]}],
    "endpoints": [], "business_rules": [], "state_machines": [],
    "events": [], "integrations": [], "acceptance_criteria": [],
}
cfg = AgentTeamConfig()
cfg.v18.architecture_md_enabled = True
cfg.v18.wave_a_schema_enforcement_enabled = True
```

## Invocation

```python
prompt = build_wave_a_prompt(
    milestone=milestone,
    ir=ir,
    dependency_artifacts={},
    scaffolded_files=[
        "apps/api/src/users/user.entity.ts",
        "apps/api/prisma/schema.prisma",
    ],
    config=cfg,
    existing_prompt_framework="PROOF-01 WAVE-A FRAMEWORK",
)
```

Run: `python tmp/h1b_proof_01.py`

## Output (actual, not paraphrased)

```
--- prompt lines 49..95 ---
0049:
0050: [ARCHITECTURE.md SCHEMA — STRICT ALLOWLIST]
0051: Your handoff file `.agent-team/milestone-milestone-1/ARCHITECTURE.md` will be validated against the allowlist below BEFORE Wave B runs. Sections outside the allowlist are rejected and you will be asked to rewrite.
0052:
0053: Allowed top-level (H2) sections:
0054: - **scope_recap** (required): accepts `## scope recap`, `## intent`
0055: - **what_wave_a_produced** (required): accepts `## what wave a produced`
0056: - **seams_wave_b** (required): accepts `## seams wave b must populate`, `## seams wave b will populate`, `## backend service seams (owned by wave b)`, `## service-layer seams wave b populates`, `## seams wave b`
0057: - **seams_wave_d** (conditional): accepts `## seams wave d must populate`, `## seams wave d will populate`, `## frontend seams (owned by wave d)`, `## frontend seams wave d populates`, `## seams wave d`
0058: - **seams_wave_t** (required): accepts `## seams wave t must populate`, `## seams wave t will populate`, `## seams wave t`
0059: - **seams_wave_e** (required): accepts `## seams wave e must populate`, `## seams wave e must enforce`, `## seams wave e will populate`, `## seams wave e will enforce`, `## seams wave e`
0060: - **schema_body** (conditional): accepts `## fields, indexes, cascades`, `## entities`, `## relationships`, `## migrations`, `## schema summary`, `## entity inventory`, `## entity inventory - this milestone`, `## entity inventory — this milestone`
0061: - **open_questions** (required): accepts `## open questions`, `## open questions / carry-forward`, `## open questions punted to wave b / architect`, `## open questions punted to wave b/architect`
0062:
0063: Reject-list (these sections are never allowed):
0064: - **DESIGN_TOKENS_DUPLICATE** — any H2 matching `design-token contract`, `design token`, `css variable`, `color palette`: Design tokens live in .agent-team/UI_DESIGN_TOKENS.json (Phase G Slice 4c). Do not duplicate tokens in the architecture handoff. Reference the JSON file by path instead.
0065: - **OWNERSHIP_MATRIX_DUPLICATE** — any H2 matching `merge-surface ownership`, `merge surface`, `ownership matrix`, `who writes what`, `merge-surface ownership matrix`: Ownership is defined in docs/SCAFFOLD_OWNERSHIP.md. Do not write a matrix here — reference that file if needed.
0066: - **STACK_REDECLARE** — any H2 matching `stack`, `technology stack`, `tech stack`: Stack is owned by the stack contract (.agent-team/STACK_CONTRACT.json, injected as [STACK CONTRACT]). Wave A must not redeclare stack here.
0067: - **CROSS_MILESTONE_CONTEXT** — any H2 matching `deferred entities`, `future milestones`: Do not describe future milestones. Wave B/D/T/E of this milestone only consume their own MilestoneScope. Future-milestone context belongs in MASTER_PLAN.md, not the architecture handoff.
0068: - **OUT_OF_SCOPE_RESTATED** — any H2 matching `out-of-scope`, `forbidden in this milestone`: Out-of-scope guardrails live in MilestoneScope (A-09) and REQUIREMENTS.md. Do not restate them here.
0069: - **SPECULATIVE_CASCADES** — any H2 matching `cascade-rule placeholder`, `cascade rule placeholder`: Cascade rules live in apps/api/prisma/schema.prisma as Prisma relations. Do not speculate about FK rules for entities this milestone does not introduce.
0070: - **SEED_RUNNER_TOPLEVEL** — any H2 matching `seed-runner seam`: Seed-runner details belong as a bullet inside '## Seams Wave B must populate'. Do not give it its own H2 — the seams sections are the single anchor for downstream waves.
0071: - **MIGRATION_PLAN_SPECULATION** — any H2 matching `migration plan`: Document only migrations this Wave A produced (under '## What Wave A produced'). Future migration names are speculative — the real migration file will be generated by the owning milestone's Wave A via 'prisma migrate dev'.
0072: - **REQUIREMENTS_RESTATED** — any H2 matching `requirements`, `definition of done`: REQUIREMENTS.md is injected into downstream prompts separately. Do not restate requirements or the Definition of Done here.
0073:
0074: Every concrete reference you cite (file paths, ports, entity names, AC ids) must be derivable from one of these injection sources: `scaffolded_files`, `ir_entities`, `acceptance_criteria`, `backend_context`, `stack_contract`, `milestone_id`, `cumulative_architecture`, `dependency_artifacts`.
0075: Fabricated references trigger a WAVE-A-SCHEMA-UNDECLARED-REF-001 finding.
0076:
--- total prompt lines: 101 ---
OK: all proof-01 assertions passed
```

## Assertion

- Double-gate render site: `src/agent_team_v15/agents.py:8367-8372`
  ```python
  if (
      v18_cfg is not None
      and bool(getattr(v18_cfg, "wave_a_schema_enforcement_enabled", False))
      and bool(getattr(v18_cfg, "architecture_md_enabled", False))
  ):
      parts.extend(_render_wave_a_schema_block(milestone_id))
  ```
- Helper: `_render_wave_a_schema_block` at `src/agent_team_v15/agents.py:8132-8195`.
- Source of truth for allowed sections + reject-list is `src/agent_team_v15/wave_a_schema.py` (`ALLOWED_SECTIONS` at :65, `DISALLOWED_SECTION_REASONS` at :98, `ALLOWED_REFERENCES` at :205, `PATTERN_UNDECLARED_REFERENCE` at :219).
- Substitutions are done via Python f-strings over helper-computed values (no `.format()` over caller content), so the rendered block contains zero unsubstituted `{var}` / `${VAR}` / `<inject:VAR>` tokens outside code blocks (verified by the proof script's own regex scan).

This output proves Wave A receives the same allowlist/disallow-list/allowed-references vocabulary the validator will enforce after the SDK turn — the LLM's teaching context and the gate's validation criteria are derived from the same module constants, not maintained as two drifting copies.

## Verification

- Pattern ID surfaced in prompt: `WAVE-A-SCHEMA-UNDECLARED-REF-001` (MEDIUM in validator).
- Guardrail checked: prompt contains no unsubstituted placeholders outside fenced code blocks.
- Guardrail checked: milestone_id substituted literally (`.agent-team/milestone-milestone-1/`, the on-disk directory shape for `milestone_id="milestone-1"`).
