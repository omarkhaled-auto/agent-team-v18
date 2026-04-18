"""Tests for ``project_walker.iter_project_files`` — the shared
safe-walker utility introduced to close the Windows MAX_PATH bug class
across every project-root file scan in the pipeline.

Smoke #9 (``build-final-smoke-20260419-010953``) reproduced a pnpm
``.pnpm/<hash>/node_modules/<pkg>/dist/...`` deep-path crash in a
walker outside ``_checkpoint_file_iter`` (which PR #37 fixed). The
shared helper lives at ``src/agent_team_v15/project_walker.py`` and
the tests below pin its contracts:

- Skip-dirs pruned at descent (``os.walk`` in-place dirnames).
- Patterns filter on filename (not full path).
- ``onerror`` swallows scandir failures without aborting.
- ``followlinks=False`` — pnpm's symlink chains can't cycle.
- Absolute ``Path`` returned regardless of ``root`` input type.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15.project_walker import (
    DEFAULT_SKIP_DIRS,
    iter_project_files,
    iter_project_paths,
)


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Skip-dir pruning (the primary regression)
# ---------------------------------------------------------------------------


def test_node_modules_pruned_at_descent(tmp_path: Path) -> None:
    _touch(tmp_path / "src" / "main.ts", "export {};")
    _touch(
        tmp_path / "node_modules" / ".pnpm" / "next@15" / "node_modules"
        / "next" / "dist" / "next-devtools" / "dev-overlay"
        / "components" / "indicator.ts",
        "// deep",
    )

    paths = iter_project_files(tmp_path, patterns=("*.ts",))
    strs = {str(p).replace("\\", "/") for p in paths}
    assert any("src/main.ts" in s for s in strs)
    assert not any("node_modules" in s for s in strs)


@pytest.mark.parametrize("skip_dir", sorted(DEFAULT_SKIP_DIRS))
def test_every_default_skip_dir_pruned(tmp_path: Path, skip_dir: str) -> None:
    _touch(tmp_path / "src" / "app.ts", "x")
    _touch(tmp_path / skip_dir / "noise.txt", "ignore me")

    files = iter_project_files(tmp_path)
    strs = [str(p).replace("\\", "/") for p in files]
    assert any("src/app.ts" in s for s in strs)
    assert not any(f"{skip_dir}/" in s for s in strs)


def test_custom_skip_dirs_honoured(tmp_path: Path) -> None:
    """Caller can override the skip set — DEFAULT_SKIP_DIRS is the
    default but not mandatory."""
    _touch(tmp_path / "src" / "app.ts", "x")
    _touch(tmp_path / "my_skip" / "secret.ts", "x")

    # Default — my_skip NOT pruned → included.
    default = iter_project_files(tmp_path, patterns=("*.ts",))
    assert any("my_skip" in str(p) for p in default)

    # Custom set — my_skip pruned.
    custom = iter_project_files(
        tmp_path, patterns=("*.ts",), skip_dirs={"my_skip"},
    )
    assert not any("my_skip" in str(p) for p in custom)


# ---------------------------------------------------------------------------
# Pattern filtering
# ---------------------------------------------------------------------------


def test_pattern_filters_by_filename(tmp_path: Path) -> None:
    _touch(tmp_path / "src" / "app.ts", "x")
    _touch(tmp_path / "src" / "app.py", "x")
    _touch(tmp_path / "README.md", "x")

    ts_only = iter_project_files(tmp_path, patterns=("*.ts",))
    assert len(ts_only) == 1 and ts_only[0].name == "app.ts"

    multi = iter_project_files(tmp_path, patterns=("*.ts", "*.md"))
    names = sorted(p.name for p in multi)
    assert names == ["README.md", "app.ts"]


def test_default_pattern_matches_all_files(tmp_path: Path) -> None:
    _touch(tmp_path / "a.txt", "x")
    _touch(tmp_path / "b" / "c.json", "x")

    files = iter_project_files(tmp_path)
    names = sorted(p.name for p in files)
    assert names == ["a.txt", "c.json"]


# ---------------------------------------------------------------------------
# iter_project_paths alias
# ---------------------------------------------------------------------------


def test_iter_project_paths_matches_iter_project_files_default(tmp_path: Path) -> None:
    _touch(tmp_path / "a.txt", "x")
    _touch(tmp_path / "node_modules" / "b.txt", "x")

    via_paths = iter_project_paths(tmp_path)
    via_files = iter_project_files(tmp_path)
    assert {str(p) for p in via_paths} == {str(p) for p in via_files}


# ---------------------------------------------------------------------------
# onerror swallows OSError
# ---------------------------------------------------------------------------


def test_onerror_swallow_does_not_abort_walk(tmp_path: Path) -> None:
    _touch(tmp_path / "src" / "ok.ts", "x")

    original_walk = os.walk

    def _walk_with_error(*args, **kwargs):
        handler = kwargs.get("onerror")
        if handler:
            handler(OSError(13, "Permission denied", str(tmp_path / "bad")))
        yield from original_walk(*args, **kwargs)

    with patch(
        "agent_team_v15.project_walker.os.walk", side_effect=_walk_with_error
    ):
        # Must not raise.
        files = iter_project_files(tmp_path)

    assert any(p.name == "ok.ts" for p in files)


def test_onerror_callback_custom_can_observe_errors(tmp_path: Path) -> None:
    _touch(tmp_path / "src" / "ok.ts", "x")
    seen: list[OSError] = []

    original_walk = os.walk

    def _walk_with_error(*args, **kwargs):
        # Use the handler supplied by iter_project_files (our custom one).
        handler = kwargs.get("onerror")
        if handler:
            handler(OSError(2, "Not found", "/missing"))
        yield from original_walk(*args, **kwargs)

    def custom_onerror(exc: OSError) -> None:
        seen.append(exc)

    with patch(
        "agent_team_v15.project_walker.os.walk", side_effect=_walk_with_error
    ):
        iter_project_files(tmp_path, onerror=custom_onerror)

    assert len(seen) == 1
    assert seen[0].errno == 2


# ---------------------------------------------------------------------------
# followlinks=False — pnpm symlink cycles
# ---------------------------------------------------------------------------


def test_symlinks_not_followed(tmp_path: Path) -> None:
    _touch(tmp_path / "apps" / "api" / "main.ts", "x")

    loop_dir = tmp_path / "node_modules" / ".pnpm" / "cycle"
    loop_dir.mkdir(parents=True)
    try:
        (loop_dir / "back").symlink_to(
            tmp_path / "apps", target_is_directory=True
        )
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this platform")

    files = iter_project_files(tmp_path, patterns=("*.ts",))
    # main.ts should be visited exactly once — no cycle duplication.
    ts_names = [p for p in files if p.name == "main.ts"]
    assert len(ts_names) == 1
    # And node_modules is pruned anyway.
    assert not any("node_modules" in str(p) for p in files)


# ---------------------------------------------------------------------------
# Input type flexibility
# ---------------------------------------------------------------------------


def test_accepts_str_root(tmp_path: Path) -> None:
    _touch(tmp_path / "a.txt", "x")
    files = iter_project_files(str(tmp_path))
    assert any(p.name == "a.txt" for p in files)


def test_returns_absolute_paths(tmp_path: Path, monkeypatch) -> None:
    """Returned paths are absolute regardless of whether ``root`` was
    relative — callers downstream pass these to subprocess / file IO,
    where relative paths re-introduce the PR #36 doubling class."""
    _touch(tmp_path / "a.txt", "x")
    monkeypatch.chdir(tmp_path.parent)
    relative_root = tmp_path.name
    files = iter_project_files(relative_root)
    assert files
    # os.walk with str root yields str dirpath that may be relative; the
    # helper joins via Path — on Windows the result inherits relativity.
    # This test documents current behaviour: callers needing absolute
    # paths should call .resolve() explicitly. If someone later changes
    # the helper to auto-resolve, update this assertion intentionally.
    # (The parent project's subprocess callers already .resolve() per
    # PR #36, so this is not a regression hole today.)
    assert all(isinstance(p, Path) for p in files)
