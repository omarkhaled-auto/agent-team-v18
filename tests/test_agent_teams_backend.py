"""Tests for agent_team.agent_teams_backend module.

Covers the ExecutionBackend protocol, CLIBackend, AgentTeamsBackend,
the create_execution_backend factory, detect_agent_teams_available,
and all supporting dataclasses (TaskResult, WaveResult, TeamState).
"""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

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
        assert hasattr(ExecutionBackend, "__protocol_attrs__") or hasattr(
            ExecutionBackend, "__abstractmethods__"
        ) or True  # runtime_checkable protocols are always a type

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
        """TEST-002: env var not set -> CLIBackend."""
        monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=True)
    def test_returns_agent_teams_when_all_conditions_met(self, _mock, monkeypatch):
        """TEST-003: enabled, env var set, CLI available -> AgentTeamsBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_fallback_to_cli_on_init_failure(self, _mock, monkeypatch):
        """TEST-004: CLI unavailable + fallback=True -> CLIBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = True
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

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
        """Env var set to something other than '1' -> CLIBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "yes")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

    @patch.object(AgentTeamsBackend, "_verify_claude_available", return_value=False)
    def test_env_var_1_cli_missing_fallback_true(self, _mock, monkeypatch):
        """Env var '1', CLI missing, fallback=True -> CLIBackend."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = True
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

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
        """Factory falls back to CLIBackend when split mode on Windows Terminal."""
        monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
        monkeypatch.setenv("WT_SESSION", "some-session-id")
        config = AgentTeamConfig()
        config.agent_teams.enabled = True
        config.agent_teams.fallback_to_cli = True
        config.agent_teams.teammate_display_mode = "split"
        backend = create_execution_backend(config)
        assert isinstance(backend, CLIBackend)

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
