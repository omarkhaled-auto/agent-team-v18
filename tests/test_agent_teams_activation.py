from __future__ import annotations

from dataclasses import fields

from agent_team_v15.agent_teams_backend import (
    AgentTeamsBackend,
    CLIBackend,
    create_execution_backend,
)
from agent_team_v15.config import (
    AgentTeamConfig,
    AgentTeamsConfig,
    ObserverConfig,
)


def test_observer_config_has_log_only_default_true() -> None:
    assert ObserverConfig().log_only is True


def test_observer_config_has_enabled_default_false() -> None:
    assert ObserverConfig().enabled is False


def test_calibration_gate_exists() -> None:
    from agent_team_v15.replay_harness import (
        CalibrationReport,
        generate_calibration_report,
    )

    report_fields = {field.name for field in fields(CalibrationReport)}
    assert callable(generate_calibration_report)
    assert "safe_to_promote" in report_fields
    assert "recommendation" in report_fields


def test_activation_step_3_is_enforced(tmp_path) -> None:
    from agent_team_v15.replay_harness import generate_calibration_report

    log_dir = tmp_path / ".agent-team"
    log_dir.mkdir()
    log_file = log_dir / "observer_log.jsonl"
    log_file.write_text(
        '{"timestamp": "2026-04-19T10:00:00", "would_interrupt": false, "did_interrupt": false}\n'
        '{"timestamp": "2026-04-20T10:00:00", "would_interrupt": false, "did_interrupt": false}\n',
        encoding="utf-8",
    )
    report = generate_calibration_report(tmp_path)
    assert report.safe_to_promote is False
    assert report.builds_analyzed == 2
    assert "Need" in report.recommendation


def test_communication_channels_exist() -> None:
    from agent_team_v15.codex_appserver import turn_steer
    from agent_team_v15.codex_lead_bridge import (
        read_pending_steer_requests,
        route_codex_wave_complete,
    )

    assert callable(turn_steer)
    assert callable(route_codex_wave_complete)
    assert callable(read_pending_steer_requests)
    assert callable(getattr(AgentTeamsBackend, "route_message"))
    assert "CODEX_WAVE_COMPLETE" in AgentTeamsBackend.MESSAGE_TYPES
    assert "STEER_REQUEST" in AgentTeamsBackend.MESSAGE_TYPES


def test_disabled_returns_cli_backend() -> None:
    config = AgentTeamConfig()
    config.agent_teams = AgentTeamsConfig(enabled=False)
    backend = create_execution_backend(config)
    assert isinstance(backend, CLIBackend)


def test_enabled_without_env_var_returns_cli_backend(monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", raising=False)
    config = AgentTeamConfig()
    config.agent_teams = AgentTeamsConfig(enabled=True, fallback_to_cli=True)
    backend = create_execution_backend(config)
    assert isinstance(backend, CLIBackend)


def test_all_gates_open_returns_agent_teams_backend(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
    config = AgentTeamConfig()
    config.agent_teams = AgentTeamsConfig(enabled=True, fallback_to_cli=False)
    try:
        backend = create_execution_backend(config)
        assert isinstance(backend, AgentTeamsBackend)
    except RuntimeError as exc:
        # create_execution_backend raises this exact path only when the Claude
        # CLI is unavailable and fallback_to_cli is false.
        message = str(exc).lower()
        assert "claude cli is not installed" in message
        assert "not on path" in message
