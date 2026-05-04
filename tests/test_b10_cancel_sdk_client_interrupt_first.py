"""B10 — _cancel_sdk_client must call interrupt() before disconnect().

Locks the contract that any SDK-client teardown drives an in-flight
``client.interrupt()`` BEFORE ``client.disconnect()`` so an active
turn is cancelled instead of being held until the parent process exits.
Each call lives in its own try/except so a failing interrupt cannot
prevent the disconnect from running.
"""
from __future__ import annotations

import inspect

import pytest
from unittest.mock import AsyncMock

from agent_team_v15.cli import _cancel_sdk_client


def test_cancel_sdk_client_static_source_lock():
    """Static-source lock: body must contain BOTH ``await client.interrupt()``
    AND ``await client.disconnect()``, with ``interrupt`` ordered FIRST.
    """
    source = inspect.getsource(_cancel_sdk_client)
    interrupt_pos = source.find("await client.interrupt()")
    disconnect_pos = source.find("await client.disconnect()")
    assert interrupt_pos != -1, (
        "_cancel_sdk_client body missing `await client.interrupt()`"
    )
    assert disconnect_pos != -1, (
        "_cancel_sdk_client body missing `await client.disconnect()`"
    )
    assert interrupt_pos < disconnect_pos, (
        "`await client.interrupt()` must be ordered BEFORE "
        "`await client.disconnect()` in _cancel_sdk_client body"
    )


@pytest.mark.asyncio
async def test_cancel_sdk_client_calls_interrupt_then_disconnect_in_order():
    """Behavioural: interrupt() must be awaited before disconnect()."""
    call_order: list[str] = []
    client = AsyncMock()
    client.interrupt.side_effect = lambda: call_order.append("interrupt")
    client.disconnect.side_effect = lambda: call_order.append("disconnect")

    await _cancel_sdk_client(client)

    assert call_order == ["interrupt", "disconnect"], (
        f"expected interrupt-then-disconnect, got {call_order}"
    )
    client.interrupt.assert_awaited_once()
    client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_sdk_client_disconnect_runs_when_interrupt_raises():
    """Interrupt-failure isolation: when interrupt() raises, disconnect()
    must STILL run. No exception propagates."""
    client = AsyncMock()
    client.interrupt.side_effect = RuntimeError("interrupt boom")

    await _cancel_sdk_client(client)

    client.interrupt.assert_awaited_once()
    client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_sdk_client_swallows_disconnect_failure():
    """Disconnect-failure isolation: when disconnect() raises, the
    helper must NOT propagate the exception (best-effort teardown)."""
    client = AsyncMock()
    client.disconnect.side_effect = RuntimeError("disconnect boom")

    # Must not raise.
    await _cancel_sdk_client(client)

    client.interrupt.assert_awaited_once()
    client.disconnect.assert_awaited_once()
