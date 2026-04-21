# Phase 4 — Peek Integration: Implementation Brief

## Phase Context

Phase 4 wires two observer strategies into their respective watchdog loops:

- **Claude waves (file-poll strategy):** Extend `_WaveWatchdogState` in
  `wave_executor.py` with peek bookkeeping fields, add two helper functions
  (`_detect_new_peek_triggers`, `_should_fire_time_based_peek`), and invoke
  `run_peek_call()` from inside `_invoke_wave_sdk_with_watchdog`'s while-True
  polling loop. The peek call runs inline after `asyncio.wait` returns but
  before the timeout check.
- **Codex waves (notification strategy):** Extend `_OrphanWatchdog.__init__`
  with three new keyword-only params (`observer_config`, `requirements_text`,
  `wave_letter`) plus two instance attrs (`codex_last_plan`,
  `codex_latest_diff`). `_execute_once()` passes the new params at
  construction time. `_wait_for_turn_completion` gets a Phase-5 stub
  hook after every notification.

**Depends on:** Phase 0 (CodexNotificationEvent, turn_steer in client),
Phase 1 (PHASE_LEAD_NAMES), Phase 3 (ObserverConfig, PeekResult,
PeekSchedule, run_peek_call, `_CODEX_WAVES`).

**Enables:** Phase 5 (semantic checks and codex_observer_checks).

**Design invariant:** Zero latency added to normal wave execution. All peek
calls are fail-open — any exception is logged and swallowed.

## Pre-Flight: Files to Read

| # | File | Lines | Purpose |
|---|------|-------|---------|
| 1 | `src/agent_team_v15/wave_executor.py` | 165–265 | `_WaveWatchdogState` dataclass full field set |
| 2 | `src/agent_team_v15/wave_executor.py` | 2485–2545 | `_capture_file_fingerprints()` at **L2499** + touched-file helpers |
| 3 | `src/agent_team_v15/wave_executor.py` | 2560–2700 | `_invoke_wave_sdk_with_watchdog` while-True loop (loop body lines 2620–2656) |
| 4 | `src/agent_team_v15/codex_appserver.py` | 90–175 | `_OrphanWatchdog` full class (constructor at L119) |
| 5 | `src/agent_team_v15/codex_appserver.py` | 865–980 | `_wait_for_turn_completion` + `_execute_once` signature (watchdog built at L950) |
| 6 | `tests/test_v18_wave_executor_extended.py` | 1–80 | Test class & mock patterns |
| 7 | `src/agent_team_v15/observer_config.py` (Phase 3 output) | full | ObserverConfig, PeekResult, PeekSchedule dataclasses |
| 8 | `docs/plans/2026-04-20-dynamic-orchestrator-observer.md` | Phase 4 § | Tasks 4.1–4.3 spec |

Read all eight before writing a single character of code.

## Pre-Flight: Context7 Research

Run the following queries **before** implementing Task 4.2:

1. `mcp__context7__resolve-library-id` with `libraryName="asyncio python"` →
   obtain `/python/cpython` ID.
2. `mcp__context7__query-docs` with `query="asyncio.wait tasks timeout
   return FIRST_COMPLETED"` — confirm that `asyncio.wait` returns
   `(done, pending)`, and that timeout-only returns an empty `done` set
   without cancelling tasks.
3. `mcp__context7__query-docs` with `query="time.monotonic elapsed time
   Python"` — confirm monotonic is process-local and cannot go backward.

**Expected conclusions (restate in implementation):**

- `asyncio.wait({task}, timeout=N)` returns `(set(), {task})` when the task
  did NOT complete within the timeout. The task keeps running. Safe to
  inject peek logic between the return and the timeout check.
- `time.monotonic()` is the correct clock for elapsed intervals. Never mix
  with `time.time()` — wall-clock drift breaks intervals.

## Pre-Flight: Sequential Thinking

Before writing Task 4.2, invoke
`mcp__sequential-thinking__sequentialthinking` with the prompt in the
dispatch. The conclusion to encode is:

> **Strategy (a) — inline `await run_peek_call(...)` after `asyncio.wait`
> returns, before the timeout check.** Rationale:
>
> 1. Peek calls are bounded (Phase 3 runtime budget ~5s). Blocking the
>    poll cycle for that long is acceptable; `poll_seconds` is already
>    ~10–30s.
> 2. Strategy (b) (create_task + add to wait set) leaks partially-finished
>    peeks across loop iterations, complicates fail-open semantics, and
>    risks peek tasks surviving wave completion.
> 3. Fail-open requirement dictates that any peek exception is caught and
>    swallowed *inside the same loop iteration*. Strategy (a) gives the
>    cleanest try/except scope.
> 4. To guarantee peek never runs forever, wrap the peek await in
>    `asyncio.wait_for(run_peek_call(...), timeout=observer_config.peek_timeout_seconds)`.
>    On `asyncio.TimeoutError`, log and continue.

Record this conclusion verbatim in the artifact.

## Corrections Applied (Phase 4)

- **Correction #1:** `_capture_file_fingerprints()` is at line **2499** of
  `wave_executor.py` (not 1747). Helpers added in Task 4.2 sit immediately
  after `_count_touched_files` (which ends at ~L2526), between it and
  `_log_wave_heartbeats`. Do not insert before `_count_touched_files`.
- **Correction #3 (CRITICAL):** `codex_last_plan` and `codex_latest_diff`
  live on `_OrphanWatchdog` in `codex_appserver.py`, **never** on
  `_WaveWatchdogState` in `wave_executor.py`. `_WaveWatchdogState` is
  Claude-only; `_OrphanWatchdog` is Codex-only. Do not cross the streams.
- **Correction #4:** `_OrphanWatchdog.__init__` must initialize
  `self.codex_last_plan = []` and `self.codex_latest_diff = ""` inside the
  body of `__init__` — these are mutable instance attrs set later by the
  notification handler (Phase 0). They are **NOT** constructor parameters.
- **Correction #6:** `_execute_once()` receives 3 new parameters
  (`observer_config`, `requirements_text`, `wave_letter`) and forwards them
  to `_OrphanWatchdog(...)` at construction (currently L950).

## CRITICAL ARCHITECTURE NOTE

> ```
> ┌───────────────────────────────────────────────────────────────────┐
> │  _WaveWatchdogState  (wave_executor.py)   ==  CLAUDE WAVES ONLY   │
> │    + peek_schedule, peek_log, last_peek_monotonic,                │
> │      peek_count, seen_files                                       │
> │    - NO codex_last_plan, NO codex_latest_diff                     │
> │                                                                   │
> │  _OrphanWatchdog     (codex_appserver.py) ==  CODEX WAVES ONLY    │
> │    + observer_config, requirements_text, wave_letter (ctor)       │
> │    + codex_last_plan, codex_latest_diff (instance attrs)          │
> └───────────────────────────────────────────────────────────────────┘
> ```
>
> **Violating this split is the single most likely Phase 4 failure mode.**
> The review artifact's first pre-check enforces it. If you find yourself
> typing `codex_last_plan` inside `wave_executor.py`, stop.

## Task-by-Task Implementation

### Task 4.1 — Extend `_WaveWatchdogState` with Claude observer fields

**File:** `src/agent_team_v15/wave_executor.py`

**Step 1 — Add imports.** Near the top of the file (after line 36, after
the `from .tracking_compat import ...` line), add:

```python
from .observer_config import ObserverConfig, PeekResult, PeekSchedule
```

(Adjust the module name to whatever Phase 3 registered the config module as;
cross-check Phase 3's handoff state before hard-coding the import.)

**Step 2 — Append new fields to `_WaveWatchdogState`.** Open the class at
line 173. After the existing `interrupt_count: int = 0` field (line 192)
and **before** the `record_progress` method (line 194), insert:

```python
    # --- Observer / peek bookkeeping (Phase 4, Claude-only) ---
    # NOTE: These fields MUST NOT include codex_last_plan/codex_latest_diff
    # — those belong on _OrphanWatchdog in codex_appserver.py.
    peek_schedule: PeekSchedule | None = None
    peek_log: list[PeekResult] = field(default_factory=list)
    last_peek_monotonic: float = 0.0
    peek_count: int = 0
    seen_files: set[str] = field(default_factory=set)
```

Do not modify any existing fields or the `record_progress` / `interrupt_oldest_orphan` methods.

**Step 3 — Tests.** Append to `tests/test_v18_wave_executor_extended.py`:

```python
def test_wave_watchdog_state_has_claude_peek_fields():
    from agent_team_v15.wave_executor import _WaveWatchdogState
    state = _WaveWatchdogState()
    assert state.peek_schedule is None
    assert state.peek_log == []
    assert state.last_peek_monotonic == 0.0
    assert state.peek_count == 0
    assert state.seen_files == set()


def test_wave_watchdog_state_rejects_codex_fields():
    """Architecture guard: codex_* fields must live on _OrphanWatchdog."""
    from agent_team_v15.wave_executor import _WaveWatchdogState
    state = _WaveWatchdogState()
    assert not hasattr(state, "codex_last_plan")
    assert not hasattr(state, "codex_latest_diff")


def test_wave_watchdog_peek_log_accumulates():
    from agent_team_v15.wave_executor import _WaveWatchdogState
    from agent_team_v15.observer_config import PeekResult
    state = _WaveWatchdogState()
    state.peek_log.append(PeekResult(verdict="ok", rationale="r1", files=[]))
    state.peek_log.append(PeekResult(verdict="steer", rationale="r2", files=["a.ts"]))
    assert len(state.peek_log) == 2
    assert state.peek_log[-1].verdict == "steer"
```

### Task 4.2 — Wire file-event peek into the Claude wave watchdog loop

**File:** `src/agent_team_v15/wave_executor.py`

**Step 1 — Add two helper functions.** After `_count_touched_files`
(ends at line ~2526), between `_count_touched_files` and `_log_wave_heartbeats`.
**Do not insert before `_count_touched_files` (line 2514)** — the helpers
belong after it so they sit alongside the existing file-fingerprint utilities.
Insert:

```python
def _detect_new_peek_triggers(
    cwd: str,
    baseline: dict[str, tuple[int, int]],
    seen_files: set[str],
) -> list[str]:
    """Return files that appeared or changed since baseline and are not yet peeked.

    Uses the same fingerprint format as _capture_file_fingerprints: a dict
    mapping posix-relative path -> (mtime_ns, size). Newly-created and
    modified files both qualify as triggers; deletions do not.
    """
    current = _capture_file_fingerprints(cwd)
    triggers: list[str] = []
    for path, fingerprint in current.items():
        if path in seen_files:
            continue
        if baseline.get(path) != fingerprint:
            triggers.append(path)
    return triggers


def _should_fire_time_based_peek(
    state: "_WaveWatchdogState",
    observer_config: "ObserverConfig",
) -> bool:
    """True when the time-based interval elapsed and per-wave budget allows."""
    if state.peek_count >= observer_config.max_peeks_per_wave:
        return False
    if observer_config.time_based_interval_seconds <= 0:
        return False
    elapsed = time.monotonic() - state.last_peek_monotonic
    return elapsed >= observer_config.time_based_interval_seconds
```

**Step 2 — Add three new parameters to `_invoke_wave_sdk_with_watchdog`.**
Current signature (line 2583):

```python
async def _invoke_wave_sdk_with_watchdog(
    *,
    execute_sdk_call: Callable[..., Any],
    prompt: str,
    wave_letter: str,
    config: Any,
    cwd: str,
    milestone: Any,
) -> tuple[float, _WaveWatchdogState]:
```

Add three keyword-only params with defaults so existing callers keep working:

```python
async def _invoke_wave_sdk_with_watchdog(
    *,
    execute_sdk_call: Callable[..., Any],
    prompt: str,
    wave_letter: str,
    config: Any,
    cwd: str,
    milestone: Any,
    observer_config: "ObserverConfig | None" = None,
    requirements_text: str = "",
) -> tuple[float, _WaveWatchdogState]:
```

Then update the caller(s) of this function (`_execute_single_wave_sdk`
and any sibling) to forward `observer_config` and `requirements_text` if
they have them in scope. When the caller does not have them, pass
defaults — peek code below is a no-op when `observer_config is None`.

**Step 3 — Inject peek invocation inside the while-True loop.** Existing
loop (lines 2620–2656):

```python
try:
    while True:
        done, _pending = await asyncio.wait({task}, timeout=poll_seconds)
        if task in done:
            return float(task.result() or 0.0), state
        timeout = _build_wave_watchdog_timeout(...)
        if timeout is not None:
            # Phase H3e interrupt recovery block — DO NOT REMOVE OR SIMPLIFY
            if state.client and state.interrupt_count == 0:
                orphan_threshold = float(_orphan_tool_idle_timeout_seconds(config))
                orphan_info = await state.interrupt_oldest_orphan(orphan_threshold)
                if orphan_info:
                    ...
                    continue
            # Second orphan or no client: hard cancel
            task.cancel()
            ...
            raise timeout
```

**WARNING: Do NOT remove or simplify the existing interrupt recovery block.**
Inside `if timeout is not None:`, there is an existing Phase H3e block:
`if state.client and state.interrupt_count == 0: ... continue`. This block
must be preserved exactly as-is. The peek injection point is ABOVE
`timeout = _build_wave_watchdog_timeout(...)`, NOT inside the timeout handler.
Only add the peek block in the gap between `if task in done: return` and
`timeout = ...`. Do not touch the interrupt recovery logic.

Insert the peek block **between** `if task in done: return ...` and the
`timeout = _build_wave_watchdog_timeout(...)` line. Per the sequential
thinking conclusion, use strategy (a): inline `await` with a wait_for
timeout and broad fail-open catch.

```python
        # --- Observer peek (Phase 4, fail-open) ---
        if observer_config is not None:
            try:
                milestone_id = str(getattr(milestone, "id", "") or "")
                new_triggers = _detect_new_peek_triggers(
                    cwd, baseline_fingerprints, state.seen_files
                )
                fire_time = _should_fire_time_based_peek(state, observer_config)
                if new_triggers or fire_time:
                    if new_triggers:
                        files_for_peek = new_triggers
                    elif state.seen_files:
                        files_for_peek = [sorted(state.seen_files)[-1]]
                    else:
                        files_for_peek = []
                    from .observer_config import run_peek_call  # lazy to avoid cycles
                    peek_coro = run_peek_call(
                        wave_letter=wave_letter,
                        requirements_text=requirements_text,
                        files=files_for_peek,
                        observer_config=observer_config,
                        cwd=cwd,
                        milestone_id=milestone_id,
                    )
                    peek_result = await asyncio.wait_for(
                        peek_coro,
                        timeout=float(observer_config.peek_timeout_seconds),
                    )
                    state.peek_log.append(peek_result)
                    state.peek_count += 1
                    state.last_peek_monotonic = time.monotonic()
                    state.seen_files.update(new_triggers)
                    if (
                        peek_result.verdict == "steer"
                        and not observer_config.log_only
                        and state.client is not None
                    ):
                        logger.warning(
                            "[Wave %s] observer steer requested: %s",
                            wave_letter,
                            peek_result.rationale,
                        )
                        # Follow interrupt_oldest_orphan pattern: call
                        # client.interrupt(), let the SDK loop resume with
                        # a corrective prompt inserted by Phase 5.
                        with contextlib.suppress(Exception):
                            await state.client.interrupt()
            except asyncio.TimeoutError:
                logger.warning(
                    "[Wave %s] observer peek exceeded %ss budget — skipping",
                    wave_letter, observer_config.peek_timeout_seconds,
                )
            except Exception:
                logger.warning(
                    "[Wave %s] observer peek failed (fail-open)",
                    wave_letter, exc_info=True,
                )
        # --- end observer peek block ---
```

**Step 4 — `milestone_id` extraction must tolerate odd milestone shapes.**
Use `str(getattr(milestone, "id", "") or "")`. Do not call `milestone.id`
directly — tests pass `SimpleNamespace` and unit callers may pass strings.

**Step 5 — Tests (peek firing).** Add to
`tests/test_v18_wave_executor_extended.py`:

```python
def test_detect_new_peek_triggers_returns_new_and_modified(tmp_path):
    from agent_team_v15.wave_executor import (
        _capture_file_fingerprints,
        _detect_new_peek_triggers,
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("x", encoding="utf-8")
    baseline = _capture_file_fingerprints(str(tmp_path))
    (tmp_path / "src" / "b.ts").write_text("y", encoding="utf-8")
    triggers = _detect_new_peek_triggers(str(tmp_path), baseline, set())
    assert any(t.endswith("b.ts") for t in triggers)


def test_should_fire_time_based_peek_respects_budget():
    from agent_team_v15.wave_executor import (
        _WaveWatchdogState, _should_fire_time_based_peek,
    )
    from agent_team_v15.observer_config import ObserverConfig
    state = _WaveWatchdogState()
    cfg = ObserverConfig(
        time_based_interval_seconds=1.0, max_peeks_per_wave=2,
    )
    state.peek_count = 2
    assert _should_fire_time_based_peek(state, cfg) is False
```

### Task 4.3 — Wire plan/diff observer into `_OrphanWatchdog` and `_wait_for_turn_completion`

**File:** `src/agent_team_v15/codex_appserver.py`

**Step 1 — Extend `_OrphanWatchdog.__init__` (line 119).** Current:

```python
def __init__(self, timeout_seconds: float = 300.0, max_orphan_events: int = 2) -> None:
    self.timeout_seconds = timeout_seconds
    self.max_orphan_events = max_orphan_events
    self._lock = threading.Lock()
    self.pending_tool_starts: dict[str, dict[str, Any]] = {}
    self.orphan_event_count: int = 0
    self.last_orphan_tool_name: str = ""
    self.last_orphan_tool_id: str = ""
    self.last_orphan_age: float = 0.0
    self._registered_orphans: set[str] = set()
```

Replace with:

```python
def __init__(
    self,
    timeout_seconds: float = 300.0,
    max_orphan_events: int = 2,
    *,
    observer_config: "ObserverConfig | None" = None,
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
    # Phase 4 observer wiring (Codex notification strategy).
    self.observer_config = observer_config
    self.requirements_text = requirements_text
    self.wave_letter = wave_letter
    # Populated by the notification handler in _process_streaming_event
    # (Phase 0) when turn/plan/updated or turn/diff/updated arrives.
    # NOT constructor params — mutated in place.
    self.codex_last_plan: list[Any] = []
    self.codex_latest_diff: str = ""
```

Add `from .observer_config import ObserverConfig` (TYPE_CHECKING-guarded
if necessary to avoid import cycles) near the top of the module.

**Step 2 — Forward new params from `_execute_once`.** `_execute_once`
currently constructs the watchdog at line 950:

```python
watchdog = _OrphanWatchdog(
    timeout_seconds=orphan_timeout_seconds,
    max_orphan_events=orphan_max_events,
)
```

Extend the `_execute_once` signature (line 934) with three new keyword-only
params:

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
    observer_config: "ObserverConfig | None" = None,
    requirements_text: str = "",
    wave_letter: str = "",
) -> CodexResult:
```

Update the `_OrphanWatchdog(...)` call at line 950 to pass them through:

```python
watchdog = _OrphanWatchdog(
    timeout_seconds=orphan_timeout_seconds,
    max_orphan_events=orphan_max_events,
    observer_config=observer_config,
    requirements_text=requirements_text,
    wave_letter=wave_letter,
)
```

Update `execute_codex()` (correction #5 from Phase 0) and any other
`_execute_once` caller to propagate the three params.

**Note:** `execute_codex()` currently also omits forwarding
`orphan_check_interval_seconds` to `_execute_once` even though
`_execute_once` accepts it (existing pre-Phase-4 gap at ~line 1151–1160).
When adding the three observer params, the implementer may optionally fix
this gap too, but must at minimum ensure the three new params are forwarded.
Do not remove any existing forwarded params.

**Step 3 — Phase 5 stub hook in `_wait_for_turn_completion`.** Current
body (line 896):

```python
while True:
    message = await client.next_notification()
    _process_streaming_event(
        message, watchdog, tokens, progress_callback, messages, capture_session,
    )

    if message.get("method") == "error":
        ...
        continue

    if message.get("method") != "turn/completed":
        continue
    ...
```

After the `_process_streaming_event(...)` call and before the
`if message.get("method") == "error":` check, insert the Phase 5 stub
hook:

```python
        # Phase 4 hook: after every notification, _process_streaming_event
        # has already mutated watchdog.codex_last_plan and
        # watchdog.codex_latest_diff (Phase 0 wiring). Phase 5 will replace
        # this stub with a rule-based check against
        # codex_observer_checks.evaluate(...). Keep fail-open semantics.
        if (
            watchdog.observer_config is not None
            and not watchdog.observer_config.log_only
            and watchdog.codex_latest_diff
        ):
            try:
                # Phase 5 replaces the pass below with:
                #   from .codex_observer_checks import evaluate
                #   verdict = evaluate(
                #       plan=watchdog.codex_last_plan,
                #       diff=watchdog.codex_latest_diff,
                #       requirements=watchdog.requirements_text,
                #       wave=watchdog.wave_letter,
                #       config=watchdog.observer_config,
                #   )
                #   if verdict.should_steer:
                #       await client.turn_steer(thread_id, turn_id, verdict.prompt)
                pass
            except Exception:
                logger.warning(
                    "Codex observer check failed (fail-open)", exc_info=True,
                )
```

**Step 4 — Tests.** Append to `tests/test_v18_wave_executor_extended.py`:

```python
def test_orphan_watchdog_has_observer_fields():
    from agent_team_v15.codex_appserver import _OrphanWatchdog
    w = _OrphanWatchdog()
    assert hasattr(w, "observer_config")
    assert hasattr(w, "requirements_text")
    assert hasattr(w, "wave_letter")
    assert hasattr(w, "codex_last_plan")
    assert hasattr(w, "codex_latest_diff")
    assert w.codex_last_plan == []
    assert w.codex_latest_diff == ""


def test_orphan_watchdog_accepts_observer_config_kwarg():
    from agent_team_v15.codex_appserver import _OrphanWatchdog
    from agent_team_v15.observer_config import ObserverConfig
    cfg = ObserverConfig()
    w = _OrphanWatchdog(
        observer_config=cfg, requirements_text="req", wave_letter="B",
    )
    assert w.observer_config is cfg
    assert w.requirements_text == "req"
    assert w.wave_letter == "B"


def test_wave_watchdog_state_does_not_have_codex_fields():
    """Arch invariant: codex_* fields must not leak to _WaveWatchdogState."""
    from agent_team_v15.wave_executor import _WaveWatchdogState
    s = _WaveWatchdogState()
    assert not hasattr(s, "codex_last_plan")
    assert not hasattr(s, "codex_latest_diff")
```

## Phase Gate: Verification Checklist

From the repo root on branch phase-h3e-recovery-and-contract-guard:

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_v18_wave_executor_extended.py -v -k "peek or observer or watchdog"
python -m pytest tests/test_codex_appserver_steer.py -v  # regression
```

All tests pass. Plus these one-line architecture guards:

```bash
python -c "from agent_team_v15.wave_executor import _WaveWatchdogState; assert not hasattr(_WaveWatchdogState(), 'codex_last_plan'), 'ARCH VIOLATION: codex_last_plan must live on _OrphanWatchdog'"
python -c "from agent_team_v15.wave_executor import _WaveWatchdogState; s = _WaveWatchdogState(); assert hasattr(s, 'peek_schedule') and hasattr(s, 'peek_log') and hasattr(s, 'seen_files')"
python -c "from agent_team_v15.codex_appserver import _OrphanWatchdog; w = _OrphanWatchdog(); assert hasattr(w, 'codex_last_plan') and hasattr(w, 'observer_config')"
python -c "from agent_team_v15.wave_executor import _detect_new_peek_triggers, _should_fire_time_based_peek; print('helpers OK')"
```

Each must exit 0 and print no AssertionError. Additionally:

```bash
python -m compileall src/agent_team_v15/wave_executor.py src/agent_team_v15/codex_appserver.py
```

must compile clean.

## Handoff State

Phase 5 can rely on the following post-conditions:

1. `_WaveWatchdogState` has `peek_schedule`, `peek_log`,
   `last_peek_monotonic`, `peek_count`, `seen_files`. It has **no**
   `codex_last_plan` or `codex_latest_diff` field.
2. `_OrphanWatchdog.__init__` accepts keyword args `observer_config`,
   `requirements_text`, `wave_letter` with safe defaults, and initializes
   instance attrs `codex_last_plan = []` and `codex_latest_diff = ""`.
3. `_execute_once` forwards the three new kwargs to `_OrphanWatchdog`.
4. `_invoke_wave_sdk_with_watchdog` accepts `observer_config` and
   `requirements_text` kwargs; when non-None, calls `run_peek_call`
   between `asyncio.wait` return and the timeout check, with a
   `wait_for` timeout equal to `observer_config.peek_timeout_seconds`.
5. `_wait_for_turn_completion` contains a fail-open stub block (the
   `pass` placeholder) that Phase 5 replaces with a real call to
   `codex_observer_checks.evaluate(...)` and `client.turn_steer(...)`.
6. All peek/observer code paths are wrapped in try/except with
   `logger.warning("...fail-open", exc_info=True)` semantics.
