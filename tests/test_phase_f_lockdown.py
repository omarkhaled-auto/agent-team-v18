"""Phase F lockdown test suite.

Locks every finding + every fix from Phase F Parts 1-2 into a
regression-ready test surface. The inventory tested here mirrors
``docs/PHASE_F_COVERAGE_MATRIX.md``:

  * F-ARCH-001..006 — functional-architect reviewer
  * F-FWK-001..009 — framework-correctness reviewer
  * F-RT-001..005 — runtime-behavior reviewer
  * F-INT-001..003 — integration-boundary reviewer
  * F-EDGE-001..011 — edge-case-adversarial reviewer

For fixed findings the test fails against pre-fix code; for accepted
or deferred findings the test pins the current behavior as a
characterization anchor.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15.audit_models import (
    AuditFinding,
    AuditReport,
    AuditReportSchemaError,
    AuditScore,
    build_report,
)
from agent_team_v15.audit_scope_scanner import (
    audit_scope_completeness_enabled,
    build_scope_gap_findings,
    scan_audit_scope,
)
from agent_team_v15.cli import (
    _consolidate_cascade_findings,
    _load_wave_d_failure_roots,
)
from agent_team_v15.confidence_banners import (
    CONFIDENCE_CONFIDENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    ConfidenceSignals,
    confidence_banners_enabled,
    derive_confidence,
    stamp_all_reports,
    stamp_build_log,
    stamp_json_report,
    stamp_markdown_report,
)
from agent_team_v15.config import AgentTeamConfig, V18Config
from agent_team_v15.forbidden_content_scanner import merge_findings_into_report
from agent_team_v15.infra_detector import (
    RuntimeInfra,
    build_probe_url,
    detect_runtime_infra,
)
from agent_team_v15.wave_b_sanitizer import (
    build_orphan_findings,
    sanitize_wave_b_outputs,
    wave_b_output_sanitization_enabled,
)
from agent_team_v15.wave_executor import _maybe_sanitize_wave_b_outputs


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeRow:
    """Minimal duck-type for FileOwnership used by the sanitizer."""

    path: str
    owner: str


class _FakeContract:
    """Duck-type OwnershipContract for sanitizer tests."""

    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = tuple(rows)

    def files_for_owner(self, owner: str) -> list[_FakeRow]:
        return [r for r in self._rows if r.owner == owner]

    def owner_for(self, path: str) -> str | None:
        for row in self._rows:
            if row.path == path:
                return row.owner
        return None


@dataclass
class _WaveResult:
    findings: list = field(default_factory=list)
    files_created: list = field(default_factory=list)
    files_modified: list = field(default_factory=list)


def _cfg(**v18_kwargs: Any) -> AgentTeamConfig:
    cfg = AgentTeamConfig()
    cfg.v18 = V18Config(**v18_kwargs)
    return cfg


def _write_state_with_wave_progress(
    cwd: Path, wave_progress: dict[str, dict[str, Any]]
) -> None:
    from agent_team_v15.state import RunState, save_state

    state = RunState()
    state.wave_progress = dict(wave_progress)
    state_dir = cwd / ".agent-team"
    state_dir.mkdir(parents=True, exist_ok=True)
    save_state(state, directory=str(state_dir))


def _mk_finding(
    fid: str,
    *,
    evidence: list[str] | None = None,
    summary: str = "",
    severity: str = "HIGH",
    requirement_id: str = "AC-01",
    verdict: str = "FAIL",
) -> AuditFinding:
    return AuditFinding(
        finding_id=fid,
        auditor="scorer",
        requirement_id=requirement_id,
        verdict=verdict,
        severity=severity,
        summary=summary,
        evidence=evidence or [],
    )


# ===========================================================================
# F-ARCH-001 — Wave B sanitizer wired into wave_executor
# ===========================================================================


class TestFArch001WaveBSanitizerWired:
    """F-ARCH-001: Wave B sanitizer must run post-Wave-B and append orphan
    findings to wave_result.findings. Pre-fix: module orphaned (no import
    from wave_executor).
    """

    def test_maybe_sanitize_wave_b_outputs_is_imported_in_wave_executor(
        self,
    ) -> None:
        """The wiring function must exist in wave_executor at the N-19 hook."""
        from agent_team_v15 import wave_executor

        assert hasattr(wave_executor, "_maybe_sanitize_wave_b_outputs"), (
            "F-ARCH-001: wave_executor must expose _maybe_sanitize_wave_b_outputs"
        )
        assert callable(wave_executor._maybe_sanitize_wave_b_outputs)

    def test_wave_b_success_branch_calls_sanitizer(self) -> None:
        """Production code in wave_executor.py must reference the sanitizer."""
        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "agent_team_v15"
            / "wave_executor.py"
        ).read_text(encoding="utf-8")
        assert "_maybe_sanitize_wave_b_outputs(" in src, (
            "F-ARCH-001: wave_executor.py must invoke "
            "_maybe_sanitize_wave_b_outputs() from Wave B success branch"
        )

    def test_sanitizer_emits_orphan_finding_on_scaffold_owned_emission(
        self, tmp_path: Path
    ) -> None:
        """Integration: Wave B emits into a scaffold-owned slot → orphan."""
        wave_result = _WaveResult(files_created=["package.json"])
        contract = _FakeContract([_FakeRow("package.json", "scaffold")])
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")

        with patch(
            "agent_team_v15.scaffold_runner.load_ownership_contract",
            return_value=contract,
        ):
            _maybe_sanitize_wave_b_outputs(
                cwd=str(tmp_path),
                config=_cfg(wave_b_output_sanitization_enabled=True),
                wave_result=wave_result,
            )

        assert len(wave_result.findings) == 1, (
            "F-ARCH-001: one orphan finding expected on scaffold-owned emission"
        )
        finding = wave_result.findings[0]
        assert finding["finding_id"] == "N-19-ORPHAN-package.json"
        assert finding["auditor"] == "wave-b-sanitizer"
        assert finding["severity"] == "MEDIUM"
        assert finding["source"] == "deterministic"


# ===========================================================================
# F-ARCH-002 — audit_scope_scanner wired into _run_milestone_audit
# ===========================================================================


class TestFArch002AuditScopeScannerWired:
    """F-ARCH-002: scope scanner must run post-scorer and emit
    AUDIT-SCOPE-GAP meta-findings into the merged AuditReport.
    """

    def test_cli_py_imports_audit_scope_scanner(self) -> None:
        """cli.py must import audit_scope_scanner symbols in _run_milestone_audit."""
        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "agent_team_v15"
            / "cli.py"
        ).read_text(encoding="utf-8")
        assert "from .audit_scope_scanner import" in src, (
            "F-ARCH-002: cli.py must import from audit_scope_scanner"
        )
        assert "scan_audit_scope" in src
        assert "build_scope_gap_findings" in src

    def test_scope_scanner_emits_gap_finding_for_uncovered_requirement(
        self, tmp_path: Path
    ) -> None:
        """Integration: a requirement with no coverage emits an INFO gap."""
        cfg = _cfg(
            audit_scope_completeness_enabled=True,
            content_scope_scanner_enabled=False,
        )
        req_path = tmp_path / "REQUIREMENTS.md"
        req_path.write_text(
            "- [ ] REQ-UX: Users should feel empowered\n",
            encoding="utf-8",
        )
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req_path, config=cfg
        )
        assert len(gaps) == 1
        payloads = build_scope_gap_findings(gaps)
        assert payloads[0]["finding_id"] == "AUDIT-SCOPE-GAP-REQ-UX"
        assert payloads[0]["severity"] == "INFO"
        assert payloads[0]["auditor"] == "audit-scope-scanner"
        assert payloads[0]["verdict"] == "UNVERIFIED"

    def test_scope_scanner_merge_through_auditfinding_from_dict(
        self, tmp_path: Path
    ) -> None:
        """Gap payloads must survive AuditFinding.from_dict round-trip."""
        cfg = _cfg(
            audit_scope_completeness_enabled=True,
            content_scope_scanner_enabled=False,
        )
        req_path = tmp_path / "REQUIREMENTS.md"
        req_path.write_text(
            "- [ ] REQ-ABSTRACT: delight the users and surprise them\n",
            encoding="utf-8",
        )
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req_path, config=cfg
        )
        payloads = build_scope_gap_findings(gaps)
        findings = [AuditFinding.from_dict(p) for p in payloads]
        assert findings[0].finding_id == "AUDIT-SCOPE-GAP-REQ-ABSTRACT"
        assert findings[0].severity == "INFO"

    def test_flag_off_returns_empty_gap_list(self, tmp_path: Path) -> None:
        cfg = _cfg(audit_scope_completeness_enabled=False)
        req_path = tmp_path / "REQUIREMENTS.md"
        req_path.write_text(
            "- [ ] REQ-UX: Users should feel empowered\n",
            encoding="utf-8",
        )
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req_path, config=cfg
        )
        assert gaps == [], "flag-off must short-circuit to empty list"


# ===========================================================================
# F-ARCH-003 — infra_detector wired into endpoint_prober
# ===========================================================================


class TestFArch003InfraDetectorWired:
    """F-ARCH-003: infra_detector must feed probe URL assembly and be
    called from endpoint_prober.
    """

    def test_endpoint_prober_imports_infra_detector(self) -> None:
        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "agent_team_v15"
            / "endpoint_prober.py"
        ).read_text(encoding="utf-8")
        assert "from .infra_detector import detect_runtime_infra" in src, (
            "F-ARCH-003: endpoint_prober must import detect_runtime_infra"
        )
        assert "from .infra_detector import build_probe_url" in src, (
            "F-ARCH-003: endpoint_prober must import build_probe_url"
        )

    def test_detect_runtime_infra_reads_api_prefix_from_main_ts(
        self, tmp_path: Path
    ) -> None:
        """Integration: main.ts with setGlobalPrefix → api_prefix populated."""
        api_src = tmp_path / "apps" / "api" / "src"
        api_src.mkdir(parents=True)
        (api_src / "main.ts").write_text(
            "app.setGlobalPrefix('api');\n", encoding="utf-8"
        )
        cfg = _cfg(runtime_infra_detection_enabled=True)

        infra = detect_runtime_infra(tmp_path, config=cfg)

        assert infra.api_prefix == "api"
        assert "api_prefix" in infra.sources

    def test_build_probe_url_honors_api_prefix(self) -> None:
        """F-ARCH-003: probe URL must include detected api_prefix once."""
        infra = RuntimeInfra(api_prefix="api")
        url = build_probe_url("http://localhost:3080", "/health", infra=infra)
        assert url == "http://localhost:3080/api/health"

    def test_build_probe_url_no_doubled_slash_with_trailing_and_leading(
        self,
    ) -> None:
        """Single slash between segments regardless of caller formatting."""
        infra = RuntimeInfra(api_prefix="/api/")
        url = build_probe_url("http://localhost:3080/", "/users", infra=infra)
        assert url == "http://localhost:3080/api/users"

    def test_build_probe_url_no_duplicate_existing_prefix(self) -> None:
        """Routes extracted with /api already present must not become /api/api."""
        infra = RuntimeInfra(api_prefix="api")
        url = build_probe_url("http://localhost:3080", "/api/users", infra=infra)
        assert url == "http://localhost:3080/api/users"

    def test_build_probe_url_no_prefix_matches_pre_phase_f_shape(self) -> None:
        """Empty prefix or None infra preserves legacy URL shape."""
        url_empty = build_probe_url("http://h:3080", "/x", infra=RuntimeInfra())
        assert url_empty == "http://h:3080/x"
        url_none = build_probe_url("http://h:3080", "/x", infra=None)
        assert url_none == "http://h:3080/x"

    def test_flag_off_returns_empty_runtime_infra(self, tmp_path: Path) -> None:
        api_src = tmp_path / "apps" / "api" / "src"
        api_src.mkdir(parents=True)
        (api_src / "main.ts").write_text(
            "app.setGlobalPrefix('api');\n", encoding="utf-8"
        )
        cfg = _cfg(runtime_infra_detection_enabled=False)
        infra = detect_runtime_infra(tmp_path, config=cfg)
        assert infra.api_prefix == ""
        assert infra.sources == {}


# ===========================================================================
# F-ARCH-004 — stamp_all_reports wired into _run_audit_loop
# ===========================================================================


class TestFArch004StampAllReportsWired:
    """F-ARCH-004: stamp_all_reports must run at audit-loop finalize."""

    def test_cli_py_imports_confidence_banners(self) -> None:
        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "agent_team_v15"
            / "cli.py"
        ).read_text(encoding="utf-8")
        assert "from .confidence_banners import" in src, (
            "F-ARCH-004: cli.py must import confidence_banners"
        )
        assert "stamp_all_reports" in src

    def test_stamp_all_reports_adds_confidence_to_audit_report(
        self, tmp_path: Path
    ) -> None:
        """Integration: AUDIT_REPORT.json gains confidence + reasoning."""
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AUDIT_REPORT.json").write_text(
            json.dumps({"score": 92.0, "findings": []}), encoding="utf-8"
        )
        cfg = _cfg(confidence_banners_enabled=True, evidence_mode="soft_gate")
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            fix_loop_converged=True,
            runtime_verification_ran=True,
            scanners_run=3,
            scanners_total=3,
        )

        touched = stamp_all_reports(
            agent_team_dir=agent_dir, signals=signals, config=cfg
        )

        assert len(touched) == 1
        audit = json.loads(
            (agent_dir / "AUDIT_REPORT.json").read_text(encoding="utf-8")
        )
        assert audit["confidence"] == CONFIDENCE_CONFIDENT
        assert "soft_gate" in audit["confidence_reasoning"]
        assert "fix loop converged" in audit["confidence_reasoning"]

    def test_stamp_all_reports_stamps_every_artefact_type(
        self, tmp_path: Path
    ) -> None:
        """All four artefact types picked up when present."""
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AUDIT_REPORT.json").write_text(
            json.dumps({"score": 92.0}), encoding="utf-8"
        )
        (agent_dir / "BUILD_LOG.txt").write_text(
            "2026-04-17 build start\n", encoding="utf-8"
        )
        (agent_dir / "GATE_A_REPORT.md").write_text(
            "# Gate A\nbody\n", encoding="utf-8"
        )
        (agent_dir / "FINAL_RECOVERY_REPORT.md").write_text(
            "# Recovery\n", encoding="utf-8"
        )

        cfg = _cfg(confidence_banners_enabled=True)
        signals = ConfidenceSignals(evidence_mode="soft_gate")
        touched = stamp_all_reports(
            agent_team_dir=agent_dir, signals=signals, config=cfg
        )

        assert len(touched) == 4
        assert all(v for v in touched.values())
        assert (agent_dir / "BUILD_LOG.txt").read_text(
            encoding="utf-8"
        ).startswith("[CONFIDENCE=")
        assert (agent_dir / "GATE_A_REPORT.md").read_text(
            encoding="utf-8"
        ).startswith("## Confidence:")
        assert (agent_dir / "FINAL_RECOVERY_REPORT.md").read_text(
            encoding="utf-8"
        ).startswith("## Confidence:")

    def test_stamp_all_reports_is_idempotent(self, tmp_path: Path) -> None:
        """Running twice does not stack banners; second call is a no-op
        when the signals are unchanged."""
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AUDIT_REPORT.json").write_text(
            json.dumps({"score": 90.0}), encoding="utf-8"
        )
        cfg = _cfg(confidence_banners_enabled=True)
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            fix_loop_converged=True,
            runtime_verification_ran=True,
        )
        first = stamp_all_reports(
            agent_team_dir=agent_dir, signals=signals, config=cfg
        )
        second = stamp_all_reports(
            agent_team_dir=agent_dir, signals=signals, config=cfg
        )
        # First call modifies; second returns False (unchanged).
        assert first[str(agent_dir / "AUDIT_REPORT.json")] is True
        assert second[str(agent_dir / "AUDIT_REPORT.json")] is False


# ===========================================================================
# F-ARCH-005 — cascade default-off flag (characterization)
# ===========================================================================


class TestFArch005CascadeFlagCharacterization:
    """F-ARCH-005 (UNFIXED, accepted): cascade_consolidation_enabled
    defaults False. Pin both the default and the "flag on activates
    cascade" behavior so the decision remains auditable.
    """

    def test_cascade_consolidation_enabled_defaults_false(self) -> None:
        cfg = V18Config()
        assert cfg.cascade_consolidation_enabled is False, (
            "F-ARCH-005: accepted-risk default MUST remain False"
        )

    def test_flag_off_cascade_is_no_op(self, tmp_path: Path) -> None:
        """Default config (flag off) leaves the report unchanged."""
        cfg = AgentTeamConfig()
        cfg.v18 = V18Config()
        findings = [
            _mk_finding("F-1", evidence=["apps/api/src/main.ts:10"]),
            _mk_finding(
                "F-2", evidence=["apps/api/src/main.ts:20"],
                requirement_id="AC-02",
            ),
        ]
        report = build_report(
            audit_id="AR-T", cycle=1, auditors_deployed=["s"], findings=findings
        )
        result = _consolidate_cascade_findings(
            report, config=cfg, cwd=str(tmp_path)
        )
        assert result is report, "flag off is a no-op on the same object"
        assert [f.finding_id for f in result.findings] == ["F-1", "F-2"]

    def test_flag_on_activates_cascade_when_wave_d_failed(
        self, tmp_path: Path
    ) -> None:
        """Pin the positive case: flag True + wave-d failure activates
        cascade consolidation so accepting the default-off risk does not
        also degrade the on-switch."""
        cfg = _cfg(cascade_consolidation_enabled=True)
        _write_state_with_wave_progress(
            tmp_path,
            {"M1": {"failed_wave": "D"}},
        )
        findings = [
            _mk_finding(
                "F-web-1",
                evidence=["apps/web/app/page.tsx:10"],
                summary="Web page broken",
            ),
            _mk_finding(
                "F-web-2",
                evidence=["apps/web/app/layout.tsx:5"],
                summary="Layout broken",
                requirement_id="AC-02",
            ),
            _mk_finding(
                "F-web-3",
                evidence=["apps/web/lib/client.ts:3"],
                summary="Client broken",
                requirement_id="AC-03",
            ),
        ]
        report = build_report(
            audit_id="AR-T",
            cycle=1,
            auditors_deployed=["s"],
            findings=findings,
        )

        result = _consolidate_cascade_findings(
            report,
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="M1",
        )

        cascade_rep = [f for f in result.findings if f.cascade_count >= 2]
        meta = [
            f for f in result.findings if f.finding_id.startswith("F-CASCADE-")
        ]
        assert cascade_rep, "flag on must produce ≥1 cascade representative"
        assert meta, "flag on must emit F-CASCADE-META finding"


# ===========================================================================
# F-ARCH-006 — derive_confidence with scanners_total == 0
# ===========================================================================


class TestFArch006DeriveConfidenceZeroScannersCharacterization:
    """F-ARCH-006 (UNFIXED): pin current behavior around scanners_total=0."""

    def test_zero_scanners_does_not_raise(self) -> None:
        """No divide-by-zero, no exception."""
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            scanners_run=0,
            scanners_total=0,
            fix_loop_converged=True,
            runtime_verification_ran=True,
        )
        label, reasoning = derive_confidence(signals)
        assert label in {
            CONFIDENCE_CONFIDENT,
            CONFIDENCE_MEDIUM,
            CONFIDENCE_LOW,
        }
        assert "0/0 post-Wave-E scanners ran" in reasoning

    def test_zero_scanners_soft_gate_converged_runtime_ran_returns_confident(
        self,
    ) -> None:
        """Pin the *current* CONFIDENT rule even though reviewer flagged
        it. If future work downgrades this path to MEDIUM, this test is
        the canary."""
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            scanners_run=0,
            scanners_total=0,
            fix_loop_converged=True,
            runtime_verification_ran=True,
        )
        label, _ = derive_confidence(signals)
        assert label == CONFIDENCE_CONFIDENT, (
            "F-ARCH-006: current CONFIDENT gate treats scanners_total==0 "
            "as full coverage — pin this to catch a future reviewer fix."
        )


# ===========================================================================
# F-FWK-001 — Prisma 5 deprecated shutdown hook (REGRESSION GUARD)
# ===========================================================================


class TestFFwk001PrismaShutdownHookRegression:
    """F-FWK-001 (FIXED by framework-correctness fixer): scaffold must NOT
    emit the deprecated enableShutdownHooks pattern.
    """

    def test_prisma_service_template_has_no_enable_shutdown_hooks(self) -> None:
        """The PrismaService emission must not include the deprecated method."""
        from agent_team_v15 import scaffold_runner

        body = scaffold_runner._api_prisma_service_template()
        assert "enableShutdownHooks" not in body, (
            "F-FWK-001 regression: deprecated enableShutdownHooks method "
            "reappeared in PrismaService emission"
        )
        assert "process.on('beforeExit'" not in body, (
            "F-FWK-001 regression: deprecated beforeExit hook reappeared"
        )
        assert "this.$on('beforeExit'" not in body, (
            "F-FWK-001 regression: Prisma 5 $on('beforeExit') reappeared"
        )

    def test_main_ts_template_calls_enable_shutdown_hooks(self) -> None:
        """Main.ts must invoke Nest-native app.enableShutdownHooks()."""
        from agent_team_v15 import scaffold_runner

        body = scaffold_runner._api_main_ts_template()
        assert "app.enableShutdownHooks()" in body, (
            "F-FWK-001 regression: main.ts must call "
            "app.enableShutdownHooks() (Nest-native lifecycle)"
        )


# ===========================================================================
# F-FWK-002..009 — framework correctness PASS findings (spot checks)
# ===========================================================================


class TestFFwk003SetGlobalPrefixRegex:
    """F-FWK-003 (PASS): infra_detector must parse bare-string setGlobalPrefix."""

    def test_detects_bare_string_prefix(self, tmp_path: Path) -> None:
        api_src = tmp_path / "apps" / "api" / "src"
        api_src.mkdir(parents=True)
        (api_src / "main.ts").write_text(
            "app.setGlobalPrefix('api', { exclude: ['health'] });\n",
            encoding="utf-8",
        )
        infra = detect_runtime_infra(
            tmp_path, config=_cfg(runtime_infra_detection_enabled=True)
        )
        assert infra.api_prefix == "api"

    def test_detects_backtick_template_prefix(self, tmp_path: Path) -> None:
        api_src = tmp_path / "apps" / "api" / "src"
        api_src.mkdir(parents=True)
        (api_src / "main.ts").write_text(
            "app.setGlobalPrefix(`v1`);\n", encoding="utf-8"
        )
        infra = detect_runtime_infra(
            tmp_path, config=_cfg(runtime_infra_detection_enabled=True)
        )
        assert infra.api_prefix == "v1"


# ===========================================================================
# F-RT-001 — codex app-server orphan interrupt fix (REGRESSION GUARD)
# ===========================================================================


class TestFRt001CodexOrphanInterruptRegression:
    """F-RT-001 (FIXED): codex_appserver must send turn/interrupt on
    first orphan and not block the event loop.
    """

    def test_send_turn_interrupt_exists(self) -> None:
        """The fix introduced _send_turn_interrupt — must still exist."""
        from agent_team_v15 import codex_appserver

        assert hasattr(codex_appserver, "_send_turn_interrupt"), (
            "F-RT-001 regression: _send_turn_interrupt must exist"
        )
        assert inspect.iscoroutinefunction(codex_appserver._send_turn_interrupt)

    def test_monitor_orphans_exists_as_coroutine(self) -> None:
        from agent_team_v15 import codex_appserver

        assert hasattr(codex_appserver, "_monitor_orphans")
        assert inspect.iscoroutinefunction(codex_appserver._monitor_orphans)

    def test_orphan_watchdog_uses_threading_lock(self) -> None:
        """F-RT-001 structural fix: watchdog must be thread-safe."""
        from agent_team_v15 import codex_appserver

        wd = codex_appserver._OrphanWatchdog(
            timeout_seconds=10, max_orphan_events=2
        )
        # threading.Lock() returns a factory-created lock object — check
        # by attempting acquire/release which only a lock supports.
        assert wd._lock.acquire(blocking=False), (
            "F-RT-001 regression: _lock must be a threading primitive"
        )
        wd._lock.release()
        assert hasattr(wd, "_registered_orphans")
        assert isinstance(wd._registered_orphans, set)

    def test_orphan_watchdog_dedupes_same_tool_id(self) -> None:
        """Same tool_id must not double-count — locks the dedup fix."""
        from agent_team_v15 import codex_appserver

        wd = codex_appserver._OrphanWatchdog(
            timeout_seconds=0.001, max_orphan_events=5
        )
        # record_start uses time.monotonic; we wait long enough for it
        # to register the orphan the first time but not the second.
        wd.record_start("tu-1", "commandExecution")
        import time as _time

        _time.sleep(0.05)

        is_orphan_1, tool_name_1, tool_id_1, _, command_summary_1 = wd.check_orphans()
        wd.register_orphan_event(tool_name_1, tool_id_1, 0.05)
        is_orphan_2, _, tool_id_2, _, _ = wd.check_orphans()
        assert is_orphan_1 is True
        assert tool_id_1 == "tu-1"
        assert command_summary_1 == ""
        # Second scan must NOT re-register the same tool
        assert is_orphan_2 is False, (
            "F-RT-001 regression: same tool_id must dedupe in check_orphans"
        )

    def test_process_streaming_event_does_not_register_orphan(self) -> None:
        """Regression: callback thread must no longer increment orphan
        count directly (responsibility moved to _monitor_orphans)."""
        from agent_team_v15 import codex_appserver

        src = inspect.getsource(codex_appserver._process_streaming_event)
        assert "register_orphan_event" not in src, (
            "F-RT-001 regression: _process_streaming_event must not call "
            "register_orphan_event — that belongs to _monitor_orphans"
        )


# ===========================================================================
# F-RT-002 — stamp_* non-atomic writes (characterization)
# ===========================================================================


class TestFRt002StampNonAtomicCharacterization:
    """F-RT-002 (UNFIXED): stamp_* helpers use write_text (non-atomic).
    Pin the current behavior: a simulated OSError during write leaves
    the operation failed and does not produce a temp-file sibling.
    """

    def test_stamp_json_report_uses_write_text(self) -> None:
        """The source must still use write_text (non-atomic). If a future
        atomic fix lands (tmp + os.replace), this test flips intentionally."""
        from agent_team_v15 import confidence_banners

        src = inspect.getsource(confidence_banners.stamp_json_report)
        assert "write_text" in src
        assert "os.replace" not in src, (
            "F-RT-002 characterization: if atomic rename is added, update "
            "this test AND remove the F-RT-002 accepted-risk marker."
        )

    def test_stamp_build_log_uses_write_text(self) -> None:
        from agent_team_v15 import confidence_banners

        src = inspect.getsource(confidence_banners.stamp_build_log)
        assert "write_text" in src
        assert "os.replace" not in src

    def test_stamp_markdown_report_uses_write_text(self) -> None:
        from agent_team_v15 import confidence_banners

        src = inspect.getsource(confidence_banners.stamp_markdown_report)
        assert "write_text" in src
        assert "os.replace" not in src

    def test_stamp_json_report_returns_false_on_oserror(
        self, tmp_path: Path
    ) -> None:
        """When write fails, stamp_json_report returns False — pinning
        the current non-atomic fail-soft behavior."""
        target = tmp_path / "AUDIT_REPORT.json"
        target.write_text(json.dumps({"score": 90}), encoding="utf-8")
        with patch.object(
            Path, "write_text", side_effect=OSError("disk full")
        ):
            result = stamp_json_report(
                target, label="MEDIUM", reasoning="x"
            )
        assert result is False, (
            "F-RT-002 characterization: write failure returns False, not raise"
        )


# ===========================================================================
# F-RT-003 — wave_b_sanitizer silent OSError (characterization)
# ===========================================================================


class TestFRt003SanitizerSilentOSErrorCharacterization:
    """F-RT-003 (UNFIXED): _scan_for_consumers silently swallows OSError
    and continues. Pin that behavior.
    """

    def test_scan_for_consumers_skips_on_read_failure(
        self, tmp_path: Path
    ) -> None:
        """A candidate file whose read fails is silently skipped."""
        from agent_team_v15 import wave_b_sanitizer

        (tmp_path / "a.ts").write_text(
            "import x from 'packages/api-client';\n", encoding="utf-8"
        )

        real_read = Path.read_text

        def _fake_read(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name == "a.ts":
                raise OSError("disk hiccup")
            return real_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", _fake_read):
            samples = wave_b_sanitizer._scan_for_consumers(
                tmp_path, "packages/api-client/index.ts"
            )
        assert samples == [], (
            "F-RT-003 characterization: OSError swallowed silently; "
            "no consumer reported"
        )

    def test_remove_orphans_default_false_in_sanitize(self) -> None:
        """Default remove_orphans=False prevents silent deletions."""
        sig = inspect.signature(sanitize_wave_b_outputs)
        default = sig.parameters["remove_orphans"].default
        assert default is False, (
            "F-RT-003 characterization: remove_orphans default MUST be False"
        )


# ===========================================================================
# F-RT-004 — dispatch_fix_agent sync-only contract (characterization)
# ===========================================================================


class TestFRt004DispatchFixAgentSyncContract:
    """F-RT-004 (UNFIXED): dispatch_fix_agent calls asyncio.run() and
    must only be invoked from sync context. Pin that contract.
    """

    def test_dispatch_fix_agent_is_sync_function(self) -> None:
        """Must remain a sync def so asyncio.run() works."""
        from agent_team_v15 import runtime_verification

        fn = runtime_verification.dispatch_fix_agent
        assert inspect.isfunction(fn)
        assert not inspect.iscoroutinefunction(fn), (
            "F-RT-004: dispatch_fix_agent must stay sync — its body uses "
            "asyncio.run() which fails inside a running loop"
        )

    def test_runtime_verification_source_uses_asyncio_run(self) -> None:
        from agent_team_v15 import runtime_verification

        src = inspect.getsource(runtime_verification.dispatch_fix_agent)
        assert "asyncio.run(" in src, (
            "F-RT-004: body MUST call asyncio.run; if this changes the "
            "sync-only contract no longer applies and F-RT-004 can be closed"
        )


# ===========================================================================
# F-INT-002 — sanitizer owner list includes wave-d (REGRESSION GUARD)
# ===========================================================================


class TestFInt002SanitizerIncludesWaveDOwner:
    """F-INT-002 (FIXED): non_wave_b_paths set must include wave-d paths
    so Wave B encroachment on wave-d slots is flagged.
    """

    def test_wave_b_emission_in_wave_d_owned_path_is_orphan(
        self, tmp_path: Path
    ) -> None:
        """Wave B writes apps/web/page.tsx (a wave-d owned path) → orphan."""
        contract = _FakeContract(
            [_FakeRow("apps/web/app/page.tsx", "wave-d")]
        )
        # Create the file so resolve() works.
        target = tmp_path / "apps" / "web" / "app" / "page.tsx"
        target.parent.mkdir(parents=True)
        target.write_text("export default function Page() { return null }\n")

        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=contract,
            wave_b_files=["apps/web/app/page.tsx"],
            config=_cfg(wave_b_output_sanitization_enabled=True),
        )

        assert report.orphan_count == 1, (
            "F-INT-002 regression: wave-d-owned emission must be flagged"
        )
        assert report.orphan_findings[0].expected_owner == "wave-d"

    def test_sanitizer_source_lists_wave_d_owner(self) -> None:
        """Belt + braces: the owner tuple in the source must contain wave-d."""
        from agent_team_v15 import wave_b_sanitizer

        src = inspect.getsource(
            wave_b_sanitizer.sanitize_wave_b_outputs
        )
        assert '"wave-d"' in src, (
            "F-INT-002 regression: sanitize_wave_b_outputs must iterate "
            "over wave-d owner to catch encroachments"
        )


# ===========================================================================
# F-EDGE-002 — Wave D cascade scoped per milestone (REGRESSION GUARD)
# ===========================================================================


class TestFEdge002WaveDCascadeMilestoneScoped:
    """F-EDGE-002 (FIXED): M1 Wave-D failure must not cascade into M2's
    findings when M2's Wave-D succeeded.
    """

    def test_load_wave_d_roots_scoped_to_milestone(
        self, tmp_path: Path
    ) -> None:
        """Only the named milestone's failed_wave is consulted."""
        _write_state_with_wave_progress(
            tmp_path,
            {
                "M1": {"failed_wave": "D"},
                "M2": {"failed_wave": ""},
            },
        )
        roots_m1 = _load_wave_d_failure_roots(
            str(tmp_path), milestone_id="M1"
        )
        roots_m2 = _load_wave_d_failure_roots(
            str(tmp_path), milestone_id="M2"
        )
        assert "apps/web" in roots_m1
        assert roots_m2 == [], (
            "F-EDGE-002 regression: M2 cascade must be empty when M2 Wave-D "
            "succeeded (even when M1 Wave-D failed)"
        )

    def test_load_wave_d_roots_legacy_union_fallback(
        self, tmp_path: Path
    ) -> None:
        """No milestone_id → legacy union across all milestones."""
        _write_state_with_wave_progress(
            tmp_path,
            {
                "M1": {"failed_wave": "D"},
                "M2": {"failed_wave": ""},
            },
        )
        roots = _load_wave_d_failure_roots(str(tmp_path))
        assert "apps/web" in roots, (
            "legacy callers (no milestone_id) still see union behavior"
        )

    def test_m2_findings_not_collapsed_when_m1_only_failed(
        self, tmp_path: Path
    ) -> None:
        """Integration: M2's audit should NOT collapse web-app findings
        when only M1's Wave D failed."""
        cfg = _cfg(cascade_consolidation_enabled=True)
        _write_state_with_wave_progress(
            tmp_path,
            {
                "M1": {"failed_wave": "D"},
                "M2": {"failed_wave": ""},
            },
        )
        findings = [
            _mk_finding(
                "F-web-1",
                evidence=["apps/web/page.tsx:1"],
                summary="Web issue 1",
            ),
            _mk_finding(
                "F-web-2",
                evidence=["apps/web/layout.tsx:1"],
                summary="Web issue 2",
                requirement_id="AC-02",
            ),
            _mk_finding(
                "F-web-3",
                evidence=["apps/web/client.ts:1"],
                summary="Web issue 3",
                requirement_id="AC-03",
            ),
        ]
        report = build_report(
            audit_id="AR-M2",
            cycle=1,
            auditors_deployed=["s"],
            findings=findings,
        )
        # Run consolidation with milestone_id="M2"
        result = _consolidate_cascade_findings(
            report,
            config=cfg,
            cwd=str(tmp_path),
            milestone_id="M2",
        )
        # M2 findings must NOT be collapsed — cascade_count stays 0.
        for f in result.findings:
            if f.finding_id.startswith("F-web-"):
                assert f.cascade_count == 0, (
                    f"F-EDGE-002 regression: {f.finding_id} was collapsed "
                    "under 'upstream Wave D' despite M2's Wave D succeeding"
                )


# ===========================================================================
# F-EDGE-003 — AuditReport.from_json schema validation (REGRESSION GUARD)
# ===========================================================================


class TestFEdge003FromJsonSchemaValidation:
    """F-EDGE-003 (FIXED): from_json must raise AuditReportSchemaError on
    non-list findings instead of AttributeError.
    """

    def test_from_json_raises_typed_error_on_dict_findings(self) -> None:
        payload = json.dumps({"findings": {"0": {}, "1": {}}, "score": 0})
        with pytest.raises(AuditReportSchemaError):
            AuditReport.from_json(payload)

    def test_from_json_raises_typed_error_on_string_findings(self) -> None:
        payload = json.dumps({"findings": "oops", "score": 0})
        with pytest.raises(AuditReportSchemaError):
            AuditReport.from_json(payload)

    def test_from_json_raises_typed_error_on_int_findings(self) -> None:
        payload = json.dumps({"findings": 42, "score": 0})
        with pytest.raises(AuditReportSchemaError):
            AuditReport.from_json(payload)

    def test_from_json_accepts_none_findings_as_empty(self) -> None:
        """None is treated as the empty-list sentinel."""
        payload = json.dumps({"findings": None, "score": 0})
        report = AuditReport.from_json(payload)
        assert report.findings == []

    def test_from_json_accepts_empty_list(self) -> None:
        payload = json.dumps({"findings": [], "score": 0})
        report = AuditReport.from_json(payload)
        assert report.findings == []

    def test_from_json_raises_typed_error_on_malformed_entry(self) -> None:
        """Non-dict entry inside the list must raise typed error."""
        payload = json.dumps({"findings": ["not-a-dict"], "score": 0})
        with pytest.raises(AuditReportSchemaError):
            AuditReport.from_json(payload)

    def test_audit_report_schema_error_is_value_error(self) -> None:
        """Subclassing ValueError allows callers to catch broadly if
        they do not want to import the typed exception."""
        assert issubclass(AuditReportSchemaError, ValueError)


# ===========================================================================
# F-EDGE-004 — Plateau oscillation characterization
# ===========================================================================


class TestFEdge004PlateauOscillationCharacterization:
    """F-EDGE-004 (UNFIXED): the plateau detector uses strict `< 3.0` which
    misses exact 3.0 deltas. Pin the current behavior so a future fix
    flips this test intentionally.
    """

    def test_plateau_check_uses_strict_less_than_3(self) -> None:
        """cli.py plateau check is `< 3.0` (strict). A future fix to `<= 3.0`
        would require updating this characterization."""
        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "agent_team_v15"
            / "cli.py"
        ).read_text(encoding="utf-8")
        # The exact phrase is at the plateau detection site.
        assert "< 3.0" in src or "< 3" in src, (
            "F-EDGE-004 characterization: plateau comparison uses strict "
            "less-than; pin this to detect a future fix"
        )


# ===========================================================================
# F-EDGE-005 — disk-full atomic write characterization
# ===========================================================================


class TestFEdge005DiskFullCharacterization:
    """F-EDGE-005 (UNFIXED): stamp_all_reports propagates disk-full as a
    False return rather than raising OSError. Characterize.
    """

    def test_stamp_all_reports_survives_oserror_during_write(
        self, tmp_path: Path
    ) -> None:
        """When an individual stamp fails it returns False; the overall
        call does not raise."""
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AUDIT_REPORT.json").write_text(
            json.dumps({"score": 80.0}), encoding="utf-8"
        )
        cfg = _cfg(confidence_banners_enabled=True)
        signals = ConfidenceSignals(evidence_mode="soft_gate")

        real_write = Path.write_text

        def _maybe_fail(self: Path, *args: Any, **kwargs: Any) -> int:
            if self.name == "AUDIT_REPORT.json":
                raise OSError("disk full")
            return real_write(self, *args, **kwargs)

        with patch.object(Path, "write_text", _maybe_fail):
            touched = stamp_all_reports(
                agent_team_dir=agent_dir, signals=signals, config=cfg
            )

        # The function returns the mapping; the JSON entry is False.
        assert touched[str(agent_dir / "AUDIT_REPORT.json")] is False


# ===========================================================================
# F-EDGE-006 — LoopState.max_iterations validation characterization
# ===========================================================================


class TestFEdge006MaxIterationsCharacterization:
    """F-EDGE-006 (UNFIXED): LoopState does not validate max_iterations.
    Characterize the current permissive behavior.
    """

    def test_loop_state_accepts_max_iterations_zero(self) -> None:
        """LoopState permits max_iterations=0 (no __post_init__ guard)."""
        from agent_team_v15.config_agent import LoopState

        # Does not raise — current behavior.
        state = LoopState(
            original_prd_path="p.md",
            codebase_path="./o",
            max_iterations=0,
        )
        assert state.max_iterations == 0

    def test_loop_state_accepts_negative_max_iterations(self) -> None:
        """Negative also accepted today — pin current behavior."""
        from agent_team_v15.config_agent import LoopState

        state = LoopState(
            original_prd_path="p.md",
            codebase_path="./o",
            max_iterations=-1,
        )
        assert state.max_iterations == -1


# ===========================================================================
# F-EDGE-007 — stamp_all_reports milestone clobber characterization
# ===========================================================================


class TestFEdge007StampAllReportsMilestoneClobberCharacterization:
    """F-EDGE-007 (UNFIXED, dormant): stamp_all_reports applies a single
    ConfidenceSignals across every artefact including per-milestone
    AUDIT_REPORT.json. Multi-milestone runs currently overwrite earlier
    milestones' banners with later signals — pin this.
    """

    def test_single_signal_applied_to_every_milestone_artefact(
        self, tmp_path: Path
    ) -> None:
        """M1 + M2 per-milestone AUDIT_REPORT.json both receive same banner."""
        agent_dir = tmp_path / ".agent-team"
        (agent_dir / "milestones" / "M1").mkdir(parents=True)
        (agent_dir / "milestones" / "M2").mkdir(parents=True)
        (agent_dir / "milestones" / "M1" / "AUDIT_REPORT.json").write_text(
            json.dumps({"score": 95}), encoding="utf-8"
        )
        (agent_dir / "milestones" / "M2" / "AUDIT_REPORT.json").write_text(
            json.dumps({"score": 60}), encoding="utf-8"
        )

        cfg = _cfg(confidence_banners_enabled=True)
        # The caller provides a single signal — current contract.
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            fix_loop_plateaued=True,
            runtime_verification_ran=False,
        )

        stamp_all_reports(
            agent_team_dir=agent_dir, signals=signals, config=cfg
        )

        m1 = json.loads(
            (agent_dir / "milestones" / "M1" / "AUDIT_REPORT.json").read_text(
                encoding="utf-8"
            )
        )
        m2 = json.loads(
            (agent_dir / "milestones" / "M2" / "AUDIT_REPORT.json").read_text(
                encoding="utf-8"
            )
        )
        # Both receive the SAME confidence — the known quirk.
        assert m1["confidence"] == m2["confidence"], (
            "F-EDGE-007 characterization: single signal broadcasts to every "
            "milestone artefact (a future per-milestone fix would diverge)"
        )


# ===========================================================================
# F-EDGE-008 — cascade scaling with many milestones
# ===========================================================================


class TestFEdge008CascadeScaling:
    """F-EDGE-008 (UNFIXED): cascade consolidation should remain correct
    for 10+ milestones. Characterize scaling assumption.
    """

    def test_cascade_consolidation_scales_to_many_milestones(
        self, tmp_path: Path
    ) -> None:
        """10 milestones all with Wave D failures → cascade still fires
        for the named milestone only."""
        progress = {
            f"M{i}": {"failed_wave": "D" if i != 5 else ""} for i in range(1, 11)
        }
        _write_state_with_wave_progress(tmp_path, progress)
        # M5 Wave D succeeded — no cascade for M5
        roots_m5 = _load_wave_d_failure_roots(
            str(tmp_path), milestone_id="M5"
        )
        assert roots_m5 == []
        # M3 Wave D failed — cascade fires
        roots_m3 = _load_wave_d_failure_roots(
            str(tmp_path), milestone_id="M3"
        )
        assert roots_m3 == ["apps/web", "packages/api-client"]


# ===========================================================================
# F-EDGE-009 — empty REQUIREMENTS.md characterization
# ===========================================================================


class TestFEdge009EmptyRequirementsCharacterization:
    """F-EDGE-009 (UNFIXED): audit_scope_scanner returns empty list on
    empty or malformed REQUIREMENTS.md. Pin the fail-open behavior.
    """

    def test_scan_with_empty_requirements_returns_empty_list(
        self, tmp_path: Path
    ) -> None:
        req_path = tmp_path / "REQUIREMENTS.md"
        req_path.write_text("", encoding="utf-8")
        gaps = scan_audit_scope(
            cwd=tmp_path,
            requirements_path=req_path,
            config=_cfg(audit_scope_completeness_enabled=True),
        )
        assert gaps == [], (
            "F-EDGE-009 characterization: empty file → empty gap list "
            "(fail-open, no parse error)"
        )

    def test_scan_with_misformatted_requirements_returns_empty_list(
        self, tmp_path: Path
    ) -> None:
        """Lines that don't match `- [ ] REQ-xxx:` form are silently ignored."""
        req_path = tmp_path / "REQUIREMENTS.md"
        req_path.write_text(
            "* REQ-001: foo\n1. REQ-002: bar\n", encoding="utf-8"
        )
        gaps = scan_audit_scope(
            cwd=tmp_path,
            requirements_path=req_path,
            config=_cfg(audit_scope_completeness_enabled=True),
        )
        assert gaps == []

    def test_scan_with_missing_requirements_file_returns_empty_list(
        self, tmp_path: Path
    ) -> None:
        req_path = tmp_path / "DOES_NOT_EXIST.md"
        gaps = scan_audit_scope(
            cwd=tmp_path,
            requirements_path=req_path,
            config=_cfg(audit_scope_completeness_enabled=True),
        )
        assert gaps == []


# ===========================================================================
# F-EDGE-010 — empty SCAFFOLD_OWNERSHIP.md characterization
# ===========================================================================


class TestFEdge010EmptyOwnershipCharacterization:
    """F-EDGE-010 (UNFIXED): wave_b_sanitizer with empty contract should
    not crash; should return no orphans.
    """

    def test_sanitize_with_empty_contract_returns_no_orphans(
        self, tmp_path: Path
    ) -> None:
        contract = _FakeContract([])
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=contract,
            wave_b_files=["apps/api/src/users/users.service.ts"],
            config=_cfg(wave_b_output_sanitization_enabled=True),
        )
        assert report.orphan_count == 0
        assert report.skipped_reason == ""

    def test_sanitize_with_none_contract_skips_and_reports(
        self, tmp_path: Path
    ) -> None:
        report = sanitize_wave_b_outputs(
            cwd=tmp_path,
            contract=None,
            wave_b_files=["apps/api/src/users.ts"],
            config=_cfg(wave_b_output_sanitization_enabled=True),
        )
        assert report.skipped_reason == "no_contract"
        assert report.orphan_count == 0


# ===========================================================================
# F-EDGE-011 — empty apps/api directory for infra_detector
# ===========================================================================


class TestFEdge011MissingApiDirCharacterization:
    """F-EDGE-011 (UNFIXED): infra_detector with missing apps/api/
    directory returns empty RuntimeInfra without raising.
    """

    def test_detect_runtime_infra_missing_api_dir(self, tmp_path: Path) -> None:
        """No apps/api dir → fully empty RuntimeInfra."""
        infra = detect_runtime_infra(
            tmp_path, config=_cfg(runtime_infra_detection_enabled=True)
        )
        assert infra.api_prefix == ""
        assert infra.cors_origin == ""
        assert infra.database_url == ""
        assert infra.jwt_audience == ""
        assert infra.sources == {}

    def test_detect_runtime_infra_missing_main_ts(self, tmp_path: Path) -> None:
        """apps/api exists but main.ts missing → api_prefix stays empty."""
        (tmp_path / "apps" / "api" / "src").mkdir(parents=True)
        infra = detect_runtime_infra(
            tmp_path, config=_cfg(runtime_infra_detection_enabled=True)
        )
        assert infra.api_prefix == ""


# ===========================================================================
# Cross-finding integration: all 4 Phase F modules firing together
# ===========================================================================


class TestPhaseFCrossFindingIntegration:
    """Integration: all 4 Phase F module wirings must cohere in a
    single audit-finalize path. If any orphan regression returns, this
    test fails early."""

    def test_all_four_modules_reachable_from_production_imports(self) -> None:
        """Grep lockdown: every Phase F module must be imported from
        production code — not just tests."""
        src_root = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15"
        combined = "\n".join(
            (src_root / f).read_text(encoding="utf-8")
            for f in (
                "cli.py",
                "wave_executor.py",
                "endpoint_prober.py",
            )
        )
        assert "from .audit_scope_scanner import" in combined, (
            "F-ARCH-002/F-INT-001/F-EDGE-001: cli.py must import audit_scope_scanner"
        )
        assert "from .confidence_banners import" in combined, (
            "F-ARCH-004: cli.py must import confidence_banners"
        )
        assert "from .infra_detector import" in combined, (
            "F-ARCH-003: endpoint_prober must import infra_detector"
        )
        assert "from .wave_b_sanitizer import" in combined, (
            "F-ARCH-001: wave_executor must import wave_b_sanitizer"
        )

    def test_full_finalize_path_stamps_and_emits(
        self, tmp_path: Path
    ) -> None:
        """Simulate an end-of-audit path: a requirement is uncovered
        (gap), stamp_all_reports runs, AUDIT_REPORT.json ends up with
        both a scope gap AND a confidence banner."""
        agent_dir = tmp_path / ".agent-team"
        agent_dir.mkdir(parents=True)
        req_path = agent_dir / "REQUIREMENTS.md"
        req_path.write_text(
            "- [ ] REQ-UX: fuzzy UI feeling\n", encoding="utf-8"
        )

        # 1. scope scanner populates gaps
        cfg = _cfg(
            audit_scope_completeness_enabled=True,
            content_scope_scanner_enabled=False,
            confidence_banners_enabled=True,
        )
        gaps = scan_audit_scope(
            cwd=tmp_path, requirements_path=req_path, config=cfg
        )
        payloads = build_scope_gap_findings(gaps)
        assert len(payloads) == 1

        # 2. write AUDIT_REPORT.json with the gap finding embedded
        (agent_dir / "AUDIT_REPORT.json").write_text(
            json.dumps(
                {
                    "findings": payloads,
                    "score": 85.0,
                    "audit_id": "AR-Test",
                }
            ),
            encoding="utf-8",
        )

        # 3. stamp_all_reports runs
        signals = ConfidenceSignals(
            evidence_mode="soft_gate",
            fix_loop_converged=True,
            runtime_verification_ran=True,
            scanners_run=3,
            scanners_total=3,
        )
        stamp_all_reports(
            agent_team_dir=agent_dir, signals=signals, config=cfg
        )

        # 4. final AUDIT_REPORT.json has both artefacts
        final = json.loads(
            (agent_dir / "AUDIT_REPORT.json").read_text(encoding="utf-8")
        )
        assert any(
            f["finding_id"].startswith("AUDIT-SCOPE-GAP-")
            for f in final["findings"]
        )
        assert final["confidence"] == CONFIDENCE_CONFIDENT
        assert "soft_gate" in final["confidence_reasoning"]


# ===========================================================================
# Flag accessors — symmetry between config default and consumer default
# ===========================================================================


class TestPhaseFFlagAccessors:
    """F-FWK-003 adjacent + F-INT config symmetry."""

    def test_all_four_phase_f_flags_default_true(self) -> None:
        cfg = V18Config()
        assert cfg.runtime_infra_detection_enabled is True
        assert cfg.confidence_banners_enabled is True
        assert cfg.audit_scope_completeness_enabled is True
        assert cfg.wave_b_output_sanitization_enabled is True

    def test_wave_b_sanitization_enabled_accessor(self) -> None:
        assert (
            wave_b_output_sanitization_enabled(
                _cfg(wave_b_output_sanitization_enabled=True)
            )
            is True
        )
        assert (
            wave_b_output_sanitization_enabled(
                _cfg(wave_b_output_sanitization_enabled=False)
            )
            is False
        )

    def test_confidence_banners_enabled_accessor(self) -> None:
        assert (
            confidence_banners_enabled(_cfg(confidence_banners_enabled=True))
            is True
        )
        assert (
            confidence_banners_enabled(_cfg(confidence_banners_enabled=False))
            is False
        )

    def test_audit_scope_completeness_enabled_accessor(self) -> None:
        assert (
            audit_scope_completeness_enabled(
                _cfg(audit_scope_completeness_enabled=True)
            )
            is True
        )
        assert (
            audit_scope_completeness_enabled(
                _cfg(audit_scope_completeness_enabled=False)
            )
            is False
        )
