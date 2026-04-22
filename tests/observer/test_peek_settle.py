"""Tests for the peek_settle_seconds mid-write gate."""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, patch

import pytest

from agent_team_v15.config import ObserverConfig
from agent_team_v15.wave_executor import (
    PeekResult,
    PeekSchedule,
    _capture_file_fingerprints,
    _detect_new_peek_triggers,
    _run_wave_observer_peek,
    _select_time_based_peek_file,
    _WaveWatchdogState,
)


def _age_file(path, seconds_in_past: float) -> None:
    target = time.time() - seconds_in_past
    os.utime(path, (target, target))


def test_detect_new_peek_triggers_excludes_fresh_files(tmp_path):
    (tmp_path / "src").mkdir()
    baseline = _capture_file_fingerprints(str(tmp_path))

    (tmp_path / "src" / "mid_write.ts").write_text("partial", encoding="utf-8")

    triggers = _detect_new_peek_triggers(
        str(tmp_path), baseline, set(), settle_seconds=5.0
    )

    assert triggers == []


def test_detect_new_peek_triggers_includes_settled_files(tmp_path):
    (tmp_path / "src").mkdir()
    baseline = _capture_file_fingerprints(str(tmp_path))

    settled = tmp_path / "src" / "done.ts"
    settled.write_text("x", encoding="utf-8")
    _age_file(settled, 10.0)

    triggers = _detect_new_peek_triggers(
        str(tmp_path), baseline, set(), settle_seconds=5.0
    )

    assert any(t.endswith("done.ts") for t in triggers)


def test_select_time_based_peek_file_excludes_fresh(tmp_path):
    (tmp_path / "src").mkdir()
    fresh = tmp_path / "src" / "mid_write.ts"
    fresh.write_text("partial", encoding="utf-8")

    schedule = PeekSchedule(
        wave="A",
        trigger_files=["src/mid_write.ts"],
        requirements_text="",
    )

    selected = _select_time_based_peek_file(
        str(tmp_path), schedule, [], settle_seconds=5.0
    )

    assert selected == ""


def test_select_time_based_peek_file_includes_settled(tmp_path):
    (tmp_path / "src").mkdir()
    settled = tmp_path / "src" / "done.ts"
    settled.write_text("x", encoding="utf-8")
    _age_file(settled, 10.0)

    schedule = PeekSchedule(
        wave="A",
        trigger_files=["src/done.ts"],
        requirements_text="",
    )

    selected = _select_time_based_peek_file(
        str(tmp_path), schedule, [], settle_seconds=5.0
    )

    assert selected == "src/done.ts"


@pytest.mark.asyncio
async def test_run_wave_observer_peek_does_not_burn_slot_when_all_fresh(tmp_path):
    (tmp_path / "src").mkdir()
    baseline = _capture_file_fingerprints(str(tmp_path))

    (tmp_path / "src" / "mid_write.ts").write_text("partial", encoding="utf-8")

    state = _WaveWatchdogState()
    state.peek_schedule = PeekSchedule(
        wave="A",
        trigger_files=["src/mid_write.ts"],
        requirements_text="",
    )

    observer_config = ObserverConfig(
        enabled=True,
        peek_settle_seconds=5.0,
        max_peeks_per_wave=5,
    )

    with patch(
        "agent_team_v15.observer_peek.run_peek_call",
        new=AsyncMock(return_value=PeekResult(
            file_path="src/mid_write.ts",
            wave="A",
            verdict="issue",
            message="should not be called",
        )),
    ) as mocked:
        await _run_wave_observer_peek(
            state=state,
            observer_config=observer_config,
            cwd=str(tmp_path),
            baseline_fingerprints=baseline,
            wave_letter="A",
        )

    assert state.peek_count == 0
    assert state.peek_log == []
    assert mocked.await_count == 0
