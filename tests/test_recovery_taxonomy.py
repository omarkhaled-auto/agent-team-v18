"""Tests for D-06 — recovery taxonomy (``debug_fleet`` + drift guard).

The ``print_recovery_report`` helper in ``display.py`` looks up each
recovery type appended during orchestration in a ``type_hints`` dict.
Missing entries rendered as "Unknown recovery type" in build-j (line
1836: "debug_fleet: Unknown recovery type"). This test enumerates every
``recovery_types.append(...)`` call site in the codebase and asserts
each type has a hint entry — so future recovery additions that forget
to register a hint fail CI loudly instead of quietly shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_team_v15.display import print_recovery_report


REPO_SRC = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15"


def _extract_recovery_types_from_source() -> set[str]:
    """Grep the source tree for every ``recovery_types.append("...")``
    call and return the literal string arguments as a set."""
    pattern = re.compile(r'recovery_types\.append\(\s*["\']([^"\']+)["\']\s*\)')
    types: set[str] = set()
    for path in REPO_SRC.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in pattern.finditer(text):
            types.add(match.group(1))
    return types


def _hints_dict() -> dict[str, str]:
    """Recover the ``type_hints`` dict by parsing ``display.py`` source.

    ``print_recovery_report`` defines the dict locally; we read it via
    the source file to avoid monkeypatching the function. Using AST
    instead of evaluating code keeps the test hermetic.
    """
    import ast

    source_path = REPO_SRC / "display.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "print_recovery_report"
        ):
            for stmt in ast.walk(node):
                if (
                    isinstance(stmt, ast.Assign)
                    and any(
                        isinstance(t, ast.Name) and t.id == "type_hints"
                        for t in stmt.targets
                    )
                    and isinstance(stmt.value, ast.Dict)
                ):
                    result: dict[str, str] = {}
                    for key_node, val_node in zip(stmt.value.keys, stmt.value.values):
                        if isinstance(key_node, ast.Constant) and isinstance(
                            val_node, ast.Constant
                        ):
                            result[key_node.value] = val_node.value
                    return result
    raise AssertionError("type_hints dict not found in print_recovery_report")


# ---------------------------------------------------------------------------
# 1. debug_fleet specifically has a hint (D-06 source bug)
# ---------------------------------------------------------------------------


def test_debug_fleet_has_explicit_hint() -> None:
    hints = _hints_dict()
    assert "debug_fleet" in hints
    hint = hints["debug_fleet"]
    assert hint and hint.strip() != "Unknown recovery type"
    # Hint is human-readable and explains the deployment.
    assert "debug" in hint.lower()


# ---------------------------------------------------------------------------
# 2. Drift guard: every recovery_types.append(...) literal has a hint
# ---------------------------------------------------------------------------


def test_every_recovery_type_has_a_registered_hint() -> None:
    """Enumerate source and assert every string literal appended to
    ``recovery_types`` has a matching entry in the hints dict."""
    found_types = _extract_recovery_types_from_source()
    hints = _hints_dict()
    missing = sorted(t for t in found_types if t not in hints)
    assert missing == [], (
        "Recovery types appended in source but missing a hint in "
        f"display.print_recovery_report.type_hints: {missing}. "
        "Add a hint so the recovery report does not render 'Unknown recovery type'."
    )


def test_no_orphan_hints() -> None:
    """Hints should describe real recovery types — an orphan hint hides a
    rename that broke the drift guard. Allow this to be a warning rather
    than a hard fail via ``xfail`` semantics: we still want visibility if
    hints accumulate without their source-side appends."""
    found_types = _extract_recovery_types_from_source()
    hints = _hints_dict()
    orphans = sorted(h for h in hints if h not in found_types)
    # Not a hard assertion — the source scan is regex-based and can miss
    # dynamically built strings. Surface as an informational check.
    if orphans:
        pytest.skip(
            "Informational: hints present without a matching "
            f"recovery_types.append source: {orphans}"
        )


# ---------------------------------------------------------------------------
# 3. print_recovery_report does not emit "Unknown recovery type" for any
#    known type
# ---------------------------------------------------------------------------


def test_print_recovery_report_no_unknown_for_known_types(capsys) -> None:
    """Exercise the real function with every known type; rich prints to
    stdout. Assert "Unknown recovery type" does not appear anywhere."""
    found_types = sorted(_extract_recovery_types_from_source())
    print_recovery_report(len(found_types), found_types)
    captured = capsys.readouterr().out
    assert "Unknown recovery type" not in captured
