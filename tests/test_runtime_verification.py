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
    check_docker_available,
    find_compose_file,
    docker_build,
    docker_start,
    run_migrations,
    smoke_test,
    run_runtime_verification,
    format_runtime_report,
    _extract_service_error,
    _check_container_health,
)
from agent_team_v15.config import AgentTeamConfig, RuntimeVerificationConfig


# ===================================================================
# Config
# ===================================================================

class TestRuntimeVerificationConfig:
    def test_default_disabled(self):
        cfg = AgentTeamConfig()
        assert cfg.runtime_verification.enabled is False

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
