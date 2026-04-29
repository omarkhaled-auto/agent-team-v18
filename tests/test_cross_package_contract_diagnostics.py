"""Phase 5.8a §K.1 — Cross-package OpenAPI / TS-client diagnostic fixtures.

Locks the contract for Phase 5.8a's advisory ``CONTRACT-DRIFT-DIAGNOSTIC-001``
emission + the per-milestone ``PHASE_5_8A_DIAGNOSTIC.json`` artifact +
the §K.2 decision-gate predicate.

ACs covered (per dispatch §K.1 + scope check-in):

* AC1 — empty spec → 0 divergences.
* AC2 — spec ≡ client → 0 divergences.
* AC3 — camelCase-vs-snake_case drift detected.
* AC4 — optional-vs-required drift detected.
* AC5 — missing-export drift detected.
* AC6a — 5 advisory CONTRACT-DRIFT-DIAGNOSTIC-001 findings do NOT gate
  the Quality Contract (``_evaluate_quality_contract`` returns COMPLETE).
* AC6b — those findings do NOT trip state-invariant Rule 1.
* AC6c — WaveFinding message carries explicit advisory wording.
* AC7 — ``[CROSS-PACKAGE-DIAG]`` summary log fires at end-of-Wave-C.
* AC8 — ``PHASE_5_8A_DIAGNOSTIC.json`` schema locked at the fixture level.

Supporting fixtures (correction-driven):

* type-class divergence detected (correction #1: types are 5.8a scope).
* polymorphic ``oneOf`` does NOT inflate divergence count (correction #1).
* per-milestone artifact path isolates M1+M2 (correction #3).
* ``_coerce_contract_result`` threads the new fields (correction #5).
* §K.2 decision-gate: 3 distinct DTOs × same class satisfies; 3 props on
  ONE DTO does NOT; 3 distinct DTOs × different classes does NOT.
* Tooling-unavailable shape: visible in artifact, ZERO drift findings (Q3).
* Diagnostic crash isolation: openapi_generator's diagnostic block does
  NOT propagate failure into Wave C (Q2 — diagnostic cannot fail Wave C).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agent_team_v15 import cross_package_diagnostic as cpd
from agent_team_v15.cross_package_diagnostic import (
    ALL_DIVERGENCE_CLASSES,
    CONTRACT_DRIFT_DIAGNOSTIC_CODE,
    DIAGNOSTIC_LOG_TAG,
    DIAGNOSTIC_SEVERITY,
    DIAGNOSTIC_VERDICT_HINT,
    DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
    DIVERGENCE_CLASS_MISSING_EXPORT,
    DIVERGENCE_CLASS_OPTIONAL_VS_REQUIRED,
    DIVERGENCE_CLASS_TYPE_MISMATCH,
    PHASE_5_8A_DIAGNOSTIC_FILENAME,
    TOOLING_PARSER_NODE_TS_AST,
    TOOLING_PARSER_UNAVAILABLE,
    DiagnosticOutcome,
    DivergenceRecord,
    compute_divergences,
    divergences_to_finding_dicts,
    k2_decision_gate_satisfied,
    write_phase_5_8a_diagnostic,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a project root, contracts dir, and api-client dir."""

    project_root = tmp_path / "project"
    contracts_dir = project_root / "contracts" / "openapi"
    client_dir = project_root / "packages" / "api-client"
    contracts_dir.mkdir(parents=True)
    client_dir.mkdir(parents=True)
    return project_root, contracts_dir, client_dir


def _write_spec(contracts_dir: Path, schemas: dict) -> Path:
    spec_path = contracts_dir / "current.json"
    spec_path.write_text(
        json.dumps({"openapi": "3.1.0", "components": {"schemas": schemas}}),
        encoding="utf-8",
    )
    return spec_path


def _write_types_gen(client_dir: Path, content: str = "") -> Path:
    types_gen = client_dir / "types.gen.ts"
    types_gen.write_text(content, encoding="utf-8")
    return types_gen


def _stub_parser(exports):
    """Build a parser_override that returns the given exports list."""

    def parser(file_path, project_root):
        return {
            "exports": exports,
            "parser": TOOLING_PARSER_NODE_TS_AST,
            "tsVersion": "5.4.5",
            "error": "",
        }

    return parser


# ---------------------------------------------------------------------------
# AC1 — empty spec → 0 divergences
# ---------------------------------------------------------------------------


def test_empty_spec_yields_no_divergences(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(contracts_dir, {})

    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([]),
    )
    assert outcome.divergences == []
    assert outcome.metrics["divergences_detected_total"] == 0
    assert outcome.metrics["schemas_in_spec"] == 0
    assert outcome.metrics["unique_divergence_classes"] == []


# ---------------------------------------------------------------------------
# AC2 — spec ≡ client → 0 divergences
# ---------------------------------------------------------------------------


def test_spec_equals_client_yields_no_divergences(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "UserDto": {
                "type": "object",
                "properties": {
                    "userId": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["userId", "name"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "UserDto",
                "kind": "type-literal",
                "line": 3,
                "properties": [
                    {"name": "userId", "optional": False, "typeText": "string"},
                    {"name": "name", "optional": False, "typeText": "string"},
                ],
            },
        ]),
    )
    assert outcome.divergences == []
    assert outcome.metrics["divergences_detected_total"] == 0
    assert outcome.metrics["schemas_in_spec"] == 1
    assert outcome.metrics["exports_in_client"] == 1


# ---------------------------------------------------------------------------
# AC3 — camelCase-vs-snake_case drift detected
# ---------------------------------------------------------------------------


def test_camel_vs_snake_drift_detected(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "UserDto": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                },
                "required": ["user_id"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "UserDto",
                "kind": "type-literal",
                "line": 3,
                "properties": [
                    {"name": "userId", "optional": False, "typeText": "string"},
                ],
            },
        ]),
    )
    case_drifts = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_CAMEL_VS_SNAKE
    ]
    assert len(case_drifts) == 1
    assert case_drifts[0].schema_name == "UserDto"
    assert case_drifts[0].spec_value == "user_id"
    assert case_drifts[0].client_value == "userId"
    # No other divergence classes should fire on a name-only mismatch (the
    # property is found by normalized-name matching, so optional flag and
    # type compare correctly).
    assert {d.divergence_class for d in outcome.divergences} == {
        DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
    }


# ---------------------------------------------------------------------------
# AC4 — optional-vs-required drift detected
# ---------------------------------------------------------------------------


def test_optional_vs_required_drift_detected(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "OrderDto": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "OrderDto",
                "kind": "type-literal",
                "line": 5,
                "properties": [
                    {"name": "id", "optional": True, "typeText": "string"},
                ],
            },
        ]),
    )
    matches = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_OPTIONAL_VS_REQUIRED
    ]
    assert len(matches) == 1
    assert matches[0].schema_name == "OrderDto"
    assert matches[0].property_name == "id"
    assert matches[0].spec_value == "required"
    assert matches[0].client_value == "optional"


# ---------------------------------------------------------------------------
# AC5 — missing-export drift detected
# ---------------------------------------------------------------------------


def test_missing_export_drift_detected(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "AuthDto": {
                "type": "object",
                "properties": {"token": {"type": "string"}},
                "required": ["token"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([]),
    )
    matches = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_MISSING_EXPORT
    ]
    assert len(matches) == 1
    assert matches[0].schema_name == "AuthDto"
    assert matches[0].spec_value == "AuthDto"
    assert matches[0].client_value == ""


# ---------------------------------------------------------------------------
# Type-class mismatch detected (correction #1 — types in 5.8a scope)
# ---------------------------------------------------------------------------


def test_type_class_mismatch_detected(tmp_workspace):
    """integer + string still fires type-mismatch (reviewer correction #2:
    OpenAPI ``integer`` is normalised to ``"number"`` for comparison; ``string``
    is unrelated, so the mismatch surfaces. ``spec_value`` is the
    normalised classifier output, not the raw spec_type)."""

    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "MetricsDto": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "MetricsDto",
                "kind": "type-literal",
                "line": 3,
                "properties": [
                    {"name": "count", "optional": False, "typeText": "string"},
                ],
            },
        ]),
    )
    matches = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_TYPE_MISMATCH
    ]
    assert len(matches) == 1
    # Post-normalisation classifier output: OpenAPI ``integer`` ≡ TS
    # ``number`` per @hey-api/openapi-ts canonical generation.
    assert matches[0].spec_value == "number"
    assert matches[0].client_value == "string"
    assert matches[0].schema_name == "MetricsDto"
    assert matches[0].property_name == "count"


def test_integer_to_number_does_not_fire_type_mismatch(tmp_workspace):
    """Negative — OpenAPI ``integer`` + TS ``number`` is canonical
    @hey-api/openapi-ts generation, NOT drift (reviewer correction #2)."""

    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "MetricsDto": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "MetricsDto",
                "kind": "type-literal",
                "line": 3,
                "properties": [
                    {"name": "count", "optional": False, "typeText": "number"},
                ],
            },
        ]),
    )
    type_mismatches = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_TYPE_MISMATCH
    ]
    assert type_mismatches == []
    assert outcome.metrics["divergences_detected_total"] == 0


def test_array_of_integer_does_not_fire_type_mismatch_against_number_array(tmp_workspace):
    """Negative — nested-array case: ``array<integer>`` ≡ ``number[]`` post
    normalisation (reviewer correction #2 — including nested arrays)."""

    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "ListDto": {
                "type": "object",
                "properties": {
                    "counts": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["counts"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "ListDto",
                "kind": "type-literal",
                "line": 3,
                "properties": [
                    {"name": "counts", "optional": False, "typeText": "number[]"},
                ],
            },
        ]),
    )
    type_mismatches = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_TYPE_MISMATCH
    ]
    assert type_mismatches == []


def test_property_missing_in_client_yields_missing_export_drift(tmp_workspace):
    """Property-level missing-export drift (reviewer correction #1):
    ``spec.UserDto.email`` exists; client ``UserDto`` lacks any normalised
    match for ``email`` → emit ``missing-export`` at property scope with
    ``property_name="email"`` populated. The whole-schema export IS present
    (so no schema-scope missing-export), but a single field is gone."""

    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "UserDto": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["id", "email"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "UserDto",
                "kind": "type-literal",
                "line": 3,
                "properties": [
                    {"name": "id", "optional": False, "typeText": "string"},
                ],
            },
        ]),
    )
    missing = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_MISSING_EXPORT
    ]
    # One property-level missing-export — NOT a whole-schema missing-export
    # (the export is present, just lost a field).
    assert len(missing) == 1
    assert missing[0].schema_name == "UserDto"
    assert missing[0].property_name == "email"
    assert missing[0].spec_value == "email"
    assert missing[0].client_value == ""
    assert "components.schemas.UserDto.properties.email" in missing[0].details


def test_property_missing_multiple_collapses_to_distinct_pair_for_k2(tmp_workspace):
    """Two missing properties on one schema → 2 divergence records, but
    the §K.2 distinct-``(class, schema)``-pair predicate still treats it as
    ONE pair (locked-in distinct-DTO discipline preserved)."""

    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "UserDto": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                },
                "required": ["id", "email", "phone"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "UserDto",
                "kind": "type-literal",
                "line": 3,
                "properties": [
                    {"name": "id", "optional": False, "typeText": "string"},
                ],
            },
        ]),
    )
    missing = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_MISSING_EXPORT
    ]
    assert len(missing) == 2
    assert sorted(d.property_name for d in missing) == ["email", "phone"]
    # K.2 predicate: 2 records but both share (class, schema) → 1 distinct pair
    diagnostics = [
        {
            "divergences": [
                {
                    "divergence_class": d.divergence_class,
                    "schema_name": d.schema_name,
                }
                for d in missing
            ],
        },
    ]
    assert not k2_decision_gate_satisfied(
        diagnostics, correlated_threshold=3,
    )


def test_array_type_mismatch_detected(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "ListDto": {
                "type": "object",
                "properties": {"items": {"type": "array", "items": {"type": "string"}}},
                "required": ["items"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "ListDto",
                "kind": "type-literal",
                "line": 3,
                "properties": [
                    {"name": "items", "optional": False, "typeText": "number[]"},
                ],
            },
        ]),
    )
    matches = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_TYPE_MISMATCH
    ]
    assert len(matches) == 1
    assert matches[0].spec_value == "array<string>"
    assert matches[0].client_value == "array<number>"


def test_nullable_does_not_fire_type_mismatch(tmp_workspace):
    """``string | null`` ≡ OpenAPI ``type: [string, "null"]`` ≡ ``string``."""

    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "NullableDto": {
                "type": "object",
                "properties": {"name": {"type": ["string", "null"]}},
                "required": ["name"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {
                "name": "NullableDto",
                "kind": "type-literal",
                "line": 3,
                "properties": [
                    {"name": "name", "optional": False, "typeText": "string | null"},
                ],
            },
        ]),
    )
    type_mismatches = [
        d
        for d in outcome.divergences
        if d.divergence_class == DIVERGENCE_CLASS_TYPE_MISMATCH
    ]
    assert type_mismatches == []


# ---------------------------------------------------------------------------
# Polymorphic skip — does NOT inflate divergence count (correction #1)
# ---------------------------------------------------------------------------


def test_polymorphic_oneof_does_not_inflate_divergences(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "PolyDto": {
                "oneOf": [
                    {"$ref": "#/components/schemas/A"},
                    {"$ref": "#/components/schemas/B"},
                ],
            },
            "A": {"type": "object", "properties": {}},
            "B": {"type": "object", "properties": {}},
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([
            {"name": "A", "kind": "type-literal", "line": 1, "properties": []},
            {"name": "B", "kind": "type-literal", "line": 5, "properties": []},
        ]),
    )
    schemas_with_divergences = {d.schema_name for d in outcome.divergences}
    # PolyDto is polymorphic so no divergence at all (NOT even missing-export).
    assert "PolyDto" not in schemas_with_divergences
    assert "PolyDto" in outcome.unsupported_polymorphic_schemas
    assert outcome.metrics["divergences_detected_total"] == 0


def test_polymorphic_anyof_and_allof_also_skipped(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "AnyDto": {"anyOf": [{"type": "string"}, {"type": "number"}]},
            "AllDto": {"allOf": [{"type": "object"}]},
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([]),
    )
    assert sorted(outcome.unsupported_polymorphic_schemas) == ["AllDto", "AnyDto"]
    assert outcome.metrics["divergences_detected_total"] == 0


# ---------------------------------------------------------------------------
# AC6 — advisory-not-gating
# ---------------------------------------------------------------------------


def test_advisory_findings_do_not_gate_quality_contract():
    """5 CONTRACT-DRIFT-DIAGNOSTIC-001 AuditFindings (verdict=UNVERIFIED,
    severity=LOW) → ``_evaluate_quality_contract`` → COMPLETE/clean/0/""."""

    from agent_team_v15.audit_models import AuditFinding, AuditReport, AuditScore
    from agent_team_v15.quality_contract import _evaluate_quality_contract
    from agent_team_v15.state import RunState

    findings = [
        AuditFinding(
            finding_id=f"F-DIAG-{i}",
            auditor="wave_pipeline",
            requirement_id="GENERAL",
            verdict=DIAGNOSTIC_VERDICT_HINT,
            severity=DIAGNOSTIC_SEVERITY,
            summary=f"diagnostic divergence {i}",
        )
        for i in range(5)
    ]
    score = AuditScore(
        total_items=0,
        passed=0,
        failed=0,
        partial=0,
        critical_count=0,
        high_count=0,
        medium_count=0,
        low_count=5,
        info_count=0,
        score=100.0,
        health="healthy",
        max_score=100,
    )
    report = AuditReport(
        audit_id="audit-test",
        timestamp="2026-04-29T00:00:00+00:00",
        cycle=1,
        auditors_deployed=["wave_pipeline"],
        findings=findings,
        score=score,
    )
    state = RunState()
    final_status, audit_status, unresolved, severity = _evaluate_quality_contract(
        report, state, config=None,
    )
    assert final_status == "COMPLETE"
    assert audit_status == "clean"
    assert unresolved == 0
    assert severity == ""


def test_advisory_findings_do_not_trip_state_invariant_rule_1():
    """Rule 1 fires only on ``HIGH``/``CRITICAL`` debt; LOW diagnostic
    findings keep ``audit_debt_severity`` empty (or LOW) and the
    invariant must NOT fire."""

    from agent_team_v15.state import RunState
    from agent_team_v15.state_invariants import validate_state_shape_invariants

    state = RunState()
    state.milestone_progress = {
        "milestone-1": {
            "status": "COMPLETE",
            # 5 LOW diagnostic findings could legitimately end up reflected
            # here if the auditor scorer promoted them; the count is non-zero
            # but severity stays LOW so Rule 1 does NOT fire.
            "unresolved_findings_count": 5,
            "audit_debt_severity": "LOW",
        }
    }
    violations = validate_state_shape_invariants(state)
    assert violations == []


def test_wave_finding_message_carries_advisory_wording():
    rec = DivergenceRecord(
        divergence_class=DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
        schema_name="UserDto",
        property_name="user_id",
        spec_value="user_id",
        client_value="userId",
        client_file="packages/api-client/types.gen.ts",
        client_line=3,
        details="property 'user_id' (OpenAPI) differs in case from 'userId'",
    )
    outcome = DiagnosticOutcome(divergences=[rec])
    findings = divergences_to_finding_dicts(outcome)
    assert len(findings) == 1
    msg = findings[0]["message"]
    assert "Phase 5.8a advisory" in msg
    assert f"verdict={DIAGNOSTIC_VERDICT_HINT}" in msg
    assert f"severity={DIAGNOSTIC_SEVERITY}" in msg
    assert "does NOT block Quality Contract" in msg
    assert findings[0]["code"] == CONTRACT_DRIFT_DIAGNOSTIC_CODE
    assert findings[0]["severity"] == DIAGNOSTIC_SEVERITY


# ---------------------------------------------------------------------------
# AC7 — ``[CROSS-PACKAGE-DIAG]`` log + WaveFinding extension
# ---------------------------------------------------------------------------


def test_cross_package_diag_summary_log_emitted(tmp_path, caplog):
    from agent_team_v15.wave_executor import (
        WaveResult,
        _emit_phase_5_8a_diagnostic,
    )

    contract_result = {
        "diagnostic_findings": [
            {
                "code": CONTRACT_DRIFT_DIAGNOSTIC_CODE,
                "severity": DIAGNOSTIC_SEVERITY,
                "file": "packages/api-client/types.gen.ts",
                "line": 3,
                "message": "[Phase 5.8a advisory] divergence",
                "divergence_class": DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                "schema_name": "UserDto",
                "property_name": "user_id",
                "spec_value": "user_id",
                "client_value": "userId",
                "details": "case",
            }
        ],
        "diagnostic_metrics": {
            "schemas_in_spec": 1,
            "exports_in_client": 1,
            "divergences_detected_total": 1,
            "unique_divergence_classes": [DIVERGENCE_CLASS_CAMEL_VS_SNAKE],
        },
        "diagnostic_tooling": {
            "ts_parser": TOOLING_PARSER_NODE_TS_AST,
            "ts_parser_version": "5.4.5",
            "error": "",
        },
        "diagnostic_unsupported_polymorphic_schemas": [],
    }

    class _M:
        id = "milestone-1"

    wave_result = WaveResult(wave="C")
    with caplog.at_level(logging.INFO, logger="agent_team_v15.wave_executor"):
        _emit_phase_5_8a_diagnostic(
            cwd=str(tmp_path),
            milestone=_M(),
            contract_result=contract_result,
            wave_result=wave_result,
        )
    assert any(
        DIAGNOSTIC_LOG_TAG in record.message for record in caplog.records
    ), [r.message for r in caplog.records]
    assert any(
        "milestone=milestone-1" in record.message
        for record in caplog.records
    )
    # WaveFinding extension
    assert len(wave_result.findings) == 1
    assert wave_result.findings[0].code == CONTRACT_DRIFT_DIAGNOSTIC_CODE
    assert wave_result.findings[0].severity == DIAGNOSTIC_SEVERITY


def test_cross_package_diag_log_fires_on_zero_divergences(tmp_path, caplog):
    """The log MUST fire even when the diagnostic was a clean zero so
    operators see the step ran (per Q3 + AC7 wording)."""

    from agent_team_v15.wave_executor import (
        WaveResult,
        _emit_phase_5_8a_diagnostic,
    )

    contract_result = {
        "diagnostic_findings": [],
        "diagnostic_metrics": {
            "schemas_in_spec": 3,
            "exports_in_client": 3,
            "divergences_detected_total": 0,
            "unique_divergence_classes": [],
        },
        "diagnostic_tooling": {
            "ts_parser": TOOLING_PARSER_NODE_TS_AST,
            "ts_parser_version": "5.4.5",
            "error": "",
        },
        "diagnostic_unsupported_polymorphic_schemas": [],
    }

    class _M:
        id = "milestone-2"

    wave_result = WaveResult(wave="C")
    with caplog.at_level(logging.INFO, logger="agent_team_v15.wave_executor"):
        _emit_phase_5_8a_diagnostic(
            cwd=str(tmp_path),
            milestone=_M(),
            contract_result=contract_result,
            wave_result=wave_result,
        )
    assert any(
        DIAGNOSTIC_LOG_TAG in record.message for record in caplog.records
    )
    assert wave_result.findings == []  # no false-positive findings


def test_cross_package_diag_log_fires_on_tooling_unavailable(tmp_path, caplog):
    """When the parser is unavailable, the log MUST surface the tooling
    error string, and ZERO drift findings emit (Q3)."""

    from agent_team_v15.wave_executor import (
        WaveResult,
        _emit_phase_5_8a_diagnostic,
    )

    contract_result = {
        "diagnostic_findings": [],
        "diagnostic_metrics": {
            "schemas_in_spec": 0,
            "exports_in_client": 0,
            "divergences_detected_total": 0,
            "unique_divergence_classes": [],
        },
        "diagnostic_tooling": {
            "ts_parser": TOOLING_PARSER_UNAVAILABLE,
            "ts_parser_version": "",
            "error": "node_unavailable: node binary not on PATH",
        },
        "diagnostic_unsupported_polymorphic_schemas": [],
    }

    class _M:
        id = "milestone-1"

    wave_result = WaveResult(wave="C")
    with caplog.at_level(logging.INFO, logger="agent_team_v15.wave_executor"):
        _emit_phase_5_8a_diagnostic(
            cwd=str(tmp_path),
            milestone=_M(),
            contract_result=contract_result,
            wave_result=wave_result,
        )
    assert any(
        DIAGNOSTIC_LOG_TAG in record.message and "tooling_error" in record.message
        for record in caplog.records
    )
    assert wave_result.findings == []  # tooling-unavailable → ZERO findings (Q3)


# ---------------------------------------------------------------------------
# AC8 — PHASE_5_8A_DIAGNOSTIC.json schema locked + per-milestone path
# ---------------------------------------------------------------------------


def test_phase_5_8a_diagnostic_json_schema_locked(tmp_path):
    cwd = tmp_path
    outcome = DiagnosticOutcome(
        divergences=[
            DivergenceRecord(
                divergence_class=DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                schema_name="UserDto",
                property_name="user_id",
                spec_value="user_id",
                client_value="userId",
                client_file="packages/api-client/types.gen.ts",
                client_line=3,
                details="case",
            )
        ],
        metrics={
            "schemas_in_spec": 1,
            "exports_in_client": 1,
            "divergences_detected_total": 1,
            "unique_divergence_classes": [DIVERGENCE_CLASS_CAMEL_VS_SNAKE],
        },
        tooling={
            "ts_parser": TOOLING_PARSER_NODE_TS_AST,
            "ts_parser_version": "5.4.5",
            "error": "",
        },
        unsupported_polymorphic_schemas=[],
    )
    target = write_phase_5_8a_diagnostic(
        cwd=str(cwd),
        milestone_id="milestone-1",
        outcome=outcome,
        smoke_id="smoke-2026-01-01",
        correlated_compile_failures=2,
        timestamp="2026-04-29T00:00:00+00:00",
    )
    assert target is not None
    expected = (
        cwd
        / ".agent-team"
        / "milestones"
        / "milestone-1"
        / PHASE_5_8A_DIAGNOSTIC_FILENAME
    )
    assert target == expected
    payload = json.loads(target.read_text(encoding="utf-8"))

    # Schema lock — every top-level key + nested key matters for the K.2
    # evaluator. Future Phase 5.8b implementer (or Wave A spec-quality
    # follow-up) consumes this exact shape.
    assert payload["phase"] == "5.8a"
    assert payload["milestone_id"] == "milestone-1"
    assert payload["smoke_id"] == "smoke-2026-01-01"
    assert payload["generated_at"] == "2026-04-29T00:00:00+00:00"
    metrics = payload["metrics"]
    assert metrics["schemas_in_spec"] == 1
    assert metrics["exports_in_client"] == 1
    assert metrics["divergences_detected_total"] == 1
    assert metrics["unique_divergence_classes"] == [
        DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
    ]
    assert metrics["divergences_correlated_with_compile_failures"] == 2
    div = payload["divergences"][0]
    assert set(div.keys()) == {
        "divergence_class",
        "schema_name",
        "property_name",
        "spec_value",
        "client_value",
        "client_file",
        "client_line",
        "details",
    }
    assert div["divergence_class"] == DIVERGENCE_CLASS_CAMEL_VS_SNAKE
    assert payload["unsupported_polymorphic_schemas"] == []
    tooling = payload["tooling"]
    assert tooling["ts_parser"] == TOOLING_PARSER_NODE_TS_AST
    assert tooling["ts_parser_version"] == "5.4.5"
    assert tooling["error"] == ""


def test_per_milestone_artifact_path_isolates_m1_and_m2(tmp_path):
    """M1+M2 smokes do NOT collide on the artifact path (correction #3)."""

    write_phase_5_8a_diagnostic(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        outcome=DiagnosticOutcome(
            metrics={
                "schemas_in_spec": 1,
                "exports_in_client": 1,
                "divergences_detected_total": 0,
                "unique_divergence_classes": [],
            },
            tooling={"ts_parser": TOOLING_PARSER_NODE_TS_AST, "ts_parser_version": "5.4.5", "error": ""},
        ),
        timestamp="2026-04-29T00:00:00+00:00",
    )
    write_phase_5_8a_diagnostic(
        cwd=str(tmp_path),
        milestone_id="milestone-2",
        outcome=DiagnosticOutcome(
            metrics={
                "schemas_in_spec": 1,
                "exports_in_client": 1,
                "divergences_detected_total": 5,
                "unique_divergence_classes": [DIVERGENCE_CLASS_CAMEL_VS_SNAKE],
            },
            tooling={"ts_parser": TOOLING_PARSER_NODE_TS_AST, "ts_parser_version": "5.4.5", "error": ""},
        ),
        timestamp="2026-04-29T00:00:00+00:00",
    )
    p1 = (
        tmp_path
        / ".agent-team"
        / "milestones"
        / "milestone-1"
        / PHASE_5_8A_DIAGNOSTIC_FILENAME
    )
    p2 = (
        tmp_path
        / ".agent-team"
        / "milestones"
        / "milestone-2"
        / PHASE_5_8A_DIAGNOSTIC_FILENAME
    )
    assert p1.is_file()
    assert p2.is_file()
    assert (
        json.loads(p1.read_text())["metrics"]["divergences_detected_total"] == 0
    )
    assert (
        json.loads(p2.read_text())["metrics"]["divergences_detected_total"] == 5
    )
    # No root-level artifact (correction #3 — the wrong path).
    assert not (tmp_path / ".agent-team" / PHASE_5_8A_DIAGNOSTIC_FILENAME).exists()


# ---------------------------------------------------------------------------
# Diagnostic crash isolation (Q2 — diagnostic NEVER fails Wave C)
# ---------------------------------------------------------------------------


def test_compute_divergences_parser_override_raise_does_not_propagate(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "UserDto": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    )

    def _exploding_parser(file_path, project_root):
        raise RuntimeError("synthetic parser explosion")

    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_exploding_parser,
    )
    # No drift findings; tooling reports the failure.
    assert outcome.divergences == []
    assert outcome.tooling["ts_parser"] == TOOLING_PARSER_UNAVAILABLE
    assert "parser_override_failed" in outcome.tooling["error"]
    assert outcome.metrics["divergences_detected_total"] == 0


def test_emit_phase_5_8a_diagnostic_handles_empty_contract_result(tmp_path, caplog):
    """Minimal-ts fallback path → empty diagnostic fields → emit stays
    silent (no log, no findings, no artifact)."""

    from agent_team_v15.wave_executor import (
        WaveResult,
        _emit_phase_5_8a_diagnostic,
    )

    class _M:
        id = "milestone-1"

    wave_result = WaveResult(wave="C")
    with caplog.at_level(logging.INFO, logger="agent_team_v15.wave_executor"):
        _emit_phase_5_8a_diagnostic(
            cwd=str(tmp_path),
            milestone=_M(),
            contract_result={},
            wave_result=wave_result,
        )
    assert wave_result.findings == []
    # No log + no artifact.
    assert not any(
        DIAGNOSTIC_LOG_TAG in record.message for record in caplog.records
    )
    artifact = (
        tmp_path
        / ".agent-team"
        / "milestones"
        / "milestone-1"
        / PHASE_5_8A_DIAGNOSTIC_FILENAME
    )
    assert not artifact.exists()


# ---------------------------------------------------------------------------
# _coerce_contract_result threading (correction #5)
# ---------------------------------------------------------------------------


def test_coerce_contract_result_threads_diagnostic_fields():
    from agent_team_v15.openapi_generator import ContractResult
    from agent_team_v15.wave_executor import _coerce_contract_result

    cr = ContractResult(
        success=True,
        client_generator="openapi-ts",
        diagnostic_findings=[{"code": CONTRACT_DRIFT_DIAGNOSTIC_CODE}],
        diagnostic_metrics={"divergences_detected_total": 1},
        diagnostic_tooling={"ts_parser": TOOLING_PARSER_NODE_TS_AST},
        diagnostic_unsupported_polymorphic_schemas=["PolyDto"],
    )
    coerced = _coerce_contract_result(cr)
    assert coerced["diagnostic_findings"] == [
        {"code": CONTRACT_DRIFT_DIAGNOSTIC_CODE},
    ]
    assert coerced["diagnostic_metrics"] == {"divergences_detected_total": 1}
    assert coerced["diagnostic_tooling"] == {
        "ts_parser": TOOLING_PARSER_NODE_TS_AST,
    }
    assert coerced["diagnostic_unsupported_polymorphic_schemas"] == ["PolyDto"]


def test_coerce_contract_result_legacy_dataclass_yields_empty_diagnostics():
    """Legacy ContractResult (pre-Phase-5.8a defaults) coerces to empty
    diagnostic fields without raising."""

    from agent_team_v15.openapi_generator import ContractResult
    from agent_team_v15.wave_executor import _coerce_contract_result

    cr = ContractResult(success=True, client_generator="minimal-ts")
    coerced = _coerce_contract_result(cr)
    assert coerced["diagnostic_findings"] == []
    assert coerced["diagnostic_metrics"] == {}
    assert coerced["diagnostic_tooling"] == {}
    assert coerced["diagnostic_unsupported_polymorphic_schemas"] == []


# ---------------------------------------------------------------------------
# §K.2 decision-gate predicate
# ---------------------------------------------------------------------------


def test_k2_decision_gate_satisfied_3_distinct_dtos_same_class():
    """3 distinct schemas sharing the SAME divergence_class across the
    smoke batch → predicate satisfied."""

    diagnostics = [
        {
            "divergences": [
                {
                    "divergence_class": DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                    "schema_name": "UserDto",
                },
                {
                    "divergence_class": DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                    "schema_name": "OrderDto",
                },
            ]
        },
        {
            "divergences": [
                {
                    "divergence_class": DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                    "schema_name": "PaymentDto",
                },
            ]
        },
    ]
    assert k2_decision_gate_satisfied(diagnostics, correlated_threshold=3)


def test_k2_decision_gate_NOT_satisfied_3_props_one_dto_same_class():
    """3 properties on ONE DTO sharing the same class → NOT satisfied
    (correction #1: distinct-schema discipline is the predicate)."""

    diagnostics = [
        {
            "divergences": [
                {
                    "divergence_class": DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                    "schema_name": "UserDto",
                    "property_name": "user_id",
                },
                {
                    "divergence_class": DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                    "schema_name": "UserDto",
                    "property_name": "first_name",
                },
                {
                    "divergence_class": DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                    "schema_name": "UserDto",
                    "property_name": "last_name",
                },
            ]
        },
    ]
    assert not k2_decision_gate_satisfied(
        diagnostics,
        correlated_threshold=3,
    )


def test_k2_decision_gate_NOT_satisfied_3_distinct_dtos_different_classes():
    """3 distinct schemas with different classes → NOT satisfied (need
    same-class correlation)."""

    diagnostics = [
        {
            "divergences": [
                {
                    "divergence_class": DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                    "schema_name": "UserDto",
                },
                {
                    "divergence_class": DIVERGENCE_CLASS_OPTIONAL_VS_REQUIRED,
                    "schema_name": "OrderDto",
                },
                {
                    "divergence_class": DIVERGENCE_CLASS_TYPE_MISMATCH,
                    "schema_name": "PaymentDto",
                },
            ]
        },
    ]
    assert not k2_decision_gate_satisfied(
        diagnostics,
        correlated_threshold=3,
    )


def test_k2_decision_gate_empty_input():
    assert k2_decision_gate_satisfied([], correlated_threshold=3) is False
    assert (
        k2_decision_gate_satisfied(
            [{"divergences": []}], correlated_threshold=3,
        )
        is False
    )


# ---------------------------------------------------------------------------
# Tooling-unavailable shape — visible in artifact, ZERO drift findings (Q3)
# ---------------------------------------------------------------------------


def test_tooling_unavailable_emits_no_drift_findings(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = _write_spec(
        contracts_dir,
        {
            "UserDto": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    )

    def _failing_parser(file_path, project_root):
        return {"exports": [], "error": "node_unavailable: no node"}

    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_failing_parser,
    )
    assert outcome.divergences == []
    assert outcome.tooling["ts_parser"] == TOOLING_PARSER_UNAVAILABLE
    assert "node_unavailable" in outcome.tooling["error"]
    assert outcome.metrics["divergences_detected_total"] == 0


def test_missing_types_gen_yields_tooling_unavailable(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    # Intentionally omit types.gen.ts.
    spec_path = _write_spec(
        contracts_dir,
        {
            "UserDto": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    )
    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([]),
    )
    assert outcome.divergences == []
    assert outcome.tooling["ts_parser"] == TOOLING_PARSER_UNAVAILABLE
    assert "client_types_gen_missing" in outcome.tooling["error"]


def test_invalid_spec_json_yields_tooling_unavailable(tmp_workspace):
    project_root, contracts_dir, client_dir = tmp_workspace
    _write_types_gen(client_dir)
    spec_path = contracts_dir / "current.json"
    spec_path.write_text("not valid json {{", encoding="utf-8")

    outcome = compute_divergences(
        spec_path=spec_path,
        client_dir=client_dir,
        project_root=project_root,
        parser_override=_stub_parser([]),
    )
    assert outcome.divergences == []
    assert outcome.tooling["ts_parser"] == TOOLING_PARSER_UNAVAILABLE
    assert "spec_load_failed" in outcome.tooling["error"]


# ---------------------------------------------------------------------------
# Constants smoke
# ---------------------------------------------------------------------------


def test_finding_code_and_severity_constants_match_dispatch():
    assert CONTRACT_DRIFT_DIAGNOSTIC_CODE == "CONTRACT-DRIFT-DIAGNOSTIC-001"
    assert DIAGNOSTIC_SEVERITY == "LOW"
    assert DIAGNOSTIC_VERDICT_HINT == "UNVERIFIED"
    assert DIAGNOSTIC_LOG_TAG == "[CROSS-PACKAGE-DIAG]"
    assert PHASE_5_8A_DIAGNOSTIC_FILENAME == "PHASE_5_8A_DIAGNOSTIC.json"
    assert set(ALL_DIVERGENCE_CLASSES) == {
        DIVERGENCE_CLASS_MISSING_EXPORT,
        DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
        DIVERGENCE_CLASS_OPTIONAL_VS_REQUIRED,
        DIVERGENCE_CLASS_TYPE_MISMATCH,
    }


# ---------------------------------------------------------------------------
# Phase 5 closeout — strict_mode recording (additive; does not change the
# legacy schema when caller does not supply the value)
# ---------------------------------------------------------------------------


def _minimal_outcome() -> DiagnosticOutcome:
    return DiagnosticOutcome(
        divergences=[],
        metrics={
            "schemas_in_spec": 0,
            "exports_in_client": 0,
            "divergences_detected_total": 0,
            "unique_divergence_classes": [],
        },
        tooling={
            "ts_parser": TOOLING_PARSER_NODE_TS_AST,
            "ts_parser_version": "5.4.5",
            "error": "",
        },
        unsupported_polymorphic_schemas=[],
    )


def test_writer_default_strict_mode_none_preserves_legacy_shape(tmp_path):
    """Phase 5 closeout — strict_mode kwarg unset MUST NOT add the field.

    Existing direct callers of write_phase_5_8a_diagnostic that don't
    supply the kwarg get byte-identical schema vs pre-Phase-5-closeout
    output. The K.2 evaluator's missing-strict-mode handling kicks in
    instead.
    """

    target = write_phase_5_8a_diagnostic(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        outcome=_minimal_outcome(),
        smoke_id="smoke-1",
        timestamp="2026-04-29T00:00:00+00:00",
    )
    assert target is not None
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert "strict_mode" not in payload


def test_writer_with_strict_on_emits_top_level_strict_mode(tmp_path):
    """Phase 5 closeout — strict_mode=True records "ON" at top level."""

    target = write_phase_5_8a_diagnostic(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        outcome=_minimal_outcome(),
        timestamp="2026-04-29T00:00:00+00:00",
        strict_mode=True,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["strict_mode"] == "ON"


def test_writer_with_strict_off_emits_top_level_strict_mode_off(tmp_path):
    """Phase 5 closeout — strict_mode=False records "OFF" at top level."""

    target = write_phase_5_8a_diagnostic(
        cwd=str(tmp_path),
        milestone_id="milestone-2",
        outcome=_minimal_outcome(),
        timestamp="2026-04-29T00:00:00+00:00",
        strict_mode=False,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["strict_mode"] == "OFF"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("ON", "ON"),
        ("on", "ON"),
        ("On", "ON"),
        ("True", "ON"),
        ("true", "ON"),
        ("1", "ON"),
        ("YES", "ON"),
        ("OFF", "OFF"),
        ("off", "OFF"),
        ("False", "OFF"),
        ("0", "OFF"),
        ("NO", "OFF"),
    ],
)
def test_writer_normalizes_string_strict_mode_values(tmp_path, value, expected):
    """Phase 5 closeout — string strict_mode values normalised case-insensitively."""

    target = write_phase_5_8a_diagnostic(
        cwd=str(tmp_path),
        milestone_id=f"milestone-{value}",
        outcome=_minimal_outcome(),
        timestamp="2026-04-29T00:00:00+00:00",
        strict_mode=value,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["strict_mode"] == expected


def test_writer_rejects_unrecognised_strict_mode(tmp_path):
    """Phase 5 closeout — typos surface immediately, not via corrupted artifact."""

    with pytest.raises(ValueError, match="unrecognised strict_mode"):
        write_phase_5_8a_diagnostic(
            cwd=str(tmp_path),
            milestone_id="milestone-1",
            outcome=_minimal_outcome(),
            strict_mode="maybe",
        )


def test_writer_strict_mode_does_not_drift_other_schema_keys(tmp_path):
    """Phase 5 closeout — schema-locked test contract preserved with strict_mode set."""

    outcome = DiagnosticOutcome(
        divergences=[
            DivergenceRecord(
                divergence_class=DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                schema_name="UserDto",
                property_name="user_id",
                spec_value="user_id",
                client_value="userId",
                client_file="packages/api-client/types.gen.ts",
                client_line=3,
                details="case",
            )
        ],
        metrics={
            "schemas_in_spec": 1,
            "exports_in_client": 1,
            "divergences_detected_total": 1,
            "unique_divergence_classes": [DIVERGENCE_CLASS_CAMEL_VS_SNAKE],
        },
        tooling={
            "ts_parser": TOOLING_PARSER_NODE_TS_AST,
            "ts_parser_version": "5.4.5",
            "error": "",
        },
        unsupported_polymorphic_schemas=[],
    )
    target = write_phase_5_8a_diagnostic(
        cwd=str(tmp_path),
        milestone_id="milestone-1",
        outcome=outcome,
        smoke_id="smoke-2026-01-01",
        correlated_compile_failures=2,
        timestamp="2026-04-29T00:00:00+00:00",
        strict_mode=True,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    # All AC8 schema-lock keys present + strict_mode added.
    assert payload["phase"] == "5.8a"
    assert payload["milestone_id"] == "milestone-1"
    assert payload["smoke_id"] == "smoke-2026-01-01"
    assert payload["generated_at"] == "2026-04-29T00:00:00+00:00"
    assert payload["strict_mode"] == "ON"
    assert payload["metrics"]["divergences_correlated_with_compile_failures"] == 2
    div = payload["divergences"][0]
    assert set(div.keys()) == {
        "divergence_class",
        "schema_name",
        "property_name",
        "spec_value",
        "client_value",
        "client_file",
        "client_line",
        "details",
    }
    assert payload["unsupported_polymorphic_schemas"] == []
    assert payload["tooling"]["ts_parser"] == TOOLING_PARSER_NODE_TS_AST


def test_emit_phase_5_8a_diagnostic_threads_strict_mode_to_writer(tmp_path):
    """Phase 5 closeout — _emit_phase_5_8a_diagnostic forwards strict-mode flag.

    The Wave C call site reads ``config.runtime_verification.tsc_strict_check_enabled``
    and passes it through ``_execute_wave_c`` →
    ``_emit_phase_5_8a_diagnostic`` → ``write_phase_5_8a_diagnostic``.
    This test exercises the helper directly with the kwarg set.
    """

    from agent_team_v15.wave_executor import (
        WaveResult,
        _emit_phase_5_8a_diagnostic,
    )

    contract_result = {
        "diagnostic_findings": [
            {
                "code": CONTRACT_DRIFT_DIAGNOSTIC_CODE,
                "severity": DIAGNOSTIC_SEVERITY,
                "file": "packages/api-client/types.gen.ts",
                "line": 1,
                "message": "[Phase 5.8a advisory] divergence",
                "divergence_class": DIVERGENCE_CLASS_CAMEL_VS_SNAKE,
                "schema_name": "UserDto",
                "property_name": "user_id",
                "spec_value": "user_id",
                "client_value": "userId",
                "details": "case",
            }
        ],
        "diagnostic_metrics": {
            "schemas_in_spec": 1,
            "exports_in_client": 1,
            "divergences_detected_total": 1,
            "unique_divergence_classes": [DIVERGENCE_CLASS_CAMEL_VS_SNAKE],
        },
        "diagnostic_tooling": {
            "ts_parser": TOOLING_PARSER_NODE_TS_AST,
            "ts_parser_version": "5.4.5",
            "error": "",
        },
        "diagnostic_unsupported_polymorphic_schemas": [],
    }

    class _M:
        id = "milestone-1"

    wave_result = WaveResult(wave="C")
    _emit_phase_5_8a_diagnostic(
        cwd=str(tmp_path),
        milestone=_M(),
        contract_result=contract_result,
        wave_result=wave_result,
        tsc_strict_enabled=True,
    )
    target = (
        tmp_path
        / ".agent-team"
        / "milestones"
        / "milestone-1"
        / PHASE_5_8A_DIAGNOSTIC_FILENAME
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["strict_mode"] == "ON"


def test_emit_phase_5_8a_diagnostic_omits_strict_mode_when_kwarg_default(tmp_path):
    """Phase 5 closeout — emit helper preserves legacy artifact shape on default."""

    from agent_team_v15.wave_executor import (
        WaveResult,
        _emit_phase_5_8a_diagnostic,
    )

    contract_result = {
        "diagnostic_findings": [],
        "diagnostic_metrics": {
            "schemas_in_spec": 0,
            "exports_in_client": 0,
            "divergences_detected_total": 0,
            "unique_divergence_classes": [],
        },
        "diagnostic_tooling": {
            "ts_parser": TOOLING_PARSER_NODE_TS_AST,
            "ts_parser_version": "5.4.5",
            "error": "",
        },
        "diagnostic_unsupported_polymorphic_schemas": [],
    }

    class _M:
        id = "milestone-1"

    wave_result = WaveResult(wave="C")
    _emit_phase_5_8a_diagnostic(
        cwd=str(tmp_path),
        milestone=_M(),
        contract_result=contract_result,
        wave_result=wave_result,
        # tsc_strict_enabled NOT passed — default None.
    )
    target = (
        tmp_path
        / ".agent-team"
        / "milestones"
        / "milestone-1"
        / PHASE_5_8A_DIAGNOSTIC_FILENAME
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert "strict_mode" not in payload
