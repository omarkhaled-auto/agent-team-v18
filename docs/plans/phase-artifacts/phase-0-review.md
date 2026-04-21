# Phase 0 — Codex App-Server Enhancements: Review Brief

This review is written adversarially. Assume the implementing agent rushed, skipped regression runs, misread the protocol spec, or copy-pasted the wrong field names. Every check below exists because it is a plausible failure mode.

## What Was Implemented

Phase 0 extends the Codex app-server transport (`src/agent_team_v15/codex_appserver.py`) with three capabilities: a `turn_steer()` JSON-RPC client method for mid-turn correction, streaming-event handlers for `turn/plan/updated` and `turn/diff/updated` that cache the latest plan and diff on the per-run `_OrphanWatchdog`, and thread-id persistence plumbed through `CodexResult` / `execute_codex` / `_execute_once` so compile_fix iterations can reuse the same Codex thread. Observer configuration (`observer_config`, `requirements_text`, `wave_letter`) is also threaded into `_OrphanWatchdog` for Phase 4 to consume.

---

## Critical Pre-Checks

Run these FIRST. If any fails, stop the review and reject the diff.

### 1. Scope containment — correction #3

```bash
cd C:/Projects/agent-team-v18-codex
grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/wave_executor.py
```

**Expected:** empty output. The Codex notification fields must live on `_OrphanWatchdog` (codex_appserver.py), never on `_WaveWatchdogState` (wave_executor.py). If this grep returns anything, correction #3 was violated and the diff must be rejected and respun.

### 2. New files exist

```bash
ls tests/test_codex_appserver_steer.py tests/test_codex_notifications.py tests/test_codex_thread_persistence.py
```

All three must exist. If any is missing, the corresponding task was skipped.

### 3. `turn_steer` is fail-open

```bash
grep -nA12 "async def turn_steer" src/agent_team_v15/codex_appserver.py
```

Must contain a `try:` block and an `except` clause wrapping the `send_request` call. If it raises unconditionally, the observer can crash a wave and the contract is broken.

### 4. Correct JSON-RPC field name

```bash
grep -n "expectedTurnId\|turnId" src/agent_team_v15/codex_appserver.py
```

The `turn_steer` payload MUST use `"expectedTurnId"` (per the Codex app-server spec), not `"turnId"`. `turn_interrupt` uses `"turnId"`. A common rushed-agent bug is to copy-paste `turn_interrupt` and keep the wrong field name. Verify `expectedTurnId` appears exactly once and is inside `turn_steer`.

### 5. `_OrphanWatchdog` backward compatibility

```bash
python -c "from agent_team_v15.codex_appserver import _OrphanWatchdog; _OrphanWatchdog(); _OrphanWatchdog(timeout_seconds=10, max_orphan_events=1)"
```

Must exit 0 silently. If the agent added `observer_config`, `requirements_text`, or `wave_letter` as positional (non-kw-only) params without defaults, this will break.

### 6. `CodexResult.thread_id` default

```bash
python -c "from agent_team_v15.codex_transport import CodexResult; r = CodexResult(); assert r.thread_id == '', r.thread_id"
```

Must be empty string by default. If it is `None` or missing, the dataclass default was omitted.

---

## Code Review Checklist

### Correctness

- [ ] `turn_steer` payload structure is exactly `{"threadId": thread_id, "expectedTurnId": turn_id, "input": [{"type": "text", "text": message}]}`. No extra fields. No typos in keys (`threadid`, `thread_id`, `turnid`, `expected_turn_id` are all wrong).
- [ ] `turn_steer` checks `if not thread_id or not turn_id or not message: return` before the request — empty inputs are a no-op, not an exception.
- [ ] `parse_codex_notification` returns `None` for:
  - `{}` (missing method)
  - `{"method": "item/started", "params": {}}` (wrong method)
  - `{"method": "turn/plan/updated"}` (missing params)
  - `{"method": "turn/plan/updated", "params": "not a dict"}` (malformed params)
- [ ] `CodexNotificationEvent` fields match the spec exactly: `event_type`, `thread_id`, `turn_id`, `payload`. No renames.
- [ ] `_process_streaming_event` stores `params["plan"]` (a list) on `watchdog.codex_last_plan` only when it is actually a list — string or None must not pollute the field.
- [ ] `_process_streaming_event` stores `params["diff"]` (a string) on `watchdog.codex_latest_diff` only when it is a string.
- [ ] `_execute_once`, when `existing_thread_id` is non-empty, skips `client.thread_start()` entirely. Verify by reading the diff — the `thread_start()` call must be gated behind an `if existing_thread_id: ... else: thread_start()` branch.
- [ ] `result.thread_id = thread_id` is set in BOTH branches (reused thread and fresh thread), so the field is always populated, including on failure paths that occur after `thread_id` is known.
- [ ] `execute_codex` propagates `result.thread_id` onto `aggregate.thread_id` so external callers receive it.

### Architecture Compliance

- [ ] Correction #3: no mention of `codex_last_plan` or `codex_latest_diff` in `wave_executor.py`. Run the grep in Pre-Check #1.
- [ ] Correction #4: `codex_last_plan` and `codex_latest_diff` are initialized in `_OrphanWatchdog.__init__` as empty defaults (`[]` and `""`), NOT accepted as constructor params. Inspect the `__init__` signature.
- [ ] Correction #5: `execute_codex` signature contains `existing_thread_id: str = ""` as a keyword-only param (after `*`).
- [ ] Correction #6: `_execute_once` signature contains `observer_config: dict[str, Any] | None = None`, `requirements_text: str = ""`, `wave_letter: str = ""` as keyword-only params (after `*`).
- [ ] Fail-open everywhere: `turn_steer` catches `Exception` (not just `_CodexAppServerError`) so even JSON serialization bugs can't crash the observer path.
- [ ] The notification handlers in `_process_streaming_event` do NOT raise. They validate types and silently return.
- [ ] Observer params are threaded `_OrphanWatchdog` via the constructor, not assigned post-hoc — this is per sequential-thinking option (a).

### Test Quality

- [ ] `test_codex_appserver_steer.py` has at least three tests: method exists, payload structure is correct, fail-open behavior (mock `send_request` raises, `turn_steer` must not).
- [ ] The fail-open test actually asserts no exception is raised — `asyncio.run(client.turn_steer(...))` must complete. A test that swallows the exception without verifying the call does not count.
- [ ] The payload test asserts the exact field `expectedTurnId` (NOT `turnId`). If the test checks `turnId`, both the test and the implementation are wrong.
- [ ] `test_codex_notifications.py` includes `test_process_streaming_event_stores_plan_on_watchdog` and a sibling for diff — tests must confirm the notification handler actually writes to `watchdog.codex_last_plan` / `.codex_latest_diff`, not merely that `parse_codex_notification` is callable.
- [ ] `test_codex_notifications.py` has a default-state test that constructs a bare `_OrphanWatchdog()` and asserts `codex_last_plan == []` and `codex_latest_diff == ""`.
- [ ] `test_codex_thread_persistence.py` asserts all four `_execute_once` new params exist AND are keyword-only AND have the correct defaults.
- [ ] No test contains `assert ... or True`, `assert True`, or `assert not False` (anti-pattern from correction #9 context).
- [ ] No test is skipped via `@pytest.mark.skip` or `pytest.skip(...)` without justification.

### Integration Safety

- [ ] Running `pytest tests/test_bug20_codex_appserver.py -v` still passes. This regression check confirms `_CodexAppServerClient`, `_OrphanWatchdog`, `_execute_once`, and `execute_codex` signature changes did not break existing tests.
- [ ] `_OrphanWatchdog(timeout_seconds=..., max_orphan_events=...)` (old call style at codex_appserver.py:950) still works — the new params are keyword-only with defaults.
- [ ] No other callers of `execute_codex` needed mandatory updates (keyword-only params with defaults mean existing callers continue to work without edits). Search for call sites: `grep -rn "execute_codex(" src/ tests/` — none should fail to compile.
- [ ] No import cycles introduced. `CodexResult` remains in `codex_transport.py`; `CodexNotificationEvent` lives in `codex_appserver.py`.
- [ ] `from dataclasses import dataclass, field` import is present in `codex_appserver.py` (the file previously did not import `dataclass`).

---

## Test Run Commands

```bash
cd C:/Projects/agent-team-v18-codex

# Phase 0 new tests
python -m pytest tests/test_codex_appserver_steer.py tests/test_codex_notifications.py tests/test_codex_thread_persistence.py -v

# Regression suite for the touched modules
python -m pytest tests/test_bug20_codex_appserver.py -v

# Broader smoke for codex paths (if present)
python -m pytest tests/ -k "codex" -v
```

All invocations must exit 0 with every selected test passing.

### Symbol import gate

```bash
python -c "from agent_team_v15.codex_appserver import _CodexAppServerClient, CodexNotificationEvent, parse_codex_notification, _OrphanWatchdog, _process_streaming_event, _execute_once, execute_codex"
python -c "from agent_team_v15.codex_transport import CodexResult; assert hasattr(CodexResult(), 'thread_id')"
```

Both must exit 0.

---

## Acceptance Criteria

Binary pass/fail. Any FAIL blocks merge.

| # | Criterion | Pass condition |
| --- | --- | --- |
| 1 | `turn_steer` exists on `_CodexAppServerClient` | `hasattr(_CodexAppServerClient, 'turn_steer')` is True |
| 2 | `turn_steer` uses `expectedTurnId` (not `turnId`) | Pre-Check #4 shows `expectedTurnId` appearing exactly once, inside `turn_steer` |
| 3 | `turn_steer` is fail-open | The fail-open test in `test_codex_appserver_steer.py` passes; mock raising RuntimeError does not propagate |
| 4 | `CodexNotificationEvent` dataclass with 4 fields exists | Imports cleanly; has `event_type`, `thread_id`, `turn_id`, `payload` |
| 5 | `parse_codex_notification` returns None for unknown methods | Test `test_parse_unknown_notification_returns_none` passes |
| 6 | `_process_streaming_event` writes `codex_last_plan` | Test `test_process_streaming_event_stores_plan_on_watchdog` passes |
| 7 | `_process_streaming_event` writes `codex_latest_diff` | Test `test_process_streaming_event_stores_diff_on_watchdog` passes |
| 8 | `_OrphanWatchdog` defaults `codex_last_plan=[]`, `codex_latest_diff=""` | Default-state test passes; Pre-Check #5 passes |
| 9 | `_OrphanWatchdog` backward compatible | `_OrphanWatchdog()` and `_OrphanWatchdog(timeout_seconds=X, max_orphan_events=Y)` do not raise |
| 10 | `CodexResult.thread_id` exists with default `""` | Pre-Check #6 passes |
| 11 | `execute_codex` accepts `existing_thread_id` kw-only | `inspect.signature` test passes |
| 12 | `_execute_once` accepts `observer_config`, `requirements_text`, `wave_letter`, `existing_thread_id` kw-only | `inspect.signature` test passes |
| 13 | Correction #3 preserved | Pre-Check #1 returns empty output |
| 14 | Existing Codex tests still pass | `tests/test_bug20_codex_appserver.py` green |
| 15 | All Phase 0 tests pass | Three new test files fully green |
| 16 | No `or True` / `assert True` anti-patterns in new tests | `grep -n "or True\|assert True" tests/test_codex_*_steer.py tests/test_codex_notifications.py tests/test_codex_thread_persistence.py` returns empty |
| 17 | `from dataclasses import dataclass, field` present in `codex_appserver.py` | Verified by grep |
| 18 | Notification handlers type-guard before assignment | Handlers check `isinstance(plan, list)` / `isinstance(diff, str)` before storing |
| 19 | `result.thread_id` populated in both reuse and fresh paths | Code inspection: the assignment happens after the branch, not inside only one arm |
| 20 | `aggregate.thread_id` propagated from `result.thread_id` | Code inspection of `execute_codex` |

If any criterion fails, the review verdict is **REJECT**. Otherwise **ACCEPT**.
