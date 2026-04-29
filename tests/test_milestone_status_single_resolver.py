"""Phase 5.5 §M.M1 — Single-resolver lint test.

Asserts no direct ``update_milestone_progress(state, id, "COMPLETE")``
or ``"DEGRADED"`` literal call remains in cli.py outside the migration
sites that are explicitly preserved (parallel-mode worktree merge,
quality-validators FAILED override, hard-execution FAILED).

This test fails CI on any future regression that adds a new
quality-dependent terminal write bypassing
``_finalize_milestone_with_quality_contract``.
"""

from __future__ import annotations

import re
from pathlib import Path


CLI_PATH = Path(__file__).parent.parent / "src" / "agent_team_v15" / "cli.py"


def test_no_direct_complete_literal_writes_in_cli():
    """No ``update_milestone_progress(..., "COMPLETE", ...)`` literal in cli.py.

    The Phase 5.5 single-resolver helper is the only authorized writer
    for COMPLETE. Future regressions that add a direct COMPLETE literal
    fail this test.
    """

    src = CLI_PATH.read_text(encoding="utf-8")
    # Match update_milestone_progress(...args..., "COMPLETE", ...) where
    # the literal "COMPLETE" appears as a positional or keyword argument.
    pattern = re.compile(
        r'update_milestone_progress\s*\([^)]*"COMPLETE"',
        re.MULTILINE | re.DOTALL,
    )
    matches = pattern.findall(src)
    assert matches == [], (
        "Phase 5.5 §M.M1 lint: direct update_milestone_progress(..., "
        f'"COMPLETE", ...) literals found in cli.py: {matches}. '
        "Route through _finalize_milestone_with_quality_contract instead."
    )


def test_no_direct_degraded_literal_writes_in_cli():
    """No ``update_milestone_progress(..., "DEGRADED", ...)`` literal in cli.py."""

    src = CLI_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r'update_milestone_progress\s*\([^)]*"DEGRADED"',
        re.MULTILINE | re.DOTALL,
    )
    matches = pattern.findall(src)
    assert matches == [], (
        "Phase 5.5 §M.M1 lint: direct update_milestone_progress(..., "
        f'"DEGRADED", ...) literals found in cli.py: {matches}. '
        "Route through _finalize_milestone_with_quality_contract instead."
    )


def test_resolver_helper_is_imported_from_quality_contract():
    """cli.py imports the resolver from quality_contract module.

    Confirms the §M.M1 chokepoint is reachable from cli.py call sites.
    """

    src = CLI_PATH.read_text(encoding="utf-8")
    assert "_finalize_milestone_with_quality_contract" in src, (
        "Phase 5.5 §M.M1: cli.py must import "
        "_finalize_milestone_with_quality_contract from quality_contract."
    )
    assert "from .quality_contract import" in src, (
        "Phase 5.5 §M.M1: cli.py must do an explicit "
        "'from .quality_contract import' to surface the chokepoint."
    )


def test_quality_contract_module_exposes_resolver():
    """The resolver helper is exported from quality_contract.py."""

    from agent_team_v15 import quality_contract
    assert hasattr(quality_contract, "_finalize_milestone_with_quality_contract")
    assert hasattr(quality_contract, "_evaluate_quality_contract")
