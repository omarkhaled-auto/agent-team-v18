from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent_team_v15 import codex_appserver
from agent_team_v15 import observer_peek as observer_peek_module
from agent_team_v15 import wave_executor as wave_executor_module
from agent_team_v15.config import AgentTeamConfig, ObserverConfig, load_config
from agent_team_v15.observer_peek import build_peek_prompt
from agent_team_v15.replay_harness import generate_calibration_report


def _make_diff(paths: list[str]) -> str:
    parts: list[str] = []
    for path in paths:
        parts.extend([
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -0,0 +1,2 @@",
            "+line one",
            "+line two",
        ])
    return "\n".join(parts) + "\n"


def test_claude_wave_peek_pipeline_wires_end_to_end(tmp_path, monkeypatch) -> None:
    target = tmp_path / "apps" / "api" / "prisma" / "schema.prisma"
    target.parent.mkdir(parents=True)
    target.write_text("model User { id String @id }", encoding="utf-8")

    observer_cfg = ObserverConfig(
        enabled=True,
        log_only=True,
        peek_cooldown_seconds=0.0,
        max_peeks_per_wave=5,
        time_based_interval_seconds=0.0,
        confidence_threshold=0.75,
    )
    state = wave_executor_module._WaveWatchdogState()
    requirements = "- [ ] apps/api/prisma/schema.prisma\n"
    milestone = SimpleNamespace(id="m1")
    wave_executor_module._initialize_wave_peek_schedule(
        state,
        observer_config=observer_cfg,
        requirements_text=requirements,
        cwd=str(tmp_path),
        milestone=milestone,
        wave_letter="A",
    )
    assert state.peek_schedule is not None
    assert wave_executor_module._should_fire_time_based_peek(0.0, 0.01, 0, 5)

    prompt = build_peek_prompt(
        file_path="apps/api/prisma/schema.prisma",
        file_content=target.read_text(encoding="utf-8"),
        schedule=state.peek_schedule,
        framework_pattern="",
    )
    assert "apps/api/prisma/schema.prisma" in prompt

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text='{"verdict":"issue","confidence":0.9,"message":"missing relation"}')
    ]

    async def _fake_anthropic_api(*args, **kwargs):
        return mock_response

    monkeypatch.setattr(observer_peek_module, "_call_anthropic_api", _fake_anthropic_api)

    asyncio.run(
        wave_executor_module._run_wave_observer_peek(
            state=state,
            observer_config=observer_cfg,
            cwd=str(tmp_path),
            baseline_fingerprints={},
            wave_letter="A",
        )
    )

    assert len(state.peek_log) == 1
    result = state.peek_log[0]

    async def _fake_wave_sdk_with_watchdog(**kwargs):
        return 0.0, state

    monkeypatch.setattr(
        wave_executor_module,
        "_invoke_wave_sdk_with_watchdog",
        _fake_wave_sdk_with_watchdog,
    )
    config = AgentTeamConfig()
    config.observer = observer_cfg

    async def _fake_sdk(*args, **kwargs):
        return None

    wave_result = asyncio.run(
        wave_executor_module._execute_wave_sdk(
            _fake_sdk,
            "A",
            "prompt",
            config,
            str(tmp_path),
            milestone,
        )
    )
    assert len(wave_result.peek_summary) == 1
    assert wave_result.peek_summary[0]["verdict"] == "issue"

    log_file = tmp_path / ".agent-team" / "observer_log.jsonl"
    lines = [
        json.loads(line.strip())
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines[0]["would_interrupt"] is True
    assert lines[0]["did_interrupt"] is False
    assert lines[0]["log_only"] is True
    assert lines[0]["run_id"]


def test_peek_summary_preserved_on_watchdog_timeout(tmp_path, monkeypatch) -> None:
    state = wave_executor_module._WaveWatchdogState()
    state.peek_log.append(
        wave_executor_module.PeekResult(
            file_path="apps/api/prisma/schema.prisma",
            wave="A",
            verdict="issue",
            confidence=0.9,
            message="missing relation",
            log_only=True,
            source="file_poll",
        )
    )

    async def _fake_wave_sdk_with_watchdog(**kwargs):
        raise wave_executor_module.WaveWatchdogTimeoutError("A", state, 1)

    monkeypatch.setattr(
        wave_executor_module,
        "_invoke_wave_sdk_with_watchdog",
        _fake_wave_sdk_with_watchdog,
    )

    config = AgentTeamConfig()
    config.observer = ObserverConfig(enabled=True, log_only=True)
    config.v18.wave_watchdog_max_retries = 0
    milestone = SimpleNamespace(id="m1")

    async def _fake_sdk(*args, **kwargs):
        return None

    wave_result = asyncio.run(
        wave_executor_module._execute_wave_sdk(
            _fake_sdk,
            "A",
            "prompt",
            config,
            str(tmp_path),
            milestone,
        )
    )

    assert wave_result.success is False
    assert wave_result.wave_timed_out is True
    assert len(wave_result.peek_summary) == 1
    assert wave_result.peek_summary[0]["verdict"] == "issue"
    assert wave_result.peek_summary[0]["file"] == "apps/api/prisma/schema.prisma"


def test_codex_notification_pipeline_emits_steer_in_log_only(tmp_path, monkeypatch) -> None:
    class _FakeClient:
        def __init__(self) -> None:
            self.cwd = str(tmp_path)
            self._messages = iter([
                {
                    "method": "turn/diff/updated",
                    "params": {
                        "diff": _make_diff([
                            "apps/web/pages/index.tsx",
                            "apps/web/components/Header.tsx",
                            "apps/web/styles/main.css",
                        ])
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {"threadId": "thread-1", "turn": {"id": "turn-1"}},
                },
            ])

        async def next_notification(self):
            return next(self._messages)

    steer_calls: list[tuple[str, str, str]] = []

    async def _fake_turn_steer(client, thread_id: str, turn_id: str, message: str) -> None:
        steer_calls.append((thread_id, turn_id, message))

    monkeypatch.setattr(codex_appserver, "turn_steer", _fake_turn_steer)

    watchdog = codex_appserver._OrphanWatchdog(
        observer_config=ObserverConfig(
            enabled=True,
            log_only=True,
            codex_notification_observer_enabled=True,
            codex_diff_check_enabled=True,
        ),
        wave_letter="B",
    )

    turn = asyncio.run(
        codex_appserver._wait_for_turn_completion(
            _FakeClient(),
            thread_id="thread-1",
            turn_id="turn-1",
            watchdog=watchdog,
            tokens=codex_appserver._TokenAccumulator(),
            progress_callback=None,
            messages=codex_appserver._MessageAccumulator(),
        )
    )

    assert turn["id"] == "turn-1"
    assert watchdog.codex_latest_diff
    from agent_team_v15.codex_observer_checks import check_codex_diff

    assert check_codex_diff(watchdog.codex_latest_diff, "B")
    assert steer_calls == []
    log_file = tmp_path / ".agent-team" / "observer_log.jsonl"
    lines = [
        json.loads(line.strip())
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines[0]["source"] == "diff_event"
    assert lines[0]["verdict"] == "issue"
    assert lines[0]["would_interrupt"] is True
    assert lines[0]["did_interrupt"] is False
    assert lines[0]["run_id"]


@pytest.mark.parametrize(
    "observer_kwargs",
    [
        {"enabled": False},
        {"enabled": True, "codex_notification_observer_enabled": False},
        {
            "enabled": True,
            "codex_notification_observer_enabled": True,
            "codex_diff_check_enabled": False,
        },
    ],
)
def test_codex_notification_observer_respects_disabled_flags(
    tmp_path,
    monkeypatch,
    observer_kwargs,
) -> None:
    class _FakeClient:
        def __init__(self) -> None:
            self.cwd = str(tmp_path)
            self._messages = iter([
                {
                    "method": "turn/diff/updated",
                    "params": {
                        "diff": _make_diff([
                            "apps/web/pages/index.tsx",
                            "apps/web/components/Header.tsx",
                            "apps/web/styles/main.css",
                        ])
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {"threadId": "thread-1", "turn": {"id": "turn-1"}},
                },
            ])

        async def next_notification(self):
            return next(self._messages)

    steer_calls: list[tuple[str, str, str]] = []

    async def _fake_turn_steer(client, thread_id: str, turn_id: str, message: str) -> None:
        steer_calls.append((thread_id, turn_id, message))

    monkeypatch.setattr(codex_appserver, "turn_steer", _fake_turn_steer)

    watchdog = codex_appserver._OrphanWatchdog(
        observer_config=ObserverConfig(log_only=False, **observer_kwargs),
        wave_letter="B",
    )

    turn = asyncio.run(
        codex_appserver._wait_for_turn_completion(
            _FakeClient(),
            thread_id="thread-1",
            turn_id="turn-1",
            watchdog=watchdog,
            tokens=codex_appserver._TokenAccumulator(),
            progress_callback=None,
            messages=codex_appserver._MessageAccumulator(),
        )
    )

    assert turn["id"] == "turn-1"
    assert watchdog.codex_latest_diff
    assert steer_calls == []
    assert not (tmp_path / ".agent-team" / "observer_log.jsonl").exists()


def test_calibration_gate_rejects_two_builds(tmp_path) -> None:
    log_dir = tmp_path / ".agent-team"
    log_dir.mkdir()
    entries = [
        {"timestamp": "2026-04-18T09:00:00", "would_interrupt": False, "did_interrupt": False},
        {"timestamp": "2026-04-18T10:00:00", "would_interrupt": False, "did_interrupt": False},
        {"timestamp": "2026-04-19T09:00:00", "would_interrupt": False, "did_interrupt": False},
        {"timestamp": "2026-04-19T10:00:00", "would_interrupt": False, "did_interrupt": False},
    ]
    (log_dir / "observer_log.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )

    report = generate_calibration_report(tmp_path)

    assert report.builds_analyzed == 2
    assert report.safe_to_promote is False
    assert report.recommendation.startswith("Need 1 more calibration build")


def test_config_round_trip_preserves_observer_and_phase_leads(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "observer:\n"
        "  enabled: true\n"
        "  log_only: true\n"
        "  confidence_threshold: 0.8\n"
        "  peek_cooldown_seconds: 45.0\n"
        "agent_teams:\n"
        "  enabled: true\n"
        "  fallback_to_cli: true\n"
        "  phase_lead_max_turns: 222\n"
        "phase_leads:\n"
        "  enabled: true\n"
        "  handoff_timeout_seconds: 444\n",
        encoding="utf-8",
    )

    cfg, overrides = load_config(config_file)

    assert isinstance(cfg, AgentTeamConfig)
    assert cfg.observer.enabled is True
    assert cfg.observer.log_only is True
    assert cfg.observer.confidence_threshold == 0.8
    assert cfg.observer.peek_cooldown_seconds == 45.0
    assert cfg.agent_teams.phase_lead_max_turns == 222
    assert cfg.phase_leads.enabled is True
    assert cfg.phase_leads.handoff_timeout_seconds == 444
    assert "observer.enabled" in overrides
