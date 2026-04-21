# Phase 5 — Semantic Observer: Review Brief

> **Reviewer stance.** This review is adversarial by design. Assume the implementation agent was rushed. Assume they copied blocks without reading them. Assume they silenced a failing test with `or True`. Your job is to find the hole before smoke does. Every check below is a separate trip-wire — run them all.

---

## What Was Implemented

Phase 5 landed three deliverables on top of the Phase 0/3/4 scaffolding:

1. **New module `src/agent_team_v15/codex_observer_checks.py`** — two public functions, both fail-open:
   - `check_codex_plan(plan_lines: list[str], wave_letter: str) -> str`
   - `check_codex_diff(diff_text: str, wave_letter: str) -> str`
   Rule-based regex scope-drift detection for Wave B (backend; rejects frontend) and Wave D (frontend; rejects backend). Any other wave letter returns `""`. Pure stdlib (`re`, `logging`); no Anthropic SDK, no network, no `asyncio`.
2. **Real check wired into `_wait_for_turn_completion`** in `src/agent_team_v15/codex_appserver.py`. The Phase 4 stub marker (`# Phase 5 will replace this stub`) is gone. Imports are lazy inside a try block. When a non-empty steer is produced and `observer_config.log_only` is False, `client.turn_steer(thread_id, turn_id, steer_msg)` is awaited. When `log_only` is True, the steer is logged but not sent.
3. **New field `WaveResult.peek_summary: list[dict[str, Any]]`** and population at the three caller sites of `_invoke_wave_sdk_with_watchdog` (~lines 3332, 3800, 3863 in `wave_executor.py`). Plus helper `_should_fire_time_based_peek(last_peek_monotonic, interval_seconds, peek_count, max_peeks) -> bool` and its wiring into the Claude polling loop.

---

## Critical Pre-Checks (run these FIRST — any failure means stop reviewing and send the PR back)

```bash
cd C:/Projects/agent-team-v18-codex

# PRE-CHECK 1 — fatal "or True" test anti-pattern.
grep -n "or True" tests/test_codex_observer_checks.py
# Expected: no output. ANY match is fatal — the test file is silently always-passing. Reject the PR.

# PRE-CHECK 2 — Phase 4 stub marker fully removed.
grep -n "Phase 5 will replace this stub" src/agent_team_v15/codex_appserver.py
# Expected: no output. A surviving marker means Task 5.2 did not land. Reject.
# NOTE: Zero matches can mean either (a) Phase 4 was applied and Phase 5 successfully
# replaced the stub — PASS; OR (b) Phase 4 was never applied and the stub was never
# written — FAIL. Disambiguate by also running:
python -c "from agent_team_v15.codex_appserver import _OrphanWatchdog; assert hasattr(_OrphanWatchdog(), 'codex_last_plan'), 'Phase 4 absent'"
# If this assertion fails, Phase 4 is absent and zero matches on the stub grep is a FAIL.

# PRE-CHECK 3 — no Anthropic/network leak into the rule-based module.
grep -nE "(^import anthropic|from anthropic|import httpx|from httpx|import asyncio|from asyncio)" src/agent_team_v15/codex_observer_checks.py
# Expected: no output. A leak means the agent ignored the "rule-based ONLY" rule. Reject.

# PRE-CHECK 4 — lazy import at call site, NOT at module top.
grep -n "from agent_team_v15.codex_observer_checks\|from .codex_observer_checks" src/agent_team_v15/codex_appserver.py
# Expected: a single hit, indented (i.e., inside a function body), surrounded by try/except. A top-level hit is a bug — the fail-open contract is broken because the import is outside the try.

# PRE-CHECK 5 — regex uses `search`, not `match`.
grep -n "re\.match\|\.match(" src/agent_team_v15/codex_observer_checks.py
# Expected: no output. `.match()` only matches at position 0 and will false-negative on paths. Reject.

# PRE-CHECK 6 — peek_summary field exists and is typed correctly.
python -c "from agent_team_v15.wave_executor import WaveResult; f = WaveResult.__dataclass_fields__['peek_summary']; assert f.default_factory is list, 'default_factory must be list'; print('peek_summary field OK')"
# Expected: "peek_summary field OK". If KeyError or AssertionError, reject.

# PRE-CHECK 7 — no placeholder code left behind.
grep -nE "# TODO|# FIXME|pass  #|NotImplementedError|\.\.\.  #" src/agent_team_v15/codex_observer_checks.py
# Expected: no output. The rules module must be complete.

# PRE-CHECK 8 — no emoji anywhere in the new module (Windows console compat).
python -c "import re, sys; t = open('src/agent_team_v15/codex_observer_checks.py', encoding='utf-8').read(); nonascii = [c for c in t if ord(c) > 127]; sys.exit(0 if not nonascii else 'Non-ASCII chars found: ' + repr(nonascii[:10]))"
# Expected: exit 0. Non-ASCII in this module is suspicious.
```

If any pre-check fails, stop and send back. If all pass, continue.

---

## Code Review Checklist

### `codex_observer_checks.py`

- [ ] Module docstring explicitly states "NO Anthropic SDK, NO API calls, NO network" and mentions fail-open.
- [ ] `_FRONTEND_FILE_PATTERNS` is a `list[re.Pattern]`, not a single compiled alternation. (List form is easier to extend and yields per-pattern hits.)
- [ ] `_FRONTEND_FILE_PATTERNS` includes at minimum: `apps/web/`, `(^|/)pages/`, `(^|/)components/`, `\.tsx$`, `\.jsx$`, `\.css$`, `tailwind\.config`.
- [ ] `_BACKEND_FILE_PATTERNS` includes at minimum: `apps/api/`, `(^|/)prisma/`, `nest-cli\.json`, `\.module\.ts$`, `Dockerfile`, `docker-compose...ya?ml`, `\.py$`.
- [ ] `_DRIFT_THRESHOLD = 2` and `_SMALL_DIFF_FLOOR = 3` are module-level constants (not magic numbers inside functions).
- [ ] `_WAVE_FORBIDDEN` maps `"B"` → frontend patterns and `"D"` → backend patterns. No other keys. Wave letters are normalised via `.upper()` before lookup.
- [ ] `check_codex_plan` and `check_codex_diff` both have a `try: ... except Exception:` that returns `""` and logs via `logger.warning("... fail-open ...", exc_info=True)`.
- [ ] `check_codex_diff` extracts changed paths from `diff --git a/X b/Y` headers (preferred) and falls back to `+++ b/X`. It deduplicates paths into a set so one file with many hunks counts once.
- [ ] `check_codex_diff` returns `""` immediately if fewer than `_SMALL_DIFF_FLOOR` distinct files are changed. Verify by inspection — this is the anti-false-positive guard for early-turn diffs.
- [ ] `check_codex_diff` returns `""` if the offending count is strictly less than `_DRIFT_THRESHOLD`. Two offending files triggers; one does not.
- [ ] Steer message contains the literal string `"Wave B"` (or `"Wave D"`), the role (backend/frontend), and up to three offending paths.
- [ ] No unused imports.

### `codex_appserver.py` — `_wait_for_turn_completion` edits

- [ ] Import of `check_codex_plan` and `check_codex_diff` happens INSIDE a try block, INSIDE `_wait_for_turn_completion`, not at the top of the module.
- [ ] Both `watchdog.codex_latest_diff` and `watchdog.codex_last_plan` are consulted. Diff is checked first; plan is only checked if the diff produced no steer.
- [ ] The code uses `getattr(watchdog, "<attr>", default)` for every observer attribute read. (Defence against stale watchdog instances.)
- [ ] Steer is only dispatched when `steer_msg` is truthy AND `observer_config is not None` AND `not observer_config.log_only`.
- [ ] When `log_only` is True (or `observer_config` is None), the code logs `"Observer (log_only) would steer Codex Wave %s: %s"` and does NOT call `client.turn_steer`.
- [ ] The outer `except Exception:` wraps EVERYTHING including the import line. Confirm by reading the indentation.
- [ ] The block does not `await` anything outside the steer dispatch. No sleeping, no polling.
- [ ] No `print(...)` calls. All output goes through `logger`.

### `wave_executor.py` — `WaveResult`, `_should_fire_time_based_peek`, caller wiring

- [ ] `peek_summary: list[dict[str, Any]] = field(default_factory=list)` appears after the `scope_violations` field and before the class boundary. No existing field was moved.
- [ ] `_should_fire_time_based_peek` uses `time.monotonic()` (not `time.time()`).
- [ ] `_should_fire_time_based_peek` returns `False` if `peek_count >= max_peeks` OR `interval_seconds <= 0`. (The zero-interval guard prevents divide-by-zero-style spam.)
- [ ] All three caller sites (lines ~3332, ~3800, ~3863) populate `wave_result.peek_summary` from `watchdog_state.peek_log`. Missing any of the three will cause smoke to report empty `peek_summary` for certain code paths.
- [ ] The population block uses `getattr(r, "<field>", default)` for every `PeekResult` attribute read. No direct attribute access.
- [ ] `wave_result.peek_summary` is NEVER populated from anywhere other than `watchdog_state.peek_log`. (Do not permit ad-hoc population elsewhere — that would mask bugs.)
- [ ] The Claude polling loop fires `state.last_peek_monotonic = time.monotonic()` after BOTH the file-event trigger and the new time-based trigger. If either path omits the update, the time-based trigger spam-fires.

### Test file `tests/test_codex_observer_checks.py`

- [ ] Contains `test_check_codex_diff_wave_b_detects_frontend` — asserts `msg != ""` AND `"Wave B" in msg`.
- [ ] Contains `test_check_codex_diff_wave_b_clean` — asserts `msg == ""`.
- [ ] Contains `test_check_codex_diff_wave_d_detects_backend` — asserts non-empty AND `"Wave D" in msg` AND `"frontend" in msg.lower()`.
- [ ] Contains `test_check_codex_diff_empty_diff_no_steer` — exercises both `""` and whitespace-only input.
- [ ] Contains `test_check_codex_diff_small_diff_below_floor_no_steer` — the three-file-floor guard. Two frontend files in Wave B → `""`.
- [ ] Contains `test_check_codex_diff_single_incidental_touch_no_steer` — drift threshold guard. One frontend file in a three-file Wave B diff → `""`.
- [ ] Contains `test_check_codex_diff_non_target_wave_no_steer` — Wave A/T/E pass-through.
- [ ] Contains `test_check_codex_plan_wave_b_frontend_plan` with a specific assertion on `"Wave B"`.
- [ ] Contains `test_check_codex_plan_wave_b_clean_plan` asserting `== ""`.
- [ ] Contains `test_check_codex_plan_single_hit_below_threshold_no_steer`.
- [ ] Contains `test_check_codex_plan_empty_input_no_steer` exercising both `[]` and `["", "   "]`.
- [ ] Contains `test_check_codex_plan_non_target_wave_no_steer`.
- [ ] Contains a fail-open exception test for BOTH functions (`test_check_codex_diff_exception_returns_empty`, `test_check_codex_plan_exception_returns_empty`). Each uses `monkeypatch` to force an internal failure and asserts the return is `""`.
- [ ] Contains a cross-validation test (`test_cross_validation_plan_and_diff_agree_on_wave_b`) that feeds the same offending path set into both functions and asserts both produce non-empty `"Wave B"` messages.
- [ ] ZERO tests contain `or True`, `assert True`, or `assert isinstance(x, str)` as the only assertion. Every test must fail if the function under test misbehaves.
- [ ] No test has a bare `except` that would swallow assertion errors.

---

## Test Run Commands

```bash
cd C:/Projects/agent-team-v18-codex

# Unit suite for this phase.
python -m pytest tests/test_codex_observer_checks.py -v
# Expect: 14 passed in <2s.

# Wave executor extended tests (peek helper additions).
python -m pytest tests/test_v18_wave_executor_extended.py -v
# Expect: full green.

# Import smoke — catches syntax errors in the new module.
python -c "import agent_team_v15.codex_observer_checks as m; print(m.__doc__[:80])"

# WaveResult field smoke.
python -c "from agent_team_v15.wave_executor import WaveResult; r = WaveResult(wave='B'); assert r.peek_summary == []; print('WaveResult.peek_summary default OK')"

# _should_fire_time_based_peek smoke.
python -c "from agent_team_v15.wave_executor import _should_fire_time_based_peek; import time; assert _should_fire_time_based_peek(time.monotonic()-120, 60.0, 0, 5) is True; assert _should_fire_time_based_peek(time.monotonic()-10, 60.0, 0, 5) is False; assert _should_fire_time_based_peek(0.0, 60.0, 5, 5) is False; assert _should_fire_time_based_peek(0.0, 0.0, 0, 5) is False; print('time-based peek OK')"

# Mutation sanity — confirm the steer actually fires on a realistic Wave B frontend diff.
python -c "
from agent_team_v15.codex_observer_checks import check_codex_diff
diff = 'diff --git a/apps/web/pages/a.tsx b/apps/web/pages/a.tsx\n+++ b/apps/web/pages/a.tsx\ndiff --git a/apps/web/pages/b.tsx b/apps/web/pages/b.tsx\n+++ b/apps/web/pages/b.tsx\ndiff --git a/apps/web/styles.css b/apps/web/styles.css\n+++ b/apps/web/styles.css\n'
msg = check_codex_diff(diff, 'B')
assert msg and 'Wave B' in msg, f'expected Wave B steer, got: {msg!r}'
print('Wave B steer fires on realistic diff')
"

# Negative mutation sanity — confirm a pure backend diff is clean for Wave B.
python -c "
from agent_team_v15.codex_observer_checks import check_codex_diff
diff = 'diff --git a/apps/api/main.py b/apps/api/main.py\n+++ b/apps/api/main.py\ndiff --git a/apps/api/users.py b/apps/api/users.py\n+++ b/apps/api/users.py\ndiff --git a/apps/api/db.py b/apps/api/db.py\n+++ b/apps/api/db.py\n'
msg = check_codex_diff(diff, 'B')
assert msg == '', f'expected empty steer for clean backend diff, got: {msg!r}'
print('Clean backend diff is silent for Wave B')
"
```

---

## Acceptance Criteria

Phase 5 is accepted only if every bullet is true:

- [ ] All eight PRE-CHECK commands produce their expected output (no `or True`, no stub marker, no Anthropic leak, lazy import, no `re.match` on paths, `peek_summary` field exists with `list` default factory, no TODO/FIXME, ASCII-only).
- [ ] `pytest tests/test_codex_observer_checks.py -v` reports 14 passed, 0 failed, 0 skipped.
- [ ] `pytest tests/test_v18_wave_executor_extended.py -v` is fully green.
- [ ] Both mutation-sanity commands in "Test Run Commands" print their success lines.
- [ ] Manual reading of `_wait_for_turn_completion` confirms: imports are inside the try block; both `codex_latest_diff` and `codex_last_plan` are consulted; `turn_steer` is only called when `observer_config` exists AND `log_only` is False; the `except Exception:` net covers the entire block including the import.
- [ ] Manual reading of `wave_executor.py` confirms: `peek_summary` populated at all three caller sites of `_invoke_wave_sdk_with_watchdog`; `_should_fire_time_based_peek` uses `time.monotonic()`; the Claude polling loop updates `state.last_peek_monotonic` on every peek fire (both file-event and time-based paths).
- [ ] No new top-level imports of `anthropic`, `httpx`, or any network library were added to any file in Phase 5.
- [ ] `git diff --stat` for Phase 5 shows changes restricted to: `src/agent_team_v15/codex_observer_checks.py` (new), `src/agent_team_v15/codex_appserver.py` (modified — `_wait_for_turn_completion` only), `src/agent_team_v15/wave_executor.py` (modified — `WaveResult`, `_should_fire_time_based_peek`, three caller sites, Claude polling loop), `tests/test_codex_observer_checks.py` (new), `tests/test_v18_wave_executor_extended.py` (appended tests only).
- [ ] No modification to `codex_transport.py`, `config.py`, `observer_peek.py`, `agent_teams_backend.py`, or any Phase 0/1/3/4 surface. If the agent touched those files, they over-reached — reject.

**Adversarial reviewer tip.** If all checks above pass, run the full suite once more with `pytest -x tests/` from a clean checkout and confirm no other tests regressed. Phase 5 adds fields to `WaveResult` and a helper to `wave_executor.py`; either change can silently break downstream consumers that pickle or introspect these types.
