"""Phase 5.2 (R-#36) — lint test for audit-dispatch path construction.

Per ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §M.M9 and
§E.4: every per-milestone audit-dispatch path construction in cli.py
must include the ``"milestones"`` segment between ``req_dir`` and
``milestone.id``. The 2026-04-28 M1 smoke surfaced multiple sites with
the broken pattern (audit-team Claude self-corrected by writing
``AUDIT_REPORT.json`` to a non-canonical nested path); this test fails
CI on any future regression.

Bug shape: ``req_dir / milestone.id / "<.agent-team|REQUIREMENTS.md>"``
Canonical: ``req_dir / "milestones" / milestone.id / "..."``

Reference canonicals: ``cli.py:1254`` (gate site) and ``cli.py:2280``
(natural-completion site).

Phase 5.2 fixes the following sites (verified at HEAD ``e7f45a1``):

* ``cli.py:5035`` — architecture-gate-fail audit-dispatch
  ``requirements_path`` else-branch fallback.
* ``cli.py:5037`` — architecture-gate-fail audit-dispatch ``audit_dir``.
* ``cli.py:5534`` — Phase 4.4 wave-fail audit-dispatch
  ``requirements_path``.
* ``cli.py:5535`` — Phase 4.4 wave-fail audit-dispatch ``audit_dir``.
* ``cli.py:6277`` — natural-completion ``_ms_audit_already_done`` guard
  (the canonical ``AUDIT_REPORT.json`` presence check; coupled to the
  same canonical contract per Option A).
* ``cli.py:6283`` — natural-completion per-milestone re-audit
  ``ms_audit_dir`` construction.
* ``cli.py:6284`` — natural-completion per-milestone re-audit
  ``ms_req_path`` else-branch fallback.
"""

from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI_PATH = _REPO_ROOT / "src" / "agent_team_v15" / "cli.py"


# Match ``req_dir / milestone.id / "<audit-output-segment>"`` without an
# intervening ``"milestones"`` segment. The segment whitelist
# (``.agent-team`` or ``REQUIREMENTS.md``) keeps the lint scoped to
# per-milestone audit-dispatch path construction; non-audit uses of
# ``req_dir / milestone.id / "<other>"`` would not trigger this lint.
#
# Catches every shape we currently see at the broken sites:
#
# * direct: ``audit_dir=str(req_dir / milestone.id / ".agent-team")``
# * conditional: ``... else str(req_dir / milestone.id / "REQUIREMENTS.md")``
# * is_file: ``(req_dir / milestone.id / ".agent-team" / "AUDIT_REPORT.json").is_file()``
# * variable: ``ms_audit_dir = str(req_dir / milestone.id / ".agent-team")``
_BAD_PATTERN = re.compile(
    r"req_dir\s*/\s*milestone\.id\s*/\s*\"(?:\.agent-team|REQUIREMENTS\.md)\"",
    re.MULTILINE,
)


def test_no_audit_dispatch_site_omits_milestones_segment() -> None:
    """Every per-milestone audit path construction in cli.py must
    include the ``"milestones"`` segment.

    Phase 5.2 (R-#36) regression check. If this fails, a new audit-
    dispatch site (or guard) was added with the broken
    ``req_dir / milestone.id / ...`` shape that omits ``"milestones"``.
    Mirror the canonical construction at cli.py:1254 + cli.py:2280.
    """

    assert _CLI_PATH.is_file(), f"cli.py not found at {_CLI_PATH}"
    cli_text = _CLI_PATH.read_text(encoding="utf-8")
    matches = _BAD_PATTERN.findall(cli_text)
    assert not matches, (
        f"Phase 5.2 R-#36 regression: found {len(matches)} broken "
        f"audit-dispatch path construction(s) in cli.py. Every "
        f"`req_dir / milestone.id / \".agent-team\"` or "
        f"`req_dir / milestone.id / \"REQUIREMENTS.md\"` must include "
        f"a `\"milestones\"` segment between `req_dir` and "
        f"`milestone.id` (mirror cli.py:1254 + cli.py:2280). "
        f"See docs/plans/2026-04-28-phase-5-quality-milestone.md "
        f"§M.M9 + §E.4."
    )
