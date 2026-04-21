from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_team_v15.observer_peek import (
    build_codex_steer_prompt,
    build_corrective_interrupt_prompt,
    build_peek_prompt,
    run_peek_call,
)
from agent_team_v15.wave_executor import PeekResult, PeekSchedule


def test_build_peek_prompt_contains_file_path():
    schedule = PeekSchedule(
        wave="A",
        trigger_files=["apps/api/prisma/schema.prisma"],
        requirements_text="- [ ] apps/api/prisma/schema.prisma\n",
    )
    prompt = build_peek_prompt(
        file_path="apps/api/prisma/schema.prisma",
        file_content="model User { id String @id }",
        schedule=schedule,
        framework_pattern="",
    )
    assert "apps/api/prisma/schema.prisma" in prompt
    assert "verdict" in prompt.lower()


@pytest.mark.asyncio
async def test_run_peek_call_returns_peek_result(tmp_path):
    prisma_dir = tmp_path / "apps" / "api" / "prisma"
    prisma_dir.mkdir(parents=True)
    (prisma_dir / "schema.prisma").write_text("model User { id String @id }")

    schedule = PeekSchedule(
        wave="A",
        trigger_files=["apps/api/prisma/schema.prisma"],
        requirements_text="- [ ] apps/api/prisma/schema.prisma\n",
    )
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"verdict":"ok","confidence":0.95,"message":"looks good"}')]

    with patch("agent_team_v15.observer_peek._call_anthropic_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_response
        result = await run_peek_call(
            cwd=str(tmp_path),
            file_path="apps/api/prisma/schema.prisma",
            schedule=schedule,
            log_only=True,
            model="claude-haiku-4-5-20251001",
            confidence_threshold=0.75,
        )

    assert isinstance(result, PeekResult)
    assert result.verdict == "ok"
    assert result.should_interrupt is False
    assert result.source == "file_poll"

    log_path = tmp_path / ".agent-team" / "observer_log.jsonl"
    assert log_path.exists()


@pytest.mark.asyncio
async def test_run_peek_call_fails_open_on_api_exception(tmp_path):
    (tmp_path / "x.py").write_text("print('hi')")
    schedule = PeekSchedule(wave="A", trigger_files=["x.py"], requirements_text="- [ ] x.py\n")

    with patch("agent_team_v15.observer_peek._call_anthropic_api", new_callable=AsyncMock) as mock_api:
        mock_api.side_effect = RuntimeError("boom")
        result = await run_peek_call(
            cwd=str(tmp_path),
            file_path="x.py",
            schedule=schedule,
            log_only=True,
            model="claude-haiku-4-5-20251001",
            confidence_threshold=0.75,
        )

    assert isinstance(result, PeekResult)
    assert result.verdict == "ok"
    assert result.should_interrupt is False


def test_build_corrective_interrupt_prompt_is_specific():
    result = PeekResult(
        file_path="apps/api/prisma/schema.prisma",
        wave="A",
        verdict="issue",
        confidence=0.88,
        message="File is an empty stub - no model definitions found",
        log_only=False,
    )
    prompt = build_corrective_interrupt_prompt(result)
    assert "schema.prisma" in prompt
    assert "empty stub" in prompt
    assert "Wave A" in prompt
    assert "OBSERVER" in prompt


def test_build_codex_steer_prompt_names_file_and_reason():
    result = PeekResult(
        file_path="apps/api/src/main.ts",
        wave="B",
        verdict="issue",
        confidence=0.9,
        message="missing NestJS bootstrap",
        log_only=False,
        source="diff_event",
    )
    prompt = build_codex_steer_prompt(result)
    assert "main.ts" in prompt
    assert "missing NestJS bootstrap" in prompt
    assert "Observer" in prompt or "observer" in prompt
