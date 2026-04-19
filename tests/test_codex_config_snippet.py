"""Phase G Slice 5f - `.codex/config.toml` at project root.

The constitution writer drops a minimal Codex config snippet at
``<cwd>/.codex/config.toml`` raising Codex's default AGENTS.md byte cap
from 32 KiB to 64 KiB (per Wave 1c sec. 4.3 / /openai/codex#7138).

The file is written whenever ``v18.agents_md_autogenerate=True`` -
Codex's behaviour is tied to the AGENTS.md lifecycle.
"""

from __future__ import annotations

from pathlib import Path

from agent_team_v15 import constitution_writer as _cw
from agent_team_v15.constitution_templates import render_codex_config_toml
from agent_team_v15.config import AgentTeamConfig


def test_render_codex_config_toml_uses_top_level_key() -> None:
    toml = render_codex_config_toml()
    assert "[features]" not in toml
    assert toml == (
        "# Raise AGENTS.md cap from 32 KiB default to 64 KiB (Phase G Slice 1d).\n"
        "project_doc_max_bytes = 65536\n"
    )


def test_write_codex_config_toml_at_dot_codex(tmp_path: Path) -> None:
    target = _cw.write_codex_config_toml(tmp_path)
    assert target == tmp_path / ".codex" / "config.toml"
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert "[features]" not in content
    assert content == (
        "# Raise AGENTS.md cap from 32 KiB default to 64 KiB (Phase G Slice 1d).\n"
        "project_doc_max_bytes = 65536\n"
    )


def test_write_codex_config_toml_creates_parent_dir(tmp_path: Path) -> None:
    """No need for caller to pre-create ``.codex/`` - writer handles it."""
    assert not (tmp_path / ".codex").exists()
    _cw.write_codex_config_toml(tmp_path)
    assert (tmp_path / ".codex").is_dir()


def test_write_all_if_enabled_writes_codex_config_with_agents_md(
    tmp_path: Path,
) -> None:
    cfg = AgentTeamConfig()
    cfg.v18.agents_md_autogenerate = True
    result = _cw.write_all_if_enabled(tmp_path, cfg)
    assert result["agents_md"] is True
    assert result["codex_config"] is True
    assert (tmp_path / ".codex" / "config.toml").is_file()


def test_write_all_if_enabled_skips_codex_config_when_agents_md_off(
    tmp_path: Path,
) -> None:
    cfg = AgentTeamConfig()
    cfg.v18.agents_md_autogenerate = False
    result = _cw.write_all_if_enabled(tmp_path, cfg)
    assert result["codex_config"] is False
    assert not (tmp_path / ".codex" / "config.toml").exists()
