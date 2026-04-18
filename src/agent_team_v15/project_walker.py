"""Safe project-tree walker that prunes skip-dirs at descent.

Central implementation of the ``os.walk`` + in-place ``dirnames``
mutation pattern used by ``_checkpoint_file_iter`` (wave_executor,
fixed in PR #37) and ``codebase_map``. Every caller that walks a
project root must use this helper so Windows MAX_PATH violations
inside ``node_modules/.pnpm/<hash>/node_modules/<pkg>/dist/…`` (pnpm
symlinks exceeding the 260-char limit) cannot abort the run.

``Path.rglob('*')`` descends eagerly — any post-filter (``if
'node_modules' in path.parts: continue``) runs only *after* the
generator has already tried to scandir into the skip-dir. On Windows,
scanning inside pnpm's nested ``.pnpm/`` symlink tree raises
``[WinError 3] The system cannot find the path specified`` mid-
iteration, killing the entire milestone (smokes #7 and #9 both died
this way in different callers).

Usage::

    from .project_walker import iter_project_files

    # Simple: every file, skip-dirs pruned at descent.
    for path in iter_project_files(project_root):
        process(path)

    # Pattern-filtered:
    for path in iter_project_files(project_root, patterns=("*.ts", "*.tsx")):
        process(path)

The ``onerror`` hook swallows transient per-directory failures
(permission denied, broken symlink, any residual MAX_PATH hit that
slipped through the prune) so a single unreadable subtree cannot abort
the whole walk.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Callable, Iterable

_logger = logging.getLogger(__name__)


DEFAULT_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".agent-team",
        ".git",
        ".next",
        ".venv",
        ".vs",
        "__pycache__",
        "bin",
        "build",
        "dist",
        "node_modules",
        "obj",
        "out",
        "target",
    }
)


def iter_project_files(
    root: Path | str,
    patterns: Iterable[str] = ("*",),
    skip_dirs: Iterable[str] = DEFAULT_SKIP_DIRS,
    *,
    onerror: Callable[[OSError], None] | None = None,
) -> list[Path]:
    """Walk *root* safely, returning files matching any of *patterns*.

    Parameters
    ----------
    root:
        Project tree root. Accepts ``Path`` or str.
    patterns:
        fnmatch glob(s) matched against the file name (not the path).
        Defaults to ``("*",)`` — every file.
    skip_dirs:
        Directory names pruned at descent. Defaults to
        ``DEFAULT_SKIP_DIRS`` (includes ``node_modules``).
    onerror:
        Optional handler for per-directory scandir failures. Defaults
        to a logger-based swallow so a single bad subtree cannot abort
        the walk.

    Returns
    -------
    list[Path]
        Absolute ``Path`` objects for every matched file.
    """
    patterns_list = [p for p in patterns]
    skip_set = set(skip_dirs)

    def _default_on_error(exc: OSError) -> None:
        _logger.debug(
            "iter_project_files: skipping %s: %s",
            getattr(exc, "filename", ""),
            exc,
        )

    results: list[Path] = []
    walk_onerror = onerror or _default_on_error

    for dirpath, dirnames, filenames in os.walk(
        str(root), topdown=True, onerror=walk_onerror, followlinks=False,
    ):
        # In-place prune MUST happen before files are yielded so os.walk
        # won't descend into skip_dirs.
        dirnames[:] = [d for d in dirnames if d not in skip_set]

        if patterns_list == ["*"]:
            for filename in filenames:
                results.append(Path(dirpath) / filename)
        else:
            for filename in filenames:
                if any(fnmatch.fnmatch(filename, pat) for pat in patterns_list):
                    results.append(Path(dirpath) / filename)
    return results


def iter_project_paths(
    root: Path | str,
    skip_dirs: Iterable[str] = DEFAULT_SKIP_DIRS,
    *,
    onerror: Callable[[OSError], None] | None = None,
) -> list[Path]:
    """Walk *root* safely, returning every file (no pattern filter).

    Convenience alias for ``iter_project_files(root, ("*",), skip_dirs)``.
    Preferred when the caller wants the full file set for
    checkpointing or content hashing.
    """
    return iter_project_files(root, ("*",), skip_dirs, onerror=onerror)


__all__ = [
    "DEFAULT_SKIP_DIRS",
    "iter_project_files",
    "iter_project_paths",
]
