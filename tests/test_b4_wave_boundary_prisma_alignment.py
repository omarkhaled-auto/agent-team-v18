"""B4 — wave_boundary prisma path alignment with scaffold canonical.

Locks the structural fix per
docs/plans/phase-artifacts/2026-05-04-m1-clean-run-blockers-handoff.md §B4.

Pre-fix the wave_boundary declared root-level ``prisma/**`` as Wave B's
scope, contradicting scaffold_runner._scaffold_prisma_schema_and_migrations
which seeds the canonical schema at ``apps/api/prisma/schema.prisma``.
The contradiction caused Codex Wave B to write to either or both
locations; auditors flagged the duplicate; ``prisma generate`` ran
against fragmented state. The fix aligns wave_boundary with the
scaffold's stated canonical layout.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from agent_team_v15 import wave_boundary
from agent_team_v15.compile_profiles import _workspace_has_package_prisma_ownership
from agent_team_v15.milestone_scope import (
    MilestoneScope,
    files_outside_scope,
    parse_files_to_create,
)


def test_glob_wave_ownership_uses_apps_api_prisma_canonical_path():
    """Static-source lock — ``_GLOB_WAVE_OWNERSHIP`` MUST declare the
    canonical ``apps/api/prisma/**`` and ``apps/api/prisma/*`` glob keys
    AND MUST NOT carry the legacy root-level ``prisma/**`` /
    ``prisma/*`` entries that contradicted the scaffold seed location.
    """
    src = inspect.getsource(wave_boundary)

    # Carve the table out of the module text so we lock against
    # _GLOB_WAVE_OWNERSHIP specifically (not stray comments).
    table_match = re.search(
        r"_GLOB_WAVE_OWNERSHIP\s*:\s*dict\[str,\s*str\]\s*=\s*\{(.+?)\}",
        src,
        re.DOTALL,
    )
    assert table_match, "_GLOB_WAVE_OWNERSHIP table not found in wave_boundary"
    table_body = table_match.group(1)

    assert '"apps/api/prisma/**": "B"' in table_body, (
        "missing canonical apps/api/prisma/** glob in _GLOB_WAVE_OWNERSHIP"
    )
    assert '"apps/api/prisma/*": "B"' in table_body, (
        "missing canonical apps/api/prisma/* glob in _GLOB_WAVE_OWNERSHIP"
    )
    assert '"prisma/**": "B"' not in table_body, (
        "legacy root-level prisma/** entry must be removed from "
        "_GLOB_WAVE_OWNERSHIP (contradicts scaffold canonical at "
        "apps/api/prisma/)"
    )
    assert '"prisma/*": "B"' not in table_body, (
        "legacy root-level prisma/* entry must be removed from "
        "_GLOB_WAVE_OWNERSHIP (contradicts scaffold canonical at "
        "apps/api/prisma/)"
    )


def test_wave_b_boundary_text_uses_canonical_apps_api_prisma_path():
    """Static-source lock — ``_WAVE_B_BOUNDARY`` text scope description
    MUST list the canonical ``apps/api/prisma/**`` path and MUST NOT
    reference root-level ``prisma/**``.
    """
    block = wave_boundary.WAVE_BOUNDARY_BLOCKS["B"]
    assert "apps/api/prisma/**" in block, (
        "Wave B boundary text missing canonical apps/api/prisma/** path"
    )
    # The Wave B block legitimately references "apps/web/" paths; we
    # only forbid root-prisma-as-scope, so check for the leading
    # bullet form that listed it as Wave B's scope pre-fix.
    assert "- prisma/**" not in block, (
        "Wave B boundary text still lists root-level prisma/** (pre-fix "
        "contradiction with scaffold canonical at apps/api/prisma/)"
    )


def test_a09_files_outside_scope_flags_root_prisma_when_milestone_canonical():
    """Behavioural — A-09 post-wave validator (``files_outside_scope``)
    classifies a Wave B output to root ``prisma/schema.prisma`` as
    out-of-scope when the milestone's allowed_file_globs list the
    canonical ``apps/api/prisma/**``. Symmetric: a write to
    ``apps/api/prisma/schema.prisma`` is in-scope.
    """
    scope = MilestoneScope(
        milestone_id="milestone-1",
        description="M1 foundation — backend + prisma at canonical path.",
        allowed_file_globs=[
            "apps/api/**",
            "apps/api/prisma/**",
            "apps/api/prisma/migrations/**",
            "docker-compose.yml",
            "package.json",
        ],
    )

    # Root prisma write — out of scope (would have been silently
    # accepted before the planner / wave_boundary canonicalisation).
    flagged = files_outside_scope(["prisma/schema.prisma"], scope)
    assert flagged == ["prisma/schema.prisma"], (
        f"expected root prisma/schema.prisma to be flagged out-of-scope "
        f"under canonical-path scope; got {flagged!r}"
    )

    # Canonical write — in scope.
    flagged_canonical = files_outside_scope(
        ["apps/api/prisma/schema.prisma"], scope
    )
    assert flagged_canonical == [], (
        f"canonical apps/api/prisma/schema.prisma must NOT be flagged; "
        f"got {flagged_canonical!r}"
    )

    # Migration under canonical path — also in scope (covered by
    # apps/api/prisma/** + apps/api/prisma/migrations/**).
    flagged_migration = files_outside_scope(
        ["apps/api/prisma/migrations/20260101000000_init/migration.sql"],
        scope,
    )
    assert flagged_migration == [], (
        f"canonical migration path must NOT be flagged; "
        f"got {flagged_migration!r}"
    )


def test_compile_profiles_workspace_prisma_ownership_works_at_canonical_path(
    tmp_path: Path,
) -> None:
    """Backward-compat — ``compile_profiles._workspace_has_package_prisma_ownership``
    returns True for the canonical scaffold layout
    (``apps/api/prisma/schema.prisma``). The scaffold seed location
    (scaffold_runner.py:1912-1915) is unchanged by B4; this test
    verifies the call path still works with the new ownership glob.
    """
    workspace_dir = tmp_path / "apps" / "api"
    prisma_dir = workspace_dir / "prisma"
    prisma_dir.mkdir(parents=True)
    (prisma_dir / "schema.prisma").write_text(
        "// scaffold seed\n"
        "generator client {\n"
        '  provider = "prisma-client-js"\n'
        "}\n"
        "datasource db {\n"
        '  provider = "postgresql"\n'
        '  url      = env("DATABASE_URL")\n'
        "}\n"
    )

    assert _workspace_has_package_prisma_ownership(workspace_dir) is True, (
        "compile_profiles must still detect the canonical "
        "apps/api/prisma/schema.prisma layout after B4"
    )

    # Sanity: workspace without the schema returns False (no false
    # positives — verifies the predicate isn't trivially True).
    empty_workspace = tmp_path / "apps" / "web"
    empty_workspace.mkdir(parents=True)
    assert _workspace_has_package_prisma_ownership(empty_workspace) is False


# ---------------------------------------------------------------------------
# B4-r2 — narrative-PRD path (`_derive_surface_globs_from_requirements`)
# ---------------------------------------------------------------------------
#
# The live M1 PRD used by hardening smokes lacks a literal ``## Files to
# Create`` block; ``parse_files_to_create`` falls through to
# ``_derive_surface_globs_from_requirements`` (milestone_scope.py:121-155).
# Pre-r2 that fallback emitted root-level ``prisma/**`` whenever the PRD
# mentioned ``prisma`` — re-introducing the same scaffold/wave_boundary
# contradiction B4-r1 closed in wave_boundary. r2 aligns the narrative
# path with the canonical ``apps/api/prisma/**`` glob so the production
# smoke path also benefits.


def test_narrative_prd_emits_canonical_apps_api_prisma_glob() -> None:
    """B4-r2: ``parse_files_to_create`` (narrative-PRD fallback) MUST
    emit ``apps/api/prisma/**`` when the PRD mentions ``prisma`` in
    free-form prose, NOT root-level ``prisma/**``. Mirrors the live M1
    PRD shape used by hardening smokes (no ``## Files to Create`` block).
    """
    narrative_prd = (
        "# Milestone 1 - Platform Foundation\n\n"
        "## In-Scope Deliverables\n\n"
        "Monorepo layout: `apps/api`, `apps/web`, `packages/api-client`, `prisma/`.\n"
        "## Merge Surfaces\n"
        "`apps/api/src/main.ts`, `prisma/schema.prisma`, `docker-compose.yml`.\n"
    )
    globs = parse_files_to_create(narrative_prd)

    assert "apps/api/prisma/**" in globs, (
        f"narrative-PRD fallback must emit canonical apps/api/prisma/** glob; "
        f"got {globs!r}"
    )
    assert "prisma/**" not in globs, (
        f"narrative-PRD fallback must NOT emit legacy root-level prisma/**; "
        f"got {globs!r}"
    )


def test_narrative_prd_only_schema_mention_still_emits_canonical_glob() -> None:
    """The regex covers the ``prisma/schema.prisma`` alternation — a PRD
    that mentions ONLY the explicit schema path (no bareword ``prisma``)
    must still emit the canonical ``apps/api/prisma/**`` glob.
    """
    narrative_prd = (
        "# Milestone 1 - Platform Foundation\n\n"
        "Define the database via `prisma/schema.prisma` and run "
        "`prisma migrate deploy` on boot.\n"
    )
    globs = parse_files_to_create(narrative_prd)

    assert "apps/api/prisma/**" in globs, (
        f"narrative-PRD with only `prisma/schema.prisma` mention must "
        f"emit canonical glob; got {globs!r}"
    )
    assert "prisma/**" not in globs


def test_narrative_prd_a09_flags_root_prisma_writes_under_canonical_scope() -> None:
    """End-to-end behavioural lock — when the narrative-PRD fallback
    builds a MilestoneScope, the A-09 ``files_outside_scope`` validator
    flags a Wave B output that writes to root ``prisma/schema.prisma``
    as out-of-scope (because the derived globs declare canonical
    ``apps/api/prisma/**`` only). This is the production smoke path
    that B4-r1 alone did not cover.
    """
    narrative_prd = (
        "# Milestone 1 - Platform Foundation\n\n"
        "Build NestJS at `apps/api/` with Prisma schema in `prisma/schema.prisma`.\n"
    )
    globs = parse_files_to_create(narrative_prd)
    scope = MilestoneScope(
        milestone_id="milestone-1",
        description="M1 narrative PRD.",
        allowed_file_globs=globs,
    )

    # Root prisma write — out of scope under the new canonical-only glob.
    flagged = files_outside_scope(["prisma/schema.prisma"], scope)
    assert flagged == ["prisma/schema.prisma"], (
        f"narrative-PRD scope must flag root prisma/schema.prisma; "
        f"got {flagged!r}"
    )

    # Canonical write — in scope.
    flagged_canonical = files_outside_scope(
        ["apps/api/prisma/schema.prisma"], scope
    )
    assert flagged_canonical == [], (
        f"canonical apps/api/prisma/schema.prisma must NOT be flagged "
        f"under narrative-PRD scope; got {flagged_canonical!r}"
    )
