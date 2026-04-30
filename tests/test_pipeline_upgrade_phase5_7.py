"""Phase 5.7 — bootstrap watchdog + productive-tool-idle + cumulative-wedge cap.

Plan: ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §J + §M.M4 + §M.M6.

Closes R-#41 (no bootstrap watchdog), R-#45 (Codex productive-tool idle wedge),
and §M.M4 (cumulative bootstrap-wedge circuit breaker). AC4 (live bootstrap-
wedge respawn) and AC10 (M3 replay against ``codex_timeout_seconds=5400``)
are deferred to the closeout-smoke checklist; this fixture file covers
AC1 + AC2 + AC3 + AC5 + AC6 + AC7 + AC8 + AC9 plus 9 supporting fixtures
for the predicate truth table, RunState round-trip, ``update_milestone_progress``
PRESERVE-on-skip, cap-boundary lock, team-mode opaque exemption, provider
scoping, sub-agent idle fallback preservation, and callback uninstall.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch, AsyncMock

import pytest

from agent_team_v15 import wave_executor as we
from agent_team_v15 import cli as cli_mod
from agent_team_v15.config import V18Config, _validate_v18_phase57
from agent_team_v15.state import (
    RunState,
    save_state,
    load_state,
    update_milestone_progress,
)
from agent_team_v15.wave_executor import (
    BuildEnvironmentUnstableError,
    WaveWatchdogTimeoutError,
    _WaveWatchdogState,
    _build_wave_watchdog_timeout,
    _is_productive_tool_event,
    _write_hang_report,
    get_bootstrap_wedge_callback,
    install_bootstrap_wedge_callback,
)


# ---------------------------------------------------------------------------
# supp 1 — predicate truth table lock
# ---------------------------------------------------------------------------


def test_is_productive_tool_event_truth_table() -> None:
    """Locks the centralised predicate per §J.4. Productive iff Codex
    ``commandExecution`` lifecycle OR Claude ``tool_use``/``tool_result``."""
    # Productive — Claude direct-SDK
    assert _is_productive_tool_event("tool_use", "Bash", "start") is True
    assert _is_productive_tool_event("tool_use", "Edit", "start") is True
    assert _is_productive_tool_event("tool_result", "", "complete") is True
    assert _is_productive_tool_event("tool_use", "Write", "start") is True
    # Productive — Codex
    assert _is_productive_tool_event("item/started", "commandExecution", "start") is True
    assert _is_productive_tool_event("item.started", "commandExecution", "start") is True
    assert _is_productive_tool_event("item/completed", "commandExecution", "complete") is True
    assert _is_productive_tool_event("item.completed", "commandExecution", "complete") is True
    # Non-productive — Codex non-tool items
    assert _is_productive_tool_event("item/started", "agentMessage", "start") is False
    assert _is_productive_tool_event("item/started", "reasoning", "start") is False
    assert _is_productive_tool_event("item/started", "plan", "start") is False
    assert _is_productive_tool_event("item/agentMessage/delta", "agentMessage", "other") is False
    # Non-productive — Claude reasoning / bookends
    assert _is_productive_tool_event("assistant_text", "", "other") is False
    assert _is_productive_tool_event("assistant_message", "", "other") is False
    assert _is_productive_tool_event("result_message", "", "other") is False
    assert _is_productive_tool_event("sdk_call_started", "", "other") is False
    assert _is_productive_tool_event("sdk_session_started", "", "other") is False
    assert _is_productive_tool_event("query_submitted", "", "other") is False
    # Non-productive — agent_teams_backend bookends
    assert _is_productive_tool_event("agent_teams_session_started", "", "start") is False
    assert _is_productive_tool_event("agent_teams_session_completed", "", "completed") is False
    # Non-productive — Codex transport-level diagnostics
    assert _is_productive_tool_event("codex_event", "commandExecution", "start") is False
    assert _is_productive_tool_event("codex_stdout", "", "other") is False
    assert _is_productive_tool_event("turn/started", "", "other") is False
    # Empty strings
    assert _is_productive_tool_event("", "", "") is False


# ---------------------------------------------------------------------------
# AC9 — config validation: rejects 30/60s tool_call_idle; default 1200
# ---------------------------------------------------------------------------


def test_tool_call_idle_timeout_validation_rejects_30() -> None:
    cfg = V18Config()
    cfg.tool_call_idle_timeout_seconds = 30
    with pytest.raises(ValueError, match=r"tool_call_idle_timeout_seconds.*>= 300"):
        _validate_v18_phase57(cfg)


def test_tool_call_idle_timeout_validation_rejects_60() -> None:
    cfg = V18Config()
    cfg.tool_call_idle_timeout_seconds = 60
    with pytest.raises(ValueError, match=r"tool_call_idle_timeout_seconds.*>= 300"):
        _validate_v18_phase57(cfg)


def test_tool_call_idle_timeout_default_is_1200() -> None:
    cfg = V18Config()
    assert cfg.tool_call_idle_timeout_seconds == 1200
    _validate_v18_phase57(cfg)  # default valid


def test_bootstrap_idle_timeout_default_is_60() -> None:
    cfg = V18Config()
    assert cfg.bootstrap_idle_timeout_seconds == 60
    _validate_v18_phase57(cfg)


def test_bootstrap_respawn_max_per_wave_default_is_3() -> None:
    cfg = V18Config()
    assert cfg.bootstrap_respawn_max_per_wave == 3


def test_cumulative_wedge_cap_default_is_10() -> None:
    cfg = V18Config()
    assert cfg.cumulative_wedge_cap == 10


def test_tool_call_idle_above_codex_timeout_rejected() -> None:
    cfg = V18Config()
    cfg.tool_call_idle_timeout_seconds = cfg.codex_timeout_seconds + 1
    with pytest.raises(ValueError, match=r"must be <= codex_timeout_seconds"):
        _validate_v18_phase57(cfg)


# ---------------------------------------------------------------------------
# AC1 — bootstrap fires on session_started with no productive event
# ---------------------------------------------------------------------------


def test_bootstrap_watchdog_fires_on_session_started_with_no_tool_calls() -> None:
    """AC1: mock SDK emits session_started + 0 productive events; bootstrap
    fires at the configured deadline."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    # Drive the deadline past 60s by rewinding ``started_monotonic``.
    state.started_monotonic = time.monotonic() - 70.0
    state.last_progress_monotonic = state.started_monotonic
    cfg = V18Config()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="D",
        state=state,
        config=type("Cfg", (), {"v18": cfg})(),
        idle_fallback_seconds=400,
        bootstrap_eligible=True,
    )
    assert timeout is not None
    assert timeout.timeout_kind == "bootstrap"
    assert timeout.timeout_seconds == 60


# ---------------------------------------------------------------------------
# AC2 — bootstrap clears on first productive event
# ---------------------------------------------------------------------------


def test_bootstrap_clears_on_first_productive_event() -> None:
    """AC2: a productive event flips bootstrap_cleared and sets
    last_tool_call_*; tier 1 no longer fires."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    assert state.bootstrap_cleared is False
    assert state.last_tool_call_monotonic == 0.0

    state.record_progress(
        message_type="tool_use",
        tool_name="Bash",
        tool_id="t1",
        event_kind="start",
    )
    assert state.bootstrap_cleared is True
    assert state.last_tool_call_monotonic > 0.0
    assert state.last_productive_tool_name == "Bash"
    assert state.tool_call_event_count == 1

    # With bootstrap cleared, tier 1 doesn't fire even at 70s elapsed.
    state.started_monotonic = time.monotonic() - 70.0
    cfg = V18Config()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="D",
        state=state,
        config=type("Cfg", (), {"v18": cfg})(),
        idle_fallback_seconds=400,
        bootstrap_eligible=True,
    )
    # Productive event was just recorded so tier 3/4 don't fire either.
    assert timeout is None


# ---------------------------------------------------------------------------
# AC3 — bootstrap-wedge stderr captured in hang report
# ---------------------------------------------------------------------------


def test_bootstrap_wedge_hang_report_includes_stderr_tail(tmp_path: Path) -> None:
    """AC3: ``state.stderr_tail`` (pre-populated by the dispatch path's
    stderr observer) is surfaced in the hang report."""
    state = _WaveWatchdogState()
    state.update_stderr_tail(b"Error: API rate limit exceeded\n")
    state.update_stderr_tail("Retry-After: 60\n")
    err = WaveWatchdogTimeoutError(
        "D", state, 60,
        role="compile_fix",
        include_role_in_message=True,
        timeout_kind="bootstrap",
    )
    path = _write_hang_report(
        cwd=str(tmp_path),
        milestone_id="m1",
        wave="D",
        timeout=err,
        cumulative_wedges_so_far=2,
        bootstrap_deadline_seconds=60,
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert "API rate limit exceeded" in payload["stderr_tail"]
    assert "Retry-After: 60" in payload["stderr_tail"]
    assert payload["timeout_kind"] == "bootstrap"
    assert payload["cumulative_wedges_so_far"] == 2
    assert payload["bootstrap_deadline_seconds"] == 60


def test_stderr_tail_ring_buffer_truncates_to_4096_chars() -> None:
    """``update_stderr_tail`` ring-buffers to last 4096 chars."""
    state = _WaveWatchdogState()
    state.update_stderr_tail("X" * 5000)
    assert len(state.stderr_tail) == 4096
    assert state.stderr_tail == "X" * 4096
    state.update_stderr_tail(b"\nYYYY")
    assert state.stderr_tail.endswith("\nYYYY")
    assert len(state.stderr_tail) == 4096


# ---------------------------------------------------------------------------
# AC5 — bootstrap respawn doesn't increment wave-retry budget
# ---------------------------------------------------------------------------


def test_bootstrap_respawn_does_not_increment_wave_retry_budget() -> None:
    """AC5: wave-retry budget (`_wave_watchdog_max_retries`) is consumed by
    the OUTER `_execute_wave_sdk` loop. Bootstrap respawn happens INSIDE
    `_invoke_*_with_watchdog`, so the outer retry counter is unchanged.

    This fixture verifies the structural property: the respawn loop in
    `_invoke_sdk_sub_agent_with_watchdog` rebuilds state fresh per attempt
    but does NOT signal back to any outer retry counter."""
    # The function signature exposes no retry-budget kwargs; the respawn
    # is purely internal. This is a structural / contract test.
    import inspect

    sig = inspect.signature(we._invoke_sdk_sub_agent_with_watchdog)
    # No retry_count_override / wave_retry_count param in sub-agent
    # watchdog (the outer wave retry budget is consumed at
    # _execute_wave_sdk level, not here).
    assert "retry_count_override" not in sig.parameters
    # Per-wave respawn cap config is read from v18 config inside the
    # function (not threaded via kwargs).
    assert "bootstrap_respawn_max_per_wave" not in sig.parameters


# ---------------------------------------------------------------------------
# AC6 — productive-tool-idle fires when only non-productive progress streams
# ---------------------------------------------------------------------------


def test_productive_tool_idle_fires_after_bootstrap_clears_with_only_non_productive_progress() -> None:
    """AC6: feed one ``commandExecution`` start (clears bootstrap), then
    1200s of ``item/agentMessage/delta``; assert tier 3 fires."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    # Productive event clears bootstrap + starts tier-3 timer.
    state.record_progress(
        message_type="item/started",
        tool_name="commandExecution",
        tool_id="cmd-1",
        event_kind="start",
    )
    state.record_progress(
        message_type="item/completed",
        tool_name="commandExecution",
        tool_id="cmd-1",
        event_kind="complete",
    )
    assert state.bootstrap_cleared is True
    assert not state.pending_tool_starts
    assert state.last_tool_call_monotonic > 0.0
    # Simulate 1200s of agentMessage deltas (non-productive). Each
    # refreshes last_progress_monotonic but NOT last_tool_call_monotonic.
    state.last_tool_call_monotonic = time.monotonic() - 1300.0  # rewind tier-3 timer
    state.record_progress(
        message_type="item/agentMessage/delta",
        tool_name="agentMessage",
        event_kind="other",
    )
    # last_progress_monotonic was just refreshed (so tier 4 won't fire),
    # but last_tool_call_monotonic is 1300s old (tier 3 fires).
    cfg = V18Config()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=type("Cfg", (), {"v18": cfg})(),
        idle_fallback_seconds=1800,
        bootstrap_eligible=True,
    )
    assert timeout is not None
    assert timeout.timeout_kind == "tool-call-idle"
    assert timeout.timeout_seconds == 1200


# ---------------------------------------------------------------------------
# AC7 — stale progress after first commandExecution fires at 1200s, not 5400s
# ---------------------------------------------------------------------------


def test_stale_progress_after_first_command_execution_fires_at_1200s_not_5400s() -> None:
    """AC7: after one ``commandExecution`` complete, no further events for
    1300s; assert tier 3 fires before ``codex_timeout_seconds=5400``."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    state.record_progress(
        message_type="item.started",
        tool_name="commandExecution",
        tool_id="cmd-1",
        event_kind="start",
    )
    state.record_progress(
        message_type="item.completed",
        tool_name="commandExecution",
        tool_id="cmd-1",
        event_kind="complete",
    )
    # No further events. Rewind both monotonics by 1300s to simulate
    # stale progress (last_tool_call AND last_progress are old).
    rewind = 1300.0
    state.last_tool_call_monotonic -= rewind
    state.last_progress_monotonic -= rewind
    cfg = V18Config()
    assert cfg.codex_timeout_seconds == 5400
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=type("Cfg", (), {"v18": cfg})(),
        idle_fallback_seconds=1800,  # generic wave-idle
        bootstrap_eligible=True,
    )
    # Tier 3 fires at 1200s < tier 4 (1800s wave-idle); both <<
    # codex_timeout_seconds=5400. AC7 just locks tier 3 fires before 5400.
    assert timeout is not None
    assert timeout.timeout_kind == "tool-call-idle"


# ---------------------------------------------------------------------------
# AC8 — pending commandExecution older than orphan threshold fires orphan-tool, NOT tool-call-idle
# ---------------------------------------------------------------------------


def test_pending_command_execution_fires_orphan_tool_not_tool_call_idle() -> None:
    """AC8: precedence — pending tool wedge > productive-tool-idle.
    A ``commandExecution`` started but not completed for >
    ``orphan_tool_idle_timeout_seconds`` MUST fire ``orphan-tool``, not
    ``tool-call-idle``."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    # commandExecution start clears bootstrap AND adds to pending_tool_starts.
    state.record_progress(
        message_type="item.started",
        tool_name="commandExecution",
        tool_id="cmd-1",
        event_kind="start",
    )
    assert state.bootstrap_cleared is True
    assert "cmd-1" in state.pending_tool_starts
    # Rewind the tool's started_monotonic past the orphan threshold (400s).
    state.pending_tool_starts["cmd-1"]["started_monotonic"] = time.monotonic() - 500.0
    # Also rewind last_tool_call_monotonic past 1200s — tier 3 would fire
    # IF it were checked, but tier 2 (orphan) takes precedence.
    state.last_tool_call_monotonic -= 1300.0
    cfg = V18Config()
    cfg_obj = type("Cfg", (), {"v18": cfg})()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=cfg_obj,
        idle_fallback_seconds=1800,
        bootstrap_eligible=True,
    )
    assert timeout is not None
    assert timeout.timeout_kind == "orphan-tool"
    assert timeout.orphan_tool_id == "cmd-1"


# ---------------------------------------------------------------------------
# supp 2 — RunState round-trip for _cumulative_wedge_budget
# ---------------------------------------------------------------------------


def test_run_state_cumulative_wedge_budget_round_trip(tmp_path: Path) -> None:
    """``_cumulative_wedge_budget`` round-trips through save/load."""
    state = RunState(task="phase-5-7-roundtrip")
    state._cumulative_wedge_budget = 7
    save_state(state, tmp_path)
    loaded = load_state(str(tmp_path))
    assert loaded is not None
    assert loaded._cumulative_wedge_budget == 7

    # Also verify backward-compat: pre-Phase-5.7 STATE.json (no field) loads to 0.
    state_path = tmp_path / "STATE.json"
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    raw.pop("_cumulative_wedge_budget", None)
    state_path.write_text(json.dumps(raw), encoding="utf-8")
    loaded2 = load_state(str(tmp_path))
    assert loaded2 is not None
    assert loaded2._cumulative_wedge_budget == 0


# ---------------------------------------------------------------------------
# supp 3 — _bootstrap_wedge_diagnostics PRESERVE-on-skip across update_milestone_progress
# ---------------------------------------------------------------------------


def test_bootstrap_wedge_diagnostics_preserved_across_update_milestone_progress() -> None:
    """``update_milestone_progress`` REPLACE-semantic must NOT wipe
    ``_bootstrap_wedge_diagnostics`` when the kwarg isn't passed."""
    state = RunState(task="phase-5-7-preserve")
    update_milestone_progress(state, "m1", "IN_PROGRESS")
    # Mutate diagnostics directly (mimics the bootstrap-wedge callback).
    state.milestone_progress["m1"]["_bootstrap_wedge_diagnostics"] = {
        "B": {"respawns": 1, "last_wedge_iso": "2026-04-29T00:00:00", "cumulative_at_wave_end": 1},
        "D": {"respawns": 2, "last_wedge_iso": "2026-04-29T00:01:00", "cumulative_at_wave_end": 3},
    }
    # Transition to COMPLETE (without passing the diagnostics kwarg).
    update_milestone_progress(state, "m1", "COMPLETE")
    diag = state.milestone_progress["m1"].get("_bootstrap_wedge_diagnostics")
    assert isinstance(diag, dict)
    assert "B" in diag and "D" in diag
    assert diag["B"]["respawns"] == 1
    assert diag["D"]["respawns"] == 2


# ---------------------------------------------------------------------------
# supp 4 — cap-boundary lock (REACHING cap raises)
# ---------------------------------------------------------------------------


def test_cumulative_wedge_cap_halt_fires_exactly_at_cap_reached(tmp_path: Path) -> None:
    """§M.M4 boundary: count REACHING cap raises BuildEnvironmentUnstableError.

    With cap=3:
    * 1st wedge → counter=1, no raise.
    * 2nd wedge → counter=2, no raise.
    * 3rd wedge → counter=3, raise BuildEnvironmentUnstableError.
    """
    state = RunState(task="phase-5-7-cap")
    state.current_milestone = "m1"
    update_milestone_progress(state, "m1", "IN_PROGRESS")
    cap = 3
    # Construct the agent_team_dir; save_state will write STATE.json there.
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)

    callback = cli_mod._make_bootstrap_wedge_callback(
        state=state,
        cap=cap,
        agent_team_dir=agent_team_dir,
        current_milestone_getter=lambda: state.current_milestone,
    )

    # 1st wedge
    callback("D", str(tmp_path / "hang1.json"))
    assert state._cumulative_wedge_budget == 1

    # 2nd wedge
    callback("D", str(tmp_path / "hang2.json"))
    assert state._cumulative_wedge_budget == 2

    # 3rd wedge — REACHES cap → raise.
    with pytest.raises(BuildEnvironmentUnstableError) as excinfo:
        callback("D", str(tmp_path / "hang3.json"))
    assert excinfo.value.count == 3
    assert excinfo.value.cap == 3
    assert state._cumulative_wedge_budget == 3

    # Per-milestone diagnostics populated.
    diag = state.milestone_progress["m1"].get("_bootstrap_wedge_diagnostics", {})
    assert "D" in diag
    assert diag["D"]["respawns"] == 3
    assert diag["D"]["cumulative_at_wave_end"] == 3
    assert diag["D"]["last_wedge_iso"]


def test_cumulative_wedge_cap_zero_disables(tmp_path: Path) -> None:
    """``cap=0`` disables the cap (legacy unbounded behaviour)."""
    state = RunState(task="phase-5-7-cap-zero")
    state.current_milestone = "m1"
    update_milestone_progress(state, "m1", "IN_PROGRESS")
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)

    callback = cli_mod._make_bootstrap_wedge_callback(
        state=state,
        cap=0,
        agent_team_dir=agent_team_dir,
        current_milestone_getter=lambda: state.current_milestone,
    )
    # Fire 100 wedges; never raises with cap=0.
    for i in range(100):
        callback("B", str(tmp_path / f"hang{i}.json"))
    assert state._cumulative_wedge_budget == 100


# ---------------------------------------------------------------------------
# supp 5 — Blocker 1: opaque team-mode subprocess > 60s does NOT bootstrap-fire
# ---------------------------------------------------------------------------


def test_team_mode_subprocess_with_no_tool_telemetry_does_NOT_bootstrap_fire() -> None:
    """Blocker 1 fixture: opaque claude --print subprocess emits ONLY
    bookend events. The cli.py team-mode exemption helper flips
    ``state.bootstrap_cleared = True`` BEFORE entering execute_prompt;
    bootstrap watchdog (tier 1) never fires, regardless of how long the
    subprocess runs."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    state.record_progress(
        message_type="agent_teams_session_started",
        tool_name="",
        event_kind="start",
    )
    # Apply the cli.py team-mode exemption (helper exposed at module level).
    cli_mod._mark_bootstrap_cleared_on_watchdog_state(state.record_progress)
    assert state.bootstrap_cleared is True
    # Tier 3 must STAY inert because last_tool_call_monotonic is 0.0
    # (no productive event ever fired).
    assert state.last_tool_call_monotonic == 0.0

    # Simulate 75s of clock advance (well past the 60s bootstrap deadline).
    state.started_monotonic = time.monotonic() - 75.0
    state.last_progress_monotonic = state.started_monotonic
    cfg = V18Config()
    cfg_obj = type("Cfg", (), {"v18": cfg})()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="D",
        state=state,
        config=cfg_obj,
        role="wave_execution",
        idle_fallback_seconds=400,
        bootstrap_eligible=True,
    )
    # Bootstrap (tier 1) DID NOT fire (bootstrap_cleared=True). Tier 3
    # DID NOT fire (last_tool_call_monotonic=0.0). Tier 4 (sub-agent
    # idle 400s) is the wedge detector here. 75s elapsed < 400s, so
    # no timeout yet.
    assert timeout is None

    # Advance to 401s — tier 4 fires (sub-agent idle 400s preserved).
    state.last_progress_monotonic = time.monotonic() - 401.0
    timeout = _build_wave_watchdog_timeout(
        wave_letter="D",
        state=state,
        config=cfg_obj,
        role="wave_execution",
        idle_fallback_seconds=400,
        bootstrap_eligible=True,
    )
    assert timeout is not None
    assert timeout.timeout_kind == "wave-idle"
    assert timeout.timeout_seconds == 400


# ---------------------------------------------------------------------------
# supp 6 — Blocker 2: provider-routed Codex (bootstrap_eligible=False) does NOT fire tier 1
# ---------------------------------------------------------------------------


def test_provider_routed_codex_does_NOT_increment_cumulative_wedge_counter() -> None:
    """Blocker 2 fixture: with ``bootstrap_eligible=False``, tier 1 is
    skipped — no bootstrap-wedge raised, no cumulative-wedge increment."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    state.started_monotonic = time.monotonic() - 75.0
    state.last_progress_monotonic = state.started_monotonic
    cfg = V18Config()
    cfg_obj = type("Cfg", (), {"v18": cfg})()
    # bootstrap_eligible=False (Codex-owned route).
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=cfg_obj,
        idle_fallback_seconds=1800,
        bootstrap_eligible=False,
    )
    # No tier 1 fire; 75s < 1800s tier 4; no firing at all.
    assert timeout is None


# ---------------------------------------------------------------------------
# supp 7 — Blocker 2: productive-tool-idle (tier 3) DOES apply to Codex paths
# ---------------------------------------------------------------------------


def test_provider_routed_codex_productive_tool_idle_DOES_apply() -> None:
    """Blocker 2 fixture: tier 3 (productive-tool-idle) applies regardless
    of ``bootstrap_eligible``. The M3 Wave B case is exactly Codex
    ``commandExecution`` idle on a Codex-owned route."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    # Codex commandExecution start → clears bootstrap AND starts tier 3 timer.
    state.record_progress(
        message_type="item/started",
        tool_name="commandExecution",
        tool_id="cmd-1",
        event_kind="start",
    )
    state.record_progress(
        message_type="item/completed",
        tool_name="commandExecution",
        tool_id="cmd-1",
        event_kind="complete",
    )
    assert state.bootstrap_cleared is True
    # Rewind tier-3 timer past 1200s.
    state.last_tool_call_monotonic = time.monotonic() - 1300.0
    cfg = V18Config()
    cfg_obj = type("Cfg", (), {"v18": cfg})()
    timeout = _build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=cfg_obj,
        idle_fallback_seconds=1800,
        bootstrap_eligible=False,  # Codex-owned route
    )
    # Tier 3 fires regardless of bootstrap_eligible — this is R-#45.
    assert timeout is not None
    assert timeout.timeout_kind == "tool-call-idle"


# ---------------------------------------------------------------------------
# supp 8 — Blocker 3: sub-agent fallback uses _sub_agent_idle_timeout, not _wave_idle_timeout
# ---------------------------------------------------------------------------


def test_sub_agent_idle_fallback_uses_sub_agent_timeout_not_wave_timeout() -> None:
    """Blocker 3 fixture: the ``idle_fallback_seconds`` kwarg is honored.
    Sub-agent callers pass 400/600s; without the kwarg, the default
    1800s wave-idle would silently take over."""
    state = _WaveWatchdogState()
    # bootstrap cleared (mark via the team-mode helper for cleanliness).
    state.bootstrap_cleared = True
    # No productive event → tier 3 stays inert.
    assert state.last_tool_call_monotonic == 0.0
    # No pending tool → tier 2 stays inert.
    assert not state.pending_tool_starts
    # Last progress 401s ago → tier 4 fires IF the fallback is 400s.
    state.last_progress_monotonic = time.monotonic() - 401.0
    cfg = V18Config()
    cfg_obj = type("Cfg", (), {"v18": cfg})()

    # Sub-agent fallback (400s) → fires.
    timeout = _build_wave_watchdog_timeout(
        wave_letter="D",
        state=state,
        config=cfg_obj,
        idle_fallback_seconds=400,  # _sub_agent_idle_timeout_seconds
        bootstrap_eligible=True,
    )
    assert timeout is not None
    assert timeout.timeout_kind == "wave-idle"
    assert timeout.timeout_seconds == 400

    # Wave fallback (1800s) at the same elapsed → does NOT fire.
    timeout2 = _build_wave_watchdog_timeout(
        wave_letter="D",
        state=state,
        config=cfg_obj,
        idle_fallback_seconds=1800,  # _wave_idle_timeout_seconds
        bootstrap_eligible=True,
    )
    assert timeout2 is None


# ---------------------------------------------------------------------------
# supp 9 — callback uninstall in finally
# ---------------------------------------------------------------------------


def test_bootstrap_wedge_callback_uninstalls_in_finally_after_exception(tmp_path: Path) -> None:
    """Q4 condition: the callback MUST uninstall in ``finally`` even when
    an exception bubbles up. Mirrors the cli.py install/uninstall pattern."""
    # Pre-state: no callback installed.
    install_bootstrap_wedge_callback(None)
    assert get_bootstrap_wedge_callback() is None

    state = RunState(task="phase-5-7-uninstall")
    state.current_milestone = "m1"
    agent_team_dir = tmp_path / ".agent-team"
    agent_team_dir.mkdir(parents=True, exist_ok=True)
    cb = cli_mod._make_bootstrap_wedge_callback(
        state=state,
        cap=10,
        agent_team_dir=agent_team_dir,
        current_milestone_getter=lambda: state.current_milestone,
    )

    class _ExpectedExc(RuntimeError):
        pass

    try:
        install_bootstrap_wedge_callback(cb)
        assert get_bootstrap_wedge_callback() is cb
        raise _ExpectedExc("simulated failure inside the milestone loop")
    except _ExpectedExc:
        pass
    finally:
        install_bootstrap_wedge_callback(None)

    # Post-finally: callback uninstalled.
    assert get_bootstrap_wedge_callback() is None


# ---------------------------------------------------------------------------
# supp 10 — hang report tool-call-idle schema
# ---------------------------------------------------------------------------


def test_run_milestone_audit_routes_through_bootstrap_watchdog_when_cwd_supplied() -> None:
    """§M.M4 line 1515 mandates re-audit sessions are bootstrap-eligible.
    Phase 5.7 reviewer-correction wires the cli.py audit dispatch through
    ``_invoke_sdk_sub_agent_with_watchdog`` with ``role="audit"`` whenever
    ``cwd`` is in scope. This fixture locks the structural property:
    ``_run_milestone_audit`` accepts a ``cwd`` kwarg AND its body calls
    ``_invoke_sdk_sub_agent_with_watchdog`` with ``role="audit"`` /
    ``wave_letter="audit"`` on the bootstrap-watchdog branch.
    """
    import inspect
    from agent_team_v15 import cli as cli_mod_local

    sig = inspect.signature(cli_mod_local._run_milestone_audit)
    assert "cwd" in sig.parameters, (
        "Phase 5.7 reviewer-correction: _run_milestone_audit must accept a "
        "``cwd`` kwarg so the audit dispatch can route through "
        "_invoke_sdk_sub_agent_with_watchdog."
    )
    assert sig.parameters["cwd"].default is None, (
        "Phase 5.7: ``cwd`` defaults to None for backward-compat with "
        "legacy callers; the bootstrap-watchdog path is gated on "
        "``cwd`` being non-empty."
    )

    src = inspect.getsource(cli_mod_local._run_milestone_audit)
    assert "_invoke_sdk_sub_agent_with_watchdog" in src, (
        "Phase 5.7 §M.M4: _run_milestone_audit must call "
        "_invoke_sdk_sub_agent_with_watchdog when cwd is supplied so "
        "the (re-)audit dispatch is bootstrap-eligible."
    )
    assert 'role="audit"' in src, (
        "Phase 5.7 reviewer-correction: the audit dispatch must emit "
        '``role="audit"`` on the resulting hang-report payload so '
        "O.4.11's payload.role grouping covers re-audit sessions."
    )
    assert 'wave_letter="audit"' in src, (
        "Phase 5.7: ``wave_letter=\"audit\"`` so hang-report filenames "
        "are wave-audit-<ts>.json (disambiguates from primary wave reports)."
    )


def test_run_milestone_audit_re_raises_build_environment_unstable_before_broad_except() -> None:
    """§M.M4 cap-halt propagation gate: ``BuildEnvironmentUnstableError`` is
    a ``RuntimeError`` (and thus ``Exception``) — the audit wrapper's broad
    ``except Exception`` would swallow it without an explicit early
    re-raise. AST/source inspection asserts the early re-raise sits
    BEFORE the broad catcher of the SDK-dispatch try block (the one
    containing the ``_invoke_sdk_sub_agent_with_watchdog`` call)."""
    import inspect
    import re
    from agent_team_v15 import cli as cli_mod_local

    src = inspect.getsource(cli_mod_local._run_milestone_audit)
    # Locate the SDK-dispatch region — it contains
    # ``_invoke_sdk_sub_agent_with_watchdog`` AND has its OWN sibling
    # ``except BuildEnvironmentUnstableError: raise`` + ``except Exception``.
    sdk_anchor = src.find("_invoke_sdk_sub_agent_with_watchdog")
    assert sdk_anchor != -1, (
        "Phase 5.7: _run_milestone_audit must call "
        "_invoke_sdk_sub_agent_with_watchdog (Phase 5.7 §M.M4 wiring)."
    )
    # Search the SUFFIX (everything after the anchor) for the early
    # re-raise and the SIBLING broad catcher. The two MUST appear in
    # that order with no intermediate ``except Exception`` clause.
    suffix = src[sdk_anchor:]
    early = re.search(
        r"except\s+BuildEnvironmentUnstableError\s*:\s*\n\s*"
        r"(?:#[^\n]*\n\s*)*"
        r"raise",
        suffix,
    )
    assert early is not None, (
        "Phase 5.7 reviewer-correction: _run_milestone_audit must catch "
        "BuildEnvironmentUnstableError and re-raise on the SDK-dispatch "
        "try-block so the §M.M4 cap halt reaches the cli_main top-level "
        "handler. Without the early re-raise, the sibling ``except "
        "Exception`` swallows the cap halt."
    )
    after_early = suffix[early.end():]
    sibling_broad = re.search(r"except\s+Exception\s+as\s+\w+\s*:", after_early)
    assert sibling_broad is not None, (
        "Phase 5.7: expected a sibling ``except Exception`` immediately "
        "after the BuildEnvironmentUnstableError re-raise."
    )


def test_run_audit_fix_unified_re_raises_build_environment_unstable_at_both_layers() -> None:
    """§M.M4 cap-halt propagation gate for the audit-fix wrapper —
    BOTH layers must early-re-raise:

    * Inner ``_run_patch_fixes`` per-feature try (cli.py:8701 area).
    * Outer ``execute_unified_fix_async`` try (cli.py:8780 area) — without
      this, the cap exception propagating up from ``_run_patch_fixes``
      is swallowed by the outer ``except Exception`` because
      BuildEnvironmentUnstableError is RuntimeError → Exception.
    """
    import inspect
    import re
    from agent_team_v15 import cli as cli_mod_local

    src = inspect.getsource(cli_mod_local._run_audit_fix_unified)

    # Both inner + outer layers must early-re-raise. Find ALL
    # ``except BuildEnvironmentUnstableError: raise`` occurrences.
    early_matches = list(
        re.finditer(
            r"except\s+BuildEnvironmentUnstableError\s*:\s*\n\s*"
            r"(?:#[^\n]*\n\s*)*"
            r"raise",
            src,
        )
    )
    assert len(early_matches) >= 2, (
        f"Phase 5.7 reviewer-correction: _run_audit_fix_unified must "
        f"catch BuildEnvironmentUnstableError and re-raise at TWO layers "
        f"— per-feature ``_run_patch_fixes`` AND outer "
        f"``execute_unified_fix_async``. Found {len(early_matches)} match(es); "
        f"need >= 2 so the cap halt propagates through both layers without "
        f"hitting a sibling broad ``except Exception``."
    )

    # The OUTER catcher must sit before its sibling ``except Exception``.
    # Anchor on the ``execute_unified_fix_async`` call to scope the search
    # to the outer try block.
    exec_anchor = src.find("execute_unified_fix_async")
    assert exec_anchor != -1
    suffix = src[exec_anchor:]
    outer_early = re.search(
        r"except\s+BuildEnvironmentUnstableError\s*:\s*\n\s*"
        r"(?:#[^\n]*\n\s*)*"
        r"raise",
        suffix,
    )
    assert outer_early is not None, (
        "Phase 5.7 §M.M4: outer execute_unified_fix_async try block must "
        "early-re-raise BuildEnvironmentUnstableError before the broad "
        "``except Exception``."
    )
    after_outer = suffix[outer_early.end():]
    sibling_broad = re.search(r"except\s+Exception\s+as\s+\w+\s*:", after_outer)
    assert sibling_broad is not None, (
        "Phase 5.7: expected a sibling ``except Exception`` after the "
        "outer BuildEnvironmentUnstableError re-raise."
    )


@pytest.mark.asyncio
async def test_run_audit_fix_unified_propagates_cap_halt_through_outer_layer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavioural lock for §M.M4 cap-halt propagation through the OUTER
    ``execute_unified_fix_async`` layer of ``_run_audit_fix_unified``.
    When the inner dispatch (here mocked at the executor level)
    raises ``BuildEnvironmentUnstableError``, the exception escapes
    the WHOLE function — locking that the outer broad ``except
    Exception`` (which exists for legitimate non-cap failures like
    fix-Claude crashing) does not swallow the cap halt."""
    from agent_team_v15 import cli as cli_mod_local
    from agent_team_v15 import wave_executor as we_mod_local
    from agent_team_v15 import fix_executor as fix_executor_mod

    # Monkeypatch ``execute_unified_fix_async`` at the source module so
    # the local import inside ``_run_audit_fix_unified`` (``from .fix_executor
    # import ..., execute_unified_fix_async, ...``) picks up the patched
    # version. The local import binding happens on every function call
    # (per Python's module-attribute lookup), so the monkeypatch applies.
    async def _raise_cap_from_executor(*args: Any, **kwargs: Any) -> float:
        raise we_mod_local.BuildEnvironmentUnstableError(count=10, cap=10)

    monkeypatch.setattr(
        fix_executor_mod,
        "execute_unified_fix_async",
        _raise_cap_from_executor,
    )

    # Provide ONE finding-like object so the function survives the
    # ``if not findings: return [], 0.0`` early-exit at line ~8302
    # AND the ``filter_denylisted_findings`` filter (empty primary_file
    # passes the denylist match). _convert_findings uses getattr with
    # defaults for every attribute, so an empty object suffices.
    fake_finding = type("_F", (), {})()
    fake_report = type(
        "_R",
        (),
        {
            "findings": [fake_finding],
            "fix_candidates": [],
            "score": type("_S", (), {"score": 0.0, "max_score": 100.0})(),
            "extras": {},
        },
    )()
    cfg = type(
        "_Cfg",
        (),
        {
            "audit_team": type(
                "_Audit",
                (),
                {
                    "audit_wave_awareness_enabled": False,
                    "lift_risk_1_when_nets_armed": False,
                },
            )(),
            "v18": V18Config(),
        },
    )()

    with pytest.raises(we_mod_local.BuildEnvironmentUnstableError):
        await cli_mod_local._run_audit_fix_unified(
            fake_report,
            cfg,
            str(tmp_path),
            "task",
            "standard",
            fix_round=1,
            milestone_id="m1",
        )


@pytest.mark.asyncio
async def test_run_audit_fix_unified_propagates_cap_halt_and_restores_env_vars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavioural lock that AGENT_TEAM_FINDING_ID +
    AGENT_TEAM_ALLOWED_PATHS env-var sentinels are restored on
    cap-halt propagation through audit-fix. The per-feature
    ``finally`` block inside ``_run_patch_fixes`` is responsible for
    the restore; this fixture verifies it survives the cap-halt
    propagation path end-to-end."""
    from agent_team_v15 import cli as cli_mod_local
    from agent_team_v15 import wave_executor as we_mod_local
    from agent_team_v15 import fix_executor as fix_executor_mod

    monkeypatch.setenv("AGENT_TEAM_FINDING_ID", "PRE_FID")
    monkeypatch.setenv("AGENT_TEAM_ALLOWED_PATHS", "PRE_PATHS")

    async def _raise_cap_from_executor(*args: Any, **kwargs: Any) -> float:
        # Mid-dispatch: emulate the per-feature env shim having SET
        # the env vars (via _run_patch_fixes) and then the cap halt
        # firing. The outer execute_unified_fix_async raises straight
        # through; the per-feature ``finally`` is responsible for
        # restore IFF the inner closure had run. For the outer-layer
        # propagation path we verify the env vars are NOT permanently
        # corrupted by an unhandled cap halt.
        raise we_mod_local.BuildEnvironmentUnstableError(count=10, cap=10)

    monkeypatch.setattr(
        fix_executor_mod,
        "execute_unified_fix_async",
        _raise_cap_from_executor,
    )
    fake_finding = type("_F", (), {})()
    fake_report = type(
        "_R",
        (),
        {
            "findings": [fake_finding],
            "fix_candidates": [],
            "score": type("_S", (), {"score": 0.0, "max_score": 100.0})(),
            "extras": {},
        },
    )()
    cfg = type(
        "_Cfg",
        (),
        {
            "audit_team": type(
                "_Audit",
                (),
                {
                    "audit_wave_awareness_enabled": False,
                    "lift_risk_1_when_nets_armed": False,
                },
            )(),
            "v18": V18Config(),
        },
    )()

    with pytest.raises(we_mod_local.BuildEnvironmentUnstableError):
        await cli_mod_local._run_audit_fix_unified(
            fake_report,
            cfg,
            str(tmp_path),
            "task",
            "standard",
            fix_round=1,
            milestone_id="m1",
        )

    # Env vars survive the cap-halt propagation (no permanent
    # corruption from an unhandled exception path; the monkeypatch
    # fixture's setenv values are restored by pytest cleanup, but
    # we verify they're still intact at this assertion point —
    # i.e., no broken env-var management leaked them away during
    # the propagation).
    assert os.environ.get("AGENT_TEAM_FINDING_ID") == "PRE_FID"
    assert os.environ.get("AGENT_TEAM_ALLOWED_PATHS") == "PRE_PATHS"


@pytest.mark.asyncio
async def test_run_milestone_audit_propagates_cap_halt_and_restores_env_vars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavioural lock for §M.M4 cap-halt propagation through the audit
    wrapper: when ``_invoke_sdk_sub_agent_with_watchdog`` raises
    ``BuildEnvironmentUnstableError``, the exception propagates out of
    ``_run_milestone_audit`` (NOT swallowed by the broad ``except Exception``)
    AND the ``AGENT_TEAM_AUDIT_*`` env vars are restored to their pre-call
    values via the ``finally`` block."""
    from agent_team_v15 import cli as cli_mod_local
    from agent_team_v15 import wave_executor as we_mod_local

    # Sentinel pre-call values — must be restored after the exception escapes.
    monkeypatch.setenv("AGENT_TEAM_AUDIT_WRITER", "PRE_SENTINEL")
    monkeypatch.setenv("AGENT_TEAM_AUDIT_OUTPUT_ROOT", "PRE_OUT")
    monkeypatch.setenv("AGENT_TEAM_AUDIT_REQUIREMENTS_PATH", "PRE_REQ")

    async def _raise_cap(**_: Any) -> tuple[float, _WaveWatchdogState]:
        raise we_mod_local.BuildEnvironmentUnstableError(count=10, cap=10)

    monkeypatch.setattr(
        we_mod_local,
        "_invoke_sdk_sub_agent_with_watchdog",
        _raise_cap,
    )
    # Stub auditors so we get to the SDK dispatch.
    monkeypatch.setattr(
        "agent_team_v15.audit_team.get_auditors_for_depth",
        lambda _depth: ["technical"],
    )
    monkeypatch.setattr(
        "agent_team_v15.audit_team.build_auditor_agent_definitions",
        lambda *args, **kwargs: {"audit-technical": {"description": "stub"}},
    )
    monkeypatch.setattr(cli_mod_local, "_build_options", lambda *a, **kw: object())

    # Fake config object — minimal shape audit needs.
    cfg = type(
        "_Cfg",
        (),
        {
            "audit_team": type(
                "_Audit",
                (),
                {
                    "max_parallel_auditors": 1,
                },
            )(),
            "v18": V18Config(),
        },
    )()

    audit_dir = tmp_path / ".agent-team" / "milestones" / "m1" / ".agent-team"
    audit_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(we_mod_local.BuildEnvironmentUnstableError):
        await cli_mod_local._run_milestone_audit(
            milestone_id="m1",
            milestone_template="full_stack",
            config=cfg,
            depth="standard",
            task_text="test",
            requirements_path=str(tmp_path / "REQUIREMENTS.md"),
            audit_dir=str(audit_dir),
            cycle=2,  # re-audit
            cwd=str(tmp_path),
        )

    # Env vars restored to their pre-call sentinel values.
    assert os.environ.get("AGENT_TEAM_AUDIT_WRITER") == "PRE_SENTINEL"
    assert os.environ.get("AGENT_TEAM_AUDIT_OUTPUT_ROOT") == "PRE_OUT"
    assert os.environ.get("AGENT_TEAM_AUDIT_REQUIREMENTS_PATH") == "PRE_REQ"


def test_run_audit_fix_unified_routes_through_bootstrap_watchdog_when_cwd_supplied() -> None:
    """§M.M4 line 1515 mandates audit-fix sessions are bootstrap-eligible.
    Phase 5.7 reviewer-correction wires the cli.py audit-fix Claude
    fallback dispatch through ``_invoke_sdk_sub_agent_with_watchdog``
    with ``role="audit_fix"`` whenever ``cwd`` is in scope.
    """
    import inspect
    from agent_team_v15 import cli as cli_mod_local

    src = inspect.getsource(cli_mod_local._run_audit_fix_unified)
    assert "_invoke_sdk_sub_agent_with_watchdog" in src, (
        "Phase 5.7 §M.M4: _run_audit_fix_unified must call "
        "_invoke_sdk_sub_agent_with_watchdog on the Claude fallback "
        "path so audit-fix is bootstrap-eligible."
    )
    assert 'role="audit_fix"' in src, (
        "Phase 5.7 reviewer-correction: the audit-fix dispatch must "
        'emit ``role="audit_fix"`` on the resulting hang-report payload '
        "so O.4.11's payload.role grouping covers audit-fix sessions."
    )
    assert 'wave_letter="audit-fix"' in src


def test_hang_report_payload_carries_audit_role_values_for_O_4_11(tmp_path: Path) -> None:
    """O.4.11 closeout-evidence row groups hang reports by payload.role
    across the four §M.M4 subprocess classes. Lock that role="audit" and
    role="audit_fix" round-trip through ``WaveWatchdogTimeoutError`` →
    ``_write_hang_report`` payload."""
    for role_value in ("audit", "audit_fix"):
        state = _WaveWatchdogState()
        state.record_progress(message_type="sdk_call_started", tool_name="")
        err = WaveWatchdogTimeoutError(
            "audit", state, 60,
            role=role_value,
            include_role_in_message=True,
            timeout_kind="bootstrap",
        )
        path = _write_hang_report(
            cwd=str(tmp_path),
            milestone_id=f"m1-{role_value}",
            wave="audit",
            timeout=err,
            cumulative_wedges_so_far=1,
            bootstrap_deadline_seconds=60,
        )
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        assert payload["role"] == role_value, (
            f"role round-trip lost for {role_value!r}: payload.role={payload['role']!r}"
        )
        assert payload["timeout_kind"] == "bootstrap"


def test_hang_report_payload_carries_role_for_O_4_11_grouping(tmp_path: Path) -> None:
    """O.4.11 (Phase 5.7 closeout) groups hang reports by ``payload.role`` —
    the writer MUST emit ``role`` from the underlying
    ``WaveWatchdogTimeoutError.role`` attribute. Default ``""`` for legacy
    callers; canonical values are ``compile_fix`` / ``audit_fix`` / ``audit``
    / ``wave``."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    err = WaveWatchdogTimeoutError(
        "D", state, 60,
        role="compile_fix",
        include_role_in_message=True,
        timeout_kind="bootstrap",
    )
    path = _write_hang_report(
        cwd=str(tmp_path),
        milestone_id="m1",
        wave="D",
        timeout=err,
        cumulative_wedges_so_far=1,
        bootstrap_deadline_seconds=60,
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["role"] == "compile_fix"

    # Wave path defaults to role="wave".
    state2 = _WaveWatchdogState()
    state2.record_progress(message_type="sdk_call_started", tool_name="")
    err2 = WaveWatchdogTimeoutError(
        "B", state2, 60,
        role="wave",
        timeout_kind="bootstrap",
    )
    path2 = _write_hang_report(
        cwd=str(tmp_path),
        milestone_id="m1",
        wave="B",
        timeout=err2,
        cumulative_wedges_so_far=1,
        bootstrap_deadline_seconds=60,
    )
    payload2 = json.loads(Path(path2).read_text(encoding="utf-8"))
    assert payload2["role"] == "wave"


def test_hang_report_tool_call_idle_schema(tmp_path: Path) -> None:
    """Hang report writer surfaces the tool-call-idle specific fields per §J.4."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    state.record_progress(
        message_type="item/started",
        tool_name="commandExecution",
        tool_id="cmd-1",
        event_kind="start",
    )
    state.record_progress(
        message_type="item/completed",
        tool_name="commandExecution",
        tool_id="cmd-1",
        event_kind="complete",
    )
    state.record_progress(
        message_type="item/agentMessage/delta",
        tool_name="agentMessage",
        event_kind="other",
    )
    err = WaveWatchdogTimeoutError(
        "B", state, 1200,
        timeout_kind="tool-call-idle",
    )
    path = _write_hang_report(
        cwd=str(tmp_path),
        milestone_id="m1",
        wave="B",
        timeout=err,
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["timeout_kind"] == "tool-call-idle"
    assert payload["last_tool_call_at"]
    assert payload["tool_call_idle_timeout_seconds"] == 1200
    assert payload["last_non_tool_progress_at"]
    assert payload["last_productive_tool_name"] == "commandExecution"
    assert payload["tool_call_event_count"] == 2


# ---------------------------------------------------------------------------
# Stage 1A closeout-remediation — orphan-tool hang report field completeness
# ---------------------------------------------------------------------------
#
# Phase 5 closeout-smoke Stage 1A (run-dir
# ``v18 test runs/phase-5-closeout-stage-1-1a-strict-on-smoke-20260430-103941``)
# surfaced an evidence gap on §O.4.7 / §O.4.10: the orphan-tool hang reports
# (``hang_reports/wave-audit-20260430T07{1722,4723}Z.json``) buried the
# ``orphan_tool_id`` / ``orphan_tool_name`` inside ``pending_tool_starts[]``
# and omitted ``cumulative_wedges_so_far`` entirely. The
# ``WaveWatchdogTimeoutError`` already carries the orphan attributes (see
# ``test_pending_command_execution_fires_orphan_tool_not_tool_call_idle``)
# and ``_get_cumulative_wedge_count()`` is read-only, so surfacing both at
# the top level on non-bootstrap reports preserves §O.4.10's
# "Codex/orphan-tool/tool-call-idle paths do NOT increment the cumulative
# counter" guarantee — the read does not call the bootstrap wedge callback.


def test_orphan_tool_hang_report_surfaces_top_level_orphan_tool_id_and_name(
    tmp_path: Path,
) -> None:
    """Closeout remediation: ``timeout_kind=="orphan-tool"`` reports MUST
    surface ``orphan_tool_id`` + ``orphan_tool_name`` at the payload top
    level (not just inside ``pending_tool_starts[]``) so smoke reviewers
    can grep the hang report directly without walking the pending list."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    state.record_progress(
        message_type="item.started",
        tool_name="commandExecution",
        tool_id="cmd-orphan-1",
        event_kind="start",
    )
    err = WaveWatchdogTimeoutError(
        "B", state, 400,
        role="wave",
        timeout_kind="orphan-tool",
        orphan_tool_id="cmd-orphan-1",
        orphan_tool_name="commandExecution",
    )
    path = _write_hang_report(
        cwd=str(tmp_path),
        milestone_id="m1",
        wave="B",
        timeout=err,
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["timeout_kind"] == "orphan-tool"
    assert payload["orphan_tool_id"] == "cmd-orphan-1"
    assert payload["orphan_tool_name"] == "commandExecution"


def test_orphan_tool_hang_report_includes_cumulative_wedges_so_far_when_supplied(
    tmp_path: Path,
) -> None:
    """§O.4.10 closeout remediation: the writer accepts and surfaces
    ``cumulative_wedges_so_far`` for *non-bootstrap* timeout kinds too.
    The value is informational (read-only); call sites must source it
    from ``_get_cumulative_wedge_count()`` WITHOUT invoking the bootstrap
    wedge callback (which is what would increment the counter)."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    state.record_progress(
        message_type="item.started",
        tool_name="commandExecution",
        tool_id="cmd-orphan-2",
        event_kind="start",
    )
    err = WaveWatchdogTimeoutError(
        "B", state, 400,
        role="audit",
        timeout_kind="orphan-tool",
        orphan_tool_id="cmd-orphan-2",
        orphan_tool_name="commandExecution",
    )
    path = _write_hang_report(
        cwd=str(tmp_path),
        milestone_id="m1",
        wave="audit",
        timeout=err,
        cumulative_wedges_so_far=0,  # informational; counter unchanged
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["timeout_kind"] == "orphan-tool"
    assert payload["cumulative_wedges_so_far"] == 0


def test_orphan_tool_hang_report_omits_orphan_fields_for_other_timeout_kinds(
    tmp_path: Path,
) -> None:
    """When ``timeout_kind`` is NOT ``orphan-tool`` (bootstrap /
    tool-call-idle / wave-idle), the top-level orphan_tool_id /
    orphan_tool_name fields MUST NOT appear — they're noise on those
    paths and reviewers expect grouping by ``timeout_kind`` to be
    unambiguous."""
    state = _WaveWatchdogState()
    state.record_progress(message_type="sdk_call_started", tool_name="")
    err = WaveWatchdogTimeoutError(
        "B", state, 60,
        role="wave",
        timeout_kind="bootstrap",
    )
    path = _write_hang_report(
        cwd=str(tmp_path),
        milestone_id="m1",
        wave="B",
        timeout=err,
        cumulative_wedges_so_far=0,
        bootstrap_deadline_seconds=60,
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert "orphan_tool_id" not in payload
    assert "orphan_tool_name" not in payload


def test_invoke_wave_sdk_orphan_path_passes_cumulative_wedges_so_far_static() -> None:
    """§O.4.10 lock at source: ``_invoke_wave_sdk_with_watchdog`` non-
    bootstrap branch MUST pass ``cumulative_wedges_so_far=
    _get_cumulative_wedge_count()`` to ``_write_hang_report``. The static
    cite is the contract: any future refactor that drops the kwarg here
    breaks the smoke evidence shape and is caught at CI."""
    import inspect
    from agent_team_v15 import wave_executor as we_local

    src = inspect.getsource(we_local._invoke_wave_sdk_with_watchdog)
    # Locate the non-bootstrap _write_hang_report block (the one preceded
    # by the "orphan-tool / tool-call-idle / wave-idle (non-respawn)"
    # comment, NOT the bootstrap branch).
    marker = "# orphan-tool / tool-call-idle / wave-idle (non-respawn)"
    assert marker in src, (
        f"Closeout remediation: {we_local._invoke_wave_sdk_with_watchdog.__name__} "
        "lost its non-bootstrap wedge marker; cannot anchor the contract."
    )
    after_marker = src.split(marker, 1)[1]
    # The next _write_hang_report call after the marker must include
    # cumulative_wedges_so_far=_get_cumulative_wedge_count().
    assert "_write_hang_report(" in after_marker, (
        "Closeout remediation: non-bootstrap branch no longer calls "
        "_write_hang_report; check the source restructure."
    )
    write_block = after_marker.split("_write_hang_report(", 1)[1]
    # Bound the kwargs scan to a generous window so we don't accidentally
    # match a later non-bootstrap caller; the kwargs block is far smaller
    # than 800 chars in practice.
    write_block = write_block[:800]
    assert "cumulative_wedges_so_far=_get_cumulative_wedge_count()" in write_block, (
        "Closeout remediation (§O.4.10): the non-bootstrap _write_hang_report "
        "call in _invoke_wave_sdk_with_watchdog must surface the read-only "
        "cumulative wedge count so smoke reviewers can verify the counter "
        "did not increment on Codex/orphan-tool/tool-call-idle paths."
    )


def test_invoke_provider_wave_orphan_path_passes_cumulative_wedges_so_far_static() -> None:
    """§O.4.10 lock at source: same contract for
    ``_invoke_provider_wave_with_watchdog`` (the provider-routed path —
    Codex Wave B/D + provider-routed Claude). The non-bootstrap wedge
    branch MUST surface ``cumulative_wedges_so_far`` so smoke evidence
    rows show the counter unchanged for Codex paths."""
    import inspect
    from agent_team_v15 import wave_executor as we_local

    src = inspect.getsource(we_local._invoke_provider_wave_with_watchdog)
    marker = "# orphan-tool / tool-call-idle / wave-idle (non-respawn)"
    assert marker in src
    after_marker = src.split(marker, 1)[1]
    assert "_write_hang_report(" in after_marker
    write_block = after_marker.split("_write_hang_report(", 1)[1]
    # Bound the kwargs scan to a generous window so we don't accidentally
    # match a later non-bootstrap caller; the kwargs block is far smaller
    # than 800 chars in practice.
    write_block = write_block[:800]
    assert "cumulative_wedges_so_far=_get_cumulative_wedge_count()" in write_block, (
        "Closeout remediation (§O.4.10): _invoke_provider_wave_with_watchdog "
        "non-bootstrap branch must surface the read-only cumulative wedge "
        "count on hang reports for Codex provider paths."
    )


def test_invoke_sdk_sub_agent_orphan_path_passes_cumulative_wedges_so_far_static() -> None:
    """§O.4.10 lock at source: same contract for
    ``_invoke_sdk_sub_agent_with_watchdog`` (compile_fix / audit /
    audit_fix sub-agent dispatches). Non-bootstrap branch MUST surface
    ``cumulative_wedges_so_far``."""
    import inspect
    from agent_team_v15 import wave_executor as we_local

    src = inspect.getsource(we_local._invoke_sdk_sub_agent_with_watchdog)
    marker = "# orphan-tool / tool-call-idle / wave-idle: not respawnable."
    assert marker in src
    after_marker = src.split(marker, 1)[1]
    assert "_write_hang_report(" in after_marker
    write_block = after_marker.split("_write_hang_report(", 1)[1]
    # Bound the kwargs scan to a generous window so we don't accidentally
    # match a later non-bootstrap caller; the kwargs block is far smaller
    # than 800 chars in practice.
    write_block = write_block[:800]
    assert "cumulative_wedges_so_far=_get_cumulative_wedge_count()" in write_block, (
        "Closeout remediation (§O.4.10): _invoke_sdk_sub_agent_with_watchdog "
        "non-bootstrap branch must surface the read-only cumulative wedge "
        "count on hang reports for compile_fix/audit/audit_fix sub-agent "
        "wedges."
    )


def test_orphan_tool_hang_report_read_does_not_invoke_bootstrap_callback() -> None:
    """§O.4.10 behavioral lock: surfacing ``cumulative_wedges_so_far`` on
    a non-bootstrap hang report MUST NOT call the bootstrap-wedge
    callback (which is what increments ``_cumulative_wedge_budget``).
    The orphan-tool path reads the count via ``_get_cumulative_wedge_count``
    only; the callback fires only on the bootstrap branch."""
    invocations: list[tuple[str, str]] = []

    def fake_cb(wave_letter: str, hang_report_path: str) -> None:
        invocations.append((wave_letter, hang_report_path))

    install_bootstrap_wedge_callback(fake_cb)
    try:
        # Direct unit-level call to _write_hang_report on a non-bootstrap
        # timeout kind — should NOT call the callback (the callback is
        # only invoked from the bootstrap branch in the watchdog poll
        # loops, NOT from inside the writer).
        state = _WaveWatchdogState()
        state.record_progress(message_type="sdk_call_started", tool_name="")
        err = WaveWatchdogTimeoutError(
            "B", state, 400,
            role="audit",
            timeout_kind="orphan-tool",
            orphan_tool_id="cmd-orphan",
            orphan_tool_name="commandExecution",
        )
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            _write_hang_report(
                cwd=td,
                milestone_id="m1",
                wave="audit",
                timeout=err,
                cumulative_wedges_so_far=0,
            )
        assert invocations == [], (
            "§O.4.10: hang-report writes for non-bootstrap kinds must "
            "NOT invoke the bootstrap-wedge callback; observed "
            f"unexpected callback invocations: {invocations!r}"
        )
    finally:
        install_bootstrap_wedge_callback(None)


# ---------------------------------------------------------------------------
# Phase 5 closeout-stage-1-remediation — Phase 5.7 §M.M5 productive-tool-idle
# watchdog coverage gap on the runtime-verification fix-loop dispatch path.
#
# Stage 1A rerun on `bb3203e` reproduced a 35-min wedge in
# `runtime_verification.dispatch_fix_agent` with NO Phase 5.7 watchdog log
# line, NO hang report, and NO orphan-tool / tool-call-idle fire — because
# `dispatch_fix_agent` called `_process_response()` directly instead of
# routing through the 4-tier `_invoke_sdk_sub_agent_with_watchdog` wrapper
# already used by audit / audit_fix / compile_fix Claude SDK sub-agents.
# Evidence: `docs/plans/phase-artifacts/phase-5-closeout-stage-1-1a-rerun-findings.md`
# + `docs/plans/phase-artifacts/phase-5-closeout-stage-1-review.md`.
# ---------------------------------------------------------------------------


def test_runtime_verification_dispatch_fix_agent_routes_through_invoke_sdk_sub_agent_with_watchdog() -> None:
    """Source-level lock — `dispatch_fix_agent`'s body MUST call
    `_invoke_sdk_sub_agent_with_watchdog` so the runtime-fix Claude SDK
    dispatch is bootstrap-eligible AND productive-tool-idle covered.

    Mirror of
    ``test_run_audit_fix_unified_routes_through_bootstrap_watchdog_when_cwd_supplied``.
    Without this wiring, a wedge in the runtime-fix Codex pipe (35-min
    tool-call-idle observed Stage 1 1A rerun attempt 2 on `bb3203e`)
    silently hangs Phase 6 indefinitely with no hang report on disk.
    """
    import inspect
    from agent_team_v15 import runtime_verification as rv_mod

    src = inspect.getsource(rv_mod.dispatch_fix_agent)
    assert "_invoke_sdk_sub_agent_with_watchdog" in src, (
        "Phase 5.7 §M.M5 follow-up: dispatch_fix_agent must call "
        "_invoke_sdk_sub_agent_with_watchdog so the runtime-fix Claude "
        "SDK dispatch is covered by the 4-tier (bootstrap → orphan-tool "
        "→ productive-tool-idle → idle fallback) watchdog. Without this, "
        "a Codex pipe wedge in the runtime fix-loop silently hangs the "
        "orchestrator (35-min wedge reproduced in Stage 1 1A rerun "
        "attempt 2 on bb3203e — see "
        "docs/plans/phase-artifacts/phase-5-closeout-stage-1-1a-rerun-findings.md)."
    )
    assert 'wave_letter="runtime-fix"' in src, (
        'Phase 5.7 §M.M5 follow-up: ``wave_letter="runtime-fix"`` so '
        "hang-report filenames are wave-runtime-fix-<ts>.json "
        "(disambiguates from primary wave / audit / audit-fix / "
        "compile-fix reports)."
    )
    # role label is f-string interpolated; check the f-string template.
    assert (
        'role=f"runtime_fix_{service}"' in src
        or "role=f'runtime_fix_{service}'" in src
    ), (
        'Phase 5.7 §M.M5 follow-up: ``role=f"runtime_fix_{service}"`` '
        "so O.4.11 grouping recognises runtime-verification subprocesses "
        "by service (api / web / db / etc). Pre-fix dispatch carried "
        "current_phase=runtime_fix_<service> on _process_response — keep "
        "the same key on the watchdog-aware path."
    )


def test_runtime_verification_dispatch_fix_agent_re_raises_build_environment_unstable_before_broad_except() -> None:
    """Phase 5.7 §M.M4 cap-halt propagation gate.

    ``BuildEnvironmentUnstableError`` is ``RuntimeError`` (and thus
    ``Exception``) — ``dispatch_fix_agent``'s broad ``except Exception``
    (which logs + returns 0.0 to keep ``runtime_verification.fix_loop``
    progressing on transient SDK failures) would swallow the cap halt
    without an explicit early re-raise. Mirror of
    ``test_run_milestone_audit_re_raises_build_environment_unstable_before_broad_except``.
    """
    import inspect
    import re
    from agent_team_v15 import runtime_verification as rv_mod

    src = inspect.getsource(rv_mod.dispatch_fix_agent)
    sdk_anchor = src.find("_invoke_sdk_sub_agent_with_watchdog")
    assert sdk_anchor != -1, (
        "Phase 5.7 §M.M5 follow-up: dispatch_fix_agent must call "
        "_invoke_sdk_sub_agent_with_watchdog (Phase 5.7 §M.M4 wiring)."
    )
    suffix = src[sdk_anchor:]
    early = re.search(
        r"except\s+BuildEnvironmentUnstableError\s*:\s*\n\s*"
        r"(?:#[^\n]*\n\s*)*"
        r"raise",
        suffix,
    )
    assert early is not None, (
        "Phase 5.7 §M.M5 follow-up: dispatch_fix_agent must catch "
        "BuildEnvironmentUnstableError and re-raise on the watchdog "
        "try-block so the §M.M4 cap halt reaches the runtime-verification "
        "outer caller. Without the early re-raise, the sibling "
        "``except Exception`` (which logs + returns 0.0 to keep fix_loop "
        "progressing) swallows the cap halt because "
        "BuildEnvironmentUnstableError is RuntimeError → Exception."
    )
    after_early = suffix[early.end():]
    sibling_broad = re.search(r"except\s+Exception\s+as\s+\w+\s*:", after_early)
    assert sibling_broad is not None, (
        "Phase 5.7 §M.M5 follow-up: expected a sibling "
        "``except Exception as exc`` immediately after the "
        "BuildEnvironmentUnstableError re-raise — preserves the legacy "
        "best-effort-fix contract for non-cap-halt failures."
    )


def test_runtime_verification_dispatch_fix_agent_does_not_install_bootstrap_wedge_callback() -> None:
    """§O.4.10 + §M.M4 invariant: only the orchestrator's RunState
    lifecycle installs the bootstrap-wedge callback (which mutates
    ``_cumulative_wedge_budget``). The runtime-fix dispatch must NOT
    register its own callback — doing so would either double-count
    bootstrap wedges or interfere with cap-halt detection.

    ``_invoke_sdk_sub_agent_with_watchdog`` reads the count via
    ``_get_cumulative_wedge_count()`` (no-mutation) for hang-report
    surfacing per the closeout-stage-1 remediation; the count itself
    only advances when the orchestrator-installed callback fires.
    """
    import inspect
    from agent_team_v15 import runtime_verification as rv_mod

    src = inspect.getsource(rv_mod.dispatch_fix_agent)
    assert "install_bootstrap_wedge_callback" not in src, (
        "Phase 5 closeout O.4.10 + §M.M4: dispatch_fix_agent must NOT "
        "install its own bootstrap-wedge callback. The wedge-counter "
        "lifecycle is owned by the orchestrator's RunState; "
        "_invoke_sdk_sub_agent_with_watchdog reads the count via "
        "_get_cumulative_wedge_count() (no-mutation)."
    )
    assert "set_bootstrap_wedge_callback" not in src, (
        "Phase 5 closeout O.4.10: dispatch_fix_agent must not double-"
        "register the wedge-counter callback under any setter alias."
    )


def test_runtime_verification_dispatch_fix_agent_threads_role_wave_letter_cwd_to_sub_agent_watchdog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Behavioural lock — dispatch_fix_agent threads ``role=f"runtime_fix_{service}"``,
    ``wave_letter="runtime-fix"``, and ``cwd=str(project_root)`` into the
    4-tier watchdog wrapper so:

    1. O.4.11 hang-report grouping by ``payload.role`` covers runtime-fix
       sessions per-service (api / web / db / etc).
    2. Hang-report filenames carry the ``wave-runtime-fix-<ts>.json``
       sentinel — disambiguates from primary wave / audit / audit-fix /
       compile-fix reports when smoke reviewers grep by file pattern.
    3. Hang reports land in ``<project_root>/.agent-team/hang_reports/``
       (the wedge that motivated this follow-up patch had no hang report
       at all because the wrap was missing).
    """
    import sys
    from unittest.mock import AsyncMock, MagicMock
    from agent_team_v15 import runtime_verification as rv_mod
    from agent_team_v15 import wave_executor as we_mod
    from agent_team_v15 import cli as cli_mod_local

    recorded: dict[str, Any] = {}

    async def _fake_invoke(**kwargs: Any) -> tuple[float, Any]:
        recorded.update(kwargs)
        return 0.0, we_mod._WaveWatchdogState()

    monkeypatch.setattr(
        we_mod,
        "_invoke_sdk_sub_agent_with_watchdog",
        _fake_invoke,
    )
    monkeypatch.setattr(
        cli_mod_local,
        "_build_options",
        lambda *a, **kw: MagicMock(),
        raising=False,
    )
    monkeypatch.setattr(
        cli_mod_local,
        "_consume_response_stream",
        AsyncMock(return_value=0.0),
        raising=False,
    )
    monkeypatch.setattr(cli_mod_local, "_backend", "api", raising=False)

    # Stub claude_agent_sdk.ClaudeSDKClient as an async-context-manageable
    # MagicMock — the fake_invoke short-circuits before _execute_sdk runs,
    # so the client is constructed but never used.
    fake_sdk_module = sys.modules.get("claude_agent_sdk") or type(sys)("claude_agent_sdk")
    fake_client_cm = AsyncMock()
    fake_client_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_client_cm.__aexit__ = AsyncMock(return_value=None)
    fake_sdk_module.ClaudeSDKClient = MagicMock(return_value=fake_client_cm)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk_module)

    cost = rv_mod.dispatch_fix_agent(
        project_root=tmp_path,
        service="api",
        phase="build",
        error="docker build failed: ...",
    )

    assert cost == 0.0, f"expected 0.0 from fake invoke; got {cost!r}"
    assert recorded.get("role") == "runtime_fix_api", (
        f"Expected role='runtime_fix_api' (O.4.11 grouping per-service); "
        f"got {recorded.get('role')!r}"
    )
    assert recorded.get("wave_letter") == "runtime-fix", (
        f"Expected wave_letter='runtime-fix' (hang-report filename "
        f"sentinel); got {recorded.get('wave_letter')!r}"
    )
    assert recorded.get("cwd") == str(tmp_path), (
        f"Expected cwd={str(tmp_path)!r} (hang reports under "
        f"<project_root>/.agent-team/hang_reports/); got "
        f"{recorded.get('cwd')!r}"
    )


def test_runtime_verification_dispatch_fix_agent_propagates_build_environment_unstable_to_caller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Behavioural lock for §M.M4 cap-halt propagation: when
    ``_invoke_sdk_sub_agent_with_watchdog`` raises
    ``BuildEnvironmentUnstableError`` (cumulative-wedge cap reached),
    ``dispatch_fix_agent`` must re-raise the exception INSTEAD of
    swallowing it via the legacy broad-except. The broad-except still
    catches every other Exception class to preserve the best-effort
    contract for transient SDK failures.
    """
    import sys
    from unittest.mock import AsyncMock, MagicMock
    from agent_team_v15 import runtime_verification as rv_mod
    from agent_team_v15 import wave_executor as we_mod
    from agent_team_v15 import cli as cli_mod_local

    cap_error = we_mod.BuildEnvironmentUnstableError(count=10, cap=10)

    async def _fake_invoke_raises(**_kwargs: Any) -> tuple[float, Any]:
        raise cap_error

    monkeypatch.setattr(
        we_mod,
        "_invoke_sdk_sub_agent_with_watchdog",
        _fake_invoke_raises,
    )
    monkeypatch.setattr(
        cli_mod_local,
        "_build_options",
        lambda *a, **kw: MagicMock(),
        raising=False,
    )
    monkeypatch.setattr(
        cli_mod_local,
        "_consume_response_stream",
        AsyncMock(return_value=0.0),
        raising=False,
    )
    monkeypatch.setattr(cli_mod_local, "_backend", "api", raising=False)

    fake_sdk_module = sys.modules.get("claude_agent_sdk") or type(sys)("claude_agent_sdk")
    fake_client_cm = AsyncMock()
    fake_client_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_client_cm.__aexit__ = AsyncMock(return_value=None)
    fake_sdk_module.ClaudeSDKClient = MagicMock(return_value=fake_client_cm)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk_module)

    with pytest.raises(we_mod.BuildEnvironmentUnstableError):
        rv_mod.dispatch_fix_agent(
            project_root=tmp_path,
            service="api",
            phase="build",
            error="docker build failed: ...",
        )


def test_runtime_verification_dispatch_fix_agent_swallows_non_cap_halt_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Regression check: non-``BuildEnvironmentUnstableError`` exceptions
    raised inside the watchdog wrapper must still be swallowed by the
    legacy broad-except (returns 0.0 + warning log) so a transient SDK
    failure doesn't crash the whole runtime-verification fix loop.
    """
    import sys
    from unittest.mock import AsyncMock, MagicMock
    from agent_team_v15 import runtime_verification as rv_mod
    from agent_team_v15 import wave_executor as we_mod
    from agent_team_v15 import cli as cli_mod_local

    async def _fake_invoke_raises_other(**_kwargs: Any) -> tuple[float, Any]:
        raise we_mod.WaveWatchdogTimeoutError(
            "runtime-fix",
            we_mod._WaveWatchdogState(),
            400,
            role="runtime_fix_api",
            timeout_kind="tool-call-idle",
        )

    monkeypatch.setattr(
        we_mod,
        "_invoke_sdk_sub_agent_with_watchdog",
        _fake_invoke_raises_other,
    )
    monkeypatch.setattr(
        cli_mod_local,
        "_build_options",
        lambda *a, **kw: MagicMock(),
        raising=False,
    )
    monkeypatch.setattr(
        cli_mod_local,
        "_consume_response_stream",
        AsyncMock(return_value=0.0),
        raising=False,
    )
    monkeypatch.setattr(cli_mod_local, "_backend", "api", raising=False)

    fake_sdk_module = sys.modules.get("claude_agent_sdk") or type(sys)("claude_agent_sdk")
    fake_client_cm = AsyncMock()
    fake_client_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_client_cm.__aexit__ = AsyncMock(return_value=None)
    fake_sdk_module.ClaudeSDKClient = MagicMock(return_value=fake_client_cm)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk_module)

    cost = rv_mod.dispatch_fix_agent(
        project_root=tmp_path,
        service="api",
        phase="build",
        error="docker build failed: ...",
    )
    assert cost == 0.0, (
        "Phase 5.7 §M.M5 follow-up: non-cap-halt exceptions (e.g. "
        "WaveWatchdogTimeoutError on tool-call-idle) must be swallowed "
        "by the broad-except so fix_loop continues with the next service "
        "instead of crashing the whole runtime-verification phase."
    )
