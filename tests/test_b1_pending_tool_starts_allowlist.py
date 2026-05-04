"""B1 — pending_tool_starts insertion is allowlist-gated to commandExecution.

Handoff: ``docs/plans/phase-artifacts/2026-05-04-m1-clean-run-blockers-handoff.md`` §B1.

Both watchdogs (``_WaveWatchdogState.record_progress`` in wave_executor.py and
``_OrphanWatchdog.record_start`` in codex_appserver.py) used to insert into
``pending_tool_starts`` unconditionally, indexed by Codex item id. Codex emits
``item.started type=reasoning id=rs_<hash>`` which produced
``tool_name="reasoning"`` and a tool_id, polluting the dict. Reasoning items
do not reliably emit ``item.completed``, so the entries persisted and the
tier-2 orphan-tool watchdog (default 400s) eventually fired on a non-tool
item — killing the wave on a watchdog that had nothing real to wait on.

The allowlist gates BOTH insert sites on ``tool_name == "commandExecution"``.
Future-safe (new item types default to NOT-orphanable). Reasoning,
agentMessage, userMessage and fileChange are all rejected at insert time;
fileChange is still tracked for tier-3 productive-tool-idle via the separate
``last_file_mutation_monotonic`` refresh at wave_executor.py:701-706.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_team_v15 import wave_executor
from agent_team_v15.codex_appserver import _OrphanWatchdog
from agent_team_v15.wave_executor import _WaveWatchdogState


# ---------------------------------------------------------------------------
# Test 1 — wave_executor: record_progress rejects reasoning
# ---------------------------------------------------------------------------


def test_wave_state_record_progress_rejects_reasoning() -> None:
    state = _WaveWatchdogState()
    state.record_progress(
        message_type="item.started",
        tool_name="reasoning",
        tool_id="rs_x",
        event_kind="start",
    )
    assert state.pending_tool_starts == {}, (
        "reasoning items must NOT enter pending_tool_starts via "
        "_WaveWatchdogState.record_progress"
    )


# ---------------------------------------------------------------------------
# Test 2 — codex_appserver: _OrphanWatchdog.record_start rejects reasoning
# ---------------------------------------------------------------------------


def test_orphan_watchdog_record_start_rejects_reasoning() -> None:
    watchdog = _OrphanWatchdog()
    watchdog.record_start(item_id="rs_x", tool_name="reasoning")
    assert watchdog.pending_tool_starts == {}, (
        "reasoning items must NOT enter pending_tool_starts via "
        "_OrphanWatchdog.record_start"
    )


# ---------------------------------------------------------------------------
# Test 3 — both sites reject the other non-commandExecution tool kinds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", ["agentMessage", "userMessage", "fileChange"])
def test_wave_state_record_progress_rejects_other_non_command_kinds(
    tool_name: str,
) -> None:
    state = _WaveWatchdogState()
    state.record_progress(
        message_type="item.started",
        tool_name=tool_name,
        tool_id=f"id_{tool_name}",
        event_kind="start",
    )
    assert state.pending_tool_starts == {}, (
        f"{tool_name} must NOT enter pending_tool_starts via "
        "_WaveWatchdogState.record_progress"
    )


@pytest.mark.parametrize("tool_name", ["agentMessage", "userMessage", "fileChange"])
def test_orphan_watchdog_record_start_rejects_other_non_command_kinds(
    tool_name: str,
) -> None:
    watchdog = _OrphanWatchdog()
    watchdog.record_start(item_id=f"id_{tool_name}", tool_name=tool_name)
    assert watchdog.pending_tool_starts == {}, (
        f"{tool_name} must NOT enter pending_tool_starts via "
        "_OrphanWatchdog.record_start"
    )


# ---------------------------------------------------------------------------
# Test 4 — both sites admit commandExecution
# ---------------------------------------------------------------------------


def test_wave_state_record_progress_admits_commandexecution() -> None:
    state = _WaveWatchdogState()
    state.record_progress(
        message_type="item.started",
        tool_name="commandExecution",
        tool_id="ce_b",
        event_kind="start",
    )
    assert "ce_b" in state.pending_tool_starts, (
        "commandExecution items MUST be tracked in pending_tool_starts via "
        "_WaveWatchdogState.record_progress"
    )
    assert state.pending_tool_starts["ce_b"]["tool_name"] == "commandExecution"


def test_orphan_watchdog_record_start_admits_commandexecution() -> None:
    watchdog = _OrphanWatchdog()
    watchdog.record_start(
        item_id="ce_b",
        tool_name="commandExecution",
        command_summary="echo hello",
    )
    assert "ce_b" in watchdog.pending_tool_starts, (
        "commandExecution items MUST be tracked in pending_tool_starts via "
        "_OrphanWatchdog.record_start"
    )
    assert watchdog.pending_tool_starts["ce_b"]["tool_name"] == "commandExecution"
    assert watchdog.pending_tool_starts["ce_b"]["command_summary"] == "echo hello"


# ---------------------------------------------------------------------------
# Test 5 — behavioural reproduction of the rerun13 wedge
# ---------------------------------------------------------------------------


def _config_400s_tier2() -> object:
    """Mirror tests/test_orphan_aware_failfast.py:_config — minimal namespace
    with the two attributes _build_wave_watchdog_timeout reads from v18."""
    import types

    return types.SimpleNamespace(
        v18=types.SimpleNamespace(
            wave_idle_timeout_seconds=1800,
            orphan_tool_idle_timeout_seconds=400,
        )
    )


def test_behavioural_reasoning_then_command_execution_no_tier2_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduces the rerun13 sequence: reasoning starts mid-turn (id=rs_a),
    then a real commandExecution (id=ce_b) starts and completes, then the
    turn pivots without emitting ``item.completed`` for rs_a. After 410s
    of idle (past the 400s tier-2 threshold), the watchdog must NOT fire —
    pending_tool_starts is empty (commandExecution popped on completion,
    reasoning never inserted).

    Pre-fix behaviour: reasoning entry remained in pending_tool_starts and
    tier-2 fired on it, killing the wave on a non-orphanable item.
    """
    state = _WaveWatchdogState()

    # Anchor monotonic at 0 so subsequent calls produce predictable ages.
    monkeypatch.setattr(wave_executor.time, "monotonic", lambda: 0.0)
    state.last_progress_monotonic = 0.0

    # 1. Codex emits item.started type=reasoning id=rs_a.
    state.record_progress(
        message_type="item.started",
        tool_name="reasoning",
        tool_id="rs_a",
        event_kind="start",
    )
    assert "rs_a" not in state.pending_tool_starts, (
        "reasoning leaked into pending_tool_starts"
    )

    # 2. Codex emits item.started type=commandExecution id=ce_b.
    state.record_progress(
        message_type="item.started",
        tool_name="commandExecution",
        tool_id="ce_b",
        event_kind="start",
    )
    assert "ce_b" in state.pending_tool_starts

    # 3. Codex emits item.completed for ce_b.
    state.record_progress(
        message_type="item.completed",
        tool_name="commandExecution",
        tool_id="ce_b",
        event_kind="complete",
    )
    assert "ce_b" not in state.pending_tool_starts

    # 4. No further completes. Advance to 410s (past the 400s tier-2
    # threshold) and check the watchdog. Pre-fix: tier-2 fires on rs_a.
    # Post-fix: pending_tool_starts is empty so no tier-2 path can fire.
    monkeypatch.setattr(wave_executor.time, "monotonic", lambda: 410.0)
    timeout = wave_executor._build_wave_watchdog_timeout(
        wave_letter="B",
        state=state,
        config=_config_400s_tier2(),
    )
    assert state.pending_tool_starts == {}, (
        "rerun13 wedge — pending_tool_starts must be empty after a clean "
        "commandExecution lifecycle and a stranded reasoning start"
    )
    assert timeout is None, (
        "tier-2 fired despite an empty pending_tool_starts; would kill the "
        "wave on a non-existent orphan tool (rerun13 bug)"
    )


# ---------------------------------------------------------------------------
# Test 6 — static-source lint: only two insertion sites in src/agent_team_v15
# ---------------------------------------------------------------------------


def test_static_lint_only_two_sites_insert_into_pending_tool_starts() -> None:
    """Locks the inventory of pending_tool_starts insertion sites at TWO:

    1. ``src/agent_team_v15/wave_executor.py`` — _WaveWatchdogState.record_progress
    2. ``src/agent_team_v15/codex_appserver.py`` — _OrphanWatchdog.record_start

    Any future call site that inserts into ``pending_tool_starts`` MUST also
    apply the commandExecution allowlist (handoff §B1 missed-angle A1
    forbids partial fixes). This static-source lint catches the regression
    by counting raw assignments across the package.

    A failure here means: either (a) a new insertion site appeared and
    needs gating, or (b) one of the two known sites was renamed/removed
    and this lint needs updating.
    """
    src_root = Path(wave_executor.__file__).resolve().parent
    insert_pattern = re.compile(r"pending_tool_starts\[[^\]]+\]\s*=")

    matches: list[tuple[Path, int, str]] = []
    for py_path in sorted(src_root.glob("*.py")):
        text = py_path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if insert_pattern.search(line):
                matches.append((py_path, lineno, line.strip()))

    rendered = "\n".join(f"  {p.name}:{ln}: {snippet}" for p, ln, snippet in matches)
    assert len(matches) == 2, (
        "expected exactly TWO pending_tool_starts insertion sites "
        "(_WaveWatchdogState.record_progress + _OrphanWatchdog.record_start); "
        f"found {len(matches)}:\n{rendered}\n"
        "Any new insertion site MUST be gated on tool_name == 'commandExecution' "
        "per handoff §B1 — see this test's docstring."
    )

    file_names = {p.name for p, _, _ in matches}
    assert file_names == {"wave_executor.py", "codex_appserver.py"}, (
        f"insertion sites must live in wave_executor.py + codex_appserver.py; "
        f"found in: {sorted(file_names)}"
    )


# ---------------------------------------------------------------------------
# Test 7 — round-4 regression: gate must read the parameter, not cached state
# ---------------------------------------------------------------------------


def test_record_progress_gate_reads_parameter_not_cached_last_tool_name() -> None:
    """Round-4 regression: the allowlist gate MUST consult the current
    event's ``tool_name`` parameter, not ``self.last_tool_name`` (which
    holds the PRIOR event's tool name when this event has an empty
    ``tool_name`` argument).

    Pre-fix: gate read ``self.last_tool_name``. With this sequence —

      1. ``record_progress(tool_name="commandExecution", tool_id="ce_1",
         event_kind="start")``  → last_tool_name = "commandExecution",
         pending_tool_starts["ce_1"] inserted (correct)
      2. ``record_progress(tool_name="", tool_id="rs_2",
         event_kind="start")``  → tool_name is empty so the
         ``if tool_name:`` guard at line 675 skips the
         ``self.last_tool_name = ...`` assignment; last_tool_name STAYS
         "commandExecution" from event 1; gate passes; pending["rs_2"]
         inserted on a non-commandExecution event (BUG)

    Post-fix: gate reads the parameter directly. Event 2's empty
    ``tool_name`` fails the equality check so pending["rs_2"] is NOT
    inserted, regardless of what state event 1 left behind.
    """
    state = _WaveWatchdogState()

    # Event 1 — real commandExecution. Must register.
    state.record_progress(
        message_type="item.started",
        tool_name="commandExecution",
        tool_id="ce_1",
        event_kind="start",
    )
    assert "ce_1" in state.pending_tool_starts
    assert state.last_tool_name == "commandExecution", (
        "preconditions: event 1 must populate last_tool_name with the "
        "stale value the gate could mistakenly read for event 2"
    )

    # Event 2 — empty tool_name (e.g., a Codex transport event without a
    # resolved item.name/type/tool_name; or a Claude SDK progress tick).
    # last_tool_name remains "commandExecution" from event 1. Pre-fix,
    # this leaks rs_2 into pending_tool_starts.
    state.record_progress(
        message_type="item.started",
        tool_name="",
        tool_id="rs_2",
        event_kind="start",
    )
    assert "rs_2" not in state.pending_tool_starts, (
        "round-4 regression: gate consulted stale last_tool_name "
        "instead of the current event's tool_name parameter; rs_2 leaked "
        "into pending_tool_starts on an empty-tool_name event"
    )

    # Event 3 — explicit non-commandExecution tool_name. Same shape — must
    # NOT leak even when last_tool_name is still "commandExecution".
    state.record_progress(
        message_type="item.started",
        tool_name="reasoning",
        tool_id="rs_3",
        event_kind="start",
    )
    assert "rs_3" not in state.pending_tool_starts, (
        "round-4 regression: gate must reject explicit non-command tool_name "
        "even when last_tool_name from a prior event was 'commandExecution'"
    )

    # Sanity: the only entry in pending_tool_starts is the genuine ce_1
    # from event 1, untouched by events 2 + 3.
    assert set(state.pending_tool_starts.keys()) == {"ce_1"}
