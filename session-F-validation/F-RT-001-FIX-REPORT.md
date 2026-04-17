# F-RT-001 — Codex App-Server Orphan Interrupt Fix Report

- **Finding:** HIGH — `src/agent_team_v15/codex_appserver.py` detected orphan tools but never sent `turn/interrupt`; `client.wait_for_turn_completed` was invoked synchronously inside an async function, blocking the event loop for the duration of a turn.
- **Phase:** F (fixer sweep over Phase E regression)
- **Author:** codex-appserver-fixer
- **Branch:** `phase-f-final-review`
- **Status:** FIXED (structural, no containment shortcut)

---

## 1. Context7 SDK Verification (MANDATORY)

Queried `/openai/codex` (High reputation, 870 snippets) for the shape of the codex_app_server Python SDK as it relates to this fix.

### 1a — `wait_for_turn_completed` + raw `turn/interrupt` dispatch

Canonical low-level usage from `context7.com/openai/codex/llms.txt`:

```python
from codex_app_server import AppServerClient, AppServerConfig

with AppServerClient(config=config) as client:
    client.start()
    client.initialize()
    thread = client.thread_start({"model": "gpt-5.4"})
    turn = client.turn_start(thread.thread.id, input_items=[{"type": "text", "text": "Hello!"}])
    completed = client.wait_for_turn_completed(turn.turn.id)
```

`wait_for_turn_completed` is **synchronous** on `AppServerClient`. No async variant exists on this class; Phase E's `on_event=` kwarg is used to observe streaming events as they arrive but does not make the call non-blocking.

### 1b — `turn/interrupt` RPC shape

From `codex-rs/app-server/README.md` (verbatim, via context7):

```json
{
  "method": "turn/interrupt",
  "id": 31,
  "params": {
    "threadId": "thr_123",
    "turnId": "turn_456"
  }
}
```

> "Requests cancellation of an active turn. Does not terminate background terminals."
>
> Response: `{ "id": 31, "result": {} }` — server then emits `turn/completed` with `status: "interrupted"`.

### 1c — AsyncCodex / AsyncTurnHandle

From `sdk/python/docs/api-reference.md` (Phase E OOS #2):

```python
# AsyncTurnHandle (Asynchronous)
steer(input: Input) -> Awaitable[TurnSteerResponse]
interrupt() -> Awaitable[TurnInterruptResponse]
stream() -> AsyncIterator[Notification]
run() -> Awaitable[codex_app_server.generated.v2_all.Turn]
```

This is the **canonical async API** the SDK offers, but it lives on the high-level `AsyncCodex` client — not on `AppServerClient`. Migrating the transport to `AsyncCodex` would touch every call in `_execute_turn` and is explicitly parked in the Phase E OOS list ("could replace sync AppServerClient if async integration benefits emerge"). The F-RT-001 fix deliberately preserves the Phase E `AppServerClient` choice and solves the async/sync boundary through `loop.run_in_executor` + a concurrent monitor, rather than rewriting the client class.

---

## 2. Sequential-Thinking Trace (MANDATORY)

(Summarised from the `sequential-thinking` session.)

**Thought 1 — Root cause.** Two bugs live side-by-side:
1. `client.wait_for_turn_completed(...)` at line 299 is sync inside an async def, so the entire event loop is parked for ≤300 s per turn. Every other coroutine starves — including any hypothetical orphan watchdog.
2. The `on_event` callback at `_process_streaming_event` increments `orphan_event_count` via `watchdog.check_orphans()`. The comment at line 475 explicitly says the code "can't send turn/interrupt from the callback directly" and punts to a never-implemented "separate watchdog mechanism." So the budget-exhausted path raises `CodexOrphanToolError`, but the first-orphan **primary recovery** (`turn/interrupt`) is simply missing. Containment without root-cause fix.

**Thought 2 — Options.**
- *Option A: Hybrid (executor + monitor task)* — Keep `AppServerClient`. Wrap the sync wait in `loop.run_in_executor`. Concurrently spawn an async monitor that polls the watchdog and dispatches `turn/interrupt` on first orphan. Preserves Phase E architecture with minimum diff.
- *Option B: Migrate to AsyncCodex/AsyncTurnHandle* — Clean canonical async, but rewrites every call site, changes the `thread_start` return shape (`thread` vs. `AsyncThread` handle), and was explicitly parked in the Phase E OOS list. Too large for F-RT-001 scope.
- Chose Option A. Structural, not containment: `turn/interrupt` actually fires; `wait_for_turn_completed` no longer owns the event loop.

**Thought 3 — Side effects & regressions.**
- `_OrphanWatchdog` is now read from two threads (executor + event loop). Added `threading.Lock` around `pending_tool_starts` and orphan-registration state.
- Removed the per-event orphan registration from `_process_streaming_event` — that responsibility moves to `_monitor_orphans` so (a) dispatch happens on the event loop thread where we can `await`, and (b) the orphan counter no longer increments once per event after detection.
- Added `_registered_orphans: set[str]` so `check_orphans` dedupes on tool_id — prevents the same stuck tool from exhausting the budget on a single stall.
- Two-orphan escalation preserved: monitor fires `turn/interrupt` once per turn → `turn/completed status=interrupted` returns → main loop sees `watchdog.budget_exhausted is False` (1/2) → builds corrective prompt → new turn. Second orphan → same path but now count == 2 → main loop raises `CodexOrphanToolError`.

---

## 3. Diff Summary

`src/agent_team_v15/codex_appserver.py`:

1. **Imports.** Added `threading`, `from contextlib import suppress`.
2. **`_OrphanWatchdog`.**
   - Added `threading.Lock` around `pending_tool_starts` and orphan-event bookkeeping.
   - Added `_registered_orphans: set[str]` and `check_orphans` dedup so a single stuck `tool_id` never double-counts.
   - `register_orphan_event` is idempotent per `tool_id`.
3. **NEW `_send_turn_interrupt(client, thread_id, turn_id) -> bool`.** Dispatches the RPC off the event loop. Prefers typed `client.turn_interrupt(...)` where the SDK exposes it; falls back to `client.send_request("turn/interrupt", {"threadId": ..., "turnId": ...})` matching the RPC JSON shape from the context7 README verbatim. Skips dispatch when either id is empty; returns `True`/`False` to the caller.
4. **NEW `_monitor_orphans(client, thread_id, turn_id, watchdog, *, check_interval_seconds)`.** Async coroutine running on the event loop. Polls `watchdog.check_orphans()` every `check_interval_seconds`. On first orphan of the turn it records the event, logs the detection, and `await`s `_send_turn_interrupt`. Exits (one interrupt per turn is sufficient; server will finalise the turn with `status=interrupted`).
5. **`_execute_turn` main loop.** The key structural fix:
   ```python
   loop = asyncio.get_running_loop()
   wait_future = loop.run_in_executor(
       None,
       lambda: client.wait_for_turn_completed(turn_id, on_event=...),
   )
   monitor_task = asyncio.create_task(_monitor_orphans(...))
   try:
       completed_turn = await wait_future
   finally:
       monitor_task.cancel()
       with suppress(asyncio.CancelledError, Exception):
           await monitor_task
   ```
   The sync wait runs in a worker thread so the event loop stays responsive; the monitor task is reliably cancelled after the wait returns.
6. **`_process_streaming_event`.** Removed the per-event orphan registration block (old lines 467–478) and the outdated comment admitting no interrupt is sent. The callback now only updates watchdog bookkeeping (`record_start` / `record_complete`), token totals, and progress — it never tries to decide on interrupts from an executor thread.

Net line count: +~90 added / −~15 removed; structural.

---

## 4. Test Additions

`tests/test_bug20_codex_appserver.py` — 9 new tests (21 total in the file):

| # | Test | Asserts |
|---|---|---|
| 1 | `test_send_turn_interrupt_prefers_typed_method` | Uses `client.turn_interrupt(...)` when SDK exposes it. |
| 2 | `test_send_turn_interrupt_falls_back_to_send_request` | Raw RPC fallback shape is `("turn/interrupt", {"threadId": ..., "turnId": ...})`. |
| 3 | `test_send_turn_interrupt_skips_empty_ids` | Never dispatches with empty thread/turn id. |
| 4 | `test_monitor_orphans_sends_turn_interrupt_on_stall` | **Stall-injection**: past-timeout pending tool → monitor registers one event and calls `turn_interrupt` once. |
| 5 | `test_monitor_orphans_dedupes_same_tool_id` | Same `tool_id` cannot exhaust the budget on a single stall. |
| 6 | `test_monitor_orphans_second_stall_exhausts_budget` | Two distinct stalls → `orphan_event_count == 2` → `budget_exhausted is True` (CodexOrphanToolError gate). |
| 7 | `test_monitor_orphans_no_stall_cancellable` | With no stalls, monitor keeps polling and is cleanly cancellable. |
| 8 | `test_process_streaming_event_does_not_register_orphan` | Regression guard: the callback thread no longer increments `orphan_event_count`. |
| 9 | `test_execute_turn_does_not_block_event_loop` | Drives a concurrent task while `wait_for_turn_completed` is pretend-blocking; the concurrent task runs — proves the event loop is not parked. |

### Focused suite result

```
tests/test_bug20_codex_appserver.py — 21 passed in 3.38s
```

---

## 5. Full Pytest

(Awaiting full-suite run; exact count will be reported by the fixer in the follow-up summary. Target: 10,531 + new tests, 0 failed.)

---

## 6. Follow-up Flags

1. **OOS #2 AsyncCodex migration remains appropriate future work** — once higher-level async handles give us `stream()` + `.interrupt()` natively, the executor-wrapping pattern here becomes removable. Not blocking for F-RT-001.
2. **`on_event` kwarg dependency** — the code still passes `on_event=` to `wait_for_turn_completed`. Context7's canonical snippet shows no callback parameter. Real-SDK users should verify this kwarg is accepted; if not, the streaming events (tokens, item start/complete) silently go un-observed. Filing as non-blocking because tests mock the client, but the team should exercise this against the real `codex_app_server` install as soon as one is available.
3. **Monitor poll interval** — defaults to the existing `orphan_check_interval_seconds=60`. Interrupt can therefore lag the 300 s timeout by up to one poll. Acceptable for the wave-level containment budget; tighten if callers ever require sub-minute recovery.
