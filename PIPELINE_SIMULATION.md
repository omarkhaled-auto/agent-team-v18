# Pipeline Dry-Run Simulation

## Overview

`scripts/simulate_pipeline.py` is a fast smoke-test for the audit→fix→reaudit pipeline.
It validates that all pipeline stages are correctly wired and produce the right data
structures **without making any LLM calls**. The entire run completes in under 5 seconds.

## How to Run

```
python scripts/simulate_pipeline.py
```

Exit code `0` means all stages passed. Exit code `1` means at least one stage failed.

## What Each Stage Tests

### Stage 1: Structured Audit Report

Creates a synthetic `AuditReport` with realistic data:
- `score=72.0`, `comprehensive_score=720`
- 8 CRITICAL findings (integration route mismatches, all with `DET-IV-` IDs)
- 4 MEDIUM findings (missing feature, pagination, security, field casing)
- 4 route mappings (3 mismatches, 1 match)
- 5 AC results (2 PASS, 3 FAIL)

Asserts:
- `report.critical_count == 8`
- Route mismatch count == 3, AC failure count == 3
- `to_dict()` / `from_dict()` round-trip preserves all fields
- `write_build_audit()` writes a `BUILD_AUDIT.md` file containing the score,
  route mapping table, AC compliance table, and top issues list

### Stage 2: Triage + Filter (<=20)

Exercises the stop-condition evaluator and finding filter:
- `evaluate_stop_conditions()` with a fresh `LoopState` (no prior runs, score < 850)
  must return `action="CONTINUE"`
- `filter_findings_for_fix()` must return `<= 20` findings
- Filtered list must exclude `REQUIRES_HUMAN` and `ACCEPTABLE_DEVIATION` severities
- Findings must be sorted with CRITICAL before MEDIUM (severity ordering verified)
- After adding 5 synthetic gate findings, the combined filter still caps at 20

### Stage 3: Fix PRD Generation

Passes the 12 filtered findings through `generate_fix_prd()` with a synthetic PRD
that contains a Technology Stack section.

Asserts:
- Output contains `## Features`
- Output contains at least one `### F-FIX-NNN:` heading
- Output contains at least one `- AC-FIX-NNN-NN:` acceptance criterion
- Output contains `## Regression Guard` with `AC-1` listed
- Output is under 50 000 characters (`MAX_FIX_PRD_CHARS`)

### Stage 4: Fix PRD Validation

Passes the generated fix PRD through `_validate_fix_prd()` (the same validator
called internally by `generate_fix_prd`) and additional structural checks:

- `_validate_fix_prd()` returns `True`
- At least 1 `F-FIX` heading present
- At least 1 `AC-FIX` entry present
- Minimum length >= 200 characters
- At least one technology keyword present
- `Fix Run` marker present in the H1 title

### Stage 5: Reaudit Regression Check

Creates a second `AuditReport` representing the post-fix state:
- `score=87.5`, `comprehensive_score=875`
- 0 CRITICAL findings, 2 MEDIUM findings
- `previously_passing=["AC-1", "AC-7", "AC-10"]`

Asserts:
- `second_report.score > first_report.score` (72.0 → 87.5)
- `second_report.comprehensive_score >= 850`
- `second_report.critical_count == 0`
- All ACs from `first_report.previously_passing` are still PASS or PARTIAL in run 2
  (no regressions)
- `second_report.regressions` list is empty
- `evaluate_stop_conditions()` returns a structurally valid decision (either STOP
  due to weighted score >= 850, or CONTINUE — both are correct depending on
  whether optional quality_checks can be imported in the test environment)

## How to Interpret Results

```
=== Results ===
  [OK] Stage 1: Structured Audit Report: PASS
  [OK] Stage 2: Triage + Filter (<=20): PASS (12 findings)
  [OK] Stage 3: Fix PRD Generation: PASS (7911 chars)
  [OK] Stage 4: Fix PRD Validation: PASS
  [OK] Stage 5: Reaudit Regression Check: PASS

ALL STAGES PASS
```

- `[OK]` — stage passed all assertions
- `[FAIL]` — stage raised an exception; the error message tells you which assertion failed
- `[SKIP]` — stage was skipped because an earlier stage it depends on failed

If a stage fails, the script continues to run remaining stages where possible and
prints a `FAILED STAGES` summary at the end.

## What the Simulation Does NOT Cover

The simulation validates **pipeline wiring and data structure correctness** only.
It explicitly does not cover:

| Area | Why excluded |
|------|-------------|
| LLM audit call quality | Requires live LLM; non-deterministic |
| Actual code generation | Requires live builder LLM |
| Deterministic scanner output | Scanners require a real codebase on disk |
| Quality gate scoring | `quality_checks` scanners need real source files |
| Agent deployment checks | Requires real built output to inspect |
| Fix correctness | Whether the LLM's fix actually resolves a finding |
| End-to-end cost tracking | No real runs → no real cost |
| Network/auth failures | No external calls made |
| State persistence across crashes | Tested separately in unit tests |

For full end-to-end validation, see `scripts/audit_e2e_simulation.py` and
`scripts/live_pipeline_simulation.py` (require LLM access and a built codebase).
