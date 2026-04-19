# proof-05 — Retry exhaustion raises `GateEnforcementError(gate="A-SCHEMA")`

## What this proves

When `rerun_count >= _get_effective_wave_a_rerun_budget(config)`, `_enforce_gate_wave_a_schema` raises `GateEnforcementError` with `.gate='A-SCHEMA'`, `.milestone_id`, and `.critical_count` populated. The fixture tree contains `WAVE_A_SCHEMA_REVIEW.json` but NO `WAVE_A_VALIDATION_HISTORY.json` — the plan-mandated guardrail that h1b must NOT introduce any new persistence layer beyond the review-JSON sibling of `WAVE_A5_REVIEW.json`.

## Fixture

Same invalid `ARCHITECTURE.md` as proof-04 (two disallowed sections → 2 CRITICAL schema_rejection findings). Written under `tempfile.TemporaryDirectory()` at `.agent-team/milestone-milestone-1/ARCHITECTURE.md`.

```python
cfg.v18.wave_a_rerun_budget = 2  # effective budget = 2
```

## Invocation

```python
from agent_team_v15.cli import GateEnforcementError, _enforce_gate_wave_a_schema

should_rerun, _ = _enforce_gate_wave_a_schema(config=cfg, cwd=str(cwd),
                                               milestone_id="milestone-1", rerun_count=0)
# → (True, review)
should_rerun, _ = _enforce_gate_wave_a_schema(config=cfg, cwd=str(cwd),
                                               milestone_id="milestone-1", rerun_count=1)
# → (True, review)
_enforce_gate_wave_a_schema(config=cfg, cwd=str(cwd),
                            milestone_id="milestone-1", rerun_count=2)
# → GateEnforcementError
```

Run: `python tmp/h1b_proof_05.py`

## Output (actual, not paraphrased)

```
rerun_count=0 → should_rerun=True verdict=FAIL
rerun_count=1 → should_rerun=True verdict=FAIL

=== GateEnforcementError raised at rerun_count=2 ===
  .gate='A-SCHEMA'
  .milestone_id='milestone-1'
  .critical_count=2
  str(exc)=GATE A-SCHEMA blocked Wave B for milestone 'milestone-1': 2 schema finding(s) remain after 2 re-run(s) of Wave A. Review .agent-team/milestones/milestone-1/WAVE_A_SCHEMA_REVIEW.json.

=== .agent-team/milestones/milestone-1/ listing ===
  WAVE_A_SCHEMA_REVIEW.json

OK: proof-05 exhaustion verified, no VALIDATION_HISTORY artifact created
```

## Assertion

- Raise site: `src/agent_team_v15/cli.py:10235-10245`
  ```python
  raise GateEnforcementError(
      (
          f"GATE A-SCHEMA blocked Wave B for milestone {milestone_id!r}: "
          f"{critical_count} schema finding(s) remain after "
          f"{rerun_count} re-run(s) of Wave A. Review "
          f".agent-team/milestones/{milestone_id}/WAVE_A_SCHEMA_REVIEW.json."
      ),
      gate="A-SCHEMA",
      milestone_id=milestone_id,
      critical_count=critical_count,
  )
  ```
- `GateEnforcementError` class: `cli.py:9837-9869`. Same class used by `_enforce_gate_a5` (`gate="A5"`, raise at `cli.py:9947`) and `_enforce_gate_t5` (`gate="T5"`, raise at `cli.py:10002`). No new exception class — h1b reuses the existing escalation mechanism per architecture-report §1F.
- Budget resolver: `_get_effective_wave_a_rerun_budget` at `cli.py:10020-10050`; called at the raise site's guard at `cli.py:10225-10227`:
  ```python
  max_reruns = _get_effective_wave_a_rerun_budget(config)
  if rerun_count < max_reruns:
      return True, review
  ```
- Plan guardrail — `WAVE_A_VALIDATION_HISTORY.json` must NOT exist: verified by `os.walk` across the whole fixture tree (`hits = []` — 0 matches anywhere). The gate's only persistence target is `WAVE_A_SCHEMA_REVIEW.json`.

The output proves exhaustion: two invalid attempts are returned as `(True, review)` (which the wave_executor loop handles as "re-dispatch Wave A"), and the third call (`rerun_count=2 >= budget=2`) raises with full context. The orchestrator catch sites branch on `exc.gate in {"A5","T5","A-SCHEMA"}` — h1b added the third member to the set, preserving the existing catch semantics.

## Verification

- Pattern ID: `WAVE-A-SCHEMA-REJECTION-001` surfaces in `critical_count=2` (both disallowed-section rejections counted).
- Guardrail checked: no `WAVE_A_VALIDATION_HISTORY.json` exists anywhere under the fixture tree (recursive `os.walk` search).
- Guardrail checked: `.agent-team/milestones/milestone-1/` contains exactly ONE file — `WAVE_A_SCHEMA_REVIEW.json` — matching architecture-report §1F's "NO NEW INFRASTRUCTURE" directive.
- Exception fields (`gate`, `milestone_id`, `critical_count`) match the `GateEnforcementError` constructor at `cli.py:9837-9869` exactly. This is the same carrier the A.5 catch handlers already key on.
