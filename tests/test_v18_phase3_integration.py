from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import cli as cli_module
from agent_team_v15.agents import build_wave_prompt
from agent_team_v15.audit_models import AuditFinding, build_report
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.evidence_ledger import EvidenceLedger
from agent_team_v15.endpoint_prober import DockerContext, ProbeResult
from agent_team_v15.wave_executor import execute_milestone_waves


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _milestone() -> SimpleNamespace:
    return SimpleNamespace(
        id="milestone-orders",
        title="Orders",
        template="full_stack",
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


class _FakeClaudeSDKClient:
    def __init__(self, *, options):
        self.options = options

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def query(self, prompt: str) -> None:
        del prompt


@pytest.mark.asyncio
async def test_phase3_integration_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    milestone = _milestone()
    config = AgentTeamConfig()
    config.v18.execution_mode = "wave"
    config.v18.evidence_mode = "soft_gate"
    config.v18.live_endpoint_check = True

    _write(
        tmp_path / ".agent-team" / "product-ir" / "product.ir.json",
        json.dumps(
            {
                "project_name": "Demo",
                "acceptance_criteria": [
                    {"id": "AC-1", "feature": "F-ORDERS", "text": "Create an order"}
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
        json.dumps({"acceptance_criteria": [{"id": "AC-1", "feature": "F-ORDERS", "required_evidence": ["http_transcript"]}]}, indent=2),
    )
    _write(
        tmp_path / ".agent-team" / "MASTER_PLAN.json",
        json.dumps({"milestones": [{"id": "milestone-orders", "ac_refs": ["AC-1"]}]}, indent=2),
    )

    captured_prompts: dict[str, str] = {}
    captured_artifact_keys: dict[str, list[str]] = {}

    async def build_prompt(**kwargs):
        captured_artifact_keys[str(kwargs["wave"])] = sorted(dict(kwargs.get("wave_artifacts", {})).keys())
        prompt = build_wave_prompt(**kwargs)
        captured_prompts[str(kwargs["wave"])] = prompt
        return prompt

    async def execute_sdk_call(*, prompt: str, wave: str, role: str = "wave", **_: object) -> float:
        if role == "wave":
            _write(tmp_path / "src" / f"{wave.lower()}.ts", f"export const {wave.lower()} = '{wave}';\n")
        return 1.25

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def extract_artifacts(**kwargs: object) -> dict[str, object]:
        if kwargs["wave"] == "B":
            return {
                "controllers": [
                    {
                        "name": "OrdersController",
                        "endpoints": [{"method": "POST", "path": "/orders", "handler": "create"}],
                    }
                ],
                "dtos": [
                    {
                        "name": "CreateOrderDto",
                        "fields": [
                            {"name": "name", "type": "string", "optional": False, "decorators": ["ApiProperty"]},
                        ],
                    }
                ],
            }
        return {"wave": kwargs["wave"], "files_created": list(kwargs.get("files_created", []) or [])}

    async def generate_contracts(*, cwd: str, milestone: object) -> dict[str, object]:
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

    async def fake_start_docker_for_probing(cwd: str, config: object) -> DockerContext:
        del cwd, config
        return DockerContext(app_url="http://localhost:3080", containers_running=True, api_healthy=True)

    async def fake_reset_db_and_seed(cwd: str) -> bool:
        del cwd
        return True

    async def fake_execute_probes(manifest, docker_ctx, cwd):
        del docker_ctx, cwd
        manifest.results = []
        for probe in manifest.probes:
            manifest.results.append(
                ProbeResult(
                    spec=probe,
                    actual_status=probe.expected_status,
                    passed=True,
                    response_body='{"id":"1"}',
                )
            )
        manifest.failures = []
        manifest.happy_pass = sum(1 for result in manifest.results if result.spec.probe_type == "happy_path")
        manifest.negative_pass = len(manifest.results) - manifest.happy_pass
        return manifest

    monkeypatch.setattr("agent_team_v15.endpoint_prober.start_docker_for_probing", fake_start_docker_for_probing)
    monkeypatch.setattr("agent_team_v15.endpoint_prober.reset_db_and_seed", fake_reset_db_and_seed)
    monkeypatch.setattr("agent_team_v15.endpoint_prober.execute_probes", fake_execute_probes)

    result = await execute_milestone_waves(
        milestone=milestone,
        ir=json.loads((tmp_path / ".agent-team" / "product-ir" / "product.ir.json").read_text(encoding="utf-8")),
        config=config,
        cwd=str(tmp_path),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=extract_artifacts,
        generate_contracts=generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
        on_wave_complete=None,
    )

    assert result.success is True
    assert isinstance(result.total_cost, float)
    # V18.2: Wave T (comprehensive test wave) sits between D5 and E.
    assert [wave.wave for wave in result.waves] == ["A", "B", "C", "D", "D5", "T", "E"]
    assert captured_artifact_keys["D"] == ["A", "B", "C"]
    assert "wave_a" not in captured_artifact_keys["D"]
    assert "REQUIREMENTS.md" in captured_prompts["E"]
    assert "TASKS.md" in captured_prompts["E"]
    assert "[PLAYWRIGHT TESTS - REQUIRED]" in captured_prompts["E"]
    assert (tmp_path / ".agent-team" / "telemetry" / "milestone-orders-probes.json").is_file()
    assert (tmp_path / ".agent-team" / "evidence" / "AC-1.json").is_file()

    ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
    ledger.load_all()
    ledger.set_required_evidence("AC-1", ["http_transcript"])

    audit_dir = tmp_path / ".agent-team"
    report = build_report(
        audit_id="audit-1",
        cycle=1,
        auditors_deployed=["requirements"],
        findings=[
            AuditFinding(
                finding_id="RA-001",
                auditor="requirements",
                requirement_id="AC-1",
                verdict="PASS",
                severity="LOW",
                summary="Order creation verified",
                evidence=["src/b.ts:1"],
            )
        ],
    )
    _write(audit_dir / "AUDIT_REPORT.json", report.to_json())

    monkeypatch.setattr(cli_module, "ClaudeSDKClient", _FakeClaudeSDKClient)

    async def fake_process_response(*args, **kwargs) -> float:
        del args, kwargs
        return 0.0

    monkeypatch.setattr(cli_module, "_process_response", fake_process_response)
    monkeypatch.setattr("agent_team_v15.audit_team.get_auditors_for_depth", lambda depth: ["requirements"])
    monkeypatch.setattr(
        "agent_team_v15.audit_team.build_auditor_agent_definitions",
        lambda *args, **kwargs: {
            "requirements": {"description": "Requirements auditor"},
            "audit-scorer": {"description": "Scorer"},
        },
    )

    gated_report, audit_cost = await cli_module._run_milestone_audit(
        milestone_id=milestone.id,
        milestone_template=milestone.template,
        config=config,
        depth="standard",
        task_text="Build orders",
        requirements_path=str(tmp_path / "REQUIREMENTS.md"),
        audit_dir=str(audit_dir),
        cycle=1,
    )

    assert audit_cost == 0.0
    assert gated_report is not None
    assert gated_report.score.score == 100.0
    assert gated_report.findings[0].verdict == "PASS"


@pytest.mark.asyncio
async def test_wave_executor_skips_prober_when_flag_is_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"prober": 0}

    async def fail_if_called(*args, **kwargs):
        called["prober"] += 1
        raise AssertionError("prober should not run")

    monkeypatch.setattr("agent_team_v15.wave_executor._run_wave_b_probing", fail_if_called)

    milestone = _milestone()
    config = AgentTeamConfig()
    # V18.2: live_endpoint_check defaults to True; this test explicitly
    # verifies that turning the flag off skips the prober.
    config.v18.live_endpoint_check = False

    async def build_prompt(**kwargs):
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(**kwargs):
        del kwargs
        return 1.0

    async def run_compile_check(**kwargs):
        del kwargs
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    async def generate_contracts(**kwargs):
        del kwargs
        return {
            "success": True,
            "milestone_spec_path": "",
            "cumulative_spec_path": "",
            "client_exports": [],
            "breaking_changes": [],
            "endpoints_summary": [],
            "files_created": [],
        }

    result = await execute_milestone_waves(
        milestone=milestone,
        ir={},
        config=config,
        cwd=str(tmp_path),
        build_wave_prompt=build_prompt,
        execute_sdk_call=execute_sdk_call,
        run_compile_check=run_compile_check,
        extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
        generate_contracts=generate_contracts,
        run_scaffolding=None,
        save_wave_state=None,
        on_wave_complete=None,
    )

    assert result.success is True
    assert called["prober"] == 0
