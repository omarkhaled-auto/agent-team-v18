"""Scope-aware scaffold verifier — regression guards for the Phase FINAL
smoke failure ``v18 test runs/build-final-smoke-20260418-041514``.

The pre-fix verifier treated every row in ``docs/SCAFFOLD_OWNERSHIP.md``
as mandatory at every milestone, so M1 Wave A failed with 41 MISSING
findings — 30+ of them (``apps/api/src/modules/users/...``, projects,
tasks, comments) belonged to M2-M5 and were correctly absent at M1.

These tests cover three contracts:

1. A scope with concrete ``allowed_file_globs`` filters the ownership
   contract to rows inside those globs.
2. Absence of scope or empty globs preserves the legacy all-rows
   behaviour (strict additive refinement, no regressions).
3. A SCOPE_FILTER summary line is emitted when rows are skipped so the
   diagnostic trail makes the filter visible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15.milestone_scope import MilestoneScope
from agent_team_v15.scaffold_runner import (
    DEFAULT_SCAFFOLD_CONFIG,
    FileOwnership,
    OwnershipContract,
)
from agent_team_v15.scaffold_verifier import run_scaffold_verifier


def _contract(paths: list[tuple[str, str, bool]]) -> OwnershipContract:
    """Build an ``OwnershipContract`` from (path, owner, optional) tuples."""
    return OwnershipContract(
        files=tuple(
            FileOwnership(path=p, owner=owner, optional=optional)
            for p, owner, optional in paths
        )
    )


def _m1_foundation_files(workspace: Path) -> None:
    """Write M1 foundation files expected by the mini contract below.

    NB (Phase H1a): ``docker-compose.yml`` must include a minimal
    ``services.api`` block. The SCAFFOLD-COMPOSE-001 topology check added
    in Phase H1a now FAILs when the api service is absent, so a postgres-
    only compose would flip this test to FAIL for a reason unrelated to
    scope filtering. We keep the fixture semantics (M1 foundation present)
    and add the api service minimally.
    """
    (workspace / "package.json").write_text("{}", encoding="utf-8")
    (workspace / "tsconfig.json").write_text("{}", encoding="utf-8")
    (workspace / "docker-compose.yml").write_text(
        "services:\n  postgres: {}\n  api:\n    image: app:latest\n",
        encoding="utf-8",
    )
    (workspace / "apps/api").mkdir(parents=True, exist_ok=True)
    (workspace / "apps/api/package.json").write_text("{}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Scope filter applied — M2-M5 rows excluded
# ---------------------------------------------------------------------------


def test_scope_aware_filters_m2_m5_rows(tmp_path: Path) -> None:
    """An M1 scope with only foundation globs must cause the verifier to
    skip M2-M5 ownership rows rather than reporting them MISSING."""

    _m1_foundation_files(tmp_path)
    contract = _contract(
        [
            ("package.json", "scaffold", False),
            ("tsconfig.json", "scaffold", False),
            ("docker-compose.yml", "scaffold", False),
            ("apps/api/package.json", "scaffold", False),
            # M2-M5 rows — must be filtered out by scope, not reported MISSING
            ("apps/api/src/modules/users/users.module.ts", "scaffold", False),
            ("apps/api/src/modules/projects/projects.module.ts", "scaffold", False),
            ("apps/api/src/modules/tasks/tasks.module.ts", "scaffold", False),
            ("apps/api/src/modules/comments/comments.module.ts", "scaffold", False),
        ]
    )
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=[
            "package.json",
            "tsconfig.json",
            "docker-compose.yml",
            "apps/api/package.json",
        ],
    )

    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=contract,
        scaffold_cfg=DEFAULT_SCAFFOLD_CONFIG,
        milestone_scope=scope,
    )

    # All 4 M1 foundation files present + 4 M2-M5 rows skipped => PASS.
    assert report.verdict == "PASS", (
        f"Expected PASS with scope filter, got {report.verdict}. "
        f"missing={[str(p) for p in report.missing]} "
        f"summary={report.summary_lines}"
    )
    assert any(
        line.startswith("SCOPE_FILTER milestone-1")
        for line in report.summary_lines
    ), f"Expected SCOPE_FILTER note in summary; got {report.summary_lines}"
    # The SCOPE_FILTER line should mention the 4 skipped rows.
    scope_line = next(
        line for line in report.summary_lines if line.startswith("SCOPE_FILTER")
    )
    assert "4 ownership row" in scope_line


# ---------------------------------------------------------------------------
# Scope filter respects legitimate in-scope missing files
# ---------------------------------------------------------------------------


def test_scope_aware_still_flags_in_scope_missing(tmp_path: Path) -> None:
    """If an M1-scope file is missing, the verifier must still FAIL — the
    scope filter only removes OUT-of-scope rows; it never hides real gaps."""

    # Only 2 of the 4 M1 foundation files are present.
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    # docker-compose.yml and apps/api/package.json deliberately missing.

    contract = _contract(
        [
            ("package.json", "scaffold", False),
            ("tsconfig.json", "scaffold", False),
            ("docker-compose.yml", "scaffold", False),
            ("apps/api/package.json", "scaffold", False),
            ("apps/api/src/modules/users/users.module.ts", "scaffold", False),
        ]
    )
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=[
            "package.json",
            "tsconfig.json",
            "docker-compose.yml",
            "apps/api/package.json",
        ],
    )

    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=contract,
        scaffold_cfg=DEFAULT_SCAFFOLD_CONFIG,
        milestone_scope=scope,
    )

    assert report.verdict == "FAIL"
    missing_names = {p.name for p in report.missing}
    assert "docker-compose.yml" in missing_names
    assert "package.json" in missing_names or "apps" in {
        parent.name for p in report.missing for parent in p.parents
    }
    # M2 users.module.ts must NOT be in the missing list — scope filter.
    assert not any(
        "users.module.ts" in str(p) for p in report.missing
    ), f"M2 row leaked into missing list: {[str(p) for p in report.missing]}"


# ---------------------------------------------------------------------------
# Scope=None or empty globs preserves legacy behaviour
# ---------------------------------------------------------------------------


def test_no_scope_preserves_legacy_all_rows(tmp_path: Path) -> None:
    """When no scope is provided, the verifier must enforce every row —
    backwards-compatible with the pre-fix behaviour."""

    _m1_foundation_files(tmp_path)
    contract = _contract(
        [
            ("package.json", "scaffold", False),
            ("apps/api/src/modules/users/users.module.ts", "scaffold", False),
        ]
    )

    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=contract,
        scaffold_cfg=DEFAULT_SCAFFOLD_CONFIG,
        milestone_scope=None,
    )

    assert report.verdict == "FAIL"
    assert any("users.module.ts" in str(p) for p in report.missing)
    assert not any(
        line.startswith("SCOPE_FILTER") for line in report.summary_lines
    )


def test_empty_globs_preserves_legacy_behaviour(tmp_path: Path) -> None:
    """A scope object with an empty ``allowed_file_globs`` list is treated
    as "no scope data available" (not "scope forbids everything"). This
    prevents a misconfigured empty-scope from accidentally passing the
    verifier when the real milestone has unmet requirements."""

    _m1_foundation_files(tmp_path)
    contract = _contract(
        [
            ("package.json", "scaffold", False),
            ("apps/api/src/modules/users/users.module.ts", "scaffold", False),
        ]
    )
    scope = MilestoneScope(
        milestone_id="milestone-1",
        allowed_file_globs=[],  # empty — should be treated as "no scope"
    )

    report = run_scaffold_verifier(
        workspace=tmp_path,
        ownership_contract=contract,
        scaffold_cfg=DEFAULT_SCAFFOLD_CONFIG,
        milestone_scope=scope,
    )

    assert report.verdict == "FAIL"
    assert any("users.module.ts" in str(p) for p in report.missing)
