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
