"""Live integration test for the Codex app-server transport."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
import subprocess
import sys

import pytest

import agent_team_v15.codex_appserver as codex_appserver_module
from agent_team_v15.codex_captures import CodexCaptureMetadata, build_capture_paths
from agent_team_v15.codex_appserver import (
    _CodexAppServerClient,
    _MessageAccumulator,
    _OrphanWatchdog,
    _TokenAccumulator,
    execute_codex,
    _wait_for_turn_completion,
    is_codex_available,
)
from agent_team_v15.codex_transport import CodexConfig, CodexResult, cleanup_codex_home, create_codex_home


def _list_codex_related_process_ids() -> set[int]:
    """Return Windows Codex/node PIDs associated with the global Codex CLI."""
    if sys.platform != "win32":
        return set()

    script = """
    Get-CimInstance Win32_Process |
      Where-Object {
        ($_.Name -in @('codex.exe', 'node.exe')) -and
        $_.CommandLine -and
        (($_.CommandLine -match '@openai\\\\codex') -or ($_.CommandLine -match 'codex-win32-x64'))
      } |
      Select-Object -ExpandProperty ProcessId
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.add(int(line))
        except ValueError:
            continue
    return pids


def _cleanup_new_codex_processes(baseline_pids: set[int]) -> None:
    """Kill Codex-related PIDs that appeared during a live test run."""
    if sys.platform != "win32":
        return

    current_pids = _list_codex_related_process_ids()
    for pid in sorted(current_pids - baseline_pids, reverse=True):
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


async def _cleanup_spawned_appserver_processes(processes: list[object]) -> None:
    """Best-effort cleanup for app-server subprocesses spawned by live tests."""
    for proc in processes:
        if proc is None or getattr(proc, "returncode", None) is not None:
            continue

        terminate = getattr(proc, "terminate", None)
        wait = getattr(proc, "wait", None)
        kill = getattr(proc, "kill", None)
        pid = getattr(proc, "pid", None)

        try:
            if callable(terminate):
                terminate()
            elif sys.platform == "win32" and pid:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

        if callable(wait):
            try:
                await asyncio.wait_for(wait(), timeout=5.0)
                continue
            except asyncio.TimeoutError:
                pass
            except Exception:
                continue

        try:
            if callable(kill):
                kill()
            elif sys.platform == "win32" and pid:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            continue

        if callable(wait):
            with suppress(Exception):
                await asyncio.wait_for(wait(), timeout=5.0)


@pytest.fixture
def tracked_appserver_processes(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Track app-server subprocesses so teardown can clean up orphans."""
    spawned: list[object] = []
    baseline_pids = _list_codex_related_process_ids()
    original_spawn = codex_appserver_module._spawn_appserver_process

    async def _tracking_spawn(*, cwd: str, env: dict[str, str]):
        proc = await original_spawn(cwd=cwd, env=env)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(codex_appserver_module, "_spawn_appserver_process", _tracking_spawn)
    yield spawned
    asyncio.run(_cleanup_spawned_appserver_processes(spawned))
    _cleanup_new_codex_processes(baseline_pids)


@pytest.mark.codex_live
@pytest.mark.asyncio
async def test_app_server_thread_start_real_codex(tmp_path, tracked_appserver_processes) -> None:
    """Proves the canonical transport dispatches through real codex app-server."""
    if not is_codex_available():
        pytest.skip("codex CLI not available")

    config = CodexConfig(model="gpt-5.4", max_retries=0, reasoning_effort="low")
    codex_home = create_codex_home(config)
    client = _CodexAppServerClient(cwd=str(tmp_path), config=config, codex_home=codex_home)
    tokens = _TokenAccumulator()
    messages = _MessageAccumulator()
    watchdog = _OrphanWatchdog(timeout_seconds=300.0, max_orphan_events=2)
    thread_id = ""

    try:
        await client.start()
        init_result = await client.initialize()
        assert Path(str(init_result["codexHome"]).removeprefix("\\\\?\\")).resolve() == codex_home.resolve()

        thread_result = await client.thread_start()
        thread_id = thread_result["thread"]["id"]
        assert thread_id

        turn_result = await client.turn_start(
            thread_id,
            "Reply with exactly OK and nothing else.",
        )
        turn_id = turn_result["turn"]["id"]
        assert turn_id

        completed_turn = await asyncio.wait_for(
            _wait_for_turn_completion(
                client,
                thread_id=thread_id,
                turn_id=turn_id,
                watchdog=watchdog,
                tokens=tokens,
                progress_callback=None,
                messages=messages,
            ),
            timeout=180.0,
        )

        assert completed_turn["status"] == "completed"
        assert messages.final_message().strip() == "OK"

        await client.thread_archive(thread_id)

        cleanup_seen = False
        try:
            while True:
                notification = await asyncio.wait_for(client.next_notification(), timeout=2.0)
                if notification.get("method") == "thread/archived":
                    if notification.get("params", {}).get("threadId") == thread_id:
                        cleanup_seen = True
                        break
                if notification.get("method") == "thread/status/changed":
                    params = notification.get("params", {})
                    if (
                        params.get("threadId") == thread_id
                        and params.get("status", {}).get("type") == "notLoaded"
                    ):
                        cleanup_seen = True
                        break
        except asyncio.TimeoutError:
            pass

        assert cleanup_seen, "thread cleanup notification was not observed"

        result = CodexResult(model=config.model)
        tokens.apply_to(result, config)
        assert result.cost_usd < 0.05
    finally:
        if thread_id:
            with suppress(Exception):
                await client.thread_archive(thread_id)
        await client.close()
        cleanup_codex_home(codex_home)


@pytest.mark.codex_live
@pytest.mark.asyncio
async def test_app_server_execute_codex_writes_file_with_workspace_write_sandbox(
    tmp_path,
    tracked_appserver_processes,
) -> None:
    if not is_codex_available():
        pytest.skip("codex CLI not available")

    target = tmp_path / "h3d_live_test.txt"
    config = CodexConfig(
        model="gpt-5.4-mini",
        max_retries=0,
        reasoning_effort="low",
        timeout_seconds=30,
    )
    config.pricing["gpt-5.4-mini"] = {
        "input": 0.75,
        "cached_input": 0.075,
        "output": 4.50,
    }
    setattr(config, "sandbox_writable_enabled", True)
    setattr(config, "sandbox_mode", "workspaceWrite")

    capture_metadata = CodexCaptureMetadata(
        milestone_id="phase-h3d-live",
        wave_letter="B",
    )
    capture_paths = build_capture_paths(tmp_path, capture_metadata)
    codex_home = create_codex_home(config)

    try:
        result = await execute_codex(
            (
                "Create a new file named h3d_live_test.txt in the current working directory "
                "containing exactly the single line hello. Then reply with exactly WROTE."
            ),
            str(tmp_path),
            config,
            codex_home,
            capture_enabled=True,
            capture_metadata=capture_metadata,
        )

        assert result.success is True
        assert target.exists()
        assert target.read_text(encoding="utf-8").lstrip("\ufeff").strip() == "hello"
        assert result.duration_seconds < 30
        assert result.cost_usd < 0.05

        protocol_text = capture_paths.protocol_path.read_text(encoding="utf-8")
        assert '"method":"thread/start"' in protocol_text
        assert '"sandbox":"workspace-write"' in protocol_text
    finally:
        cleanup_codex_home(codex_home)
