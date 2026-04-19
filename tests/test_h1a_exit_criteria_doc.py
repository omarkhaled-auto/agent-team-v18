"""Phase H1a Item 8 — PHASE_FINAL_EXIT_CRITERIA.md must exist at the repo
root and carry the same 20 checkbox lines as
``MASTER_IMPLEMENTATION_PLAN_v2.md:1086-1105`` (line-for-line modulo
whitespace).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXIT_CRITERIA = _REPO_ROOT / "PHASE_FINAL_EXIT_CRITERIA.md"
_MASTER_PLAN = _REPO_ROOT / "MASTER_IMPLEMENTATION_PLAN_v2.md"
_CHECKBOX_RE = re.compile(r"^\s*-\s*\[\s*[ xX]\s*\]\s*(.*?)\s*$")


def _collect_checkboxes(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        m = _CHECKBOX_RE.match(raw)
        if m:
            lines.append(m.group(1).strip())
    return lines


def test_exit_criteria_doc_exists() -> None:
    assert _EXIT_CRITERIA.is_file(), (
        f"Phase FINAL exit criteria doc missing at {_EXIT_CRITERIA}"
    )


def test_exit_criteria_has_exactly_20_checkboxes() -> None:
    text = _EXIT_CRITERIA.read_text(encoding="utf-8")
    checkboxes = _collect_checkboxes(text)
    assert len(checkboxes) == 20, (
        f"Expected 20 checkboxes, got {len(checkboxes)}: {checkboxes}"
    )


def test_every_criterion_has_a_checkbox_syntax() -> None:
    """Every criterion line must begin with a ``- [ ]`` / ``- [x]``
    prefix. This guards against a future edit that turns a checkbox
    into a bullet-only line."""

    text = _EXIT_CRITERIA.read_text(encoding="utf-8")
    # Lines we consider "criteria" are ones that fall within the
    # contiguous block of checkbox bullets at the bottom of the file.
    lines = text.splitlines()
    # Collect all checkbox lines — any non-checkbox line in between two
    # checkbox lines that starts with "- " would be a regression.
    checkbox_indices = [
        i for i, line in enumerate(lines) if _CHECKBOX_RE.match(line)
    ]
    assert checkbox_indices, "no checkboxes found in exit-criteria doc"
    first, last = checkbox_indices[0], checkbox_indices[-1]
    for idx in range(first, last + 1):
        line = lines[idx].rstrip()
        if not line:
            continue  # blank lines allowed between checkboxes
        assert _CHECKBOX_RE.match(line), (
            f"Line {idx + 1} inside checkbox block is not a checkbox: {line!r}"
        )


def test_exit_criteria_matches_master_plan_lines_1086_1105() -> None:
    """Content of the 20 checkboxes must match the plan canonical
    source line-for-line (strip whitespace differences)."""

    master_text = _MASTER_PLAN.read_text(encoding="utf-8")
    master_checkboxes = _collect_checkboxes(master_text)

    # The plan has many checkbox sections; isolate the final-exit block.
    # Anchor on the same unique phrasings: "All milestones M1-M6 PASS"
    # opens the block, "PHASE_FINAL_SMOKE_REPORT.md captures full" closes it.
    try:
        start = next(
            i
            for i, c in enumerate(master_checkboxes)
            if "All milestones M1-M6 PASS" in c
        )
    except StopIteration:  # pragma: no cover — defensive
        pytest.fail("master plan missing 'All milestones M1-M6 PASS' checkbox")
    try:
        end = next(
            i
            for i, c in enumerate(master_checkboxes[start:], start=start)
            if "PHASE_FINAL_SMOKE_REPORT.md captures full" in c
        )
    except StopIteration:  # pragma: no cover — defensive
        pytest.fail(
            "master plan missing 'PHASE_FINAL_SMOKE_REPORT.md captures full' checkbox"
        )
    plan_block = master_checkboxes[start : end + 1]
    assert len(plan_block) == 20, (
        f"expected 20 checkboxes in plan slice, got {len(plan_block)}"
    )

    doc_block = _collect_checkboxes(_EXIT_CRITERIA.read_text(encoding="utf-8"))
    assert doc_block == plan_block, (
        "Exit-criteria doc diverged from MASTER_IMPLEMENTATION_PLAN_v2.md "
        "line 1086-1105."
    )
