# proof-03 — Derivability validator blocks smoke-#11 defect class

## What this proves

The concrete-reference derivability validator (`_validate_concrete_references`) fires `WAVE-A-SCHEMA-REFERENCE-001` HIGH findings for every smoke-#11 drift shape — `PORT ?? 8080` fallback-default when DoD=3080, hallucinated `TaxInvoice` entity against empty `ir_entities`, invented `apps/invented/main.ts` path outside the allowed surfaces, `NFR-MADEUP-999` AC not in scope, and future-milestone reference `M7`. All 5 categories fire at HIGH severity in a single validator pass. This is the root-cause fix for smoke #11: the validator does not depend on `{placeholder}` syntax — it cross-checks literal values against the eight injection sources.

## Fixture

```markdown
# Milestone 1 — Users

## Scope recap
Users MVP with tax invoice emission.

## What Wave A produced
- apps/api/src/main.ts binds to `process.env.PORT ?? 8080`.
- apps/invented/main.ts — handoff surface.
- Adds AC NFR-MADEUP-999 acceptance criterion.
- Depends on M7 predecessor data.

## Entities
- TaxInvoice: fields id (string), total (decimal), issued_at (timestamp).

## Seams Wave B must populate
- TaxInvoiceService.emit()

## Seams Wave D must populate
- TaxInvoice list view.

## Seams Wave T must populate
- tax-invoice.controller.spec.ts

## Seams Wave E must populate
- e2e tax-invoice.spec.ts

## Open questions
- none
```

Injection sources mirror M1 on-disk state: `scaffolded_files` lists three files, `scaffold_ownership_paths` adds two more, `ir_entities=[]` (foundation milestone), `ir_acceptance_criteria=["FR-USERS-1","FR-USERS-2","BR-USERS-1"]`, `stack_contract={"ports":{"api":3080}, "dod":{"port":3080}}`, `backend_context` gives `api_root/repository_example_path/entity_example_path`, `dependency_artifacts={}` (no predecessor), `cumulative_architecture=""`.

## Invocation

```python
from agent_team_v15.wave_a_schema_validator import validate_wave_a_output

result = validate_wave_a_output(
    FIXTURE,
    milestone_id="milestone-1",
    scaffolded_files=scaffolded_files,
    scaffold_ownership_paths=scaffold_ownership,
    ir_entities=[],                                  # foundation milestone
    ir_acceptance_criteria=["FR-USERS-1","FR-USERS-2","BR-USERS-1"],
    stack_contract={"ports":{"api":3080}, "dod":{"port":3080}},
    backend_context=backend_context,
    cumulative_architecture="",
    dependency_artifacts={},
)
```

Run: `python tmp/h1b_proof_03.py`

## Output (actual, not paraphrased)

```
=== concrete_references (raw dataclasses) ===
  token='8080'  category='port'  severity=HIGH
    message=Wave A handoff references port 8080 via a fallback-default expression (e.g. `PORT ?? 8080`) which is not in the stack co...
  token='8080'  category='port'  severity=HIGH
    message=Wave A handoff references port 8080 which is not in the stack contract ports ([3080]). Cite only values provided to the ...
  token='TaxInvoice'  category='entity'  severity=HIGH
    message=Wave A handoff references entity 'TaxInvoice' which is not in the milestone IR entity scope ([] (empty)). Cite only enti...
  token='apps/invented/main.ts'  category='file_path'  severity=HIGH
    message=Wave A handoff references path 'apps/invented/main.ts' which is not in the scaffolded_files list, docs/SCAFFOLD_OWNERSHI...
  token='NFR-MADEUP-999'  category='ac_id'  severity=HIGH
    message=Wave A handoff references acceptance-criterion 'NFR-MADEUP-999' which is not in the milestone-scoped AC list. Cite only ...
  token='M7'  category='milestone_ref'  severity=HIGH
    message=Wave A handoff references milestone 'M7' which is neither this milestone nor a predecessor in dependency_artifacts / cum...

=== categories hit: ['ac_id', 'entity', 'file_path', 'milestone_ref', 'port'] ===

=== review.findings entries with pattern_id WAVE-A-SCHEMA-REFERENCE-001 ===
[
  {
    "category": "schema_concrete_reference_port",
    "ref": "8080",
    "severity": "HIGH",
    "issue": "Wave A handoff references port 8080 via a fallback-default expression (e.g. `PORT ?? 8080`) which is not in the stack contract ports ([3080]). Cite only values provided to the Wave A prompt.",
    "pattern_id": "WAVE-A-SCHEMA-REFERENCE-001"
  },
  {
    "category": "schema_concrete_reference_port",
    "ref": "8080",
    "severity": "HIGH",
    "issue": "Wave A handoff references port 8080 which is not in the stack contract ports ([3080]). Cite only values provided to the Wave A prompt.",
    "pattern_id": "WAVE-A-SCHEMA-REFERENCE-001"
  },
  {
    "category": "schema_concrete_reference_entity",
    "ref": "TaxInvoice",
    "severity": "HIGH",
    "issue": "Wave A handoff references entity 'TaxInvoice' which is not in the milestone IR entity scope ([] (empty)). Cite only entities provided to the Wave A prompt; if this is a foundation milestone, use an explicit-zero declaration instead.",
    "pattern_id": "WAVE-A-SCHEMA-REFERENCE-001"
  },
  {
    "category": "schema_concrete_reference_file_path",
    "ref": "apps/invented/main.ts",
    "severity": "HIGH",
    "issue": "Wave A handoff references path 'apps/invented/main.ts' which is not in the scaffolded_files list, docs/SCAFFOLD_OWNERSHIP.md, or the backend_context prefixes. Cite only values provided to the Wave A prompt.",
    "pattern_id": "WAVE-A-SCHEMA-REFERENCE-001"
  },
  {
    "category": "schema_concrete_reference_ac_id",
    "ref": "NFR-MADEUP-999",
    "severity": "HIGH",
    "issue": "Wave A handoff references acceptance-criterion 'NFR-MADEUP-999' which is not in the milestone-scoped AC list. Cite only AC ids provided to the Wave A prompt.",
    "pattern_id": "WAVE-A-SCHEMA-REFERENCE-001"
  },
  {
    "category": "schema_concrete_reference_milestone_ref",
    "ref": "M7",
    "severity": "HIGH",
    "issue": "Wave A handoff references milestone 'M7' which is neither this milestone nor a predecessor in dependency_artifacts / cumulative ARCHITECTURE.md. Do not describe future milestones — their context is not available to downstream waves.",
    "pattern_id": "WAVE-A-SCHEMA-REFERENCE-001"
  }
]

OK: proof-03 assertions passed — smoke-#11 defect class blocked
```

## Assertion

- Entry point: `validate_wave_a_output` at `src/agent_team_v15/wave_a_schema_validator.py:174-339`. Concrete-reference block runs at `:310-337`.
- Core enforcer: `_validate_concrete_references` at `src/agent_team_v15/wave_a_schema_validator.py:465-707`.
  - Ports — fallback-default `PORT ??/||/:-/:= <digits>` at `:496-516` (the exact smoke-#11 pattern); broader port-literal scan in `what_wave_a_produced` + `seams_wave_b` bodies at `:517-551`.
  - Entity names — CamelCase scan scoped to `schema_body` sections at `:553-587` with the framework-idiom noise list at `:793-820`.
  - File paths — `apps/…` / `packages/…` tokens diffed against `scaffolded_files + scaffold_ownership + backend_context prefixes` at `:589-633`.
  - AC ids — `FR-…/BR-…/NFR-…` regex at `:635-660`.
  - Milestone refs — `M<n>` regex matched against `self + dependency_artifacts.keys() + cumulative_architecture` at `:662-705`.
- Pattern constant: `PATTERN_CONCRETE_REFERENCE = "WAVE-A-SCHEMA-REFERENCE-001"` at `src/agent_team_v15/wave_a_schema.py:223`.
- Severity: `ConcreteReferenceViolation.severity: str = "HIGH"` default at `wave_a_schema_validator.py:72`.

The stanza that blocks smoke #11's 8080 drift is `_port_fallback_re = re.compile(r"PORT\s*(?:\?\?|\|\||:-|:=|\?|:)\s*(\d{2,5})", re.IGNORECASE)` at `wave_a_schema_validator.py:446-448` + the iteration at `:496-516`. It matches `PORT ?? 8080` directly, which the pre-H1b placeholder scan (only `{var}` / `${VAR}` / `<inject:VAR>`) could not see.

## Verification

- Pattern ID: `WAVE-A-SCHEMA-REFERENCE-001` / severity HIGH (all 6 findings).
- Guardrail checked: all 5 required categories (`port`, `entity`, `file_path`, `ac_id`, `milestone_ref`) produce at least one HIGH finding.
- Guardrail checked: port `8080` surfaced twice — once from the high-specificity fallback-default pattern and once from the broader literal scan (intentional belt-and-suspenders; both sites map to the same pattern ID).
- Root-cause fix vs containment: this is the structural fix for smoke #11's defect class (per the architecture-report §11 "Derivability validator added in the post-review fix round" note). There is no timeout or retry cap masking the drift — the validator refuses the handoff at the boundary.
