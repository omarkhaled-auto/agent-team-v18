"""DoD feasibility verifier — Phase H1a Item 3.

Parses a milestone's ``REQUIREMENTS.md`` ``## Definition of Done`` block
for shell commands (``pnpm X``, ``npm run X``, compound ``cd DIR && pnpm X``)
and asserts each referenced script exists in at least one of:

  * ``<root>/package.json``
  * ``<root>/apps/api/package.json``
  * ``<root>/apps/web/package.json``

Bare executables (``docker``, ``curl``, ``git``) are skipped. One
``DOD-FEASIBILITY-001`` HIGH finding is emitted per unresolvable command,
naming the command and the files searched.

The hook site is ``wave_executor.py`` milestone-teardown (between
``persist_wave_findings_for_audit`` and ``architecture_writer.append_milestone``)
so the check fires even on milestones that failed at Wave B — Wave E never
ran in smoke #11's M1, but the feasibility gap was a root cause we must
surface regardless.

Flag-gated by ``v18.dod_feasibility_verifier_enabled`` at the call site.
Graceful skip on missing preconditions (no REQUIREMENTS.md, no DoD block,
no package.json anywhere, unparseable block) — no crash, no WARN spam.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .requirements_parser import _iter_dod_lines  # type: ignore[attr-defined]

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Finding:
    """Minimal finding shape — converted to WaveFinding by caller."""

    code: str
    severity: str
    file: str
    message: str


# Executable tokens we ignore. Extend conservatively — if a token is
# truly a bare system binary, skipping it avoids false positives.
_BARE_EXECUTABLES = frozenset(
    {
        "docker",
        "curl",
        "wget",
        "git",
        "psql",
        "sh",
        "bash",
        "cd",
        "ls",
        "echo",
        "rm",
        "mkdir",
        "test",
        "node",
        "python",
        "python3",
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "PATCH",
        "HTTP",
    }
)

# Package-manager prefixes we DO check. Order matters only for
# readability — the parser handles each independently.
_PKG_MANAGER_PREFIXES = ("pnpm", "npm", "yarn")

# Matches backtick-wrapped inline command chunks — we only inspect
# what's inside backticks; prose outside is not a command.
_BACKTICK_RE = re.compile(r"`([^`]+)`")

# Matches ``pnpm --filter <x> <script>`` / ``pnpm run <script>`` /
# ``pnpm <script>`` / ``npm run <script>`` / ``yarn <script>``.
# Group 1: package-manager. Group 2: optional ``run``/``--filter X``.
# Group 3: script token.
_PKG_SCRIPT_RE = re.compile(
    r"\b(pnpm|npm|yarn)\b"
    r"(?:\s+--filter\s+\S+|\s+run)?"
    r"\s+([A-Za-z][\w:\-\.]*)",
)


def _load_package_scripts(path: Path) -> Optional[set[str]]:
    """Return the set of script names in a package.json, or None if absent."""

    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return set()
    return {str(k) for k in scripts.keys() if isinstance(k, str)}


def _gather_all_scripts(project_root: Path) -> tuple[dict[str, set[str]], list[Path]]:
    """Scan the three known package.json locations.

    Returns a mapping of label → script-set for each manifest that exists,
    plus the list of paths searched (for diagnostic messages).
    """

    candidates = [
        ("root", project_root / "package.json"),
        ("apps/api", project_root / "apps" / "api" / "package.json"),
        ("apps/web", project_root / "apps" / "web" / "package.json"),
    ]
    found: dict[str, set[str]] = {}
    searched: list[Path] = []
    for label, path in candidates:
        searched.append(path)
        scripts = _load_package_scripts(path)
        if scripts is None:
            continue
        found[label] = scripts
    return found, searched


def _extract_commands_from_dod(text: str) -> list[str]:
    """Return the ordered list of backtick-wrapped chunks inside the DoD block."""

    chunks: list[str] = []
    for line in _iter_dod_lines(text):
        for match in _BACKTICK_RE.finditer(line):
            chunks.append(match.group(1).strip())
    return chunks


def _iter_pkg_scripts(command: str) -> Iterable[tuple[str, str]]:
    """Yield ``(manager, script)`` for each resolvable script in a command chunk.

    Handles ``&&``-chained forms (``pnpm install && pnpm typecheck``),
    ``pnpm --filter`` forms, and bare ``pnpm X`` forms. Matches are
    conservative — tokens that do not clearly resolve to a script (e.g.
    positional args) are dropped.
    """

    # Match across the whole chunk; ``&&``/``||``/``;`` do not interfere
    # with the regex (it anchors on pnpm/npm/yarn word boundaries).
    for match in _PKG_SCRIPT_RE.finditer(command):
        manager = match.group(1)
        script = match.group(2)
        if not script:
            continue
        # Skip the ``install`` primitive — it's a package-manager builtin,
        # not a scripts-block entry. Same for a small set of builtins.
        if script in {"install", "i", "add", "remove", "exec", "dlx", "create"}:
            continue
        yield manager, script


def run_dod_feasibility_check(
    project_root: Path | str,
    milestone_dir: Path | str,
) -> list[Finding]:
    """Run the DoD feasibility check for one milestone.

    Reads ``<milestone_dir>/REQUIREMENTS.md``, locates the
    ``## Definition of Done`` block, and emits
    ``DOD-FEASIBILITY-001`` per unresolvable ``pnpm``/``npm``/``yarn``
    script reference.

    Returns a (possibly empty) list of :class:`Finding`. Graceful skip
    with an empty list when REQUIREMENTS.md is missing, has no DoD
    block, or no package.json exists anywhere (silent — callers
    already know the precondition surface from architecture).
    """

    root = Path(project_root)
    req_path = Path(milestone_dir) / "REQUIREMENTS.md"

    if not req_path.exists():
        return []

    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return []

    commands = _extract_commands_from_dod(text)
    if not commands:
        # Either no DoD block at all, or a DoD block with no backticked
        # commands. Surface one WARN and return — not a finding.
        _logger.warning(
            "DoD feasibility: no backticked commands under ## Definition "
            "of Done in %s",
            req_path,
        )
        return []

    scripts_by_label, searched = _gather_all_scripts(root)
    if not scripts_by_label:
        # No package.json anywhere — not a feasibility finding; the
        # scaffolder runs later or the project uses a different tool.
        return []

    # Flatten the script inventory for fast lookup; preserve label-set
    # for error reporting.
    all_scripts: set[str] = set()
    for label_scripts in scripts_by_label.values():
        all_scripts.update(label_scripts)
    searched_labels = sorted(scripts_by_label.keys())

    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for command in commands:
        for manager, script in _iter_pkg_scripts(command):
            if script in _BARE_EXECUTABLES:
                continue
            key = (manager, script)
            if key in seen:
                continue
            seen.add(key)
            if script in all_scripts:
                continue
            # Build a stable message that Wave 3 tests can grep.
            message = (
                f"DoD command `{manager} {script}` references a script "
                f"that is not defined in any known package.json. "
                f"Searched: {', '.join(searched_labels)} "
                f"(files: {[p.as_posix() for p in searched]})."
            )
            findings.append(
                Finding(
                    code="DOD-FEASIBILITY-001",
                    severity="HIGH",
                    file=req_path.as_posix(),
                    message=message,
                )
            )

    return findings


__all__ = ["Finding", "run_dod_feasibility_check"]
