"""Phase G Slice 1d — CLAUDE.md / AGENTS.md writer + 32-KiB enforcement.

Covers ``agent_team_v15.constitution_writer``:

- ``write_claude_md`` / ``write_agents_md`` / ``write_codex_config_toml``
  render the templates to disk at the expected paths.
- Runtime 32 KiB enforcement: when AGENTS.md renders larger than the
  configured cap, the writer truncates at the last complete ``## `` section
  boundary and emits a warning; if truncation cannot land on a boundary,
  it raises ``AgentsMdOverflowError``.
- ``write_all_if_enabled`` is gated by
  ``v18.claude_md_autogenerate`` / ``v18.agents_md_autogenerate`` flags.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import constitution_writer as _cw
from agent_team_v15.config import AgentTeamConfig


def test_write_claude_md_creates_file_at_root(tmp_path: Path) -> None:
    path = _cw.write_claude_md(tmp_path)
    assert path == tmp_path / "CLAUDE.md"
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    # Must contain at least one R8 invariant marker.
    assert "# Claude Code" in content
    assert "packages/api-client" in content


def test_write_agents_md_creates_file_at_root(tmp_path: Path) -> None:
    path = _cw.write_agents_md(tmp_path)
    assert path == tmp_path / "AGENTS.md"
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "# AGENTS.md" in content


def test_write_agents_md_truncates_at_section_boundary_on_overflow(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the rendered content exceeds ``max_bytes``, the writer must
    drop to the last complete ``^## `` boundary and warn."""
    caplog.set_level(logging.WARNING, logger="agent_team_v15.constitution_writer")
    # Max_bytes set intentionally small — 600 bytes is less than the
    # current rendered AGENTS.md template (~1200-1400 bytes with the
    # default stack), which forces the truncation path.
    path = _cw.write_agents_md(tmp_path, max_bytes=600)
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "truncated at section boundary" in content.lower()
    assert len(content.encode("utf-8")) <= 1024
    # Warning emitted with both sizes.
    assert any(
        "AGENTS.md rendered" in rec.getMessage()
        and "truncating" in rec.getMessage()
        for rec in caplog.records
    )


def test_write_agents_md_raises_when_boundary_unfindable(tmp_path: Path) -> None:
    """An absurdly small cap that cannot reach any ``## `` boundary raises
    ``AgentsMdOverflowError`` so callers can react (e.g., skip the write)."""
    with pytest.raises(_cw.AgentsMdOverflowError):
        _cw.write_agents_md(tmp_path, max_bytes=10)


def test_write_codex_config_toml_writes_under_dot_codex(tmp_path: Path) -> None:
    path = _cw.write_codex_config_toml(tmp_path)
    assert path == tmp_path / ".codex" / "config.toml"
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "project_doc_max_bytes = 65536" in content


def test_write_all_flag_off_by_default_does_nothing(tmp_path: Path) -> None:
    cfg = AgentTeamConfig()
    # Default flags are off.
    result = _cw.write_all_if_enabled(tmp_path, cfg)
    assert result == {"claude_md": False, "agents_md": False, "codex_config": False}
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".codex" / "config.toml").exists()


def test_write_all_with_flags_on_creates_all_three(tmp_path: Path) -> None:
    cfg = AgentTeamConfig()
    cfg.v18.claude_md_autogenerate = True
    cfg.v18.agents_md_autogenerate = True
    result = _cw.write_all_if_enabled(tmp_path, cfg)
    assert result == {"claude_md": True, "agents_md": True, "codex_config": True}
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / ".codex" / "config.toml").is_file()


def test_write_all_agents_md_overflow_is_advisory(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The advisory contract: overflow does not halt the pipeline — it logs
    and skips the AGENTS.md file."""
    caplog.set_level(logging.ERROR, logger="agent_team_v15.constitution_writer")
    cfg = AgentTeamConfig()
    cfg.v18.claude_md_autogenerate = True
    cfg.v18.agents_md_autogenerate = True
    cfg.v18.agents_md_max_bytes = 10  # un-truncatable
    result = _cw.write_all_if_enabled(tmp_path, cfg)
    assert result["agents_md"] is False
    # CLAUDE.md still wrote fine; codex config still wrote fine.
    assert result["claude_md"] is True
    assert result["codex_config"] is True
    # Error log surfaced the overflow.
    assert any(
        "agents_md_max_bytes" in rec.getMessage().lower()
        or "overflow" in rec.getMessage().lower()
        for rec in caplog.records
    )
