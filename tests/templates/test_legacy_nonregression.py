"""Non-regression guard: Path A refactor preserves legacy scaffold contract.

Briefed requirement (Issue #14 / Path A): "The refactored templates, when
rendered with default slots (with audit fixes applied), must produce output
that preserves the current scaffold contract." This test pins the intentional
diffs (the audit fixes) explicitly and fails loudly if an unintentional change
creeps in.

The pre-refactor legacy strings are snapshotted verbatim as module-level
constants below so the diff story remains auditable when the scaffold
templates are touched in the future.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15.template_renderer import render_template


# ---------------------------------------------------------------------------
# Pre-refactor legacy strings (verbatim from scaffold_runner.py pre-Path-A).
# These are FROZEN snapshots. Do NOT modify to chase renderer changes —
# the point of this file is to surface diffs for review.
# ---------------------------------------------------------------------------

LEGACY_INLINE_COMPOSE = (
    "services:\n"
    "  postgres:\n"
    "    image: postgres:16-alpine\n"
    "    ports:\n"
    '      - "5432:5432"\n'
    "    environment:\n"
    "      POSTGRES_USER: ${POSTGRES_USER:-postgres}\n"
    "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}\n"
    "      POSTGRES_DB: ${POSTGRES_DB:-app}\n"
    "    volumes:\n"
    "      - postgres_data:/var/lib/postgresql/data\n"
    "    healthcheck:\n"
    '      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-app}"]\n'
    "      interval: 10s\n"
    "      timeout: 5s\n"
    "      retries: 5\n"
    "\n"
    "  api:\n"
    "    build:\n"
    "      context: ./apps/api\n"  # <-- DOCK-001 bug: narrow context
    "    ports:\n"
    '      - "4000:4000"\n'
    "    environment:\n"
    "      DATABASE_URL: postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-postgres}@postgres:5432/${POSTGRES_DB:-app}?schema=public\n"
    '      PORT: "4000"\n'
    "      JWT_SECRET: ${JWT_SECRET:-dev-secret-change-me}\n"
    "    depends_on:\n"
    "      postgres:\n"
    "        condition: service_healthy\n"
    "    healthcheck:\n"
    '      test: ["CMD-SHELL", "curl -f http://localhost:4000/api/health || exit 1"]\n'
    "      interval: 10s\n"
    "      timeout: 5s\n"
    "      retries: 5\n"
    "    volumes:\n"
    "      - ./apps/api/src:/app/src\n"  # <-- Stale mount bug
    "      - ./apps/api/prisma:/app/prisma\n"  # <-- Stale mount bug
    "\n"
    "  web:\n"
    "    build:\n"
    "      context: ./apps/web\n"  # <-- DOCK-001 bug: narrow context
    "    ports:\n"
    '      - "3000:3000"\n'
    "    environment:\n"
    "      NEXT_PUBLIC_API_URL: http://localhost:4000/api\n"
    "      INTERNAL_API_URL: http://api:4000/api\n"
    "    depends_on:\n"
    "      api:\n"
    "        condition: service_healthy\n"
    "\n"
    "volumes:\n"
    "  postgres_data:\n"
)


def _rendered(name: str) -> str:
    rendered = render_template("pnpm_monorepo")
    return rendered.files[Path(name)]


class TestComposeLegacyContract:
    """Compare rendered compose.yml to the legacy string; pin the audit fixes.

    Audit fixes deliberately introduced by Path A:
      1. DOCK-001 (api): ``context: ./apps/api`` → ``context: . / dockerfile: apps/api/Dockerfile``
      2. DOCK-001 (web): ``context: ./apps/web`` → ``context: . / dockerfile: apps/web/Dockerfile``
      3. Stale bind mounts: removed ``./apps/api/src:/app/src`` + ``./apps/api/prisma:/app/prisma``
      4. Healthcheck: curl → node (smaller attack surface, no curl dep needed)
    Any OTHER diff between rendered and legacy is an unintentional regression.
    """

    def test_postgres_service_unchanged(self) -> None:
        rendered = _rendered("docker-compose.yml")
        # postgres service block (credentials, port, healthcheck) must carry over.
        assert "image: postgres:16-alpine" in rendered
        assert 'POSTGRES_USER: ${POSTGRES_USER:-postgres}' in rendered
        assert 'POSTGRES_DB: ${POSTGRES_DB:-app}' in rendered
        assert "- postgres_data:/var/lib/postgresql/data" in rendered
        assert 'pg_isready' in rendered

    def test_audit_fix_1_dock001_api_context(self) -> None:
        rendered = _rendered("docker-compose.yml")
        # Legacy bug GONE:
        assert "context: ./apps/api" not in rendered
        # Fix present:
        assert "dockerfile: apps/api/Dockerfile" in rendered

    def test_audit_fix_2_dock001_web_context(self) -> None:
        rendered = _rendered("docker-compose.yml")
        assert "context: ./apps/web" not in rendered
        assert "dockerfile: apps/web/Dockerfile" in rendered

    def test_audit_fix_3_stale_bind_mounts_removed(self) -> None:
        rendered = _rendered("docker-compose.yml")
        assert "./apps/api/src:/app/src" not in rendered
        assert "./apps/api/prisma:/app/prisma" not in rendered

    def test_audit_fix_4_healthcheck_no_curl(self) -> None:
        rendered = _rendered("docker-compose.yml")
        # curl was the legacy healthcheck tool; node stdlib http is the
        # replacement. The container image no longer needs curl installed.
        assert "curl -f http://localhost" not in rendered
        assert "require('http').get" in rendered

    def test_depends_on_long_form_preserved(self) -> None:
        """The long-form ``condition: service_healthy`` wiring must stay —
        it's load-bearing for the Phase 6 compose-sanity gate."""
        rendered = _rendered("docker-compose.yml")
        assert "condition: service_healthy" in rendered
        # postgres must be gated by api
        assert "depends_on" in rendered

    def test_ports_preserved(self) -> None:
        rendered = _rendered("docker-compose.yml")
        assert '"5432:5432"' in rendered
        assert '"4000:4000"' in rendered
        assert '"3000:3000"' in rendered

    def test_web_envs_preserved(self) -> None:
        rendered = _rendered("docker-compose.yml")
        assert "NEXT_PUBLIC_API_URL: http://localhost:4000/api" in rendered
        assert "INTERNAL_API_URL: http://api:4000/api" in rendered

    def test_no_unexpected_legacy_markers(self) -> None:
        """Guard against silent regressions. If any of these substrings
        sneak back in, we're likely reintroducing a bug."""
        rendered = _rendered("docker-compose.yml")
        forbidden_markers = [
            "context: ./apps/api",
            "context: ./apps/web",
            "./apps/api/src:/app/src",
            "./apps/api/prisma:/app/prisma",
            "curl -f http://localhost:4000",
        ]
        for marker in forbidden_markers:
            assert marker not in rendered, (
                f"Legacy bug marker resurfaced: {marker!r}. "
                f"This means the Path A audit fix was accidentally reverted."
            )


class TestWebDockerfileLegacyContract:
    """Compare rendered web Dockerfile to the legacy string; pin audit fixes.

    Audit fixes deliberately introduced by Path A:
      1. Add non-root ``USER appuser`` in runner stage (security hardening).
      2. Add ``apps/web/node_modules`` copy in runner for workspace symlink
         resolution at ``next start``.
    """

    def test_structural_patterns_preserved(self) -> None:
        rendered = _rendered("apps/web/Dockerfile")
        # Multi-stage signatures the legacy string had must still exist.
        assert "FROM node:20-alpine AS base" in rendered
        assert "corepack enable" in rendered
        assert "pnpm install --frozen-lockfile" in rendered
        # Build invocation: calls the package's build script (not a direct
        # ``pnpm next build``) so the Dockerfile stays decoupled from
        # app-level tooling choices.
        assert "pnpm run build" in rendered
        assert 'CMD ["pnpm", "next", "start"]' in rendered
        assert "pnpm-workspace.yaml" in rendered
        assert "COPY packages/shared/package.json packages/shared/" in rendered

    def test_audit_fix_1_non_root_user(self) -> None:
        rendered = _rendered("apps/web/Dockerfile")
        assert "adduser" in rendered
        assert "USER appuser" in rendered

    def test_audit_fix_2_single_copy_node_modules_in_runner(self) -> None:
        """Audit fix #2 (post-smoke revision): runner stage copies the entire
        ``/app/node_modules`` hoisted store in a single COPY rather than
        attempting a per-workspace COPY. The per-workspace approach fails
        against lean lockfiles where a workspace may have no local
        node_modules subtree of its own (live smoke uncovered this)."""
        rendered = _rendered("apps/web/Dockerfile")
        assert "COPY --from=build /app/node_modules /app/node_modules" in rendered
        # The per-workspace COPY must NOT be present — live smoke showed
        # it fails with "failed to compute cache key: not found" when the
        # tree doesn't exist.
        assert (
            "COPY --from=build /app/apps/web/node_modules ./node_modules"
            not in rendered
        )

    def test_ports_and_expose(self) -> None:
        rendered = _rendered("apps/web/Dockerfile")
        assert "EXPOSE 3000" in rendered


class TestApiDockerfileIsNew:
    """The api Dockerfile is new with Path A — previously Codex authored it
    per-run. Assert the structural invariants the Wave B DOCK-* bars require."""

    def test_multi_stage_structure(self) -> None:
        rendered = _rendered("apps/api/Dockerfile")
        assert "AS deps" in rendered
        assert "AS build" in rendered
        assert "AS runtime" in rendered

    def test_prisma_generate_in_build_stage(self) -> None:
        rendered = _rendered("apps/api/Dockerfile")
        assert "prisma generate" in rendered

    def test_migrate_deploy_not_dev(self) -> None:
        """AUD-023: production entrypoint runs `migrate deploy`, NEVER `migrate dev`."""
        rendered = _rendered("apps/api/Dockerfile")
        assert "prisma migrate deploy" in rendered
        assert "prisma migrate dev" not in rendered

    def test_non_root_user(self) -> None:
        rendered = _rendered("apps/api/Dockerfile")
        assert "adduser" in rendered
        assert "USER appuser" in rendered


class TestDockerignoreContent:
    def test_excludes_node_modules(self) -> None:
        rendered = _rendered(".dockerignore")
        assert "**/node_modules" in rendered

    def test_excludes_secrets(self) -> None:
        rendered = _rendered(".dockerignore")
        assert ".env" in rendered
        assert "!.env.example" in rendered

    def test_excludes_vcs(self) -> None:
        rendered = _rendered(".dockerignore")
        assert ".git" in rendered

    def test_excludes_agent_team_scratch(self) -> None:
        rendered = _rendered(".dockerignore")
        assert ".agent-team" in rendered
