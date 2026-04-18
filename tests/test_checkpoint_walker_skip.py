"""Regression: ``_checkpoint_file_iter`` must never descend into skip-dirs.

Smoke #7 (``build-final-smoke-20260418-221709``) crashed with
``WinError 3`` when the walker hit ``node_modules/.pnpm/…/next-devtools/
dev-overlay/components/errors/dev-tools-indicator/dev-tools-info`` —
a pnpm symlink chain that exceeded Windows MAX_PATH (260 chars). The
previous ``Path.rglob('*')`` implementation descended eagerly; the
post-filter ``if any(part in _DEFAULT_SKIP_DIRS ...)`` could not stop
rglob from raising inside ``node_modules``. Wave B had completed
successfully (111 files in ``apps/``, ``nest build`` exit 0); the
next pipeline step that took a checkpoint aborted the whole milestone.

The fix switches to ``os.walk`` with in-place ``dirnames`` pruning so
skip-dirs are NEVER entered. These tests pin:

1. A synthetic ``node_modules/`` sub-tree with a very long path is
   fully skipped (walker never raises, no file returned from inside).
2. ``node_modules`` at any depth is skipped, not just the top level.
3. Other skip-dirs (``.git``, ``.next``, ``build``, ``dist``,
   ``.venv``, ``__pycache__``, ``.agent-team``) are also skipped.
4. Files outside skip-dirs are still included.
5. Unreadable directories (simulated via ``onerror``) don't abort
   the walk.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15.wave_executor import (
    _DEFAULT_SKIP_DIRS,
    _checkpoint_file_iter,
)


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# node_modules skipped — primary regression
# ---------------------------------------------------------------------------


def test_node_modules_not_walked_into(tmp_path: Path) -> None:
    _touch(tmp_path / "src" / "main.ts", "export const x = 1;\n")
    _touch(
        tmp_path / "node_modules" / "next" / "dist" / "index.js",
        "// deep dep",
    )
    _touch(
        tmp_path / "node_modules" / ".pnpm" / "next-intl@3.26" / "node_modules"
        / "next" / "dist" / "next-devtools" / "dev-overlay" / "components"
        / "errors" / "indicator.ts",
        "// very deep path",
    )

    files = _checkpoint_file_iter(tmp_path)
    file_strs = {str(f).replace("\\", "/") for f in files}
    assert any("src/main.ts" in s for s in file_strs)
    # Every returned path must be outside node_modules.
    assert not any("node_modules" in s for s in file_strs), (
        f"Files from inside node_modules leaked into the walk: "
        f"{[s for s in file_strs if 'node_modules' in s]}"
    )


def test_nested_node_modules_skipped_at_any_depth(tmp_path: Path) -> None:
    """pnpm symlinks nested workspace ``node_modules/`` inside
    ``node_modules/.pnpm/<hash>/``. Prune must engage at every level."""
    _touch(tmp_path / "apps" / "api" / "src" / "main.ts", "x")
    _touch(
        tmp_path / "apps" / "api" / "node_modules" / "nest" / "dist" / "x.js",
        "deep",
    )

    files = _checkpoint_file_iter(tmp_path)
    file_strs = [str(f).replace("\\", "/") for f in files]
    assert any("main.ts" in s for s in file_strs)
    assert not any("node_modules" in s for s in file_strs)


# ---------------------------------------------------------------------------
# All configured skip-dirs honoured
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skip_dir", sorted(_DEFAULT_SKIP_DIRS))
def test_every_skip_dir_pruned(tmp_path: Path, skip_dir: str) -> None:
    _touch(tmp_path / "src" / "app.ts", "x")
    _touch(tmp_path / skip_dir / "noisy.txt", "should skip")

    files = _checkpoint_file_iter(tmp_path)
    file_strs = [str(f).replace("\\", "/") for f in files]
    assert any("src/app.ts" in s for s in file_strs)
    assert not any(skip_dir + "/" in s for s in file_strs), (
        f"{skip_dir} content included in walk: "
        f"{[s for s in file_strs if skip_dir + '/' in s]}"
    )


# ---------------------------------------------------------------------------
# Defensive: onerror swallowing
# ---------------------------------------------------------------------------


def test_scandir_error_does_not_abort_walk(tmp_path: Path) -> None:
    """Simulate a subprocess where ``os.walk`` hands an OSError to
    ``onerror`` mid-walk (e.g. permission denied on one subtree). The
    walker must keep going — previously rglob raised immediately."""
    _touch(tmp_path / "src" / "ok.ts", "x")
    _touch(tmp_path / "bad" / "inaccessible.txt", "y")

    original_walk = os.walk

    def _walk_with_error(*args, **kwargs):  # type: ignore[no-untyped-def]
        # Synthesise an onerror event: simulate scandir raising on one
        # directory while the rest of the walk proceeds normally.
        onerror = kwargs.get("onerror")
        if onerror:
            onerror(OSError(13, "Permission denied", str(tmp_path / "bad")))
        yield from original_walk(*args, **kwargs)

    with patch("agent_team_v15.wave_executor.os.walk", side_effect=_walk_with_error):
        # Should not raise.
        files = _checkpoint_file_iter(tmp_path)

    file_strs = [str(f).replace("\\", "/") for f in files]
    assert any("src/ok.ts" in s for s in file_strs)


# ---------------------------------------------------------------------------
# Follow-links=False: symlink cycles can't stall the walker
# ---------------------------------------------------------------------------


def test_symlinks_not_followed(tmp_path: Path) -> None:
    """pnpm's ``node_modules/.pnpm/`` contains symlinks back into
    sibling workspace dirs, which can create cycles. Walker must NOT
    follow symlinks — ``followlinks=False`` guards against infinite
    recursion and MAX_PATH blow-up."""
    # Setup: a target outside node_modules (to confirm walker visits it
    # without following a symlink *into* it).
    _touch(tmp_path / "apps" / "api" / "src" / "main.ts", "x")

    # Create a symlink inside a skip-dir pointing back to apps/api.
    # (On Windows without admin, symlinks may fail — skip gracefully.)
    link_dir = tmp_path / "node_modules" / ".pnpm" / "loop"
    link_dir.mkdir(parents=True)
    try:
        (link_dir / "back-to-apps").symlink_to(
            tmp_path / "apps", target_is_directory=True
        )
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this platform")

    files = _checkpoint_file_iter(tmp_path)
    file_strs = [str(f).replace("\\", "/") for f in files]
    # main.ts should be visited exactly once (via the direct path,
    # not via the symlink chain).
    main_matches = [s for s in file_strs if "main.ts" in s]
    assert len(main_matches) == 1
    # The symlinked path under node_modules must not appear.
    assert not any("node_modules" in s for s in file_strs)
