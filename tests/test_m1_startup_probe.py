"""Tests for the M1 startup-AC probe (D-20).

Covers the probe module itself (via ``m1_startup_probe._run`` mocking)
and the audit-phase integration (``_maybe_run_m1_startup_probe``).

All subprocess invocations are mocked — no real ``npm``, ``docker``,
or ``npx`` commands run in this test module. The production probe
executes real subprocesses at pipeline runtime; that path is covered
by Session 6's Gate A smoke, not unit tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15 import m1_startup_probe
from agent_team_v15.audit_models import (
    AuditFinding,
    AuditReport,
    build_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pass_result(exit_code: int = 0) -> dict:
    return {
        "status": "pass" if exit_code == 0 else "fail",
        "exit_code": exit_code,
        "stdout_tail": "",
        "stderr_tail": "",
        "duration_s": 0.1,
    }


def _fail_result(exit_code: int = 1) -> dict:
    return {
        "status": "fail",
        "exit_code": exit_code,
        "stdout_tail": "",
        "stderr_tail": "boom",
        "duration_s": 0.1,
    }


def _timeout_result() -> dict:
    return {
        "status": "timeout",
        "exit_code": -1,
        "stdout_tail": "",
        "stderr_tail": "",
        "duration_s": 300.0,
    }


def _empty_report() -> AuditReport:
    """Build a minimal AuditReport through the canonical path."""
    findings: list[AuditFinding] = []
    return build_report("audit-test-1", 1, ["requirements"], findings)


def _write_master_plan(
    agent_team_dir: Path,
    milestone_id: str,
    entity_count: int,
    template: str = "full_stack",
) -> None:
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema_version": 1,
        "milestones": [
            {
                "id": milestone_id,
                "title": "test",
                "template": template,
                "complexity_estimate": {"entity_count": entity_count},
            }
        ],
    }
    (agent_team_dir / "MASTER_PLAN.json").write_text(
        json.dumps(plan), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Probe unit tests (plan §4, 5 tests)
# ---------------------------------------------------------------------------

class TestRunM1StartupProbe:

    def test_happy_path_all_probes_pass(self, tmp_path):
        """Plan §4 test 1: all 5 probes return exit 0; acceptance_tests
        has 5 entries all status=pass (plus compose_down teardown)."""
        workspace = tmp_path / "project"
        workspace.mkdir()

        with patch.object(
            m1_startup_probe, "_run", return_value=_pass_result(0)
        ) as mock_run, patch.object(
            m1_startup_probe,
            "_compose_command",
            return_value=["docker", "compose"],
        ):
            results = m1_startup_probe.run_m1_startup_probe(workspace)

        expected_probes = {
            "npm_install",
            "compose_up",
            "prisma_migrate",
            "test_api",
            "test_web",
            "compose_down",
        }
        assert set(results.keys()) == expected_probes
        for key in ("npm_install", "compose_up", "prisma_migrate",
                    "test_api", "test_web"):
            assert results[key]["status"] == "pass", key
        # _run called at least 6 times (5 probes + teardown).
        assert mock_run.call_count >= 6

    def test_pnpm_workspace_uses_pnpm_commands(self, tmp_path):
        """M1 scaffolded workspaces declare pnpm and must not be probed with npm."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        (workspace / "package.json").write_text(
            json.dumps({"packageManager": "pnpm@10.17.1"}),
            encoding="utf-8",
        )
        (workspace / "pnpm-workspace.yaml").write_text(
            "packages:\n  - 'apps/*'\n  - 'packages/*'\n",
            encoding="utf-8",
        )

        calls: list[tuple[list[str], Path]] = []

        def _fake_run(cmd, **kwargs):
            calls.append((list(cmd), Path(kwargs["cwd"])))
            return _pass_result(0)

        with patch.object(m1_startup_probe, "_run", side_effect=_fake_run), \
             patch.object(
                 m1_startup_probe,
                 "_compose_command",
                 return_value=["docker", "compose"],
             ):
            results = m1_startup_probe.run_m1_startup_probe(workspace)

        assert results["npm_install"]["status"] == "pass"
        commands = [cmd for cmd, _cwd in calls]
        assert ["pnpm", "install", "--frozen-lockfile"] in commands
        assert [
            "pnpm",
            "--filter",
            "api",
            "exec",
            "prisma",
            "migrate",
            "dev",
            "--name",
            "init",
        ] in commands
        assert ["pnpm", "run", "test:api"] in commands
        assert ["pnpm", "run", "test:web"] in commands
        assert not any(cmd[0] in {"npm", "npx"} for cmd in commands)

    def test_npm_install_fail_flips_verdict_to_fail(self, tmp_path):
        """Plan §4 test 2: mock npm install exit 1; integration layer
        flips AuditReport.extras['verdict'] to FAIL regardless of
        finding count."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        agent_team_dir = workspace / ".agent-team"
        _write_master_plan(agent_team_dir, "milestone-1", entity_count=0)

        # npm_install fails, everything else would pass but verdict
        # must flip to FAIL regardless.
        call_outcomes = iter([
            _fail_result(1),   # npm_install
            _pass_result(0),   # compose_up
            _pass_result(0),   # prisma_migrate
            _pass_result(0),   # test_api
            _pass_result(0),   # test_web
            _pass_result(0),   # compose_down
        ])

        def _fake_run(*args, **kwargs):
            return next(call_outcomes)

        # Minimal config stub — only ``config.v18.m1_startup_probe`` is
        # consulted; _maybe_run_m1_startup_probe only reads that flag.
        class _V18: m1_startup_probe = True
        class _Cfg: v18 = _V18()

        from agent_team_v15.cli import _maybe_run_m1_startup_probe

        report = _empty_report()
        with patch.object(m1_startup_probe, "_run", side_effect=_fake_run), \
             patch.object(m1_startup_probe, "_compose_command",
                          return_value=["docker", "compose"]):
            updated = _maybe_run_m1_startup_probe(
                report,
                milestone_id="milestone-1",
                milestone_template="full_stack",
                audit_dir=str(agent_team_dir),
                config=_Cfg(),
            )

        assert "m1_startup_probe" in updated.acceptance_tests
        assert updated.acceptance_tests["m1_startup_probe"]["npm_install"]["status"] == "fail"
        assert updated.extras.get("verdict") == "FAIL"

    def test_non_infrastructure_milestone_skipped(self, tmp_path):
        """Plan §4 test 3: non-infra milestone (entity_count>0) skipped;
        acceptance_tests stays empty and probe module is never called."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        agent_team_dir = workspace / ".agent-team"
        _write_master_plan(agent_team_dir, "milestone-3", entity_count=2)

        class _V18: m1_startup_probe = True
        class _Cfg: v18 = _V18()

        from agent_team_v15.cli import _maybe_run_m1_startup_probe

        report = _empty_report()
        with patch.object(
            m1_startup_probe, "run_m1_startup_probe"
        ) as mock_probe:
            updated = _maybe_run_m1_startup_probe(
                report,
                milestone_id="milestone-3",
                milestone_template="full_stack",
                audit_dir=str(agent_team_dir),
                config=_Cfg(),
            )

        assert updated.acceptance_tests == {}
        mock_probe.assert_not_called()

    def test_timeout_recorded_without_crashing(self, tmp_path):
        """Plan §4 test 4: subprocess.TimeoutExpired is caught by _run
        and surfaces as status='timeout'; pipeline continues."""
        workspace = tmp_path / "project"
        workspace.mkdir()

        import subprocess as _subprocess

        def _raise_timeout(*args, **kwargs):
            raise _subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        # Call the real _run through a mocked subprocess.run to prove the
        # exception handling path works end-to-end (including the tail
        # capture from TimeoutExpired).
        with patch("agent_team_v15.m1_startup_probe.subprocess.run",
                   side_effect=_raise_timeout), \
             patch.object(m1_startup_probe, "_compose_command",
                          return_value=["docker", "compose"]):
            results = m1_startup_probe.run_m1_startup_probe(workspace)

        # npm_install is the first probe; it should surface as timeout.
        assert results["npm_install"]["status"] == "timeout"
        # Pipeline continues — compose_down still recorded (teardown).
        assert "compose_down" in results
        assert results["compose_down"]["status"] == "timeout"

    def test_teardown_runs_even_when_probe_raises_midway(self, tmp_path):
        """Plan §4 test 5: if an earlier probe raises an unexpected
        exception, the finally block still invokes compose_down."""
        workspace = tmp_path / "project"
        workspace.mkdir()

        calls: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:3] == ["docker", "compose", "up"]:
                raise RuntimeError("compose_up exploded")
            return _pass_result(0)

        with patch.object(m1_startup_probe, "_run", side_effect=_fake_run), \
             patch.object(m1_startup_probe, "_compose_command",
                          return_value=["docker", "compose"]):
            with pytest.raises(RuntimeError, match="compose_up exploded"):
                m1_startup_probe.run_m1_startup_probe(workspace)

        # npm_install called, compose_up called (raised), compose_down
        # called despite the raise.
        cmds_flat = [" ".join(c) for c in calls]
        assert any(c.startswith("npm install") for c in cmds_flat)
        assert any(c.startswith("docker compose up") for c in cmds_flat)
        assert any(c.startswith("docker compose down") for c in cmds_flat)
