"""D-07 round-trip validation: load build-j's real AUDIT_REPORT.json via
the permissive ``AuditReport.from_json`` and print the populated fields.

Usage (from the repo root):

    python "v18 test runs/session-03-validation/roundtrip-buildj-audit.py"

Writes a single line of summary to stdout. Redirect to the transcript
file under the same directory to archive the outcome.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo import bootstrap — keep this self-contained so the script can run
# without ``pip install -e .`` in a throwaway worktree.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from agent_team_v15.audit_models import AuditReport  # noqa: E402

# ``build-j-closeout-sonnet-20260415`` lives in the primary worktree's
# ``v18 test runs`` directory (gitignored outside of PR branches). Resolve
# it from either worktree so the script works from the session-03 worktree
# and from a follow-up review run in the primary worktree.
_CANDIDATE_ROOTS = [
    _REPO,
    _REPO.parent / "agent-team-v18-codex",
]
SOURCE = None
for root in _CANDIDATE_ROOTS:
    candidate = root / "v18 test runs" / "build-j-closeout-sonnet-20260415" / ".agent-team" / "AUDIT_REPORT.json"
    if candidate.is_file():
        SOURCE = candidate
        break
if SOURCE is None:
    raise SystemExit(
        "build-j AUDIT_REPORT.json not found in any of: "
        + ", ".join(str(r) for r in _CANDIDATE_ROOTS)
    )


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    report = AuditReport.from_json(text)

    print(f"source:          {SOURCE}")
    print(f"audit_id:        {report.audit_id}")
    print(f"cycle:           {report.cycle}")
    print(f"timestamp:       {report.timestamp}")
    print(f"auditors:        {report.auditors_deployed}")
    print(f"findings_count:  {len(report.findings)}")
    print(f"score.score:     {report.score.score}")
    print(f"score.max_score: {report.score.max_score}")
    print(f"score.health:    {report.score.health!r}")
    print(f"extras.verdict:  {report.extras.get('verdict')!r}")
    print(f"extras.health:   {report.extras.get('health')!r}")
    print(f"extras.notes:    {str(report.extras.get('notes'))[:60]!r}...")
    print(f"extras keys:     {sorted(report.extras.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
