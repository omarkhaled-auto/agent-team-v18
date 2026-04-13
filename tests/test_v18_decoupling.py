"""V18.2 decoupling tests.

Asserts that Playwright/API verification/wiring/i18n scanner instructions
are emitted independently of ``evidence_mode`` and that evidence-record
creation is gated only by ``evidence_mode != "disabled"``.

Also asserts the new default values (record_only / live_endpoint_check=True)
and graceful Docker-missing skip behavior.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15 import cli as cli_module
from agent_team_v15 import wave_executor as wave_executor_module
from agent_team_v15.agents import build_wave_e_prompt
from agent_team_v15.config import AgentTeamConfig, apply_depth_quality_gating


FRAMEWORK_MARKER = "FRAMEWORK_MARKER"


def _milestone(template: str = "full_stack") -> SimpleNamespace:
    return SimpleNamespace(
        id="milestone-1",
        title="Orders",
        template=template,
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _ir() -> dict[str, object]:
    return {
        "acceptance_criteria": [
            {"id": "AC-1", "feature": "F-ORDERS", "text": "Show orders list"}
        ]
    }


def _wave_e_prompt(*, evidence_mode: str = "record_only", template: str = "full_stack") -> str:
    config = AgentTeamConfig()
    config.v18.evidence_mode = evidence_mode
    return build_wave_e_prompt(
        milestone=_milestone(template=template),
        ir=_ir(),
        wave_artifacts={},
        config=config,
        existing_prompt_framework=FRAMEWORK_MARKER,
    )


# ---------------------------------------------------------------------------
# Wave E prompt decoupling — Playwright/wiring/i18n are independent of evidence
# ---------------------------------------------------------------------------


class TestWaveEPromptDecoupling:
    def test_wave_e_prompt_includes_playwright_when_evidence_disabled(self) -> None:
        """Playwright instructions present even with evidence_mode='disabled'."""
        prompt = _wave_e_prompt(evidence_mode="disabled", template="full_stack")
        assert "[PLAYWRIGHT TESTS - REQUIRED]" in prompt
        assert "npx playwright test" in prompt

    def test_wave_e_prompt_includes_playwright_for_full_stack(self) -> None:
        """full_stack milestones get Playwright instructions (any evidence_mode)."""
        for mode in ("disabled", "record_only", "soft_gate", "hard_gate"):
            prompt = _wave_e_prompt(evidence_mode=mode, template="full_stack")
            assert "[PLAYWRIGHT TESTS - REQUIRED]" in prompt, f"mode={mode}"

    def test_wave_e_prompt_includes_playwright_for_frontend_only(self) -> None:
        prompt = _wave_e_prompt(evidence_mode="disabled", template="frontend_only")
        assert "[PLAYWRIGHT TESTS - REQUIRED]" in prompt
        assert "[API VERIFICATION SCRIPTS - REQUIRED]" not in prompt

    def test_wave_e_prompt_includes_api_verification_for_backend_only(self) -> None:
        """backend_only milestones get API verification instructions."""
        prompt = _wave_e_prompt(evidence_mode="disabled", template="backend_only")
        assert "[API VERIFICATION SCRIPTS - REQUIRED]" in prompt
        assert "[PLAYWRIGHT TESTS - REQUIRED]" not in prompt

    def test_wave_e_prompt_evidence_section_gated_by_evidence_mode(self) -> None:
        """Evidence collection section only appears when evidence_mode != 'disabled'."""
        disabled = _wave_e_prompt(evidence_mode="disabled")
        record_only = _wave_e_prompt(evidence_mode="record_only")
        soft = _wave_e_prompt(evidence_mode="soft_gate")

        assert "[EVIDENCE COLLECTION - REQUIRED]" not in disabled
        assert "[EVIDENCE COLLECTION - REQUIRED]" in record_only
        assert "[EVIDENCE COLLECTION - REQUIRED]" in soft

    def test_wave_e_prompt_includes_wiring_scanner_for_frontend(self) -> None:
        """Wiring scanner instructions always emitted (no evidence_mode gate)."""
        for mode in ("disabled", "record_only", "soft_gate"):
            prompt = _wave_e_prompt(evidence_mode=mode, template="full_stack")
            assert "[WIRING SCANNER - REQUIRED]" in prompt, f"mode={mode}"

    def test_wave_e_prompt_includes_i18n_scanner_for_frontend(self) -> None:
        for mode in ("disabled", "record_only", "soft_gate"):
            prompt = _wave_e_prompt(evidence_mode=mode, template="full_stack")
            assert "[I18N SCANNER - REQUIRED]" in prompt, f"mode={mode}"


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    def test_live_endpoint_check_default_true(self) -> None:
        """V18.2: live_endpoint_check defaults to True."""
        assert AgentTeamConfig().v18.live_endpoint_check is True

    def test_evidence_mode_default_record_only(self) -> None:
        """V18.2: evidence_mode defaults to 'record_only'."""
        assert AgentTeamConfig().v18.evidence_mode == "record_only"

    def test_wave_t_enabled_default_true(self) -> None:
        """V18.2: wave_t_enabled defaults to True."""
        assert AgentTeamConfig().v18.wave_t_enabled is True

    def test_no_depth_disables_live_endpoint_check(self) -> None:
        """No depth preset should DOWNGRADE live_endpoint_check to False."""
        for depth in ("quick", "standard", "thorough", "exhaustive", "enterprise"):
            cfg = AgentTeamConfig()
            apply_depth_quality_gating(depth, cfg)
            assert cfg.v18.live_endpoint_check is True, f"depth={depth} disabled probes"

    def test_no_depth_disables_evidence_mode(self) -> None:
        """No depth preset should DOWNGRADE evidence_mode to 'disabled'."""
        for depth in ("quick", "standard", "thorough", "exhaustive", "enterprise"):
            cfg = AgentTeamConfig()
            apply_depth_quality_gating(depth, cfg)
            assert cfg.v18.evidence_mode != "disabled", f"depth={depth} disabled evidence"

    def test_exhaustive_upgrades_evidence_to_soft_gate(self) -> None:
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", cfg)
        assert cfg.v18.evidence_mode == "soft_gate"

    def test_enterprise_upgrades_evidence_to_soft_gate(self) -> None:
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("enterprise", cfg)
        assert cfg.v18.evidence_mode == "soft_gate"


# ---------------------------------------------------------------------------
# Docker graceful-skip
# ---------------------------------------------------------------------------


class TestProbeGracefulSkip:
    @pytest.mark.asyncio
    async def test_probes_skip_gracefully_without_docker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When Docker / compose infrastructure is unavailable, probes log a
        warning and skip. The build continues (no wave failure)."""
        from agent_team_v15 import endpoint_prober as ep

        class _Ctx:
            app_url = "http://localhost:3080"
            containers_running = False
            api_healthy = False
            external_app = True
            startup_error = (
                "live_endpoint_check=True but no compose file was found under "
                f"{tmp_path} and no healthy external app responded at http://localhost:3080"
            )

        async def _fake_start(*_a, **_k):
            return _Ctx()

        monkeypatch.setattr(ep, "start_docker_for_probing", _fake_start)

        ok, msg, findings = await wave_executor_module._run_wave_b_probing(
            milestone=_milestone(),
            ir=_ir(),
            config=AgentTeamConfig(),
            cwd=str(tmp_path),
            wave_artifacts={},
            execute_sdk_call=lambda **_: 0.0,
        )

        assert ok is True
        assert msg == ""
        assert findings == []


# ---------------------------------------------------------------------------
# Evidence recording semantics
# ---------------------------------------------------------------------------


class TestEvidenceRecording:
    def test_evidence_records_created_in_record_only_mode(self, tmp_path: Path) -> None:
        """record_only creates .agent-team/evidence/ files."""
        from agent_team_v15.evidence_ledger import EvidenceLedger, EvidenceRecord

        ledger = EvidenceLedger(tmp_path / ".agent-team" / "evidence")
        ledger.record_evidence(
            ac_id="AC-1",
            evidence=EvidenceRecord(type="code_span", path="src/a.ts", content=""),
            verdict="PASS",
        )

        evidence_file = tmp_path / ".agent-team" / "evidence" / "AC-1.json"
        assert evidence_file.is_file()

    def test_evidence_does_not_affect_scoring_in_record_only(self) -> None:
        """record_only evidence doesn't change audit scores."""
        from pathlib import Path as _P
        from agent_team_v15.evidence_ledger import EvidenceLedger

        ledger = EvidenceLedger(_P("/tmp/doesnotmatter"))
        # record_only returns the legacy verdict unchanged regardless of
        # required evidence presence/absence.
        verdict = ledger.evaluate_with_evidence_gate(
            ac_id="AC-1",
            legacy_verdict="PASS",
            evidence_mode="record_only",
            collector_availability={"http_transcript": True},
        )
        assert verdict == "PASS"


# ---------------------------------------------------------------------------
# Playwright MCP decoupling in cli._prepare_wave_sdk_options
# ---------------------------------------------------------------------------


class TestPlaywrightMCPDecoupling:
    def test_playwright_mcp_attaches_for_frontend_regardless_of_evidence_mode(self) -> None:
        """Playwright MCP is added to Wave E for any frontend template —
        no longer gated on evidence_mode."""
        from agent_team_v15.cli import _prepare_wave_sdk_options

        signature = inspect.getsource(_prepare_wave_sdk_options)
        # The decoupled check should NOT depend on evidence_mode gating.
        assert "evidence_mode in {\"soft_gate\", \"hard_gate\"}" not in signature


# ---------------------------------------------------------------------------
# Wave sequences — E present, T inserted before E
# ---------------------------------------------------------------------------


class TestWaveSequences:
    def test_wave_e_present_in_all_sequences(self) -> None:
        """Wave E present in full_stack, backend_only, and frontend_only."""
        for template, waves in wave_executor_module.WAVE_SEQUENCES.items():
            assert "E" in waves, f"template={template}"

    def test_wave_t_inserted_before_e_when_enabled(self) -> None:
        cfg = AgentTeamConfig()
        cfg.v18.wave_t_enabled = True
        for template in ("full_stack", "backend_only", "frontend_only"):
            waves = wave_executor_module._wave_sequence(template, cfg)
            assert "T" in waves, f"template={template}"
            assert waves.index("T") == waves.index("E") - 1, f"template={template}"

    def test_wave_t_absent_when_disabled(self) -> None:
        cfg = AgentTeamConfig()
        cfg.v18.wave_t_enabled = False
        for template in ("full_stack", "backend_only", "frontend_only"):
            assert "T" not in wave_executor_module._wave_sequence(template, cfg)


# ---------------------------------------------------------------------------
# Deterministic scan adapter
# ---------------------------------------------------------------------------


class TestPostWaveEScans:
    def test_scan_adapter_returns_list(self, tmp_path: Path) -> None:
        """_run_post_wave_e_scans returns a list (possibly empty) without raising."""
        findings = wave_executor_module._run_post_wave_e_scans(str(tmp_path))
        assert isinstance(findings, list)

    def test_scan_adapter_includes_generated_client_field_alignment(self, tmp_path: Path) -> None:
        client_dir = tmp_path / "packages" / "api-client"
        client_dir.mkdir(parents=True)
        (client_dir / "types.ts").write_text(
            "export interface Order {\n  customer_id: string;\n}\n",
            encoding="utf-8",
        )
        (client_dir / "index.ts").write_text(
            "export async function listOrders(): Promise<Order[]> {\n  return [];\n}\n",
            encoding="utf-8",
        )

        frontend_dir = tmp_path / "apps" / "web" / "src"
        frontend_dir.mkdir(parents=True)
        (frontend_dir / "orders.tsx").write_text(
            "import { listOrders } from '@project/api-client';\n"
            "interface Order {\n"
            "  customerId: string;\n"
            "}\n"
            "export default function OrdersPage() { void listOrders; return <div />; }\n",
            encoding="utf-8",
        )

        findings = wave_executor_module._run_post_wave_e_scans(str(tmp_path))
        assert "CONTRACT-FIELD-002" in {finding.code for finding in findings}

    def test_violation_to_finding_conversion(self) -> None:
        """_violation_to_finding maps Violation.severity → WaveFinding.severity."""
        V = SimpleNamespace(
            check="WIRING-CLIENT-001",
            message="zero imports",
            file_path="apps/web/src/app.tsx",
            line=1,
            severity="critical",
        )
        finding = wave_executor_module._violation_to_finding(V)
        assert finding.code == "WIRING-CLIENT-001"
        assert finding.severity == "HIGH"
        assert finding.file == "apps/web/src/app.tsx"
        assert finding.line == 1


# ---------------------------------------------------------------------------
# Wave findings → audit loop bridge (V18.2)
# ---------------------------------------------------------------------------


class TestWaveFindingsAuditBridge:
    def test_persist_wave_findings_writes_json_for_audit(self, tmp_path: Path) -> None:
        """Wave findings are persisted to .agent-team/milestones/<id>/WAVE_FINDINGS.json."""
        import json as _json

        wave_a = wave_executor_module.WaveResult(wave="A")
        wave_b = wave_executor_module.WaveResult(wave="B")
        wave_b.findings.append(
            wave_executor_module.WaveFinding(
                code="PROBE-500",
                severity="HIGH",
                file="apps/api/src/orders/controller.ts",
                line=42,
                message="POST /orders returned 500, expected 201",
            )
        )
        wave_t = wave_executor_module.WaveResult(wave="T")
        wave_t.findings.append(
            wave_executor_module.WaveFinding(
                code="TEST-FAIL",
                severity="HIGH",
                file="",
                line=0,
                message="2 test(s) still failing after 2 Wave T fix iteration(s).",
            )
        )

        path = wave_executor_module.persist_wave_findings_for_audit(
            str(tmp_path), "milestone-orders", [wave_a, wave_b, wave_t]
        )
        assert path is not None
        assert path == tmp_path / ".agent-team" / "milestones" / "milestone-orders" / "WAVE_FINDINGS.json"
        assert path.is_file()

        payload = _json.loads(path.read_text(encoding="utf-8"))
        assert payload["milestone_id"] == "milestone-orders"
        codes = [f["code"] for f in payload["findings"]]
        waves = [f["wave"] for f in payload["findings"]]
        assert "PROBE-500" in codes
        assert "TEST-FAIL" in codes
        assert "B" in waves and "T" in waves

    def test_persist_wave_findings_writes_empty_record_when_no_findings(self, tmp_path: Path) -> None:
        import json as _json

        wave = wave_executor_module.WaveResult(wave="E")
        path = wave_executor_module.persist_wave_findings_for_audit(
            str(tmp_path), "milestone-nof", [wave]
        )
        assert path is not None
        payload = _json.loads(path.read_text(encoding="utf-8"))
        assert payload["findings"] == []

    def test_persist_wave_findings_handles_missing_milestone_id(self, tmp_path: Path) -> None:
        assert (
            wave_executor_module.persist_wave_findings_for_audit(str(tmp_path), "", [])
            is None
        )

    def test_format_wave_findings_for_audit_injects_into_prompt(self, tmp_path: Path) -> None:
        """_format_wave_findings_for_audit surfaces WAVE_FINDINGS.json to the audit prompt."""
        import json as _json

        audit_dir = tmp_path / ".agent-team"
        milestone_dir = audit_dir / "milestones" / "milestone-x"
        milestone_dir.mkdir(parents=True, exist_ok=True)
        (milestone_dir / "WAVE_FINDINGS.json").write_text(
            _json.dumps(
                {
                    "milestone_id": "milestone-x",
                    "findings": [
                        {
                            "wave": "B",
                            "code": "PROBE-401",
                            "severity": "HIGH",
                            "file": "apps/api/src/auth.guard.ts",
                            "line": 10,
                            "message": "protected route returned 200, expected 401",
                        },
                        {
                            "wave": "E",
                            "code": "WIRING-CLIENT-001",
                            "severity": "HIGH",
                            "file": "apps/web/src/app.tsx",
                            "line": 1,
                            "message": "manual fetch() found",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        block = cli_module._format_wave_findings_for_audit(
            audit_dir=str(audit_dir), milestone_id="milestone-x"
        )
        assert "[WAVE FINDINGS" in block
        assert "PROBE-401" in block
        assert "WIRING-CLIENT-001" in block
        assert "auth.guard.ts:10" in block

    def test_format_wave_findings_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        assert (
            cli_module._format_wave_findings_for_audit(
                audit_dir=str(tmp_path / ".agent-team"), milestone_id="missing"
            )
            == ""
        )


# ---------------------------------------------------------------------------
# Windows + missing-tool handling for the post-Wave-E runners
# ---------------------------------------------------------------------------


class TestNodeRunnerRobustness:
    def test_resolve_shell_command_falls_back_to_cmd_on_windows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On Windows, npm/npx should resolve through the .cmd fallback."""
        import shutil as _shutil
        import sys as _sys

        monkeypatch.setattr(_sys, "platform", "win32")

        def _fake_which(name: str) -> str | None:
            if name == "npm":
                return None
            if name == "npm.cmd":
                return "C:/fake/npm.cmd"
            return None

        monkeypatch.setattr(_shutil, "which", _fake_which)
        resolved = wave_executor_module._resolve_shell_command(["npm", "test"])
        assert resolved == ["C:/fake/npm.cmd", "test"]

    def test_resolve_shell_command_leaves_argv_alone_when_tool_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If neither exe nor .cmd exists, return the original argv unchanged."""
        import shutil as _shutil

        monkeypatch.setattr(_shutil, "which", lambda _n: None)
        assert wave_executor_module._resolve_shell_command(["npm", "test"]) == ["npm", "test"]

    @pytest.mark.asyncio
    async def test_run_node_tests_skips_when_no_package_json(self, tmp_path: Path) -> None:
        ran, passed, failed, msg = await wave_executor_module._run_node_tests(
            str(tmp_path), "apps/api", timeout=5.0
        )
        assert ran is False
        assert (passed, failed) == (0, 0)
        assert "package.json not found" in msg

    @pytest.mark.asyncio
    async def test_run_node_tests_skips_when_no_test_script(self, tmp_path: Path) -> None:
        import json as _json

        api_dir = tmp_path / "apps" / "api"
        api_dir.mkdir(parents=True, exist_ok=True)
        (api_dir / "package.json").write_text(
            _json.dumps({"name": "api", "scripts": {"build": "tsc"}}),
            encoding="utf-8",
        )
        ran, _p, _f, msg = await wave_executor_module._run_node_tests(
            str(tmp_path), "apps/api", timeout=5.0
        )
        assert ran is False
        assert "no scripts.test" in msg

    @pytest.mark.asyncio
    async def test_run_node_tests_marks_missing_tool_as_not_ran(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When npm itself is missing, the runner reports ran=False (not a zero-count run)."""
        import json as _json

        api_dir = tmp_path / "apps" / "api"
        api_dir.mkdir(parents=True, exist_ok=True)
        (api_dir / "package.json").write_text(
            _json.dumps({"name": "api", "scripts": {"test": "jest"}}),
            encoding="utf-8",
        )

        async def _fake_shell_command(cmd, cwd, timeout):
            return 127, "", "command not found: npm"

        monkeypatch.setattr(wave_executor_module, "_run_shell_command", _fake_shell_command)
        ran, passed, failed, msg = await wave_executor_module._run_node_tests(
            str(tmp_path), "apps/api", timeout=5.0
        )
        assert ran is False
        assert (passed, failed) == (0, 0)
        assert "npm test unavailable" in msg
