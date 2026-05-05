from __future__ import annotations

import inspect
import logging

import pytest

from agent_team_v15 import cli as cli_module
from agent_team_v15.config import AgentTeamConfig


ASSISTANT_TOOL_RESULT_BLOCK = """                elif isinstance(block, ToolResultBlock):
                    _emit_progress(
                        "tool_result", "",
                        tool_id=block.tool_use_id, event_kind="complete",
                    )
                    detector.on_tool_result(block.tool_use_id)
"""


class _FakeUserMessage:
    def __init__(self, content: list[object]) -> None:
        self.content = content


class _FakeToolResultBlock:
    def __init__(self, tool_use_id: str) -> None:
        self.tool_use_id = tool_use_id


class _FakeResultMessage:
    total_cost_usd = 0.0


class _NeverMessage:
    pass


async def _run_user_message_tool_result_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, str]]:
    monkeypatch.setattr(cli_module, "AssistantMessage", _NeverMessage)
    monkeypatch.setattr(cli_module, "ResultMessage", _FakeResultMessage)
    monkeypatch.setattr(cli_module, "ToolResultBlock", _FakeToolResultBlock)
    monkeypatch.setattr(cli_module, "UserMessage", _FakeUserMessage, raising=False)

    class _Client:
        def receive_response(self):
            async def _iterator():
                yield _FakeUserMessage([_FakeToolResultBlock("tool-result-1")])
                yield _FakeResultMessage()

            return _iterator()

    events: list[dict[str, str]] = []
    await cli_module._consume_response_stream(
        _Client(),
        AgentTeamConfig(),
        {},
        progress_callback=lambda **event: events.append(event),
    )
    return events


@pytest.mark.asyncio
async def test_user_message_tool_result_reaches_forward_compat_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _run_user_message_tool_result_stream(monkeypatch)

    assert {
        "message_type": "tool_result",
        "tool_name": "",
        "tool_id": "tool-result-1",
        "event_kind": "complete",
    } in events


@pytest.mark.asyncio
async def test_user_message_tool_result_branch_logs_debug(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=cli_module.logger.name):
        await _run_user_message_tool_result_stream(monkeypatch)

    assert any(
        "Forward-compatible UserMessage ToolResultBlock" in record.getMessage()
        for record in caplog.records
    )


def test_assistant_message_tool_result_path_is_byte_locked() -> None:
    source = inspect.getsource(cli_module._consume_response_stream)

    assert source.count(ASSISTANT_TOOL_RESULT_BLOCK) == 1


def test_user_message_branch_position_is_locked() -> None:
    source = inspect.getsource(cli_module._consume_response_stream)

    assistant_position = source.index("if isinstance(msg, AssistantMessage):")
    result_position = source.index("elif isinstance(msg, ResultMessage):")
    user_position = source.index("elif isinstance(msg, UserMessage):")
    orphan_position = source.index("# Check for orphans on each message")

    assert assistant_position < result_position < user_position < orphan_position


def test_user_message_forward_compat_comment_names_inert_sdk_flag() -> None:
    source = inspect.getsource(cli_module._consume_response_stream)

    assert "inert today" in source
    assert "replay-user-messages" in source
    assert 'extra_args={"replay-user-messages"' not in source
