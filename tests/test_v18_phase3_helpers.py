from __future__ import annotations

import json
import socket
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

import agent_team_v15.endpoint_prober as endpoint_prober_module
from agent_team_v15 import cli as cli_module
from agent_team_v15.cli import _build_options, _prepare_wave_sdk_options
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.audit_models import AuditFinding, build_report
from agent_team_v15.endpoint_prober import (
    DockerContext,
    ProbeManifest,
    ProbeResult,
    ProbeSpec,
    _build_duplicate_body,
    _build_invalid_request_body,
    _build_valid_request_body,
    _collect_endpoints,
    _verify_db_mutation,
    collect_db_assertion_evidence,
    collect_probe_evidence,
    collect_simulator_evidence,
    execute_probes,
    format_probe_failures_for_fix,
    generate_probe_manifest,
)
from agent_team_v15.evidence_ledger import EvidenceLedger, EvidenceRecord, resolve_collector_availability
from agent_team_v15.fix_executor import (
    _check_contract_sensitive,
    _rerun_probes_for_acs,
    analyze_blast_radius,
    is_foundation_fix,
    run_regression_check,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_product_ir(root: Path) -> None:
    _write(
        root / ".agent-team" / "product-ir" / "product.ir.json",
        json.dumps(
            {
                "endpoints": [
                    {
                        "method": "POST",
                        "path": "/orders",
                        "owner_feature": "F-ORDERS",
                        "auth": True,
                    }
                ],
                "acceptance_criteria": [
                    {"id": "AC-1", "feature": "F-ORDERS", "text": "Create an order"},
                    {"id": "AC-2", "feature": "F-PAYMENTS", "text": "Process a payment"},
                ],
                "integrations": [
                    {"vendor": "Stripe", "type": "payment", "owner_feature": "F-PAYMENTS"}
                ],
            },
            indent=2,
        ),
    )


def _wave_b_artifact() -> dict[str, object]:
    return {
        "controllers": [
            {
                "name": "OrdersController",
                "endpoints": [
                    {"method": "POST", "path": "/orders", "handler": "create"},
                    {"method": "GET", "path": "/orders", "handler": "list"},
                    {"method": "GET", "path": "/orders/:id", "handler": "getOne"},
                ],
            }
        ],
        "dtos": [
            {
                "name": "CreateOrderDto",
                "file": "apps/api/src/orders/create-order.dto.ts",
                "fields": [
                    {"name": "name", "type": "string", "optional": False, "decorators": ["ApiProperty"]},
                    {"name": "quantity", "type": "number", "optional": False, "decorators": ["ApiProperty"]},
                ],
            }
        ],
    }


def test_generate_probe_manifest_adds_happy_and_negative_probes() -> None:
    manifest = generate_probe_manifest(
        "milestone-orders",
        _wave_b_artifact(),
        None,
        {
            "endpoints": [{"method": "POST", "path": "/orders", "auth": True}],
        },
        {"orders": [{"id": "1"}], "name": "existing-order"},
    )

    probes = {(probe.method, probe.path, probe.probe_type) for probe in manifest.probes}
    assert ("POST", "/orders", "happy_path") in probes
    assert ("POST", "/orders", "401_unauthenticated") in probes
    assert ("POST", "/orders", "400_invalid_body") in probes
    assert ("POST", "/orders", "409_duplicate") in probes
    assert ("GET", "/orders/:id", "404_not_found") in probes


def test_generate_probe_manifest_public_read_only_route_stays_minimal() -> None:
    manifest = generate_probe_manifest(
        "milestone-orders",
        {
            "controllers": [{"name": "OrdersController", "endpoints": [{"method": "GET", "path": "/orders", "handler": "list"}]}],
            "dtos": [],
        },
        None,
        {},
        {},
    )

    assert [(probe.method, probe.path, probe.probe_type) for probe in manifest.probes] == [
        ("GET", "/orders", "happy_path")
    ]


def test_collect_endpoints_prefers_wave_b_artifacts_then_ir(tmp_path: Path) -> None:
    spec_path = _write(
        tmp_path / "current.json",
        json.dumps({"paths": {"/orders": {"post": {"security": [{"bearerAuth": []}]}}}}),
    )
    endpoints = _collect_endpoints(_wave_b_artifact(), spec_path, {})
    post_orders = next(item for item in endpoints if item["method"] == "POST" and item["path"] == "/orders")
    assert post_orders["security"] == [{"bearerAuth": []}]

    fallback = _collect_endpoints({}, None, {"endpoints": [{"method": "GET", "path": "/health", "tags": ["system"]}]})
    assert fallback == [
        {
            "method": "GET",
            "path": "/health",
            "parameters": [],
            "requestBody": {},
            "responses": {},
            "security": [],
            "tags": ["system"],
            "owner_feature": "",
            "auth": None,
            "dto_fields": [],
        }
    ]


def test_request_body_builders_use_schema_and_invalid_types() -> None:
    endpoint = {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                        },
                        "required": ["name", "quantity"],
                    }
                }
            }
        }
    }

    assert _build_valid_request_body(endpoint, {}) == {"name": "test_name", "quantity": 1}
    invalid_body = _build_invalid_request_body(endpoint)
    assert invalid_body["name"] is None
    assert invalid_body["quantity"] == "not-a-number"


def test_happy_path_body_avoids_existing_seed_record_values() -> None:
    endpoint = {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                        },
                        "required": ["name", "quantity"],
                    }
                }
            }
        }
    }

    fixtures = {
        "existing_record": {"name": "duplicate"},
        "quantity": 3,
    }

    assert _build_valid_request_body(endpoint, fixtures) == {"name": "test_name", "quantity": 3}
    assert _build_duplicate_body(endpoint, fixtures) == {"name": "duplicate", "quantity": 3}


@pytest.mark.asyncio
async def test_execute_probes_skips_when_docker_is_unhealthy() -> None:
    manifest = ProbeManifest(
        milestone_id="milestone-orders",
        probes=[ProbeSpec(endpoint="GET /orders", method="GET", path="/orders", probe_type="happy_path", expected_status=200)],
    )

    result = await execute_probes(manifest, DockerContext(app_url="http://localhost:3000", api_healthy=False), cwd=".")
    assert result.results == []
    assert result.failures == []


def test_format_probe_failures_for_fix_is_parseable() -> None:
    manifest = ProbeManifest(
        milestone_id="milestone-orders",
        total_probes=1,
        failures=[
            ProbeResult(
                spec=ProbeSpec(endpoint="POST /orders", method="POST", path="/orders", probe_type="400_invalid_body", expected_status=400),
                actual_status=500,
                passed=False,
                response_body='{"message":"boom"}',
            )
        ],
    )
    prompt = format_probe_failures_for_fix(manifest)
    assert "[ENDPOINT PROBE FAILURES - 1 of 1 probes failed]" in prompt
    assert "400_invalid_body: POST /orders" in prompt
    assert "Expected 400, got 500" in prompt


def test_collect_probe_and_simulator_evidence_map_to_acs(tmp_path: Path) -> None:
    _write_product_ir(tmp_path)
    manifest = ProbeManifest(
        milestone_id="milestone-orders",
        results=[
            ProbeResult(
                spec=ProbeSpec(endpoint="POST /orders", method="POST", path="/orders", probe_type="happy_path", expected_status=201),
                actual_status=201,
                passed=True,
                response_body='{"id":"1"}',
            )
        ],
    )
    probe_evidence = collect_probe_evidence(manifest, str(tmp_path))
    assert probe_evidence[0][0] == "AC-1"
    assert probe_evidence[0][1].type == "http_transcript"


@pytest.mark.asyncio
async def test_collect_db_assertion_evidence_uses_real_db_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_product_ir(tmp_path)
    _write(
        tmp_path / ".env",
        "POSTGRES_USER=orders\nPOSTGRES_DB=orders_db\nPOSTGRES_PASSWORD=secret\n",
    )
    _write(
        tmp_path / "docker-compose.yml",
        "\n".join(
            [
                "services:",
                "  api:",
                "    image: orders-api",
                "  db:",
                "    image: postgres:16",
            ]
        ),
    )
    _write(
        tmp_path / "prisma" / "schema.prisma",
        "\n".join(
            [
                "model Order {",
                "  id   String @id",
                "  name String",
                '  @@map("orders")',
                "}",
            ]
        ),
    )

    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        if cmd[:3] == ["docker", "compose", "-f"] and cmd[4:7] == ["ps", "--format", "{{.Name}}"]:
            service = cmd[-1]
            container = "orders-api-1" if service == "api" else "orders-db-1"
            return subprocess.CompletedProcess(cmd, 0, f"{container}\n", "")
        if cmd[:3] == ["docker", "exec", "-i"] and "npx" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "prisma execute failed")
        if cmd[:2] == ["docker", "exec"] and "psql" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "1\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(endpoint_prober_module.subprocess, "run", _fake_run)

    manifest = ProbeManifest(
        milestone_id="milestone-orders",
        results=[
            ProbeResult(
                spec=ProbeSpec(endpoint="POST /orders", method="POST", path="/orders", probe_type="happy_path", expected_status=201),
                actual_status=201,
                passed=True,
                response_body='{"id":"1","status":"created"}',
            )
        ],
    )
    db_evidence = await collect_db_assertion_evidence(
        manifest,
        DockerContext(app_url="http://localhost:3000", api_healthy=True),
        str(tmp_path),
    )
    assert any("psql" in cmd for cmd in calls)
    assert db_evidence[0][0] == "AC-1"
    assert db_evidence[0][1].type == "db_assertion"


@pytest.mark.asyncio
async def test_verify_db_mutation_returns_none_without_real_db_access(tmp_path: Path) -> None:
    result = await _verify_db_mutation(
        ProbeSpec(endpoint="POST /orders", method="POST", path="/orders", probe_type="happy_path", expected_status=201),
        '{"id":"1","name":"existing"}',
        str(tmp_path),
    )
    assert result is None


@pytest.mark.asyncio
async def test_collect_simulator_state_maps_to_acs(tmp_path: Path) -> None:
    _write_product_ir(tmp_path)

    _write(
        tmp_path / "apps" / "api" / "src" / "integrations" / "stripe" / "payments.simulator-state.json",
        json.dumps({"vendor": "Stripe", "recorded_calls": [{"method": "chargeCard"}]}),
    )
    sim_evidence = await collect_simulator_evidence(str(tmp_path))
    assert sim_evidence[0][0] == "AC-2"
    assert sim_evidence[0][1].type == "simulator_state"


def test_resolve_collector_availability_and_evidence_gate(tmp_path: Path) -> None:
    config = AgentTeamConfig()
    config.v18.evidence_mode = "soft_gate"
    config.v18.live_endpoint_check = True

    _write(
        tmp_path / ".agent-team" / "MASTER_PLAN.json",
        json.dumps({"milestones": [{"id": "milestone-orders", "ac_refs": ["AC-1", "AC-2"]}]}, indent=2),
    )
    availability_ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
    availability_ledger.record_evidence("AC-1", EvidenceRecord(type="http_transcript", content="HTTP 201"), verdict="PASS")
    availability_ledger.record_evidence("AC-1", EvidenceRecord(type="db_assertion", content="SELECT 1"), verdict="PASS")
    availability_ledger.record_evidence("AC-1", EvidenceRecord(type="simulator_state", content='{"ok":true}'), verdict="PASS")
    availability_ledger.record_evidence("AC-2", EvidenceRecord(type="playwright_trace", content="trace.zip"), verdict="PASS")

    available = resolve_collector_availability("milestone-orders", "full_stack", config, str(tmp_path))
    assert available["http_transcript"] is True
    assert available["db_assertion"] is True
    assert available["simulator_state"] is True
    assert available["playwright_trace"] is True

    ledger = EvidenceLedger(tmp_path / "evidence")
    ledger.set_required_evidence("AC-1", ["http_transcript"])
    assert ledger.evaluate_with_evidence_gate("AC-1", "PASS", "soft_gate", available) == "PARTIAL"
    ledger.record_evidence("AC-1", EvidenceRecord(type="http_transcript", content="ok"), verdict="PASS")
    assert ledger.evaluate_with_evidence_gate("AC-1", "PASS", "soft_gate", available) == "PASS"

    ledger.set_required_evidence("AC-2", ["playwright_trace"])
    assert ledger.evaluate_with_evidence_gate("AC-2", "PASS", "soft_gate", {"playwright_trace": False}) == "UNVERIFIED"
    assert ledger.evaluate_with_evidence_gate("AC-2", "FAIL", "soft_gate", {"playwright_trace": False}) == "FAIL"
    assert ledger.evaluate_with_evidence_gate("AC-2", "PASS", "hard_gate", available) == "PARTIAL"


def test_patch_lane_helpers_detect_blast_radius_and_contract_sensitivity(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "quotation" / "quotation.service.ts", "export class QuotationService {}\n")
    _write(
        tmp_path / "src" / "quotation" / "quotation.controller.ts",
        "import { QuotationService } from './quotation.service';\nexport class QuotationController {}\n",
    )
    _write(
        tmp_path / "src" / "quotation" / "quotation.module.ts",
        "import { QuotationService } from './quotation.service';\nexport class QuotationModule {}\n",
    )
    _write(tmp_path / "src" / "quotation" / "quotation.dto.ts", "@ApiProperty()\nexport class QuotationDto {}\n")

    blast = analyze_blast_radius(["src/quotation/quotation.service.ts"], tmp_path)
    assert "src/quotation/quotation.controller.ts" in blast["affected_files"]
    assert "src/quotation/quotation.module.ts" in blast["affected_files"]
    assert _check_contract_sensitive(["src/quotation/quotation.controller.ts"], tmp_path) is True
    assert _check_contract_sensitive(["src/quotation/quotation.dto.ts"], tmp_path) is True
    assert _check_contract_sensitive(["src/quotation/quotation.service.ts"], tmp_path) is False
    assert is_foundation_fix([{"files_to_modify": ["src/common/logger.ts"]}]) is True
    assert is_foundation_fix([{"files_to_modify": ["src/quotation/quotation.service.ts"]}]) is False


def test_run_regression_check_without_e2e_dir_is_safe(tmp_path: Path) -> None:
    config = AgentTeamConfig()
    assert run_regression_check(str(tmp_path), ["AC-1"], config) == []


def test_rerun_probes_for_acs_executes_saved_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_product_ir(tmp_path)
    _write(
        tmp_path / ".agent-team" / "telemetry" / "milestone-orders-probe-manifest.json",
        json.dumps(
            {
                "milestone_id": "milestone-orders",
                "probes": [
                    {
                        "method": "POST",
                        "path": "/orders",
                        "probe_type": "happy_path",
                        "expected_status": 201,
                        "request_body": {"name": "existing"},
                        "headers": {},
                        "path_params": {},
                        "mapped_ac_ids": ["AC-1"],
                    }
                ],
            },
            indent=2,
        ),
    )

    calls = {"execute": 0, "reset": 0}

    async def _start_docker_for_probing(*_args, **_kwargs):
        return DockerContext(app_url="http://localhost:3080", api_healthy=True)

    async def _reset_db_and_seed(*_args, **_kwargs):
        calls["reset"] += 1
        return True

    async def _execute_probes(manifest, _docker_ctx, _cwd):
        calls["execute"] += 1
        manifest.results = [
            ProbeResult(
                spec=manifest.probes[0],
                actual_status=500,
                passed=False,
                response_body='{"message":"boom"}',
                error="boom",
            )
        ]
        return manifest

    monkeypatch.setattr(endpoint_prober_module, "start_docker_for_probing", _start_docker_for_probing)
    monkeypatch.setattr(endpoint_prober_module, "reset_db_and_seed", _reset_db_and_seed)
    monkeypatch.setattr(endpoint_prober_module, "execute_probes", _execute_probes)

    regressed = _rerun_probes_for_acs(["AC-1"], str(tmp_path), AgentTeamConfig())

    assert calls["reset"] == 1
    assert calls["execute"] == 1
    assert regressed == ["AC-1"]


def test_rerun_probes_for_acs_logs_degraded_coverage(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        regressed = _rerun_probes_for_acs(["AC-1"], str(tmp_path), AgentTeamConfig())

    assert regressed == []
    assert "regression probe coverage degraded" in caplog.text.lower()


def test_prepare_wave_sdk_options_adds_playwright_only_for_wave_e() -> None:
    # V18.2 decoupling: Playwright MCP attaches to Wave E for any frontend
    # template (full_stack/frontend_only) regardless of evidence_mode, because
    # Wave E now ALWAYS emits Playwright instructions for frontend milestones.
    config = AgentTeamConfig()
    config.v18.evidence_mode = "soft_gate"
    base_options = _build_options(config)
    milestone = SimpleNamespace(template="full_stack")

    wave_e_options = _prepare_wave_sdk_options(base_options, config, "E", milestone)
    assert "playwright" in (wave_e_options.mcp_servers or {})
    assert any(tool.startswith("mcp__playwright__") for tool in wave_e_options.allowed_tools)

    # record_only still attaches Playwright for frontend Wave E — decoupled.
    config.v18.evidence_mode = "record_only"
    record_only_options = _prepare_wave_sdk_options(base_options, config, "E", milestone)
    assert "playwright" in (record_only_options.mcp_servers or {})

    # backend_only templates do NOT attach Playwright (no frontend to test).
    backend_milestone = SimpleNamespace(template="backend_only")
    backend_options = _prepare_wave_sdk_options(base_options, config, "E", backend_milestone)
    assert "playwright" not in (backend_options.mcp_servers or {})

    # Non-E waves never attach Playwright.
    wave_d_options = _prepare_wave_sdk_options(base_options, config, "D", milestone)
    assert "playwright" not in (wave_d_options.mcp_servers or {})


def test_phase4_parallel_isolation_requires_explicit_phase4_execution_mode() -> None:
    config = AgentTeamConfig()
    config.v18.git_isolation = True
    config.v18.execution_mode = "wave"
    assert cli_module._phase4_parallel_isolation_enabled(config) is False

    config.v18.execution_mode = "phase4_parallel"
    assert cli_module._phase4_parallel_isolation_enabled(config) is True


@pytest.mark.asyncio
async def test_start_docker_for_probing_accepts_healthy_external_app_without_compose(tmp_path: Path) -> None:
    port = _free_port()

    class _HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", port), _HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        config = AgentTeamConfig()
        config.browser_testing.app_port = port
        context = await endpoint_prober_module.start_docker_for_probing(str(tmp_path), config)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert context.api_healthy is True
    assert context.external_app is True
    assert context.app_url == f"http://localhost:{port}"


@pytest.mark.asyncio
async def test_run_audit_fix_unified_supplies_full_builder_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = build_report(
        audit_id="audit-1",
        cycle=1,
        auditors_deployed=["requirements"],
        findings=[
            AuditFinding(
                finding_id="RA-001",
                auditor="requirements",
                requirement_id="AC-1",
                verdict="FAIL",
                severity="HIGH",
                summary="Controller contract is broken",
                remediation="Regenerate the contract surface",
                evidence=["src/orders/orders.controller.ts:1"],
            )
        ],
    )
    captured: dict[str, bool] = {}

    async def _fake_execute_unified_fix_async(**kwargs: object) -> float:
        captured["has_full_build"] = callable(kwargs.get("run_full_build"))
        captured["has_patch_fixes"] = callable(kwargs.get("run_patch_fixes"))
        return 0.0

    monkeypatch.setattr("agent_team_v15.fix_executor.execute_unified_fix_async", _fake_execute_unified_fix_async)

    modified_files, cost = await cli_module._run_audit_fix_unified(
        report=report,
        config=AgentTeamConfig(),
        cwd=str(tmp_path),
        task_text="Fix the audit findings",
        depth="standard",
        fix_round=1,
    )

    assert modified_files == []
    assert cost == pytest.approx(0.0)
    assert captured == {"has_full_build": True, "has_patch_fixes": True}
