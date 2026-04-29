"""Phase 5 closeout-smoke harness scripts.

Operator-driven tooling for executing the staged closeout-smoke plan
described in ``docs/plans/phase-artifacts/phase-5-closeout-smoke-plan.md``:

* :mod:`scripts.phase_5_closeout.k2_evaluator` — Phase 5.8a §K.2
  decision-gate evaluator. Reads per-milestone PHASE_5_8A_DIAGNOSTIC.json
  artifacts from a smoke batch, applies the §K.2 predicate, writes
  PHASE_5_8A_DIAGNOSTIC_SUMMARY.md.
* :mod:`scripts.phase_5_closeout.fault_injection` — Stage 2A fault-
  injection helpers for Phase 5.7 closure rows. Default-off; importing
  the module is a no-op. Operator-driven activation only.

Plan approval ≠ spend authorization. Every smoke fires only after
explicit operator release per the staged closeout-smoke plan.
"""
