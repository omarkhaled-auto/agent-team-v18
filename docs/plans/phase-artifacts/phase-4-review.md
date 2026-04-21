# Phase 4 — Peek Integration: Review Brief

This review artifact is adversarial by design. Do not skim. A rushed
implementation will likely fail exactly the checks below.

## What Was Implemented

Phase 4 wires the observer loop into two separate watchdog paths:

- `_WaveWatchdogState` (Claude waves) gets five new fields for file-event
  peek bookkeeping: `peek_schedule`, `peek_log`, `last_peek_monotonic`,
  `peek_count`, `seen_files`.
- Two new module-level helpers in `wave_executor.py`:
  `_detect_new_peek_triggers()` (fingerprint diff) and
  `_should_fire_time_based_peek()` (interval + per-wave budget gate).
- `_invoke_wave_sdk_with_watchdog()` grows two keyword-only params
  (`observer_config`, `requirements_text`) and invokes `run_peek_call`
  inline between `asyncio.wait` and the timeout check, wrapped in
  `asyncio.wait_for` + broad try/except for fail-open semantics.
- `_OrphanWatchdog.__init__` (Codex waves) grows three keyword-only
  params (`observer_config`, `requirements_text`, `wave_letter`) and two
  instance attrs (`codex_last_plan`, `codex_latest_diff`). `_execute_once`
  forwards the three params at construction time.
- `_wait_for_turn_completion` gains a Phase-5 stub block: reads
  `watchdog.codex_last_plan` / `codex_latest_diff` after every
  notification, with an empty `pass` the Phase-5 implementer fills in.

## Critical Pre-Checks

**Run these FIRST, in order. If #1 fails, reject the PR immediately
without reading further — it is the critical architecture violation.**

### Check 1 (ARCHITECTURE — STOP IF THIS FAILS)

```bash
python -c "from agent_team_v15.wave_executor import _WaveWatchdogState; assert not hasattr(_WaveWatchdogState(), 'codex_last_plan'), 'ARCH VIOLATION'"
python -c "from agent_team_v15.wave_executor import _WaveWatchdogState; assert not hasattr(_WaveWatchdogState(), 'codex_latest_diff'), 'ARCH VIOLATION'"
```

Both must exit 0. If either raises `ARCH VIOLATION`, the implementer
conflated `_WaveWatchdogState` (Claude) with `_OrphanWatchdog` (Codex).
Reject and re-dispatch. Do not proceed to check 2.

### Check 2 (Claude peek fields present)

```bash
python -c "
from agent_team_v15.wave_executor import _WaveWatchdogState
s = _WaveWatchdogState()
for name in ('peek_schedule', 'peek_log', 'last_peek_monotonic', 'peek_count', 'seen_files'):
    assert hasattr(s, name), f'missing: {name}'
assert s.peek_schedule is None
assert s.peek_log == []
assert s.last_peek_monotonic == 0.0
assert s.peek_count == 0
assert s.seen_files == set()
print('claude peek fields OK')
"
```

### Check 3 (Codex watchdog observer fields present)

```bash
python -c "
from agent_team_v15.codex_appserver import _OrphanWatchdog
w = _OrphanWatchdog()
for name in ('observer_config', 'requirements_text', 'wave_letter', 'codex_last_plan', 'codex_latest_diff'):
    assert hasattr(w, name), f'missing: {name}'
assert w.codex_last_plan == []
assert w.codex_latest_diff == ''
print('codex observer fields OK')
"
```

### Check 4 (helpers exist and have the right signature)

```bash
python -c "
import inspect
from agent_team_v15.wave_executor import _detect_new_peek_triggers, _should_fire_time_based_peek
sig1 = inspect.signature(_detect_new_peek_triggers)
assert list(sig1.parameters) == ['cwd', 'baseline', 'seen_files'], sig1
sig2 = inspect.signature(_should_fire_time_based_peek)
assert list(sig2.parameters) == ['state', 'observer_config'], sig2
print('helpers OK')
"
```

### Check 5 (Codex observer kwargs are keyword-only)

```bash
python -c "
import inspect
from agent_team_v15.codex_appserver import _OrphanWatchdog
params = inspect.signature(_OrphanWatchdog.__init__).parameters
for name in ('observer_config', 'requirements_text', 'wave_letter'):
    assert params[name].kind == inspect.Parameter.KEYWORD_ONLY, f'{name} not keyword-only'
print('keyword-only OK')
"
```

### Check 6 (syntax)

```bash
python -m compileall src/agent_team_v15/wave_executor.py src/agent_team_v15/codex_appserver.py
```

Exit 0 with no errors.

## Code Review Checklist

Perform **each** item by opening the diff. Do not rely on test output alone.

### 4.1 — `_WaveWatchdogState` fields

- [ ] The five new fields are added *after* `interrupt_count: int = 0`
      and *before* `record_progress(...)`. Not interleaved.
- [ ] `peek_schedule` is typed `PeekSchedule | None = None` (not
      `PeekSchedule = None` — that is a type error).
- [ ] `peek_log` and `seen_files` use `field(default_factory=...)`. A bare
      `= []` or `= set()` is a dataclass bug (shared mutable default).
- [ ] No field named `codex_last_plan` or `codex_latest_diff` exists in
      `_WaveWatchdogState`. **Grep the whole file:**
      `grep -n "codex_last_plan\|codex_latest_diff" src/agent_team_v15/wave_executor.py`
      must return **zero** matches. If any appear, reject.
- [ ] Imports for `ObserverConfig`, `PeekResult`, `PeekSchedule` added
      at module top. Not inside the class. Not inside a function (the
      lazy `run_peek_call` import inside the loop is acceptable to avoid
      cycles).

### 4.2 — Peek helpers & loop injection

- [ ] `_detect_new_peek_triggers` compares `current` against both
      `baseline` and `seen_files`. Does **not** mutate `seen_files`
      (mutation happens at the call site in the watchdog loop).
- [ ] `_should_fire_time_based_peek` returns False when
      `peek_count >= max_peeks_per_wave`. Verify the comparison is `>=`,
      not `>`. Off-by-one would let a wave fire one extra peek beyond
      budget.
- [ ] `_should_fire_time_based_peek` returns False when
      `time_based_interval_seconds <= 0` (feature-disabled sentinel).
- [ ] Uses `time.monotonic()` for the elapsed calc. **Not** `time.time()`.
- [ ] Peek injection point: after `if task in done: return ...` and
      **before** `timeout = _build_wave_watchdog_timeout(...)`. If the
      peek block is after the timeout check, the timeout may short-circuit
      peek.
- [ ] Peek await is wrapped in `asyncio.wait_for(..., timeout=observer_config.peek_timeout_seconds)`.
      Without this, a hung peek wedges the whole wave — a direct violation
      of the zero-latency invariant.
- [ ] The whole peek block is wrapped in `try/except Exception` with
      `logger.warning(..., exc_info=True)`. A bare `except:` is rejected.
- [ ] `log_only` branch: when `observer_config.log_only is True`, the
      code must **not** call `client.interrupt()` — verdict is logged only.
- [ ] `milestone_id` extracted via
      `str(getattr(milestone, "id", "") or "")`. Direct `milestone.id` is
      rejected.
- [ ] The two new params on `_invoke_wave_sdk_with_watchdog` are
      keyword-only, with `None` / `""` defaults, so existing call sites
      keep compiling.
- [ ] After firing a peek, all three state fields update:
      `peek_count += 1`, `last_peek_monotonic = time.monotonic()`,
      `seen_files.update(new_triggers)`. Missing any of the three causes
      runaway peek firing.

### 4.3 — `_OrphanWatchdog` + `_wait_for_turn_completion`

- [ ] `_OrphanWatchdog.__init__` accepts `observer_config`,
      `requirements_text`, `wave_letter` as **keyword-only** (after `*`).
      Positional would break existing call sites.
- [ ] `codex_last_plan` is initialized as `[]` (a new list instance) in
      the body of `__init__`. Not as a default param. Not as a class attr.
      The former is a shared-mutable-default bug; the latter means all
      watchdog instances share one list.
- [ ] `codex_latest_diff` is initialized as `""`.
- [ ] `_execute_once` signature has three new keyword-only params with
      defaults. The `_OrphanWatchdog(...)` call at L950-ish forwards them.
- [ ] `execute_codex()` (top-level entry point) also forwards them to
      `_execute_once`. **Grep:**
      `grep -n "_execute_once(" src/agent_team_v15/codex_appserver.py`
      and verify every call site passes them (or the defaults are correct
      for that site).
- [ ] In `_wait_for_turn_completion`, the stub hook block is placed
      after `_process_streaming_event(...)` and before the error/method
      checks.
- [ ] Stub hook is guarded by `watchdog.observer_config is not None`
      and wrapped in try/except with fail-open logging.
- [ ] Stub contains `pass` (or an equivalent no-op); it must **not**
      actually call `client.turn_steer(...)` — that is Phase 5.
- [ ] `watchdog.observer_config.log_only` is respected even in the stub
      (no steer when log_only).

### Integration Safety

- [ ] Phase 0 observer wiring for `turn/plan/updated`/`turn/diff/updated` is
      confirmed merged (verify `_process_streaming_event` sets
      `watchdog.codex_last_plan`/`codex_latest_diff`). If absent, the stub
      hook in `_wait_for_turn_completion` will never fire — this is a
      dependency blocker, not a Phase 4 bug.

## Test Run Commands

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_v18_wave_executor_extended.py -v -k "peek or observer or watchdog"
python -m pytest tests/test_codex_appserver_steer.py -v
python -m pytest tests/test_v18_wave_executor_extended.py::test_orphan_watchdog_has_observer_fields -v
python -m pytest tests/test_v18_wave_executor_extended.py::test_wave_watchdog_state_does_not_have_codex_fields -v
python -m pytest tests/test_v18_wave_executor_extended.py::test_detect_new_peek_triggers_returns_new_and_modified -v
```

All must report `passed`. Any `skipped` on the new tests is a red flag —
the reviewer should inspect the skip reason before accepting.

### Regression sanity

```bash
python -m pytest tests/ -x -k "wave or watchdog or codex" --timeout=60
```

No pre-existing test should start failing. If any do, the peek wiring
leaked into a hot path it should not have.

## Acceptance Criteria

The PR is accepted only when **all** of the following hold:

1. Check 1 (architecture) passes. This is non-negotiable.
2. Checks 2–6 pass.
3. Every item in the Code Review Checklist is verified by opening the
   diff (not inferred from test output).
4. `pytest tests/test_v18_wave_executor_extended.py -v -k "peek or observer or watchdog"`
   reports all new tests passing, with no new skips.
5. `pytest tests/test_codex_appserver_steer.py -v` continues to pass —
   Phase 4 must not break Phase 0/0.5 steer wiring.
6. Grep for `codex_last_plan\|codex_latest_diff` inside
   `src/agent_team_v15/wave_executor.py` returns **zero** matches.
7. Grep for `observer_config` inside
   `src/agent_team_v15/codex_appserver.py` returns **at least three**
   matches (`__init__` signature, constructor body assignment,
   `_execute_once` forwarding; more if stub hook branches reference it).
8. `python -m compileall src/agent_team_v15/wave_executor.py src/agent_team_v15/codex_appserver.py`
   exits 0.
9. No `# TODO`, `pass  # ...fill in later`, or `...` tokens outside the
   explicitly-sanctioned Phase-5 stub (the stub is allowed exactly one
   `pass` inside the documented hook block).
10. Handoff state documented in the PR description matches the Phase 4
    impl brief's Handoff State section verbatim.

If any criterion fails, reject and return the list of failing items to
the implementer. Do not patch forward in the same PR — the V18 feedback
memory is explicit that in-flight fixes during review need authorization.
