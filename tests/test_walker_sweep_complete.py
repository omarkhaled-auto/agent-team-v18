"""Structural invariant: no project-root walker may use unsafe patterns.

This test enforces the migration completed across PRs #37, #39, #40, and
the final sweep branch ``phase-final-sweep-walkers-v2``. It greps
``src/agent_team_v15/`` for the two Windows-MAX-PATH-unsafe patterns:

- ``Path.rglob(...)``  — descends eagerly before any post-filter runs.
- ``Path.glob("**/...")`` — same eager descent.

On Windows, pnpm's ``node_modules/.pnpm/<hash>/node_modules/<pkg>/dist/
next-devtools/...`` symlink trees exceed the 260-char MAX_PATH limit.
``Path.rglob`` raises ``[WinError 3]`` mid-iteration before any
``if 'node_modules' in path.parts`` post-filter can engage — killing
the entire milestone. The fix is ``agent_team_v15.project_walker.
iter_project_files``, which uses ``os.walk(topdown=True)`` with
in-place ``dirnames`` mutation so skip-dirs are pruned at descent.

Known-safe exceptions are enumerated explicitly below so future readers
see the reasoning. Each exception has a ``# Safe:`` comment on the
immediate preceding or trailing line pointing at the directory guarantee
(e.g., ``.agent-team/`` orchestration subtree that cannot contain
``node_modules``, or documentation strings quoting the anti-pattern).

If this test fails, someone reintroduced the anti-pattern. Fix it by
migrating to ``iter_project_files`` — never silence the test.
"""

from __future__ import annotations

import re
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15"

# Regex for the two unsafe walker forms.
_RE_RGLOB = re.compile(r"\.rglob\(")
# Path.glob("**/…") — starts a ``**`` inside the glob string. Matches
# ``glob("**/x")`` and ``glob(f"**/x")``; does NOT match single-level
# ``glob("*.py")`` which Path.glob handles without recursion.
_RE_GLOB_DOUBLESTAR = re.compile(r"""\.glob\(\s*f?["'][^"']*\*\*""")


# ---------------------------------------------------------------------------
# Allow-list: each entry is (filename, line_number, reason).
#
# A line is allowed only when ALL of the following hold:
#   1. It appears in the allow-list exactly (file + line).
#   2. The surrounding context makes the walker safe — either because
#      the walked directory cannot contain ``node_modules`` (e.g.,
#      ``.agent-team/`` orchestration-only subtree, source-only sub-dirs
#      like ``apps/api/src/prisma/`` where pnpm never places its tree)
#      OR because the text is a documentation comment / docstring
#      quoting the anti-pattern for future readers.
#
# Drift between the allow-list and the source of truth is a bug — if
# someone renames a function or moves a line, update the allow-list in
# the same commit. Never widen it to silence failures.
# ---------------------------------------------------------------------------

_ALLOWED_RGLOB: tuple[tuple[str, int, str], ...] = (
    (
        "codebase_map.py",
        242,
        "Documentation string quoting Path.rglob() as the anti-pattern "
        "this function intentionally avoids.",
    ),
    (
        "cli.py",
        13617,
        "Safe: req_dir_path is .agent-team/ — orchestration-only "
        "directory with no node_modules; no pnpm MAX_PATH risk.",
    ),
    (
        "endpoint_prober.py",
        2112,
        "Safe: apps/api/src/integrations/ is a source sub-directory — "
        "pnpm places node_modules at apps/api/node_modules/, never "
        "inside src/.",
    ),
    (
        "milestone_manager.py",
        1373,
        "Safe: entry is .agent-team/milestone-N/ — orchestration-only "
        "directory with no node_modules; no pnpm MAX_PATH risk.",
    ),
    (
        "project_walker.py",
        10,
        "Module docstring quoting Path.rglob('*') as the anti-pattern "
        "the helper exists to replace.",
    ),
    (
        "wave_executor.py",
        327,
        "Docstring for _checkpoint_file_iter explaining the historical "
        "Path.rglob('*') bug fixed by os.walk + dirnames pruning.",
    ),
    (
        "wave_executor.py",
        1318,
        "Safe: stale_dir is apps/api/src/prisma/ — source sub-directory "
        "where pnpm never places node_modules.",
    ),
)

# ``.glob("**/...")`` — documentation-only exceptions.
_ALLOWED_GLOB_DOUBLESTAR: tuple[tuple[str, int, str], ...] = (
    (
        "agents.py",
        7683,
        "Comment quoting Path.glob('apps/web/**/*.tsx') as the "
        "anti-pattern the migrated _find_existing_relative_paths "
        "helper now avoids.",
    ),
)


def _scan_directory(
    pattern: re.Pattern[str],
) -> list[tuple[str, int, str]]:
    """Return every (relative_filename, line_number, line_text) match."""
    matches: list[tuple[str, int, str]] = []
    for py_file in sorted(SRC_ROOT.glob("*.py")):
        try:
            text = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                matches.append((py_file.name, idx, line.rstrip()))
    return matches


def _render_diff(
    found: list[tuple[str, int, str]],
    allow: tuple[tuple[str, int, str], ...],
) -> str:
    """Build a diff-style diagnostic when the invariant fails."""
    allow_set = {(f, ln) for f, ln, _ in allow}
    found_set = {(f, ln) for f, ln, _ in found}
    extra = [m for m in found if (m[0], m[1]) not in allow_set]
    missing = [m for m in allow if (m[0], m[1]) not in found_set]
    lines: list[str] = []
    if extra:
        lines.append("UNEXPECTED unsafe walker(s) — migrate to iter_project_files:")
        for filename, line_no, text in extra:
            lines.append(f"  {filename}:{line_no}: {text.strip()}")
    if missing:
        lines.append(
            "Allow-list entries with no matching code — remove stale "
            "allow-list rows after deleting / moving the code:"
        )
        for filename, line_no, reason in missing:
            lines.append(f"  {filename}:{line_no}: {reason}")
    return "\n".join(lines)


def test_no_unsafe_rglob_in_agent_team_v15() -> None:
    """Every ``Path.rglob(...)`` must migrate unless allow-listed.

    This is a structural invariant — it catches anyone reintroducing the
    eager-descent anti-pattern that crashed smokes #7 and #9 on Windows.
    """
    found = _scan_directory(_RE_RGLOB)
    allow_set = {(f, ln) for f, ln, _ in _ALLOWED_RGLOB}
    unexpected = [m for m in found if (m[0], m[1]) not in allow_set]
    stale = [
        entry
        for entry in _ALLOWED_RGLOB
        if (entry[0], entry[1]) not in {(f, ln) for f, ln, _ in found}
    ]
    if unexpected or stale:
        raise AssertionError(
            "Walker-sweep invariant violated:\n"
            + _render_diff(found, _ALLOWED_RGLOB)
            + "\n\nSee src/agent_team_v15/project_walker.py for the "
              "canonical iter_project_files helper."
        )


def test_no_unsafe_glob_doublestar_in_agent_team_v15() -> None:
    """Every ``Path.glob("**/...")`` must migrate unless allow-listed.

    ``Path.glob("**/…")`` uses the same eager-descent engine as rglob —
    the ``**`` descends into ``node_modules/.pnpm/<hash>/...`` before
    any post-filter can prune, raising ``[WinError 3]`` on Windows.
    """
    found = _scan_directory(_RE_GLOB_DOUBLESTAR)
    allow_set = {(f, ln) for f, ln, _ in _ALLOWED_GLOB_DOUBLESTAR}
    unexpected = [m for m in found if (m[0], m[1]) not in allow_set]
    stale = [
        entry
        for entry in _ALLOWED_GLOB_DOUBLESTAR
        if (entry[0], entry[1]) not in {(f, ln) for f, ln, _ in found}
    ]
    if unexpected or stale:
        raise AssertionError(
            "Walker-sweep invariant violated:\n"
            + _render_diff(found, _ALLOWED_GLOB_DOUBLESTAR)
            + "\n\nSee src/agent_team_v15/project_walker.py for the "
              "canonical iter_project_files helper."
        )


def test_allow_list_entries_have_safety_comment_or_docstring() -> None:
    """Each allow-listed site must have a Safe: comment or live in a docstring.

    Guards against silently accepting an unsafe site by adding it to the
    allow-list — every allow-list entry must carry its justification in
    the source so a reviewer can verify the claim.
    """
    failures: list[str] = []
    for filename, line_no, reason in (*_ALLOWED_RGLOB, *_ALLOWED_GLOB_DOUBLESTAR):
        path = SRC_ROOT / filename
        text = path.read_text(encoding="utf-8").splitlines()
        # Search a small window above the hit line for either a
        # ``# Safe:`` comment, the string ``"""`` (docstring context), or
        # a direct reference to Path.rglob / Path.glob in the line
        # itself — those are the documentation-only references.
        window_start = max(0, line_no - 8)
        window = "\n".join(text[window_start:line_no])
        line_text = text[line_no - 1] if line_no <= len(text) else ""
        has_safe_comment = "# Safe:" in window or "# Safe:" in line_text
        in_docstring = '"""' in window
        is_pattern_comment = (
            line_text.lstrip().startswith("#")
            and ("Path.rglob" in line_text or "Path.glob" in line_text
                 or "rglob" in line_text or "glob(" in line_text)
        )
        mentions_pattern_in_text = (
            "Path.rglob" in line_text
            or "Path.glob" in line_text
            or "rglob" in line_text
        )
        if not (has_safe_comment or in_docstring or is_pattern_comment or mentions_pattern_in_text):
            failures.append(
                f"{filename}:{line_no} — allow-list says "
                f"{reason!r} but no '# Safe:' comment, docstring, or "
                f"anti-pattern-quoting comment found within 8 lines "
                f"above the walker call."
            )
    if failures:
        raise AssertionError(
            "Allow-list entries missing in-source justification:\n"
            + "\n".join(f"  {f}" for f in failures)
        )
