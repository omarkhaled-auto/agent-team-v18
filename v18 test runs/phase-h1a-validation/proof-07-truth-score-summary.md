# Proof 07 — TRUTH summary BUILD_LOG panel

## Feature

Phase H1a Item 7: `cli._format_truth_summary_block` reads
`TRUTH_SCORES.json` and returns a 3-line BUILD_LOG panel (`TRUTH SCORE:`,
`GATE:`, `PER-DIMENSION:`). Always-on (no flag gate — it's a telemetry
surface change). Emitted at `cli.py:14018-14024` immediately after
`TRUTH_SCORES.json` is persisted and before the truth-threshold check.

## Production call chain

1. `cli.py:14012` persists `TRUTH_SCORES.json` via `_truth_scores_path.write_text(...)`.
2. `cli.py:14018-14027`: always-on block computes `_format_truth_summary_block(_truth_scores_path, fallback_score=_post_truth_score)` and emits each line via `print_info(...)` into the console capture (BUILD_LOG).
3. Disk read is canonical; when read fails, the in-memory `_post_truth_score` is used as a fallback (graceful).

The proof script calls `_format_truth_summary_block` directly with a
fixture `TRUTH_SCORES.json` on disk — the same callable the pipeline uses.

## Fixture

`fixtures/proof-07/TRUTH_SCORES.json`:

```json
{
  "overall": 0.548,
  "gate": "escalate",
  "passed": false,
  "dimensions": {
    "requirements_coverage": 0.78,
    "contracts_alignment": 0.60,
    "evidence_freshness": 0.45,
    "audit_agreement": 0.55,
    "invariant_preservation": 0.40,
    "consistency_across_waves": 0.62
  }
}
```

## Command

```bash
python "v18 test runs/phase-h1a-validation/scripts/proof_07_truth_summary.py" \
  > "v18 test runs/phase-h1a-validation/proof_07_output.txt"
```

## Salient output

```
Rendered BUILD_LOG TRUTH panel
==============================================================================
TRUTH SCORE: 0.548
GATE: ESCALATE (threshold 0.95 PASS / 0.80 RETRY / below ESCALATE)
PER-DIMENSION: requirements_coverage=0.78, contracts_alignment=0.60, evidence_freshness=0.45, audit_agreement=0.55, invariant_preservation=0.40, consistency_across_waves=0.62
```

### Summary

```
  TRUTH SCORE line emitted (0.548):              True
  GATE: ESCALATE emitted:                        True
  PER-DIMENSION line shows all 6 dimensions:     True (counted 6)
```

## Interpretation

The emitter renders the 3-line panel with the overall score (0.548), the
normalized gate token (`ESCALATE`, uppercased from the stored
`"escalate"`), the threshold legend, and the full `PER-DIMENSION`
enumeration with every one of the 6 fixture dimensions preserved in
insertion order and formatted to two decimal places. The panel is the
artifact that BUILD_LOG captures via `print_info` — auditors reading
BUILD_LOG see this exact text anchored right after TRUTH_SCORES.json is
written. **PASS.**

## Status: PASS
