"""Phase 2 milestone tracking compatibility helpers.

These helpers are intentionally narrow: they normalize Wave E milestone
tracking documents so legacy post-milestone health checks can parse them
without turning Phase 2 into a later-phase verification stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_TASK_BLOCK_RE = re.compile(r"(?=^###\s+TASK-\d+)", re.MULTILINE)
_TASK_ID_RE = re.compile(r"^###\s+(TASK-\d+)", re.MULTILINE)
_TASK_STATUS_RE = re.compile(r"^(?P<indent>\s*)-?\s*Status:\s*(?P<status>[A-Za-z_]+)\s*$", re.IGNORECASE)
_TASK_FIELD_RE = re.compile(
    r"^\s*-?\s*(Description|Files|Status|Depends-On|Depends On|Dependencies|Parent|Milestone)\s*:\s*(.*)$",
    re.IGNORECASE,
)
_REQ_LINE_RE = re.compile(r"^(?P<indent>\s*-\s*\[)(?P<checked>[ xX])(?P<body>\]\s*.+?)\s*$")
_REVIEW_CYCLES_RE = re.compile(r"\(review_cycles:\s*(\d+)\)")
_PLACEHOLDER_PATTERNS = (
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bFIXME\b", re.IGNORECASE),
    re.compile(r"\bnot implemented\b", re.IGNORECASE),
    re.compile(r"\bNotImplementedError\b"),
    re.compile(r"throw\s+new\s+Error\s*\(\s*['\"](?:todo|not implemented)", re.IGNORECASE),
    re.compile(r"res\s*\.\s*status\s*\(\s*501\s*\)", re.IGNORECASE),
)


@dataclass(frozen=True)
class TaskDocBlock:
    """Tolerant view of one TASKS.md block."""

    task_id: str
    status: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class TrackingCompatResult:
    """Outcome of milestone tracking normalization."""

    requirements_updated: bool = False
    tasks_updated: bool = False
    auto_marked_requirements: bool = False


def finalize_phase2_tracking_docs(
    *,
    cwd: str,
    milestone_id: str,
    completed_waves: list[Any],
) -> TrackingCompatResult:
    """Normalize milestone tracking docs for legacy health compatibility.

    The helper only auto-marks unchecked requirements when the milestone looks
    structurally complete already:

    - all executed waves succeeded,
    - compile gates passed for compile-bearing waves,
    - all milestone tasks are complete,
    - every listed task file exists,
    - and no obvious placeholder markers remain in those files.
    """

    milestone_dir = Path(cwd) / ".agent-team" / "milestones" / milestone_id
    requirements_path = milestone_dir / "REQUIREMENTS.md"
    tasks_path = milestone_dir / "TASKS.md"

    result = TrackingCompatResult()
    if not requirements_path.is_file() or not tasks_path.is_file():
        return result

    tasks_content = tasks_path.read_text(encoding="utf-8")
    normalized_tasks, task_blocks = _normalize_tasks_content(tasks_content)
    tasks_updated = normalized_tasks != tasks_content
    if tasks_updated:
        tasks_path.write_text(normalized_tasks, encoding="utf-8")

    requirements_content = requirements_path.read_text(encoding="utf-8")
    finalized_requirements, requirements_updated, auto_marked = _finalize_requirements_content(
        requirements_content=requirements_content,
        root=Path(cwd),
        task_blocks=task_blocks,
        completed_waves=completed_waves,
    )
    if requirements_updated:
        requirements_path.write_text(finalized_requirements, encoding="utf-8")

    return TrackingCompatResult(
        requirements_updated=requirements_updated,
        tasks_updated=tasks_updated,
        auto_marked_requirements=auto_marked,
    )


def _normalize_tasks_content(content: str) -> tuple[str, list[TaskDocBlock]]:
    lines = content.splitlines()
    normalized_lines: list[str] = []
    task_blocks = _parse_task_blocks(content)

    for line in lines:
        match = _TASK_STATUS_RE.match(line)
        if match:
            normalized_status = _normalize_task_status(match.group("status"))
            normalized_lines.append(f"{match.group('indent')}- Status: {normalized_status}")
            continue
        normalized_lines.append(line)

    normalized = "\n".join(normalized_lines)
    if content.endswith("\n"):
        normalized += "\n"
    return normalized, task_blocks


def _parse_task_blocks(content: str) -> list[TaskDocBlock]:
    blocks = [block.strip("\n") for block in _TASK_BLOCK_RE.split(content) if _TASK_ID_RE.search(block or "")]
    parsed: list[TaskDocBlock] = []

    for block in blocks:
        task_id_match = _TASK_ID_RE.search(block)
        if not task_id_match:
            continue
        task_id = task_id_match.group(1)
        status = "PENDING"
        files: list[str] = []
        in_files_section = False

        for raw_line in block.splitlines()[1:]:
            stripped = raw_line.strip()
            if not stripped:
                in_files_section = False
                continue

            field_match = _TASK_FIELD_RE.match(raw_line)
            if field_match:
                field_name = field_match.group(1).lower()
                field_value = field_match.group(2).strip()
                in_files_section = field_name == "files"
                if field_name == "status":
                    status = _normalize_task_status(field_value)
                if field_name == "files" and field_value:
                    files.extend(_split_inline_file_field(field_value))
                continue

            if in_files_section and stripped.startswith("-"):
                files.append(_clean_task_file_entry(stripped[1:].strip()))

        parsed.append(TaskDocBlock(task_id=task_id, status=status, files=tuple(dict.fromkeys(f for f in files if f))))

    return parsed


def _split_inline_file_field(value: str) -> list[str]:
    return [
        _clean_task_file_entry(part.strip())
        for part in re.split(r"[,;]", value)
        if part.strip()
    ]


def _clean_task_file_entry(value: str) -> str:
    cleaned = value.strip().strip("`")
    cleaned = re.sub(r"\s+\((?:updated|modified|created)\)\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.replace("\\", "/")


def _normalize_task_status(value: str) -> str:
    token = (value or "").strip().upper()
    if token in {"DONE", "COMPLETED"}:
        return "COMPLETE"
    if token in {"TODO", "OPEN"}:
        return "PENDING"
    return token or "PENDING"


def _finalize_requirements_content(
    *,
    requirements_content: str,
    root: Path,
    task_blocks: list[TaskDocBlock],
    completed_waves: list[Any],
) -> tuple[str, bool, bool]:
    if not task_blocks:
        return requirements_content, False, False

    requirement_lines = [
        line for line in requirements_content.splitlines()
        if _REQ_LINE_RE.match(line)
    ]
    if not requirement_lines:
        return requirements_content, False, False

    structurally_complete = _is_structurally_complete(
        root=root,
        task_blocks=task_blocks,
        completed_waves=completed_waves,
    )
    if not structurally_complete:
        return requirements_content, False, False

    all_unchecked = all(match.group("checked").lower() != "x" for line in requirement_lines if (match := _REQ_LINE_RE.match(line)))
    updated_lines: list[str] = []
    changed = False

    for line in requirements_content.splitlines():
        match = _REQ_LINE_RE.match(line)
        if not match:
            updated_lines.append(line)
            continue

        checked = match.group("checked")
        if all_unchecked:
            checked = "x"
        body = _ensure_review_cycles_at_least_one(match.group("body"))
        updated_line = f"{match.group('indent')}{checked}{body}"
        updated_lines.append(updated_line)
        changed = changed or updated_line != line

    updated_content = "\n".join(updated_lines)
    if requirements_content.endswith("\n"):
        updated_content += "\n"
    return updated_content, changed, all_unchecked and changed


def _ensure_review_cycles_at_least_one(body: str) -> str:
    match = _REVIEW_CYCLES_RE.search(body)
    if match:
        current = int(match.group(1))
        if current >= 1:
            return body
        return _REVIEW_CYCLES_RE.sub("(review_cycles: 1)", body)
    return f"{body} (review_cycles: 1)"


def _is_structurally_complete(
    *,
    root: Path,
    task_blocks: list[TaskDocBlock],
    completed_waves: list[Any],
) -> bool:
    if not completed_waves:
        return False
    if not all(bool(getattr(wave, "success", False)) for wave in completed_waves):
        return False
    if not all(
        getattr(wave, "wave", "") not in {"A", "B", "D"}
        or getattr(wave, "compile_iterations", 0) == 0
        or bool(getattr(wave, "compile_passed", False))
        for wave in completed_waves
    ):
        return False
    if not all(task.status == "COMPLETE" for task in task_blocks):
        return False

    task_files = _collect_task_files(root, task_blocks)
    if not task_files:
        return False
    if not all(path.is_file() for path in task_files):
        return False
    if _contains_placeholder_markers(task_files):
        return False
    return True


def _collect_task_files(root: Path, task_blocks: list[TaskDocBlock]) -> list[Path]:
    seen: dict[str, Path] = {}
    for task in task_blocks:
        for file_ref in task.files:
            rel_path = file_ref.strip().lstrip("./")
            if not rel_path:
                continue
            seen.setdefault(rel_path, root / rel_path)
    return list(seen.values())


def _contains_placeholder_markers(paths: list[Path]) -> bool:
    for path in paths:
        suffix = path.suffix.lower()
        if suffix and suffix not in {".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".py", ".dart", ".cs"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(pattern.search(content) for pattern in _PLACEHOLDER_PATTERNS):
            return True
    return False


__all__ = [
    "TaskDocBlock",
    "TrackingCompatResult",
    "finalize_phase2_tracking_docs",
]
