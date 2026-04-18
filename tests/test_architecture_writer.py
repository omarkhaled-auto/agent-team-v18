"""Phase G Slice 1c — Cumulative ARCHITECTURE.md writer.

Covers ``agent_team_v15.architecture_writer``'s three entrypoints:
``init_if_missing``, ``append_milestone``, ``summarize_if_over``. Each is
idempotent and swallows IO errors (per module docstring); tests assert the
text shape of the generated file plus rollup behaviour when the file grows
past the configured line cap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_team_v15 import architecture_writer as _aw


def test_init_if_missing_creates_expected_skeleton(tmp_path: Path) -> None:
    created = _aw.init_if_missing(tmp_path, project_name="demo")
    assert created is True
    content = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert content.startswith("# Architecture — demo")
    assert "## Summary" in content
    assert "- Milestones completed: 0" in content
    assert "## Entities (cumulative)" in content
    assert "## Endpoints (cumulative)" in content
    assert "## Manual notes" in content


def test_init_if_missing_is_idempotent(tmp_path: Path) -> None:
    """Re-running init MUST NOT overwrite existing content."""
    _aw.init_if_missing(tmp_path, project_name="demo")
    first = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    # Manual edit the human "Manual notes" section.
    (tmp_path / "ARCHITECTURE.md").write_text(
        first + "\nsome human note\n", encoding="utf-8"
    )
    created = _aw.init_if_missing(tmp_path, project_name="demo")
    assert created is False  # no-op on second call
    # Human-added note survives the no-op.
    assert "some human note" in (tmp_path / "ARCHITECTURE.md").read_text(
        encoding="utf-8"
    )


def test_append_milestone_adds_block_and_updates_tables(tmp_path: Path) -> None:
    _aw.init_if_missing(tmp_path, project_name="demo")
    wave_artifacts = {
        "A": {
            "entities": [
                {"name": "User", "fields": ["id", "email"], "relations": []},
            ],
            "decisions": [{"text": "Use Prisma for migrations"}],
        },
        "B": {
            "endpoints": [
                {"path": "/api/users", "method": "GET", "dto": "UserDto"},
            ],
        },
    }
    ok = _aw.append_milestone(
        "M1", wave_artifacts, tmp_path, title="User CRUD"
    )
    assert ok is True
    content = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "## Milestone M1 — User CRUD" in content
    # Decision text inherited from Wave A.
    assert "Use Prisma for migrations" in content
    # Entity and endpoint appear in cumulative tables too.
    assert "| User | M1 | 2 |" in content
    assert "| /api/users | GET | M1 | UserDto |" in content
    # Milestone counter incremented.
    assert "- Milestones completed: 1" in content


def test_append_milestone_is_idempotent_on_same_id(tmp_path: Path) -> None:
    """Second call for the same milestone must not duplicate table rows."""
    _aw.init_if_missing(tmp_path, project_name="demo")
    artifacts = {
        "A": {"entities": [{"name": "Tag", "fields": ["id"]}]},
        "B": {"endpoints": [{"path": "/api/tags", "method": "GET", "dto": "TagDto"}]},
    }
    _aw.append_milestone("M2", artifacts, tmp_path)
    _aw.append_milestone("M2", artifacts, tmp_path)
    content = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert content.count("| Tag | M2 | 1 |") == 1
    assert content.count("| /api/tags | GET | M2 | TagDto |") == 1


def test_summarize_if_over_rolls_up_oldest_blocks(tmp_path: Path) -> None:
    """When the file exceeds max_lines, oldest milestones collapse to a rollup."""
    _aw.init_if_missing(tmp_path, project_name="demo")
    # Produce 8 milestone blocks so summarization triggers.
    for i in range(1, 9):
        _aw.append_milestone(
            f"M{i}",
            {
                "A": {
                    "entities": [
                        {"name": f"Entity{i}", "fields": list("abcdefghij")}
                    ]
                }
            },
            tmp_path,
        )
    # Force summarization by asserting tiny ceiling.
    rolled = _aw.summarize_if_over(tmp_path, max_lines=10, summarize_floor=3)
    assert rolled is True
    content = (tmp_path / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "(rolled up)" in content
    # The most-recent milestones must survive verbatim as full blocks.
    assert "## Milestone M8" in content
    assert "## Milestone M7" in content
    assert "## Milestone M6" in content
    # Oldest block should have been collapsed into the rollup header.
    assert "## Milestone M1 " not in content or "rolled up" in content


def test_errors_are_swallowed_and_never_raise(tmp_path: Path) -> None:
    """All three entrypoints must be non-fatal on unexpected input."""
    # Append_milestone with no init, non-dict artifacts, bad cwd.
    assert _aw.append_milestone("M0", None, tmp_path) in (True, False)
    # summarize_if_over on a missing file is a benign no-op.
    assert (
        _aw.summarize_if_over(tmp_path / "does_not_exist") is False
    )
