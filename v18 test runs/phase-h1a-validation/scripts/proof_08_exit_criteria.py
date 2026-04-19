"""Proof 08: PHASE_FINAL_EXIT_CRITERIA.md checkbox lines match
MASTER_IMPLEMENTATION_PLAN_v2.md:1086-1105 line-for-line.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

# Force stdout to UTF-8 so the ≤/— characters in the checklist render.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[3]
EXIT_CRITERIA = ROOT / "PHASE_FINAL_EXIT_CRITERIA.md"
PLAN = ROOT / "MASTER_IMPLEMENTATION_PLAN_v2.md"


def read_checkbox_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [L for L in lines if L.lstrip().startswith("- [ ]")]


def main() -> int:
    exit_lines_all = read_checkbox_lines(EXIT_CRITERIA)
    # Extract the 20 criterion lines. PHASE_FINAL_EXIT_CRITERIA.md header
    # (must-pass / should-pass / may-pass bullets) use "- #N ..." not "- [ ]",
    # so our filter already excludes them.
    exit_lines = exit_lines_all

    plan_lines_raw = PLAN.read_text(encoding="utf-8").splitlines()
    plan_segment = plan_lines_raw[1085:1105]  # 1086-1105 (1-indexed → 0-indexed 1085-1104)
    plan_lines = [L for L in plan_segment if L.lstrip().startswith("- [ ]")]

    print(f"EXIT_CRITERIA checkbox count: {len(exit_lines)}")
    print(f"PLAN:1086-1105 checkbox count: {len(plan_lines)}")
    print()

    print("=" * 78)
    print("Line-for-line diff (EXIT_CRITERIA vs PLAN)")
    print("=" * 78)
    mismatches = 0
    for i in range(max(len(exit_lines), len(plan_lines))):
        e = exit_lines[i] if i < len(exit_lines) else "<EOF>"
        p = plan_lines[i] if i < len(plan_lines) else "<EOF>"
        if e == p:
            print(f"  [{i+1:2d}] MATCH: {e[:80]}...")
        else:
            mismatches += 1
            print(f"  [{i+1:2d}] MISMATCH:")
            print(f"        exit:  {e}")
            print(f"        plan:  {p}")

    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  checkbox count matches (20 == {len(exit_lines)}):           {len(exit_lines) == 20 and len(plan_lines) == 20}")
    print(f"  all 20 lines match line-for-line:                  {mismatches == 0}")
    return 0 if (mismatches == 0 and len(exit_lines) == 20 and len(plan_lines) == 20) else 2


if __name__ == "__main__":
    sys.exit(main())
