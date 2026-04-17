"""Phase G Slice 5e — TEST_AUDITOR prompt consumes Wave T.5 gap list.

``audit_prompts._append_wave_t5_gap_rule_if_enabled`` appends the
``## Phase G Slice 5e — Wave T.5 gap-list consumption`` section to the
TEST auditor prompt when
``v18.wave_t5_gap_list_inject_test_auditor=True``. Other auditors
(``requirements``, ``technical``, ``interface``, ``mcp_library``,
``prd_fidelity``, ``comprehensive``, ``scorer``) are untouched.
"""

from __future__ import annotations

from agent_team_v15 import audit_prompts as _ap
from agent_team_v15.audit_prompts import (
    TEST_AUDITOR_PROMPT,
    _append_wave_t5_gap_rule_if_enabled,
    get_scoped_auditor_prompt,
)
from agent_team_v15.config import AgentTeamConfig


def _config(*, flag: bool) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_t5_gap_list_inject_test_auditor = flag
    return cfg


def test_append_rule_is_identity_when_flag_off() -> None:
    result = _append_wave_t5_gap_rule_if_enabled(
        TEST_AUDITOR_PROMPT, "test", _config(flag=False)
    )
    assert result == TEST_AUDITOR_PROMPT


def test_append_rule_adds_consumption_section_when_flag_on() -> None:
    result = _append_wave_t5_gap_rule_if_enabled(
        TEST_AUDITOR_PROMPT, "test", _config(flag=True)
    )
    assert result != TEST_AUDITOR_PROMPT
    assert "Wave T.5 gap-list consumption" in result
    assert "WAVE_T5_GAPS.json" in result


def test_append_rule_does_not_touch_other_auditors() -> None:
    cfg = _config(flag=True)
    for auditor in (
        "requirements",
        "technical",
        "interface",
        "mcp_library",
        "prd_fidelity",
        "comprehensive",
        "scorer",
    ):
        base = _ap.AUDIT_PROMPTS[auditor]
        result = _append_wave_t5_gap_rule_if_enabled(base, auditor, cfg)
        assert result == base, f"{auditor} was wrongly decorated"


def test_append_rule_noop_when_config_missing() -> None:
    result = _append_wave_t5_gap_rule_if_enabled(
        TEST_AUDITOR_PROMPT, "test", None
    )
    assert result == TEST_AUDITOR_PROMPT


def test_get_scoped_auditor_prompt_applies_rule_for_test() -> None:
    """The scoped wrapper composes the Slice 5e injection with the audit-scope
    preamble so callers get a single formatted prompt."""
    prompt = get_scoped_auditor_prompt(
        "test",
        scope=None,
        config=_config(flag=True),
    )
    assert "WAVE_T5_GAPS.json" in prompt
    # HIGH+ severity rule present.
    assert "HIGH+" in prompt


def test_get_scoped_auditor_prompt_test_auditor_matches_base_when_flag_off() -> None:
    prompt = get_scoped_auditor_prompt(
        "test",
        scope=None,
        config=_config(flag=False),
    )
    assert "WAVE_T5_GAPS.json" not in prompt
