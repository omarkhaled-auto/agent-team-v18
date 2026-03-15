"""Tests for runtime verification (v16.5)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_team_v15.runtime_verification import (
    RuntimeReport,
    BuildResult,
    ServiceStatus,
    FixAttempt,
    FixTracker,
    check_docker_available,
    find_compose_file,
    docker_build,
    docker_start,
    run_migrations,
    smoke_test,
    run_runtime_verification,
    format_runtime_report,
    build_fix_prompt,
    _extract_service_error,
    _check_container_health,
)
from agent_team_v15.config import AgentTeamConfig, RuntimeVerificationConfig


# ===================================================================
# Config
# ===================================================================

class TestRuntimeVerificationConfig:
    def test_default_enabled(self):
        cfg = AgentTeamConfig()
        assert cfg.runtime_verification.enabled is True

    def test_default_values(self):
        rv = RuntimeVerificationConfig()
        assert rv.docker_build is True
        assert rv.docker_start is True
        assert rv.database_init is True
        assert rv.smoke_test is True
        assert rv.cleanup_after is False
        assert rv.max_build_fix_rounds == 2
        assert rv.startup_timeout_s == 90

    def test_config_from_yaml(self):
        from agent_team_v15.config import _dict_to_config
        cfg, _ = _dict_to_config({"runtime_verification": {"enabled": True, "cleanup_after": True}})
        assert cfg.runtime_verification.enabled is True
        assert cfg.runtime_verification.cleanup_after is True
        assert cfg.runtime_verification.docker_build is True  # default preserved

    def test_stays_enabled_at_thorough_prd_mode(self):
        from agent_team_v15.config import apply_depth_quality_gating
        cfg = AgentTeamConfig()
        assert cfg.runtime_verification.enabled is True
        apply_depth_quality_gating("thorough", cfg, prd_mode=True)
        assert cfg.runtime_verification.enabled is True

    def test_stays_enabled_at_exhaustive_prd_mode(self):
        from agent_team_v15.config import apply_depth_quality_gating
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("exhaustive", cfg, prd_mode=True)
        assert cfg.runtime_verification.enabled is True

    def test_stays_enabled_at_standard(self):
        """Standard depth keeps runtime verification enabled (default).
        The code gracefully skips if no compose file found."""
        from agent_team_v15.config import apply_depth_quality_gating
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("standard", cfg, prd_mode=True)
        assert cfg.runtime_verification.enabled is True

    def test_disabled_at_quick(self):
        from agent_team_v15.config import apply_depth_quality_gating
        cfg = AgentTeamConfig()
        apply_depth_quality_gating("quick", cfg, prd_mode=True)
        assert cfg.runtime_verification.enabled is False

    def test_user_override_respected(self):
        from agent_team_v15.config import apply_depth_quality_gating
        cfg = AgentTeamConfig()
        cfg.runtime_verification.enabled = False
        # User explicitly set it to false — depth gating should respect that
        apply_depth_quality_gating("exhaustive", cfg, prd_mode=True, user_overrides={"runtime_verification.enabled"})
        assert cfg.runtime_verification.enabled is False


# ===================================================================
# Docker availability
# ===================================================================

class TestCheckDockerAvailable:
    @patch("agent_team_v15.runtime_verification._run_cmd")
    def test_docker_available(self, mock_run):
        mock_run.return_value = (0, "Docker info output", "")
        assert check_docker_available() is True

    @patch("agent_team_v15.runtime_verification._run_cmd")
    def test_docker_not_available(self, mock_run):
        mock_run.return_value = (1, "", "Cannot connect to Docker daemon")
        assert check_docker_available() is False


# ===================================================================
# Find compose file
# ===================================================================

class TestFindComposeFile:
    def test_finds_docker_compose_yml(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
        result = find_compose_file(tmp_path)
        assert result is not None
        assert result.name == "docker-compose.yml"

    def test_finds_compose_yaml(self, tmp_path):
        (tmp_path / "compose.yaml").write_text("version: '3'\n")
        result = find_compose_file(tmp_path)
        assert result is not None
        assert result.name == "compose.yaml"

    def test_returns_none_when_missing(self, tmp_path):
        result = find_compose_file(tmp_path)
        assert result is None

    def test_override_path(self, tmp_path):
        custom = tmp_path / "custom-compose.yml"
        custom.write_text("version: '3'\n")
        result = find_compose_file(tmp_path, override=str(custom))
        assert result is not None
        assert result.name == "custom-compose.yml"


# ===================================================================
# Docker build
# ===================================================================

class TestDockerBuild:
    @patch("agent_team_v15.runtime_verification._run_docker")
    def test_successful_build(self, mock_run, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'\n")
        # First call: list services
        # Second call: build
        mock_run.side_effect = [
            (0, "auth\ngl\nar\n", ""),  # config --services
            (0, "", ""),  # build
        ]
        results = docker_build(tmp_path, compose)
        assert len(results) == 3
        assert all(r.success for r in results)

    @patch("agent_team_v15.runtime_verification._run_docker")
    def test_partial_build_failure(self, mock_run, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'\n")
        mock_run.side_effect = [
            (0, "auth\nasset\n", ""),
            (1, "", "target asset: failed to solve: npm run build error"),
        ]
        results = docker_build(tmp_path, compose)
        assert len(results) == 2
        auth_result = next(r for r in results if r.service == "auth")
        asset_result = next(r for r in results if r.service == "asset")
        assert auth_result.success is True
        assert asset_result.success is False
        assert "asset" in asset_result.error.lower()


# ===================================================================
# Service status
# ===================================================================

class TestCheckContainerHealth:
    @patch("agent_team_v15.runtime_verification._run_docker")
    def test_healthy_services(self, mock_run, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("")
        mock_run.return_value = (0, "auth\tUp 30s (healthy)\ngl\tUp 30s (healthy)\n", "")
        statuses = _check_container_health(tmp_path, compose)
        assert len(statuses) == 2
        assert all(s.healthy for s in statuses)

    @patch("agent_team_v15.runtime_verification._run_docker")
    def test_restarting_service(self, mock_run, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("")
        mock_run.return_value = (0, "auth\tUp 30s (healthy)\ntax\tRestarting (1) 5s ago\n", "")
        statuses = _check_container_health(tmp_path, compose)
        auth = next(s for s in statuses if s.service == "auth")
        tax = next(s for s in statuses if s.service == "tax")
        assert auth.healthy is True
        assert tax.healthy is False
        assert "restarting" in tax.error.lower()


# ===================================================================
# Migrations
# ===================================================================

class TestRunMigrations:
    def test_no_migration_dir(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("")
        success, error = run_migrations(tmp_path, compose)
        assert success is True
        assert error == ""

    def test_finds_migration_dir(self, tmp_path):
        mig_dir = tmp_path / "database" / "migrations"
        mig_dir.mkdir(parents=True)
        (mig_dir / "001_init.sql").write_text("CREATE TABLE test (id INT);")
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services:\n  postgres:\n    image: postgres\n")
        # Mock the docker exec call
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            success, error = run_migrations(tmp_path, compose, db_user="test", db_name="test")
            assert success is True


# ===================================================================
# Smoke test
# ===================================================================

class TestSmokeTest:
    @patch("subprocess.run")
    def test_smoke_test_healthy_service(self, mock_run, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("")
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"status":"ok"}', stderr="",
        )
        services = [
            ServiceStatus(service="auth", healthy=True),
            ServiceStatus(service="postgres", healthy=True),  # should be skipped
        ]
        results = smoke_test(tmp_path, compose, services)
        assert "auth" in results
        assert "postgres" not in results  # infrastructure excluded

    @patch("subprocess.run")
    def test_smoke_test_skip_unhealthy(self, mock_run, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("")
        services = [
            ServiceStatus(service="tax", healthy=False, error="restarting"),
        ]
        results = smoke_test(tmp_path, compose, services)
        assert "tax" not in results


# ===================================================================
# Extract service error
# ===================================================================

class TestExtractServiceError:
    def test_extracts_relevant_lines(self):
        stderr = "Building auth...\nDone.\ntarget asset: failed to solve\nTypeScript error\nDone."
        error = _extract_service_error(stderr, "asset")
        assert "asset" in error.lower()
        assert "failed" in error.lower()

    def test_fallback_on_no_match(self):
        stderr = "Some generic error"
        error = _extract_service_error(stderr, "unknown")
        assert len(error) > 0


# ===================================================================
# Report formatting
# ===================================================================

class TestFormatRuntimeReport:
    def test_docker_not_available(self):
        report = RuntimeReport(docker_available=False)
        text = format_runtime_report(report)
        assert "Docker not available" in text

    def test_no_compose_file(self):
        report = RuntimeReport(docker_available=True, compose_file="")
        text = format_runtime_report(report)
        assert "No docker-compose" in text

    def test_full_report(self):
        report = RuntimeReport(
            docker_available=True,
            compose_file="docker-compose.yml",
            build_results=[
                BuildResult(service="auth", success=True),
                BuildResult(service="asset", success=False, error="TS error"),
            ],
            services_healthy=3,
            services_total=5,
            services_status=[
                ServiceStatus(service="auth", healthy=True),
                ServiceStatus(service="gl", healthy=True),
                ServiceStatus(service="tax", healthy=False, error="crash"),
            ],
            migrations_run=True,
            smoke_results={"auth": {"health": True}, "gl": {"health": True}},
            total_duration_s=45.0,
        )
        text = format_runtime_report(report)
        assert "Docker Build: 1/2" in text
        assert "Services: 3/5" in text
        assert "Migrations: OK" in text
        assert "Smoke Test: 2/2" in text
        assert "45.0s" in text


# ===================================================================
# Full pipeline (mocked Docker)
# ===================================================================

class TestRunRuntimeVerification:
    @patch("agent_team_v15.runtime_verification.check_docker_available")
    def test_skips_when_docker_unavailable(self, mock_docker, tmp_path):
        mock_docker.return_value = False
        report = run_runtime_verification(tmp_path)
        assert report.docker_available is False
        assert report.build_results == []

    @patch("agent_team_v15.runtime_verification.check_docker_available")
    def test_skips_when_no_compose(self, mock_docker, tmp_path):
        mock_docker.return_value = True
        report = run_runtime_verification(tmp_path)
        assert report.compose_file == ""

    @patch("agent_team_v15.runtime_verification.check_docker_available")
    @patch("agent_team_v15.runtime_verification.docker_build")
    @patch("agent_team_v15.runtime_verification.docker_start")
    @patch("agent_team_v15.runtime_verification.run_migrations")
    @patch("agent_team_v15.runtime_verification.run_seed_scripts")
    @patch("agent_team_v15.runtime_verification.smoke_test")
    def test_full_pipeline(self, mock_smoke, mock_seed, mock_mig, mock_start, mock_build, mock_docker, tmp_path):
        mock_docker.return_value = True
        (tmp_path / "docker-compose.yml").write_text("version: '3'\n")

        mock_build.return_value = [BuildResult(service="auth", success=True)]
        mock_start.return_value = [ServiceStatus(service="auth", healthy=True)]
        mock_mig.return_value = (True, "")
        mock_seed.return_value = (True, "")
        mock_smoke.return_value = {"auth": {"health": True}}

        report = run_runtime_verification(tmp_path)
        assert report.docker_available is True
        assert len(report.build_results) == 1
        assert report.services_healthy == 1
        assert report.migrations_run is True
        assert "auth" in report.smoke_results


# ===================================================================
# Fix Tracker
# ===================================================================

class TestFixTracker:
    def test_initial_state(self):
        t = FixTracker(max_rounds_per_service=3, max_total_rounds=5, max_budget_usd=50.0)
        assert t.total_cost == 0.0
        assert t.budget_exceeded is False
        assert t.given_up_services == []

    def test_can_fix_initially(self):
        t = FixTracker()
        assert t.can_fix("auth") is True

    def test_cannot_fix_after_max_attempts(self):
        t = FixTracker(max_rounds_per_service=2)
        t.record_attempt("auth", "build", "error1", cost=5.0)
        assert t.can_fix("auth") is True
        t.record_attempt("auth", "build", "error2", cost=5.0)
        assert t.can_fix("auth") is False

    def test_budget_exceeded(self):
        t = FixTracker(max_budget_usd=10.0)
        t.record_attempt("auth", "build", "error", cost=11.0)
        assert t.budget_exceeded is True
        assert t.can_fix("gl") is False  # Budget exceeded for ALL services

    def test_repeat_error_detection(self):
        t = FixTracker()
        assert t.is_repeat_error("auth", "TypeError at line 5") is False  # First time
        assert t.is_repeat_error("auth", "TypeError at line 5") is True   # Same error

    def test_different_error_not_repeat(self):
        t = FixTracker()
        t.is_repeat_error("auth", "TypeError at line 5")
        assert t.is_repeat_error("auth", "ImportError: no module named X") is False

    def test_mark_given_up(self):
        t = FixTracker()
        t.mark_given_up("tax", "repeat error")
        assert "tax" in t.given_up_services
        assert t.can_fix("tax") is False

    def test_independent_service_tracking(self):
        t = FixTracker(max_rounds_per_service=2)
        t.record_attempt("auth", "build", "err", cost=5.0)
        t.record_attempt("auth", "build", "err", cost=5.0)
        assert t.can_fix("auth") is False
        assert t.can_fix("gl") is True  # Different service still fixable

    def test_total_rounds_exceeded(self):
        t = FixTracker(max_total_rounds=3, max_rounds_per_service=10)
        t.record_attempt("a", "build", "e1")
        t.record_attempt("b", "build", "e2")
        t.record_attempt("c", "build", "e3")
        assert t.total_rounds_exceeded is True

    def test_attempts_log(self):
        t = FixTracker()
        t.record_attempt("auth", "build", "TS error", cost=8.5)
        assert len(t.attempts_log) == 1
        assert t.attempts_log[0].service == "auth"
        assert t.attempts_log[0].phase == "build"
        assert t.attempts_log[0].cost_usd == 8.5


# ===================================================================
# Fix prompt generation
# ===================================================================

class TestBuildFixPrompt:
    def test_build_error_prompt(self):
        prompt = build_fix_prompt("asset", "build", "TS2769: No overload matches")
        assert "asset" in prompt
        assert "Docker Build Error" in prompt
        assert "TS2769" in prompt
        assert "Do NOT change the Dockerfile" in prompt

    def test_startup_error_prompt(self):
        prompt = build_fix_prompt("tax", "startup", "ModuleNotFoundError: globalbooks_common")
        assert "tax" in prompt
        assert "Startup Error" in prompt
        assert "globalbooks_common" in prompt


# ===================================================================
# Fix loop integration
# ===================================================================

class TestFixLoopConfig:
    def test_new_config_defaults(self):
        rv = RuntimeVerificationConfig()
        assert rv.fix_loop is True
        assert rv.max_fix_rounds_per_service == 3
        assert rv.max_total_fix_rounds == 5
        assert rv.max_fix_budget_usd == 75.0

    def test_yaml_config(self):
        from agent_team_v15.config import _dict_to_config
        cfg, _ = _dict_to_config({
            "runtime_verification": {
                "enabled": True,
                "fix_loop": True,
                "max_fix_rounds_per_service": 5,
                "max_fix_budget_usd": 100.0,
            }
        })
        assert cfg.runtime_verification.max_fix_rounds_per_service == 5
        assert cfg.runtime_verification.max_fix_budget_usd == 100.0


class TestFixLoopPipeline:
    @patch("agent_team_v15.runtime_verification.check_docker_available")
    @patch("agent_team_v15.runtime_verification.docker_build")
    @patch("agent_team_v15.runtime_verification.docker_start")
    @patch("agent_team_v15.runtime_verification.dispatch_fix_agent")
    @patch("agent_team_v15.runtime_verification.run_migrations")
    @patch("agent_team_v15.runtime_verification.run_seed_scripts")
    @patch("agent_team_v15.runtime_verification.smoke_test")
    @patch("agent_team_v15.runtime_verification._run_docker")
    def test_fix_loop_retries_failed_build(
        self, mock_docker_run, mock_smoke, mock_seed, mock_mig,
        mock_fix, mock_start, mock_build, mock_docker_avail, tmp_path
    ):
        """Build fails first time, fix agent runs, build succeeds second time."""
        mock_docker_avail.return_value = True
        (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
        mock_docker_run.return_value = (0, "", "")  # for docker down

        # Round 1: build fails for asset
        # Round 2: build succeeds
        mock_build.side_effect = [
            [BuildResult("auth", True), BuildResult("asset", False, error="TS error line 149")],
            [BuildResult("auth", True), BuildResult("asset", True)],
        ]
        mock_fix.return_value = 8.0  # Fix costs $8
        mock_start.return_value = [
            ServiceStatus("auth", True), ServiceStatus("asset", True),
        ]
        mock_mig.return_value = (True, "")
        mock_seed.return_value = (True, "")
        mock_smoke.return_value = {"auth": {"health": True}, "asset": {"health": True}}

        report = run_runtime_verification(
            tmp_path, fix_loop=True,
            max_fix_rounds_per_service=3, max_total_fix_rounds=5,
            max_fix_budget_usd=50.0,
        )
        assert report.services_healthy == 2
        assert len(report.fix_attempts) == 1
        assert report.fix_attempts[0].service == "asset"
        assert report.fix_cost_usd == 8.0

    @patch("agent_team_v15.runtime_verification.check_docker_available")
    @patch("agent_team_v15.runtime_verification.docker_build")
    @patch("agent_team_v15.runtime_verification.dispatch_fix_agent")
    @patch("agent_team_v15.runtime_verification._run_docker")
    def test_fix_loop_gives_up_after_max_attempts(
        self, mock_docker_run, mock_fix, mock_build, mock_docker_avail, tmp_path
    ):
        """Service fails repeatedly — given up after max_fix_rounds_per_service."""
        mock_docker_avail.return_value = True
        (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
        mock_docker_run.return_value = (0, "", "")

        # Always fails with different errors — provide enough for max rounds
        mock_build.side_effect = [
            [BuildResult("asset", False, error=f"Error round {i}")]
            for i in range(15)  # More than enough
        ]
        mock_fix.return_value = 5.0

        report = run_runtime_verification(
            tmp_path, fix_loop=True,
            max_fix_rounds_per_service=2, max_total_fix_rounds=10,
            max_fix_budget_usd=100.0,
            docker_start_enabled=False,
            database_init_enabled=False,
            smoke_test_enabled=False,
        )
        assert "asset" in report.services_given_up
        assert len(report.fix_attempts) == 2  # Stopped after 2

    @patch("agent_team_v15.runtime_verification.check_docker_available")
    @patch("agent_team_v15.runtime_verification.docker_build")
    @patch("agent_team_v15.runtime_verification.dispatch_fix_agent")
    @patch("agent_team_v15.runtime_verification._run_docker")
    def test_fix_loop_stops_on_budget(
        self, mock_docker_run, mock_fix, mock_build, mock_docker_avail, tmp_path
    ):
        """Budget cap stops fix loop."""
        mock_docker_avail.return_value = True
        (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
        mock_docker_run.return_value = (0, "", "")

        mock_build.return_value = [BuildResult("svc", False, error="err")]
        mock_fix.return_value = 30.0  # Each fix costs $30

        report = run_runtime_verification(
            tmp_path, fix_loop=True,
            max_fix_rounds_per_service=10, max_total_fix_rounds=10,
            max_fix_budget_usd=25.0,  # Budget is only $25
            docker_start_enabled=False,
            database_init_enabled=False,
            smoke_test_enabled=False,
        )
        assert report.budget_exceeded is True
        assert report.fix_cost_usd >= 25.0
        assert len(report.fix_attempts) == 1  # Only 1 attempt before budget exceeded

    @patch("agent_team_v15.runtime_verification.check_docker_available")
    @patch("agent_team_v15.runtime_verification.docker_build")
    @patch("agent_team_v15.runtime_verification.dispatch_fix_agent")
    @patch("agent_team_v15.runtime_verification._run_docker")
    def test_repeat_error_gives_up(
        self, mock_docker_run, mock_fix, mock_build, mock_docker_avail, tmp_path
    ):
        """Same error twice → service given up."""
        mock_docker_avail.return_value = True
        (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
        mock_docker_run.return_value = (0, "", "")

        # Same error every time — provide enough for the loop
        mock_build.side_effect = [
            [BuildResult("tax", False, error="IndentationError line 69")]
            for _ in range(15)
        ]
        mock_fix.return_value = 5.0

        report = run_runtime_verification(
            tmp_path, fix_loop=True,
            max_fix_rounds_per_service=5, max_total_fix_rounds=10,
            max_fix_budget_usd=100.0,
            docker_start_enabled=False,
            database_init_enabled=False,
            smoke_test_enabled=False,
        )
        assert "tax" in report.services_given_up
        # Only 1 fix attempt — second time detected as repeat and given up
        assert len(report.fix_attempts) == 1
