"""Phase G Slice 4f — TEAM_ORCHESTRATOR_SYSTEM_PROMPT rewrite contract.

The orchestrator system prompt at ``agents.py:1668`` was rewritten into
XML sections with explicit rules for GATE 8/9, the injection-re-emit
rule, the empty-milestone rule, the ``<conflicts>`` block, and a
completion criterion stated ONCE (not four times).

This module is the CANONICAL contract for the new shape. Tests here
replace the old ALL-CAPS section-header assertions that were deleted
across ``test_agents.py``, ``test_prompt_integrity.py``,
``test_department_model.py``, ``test_department_integration.py``,
``test_enterprise_final_simulation.py``, and ``test_critical_wiring_fix.py``.
"""

from __future__ import annotations

from agent_team_v15.agents import TEAM_ORCHESTRATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# XML section structure
# ---------------------------------------------------------------------------


def test_prompt_opens_with_role_xml_section() -> None:
    assert "<role>" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    assert "</role>" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


def test_prompt_includes_every_required_xml_section() -> None:
    for section in (
        "<role>",
        "<wave_sequence>",
        "<delegation_workflow>",
        "<gates>",
        "<escalation>",
        "<completion>",
        "<enterprise_mode>",
        "<conflicts>",
    ):
        assert section in TEAM_ORCHESTRATOR_SYSTEM_PROMPT, f"Missing {section}"


# ---------------------------------------------------------------------------
# GATE 8 / GATE 9 rules MUST live in the prompt body
# ---------------------------------------------------------------------------


def test_gate_8_rule_present_in_body() -> None:
    """GATE 8 must block Wave B when Wave A.5 verdict is FAIL with CRITICAL."""
    assert "GATE 8" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    # Rule describes Wave A.5 verdict → Wave B gating.
    assert "Wave A.5" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    assert "Wave B" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


def test_gate_9_rule_present_in_body() -> None:
    """GATE 9 must block Wave E when Wave T.5 has CRITICAL gaps."""
    assert "GATE 9" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    assert "Wave T.5" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    assert "Wave E" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


def test_gate_8_references_rerun_policy_max_one() -> None:
    """Max 1 re-run of Wave A is explicit in the prompt body."""
    assert "max 1 re-run" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


def test_gate_9_references_iteration_2_loopback() -> None:
    """T.5 gap loops back to Wave T iteration 2."""
    assert "iteration 2" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Injection-re-emit + empty-milestone rules (escalation path)
# ---------------------------------------------------------------------------


def test_injection_re_emit_rule_present() -> None:
    """When a phase lead rejects a prompt with an injection-like reason, the
    orchestrator re-emits via system-addendum shape (Slice 1e)."""
    lowered = TEAM_ORCHESTRATOR_SYSTEM_PROMPT.lower()
    assert "injection" in lowered
    assert "system-addendum" in lowered or "system addendum" in lowered


def test_empty_milestone_rule_present() -> None:
    """Empty milestones are planner bugs — log to PLANNER_ERRORS.md + skip."""
    assert "Empty milestone" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT or "empty milestone" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    assert "PLANNER_ERRORS" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# <conflicts> block — rules about $orchestrator_st_instructions
# ---------------------------------------------------------------------------


def test_conflicts_block_declares_prompt_wins() -> None:
    """If `$orchestrator_st_instructions` contradicts a gate, the gate wins."""
    assert "<conflicts>" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    assert "$orchestrator_st_instructions" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    assert "gate in this prompt WINS" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# "Build is COMPLETE" stated exactly ONCE (not 4x — old redundancy was a
# context-compression regression per Slice 4f design doc)
# ---------------------------------------------------------------------------


def test_build_is_complete_phrase_appears_exactly_once() -> None:
    phrase = "Build is COMPLETE"
    count = TEAM_ORCHESTRATOR_SYSTEM_PROMPT.count(phrase)
    assert count == 1, f"Expected 1 occurrence of {phrase!r}, got {count}"


def test_completion_block_requires_all_three_leads() -> None:
    """The completion criterion names all three terminal leads."""
    # The three-way AND is asserted in the <completion> block.
    assert "review-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    assert "testing-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT
    assert "audit-lead" in TEAM_ORCHESTRATOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Wave sequence reflects the post-Phase-G pipeline
# ---------------------------------------------------------------------------


def test_wave_sequence_block_names_all_phase_g_waves() -> None:
    for wave in ("Wave A", "Wave A.5", "Wave Scaffold", "Wave B", "Wave C",
                 "Wave D", "Wave T", "Wave T.5", "Wave E"):
        assert wave in TEAM_ORCHESTRATOR_SYSTEM_PROMPT, f"Missing {wave}"
