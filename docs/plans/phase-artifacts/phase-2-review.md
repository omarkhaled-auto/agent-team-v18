# Phase 2 — Replay Harness: Review Brief

This review brief is deliberately adversarial. The implementation agent moves fast and skips rarely-enforced contracts. The goal of this review is to catch every such skip **before** Phase 5 wires the replay harness into the live-mode promotion gate. If the reviewer accepts a broken `safe_to_promote` contract here, Phase 5 will gate live `client.interrupt()` calls on a lie.

## What Was Implemented

Phase 2 created one new module and one new test file:

- `src/agent_team_v15/replay_harness.py` — offline calibration harness: `ReplaySnapshot`, `ReplayReport`, `CalibrationReport`, `ReplayRunner`, `generate_calibration_report`.
- `tests/test_replay_harness.py` — five tests covering the promotion gate thresholds, DI of the peek callable, and fail-open behaviour.

No other files changed. The harness reads frozen `cwd-snapshot-*` directories via a caller-injected async peek callable and aggregates per-peek false-positive / true-positive counts across snapshots. `CalibrationReport.safe_to_promote` is True iff `build_count >= 3 AND false_positive_rate < 0.10`. Phase 5 will import `generate_calibration_report` and use `safe_to_promote` as the single gate before enabling live-mode observer interrupts.

## Critical Pre-Checks

Run these before any code reading. If any fail, the review stops and the implementation is returned.

1. Module exists and imports cleanly:
   ```bash
   cd C:/Projects/agent-team-v18-codex
   python -c "from agent_team_v15.replay_harness import CalibrationReport, ReplayReport, ReplayRunner, ReplaySnapshot, generate_calibration_report; print('imports OK')"
   ```
2. Test file exists:
   ```bash
   python -c "from pathlib import Path; assert Path('tests/test_replay_harness.py').exists(); print('test file present')"
   ```
3. No Phase-3 imports in replay_harness.py (Protocol isolation):
   ```bash
   python -c "
   from pathlib import Path
   src = Path('src/agent_team_v15/replay_harness.py').read_text(encoding='utf-8')
   for banned in ('observer_peek', 'from agent_team_v15.observer', 'import observer_peek'):
       assert banned not in src, f'BANNED token {banned!r} found in replay_harness.py'
   print('no-import invariant OK')
   "
   ```
   Also verify via `Grep`:
   ```bash
   # Use the repo's Grep tool equivalent:
   # pattern: observer_peek|observer_config|from agent_team_v15\.observer
   # path: src/agent_team_v15/replay_harness.py
   # Expected: zero matches.
   ```
4. Plan-vs-source correction #1 is honoured — no stale line number:
   ```bash
   python -c "
   from pathlib import Path
   for p in (Path('docs/plans/phase-artifacts/phase-2-impl.md'), Path('src/agent_team_v15/replay_harness.py')):
       if p.exists() and '1747' in p.read_text(encoding='utf-8'):
           raise AssertionError(f'{p} references stale line 1747 (should be 2499)')
   print('correction #1 OK')
   "
   ```
5. Tests currently pass:
   ```bash
   python -m pytest tests/test_replay_harness.py -v
   ```
   Expected: `5 passed`. If any test fails, review stops.

## Code Review Checklist

### Correctness

- [ ] **`safe_to_promote` threshold is strict-less-than on FP rate, not `<=`.** Construct a `CalibrationReport` where `false_positive_rate = 0.10` exactly — it must be False. Read the source and confirm the comparison is `<`, not `<=`.
- [ ] **`safe_to_promote` requires both `build_count >= 3` AND `false_positive_rate < 0.10`.** Neither alone is sufficient. Reviewer must verify both conditions are `and`-combined, not `or`.
- [ ] **2-build cases are False even with 0% FP rate.** This is the exact assertion in `test_calibration_requires_3_builds`. The test must check `report.safe_to_promote is False` (identity, not truthy), and `report.build_count == 2`. A test that merely checks `not report.safe_to_promote` passes for any falsy value including None / 0 and is rejected.
- [ ] **`false_positive_rate` denominator is total peek count, not snapshot count.** Example: 2 snapshots each returning 10 peeks, 1 FP total → rate is `1/20 = 0.05`, not `1/2 = 0.5`. Read the source, confirm the formula is `total_fp / total_peek_count`.
- [ ] **`false_positive_rate` is 0.0 when no peeks happened** (not `ZeroDivisionError`, not NaN). Construct with empty snapshots list → `build_count=0`, `false_positive_rate=0.0`, `safe_to_promote=False`.
- [ ] **`generate_calibration_report` is `async def`** (the teammate mandate explicitly requires this). Verify via `import inspect; inspect.iscoroutinefunction(generate_calibration_report) is True`.
- [ ] **`generate_calibration_report` accepts `(runner, snapshots)`, not a cwd path.** The plan's original snippet used a cwd-based JSONL log pattern — the mandate overrides this. Confirm the signature matches the mandate, not the plan body.

### Architecture

- [ ] **`replay_harness.py` has zero imports of Phase 3/4/5 modules.** Specifically: no `observer_peek`, no `observer_config`, no `peek` symbol at module level. The only imports permitted are stdlib (`dataclasses`, `pathlib`, `typing`). This is enforced both by source grep and by runtime introspection.
- [ ] **`ReplayRunner.__init__` takes `peek_fn` as a constructor argument.** Not a module path string (option b), not a Protocol default (option c). Dependency injection only.
- [ ] **Module constants, not magic numbers.** Promotion thresholds live in named constants (`_MIN_BUILDS_FOR_PROMOTION`, `_MAX_FALSE_POSITIVE_RATE`). If the implementer inlined `3` and `0.10` literals inside `generate_calibration_report`, flag it — future tuning must touch one place.
- [ ] **No writes to the snapshot directory.** Search the module for any `write_text`, `mkdir`, `open(..., "w")`, or `unlink` call — there must be none. Replay is read-only by contract.
- [ ] **No calls to live wave code.** No imports from `wave_executor`, `codex_appserver`, `agent_teams_backend`, `codex_transport`. The harness is conceptually inspired by `_capture_file_fingerprints` (wave_executor.py:2499) but does not import it.

### Test Quality

- [ ] **`test_replay_runner_fail_open` actually catches exceptions.** The test must use a peek callable that raises (e.g., `raise RuntimeError("peek blew up")`), then wrap `asyncio.run(runner.run(snapshot))` outside any `try/except` and assert that no exception is raised. A test that wraps the call in `try/except Exception: pass` silently hides a regression where `ReplayRunner.run` stops catching — reject it.
- [ ] **`test_replay_runner_uses_injected_callable` uses `AsyncMock` or an async function and asserts `await_count == 1`.** A version that only asserts the return value has `isinstance(report, ReplayReport)` does not prove the injected callable was used (the implementation could still import a hardcoded peek).
- [ ] **No `or True` / `or False` bypasses in any assertion.** Grep the test file for `or True`, `or False`, `assert True`, `assert False is False`. This is correction #9 from the 10-corrections list — Phase 5 has a known gotcha, but reviewers must still check Phase 2 tests because the pattern tends to spread.
- [ ] **`test_calibration_rejects_high_fp_rate` uses a realistic scenario.** 20 snapshots returning 1 peek each with 3 steers → FP rate 0.15. The test must assert `report.false_positive_rate == pytest.approx(0.15)` (not just `> 0.10`). Exact-rate assertions catch off-by-one and wrong-denominator bugs.
- [ ] **`test_calibration_approves_low_fp_rate` asserts exact rate too.** Same reasoning — 20 snapshots, 1 steer, FP rate 0.05.
- [ ] **All tests use `tmp_path`, no real snapshot directories.** Phase 2 is a unit test; do not depend on `v18 test runs/` content. Grep for `v18 test runs` in the test file — there must be zero matches.
- [ ] **Tests call `asyncio.run(...)` directly, not `pytest.mark.asyncio`.** This keeps the suite free of the `pytest-asyncio` dependency unless it is already in `pyproject.toml`. If the implementer added `pytest-asyncio`, flag it — extra dependency for no gain.

### Integration Safety

- [ ] **No new entries in any `__init__.py`.** Phase 2 does not re-export replay-harness symbols from the package root. Phase 5 imports them directly from `agent_team_v15.replay_harness`.
- [ ] **No changes to `wave_executor.py`, `codex_appserver.py`, `agent_teams_backend.py`, `codex_transport.py`, or `config.py`.** Phase 2 is strictly additive. Run `git diff --stat` and confirm only `src/agent_team_v15/replay_harness.py` and `tests/test_replay_harness.py` appear.
- [ ] **No new runtime dependencies in `pyproject.toml` / `requirements*.txt`.** The module uses only stdlib.
- [ ] **No changes to smoke scripts, CI workflows, or `Makefile`.** Phase 2 is not wired into CI in this phase.
- [ ] **Existing test suite still passes.** Run `python -m pytest tests/ -x` and confirm no regressions. A new module importing a missing symbol can break unrelated collectors.

## Test Run Commands

Run each of these and record the full output. The review is not complete until every one matches its expected line.

```bash
cd C:/Projects/agent-team-v18-codex

# 1. New tests
python -m pytest tests/test_replay_harness.py -v
# Expected: 5 passed

# 2. Import smoke
python -c "from agent_team_v15.replay_harness import CalibrationReport, ReplayRunner, ReplaySnapshot, ReplayReport, generate_calibration_report; print('imports OK')"
# Expected: imports OK

# 3. Calibration gate smoke (verbatim from the handoff contract)
python -c "
import asyncio
from agent_team_v15.replay_harness import ReplayRunner, ReplaySnapshot, generate_calibration_report
from pathlib import Path
async def mock_peek(d, *a, **kw): return []
runner = ReplayRunner(mock_peek)
snapshots = [ReplaySnapshot(Path('.'), f'build-{i}', 'B') for i in range(2)]
report = asyncio.run(generate_calibration_report(runner, snapshots))
assert report.safe_to_promote == False, 'Must require 3+ builds'
print('calibration gate works')
"
# Expected: calibration gate works

# 4. Fail-open smoke
python -c "
import asyncio
from pathlib import Path
from agent_team_v15.replay_harness import ReplayRunner, ReplaySnapshot
async def boom(*a, **kw): raise RuntimeError('x')
r = ReplayRunner(boom)
s = ReplaySnapshot(Path('.'), 'b', 'B')
report = asyncio.run(r.run(s))
assert report.peek_results == [] and report.false_positives == 0
print('fail-open OK')
"
# Expected: fail-open OK

# 5. Source-grep isolation check
python -c "
from pathlib import Path
src = Path('src/agent_team_v15/replay_harness.py').read_text(encoding='utf-8')
for banned in ('observer_peek', 'from agent_team_v15.observer', 'import observer_peek'):
    assert banned not in src, f'BANNED token {banned!r} in replay_harness.py'
print('no-import invariant OK')
"
# Expected: no-import invariant OK

# 6. async signature introspection
python -c "
import inspect
from agent_team_v15.replay_harness import generate_calibration_report
assert inspect.iscoroutinefunction(generate_calibration_report), 'generate_calibration_report must be async'
print('async signature OK')
"
# Expected: async signature OK

# 7. Threshold boundary — build_count == 3 AND fp_rate == 0.10 exactly is NOT safe
python -c "
import asyncio
from pathlib import Path
from agent_team_v15.replay_harness import (
    ReplayRunner, ReplaySnapshot, generate_calibration_report,
)
# 3 snapshots, 10 peeks each, 1 FP per snapshot -> 3/30 = 0.10 exactly -> NOT safe
async def peek_tenth_steer(d, *a, **kw):
    return [{'verdict': 'steer'}] + [{'verdict': 'ok'}] * 9
runner = ReplayRunner(peek_tenth_steer)
snaps = [ReplaySnapshot(Path('.'), f'b{i}', 'B') for i in range(3)]
r = asyncio.run(generate_calibration_report(runner, snaps))
assert abs(r.false_positive_rate - 0.10) < 1e-9, f'rate was {r.false_positive_rate}'
assert r.safe_to_promote is False, 'fp_rate == 0.10 must NOT promote (strict less-than)'
print('boundary-strict-lt OK')
"
# Expected: boundary-strict-lt OK

# 8. Threshold boundary — build_count == 2 with 0% FP is still NOT safe
python -c "
import asyncio
from pathlib import Path
from agent_team_v15.replay_harness import (
    ReplayRunner, ReplaySnapshot, generate_calibration_report,
)
async def clean(d, *a, **kw): return [{'verdict': 'ok'}] * 100
runner = ReplayRunner(clean)
snaps = [ReplaySnapshot(Path('.'), f'b{i}', 'B') for i in range(2)]
r = asyncio.run(generate_calibration_report(runner, snaps))
assert r.build_count == 2
assert r.false_positive_rate == 0.0
assert r.safe_to_promote is False, '2 builds must NOT promote even at 0% FP'
print('boundary-two-builds OK')
"
# Expected: boundary-two-builds OK

# 9. Regression — existing tests still green
python -m pytest tests/ -x --ignore=tests/test_replay_harness.py -q 2>&1 | tail -5
# Expected: no failures introduced by Phase 2 changes
```

## Acceptance Criteria

Phase 2 is accepted when **all** of the following hold. Any single failure blocks acceptance.

1. `python -m pytest tests/test_replay_harness.py -v` reports exactly `5 passed, 0 failed`. No xfail, no skip, no warning about async-def-collected-as-test.
2. All eight smoke commands in "Test Run Commands" print their expected success line verbatim.
3. `git diff --stat` between the Phase 2 start and end commits shows only two files changed: `src/agent_team_v15/replay_harness.py` (new) and `tests/test_replay_harness.py` (new).
4. `replay_harness.py` has no `import` of any Phase 3/4/5 module. Source grep confirms zero matches for `observer_peek`, `observer_config`, and `from agent_team_v15.observer`.
5. `generate_calibration_report` is a coroutine function (`inspect.iscoroutinefunction` returns True), accepts `(runner, snapshots)`, and returns `CalibrationReport`.
6. `safe_to_promote` is False for every one of these cases: `build_count = 0`, `build_count = 1`, `build_count = 2`, `build_count = 3 with fp_rate = 0.10 exactly`, `build_count = 20 with fp_rate = 0.15`. It is True for `build_count = 20 with fp_rate = 0.05` and `build_count = 3 with fp_rate = 0.0`.
7. `ReplayRunner.run` does not propagate any `Exception` raised by the injected peek callable. It returns a `ReplayReport` with `peek_results == []` and `false_positives == 0`.
8. `ReplayRunner.__init__` takes `peek_fn` as a positional/keyword argument. There is no hardcoded fallback peek import anywhere in the module.
9. No test in `tests/test_replay_harness.py` contains `or True`, `or False`, `assert True`, `skip`, `xfail`, or any other always-pass pattern. Every assertion is a real assertion against a computed value.
10. The existing test suite (`python -m pytest tests/ -x --ignore=tests/test_replay_harness.py`) still passes. Phase 2 introduces zero regressions.

If any item 1–10 fails, the reviewer returns the implementation with a pointer to the specific failing command and expected output. Do not accept partial credit: `safe_to_promote` is a **gate**, and a gate that passes for 2 builds or for 10% FP rate is a gate that does not exist.
