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

import json
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
    recommendation: str = ""

    @property
    def builds_analyzed(self) -> int:
        """Compatibility alias used by activation docs and smoke reports."""
        return self.build_count


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


def _recommendation(build_count: int, false_positive_rate: float, safe: bool) -> str:
    if build_count < _MIN_BUILDS_FOR_PROMOTION:
        remaining = _MIN_BUILDS_FOR_PROMOTION - build_count
        noun = "build" if remaining == 1 else "builds"
        return (
            f"Need {remaining} more calibration {noun} before promotion; "
            "safe_to_promote: False"
        )
    if not safe:
        return (
            "False-positive rate is too high "
            f"({false_positive_rate:.1%}); safe_to_promote: False"
        )
    return (
        "Calibration gate passed "
        f"({false_positive_rate:.1%} false-positive rate); safe_to_promote: True"
    )


def _log_build_key(entry: dict[str, Any], line_number: int) -> str:
    for key in ("build_id", "run_id", "milestone_id", "snapshot_id"):
        value = entry.get(key)
        if value:
            return f"{key}:{value}"
    timestamp = str(entry.get("timestamp", "")).strip()
    if len(timestamp) >= 10:
        return f"date:{timestamp[:10]}"
    return f"line:{line_number}"


def _generate_log_calibration_report(cwd: str | Path) -> CalibrationReport:
    """Aggregate ``cwd/.agent-team/observer_log.jsonl`` for activation gating."""
    log_path = Path(cwd) / ".agent-team" / "observer_log.jsonl"
    if not log_path.is_file():
        raise FileNotFoundError(
            f"observer_log.jsonl not found at {log_path}"
        )

    decisions: list[dict[str, Any]] = []
    build_keys: set[str] = set()
    with log_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            decisions.append(entry)
            build_keys.add(_log_build_key(entry, line_number))

    total = len(decisions)
    false_positives = 0
    for entry in decisions:
        would_interrupt = bool(entry.get("would_interrupt"))
        positive_verdict = str(entry.get("verdict", "")).lower() in {
            "issue",
            "steer",
            "interrupt",
        }
        if (would_interrupt or positive_verdict) and entry.get("ground_truth") != "tp":
            false_positives += 1

    fp_rate = (false_positives / total) if total else 0.0
    build_count = len(build_keys)
    safe = (
        build_count >= _MIN_BUILDS_FOR_PROMOTION
        and fp_rate < _MAX_FALSE_POSITIVE_RATE
    )
    return CalibrationReport(
        build_count=build_count,
        false_positive_rate=fp_rate,
        safe_to_promote=safe,
        recommendation=_recommendation(build_count, fp_rate, safe),
    )


async def _generate_replay_calibration_report(
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
        recommendation=_recommendation(build_count, fp_rate, safe),
    )


def generate_calibration_report(
    runner_or_cwd: ReplayRunner | str | Path,
    snapshots: Sequence[ReplaySnapshot] | None = None,
) -> CalibrationReport | Awaitable[CalibrationReport]:
    """Generate a calibration report from replay snapshots or observer JSONL.

    ``generate_calibration_report(runner, snapshots)`` preserves the Phase 2
    async replay API and returns an awaitable. ``generate_calibration_report(cwd)``
    synchronously reads ``cwd/.agent-team/observer_log.jsonl`` for the activation
    checklist gate.
    """

    if isinstance(runner_or_cwd, ReplayRunner):
        if snapshots is None:
            raise TypeError("snapshots are required when using ReplayRunner")
        return _generate_replay_calibration_report(runner_or_cwd, snapshots)
    if snapshots is not None:
        raise TypeError("snapshots are only valid with ReplayRunner")
    return _generate_log_calibration_report(runner_or_cwd)
