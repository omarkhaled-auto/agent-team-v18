from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent_team_v15 import cli
from agent_team_v15 import runtime_verification as rv
from agent_team_v15.audit_models import AuditReport, AuditScore
from agent_team_v15.config import _dict_to_config
from agent_team_v15.runtime_verification import BuildResult, ServiceStatus, run_runtime_verification


live_tests = importlib.import_module("tests.test_codex_appserver_live")


class _ImmediateAwaitable:
    def __init__(self, value: int | None) -> None:
        self.value = value

    def __await__(self):
        async def _done():
            return self.value

        return _done().__await__()


class _DummyAsyncProcess:
    def __init__(self, *, pid: int = 12345, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self):
        self.wait_calls += 1
        return _ImmediateAwaitable(self.returncode)


def _make_config(*, reaudit_trigger_fix_enabled: bool = False):
    cfg, _ = _dict_to_config({
        "audit_team": {
            "enabled": True,
            "max_reaudit_cycles": 2,
            "score_healthy_threshold": 85.0,
        },
        "v18": {
            "reaudit_trigger_fix_enabled": reaudit_trigger_fix_enabled,
        },
    })
    return cfg


def _make_audit_report(*, cycle: int, score: float, health: str) -> AuditReport:
    return AuditReport(
        audit_id=f"audit-{cycle}",
        timestamp="2026-04-20T00:00:00Z",
        cycle=cycle,
        auditors_deployed=["requirements"],
        findings=[],
        score=AuditScore(
            total_items=1,
            passed=1 if health == "healthy" else 0,
            failed=0 if health == "healthy" else 1,
            partial=0,
            critical_count=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            info_count=0,
            score=score,
            health=health,
            max_score=100,
        ),
    )


def test_codex_live_cleanup_terminates_running_process() -> None:
    proc = _DummyAsyncProcess()

    with patch.object(live_tests.asyncio, "wait_for", side_effect=[None]):
        asyncio.run(live_tests._cleanup_spawned_appserver_processes([proc]))

    assert proc.terminate_calls == 1
    assert proc.kill_calls == 0
    assert proc.wait_calls == 1


def test_codex_live_cleanup_falls_back_to_kill_after_timeout() -> None:
    proc = _DummyAsyncProcess()

    with patch.object(
        live_tests.asyncio,
        "wait_for",
        side_effect=[asyncio.TimeoutError(), None],
    ):
        asyncio.run(live_tests._cleanup_spawned_appserver_processes([proc]))

    assert proc.terminate_calls == 1
    assert proc.kill_calls == 1
    assert proc.wait_calls == 2


def test_runtime_refresh_flag_off_keeps_single_read(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "docker_build", return_value=[BuildResult("api", True)]), \
         patch.object(rv, "docker_start", return_value=[ServiceStatus("api", False, error="starting")]), \
         patch.object(rv, "_refresh_container_health") as mock_refresh:
        report = run_runtime_verification(
            tmp_path,
            fix_loop=False,
            database_init_enabled=False,
            smoke_test_enabled=False,
            runtime_verifier_refresh_enabled=False,
        )

    mock_refresh.assert_not_called()
    assert report.services_total == 1
    assert report.services_healthy == 0


def test_refresh_container_health_retries_until_healthy(tmp_path: Path) -> None:
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    stale_status = [ServiceStatus("api", False, error="starting")]
    healthy_status = [ServiceStatus("api", True)]

    with patch.object(
        rv,
        "_check_container_health",
        side_effect=[stale_status, stale_status, healthy_status],
    ) as mock_check, \
         patch.object(rv, "_attach_logs_to_unhealthy_services", side_effect=lambda *_args: _args[2]), \
         patch.object(rv.time, "sleep") as mock_sleep:
        refreshed = rv._refresh_container_health(
            tmp_path,
            compose_file,
            attempts=5,
            interval_seconds=3.0,
        )

    assert refreshed == healthy_status
    assert mock_check.call_count == 3
    assert mock_sleep.call_count == 2


def test_refresh_container_health_returns_last_unhealthy_status(tmp_path: Path) -> None:
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    first = [ServiceStatus("api", False, error="starting")]
    last = [ServiceStatus("api", False, error="still starting")]

    with patch.object(rv, "_check_container_health", side_effect=[first, last]) as mock_check, \
         patch.object(rv, "_attach_logs_to_unhealthy_services", side_effect=lambda *_args: _args[2]), \
         patch.object(rv.time, "sleep") as mock_sleep:
        refreshed = rv._refresh_container_health(
            tmp_path,
            compose_file,
            attempts=2,
            interval_seconds=1.0,
        )

    assert refreshed == last
    assert mock_check.call_count == 2
    assert mock_sleep.call_count == 1


def test_fix_loop_runs_final_verification_pass_when_cap_reached(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "docker_build", return_value=[BuildResult("api", True)]), \
         patch.object(
             rv,
             "docker_start",
             side_effect=[
                 [ServiceStatus("api", False, error="boom", logs_tail="boom")],
                 [ServiceStatus("api", True)],
             ],
         ) as mock_start, \
         patch.object(rv, "dispatch_fix_agent", return_value=1.0) as mock_fix, \
         patch.object(rv, "_run_docker", return_value=(0, "", "")):
        report = run_runtime_verification(
            tmp_path,
            fix_loop=True,
            max_fix_rounds_per_service=2,
            max_total_fix_rounds=1,
            database_init_enabled=False,
            smoke_test_enabled=False,
        )

    assert mock_fix.call_count == 1
    assert mock_start.call_count == 2
    assert report.services_total == 1
    assert report.services_healthy == 1


def test_fix_loop_cap_telemetry_emits_when_final_verification_still_unhealthy(
    tmp_path: Path,
    caplog,
) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    with patch.object(rv, "check_docker_available", return_value=True), \
         patch.object(rv, "docker_build", return_value=[BuildResult("api", True)]), \
         patch.object(
             rv,
             "docker_start",
             side_effect=[
                 [ServiceStatus("api", False, error="boom", logs_tail="boom")],
                 [ServiceStatus("api", False, error="still boom", logs_tail="still boom")],
             ],
         ), \
         patch.object(rv, "dispatch_fix_agent", return_value=1.0), \
         patch.object(rv, "_run_docker", return_value=(0, "", "")), \
         caplog.at_level(logging.WARNING):
        report = run_runtime_verification(
            tmp_path,
            fix_loop=True,
            max_fix_rounds_per_service=2,
            max_total_fix_rounds=1,
            database_init_enabled=False,
            smoke_test_enabled=False,
        )

    assert report.services_healthy == 0
    assert any("FIX-LOOP-CAP-REACHED" in record.message for record in caplog.records)


def test_failed_milestone_audit_flag_off_skips_audit_loop(tmp_path: Path) -> None:
    cfg = _make_config(reaudit_trigger_fix_enabled=False)
    requirements_path = tmp_path / "REQUIREMENTS.md"
    requirements_path.write_text("# REQ\n", encoding="utf-8")

    with patch.object(cli, "_run_audit_loop", new=AsyncMock()) as mock_loop:
        cost = asyncio.run(
            cli._run_failed_milestone_audit_if_enabled(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=cfg,
                depth="medium",
                task_text="test",
                requirements_path=str(requirements_path),
                audit_dir=str(tmp_path / ".agent-team"),
                cwd=str(tmp_path),
            )
        )

    assert cost == 0.0
    mock_loop.assert_not_awaited()


def test_failed_milestone_audit_flag_on_runs_audit_loop(tmp_path: Path) -> None:
    cfg = _make_config(reaudit_trigger_fix_enabled=True)
    requirements_path = tmp_path / "REQUIREMENTS.md"
    requirements_path.write_text("# REQ\n", encoding="utf-8")
    report = _make_audit_report(cycle=1, score=52.0, health="failed")

    with patch.object(cli, "_run_audit_loop", new=AsyncMock(return_value=(report, 3.5))) as mock_loop:
        cost = asyncio.run(
            cli._run_failed_milestone_audit_if_enabled(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=cfg,
                depth="medium",
                task_text="test",
                requirements_path=str(requirements_path),
                audit_dir=str(tmp_path / ".agent-team"),
                cwd=str(tmp_path),
            )
        )

    assert cost == 3.5
    mock_loop.assert_awaited_once()


def test_audit_loop_reaudits_low_score_until_healthy(tmp_path: Path) -> None:
    cfg = _make_config(reaudit_trigger_fix_enabled=True)
    requirements_path = tmp_path / "REQUIREMENTS.md"
    requirements_path.write_text("# REQ\n", encoding="utf-8")
    audit_dir = tmp_path / ".agent-team"
    audit_dir.mkdir(parents=True, exist_ok=True)
    seen_cycles: list[int] = []

    async def _fake_run_milestone_audit(**kwargs):
        cycle = kwargs["cycle"]
        seen_cycles.append(cycle)
        if cycle == 1:
            return _make_audit_report(cycle=1, score=52.0, health="failed"), 1.0
        return _make_audit_report(cycle=2, score=86.0, health="healthy"), 1.0

    with patch.object(cli, "_run_milestone_audit", side_effect=_fake_run_milestone_audit), \
         patch.object(cli, "_run_audit_fix_unified", new=AsyncMock(return_value=([], 2.0))) as mock_fix:
        report, total_cost = asyncio.run(
            cli._run_audit_loop(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=cfg,
                depth="medium",
                task_text="test",
                requirements_path=str(requirements_path),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
            )
        )

    assert seen_cycles == [1, 2]
    mock_fix.assert_awaited_once()
    assert report is not None
    assert report.cycle == 2
    assert total_cost == 4.0


def test_audit_loop_stops_after_first_healthy_cycle(tmp_path: Path) -> None:
    cfg = _make_config(reaudit_trigger_fix_enabled=True)
    requirements_path = tmp_path / "REQUIREMENTS.md"
    requirements_path.write_text("# REQ\n", encoding="utf-8")
    audit_dir = tmp_path / ".agent-team"
    audit_dir.mkdir(parents=True, exist_ok=True)
    seen_cycles: list[int] = []

    async def _fake_run_milestone_audit(**kwargs):
        cycle = kwargs["cycle"]
        seen_cycles.append(cycle)
        return _make_audit_report(cycle=cycle, score=92.0, health="healthy"), 1.0

    with patch.object(cli, "_run_milestone_audit", side_effect=_fake_run_milestone_audit), \
         patch.object(cli, "_run_audit_fix_unified", new=AsyncMock(return_value=([], 2.0))) as mock_fix:
        report, total_cost = asyncio.run(
            cli._run_audit_loop(
                milestone_id="milestone-1",
                milestone_template="full_stack",
                config=cfg,
                depth="medium",
                task_text="test",
                requirements_path=str(requirements_path),
                audit_dir=str(audit_dir),
                cwd=str(tmp_path),
            )
        )

    assert seen_cycles == [1]
    mock_fix.assert_not_awaited()
    assert report is not None
    assert report.cycle == 1
    assert total_cost == 1.0


def test_h3g_config_flags_round_trip() -> None:
    cfg, _ = _dict_to_config({
        "v18": {
            "runtime_verifier_refresh_enabled": True,
            "runtime_verifier_refresh_attempts": 7,
            "runtime_verifier_refresh_interval_seconds": 1.5,
            "reaudit_trigger_fix_enabled": True,
        },
    })

    assert cfg.v18.runtime_verifier_refresh_enabled is True
    assert cfg.v18.runtime_verifier_refresh_attempts == 7
    assert cfg.v18.runtime_verifier_refresh_interval_seconds == 1.5
    assert cfg.v18.reaudit_trigger_fix_enabled is True
