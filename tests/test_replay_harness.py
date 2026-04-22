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


def test_generate_calibration_report_raises_on_missing_log(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_calibration_report(tmp_path)
