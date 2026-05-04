from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest


class _FakeClient:
    def __init__(
        self,
        *,
        initialize_result: dict[str, Any] | None = None,
        initialize_error: Exception | None = None,
        notifications: list[dict[str, Any]] | None = None,
        hang_notifications: bool = False,
    ) -> None:
        self.initialize_calls = 0
        self.thread_start_calls = 0
        self.turn_start_calls = 0
        self.initialize_result = initialize_result or {
            "userAgent": "test",
            "codexHome": "/tmp/codex-home",
        }
        self.initialize_error = initialize_error
        self.notifications = list(notifications or [])
        self.hang_notifications = hang_notifications

    async def initialize(self) -> dict[str, Any]:
        self.initialize_calls += 1
        if self.initialize_error is not None:
            raise self.initialize_error
        return self.initialize_result

    async def thread_start(self) -> dict[str, Any]:
        self.thread_start_calls += 1
        return {"thread": {"id": "preflight-thread"}}

    async def turn_start(self, thread_id: str, prompt: str) -> dict[str, Any]:
        self.turn_start_calls += 1
        assert thread_id == "preflight-thread"
        assert "literal string OK" in prompt
        return {"turn": {"id": "preflight-turn"}}

    async def next_notification(self) -> dict[str, Any]:
        if self.notifications:
            return self.notifications.pop(0)
        if self.hang_notifications:
            await asyncio.sleep(3600)
        return {"method": "noise", "params": {}}


@pytest.mark.asyncio
async def test_execute_once_start_failure_raises_preflight_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    class _StartFailClient:
        returncode = 0

        async def start(self) -> None:
            raise FileNotFoundError("codex binary missing")

        async def close(self) -> None:
            return None

        def stderr_excerpt(self, limit: int = 300) -> str:
            return ""

    monkeypatch.setattr(mod, "_CodexAppServerClient", lambda *_args, **_kwargs: _StartFailClient())

    with pytest.raises(mod.CodexAppserverPreflightError, match="startup failed"):
        await mod._execute_once(
            "real prompt",
            str(tmp_path),
            mod.CodexConfig(max_retries=0),
            tmp_path,
        )


@pytest.mark.asyncio
async def test_preflight_wraps_thread_start_dispatch_error() -> None:
    from agent_team_v15.codex_appserver import (
        CodexAppserverPreflightError,
        CodexDispatchError,
        _preflight_codex_appserver,
    )

    class _DispatchFailClient(_FakeClient):
        async def thread_start(self) -> dict[str, Any]:
            raise CodexDispatchError("Invalid codex_sandbox_mode")

    with pytest.raises(CodexAppserverPreflightError, match="Invalid codex_sandbox_mode"):
        await _preflight_codex_appserver(_DispatchFailClient(), timeout=0.1)


def test_preflight_source_wraps_codex_dispatch_error() -> None:
    import inspect

    from agent_team_v15.codex_appserver import _preflight_codex_appserver

    source = inspect.getsource(_preflight_codex_appserver)

    assert "except CodexDispatchError" not in source
    assert "raise CodexDispatchError" not in source


@pytest.mark.asyncio
async def test_preflight_passes_when_turn_completed_arrives() -> None:
    from agent_team_v15.codex_appserver import _preflight_codex_appserver

    client = _FakeClient(
        notifications=[
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "preflight-thread",
                    "turn": {"id": "preflight-turn", "status": "completed"},
                },
            }
        ],
    )

    await _preflight_codex_appserver(client, timeout=0.1)

    assert client.initialize_calls == 1
    assert client.thread_start_calls == 1
    assert client.turn_start_calls == 1


@pytest.mark.asyncio
async def test_preflight_timeout_raises_typed_error() -> None:
    from agent_team_v15.codex_appserver import (
        CodexAppserverPreflightError,
        _preflight_codex_appserver,
    )

    client = _FakeClient(hang_notifications=True)

    with pytest.raises(CodexAppserverPreflightError, match="timed out"):
        await _preflight_codex_appserver(client, timeout=0.01)


@pytest.mark.asyncio
async def test_preflight_initialize_error_raises_typed_error() -> None:
    from agent_team_v15.codex_appserver import (
        CodexAppserverPreflightError,
        _preflight_codex_appserver,
    )

    client = _FakeClient(initialize_error=RuntimeError("initialize exploded"))

    with pytest.raises(CodexAppserverPreflightError, match="initialize failed"):
        await _preflight_codex_appserver(client, timeout=0.1)


@pytest.mark.asyncio
async def test_preflight_success_is_cached_once_per_client_session() -> None:
    from agent_team_v15.codex_appserver import _preflight_codex_appserver

    client = _FakeClient(
        notifications=[
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "preflight-thread",
                    "turn": {"id": "preflight-turn", "status": "completed"},
                },
            }
        ],
    )

    await _preflight_codex_appserver(client, timeout=0.1)
    await _preflight_codex_appserver(client, timeout=0.1)

    assert client.initialize_calls == 1
    assert client.thread_start_calls == 1
    assert client.turn_start_calls == 1


@dataclass
class _FakeCheckpoint:
    file_manifest: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.file_manifest is None:
            self.file_manifest = {}


def _fake_diff(_before: Any, _after: Any) -> SimpleNamespace:
    return SimpleNamespace(created=[], modified=[], deleted=[])


@pytest.mark.asyncio
async def test_provider_router_surfaces_preflight_failure_reason(tmp_path: Path) -> None:
    from agent_team_v15.codex_appserver import CodexAppserverPreflightError
    from agent_team_v15.codex_transport import CodexConfig
    from agent_team_v15.provider_router import WaveProviderMap, execute_wave_with_provider

    async def _raise_preflight(*_args: Any, **_kwargs: Any) -> None:
        raise CodexAppserverPreflightError("preflight timed out after 0.01s")

    transport = SimpleNamespace(
        is_codex_available=lambda: True,
        execute_codex=_raise_preflight,
    )

    result = await execute_wave_with_provider(
        wave_letter="B",
        prompt="wire backend",
        cwd=str(tmp_path),
        config=SimpleNamespace(v18=SimpleNamespace()),
        provider_map=WaveProviderMap(B="codex"),
        claude_callback=AsyncMock(return_value=0.01),
        claude_callback_kwargs={},
        codex_transport_module=transport,
        codex_config=CodexConfig(max_retries=0),
        codex_home=tmp_path,
        checkpoint_create=lambda _label, _cwd: _FakeCheckpoint(),
        checkpoint_diff=_fake_diff,
    )

    assert result["success"] is False
    assert result["provider"] == "codex"
    assert result["failure_reason"] == "codex_appserver_preflight_failed"
    assert "preflight" in result["error_message"].lower()


def test_cli_classifier_maps_preflight_failure_to_exit_reason() -> None:
    from agent_team_v15 import cli as cli_module

    wave_result = SimpleNamespace(
        success=False,
        error_message=(
            "codex_appserver_preflight_failed: preflight timed out before "
            "turn/completed"
        ),
    )

    assert (
        cli_module._phase_4_5_terminal_transport_failure_reason(wave_result)
        == "codex_appserver_preflight_failed"
    )


def test_cli_preflight_failure_exits_with_environmental_code() -> None:
    from agent_team_v15 import cli as cli_module

    with pytest.raises(SystemExit) as excinfo:
        cli_module._phase_4_5_exit_for_codex_environmental_failure(
            "codex_appserver_preflight_failed"
        )

    assert excinfo.value.code == 2


@pytest.mark.asyncio
async def test_execute_once_preflights_once_when_session_has_multiple_turns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    class _LifecycleClient(_FakeClient):
        def __init__(self) -> None:
            super().__init__(
                notifications=[
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": "preflight-thread",
                            "turn": {"id": "preflight-turn", "status": "completed"},
                        },
                    }
                ],
            )
            self.close = AsyncMock()
            self.thread_archive = AsyncMock(return_value={})
            self.returncode = 0
            self.cwd = str(tmp_path)
            self.stderr_excerpt = lambda limit=300: ""
            self.real_turns = 0

        async def start(self) -> None:
            return None

        async def turn_start(self, thread_id: str, prompt: str) -> dict[str, Any]:
            if "literal string OK" in prompt:
                return await super().turn_start(thread_id, prompt)
            self.real_turns += 1
            return {"turn": {"id": f"real-turn-{self.real_turns}"}}

    fake_client = _LifecycleClient()
    completions = [
        {"status": "interrupted", "error": None},
        {"status": "completed", "error": None},
    ]

    async def _fake_wait_for_turn_completion(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return completions.pop(0)

    monkeypatch.setattr(mod, "_CodexAppServerClient", lambda *_args, **_kwargs: fake_client)
    monkeypatch.setattr(mod, "_wait_for_turn_completion", _fake_wait_for_turn_completion)

    result = await mod._execute_once(
        "real prompt",
        str(tmp_path),
        mod.CodexConfig(max_retries=0),
        tmp_path,
    )

    assert result.success is True
    assert fake_client.initialize_calls == 1
    assert fake_client.thread_start_calls == 2
    assert fake_client.turn_start_calls == 1
    assert fake_client.real_turns == 2
