"""Opt-in Docker smoke: render the template + a minimal workspace shell,
then run ``docker compose build`` end-to-end.

This is the definitive check that our curated templates actually build.
Skipped by default — set ``RUN_DOCKER_INTEGRATION_TESTS=1`` in the
environment to opt in. Also requires a working Docker daemon + buildkit.

Usage:
    RUN_DOCKER_INTEGRATION_TESTS=1 PYTHONPATH=src \\
        pytest tests/templates/test_pnpm_monorepo_docker_build.py -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_team_v15.template_renderer import drop_template, render_template


_OPT_IN_ENV = "RUN_DOCKER_INTEGRATION_TESTS"


def _docker_available() -> bool:
    """True iff ``docker`` is on PATH and ``docker info`` succeeds."""
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def _opt_in_enabled() -> bool:
    return os.environ.get(_OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes"}


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _opt_in_enabled(),
        reason=f"opt-in only — set {_OPT_IN_ENV}=1 to run Docker smoke",
    ),
    pytest.mark.skipif(
        not _docker_available(),
        reason="Docker daemon not available",
    ),
]


# ---------------------------------------------------------------------------
# Minimal pnpm workspace shell — just enough files to satisfy the Dockerfiles.
# ---------------------------------------------------------------------------

def _write_workspace_shell(root: Path) -> None:
    """Populate ``root`` with a minimum-viable pnpm workspace that the
    curated Dockerfiles can successfully build against.

    The shell includes:
      - pnpm-workspace.yaml with apps/* + packages/* globs
      - root package.json
      - pnpm-lock.yaml (empty — `pnpm install --frozen-lockfile` accepts
        empty lockfiles when no deps are declared)
      - apps/api/package.json + src/main.ts + tsconfig.json
      - apps/web/package.json + next.config.js + src/app/page.tsx +
        public/.gitkeep
      - packages/shared/package.json + src/index.ts
    """

    (root / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'apps/*'\n  - 'packages/*'\n",
        encoding="utf-8",
    )

    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "smoke-test-root",
                "version": "0.0.0",
                "private": True,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    # Empty lockfile — pnpm will accept it because no deps are declared.
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    # --- apps/api ---
    api = root / "apps" / "api"
    api.mkdir(parents=True, exist_ok=True)
    (api / "package.json").write_text(
        json.dumps(
            {
                "name": "api",
                "version": "0.0.0",
                "private": True,
                "scripts": {
                    "build": "mkdir -p dist && cp src/main.ts dist/main.js",
                },
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    (api / "src").mkdir(parents=True, exist_ok=True)
    (api / "src" / "main.ts").write_text(
        "console.log('api smoke ok');\n", encoding="utf-8"
    )
    # Prisma schema is optional — the Dockerfile's `prisma generate` step
    # short-circuits when no schema is present. We omit it here to keep
    # the smoke fast.

    # --- apps/web ---
    web = root / "apps" / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "package.json").write_text(
        json.dumps(
            {
                "name": "web",
                "version": "0.0.0",
                "private": True,
                "scripts": {
                    # next is not installed (empty lockfile) so fake the build step.
                    "build": "mkdir -p .next && echo built > .next/.smoke",
                },
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    (web / "next.config.js").write_text(
        "module.exports = {};\n", encoding="utf-8"
    )
    public_dir = web / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    (public_dir / ".gitkeep").write_text("", encoding="utf-8")
    (web / "src" / "app").mkdir(parents=True, exist_ok=True)
    (web / "src" / "app" / "page.tsx").write_text(
        "export default function Home() { return <div>smoke</div>; }\n",
        encoding="utf-8",
    )

    # --- packages/shared ---
    shared = root / "packages" / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "package.json").write_text(
        json.dumps(
            {
                "name": "shared",
                "version": "0.0.0",
                "private": True,
                "main": "src/index.ts",
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    (shared / "src").mkdir(parents=True, exist_ok=True)
    (shared / "src" / "index.ts").write_text(
        "export const SMOKE = true;\n", encoding="utf-8"
    )


def _run(cmd: list[str], cwd: Path, *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


class TestPnpmMonorepoDockerBuild:
    """End-to-end Docker smoke for the curated pnpm_monorepo template.

    Caveats on this smoke (documented so reviewers understand what is and is
    NOT being verified):

    1. We render the curated templates (api + web Dockerfiles, compose,
       .dockerignore) and drop them into a minimal pnpm workspace shell.
    2. ``docker compose build`` is expected to exit 0. This exercises the
       full Dockerfile: workspace install, cached deps layer, build stage,
       runtime stage assembly, multi-stage COPY --from ordering.
    3. The smoke uses fake `build` scripts (`cp`, `mkdir`, `echo`) rather
       than real Next/NestJS builds — full production builds would pull
       megabytes of deps and take 5+ minutes per run, which is too slow
       for a smoke that may run in CI. The structural Dockerfile invariants
       (DOCK-001..DOCK-006) are what we actually test; real framework
       toolchain behavior is validated in the live R1B1+ calibration runs.
    """

    def test_docker_compose_build_exits_zero(self, tmp_path: Path) -> None:
        _write_workspace_shell(tmp_path)
        rendered = render_template("pnpm_monorepo")
        drop_template(rendered, tmp_path, overwrite=False)

        # Verify the 4 template files landed.
        assert (tmp_path / "docker-compose.yml").is_file()
        assert (tmp_path / "apps" / "api" / "Dockerfile").is_file()
        assert (tmp_path / "apps" / "web" / "Dockerfile").is_file()
        assert (tmp_path / ".dockerignore").is_file()

        try:
            # `docker compose build` (not `docker-compose build` — v1 is EOL).
            result = _run(
                ["docker", "compose", "build", "--progress=plain"],
                cwd=tmp_path,
            )
            if result.returncode != 0:
                pytest.fail(
                    "docker compose build exited nonzero.\n"
                    f"stdout tail:\n{result.stdout[-2000:]}\n"
                    f"stderr tail:\n{result.stderr[-2000:]}\n"
                )
        finally:
            # Always tear down — `docker compose down -v` removes the
            # postgres volume too so repeat runs start fresh.
            _run(
                ["docker", "compose", "down", "-v", "--rmi", "local"],
                cwd=tmp_path,
                timeout=120,
            )
