"""Tests for Bug #20: Codex app-server transport migration."""
import importlib
import inspect
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_team_v15"


# ---------------------------------------------------------------------------
# Module existence and public API
# ---------------------------------------------------------------------------

def test_codex_appserver_module_exists():
    """The codex_appserver module must be importable."""
    import agent_team_v15.codex_appserver as mod
    assert mod is not None


def test_codex_appserver_execute_codex_function_exists():
    """execute_codex must be a callable in codex_appserver."""
    from agent_team_v15.codex_appserver import execute_codex
    assert callable(execute_codex)
    assert inspect.iscoroutinefunction(execute_codex), "execute_codex must be async"


def test_codex_appserver_is_codex_available_function_exists():
    """is_codex_available must be a callable in codex_appserver."""
    from agent_team_v15.codex_appserver import is_codex_available
    assert callable(is_codex_available)


# ---------------------------------------------------------------------------
# CodexOrphanToolError
# ---------------------------------------------------------------------------

def test_codex_orphan_tool_error_exception():
    """CodexOrphanToolError must exist with tool_name, tool_id,
    age_seconds, and orphan_count fields."""
    from agent_team_v15.codex_appserver import CodexOrphanToolError

    err = CodexOrphanToolError(
        tool_name="shell",
        tool_id="tu-123",
        age_seconds=350.0,
        orphan_count=2,
    )
    assert err.tool_name == "shell"
    assert err.tool_id == "tu-123"
    assert err.age_seconds == 350.0
    assert err.orphan_count == 2
    assert isinstance(err, Exception)
    assert "shell" in str(err)


# ---------------------------------------------------------------------------
# Config flags
# ---------------------------------------------------------------------------

def test_codex_transport_mode_flag_exists():
    """V18Config must have codex_transport_mode with default 'exec'."""
    from agent_team_v15.config import V18Config

    cfg = V18Config()
    assert hasattr(cfg, "codex_transport_mode")
    assert cfg.codex_transport_mode == "exec"


def test_codex_orphan_timeout_flag_exists():
    """V18Config must have codex_orphan_tool_timeout_seconds with default 300."""
    from agent_team_v15.config import V18Config

    cfg = V18Config()
    assert hasattr(cfg, "codex_orphan_tool_timeout_seconds")
    assert cfg.codex_orphan_tool_timeout_seconds == 300


# ---------------------------------------------------------------------------
# Provider router integration
# ---------------------------------------------------------------------------

def test_provider_router_imports_codex_orphan_error():
    """provider_router must gracefully import CodexOrphanToolError from
    codex_appserver.  The import uses a try/except so that exec-only
    environments don't crash."""
    source = (SRC_DIR / "provider_router.py").read_text(encoding="utf-8")
    assert "CodexOrphanToolError" in source
    # The graceful fallback pattern
    assert "except ImportError" in source


def test_provider_router_catches_watchdog_timeout_for_fallback():
    """WaveWatchdogTimeoutError must be caught in the Codex execution path
    and route to _claude_fallback (NOT re-raise)."""
    source = (SRC_DIR / "provider_router.py").read_text(encoding="utf-8")
    assert "except WaveWatchdogTimeoutError" in source
    # After catching, it should call _claude_fallback
    idx = source.find("except WaveWatchdogTimeoutError")
    assert idx != -1
    region_after = source[idx:idx + 500]
    assert "_claude_fallback" in region_after


def test_provider_router_catches_orphan_error_for_fallback():
    """CodexOrphanToolError must be caught in the Codex execution path
    and route to _claude_fallback."""
    source = (SRC_DIR / "provider_router.py").read_text(encoding="utf-8")
    assert "_CodexOrphanToolError" in source
    idx = source.find("except _CodexOrphanToolError")
    assert idx != -1
    region_after = source[idx:idx + 800]
    assert "_claude_fallback" in region_after


# ---------------------------------------------------------------------------
# Transport factory routing
# ---------------------------------------------------------------------------

def test_codex_transport_factory_routes_by_flag():
    """When codex_transport_mode is 'app-server', the app-server module should
    be used; when 'exec', the original codex_transport module is used.
    We verify both modules have the required execute_codex API."""
    from agent_team_v15 import codex_appserver, codex_transport

    # Both modules must expose execute_codex
    assert hasattr(codex_appserver, "execute_codex")
    assert hasattr(codex_transport, "execute_codex")
    # Both must expose is_codex_available
    assert hasattr(codex_appserver, "is_codex_available")
    assert hasattr(codex_transport, "is_codex_available")


def test_old_codex_transport_preserved():
    """codex_transport.py must still be importable with unchanged public API:
    execute_codex, is_codex_available, CodexConfig, CodexResult."""
    from agent_team_v15.codex_transport import (
        execute_codex,
        is_codex_available,
        CodexConfig,
        CodexResult,
    )
    assert callable(execute_codex)
    assert callable(is_codex_available)
    assert inspect.isclass(CodexConfig)
    assert inspect.isclass(CodexResult)


def test_codex_appserver_reuses_codex_config_and_result():
    """codex_appserver must reuse CodexConfig and CodexResult from
    codex_transport so callers see identical types."""
    from agent_team_v15.codex_appserver import CodexConfig as AppConfig
    from agent_team_v15.codex_appserver import CodexResult as AppResult
    from agent_team_v15.codex_transport import CodexConfig, CodexResult

    assert AppConfig is CodexConfig, "codex_appserver.CodexConfig is not the same class"
    assert AppResult is CodexResult, "codex_appserver.CodexResult is not the same class"


# ---------------------------------------------------------------------------
# F-RT-001 — orphan interrupt is actually dispatched
# ---------------------------------------------------------------------------

import asyncio
import time


class _FakeAppServerClient:
    """Minimal async-safe stand-in for AppServerClient used by orphan tests."""

    def __init__(self) -> None:
        self.interrupt_calls: list[tuple[str, str]] = []

    def turn_interrupt(self, thread_id: str, turn_id: str) -> None:
        self.interrupt_calls.append((thread_id, turn_id))


def test_send_turn_interrupt_prefers_typed_method():
    """_send_turn_interrupt must call client.turn_interrupt when present."""
    from agent_team_v15.codex_appserver import _send_turn_interrupt

    client = _FakeAppServerClient()
    ok = asyncio.run(_send_turn_interrupt(client, "thr_1", "turn_1"))
    assert ok is True
    assert client.interrupt_calls == [("thr_1", "turn_1")]


def test_send_turn_interrupt_falls_back_to_send_request():
    """When turn_interrupt is absent, _send_turn_interrupt must fall back to
    the generic send_request RPC shape ('turn/interrupt', {threadId, turnId})."""
    from agent_team_v15.codex_appserver import _send_turn_interrupt

    calls: list[tuple[str, dict]] = []

    class _LowLevelClient:
        def send_request(self, method: str, params: dict) -> None:
            calls.append((method, dict(params)))

    ok = asyncio.run(_send_turn_interrupt(_LowLevelClient(), "thr_2", "turn_2"))
    assert ok is True
    assert calls == [("turn/interrupt", {"threadId": "thr_2", "turnId": "turn_2"})]


def test_send_turn_interrupt_skips_empty_ids():
    """_send_turn_interrupt must never dispatch when thread/turn id is empty."""
    from agent_team_v15.codex_appserver import _send_turn_interrupt

    client = _FakeAppServerClient()
    assert asyncio.run(_send_turn_interrupt(client, "", "turn_1")) is False
    assert asyncio.run(_send_turn_interrupt(client, "thr_1", "")) is False
    assert client.interrupt_calls == []


def test_monitor_orphans_sends_turn_interrupt_on_stall():
    """Stall injection: with a stale entry in pending_tool_starts the monitor
    must register exactly one orphan event and fire turn/interrupt."""
    from agent_team_v15.codex_appserver import _OrphanWatchdog, _monitor_orphans

    watchdog = _OrphanWatchdog(timeout_seconds=1.0, max_orphan_events=2)
    # Inject a stall that is already past the timeout.
    watchdog.pending_tool_starts["tu-stall-1"] = {
        "tool_name": "shell",
        "started_monotonic": time.monotonic() - 10.0,
    }
    client = _FakeAppServerClient()

    sent = asyncio.run(
        _monitor_orphans(
            client,
            "thr_x",
            "turn_x",
            watchdog,
            check_interval_seconds=0.05,
        )
    )
    assert sent is True
    assert watchdog.orphan_event_count == 1
    assert watchdog.last_orphan_tool_name == "shell"
    assert watchdog.last_orphan_tool_id == "tu-stall-1"
    assert client.interrupt_calls == [("thr_x", "turn_x")]


def test_monitor_orphans_dedupes_same_tool_id():
    """check_orphans must skip tool_ids already registered so orphan_event_count
    tracks distinct stalls — not spin once per poll on the same stuck tool."""
    from agent_team_v15.codex_appserver import _OrphanWatchdog

    watchdog = _OrphanWatchdog(timeout_seconds=1.0, max_orphan_events=2)
    watchdog.pending_tool_starts["tu-stall-1"] = {
        "tool_name": "shell",
        "started_monotonic": time.monotonic() - 10.0,
    }

    is_orphan, _, tool_id, _ = watchdog.check_orphans()
    assert is_orphan
    watchdog.register_orphan_event("shell", tool_id, 10.0)
    assert watchdog.orphan_event_count == 1
    # Still past timeout, but already registered — must not surface again.
    is_orphan_again, _, _, _ = watchdog.check_orphans()
    assert is_orphan_again is False


def test_monitor_orphans_second_stall_exhausts_budget():
    """Two distinct stalls must drive orphan_event_count to max_orphan_events,
    marking the watchdog budget_exhausted — this is the CodexOrphanToolError
    containment gate the main loop checks after turn completion."""
    from agent_team_v15.codex_appserver import _OrphanWatchdog, _monitor_orphans

    watchdog = _OrphanWatchdog(timeout_seconds=1.0, max_orphan_events=2)
    # First stall
    watchdog.pending_tool_starts["tu-stall-1"] = {
        "tool_name": "shell",
        "started_monotonic": time.monotonic() - 10.0,
    }
    client = _FakeAppServerClient()
    asyncio.run(
        _monitor_orphans(
            client, "thr", "turn1", watchdog, check_interval_seconds=0.05,
        )
    )
    assert watchdog.orphan_event_count == 1
    assert watchdog.budget_exhausted is False

    # Simulate completion of the first stalled tool + arrival of a second stall
    watchdog.record_complete("tu-stall-1")
    watchdog.pending_tool_starts["tu-stall-2"] = {
        "tool_name": "apply_patch",
        "started_monotonic": time.monotonic() - 10.0,
    }
    asyncio.run(
        _monitor_orphans(
            client, "thr", "turn2", watchdog, check_interval_seconds=0.05,
        )
    )
    assert watchdog.orphan_event_count == 2
    assert watchdog.budget_exhausted is True
    assert client.interrupt_calls == [("thr", "turn1"), ("thr", "turn2")]


def test_monitor_orphans_no_stall_cancellable():
    """With no orphans, the monitor must keep polling until cancelled — it
    must not spin-loop or return early."""
    from agent_team_v15.codex_appserver import _OrphanWatchdog, _monitor_orphans

    watchdog = _OrphanWatchdog(timeout_seconds=300.0, max_orphan_events=2)
    client = _FakeAppServerClient()

    async def _drive() -> None:
        task = asyncio.create_task(
            _monitor_orphans(
                client, "thr", "turn", watchdog, check_interval_seconds=0.05,
            )
        )
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_drive())
    assert watchdog.orphan_event_count == 0
    assert client.interrupt_calls == []


def test_process_streaming_event_does_not_register_orphan():
    """Regression guard: _process_streaming_event must NOT increment
    orphan_event_count — that responsibility moved to the concurrent
    monitor so the callback (running in an executor thread) cannot race
    the event loop or double-count."""
    from agent_team_v15.codex_appserver import (
        _OrphanWatchdog,
        _TokenAccumulator,
        _process_streaming_event,
    )

    watchdog = _OrphanWatchdog(timeout_seconds=1.0, max_orphan_events=2)
    # Seed a past-timeout pending tool.
    watchdog.pending_tool_starts["tu-old"] = {
        "tool_name": "shell",
        "started_monotonic": time.monotonic() - 10.0,
    }
    tokens = _TokenAccumulator()

    # A benign streaming event — the orphan is past timeout but this callback
    # must NOT register/increment.
    _process_streaming_event(
        {"method": "item/agentMessage/delta", "params": {}},
        watchdog,
        tokens,
        None,
    )
    assert watchdog.orphan_event_count == 0


def test_execute_turn_does_not_block_event_loop(tmp_path, monkeypatch):
    """_execute_turn must run wait_for_turn_completed in an executor so the
    event loop stays responsive — verified by driving a concurrent task
    while the synchronous wait is pretending to block."""
    from agent_team_v15 import codex_appserver as mod
    from agent_team_v15.codex_transport import CodexConfig

    class _Turn:
        class _T:
            id = "turn_1"
            status = "completed"
        turn = _T()
        status = "completed"
        final_response = "done"
        error = None

    class _Thread:
        class _T:
            id = "thr_1"
        thread = _T()

    class _Init:
        userAgent = "test"

    wait_started = asyncio.Event()
    wait_release = asyncio.Event()
    concurrent_ran: dict[str, bool] = {"yes": False}

    class _FakeClient:
        def __init__(self, *a, **kw) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def start(self):
            return None

        def initialize(self):
            return _Init()

        def thread_start(self, *_a, **_kw):
            return _Thread()

        def turn_start(self, *_a, **_kw):
            return _Turn()

        def wait_for_turn_completed(self, turn_id, on_event=None):
            # Signal via loop.call_soon_threadsafe — we're in a worker thread.
            loop.call_soon_threadsafe(wait_started.set)
            # Block on a threading.Event so the test can verify concurrency.
            release_flag.wait(timeout=5)
            return _Turn()

        def turn_interrupt(self, *_a, **_kw):
            return None

    import threading as _threading
    release_flag = _threading.Event()

    fake_module = type("_M", (), {
        "AppServerClient": _FakeClient,
        "AppServerConfig": lambda **kw: type("_C", (), kw)(),
    })
    import sys
    monkeypatch.setitem(sys.modules, "codex_app_server", fake_module)

    async def _run():
        nonlocal loop
        loop = asyncio.get_running_loop()

        async def _concurrent():
            await wait_started.wait()
            # Prove the event loop is alive while wait_for_turn_completed
            # is blocking in its executor thread.
            concurrent_ran["yes"] = True
            release_flag.set()

        concurrent_task = asyncio.create_task(_concurrent())
        result = await mod._execute_turn(
            "hi",
            str(tmp_path),
            CodexConfig(),
            tmp_path,
            orphan_timeout_seconds=300.0,
            orphan_check_interval_seconds=0.05,
        )
        await concurrent_task
        return result

    loop = None  # noqa: F841
    result = asyncio.run(_run())
    assert concurrent_ran["yes"] is True, (
        "event loop was blocked while wait_for_turn_completed was sync-waiting"
    )
    assert result.success is True
