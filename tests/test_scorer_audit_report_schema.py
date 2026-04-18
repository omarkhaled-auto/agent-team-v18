"""Phase G Slice 1f — SCORER_AGENT_PROMPT enumerates all 17 AUDIT_REPORT keys.

The scorer prompt at ``audit_prompts.py:1292`` prepends an
``<output_schema>`` block listing every top-level key the downstream
parser requires. The keys are:

    schema_version, generated, milestone, audit_cycle, overall_score,
    max_score, verdict, threshold_pass, auditors_run, raw_finding_count,
    deduplicated_finding_count, findings, fix_candidates, by_severity,
    by_file, by_requirement, audit_id

Regression context: build-j:1423 failed because the scorer emitted a
report missing ``audit_id``, and the parser's fail-closed path was invoked.
This test guards against any subtraction from the canonical list.
"""

from __future__ import annotations

from agent_team_v15.audit_prompts import SCORER_AGENT_PROMPT, AUDIT_PROMPTS


CANONICAL_17_KEYS = (
    "schema_version",
    "generated",
    "milestone",
    "audit_cycle",
    "overall_score",
    "max_score",
    "verdict",
    "threshold_pass",
    "auditors_run",
    "raw_finding_count",
    "deduplicated_finding_count",
    "findings",
    "fix_candidates",
    "by_severity",
    "by_file",
    "by_requirement",
    "audit_id",
)


def test_all_17_keys_appear_verbatim_in_scorer_prompt() -> None:
    for key in CANONICAL_17_KEYS:
        assert key in SCORER_AGENT_PROMPT, f"Missing key in prompt: {key!r}"


def test_scorer_prompt_declares_17_count_explicitly() -> None:
    assert "17 keys" in SCORER_AGENT_PROMPT


def test_output_schema_block_present() -> None:
    assert "<output_schema>" in SCORER_AGENT_PROMPT
    assert "</output_schema>" in SCORER_AGENT_PROMPT


def test_scorer_prompt_registered_in_audit_prompts_registry() -> None:
    """Ensures downstream callers can still look up the updated prompt."""
    assert AUDIT_PROMPTS.get("scorer") is SCORER_AGENT_PROMPT


def test_audit_id_guidance_references_parser_failure() -> None:
    """build-j:1423 motivation: ``audit_id`` must be flagged REQUIRED so the
    prompt cannot silently drop it."""
    assert "audit_id" in SCORER_AGENT_PROMPT
    # The prompt explicitly warns the model that missing keys fail the parser.
    assert "parser fails" in SCORER_AGENT_PROMPT or "REQUIRED" in SCORER_AGENT_PROMPT
