from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_team_v15.config import AgentTeamConfig
from agent_team_v15.wave_executor import (
    WaveWatchdogTimeoutError,
    _execute_wave_sdk,
    _execute_wave_t,
    _invoke_sdk_sub_agent_with_watchdog,
    execute_milestone_waves,
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
    config.v18.wave_total_timeout_seconds = 2
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


@pytest.mark.asyncio
async def test_execute_milestone_waves_enforces_total_wave_timeout_when_progress_continues(
    tmp_path: Path,
) -> None:
    config = _config()
    config.v18.wave_watchdog_max_retries = 0
    config.v18.wave_t_enabled = False

    async def build_prompt(**kwargs: object) -> str:
        return f"wave {kwargs['wave']}"

    async def execute_sdk_call(
        *,
        progress_callback=None,
        **_: object,
    ) -> float:
        while True:
            if progress_callback is not None:
                progress_callback(message_type="assistant_text", tool_name="")
            await asyncio.sleep(0.1)

    async def run_compile_check(**_: object) -> dict[str, object]:
        return {"passed": True, "iterations": 1, "initial_error_count": 0, "errors": []}

    started = time.monotonic()
    result = await asyncio.wait_for(
        execute_milestone_waves(
            milestone=_milestone(template="frontend_only", milestone_id="M-WAVE-TOTAL"),
            ir={"i18n": {"locales": ["en"]}},
            config=config,
            cwd=str(tmp_path),
            build_wave_prompt=build_prompt,
            execute_sdk_call=execute_sdk_call,
            run_compile_check=run_compile_check,
            extract_artifacts=lambda **kwargs: {"wave": kwargs["wave"]},
            generate_contracts=None,
            run_scaffolding=None,
            save_wave_state=None,
        ),
        timeout=5.0,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    assert result.success is False
    assert result.error_wave == "A"
    assert result.waves
    assert result.waves[0].wave == "A"
    assert result.waves[0].wave_timed_out is True
    assert result.waves[0].wave_watchdog_fired_at
    assert "total timeout" in result.waves[0].error_message.lower()
