"""Phase G Slice 1a — CLAUDE.md opt-in via `setting_sources=["project"]`.

Covers ``_build_options`` in ``agent_team_v15.cli``: when
``v18.claude_md_setting_sources_enabled`` is True AND a ``cwd`` is provided,
``ClaudeAgentOptions`` must carry ``setting_sources=["project"]`` so the
Claude Agent SDK auto-loads the generated-project ``CLAUDE.md``. The
hand-built ``system_prompt`` must NOT be flipped to the ``claude_code``
preset — that would overwrite the D-05 prompt-injection isolation fix in
``cli.py:390-408``. Flag OFF is the legacy behaviour (no field emitted).
"""

from __future__ import annotations

import pytest

from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig


def _config(*, flag: bool = False) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.claude_md_setting_sources_enabled = flag
    return cfg


def test_flag_on_emits_setting_sources_project(tmp_path) -> None:
    """Flag ON + cwd supplied → ``setting_sources=["project"]`` is present."""
    opts = _cli._build_options(_config(flag=True), cwd=str(tmp_path))
    assert getattr(opts, "setting_sources", None) == ["project"]


def test_flag_off_omits_setting_sources(tmp_path) -> None:
    """Default (flag OFF) must leave ``setting_sources`` at SDK default."""
    opts = _cli._build_options(_config(flag=False), cwd=str(tmp_path))
    value = getattr(opts, "setting_sources", None)
    # SDK default is either absent or None — must NOT be the opted-in list.
    assert value != ["project"]


def test_flag_on_without_cwd_does_not_set_setting_sources() -> None:
    """No cwd → no setting_sources (can't point the SDK at a project root)."""
    opts = _cli._build_options(_config(flag=True), cwd=None)
    assert getattr(opts, "setting_sources", None) != ["project"]


def test_flag_on_preserves_custom_system_prompt(tmp_path) -> None:
    """Slice 1a MUST NOT flip the system prompt to the claude_code preset —
    the hand-built prompt carries the D-05 isolation fix and the V18 roles.
    """
    opts = _cli._build_options(_config(flag=True), cwd=str(tmp_path))
    sys_prompt = getattr(opts, "system_prompt", "")
    assert isinstance(sys_prompt, str)
    # Any non-trivial orchestration prompt is long; the D-05 isolation fix
    # embeds a "NOT injected" framing phrase when relevant. The field must
    # be a concrete string, never the SDK's claude_code preset tuple.
    assert sys_prompt != ""
    assert sys_prompt != "claude_code"


def test_flag_on_with_system_prompt_addendum_still_emits_setting_sources(
    tmp_path,
) -> None:
    """Combining an addendum with the opt-in still produces setting_sources."""
    opts = _cli._build_options(
        _config(flag=True),
        cwd=str(tmp_path),
        system_prompt_addendum="PIPELINE CONTEXT: hello",
    )
    assert getattr(opts, "setting_sources", None) == ["project"]
    sys_prompt = getattr(opts, "system_prompt", "")
    assert "PIPELINE CONTEXT: hello" in sys_prompt
