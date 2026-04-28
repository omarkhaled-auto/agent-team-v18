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


# ---------------------------------------------------------------------------
# R-#36 follow-up — integration audit must NOT pollute root .agent-team/
# (post-2026-04-28 Wave 1 closeout smoke; reviewer-spec adjustment 7)
# ---------------------------------------------------------------------------
#
# The 2026-04-28 Wave 1 closeout smoke surfaced an orphan
# ``<run-dir>/.agent-team/AUDIT_REPORT.json`` alongside the canonical
# per-milestone gating reports under
# ``<run-dir>/.agent-team/milestones/<id>/.agent-team/AUDIT_REPORT.json``.
# Reviewer-spec adjustment 7 (post-2026-04-28): the source is the
# integration audit at the cli.py final-orchestration block; that
# audit was being run with ``audit_dir=req_dir`` (i.e.
# ``<run-dir>/.agent-team``), so the auditor's own
# ``AUDIT_REPORT.json`` landed at the run-dir root before being
# copied/renamed to ``AUDIT_REPORT_INTEGRATION.json``.
#
# Fix landed in cli.py: the integration audit now runs in
# ``<req_dir>/_integration_staging/`` and copies the report to
# ``<req_dir>/AUDIT_REPORT_INTEGRATION.json``.  This lint scopes to
# the milestone-orchestration / final-integration-audit block and
# fails CI on any regression that reintroduces ``audit_dir=req_dir``
# or ``audit_dir=str(req_dir)`` for the integration audit dispatch.
# Standard-mode runs and other code paths that legitimately reference
# ``req_dir`` are unaffected.

# Capture the integration-audit block (anchored on the comment that
# names this audit) plus a lookahead window large enough to cover the
# ``audit_dir=...`` keyword arg in the same ``_run_milestone_audit``
# call.  The block is delimited by the next top-level statement after
# the ``_run_milestone_audit`` close-paren — the surrounding ``if
# config.audit_team.enabled:`` body is short (~25 lines) so a 60-line
# window is conservative.
_INTEGRATION_AUDIT_BLOCK_RE = re.compile(
    r"#\s*Final cross-milestone integration audit.*?"
    r"_run_milestone_audit\([^)]{0,2000}\)",
    re.MULTILINE | re.DOTALL,
)
_INTEGRATION_AUDIT_BAD_AUDIT_DIR_RE = re.compile(
    r"audit_dir\s*=\s*str\(\s*req_dir\s*\)|"
    r"audit_dir\s*=\s*req_dir\b|"
    r"integration_audit_dir\s*=\s*str\(\s*req_dir\s*\)\s*$|"
    r"integration_audit_dir\s*=\s*req_dir\b",
    re.MULTILINE,
)


def test_integration_audit_does_not_pollute_run_dir_root() -> None:
    """The integration audit must NOT run with
    ``audit_dir=str(req_dir)`` or ``audit_dir=req_dir`` because that
    sites the auditors' temporary ``AUDIT_REPORT.json`` at the
    run-dir root next to the renamed
    ``AUDIT_REPORT_INTEGRATION.json``. Reviewers cannot then tell
    which is the gating report and which is advisory.

    The fix: integration audit runs in
    ``<req_dir>/_integration_staging/``; only the renamed
    ``AUDIT_REPORT_INTEGRATION.json`` lands at ``<req_dir>``.
    Per-milestone gating reports under
    ``milestones/<id>/.agent-team/AUDIT_REPORT.json`` remain the
    canonical ``AUDIT_REPORT.json`` location for those consumers.

    Scoped lint per reviewer-spec adjustment 7 — only the
    integration-audit block at the end of ``_run_prd_milestones`` is
    inspected. Standard-mode runs and other code paths that
    reference ``req_dir`` directly are unaffected by this lint.
    """

    assert _CLI_PATH.is_file(), f"cli.py not found at {_CLI_PATH}"
    cli_text = _CLI_PATH.read_text(encoding="utf-8")
    block_match = _INTEGRATION_AUDIT_BLOCK_RE.search(cli_text)
    assert block_match is not None, (
        "Could not locate the integration-audit block in cli.py "
        "(expected the '# Final cross-milestone integration audit' "
        "comment followed by a '_run_milestone_audit(...)' call). "
        "If this anchor was renamed, update the lint regex to track "
        "the new comment."
    )
    block = block_match.group(0)
    bad_matches = _INTEGRATION_AUDIT_BAD_AUDIT_DIR_RE.findall(block)
    assert not bad_matches, (
        f"R-#36 follow-up regression: the integration audit block "
        f"reintroduced ``audit_dir=req_dir`` (found {len(bad_matches)} "
        f"match(es)). The integration audit MUST run in a staging "
        f"subdirectory (e.g. ``<req_dir>/_integration_staging/``) so "
        f"its temporary ``AUDIT_REPORT.json`` does not land at the "
        f"run-dir root next to ``AUDIT_REPORT_INTEGRATION.json``. "
        f"See the 2026-04-28 Wave 1 closeout smoke landing memo "
        f"for the live-evidence shape this fix prevents."
    )


def test_integration_audit_block_uses_staging_subdir() -> None:
    """Positive lock — the integration audit block must reference a
    staging subdirectory under ``req_dir`` (not ``req_dir`` itself).
    The exact subdir name (``_integration_staging``) is locked so the
    fix is durable against accidental rename. If the staging-dir
    name evolves, update this assertion AND
    ``test_integration_audit_does_not_pollute_run_dir_root`` together.
    """

    assert _CLI_PATH.is_file(), f"cli.py not found at {_CLI_PATH}"
    cli_text = _CLI_PATH.read_text(encoding="utf-8")
    block_match = _INTEGRATION_AUDIT_BLOCK_RE.search(cli_text)
    assert block_match is not None
    block = block_match.group(0)
    assert "_integration_staging" in block, (
        "Integration-audit block must use a staging subdirectory "
        "under req_dir to avoid polluting the run-dir root with the "
        "auditor's temporary AUDIT_REPORT.json. Expected reference "
        "to '_integration_staging' in the block."
    )
    # Cleanup must follow — orphaned staging dirs would confuse
    # next-run reviewers and violate the path-classification contract.
    # Look ahead from the block for the rmtree cleanup call. The
    # report-write + cleanup tail can grow as Phase 5.5+ adds the
    # quality-debt sidecar — use a generous 2500-char window.
    block_end = block_match.end()
    cleanup_window = cli_text[block_end : block_end + 2500]
    assert "rmtree" in cleanup_window and "integration_staging_dir" in cleanup_window, (
        "Integration-audit block must clean up the staging "
        "subdirectory after the rename to "
        "AUDIT_REPORT_INTEGRATION.json. Expected an "
        "``rmtree(integration_staging_dir, ignore_errors=True)`` "
        "call within ~2500 chars after the audit dispatch."
    )
