"""Tests for D-11 — unconditional WAVE_FINDINGS.json with skip marker.

The pipeline always writes ``.agent-team/milestones/<id>/WAVE_FINDINGS.json``
at end of milestone wave execution. Before D-11 the file for a build
where Wave T never ran looked identical to a Wave-T-completed-empty
build — ``{"findings": []}`` with no status indicator. This test module
covers the four scenarios laid out in the per-item plan.

No SDK, subprocess, or network calls. Pure ``WaveResult`` → JSON
exercise of ``persist_wave_findings_for_audit``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_team_v15.wave_executor import (
    WaveFinding,
    WaveResult,
    _derive_wave_t_status,
    persist_wave_findings_for_audit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wave(
    letter: str,
    *,
    success: bool = True,
    findings: list[WaveFinding] | None = None,
    error: str = "",
) -> WaveResult:
    return WaveResult(
        wave=letter,
        success=success,
        findings=findings or [],
        error_message=error,
    )


def _finding(code: str = "TEST-FAIL-UNIT", severity: str = "HIGH") -> WaveFinding:
    return WaveFinding(
        code=code,
        severity=severity,
        file="apps/api",
        line=0,
        message="unit test failure",
    )


# ---------------------------------------------------------------------------
# 1. Wave D failure writes skip marker
# ---------------------------------------------------------------------------


def test_wave_d_failure_writes_skip_marker(tmp_path: Path) -> None:
    waves = [
        _wave("A", success=True),
        _wave("B", success=True),
        _wave("C", success=True),
        _wave("D", success=False, error="compile fail"),
    ]
    path = persist_wave_findings_for_audit(
        str(tmp_path),
        "milestone-1",
        waves,
        wave_t_expected=True,
        failing_wave="D",
    )
    assert path is not None and path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["milestone_id"] == "milestone-1"
    assert payload["wave_t_status"] == "skipped"
    # Skip reason must name the failing upstream wave so observers can
    # pinpoint where the chain broke without reading telemetry.
    assert "Wave D" in payload["skip_reason"]
    assert payload["findings"] == []
    # generated_at is present and string-shaped.
    assert isinstance(payload["generated_at"], str)


def test_skip_marker_is_valid_json(tmp_path: Path) -> None:
    waves = [_wave("A", success=False, error="wedged")]
    path = persist_wave_findings_for_audit(
        str(tmp_path),
        "milestone-1",
        waves,
        wave_t_expected=True,
        failing_wave="A",
    )
    assert path is not None
    # Round-trip — no trailing bytes, no corruption.
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("milestone_id", "generated_at", "wave_t_status", "findings"):
        assert key in data, f"missing required key {key}"
    assert isinstance(data["findings"], list)


def test_skip_marker_reason_names_upstream_wave(tmp_path: Path) -> None:
    """The reason string must mention the actual failing wave letter so
    operators can triage without reading per-wave telemetry."""
    waves = [
        _wave("A", success=True),
        _wave("B", success=False, error="Wave B wedged"),
    ]
    path = persist_wave_findings_for_audit(
        str(tmp_path),
        "milestone-1",
        waves,
        wave_t_expected=True,
        failing_wave="B",
    )
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["wave_t_status"] == "skipped"
    assert "Wave B" in payload["skip_reason"]
    assert "Wave T" in payload["skip_reason"]


# ---------------------------------------------------------------------------
# 2. Wave D success + Wave T runs: existing behaviour preserved
# ---------------------------------------------------------------------------


def test_wave_t_completed_preserves_findings(tmp_path: Path) -> None:
    """The real-findings path is unchanged when Wave T runs successfully."""
    t_findings = [_finding("TEST-FAIL-E2E", "HIGH")]
    waves = [
        _wave("A"),
        _wave("B"),
        _wave("C"),
        _wave("D"),
        _wave("D5"),
        _wave("T", success=True, findings=t_findings),
        _wave("E"),
    ]
    path = persist_wave_findings_for_audit(
        str(tmp_path),
        "milestone-1",
        waves,
        wave_t_expected=True,
        failing_wave=None,
    )
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["wave_t_status"] == "completed"
    # Completed-clean runs do not emit a skip_reason.
    assert "skip_reason" not in payload
    # Findings list carries Wave T output.
    assert any(
        entry["wave"] == "T" and entry["code"] == "TEST-FAIL-E2E"
        for entry in payload["findings"]
    )


def test_wave_t_ran_but_failed_marked_completed_with_failure(tmp_path: Path) -> None:
    """When Wave T executed but returned ``success=false`` (e.g. fix loop
    exhausted), the marker distinguishes that from a true skip — the
    auditor sees "completed_with_failure" with the error surfaced."""
    waves = [
        _wave("A"),
        _wave("B"),
        _wave("C"),
        _wave("D"),
        _wave("D5"),
        _wave("T", success=False, error="fix loop exhausted"),
    ]
    path = persist_wave_findings_for_audit(
        str(tmp_path),
        "milestone-1",
        waves,
        wave_t_expected=True,
        failing_wave="T",
    )
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["wave_t_status"] == "completed_with_failure"
    assert "fix loop exhausted" in payload["skip_reason"]


def test_wave_t_disabled_records_disabled_status(tmp_path: Path) -> None:
    waves = [_wave("A"), _wave("B"), _wave("C"), _wave("D"), _wave("E")]
    path = persist_wave_findings_for_audit(
        str(tmp_path),
        "milestone-2",
        waves,
        wave_t_expected=False,
        failing_wave=None,
    )
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["wave_t_status"] == "disabled"
    assert "disabled" in payload["skip_reason"].lower()


# ---------------------------------------------------------------------------
# 3. Missing milestone id → no-op (pre-existing contract preserved)
# ---------------------------------------------------------------------------


def test_missing_milestone_id_returns_none(tmp_path: Path) -> None:
    result = persist_wave_findings_for_audit(
        str(tmp_path), "", [], wave_t_expected=True, failing_wave="D"
    )
    assert result is None
    # And no file is written.
    assert not any(tmp_path.rglob("WAVE_FINDINGS.json"))


# ---------------------------------------------------------------------------
# 4. _derive_wave_t_status unit coverage (isolates the decision table)
# ---------------------------------------------------------------------------


def test_derive_status_wave_t_completed() -> None:
    status, reason = _derive_wave_t_status(
        [_wave("T", success=True)], wave_t_expected=True, failing_wave=None
    )
    assert status == "completed"
    assert reason is None


def test_derive_status_skipped_with_failing_wave() -> None:
    status, reason = _derive_wave_t_status(
        [_wave("D", success=False)], wave_t_expected=True, failing_wave="D"
    )
    assert status == "skipped"
    assert "Wave D" in reason  # type: ignore[operator]


def test_derive_status_skipped_without_failing_wave() -> None:
    status, reason = _derive_wave_t_status(
        [_wave("A")], wave_t_expected=True, failing_wave=None
    )
    assert status == "skipped"
    assert reason is not None


def test_derive_status_disabled() -> None:
    status, reason = _derive_wave_t_status(
        [_wave("E")], wave_t_expected=False, failing_wave=None
    )
    assert status == "disabled"
    assert reason is not None
