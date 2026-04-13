from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_team_v15.cli as cli_module
import agent_team_v15.milestone_manager as milestone_manager_module
import agent_team_v15.wave_executor as wave_executor_module
from agent_team_v15 import endpoint_prober as endpoint_prober_module
from agent_team_v15.agents import build_wave_prompt
from agent_team_v15.audit_agent import (
    AcceptanceCriterion,
    CheckResult,
    _apply_evidence_gating_to_results,
    _parse_ac_results_from_response,
)
from agent_team_v15.audit_models import AuditFinding, build_report
from agent_team_v15.cli import _apply_evidence_gating_to_audit_report, _prepare_wave_sdk_options
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.evidence_ledger import (
    EvidenceLedger,
    EvidenceRecord,
    map_endpoint_to_acs,
    map_integration_to_acs,
    resolve_collector_availability,
)
from agent_team_v15.endpoint_prober import ProbeResult, _collect_endpoints, collect_probe_evidence, generate_probe_manifest
from agent_team_v15.fix_executor import _check_contract_sensitive, analyze_blast_radius, is_foundation_fix, run_regression_check
from agent_team_v15.milestone_manager import MasterPlan, MasterPlanMilestone, MilestoneManager
from agent_team_v15.wave_executor import execute_milestone_waves


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _milestone(
    milestone_id: str = "milestone-orders",
    *,
    template: str = "full_stack",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title="Orders",
        template=template,
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _product_ir() -> dict[str, object]:
    return {
        "acceptance_criteria": [
            {"id": "AC-1", "feature": "F-ORDERS", "text": "Create and view orders"},
            {"id": "AC-2", "feature": "F-PAYMENTS", "text": "Stripe payment sync"},
        ],
        "endpoints": [
            {"method": "POST", "path": "/orders", "owner_feature": "F-ORDERS", "protected": True},
            {"method": "GET", "path": "/orders/:id", "owner_feature": "F-ORDERS"},
        ],
        "integrations": [{"vendor": "Stripe", "type": "payment"}],
    }


def _soft_gate_config(*, live_endpoint_check: bool = True) -> AgentTeamConfig:
    config = AgentTeamConfig()
    config.v18.execution_mode = "wave"
    config.v18.evidence_mode = "soft_gate"
    config.v18.live_endpoint_check = live_endpoint_check
    return config


def test_generate_probe_manifest_for_protected_mutating_route() -> None:
    manifest = generate_probe_manifest(
        milestone_id="milestone-orders",
        wave_b_artifact={
            "controllers": [
                {
                    "name": "OrdersController",
                    "endpoints": [
                        {"method": "POST", "path": "/orders/:id/approve", "handler": "approve"},
                    ],
                }
            ],
            "dtos": [
                {
                    "name": "ApproveOrderDto",
                    "fields": [{"name": "note", "type": "string", "optional": False, "decorators": []}],
                }
            ],
        },
        openapi_spec_path=None,
        ir={
            "endpoints": [
                {"method": "POST", "path": "/orders/:id/approve", "protected": True},
            ]
        },
        seed_fixtures={"id": "123e4567-e89b-12d3-a456-426614174000"},
    )

    probe_types = {probe.probe_type for probe in manifest.probes}
    assert probe_types == {"happy_path", "401_unauthenticated", "400_invalid_body", "404_not_found"}


def test_generate_probe_manifest_for_creation_route_adds_duplicate_probe() -> None:
    manifest = generate_probe_manifest(
        milestone_id="milestone-orders",
        wave_b_artifact={
            "controllers": [
                {
                    "name": "OrdersController",
                    "endpoints": [
                        {"method": "POST", "path": "/orders", "handler": "create"},
                    ],
                }
            ],
            "dtos": [
                {
                    "name": "CreateOrderDto",
                    "fields": [{"name": "name", "type": "string", "optional": False, "decorators": []}],
                }
            ],
        },
        openapi_spec_path=None,
        ir={},
        seed_fixtures={"orders": [{"name": "existing"}], "name": "existing"},
    )

    probe_types = {probe.probe_type for probe in manifest.probes}
    assert "409_duplicate" in probe_types
    assert "400_invalid_body" in probe_types


def test_public_readonly_parameterized_route_only_gets_happy_and_404() -> None:
    manifest = generate_probe_manifest(
        milestone_id="milestone-orders",
        wave_b_artifact={
            "controllers": [
                {
                    "name": "OrdersController",
                    "endpoints": [
                        {"method": "GET", "path": "/orders/:id", "handler": "getOne"},
                    ],
                }
            ],
            "dtos": [],
        },
        openapi_spec_path=None,
        ir={},
        seed_fixtures={"id": "123e4567-e89b-12d3-a456-426614174000"},
    )

    probe_types = {probe.probe_type for probe in manifest.probes}
    assert probe_types == {"happy_path", "404_not_found"}


def test_collect_probe_evidence_maps_http_transcripts_to_acs(tmp_path: Path) -> None:
    product_ir_dir = tmp_path / ".agent-team" / "product-ir"
    product_ir_dir.mkdir(parents=True, exist_ok=True)
    (product_ir_dir / "product.ir.json").write_text(json.dumps(_product_ir()), encoding="utf-8")

    manifest = generate_probe_manifest(
        milestone_id="milestone-orders",
        wave_b_artifact={
            "controllers": [{"name": "OrdersController", "endpoints": [{"method": "POST", "path": "/orders", "handler": "create"}]}],
            "dtos": [{"name": "CreateOrderDto", "fields": [{"name": "name", "type": "string", "optional": False, "decorators": []}]}],
        },
        openapi_spec_path=None,
        ir=_product_ir(),
        seed_fixtures={"name": "existing"},
    )
    probe = manifest.probes[0]
    manifest.results = [
        ProbeResult(
            spec=probe,
            actual_status=probe.expected_status,
            passed=True,
            response_body='{"ok": true}',
            duration_ms=5.0,
        )
    ]

    evidence_pairs = collect_probe_evidence(manifest, str(tmp_path))

    assert len(evidence_pairs) == 1
    assert evidence_pairs[0][0] == "AC-1"
    assert evidence_pairs[0][1].type == "http_transcript"


def test_collect_endpoints_falls_back_to_ir_when_artifact_and_spec_missing() -> None:
    endpoints = _collect_endpoints(
        wave_b_artifact={},
        spec_path=None,
        ir={"endpoints": [{"method": "GET", "path": "/orders", "owner_feature": "F-ORDERS", "tags": ["orders"]}]},
    )

    assert endpoints[0]["method"] == "GET"
    assert endpoints[0]["path"] == "/orders"
    assert endpoints[0]["owner_feature"] == "F-ORDERS"


def test_resolve_collector_availability_detects_milestone_scoped_evidence_outputs(tmp_path: Path) -> None:
    config = _soft_gate_config(live_endpoint_check=True)
    _write(
        tmp_path / ".agent-team" / "MASTER_PLAN.json",
        json.dumps(
            {
                "milestones": [
                    {"id": "milestone-orders", "ac_refs": ["AC-1", "AC-2"]},
                    {"id": "milestone-payments", "ac_refs": ["AC-3"]},
                ]
            },
            indent=2,
        ),
    )
    ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
    ledger.record_evidence("AC-1", EvidenceRecord(type="http_transcript", content="HTTP 201"), verdict="PASS")
    ledger.record_evidence("AC-1", EvidenceRecord(type="db_assertion", content="SELECT 1"), verdict="PASS")
    ledger.record_evidence("AC-1", EvidenceRecord(type="simulator_state", content='{"ok":true}'), verdict="PASS")
    ledger.record_evidence("AC-2", EvidenceRecord(type="playwright_trace", content="trace.zip"), verdict="PASS")
    ledger.record_evidence("AC-3", EvidenceRecord(type="db_assertion", content="other milestone"), verdict="PASS")
    _write(tmp_path / "e2e" / "tests" / "milestone-orders" / "orders.spec.ts", "test('orders', () => {});\n")

    availability = resolve_collector_availability(
        milestone_id="milestone-orders",
        milestone_template="full_stack",
        config=config,
        cwd=str(tmp_path),
    )

    assert availability["code_span"] is True
    assert availability["http_transcript"] is True
    assert availability["db_assertion"] is True
    assert availability["simulator_state"] is True
    assert availability["playwright_trace"] is True

    frontend_only = resolve_collector_availability(
        milestone_id="milestone-orders",
        milestone_template="frontend_only",
        config=config,
        cwd=str(tmp_path),
    )
    assert frontend_only["http_transcript"] is False

    payments = resolve_collector_availability(
        milestone_id="milestone-payments",
        milestone_template="full_stack",
        config=config,
        cwd=str(tmp_path),
    )
    assert payments["db_assertion"] is True
    assert payments["http_transcript"] is False
    assert payments["playwright_trace"] is False


def test_evidence_gate_soft_and_hard_modes(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "evidence")
    ledger.set_required_evidence("AC-1", ["http_transcript"])
    ledger.record_evidence("AC-1", EvidenceRecord(type="code_span", content="impl"), verdict="PASS")

    assert ledger.evaluate_with_evidence_gate("AC-1", "PASS", "soft_gate", {"http_transcript": True}) == "PARTIAL"
    assert ledger.evaluate_with_evidence_gate("AC-1", "PASS", "soft_gate", {"http_transcript": False}) == "UNVERIFIED"
    assert ledger.evaluate_with_evidence_gate("AC-1", "PASS", "hard_gate", {"http_transcript": True}) == "PARTIAL"
    assert ledger.evaluate_with_evidence_gate("AC-1", "FAIL", "soft_gate", {"http_transcript": True}) == "FAIL"


def test_map_endpoint_and_integration_to_acs_use_product_ir(tmp_path: Path) -> None:
    product_ir_dir = tmp_path / ".agent-team" / "product-ir"
    product_ir_dir.mkdir(parents=True, exist_ok=True)
    (product_ir_dir / "product.ir.json").write_text(json.dumps(_product_ir()), encoding="utf-8")

    assert map_endpoint_to_acs("POST", "/orders", str(tmp_path)) == ["AC-1"]
    assert map_integration_to_acs("Stripe", "charge", str(tmp_path)) == ["AC-2"]


def test_patch_lane_helpers_detect_blast_radius_and_contract_sensitivity(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "quotation" / "quotation.service.ts", "export class QuotationService {}\n")
    _write(
        tmp_path / "src" / "quotation" / "quotation.controller.ts",
        "import { QuotationService } from './quotation.service';\nexport class QuotationController {}\n",
    )
    _write(
        tmp_path / "src" / "quotation" / "quotation.module.ts",
        "import { QuotationController } from './quotation.controller';\nimport { QuotationService } from './quotation.service';\n",
    )
    _write(tmp_path / "src" / "quotation" / "quotation.dto.ts", "@ApiProperty()\nexport class QuotationDto {}\n")

    blast_radius = analyze_blast_radius(["src/quotation/quotation.service.ts"], tmp_path)

    assert "src/quotation/quotation.controller.ts" in blast_radius["affected_files"]
    assert "src/quotation/quotation.module.ts" in blast_radius["affected_files"]
    assert blast_radius["crosses_boundary"] is False
    assert _check_contract_sensitive(["src/quotation/quotation.controller.ts"], tmp_path) is True
    assert _check_contract_sensitive(["src/quotation/quotation.service.ts"], tmp_path) is False
    assert is_foundation_fix([{"files_to_modify": ["src/app.module.ts"]}]) is True


def test_run_regression_check_without_e2e_dir_is_safe(tmp_path: Path) -> None:
    assert run_regression_check(str(tmp_path), ["AC-1"], AgentTeamConfig()) == []


def test_prepare_wave_sdk_options_adds_playwright_only_for_wave_e_frontend() -> None:
    base_options = SimpleNamespace(mcp_servers={}, allowed_tools=["Read"])
    config = _soft_gate_config(live_endpoint_check=True)

    wave_e_options = _prepare_wave_sdk_options(base_options, config, "E", _milestone(template="full_stack"))
    wave_b_options = _prepare_wave_sdk_options(base_options, config, "B", _milestone(template="full_stack"))

    assert "playwright" in wave_e_options.mcp_servers
    assert "playwright" not in wave_b_options.mcp_servers


def test_cli_audit_report_downgrades_when_available_evidence_is_missing(tmp_path: Path) -> None:
    config = _soft_gate_config(live_endpoint_check=True)
    _write(
        tmp_path / ".agent-team" / "MASTER_PLAN.json",
        json.dumps({"milestones": [{"id": "milestone-orders", "ac_refs": ["AC-1", "AC-2"]}]}, indent=2),
    )
    ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
    ledger.set_required_evidence("AC-1", ["http_transcript"])
    ledger.record_evidence("AC-1", EvidenceRecord(type="code_span", content="impl"), verdict="PASS")
    ledger.record_evidence("AC-2", EvidenceRecord(type="http_transcript", content="HTTP 201"), verdict="PASS")

    report = build_report(
        audit_id="audit-gated",
        cycle=1,
        auditors_deployed=["requirements"],
        findings=[
            AuditFinding(
                finding_id="REQ-1",
                auditor="requirements",
                requirement_id="AC-1",
                verdict="PASS",
                severity="LOW",
                summary="Orders look implemented",
                evidence=["src/orders.ts:1"],
                remediation="",
            )
        ],
    )

    gated = _apply_evidence_gating_to_audit_report(
        report,
        milestone_id="milestone-orders",
        milestone_template="full_stack",
        config=config,
        cwd=str(tmp_path),
    )

    assert gated.findings[0].verdict == "PARTIAL"
    assert gated.score.partial == 1


def test_unverified_survives_full_audit_path(tmp_path: Path) -> None:
    config = _soft_gate_config(live_endpoint_check=False)
    _write(
        tmp_path / ".agent-team" / "MASTER_PLAN.json",
        json.dumps({"milestones": [{"id": "milestone-orders", "ac_refs": ["AC-1"]}]}, indent=2),
    )

    ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
    ledger.set_required_evidence("AC-1", ["playwright_trace"])

    results = [CheckResult(ac_id="AC-1", verdict="PASS", evidence="src/orders.ts:1")]
    _apply_evidence_gating_to_results(
        results,
        tmp_path / ".agent-team",
        tmp_path,
        {
            "evidence_mode": "soft_gate",
            "live_endpoint_check": True,
            "current_milestone_id": "milestone-orders",
            "milestone_template": "full_stack",
        },
    )

    assert results[0].verdict == "UNVERIFIED"

    ac_results = _parse_ac_results_from_response(
        "",
        [AcceptanceCriterion(id="AC-1", feature="F-ORDERS", text="Create and view orders")],
        results,
    )
    assert ac_results[0].status == "UNVERIFIED"
    assert ac_results[0].score == 0.5

    report = build_report(
        audit_id="audit-unverified",
        cycle=1,
        auditors_deployed=["requirements"],
        findings=[
            AuditFinding(
                finding_id="REQ-1",
                auditor="requirements",
                requirement_id="AC-1",
                verdict=results[0].verdict,
                severity="LOW",
                summary="Awaiting runtime evidence",
                evidence=["src/orders.ts:1"],
                remediation="",
            )
        ],
    )
    gated = _apply_evidence_gating_to_audit_report(
        report,
        milestone_id="milestone-orders",
        milestone_template="full_stack",
        config=config,
        cwd=str(tmp_path),
    )

    assert gated.findings[0].verdict == "UNVERIFIED"
    assert gated.score.partial == 1
    assert gated.score.score == 50.0
    assert '"verdict": "UNVERIFIED"' in gated.to_json()


@pytest.mark.asyncio
async def test_docker_cleanup_on_build_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = AgentTeamConfig()
    config.v18.execution_mode = "wave"
    config.v18.live_endpoint_check = True
    config.audit_team.enabled = False
    config.tech_research.enabled = False
    config.pseudocode.enabled = False
    config.integration_gate.enabled = False
    config.post_orchestration_scans.infrastructure_scan = False
    config.tracking_documents.milestone_handoff = False
    config.milestone.health_gate = False
    config.gate_enforcement.enforce_architecture = False
    config.gate_enforcement.enforce_pseudocode = False
    config.gate_enforcement.enforce_requirements = False
    config.gate_enforcement.enforce_review_count = False
    config.gate_enforcement.enforce_truth_score = False

    req_dir = tmp_path / config.convergence.requirements_dir
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / config.convergence.master_plan_file).write_text("# plan\n", encoding="utf-8")

    plan = MasterPlan(
        milestones=[MasterPlanMilestone(id="milestone-orders", title="Orders", template="full_stack")]
    )

    monkeypatch.setattr(milestone_manager_module, "parse_master_plan", lambda _content: plan)
    monkeypatch.setattr(milestone_manager_module, "generate_master_plan_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        milestone_manager_module,
        "build_milestone_context",
        lambda *_args, **_kwargs: SimpleNamespace(requirements_path=str(req_dir / "milestones" / "milestone-orders" / "REQUIREMENTS.md")),
    )
    monkeypatch.setattr(milestone_manager_module, "render_predecessor_context", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(milestone_manager_module, "compute_rollup_health", lambda *_args, **_kwargs: {"health": "failed"})
    monkeypatch.setattr(milestone_manager_module, "aggregate_milestone_convergence", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli_module, "_build_completed_milestones_context", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_module, "build_milestone_execution_prompt", lambda **_kwargs: "prompt")

    async def _fail_wave_execution(**_kwargs):
        raise RuntimeError("boom")

    cleanup_calls: list[str] = []
    monkeypatch.setattr(wave_executor_module, "execute_milestone_waves", _fail_wave_execution)
    monkeypatch.setattr(endpoint_prober_module, "stop_docker_containers", lambda cwd: cleanup_calls.append(cwd))

    total_cost, convergence_report = await cli_module._run_prd_milestones(
        task="Build orders",
        config=config,
        cwd=str(tmp_path),
        depth="low",
        prd_path=None,
    )

    assert total_cost == 0.0
    assert convergence_report is None
    assert cleanup_calls == [str(tmp_path), str(tmp_path)]


@pytest.mark.asyncio
async def test_wave_executor_skips_prober_when_flag_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"start": 0}

    async def _start_docker_for_probing(*_args, **_kwargs):
        calls["start"] += 1
        return endpoint_prober_module.DockerContext(app_url="http://localhost:3080", containers_running=True, api_healthy=True)

    monkeypatch.setattr(endpoint_prober_module, "start_docker_for_probing", _start_docker_for_probing)

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = true;\n")
        return 1.0

    async def _run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
        milestone_id = getattr(milestone, "id", "milestone-orders")
        current_spec = _write(Path(cwd) / "contracts" / "openapi" / "current.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
        local_spec = _write(Path(cwd) / "contracts" / "openapi" / f"{milestone_id}.json", json.dumps({"paths": {"/orders": {"get": {}}}}))
        return {
            "success": True,
            "milestone_spec_path": str(local_spec),
            "cumulative_spec_path": str(current_spec),
            "client_exports": ["listOrders"],
            "breaking_changes": [],
            "endpoints_summary": [{"method": "GET", "path": "/orders"}],
            "files_created": [],
        }

    # V18.2: live_endpoint_check defaults to True; this test explicitly
    # verifies that the flag being False skips the prober start call.
    config = AgentTeamConfig()
    config.v18.live_endpoint_check = False

    result = await execute_milestone_waves(
        milestone=_milestone(),
        ir=_product_ir(),
        config=config,
        cwd=str(tmp_path),
        build_wave_prompt=lambda **kwargs: build_wave_prompt(**kwargs),
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=_generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    assert result.success is True
    assert calls["start"] == 0


@pytest.mark.asyncio
async def test_phase3_integration_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end Phase 3 smoke across waves, probing, evidence, audit, and health."""
    milestone = _milestone()
    milestone.ac_refs = ["AC-1", "AC-2"]
    config = _soft_gate_config(live_endpoint_check=True)
    captured: dict[str, object] = {
        "compile_calls": [],
        "prompt_by_wave": {},
        "artifact_keys_for_d": [],
        "probe_total": 0,
        "events": [],
    }

    product_ir_dir = tmp_path / ".agent-team" / "product-ir"
    product_ir_dir.mkdir(parents=True, exist_ok=True)
    (product_ir_dir / "product.ir.json").write_text(json.dumps(_product_ir()), encoding="utf-8")
    _write(
        tmp_path / ".agent-team" / "MASTER_PLAN.json",
        json.dumps(
            {
                "milestones": [
                    {"id": milestone.id, "ac_refs": ["AC-1", "AC-2"]},
                    {"id": "milestone-payments", "ac_refs": ["AC-9"]},
                ]
            },
            indent=2,
        ),
    )
    _write(
        tmp_path / ".agent-team" / "milestones" / milestone.id / "REQUIREMENTS.md",
        "- [x] AC-1: Orders endpoint verified\n- [x] AC-2: Orders UI reviewed\nreview_cycles: 1\n",
    )

    async def _build_prompt(**kwargs: object) -> str:
        prompt = build_wave_prompt(**kwargs)
        wave = str(kwargs["wave"])
        captured["prompt_by_wave"][wave] = prompt
        if wave == "D":
            captured["artifact_keys_for_d"] = sorted(dict(kwargs["wave_artifacts"]).keys())
        return prompt

    async def _execute_sdk_call(*, prompt: str, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            captured["events"].append(f"sdk:{wave}")
            _write(tmp_path / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = {json.dumps(prompt[:20])};\n")
        return 1.25

    async def _run_compile_check(*, wave: str = "", **_: object) -> dict[str, object]:
        captured["compile_calls"].append(wave)
        captured["events"].append(f"compile:{wave}")
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _extract_artifacts(**kwargs: object) -> dict[str, object]:
        wave = str(kwargs["wave"])
        if wave == "B":
            return {
                "controllers": [
                    {"name": "OrdersController", "endpoints": [{"method": "POST", "path": "/orders", "handler": "create"}]},
                ],
                "dtos": [
                    {"name": "CreateOrderDto", "fields": [{"name": "name", "type": "string", "optional": False, "decorators": []}]},
                ],
                "files_created": list(kwargs.get("files_created", []) or []),
                "files_modified": list(kwargs.get("files_modified", []) or []),
            }
        return {
            "wave": wave,
            "files_created": list(kwargs.get("files_created", []) or []),
            "files_modified": list(kwargs.get("files_modified", []) or []),
        }

    async def _generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
        captured["events"].append("contracts")
        milestone_id = getattr(milestone, "id", "milestone-orders")
        current_spec = _write(Path(cwd) / "contracts" / "openapi" / "current.json", json.dumps({"paths": {"/orders": {"post": {}}}}))
        local_spec = _write(Path(cwd) / "contracts" / "openapi" / f"{milestone_id}.json", json.dumps({"paths": {"/orders": {"post": {}}}}))
        return {
            "success": True,
            "milestone_spec_path": str(local_spec),
            "cumulative_spec_path": str(current_spec),
            "client_exports": ["createOrder"],
            "breaking_changes": [],
            "endpoints_summary": [{"method": "POST", "path": "/orders"}],
            "files_created": [
                str(local_spec.relative_to(cwd)).replace("\\", "/"),
                str(current_spec.relative_to(cwd)).replace("\\", "/"),
            ],
        }

    async def _start_docker_for_probing(*_args, **_kwargs):
        return endpoint_prober_module.DockerContext(
            app_url="http://localhost:3080",
            containers_running=True,
            api_healthy=True,
        )

    async def _reset_db_and_seed(*_args, **_kwargs):
        return True

    async def _execute_probes(manifest, _docker_ctx, _cwd):
        captured["events"].append("probes")
        captured["probe_total"] = manifest.total_probes
        probe = manifest.probes[0]
        manifest.results = [
            ProbeResult(
                spec=probe,
                actual_status=probe.expected_status,
                passed=True,
                response_body='{"id":"1","name":"existing"}',
                duration_ms=4.0,
            )
        ]
        manifest.failures = []
        manifest.happy_pass = 1
        manifest.happy_fail = 0
        manifest.negative_pass = 0
        manifest.negative_fail = 0
        return manifest

    async def _collect_db_assertion_evidence(*_args, **_kwargs):
        return []

    async def _collect_simulator_evidence(*_args, **_kwargs):
        return []

    monkeypatch.setattr(endpoint_prober_module, "start_docker_for_probing", _start_docker_for_probing)
    monkeypatch.setattr(endpoint_prober_module, "reset_db_and_seed", _reset_db_and_seed)
    monkeypatch.setattr(endpoint_prober_module, "execute_probes", _execute_probes)
    monkeypatch.setattr(endpoint_prober_module, "collect_db_assertion_evidence", _collect_db_assertion_evidence)
    monkeypatch.setattr(endpoint_prober_module, "collect_simulator_evidence", _collect_simulator_evidence)

    result = await execute_milestone_waves(
        milestone=milestone,
        ir=_product_ir(),
        config=config,
        cwd=str(tmp_path),
        build_wave_prompt=_build_prompt,
        execute_sdk_call=_execute_sdk_call,
        run_compile_check=_run_compile_check,
        extract_artifacts=_extract_artifacts,
        generate_contracts=_generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
    )

    # V18.2: Wave T (comprehensive test wave) sits between D5 and E.
    assert [wave.wave for wave in result.waves] == ["A", "B", "C", "D", "D5", "T", "E"]
    assert captured["compile_calls"] == ["A", "B", "D", "D5"]
    assert captured["probe_total"] >= 1
    assert captured["events"].index("compile:B") < captured["events"].index("probes") < captured["events"].index("contracts")
    assert captured["events"].index("contracts") < captured["events"].index("sdk:D")
    assert "[PLAYWRIGHT TESTS - REQUIRED]" in captured["prompt_by_wave"]["E"]
    assert "[WIRING SCANNER - REQUIRED]" in captured["prompt_by_wave"]["E"]
    assert "REQUIREMENTS.md" in captured["prompt_by_wave"]["E"]
    assert "TASKS.md" in captured["prompt_by_wave"]["E"]
    assert isinstance(result.total_cost, float)
    assert set(captured["artifact_keys_for_d"]) >= {"A", "B", "C"}
    assert not any(key.startswith("wave_") for key in captured["artifact_keys_for_d"])

    evidence_dir = tmp_path / ".agent-team" / "evidence"
    evidence_path = evidence_dir / "AC-1.json"
    assert evidence_path.is_file()
    manifest_path = tmp_path / ".agent-team" / "telemetry" / f"{milestone.id}-probe-manifest.json"
    assert manifest_path.is_file()
    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved_manifest["probes"][0]["method"] == "POST"
    assert saved_manifest["probes"][0]["path"] == "/orders"
    assert saved_manifest["probes"][0]["mapped_ac_ids"] == ["AC-1"]

    ledger = EvidenceLedger(evidence_dir)
    ledger.load_all()
    ledger.set_required_evidence("AC-1", ["http_transcript", "code_span"])
    ledger.set_required_evidence("AC-2", ["playwright_trace"])
    _write(tmp_path / "src" / "evidence.ts", "export const evidence = true;\n")
    ledger.record_evidence(
        "AC-1",
        EvidenceRecord(type="code_span", path="src/evidence.ts", content="src/evidence.ts:1", source="wave_e"),
        verdict="PASS",
    )
    ledger.record_evidence(
        "AC-9",
        EvidenceRecord(type="db_assertion", content="SELECT 1", source="other_milestone"),
        verdict="PASS",
    )

    availability = resolve_collector_availability(
        milestone_id=milestone.id,
        milestone_template=milestone.template,
        config=config,
        cwd=str(tmp_path),
    )
    assert availability["http_transcript"] is True
    assert availability["db_assertion"] is False
    assert availability["playwright_trace"] is False

    other_availability = resolve_collector_availability(
        milestone_id="milestone-payments",
        milestone_template="full_stack",
        config=config,
        cwd=str(tmp_path),
    )
    assert other_availability["db_assertion"] is True

    audit_results = [
        CheckResult(ac_id="AC-1", verdict="PASS", evidence="src/evidence.ts:1"),
        CheckResult(ac_id="AC-2", verdict="PASS", evidence="src/orders.page.tsx:1"),
    ]
    _apply_evidence_gating_to_results(
        audit_results,
        tmp_path / ".agent-team",
        tmp_path,
        {
            "evidence_mode": "soft_gate",
            "live_endpoint_check": True,
            "current_milestone_id": milestone.id,
            "milestone_template": milestone.template,
        },
    )
    assert [item.verdict for item in audit_results] == ["PASS", "UNVERIFIED"]

    parsed_results = _parse_ac_results_from_response(
        "",
        [
            AcceptanceCriterion(id="AC-1", feature="F-ORDERS", text="Create and view orders"),
            AcceptanceCriterion(id="AC-2", feature="F-ORDERS", text="Verify orders UI"),
        ],
        audit_results,
    )
    assert [item.status for item in parsed_results] == ["PASS", "UNVERIFIED"]
    assert parsed_results[1].score == 0.5

    report = build_report(
        audit_id="audit-1",
        cycle=1,
        auditors_deployed=["requirements"],
        findings=[
            AuditFinding(
                finding_id="REQ-1",
                auditor="requirements",
                requirement_id="AC-1",
                verdict=audit_results[0].verdict,
                severity="LOW",
                summary="Order flow implemented",
                evidence=["src/evidence.ts:1"],
                remediation="",
            ),
            AuditFinding(
                finding_id="REQ-2",
                auditor="requirements",
                requirement_id="AC-2",
                verdict=audit_results[1].verdict,
                severity="LOW",
                summary="Orders UI pending runtime evidence",
                evidence=["src/orders.page.tsx:1"],
                remediation="",
            ),
        ],
        healthy_threshold=90.0,
        degraded_threshold=70.0,
    )
    gated_report = _apply_evidence_gating_to_audit_report(
        report,
        milestone_id=milestone.id,
        milestone_template=milestone.template,
        config=config,
        cwd=str(tmp_path),
    )

    assert gated_report.findings[0].verdict == "PASS"
    assert gated_report.findings[1].verdict == "UNVERIFIED"
    assert gated_report.score.partial == 1
    assert gated_report.score.score == pytest.approx(75.0)

    health_report = MilestoneManager(tmp_path).check_milestone_health(milestone.id)
    assert health_report.total_requirements == 2
    assert health_report.checked_requirements == 2
    assert health_report.health == "healthy"
