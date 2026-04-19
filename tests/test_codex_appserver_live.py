"""Live integration test for the Codex app-server transport."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_team_v15.codex_appserver import (
    _CodexAppServerClient,
    _MessageAccumulator,
    _OrphanWatchdog,
    _TokenAccumulator,
    _wait_for_turn_completion,
    is_codex_available,
)
from agent_team_v15.codex_transport import CodexConfig, CodexResult, cleanup_codex_home, create_codex_home


@pytest.mark.codex_live
@pytest.mark.asyncio
async def test_app_server_thread_start_real_codex(tmp_path) -> None:
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
        await client.close()
        cleanup_codex_home(codex_home)
