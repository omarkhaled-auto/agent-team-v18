# Phase 4 â€” Peek Integration: Reviewer Verdict

**Reviewer session:** 2026-04-21
**Branch reviewed:** master (working tree, uncommitted per the branch workflow memo â€” changes live in the working tree only)
**Verdict:** **PASS**

## Executive summary

Every acceptance criterion is satisfied. A review-time documentation nit
was found for criterion #6: a `_WaveWatchdogState` comment mentioned the
Codex plan/diff field names even though the fields did not exist there.
The implementation follow-up rephrased that comment, so the literal grep
against `wave_executor.py` is also clean.

## Pre-checks (all pass)

| Check | Result |
|-------|--------|
| 1 â€” architecture (no codex fields on `_WaveWatchdogState`) | **PASS** â€” assertion exits 0 for both attrs |
| 2 â€” Claude peek fields present with correct defaults | PASS |
| 3 â€” Codex watchdog observer fields present with correct defaults | PASS |
| 4 â€” helpers exist with correct signature | PASS (`_detect_new_peek_triggers(cwd, baseline, seen_files)`, `_should_fire_time_based_peek(state, observer_config)`) |
| 5 â€” Codex observer kwargs keyword-only | PASS (all three KEYWORD_ONLY) |
| 6 â€” `compileall` clean | PASS |

## Code Review Checklist (diff walked)

### 4.1 `_WaveWatchdogState` fields

- [x] Fields sit between `interrupt_count` (L274) and `record_progress(...)` (L283) â€” not interleaved.
- [x] `peek_schedule: PeekSchedule | None = None` (not the bare `PeekSchedule = None` footgun).
- [x] `peek_log` and `seen_files` both use `field(default_factory=...)` â€” no shared mutable defaults.
- [x] **Grep nit resolved:** `codex_last_plan|codex_latest_diff` now returns zero matches in `wave_executor.py`. Architecture Check 1 independently confirms no such attribute exists on `_WaveWatchdogState`.
- [x] `ObserverConfig` imported at module top (L29). `PeekSchedule` / `PeekResult` / `build_peek_schedule` are *defined* in the same module (L179, L213, L227), so no import needed â€” acceptable. `run_peek_call` is lazy-imported at the call site (L2741) to avoid import cycles â€” explicitly sanctioned.

### 4.2 Peek helpers & loop injection

- [x] `_detect_new_peek_triggers` compares current to both `baseline` and `seen_files`; does *not* mutate `seen_files` (mutation happens at the call site, L2762 `state.seen_files.add(file_for_peek)`).
- [x] `_should_fire_time_based_peek` uses `>=` (L2655) against `max_peeks_per_wave` â€” no off-by-one.
- [x] Returns False when `time_based_interval_seconds <= 0` (L2657).
- [x] Uses `time.monotonic()` (L2659).
- [x] Peek injection: after `if task in done: return ...` (L2903â€“2904 / L3031â€“3032) and before `_build_wave_watchdog_timeout(...)`. Both Claude-only and provider-wave paths have the hook correctly placed.
- [x] Peek await wrapped in `asyncio.wait_for(peek_coro, timeout=float(observer_config.peek_timeout_seconds))` (L2755-2758).
- [x] Whole block wrapped in `try/except asyncio.TimeoutError` + `try/except Exception` with `exc_info=True` on the broad branch (L2771-2782).
- [x] `log_only` respected: `run_peek_call` itself sets `should_interrupt=False` whenever `log_only=True` (observer_peek.py L161). Caller gate is `if peek_result.should_interrupt and state.client is not None`, so no interrupt fires in log-only mode.
- [x] `milestone_id = str(getattr(milestone, "id", "") or "")` (inside `_initialize_wave_peek_schedule`).
- [x] `observer_config` and `requirements_text` are keyword-only on both `_invoke_wave_sdk_with_watchdog` (L2857) and `_invoke_provider_wave_with_watchdog` (L2958) â€” both have `*` before them, with `None` / `""` defaults.
- [x] After firing a peek, all three state fields update: `peek_count += 1`, `last_peek_monotonic = time.monotonic()`, `seen_files.add(...)` (L2759-2762).

### 4.3 `_OrphanWatchdog` + `_wait_for_turn_completion`

- [x] All three new `__init__` params are keyword-only (after the existing `*`, L162-164). Verified structurally by Check 5.
- [x] `codex_last_plan = []` and `codex_latest_diff = ""` initialized in `__init__` body (codex_appserver.py L183-184) â€” not default params, not class attrs.
- [x] `observer_config` stored directly as the `ObserverConfig` reference (L178), no more `dict(observer_config or {})` coercion. This matches the stored-typed-object invariant from the Phase 4 brief.
- [x] `_execute_once` has the three new keyword-only params (L1195-1197) and forwards them to the `_OrphanWatchdog(...)` call (L1206-1208).
- [x] `execute_codex(...)` top-level entry point also forwards them via `_execute_once(...)` call (L1419-1430).
- [x] Stub hook sits after `_process_streaming_event(...)` (L1097-1104) and before `if message.get("method") == "error":` (L1123) â€” correct placement.
- [x] Stub is guarded by `watchdog.observer_config is not None and not watchdog.observer_config.log_only and watchdog.codex_latest_diff` (L1110-1114) and wrapped in `try: pass except Exception: logger.warning(..., exc_info=True)`.
- [x] Stub contains a single `pass` (L1116); no `client.turn_steer(...)` â€” Phase 5 is intact.
- [x] `log_only` honored in the stub via the `not watchdog.observer_config.log_only` clause.

### Integration safety

- [x] Phase 0 wiring: `_process_streaming_event` sets `watchdog.codex_last_plan = list(plan)` (L1043) and `watchdog.codex_latest_diff = diff` (L1049). The stub hook will receive live data at Phase 5 time.
- [x] `provider_router._build_codex_observer_kwargs` dynamically checks each transport's signature (via `_call_accepts_kwarg`) before forwarding the three kwargs â€” backward compatible with legacy Codex transports that predate Phase 4. Slight oddity: `side_effect` introspection in that helper is a test-double workaround, but it is localized and not load-bearing for production code paths.

## Test results

All required suites pass, no skips.

```
tests/test_v18_wave_executor_extended.py  -k "peek or observer or watchdog" : 11 passed
tests/test_codex_appserver_steer.py                                          : 3 passed
tests/test_v18_wave_executor_extended.py                                      : 30 passed
pytest tests/ -k "wave or watchdog or codex"                                  : 906 passed, 1 skipped (pre-existing)
python -m compileall src/agent_team_v15/wave_executor.py src/agent_team_v15/codex_appserver.py : exit 0
```

The `test_wave_watchdog_state_does_not_have_codex_fields` and
`test_orphan_watchdog_has_observer_fields` regression guards are green â€”
the architectural split is now enforced by both the code *and* a test.

## Acceptance-criteria tally

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Check 1 (architecture) passes | PASS |
| 2 | Checks 2â€“6 pass | PASS |
| 3 | Every checklist item verified from diff | PASS |
| 4 | Peek/observer/watchdog pytest slice green, no new skips | PASS |
| 5 | `test_codex_appserver_steer.py` still green | PASS (3/3) |
| 6 | Grep for `codex_last_plan\|codex_latest_diff` in `wave_executor.py` returns zero matches | PASS |
| 7 | Grep for `observer_config` in `codex_appserver.py` â‰¥ 3 matches | PASS (8 matches) |
| 8 | `compileall` exits 0 | PASS |
| 9 | Exactly one `pass` in the sanctioned Phase-5 stub | PASS (codex_appserver.py L1116, no others in the diff) |
| 10 | Handoff state in PR description matches impl brief | Impl agent's handoff summary is consistent with the Phase 4 brief. The untracked `.tmp-codex-src/` and `phase-5-5-audit*` files are pre-existing and out of scope for this phase. |

## Builder-run thought experiment

I mentally ran three scenarios against the live code to check that the
wiring is more than test-green:

**Scenario 1 â€” pure Claude wave (e.g., wave A, observer enabled).**
`_execute_wave_sdk` â†’ `_invoke_wave_sdk_with_watchdog` with
`observer_config=config.observer, requirements_text=""`.
`_initialize_wave_peek_schedule` reads
`.agent-team/milestones/<id>/REQUIREMENTS.md` because
`requirements_text` is empty, builds a file-poll `PeekSchedule`
(wave letter is not in `_CODEX_WAVES`). Each iteration after
`asyncio.wait(...)` the peek helper diffs fingerprints, fires on new
files, applies budget/cooldown gates, awaits `run_peek_call` under
`wait_for(..., 5.0)`, logs/interrupts per verdict, then falls through
to the existing timeout gate. If observer is globally disabled
(`config.observer.enabled=False`, the default),
`_initialize_wave_peek_schedule` no-ops and the peek helper returns
immediately â€” zero runtime impact on existing Claude paths.

**Scenario 2 â€” pure Codex wave (provider route, no fallback).**
`_invoke_provider_wave_with_watchdog` builds the schedule with
`uses_notifications=True` for Codex-letter waves, so the peek helper's
first guard (`state.peek_schedule.uses_notifications and not
force_file_poll`) returns early. Meanwhile `provider_router`'s
`_build_codex_observer_kwargs` forwards `observer_config`,
`requirements_text`, and `wave_letter` to `execute_codex`, which
constructs `_OrphanWatchdog` with those kwargs. Inside
`_wait_for_turn_completion`, `_process_streaming_event` keeps
`codex_last_plan` / `codex_latest_diff` fresh; the Phase-5 stub fires
`pass` after each notification (no-op in Phase 4).

**Scenario 3 â€” Codex-routed wave that falls back to Claude.**
`force_claude_fallback_reason` is set by the router â†’
`_provider_route_uses_claude_file_poll` returns True â†’ `force_file_poll`
overrides the `uses_notifications` guard â†’ the Claude-style file-poll
peek runs against a Codex-letter wave. This is the trickiest path and
it is implemented correctly.

Edge cases I specifically examined:

- Initial `last_peek_monotonic=0.0` makes `_should_fire_time_based_peek`
  return True on iteration 1, but without new triggers and without
  `seen_files` populated yet, the helper falls through to `files_for_peek=[]`
  and early-returns. No spurious peek.
- `run_peek_call` failure/timeout: wrapped in two except branches,
  both log with fail-open semantics; state is not updated on failure
  (because the state-update lines come after `await asyncio.wait_for`).
  That means a failing peek does **not** burn budget, which is the
  correct behaviour â€” a hung observer call shouldn't prevent a later
  successful one.
- `observer_config=None`: `_initialize_wave_peek_schedule` and
  `_run_wave_observer_peek` both guard on `observer_config is None`.
  Safe.
- Per-iteration budget: `if state.peek_count >= observer_config.max_peeks_per_wave: break`
  inside the file loop (L2744) prevents the "multiple new files in one
  iteration overshoot the budget" failure mode.

## Recommendations (non-blocking)

1. Consider asserting `observer_config.peek_timeout_seconds > 0` at
   config-load time (not Phase 4 scope, but easy defense-in-depth for
   Phase 5).
2. The `side_effect` introspection in
   `provider_router._call_accepts_kwarg` is a test-driven concession;
   once all Codex transports uniformly accept the three kwargs, the
   helper can be deleted and the call can be unconditional.

## Verdict

**PASS.** Phase 4 is safe to hand off to Phase 5. The architecture
separation is rigorously enforced (field-level + test-level), all
observer-peek code paths are fail-open, log_only is honored in both
paths, and regressions are clean across the 906-test wave/watchdog/codex
slice. The review-time grep nit has been resolved.
