# proof-04 — Retry success drives `_enforce_gate_wave_a_schema` through a rerun

## What this proves

`_enforce_gate_wave_a_schema` detects an invalid ARCHITECTURE.md, returns `(True, review_dict)` on `rerun_count=0`, persists the review at `.agent-team/milestones/milestone-1/WAVE_A_SCHEMA_REVIEW.json`, and returns `(False, {})` on `rerun_count=1` after the ARCHITECTURE.md file is replaced with a valid body. The rendered `[SCHEMA FEEDBACK]` block is the text that the Wave A re-dispatch concatenates into `stack_contract_rejection_context` (see `wave_executor.py:4596-4618`).

## Fixture

Invalid body (disallowed sections) vs valid body — written to the fixture's `.agent-team/milestone-milestone-1/ARCHITECTURE.md` via `tempfile.TemporaryDirectory()`:

```python
# INVALID_ARCH excerpt (disallowed sections present)
## Design-token contract
| token | value |
| --- | --- |
| brand | #1a73e8 |

## Merge-surface ownership matrix
| surface | owner |
| --- | --- |
| apps/api/src/main.ts | wave_b |
```

```python
# VALID_ARCH excerpt (all required canonical sections, no disallowed H2s)
## Scope recap
## What Wave A produced
## Seams Wave B must populate
## Seams Wave D must populate
## Seams Wave T must populate
## Seams Wave E must populate
## Open questions
```

## Invocation

```python
import tempfile
from pathlib import Path
from agent_team_v15.cli import _enforce_gate_wave_a_schema, _format_schema_rejection_feedback
from agent_team_v15.config import AgentTeamConfig

with tempfile.TemporaryDirectory(prefix="h1b-proof-04-") as tmp:
    cwd = Path(tmp)
    (cwd / ".agent-team" / "milestone-milestone-1").mkdir(parents=True, exist_ok=True)
    arch_path = cwd / ".agent-team" / "milestone-milestone-1" / "ARCHITECTURE.md"
    arch_path.write_text(INVALID_ARCH, encoding="utf-8")

    cfg = AgentTeamConfig()
    cfg.v18.architecture_md_enabled = True
    cfg.v18.wave_a_schema_enforcement_enabled = True
    cfg.v18.wave_a_rerun_budget = 2

    should_rerun, review = _enforce_gate_wave_a_schema(
        config=cfg, cwd=str(cwd), milestone_id="milestone-1", rerun_count=0,
    )
    feedback = _format_schema_rejection_feedback(review, rerun_count=0, max_reruns=2)

    arch_path.write_text(VALID_ARCH, encoding="utf-8")
    should_rerun2, review2 = _enforce_gate_wave_a_schema(
        config=cfg, cwd=str(cwd), milestone_id="milestone-1", rerun_count=1,
    )
```

Run: `python tmp/h1b_proof_04.py`

## Output (actual, not paraphrased)

```
[setup] wrote invalid ARCHITECTURE.md to C:\Users\OMARKH~1\AppData\Local\Temp\h1b-proof-04-tksyw2bd\.agent-team\milestone-milestone-1\ARCHITECTURE.md

=== First call (rerun_count=0) ===
should_rerun=True  review_keys=['architecture_path', 'findings', 'milestone_id', 'skipped_concrete_checks', 'skipped_reason', 'verdict']

=== [SCHEMA FEEDBACK] block (would concatenate into stack_contract_rejection_context) ===
[SCHEMA FEEDBACK]
Wave A schema validator rejected the ARCHITECTURE.md you previously produced. Retry 1 of 2. Address EVERY item below and emit a fresh ARCHITECTURE.md — do not patch the old one.

1. [schema_rejection] Design-token contract
   Reason: Design tokens live in .agent-team/UI_DESIGN_TOKENS.json (Phase G Slice 4c). Do not duplicate tokens in the architecture handoff. Reference the JSON file by path instead.

2. [schema_rejection] Merge-surface ownership matrix
   Reason: Ownership is defined in docs/SCAFFOLD_OWNERSHIP.md. Do not write a matrix here — reference that file if needed.

=== persisted at .agent-team\milestones\milestone-1\WAVE_A_SCHEMA_REVIEW.json ===
verdict=FAIL  findings_count=2

[setup] rewrote ARCHITECTURE.md with valid body

=== Second call (rerun_count=1) ===
should_rerun=False  review={}

OK: proof-04 retry success verified
```

## Assertion

- Gate function: `_enforce_gate_wave_a_schema` at `src/agent_team_v15/cli.py:10136-10245`. Keyword-only signature matches `_enforce_gate_a5` 1:1.
- No-op paths:
  - `wave_a_schema_enforcement_enabled=False` returns `(False, {})` at `cli.py:10163-10164`.
  - `architecture_md_enabled=False` logs INFO and returns `(False, {})` at `cli.py:10166-10172`.
- Validator invocation: `cli.py:10180-10210` calls `load_architecture_md` + `validate_wave_a_output` with the eight injection sources resolved via `_resolve_wave_a_injection_sources` at `cli.py:10188`.
- Persistence: `_persist_wave_a_schema_review` at `cli.py:10072-10097`. Target path = `.agent-team/milestones/<milestone_id>/WAVE_A_SCHEMA_REVIEW.json` (note: `milestones/` plural, distinct from the input `milestone-<id>/` directory — see proof-05 verification).
- Retry-return branch: `if rerun_count < max_reruns: return True, review` at `cli.py:10226-10227`.
- Feedback formatter: `_format_schema_rejection_feedback` at `cli.py:10100-10133`. Block header: literal string `"[SCHEMA FEEDBACK]"` at `cli.py:10118`.
- Re-dispatch channel: the Wave A re-dispatch at `wave_executor.py:4596-4618` builds `merged_rejection = wave_a_rejection_context + wave_a_schema_rejection_context` and passes it as `stack_contract_rejection_context=merged_rejection` into `build_wave_prompt`, which surfaces it at `agents.py:8353-8358` under `[PRIOR ATTEMPT REJECTED]`.

The output proves the full gate cycle: detect → persist → format feedback → (re-dispatch happens here) → re-validate. When the ARCHITECTURE.md is repaired, the gate returns `(False, {})` and the caller falls through to Wave B. No `WAVE_A_VALIDATION_HISTORY.json` is written — the retry counter is function-local in wave_executor (see proof-05 guardrail).

## Verification

- Pattern ID: `WAVE-A-SCHEMA-REJECTION-001` / severity CRITICAL (2 findings in persisted review).
- Guardrail checked: `WAVE_A_SCHEMA_REVIEW.json` written at the expected path under `.agent-team/milestones/milestone-1/`.
- Guardrail checked: `[SCHEMA FEEDBACK]` block header literal present; both rejected sections plus their teaching text appear in the block body.
- Guardrail checked: on repaired ARCHITECTURE.md, `_enforce_gate_wave_a_schema` with `rerun_count=1` returns `(False, {})` (empty dict) — exact match to the A.5 gate's pass return shape (see `cli.py:9938`).
