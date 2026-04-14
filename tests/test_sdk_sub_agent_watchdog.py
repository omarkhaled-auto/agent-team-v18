from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_team_v15.wave_executor as wave_executor_module
from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_executor import (
    WaveWatchdogTimeoutError,
    _execute_wave_sdk,
    _execute_wave_t,
    _invoke_sdk_sub_agent_with_watchdog,
)


def _milestone(
    *,
    template: str = "full_stack",
    milestone_id: str = "milestone-watchdog",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=milestone_id,
        title="Orders",
        template=template,
        description="Orders milestone",
        dependencies=[],
        feature_refs=["F-ORDERS"],
        ac_refs=[],
        merge_surfaces=[],
        stack_target="NestJS Next.js",
    )


def _config() -> AgentTeamConfig:
    config = AgentTeamConfig()
    config.v18.wave_watchdog_poll_seconds = 1
    config.v18.wave_idle_timeout_seconds = 1
    config.v18.sub_agent_idle_timeout_seconds = 1
    return config


async def _never_returns(**_: object) -> float:
    await asyncio.Future()
    return 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "wave", "role"),
    [
        ("probe_fix", "B", "probe_fix"),
        ("wave_t_initial", "T", "wave"),
        ("wave_t_test_fix", "T", "test_fix"),
        ("compile_fix_generic", "A", "compile_fix"),
        ("compile_fix_dto_guard", "B", "compile_fix"),
        ("compile_fix_frontend_guard", "D", "compile_fix"),
    ],
    ids=[
        "probe_fix",
        "wave_t_initial",
        "wave_t_test_fix",
        "compile_fix_generic",
        "compile_fix_dto_guard",
        "compile_fix_frontend_guard",
    ],
)
async def test_sdk_sub_agent_watchdog_times_out_for_each_wrapped_call_site(
    tmp_path: Path,
    case_id: str,
    wave: str,
    role: str,
) -> None:
    del case_id
    config = _config()
    milestone = _milestone()
    started = time.monotonic()

    with pytest.raises(WaveWatchdogTimeoutError) as exc_info:
        await asyncio.wait_for(
            _invoke_sdk_sub_agent_with_watchdog(
                execute_sdk_call=_never_returns,
                prompt=f"{wave}:{role}",
                wave_letter=wave,
                role=role,
                config=config,
                cwd=str(tmp_path),
                milestone=milestone,
            ),
            timeout=3.0,
        )

    elapsed = time.monotonic() - started
    assert elapsed < 3.0
    assert exc_info.value.wave == wave
    assert exc_info.value.role == role
    assert exc_info.value.timeout_seconds == 1
    assert role in str(exc_info.value)


@pytest.mark.asyncio
async def test_generic_wave_watchdog_still_retries_once(
    tmp_path: Path,
) -> None:
    config = _config()
    config.v18.wave_watchdog_max_retries = 1
    attempts: list[str] = []

    async def execute_sdk_call(
        *,
        wave: str,
        role: str = "wave",
        progress_callback=None,
        **_: object,
    ) -> float:
        del progress_callback
        attempts.append(f"{wave}:{role}")
        await asyncio.Future()
        return 0.0

    result = await asyncio.wait_for(
        _execute_wave_sdk(
            execute_sdk_call=execute_sdk_call,
            wave_letter="A",
            prompt="wave A",
            config=config,
            cwd=str(tmp_path),
            milestone=_milestone(),
        ),
        timeout=5.0,
    )

    assert result.success is False
    assert result.wave_timed_out is True
    assert result.wave_watchdog_fired_at
    assert result.hang_report_path
    assert Path(result.hang_report_path).is_file()
    assert attempts == ["A:wave", "A:wave"]


@pytest.mark.asyncio
async def test_wave_heartbeat_uses_visible_console_output(monkeypatch, tmp_path: Path) -> None:
    state = wave_executor_module._WaveWatchdogState()
    state.sdk_call_count = 2
    state.record_progress(message_type="item.completed", tool_name="write")

    messages: list[str] = []
    loop_task: asyncio.Future[None] = asyncio.Future()
    sleep_calls = 0

    async def _fake_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2 and not loop_task.done():
            loop_task.set_result(None)

    monkeypatch.setattr(wave_executor_module, "print_info", messages.append)
    monkeypatch.setattr(wave_executor_module, "_count_touched_files", lambda *_args, **_kwargs: 3)
    monkeypatch.setattr(wave_executor_module.asyncio, "sleep", _fake_sleep)

    await wave_executor_module._log_wave_heartbeats(
        task=loop_task,
        state=state,
        wave_letter="B",
        cwd=str(tmp_path),
        baseline_fingerprints={},
    )

    assert any("[Wave B] active - last write" in message for message in messages)


@pytest.mark.asyncio
async def test_execute_wave_t_returns_timeout_result_when_sdk_hangs(
    tmp_path: Path,
) -> None:
    config = _config()

    async def build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    started = time.monotonic()
    result = await asyncio.wait_for(
        _execute_wave_t(
            execute_sdk_call=_never_returns,
            build_wave_prompt=build_prompt,
            run_compile_check=None,
            milestone=_milestone(),
            ir={"acceptance_criteria": []},
            config=config,
            cwd=str(tmp_path),
            template="full_stack",
            wave_artifacts={},
            dependency_artifacts={},
            scaffolded_files=[],
        ),
        timeout=4.0,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 4.0
    assert result.success is False
    assert result.wave_timed_out is True
    assert result.wave_watchdog_fired_at
    assert result.error_message
