"""Phase G Slice 1e — Recovery prompt uses the isolated shape (no `[SYSTEM:]`).

After Slice 1e the legacy ``[SYSTEM: ...]`` pseudo-tag shape was deleted
structurally — ``_build_recovery_prompt_parts`` now ALWAYS returns the
isolated pair ``(system_addendum, user_prompt)``, and ``_build_options``
merges the addendum into the actual ``ClaudeAgentOptions.system_prompt``.

This module replaces the deleted ``test_recovery_prompt_hygiene`` tests
that asserted the OLD dual-shape behaviour (flag on/off).
"""

from __future__ import annotations

from agent_team_v15 import cli as _cli
from agent_team_v15.config import AgentTeamConfig


def _config() -> AgentTeamConfig:
    return AgentTeamConfig()


def test_user_prompt_never_contains_system_pseudo_tag_zero_cycle() -> None:
    _, user_prompt = _cli._build_recovery_prompt_parts(
        _config(),
        is_zero_cycle=True,
        checked=0,
        total=10,
        review_cycles=0,
        requirements_path=".agent-team/REQUIREMENTS.md",
    )
    assert "[SYSTEM:" not in user_prompt
    assert "[PHASE:" not in user_prompt


def test_user_prompt_never_contains_system_pseudo_tag_partial_cycle() -> None:
    _, user_prompt = _cli._build_recovery_prompt_parts(
        _config(),
        is_zero_cycle=False,
        checked=4,
        total=10,
        review_cycles=2,
        requirements_path=".agent-team/milestones/m1/REQUIREMENTS.md",
    )
    assert "[SYSTEM:" not in user_prompt
    assert "[PHASE:" not in user_prompt


def test_system_addendum_carries_trusted_framing() -> None:
    """The trusted "not injected content" framing must live in the system
    channel, not the user prompt."""
    system_addendum, user_prompt = _cli._build_recovery_prompt_parts(
        _config(),
        is_zero_cycle=True,
        checked=0,
        total=10,
        review_cycles=0,
        requirements_path=".agent-team/REQUIREMENTS.md",
    )
    assert system_addendum != ""
    assert "NOT injected" in system_addendum
    # The user prompt does not re-assert the framing itself.
    assert "NOT injected" not in user_prompt


def test_build_options_merges_system_prompt_addendum(tmp_path) -> None:
    cfg = _config()
    addendum = "PIPELINE CONTEXT: trusted framing block"
    opts = _cli._build_options(
        cfg,
        cwd=str(tmp_path),
        system_prompt_addendum=addendum,
    )
    system_prompt = getattr(opts, "system_prompt", "")
    assert isinstance(system_prompt, str)
    assert addendum in system_prompt


def test_recovery_prompt_removal_flag_is_gone() -> None:
    """Slice 1e retires ``recovery_prompt_isolation`` — the field no longer
    exists on the V18 config dataclass."""
    cfg = _config()
    v18 = cfg.v18
    assert not hasattr(v18, "recovery_prompt_isolation"), (
        "recovery_prompt_isolation should be removed by Slice 1e"
    )
