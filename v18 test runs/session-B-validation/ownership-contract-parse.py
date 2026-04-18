"""V5 — ownership contract parser consistency check.

Runs load_ownership_contract() against docs/SCAFFOLD_OWNERSHIP.md and asserts
the counts + spot-check invariants specified in the wiring-verification spec.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

# Change working directory so the default path (``docs/SCAFFOLD_OWNERSHIP.md``)
# resolves relative to the repo root.
import os
os.chdir(str(REPO_ROOT))

from agent_team_v15.scaffold_runner import load_ownership_contract  # noqa: E402

contract = load_ownership_contract()

lines: list[str] = []


def record(label: str, value: object, expected: object) -> bool:
    ok = value == expected
    status = "PASS" if ok else "FAIL"
    lines.append(f"{status} {label}: expected={expected!r} got={value!r}")
    return ok


results = []

# Total row count
results.append(record("total rows", len(contract.files), 60))

# Owner counts
for owner, expected in [
    ("scaffold", 44),
    ("wave-b", 12),
    ("wave-d", 1),
    ("wave-c-generator", 3),
]:
    count = len(contract.files_for_owner(owner))
    results.append(record(f"files_for_owner({owner!r})", count, expected))

# emits_stub=true rows — all 13 have owner=scaffold
stub_rows = [f for f in contract.files if f.emits_stub]
results.append(record("emits_stub=True count", len(stub_rows), 13))
stub_non_scaffold = [f for f in stub_rows if f.owner != "scaffold"]
results.append(record(
    "emits_stub=True rows with owner!=scaffold",
    len(stub_non_scaffold),
    0,
))

# is_optional spot checks
results.append(record("is_optional('.editorconfig')", contract.is_optional(".editorconfig"), True))
results.append(record("is_optional('.nvmrc')", contract.is_optional(".nvmrc"), True))

# owner_for spot checks
results.append(record(
    "owner_for('packages/shared/src/error-codes.ts')",
    contract.owner_for("packages/shared/src/error-codes.ts"),
    "scaffold",
))
results.append(record(
    "owner_for('apps/api/src/main.ts')",
    contract.owner_for("apps/api/src/main.ts"),
    "scaffold",
))

# Diagnostic — list each owner's files (short form)
lines.append("")
lines.append("-- Owner-group summary --")
for owner in ("scaffold", "wave-b", "wave-d", "wave-c-generator"):
    rows = contract.files_for_owner(owner)
    lines.append(f"[{owner}] {len(rows)} files")
    for r in rows:
        opt = " (optional)" if r.optional else ""
        stub = " (stub)" if r.emits_stub else ""
        lines.append(f"  - {r.path}{opt}{stub}")

lines.append("")
if all(results):
    lines.append("SUMMARY: PASS — all 8 invariants satisfied")
else:
    fails = [l for l in lines if l.startswith("FAIL")]
    lines.append(f"SUMMARY: FAIL — {len(fails)} invariant(s) did not hold")

print("\n".join(lines))
