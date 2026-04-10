from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_team_v15.tracking_compat import finalize_phase2_tracking_docs


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _wave(wave: str, *, compile_iterations: int = 0, compile_passed: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        wave=wave,
        success=True,
        compile_iterations=compile_iterations,
        compile_passed=compile_passed,
    )


def _milestone_dir(root: Path) -> Path:
    milestone_dir = root / ".agent-team" / "milestones" / "milestone-1"
    milestone_dir.mkdir(parents=True, exist_ok=True)
    return milestone_dir


def test_finalize_phase2_tracking_docs_marks_complete_docs_when_structurally_complete(tmp_path: Path) -> None:
    milestone_dir = _milestone_dir(tmp_path)
    _write(
        milestone_dir / "REQUIREMENTS.md",
        "\n".join(
            [
                "# Milestone 1",
                "",
                "- [ ] REQ-101: Create the bookmark schema.",
                "- [ ] REQ-102: Implement bookmark endpoints.",
                "",
            ]
        ),
    )
    _write(
        milestone_dir / "TASKS.md",
        "\n".join(
            [
                "### TASK-001",
                "Description: Create the schema.",
                "Files:",
                "- src/bookmarks/bookmark.entity.ts",
                "Status: DONE",
                "",
                "### TASK-002",
                "Description: Implement the endpoints.",
                "Files:",
                "- src/bookmarks/bookmarks.module.ts (updated)",
                "- src/bookmarks/bookmarks.controller.ts",
                "Status: DONE",
                "",
            ]
        ),
    )
    _write(tmp_path / "src" / "bookmarks" / "bookmark.entity.ts", "export type Bookmark = { id: string };\n")
    _write(tmp_path / "src" / "bookmarks" / "bookmarks.module.ts", "export const bookmarksModule = true;\n")
    _write(
        tmp_path / "src" / "bookmarks" / "bookmarks.controller.ts",
        "const app = { get(_path: string, _handler: unknown) {} };\napp.get('/api/bookmarks', () => undefined);\n",
    )

    result = finalize_phase2_tracking_docs(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        completed_waves=[
            _wave("A", compile_iterations=1, compile_passed=True),
            _wave("B", compile_iterations=1, compile_passed=True),
            _wave("C"),
            _wave("E"),
        ],
    )

    assert result.tasks_updated is True
    assert result.requirements_updated is True
    assert result.auto_marked_requirements is True

    requirements = (milestone_dir / "REQUIREMENTS.md").read_text(encoding="utf-8")
    assert "- [x] REQ-101: Create the bookmark schema. (review_cycles: 1)" in requirements
    assert "- [x] REQ-102: Implement bookmark endpoints. (review_cycles: 1)" in requirements

    tasks = (milestone_dir / "TASKS.md").read_text(encoding="utf-8")
    assert "- Status: COMPLETE" in tasks
    assert "Status: DONE" not in tasks


def test_finalize_phase2_tracking_docs_leaves_requirements_unchecked_when_tasks_are_incomplete(tmp_path: Path) -> None:
    milestone_dir = _milestone_dir(tmp_path)
    _write(
        milestone_dir / "REQUIREMENTS.md",
        "- [ ] REQ-101: Create the bookmark schema.\n",
    )
    _write(
        milestone_dir / "TASKS.md",
        "\n".join(
            [
                "### TASK-001",
                "Description: Create the schema.",
                "Files:",
                "- src/bookmarks/bookmark.entity.ts",
                "Status: TODO",
                "",
            ]
        ),
    )
    _write(tmp_path / "src" / "bookmarks" / "bookmark.entity.ts", "export type Bookmark = { id: string };\n")

    result = finalize_phase2_tracking_docs(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        completed_waves=[
            _wave("A", compile_iterations=1, compile_passed=True),
            _wave("B", compile_iterations=1, compile_passed=True),
            _wave("C"),
            _wave("E"),
        ],
    )

    assert result.tasks_updated is True
    assert result.requirements_updated is False
    assert result.auto_marked_requirements is False

    requirements = (milestone_dir / "REQUIREMENTS.md").read_text(encoding="utf-8")
    assert "- [ ] REQ-101: Create the bookmark schema." in requirements
    assert "(review_cycles:" not in requirements


def test_finalize_phase2_tracking_docs_blocks_auto_check_when_placeholder_markers_exist(tmp_path: Path) -> None:
    milestone_dir = _milestone_dir(tmp_path)
    _write(
        milestone_dir / "REQUIREMENTS.md",
        "- [ ] REQ-101: Create the bookmark schema.\n",
    )
    _write(
        milestone_dir / "TASKS.md",
        "\n".join(
            [
                "### TASK-001",
                "Description: Create the schema.",
                "Files:",
                "- src/bookmarks/bookmark.entity.ts",
                "Status: DONE",
                "",
            ]
        ),
    )
    _write(
        tmp_path / "src" / "bookmarks" / "bookmark.entity.ts",
        "export function buildBookmark() { throw new Error('TODO'); }\n",
    )

    result = finalize_phase2_tracking_docs(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        completed_waves=[
            _wave("A", compile_iterations=1, compile_passed=True),
            _wave("B", compile_iterations=1, compile_passed=True),
            _wave("C"),
            _wave("E"),
        ],
    )

    assert result.tasks_updated is True
    assert result.requirements_updated is False
    assert result.auto_marked_requirements is False
    requirements = (milestone_dir / "REQUIREMENTS.md").read_text(encoding="utf-8")
    assert "- [ ] REQ-101: Create the bookmark schema." in requirements


def test_finalize_phase2_tracking_docs_preserves_existing_review_cycles_and_checked_state(tmp_path: Path) -> None:
    milestone_dir = _milestone_dir(tmp_path)
    _write(
        milestone_dir / "REQUIREMENTS.md",
        "\n".join(
            [
                "- [x] REQ-101: Create the bookmark schema. (review_cycles: 3)",
                "- [ ] REQ-102: Implement bookmark endpoints.",
                "",
            ]
        ),
    )
    _write(
        milestone_dir / "TASKS.md",
        "\n".join(
            [
                "### TASK-001",
                "Description: Create the schema.",
                "Files:",
                "- src/bookmarks/bookmark.entity.ts",
                "Status: DONE",
                "",
            ]
        ),
    )
    _write(tmp_path / "src" / "bookmarks" / "bookmark.entity.ts", "export type Bookmark = { id: string };\n")

    result = finalize_phase2_tracking_docs(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        completed_waves=[
            _wave("A", compile_iterations=1, compile_passed=True),
            _wave("B", compile_iterations=1, compile_passed=True),
            _wave("C"),
            _wave("E"),
        ],
    )

    assert result.requirements_updated is True
    requirements = (milestone_dir / "REQUIREMENTS.md").read_text(encoding="utf-8")
    assert "- [x] REQ-101: Create the bookmark schema. (review_cycles: 3)" in requirements
    assert "- [ ] REQ-102: Implement bookmark endpoints. (review_cycles: 1)" in requirements
