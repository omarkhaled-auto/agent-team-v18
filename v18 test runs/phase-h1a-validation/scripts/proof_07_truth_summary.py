"""Proof 07: BUILD_LOG-visible TRUTH panel.

Fixture: a TRUTH_SCORES.json at gate=escalate with 6 dimensions. Invoke
the production emitter ``cli._format_truth_summary_block`` (used at
cli.py:14019) and show the rendered panel lines.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
FIXTURE = THIS.parent.parent / "fixtures" / "proof-07"


TRUTH_SCORES = {
    "overall": 0.548,
    "gate": "escalate",
    "passed": False,
    "dimensions": {
        "requirements_coverage": 0.78,
        "contracts_alignment": 0.60,
        "evidence_freshness": 0.45,
        "audit_agreement": 0.55,
        "invariant_preservation": 0.40,
        "consistency_across_waves": 0.62,
    },
}


def build_fixture() -> Path:
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    FIXTURE.mkdir(parents=True)
    (FIXTURE / "TRUTH_SCORES.json").write_text(
        json.dumps(TRUTH_SCORES, indent=2), encoding="utf-8"
    )
    return FIXTURE


def main() -> int:
    from agent_team_v15.cli import _format_truth_summary_block

    root = build_fixture()
    truth_path = root / "TRUTH_SCORES.json"

    print("Invoking production emitter cli._format_truth_summary_block")
    print(f"  TRUTH_SCORES.json path: {truth_path}")
    print(f"  file contents: overall=0.548 gate=escalate, 6 dimensions")
    print()

    lines = _format_truth_summary_block(truth_path)

    print("=" * 78)
    print("Rendered BUILD_LOG TRUTH panel")
    print("=" * 78)
    for line in lines:
        print(line)
    print()

    # Assertions
    joined = "\n".join(lines)
    has_gate_escalate = "GATE: ESCALATE" in joined
    has_overall = "TRUTH SCORE: 0.548" in joined
    per_dim_line = next((L for L in lines if L.startswith("PER-DIMENSION:")), "")
    dim_count = per_dim_line.count("=") if per_dim_line else 0

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  TRUTH SCORE line emitted (0.548):              {has_overall}")
    print(f"  GATE: ESCALATE emitted:                        {has_gate_escalate}")
    print(f"  PER-DIMENSION line shows all 6 dimensions:     {dim_count == 6} (counted {dim_count})")
    return 0 if (has_gate_escalate and has_overall and dim_count == 6) else 2


if __name__ == "__main__":
    sys.exit(main())
