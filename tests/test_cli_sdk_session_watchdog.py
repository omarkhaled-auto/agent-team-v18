from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import pytest

import agent_team_v15.cli as cli_module
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_executor import WaveWatchdogTimeoutError


class _FakeAssistantMessage:
    def __init__(self, content: list[object]) -> None:
        self.content = content


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _NeverResult:
    pass


@pytest.mark.asyncio
async def test_run_sdk_session_with_watchdog_raises_when_stream_goes_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AgentTeamConfig()
    config.v18.sub_agent_idle_timeout_seconds = 1
    phase_costs: dict[str, float] = {}

    monkeypatch.setattr(cli_module, "AssistantMessage", _FakeAssistantMessage)
    monkeypatch.setattr(cli_module, "TextBlock", _FakeTextBlock)
    monkeypatch.setattr(cli_module, "ToolUseBlock", _NeverResult)
    monkeypatch.setattr(cli_module, "ResultMessage", _NeverResult)

    class HangingClient:
        def __init__(self) -> None:
            self.disconnect_calls = 0
            self.prompts: list[str] = []

        async def query(self, prompt: str) -> None:
            self.prompts.append(prompt)

        async def disconnect(self) -> None:
            self.disconnect_calls += 1

        def receive_response(self):
            async def _iterator():
                yield _FakeAssistantMessage([_FakeTextBlock("working")])
                await asyncio.Future()

            return _iterator()

    client = HangingClient()
    started = time.perf_counter()

    with pytest.raises(WaveWatchdogTimeoutError) as exc_info:
        await cli_module._run_sdk_session_with_watchdog(
            client,
            "prompt",
            config,
            phase_costs,
            role="research",
        )

    elapsed = time.perf_counter() - started
    assert elapsed < 1.3
    assert client.disconnect_calls == 1
    assert exc_info.value.role == "research"


@pytest.mark.parametrize(
    ("label", "pattern"),
    [
        (
            "interactive_initial",
            r"print_task_start\(task\[:200\].*?_run_sdk_session_with_watchdog\(\s*client,\s*prompt,\s*config,\s*phase_costs,\s*role=\"orchestration\"",
        ),
        (
            "interactive_follow_up",
            r"print_task_start\(user_input.*?_run_sdk_session_with_watchdog\(\s*client,\s*prompt,\s*config,\s*phase_costs,\s*role=\"orchestration\"",
        ),
        (
            "single_run",
            r"total_cost = await _run_sdk_session_with_watchdog\(\s*client,\s*prompt,\s*config,\s*phase_costs,\s*role=\"orchestration\"",
        ),
        (
            "research_initial",
            r"total_cost = await _run_sdk_session_with_watchdog\(\s*client,\s*research_prompt,\s*config,\s*phase_costs,\s*role=\"research\"",
        ),
        (
            "research_retry",
            r"retry_cost = await _run_sdk_session_with_watchdog\(\s*client,\s*retry_prompt,\s*config,\s*phase_costs,\s*role=\"research\"",
        ),
        (
            "pseudocode_agent",
            r"item_cost = await _run_sdk_session_with_watchdog\(\s*client,\s*agent_prompt,\s*config,\s*phase_costs,\s*role=\"pseudocode\"",
        ),
        (
            "decomposition_initial",
            r"decomp_cost = await _run_sdk_session_with_watchdog\(\s*client,\s*decomp_prompt,\s*config,\s*phase_costs,\s*role=\"decomposition\"",
        ),
        (
            "decomposition_retry",
            r"retry_cost = await _run_sdk_session_with_watchdog\(\s*retry_client,\s*retry_prompt,\s*config,\s*retry_phase_costs,\s*role=\"decomposition\"",
        ),
        (
            "isolated_milestone_sdk",
            r"milestone_cost = await _run_sdk_session_with_watchdog\(\s*client,\s*ms_prompt,\s*run_config,\s*ms_phase_costs,\s*role=\"milestone_execution\"",
        ),
        (
            "main_milestone_sdk",
            r"_ms_sdk_cost = await _run_sdk_session_with_watchdog\(\s*client,\s*ms_prompt,\s*config,\s*ms_phase_costs,\s*role=\"milestone_execution\"",
        ),
    ],
)
def test_targeted_cli_sites_use_sdk_session_watchdog(label: str, pattern: str) -> None:
    source = Path(cli_module.__file__).read_text(encoding="utf-8")
    assert re.search(pattern, source, flags=re.DOTALL), label


def test_milestone_timeout_warning_uses_actual_wave_execution_timeout() -> None:
    source = Path(cli_module.__file__).read_text(encoding="utf-8")

    assert "wave_execution_timeout_s = _ms_timeout_s * 1.5" in source
    assert "timeout=wave_execution_timeout_s" in source
    assert 'f"Milestone {milestone.id} timed out after {wave_execution_timeout_s:.0f}s. "' in source
