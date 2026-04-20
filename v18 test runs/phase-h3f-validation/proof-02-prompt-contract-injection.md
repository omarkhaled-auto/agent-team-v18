# Proof 02 - Prompt Contract Injection

## Scope

Show that Wave A receives a new `<ownership_contract>` block only when
`wave_a_ownership_contract_injection_enabled=True`, and that the path list comes
from the ownership contract rather than a hardcoded prompt list.

## Evidence

Pytest command:

```text
pytest tests/test_h3f_ownership_enforcement.py tests/test_config_v18_loader_gaps.py -v --tb=short
```

Relevant tests:

- `test_scaffold_owned_paths_are_sourced_from_workspace_contract`
- `test_wave_a_prompt_omits_ownership_block_when_flag_off`
- `test_wave_a_prompt_injects_ownership_block_after_explicit_values`

Observed results:

- `get_scaffold_owned_paths_for_wave_a_prompt(tmp_path)` reads the
  workspace-local `docs/SCAFFOLD_OWNERSHIP.md`, normalizes backslashes, and
  returns a sorted scaffold-owned list.
- With the H3f injection flag off:
  - prompt still includes the H3e explicit-values block when enabled
  - prompt omits `<ownership_contract>`
- With the H3f injection flag on:
  - prompt includes `<ownership_contract>`
  - prompt order is:
    1. H3e explicit contract values
    2. H3f ownership contract
    3. `[WAVE A - SCHEMA / FOUNDATION SPECIALIST]`
  - prompt bullets match the parsed ownership-contract rows

Ring summary:

```text
37 passed in 0.51s
```

Output file:

- `v18 test runs/phase-h3f-validation/pytest-output-h3f-ring.txt`

## Conclusion

The H3f prompt hardening is single-source-of-truth driven. It is fully
flag-gated and does not alter the flag-off prompt body.
