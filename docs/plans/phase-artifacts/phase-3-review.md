# Phase 3 — Peek Infrastructure: Review Brief

This review is **adversarial**. Assume the implementing agent was fast, tired, and skipped things. Every check below has been chosen because it catches a specific failure mode a rushed agent would hit. Do not mark a box "pass" unless you personally ran the command and read the output.

---

## What Was Implemented

Phase 3 adds the peek-observer type system:

1. **`ObserverConfig`** dataclass in `src/agent_team_v15/config.py` (inserted before `AgentTeamsConfig`) — 13 flat fields, safe defaults (`enabled=False`, `log_only=True`).
2. **`observer: ObserverConfig` field** on `AgentTeamConfig` at line ~1257 (immediately after `phase_leads`).
3. **`_CODEX_WAVES`, `PeekResult`, `PeekSchedule`, `build_peek_schedule`** in `src/agent_team_v15/wave_executor.py` between `WaveCheckpoint` and `_WaveWatchdogState`.
4. **`src/agent_team_v15/observer_peek.py`** — a new module implementing the Claude-wave file-poll strategy (Haiku-backed, fail-open). **Zero Codex notification code.**
5. Three new test files: `tests/test_observer_config.py`, `tests/test_peek_dataclasses.py`, `tests/test_observer_peek.py`.

Nothing is wired into the execution path yet; Phase 4 consumes these symbols.

---

## Critical Pre-Checks

Run these **first**. A failure here invalidates the phase immediately — do not continue the review.

### P1. Files exist with the correct content outline

```bash
cd C:/Projects/agent-team-v18-codex
ls src/agent_team_v15/observer_peek.py
ls tests/test_observer_config.py tests/test_peek_dataclasses.py tests/test_observer_peek.py
```
All four must exist. If `observer_peek.py` is missing, Task 3.3 was skipped.

### P2. Imports clean, no circular dependency

```bash
python -c "from agent_team_v15 import observer_peek, wave_executor, config; print('imports clean')"
```
Expected: `imports clean`. `observer_peek` imports `PeekResult`/`PeekSchedule` from `wave_executor`; `wave_executor` must NOT import `observer_peek` (that would be a circular import and also an architecture violation — Phase 4 is the layer that composes them).

Verify the non-reverse-dependency explicitly:
```bash
grep -n "from .observer_peek\|from agent_team_v15.observer_peek\|import observer_peek" src/agent_team_v15/wave_executor.py
```
**Expected: empty.** If any line matches, Phase 3 has leaked ahead into Phase 4 wiring — reject.

### P3. Anti-pattern scan — Codex code MUST NOT appear in observer_peek.py

```bash
grep -n "turn/plan\|turn/diff\|notification\|CodexNotificationEvent\|codex_appserver\|turn_steer" src/agent_team_v15/observer_peek.py
```
**Expected: empty output, exit code 1.** Any hit is an architecture violation. Reject the phase and require rewrite.

### P4. Safe defaults — the silent-by-default contract

```bash
python -c "from agent_team_v15.config import ObserverConfig; c = ObserverConfig(); assert c.log_only is True, 'log_only default must be True'; assert c.enabled is False, 'enabled default must be False'; print('safe defaults OK')"
```
If either assertion fires, reject. These defaults are the "never accidentally interrupts" contract.

### P5. `_CODEX_WAVES` membership is correct

```bash
python -c "from agent_team_v15.wave_executor import _CODEX_WAVES; expected = {'A5','B','D','T5'}; assert set(_CODEX_WAVES) == expected, f'got {set(_CODEX_WAVES)}'; print('codex waves OK')"
```
Common mistake: an agent "improving" the set by including `T` (Claude) or `A` (Claude). Any extra or missing entry = reject.

---

## Code Review Checklist

Walk the diff. Use `git diff master -- src/agent_team_v15/config.py src/agent_team_v15/wave_executor.py src/agent_team_v15/observer_peek.py tests/test_observer_config.py tests/test_peek_dataclasses.py tests/test_observer_peek.py`. Tick every box yourself — do not accept a "looks fine" skim.

### Correctness

- [ ] `ObserverConfig` declared as a **`@dataclass`** (not a plain class). Check line immediately above the class.
- [ ] Inserted **before** `AgentTeamsConfig` in `config.py` (roughly line 635 pre-insert). It must NOT be defined inside `AgentTeamConfig` or after it.
- [ ] All 13 `ObserverConfig` fields present with exact names and types:
  - `enabled: bool = False`
  - `log_only: bool = True`
  - `confidence_threshold: float = 0.75`
  - `context7_enabled: bool = True`
  - `context7_fallback_to_training: bool = True`
  - `model: str = "claude-haiku-4-5-20251001"`
  - `max_tokens: int = 512`
  - `peek_cooldown_seconds: float = 60.0`
  - `max_peeks_per_wave: int = 5`
  - `time_based_interval_seconds: float = 300.0`  *(float, not int — Phase 4 does float math on it)*
  - `codex_notification_observer_enabled: bool = True`
  - `codex_plan_check_enabled: bool = True`
  - `codex_diff_check_enabled: bool = True`
- [ ] **Field-name anti-aliases not present.** Run `grep -n "peek_model\|codex_notification_enabled\s*:\|claude_file_poll_enabled" src/agent_team_v15/config.py` — **must return empty**. These are the team-lead dispatch names that were explicitly superseded by the plan canonical names; if they leak in, Phase 4 imports break.
- [ ] `AgentTeamConfig` at line **1210** has exactly one new line: `observer: ObserverConfig = field(default_factory=ObserverConfig)`. Located after `phase_leads`, before `contract_engine`.
  ```bash
  grep -n "observer: ObserverConfig" src/agent_team_v15/config.py
  # Should print exactly ONE line in the 1255-1260 range.
  ```
- [ ] `_CODEX_WAVES` declared as `frozenset[str]`, not `set` or `list`. Mutability here would be a silent correctness bug.
- [ ] `PeekResult.timestamp` uses `field(default_factory=lambda: datetime.now(timezone.utc).isoformat())` — matches the style of `_WaveWatchdogState.started_at` on line 175.
- [ ] `PeekResult.should_interrupt` is a `@property`, not a method or plain attr. Tests rely on attribute access; a method decl would silently "pass" attribute-truth tests because bound methods are truthy.
- [ ] `PeekResult.should_steer` exists — Phase 5 consumes it for Codex `turn/steer` routing.
- [ ] `PeekSchedule.uses_notifications` uses `self.wave.upper() in _CODEX_WAVES` (case-insensitive).
- [ ] `build_peek_schedule` preserves insertion order when deduping: `list(dict.fromkeys(trigger_files))`. A plain `list(set(...))` is wrong (non-deterministic order).
- [ ] `run_peek_call` is declared `async def`. Phase 4 awaits it; a sync `def` would silently await a non-coroutine in Phase 4 and TypeError at runtime.
- [ ] Model string is `"claude-haiku-4-5-20251001"` (passed via `model` param from caller, default only in `ObserverConfig`). No hard-coded sonnet/opus IDs anywhere in `observer_peek.py`.

### Architecture

- [ ] **CRITICAL: observer_peek.py has ZERO Codex notification code.**
  ```bash
  grep -n "turn/plan\|turn/diff\|notification\|CodexNotificationEvent\|codex_appserver\|turn_steer" src/agent_team_v15/observer_peek.py
  # Expected: empty (exit code 1). Any hit = architecture violation = reject.
  ```
- [ ] Module docstring of `observer_peek.py` explicitly states "Codex waves do NOT use this module" — the anti-pattern reminder is preserved in the source so future readers see it without re-deriving the boundary.
- [ ] `observer_peek.py` imports `PeekResult`/`PeekSchedule` from `wave_executor` (one-way dependency). Phase-4 is the layer that wires them; `wave_executor.py` must NOT import `observer_peek`:
  ```bash
  grep -n "from .observer_peek\|from agent_team_v15.observer_peek\|import observer_peek" src/agent_team_v15/wave_executor.py
  # Expected: empty. Any hit = premature Phase-4 wiring = reject.
  ```
- [ ] **`_call_anthropic_api` uses `anthropic.AsyncAnthropic()`** — NOT `anthropic.Anthropic()` (sync). Using the sync client inside an async function would silently block the event loop.
- [ ] `client.messages.create(...)` call uses `system=` as a **top-level parameter**, not embedded as a system message in `messages=[...]`. Confirmed against Anthropic SDK docs.
- [ ] `import anthropic` is **inside** `_call_anthropic_api` (lazy), not at module top-level. Top-level import breaks the module in environments without the SDK installed and defeats the fail-open contract for non-observer callers.
  ```bash
  grep -n "^import anthropic\|^from anthropic" src/agent_team_v15/observer_peek.py
  # Expected: empty. The import must only appear inside _call_anthropic_api's body.
  ```
- [ ] Insertion location in `wave_executor.py`: after `_DeterministicGuardResult` (~line 170), before `_WaveWatchdogState` (line 173). Running `grep -n "^class\|^@dataclass" src/agent_team_v15/wave_executor.py | head -20` should show order:
  `WaveFinding` → `WaveResult` → `WaveCheckpoint` → `CheckpointDiff` → `CompileCheckResult` → `_DeterministicGuardResult` → **`PeekResult` → `PeekSchedule`** → `_WaveWatchdogState` → ...
- [ ] No new top-level imports added to `wave_executor.py` (`datetime`, `timezone`, `field`, `dataclass` already in scope; `re` imported lazily inside `build_peek_schedule`).

### Test Quality

- [ ] `tests/test_observer_config.py` has 3 tests: defaults (including `log_only=True`, `model=...`, `codex_notification_observer_enabled=True`), parent-field presence, and context7/time/max_peeks defaults.
- [ ] `tests/test_peek_dataclasses.py` has at least 6 tests including `_CODEX_WAVES` membership (B, D, A5, T5 in; A, T, D5, E out) and case-insensitive `uses_notifications`.
- [ ] `tests/test_observer_peek.py` contains a **fail-open test** (`test_run_peek_call_fails_open_on_api_exception`) that mocks `_call_anthropic_api` with `side_effect=RuntimeError("boom")` and asserts no exception escapes. If this test is missing, the fail-open contract is unverified — reject.
- [ ] `tests/test_observer_peek.py` asserts the JSONL log file is **actually written** (`(tmp_path / ".agent-team" / "observer_log.jsonl").exists()`), not just that the function returned.
- [ ] No `or True` short-circuits in any assertion (plan Correction #9 flagged this anti-pattern). Check:
  ```bash
  grep -n "or True" tests/test_observer_config.py tests/test_peek_dataclasses.py tests/test_observer_peek.py
  # Expected: empty.
  ```
- [ ] No `@pytest.mark.skip`, no `pytest.importorskip("anthropic")` in the three new test files — skipping hides the fail-open contract.
- [ ] Tests use `unittest.mock.AsyncMock` + `patch("agent_team_v15.observer_peek._call_anthropic_api", ...)` — the mock target is the module-local name, not `anthropic.AsyncAnthropic` directly.

### Integration Safety

- [ ] `run_peek_call` has a **top-level `try/except Exception`** wrapping its entire body that returns a safe `PeekResult(verdict="ok", confidence=0.0, ...)`. Verify by reading end-to-end: there must be `return safe_result` in the outermost except branch. A raised exception here would abort the wave in Phase 4.
- [ ] The **inner** try/except around `_call_anthropic_api` is still present (two layers: API errors → degrade to `{"verdict":"ok","confidence":0.0}`; any other error → outer safe result).
- [ ] `_write_observer_log` is called in both the happy path **and** the outer safe-result path. The observer log must be append-only proof that the observer ran, even on infrastructure failure.
- [ ] `_write_observer_log` itself is wrapped in try/except and never raises (I/O, permission errors on `.agent-team/` must not crash the wave).
- [ ] Safe defaults hold end-to-end: `AgentTeamConfig().observer.log_only is True` AND `AgentTeamConfig().observer.enabled is False`. These are the "observer never accidentally interrupts" contract.
- [ ] No `# TODO`, no `pass`, no `...` placeholders in `observer_peek.py`:
  ```bash
  grep -n "# TODO\|NotImplementedError\|^\s*pass\s*$\|^\s*\.\.\.\s*$" src/agent_team_v15/observer_peek.py
  # Expected: empty.
  ```
- [ ] Three git commits landed with the messages specified in Tasks 3.1, 3.2, 3.3 — one per task, no squashing, no extra files, no unrelated changes.

---

## Test Run Commands

Run these in order. Stop at the first failure.

```bash
cd C:/Projects/agent-team-v18-codex

# 1. Phase 3 test suite
python -m pytest tests/test_observer_config.py tests/test_peek_dataclasses.py tests/test_observer_peek.py -v

# 2. Targeted fail-open verification
python -m pytest tests/test_observer_peek.py::test_run_peek_call_fails_open_on_api_exception -v

# 3. Full existing suite regression — Phase 3 must break nothing
python -m pytest tests/ -x -q --ignore=tests/test_smoke

# 4. Import smoke
python -c "from agent_team_v15 import observer_peek, wave_executor, config; print('imports clean')"

# 5. Round-trip default instantiation
python -c "from agent_team_v15.config import AgentTeamConfig; c = AgentTeamConfig(); assert c.observer.log_only is True; assert c.observer.model == 'claude-haiku-4-5-20251001'; print('wiring OK')"

# 6. Anti-pattern scan
grep -n "turn/plan\|turn/diff\|notification\|CodexNotificationEvent\|codex_appserver" src/agent_team_v15/observer_peek.py
# Expected empty.

# 7. Strategy split
python -c "from agent_team_v15.wave_executor import build_peek_schedule; assert build_peek_schedule('','B').uses_notifications is True; assert build_peek_schedule('','A').uses_notifications is False; print('split OK')"
```

If command 3 (full suite regression) reports failures that are not pre-existing, those are Phase 3's fault — trace the breakage before accepting.

---

## Acceptance Criteria

Phase 3 is accepted when **all** of the following are true:

1. All 14+ Phase-3 tests pass under `pytest -v`. (3 config + 6 dataclass + 5 peek = 14 minimum.)
2. P1 through P5 (Critical Pre-Checks) all pass.
3. Every box in C1–C4 (Code Review Checklist) is ticked, by hand, by the reviewer.
4. `grep -n "turn/plan\|turn/diff\|notification\|CodexNotificationEvent\|codex_appserver" src/agent_team_v15/observer_peek.py` is empty.
5. `grep -n "peek_model\|codex_notification_enabled\s*:\|claude_file_poll_enabled" src/agent_team_v15/config.py` is empty.
6. `grep -n "from .observer_peek\|from agent_team_v15.observer_peek\|import observer_peek" src/agent_team_v15/wave_executor.py` is empty (no premature Phase-4 wiring).
7. Full existing test suite (excluding smoke) has zero new failures attributable to Phase 3.
8. `AgentTeamConfig().observer.log_only is True` — the silent-by-default contract holds end to end.
9. `build_peek_schedule("","B").uses_notifications is True` AND `build_peek_schedule("","A").uses_notifications is False`.
10. `PeekResult(file_path="x", wave="B", verdict="issue", confidence=0.9, log_only=False).should_interrupt is True` AND the same with `log_only=True` returns `False`.
11. Three git commits were created with the messages specified in Tasks 3.1, 3.2, 3.3 (one per task, no squashing, no extra files).

**If any criterion above is unmet, Phase 3 is rejected.** Do not move to Phase 4 until every item is green.

### Adversarial Final Pass

Before signing off, take 60 seconds to look for these specific sloppy-agent tells:

- An extra `observer: ObserverConfig` field accidentally added to `AgentTeamsConfig` (wrong parent).
- `_CODEX_WAVES` declared as a `set` (mutable), `list`, or missing the type annotation.
- `PeekResult.should_interrupt` implemented as a method (`def should_interrupt(self):`) instead of a `@property`. Tests would still pass if the method is never called — but Phase 4 accesses it as an attribute.
- `run_peek_call` missing `async` keyword — would manifest as Phase 4 getting a coroutine-wrapper TypeError.
- A lone `import anthropic` at module top-level in `observer_peek.py` — this breaks import in environments without the SDK installed. The import belongs **inside** `_call_anthropic_api` (per the source in the impl brief).
- Tests skipped via `@pytest.mark.skip` or `pytest.importorskip("anthropic")` — that would hide the fail-open contract.
- `log_only=False` accidentally hard-coded into `ObserverConfig` defaults "because the developer was testing".

Only after all of the above have been checked by eye — not just greppped — should the phase gate be opened.
