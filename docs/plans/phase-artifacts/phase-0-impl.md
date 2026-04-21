# Phase 0 — Codex App-Server Enhancements: Implementation Brief

## Phase Context

**What:** Close three gaps in the Codex app-server transport so Codex waves match Claude waves in observability and mid-turn control.

1. Add `turn/steer` JSON-RPC support to `_CodexAppServerClient` so the dynamic observer can inject mid-turn correction messages without interrupting.
2. Parse `turn/plan/updated` and `turn/diff/updated` notifications and stash the latest plan + diff on the per-run `_OrphanWatchdog` instance so the observer can peek at real Codex work-in-progress state.
3. Persist the Codex `thread_id` on `CodexResult` and accept an `existing_thread_id` param on `execute_codex()` / `_execute_once()` so compile_fix iterations in Wave B/D reuse the original thread rather than starting a fresh one.

**Why:** Downstream phases depend on these primitives:
- Phase 1 requires `turn_steer` to implement the orchestrator steer path.
- Phase 4 requires `codex_last_plan` and `codex_latest_diff` on `_OrphanWatchdog` so the observer peek can introspect Codex state.
- Wave B/D retry logic (later phase) requires thread persistence.

**Depends on:** Nothing — this is the first phase.

**Task order:** 0.1 → 0.2 → 0.3 (strict; 0.2 mutates the `_OrphanWatchdog` `__init__` signature that 0.3 also extends, so doing 0.2 first prevents a merge-style conflict on the same `__init__` body).

---

## Pre-Flight: Files to Read

Read ALL of these before writing code. Do not skim.

| File | Lines | What to look for |
| --- | --- | --- |
| `src/agent_team_v15/codex_appserver.py` | 1–90 | Imports, module constants, `CodexOrphanToolError`, `_CodexAppServerError`; confirm `from .codex_transport import CodexConfig, CodexResult` is already there |
| `src/agent_team_v15/codex_appserver.py` | 90–170 | `_OrphanWatchdog.__init__` existing signature: `def __init__(self, timeout_seconds: float = 300.0, max_orphan_events: int = 2) -> None:` and its instance attrs |
| `src/agent_team_v15/codex_appserver.py` | 600–720 | `_CodexAppServerClient.__init__`, `turn_start`, `turn_interrupt`, `thread_start`, `thread_archive`, `next_notification`, and the free-function `_send_turn_interrupt` (pattern to mirror for fail-open wrappers) |
| `src/agent_team_v15/codex_appserver.py` | 775–860 | `_process_streaming_event` — existing method dispatch (`item/started`, `item/completed`, `thread/tokenUsage/updated`, `model/rerouted`). New handlers for `turn/plan/updated` and `turn/diff/updated` go here |
| `src/agent_team_v15/codex_appserver.py` | 934–1000 | `_execute_once` signature and construction of `_OrphanWatchdog(timeout_seconds=..., max_orphan_events=...)` at line 950; `thread_result = await client.thread_start()` at 973 and `thread_id` assignment at 975 |
| `src/agent_team_v15/codex_appserver.py` | 1000–1098 | Remainder of `_execute_once` — how it uses `watchdog`, writes `result.*`, returns `result` |
| `src/agent_team_v15/codex_appserver.py` | 1101–1207 | `execute_codex()` outer wrapper that calls `_execute_once` |
| `src/agent_team_v15/codex_transport.py` | 60–90 | `CodexResult` dataclass fields — confirm no existing `thread_id` field |
| `tests/test_bug20_codex_appserver.py` | 1–120 | Mock process + stdin/stdout patterns, `_exact_request_bytes`, `_MockProcess.on_request`. Use this same style for new tests |
| `docs/plans/2026-04-20-dynamic-orchestrator-observer.md` | Phase 0 section (lines ~69–280) | Original plan spec (treat this brief as authoritative when they differ) |

---

## Pre-Flight: Context7 Research

These queries were already run for this brief; their authoritative findings are baked into the task specs below. If you need to re-verify, use:

1. `mcp__context7__resolve-library-id` with `libraryName="Codex"`, `query="codex app-server JSON-RPC turn/steer"`. Expected library ID: `/openai/codex`.
2. `mcp__context7__query-docs` with `libraryId="/openai/codex"`, `query="app-server JSON-RPC turn/steer turn/plan/updated turn/diff/updated notification schema"`.

**Confirmed protocol contracts (from `/openai/codex`, `codex-rs/app-server/README.md`):**

- `turn/steer` request params: `{ "threadId": str, "expectedTurnId": str, "input": [ {"type": "text", "text": str} ] }`. Note the field is `expectedTurnId`, NOT `turnId` (this is the key difference from `turn/interrupt`).
- `turn/plan/updated` notification params: `{ "turnId": str, "explanation": str (optional), "plan": [ { "step": str, "status": "pending"|"inProgress"|"completed" } ] }`. Note: canonical schema does NOT include `threadId`; we must tolerate its absence.
- `turn/diff/updated` notification params: `{ "threadId": str, "turnId": str, "diff": str }`.
- `thread/start` response: `{ "thread": { "id": str, "createdAt": int, "updatedAt": int } }` — the existing `_execute_once` already reads `thread.id` at line 975. No schema change needed on the response side.

---

## Pre-Flight: Sequential Thinking

The following prompt was run through `mcp__sequential-thinking__sequentialthinking` to decide how to extend `_OrphanWatchdog`:

> "Given that `_execute_once` in codex_appserver.py must pass `observer_config`, `requirements_text`, and `wave_letter` to `_OrphanWatchdog`, and that `_OrphanWatchdog.__init__` must NOT change its external constructor signature in a way that breaks existing callers (there are existing tests), what is the safest way to add these three fields? Analyze three options: (a) add as keyword-only args with None defaults to __init__; (b) add a separate configure_observer() method called after construction; (c) assign as instance attributes directly after construction in _execute_once, bypassing __init__ entirely."

**Conclusion: Option (a) — keyword-only args with safe defaults in `__init__`.**

Reasoning:
- Existing call site at line 950 uses only `timeout_seconds=` and `max_orphan_events=` keywords, so new keyword-only params with defaults are backward compatible.
- Attributes are always defined before any method call (including the notification handler), eliminating `AttributeError` risk.
- Option (b) introduces temporal coupling: `_process_streaming_event` could fire for `turn/plan/updated` before `configure_observer()` was called.
- Option (c) scatters attribute assignment across modules and is invisible to unit tests that construct `_OrphanWatchdog` standalone.
- `codex_last_plan` and `codex_latest_diff` (per correction #4) are *runtime state* set by the notification handler, not config, and should be initialized to empty defaults inside `__init__` — not accepted as constructor params.

---

## Corrections Applied (Phase 0)

| # | Correction | How it is applied in this brief |
| --- | --- | --- |
| 3 | `codex_last_plan` / `codex_latest_diff` belong on `_OrphanWatchdog` (codex_appserver.py), NOT on `_WaveWatchdogState` (wave_executor.py). | Task 0.2 adds them to `_OrphanWatchdog.__init__` only. A phase-gate grep must confirm `_WaveWatchdogState` is NOT touched. |
| 4 | `_OrphanWatchdog.__init__` must initialize `codex_last_plan=[]` and `codex_latest_diff=""` as instance attrs (not constructor params) — these are set by the notification handler after construction. | Task 0.2 initializes them as fixed empty defaults in `__init__`, never as parameters. |
| 5 | `execute_codex()` gets new param `existing_thread_id: str = ""`. | Task 0.3 adds this keyword-only param and threads it down to `_execute_once`. |
| 6 | `_execute_once()` gets 3 new params: `observer_config`, `requirements_text`, `wave_letter` — passed to `_OrphanWatchdog` at construction time. | Task 0.3 adds these as keyword-only params on `_execute_once` and forwards them to the `_OrphanWatchdog(...)` call, which accepts them (keyword-only, per Task 0.2). |

---

## Task-by-Task Implementation

### Task 0.1 — Add `turn_steer()` to `_CodexAppServerClient`

**Files to modify:** `src/agent_team_v15/codex_appserver.py`

**Files to create:** `tests/test_codex_appserver_steer.py`

#### Step 1 — Write the test first

Create `tests/test_codex_appserver_steer.py` with the following content. Do not run it yet; it will fail until Step 2.

```python
"""Tests for _CodexAppServerClient.turn_steer (Phase 0, Task 0.1)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent_team_v15.codex_appserver import _CodexAppServerClient
from agent_team_v15.codex_transport import CodexConfig


def test_client_exposes_turn_steer_method() -> None:
    assert hasattr(_CodexAppServerClient, "turn_steer"), (
        "_CodexAppServerClient must expose turn_steer() for Phase 0"
    )
    assert callable(getattr(_CodexAppServerClient, "turn_steer"))


def test_turn_steer_sends_correct_jsonrpc_payload(tmp_path) -> None:
    client = _CodexAppServerClient(
        cwd=str(tmp_path),
        config=CodexConfig(),
        codex_home=tmp_path,
    )

    captured: dict[str, Any] = {}

    async def fake_send_request(method: str, params: dict[str, Any]) -> dict[str, Any]:
        captured["method"] = method
        captured["params"] = params
        return {}

    client.send_request = fake_send_request  # type: ignore[assignment]

    asyncio.run(client.turn_steer("thread_abc", "turn_xyz", "Keep it brief"))

    assert captured["method"] == "turn/steer"
    assert captured["params"]["threadId"] == "thread_abc"
    assert captured["params"]["expectedTurnId"] == "turn_xyz"
    assert captured["params"]["input"] == [{"type": "text", "text": "Keep it brief"}]


def test_turn_steer_is_fail_open_on_transport_error(tmp_path) -> None:
    client = _CodexAppServerClient(
        cwd=str(tmp_path),
        config=CodexConfig(),
        codex_home=tmp_path,
    )

    async def boom(method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("transport offline")

    client.send_request = boom  # type: ignore[assignment]

    # Must NOT raise; fail-open is mandatory.
    asyncio.run(client.turn_steer("thread_abc", "turn_xyz", "hi"))
```

#### Step 2 — Implement `turn_steer`

Open `src/agent_team_v15/codex_appserver.py`. Locate `turn_interrupt` at line 681. Insert a new method immediately after it (before `thread_archive` at line 687).

Add this method verbatim:

```python
    async def turn_steer(self, thread_id: str, turn_id: str, message: str) -> None:
        """Inject a mid-turn steering message into an in-flight turn.

        Fail-open: any transport error is logged and swallowed. The observer
        must never be able to break the wave by failing to steer.
        """
        if not thread_id or not turn_id or not message:
            return
        try:
            await self.send_request(
                "turn/steer",
                {
                    "threadId": thread_id,
                    "expectedTurnId": turn_id,
                    "input": [{"type": "text", "text": message}],
                },
            )
        except Exception as exc:  # noqa: BLE001 - fail-open by contract
            logger.warning("turn/steer dispatch failed (fail-open): %s", exc)
```

Note the use of `expectedTurnId` (per the Codex app-server spec). Do NOT use `turnId` — that is the interrupt field, not the steer field.

#### Step 3 — Quick verify

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_codex_appserver_steer.py -v
```

All three tests must pass.

---

### Task 0.2 — Parse `turn/plan/updated` and `turn/diff/updated` notifications

**Files to modify:** `src/agent_team_v15/codex_appserver.py`

**Files to create:** `tests/test_codex_notifications.py`

#### Step 1 — Write the test first

Create `tests/test_codex_notifications.py`:

```python
"""Tests for Codex notification parsing + watchdog storage (Phase 0, Task 0.2)."""

from __future__ import annotations

import pytest

from agent_team_v15.codex_appserver import (
    CodexNotificationEvent,
    _OrphanWatchdog,
    _TokenAccumulator,
    _process_streaming_event,
    parse_codex_notification,
)


def test_parse_turn_plan_updated() -> None:
    raw = {
        "method": "turn/plan/updated",
        "params": {
            "turnId": "turn_123",
            "explanation": "Refactor plan",
            "plan": [
                {"step": "analyze", "status": "completed"},
                {"step": "implement", "status": "inProgress"},
            ],
        },
    }
    event = parse_codex_notification(raw)
    assert event is not None
    assert isinstance(event, CodexNotificationEvent)
    assert event.event_type == "turn/plan/updated"
    assert event.turn_id == "turn_123"
    assert event.payload["plan"][0]["status"] == "completed"


def test_parse_turn_diff_updated() -> None:
    raw = {
        "method": "turn/diff/updated",
        "params": {
            "threadId": "thread_abc",
            "turnId": "turn_123",
            "diff": "--- a/x\n+++ b/x\n@@\n-old\n+new",
        },
    }
    event = parse_codex_notification(raw)
    assert event is not None
    assert event.event_type == "turn/diff/updated"
    assert event.thread_id == "thread_abc"
    assert event.turn_id == "turn_123"
    assert "new" in event.payload["diff"]


def test_parse_unknown_notification_returns_none() -> None:
    assert parse_codex_notification({"method": "item/started", "params": {}}) is None
    assert parse_codex_notification({}) is None
    assert parse_codex_notification({"method": "turn/plan/updated"}) is None  # missing params


def test_process_streaming_event_stores_plan_on_watchdog() -> None:
    watchdog = _OrphanWatchdog()
    tokens = _TokenAccumulator()
    event = {
        "method": "turn/plan/updated",
        "params": {
            "turnId": "turn_123",
            "plan": [{"step": "analyze", "status": "completed"}],
        },
    }

    _process_streaming_event(event, watchdog, tokens, progress_callback=None)

    assert watchdog.codex_last_plan == [{"step": "analyze", "status": "completed"}]


def test_process_streaming_event_stores_diff_on_watchdog() -> None:
    watchdog = _OrphanWatchdog()
    tokens = _TokenAccumulator()
    event = {
        "method": "turn/diff/updated",
        "params": {
            "threadId": "thread_abc",
            "turnId": "turn_123",
            "diff": "--- a/x\n+++ b/x\n",
        },
    }

    _process_streaming_event(event, watchdog, tokens, progress_callback=None)

    assert watchdog.codex_latest_diff == "--- a/x\n+++ b/x\n"


def test_orphan_watchdog_defaults_have_plan_and_diff_fields() -> None:
    watchdog = _OrphanWatchdog()
    assert watchdog.codex_last_plan == []
    assert watchdog.codex_latest_diff == ""
```

#### Step 2 — Implement

**(a)** Add a module-level dataclass and parser near the top of `codex_appserver.py`, immediately after the `CodexDispatchError` class (currently line 73–74) and before the `is_codex_available` function at line 77. Also add `from dataclasses import dataclass` at the top of the file if it is not already imported (it is not currently — add it after line 13 `import threading`).

Insert at the top of the imports region:

```python
from dataclasses import dataclass, field
```

Insert after `CodexDispatchError` (around line 74):

```python
@dataclass
class CodexNotificationEvent:
    """Parsed Codex app-server streaming notification of interest."""

    event_type: str
    thread_id: str
    turn_id: str
    payload: dict[str, Any]


_CODEX_OBSERVED_NOTIFICATION_METHODS = frozenset(
    {"turn/plan/updated", "turn/diff/updated"}
)


def parse_codex_notification(event: dict[str, Any]) -> CodexNotificationEvent | None:
    """Parse a raw JSON-RPC notification into a CodexNotificationEvent.

    Returns ``None`` for notifications outside the observed set or for
    malformed payloads.
    """
    if not isinstance(event, dict):
        return None
    method = str(event.get("method", "") or "")
    if method not in _CODEX_OBSERVED_NOTIFICATION_METHODS:
        return None
    params = event.get("params")
    if not isinstance(params, dict):
        return None
    return CodexNotificationEvent(
        event_type=method,
        thread_id=str(params.get("threadId", "") or ""),
        turn_id=str(params.get("turnId", "") or ""),
        payload=params,
    )
```

**(b)** Extend `_OrphanWatchdog.__init__` (line 119). Replace the existing signature and body to add the observer config params (kw-only, correction #6) and the runtime-state fields (correction #3 / #4):

```python
    def __init__(
        self,
        timeout_seconds: float = 300.0,
        max_orphan_events: int = 2,
        *,
        observer_config: dict[str, Any] | None = None,
        requirements_text: str = "",
        wave_letter: str = "",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_orphan_events = max_orphan_events
        self._lock = threading.Lock()
        self.pending_tool_starts: dict[str, dict[str, Any]] = {}
        self.orphan_event_count: int = 0
        self.last_orphan_tool_name: str = ""
        self.last_orphan_tool_id: str = ""
        self.last_orphan_age: float = 0.0
        self._registered_orphans: set[str] = set()
        # Observer configuration (read by Phase 4 peek/steer path).
        self.observer_config: dict[str, Any] = dict(observer_config or {})
        self.requirements_text: str = requirements_text
        self.wave_letter: str = wave_letter
        # Runtime state populated by the streaming notification handler
        # (correction #3/#4 — instance attrs, not constructor params).
        self.codex_last_plan: list[dict[str, Any]] = []
        self.codex_latest_diff: str = ""
```

**(c)** Extend `_process_streaming_event` in `codex_appserver.py` (line 786). Add two new handler branches at the end, right after the `model/rerouted` branch that ends at line 852.

**Also add `return` to the existing `model/rerouted` handler.** The current handler (lines 847–852) ends with `logger.info(...)` but has no `return` statement. Without adding `return` after the logger call, `model/rerouted` events will fall through into the new `turn/plan/updated`/`turn/diff/updated` handlers. The fall-through is harmless (method string won't match), but it is incorrect. Add `return` on line 853 (after the closing `)` of `logger.info`) BEFORE inserting the new handlers below it.

Insert before the closing blank line of the function (after line 852):

```python
    if method == "turn/plan/updated":
        plan = params.get("plan")
        if isinstance(plan, list):
            watchdog.codex_last_plan = list(plan)
        return

    if method == "turn/diff/updated":
        diff = params.get("diff")
        if isinstance(diff, str):
            watchdog.codex_latest_diff = diff
        return
```

These handlers use only the `watchdog` parameter already in scope; no new arguments to the function are needed.

#### Step 3 — Quick verify

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_codex_notifications.py -v
```

All six tests must pass.

---

### Task 0.3 — Thread persistence + observer config wiring

**Files to modify:**
- `src/agent_team_v15/codex_transport.py` (add `thread_id` field to `CodexResult`)
- `src/agent_team_v15/codex_appserver.py` (extend `execute_codex` + `_execute_once`)

**Files to create:** `tests/test_codex_thread_persistence.py`

#### Step 1 — Write the test first

Create `tests/test_codex_thread_persistence.py`:

```python
"""Tests for Codex thread persistence + observer config wiring (Phase 0, Task 0.3)."""

from __future__ import annotations

import inspect

import pytest

from agent_team_v15.codex_appserver import _execute_once, execute_codex
from agent_team_v15.codex_transport import CodexResult


def test_codex_result_has_thread_id_field() -> None:
    result = CodexResult(success=True, exit_code=0, duration_seconds=0.0)
    assert hasattr(result, "thread_id")
    assert result.thread_id == ""


def test_codex_result_accepts_thread_id_kwarg() -> None:
    result = CodexResult(thread_id="thr_abc")
    assert result.thread_id == "thr_abc"


def test_execute_codex_accepts_existing_thread_id_param() -> None:
    sig = inspect.signature(execute_codex)
    assert "existing_thread_id" in sig.parameters
    param = sig.parameters["existing_thread_id"]
    assert param.default == ""
    assert param.kind == inspect.Parameter.KEYWORD_ONLY


def test_execute_once_accepts_observer_params() -> None:
    sig = inspect.signature(_execute_once)
    for name in ("existing_thread_id", "observer_config", "requirements_text", "wave_letter"):
        assert name in sig.parameters, f"_execute_once must accept {name}"
        assert sig.parameters[name].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["existing_thread_id"].default == ""
    assert sig.parameters["observer_config"].default is None
    assert sig.parameters["requirements_text"].default == ""
    assert sig.parameters["wave_letter"].default == ""
```

#### Step 2 — Implement

**(a)** In `src/agent_team_v15/codex_transport.py`, add a `thread_id` field to the `CodexResult` dataclass. Open lines 65–84; after the `retry_count: int = 0` line (line 84), add:

```python
    thread_id: str = ""
```

The final dataclass body must look like:

```python
@dataclass
class CodexResult:
    """Outcome of one ``codex exec`` run."""

    success: bool = False
    exit_code: int = -1
    duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    final_message: str = ""
    error: str = ""
    retry_count: int = 0
    thread_id: str = ""
```

**(b)** In `src/agent_team_v15/codex_appserver.py`, extend `_execute_once` (line 934). Replace the signature header with:

```python
async def _execute_once(
    prompt: str,
    cwd: str,
    config: CodexConfig,
    codex_home: Path,
    *,
    orphan_timeout_seconds: float = 300.0,
    orphan_max_events: int = 2,
    orphan_check_interval_seconds: float = 60.0,
    progress_callback: Callable[..., Any] | None = None,
    capture_session: CodexCaptureSession | None = None,
    existing_thread_id: str = "",
    observer_config: dict[str, Any] | None = None,
    requirements_text: str = "",
    wave_letter: str = "",
) -> CodexResult:
```

Then update the watchdog construction at line 950 to pass the observer fields through:

```python
    watchdog = _OrphanWatchdog(
        timeout_seconds=orphan_timeout_seconds,
        max_orphan_events=orphan_max_events,
        observer_config=observer_config,
        requirements_text=requirements_text,
        wave_letter=wave_letter,
    )
```

Replace the `thread_start()` block starting at line 973 so it honors `existing_thread_id`:

```python
        if existing_thread_id:
            thread_id = existing_thread_id
            logger.info("Thread reused: id=%s", thread_id)
        else:
            thread_result = await client.thread_start()
            thread = thread_result.get("thread", {})
            thread_id = str(thread.get("id", "") or "")
            _warn_if_cwd_mismatch(
                expected_cwd=cwd,
                thread_result=thread_result,
                config=config,
            )
            logger.info("Thread started: id=%s", thread_id)
        result.thread_id = thread_id
```

The `result.thread_id = thread_id` line guarantees the field is populated whether the thread was reused or created, before the turn loop begins.

**(c)** Extend `execute_codex` (line 1101). Replace its signature with:

```python
async def execute_codex(
    prompt: str,
    cwd: str,
    config: Optional[CodexConfig] = None,
    codex_home: Optional[Path] = None,
    *,
    progress_callback: Callable[..., Any] | None = None,
    orphan_timeout_seconds: float = 300.0,
    orphan_max_events: int = 2,
    capture_enabled: bool = False,
    capture_metadata: CodexCaptureMetadata | None = None,
    existing_thread_id: str = "",
    observer_config: dict[str, Any] | None = None,
    requirements_text: str = "",
    wave_letter: str = "",
) -> CodexResult:
```

Then update the inner `_execute_once(...)` call (around line 1151) to forward the four new kwargs:

```python
                result = await asyncio.wait_for(
                    _execute_once(
                        prompt,
                        cwd,
                        config,
                        codex_home,
                        orphan_timeout_seconds=orphan_timeout_seconds,
                        orphan_max_events=orphan_max_events,
                        progress_callback=progress_callback,
                        capture_session=capture_session,
                        existing_thread_id=existing_thread_id,
                        observer_config=observer_config,
                        requirements_text=requirements_text,
                        wave_letter=wave_letter,
                    ),
                    timeout=config.timeout_seconds,
                )
```

Finally, propagate the `thread_id` onto the aggregate so Wave B/D retry loops can re-use it. Find the `aggregate.success = True` branch inside `execute_codex` (around line 1173) and immediately before `aggregate.duration_seconds = round(...)` (line 1175) add:

```python
                aggregate.thread_id = result.thread_id
```

Also on the exit-after-all-attempts path (after the loop, around line 1202–1205), before `return aggregate`, add:

```python
    if not aggregate.thread_id:
        aggregate.thread_id = last_result.thread_id
```

#### Step 3 — Quick verify

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_codex_thread_persistence.py -v
```

All four tests must pass.

---

## Phase Gate: Verification Checklist

Run every command below. Each must produce the stated outcome before declaring Phase 0 done.

### Test run

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_codex_appserver_steer.py tests/test_codex_notifications.py tests/test_codex_thread_persistence.py -v
```

Expected: all tests pass.

### Regression check (existing Codex tests must still pass)

```bash
python -m pytest tests/test_bug20_codex_appserver.py -v
```

Expected: all existing tests still pass — no signature breakage.

### Symbol presence checks

```bash
python -c "from agent_team_v15.codex_appserver import _CodexAppServerClient; assert hasattr(_CodexAppServerClient, 'turn_steer')"
python -c "from agent_team_v15.codex_transport import CodexResult; r = CodexResult(success=True, exit_code=0, duration_seconds=0.0); assert hasattr(r, 'thread_id') and r.thread_id == ''"
python -c "from agent_team_v15.codex_appserver import CodexNotificationEvent, parse_codex_notification; assert parse_codex_notification({'method':'turn/plan/updated','params':{'turnId':'t','plan':[]}}).event_type == 'turn/plan/updated'"
python -c "from agent_team_v15.codex_appserver import _OrphanWatchdog; w = _OrphanWatchdog(); assert w.codex_last_plan == [] and w.codex_latest_diff == ''"
python -c "import inspect; from agent_team_v15.codex_appserver import execute_codex; assert 'existing_thread_id' in inspect.signature(execute_codex).parameters"
python -c "import inspect; from agent_team_v15.codex_appserver import _execute_once; p = inspect.signature(_execute_once).parameters; assert all(n in p for n in ('existing_thread_id','observer_config','requirements_text','wave_letter'))"
```

Each must exit 0 silently.

### Anti-pattern greps

```bash
# Correction #3: these fields must NOT appear in wave_executor.py
grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/wave_executor.py
# Expected: empty output.

# turn_steer must be fail-open (wrapped in try/except)
grep -nA8 "async def turn_steer" src/agent_team_v15/codex_appserver.py
# Expected: output contains "try:" and "except" within the method body.

# Must use expectedTurnId (not turnId) for steer
grep -n "expectedTurnId" src/agent_team_v15/codex_appserver.py
# Expected: exactly one occurrence inside turn_steer.
```

### Behavior checks

- Construct `_OrphanWatchdog()` with zero args — must not raise (backward compatibility).
- Construct `_OrphanWatchdog(timeout_seconds=10, max_orphan_events=1)` with only the original kwargs — must not raise.
- Feed a `turn/plan/updated` event through `_process_streaming_event`; `watchdog.codex_last_plan` must equal the `plan` list.
- Feed a `turn/diff/updated` event through `_process_streaming_event`; `watchdog.codex_latest_diff` must equal the `diff` string.

---

## Handoff State

After Phase 0 completion, downstream phases may assume all of the following:

1. `_CodexAppServerClient.turn_steer(thread_id: str, turn_id: str, message: str) -> None` exists in `src/agent_team_v15/codex_appserver.py`. It is **fail-open**: any transport/protocol exception is logged at WARNING and swallowed. It uses the JSON-RPC method `turn/steer` with params `{threadId, expectedTurnId, input}`.
2. `CodexNotificationEvent` dataclass (fields: `event_type`, `thread_id`, `turn_id`, `payload`) is importable from `agent_team_v15.codex_appserver`.
3. `parse_codex_notification(event: dict) -> CodexNotificationEvent | None` returns `None` for any non-observed method (anything other than `turn/plan/updated` / `turn/diff/updated`) or malformed payload.
4. `_OrphanWatchdog` instances expose:
   - `codex_last_plan: list[dict]` — latest plan snapshot (populated by `_process_streaming_event`).
   - `codex_latest_diff: str` — latest aggregated diff snapshot.
   - `observer_config: dict` — config dict forwarded from `_execute_once`.
   - `requirements_text: str` — forwarded requirements for this wave.
   - `wave_letter: str` — wave identifier (e.g., "B", "D").
   These fields are ALWAYS initialized (to empty defaults) by `__init__`, so downstream code may read them unconditionally.
5. `CodexResult.thread_id: str` field exists and defaults to `""`; it is populated by `_execute_once` as soon as the thread is created or reused.
6. `execute_codex()` accepts keyword-only params `existing_thread_id`, `observer_config`, `requirements_text`, `wave_letter`. When `existing_thread_id` is non-empty, `_execute_once` skips `thread/start` entirely and reuses the provided thread.
7. Correction #3 is preserved: `_WaveWatchdogState` in `wave_executor.py` is **NOT** touched in Phase 0. The plan/diff fields live exclusively on `_OrphanWatchdog`.
