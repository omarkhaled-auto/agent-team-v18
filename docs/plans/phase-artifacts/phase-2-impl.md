# Phase 2 — Replay Harness: Implementation Brief

## Phase Context

Phase 2 delivers an **offline calibration harness** for the Dynamic Orchestrator Observer. The harness feeds frozen `cwd-snapshot-*` directories from past smoke runs into a peek callable and aggregates false-positive / true-positive metrics across replays. It is the promotion gate for Phase 5's live observer: `CalibrationReport.safe_to_promote` must be True before the orchestrator may call `client.interrupt()` based on observer verdicts in a live wave.

Properties Phase 2 must honour:

- **Zero risk to live builds.** `replay_harness.py` never imports from wave-execution code paths and never writes to a live cwd. It only reads frozen snapshot directories and invokes a caller-injected async peek callable.
- **Phase independence.** Phase 2 ships and tests without Phase 3 / 4 / 5 existing. The real `observer_peek.run_peek_call` is not referenced by module-level imports. Tests use async mocks.
- **Fail-open.** Any exception from the peek callable or snapshot I/O yields an empty `ReplayReport`; the exception does not propagate.
- **Strict promotion gate.** `safe_to_promote` is True if and only if `build_count >= 3 AND false_positive_rate < 0.10`. Both conditions must hold. Boundary cases (`==`) behave as documented: 3 builds passes the count test; exactly `0.10` fails the rate test.

Handoff to Phase 5: Phase 5 imports `generate_calibration_report`, `ReplayRunner`, `ReplaySnapshot`, and `CalibrationReport` from `agent_team_v15.replay_harness` and uses `safe_to_promote` as the single gate before enabling live-mode `interrupt()` calls.

## Pre-Flight: Files to Read

Read every file below before writing any code. Record the facts in the "What to extract" column — they are load-bearing.

| # | Path | Lines | What to extract |
|---|------|-------|-----------------|
| 1 | `src/agent_team_v15/wave_executor.py` | 2499–2511 | `_capture_file_fingerprints(cwd: str) -> dict[str, tuple[int, int]]`. Returns dict keyed by POSIX-relative path, values are `(st_mtime_ns, st_size)` tuples. This is the existing on-disk-state snapshot mechanism — understand it conceptually so `ReplaySnapshot` does not reinvent it. Phase 2 does not call this function; it mirrors the concept (frozen state on disk + identifier tuple). |
| 2 | `src/agent_team_v15/codex_transport.py` | 65–85 | `CodexResult` dataclass. Fields: `success`, `exit_code`, `duration_seconds`, token counters, `files_created`, `files_modified`, `final_message`, `error`, `retry_count`. Phase 2 does **not** instantiate `CodexResult`, but Phase 5's `peek_summary` will reference it — keep field names accurate if you surface them in `ReplayReport.peek_results`. |
| 3 | `docs/plans/2026-04-20-dynamic-orchestrator-observer.md` | 787–1005 | Phase 2 section. Source of `ReplaySnapshot` / `ReplayRunner` / `CalibrationReport` specs. **Override from teammate mandate (takes precedence where they diverge):** `generate_calibration_report` is `async` and accepts `(runner, snapshots)`, not a cwd path. FP rate is `false_positives / total_peeks`, aggregated by calling `runner.run(...)` on each snapshot. |
| 4 | `tests/test_state.py` | 1–60 | Test style: `from __future__ import annotations`, `import pytest`, plain `class Test…:` or module-level `def test_…` functions, `tmp_path` fixture for filesystem tests. Mirror this style in `tests/test_replay_harness.py`. |
| 5 | Repo root listing | — | Snapshot directories live under `v18 test runs/` and `runs/`. These are inputs for real calibration runs — Phase 2 tests do **not** read them; tests use `tmp_path` only. |

### Correction-critical fact to confirm

- `_capture_file_fingerprints` is at `wave_executor.py:2499` (not 1747 as the plan header says). This is correction #1 from the 10-corrections list. Do not cite line 1747 anywhere in the artifact.

## Pre-Flight: Context7 Research

Before writing the module, the implementer must have these three answers from context7:

1. **`pathlib.Path.iterdir()`** — yields `Path` objects for every entry; does not include `.` / `..`; order is arbitrary. For deterministic test assertions, sort the result (e.g., `sorted(...)` on paths or names). Raises `OSError` on non-directory / inaccessible paths — this must be caught in the `list_snapshots`-style helper if one is exposed.
2. **`asyncio.run(coro)`** — the supported entry point for invoking a coroutine from synchronous test code. Use `asyncio.run(generate_calibration_report(runner, snapshots))` inside `def test_…` functions. Do **not** require `pytest-asyncio`; using `asyncio.run` keeps the test file free of marker dependencies.
3. **`dataclasses.field(default_factory=list)`** — mandatory for any mutable default. Every list-typed field on `ReplaySnapshot`, `ReplayReport`, and `CalibrationReport` uses `field(default_factory=list)`.

If `pytest-asyncio` markers are desired later, that is an enhancement; this phase ships with `asyncio.run` and zero new test dependencies.

## Pre-Flight: Sequential Thinking

Decision required: how does `ReplayRunner` obtain the peek callable without a module-level `from agent_team_v15.observer_peek import ...`?

Three options were evaluated:

- **(a) Constructor dependency injection** — `__init__(self, peek_fn: Callable[..., Awaitable[...]])`. Caller supplies the callable at construction time.
- **(b) Module path + `importlib.import_module`** — pass a dotted-path string; resolve at runtime.
- **(c) `Protocol` class** — declare a `PeekCallable` protocol; still requires DI at construction.

**Decision: (a) constructor injection.** Reasons:

- Phase 2 ships before Phase 3 exists. Tests construct `ReplayRunner(mock_peek)` where `mock_peek` is an `async def` or `unittest.mock.AsyncMock`. No import of a not-yet-existing module.
- Phase 5 / integration code constructs `ReplayRunner(observer_peek.run_peek_call)` at call time, keeping `replay_harness.py` free of `observer_peek` references.
- Option (b) introduces fragile module-path strings and hidden side effects.
- Option (c) adds typing ceremony but still needs DI — strictly more code for the same behaviour.

Bind this decision: `replay_harness.py` **must not** contain a top-level `import` or `from ... import ...` of `observer_peek`, `peek`, or any Phase-3/4/5 module. The review artifact greps for this.

## Corrections Applied (Phase 2)

| # | Correction | How it is applied in this artifact |
|---|------------|------------------------------------|
| 1 | `_capture_file_fingerprints` is at `wave_executor.py:2499` (not 1747) | Pre-flight table cites line 2499. No snippet in this brief references 1747. Phase 2 does not call `_capture_file_fingerprints` itself, but the corrected line is cited when describing the "existing file-fingerprint mechanism" that `ReplaySnapshot` mirrors conceptually. |

Corrections #2–#10 are not Phase-2-relevant and are handled in other phases.

## Task 2.1: Create `replay_harness.py`

Files:

- Create: `src/agent_team_v15/replay_harness.py`
- Create: `tests/test_replay_harness.py`

### Step 1 — Write the failing tests first

Write `tests/test_replay_harness.py` exactly as specified below. Run the test suite before writing the module so all five tests fail with `ModuleNotFoundError` / `ImportError`. That is the required red state.

```python
"""Tests for agent_team_v15.replay_harness."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_team_v15.replay_harness import (
    CalibrationReport,
    ReplayReport,
    ReplayRunner,
    ReplaySnapshot,
    generate_calibration_report,
)


def _make_snapshots(tmp_path: Path, count: int, wave: str = "B") -> list[ReplaySnapshot]:
    snaps: list[ReplaySnapshot] = []
    for i in range(count):
        d = tmp_path / f"cwd-snapshot-build-{i}"
        d.mkdir()
        snaps.append(ReplaySnapshot(snapshot_dir=d, build_id=f"build-{i}", wave_letter=wave))
    return snaps


def _peek_with_verdicts(verdicts: list[str]):
    """Return an async peek callable that yields one peek result per snapshot.

    Each peek result is a list of dicts with a ``verdict`` key. ``"steer"`` marks
    a suggestion that would have fired an interrupt; ``"ok"`` is a no-op peek.
    """

    iterator = iter(verdicts)

    async def _peek(snapshot_dir: Path, *args, **kwargs) -> list[dict]:
        try:
            verdict = next(iterator)
        except StopIteration:
            verdict = "ok"
        return [{"verdict": verdict, "snapshot_dir": str(snapshot_dir)}]

    return _peek


def test_calibration_requires_3_builds(tmp_path):
    peek = _peek_with_verdicts(["ok", "ok"])
    runner = ReplayRunner(peek_fn=peek)
    snapshots = _make_snapshots(tmp_path, count=2)

    report = asyncio.run(generate_calibration_report(runner, snapshots))

    assert report.build_count == 2
    assert report.safe_to_promote is False, (
        "safe_to_promote must be False when build_count < 3, "
        f"got build_count={report.build_count}, fp_rate={report.false_positive_rate}"
    )


def test_calibration_rejects_high_fp_rate(tmp_path):
    # 20 builds, 3 steers -> fp_rate = 0.15 (> 0.10 threshold)
    verdicts = ["steer", "steer", "steer"] + ["ok"] * 17
    peek = _peek_with_verdicts(verdicts)
    runner = ReplayRunner(peek_fn=peek)
    snapshots = _make_snapshots(tmp_path, count=20)

    report = asyncio.run(generate_calibration_report(runner, snapshots))

    assert report.build_count == 20
    assert report.false_positive_rate == pytest.approx(0.15)
    assert report.safe_to_promote is False


def test_calibration_approves_low_fp_rate(tmp_path):
    # 20 builds, 1 steer -> fp_rate = 0.05 (< 0.10 threshold)
    verdicts = ["steer"] + ["ok"] * 19
    peek = _peek_with_verdicts(verdicts)
    runner = ReplayRunner(peek_fn=peek)
    snapshots = _make_snapshots(tmp_path, count=20)

    report = asyncio.run(generate_calibration_report(runner, snapshots))

    assert report.build_count == 20
    assert report.false_positive_rate == pytest.approx(0.05)
    assert report.safe_to_promote is True


def test_replay_runner_uses_injected_callable(tmp_path):
    mock_peek = AsyncMock(return_value=[{"verdict": "ok"}])
    runner = ReplayRunner(peek_fn=mock_peek)
    snapshot = _make_snapshots(tmp_path, count=1)[0]

    report = asyncio.run(runner.run(snapshot))

    assert isinstance(report, ReplayReport)
    assert mock_peek.await_count == 1
    # Confirm the runner did not reach into observer_peek or any other module.
    called_args, called_kwargs = mock_peek.call_args
    # First positional arg is the snapshot_dir
    assert called_args[0] == snapshot.snapshot_dir


def test_replay_runner_fail_open(tmp_path):
    async def exploding_peek(*args, **kwargs):
        raise RuntimeError("peek blew up")

    runner = ReplayRunner(peek_fn=exploding_peek)
    snapshot = _make_snapshots(tmp_path, count=1)[0]

    # Must not raise.
    report = asyncio.run(runner.run(snapshot))

    assert isinstance(report, ReplayReport)
    assert report.peek_results == []
    assert report.false_positives == 0
    assert report.true_positives == 0
    assert report.snapshot is snapshot
```

Run:

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_replay_harness.py -v
```

Expected (red): five collection / import failures because `replay_harness.py` does not yet exist. Proceed only after confirming red.

### Step 2 — Implement `replay_harness.py`

Write `src/agent_team_v15/replay_harness.py` with the content below. No other files change in Phase 2.

```python
"""Offline replay harness for calibrating the orchestrator observer.

Phase 2 — Dynamic Orchestrator Observer.

This module feeds frozen ``cwd-snapshot-*`` directories from past smoke runs
into a caller-injected async peek callable and aggregates false-positive /
true-positive metrics across the replays. It never touches a live wave and
never imports from Phase 3/4/5 observer modules — the peek callable is
supplied by the caller (dependency injection).

Promotion gate: :func:`generate_calibration_report` returns a
:class:`CalibrationReport` whose ``safe_to_promote`` attribute is True if
and only if ``build_count >= 3`` and ``false_positive_rate < 0.10``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

PeekCallable = Callable[..., Awaitable[list[dict[str, Any]]]]

_MIN_BUILDS_FOR_PROMOTION = 3
_MAX_FALSE_POSITIVE_RATE = 0.10


@dataclass
class ReplaySnapshot:
    """Pointer to a frozen cwd snapshot directory from a past smoke run."""

    snapshot_dir: Path
    build_id: str
    wave_letter: str


@dataclass
class ReplayReport:
    """Aggregated peek results for a single snapshot replay."""

    snapshot: ReplaySnapshot
    peek_results: list[dict[str, Any]] = field(default_factory=list)
    false_positives: int = 0
    true_positives: int = 0


@dataclass
class CalibrationReport:
    """Cross-snapshot aggregation used as the live-mode promotion gate."""

    build_count: int = 0
    false_positive_rate: float = 0.0
    safe_to_promote: bool = False
    reports: list[ReplayReport] = field(default_factory=list)


def _classify(peek_result: dict[str, Any]) -> str:
    """Return ``"fp"`` / ``"tp"`` / ``"ok"`` for one peek result entry.

    A peek result with ``verdict == "steer"`` or ``verdict == "interrupt"`` is a
    positive suggestion. Absent ground-truth labelling, Phase 2 treats every
    positive against a frozen snapshot as a false positive (the build already
    completed without that interrupt). Phase 5 may override by populating
    ``peek_result["ground_truth"] = "tp"``.
    """

    verdict = peek_result.get("verdict")
    if verdict not in ("steer", "interrupt"):
        return "ok"
    if peek_result.get("ground_truth") == "tp":
        return "tp"
    return "fp"


class ReplayRunner:
    """Runs a caller-injected async peek callable against a snapshot."""

    def __init__(self, peek_fn: PeekCallable) -> None:
        self._peek_fn = peek_fn

    async def run(self, snapshot: ReplaySnapshot) -> ReplayReport:
        try:
            results = await self._peek_fn(
                snapshot.snapshot_dir,
                build_id=snapshot.build_id,
                wave_letter=snapshot.wave_letter,
            )
        except Exception:
            return ReplayReport(snapshot=snapshot)

        if not isinstance(results, list):
            return ReplayReport(snapshot=snapshot)

        fp = 0
        tp = 0
        for entry in results:
            if not isinstance(entry, dict):
                continue
            kind = _classify(entry)
            if kind == "fp":
                fp += 1
            elif kind == "tp":
                tp += 1

        return ReplayReport(
            snapshot=snapshot,
            peek_results=list(results),
            false_positives=fp,
            true_positives=tp,
        )


async def generate_calibration_report(
    runner: ReplayRunner,
    snapshots: Sequence[ReplaySnapshot],
) -> CalibrationReport:
    """Aggregate :class:`ReplayReport` objects into a :class:`CalibrationReport`.

    ``safe_to_promote`` is True only when ``build_count >= 3`` and
    ``false_positive_rate < 0.10``. ``false_positive_rate`` is computed as
    ``total_false_positives / total_peek_count`` across every peek result
    returned by every snapshot — not per snapshot.
    """

    reports: list[ReplayReport] = []
    for snapshot in snapshots:
        report = await runner.run(snapshot)
        reports.append(report)

    total_peeks = sum(len(r.peek_results) for r in reports)
    total_fp = sum(r.false_positives for r in reports)
    fp_rate = (total_fp / total_peeks) if total_peeks > 0 else 0.0
    build_count = len(reports)
    safe = (
        build_count >= _MIN_BUILDS_FOR_PROMOTION
        and fp_rate < _MAX_FALSE_POSITIVE_RATE
    )

    return CalibrationReport(
        build_count=build_count,
        false_positive_rate=fp_rate,
        safe_to_promote=safe,
        reports=reports,
    )
```

Key invariants in the implementation:

- `_peek_fn` is stored as an instance attribute at construction; there is no fallback to any imported symbol.
- `ReplayRunner.run` wraps the peek call in `try / except Exception` and returns an empty `ReplayReport` on failure. `BaseException` (`KeyboardInterrupt`, `SystemExit`) is intentionally not caught.
- `false_positive_rate` denominator is **total peek-result count**, not snapshot count — ensures multiple peeks per snapshot are weighted correctly.
- Promotion thresholds are module constants (`_MIN_BUILDS_FOR_PROMOTION`, `_MAX_FALSE_POSITIVE_RATE`) — future tuning touches one place.
- There is no module-level import of any Phase 3/4/5 code. The only stdlib dependency is `dataclasses`, `pathlib`, and `typing`.

### Step 3 — Quick verification

Run tests:

```bash
cd C:/Projects/agent-team-v18-codex
python -m pytest tests/test_replay_harness.py -v
```

Expected: `5 passed`.

Run import smoke:

```bash
python -c "from agent_team_v15.replay_harness import CalibrationReport, ReplayRunner, ReplaySnapshot, ReplayReport, generate_calibration_report; print('imports OK')"
```

Run promotion-gate smoke (exactly the command specified in the handoff contract):

```bash
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
```

Expected: prints `calibration gate works`.

Confirm the no-import invariant:

```bash
python -c "import agent_team_v15.replay_harness as m; import sys; assert not any('observer_peek' in name for name in sys.modules), 'replay_harness must not import observer_peek transitively'; print('no-import invariant OK')"
```

Expected: prints `no-import invariant OK`.

## Phase Gate: Verification Checklist

All of the following must succeed, in order, before declaring Phase 2 done:

1. Pytest — from `C:/Projects/agent-team-v18-codex`:
   ```bash
   python -m pytest tests/test_replay_harness.py -v
   ```
   Expected: `5 passed`. Any failure blocks the gate; the cause is fixed in `replay_harness.py` or the test, never by loosening the assertion.

2. Import smoke:
   ```bash
   python -c "from agent_team_v15.replay_harness import CalibrationReport, ReplayRunner, generate_calibration_report; print('imports OK')"
   ```
   Expected: `imports OK`.

3. Gate-behaviour smoke (verbatim from teammate mandate):
   ```bash
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
   ```
   Expected: `calibration gate works`.

4. No-import invariant (adversarial check for Phase 3 isolation):
   ```bash
   python -c "import agent_team_v15.replay_harness as m; assert 'observer_peek' not in (getattr(m, '__dict__', {}) or {}); print('no-import invariant OK')"
   ```
   Plus a source-level grep check:
   ```bash
   python -c "
   from pathlib import Path
   src = Path('src/agent_team_v15/replay_harness.py').read_text(encoding='utf-8')
   for banned in ('observer_peek', 'from agent_team_v15.observer'):
       assert banned not in src, f'replay_harness must not reference {banned!r}'
   print('source-grep OK')
   "
   ```
   Expected: both print `OK` lines.

5. Fail-open contract — exercised by `test_replay_runner_fail_open`, but re-run as a manual smoke to confirm no exception escapes:
   ```bash
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
   ```
   Expected: `fail-open OK`.

Only when items 1–5 each print their expected success line may Phase 2 be marked complete.

## Handoff State

Phase 5 (semantic observer / calibration gate) depends on the following public contract from Phase 2. These are the only symbols Phase 5 may import from `agent_team_v15.replay_harness`:

| Symbol | Signature | Phase 5 usage |
|--------|-----------|---------------|
| `ReplaySnapshot` | `@dataclass(snapshot_dir: Path, build_id: str, wave_letter: str)` | Constructed by Phase 5 from snapshots discovered under `v18 test runs/` and `runs/`. |
| `ReplayRunner` | `__init__(peek_fn: PeekCallable)` + `async run(snapshot) -> ReplayReport` | Phase 5 constructs `ReplayRunner(observer_peek.run_peek_call)` — no other wiring. |
| `generate_calibration_report` | `async (runner, snapshots) -> CalibrationReport` | Phase 5 awaits it and reads `.safe_to_promote`. No other field is part of the gate contract. |
| `CalibrationReport.safe_to_promote` | `bool` | **The single promotion gate.** True iff `build_count >= 3 and false_positive_rate < 0.10`. |

Guarantees Phase 5 can rely on:

- `generate_calibration_report` never raises from peek-side failures — individual snapshot failures become empty `ReplayReport`s and are still counted toward `build_count`.
- The peek callable is called with `snapshot_dir` as the first positional argument, plus `build_id=` and `wave_letter=` keyword arguments. Phase 3's `observer_peek.run_peek_call` must accept this signature (verify in Phase 3 review).
- `false_positive_rate` is `total_false_positives / total_peek_count`. If Phase 5 wants per-snapshot rates, it must aggregate from `CalibrationReport.reports` itself.

Non-contracts (do not depend on these in Phase 5):

- Internal promotion thresholds are `_MIN_BUILDS_FOR_PROMOTION` / `_MAX_FALSE_POSITIVE_RATE` — these are `_`-prefixed and may be tuned in-place without breaking callers.
- `ReplayReport.peek_results` is whatever the peek callable returned (a `list[dict]`); schema of individual entries is owned by Phase 3.
