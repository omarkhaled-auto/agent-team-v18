from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest


class _MockStdin:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _MockProcess:
    def __init__(self, *, pid: int = 4242, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.stdin = _MockStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.wait_calls = 0
        self.terminate_calls = 0
        self.kill_calls = 0

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9


class _DelayedStderr:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._release = asyncio.Event()
        self._sent = False

    def release(self) -> None:
        self._release.set()

    async def readline(self) -> bytes:
        if self._sent:
            self._events.append("stderr-eof")
            return b""
        self._events.append("stderr-awaiting-release")
        try:
            await self._release.wait()
        except asyncio.CancelledError:
            self._events.append("stderr-cancelled")
            raise
        self._sent = True
        self._events.append("stderr-line-returned")
        return b"late app-server stderr\n"


class _ProcessWithDelayedStderr:
    def __init__(self, events: list[str]) -> None:
        self.pid = 4321
        self.returncode: int | None = 0
        self.stdin = _MockStdin()
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_eof()
        self.stderr = _DelayedStderr(events)
        self._events = events

    async def wait(self) -> int:
        self._events.append("process-wait")
        self.stderr.release()
        return 0

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class _NeverStderr:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def readline(self) -> bytes:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self._events.append("stderr-cancelled")
            raise
        return b""


class _ProcessWithNeverStderr:
    def __init__(self, events: list[str]) -> None:
        self.pid = 4322
        self.returncode: int | None = 0
        self.stdin = _MockStdin()
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_eof()
        self.stderr = _NeverStderr(events)

    async def wait(self) -> int:
        return 0

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


@pytest.mark.asyncio
async def test_transport_start_tracks_app_server_pid_and_shell_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    proc = _MockProcess(pid=7321)

    async def _fake_spawn(*, cwd: str, env: dict[str, str]):
        assert cwd == str(tmp_path)
        assert env["CODEX_HOME"] == str(tmp_path)
        return proc

    monkeypatch.setattr(mod, "_build_appserver_command", lambda: (["codex.cmd"], True))
    monkeypatch.setattr(mod, "_spawn_appserver_process", _fake_spawn)

    transport = mod._CodexJSONRPCTransport(cwd=str(tmp_path), codex_home=tmp_path)
    await transport.start()

    assert transport._app_server_pid == 7321
    assert transport._use_shell is True

    await transport.close()


@pytest.mark.asyncio
async def test_transport_close_drains_stderr_before_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    events: list[str] = []
    proc = _ProcessWithDelayedStderr(events)

    async def _fake_spawn(*, cwd: str, env: dict[str, str]):
        del cwd, env
        return proc

    monkeypatch.setattr(mod, "_spawn_appserver_process", _fake_spawn)

    transport = mod._CodexJSONRPCTransport(cwd=str(tmp_path), codex_home=tmp_path)
    await transport.start()
    await asyncio.sleep(0)

    await transport.close()

    assert "stderr-cancelled" not in events
    assert transport.stderr_excerpt() == "late app-server stderr"
    assert events.index("process-wait") < events.index("stderr-line-returned")


@pytest.mark.asyncio
async def test_transport_close_cancels_stderr_only_after_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    events: list[str] = []
    proc = _ProcessWithNeverStderr(events)

    async def _fake_spawn(*, cwd: str, env: dict[str, str]):
        del cwd, env
        return proc

    original_wait_for = asyncio.wait_for

    async def _fake_wait_for(awaitable, timeout):
        if timeout == 2.0:
            assert awaitable is transport._stderr_task
            raise asyncio.TimeoutError
        return await original_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(mod, "_spawn_appserver_process", _fake_spawn)
    monkeypatch.setattr(mod.asyncio, "wait_for", _fake_wait_for)

    transport = mod._CodexJSONRPCTransport(cwd=str(tmp_path), codex_home=tmp_path)
    await transport.start()
    await asyncio.sleep(0)

    await transport.close()

    assert events == ["stderr-cancelled"]


@pytest.mark.asyncio
async def test_transport_close_uses_tracked_teardown_when_flag_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    proc = _MockProcess(pid=8456)

    async def _fake_spawn(*, cwd: str, env: dict[str, str]):
        del cwd, env
        return proc

    async def _fake_teardown(*args, **kwargs) -> None:
        del args, kwargs
        return None

    teardown = AsyncMock(side_effect=_fake_teardown)

    monkeypatch.setattr(mod, "_build_appserver_command", lambda: (["codex.cmd"], True))
    monkeypatch.setattr(mod, "_spawn_appserver_process", _fake_spawn)
    monkeypatch.setattr(mod, "_perform_app_server_teardown", teardown)

    transport = mod._CodexJSONRPCTransport(
        cwd=str(tmp_path),
        codex_home=tmp_path,
        app_server_teardown_enabled=True,
    )
    await transport.start()
    await transport.close()
    await transport.close()

    assert teardown.await_count == 1
    args = teardown.await_args
    assert args.args == (proc,)
    assert args.kwargs["pid"] == 8456
    assert args.kwargs["use_shell"] is True


@pytest.mark.asyncio
async def test_transport_close_preserves_legacy_path_when_flag_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    proc = _MockProcess(pid=9150)

    async def _fake_spawn(*, cwd: str, env: dict[str, str]):
        del cwd, env
        return proc

    teardown = AsyncMock()

    monkeypatch.setattr(mod, "_build_appserver_command", lambda: (["codex.cmd"], True))
    monkeypatch.setattr(mod, "_spawn_appserver_process", _fake_spawn)
    monkeypatch.setattr(mod, "_perform_app_server_teardown", teardown)

    transport = mod._CodexJSONRPCTransport(
        cwd=str(tmp_path),
        codex_home=tmp_path,
        app_server_teardown_enabled=False,
    )
    await transport.start()
    await transport.close()

    assert teardown.await_count == 0
    assert proc.wait_calls == 1


@pytest.mark.asyncio
async def test_perform_app_server_teardown_uses_taskkill_for_windows_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    proc = _MockProcess(pid=36704)
    kill_tree = AsyncMock()

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_kill_process_tree_windows", kill_tree)

    await mod._perform_app_server_teardown(proc, pid=36704, use_shell=True)

    kill_tree.assert_awaited_once_with(36704, timeout_seconds=5.0)
    assert proc.terminate_calls == 0
    assert proc.kill_calls == 0


@pytest.mark.asyncio
async def test_perform_app_server_teardown_noops_for_dead_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    proc = _MockProcess(pid=5000, returncode=0)
    monkeypatch.setattr(mod.sys, "platform", "linux")

    await mod._perform_app_server_teardown(proc, pid=5000, use_shell=False)

    assert proc.wait_calls == 0
    assert proc.terminate_calls == 0
    assert proc.kill_calls == 0


@pytest.mark.asyncio
async def test_perform_app_server_teardown_terminates_non_windows_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    proc = _MockProcess(pid=6001)
    monkeypatch.setattr(mod.sys, "platform", "linux")

    await mod._perform_app_server_teardown(proc, pid=6001, use_shell=False)

    assert proc.terminate_calls == 1
    assert proc.kill_calls == 0
    assert proc.wait_calls == 1


@pytest.mark.asyncio
async def test_transport_close_terminates_real_subprocess_when_flag_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from agent_team_v15 import codex_appserver as mod

    monkeypatch.setattr(
        mod,
        "_build_appserver_command",
        lambda: ([sys.executable, "-c", "import time; time.sleep(60)"], False),
    )

    transport = mod._CodexJSONRPCTransport(
        cwd=str(tmp_path),
        codex_home=tmp_path,
        app_server_teardown_enabled=True,
    )
    await transport.start()

    proc = transport.process
    assert proc is not None
    assert proc.returncode is None

    await transport.close()

    assert proc.returncode is not None
