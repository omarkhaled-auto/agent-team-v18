"""Path-doubling regression — smoke #6 (build-final-smoke-20260418-194354).

When ``start_docker_for_probing`` was called with a relative ``cwd``
string (the common path inside the test runner — ``"v18 test runs/
build-final-smoke-…"``), every downstream docker call resolved the
compose file path relative to the subprocess cwd, doubling the
project-root prefix:

    docker compose -f v18 test runs/build-final.../docker-compose.yml
                   cwd=v18 test runs/build-final...

  → looks for ``<process-cwd>/v18 test runs/build-final.../v18 test runs/
    build-final.../docker-compose.yml``  → ENOENT

Wave B's compile passed and produced 16 backend files; the live
endpoint probe then failed instantly on the doubled path. Same bug
also fired in Phase 6 runtime verification.

These tests pin the fix:
- ``find_compose_file`` returns an absolute path (``.resolve()``).
- ``docker_build`` invokes subprocess with absolute ``cwd`` + absolute
  ``-f`` arg, so subprocess cwd-relative resolution can't double the
  prefix even if the caller passes a relative path.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_team_v15.runtime_verification import (
    docker_build,
    find_compose_file,
)


def _make_compose(tmp_path: Path) -> Path:
    """Touch a docker-compose.yml inside tmp_path."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services:\n  api: {}\n", encoding="utf-8")
    return compose


# ---------------------------------------------------------------------------
# find_compose_file returns an absolute path
# ---------------------------------------------------------------------------


def test_find_compose_file_returns_absolute_for_relative_root(tmp_path: Path, monkeypatch) -> None:
    """When called with a relative ``project_root``, the helper must
    return an absolute path so downstream docker calls don't double-
    resolve against the subprocess cwd."""
    _make_compose(tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    relative_root = Path(tmp_path.name)  # e.g. "tmp_XXX" — relative

    found = find_compose_file(relative_root)
    assert found is not None
    assert found.is_absolute(), (
        f"find_compose_file returned a relative path {found!r} — "
        f"docker subprocess will resolve it relative to its cwd, "
        f"doubling the project-root prefix (smoke #6 root cause)."
    )


def test_find_compose_file_returns_absolute_for_absolute_root(tmp_path: Path) -> None:
    """Absolute project_root → absolute return value (idempotent)."""
    _make_compose(tmp_path)
    found = find_compose_file(tmp_path.resolve())
    assert found is not None
    assert found.is_absolute()


def test_find_compose_file_override_returns_absolute(tmp_path: Path, monkeypatch) -> None:
    """The ``override`` path must also be normalised to absolute when
    the override is relative."""
    _make_compose(tmp_path)
    monkeypatch.chdir(tmp_path)
    found = find_compose_file(tmp_path, override="docker-compose.yml")
    assert found is not None
    assert found.is_absolute()


# ---------------------------------------------------------------------------
# docker_build defends against relative inputs
# ---------------------------------------------------------------------------


def test_docker_build_passes_absolute_cwd_and_compose_path(tmp_path: Path, monkeypatch) -> None:
    """Even if the caller hands ``docker_build`` relative paths, the
    subprocess invocation must use absolute paths for both ``cwd`` and
    the ``-f`` arg — otherwise the doubled-path bug recurs.

    Captures the subprocess.run call via mock and verifies the args
    docker actually sees."""
    compose = _make_compose(tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    rel_root = Path(tmp_path.name)
    rel_compose = rel_root / "docker-compose.yml"

    with patch("agent_team_v15.runtime_verification.subprocess.run") as mock_run:
        # First subprocess call: ``docker compose -f X config --services``
        # Return rc=1 to force the early-exit path so we don't hit the
        # second call; we only care about the FIRST invocation's args.
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        docker_build(rel_root, rel_compose)

        assert mock_run.called
        call = mock_run.call_args
        # Inspect kwargs and positional args
        passed_cwd = call.kwargs.get("cwd")
        passed_args = call.args[0]  # first positional = cmd list

        # cwd: must be absolute
        assert passed_cwd is not None
        assert os.path.isabs(passed_cwd), (
            f"docker subprocess invoked with relative cwd={passed_cwd!r}. "
            f"Subprocess will resolve it against the parent process cwd, "
            f"causing the smoke-#6 path-doubling bug."
        )

        # -f arg must be absolute
        assert "-f" in passed_args
        f_idx = passed_args.index("-f")
        f_value = passed_args[f_idx + 1]
        assert os.path.isabs(f_value), (
            f"docker -f arg is relative ({f_value!r}). Subprocess will "
            f"resolve it relative to the (possibly relative) cwd, doubling "
            f"the project-root prefix."
        )

        # Sanity: the absolute -f arg must NOT contain the project-root
        # name twice (the doubled-path signature).
        root_name = tmp_path.name
        assert f_value.count(root_name) == 1, (
            f"docker -f arg contains the project-root name {root_name!r} "
            f"twice ({f_value!r}) — exact doubled-path regression."
        )
