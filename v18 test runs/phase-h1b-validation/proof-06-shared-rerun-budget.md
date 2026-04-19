# proof-06 — Shared rerun budget resolver across schema gate + A.5

## What this proves

`_get_effective_wave_a_rerun_budget(config)` honors the canonical `wave_a_rerun_budget` key (default 2) AND the legacy `wave_a5_max_reruns` key — when the legacy key is set to a non-default value it overrides the canonical budget AND emits a `DeprecationWarning` via Python's `warnings` module. Both gate functions (`_enforce_gate_wave_a_schema` AND `_enforce_gate_a5`) route their budget read through the same resolver, so the shared-budget invariant holds: schema gate + stack-contract retry + A.5 retry all drain the same counter.

(This is a correction vs wiring-verifier §4B Observation 1 — in the current source, `_enforce_gate_a5` has been updated to also call `_get_effective_wave_a_rerun_budget`. The observation was accurate for an earlier snapshot but is stale for h1b HEAD.)

## Fixture

```python
# Case 1: canonical=2, legacy=default (1) → resolver returns 2, no warning
cfg1 = AgentTeamConfig()
cfg1.v18.wave_a_rerun_budget = 2
cfg1.v18.wave_a5_max_reruns = 1  # legacy default

# Case 2: canonical=2, legacy=5 (override) → resolver returns 5 + DeprecationWarning
cfg2 = AgentTeamConfig()
cfg2.v18.wave_a_rerun_budget = 2
cfg2.v18.wave_a5_max_reruns = 5  # legacy override
```

## Invocation

```python
import warnings, inspect
from agent_team_v15.cli import (
    _enforce_gate_a5, _enforce_gate_wave_a_schema,
    _get_effective_wave_a_rerun_budget,
)
with warnings.catch_warnings(record=True) as w1:
    warnings.simplefilter("always")
    budget1 = _get_effective_wave_a_rerun_budget(cfg1)   # 2, 0 warns

with warnings.catch_warnings(record=True) as w2:
    warnings.simplefilter("always")
    budget2 = _get_effective_wave_a_rerun_budget(cfg2)   # 5, 1 DeprecationWarning

src_a5 = inspect.getsource(_enforce_gate_a5)
src_schema = inspect.getsource(_enforce_gate_wave_a_schema)
sig_a5 = inspect.signature(_enforce_gate_a5)
sig_schema = inspect.signature(_enforce_gate_wave_a_schema)
```

Run: `python tmp/h1b_proof_06.py`

## Output (actual, not paraphrased)

```
Case 1: canonical=2 legacy=1 (default) → budget=2  warnings=0
Case 2: canonical=2 legacy=5 → budget=5  warnings=1
  DeprecationWarning message: v18.wave_a5_max_reruns is deprecated; use v18.wave_a_rerun_budget instead.

=== _enforce_gate_a5 budget-read lines ===
        ``v18.wave_a5_max_reruns`` re-runs; Wave B must be blocked.
      # honors `wave_a_rerun_budget` canonically and forwards a non-default
      # legacy `wave_a5_max_reruns` with a one-shot deprecation warning.
      max_reruns = _get_effective_wave_a_rerun_budget(config)
      if rerun_count < max_reruns:

=== signatures match: ['config', 'cwd', 'milestone_id', 'rerun_count'] ===

=== _get_effective_wave_a_rerun_budget source ===
def _get_effective_wave_a_rerun_budget(config: AgentTeamConfig) -> int:
    """Resolve the shared Wave A rerun budget.

    Precedence:
    1. If the legacy ``wave_a5_max_reruns`` key was supplied in the loaded
       config AND differs from the default, forward its value as the
       effective budget (after emitting a ``DeprecationWarning`` —
       Python's ``warnings`` module dedupes to once-per-source-location
       by default, so no module state is required).
    2. Otherwise read ``wave_a_rerun_budget`` (default 2).

    The returned value is decremented across schema gate, stack-contract
    rejection, AND A.5 — all three share the counter.
    """
    v18 = getattr(config, "v18", None)
    if v18 is None:
        return 2

    canonical = int(getattr(v18, "wave_a_rerun_budget", 2) or 2)
    legacy = getattr(v18, "wave_a5_max_reruns", None)
    if isinstance(legacy, int) and legacy != 1:
        import warnings

        warnings.warn(
            "v18.wave_a5_max_reruns is deprecated; use v18.wave_a_rerun_budget "
            "instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return int(legacy)
    return canonical
```

## Assertion

- Resolver: `_get_effective_wave_a_rerun_budget` at `src/agent_team_v15/cli.py:10020-10050`.
- Schema gate invocation: `cli.py:10225` (`max_reruns = _get_effective_wave_a_rerun_budget(config)`).
- A.5 gate invocation: `cli.py:9944` (same call — `inspect.getsource(_enforce_gate_a5)` above shows the literal line `max_reruns = _get_effective_wave_a_rerun_budget(config)`). **Both gates use the resolver symmetrically** — this is the post-review state. The wiring-verifier report noted asymmetry at an earlier commit; h1b HEAD has both gates routed through the resolver.
- Warnings dedupe: via `warnings.warn(..., DeprecationWarning, stacklevel=2)` at `cli.py:10043-10048`. No module-level dedupe set — architecture-report §11 explicitly documents the swap from `_WAVE_A_SCHEMA_ALIAS_WARNED` to `warnings.warn`.
- Signature mirror: `inspect.signature` shows `['config', 'cwd', 'milestone_id', 'rerun_count']` for both gate functions (all KEYWORD_ONLY), enforcing the Wave 2A "mirror _enforce_gate_a5 exactly" constraint.

The output proves:
1. Canonical key wins when legacy is at default (no warning).
2. Legacy key wins when overridden + emits `DeprecationWarning` (not a module-state hack).
3. Both gate functions read via the resolver, so the rerun budget is a single shared counter — schema gate consuming 1 rerun leaves only 1 for A.5 / stack-contract retry (assuming budget=2).

## Verification

- Pattern ID: n/a (config-resolution helper, not a finding emitter).
- Guardrail checked: `DeprecationWarning` category emitted (not a plain `UserWarning` or print).
- Guardrail checked: `inspect.getsource(_enforce_gate_a5)` contains the literal line `max_reruns = _get_effective_wave_a_rerun_budget(config)` — confirmed by the proof-script output above.
- Guardrail checked: no module-global dedupe set `_WAVE_A_SCHEMA_ALIAS_WARNED` referenced inside the resolver body.
- Informational note: wiring-verification §4B Obs 1 said "A.5 reads `wave_a5_max_reruns` directly at cli.py:9940" — at h1b HEAD the call site is `cli.py:9944 max_reruns = _get_effective_wave_a_rerun_budget(config)`. The asymmetry is closed; the verifier's observation was accurate for its snapshot but stale for this proof's snapshot. **Not a bridge gap** — the post-review state is strictly better than the verified state.
