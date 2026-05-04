"""Compile-check env readiness — smoke #8 regression.

Smoke #8 (``build-final-smoke-20260418-232245``) burned $10.72 on
5 failed Wave B compile-fix iterations. Wave B's source was
structurally clean ("``nest build`` exit 0" per the agent's own
log); the failure was in the compile-check harness environment:

  ``npx tsc --noEmit`` was invoked before ``pnpm install`` ran, so
  Windows' App Execution Alias stub for ``tsc.exe`` printed:

     :0 — This is not the tsc command you are looking for

  exiting with code 1. The compile-check harness parsed this as a
  real compile failure and the fix prompt looped up to the iteration
  cap.

Two complementary fixes tested here:

1. ``_WINDOWS_AEP_SENTINEL_RE`` (``compile_profiles.py``) catches
   the sentinel BEFORE the tsc-error parser runs and emits a
   dedicated ``ENV_NOT_READY`` code so the failure is legible.

2. ``_install_workspace_deps_if_needed`` (``wave_executor.py``) runs
   ``pnpm install`` (falls back to ``npm install``) after the
   scaffolder emits ``package.json``. Idempotent (skips when
   ``node_modules/`` already exists).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15.compile_profiles import (
    CompileProfile,
    _WINDOWS_AEP_SENTINEL_RE,
    run_wave_compile_check,
)
from agent_team_v15.wave_executor import _install_workspace_deps_if_needed


# ---------------------------------------------------------------------------
# AEP sentinel detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "output,expected",
    [
        (
            "This is not the tsc command you are looking for",
            True,
        ),
        (
            "               This is not the TSC command you are looking for\n"
            "\nTo get access to the TypeScript compiler, tsc, from the command line either:\n",
            True,
        ),
        # Other apps hitting the App Execution Alias.
        (
            "This is not the python command you are looking for",
            True,
        ),
        # Real tsc output must not trigger.
        (
            "apps/api/src/main.ts(5,10): error TS2304: Cannot find name 'foo'.",
            False,
        ),
        (
            "",
            False,
        ),
    ],
)
def test_aep_sentinel_regex(output: str, expected: bool) -> None:
    assert bool(_WINDOWS_AEP_SENTINEL_RE.search(output)) is expected


def test_compile_check_emits_env_not_ready_on_aep_output(tmp_path: Path) -> None:
    """When a compile command returns the Windows AEP placeholder,
    ``run_wave_compile_check`` must surface a single ``ENV_NOT_READY``
    error (not loop-inducing fallback errors) so the fix harness
    can distinguish "tsc is missing" from "tsc found errors"."""
    profile = CompileProfile(
        name="test_ts",
        commands=[["npx", "tsc", "--noEmit"]],
        description="test",
    )
    # Write a dummy project layout so the harness walks cleanly.
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")

    # Mock _run_command to return the AEP sentinel + non-zero exit.
    aep_output = (
        "                This is not the tsc command you are looking for\n"
        "\nTo get access to the TypeScript compiler, tsc, from the command line:\n"
    )

    async def fake_run_command(cmd, cwd, timeout=120):
        return (1, aep_output)

    with patch(
        "agent_team_v15.compile_profiles._run_command",
        side_effect=fake_run_command,
    ):
        result = asyncio.get_event_loop().run_until_complete(
            run_wave_compile_check(str(tmp_path), profile)
        ) if False else asyncio.run(run_wave_compile_check(str(tmp_path), profile))

    assert result.passed is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err["code"] == "ENV_NOT_READY"
    assert "pnpm install" in err["message"] or "npm install" in err["message"]


def test_compile_check_preserves_real_tsc_error_path(tmp_path: Path) -> None:
    """Sanity: real tsc error output (no AEP sentinel) goes through the
    normal parser, not the ENV_NOT_READY branch."""
    profile = CompileProfile(
        name="test_ts",
        commands=[["npx", "tsc", "--noEmit"]],
        description="test",
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")

    real_tsc = "apps/api/src/main.ts(5,10): error TS2304: Cannot find name 'foo'."

    async def fake_run_command(cmd, cwd, timeout=120):
        return (1, real_tsc)

    with patch(
        "agent_team_v15.compile_profiles._run_command",
        side_effect=fake_run_command,
    ):
        result = asyncio.run(run_wave_compile_check(str(tmp_path), profile))

    assert result.passed is False
    assert not any(e.get("code") == "ENV_NOT_READY" for e in result.errors)


# ---------------------------------------------------------------------------
# _install_workspace_deps_if_needed
# ---------------------------------------------------------------------------


def test_install_skips_when_node_modules_exists(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()

    with patch(
        "agent_team_v15.wave_executor.subprocess.run"
    ) as mock_run:
        _install_workspace_deps_if_needed(str(tmp_path))
        mock_run.assert_not_called()


def test_install_skips_when_no_package_json(tmp_path: Path) -> None:
    with patch(
        "agent_team_v15.wave_executor.subprocess.run"
    ) as mock_run:
        _install_workspace_deps_if_needed(str(tmp_path))
        mock_run.assert_not_called()


def test_install_prefers_pnpm_then_npm(tmp_path: Path) -> None:
    """When both pnpm and npm resolve, pnpm is tried first. If pnpm
    returns success, npm is never invoked."""
    (tmp_path / "package.json").write_text(
        '{"name": "taskflow", "private": true}', encoding="utf-8"
    )
    calls: list[str] = []

    def fake_which(cmd: str):
        if cmd in ("pnpm", "pnpm.cmd"):
            return "/fake/pnpm"
        if cmd in ("npm", "npm.cmd"):
            return "/fake/npm"
        return None

    def fake_run(cmd, **kwargs):
        calls.append(cmd[0])
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("agent_team_v15.wave_executor.shutil.which", side_effect=fake_which), \
         patch("agent_team_v15.wave_executor.subprocess.run", side_effect=fake_run):
        _install_workspace_deps_if_needed(str(tmp_path))

    assert calls == ["/fake/pnpm"], (
        f"Expected pnpm-only when pnpm succeeds; got {calls}"
    )


def test_install_falls_back_to_npm_on_pnpm_failure(tmp_path: Path) -> None:
    """Non-zero exit from pnpm must cascade to npm, not abort."""
    (tmp_path / "package.json").write_text(
        '{"name": "taskflow", "private": true}', encoding="utf-8"
    )
    calls: list[str] = []

    def fake_which(cmd: str):
        if cmd in ("pnpm", "pnpm.cmd"):
            return "/fake/pnpm"
        if cmd in ("npm", "npm.cmd"):
            return "/fake/npm"
        return None

    def fake_run(cmd, **kwargs):
        calls.append(cmd[0])
        if cmd[0] == "/fake/pnpm":
            return MagicMock(returncode=1, stdout="", stderr="pnpm: broken lockfile")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("agent_team_v15.wave_executor.shutil.which", side_effect=fake_which), \
         patch("agent_team_v15.wave_executor.subprocess.run", side_effect=fake_run):
        _install_workspace_deps_if_needed(str(tmp_path))

    assert calls == ["/fake/pnpm", "/fake/npm"], (
        f"Expected pnpm→npm cascade; got {calls}"
    )


def test_install_pnpm_workspace_uses_frozen_lockfile_without_npm_fallback(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name": "taskflow", "private": true, "packageManager": "pnpm@10.17.1"}',
        encoding="utf-8",
    )
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_which(cmd: str):
        if cmd in ("pnpm", "pnpm.cmd"):
            return "/fake/pnpm"
        if cmd in ("npm", "npm.cmd"):
            return "/fake/npm"
        return None

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("agent_team_v15.wave_executor.shutil.which", side_effect=fake_which), \
         patch("agent_team_v15.wave_executor.subprocess.run", side_effect=fake_run):
        _install_workspace_deps_if_needed(str(tmp_path))

    assert calls == [["/fake/pnpm", "install", "--frozen-lockfile"]]


def test_install_pnpm_workspace_force_relinks_after_wave_c_even_with_root_marker(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text(
        '{"name": "taskflow", "private": true, "packageManager": "pnpm@10.17.1"}',
        encoding="utf-8",
    )
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "packages:\n  - 'apps/*'\n  - 'packages/*'\n",
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / ".modules.yaml").write_text("layoutVersion: 5\n", encoding="utf-8")
    (tmp_path / "packages" / "api-client").mkdir(parents=True)
    (tmp_path / "packages" / "api-client" / "package.json").write_text(
        '{"name":"@taskflow/api-client","dependencies":{"@hey-api/client-fetch":"^0.8.0"}}',
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_which(cmd: str):
        if cmd in ("pnpm", "pnpm.cmd"):
            return "/fake/pnpm"
        return None

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("agent_team_v15.wave_executor.shutil.which", side_effect=fake_which), \
         patch("agent_team_v15.wave_executor.subprocess.run", side_effect=fake_run):
        _install_workspace_deps_if_needed(str(tmp_path), force=True)

    assert calls == [["/fake/pnpm", "install", "--frozen-lockfile"]]


def test_install_pnpm_workspace_missing_lockfile_raises(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name": "taskflow", "private": true, "packageManager": "pnpm@10.17.1"}',
        encoding="utf-8",
    )
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing pnpm-lock.yaml"):
        _install_workspace_deps_if_needed(str(tmp_path))


def test_install_swallows_timeout_and_continues(tmp_path: Path) -> None:
    """A timeout on pnpm must not abort the whole pipeline — caller
    catches the error, logs, and continues."""
    import subprocess

    (tmp_path / "package.json").write_text(
        '{"name": "taskflow", "private": true}', encoding="utf-8"
    )

    def fake_which(cmd: str):
        if cmd in ("pnpm", "pnpm.cmd"):
            return "/fake/pnpm"
        return None

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 600))

    with patch("agent_team_v15.wave_executor.shutil.which", side_effect=fake_which), \
         patch("agent_team_v15.wave_executor.subprocess.run", side_effect=fake_run):
        # Must not raise.
        _install_workspace_deps_if_needed(str(tmp_path))


def test_install_uses_absolute_cwd(tmp_path: Path, monkeypatch) -> None:
    """Mirror of PR #36 lesson — subprocess cwd must be absolute to
    avoid Windows path-doubling with relative inputs."""
    (tmp_path / "package.json").write_text(
        '{"name": "taskflow"}', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path.parent)
    relative_cwd = tmp_path.name  # relative string

    cwd_seen: list[str] = []

    def fake_which(cmd: str):
        if cmd in ("pnpm", "pnpm.cmd"):
            return "/fake/pnpm"
        return None

    def fake_run(cmd, **kwargs):
        cwd_seen.append(kwargs.get("cwd"))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("agent_team_v15.wave_executor.shutil.which", side_effect=fake_which), \
         patch("agent_team_v15.wave_executor.subprocess.run", side_effect=fake_run):
        _install_workspace_deps_if_needed(relative_cwd)

    assert cwd_seen, "subprocess.run was not invoked"
    import os as _os
    assert _os.path.isabs(cwd_seen[0]), (
        f"Install invoked with relative cwd={cwd_seen[0]!r} — relative "
        f"paths on Windows can cause path-doubling per PR #36."
    )
