"""Tests for peek-timeout skip-entry logging."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_team_v15.config import ObserverConfig
from agent_team_v15.wave_executor import (
    PeekSchedule,
    _capture_file_fingerprints,
    _run_wave_observer_peek,
    _WaveWatchdogState,
)


def _age_file(path: Path, seconds_in_past: float) -> None:
    target = time.time() - seconds_in_past
    os.utime(path, (target, target))


@pytest.mark.asyncio
async def test_peek_timeout_writes_skip_entry(tmp_path):
    (tmp_path / "src").mkdir()
    baseline = _capture_file_fingerprints(str(tmp_path))

    settled = tmp_path / "src" / "done.ts"
    settled.write_text("x", encoding="utf-8")
    _age_file(settled, 10.0)

    state = _WaveWatchdogState()
    state.peek_schedule = PeekSchedule(
        wave="A",
        trigger_files=["src/done.ts"],
        requirements_text="",
    )

    observer_config = ObserverConfig(
        enabled=True,
        peek_settle_seconds=5.0,
        peek_timeout_seconds=0.001,
        max_peeks_per_wave=5,
    )

    async def slow_peek(*_args, **_kwargs):
        await asyncio.sleep(1.0)
        raise AssertionError("should have been cancelled by wait_for")

    with patch("agent_team_v15.observer_peek.run_peek_call", new=slow_peek):
        await _run_wave_observer_peek(
            state=state,
            observer_config=observer_config,
            cwd=str(tmp_path),
            baseline_fingerprints=baseline,
            wave_letter="A",
        )

    # peek_count must NOT be incremented (timeout, not completed peek).
    assert state.peek_count == 0
    # File marked seen so it isn't retried immediately.
    assert "src/done.ts" in state.seen_files

    log_path = tmp_path / ".agent-team" / "observer_log.jsonl"
    assert log_path.exists(), "timeout should produce a skip entry"

    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["verdict"] == "skip"
    assert entry["wave"] == "A"
    assert entry["file"] == "src/done.ts"
    assert entry["message"] == "peek timeout after 0.001s"
    assert entry["source"] == "file_poll"
