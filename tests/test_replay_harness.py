"""Tests for agent_team_v15.replay_harness."""

from __future__ import annotations

import asyncio
import json
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


def _write_log(cwd: Path, entries: list[dict]) -> Path:
    log_dir = cwd / ".agent-team"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "observer_log.jsonl"
    log_file.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    return log_file


def test_calibration_rejects_narrow_wave_coverage(tmp_path):
    entries = [
        {
            "timestamp": "2026-04-18T09:00:00",
            "build_id": f"build-{i}",
            "wave": "B",
            "would_interrupt": False,
        }
        for i in range(3)
    ]
    _write_log(tmp_path, entries)

    # Explicit override preserves the original Round-2 semantics of this test:
    # a 1-wave log must fail a 4-wave floor.
    report = generate_calibration_report(tmp_path, min_waves_covered=4)

    assert report.build_count == 3
    assert report.safe_to_promote is False
    assert "wave coverage" in report.recommendation.lower()


def test_calibration_accepts_broad_wave_coverage(tmp_path):
    entries = [
        {
            "timestamp": "2026-04-18T09:00:00",
            "build_id": "build-0",
            "wave": "A",
            "would_interrupt": False,
        },
        {
            "timestamp": "2026-04-18T10:00:00",
            "build_id": "build-1",
            "wave": "B",
            "would_interrupt": False,
        },
        {
            "timestamp": "2026-04-18T11:00:00",
            "build_id": "build-2",
            "wave": "D",
            "would_interrupt": False,
        },
        {
            "timestamp": "2026-04-18T12:00:00",
            "build_id": "build-2",
            "wave": "T",
            "would_interrupt": False,
        },
    ]
    _write_log(tmp_path, entries)

    report = generate_calibration_report(tmp_path, min_waves_covered=4)

    assert report.build_count == 3
    assert report.safe_to_promote is True


def test_calibration_accepts_two_waves_under_default_floor(tmp_path):
    """Default floor (2) promotes logs with at least two distinct waves.

    Corpus-grounded: CLIBackend Round 1 has {A, B, D} as its realistic
    observable surface; two-wave coverage is a legitimate pass condition.
    """
    entries = [
        {
            "timestamp": "2026-04-18T09:00:00",
            "build_id": "build-0",
            "wave": "A",
            "would_interrupt": False,
        },
        {
            "timestamp": "2026-04-18T10:00:00",
            "build_id": "build-1",
            "wave": "B",
            "would_interrupt": False,
        },
        {
            "timestamp": "2026-04-18T11:00:00",
            "build_id": "build-2",
            "wave": "B",
            "would_interrupt": False,
        },
    ]
    _write_log(tmp_path, entries)

    report = generate_calibration_report(tmp_path)

    assert report.build_count == 3
    assert report.waves_covered == ["A", "B"]
    assert report.safe_to_promote is True


def test_calibration_rejects_single_wave_under_default_floor(tmp_path):
    """Default floor (2) still rejects single-wave logs as too narrow."""
    entries = [
        {
            "timestamp": "2026-04-18T09:00:00",
            "build_id": f"build-{i}",
            "wave": "B",
            "would_interrupt": False,
        }
        for i in range(3)
    ]
    _write_log(tmp_path, entries)

    report = generate_calibration_report(tmp_path)

    assert report.build_count == 3
    assert report.waves_covered == ["B"]
    assert report.safe_to_promote is False
    assert "wave coverage" in report.recommendation.lower()


def test_calibration_min_waves_override_read_from_kwarg(tmp_path):
    """Explicit kwarg overrides whatever ObserverConfig default provides."""
    entries = [
        {
            "timestamp": "2026-04-18T09:00:00",
            "build_id": "build-0",
            "wave": "A",
            "would_interrupt": False,
        },
        {
            "timestamp": "2026-04-18T10:00:00",
            "build_id": "build-1",
            "wave": "B",
            "would_interrupt": False,
        },
        {
            "timestamp": "2026-04-18T11:00:00",
            "build_id": "build-2",
            "wave": "D",
            "would_interrupt": False,
        },
    ]
    _write_log(tmp_path, entries)

    # With the default floor (2), 3 waves passes.
    assert generate_calibration_report(tmp_path).safe_to_promote is True
    # With an override of 5, 3 waves fails.
    strict = generate_calibration_report(tmp_path, min_waves_covered=5)
    assert strict.safe_to_promote is False
    assert "wave coverage" in strict.recommendation.lower()


def test_calibration_report_exposes_waves_covered(tmp_path):
    entries = [
        {
            "timestamp": "2026-04-18T09:00:00",
            "build_id": "build-0",
            "wave": "t",
            "would_interrupt": False,
        },
        {
            "timestamp": "2026-04-18T10:00:00",
            "build_id": "build-1",
            "wave": "a",
            "would_interrupt": False,
        },
        {
            "timestamp": "2026-04-18T11:00:00",
            "build_id": "build-2",
            "wave": "B",
            "would_interrupt": False,
        },
    ]
    _write_log(tmp_path, entries)

    report = generate_calibration_report(tmp_path)

    assert report.waves_covered == ["A", "B", "T"]


def test_generate_calibration_report_raises_on_missing_log(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_calibration_report(tmp_path)
