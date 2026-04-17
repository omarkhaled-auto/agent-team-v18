"""CLAUDE.md / AGENTS.md / .codex/config.toml writer (Phase G Slice 1d).

Renders templates from `constitution_templates` and writes them to the
generated-project root on pipeline startup (before M1 dispatch). All writes
are flag-gated (defaults OFF); failure is advisory — the pipeline never
blocks on a missing constitution file.

Runtime size check: per Wave 1c §4.3 (silent-truncation warning from
/openai/codex#7138), the AGENTS.md renderer must enforce
`v18.agents_md_max_bytes`. On overflow the writer truncates to the last
complete top-level section and emits a warning; it raises
`AgentsMdOverflowError` only if truncation fails.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import constitution_templates as _templates

logger = logging.getLogger(__name__)


class AgentsMdOverflowError(RuntimeError):
    """Raised when AGENTS.md exceeds `agents_md_max_bytes` and cannot be
    safely truncated to a complete section boundary."""


def _resolve_stack(config: Any, cwd: str | Path) -> dict[str, Any]:
    stack: dict[str, Any] = {"project_name": Path(cwd).name or "project"}
    try:
        from .stack_contract import load_stack_contract

        resolved = load_stack_contract(str(cwd))
        if resolved is not None:
            contract = resolved.to_dict()
            for key in ("backend", "frontend", "api_client", "tests", "orm", "test_framework"):
                value = contract.get(key)
                if value:
                    stack[key] = value
    except Exception:  # noqa: BLE001 — optional metadata
        pass
    return stack


def write_claude_md(cwd: str | Path, stack: dict[str, Any] | None = None) -> Path:
    target = Path(cwd) / "CLAUDE.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_templates.render_claude_md(stack), encoding="utf-8")
    return target


def _truncate_to_section_boundary(content: str, max_bytes: int) -> str:
    """Truncate `content` to the last complete `^## ` section within `max_bytes`."""
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content
    # Walk sections (top-level `## ` headers) and keep the last boundary that
    # fits within max_bytes.
    lines = content.splitlines(keepends=True)
    cumulative = 0
    last_safe_index = 0
    for idx, line in enumerate(lines):
        cumulative += len(line.encode("utf-8"))
        if cumulative > max_bytes:
            break
        if line.startswith("## "):
            last_safe_index = idx
    if last_safe_index == 0:
        raise AgentsMdOverflowError(
            f"AGENTS.md cannot be truncated to a section boundary under {max_bytes} bytes"
        )
    truncated = "".join(lines[:last_safe_index])
    truncated += (
        "\n<!-- AGENTS.md truncated at section boundary; see source templates "
        "for full content. -->\n"
    )
    return truncated


def write_agents_md(
    cwd: str | Path,
    stack: dict[str, Any] | None = None,
    max_bytes: int = 32768,
) -> Path:
    """Write AGENTS.md with runtime size enforcement."""
    content = _templates.render_agents_md(stack)
    encoded_size = len(content.encode("utf-8"))
    if encoded_size > max_bytes:
        logger.warning(
            "AGENTS.md rendered %d bytes > cap %d; truncating to last complete section.",
            encoded_size,
            max_bytes,
        )
        content = _truncate_to_section_boundary(content, max_bytes)
    target = Path(cwd) / "AGENTS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def write_codex_config_toml(cwd: str | Path) -> Path:
    target = Path(cwd) / ".codex" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_templates.render_codex_config_toml(), encoding="utf-8")
    return target


def write_all_if_enabled(cwd: str | Path, config: Any) -> dict[str, bool]:
    """Consult flags and write whatever is enabled. Never raises.

    Returns `{"claude_md": bool, "agents_md": bool, "codex_config": bool}`.
    """
    result = {"claude_md": False, "agents_md": False, "codex_config": False}
    v18 = getattr(config, "v18", None)
    stack = _resolve_stack(config, cwd)

    if getattr(v18, "claude_md_autogenerate", False):
        try:
            write_claude_md(cwd, stack)
            result["claude_md"] = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("constitution_writer.write_claude_md failed: %s", exc)

    if getattr(v18, "agents_md_autogenerate", False):
        try:
            max_bytes = int(getattr(v18, "agents_md_max_bytes", 32768))
            write_agents_md(cwd, stack, max_bytes=max_bytes)
            result["agents_md"] = True
        except AgentsMdOverflowError:
            logger.error(
                "AGENTS.md overflowed agents_md_max_bytes and could not be truncated; "
                "skipping write. Increase agents_md_max_bytes or shrink template."
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("constitution_writer.write_agents_md failed: %s", exc)

    # The Codex config snippet ships alongside AGENTS.md when auto-generated
    # (raises Codex's 32 KiB cap to 64 KiB per Wave 1c §4.3).
    if getattr(v18, "agents_md_autogenerate", False):
        try:
            write_codex_config_toml(cwd)
            result["codex_config"] = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("constitution_writer.write_codex_config_toml failed: %s", exc)

    return result


__all__ = [
    "AgentsMdOverflowError",
    "write_claude_md",
    "write_agents_md",
    "write_codex_config_toml",
    "write_all_if_enabled",
]
