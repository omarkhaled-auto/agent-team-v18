# proof-02 — Schema validator rejects smoke-#11-pattern disallowed sections

## What this proves

`validate_wave_a_output` rejects the two disallowed sections from smoke #11's drift class (`## Design-token contract`, `## Merge-surface ownership matrix`) with their named reason codes (`DESIGN_TOKENS_DUPLICATE`, `OWNERSHIP_MATRIX_DUPLICATE`) and the exact teaching text from `DISALLOWED_SECTION_REASONS`. The rendered `[SCHEMA FEEDBACK]` block shows exactly what Wave A receives via `stack_contract_rejection_context` on the retry turn.

## Fixture

```markdown
# Milestone 1 — Users architecture handoff

## Scope recap
Users milestone MVP.

## What Wave A produced
- apps/api/prisma/schema.prisma
- User entity

## Design-token contract
| token | value |
| --- | --- |
| color.brand | #1a73e8 |
| color.bg    | #ffffff |
| color.error | #d93025 |

## Merge-surface ownership matrix
| surface | owner |
| --- | --- |
| apps/api/src/main.ts    | wave_b |
| apps/api/prisma/schema  | wave_a |
| apps/web/src/layout.tsx | wave_d |
| apps/web/src/auth.tsx   | wave_d |

## Seams Wave B must populate
- UsersService.listUsers() seam.

## Seams Wave T must populate
- users.controller.spec.ts

## Seams Wave E must populate
- e2e users smoke test

## Open questions
- none
```

## Invocation

```python
from agent_team_v15.wave_a_schema_validator import (
    validate_wave_a_output, format_schema_rejection_message,
)
result = validate_wave_a_output(FIXTURE, milestone_id="milestone-1")
review = result.to_review_dict()
msg = format_schema_rejection_message(result, rerun_count=0, max_reruns=2)
```

Run: `python tmp/h1b_proof_02.py`

## Output (actual, not paraphrased)

```
=== result.to_review_dict() ===
{
  "milestone_id": "milestone-1",
  "architecture_path": "",
  "verdict": "FAIL",
  "findings": [
    {
      "category": "schema_rejection",
      "ref": "Design-token contract",
      "severity": "CRITICAL",
      "issue": "Design tokens live in .agent-team/UI_DESIGN_TOKENS.json (Phase G Slice 4c). Do not duplicate tokens in the architecture handoff. Reference the JSON file by path instead.",
      "reason_code": "DESIGN_TOKENS_DUPLICATE",
      "pattern_id": "WAVE-A-SCHEMA-REJECTION-001"
    },
    {
      "category": "schema_rejection",
      "ref": "Merge-surface ownership matrix",
      "severity": "CRITICAL",
      "issue": "Ownership is defined in docs/SCAFFOLD_OWNERSHIP.md. Do not write a matrix here — reference that file if needed.",
      "reason_code": "OWNERSHIP_MATRIX_DUPLICATE",
      "pattern_id": "WAVE-A-SCHEMA-REJECTION-001"
    },
    {
      "category": "schema_missing_required",
      "ref": "seams_wave_d",
      "severity": "CRITICAL",
      "issue": "Required section '## Seams wave d must populate' is missing from ARCHITECTURE.md.",
      "pattern_id": "WAVE-A-SCHEMA-REJECTION-001"
    }
  ],
  "skipped_reason": "",
  "skipped_concrete_checks": [
    "ports",
    "entity_names",
    "file_paths",
    "ac_ids"
  ]
}

=== reason codes found ===
['DESIGN_TOKENS_DUPLICATE', 'OWNERSHIP_MATRIX_DUPLICATE']

=== format_schema_rejection_message(rerun=0, max=2) ===
[SCHEMA FEEDBACK]
Wave A schema validator rejected the ARCHITECTURE.md you previously produced. Retry 1 of 2 available. Address EVERY item below and emit a fresh ARCHITECTURE.md — do not patch the old one.

1. [section] ## Design-token contract
   Reason: Design tokens live in .agent-team/UI_DESIGN_TOKENS.json (Phase G Slice 4c). Do not duplicate tokens in the architecture handoff. Reference the JSON file by path instead.

2. [section] ## Merge-surface ownership matrix
   Reason: Ownership is defined in docs/SCAFFOLD_OWNERSHIP.md. Do not write a matrix here — reference that file if needed.

3. [missing] ## Seams wave d must populate (canonical: seams_wave_d)
   Reason: Required section is absent. Add it — see the [ARCHITECTURE.md SCHEMA] block in this prompt for the full allowlist.
```

## Assertion

- Validator: `validate_wave_a_output` at `src/agent_team_v15/wave_a_schema_validator.py:174-339`. Disallowed-section match path: `_match_disallowed` at `:424-429`, iterating `wave_a_schema.DISALLOWED_SECTION_REASONS`.
- Teaching text source: `src/agent_team_v15/wave_a_schema.py:98-183` (`DISALLOWED_SECTION_REASONS`). The rejection "Design tokens live in .agent-team/UI_DESIGN_TOKENS.json …" is byte-identical to `:103-107` in the constants module.
- `SchemaValidationResult.to_review_dict` emitter: `:97-159`. All three findings carry `pattern_id="WAVE-A-SCHEMA-REJECTION-001"` (constant `PATTERN_SECTION_REJECTION` at `wave_a_schema.py:218`).
- Formatter: `format_schema_rejection_message` at `wave_a_schema_validator.py:342-396`. The block is the sub-block that the gate formatter `_format_schema_rejection_feedback` in cli.py composes into the `stack_contract_rejection_context` kwarg on the next Wave A dispatch (see proof-04).

This output proves the validator emits the rejection with (a) the named reason code from the module constant, (b) the full teaching text, and (c) the correct pattern ID. The formatter bundles it into the `[SCHEMA FEEDBACK]` block that plugs into the `[PRIOR ATTEMPT REJECTED]` channel at `agents.py:8353-8358` on re-dispatch. Smoke #11's invented sections are blocked deterministically at gate time.

## Verification

- Pattern ID: `WAVE-A-SCHEMA-REJECTION-001` / severity CRITICAL (per the to_review_dict shape).
- Guardrail checked: reason codes `DESIGN_TOKENS_DUPLICATE` + `OWNERSHIP_MATRIX_DUPLICATE` emitted verbatim, not paraphrased.
- Skipped-checks list (`["ports", "entity_names", "file_paths", "ac_ids"]`) shows the derivability check falls back to skip (no false positives) when the caller does not supply injection sources. Proof-03 proves the same checks fire HIGH when sources ARE supplied.
