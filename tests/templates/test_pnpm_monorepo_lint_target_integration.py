"""B6c Docker integration proof for the pnpm_monorepo lint target.

This test is intentionally not behind RUN_DOCKER_INTEGRATION_TESTS. It is the
load-bearing B6c regression proof: the scaffolded Compose service named
``api`` must read ``build.target: lint`` from docker-compose.yml, and
``docker compose build api`` must fail on a strict TypeScript error in a
``*.spec.ts`` file that ``tsconfig.build.json`` excludes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_team_v15.template_renderer import drop_template, render_template


pytestmark = pytest.mark.integration


def _command_available(command: str) -> bool:
    return shutil.which(command) is not None


def _docker_available() -> bool:
    if not _command_available("docker"):
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _run(cmd: list[str], cwd: Path, *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _write_strict_spec_workspace(root: Path) -> None:
    (root / ".npmrc").write_text("auto-install-peers=false\n", encoding="utf-8")
    (root / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'apps/*'\n  - 'packages/*'\n",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "b6c-lint-target-proof",
                "version": "0.0.0",
                "private": True,
                "packageManager": "pnpm@10.17.1",
                "devDependencies": {"typescript": "5.8.3"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "CommonJS",
                    "moduleResolution": "Node",
                    "strict": True,
                    "noEmit": True,
                    "skipLibCheck": True,
                },
                "include": ["apps/api/src/**/*.ts"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "tsconfig.build.json").write_text(
        json.dumps(
            {
                "extends": "./tsconfig.json",
                "exclude": ["**/*.spec.ts"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    api = root / "apps" / "api"
    api.mkdir(parents=True, exist_ok=True)
    (api / "package.json").write_text(
        json.dumps(
            {
                "name": "api",
                "version": "0.0.0",
                "private": True,
                "scripts": {
                    "build": "npx tsc --project ../../tsconfig.build.json",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (api / "src").mkdir(parents=True, exist_ok=True)
    (api / "src" / "main.ts").write_text("export const ok = 1;\n", encoding="utf-8")
    (api / "src" / "main.spec.ts").write_text(
        "const value: number = 'spec files must be checked';\n",
        encoding="utf-8",
    )

    web = root / "apps" / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "package.json").write_text(
        json.dumps(
            {
                "name": "web",
                "version": "0.0.0",
                "private": True,
                "scripts": {"build": "mkdir -p .next && echo built > .next/.b6c"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    for rel, package_name in (
        ("packages/shared", "shared"),
        ("packages/api-client", "@taskflow/api-client"),
    ):
        pkg = root / rel
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "package.json").write_text(
            json.dumps(
                {
                    "name": package_name,
                    "version": "0.0.0",
                    "private": True,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def test_compose_build_api_lint_target_fails_on_spec_type_error(tmp_path: Path) -> None:
    if not _docker_available():
        pytest.skip("Docker daemon not available")
    if not _command_available("pnpm"):
        pytest.skip("pnpm not available to generate the frozen lockfile")

    _write_strict_spec_workspace(tmp_path)
    lock = _run(["pnpm", "install", "--lockfile-only", "--ignore-scripts"], tmp_path, timeout=180)
    if lock.returncode != 0:
        pytest.fail(
            "pnpm lockfile generation failed.\n"
            f"stdout tail:\n{lock.stdout[-2000:]}\n"
            f"stderr tail:\n{lock.stderr[-2000:]}"
        )

    rendered = render_template("pnpm_monorepo")
    drop_template(rendered, tmp_path, overwrite=False)
    compose = (tmp_path / "docker-compose.yml").read_text(encoding="utf-8")
    assert "target: lint" in compose
    assert "--target" not in compose

    try:
        result = _run(
            ["docker", "compose", "build", "--progress=plain", "api"],
            cwd=tmp_path,
            timeout=600,
        )
        combined = f"{result.stdout}\n{result.stderr}"
        assert result.returncode != 0, "docker compose build api unexpectedly passed"
        assert "apps/api/src/main.spec.ts" in combined
        assert "TS2322" in combined

        from agent_team_v15.runtime_verification import docker_build
        from agent_team_v15.wave_b_self_verify import run_wave_b_acceptance_test

        build_results = docker_build(
            tmp_path,
            tmp_path / "docker-compose.yml",
            services=["api"],
            parallel=False,
        )
        assert len(build_results) == 1
        assert build_results[0].success is False
        assert "apps/api/src/main.spec.ts" in (build_results[0].error or "")
        assert "TS2322" in (build_results[0].error or "")

        wave_result = run_wave_b_acceptance_test(tmp_path, timeout_seconds=600)
        assert wave_result.passed is False
        assert any("apps/api/src/main.spec.ts" in item for item in wave_result.tsc_failures)
        assert any("TS2322" in item for item in wave_result.tsc_failures)
        assert "TS2322" in wave_result.retry_prompt_suffix
    finally:
        _run(
            ["docker", "compose", "down", "-v", "--rmi", "local"],
            cwd=tmp_path,
            timeout=120,
        )
