"""Phase G — audit-prompt 30-finding cap.

Wave 2b Part 11 prescribes a two-block continuation emission for audit
prompts that overflow the 30-finding cap (MEDIUM findings past the cap
surface in a ``<findings_continuation>`` second JSON block). The
continuation block itself was DEFERRED during impl-plan review
(wave1b.md §7) — the current shared cap rule in ``audit_prompts``
keeps the single-block shape and caps at 30 findings with a
CRITICAL/HIGH filter beyond.

These tests freeze the current contract so a future Phase H upgrade to
two-block emission is an explicit change (not a silent drift).
"""

from __future__ import annotations

from agent_team_v15.audit_prompts import AUDIT_PROMPTS


FILTER_CAP_PHRASE = "Cap output at 30 findings"


def test_shared_cap_rule_present_in_requirements_auditor() -> None:
    """The shared ``_SHARED_AUDITOR_FORMAT_RULES`` (or equivalent) flows
    into the requirements auditor prompt body."""
    prompt = AUDIT_PROMPTS["requirements"]
    assert FILTER_CAP_PHRASE in prompt
    # Rule qualifies the filter when the cap overflows.
    assert "CRITICAL and HIGH" in prompt


def test_cap_rule_absent_continuation_block_per_deferred_decision() -> None:
    """Wave 2b Part 11's two-block ``<findings_continuation>`` emission was
    DEFERRED (see docs/plans/2026-04-17-phase-g-implplan-review-wave1b.md §7).
    Until Phase H lands, the continuation block must NOT appear in any
    auditor prompt, so the current single-block parser stays authoritative.
    """
    for name, prompt in AUDIT_PROMPTS.items():
        assert "<findings_continuation>" not in prompt, (
            f"{name}: continuation block was deferred to Phase H"
        )


def test_every_auditor_carries_the_cap_rule() -> None:
    """Every non-scorer auditor inherits the shared cap rule (scorer itself
    emits the consolidated report, not per-auditor findings)."""
    for name in (
        "requirements",
        "technical",
        "interface",
        "test",
        "mcp_library",
        "prd_fidelity",
        "comprehensive",
    ):
        assert FILTER_CAP_PHRASE in AUDIT_PROMPTS[name], (
            f"{name} missing 30-finding cap rule"
        )


def test_scorer_does_not_carry_the_cap_rule() -> None:
    """The scorer aggregates across auditors — it does not produce findings
    directly — so the cap rule does not apply to its prompt."""
    assert FILTER_CAP_PHRASE not in AUDIT_PROMPTS["scorer"]
