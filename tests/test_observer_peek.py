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


@pytest.mark.asyncio
async def test_call_anthropic_api_uses_claude_agent_sdk_first():
    """The peek must prefer subscription auth (claude_agent_sdk) over the
    anthropic SDK, so operators running on `claude login` auth don't need
    to set ANTHROPIC_API_KEY."""
    from agent_team_v15 import observer_peek

    sdk_calls: list[tuple[str, str, str]] = []

    async def _fake_sdk(prompt: str, system: str, model: str):
        sdk_calls.append((prompt, system, model))
        return observer_peek._PeekResponseShim(
            '{"verdict":"ok","confidence":0.8,"message":"sdk ran"}'
        )

    async def _fake_api_should_not_fire(*a, **kw):
        raise AssertionError("anthropic SDK fallback should not be called when claude_agent_sdk works")

    with patch.object(observer_peek, "_call_via_claude_agent_sdk", new=_fake_sdk):
        with patch("anthropic.AsyncAnthropic", side_effect=_fake_api_should_not_fire):
            response = await observer_peek._call_anthropic_api(
                prompt="peek this",
                system="you are an observer",
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
            )

    assert sdk_calls == [("peek this", "you are an observer", "claude-haiku-4-5-20251001")]
    assert response.content[0].text.startswith("{")


@pytest.mark.asyncio
async def test_call_anthropic_api_falls_back_to_anthropic_sdk_when_claude_agent_sdk_fails():
    """When claude_agent_sdk is unavailable (import error or runtime failure),
    the peek must fall through to the anthropic SDK. This preserves backwards
    compatibility for operators who use ANTHROPIC_API_KEY instead of claude login."""
    from agent_team_v15 import observer_peek

    async def _sdk_raises(prompt: str, system: str, model: str):
        raise ImportError("claude_agent_sdk not installed")

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"verdict":"ok","confidence":0.6,"message":"api ran"}')]

    fake_messages = MagicMock()
    fake_messages.create = AsyncMock(return_value=fake_response)
    fake_client = MagicMock()
    fake_client.messages = fake_messages

    with patch.object(observer_peek, "_call_via_claude_agent_sdk", new=_sdk_raises):
        with patch("anthropic.AsyncAnthropic", return_value=fake_client):
            response = await observer_peek._call_anthropic_api(
                prompt="peek this",
                system="you are an observer",
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
            )

    assert fake_messages.create.await_count == 1
    assert response.content[0].text == '{"verdict":"ok","confidence":0.6,"message":"api ran"}'


def test_peek_response_shim_matches_anthropic_sdk_shape():
    """The shim must expose the same .content[0].text attribute chain the
    call sites use on the real anthropic response object."""
    from agent_team_v15.observer_peek import _PeekResponseShim

    shim = _PeekResponseShim('{"verdict":"issue","confidence":0.9,"message":"missing bootstrap"}')
    assert shim.content[0].text.startswith("{")
    assert "bootstrap" in shim.content[0].text


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
