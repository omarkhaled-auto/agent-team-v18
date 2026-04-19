"""Phase H1b — Wave A schema constants + validator unit tests.

Covers :mod:`wave_a_schema` (allowlist / disallow-list / references) and
:mod:`wave_a_schema_validator` (heading parse, reason-named rejections,
undeclared reference detection, frozen-dataclass result shape).
"""

from __future__ import annotations

import re

import pytest

from agent_team_v15 import wave_a_schema
from agent_team_v15.wave_a_schema_validator import (
    MissingRequiredSection,
    SchemaValidationResult,
    SectionRejection,
    UndeclaredReference,
    validate_wave_a_output,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_passing_body() -> str:
    """Smallest ARCHITECTURE.md body that should pass the default validator.

    Covers the six always-required canonical sections plus
    ``seams_wave_d`` (conditional-required for ``full_stack``/``frontend``
    templates — the validator default requires it).
    """

    return "\n".join(
        [
            "## Scope recap",
            "Milestone milestone-1 — foundation.",
            "",
            "## What Wave A produced",
            "- schema.prisma",
            "",
            "## Seams Wave B must populate",
            "- apps/api/src/main.ts",
            "",
            "## Seams Wave D must populate",
            "- apps/web/src/layout.tsx",
            "",
            "## Seams Wave T must populate",
            "- jest.config.ts",
            "",
            "## Seams Wave E must populate",
            "- no hardcoded strings",
            "",
            "## Open questions",
            "- None.",
            "",
        ]
    )


# ---------------------------------------------------------------------------
# Schema-coverage structural tests (§3)
# ---------------------------------------------------------------------------


def test_allowed_sections_is_non_empty_and_keyed_by_canonical() -> None:
    assert isinstance(wave_a_schema.ALLOWED_SECTIONS, (dict, type(wave_a_schema.ALLOWED_SECTIONS)))
    assert len(wave_a_schema.ALLOWED_SECTIONS) >= 1
    for canonical, aliases in wave_a_schema.ALLOWED_SECTIONS.items():
        assert isinstance(canonical, str) and canonical
        assert isinstance(aliases, tuple)
        assert all(isinstance(a, str) and a for a in aliases)


def test_disallowed_section_reasons_every_entry_has_reason_text() -> None:
    assert len(wave_a_schema.DISALLOWED_SECTION_REASONS) >= 1
    for substrings, reason_code, message in wave_a_schema.DISALLOWED_SECTION_REASONS:
        assert isinstance(substrings, tuple) and substrings
        assert isinstance(reason_code, str) and reason_code
        assert isinstance(message, str) and message.strip()


def test_allowed_references_is_non_empty_tuple() -> None:
    assert isinstance(wave_a_schema.ALLOWED_REFERENCES, tuple)
    assert len(wave_a_schema.ALLOWED_REFERENCES) >= 1
    assert all(isinstance(r, str) and r for r in wave_a_schema.ALLOWED_REFERENCES)


def test_required_sections_subset_of_allowed() -> None:
    assert wave_a_schema.REQUIRED_SECTIONS.issubset(
        set(wave_a_schema.ALLOWED_SECTIONS.keys())
    )


def test_pattern_ids_are_distinct_strings() -> None:
    assert wave_a_schema.PATTERN_SECTION_REJECTION
    assert wave_a_schema.PATTERN_UNDECLARED_REFERENCE
    assert (
        wave_a_schema.PATTERN_SECTION_REJECTION
        != wave_a_schema.PATTERN_UNDECLARED_REFERENCE
    )


# STRUCTURAL anti-pattern check: the schema constants and validator must
# not hold any mutable module-level retry state. Dedupe sets in cli.py
# are intentionally allowed (they guard against noisy log spam, not
# retry-count state) — only the schema/validator modules are scanned
# here per the plan directive.
def test_schema_modules_have_no_mutable_module_globals() -> None:
    import inspect

    for mod in (wave_a_schema,):
        src = inspect.getsource(mod)
        # Match lines starting with ``_[A-Z_]+ =`` that are NOT Final[...]
        # or frozenset / tuple definitions — those are immutable constants.
        for line in src.splitlines():
            stripped = line.strip()
            m = re.match(r"^(_[A-Z_]+)\s*=", stripped)
            if not m:
                continue
            # Allow Final[...] / frozenset(...) / tuple literal patterns.
            assert (
                ": Final" in line
                or "frozenset(" in stripped
                or stripped.endswith("(")
                or "tuple(" in stripped
            ), (
                f"Mutable module-level global in {mod.__name__}: {stripped!r}"
            )


# ---------------------------------------------------------------------------
# Allowlist enforcement (§4)
# ---------------------------------------------------------------------------


def test_minimal_passing_body_yields_no_findings() -> None:
    result = validate_wave_a_output(
        _minimal_passing_body(),
        "milestone-1",
        architecture_path="/tmp/ARCHITECTURE.md",
    )
    assert not result.has_findings
    assert result.disallowed_sections == []
    assert result.missing_required == []
    assert result.undeclared_references == []


def test_unknown_section_rejected_with_allowed_list_in_message() -> None:
    body = _minimal_passing_body() + "\n## Invented section\nbody\n"
    result = validate_wave_a_output(body, "milestone-1")
    assert result.has_findings
    codes = {r.reason_code for r in result.disallowed_sections}
    assert "UNKNOWN_SECTION" in codes
    # Message should enumerate (mention) the canonical allowed keys.
    msgs = " ".join(r.message for r in result.disallowed_sections)
    for canonical in wave_a_schema.ALLOWED_SECTIONS:
        assert canonical in msgs, (
            f"UNKNOWN_SECTION rejection message missing canonical key {canonical!r}: {msgs!r}"
        )


def test_design_token_section_rejected_by_named_reason() -> None:
    body = _minimal_passing_body() + "\n## Design-token contract\n- #FF00AA\n"
    result = validate_wave_a_output(body, "milestone-1")
    assert result.has_findings
    codes = {r.reason_code for r in result.disallowed_sections}
    assert "DESIGN_TOKENS_DUPLICATE" in codes
    msg = next(
        r.message for r in result.disallowed_sections
        if r.reason_code == "DESIGN_TOKENS_DUPLICATE"
    )
    # Message must carry the exact teaching text.
    assert "UI_DESIGN_TOKENS.json" in msg
    assert "Phase G Slice 4c" in msg


def test_every_disallowed_reason_entry_produces_rejection() -> None:
    """Each DISALLOWED_SECTION_REASONS entry triggers a rejection carrying
    its exact teaching text when an H2 matches any of its substrings."""
    for substrings, reason_code, message in wave_a_schema.DISALLOWED_SECTION_REASONS:
        trigger = substrings[0]
        body = (
            _minimal_passing_body()
            + f"\n## {trigger.title()}\nbody line\n"
        )
        result = validate_wave_a_output(body, "milestone-1")
        matching = [
            r for r in result.disallowed_sections if r.reason_code == reason_code
        ]
        assert matching, (
            f"Expected reason_code={reason_code!r} for trigger={trigger!r}, "
            f"got {[r.reason_code for r in result.disallowed_sections]}"
        )
        assert any(message == m.message for m in matching), (
            f"Rejection message for {reason_code!r} did not match the teaching "
            f"text exactly. Got: {[m.message for m in matching]!r}"
        )


def test_missing_required_section_yields_missing_required_finding() -> None:
    # Drop "## Open questions" — still a required section.
    body = "\n".join(
        [
            "## Scope recap",
            "intent.",
            "",
            "## What Wave A produced",
            "- f",
            "",
            "## Seams Wave B must populate",
            "- x",
            "",
            "## Seams Wave D must populate",
            "- x",
            "",
            "## Seams Wave T must populate",
            "- x",
            "",
            "## Seams Wave E must populate",
            "- x",
            "",
        ]
    )
    result = validate_wave_a_output(body, "milestone-1")
    assert result.has_findings
    canonical_missing = {m.canonical for m in result.missing_required}
    assert "open_questions" in canonical_missing


# ---------------------------------------------------------------------------
# Undeclared reference detection (§6)
# ---------------------------------------------------------------------------


def test_legit_allowed_reference_token_accepted() -> None:
    body = _minimal_passing_body() + (
        "\n## Fields, indexes, cascades\n"
        "Cite via {scaffolded_files} and {milestone_id}.\n"
    )
    result = validate_wave_a_output(body, "milestone-1")
    assert result.undeclared_references == []


def test_fabricated_dollar_placeholder_rejected() -> None:
    body = _minimal_passing_body() + "\nPort: ${API_PORT}\n"
    result = validate_wave_a_output(body, "milestone-1")
    assert result.undeclared_references, "expected undeclared reference finding"
    tokens = {u.token for u in result.undeclared_references}
    assert any("API_PORT" in t for t in tokens), tokens
    # Pattern id threaded through review dict.
    review = result.to_review_dict()
    pattern_ids = {f.get("pattern_id") for f in review["findings"]}
    assert wave_a_schema.PATTERN_UNDECLARED_REFERENCE in pattern_ids
    undecl = next(
        f for f in review["findings"] if f.get("pattern_id") == wave_a_schema.PATTERN_UNDECLARED_REFERENCE
    )
    assert undecl["severity"] == "MEDIUM"
    assert "API_PORT" in undecl["ref"]


def test_inject_future_milestone_rejected() -> None:
    body = _minimal_passing_body() + "\n<inject:future_milestone>\n"
    result = validate_wave_a_output(body, "milestone-1")
    tokens = {u.token for u in result.undeclared_references}
    assert "<inject:future_milestone>" in tokens


# ---------------------------------------------------------------------------
# Result shape + to_review_dict
# ---------------------------------------------------------------------------


def test_result_subcomponent_dataclasses_are_frozen() -> None:
    rej = SectionRejection(
        heading="x", canonical_match="x", reason_code="Y", message="z"
    )
    with pytest.raises(Exception):
        rej.heading = "changed"  # type: ignore[misc]
    miss = MissingRequiredSection(canonical="k", example_heading="## K")
    with pytest.raises(Exception):
        miss.canonical = "other"  # type: ignore[misc]
    ref = UndeclaredReference(token="{x}", severity="MEDIUM")
    with pytest.raises(Exception):
        ref.token = "{y}"  # type: ignore[misc]


def test_to_review_dict_shape() -> None:
    body = _minimal_passing_body() + "\n## Design-token contract\n- #hex\n"
    result = validate_wave_a_output(body, "milestone-1")
    review = result.to_review_dict()
    assert review["milestone_id"] == "milestone-1"
    assert review["verdict"] == "FAIL"
    assert isinstance(review["findings"], list) and review["findings"]
    first = review["findings"][0]
    assert set(first.keys()) >= {
        "category",
        "ref",
        "severity",
        "issue",
        "pattern_id",
    }
    assert first["pattern_id"] == wave_a_schema.PATTERN_SECTION_REJECTION


def test_to_review_dict_passing_verdict_when_no_findings() -> None:
    result = validate_wave_a_output(_minimal_passing_body(), "milestone-1")
    review = result.to_review_dict()
    assert review["verdict"] == "PASS"
    assert review["findings"] == []


def test_empty_content_is_skipped_not_failed() -> None:
    result = validate_wave_a_output("", "milestone-1")
    assert not result.has_findings
    assert result.skipped_reason
    review = result.to_review_dict()
    assert review["verdict"] == "PASS"
    assert review["skipped_reason"]


# ---------------------------------------------------------------------------
# Conditional requirement interaction
# ---------------------------------------------------------------------------


def test_require_schema_body_flips_schema_section_required() -> None:
    # Same body that passed in the minimal test; now require schema_body.
    result = validate_wave_a_output(
        _minimal_passing_body(),
        "milestone-1",
        require_schema_body=True,
    )
    canonicals = {m.canonical for m in result.missing_required}
    assert "schema_body" in canonicals


def test_require_seams_wave_d_false_removes_requirement() -> None:
    body = "\n".join(
        [
            "## Scope recap",
            "a",
            "",
            "## What Wave A produced",
            "- x",
            "",
            "## Seams Wave B must populate",
            "- x",
            "",
            "## Seams Wave T must populate",
            "- x",
            "",
            "## Seams Wave E must populate",
            "- x",
            "",
            "## Open questions",
            "- None",
            "",
        ]
    )
    result = validate_wave_a_output(
        body, "milestone-1", require_seams_wave_d=False
    )
    canonicals = {m.canonical for m in result.missing_required}
    assert "seams_wave_d" not in canonicals


def test_allowed_references_override_respected() -> None:
    body = _minimal_passing_body() + "\n{custom_token}\n"
    # Override — add custom_token as an allowed reference.
    result = validate_wave_a_output(
        body,
        "milestone-1",
        allowed_references_override=list(wave_a_schema.ALLOWED_REFERENCES)
        + ["custom_token"],
    )
    tokens = {u.token for u in result.undeclared_references}
    assert "{custom_token}" not in tokens
