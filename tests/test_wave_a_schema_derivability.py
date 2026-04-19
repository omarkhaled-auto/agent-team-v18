"""Phase H1b-fix — derivability validator (WAVE-A-SCHEMA-REFERENCE-001).

Covers :func:`wave_a_schema_validator._validate_concrete_references` +
:class:`ConcreteReferenceViolation` for the five check categories
described in allowlist-evidence §6 Table 1–8:

* ports
* entity names
* file paths
* AC IDs
* predecessor-milestone refs

For each category:

* positive (derivable → no violation)
* negative (not derivable → WAVE-A-SCHEMA-REFERENCE-001 at HIGH)
* skip-path (source None → category appears in ``skipped_concrete_checks``
  and NO false-positive violation is emitted)

Plus:

* a smoke #11 end-to-end fixture that exercises all five check
  categories simultaneously (port 8080 via `??` fallback + unlisted
  entity + out-of-scaffold path + unknown AC + unknown M-ref)
* integration with :func:`cli._enforce_gate_wave_a_schema` to prove the
  resolved injection sources flow through correctly and
  ``skipped_sources`` is surfaced when on-disk artifacts are absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15 import cli as _cli
from agent_team_v15 import wave_a_schema
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_a_schema_validator import (
    ConcreteReferenceViolation,
    _validate_concrete_references,
    validate_wave_a_output,
)


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------


def _full_body(*extra_sections: str) -> str:
    """A minimal-but-passing ARCHITECTURE.md body, plus optional extra
    section bodies (injected verbatim as H2 sections)."""
    parts = [
        "## Scope recap",
        "Milestone milestone-1.",
        "",
        "## What Wave A produced",
        "- schema.prisma",
        "",
        "## Seams Wave B must populate",
        "- main.ts",
        "",
        "## Seams Wave D must populate",
        "- layout.tsx",
        "",
        "## Seams Wave T must populate",
        "- jest",
        "",
        "## Seams Wave E must populate",
        "- lint",
        "",
        "## Open questions",
        "- None.",
        "",
    ]
    parts.extend(extra_sections)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 1. Ports
# ---------------------------------------------------------------------------


def test_port_positive_allowed_port_in_stack_contract() -> None:
    body = _full_body(
        "## Fields, indexes, cascades",
        "API listens on 3080.",
        "",
    )
    violations, skipped = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={"ports": [3080, 5432]},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    port_violations = [v for v in violations if v.category == "port"]
    assert port_violations == []
    assert "ports" not in skipped


def test_port_negative_fallback_default_smoke11_pattern() -> None:
    """Smoke #11 defect class: `PORT ?? 8080` while DoD requires 3080."""
    body = _full_body(
        "## Fields, indexes, cascades",
        "listen on PORT ?? 8080.",
        "",
    )
    violations, skipped = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={"ports": [3080]},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    port_violations = [v for v in violations if v.category == "port"]
    assert port_violations, "expected PORT ?? 8080 fallback-default violation"
    v = port_violations[0]
    assert v.token == "8080"
    assert v.severity == "HIGH"
    assert "8080" in v.message
    assert "stack contract" in v.message.lower()


def test_port_negative_literal_in_what_wave_a_produced() -> None:
    body = _full_body(
        "## What Wave A produced — extra",
        "",
    )
    # Insert drift into the already-present `## What Wave A produced`.
    body_with_drift = body.replace(
        "## What Wave A produced\n- schema.prisma",
        "## What Wave A produced\n- schema.prisma\n- api exposed on 9999",
    )
    violations, _ = _validate_concrete_references(
        content=body_with_drift,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={"ports": [3080]},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    port_violations = [v for v in violations if v.category == "port"]
    assert any(v.token == "9999" for v in port_violations)


def test_port_skip_when_stack_contract_none() -> None:
    body = _full_body("## Fields, indexes, cascades", "PORT ?? 8080.", "")
    violations, skipped = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract=None,
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    assert "ports" in skipped
    port_violations = [v for v in violations if v.category == "port"]
    assert port_violations == [], "no false positives when stack_contract is None"


def test_port_allowed_via_dod_port_shape() -> None:
    """Stack contract may carry `dod.port` instead of `ports` list."""
    body = _full_body(
        "## Fields, indexes, cascades",
        "API listens on PORT ?? 3080.",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={"dod": {"port": 3080}},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    port_violations = [v for v in violations if v.category == "port"]
    assert port_violations == []


# ---------------------------------------------------------------------------
# 2. Entity names
# ---------------------------------------------------------------------------


def test_entity_positive_listed_in_ir() -> None:
    body = _full_body(
        "## Fields, indexes, cascades",
        "- Order (id, total, status)",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=["Order"],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    entity_violations = [v for v in violations if v.category == "entity"]
    assert entity_violations == []


def test_entity_negative_hallucinated_camelcase() -> None:
    body = _full_body(
        "## Fields, indexes, cascades",
        "- Order (id, total)",
        "- TaxInvoice (lineItemTotal, vat)",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=["Order"],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    entity_violations = [v for v in violations if v.category == "entity"]
    tokens = {v.token for v in entity_violations}
    assert "TaxInvoice" in tokens
    v = next(v for v in entity_violations if v.token == "TaxInvoice")
    assert v.severity == "HIGH"
    assert "milestone IR entity scope" in v.message


def test_entity_framework_noise_not_flagged() -> None:
    body = _full_body(
        "## Fields, indexes, cascades",
        "- Order entity; service is OrderService; module is OrderModule.",
        "- Client uses PrismaClient and HttpException.",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=["Order"],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    entity_violations = [v for v in violations if v.category == "entity"]
    tokens = {v.token for v in entity_violations}
    # Framework-idiom suffixes must not surface as hallucinated entities.
    assert "OrderService" not in tokens
    assert "OrderModule" not in tokens
    assert "PrismaClient" not in tokens
    assert "HttpException" not in tokens


def test_entity_skip_when_ir_entities_none() -> None:
    body = _full_body(
        "## Fields, indexes, cascades",
        "- TaxInvoice (line, vat)",
        "",
    )
    violations, skipped = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=None,
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    assert "entity_names" in skipped
    entity_violations = [v for v in violations if v.category == "entity"]
    assert entity_violations == [], "no false positives when ir_entities is None"


# ---------------------------------------------------------------------------
# 3. File paths
# ---------------------------------------------------------------------------


def test_path_positive_listed_in_scaffolded_files() -> None:
    body = _full_body()
    # Override the Wave-B seams body with a real scaffolded path citation.
    body = body.replace(
        "## Seams Wave B must populate\n- main.ts",
        "## Seams Wave B must populate\n- `apps/api/src/main.ts`",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=["apps/api/src/main.ts"],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    path_violations = [v for v in violations if v.category == "file_path"]
    assert path_violations == []


def test_path_positive_via_api_root_prefix() -> None:
    body = _full_body(
        "## Extra prose with path apps/api/src/orders/order.service.ts",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context={"api_root": "apps/api/src"},
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    path_violations = [v for v in violations if v.category == "file_path"]
    assert path_violations == [], "api_root prefix should exempt derived path"


def test_path_positive_via_scaffold_ownership_paths() -> None:
    body = _full_body(
        "## Extra apps/web/src/future-page.tsx",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=["apps/web/src/future-page.tsx"],
    )
    path_violations = [v for v in violations if v.category == "file_path"]
    assert path_violations == []


def test_path_negative_unknown_path() -> None:
    body = _full_body(
        "## Extra apps/invented/pkg.ts",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=["apps/api/src/main.ts"],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context={"api_root": "apps/api/src"},
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    path_violations = [v for v in violations if v.category == "file_path"]
    tokens = {v.token for v in path_violations}
    assert "apps/invented/pkg.ts" in tokens
    v = next(v for v in path_violations if v.token == "apps/invented/pkg.ts")
    assert v.severity == "HIGH"
    assert "scaffolded_files" in v.message or "backend_context" in v.message


def test_path_skip_when_scaffolded_files_none() -> None:
    body = _full_body(
        "## Extra apps/invented/pkg.ts",
        "",
    )
    violations, skipped = _validate_concrete_references(
        content=body,
        scaffolded_files=None,
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    assert "file_paths" in skipped
    path_violations = [v for v in violations if v.category == "file_path"]
    assert path_violations == []


# ---------------------------------------------------------------------------
# 4. AC IDs
# ---------------------------------------------------------------------------


def test_ac_id_positive_listed() -> None:
    body = _full_body(
        "## Extra context",
        "Implements FR-FOUND-004 and BR-GEN-009.",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=["FR-FOUND-004", "BR-GEN-009"],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    ac_violations = [v for v in violations if v.category == "ac_id"]
    assert ac_violations == []


def test_ac_id_negative_unknown() -> None:
    body = _full_body(
        "## Extra context",
        "Implements FR-FOUND-004 and NFR-MADEUP-999.",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=["FR-FOUND-004"],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    ac_violations = [v for v in violations if v.category == "ac_id"]
    tokens = {v.token for v in ac_violations}
    assert "NFR-MADEUP-999" in tokens
    assert "FR-FOUND-004" not in tokens
    v = next(v for v in ac_violations if v.token == "NFR-MADEUP-999")
    assert v.severity == "HIGH"
    assert "milestone-scoped AC list" in v.message


def test_ac_id_skip_when_criteria_none() -> None:
    body = _full_body(
        "## Extra context",
        "Implements NFR-MADEUP-999.",
        "",
    )
    violations, skipped = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=None,
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    assert "ac_ids" in skipped
    ac_violations = [v for v in violations if v.category == "ac_id"]
    assert ac_violations == []


# ---------------------------------------------------------------------------
# 5. Predecessor-milestone refs
# ---------------------------------------------------------------------------


def test_milestone_ref_positive_self() -> None:
    body = _full_body(
        "## Extra",
        "This M1 deliverable.",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts={},
        scaffold_ownership_paths=None,
    )
    mref_violations = [v for v in violations if v.category == "milestone_ref"]
    assert mref_violations == []


def test_milestone_ref_positive_in_dependency_artifacts() -> None:
    body = _full_body(
        "## Extra",
        "Building on M1 and M2 deliverables.",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-3",
        cumulative_architecture=None,
        dependency_artifacts={"milestone-1": {}, "milestone-2": {}},
        scaffold_ownership_paths=None,
    )
    mref_violations = [v for v in violations if v.category == "milestone_ref"]
    assert mref_violations == []


def test_milestone_ref_positive_from_cumulative_blob() -> None:
    body = _full_body(
        "## Extra",
        "References M1 (foundation milestone).",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-2",
        cumulative_architecture="## M1 summary\n- bootstrap done.\n",
        dependency_artifacts={},
        scaffold_ownership_paths=None,
    )
    mref_violations = [v for v in violations if v.category == "milestone_ref"]
    assert mref_violations == []


def test_milestone_ref_negative_future_milestone() -> None:
    body = _full_body(
        "## Extra",
        "The M5 Comment entity will cascade from M4 Task.",
        "",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts={},
        scaffold_ownership_paths=None,
    )
    mref_violations = [v for v in violations if v.category == "milestone_ref"]
    tokens = {v.token for v in mref_violations}
    assert "M5" in tokens
    assert "M4" in tokens
    v = next(v for v in mref_violations if v.token == "M5")
    assert v.severity == "HIGH"
    assert "dependency_artifacts" in v.message


def test_milestone_ref_not_skipped_when_deps_none() -> None:
    """Milestone-ref check is never skipped — milestone_id is always
    passed and dependency_artifacts defaults to {} when None."""
    body = _full_body(
        "## Extra",
        "Future M9 thing.",
        "",
    )
    violations, skipped = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    assert "milestone_refs" not in skipped
    mref_violations = [v for v in violations if v.category == "milestone_ref"]
    assert any(v.token == "M9" for v in mref_violations)


# ---------------------------------------------------------------------------
# Smoke #11 end-to-end fixture (all five categories simultaneously)
# ---------------------------------------------------------------------------


_SMOKE11_BODY = "\n".join(
    [
        "## Scope recap",
        "Milestone milestone-1. This M4 deliverable is foundation-only.",
        "",
        "## What Wave A produced",
        "- `apps/api/prisma/schema.prisma`",
        "- `docker-compose.yml` — postgres on 5432",
        "",
        "## Seams Wave B must populate",
        "- `apps/api/src/main.ts` — listen on PORT ?? 8080.",
        "- `apps/invented/main.ts` — second app entrypoint.",
        "",
        "## Seams Wave D must populate",
        "- layout.tsx",
        "",
        "## Seams Wave T must populate",
        "- jest config",
        "",
        "## Seams Wave E must populate",
        "- lint",
        "",
        "## Fields, indexes, cascades",
        "- TaxInvoice (lineTotal, vatCode) — planned for later milestone.",
        "",
        "## Open questions",
        "- Related to NFR-MADEUP-999 and M5 cascade planning.",
        "",
    ]
)


def test_smoke_11_end_to_end_all_categories() -> None:
    """Exercise all five derivability checks simultaneously.

    Fixture carries: PORT ?? 8080 (port), TaxInvoice (entity),
    apps/invented/main.ts (file_path), NFR-MADEUP-999 (ac_id), M5
    (milestone_ref). Expect at least one violation per category — 5+.
    """
    violations, skipped = _validate_concrete_references(
        content=_SMOKE11_BODY,
        scaffolded_files=[
            "apps/api/src/main.ts",
            "apps/api/prisma/schema.prisma",
            "docker-compose.yml",
        ],
        ir_entities=["User", "Order"],  # TaxInvoice is fabricated
        ir_acceptance_criteria=["FR-FOUND-001", "FR-FOUND-004"],
        stack_contract={"ports": [3080, 5432]},
        backend_context={"api_root": "apps/api/src"},
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts={},
        scaffold_ownership_paths=None,
    )
    # All five categories are exercised; none should be skipped.
    assert skipped == [], (
        f"expected all five categories to run, got skipped={skipped!r}"
    )
    categories_seen = {v.category for v in violations}
    assert categories_seen == {
        "port",
        "entity",
        "file_path",
        "ac_id",
        "milestone_ref",
    }, f"missing a category: {categories_seen!r}"
    # Pattern id + severity threaded through every violation.
    for v in violations:
        assert isinstance(v, ConcreteReferenceViolation)
        assert v.severity == "HIGH"

    # At least 5 violations total (one per category minimum).
    assert len(violations) >= 5


def test_smoke_11_via_public_validate_wave_a_output() -> None:
    """Same fixture, driven through :func:`validate_wave_a_output` so the
    findings surface in ``to_review_dict()`` with the structured shape."""
    result = validate_wave_a_output(
        _SMOKE11_BODY,
        "milestone-1",
        scaffolded_files=[
            "apps/api/src/main.ts",
            "apps/api/prisma/schema.prisma",
            "docker-compose.yml",
        ],
        ir_entities=["User", "Order"],
        ir_acceptance_criteria=["FR-FOUND-001", "FR-FOUND-004"],
        stack_contract={"ports": [3080, 5432]},
        backend_context={"api_root": "apps/api/src"},
        cumulative_architecture=None,
        dependency_artifacts={},
        scaffold_ownership_paths=None,
    )
    assert result.has_findings
    review = result.to_review_dict()
    pattern_ids = {f.get("pattern_id") for f in review["findings"]}
    assert wave_a_schema.PATTERN_CONCRETE_REFERENCE in pattern_ids
    # The 5 derivability violations all carry the REFERENCE-001 pattern id
    # under their category-prefixed review-dict key.
    concrete_findings = [
        f for f in review["findings"]
        if f.get("pattern_id") == wave_a_schema.PATTERN_CONCRETE_REFERENCE
    ]
    assert len(concrete_findings) >= 5
    categories = {f.get("category") for f in concrete_findings}
    assert categories == {
        "schema_concrete_reference_port",
        "schema_concrete_reference_entity",
        "schema_concrete_reference_file_path",
        "schema_concrete_reference_ac_id",
        "schema_concrete_reference_milestone_ref",
    }


# ---------------------------------------------------------------------------
# CLI gate integration — _enforce_gate_wave_a_schema forwarding
# ---------------------------------------------------------------------------


def _seed_architecture_md(tmp_path: Path, milestone_id: str, body: str) -> Path:
    path = (
        tmp_path
        / ".agent-team"
        / f"milestone-{milestone_id}"
        / "ARCHITECTURE.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _seed_scaffold_wave_artifact(
    tmp_path: Path, milestone_id: str, files: list[str]
) -> None:
    art_dir = tmp_path / ".agent-team" / "wave-artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    payload = {"scaffolded_files": files}
    (art_dir / f"{milestone_id}-wave-SCAFFOLD.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _seed_ir(
    tmp_path: Path, entities: list[str], ac_ids: list[str]
) -> None:
    ir_dir = tmp_path / ".agent-team" / "product-ir"
    ir_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "entities": [{"name": e} for e in entities],
        "acceptance_criteria": [{"id": a} for a in ac_ids],
    }
    (ir_dir / "product.ir.json").write_text(json.dumps(payload), encoding="utf-8")


def _cfg() -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18.wave_a_schema_enforcement_enabled = True
    cfg.v18.architecture_md_enabled = True
    cfg.v18.wave_a_rerun_budget = 5  # high so we see TRUE, not raise
    return cfg


def test_gate_forwards_injection_sources_and_flags_drift(tmp_path: Path) -> None:
    """The gate wires scaffolded_files + IR + stack_contract via
    ``_resolve_wave_a_injection_sources`` and the smoke-#11-style body
    produces concrete-reference violations in the persisted review."""
    _seed_architecture_md(tmp_path, "milestone-1", _SMOKE11_BODY)
    _seed_scaffold_wave_artifact(
        tmp_path,
        "milestone-1",
        ["apps/api/src/main.ts", "apps/api/prisma/schema.prisma"],
    )
    _seed_ir(tmp_path, ["User", "Order"], ["FR-FOUND-001", "FR-FOUND-004"])
    # Seed a stack contract file. The persisted StackContract schema has
    # no port fields, so `_extract_allowed_ports` resolves to an empty
    # set — every port literal in the body then drifts. That is exactly
    # the behaviour the integration test needs to observe: the gate
    # wires the resolved contract dict into the validator and the port
    # category fires.
    from agent_team_v15.stack_contract import (
        StackContract,
        write_stack_contract,
    )

    write_stack_contract(
        tmp_path,
        StackContract(
            backend_framework="nestjs",
            frontend_framework="nextjs",
            database="postgres",
            confidence="explicit",
        ),
    )

    should_rerun, review = _cli._enforce_gate_wave_a_schema(
        config=_cfg(),
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    assert should_rerun is True
    assert isinstance(review, dict)
    assert review["verdict"] == "FAIL"
    # Concrete-reference pattern id present in persisted findings.
    pattern_ids = {f.get("pattern_id") for f in review["findings"]}
    assert wave_a_schema.PATTERN_CONCRETE_REFERENCE in pattern_ids
    # At least the port + ac + milestone categories fire (entity + path
    # depend on section-scoping which is exercised in the unit tests
    # above; the integration test's main claim is that the CLI gate
    # forwards the sources).
    categories = {
        f.get("category")
        for f in review["findings"]
        if f.get("pattern_id") == wave_a_schema.PATTERN_CONCRETE_REFERENCE
    }
    assert "schema_concrete_reference_port" in categories
    assert "schema_concrete_reference_milestone_ref" in categories


def test_gate_surfaces_skipped_sources_when_on_disk_artifacts_absent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When scaffolded_files / IR / stack_contract are absent on disk,
    the gate must skip those derivability checks (no false positive) and
    log the skipped-sources list."""
    _seed_architecture_md(tmp_path, "milestone-1", _SMOKE11_BODY)
    caplog.set_level("INFO", logger="agent_team_v15.cli")
    should_rerun, review = _cli._enforce_gate_wave_a_schema(
        config=_cfg(),
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        rerun_count=0,
    )
    # At least the milestone-ref check still fires (never skipped), so
    # the gate returns True or an empty review — either is fine as long
    # as no port/entity/file_path/ac_id false positives surface.
    if review:
        cats = {
            f.get("category")
            for f in review.get("findings", [])
            if f.get("pattern_id") == wave_a_schema.PATTERN_CONCRETE_REFERENCE
        }
        assert "schema_concrete_reference_port" not in cats
        assert "schema_concrete_reference_entity" not in cats
        assert "schema_concrete_reference_file_path" not in cats
        assert "schema_concrete_reference_ac_id" not in cats
    # Log message must mention skipped sources.
    skip_logs = [
        r for r in caplog.records
        if "skipping concrete-ref checks" in r.getMessage()
    ]
    assert skip_logs, (
        f"Expected skipped-sources INFO log. Captured: "
        f"{[r.getMessage() for r in caplog.records]!r}"
    )
    msg = skip_logs[0].getMessage()
    assert "scaffolded_files" in msg
    assert "stack_contract" in msg
    assert "ir_entities" in msg


# ---------------------------------------------------------------------------
# Heuristic edge-case tests (spec F.1 + F.3)
# ---------------------------------------------------------------------------


def test_year_literals_not_flagged_as_ports() -> None:
    """Spec F.1 — 2020–2099 year literals inside a port-check section
    must not drift even when stack_contract has an empty port set."""
    body = _full_body()
    body_with_year = body.replace(
        "## What Wave A produced\n- schema.prisma",
        "## What Wave A produced\n- schema.prisma\n- Copyright 2026 taskflow.",
    )
    violations, _ = _validate_concrete_references(
        content=body_with_year,
        scaffolded_files=[],
        ir_entities=[],
        ir_acceptance_criteria=[],
        stack_contract={"ports": []},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    port_violations = [v for v in violations if v.category == "port"]
    assert all(v.token != "2026" for v in port_violations), (
        f"2026 year literal incorrectly flagged as port: {port_violations!r}"
    )


def test_camelcase_in_prose_section_not_flagged_as_entity() -> None:
    """Spec F.3 — CamelCase identifiers outside the schema section (e.g.
    ``MilestoneScope`` inside ``## Open questions``) must not surface as
    hallucinated entities."""
    body = _full_body(
        "## Fields, indexes, cascades",
        "- Order",
        "",
    )
    body = body.replace(
        "## Open questions\n- None.",
        "## Open questions\n- None. See MilestoneScope for scope wiring.",
    )
    violations, _ = _validate_concrete_references(
        content=body,
        scaffolded_files=[],
        ir_entities=["Order"],
        ir_acceptance_criteria=[],
        stack_contract={},
        backend_context=None,
        milestone_id="milestone-1",
        cumulative_architecture=None,
        dependency_artifacts=None,
        scaffold_ownership_paths=None,
    )
    entity_violations = [v for v in violations if v.category == "entity"]
    assert all(v.token != "MilestoneScope" for v in entity_violations), (
        "Prose-section CamelCase must not trigger entity drift"
    )


def test_gate_resolve_injection_sources_returns_all_keys(tmp_path: Path) -> None:
    """Structural: the resolver helper must return a dict containing the
    eight canonical injection-source keys plus a skipped_sources list."""
    resolved = _cli._resolve_wave_a_injection_sources(
        str(tmp_path), "milestone-1"
    )
    required_keys = {
        "scaffolded_files",
        "ir_entities",
        "ir_acceptance_criteria",
        "stack_contract",
        "backend_context",
        "cumulative_architecture",
        "dependency_artifacts",
        "skipped_sources",
    }
    assert required_keys.issubset(set(resolved.keys()))
    # Empty tmp_path → most sources skipped.
    assert isinstance(resolved["skipped_sources"], list)
    assert "scaffolded_files" in resolved["skipped_sources"]
