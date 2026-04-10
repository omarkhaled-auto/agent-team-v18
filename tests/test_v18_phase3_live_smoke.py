from __future__ import annotations

import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from agent_team_v15.agents import build_wave_prompt
from agent_team_v15.artifact_store import extract_wave_artifacts
from agent_team_v15.audit_agent import _prime_evidence_ledger
from agent_team_v15.audit_models import AuditFinding, build_report
from agent_team_v15.cli import _apply_evidence_gating_to_audit_report
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.evidence_ledger import EvidenceLedger
from agent_team_v15.wave_executor import execute_milestone_waves


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(
        id="milestone-orders",
        title="Orders",
        template="full_stack",
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS", "F-ORDERS-UI"],
        ac_refs=["AC-1", "AC-2"],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


class _OrdersHandler(BaseHTTPRequestHandler):
    state_file: Path

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/api/health", "/health", "/", "/api"}:
            self._json(200, {"ok": True})
            return
        self._json(404, {"message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/orders":
            self._json(404, {"message": "not found"})
            return
        if self.headers.get("Authorization") != "Bearer test-token":
            self._json(401, {"message": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"message": "invalid json"})
            return

        if (
            not isinstance(payload, dict)
            or payload.get("__invalid_field__")
            or not isinstance(payload.get("name"), str)
            or not isinstance(payload.get("quantity"), int)
        ):
            self._json(400, {"message": "invalid body"})
            return

        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        existing_names = list(state.get("existing_names", []) or [])
        if payload["name"] in existing_names:
            self._json(409, {"message": "duplicate"})
            return

        self._json(201, {"id": "1", "name": payload["name"], "quantity": payload["quantity"]})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        del format, args


@pytest.mark.asyncio
async def test_phase3_live_smoke_external_app(tmp_path: Path) -> None:
    port = _free_port()
    runtime_state = _write(tmp_path / "runtime_state.json", json.dumps({"existing_names": []}, indent=2))
    _write(
        tmp_path / "seed" / "fixtures.json",
        json.dumps({"existing_record": {"name": "duplicate"}, "quantity": 1}, indent=2),
    )
    _write(
        tmp_path / "seed" / "run_all.py",
        "\n".join(
            [
                "from pathlib import Path",
                "import json",
                "",
                "root = Path(__file__).resolve().parent.parent",
                "state_path = root / 'runtime_state.json'",
                "state_path.write_text(json.dumps({'existing_names': ['duplicate']}, indent=2), encoding='utf-8')",
            ]
        )
        + "\n",
    )
    _write(
        tmp_path / ".agent-team" / "MASTER_PLAN.json",
        json.dumps({"milestones": [{"id": "milestone-orders", "ac_refs": ["AC-1", "AC-2"]}]}, indent=2),
    )
    _write(
        tmp_path / ".agent-team" / "product-ir" / "product.ir.json",
        json.dumps(
            {
                "project_name": "Demo",
                "acceptance_criteria": [
                    {"id": "AC-1", "feature": "F-ORDERS", "text": "Create an order"},
                    {"id": "AC-2", "feature": "F-ORDERS-UI", "text": "Order UI verification"},
                ],
                "endpoints": [
                    {
                        "method": "POST",
                        "path": "/orders",
                        "owner_feature": "F-ORDERS",
                        "auth": True,
                    }
                ],
            },
            indent=2,
        ),
    )
    _write(
        tmp_path / ".agent-team" / "product-ir" / "acceptance-criteria.ir.json",
        json.dumps(
            {
                "acceptance_criteria": [
                    {"id": "AC-1", "feature": "F-ORDERS", "required_evidence": ["http_transcript"]},
                    {"id": "AC-2", "feature": "F-ORDERS-UI", "required_evidence": ["playwright_trace"]},
                ]
            },
            indent=2,
        ),
    )
    _write(
        tmp_path / ".agent-team" / "milestones" / "milestone-orders" / "REQUIREMENTS.md",
        "- [ ] AC-1: Create an order\n- [ ] AC-2: Verify the UI\nreview_cycles: 0\n",
    )
    _write(
        tmp_path / ".agent-team" / "milestones" / "milestone-orders" / "TASKS.md",
        "Status: TODO\nFiles: []\n",
    )

    _OrdersHandler.state_file = runtime_state
    server = ThreadingHTTPServer(("127.0.0.1", port), _OrdersHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    milestone = _milestone()
    config = AgentTeamConfig()
    config.v18.execution_mode = "wave"
    config.v18.evidence_mode = "soft_gate"
    config.v18.live_endpoint_check = True
    config.browser_testing.app_port = port

    captured_prompts: dict[str, str] = {}

    async def _build_prompt(**kwargs: object) -> str:
        prompt = build_wave_prompt(**kwargs)
        captured_prompts[str(kwargs["wave"])] = prompt
        return prompt

    async def _execute_sdk_call(*, wave: str, role: str = "wave", **_: object) -> float:
        if role != "wave":
            return 0.0

        if wave == "A":
            _write(
                tmp_path / "apps" / "api" / "src" / "orders" / "orders.service.ts",
                "export class OrdersService {\n  create(): string {\n    return 'ok';\n  }\n}\n",
            )
        elif wave == "B":
            _write(
                tmp_path / "apps" / "api" / "src" / "orders" / "orders.controller.ts",
                "\n".join(
                    [
                        "import { Controller, Post, Body } from '@nestjs/common';",
                        "import { CreateOrderDto } from './create-order.dto';",
                        "",
                        "@Controller('orders')",
                        "export class OrdersController {",
                        "  @Post()",
                        "  create(@Body() dto: CreateOrderDto) {",
                        "    return dto;",
                        "  }",
                        "}",
                    ]
                )
                + "\n",
            )
            _write(
                tmp_path / "apps" / "api" / "src" / "orders" / "create-order.dto.ts",
                "\n".join(
                    [
                        "export class CreateOrderDto {",
                        "  @ApiProperty()",
                        "  name: string;",
                        "",
                        "  @ApiProperty()",
                        "  quantity: number;",
                        "}",
                    ]
                )
                + "\n",
            )
        elif wave == "D":
            _write(
                tmp_path / "apps" / "web" / "app" / "orders" / "page.tsx",
                "export default function OrdersPage() {\n  return <div>Orders</div>;\n}\n",
            )
        return 1.0

    async def _run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def _generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
        milestone_id = getattr(milestone, "id", "milestone-orders")
        current_spec = _write(
            Path(cwd) / "contracts" / "openapi" / "current.json",
            json.dumps({"paths": {"/orders": {"post": {"responses": {"201": {"description": "created"}}}}}}, indent=2),
        )
        local_spec = _write(
            Path(cwd) / "contracts" / "openapi" / f"{milestone_id}.json",
            json.dumps({"paths": {"/orders": {"post": {"responses": {"201": {"description": "created"}}}}}}, indent=2),
        )
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

    try:
        result = await execute_milestone_waves(
            milestone=milestone,
            ir=json.loads((tmp_path / ".agent-team" / "product-ir" / "product.ir.json").read_text(encoding="utf-8")),
            config=config,
            cwd=str(tmp_path),
            build_wave_prompt=_build_prompt,
            execute_sdk_call=_execute_sdk_call,
            run_compile_check=_run_compile_check,
            extract_artifacts=extract_wave_artifacts,
            generate_contracts=_generate_contracts,
            run_scaffolding=None,
            save_wave_state=None,
            on_wave_complete=None,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.success is True
    assert [wave.wave for wave in result.waves] == ["A", "B", "C", "D", "E"]
    assert "[PLAYWRIGHT TESTS - REQUIRED]" in captured_prompts["E"]
    assert "[WIRING SCANNER - REQUIRED]" in captured_prompts["E"]
    assert "REQUIREMENTS.md" in captured_prompts["E"]
    assert "TASKS.md" in captured_prompts["E"]

    manifest_path = tmp_path / ".agent-team" / "telemetry" / "milestone-orders-probe-manifest.json"
    telemetry_path = tmp_path / ".agent-team" / "telemetry" / "milestone-orders-probes.json"
    evidence_path = tmp_path / ".agent-team" / "evidence" / "AC-1.json"
    assert manifest_path.is_file()
    assert telemetry_path.is_file()
    assert evidence_path.is_file()

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    probe_types = {probe["probe_type"] for probe in saved_manifest["probes"]}
    assert {"happy_path", "401_unauthenticated", "400_invalid_body", "409_duplicate"} <= probe_types

    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
    actual_statuses = {
        probe["spec"]["probe_type"]: probe["actual_status"]
        for probe in telemetry["results"]
    }
    assert actual_statuses["happy_path"] == 201
    assert actual_statuses["401_unauthenticated"] == 401
    assert actual_statuses["400_invalid_body"] == 400
    assert actual_statuses["409_duplicate"] == 409

    ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
    ledger.load_all()
    ac1 = ledger.get_entry("AC-1")
    assert ac1 is not None
    assert any(record.type == "http_transcript" for record in ac1.evidence)

    _prime_evidence_ledger(tmp_path / ".agent-team")
    report = build_report(
        audit_id="audit-live-smoke",
        cycle=1,
        auditors_deployed=["requirements"],
        findings=[
            AuditFinding(
                finding_id="RA-001",
                auditor="requirements",
                requirement_id="AC-1",
                verdict="PASS",
                severity="LOW",
                summary="Order API verified",
                evidence=["apps/api/src/orders/orders.controller.ts:1"],
            ),
            AuditFinding(
                finding_id="RA-002",
                auditor="requirements",
                requirement_id="AC-2",
                verdict="PASS",
                severity="LOW",
                summary="Order UI verified",
                evidence=["apps/web/app/orders/page.tsx:1"],
            ),
        ],
    )
    gated = _apply_evidence_gating_to_audit_report(
        report,
        milestone_id=milestone.id,
        milestone_template=milestone.template,
        config=config,
        cwd=str(tmp_path),
    )

    verdicts = {finding.requirement_id: finding.verdict for finding in gated.findings}
    assert verdicts["AC-1"] == "PASS"
    assert verdicts["AC-2"] == "UNVERIFIED"
    assert gated.score.partial == 1
