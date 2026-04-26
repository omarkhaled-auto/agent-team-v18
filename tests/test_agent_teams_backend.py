"""Tests for agent_team.agent_teams_backend module.

Covers the ExecutionBackend protocol, CLIBackend, AgentTeamsBackend,
the create_execution_backend factory, detect_agent_teams_available,
and all supporting dataclasses (TaskResult, WaveResult, TeamState).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.agent_teams_backend import (
    AgentTeamsBackend,
    CLIBackend,
    ExecutionBackend,
    TaskResult,
    TeamState,
    WaveResult,
    create_execution_backend,
    detect_agent_teams_available,
)
from agent_team_v15.config import AgentTeamConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockWave:
    """Minimal mock that satisfies the ExecutionWave interface used by backends."""

    def __init__(self, wave_number: int = 0, task_ids: list[str] | None = None):
        self.wave_number = wave_number
        self.task_ids = task_ids or []


@pytest.fixture
def config() -> AgentTeamConfig:
    return AgentTeamConfig()


# ---------------------------------------------------------------------------
# Dataclass field tests
# ---------------------------------------------------------------------------

class TestTaskResult:
    """Verify TaskResult dataclass fields and defaults."""

    def test_fields_present(self):
        tr = TaskResult(
            task_id="t1",
            status="completed",
            output="ok",
            error="",
            files_created=["a.py"],
            files_modified=["b.py"],
        )
        assert tr.task_id == "t1"
        assert tr.status == "completed"
        assert tr.output == "ok"
        assert tr.error == ""
        assert tr.files_created == ["a.py"]
        assert tr.files_modified == ["b.py"]
        assert tr.duration_seconds == 0.0

    def test_duration_default(self):
        tr = TaskResult("x", "failed", "", "err", [], [])
        assert tr.duration_seconds == 0.0

    def test_duration_custom(self):
        tr = TaskResult("x", "completed", "", "", [], [], duration_seconds=5.5)
        assert tr.duration_seconds == 5.5


class TestWaveResult:
    """Verify WaveResult dataclass fields and defaults."""

    def test_fields_present(self):
        wr = WaveResult(wave_index=2, task_results=[], all_succeeded=True)
        assert wr.wave_index == 2
        assert wr.task_results == []
        assert wr.all_succeeded is True
        assert wr.duration_seconds == 0.0

    def test_all_succeeded_true(self):
        results = [
            TaskResult("a", "completed", "", "", [], []),
            TaskResult("b", "completed", "", "", [], []),
        ]
        wr = WaveResult(wave_index=0, task_results=results, all_succeeded=True)
        assert wr.all_succeeded is True

    def test_all_succeeded_false_when_failure(self):
        results = [
            TaskResult("a", "completed", "", "", [], []),
            TaskResult("b", "failed", "", "oops", [], []),
        ]
        wr = WaveResult(wave_index=0, task_results=results, all_succeeded=False)
        assert wr.all_succeeded is False


class TestTeamState:
    """Verify TeamState dataclass fields and defaults."""

    def test_fields_present(self):
        ts = TeamState(
            mode="cli",
            active=True,
            teammates=["alice"],
            completed_tasks=["t1"],
            failed_tasks=[],
        )
        assert ts.mode == "cli"
        assert ts.active is True
        assert ts.teammates == ["alice"]
        assert ts.completed_tasks == ["t1"]
        assert ts.failed_tasks == []
        assert ts.total_messages == 0

    def test_total_messages_default(self):
        ts = TeamState("agent_teams", False, [], [], [])
        assert ts.total_messages == 0


# ---------------------------------------------------------------------------
# ExecutionBackend protocol tests
# ---------------------------------------------------------------------------

class TestExecutionBackendProtocol:
    """Verify the protocol is runtime_checkable and both backends satisfy it."""

    def test_protocol_is_runtime_checkable(self):
        # ExecutionBackend should be usable with isinstance at runtime
        assert isinstance(CLIBackend(AgentTeamConfig()), ExecutionBackend)

    def test_cli_backend_satisfies_protocol(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        assert isinstance(backend, ExecutionBackend)

    def test_agent_teams_backend_satisfies_protocol(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        assert isinstance(backend, ExecutionBackend)


# ---------------------------------------------------------------------------
# CLIBackend tests
# ---------------------------------------------------------------------------

class TestCLIBackend:
    """Tests for CLIBackend (Mode B)."""

    def test_supports_peer_messaging_returns_false(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        assert backend.supports_peer_messaging() is False

    def test_supports_self_claiming_returns_false(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        assert backend.supports_self_claiming() is False

    def test_initialize_returns_team_state_with_cli_mode(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        state = asyncio.run(backend.initialize())
        assert isinstance(state, TeamState)
        assert state.mode == "cli"
        assert state.active is True
        assert state.teammates == []

    def test_send_context_returns_true(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        result = asyncio.run(backend.send_context("some context"))
        assert result is True

    def test_shutdown_sets_state_inactive(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        asyncio.run(backend.initialize())
        assert backend._state.active is True
        asyncio.run(backend.shutdown())
        assert backend._state.active is False

    def test_execute_wave_returns_wave_result(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        asyncio.run(backend.initialize())
        wave = MockWave(wave_number=1, task_ids=["task-a", "task-b"])
        result = asyncio.run(backend.execute_wave(wave))
        assert isinstance(result, WaveResult)
        assert result.wave_index == 1
        assert len(result.task_results) == 2
        assert result.all_succeeded is True
        for tr in result.task_results:
            assert tr.status == "completed"

    def test_execute_wave_tracks_completed_tasks(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        asyncio.run(backend.initialize())
        wave = MockWave(wave_number=0, task_ids=["t1", "t2", "t3"])
        asyncio.run(backend.execute_wave(wave))
        assert backend._state.completed_tasks == ["t1", "t2", "t3"]

    def test_execute_wave_empty_tasks(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        asyncio.run(backend.initialize())
        wave = MockWave(wave_number=0, task_ids=[])
        result = asyncio.run(backend.execute_wave(wave))
        assert isinstance(result, WaveResult)
        assert result.task_results == []
        assert result.all_succeeded is True

    def test_execute_task_returns_task_result(self, config: AgentTeamConfig):
        backend = CLIBackend(config)
        mock_task = MagicMock()
        mock_task.id = "single-task"
        result = asyncio.run(backend.execute_task(mock_task))
        assert isinstance(result, TaskResult)
        assert result.task_id == "single-task"
        assert result.status == "completed"

    def test_execute_task_uses_str_fallback(self, config: AgentTeamConfig):
        """When task has no 'id' attribute, str(task) is used."""
        backend = CLIBackend(config)
        result = asyncio.run(backend.execute_task("raw-string-task"))
        assert result.task_id == "raw-string-task"


# ---------------------------------------------------------------------------
# AgentTeamsBackend tests
# ---------------------------------------------------------------------------

class TestAgentTeamsBackend:
    """Tests for AgentTeamsBackend (Mode A)."""

    def test_supports_peer_messaging_returns_true(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        assert backend.supports_peer_messaging() is True

    def test_wave_letter_from_task_id_extracts_single_letter(self):
        assert AgentTeamsBackend._wave_letter_from_task_id("wave-D-milestone-1") == "D"

    def test_wave_letter_from_task_id_extracts_letter_with_digit(self):
        # A5 / D5 / T5 are valid wave names in this system.
        assert AgentTeamsBackend._wave_letter_from_task_id("wave-A5-milestone-2") == "A5"
        assert AgentTeamsBackend._wave_letter_from_task_id("wave-T5-milestone-1") == "T5"

    def test_wave_letter_from_task_id_returns_empty_for_non_wave(self):
        assert AgentTeamsBackend._wave_letter_from_task_id("phase-lead-architect") == ""
        assert AgentTeamsBackend._wave_letter_from_task_id("") == ""
        assert AgentTeamsBackend._wave_letter_from_task_id("free-form-task") == ""

    def test_build_teammate_env_sets_wave_letter_for_wave_d(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        env = backend._build_teammate_env(task_id="wave-D-milestone-1", cwd="C:/run")
        assert env["AGENT_TEAM_WAVE_LETTER"] == "D"
        assert env["AGENT_TEAM_PROJECT_DIR"] == "C:/run"

    def test_build_teammate_env_omits_wave_letter_for_phase_leads(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        env = backend._build_teammate_env()
        assert "AGENT_TEAM_WAVE_LETTER" not in env

    def test_ensure_wave_d_path_guard_settings_creates_settings(self, tmp_path):
        AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.is_file()
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        pre = data["PreToolUse"]
        assert isinstance(pre, list) and len(pre) == 1
        entry = pre[0]
        assert entry["matcher"] == "Write|Edit|MultiEdit|NotebookEdit"
        assert entry["agent_team_v15_wave_d_path_guard"] is True
        hooks = entry["hooks"]
        assert len(hooks) == 1
        assert hooks[0]["type"] == "command"
        assert "wave_d_path_guard" in hooks[0]["command"]

    def test_ensure_wave_d_path_guard_settings_is_idempotent(self, tmp_path):
        AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
        AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
        data = json.loads(
            (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        # Marker entry must appear exactly once even after repeated calls.
        marker_count = sum(
            1
            for entry in data["PreToolUse"]
            if isinstance(entry, dict)
            and entry.get("agent_team_v15_wave_d_path_guard")
        )
        assert marker_count == 1

    def test_ensure_wave_d_path_guard_settings_preserves_unrelated_hooks(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        unrelated = {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo"}]}
            ],
            "SessionStart": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "noop"}]}
            ],
        }
        (claude_dir / "settings.json").write_text(
            json.dumps(unrelated), encoding="utf-8"
        )
        AgentTeamsBackend._ensure_wave_d_path_guard_settings(str(tmp_path))
        data = json.loads(
            (claude_dir / "settings.json").read_text(encoding="utf-8")
        )
        # The Bash hook entry survives.
        bash_present = any(
            isinstance(entry, dict) and entry.get("matcher") == "Bash"
            for entry in data["PreToolUse"]
        )
        assert bash_present
        # The Wave D guard entry was added.
        guard_present = any(
            isinstance(entry, dict)
            and entry.get("agent_team_v15_wave_d_path_guard")
            for entry in data["PreToolUse"]
        )
        assert guard_present
        # Unrelated event keys are preserved.
        assert "SessionStart" in data

    def test_supports_self_claiming_returns_true(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        assert backend.supports_self_claiming() is True

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_verify_claude_available_returns_false_when_not_found(self, _mock):
        assert AgentTeamsBackend._verify_claude_available() is False

    @patch(
        "subprocess.run",
        return_value=MagicMock(returncode=0),
    )
    def test_verify_claude_available_returns_true_when_success(self, _mock_run):
        assert AgentTeamsBackend._verify_claude_available() is True

    @patch(
        "subprocess.run",
        side_effect=FileNotFoundError("not found"),
    )
    def test_verify_claude_available_false_on_file_not_found(self, _mock_run):
        assert AgentTeamsBackend._verify_claude_available() is False

    @patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=10),
    )
    def test_verify_claude_available_false_on_timeout(self, _mock_run):
        assert AgentTeamsBackend._verify_claude_available() is False

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_initialize_sets_env_vars(self, _mock_verify, config: AgentTeamConfig, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL", raising=False)
        config.agent_teams.teammate_model = "sonnet"
        backend = AgentTeamsBackend(config)
        state = asyncio.run(backend.initialize())
        assert state.mode == "agent_teams"
        assert state.active is True
        import os
        assert os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS") == "1"
        assert os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL") == "sonnet"

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_initialize_raises_when_cli_unavailable(self, _mock_verify, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        with pytest.raises(RuntimeError, match="Claude CLI is not available"):
            asyncio.run(backend.initialize())

    def test_shutdown_sets_state_inactive(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        # Manually set active to simulate initialized state
        backend._state.active = True
        asyncio.run(backend.shutdown())
        assert backend._state.active is False
        assert backend._active_teammates == {}

    def test_shutdown_clears_active_teammates(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._active_teammates = {"worker-1": MagicMock(), "worker-2": MagicMock()}
        asyncio.run(backend.shutdown())
        assert len(backend._active_teammates) == 0

    def test_shutdown_noop_when_already_inactive(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        assert backend._state.active is False
        # Should not raise
        asyncio.run(backend.shutdown())
        assert backend._state.active is False

    def test_send_context_returns_false_when_not_active(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        assert backend._state.active is False
        result = asyncio.run(backend.send_context("hello"))
        assert result is False

    def test_send_context_returns_false_when_no_teammates(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._active_teammates = {}
        result = asyncio.run(backend.send_context("hello"))
        assert result is False

    def test_send_context_returns_true_with_active_teammates(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._active_teammates = {"worker-1": MagicMock()}
        result = asyncio.run(backend.send_context("hello"))
        assert result is True
        assert backend._state.total_messages == 1


# ---------------------------------------------------------------------------
# create_execution_backend factory tests
# ---------------------------------------------------------------------------

class TestCreateExecutionBackend:
    """Tests for the create_execution_backend factory function."""

    def test_returns_cli_when_disabled(self):
        """TEST-001: disabled config -> CLIBackend."""
        config = AgentTeamConfig()
        config.agent_teams.enabled = False
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

    def test_returns_cli_when_env_var_not_set(self, monkeypatch):
        """TEST-002: env var not set -> AgentTeamsBackend sets it internally."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = False
        with patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True):
            backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)
        assert os.environ["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_returns_agent_teams_when_all_conditions_met(self, _mock, monkeypatch):
        """TEST-003: enabled, env var set, CLI available -> AgentTeamsBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_fails_fast_on_cli_init_failure_even_when_fallback_true(self, _mock, monkeypatch):
        """TEST-004: CLI unavailable -> fail fast; no silent CLI fallback."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = True
        with pytest.raises(RuntimeError, match="claude CLI is not installed"):
            create_execution_backend(config)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_raises_when_fallback_disabled(self, _mock, monkeypatch):
        """TEST-005: CLI unavailable + fallback=False -> RuntimeError."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = False
        with pytest.raises(RuntimeError, match="claude CLI is not installed"):
            create_execution_backend(config)

    def test_returns_cli_when_env_var_wrong_value(self, monkeypatch):
        """Env var set to something other than '1' is corrected internally."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "yes")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = False
        with patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True):
            backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)
        assert os.environ["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_env_var_1_cli_missing_fallback_true_still_raises(self, _mock, monkeypatch):
        """Env var '1', CLI missing -> RuntimeError even when fallback=True."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = True
        with pytest.raises(RuntimeError):
            create_execution_backend(config)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_env_var_1_cli_missing_fallback_false_raises(self, _mock, monkeypatch):
        """Env var '1', CLI missing, fallback=False -> RuntimeError."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = False
        with pytest.raises(RuntimeError):
            create_execution_backend(config)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.platform.system", return_value="Windows")
    def test_fallback_on_windows_terminal_split_mode(self, _mock_plat, _mock_cli, monkeypatch):
        """Unsupported display mode raises instead of falling back silently."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.setenv("WT_SESSION", "some-session-id")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = True
        config.agent_teams.teammate_display_mode = "split"
        with pytest.raises(RuntimeError, match="display mode"):
            create_execution_backend(config)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.platform.system", return_value="Windows")
    def test_raises_on_windows_terminal_split_mode_no_fallback(self, _mock_plat, _mock_cli, monkeypatch):
        """Factory raises RuntimeError when split mode on Windows Terminal + no fallback."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.setenv("WT_SESSION", "some-session-id")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = False
        config.agent_teams.teammate_display_mode = "split"
        with pytest.raises(RuntimeError, match="display mode"):
            create_execution_backend(config)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.platform.system", return_value="Windows")
    def test_agent_teams_on_windows_terminal_in_process_mode(self, _mock_plat, _mock_cli, monkeypatch):
        """Factory returns AgentTeamsBackend when in-process mode on Windows Terminal."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.setenv("WT_SESSION", "some-session-id")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.teammate_display_mode = "in-process"
        backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)


class TestCreateExecutionBackendStrictGate:
    """Strict-mode gate at ``--depth exhaustive`` (Issue 4)."""

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_select_backend_enables_env_at_exhaustive_when_env_missing(self, _mock_cli, monkeypatch):
        """depth='exhaustive' + env unset -> AgentTeamsBackend with env set."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        assert config.agent_teams.require_experimental_flag_at_exhaustive is True
        backend = create_execution_backend(config, depth="exhaustive")
        assert isinstance(backend, AgentTeamsBackend)
        assert os.environ["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_select_backend_ignores_legacy_strict_flag_disabled(self, _mock_cli, monkeypatch):
        """Legacy strict flag no longer authorizes CLI fallback."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.require_experimental_flag_at_exhaustive = False
        backend = create_execution_backend(config, depth="exhaustive")
        assert isinstance(backend, AgentTeamsBackend)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_select_backend_uses_agent_teams_at_standard_depth(self, _mock_cli, monkeypatch):
        """depth='standard' + env unset -> AgentTeamsBackend."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        assert config.agent_teams.require_experimental_flag_at_exhaustive is True
        backend = create_execution_backend(config, depth="standard")
        assert isinstance(backend, AgentTeamsBackend)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_select_backend_returns_agent_teams_when_env_set(self, _mock_cli, monkeypatch):
        """env='1' + depth='exhaustive' -> AgentTeamsBackend (no raise)."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.teammate_display_mode = "in-process"
        backend = create_execution_backend(config, depth="exhaustive")
        assert isinstance(backend, AgentTeamsBackend)

    def test_select_backend_logs_info_on_selection(self, monkeypatch, caplog):
        """Top-of-function INFO log captures enabled flag, env flag, and depth."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = AgentTeamConfig()
        config.agent_teams.enabled = False
        with caplog.at_level(logging.INFO, logger="agent_team_v15.agent_teams_backend"):
            create_execution_backend(config, depth="standard")
        assert any(
            "select_backend: agent_teams.enabled=False" in rec.message
            and "depth=standard" in rec.message
            for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# detect_agent_teams_available tests
# ---------------------------------------------------------------------------

class TestDetectAgentTeamsAvailable:
    """Tests for the detect_agent_teams_available helper."""

    def test_returns_false_when_env_var_not_set(self, monkeypatch):
        """TEST-016: env var absent -> False."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        assert detect_agent_teams_available() is False

    def test_returns_false_when_env_var_wrong(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "0")
        assert detect_agent_teams_available() is False

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_returns_false_when_cli_unavailable(self, _mock, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        assert detect_agent_teams_available() is False

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.platform.system", return_value="Windows")
    def test_returns_false_on_windows_terminal_split_mode(self, _mock_plat, _mock_cli, monkeypatch):
        """Windows Terminal + split display mode -> unavailable."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.setenv("WT_SESSION", "some-session-id")
        assert detect_agent_teams_available(display_mode="split") is False

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.platform.system", return_value="Windows")
    def test_returns_false_on_windows_terminal_tmux_mode(self, _mock_plat, _mock_cli, monkeypatch):
        """Windows Terminal + tmux display mode -> unavailable."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.setenv("WT_SESSION", "some-session-id")
        assert detect_agent_teams_available(display_mode="tmux") is False

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.platform.system", return_value="Windows")
    def test_returns_true_on_windows_terminal_in_process_mode(self, _mock_plat, _mock_cli, monkeypatch):
        """Windows Terminal + in-process display mode -> available (no split needed)."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.setenv("WT_SESSION", "some-session-id")
        assert detect_agent_teams_available(display_mode="in-process") is True

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.platform.system", return_value="Windows")
    def test_returns_true_on_windows_terminal_default_mode(self, _mock_plat, _mock_cli, monkeypatch):
        """Windows Terminal + default display mode (in-process) -> available."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.setenv("WT_SESSION", "some-session-id")
        assert detect_agent_teams_available() is True

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.platform.system", return_value="Linux")
    def test_returns_true_on_linux_with_all_conditions(self, _mock_plat, _mock_cli, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        assert detect_agent_teams_available() is True

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.platform.system", return_value="Windows")
    def test_returns_true_on_windows_without_wt_session(self, _mock_plat, _mock_cli, monkeypatch):
        """Windows but NOT Windows Terminal (no WT_SESSION) -> available."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.delenv("WT_SESSION", raising=False)
        assert detect_agent_teams_available() is True


# ---------------------------------------------------------------------------
# JSON output parsing tests
# ---------------------------------------------------------------------------

class TestParseClaudeJsonOutput:
    """Tests for AgentTeamsBackend._parse_claude_json_output."""

    def test_empty_string_returns_defaults(self):
        result = AgentTeamsBackend._parse_claude_json_output("")
        assert result["result"] == ""
        assert result["files_created"] == []
        assert result["files_modified"] == []
        assert result["error"] == ""

    def test_whitespace_only_returns_defaults(self):
        result = AgentTeamsBackend._parse_claude_json_output("   \n  ")
        assert result["result"] == ""

    def test_single_json_object_with_result(self):
        data = json.dumps({"result": "Task completed successfully"})
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["result"] == "Task completed successfully"

    def test_json_with_content_string(self):
        data = json.dumps({"content": "Hello from Claude"})
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["result"] == "Hello from Claude"

    def test_json_with_content_blocks(self):
        data = json.dumps({
            "content": [
                {"type": "text", "text": "First block"},
                {"type": "text", "text": "Second block"},
            ]
        })
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert "First block" in result["result"]
        assert "Second block" in result["result"]

    def test_json_with_message_field(self):
        data = json.dumps({"message": "Done"})
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["result"] == "Done"

    def test_json_with_files_created(self):
        data = json.dumps({
            "result": "ok",
            "files_created": ["src/main.py", "tests/test_main.py"],
        })
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["files_created"] == ["src/main.py", "tests/test_main.py"]

    def test_json_with_files_modified(self):
        data = json.dumps({
            "result": "ok",
            "files_modified": ["README.md"],
        })
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["files_modified"] == ["README.md"]

    def test_json_with_cost_usd(self):
        data = json.dumps({"result": "ok", "cost_usd": 0.05})
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["cost_usd"] == 0.05

    def test_json_with_total_cost_usd(self):
        data = json.dumps({"result": "ok", "total_cost_usd": 0.12})
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["cost_usd"] == 0.12

    def test_json_with_error_field(self):
        data = json.dumps({"error": "Something went wrong"})
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["error"] == "Something went wrong"

    def test_json_with_is_error_flag(self):
        data = json.dumps({"result": "error details", "is_error": True})
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["error"] == "error details"

    def test_jsonl_multi_line(self):
        """JSONL: parser uses the last valid JSON line."""
        lines = [
            json.dumps({"result": "partial"}),
            json.dumps({"result": "final answer", "files_created": ["out.py"]}),
        ]
        result = AgentTeamsBackend._parse_claude_json_output("\n".join(lines))
        assert result["result"] == "final answer"
        assert result["files_created"] == ["out.py"]

    def test_plain_text_fallback(self):
        """Non-JSON text is returned as the result."""
        result = AgentTeamsBackend._parse_claude_json_output("Just plain text output")
        assert result["result"] == "Just plain text output"

    def test_non_dict_json_value(self):
        """JSON array or primitive is stringified."""
        result = AgentTeamsBackend._parse_claude_json_output('"just a string"')
        assert result["result"] == "just a string"

    def test_invalid_cost_ignored(self):
        data = json.dumps({"result": "ok", "cost_usd": "not a number"})
        result = AgentTeamsBackend._parse_claude_json_output(data)
        assert result["cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# Command building tests
# ---------------------------------------------------------------------------

class TestBuildClaudeCmd:
    """Tests for AgentTeamsBackend._build_claude_cmd."""

    def test_basic_command_structure(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._claude_path = "/usr/bin/claude"
        cmd = backend._build_claude_cmd("TASK-001", "Do something")
        assert cmd[0] == "/usr/bin/claude"
        assert "--print" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd
        assert "-p" not in cmd
        assert "Do something" not in cmd

    def test_permission_mode_included(self, config: AgentTeamConfig):
        config.agent_teams.teammate_permission_mode = "bypassPermissions"
        backend = AgentTeamsBackend(config)
        backend._claude_path = "claude"
        cmd = backend._build_claude_cmd("TASK-001", "test")
        assert "--permission-mode" in cmd
        assert "bypassPermissions" in cmd

    def test_model_flag_included(self, config: AgentTeamConfig):
        config.agent_teams.teammate_model = "claude-sonnet-4-6"
        backend = AgentTeamsBackend(config)
        backend._claude_path = "claude"
        cmd = backend._build_claude_cmd("TASK-001", "test")
        assert "--model" in cmd
        assert "claude-sonnet-4-6" in cmd

    def test_add_dir_included_for_explicit_cwd(self, config: AgentTeamConfig, tmp_path: Path):
        backend = AgentTeamsBackend(config)
        backend._claude_path = "claude"
        cmd = backend._build_claude_cmd("TASK-001", "test", cwd=tmp_path)
        assert "--add-dir" in cmd
        assert str(tmp_path) in cmd

    def test_empty_permission_mode_excluded(self, config: AgentTeamConfig):
        config.agent_teams.teammate_permission_mode = ""
        backend = AgentTeamsBackend(config)
        backend._claude_path = "claude"
        cmd = backend._build_claude_cmd("TASK-001", "test")
        assert "--permission-mode" not in cmd

    def test_wave_prompt_is_not_embedded_in_argv(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._claude_path = "claude"
        long_prompt = "x" * 20000
        cmd = backend._build_claude_cmd("TASK-001", long_prompt)
        assert all(long_prompt not in part for part in cmd)


# ---------------------------------------------------------------------------
# Teammate environment tests
# ---------------------------------------------------------------------------

class TestBuildTeammateEnv:
    """Tests for AgentTeamsBackend._build_teammate_env."""

    def test_sets_experimental_flag(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        env = backend._build_teammate_env()
        assert env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"

    def test_sets_model_when_configured(self, config: AgentTeamConfig):
        config.agent_teams.teammate_model = "claude-sonnet-4-6"
        backend = AgentTeamsBackend(config)
        env = backend._build_teammate_env()
        assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "claude-sonnet-4-6"

    def test_no_model_when_empty(self, config: AgentTeamConfig, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL", raising=False)
        config.agent_teams.teammate_model = ""
        backend = AgentTeamsBackend(config)
        env = backend._build_teammate_env()
        assert "CLAUDE_CODE_SUBAGENT_MODEL" not in env

    def test_context_dir_in_env(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._context_dir = Path("/tmp/test/context")
        env = backend._build_teammate_env()
        assert env["AGENT_TEAMS_CONTEXT_DIR"] == str(Path("/tmp/test/context"))

    def test_output_dir_in_env(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._output_dir = Path("/tmp/test/output")
        env = backend._build_teammate_env()
        assert env["AGENT_TEAMS_OUTPUT_DIR"] == str(Path("/tmp/test/output"))


# ---------------------------------------------------------------------------
# Initialize tests (new features)
# ---------------------------------------------------------------------------

class TestAgentTeamsBackendInitialize:
    """Tests for AgentTeamsBackend.initialize new features."""

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.shutil.which", return_value="/usr/bin/claude")
    def test_initialize_resolves_claude_path(self, _mock_which, _mock_verify, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        asyncio.run(backend.initialize())
        assert backend._claude_path == "/usr/bin/claude"

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    @patch("agent_team_v15.agent_teams_backend.shutil.which", return_value=None)
    def test_initialize_falls_back_to_claude_when_which_fails(self, _mock_which, _mock_verify, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        asyncio.run(backend.initialize())
        assert backend._claude_path == "claude"

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_initialize_creates_context_dir(self, _mock_verify, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        asyncio.run(backend.initialize())
        assert backend._context_dir is not None
        assert backend._context_dir.is_dir()
        # Cleanup
        asyncio.run(backend.shutdown())

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_initialize_creates_output_dir(self, _mock_verify, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        asyncio.run(backend.initialize())
        assert backend._output_dir is not None
        assert backend._output_dir.is_dir()
        asyncio.run(backend.shutdown())


# ---------------------------------------------------------------------------
# Spawn teammate tests (mocked subprocess)
# ---------------------------------------------------------------------------

class TestSpawnTeammate:
    """Tests for AgentTeamsBackend._spawn_teammate with mocked subprocess."""

    @pytest.fixture
    def backend(self, config: AgentTeamConfig) -> AgentTeamsBackend:
        b = AgentTeamsBackend(config)
        b._claude_path = "claude"
        b._state.active = True
        b._context_dir = Path(tempfile.mkdtemp()) / "context"
        b._output_dir = Path(tempfile.mkdtemp()) / "output"
        b._context_dir.mkdir(parents=True, exist_ok=True)
        b._output_dir.mkdir(parents=True, exist_ok=True)
        return b

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_spawn_returns_completed_on_success(self, mock_exec, backend):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(
            json.dumps({"result": "Done", "files_created": ["new.py"]}).encode(),
            b"",
        ))
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result = asyncio.run(backend._spawn_teammate("TASK-001", "Do it", 60))
        assert result.status == "completed"
        assert result.task_id == "TASK-001"
        assert result.output == "Done"
        assert result.files_created == ["new.py"]
        assert mock_exec.call_args.kwargs["cwd"] is None
        assert mock_exec.call_args.kwargs["stdin"] == asyncio.subprocess.PIPE
        mock_proc.communicate.assert_awaited_once_with(input=b"Do it")

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_spawn_threads_explicit_cwd_to_subprocess(self, mock_exec, backend, tmp_path: Path):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b'{"result":"Done"}', b""))
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result = asyncio.run(backend._spawn_teammate("TASK-CWD", "Do it", 60, cwd=tmp_path))
        assert result.status == "completed"
        assert mock_exec.call_args.kwargs["cwd"] == str(tmp_path)

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_spawn_returns_failed_on_nonzero_exit(self, mock_exec, backend):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error occurred"))
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        result = asyncio.run(backend._spawn_teammate("TASK-002", "Do it", 60))
        assert result.status == "failed"
        assert "Error occurred" in result.error

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_spawn_returns_timeout_on_timeout(self, mock_exec, backend):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_proc.returncode = None
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_exec.return_value = mock_proc

        result = asyncio.run(backend._spawn_teammate("TASK-003", "Do it", 0.01))
        assert result.status == "timeout"
        assert "timed out" in result.error

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_spawn_registers_and_removes_teammate(self, mock_exec, backend):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        asyncio.run(backend._spawn_teammate("TASK-004", "Do it", 60))
        # After completion, teammate should be removed from active
        assert "teammate-TASK-004" not in backend._active_teammates

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat",
           side_effect=FileNotFoundError("not found"))
    def test_spawn_returns_failed_when_claude_not_found(self, _mock_exec, backend):
        result = asyncio.run(backend._spawn_teammate("TASK-005", "Do it", 60))
        assert result.status == "failed"
        assert "not found" in result.error.lower()

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat",
           side_effect=OSError("permission denied"))
    def test_spawn_returns_failed_on_os_error(self, _mock_exec, backend):
        result = asyncio.run(backend._spawn_teammate("TASK-006", "Do it", 60))
        assert result.status == "failed"
        assert "permission denied" in result.error.lower()

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_spawn_parses_partial_output_on_failure(self, mock_exec, backend):
        """Even on non-zero exit, parse any JSON output."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(
            json.dumps({"result": "partial work", "files_modified": ["a.py"]}).encode(),
            b"",
        ))
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        result = asyncio.run(backend._spawn_teammate("TASK-007", "Do it", 60))
        assert result.status == "failed"
        assert result.output == "partial work"
        assert result.files_modified == ["a.py"]


# ---------------------------------------------------------------------------
# Execute task tests
# ---------------------------------------------------------------------------

class TestAgentTeamsExecuteTask:
    """Tests for AgentTeamsBackend.execute_task."""

    @patch.object(AgentTeamsBackend, "_spawn_teammate")
    def test_execute_task_extracts_id(self, mock_spawn, config: AgentTeamConfig):
        mock_spawn.return_value = TaskResult(
            task_id="T-1", status="completed", output="ok",
            error="", files_created=[], files_modified=[], duration_seconds=1.0,
        )
        backend = AgentTeamsBackend(config)
        task = MagicMock()
        task.id = "T-1"
        task.description = "A task"
        task.title = "Test task"
        result = asyncio.run(backend.execute_task(task))
        assert result.task_id == "T-1"
        assert result.status == "completed"
        assert "T-1" in backend._state.completed_tasks


class TestAgentTeamsExecutePrompt:
    """Tests for full wave-prompt execution through Agent Teams."""

    @patch.object(AgentTeamsBackend, "_spawn_teammate")
    def test_execute_prompt_passes_full_prompt_and_cwd(self, mock_spawn, config: AgentTeamConfig, tmp_path: Path):
        mock_spawn.return_value = TaskResult(
            task_id="wave-B-M1",
            status="completed",
            output="done",
            error="",
            files_created=[],
            files_modified=[],
            duration_seconds=1.0,
        )
        backend = AgentTeamsBackend(config)
        result_cost = asyncio.run(
            backend.execute_prompt(
                prompt="FULL WAVE B PROMPT",
                cwd=tmp_path,
                wave="B",
                milestone=type("Milestone", (), {"id": "M1"})(),
            )
        )
        assert result_cost == 0.0
        args, kwargs = mock_spawn.call_args
        assert args[0] == "wave-B-M1"
        assert args[1] == "FULL WAVE B PROMPT"
        assert kwargs["cwd"] == tmp_path

    @patch.object(AgentTeamsBackend, "_spawn_teammate")
    def test_execute_task_tracks_failures(self, mock_spawn, config: AgentTeamConfig):
        mock_spawn.return_value = TaskResult(
            task_id="T-2", status="failed", output="",
            error="boom", files_created=[], files_modified=[], duration_seconds=1.0,
        )
        backend = AgentTeamsBackend(config)
        result = asyncio.run(backend.execute_task("T-2"))
        assert result.status == "failed"
        assert "T-2" in backend._state.failed_tasks

    @patch.object(AgentTeamsBackend, "_spawn_teammate")
    def test_execute_task_uses_str_fallback_for_id(self, mock_spawn, config: AgentTeamConfig):
        mock_spawn.return_value = TaskResult(
            task_id="raw-string", status="completed", output="",
            error="", files_created=[], files_modified=[], duration_seconds=0.5,
        )
        backend = AgentTeamsBackend(config)
        result = asyncio.run(backend.execute_task("raw-string"))
        assert result.task_id == "raw-string"


# ---------------------------------------------------------------------------
# Execute wave tests
# ---------------------------------------------------------------------------

class TestAgentTeamsExecuteWave:
    """Tests for AgentTeamsBackend.execute_wave with mocked teammates."""

    @patch.object(AgentTeamsBackend, "_spawn_teammate")
    def test_wave_collects_all_results(self, mock_spawn, config: AgentTeamConfig):
        async def fake_spawn(task_id, prompt, timeout):
            return TaskResult(
                task_id=task_id, status="completed", output=f"done-{task_id}",
                error="", files_created=[], files_modified=[], duration_seconds=0.1,
            )
        mock_spawn.side_effect = fake_spawn

        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._context_dir = None
        wave = MockWave(wave_number=1, task_ids=["A", "B", "C"])
        result = asyncio.run(backend.execute_wave(wave))
        assert isinstance(result, WaveResult)
        assert result.wave_index == 1
        assert len(result.task_results) == 3
        assert result.all_succeeded is True

    @patch.object(AgentTeamsBackend, "_spawn_teammate")
    def test_wave_marks_failures(self, mock_spawn, config: AgentTeamConfig):
        async def fake_spawn(task_id, prompt, timeout):
            if task_id == "B":
                return TaskResult(
                    task_id=task_id, status="failed", output="",
                    error="exploded", files_created=[], files_modified=[], duration_seconds=0.1,
                )
            return TaskResult(
                task_id=task_id, status="completed", output="ok",
                error="", files_created=[], files_modified=[], duration_seconds=0.1,
            )
        mock_spawn.side_effect = fake_spawn

        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._context_dir = None
        wave = MockWave(wave_number=0, task_ids=["A", "B"])
        result = asyncio.run(backend.execute_wave(wave))
        assert result.all_succeeded is False
        assert "B" in backend._state.failed_tasks
        assert "A" in backend._state.completed_tasks

    @patch.object(AgentTeamsBackend, "_spawn_teammate")
    def test_wave_empty_tasks(self, mock_spawn, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._context_dir = None
        wave = MockWave(wave_number=0, task_ids=[])
        result = asyncio.run(backend.execute_wave(wave))
        assert result.task_results == []
        assert result.all_succeeded is True

    @patch.object(AgentTeamsBackend, "_spawn_teammate")
    def test_wave_handles_exception_in_gather(self, mock_spawn, config: AgentTeamConfig):
        """When a task raises an exception, it's captured as a failed result."""
        call_count = 0
        async def fake_spawn(task_id, prompt, timeout):
            nonlocal call_count
            call_count += 1
            if task_id == "X":
                raise RuntimeError("unexpected crash")
            return TaskResult(
                task_id=task_id, status="completed", output="ok",
                error="", files_created=[], files_modified=[], duration_seconds=0.1,
            )
        mock_spawn.side_effect = fake_spawn

        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._context_dir = None
        wave = MockWave(wave_number=0, task_ids=["X", "Y"])
        result = asyncio.run(backend.execute_wave(wave))
        assert result.all_succeeded is False
        statuses = {r.task_id: r.status for r in result.task_results}
        assert statuses.get("X") == "failed" or "X" in backend._state.failed_tasks


# ---------------------------------------------------------------------------
# send_context tests (new implementation)
# ---------------------------------------------------------------------------

class TestSendContextNew:
    """Tests for the new file-based send_context."""

    def test_writes_context_file(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._context_dir = Path(tempfile.mkdtemp())
        mock_proc = MagicMock()
        mock_proc.returncode = None  # Still running
        backend._active_teammates = {"worker-1": mock_proc}

        result = asyncio.run(backend.send_context("shared info here"))
        assert result is True
        files = list(backend._context_dir.glob("context_*.md"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == "shared info here"

    def test_increments_total_messages(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._context_dir = Path(tempfile.mkdtemp())
        backend._active_teammates = {
            "w1": MagicMock(returncode=None),
            "w2": MagicMock(returncode=None),
        }

        asyncio.run(backend.send_context("ctx"))
        assert backend._state.total_messages == 2


# ---------------------------------------------------------------------------
# Shutdown tests (new implementation)
# ---------------------------------------------------------------------------

class TestShutdownNew:
    """Tests for the new process-killing shutdown."""

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_shutdown_cleans_up_temp_dirs(self, _mock_verify, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        asyncio.run(backend.initialize())
        assert backend._context_dir is not None
        context_parent = backend._context_dir.parent
        asyncio.run(backend.shutdown())
        assert backend._context_dir is None
        assert backend._output_dir is None

    def test_shutdown_clears_teammates_list(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._state.teammates = ["a", "b"]
        backend._active_teammates = {}
        asyncio.run(backend.shutdown())
        assert backend._state.teammates == []


# ---------------------------------------------------------------------------
# Teammate health check tests
# ---------------------------------------------------------------------------

class TestIsTeammateAlive:
    """Tests for AgentTeamsBackend._is_teammate_alive."""

    def test_alive_when_running(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        mock_proc = MagicMock()
        mock_proc.returncode = None
        backend._active_teammates["worker-1"] = mock_proc
        assert backend._is_teammate_alive("worker-1") is True

    def test_not_alive_when_exited(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        backend._active_teammates["worker-2"] = mock_proc
        assert backend._is_teammate_alive("worker-2") is False

    def test_not_alive_when_unknown(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        assert backend._is_teammate_alive("nonexistent") is False


# ---------------------------------------------------------------------------
# Resolve claude path tests
# ---------------------------------------------------------------------------

class TestResolveClaudePath:
    """Tests for AgentTeamsBackend._resolve_claude_path."""

    @patch("agent_team_v15.agent_teams_backend.shutil.which", return_value="/usr/local/bin/claude")
    def test_returns_which_result(self, _mock):
        assert AgentTeamsBackend._resolve_claude_path() == "/usr/local/bin/claude"

    @patch("agent_team_v15.agent_teams_backend.shutil.which", return_value=None)
    def test_falls_back_to_claude(self, _mock):
        assert AgentTeamsBackend._resolve_claude_path() == "claude"


# ---------------------------------------------------------------------------
# Phase lead config access tests
# ---------------------------------------------------------------------------

class TestGetPhaseLeadConfig:
    """Tests for AgentTeamsBackend._get_phase_lead_config."""

    def test_returns_wave_a_lead(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        cfg = backend._get_phase_lead_config("wave-a-lead")
        assert cfg is not None
        assert "Read" in cfg.tools

    def test_returns_wave_t_lead(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        cfg = backend._get_phase_lead_config("wave-t-lead")
        assert cfg is not None
        assert "Bash" in cfg.tools

    def test_returns_none_for_unknown(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        assert backend._get_phase_lead_config("unknown-lead") is None

    def test_all_wave_leads_have_config(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        for name in AgentTeamsBackend.PHASE_LEAD_NAMES:
            assert backend._get_phase_lead_config(name) is not None


# ---------------------------------------------------------------------------
# Phase lead command building tests
# ---------------------------------------------------------------------------

class TestBuildPhaseLeadCmd:
    """Tests for AgentTeamsBackend._build_phase_lead_cmd."""

    def test_basic_command(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._claude_path = "claude"
        cmd = backend._build_phase_lead_cmd("wave-a-lead", "You are the planning lead.")
        assert cmd[0] == "claude"
        assert "--print" in cmd
        assert "--output-format" in cmd
        assert "-p" in cmd
        assert "You are the planning lead." in cmd

    def test_uses_lead_specific_model(self, config: AgentTeamConfig):
        config.phase_leads.wave_a_lead.model = "claude-sonnet-4-6"
        backend = AgentTeamsBackend(config)
        backend._claude_path = "claude"
        cmd = backend._build_phase_lead_cmd("wave-a-lead", "test")
        assert "--model" in cmd
        assert "claude-sonnet-4-6" in cmd

    def test_falls_back_to_phase_lead_model(self, config: AgentTeamConfig):
        config.agent_teams.phase_lead_model = "opus"
        config.phase_leads.wave_e_lead.model = ""
        backend = AgentTeamsBackend(config)
        backend._claude_path = "claude"
        cmd = backend._build_phase_lead_cmd("wave-e-lead", "test")
        assert "--model" in cmd
        assert "opus" in cmd

    def test_no_model_flag_when_empty(self, config: AgentTeamConfig):
        config.agent_teams.phase_lead_model = ""
        config.phase_leads.wave_t_lead.model = ""
        backend = AgentTeamsBackend(config)
        backend._claude_path = "claude"
        cmd = backend._build_phase_lead_cmd("wave-t-lead", "test")
        assert "--model" not in cmd


# ---------------------------------------------------------------------------
# Spawn phase leads tests
# ---------------------------------------------------------------------------

class TestSpawnPhaseLeads:
    """Tests for AgentTeamsBackend.spawn_phase_leads."""

    def test_returns_false_when_not_active(self, config: AgentTeamConfig):
        config.phase_leads.enabled = True
        backend = AgentTeamsBackend(config)
        results = asyncio.run(backend.spawn_phase_leads())
        assert all(v is False for v in results.values())

    def test_returns_false_when_phase_leads_disabled(self, config: AgentTeamConfig):
        config.phase_leads.enabled = False
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        results = asyncio.run(backend.spawn_phase_leads())
        assert all(v is False for v in results.values())

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_spawns_all_wave_leads(self, mock_exec, config: AgentTeamConfig):
        config.phase_leads.enabled = True
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._claude_path = "claude"

        mock_proc = AsyncMock()
        mock_proc.pid = 12345
        mock_exec.return_value = mock_proc

        results = asyncio.run(backend.spawn_phase_leads())
        assert len(results) == 4
        assert all(v is True for v in results.values())
        assert len(backend._phase_leads) == 4
        assert set(backend._phase_leads.keys()) == set(AgentTeamsBackend.PHASE_LEAD_NAMES)

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_skips_disabled_lead(self, mock_exec, config: AgentTeamConfig):
        config.phase_leads.enabled = True
        config.phase_leads.wave_t_lead.enabled = False
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._claude_path = "claude"

        mock_proc = AsyncMock()
        mock_proc.pid = 111
        mock_exec.return_value = mock_proc

        results = asyncio.run(backend.spawn_phase_leads())
        assert results["wave-t-lead"] is False
        assert "wave-t-lead" not in backend._phase_leads
        assert results["wave-a-lead"] is True

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat",
           side_effect=FileNotFoundError("not found"))
    def test_handles_spawn_failure(self, _mock_exec, config: AgentTeamConfig):
        config.phase_leads.enabled = True
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._claude_path = "claude"

        results = asyncio.run(backend.spawn_phase_leads())
        assert all(v is False for v in results.values())
        assert len(backend._phase_leads) == 0

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_uses_custom_prompts(self, mock_exec, config: AgentTeamConfig):
        config.phase_leads.enabled = True
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._claude_path = "claude"

        mock_proc = AsyncMock()
        mock_proc.pid = 999
        mock_exec.return_value = mock_proc

        custom_prompts = {"wave-a-lead": "Custom planning prompt"}
        asyncio.run(backend.spawn_phase_leads(prompts=custom_prompts))

        # The first call should be for wave-a-lead with custom prompt
        first_call_args = mock_exec.call_args_list[0]
        cmd_args = first_call_args[0]  # positional args
        assert "Custom planning prompt" in cmd_args


# ---------------------------------------------------------------------------
# Respawn phase lead tests
# ---------------------------------------------------------------------------

class TestRespawnPhaseLead:
    """Tests for AgentTeamsBackend.respawn_phase_lead."""

    def test_rejects_unknown_lead(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        result = asyncio.run(backend.respawn_phase_lead("unknown-lead"))
        assert result is False

    @patch("agent_team_v15.agent_teams_backend.create_subprocess_exec_compat")
    def test_respawn_kills_old_and_spawns_new(self, mock_exec, config: AgentTeamConfig):
        config.phase_leads.enabled = True
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._claude_path = "claude"
        backend._state.teammates = ["wave-a-lead"]

        # Set up old process
        old_proc = AsyncMock()
        old_proc.returncode = None
        old_proc.terminate = MagicMock()
        old_proc.wait = AsyncMock(return_value=0)
        backend._phase_leads["wave-a-lead"] = old_proc

        # New process
        new_proc = AsyncMock()
        new_proc.pid = 777
        mock_exec.return_value = new_proc

        result = asyncio.run(backend.respawn_phase_lead("wave-a-lead"))
        assert result is True
        # Old proc should have been terminated
        old_proc.terminate.assert_called()


# ---------------------------------------------------------------------------
# Check phase lead health tests
# ---------------------------------------------------------------------------

class TestCheckPhaseLeadHealth:
    """Tests for AgentTeamsBackend.check_phase_lead_health."""

    def test_all_not_spawned(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        statuses = asyncio.run(backend.check_phase_lead_health())
        assert all(s == "not_spawned" for s in statuses.values())
        assert len(statuses) == 4

    def test_mix_of_statuses(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        running = MagicMock(returncode=None)
        exited = MagicMock(returncode=0)
        backend._phase_leads["wave-a-lead"] = running
        backend._phase_leads["wave-t-lead"] = exited

        statuses = asyncio.run(backend.check_phase_lead_health())
        assert statuses["wave-a-lead"] == "running"
        assert statuses["wave-t-lead"] == "exited"
        assert statuses["wave-d5-lead"] == "not_spawned"
        assert statuses["wave-e-lead"] == "not_spawned"


# ---------------------------------------------------------------------------
# Route message tests
# ---------------------------------------------------------------------------

class TestRouteMessage:
    """Tests for AgentTeamsBackend.route_message."""

    def test_returns_false_without_context_dir(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        result = asyncio.run(backend.route_message(
            "wave-a-lead", "WAVE_COMPLETE", "Wave 1 done",
        ))
        assert result is False

    def test_routes_message_to_single_recipient(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._context_dir = Path(tempfile.mkdtemp())

        result = asyncio.run(backend.route_message(
            "wave-e-lead", "WAVE_COMPLETE", "Wave 1 done", "wave-a-lead",
        ))
        assert result is True
        files = list(backend._context_dir.glob("msg_*_to_wave-e-lead.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "To: wave-e-lead" in content
        assert "From: wave-a-lead" in content
        assert "Type: WAVE_COMPLETE" in content
        assert "Wave 1 done" in content

    def test_broadcasts_to_all_leads(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._context_dir = Path(tempfile.mkdtemp())

        result = asyncio.run(backend.route_message(
            "*", "SYSTEM_STATE", "All phases PAUSE",
        ))
        assert result is True
        files = list(backend._context_dir.glob("msg_*.md"))
        assert len(files) == 4  # One file per lead

    def test_logs_message(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._context_dir = Path(tempfile.mkdtemp())

        asyncio.run(backend.route_message(
            "wave-d5-lead", "REQUIREMENTS_READY", "Done",
            "wave-a-lead",
        ))
        log = backend.get_message_log()
        assert len(log) == 1
        assert log[0]["from"] == "wave-a-lead"
        assert log[0]["to"] == "wave-d5-lead"
        assert log[0]["type"] == "REQUIREMENTS_READY"

    def test_increments_total_messages(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._context_dir = Path(tempfile.mkdtemp())

        asyncio.run(backend.route_message("wave-a-lead", "ARCHITECTURE_READY", "Go"))
        assert backend._state.total_messages == 1

    def test_unrecognized_type_still_delivers(self, config: AgentTeamConfig):
        """Unrecognized message types are warned about but still delivered."""
        backend = AgentTeamsBackend(config)
        backend._context_dir = Path(tempfile.mkdtemp())

        result = asyncio.run(backend.route_message(
            "wave-a-lead", "CUSTOM_TYPE", "body",
        ))
        assert result is True


# ---------------------------------------------------------------------------
# Is teammate alive with phase leads tests
# ---------------------------------------------------------------------------

class TestIsTeammateAliveWithPhaseLeads:
    """Verify _is_teammate_alive checks both dicts."""

    def test_checks_phase_leads_dict(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        mock_proc = MagicMock(returncode=None)
        backend._phase_leads["wave-a-lead"] = mock_proc
        assert backend._is_teammate_alive("wave-a-lead") is True

    def test_phase_lead_exited(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        mock_proc = MagicMock(returncode=1)
        backend._phase_leads["wave-a-lead"] = mock_proc
        assert backend._is_teammate_alive("wave-a-lead") is False


# ---------------------------------------------------------------------------
# Shutdown with phase leads tests
# ---------------------------------------------------------------------------

class TestShutdownWithPhaseLeads:
    """Verify shutdown kills both task teammates and phase leads."""

    def test_shutdown_clears_phase_leads(self, config: AgentTeamConfig):
        backend = AgentTeamsBackend(config)
        backend._state.active = True
        backend._phase_leads = {"wave-a-lead": MagicMock(returncode=0)}
        backend._message_log = [{"from": "a", "to": "b", "type": "X", "timestamp": "1"}]
        asyncio.run(backend.shutdown())
        assert len(backend._phase_leads) == 0
        assert len(backend._message_log) == 0
        assert backend._state.active is False


# ---------------------------------------------------------------------------
# Class-level constants tests
# ---------------------------------------------------------------------------

class TestClassConstants:
    """Verify class-level constants are correct."""

    def test_phase_lead_names(self):
        assert AgentTeamsBackend.PHASE_LEAD_NAMES == [
            "wave-a-lead",
            "wave-d5-lead",
            "wave-t-lead",
            "wave-e-lead",
        ]

    def test_message_types(self):
        assert "REQUIREMENTS_READY" in AgentTeamsBackend.MESSAGE_TYPES
        assert "ARCHITECTURE_READY" in AgentTeamsBackend.MESSAGE_TYPES
        assert "WAVE_COMPLETE" in AgentTeamsBackend.MESSAGE_TYPES
        assert "CONVERGENCE_COMPLETE" in AgentTeamsBackend.MESSAGE_TYPES
        assert "TESTING_COMPLETE" in AgentTeamsBackend.MESSAGE_TYPES

    def test_message_types_count(self):
        assert len(AgentTeamsBackend.MESSAGE_TYPES) == 13
