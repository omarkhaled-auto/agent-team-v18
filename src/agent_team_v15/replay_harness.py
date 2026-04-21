"""Offline replay harness for calibrating the orchestrator observer.

Phase 2 - Dynamic Orchestrator Observer.

This module feeds frozen ``cwd-snapshot-*`` directories from past smoke runs
into a caller-injected async peek callable and aggregates false-positive /
true-positive metrics across the replays. It never touches a live wave and
never imports from Phase 3/4/5 observer modules - the peek callable is
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
    returned by every snapshot - not per snapshot.
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
