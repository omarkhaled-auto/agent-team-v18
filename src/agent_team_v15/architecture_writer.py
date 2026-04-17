"""Cumulative ARCHITECTURE.md writer (Phase G Slice 1c, R3).

Maintains `<cwd>/ARCHITECTURE.md` — the cumulative cross-milestone knowledge
accumulator. Distinct from the per-milestone `.agent-team/milestone-{id}/
ARCHITECTURE.md` that Wave A writes as a Claude-authored handoff (Slice 5a,
not this module).

Public surface:
    init_if_missing(cwd)                      — called once before M1 dispatch
    append_milestone(milestone_id, wave_artifacts, cwd, stack_contract=None,
                     title=None)              — called at milestone end
    summarize_if_over(cwd, max_lines,
                      summarize_floor)        — live-file size guard

All three operations are idempotent and never raise on malformed/missing
input — failure to write the cumulative doc must never block the build
pipeline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_FILE_NAME = "ARCHITECTURE.md"
_MANUAL_NOTES_HEADER = "## Manual notes"
_ROLLUP_HEADER_PREFIX = "## Milestones "


def _arch_path(cwd: str | Path) -> Path:
    return Path(cwd) / _FILE_NAME


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _initial_content(project_name: str, stack: dict[str, Any] | None) -> str:
    fe = (stack or {}).get("frontend") or "<TBD>"
    be = (stack or {}).get("backend") or "<TBD>"
    db = (stack or {}).get("database") or "<TBD>"
    return (
        f"# Architecture — {project_name}\n\n"
        "> Auto-maintained by V18 builder. Human edits outside "
        f"`{_MANUAL_NOTES_HEADER}` will be overwritten.\n\n"
        "## Summary\n"
        f"- Stack: {fe} / {be} / {db}\n"
        "- Milestones completed: 0\n"
        f"- Last update: {_iso_now()}\n\n"
        "## Entities (cumulative)\n"
        "| Name | First milestone | Current fields (count) | Relations |\n"
        "|------|-----------------|------------------------|-----------|\n\n"
        "## Endpoints (cumulative)\n"
        "| Path | Method | Owner milestone | DTO |\n"
        "|------|--------|-----------------|-----|\n\n"
        f"{_MANUAL_NOTES_HEADER}\n"
        "<!-- free-form human section; never overwritten by the builder -->\n"
    )


def init_if_missing(
    cwd: str | Path,
    project_name: str | None = None,
    stack_contract: dict[str, Any] | None = None,
) -> bool:
    """Write the initial cumulative ARCHITECTURE.md if absent.

    Returns True if a new file was created, False if one already existed or
    an error was swallowed. Never raises.
    """
    try:
        path = _arch_path(cwd)
        if path.exists():
            return False
        name = project_name or Path(cwd).name or "project"
        path.write_text(_initial_content(name, stack_contract), encoding="utf-8")
        logger.info("ARCHITECTURE.md initialized at %s", path)
        return True
    except Exception as exc:  # noqa: BLE001 — non-fatal
        logger.warning("architecture_writer.init_if_missing failed: %s", exc)
        return False


def _extract_entities(wave_artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    wave_a = wave_artifacts.get("A") or {}
    entities = (
        wave_a.get("entities")
        or wave_a.get("data_model", {}).get("entities")
        or []
    )
    out: list[dict[str, Any]] = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        name = ent.get("name") or ent.get("entity") or ent.get("id")
        if not name:
            continue
        fields = ent.get("fields") or ent.get("attributes") or []
        relations = ent.get("relations") or ent.get("relationships") or []
        rel_summary = ", ".join(
            str(r.get("to") or r.get("target") or r.get("name") or r)
            for r in relations
            if r
        ) or "-"
        out.append({
            "name": str(name),
            "field_count": len(fields) if isinstance(fields, (list, tuple)) else 0,
            "relations": rel_summary,
        })
    return out


def _extract_endpoints(wave_artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    wave_b = wave_artifacts.get("B") or {}
    endpoints = (
        wave_b.get("endpoints")
        or wave_b.get("routes")
        or wave_artifacts.get("A", {}).get("endpoints")
        or []
    )
    out: list[dict[str, Any]] = []
    for ep in endpoints:
        if not isinstance(ep, dict):
            continue
        path = ep.get("path") or ep.get("route") or ep.get("url")
        method = (ep.get("method") or ep.get("verb") or "GET").upper()
        dto = ep.get("dto") or ep.get("response_type") or "-"
        if not path:
            continue
        out.append({"path": str(path), "method": str(method), "dto": str(dto)})
    return out


def _extract_decisions(wave_artifacts: dict[str, Any]) -> list[str]:
    decisions: list[str] = []
    for w in ("A", "B", "D", "T", "E"):
        art = wave_artifacts.get(w) or {}
        for key in ("decisions", "design_decisions", "architecture_decisions"):
            items = art.get(key) or []
            if isinstance(items, str):
                items = [items]
            for d in items:
                if isinstance(d, dict):
                    text = d.get("text") or d.get("summary") or d.get("decision")
                elif isinstance(d, str):
                    text = d
                else:
                    text = None
                if text:
                    decisions.append(f"[{w}] {text}")
    return decisions


def _render_milestone_block(
    milestone_id: str,
    title: str | None,
    entities: list[dict[str, Any]],
    endpoints: list[dict[str, Any]],
    decisions: list[str],
) -> str:
    title_part = f" — {title}" if title else ""
    lines = [f"## Milestone {milestone_id}{title_part} ({_iso_now()})\n"]
    lines.append("### Decisions")
    if decisions:
        for d in decisions:
            lines.append(f"- {d}")
    else:
        lines.append("- (none recorded)")
    lines.append("")
    lines.append("### New entities")
    if entities:
        for e in entities:
            lines.append(
                f"- `{e['name']}` — {e['field_count']} field(s); relations: {e['relations']}"
            )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("### New endpoints")
    if endpoints:
        for ep in endpoints:
            lines.append(f"- `{ep['method']} {ep['path']}` → {ep['dto']}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("### Known limitations")
    lines.append("- (none recorded)")
    lines.append("")
    return "\n".join(lines)


def _update_cumulative_tables(
    existing: str,
    milestone_id: str,
    new_entities: list[dict[str, Any]],
    new_endpoints: list[dict[str, Any]],
) -> str:
    text = existing
    # Entities table: insert new rows before the first blank line after the
    # separator row. If an entity with the same name already appears, skip.
    for e in new_entities:
        row = f"| {e['name']} | {milestone_id} | {e['field_count']} | {e['relations']} |"
        if row in text:
            continue
        marker = "|------|-----------------|------------------------|-----------|\n"
        if marker in text and f"| {e['name']} |" not in text:
            text = text.replace(marker, marker + row + "\n", 1)
    for ep in new_endpoints:
        row = f"| {ep['path']} | {ep['method']} | {milestone_id} | {ep['dto']} |"
        if row in text:
            continue
        marker = "|------|--------|-----------------|-----|\n"
        if marker in text and f"| {ep['path']} | {ep['method']} |" not in text:
            text = text.replace(marker, marker + row + "\n", 1)
    return text


def _bump_summary_counter(text: str) -> str:
    import re

    def repl(match: "re.Match[str]") -> str:
        current = int(match.group(1))
        return f"- Milestones completed: {current + 1}\n- Last update: {_iso_now()}"

    pattern = re.compile(
        r"- Milestones completed: (\d+)\n- Last update: [^\n]+",
        re.MULTILINE,
    )
    return pattern.sub(repl, text, count=1)


def append_milestone(
    milestone_id: str,
    wave_artifacts: dict[str, Any] | None,
    cwd: str | Path,
    stack_contract: dict[str, Any] | None = None,
    title: str | None = None,
) -> bool:
    """Append a `## Milestone ...` block and merge cumulative tables.

    Returns True on successful write, False on no-op or swallowed error.
    """
    try:
        path = _arch_path(cwd)
        if not path.exists():
            init_if_missing(cwd, stack_contract=stack_contract)
        if not path.exists():
            return False
        existing = path.read_text(encoding="utf-8")

        artifacts = wave_artifacts or {}
        entities = _extract_entities(artifacts)
        endpoints = _extract_endpoints(artifacts)
        decisions = _extract_decisions(artifacts)

        block = _render_milestone_block(
            milestone_id, title, entities, endpoints, decisions
        )

        updated = _update_cumulative_tables(existing, milestone_id, entities, endpoints)
        updated = _bump_summary_counter(updated)

        # Insert milestone block immediately before `## Manual notes`.
        if _MANUAL_NOTES_HEADER in updated:
            updated = updated.replace(
                _MANUAL_NOTES_HEADER, block + "\n" + _MANUAL_NOTES_HEADER, 1
            )
        else:
            updated = updated.rstrip("\n") + "\n\n" + block + "\n"

        path.write_text(updated, encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001 — non-fatal
        logger.warning(
            "architecture_writer.append_milestone(%s) failed: %s",
            milestone_id,
            exc,
        )
        return False


def _collect_milestone_sections(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return list of (start_idx, end_idx_exclusive, milestone_id)."""
    sections: list[tuple[int, int, str]] = []
    starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if line.startswith("## Milestone ") and not line.startswith(_ROLLUP_HEADER_PREFIX):
            parts = line[len("## Milestone "):].split(" ", 1)
            mid = parts[0] if parts else ""
            starts.append((i, mid.strip()))
    for idx, (start, mid) in enumerate(starts):
        if idx + 1 < len(starts):
            end = starts[idx + 1][0]
        else:
            # End before Manual notes or at EOF.
            end = len(lines)
            for j in range(start + 1, len(lines)):
                if lines[j].startswith(_MANUAL_NOTES_HEADER) or lines[j].startswith(_ROLLUP_HEADER_PREFIX):
                    end = j
                    break
        sections.append((start, end, mid))
    return sections


def summarize_if_over(
    cwd: str | Path,
    max_lines: int = 500,
    summarize_floor: int = 5,
) -> bool:
    """Collapse oldest milestone sections into a rollup if file exceeds max_lines.

    Keeps `summarize_floor` most recent milestone blocks verbatim. Older
    blocks are replaced by a single `## Milestones 1..N (rolled up)` header
    with one-line summaries. Cumulative tables are preserved untouched.
    """
    try:
        path = _arch_path(cwd)
        if not path.exists():
            return False
        existing = path.read_text(encoding="utf-8")
        lines = existing.splitlines()
        if len(lines) <= max_lines:
            return False
        sections = _collect_milestone_sections(lines)
        if len(sections) <= summarize_floor:
            return False
        rollup_count = len(sections) - summarize_floor
        rolled = sections[:rollup_count]
        summary_lines = [
            f"## Milestones {rolled[0][2]}..{rolled[-1][2]} (rolled up) ({_iso_now()})",
            "",
            "Earlier milestone blocks were collapsed to keep ARCHITECTURE.md under "
            f"{max_lines} lines. Cumulative Entities/Endpoints tables above are the "
            "authoritative record; per-milestone decisions were summarized:",
            "",
        ]
        for _, _, mid in rolled:
            summary_lines.append(f"- {mid}: rolled-up (see git history for full detail)")
        summary_lines.append("")

        first_start = rolled[0][0]
        last_end = rolled[-1][1]
        new_lines = lines[:first_start] + summary_lines + lines[last_end:]
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.info(
            "ARCHITECTURE.md rolled up %d milestone section(s); size %d -> %d lines",
            rollup_count,
            len(lines),
            len(new_lines),
        )
        return True
    except Exception as exc:  # noqa: BLE001 — non-fatal
        logger.warning("architecture_writer.summarize_if_over failed: %s", exc)
        return False


__all__ = [
    "init_if_missing",
    "append_milestone",
    "summarize_if_over",
]
