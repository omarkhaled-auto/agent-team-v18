"""Tests for the application lifecycle manager."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_team_v15.app_lifecycle import (
    AppInstance,
    AppLifecycleError,
    AppLifecycleManager,
    AuthSetup,
    BrowserTestUser,
    detect_stack,
)


# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------


class TestStackDetection:
    def test_nextjs(self, tmp_path):
        pkg = {"dependencies": {"next": "14.0.0", "react": "18.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert detect_stack(tmp_path) == "nextjs"

    def test_vite(self, tmp_path):
        pkg = {"devDependencies": {"vite": "5.0.0"}, "dependencies": {"react": "18.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert detect_stack(tmp_path) == "vite"

    def test_express(self, tmp_path):
        pkg = {"dependencies": {"express": "4.18.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert detect_stack(tmp_path) == "express"

    def test_unknown_no_file(self, tmp_path):
        assert detect_stack(tmp_path) == "unknown"

    def test_unknown_empty_deps(self, tmp_path):
        pkg = {"dependencies": {}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert detect_stack(tmp_path) == "unknown"

    def test_nextjs_takes_precedence_over_express(self, tmp_path):
        pkg = {"dependencies": {"next": "14.0.0", "express": "4.18.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert detect_stack(tmp_path) == "nextjs"


# ---------------------------------------------------------------------------
# AppLifecycleManager
# ---------------------------------------------------------------------------


class TestAppLifecycleManager:
    def test_init(self, tmp_path):
        mgr = AppLifecycleManager(cwd=tmp_path, port=3080)
        assert mgr.cwd == tmp_path
        assert mgr.port == 3080
        assert mgr.instance is None

    def test_stop_when_no_instance(self, tmp_path):
        mgr = AppLifecycleManager(cwd=tmp_path)
        mgr.stop()  # Should not raise

    def test_get_database_url_from_env(self, tmp_path):
        env_content = 'DATABASE_URL="postgresql://user:pass@localhost:5432/testdb"\n'
        (tmp_path / ".env").write_text(env_content)
        mgr = AppLifecycleManager(cwd=tmp_path)
        url = mgr._get_database_url()
        assert "postgresql" in url
        assert "testdb" in url

    def test_get_database_url_default(self, tmp_path):
        mgr = AppLifecycleManager(cwd=tmp_path)
        url = mgr._get_database_url()
        assert "postgresql" in url

    @patch("agent_team_v15.app_lifecycle.subprocess.run")
    def test_docker_skipped_when_no_compose(self, mock_run, tmp_path):
        mgr = AppLifecycleManager(cwd=tmp_path)
        mgr.instance = AppInstance(cwd=tmp_path, port=3080)
        mgr._start_docker_if_needed()
        # subprocess.run should NOT be called (no compose file)
        mock_run.assert_not_called()
        assert not mgr.instance.docker_running

    @patch("agent_team_v15.app_lifecycle.subprocess.run")
    def test_migrations_skipped_when_no_prisma(self, mock_run, tmp_path):
        mgr = AppLifecycleManager(cwd=tmp_path)
        mgr.instance = AppInstance(cwd=tmp_path, port=3080)
        mgr._run_migrations()
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# TestAuthSetup
# ---------------------------------------------------------------------------


class TestAuthSetupClass:
    def test_init(self, tmp_path):
        setup = AuthSetup(cwd=tmp_path, database_url="postgresql://test")
        assert setup.database_url == "postgresql://test"

    def test_reads_database_url_from_env(self, tmp_path):
        (tmp_path / ".env").write_text('DATABASE_URL="postgresql://from-env"\n')
        setup = AuthSetup(cwd=tmp_path)
        assert "from-env" in setup.database_url

    def test_session_script_is_valid_js(self):
        setup = AuthSetup(cwd=Path("."))
        script = setup.create_test_session_script()
        assert "PrismaClient" in script
        assert "JSON.stringify" in script
        assert "browser-test@agent-team.local" in script

    @patch("agent_team_v15.app_lifecycle.subprocess.run")
    def test_create_session_returns_user(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"user_id": "123", "email": "test@test.com", "token": "abc123"}\n',
            stderr="",
        )
        setup = AuthSetup(cwd=tmp_path, database_url="postgresql://test")
        user = setup.create_test_session()
        assert user is not None
        assert user.customer_id == "123"
        assert user.email == "test@test.com"
        assert user.token == "abc123"

    @patch("agent_team_v15.app_lifecycle.subprocess.run")
    def test_create_session_handles_error(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: cannot find module",
        )
        setup = AuthSetup(cwd=tmp_path, database_url="postgresql://test")
        user = setup.create_test_session()
        assert user is None

    @patch("agent_team_v15.app_lifecycle.subprocess.run")
    def test_create_session_handles_json_error(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"error": "No compatible user model found"}\n',
            stderr="",
        )
        setup = AuthSetup(cwd=tmp_path, database_url="postgresql://test")
        user = setup.create_test_session()
        assert user is None

    def test_get_seed_credentials(self, tmp_path):
        # Create a mock seed file
        seed_dir = tmp_path / "prisma"
        seed_dir.mkdir()
        seed_file = seed_dir / "seed.ts"
        seed_file.write_text(
            'const admin = {\n'
            '  email: "admin@example.com",\n'
            '  password: "Admin123!",\n'
            '  role: "admin",\n'
            '};\n'
        )
        setup = AuthSetup(cwd=tmp_path)
        creds = setup.get_seed_credentials()
        assert "admin" in creds
        assert creds["admin"]["email"] == "admin@example.com"
