"""Phase A production-caller proof for N-15: AuditReport.to_json preserves extras.

Loads build-l's real AUDIT_REPORT.json (scorer-raw shape, contains 14+ scorer-side
extras keys that were silently dropped prior to N-15). Runs it through
AuditReport.from_json -> AuditReport.to_json round-trip via the real library
import chain. Asserts every scorer-side key survives.

Exits 0 on success, 1 on any assertion failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from agent_team_v15.audit_models import AuditReport  # noqa: E402

FIXTURE = REPO_ROOT / "v18 test runs" / "build-l-gate-a-20260416" / ".agent-team" / "AUDIT_REPORT.json"

SCORER_EXTRAS_KEYS_EXPECTED = [
    "schema_version",
    "generated",
    "milestone",
    "verdict",
    "threshold_pass",
    "overall_score",
    "auditors_run",
    "raw_finding_count",
    "deduplicated_finding_count",
    "pass_notes",
    "summary",
    "score_breakdown",
    "dod_results",
    "by_category",
]

CANONICAL_NESTED_KEYS = {
    "max_score": ("score", "max_score"),
}


def _fail(label: str, detail: str) -> None:
    print(f"[FAIL] {label}: {detail}")
    sys.exit(1)


def _pass(label: str, detail: str = "") -> None:
    print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    if not FIXTURE.is_file():
        _fail("fixture_present", f"{FIXTURE} missing — cannot validate N-15 roundtrip against real scorer output")

    raw_text = FIXTURE.read_text(encoding="utf-8")
    original = json.loads(raw_text)

    report = AuditReport.from_json(raw_text)
    roundtrip_text = report.to_json()
    roundtrip = json.loads(roundtrip_text)

    _pass("from_json_succeeds", f"findings={len(report.findings)} fix_candidates={len(report.fix_candidates)} extras_count={len(report.extras)}")

    for key in SCORER_EXTRAS_KEYS_EXPECTED:
        if key in original:
            if key not in roundtrip:
                _fail(f"extras_key_survives[{key}]",
                      f"key present in scorer-raw input but missing from to_json output — N-15 regression")
            if roundtrip[key] != original[key]:
                _fail(f"extras_value_preserved[{key}]",
                      f"value changed: input={original[key]!r}, output={roundtrip[key]!r}")
            _pass(f"extras_key_survives[{key}]")

    for key, nested_path in CANONICAL_NESTED_KEYS.items():
        if key not in original:
            continue
        node = roundtrip
        for step in nested_path:
            if not isinstance(node, dict) or step not in node:
                _fail(f"canonical_nested[{key}]", f"expected path {nested_path!r}; got {roundtrip!r}")
            node = node[step]
        if node != original[key]:
            _fail(f"canonical_nested[{key}]", f"expected nested value {original[key]!r}, got {node!r}")
        _pass(f"canonical_nested[{key}]", f"top-level {key}={original[key]} migrated to {'.'.join(nested_path)}")

    if roundtrip.get("scope") != {}:
        _pass("scope_field_emitted", f"scope={roundtrip.get('scope')!r}")
    else:
        _pass("scope_field_emitted", "empty scope on scorer-raw roundtrip (expected — scorer output had no scope)")

    print()
    print(f"[OVERALL] N-15 round-trip proof against build-l fixture PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
