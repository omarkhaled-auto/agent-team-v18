from __future__ import annotations

import pytest

from agent_team_v15.codex_transport import CodexConfig


def _watchdog(
    *,
    timeout_seconds: float = 307.0,
    tool_name: str = "commandExecution",
    age_seconds: float = 307.0,
    command_summary: str = "pnpm install",
):
    from agent_team_v15.codex_appserver import _OrphanWatchdog

    watchdog = _OrphanWatchdog(timeout_seconds=timeout_seconds, max_orphan_events=2)
    watchdog.register_orphan_event(
        tool_name,
        "tool_1",
        age_seconds,
        command_summary=command_summary,
    )
    return watchdog


def test_refined_interrupt_prompt_names_command_and_preserves_tool_use() -> None:
    from agent_team_v15.codex_appserver import _build_turn_interrupt_prompt

    prompt = _build_turn_interrupt_prompt(
        _watchdog(),
        CodexConfig(turn_interrupt_message_refined_enabled=True),
    )

    assert "running command `pnpm install`" in prompt
    assert "You may continue using `commandExecution` for other commands." in prompt
    assert "Do NOT retry the stalled command" in prompt
    assert "validation, build, or test steps" in prompt
    assert "Do not run that tool again" not in prompt


def test_legacy_interrupt_prompt_is_byte_identical_when_flag_off() -> None:
    from agent_team_v15.codex_appserver import _legacy_turn_interrupt_prompt

    prompt = _legacy_turn_interrupt_prompt(_watchdog())

    assert prompt == (
        "The previous turn's tool (tool_name=commandExecution) "
        "stalled for >307s. Do not run that tool again; "
        "continue the remaining work using alternative approaches."
    )


def test_refined_interrupt_prompt_falls_back_when_command_missing() -> None:
    from agent_team_v15.codex_appserver import _build_turn_interrupt_prompt

    prompt = _build_turn_interrupt_prompt(
        _watchdog(tool_name="shell", command_summary=""),
        CodexConfig(turn_interrupt_message_refined_enabled=True),
    )

    assert "running command" not in prompt
    assert "The previous invocation of `shell` stalled for >307s" in prompt
    assert "Do NOT retry that stalled invocation" in prompt


def test_process_streaming_event_truncates_long_command_summary() -> None:
    from agent_team_v15.codex_appserver import (
        _MessageAccumulator,
        _OrphanWatchdog,
        _TokenAccumulator,
        _process_streaming_event,
    )

    watchdog = _OrphanWatchdog(timeout_seconds=307.0, max_orphan_events=2)
    tokens = _TokenAccumulator()
    messages = _MessageAccumulator()
    long_command = "pnpm install " + "workspace-package " * 10

    _process_streaming_event(
        {
            "method": "item/started",
            "params": {
                "item": {
                    "id": "tool_1",
                    "name": "commandExecution",
                    "command": long_command,
                }
            },
        },
        watchdog,
        tokens,
        progress_callback=None,
        messages=messages,
    )

    summary = watchdog.pending_tool_starts["tool_1"]["command_summary"]
    assert len(summary) == 80
    assert summary.startswith("pnpm install workspace-package")
    assert summary.endswith("...")


@pytest.mark.asyncio
async def test_execute_once_retries_with_refined_interrupt_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    class _FakeClient:
        instances: list["_FakeClient"] = []

        def __init__(self, *, cwd: str, config: CodexConfig, codex_home, protocol_logger=None) -> None:
            del protocol_logger
            self.cwd = cwd
            self.config = config
            self.codex_home = codex_home
            self.returncode = 0
            self.prompts: list[str] = []
            self.archived_threads: list[str] = []
            self.closed = False
            _FakeClient.instances.append(self)

        async def start(self) -> None:
            return None

        async def initialize(self) -> dict[str, str]:
            return {"userAgent": "pytest", "codexHome": str(self.codex_home)}

        async def thread_start(self) -> dict[str, object]:
            return {"thread": {"id": "thr_1"}, "cwd": self.cwd}

        async def turn_start(self, thread_id: str, prompt: str) -> dict[str, object]:
            assert thread_id == "thr_1"
            self.prompts.append(prompt)
            return {
                "turn": {
                    "id": f"turn_{len(self.prompts)}",
                    "status": "inProgress",
                    "items": [],
                    "error": None,
                }
            }

        async def thread_archive(self, thread_id: str) -> dict[str, object]:
            self.archived_threads.append(thread_id)
            return {}

        async def close(self) -> None:
            self.closed = True

        def stderr_excerpt(self, limit: int = 300) -> str:
            del limit
            return ""

    wait_calls = {"count": 0}

    async def _fake_wait_for_turn_completion(
        client,
        *,
        thread_id: str,
        turn_id: str,
        watchdog,
        tokens,
        progress_callback,
        messages,
        capture_session=None,
    ) -> dict[str, object]:
        del client, thread_id, turn_id, tokens, progress_callback, capture_session
        wait_calls["count"] += 1
        if wait_calls["count"] == 1:
            watchdog.register_orphan_event(
                "commandExecution",
                "tool_1",
                307.0,
                command_summary="pnpm install",
            )
            return {"id": "turn_1", "status": "interrupted", "error": None}
        messages._final_answer = "OK"
        return {"id": "turn_2", "status": "completed", "error": None}

    async def _fake_monitor_orphans(*args, **kwargs) -> bool:
        del args, kwargs
        return False

    monkeypatch.setattr(mod, "_CodexAppServerClient", _FakeClient)
    monkeypatch.setattr(mod, "_wait_for_turn_completion", _fake_wait_for_turn_completion)
    monkeypatch.setattr(mod, "_monitor_orphans", _fake_monitor_orphans)

    config = CodexConfig(
        max_retries=0,
        reasoning_effort="low",
        turn_interrupt_message_refined_enabled=True,
    )
    result = await mod._execute_once(
        "initial prompt",
        str(tmp_path),
        config,
        tmp_path,
        orphan_timeout_seconds=307.0,
        orphan_check_interval_seconds=0.01,
    )

    client = _FakeClient.instances[-1]
    assert result.success is True
    assert result.final_message == "OK"
    assert client.prompts[0] == "initial prompt"
    assert client.prompts[1] == (
        "The previous invocation of `commandExecution` running command `pnpm install` stalled "
        "for >307s and was interrupted. You may continue using `commandExecution` for "
        "other commands. Do NOT retry the stalled command; treat its effects as already applied "
        "(any files it created or modified are present on disk). Continue with the remaining "
        "work, including any validation, build, or test steps you would normally perform."
    )
    assert client.archived_threads == ["thr_1"]
    assert client.closed is True
