"""Phase H1b — Wave A ARCHITECTURE.md schema constants.

Load-bearing allowlist, disallow-list, and reference set derived from
``docs/plans/phase-h1b-allowlist-evidence.md`` §4-§6. These values are
consumed by :mod:`wave_a_schema_validator` to decide whether the
``.agent-team/milestone-{milestone_id}/ARCHITECTURE.md`` file Wave A
emits drifts from the M1-first allowlist.

No module-level mutable state (see Wave 2A anti-pattern #1).
"""

from __future__ import annotations

from typing import Final, Mapping


# Wave-letter templates for conditional required sections. Kept here so
# the validator and the prompt renderer share one source of truth.

_SEAMS_WAVE_B_ALIASES: Final[tuple[str, ...]] = (
    "seams wave b must populate",
    "seams wave b will populate",
    "backend service seams (owned by wave b)",
    "service-layer seams wave b populates",
    "seams wave b",
)

_SEAMS_WAVE_D_ALIASES: Final[tuple[str, ...]] = (
    "seams wave d must populate",
    "seams wave d will populate",
    "frontend seams (owned by wave d)",
    "frontend seams wave d populates",
    "seams wave d",
)

_SEAMS_WAVE_T_ALIASES: Final[tuple[str, ...]] = (
    "seams wave t must populate",
    "seams wave t will populate",
    "seams wave t",
)

_SEAMS_WAVE_E_ALIASES: Final[tuple[str, ...]] = (
    "seams wave e must populate",
    "seams wave e must enforce",
    "seams wave e will populate",
    "seams wave e will enforce",
    "seams wave e",
)

_SCHEMA_BODY_ALIASES: Final[tuple[str, ...]] = (
    "fields, indexes, cascades",
    "entities",
    "relationships",
    "migrations",
    "schema summary",
    "entity inventory",
    "entity inventory - this milestone",
    "entity inventory — this milestone",
)


# Canonical section → case-insensitive aliases. Any section whose
# normalized title startswith / matches one of these aliases is treated
# as the canonical section name.
ALLOWED_SECTIONS: Final[Mapping[str, tuple[str, ...]]] = {
    "scope_recap": ("scope recap", "intent"),
    "what_wave_a_produced": ("what wave a produced",),
    "seams_wave_b": _SEAMS_WAVE_B_ALIASES,
    "seams_wave_d": _SEAMS_WAVE_D_ALIASES,
    "seams_wave_t": _SEAMS_WAVE_T_ALIASES,
    "seams_wave_e": _SEAMS_WAVE_E_ALIASES,
    "schema_body": _SCHEMA_BODY_ALIASES,
    "open_questions": (
        "open questions",
        "open questions / carry-forward",
        "open questions punted to wave b / architect",
        "open questions punted to wave b/architect",
    ),
}


# Always-required canonical sections (subset of ALLOWED_SECTIONS keys).
# Conditional sections ``seams_wave_d`` and ``schema_body`` are added
# by the validator based on milestone template / IR entity scope.
REQUIRED_SECTIONS: Final[frozenset[str]] = frozenset({
    "scope_recap",
    "what_wave_a_produced",
    "seams_wave_b",
    "seams_wave_t",
    "seams_wave_e",
    "open_questions",
})


# H2 titles that match one of these (case-insensitive substring) earn
# an immediate rejection with the paired teaching text. Order matters:
# more specific matches appear earlier.
DISALLOWED_SECTION_REASONS: Final[tuple[tuple[tuple[str, ...], str, str], ...]] = (
    (
        ("design-token contract", "design token", "css variable", "color palette"),
        "DESIGN_TOKENS_DUPLICATE",
        (
            "Design tokens live in .agent-team/UI_DESIGN_TOKENS.json (Phase G "
            "Slice 4c). Do not duplicate tokens in the architecture handoff. "
            "Reference the JSON file by path instead."
        ),
    ),
    (
        (
            "merge-surface ownership",
            "merge surface",
            "ownership matrix",
            "who writes what",
            "merge-surface ownership matrix",
        ),
        "OWNERSHIP_MATRIX_DUPLICATE",
        (
            "Ownership is defined in docs/SCAFFOLD_OWNERSHIP.md. Do not write "
            "a matrix here — reference that file if needed."
        ),
    ),
    (
        ("stack", "technology stack", "tech stack"),
        "STACK_REDECLARE",
        (
            "Stack is owned by the stack contract (.agent-team/STACK_CONTRACT.json, "
            "injected as [STACK CONTRACT]). Wave A must not redeclare stack here."
        ),
    ),
    (
        ("deferred entities", "future milestones"),
        "CROSS_MILESTONE_CONTEXT",
        (
            "Do not describe future milestones. Wave B/D/T/E of this milestone "
            "only consume their own MilestoneScope. Future-milestone context "
            "belongs in MASTER_PLAN.md, not the architecture handoff."
        ),
    ),
    (
        ("out-of-scope", "forbidden in this milestone"),
        "OUT_OF_SCOPE_RESTATED",
        (
            "Out-of-scope guardrails live in MilestoneScope (A-09) and "
            "REQUIREMENTS.md. Do not restate them here."
        ),
    ),
    (
        ("cascade-rule placeholder", "cascade rule placeholder"),
        "SPECULATIVE_CASCADES",
        (
            "Cascade rules live in apps/api/prisma/schema.prisma as Prisma "
            "relations. Do not speculate about FK rules for entities this "
            "milestone does not introduce."
        ),
    ),
    (
        ("seed-runner seam",),
        "SEED_RUNNER_TOPLEVEL",
        (
            "Seed-runner details belong as a bullet inside "
            "'## Seams Wave B must populate'. Do not give it its own H2 — "
            "the seams sections are the single anchor for downstream waves."
        ),
    ),
    (
        ("migration plan",),
        "MIGRATION_PLAN_SPECULATION",
        (
            "Document only migrations this Wave A produced (under "
            "'## What Wave A produced'). Future migration names are "
            "speculative — the real migration file will be generated by the "
            "owning milestone's Wave A via 'prisma migrate dev'."
        ),
    ),
    (
        ("requirements", "definition of done"),
        "REQUIREMENTS_RESTATED",
        (
            "REQUIREMENTS.md is injected into downstream prompts separately. "
            "Do not restate requirements or the Definition of Done here."
        ),
    ),
)


# The hallucinated-entity rule is a content-aware check (§5 row G) —
# not a pure section-name match. Its teaching text is kept here so the
# validator can cite it directly.
EMPTY_SCOPE_ENTITY_TABLE_REASON: Final[tuple[str, str]] = (
    "EMPTY_SCOPE_ENTITY_TABLE",
    (
        "This milestone's IR has zero entities in scope — an "
        "entity/schema table is a hallucination. Use an explicit-zero "
        "declaration instead (e.g. 'Fields, indexes, cascades — "
        "intentionally empty')."
    ),
)


# ALLOWED_REFERENCES — the eight injection surfaces Wave A has evidence
# for. Values are the *source labels* used in rejection messages. The
# validator resolves which concrete paths / ids are allowed by reading
# the Wave A inputs at validation time; this constant anchors the
# source-label vocabulary.
ALLOWED_REFERENCES: Final[tuple[str, ...]] = (
    "scaffolded_files",
    "ir_entities",
    "acceptance_criteria",
    "backend_context",
    "stack_contract",
    "milestone_id",
    "cumulative_architecture",
    "dependency_artifacts",
)


# Pattern IDs emitted by the validator (§1F of the architecture report).
PATTERN_SECTION_REJECTION: Final[str] = "WAVE-A-SCHEMA-REJECTION-001"
PATTERN_UNDECLARED_REFERENCE: Final[str] = "WAVE-A-SCHEMA-UNDECLARED-REF-001"
# Concrete-reference derivability violations (allowlist-evidence §6 Table 1–8).
# Emitted when Wave A cites a port / entity name / file path / AC id / predecessor
# milestone id that is NOT derivable from one of the eight injection sources.
PATTERN_CONCRETE_REFERENCE: Final[str] = "WAVE-A-SCHEMA-REFERENCE-001"


# Maximum retries surface — the validator exposes the canonical config
# key so the CLI shim can resolve effective budget without importing
# config.py mid-validator.
MAX_RETRIES_CONFIG_KEY: Final[str] = "wave_a_rerun_budget"
MAX_RETRIES_LEGACY_ALIAS: Final[str] = "wave_a5_max_reruns"
