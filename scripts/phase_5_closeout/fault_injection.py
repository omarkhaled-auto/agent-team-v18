"""Stage 2A fault-injection harness for Phase 5.7 closeout rows.

**DEFAULT OFF.** Importing this module is a no-op on production code
paths. Each helper is invoked explicitly by the operator's smoke
wrapper; no helper runs unless armed.

Closure rows from ``docs/plans/2026-04-28-phase-5-quality-milestone.md`` §O.4:

* **O.4.5 / O.4.7 / O.4.9 / O.4.11** — bootstrap-wedge respawn observed
  on a real Claude SDK dispatch. Live injection required (the operator
  wraps the smoke command with the relevant context manager). Helpers:

  * :func:`arm_first_call_delay` — async context manager that holds
    the next SDK callback's first invocation for *delay_seconds* on
    the matched (role, wave_letter) dispatch.
  * :func:`arm_pipe_pause_on_every_dispatch` — like above but applies
    to every dispatch until disarmed (drives O.4.8 cumulative cap).

* **O.4.6** — productive-tool-idle fires at 1200s on M3 replay. The
  fixture-replay variant in :func:`replay_m3_productive_tool_idle_fixture`
  walks the m1-hardening-smoke-20260428-112339 BUILD_LOG event sequence
  through the watchdog state machine and reports the predicted
  timeout_kind + fire-time. **REHEARSAL EVIDENCE ONLY** per the Phase 5
  closeout-smoke plan approver constraint #3 — does NOT close O.4.6.
  Live M3 smoke OR injected M1 stalled-commandExecution dispatch
  required for actual closure.

* **O.4.8** — cumulative-cap halt with
  ``failure_reason=sdk_pipe_environment_unstable`` + EXIT 2.
  Composes :func:`arm_pipe_pause_on_every_dispatch` + the production
  ``--cumulative-wedge-cap N`` CLI flag (default Phase 5.7 wiring).

* **O.4.10** — provider-routed Codex paths do NOT increment
  ``_cumulative_wedge_budget``. Post-hoc analyzer
  :func:`analyze_run_dir_cumulative_wedge_budget` reads the run-dir's
  STATE.json + hang_reports and asserts the invariant.

Operator wiring pattern (Stage 2A.i bootstrap-wedge respawn smoke):

.. code-block:: python

    import asyncio
    from scripts.phase_5_closeout.fault_injection import arm_first_call_delay
    # ... operator smoke entry-point that calls into the production CLI ...

    async def run_smoke():
        async with arm_first_call_delay(role="wave", wave_letter="A", delay_seconds=70.0):
            # invoke the production smoke runner; the first Wave-A SDK
            # callback will be held for 70s, tripping the 60s
            # bootstrap-watchdog deadline.
            await production_smoke_runner.run(...)

    asyncio.run(run_smoke())

The harness intentionally does NOT include a smoke-runner. Operators
plumb these helpers into their own wrapper scripts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live-injection state — explicit module globals; only set when armed
# ---------------------------------------------------------------------------


@dataclass
class _InjectionState:
    """Holds armed-injection metadata. ``armed=False`` is the default."""

    armed: bool = False
    role: str = ""  # "" matches any role
    wave_letter: str = ""  # "" matches any wave
    delay_seconds: float = 0.0
    persistent: bool = False  # False = first-match-only; True = every match
    matched_count: int = 0


_INJECTION = _InjectionState()


def _injection_matches(*, role: str, wave_letter: str) -> bool:
    """Return True if the armed injection matches this dispatch.

    Empty string matches any value. ``persistent=False`` injections
    self-disarm after first match.
    """

    if not _INJECTION.armed:
        return False
    if _INJECTION.role and _INJECTION.role != role:
        return False
    if _INJECTION.wave_letter and _INJECTION.wave_letter != wave_letter:
        return False
    return True


async def maybe_inject_delay(
    *,
    role: str = "",
    wave_letter: str = "",
) -> None:
    """Hook the operator's smoke wrapper plumbs into the SDK callback path.

    Default-off: when no injection is armed, this is an immediate
    awaitable returning ``None``. When armed and the (role, wave_letter)
    matches, sleeps for the configured delay before returning.

    Operator wiring example: in the smoke wrapper, replace the SDK
    callback with one that calls ``await maybe_inject_delay(role=...,
    wave_letter=...)`` before invoking the real callback.
    """

    if not _injection_matches(role=role, wave_letter=wave_letter):
        return
    delay = _INJECTION.delay_seconds
    _INJECTION.matched_count += 1
    _logger.warning(
        "[FAULT-INJECTION] holding %s/%s SDK callback for %.1fs (match #%d)",
        role or "*", wave_letter or "*", delay, _INJECTION.matched_count,
    )
    if not _INJECTION.persistent:
        _INJECTION.armed = False
    await asyncio.sleep(delay)


@contextlib.asynccontextmanager
async def arm_first_call_delay(
    *,
    role: str = "",
    wave_letter: str = "",
    delay_seconds: float = 70.0,
) -> AsyncIterator[None]:
    """Async context manager — arm a one-shot first-call delay injection.

    Default delay 70s exceeds Phase 5.7's ``bootstrap_idle_timeout_seconds=60``
    by a 10s margin so the bootstrap watchdog deterministically fires.

    Closes O.4.5 / O.4.7 / O.4.9 / O.4.11 when the operator wraps a real
    smoke around this context manager.
    """

    if _INJECTION.armed:
        raise RuntimeError(
            "Phase 5.7 fault-injection: an injection is already armed; "
            "disarm before re-arming. (Concurrent injections are not "
            "supported — each closure row needs its own clean smoke.)"
        )
    _INJECTION.armed = True
    _INJECTION.role = role
    _INJECTION.wave_letter = wave_letter
    _INJECTION.delay_seconds = float(delay_seconds)
    _INJECTION.persistent = False
    _INJECTION.matched_count = 0
    try:
        yield
    finally:
        _INJECTION.armed = False
        _INJECTION.role = ""
        _INJECTION.wave_letter = ""
        _INJECTION.delay_seconds = 0.0
        _INJECTION.persistent = False


@contextlib.asynccontextmanager
async def arm_pipe_pause_on_every_dispatch(
    *,
    delay_seconds: float = 70.0,
) -> AsyncIterator[None]:
    """Async context manager — arm a persistent every-dispatch delay.

    Composed with the production ``--cumulative-wedge-cap N`` flag,
    this drives the cumulative-cap halt smoke (O.4.8). Cap reached on
    the Nth dispatch → STATE.json shows
    ``failure_reason=sdk_pipe_environment_unstable`` + EXIT 2.
    """

    if _INJECTION.armed:
        raise RuntimeError(
            "Phase 5.7 fault-injection: an injection is already armed; "
            "disarm before re-arming."
        )
    _INJECTION.armed = True
    _INJECTION.role = ""
    _INJECTION.wave_letter = ""
    _INJECTION.delay_seconds = float(delay_seconds)
    _INJECTION.persistent = True
    _INJECTION.matched_count = 0
    try:
        yield
    finally:
        _INJECTION.armed = False
        _INJECTION.delay_seconds = 0.0
        _INJECTION.persistent = False


def is_armed() -> bool:
    """Return True iff a fault injection is currently armed.

    Used by tests + the smoke wrapper's pre-flight check.
    """

    return _INJECTION.armed


def matched_count() -> int:
    """Return the number of injection matches since the current arm."""

    return _INJECTION.matched_count


# ---------------------------------------------------------------------------
# O.4.6 — productive-tool-idle fixture-replay (REHEARSAL EVIDENCE ONLY)
# ---------------------------------------------------------------------------


@dataclass
class _ReplayOutcome:
    predicted_timeout_kind: str  # "tool-call-idle" | "wave-idle" | "bootstrap" | "none"
    predicted_fire_time_s: float
    last_productive_event_at_s: float
    productive_event_count: int
    fixture_path: Path


def _parse_build_log_event_timeline(
    build_log_text: str,
) -> list[tuple[float, str, str, str]]:
    """Extract (relative_time_s, message_type, tool_name, event_kind) tuples.

    Returns relative seconds from the first event timestamp. Best-effort
    parser — defaults to empty list when the log shape is unparseable.
    """

    import re

    timestamp_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?"
    )
    events: list[tuple[float, str, str, str]] = []
    base_seconds: float | None = None

    def _to_seconds(line: str) -> float | None:
        match = timestamp_re.match(line)
        if not match:
            return None
        _date, hh, mm, ss = match.group(1), match.group(2), match.group(3), match.group(4)
        frac = match.group(5) or "0"
        try:
            seconds_in_day = (
                int(hh) * 3600 + int(mm) * 60 + int(ss) + float("0." + frac)
            )
        except ValueError:
            return None
        return seconds_in_day

    for line in build_log_text.splitlines():
        ts = _to_seconds(line)
        if ts is None:
            continue
        if base_seconds is None:
            base_seconds = ts
        rel = ts - base_seconds
        # Heuristic message_type extraction; mirrors the Phase 5.7
        # _is_productive_tool_event truth table at a coarser level.
        if "commandExecution" in line:
            kind = (
                "complete"
                if ("item/completed" in line or "item.completed" in line)
                else ("start" if ("item/started" in line or "item.started" in line) else "other")
            )
            events.append((rel, "item/started" if kind == "start" else "item/completed" if kind == "complete" else "other", "commandExecution", kind))
        elif "agentMessage" in line:
            events.append((rel, "item/started", "agentMessage", "start"))
        elif "tool_use" in line:
            events.append((rel, "tool_use", "", "start"))
        elif "tool_result" in line:
            events.append((rel, "tool_result", "", "complete"))
    return events


def replay_m3_productive_tool_idle_fixture(
    fixture_path: Path,
    *,
    tool_call_idle_timeout_seconds: int = 1200,
) -> _ReplayOutcome:
    """Offline replay against m1-hardening-smoke-20260428-112339 BUILD_LOG.

    Walks the event sequence through a simplified watchdog state
    machine (mirrors Phase 5.7's tier 3 productive-tool-idle predicate).
    Returns the predicted ``timeout_kind`` and fire-time so operators
    can verify the fixture would trip the 1200s threshold (vs 5400s
    pre-Phase-5.7).

    REHEARSAL EVIDENCE ONLY — does NOT close O.4.6. Live M3 smoke or
    injected M1 stalled-commandExecution dispatch required for actual
    closure per the closeout-smoke plan.
    """

    if not fixture_path.is_file():
        raise FileNotFoundError(
            f"Fixture not found: {fixture_path}. Expected the BUILD_LOG.txt "
            f"from a prior smoke run-dir (e.g. "
            f"'v18 test runs/m1-hardening-smoke-20260428-112339/BUILD_LOG.txt')."
        )
    text = fixture_path.read_text(encoding="utf-8", errors="replace")
    events = _parse_build_log_event_timeline(text)
    if not events:
        return _ReplayOutcome(
            predicted_timeout_kind="none",
            predicted_fire_time_s=0.0,
            last_productive_event_at_s=0.0,
            productive_event_count=0,
            fixture_path=fixture_path,
        )

    # Replay the simplified tier-3 state machine. Production's check
    # ``state.last_tool_call_monotonic > 0.0`` works in monotonic time;
    # in this offline replay relative time starts at 0.0, so we gate
    # the predicate on ``productive_count > 0`` instead — semantically
    # identical (a productive event has been observed).
    last_productive_at = 0.0
    productive_count = 0
    bootstrap_cleared = False
    for rel, msg_type, tool_name, kind in events:
        is_productive = (
            (msg_type == "tool_use" and kind == "start")
            or (msg_type == "tool_result" and kind == "complete")
            or (
                tool_name == "commandExecution"
                and msg_type in {"item/started", "item/completed"}
                and kind in {"start", "complete"}
            )
        )
        if is_productive:
            last_productive_at = rel
            productive_count += 1
            bootstrap_cleared = True
        if (
            bootstrap_cleared
            and productive_count > 0
            and (rel - last_productive_at) >= tool_call_idle_timeout_seconds
        ):
            return _ReplayOutcome(
                predicted_timeout_kind="tool-call-idle",
                predicted_fire_time_s=rel,
                last_productive_event_at_s=last_productive_at,
                productive_event_count=productive_count,
                fixture_path=fixture_path,
            )

    return _ReplayOutcome(
        predicted_timeout_kind="none",
        predicted_fire_time_s=0.0,
        last_productive_event_at_s=last_productive_at,
        productive_event_count=productive_count,
        fixture_path=fixture_path,
    )


# ---------------------------------------------------------------------------
# O.4.10 — post-hoc analyzer for Codex no-counter invariant
# ---------------------------------------------------------------------------


@dataclass
class _CumulativeWedgeAnalysis:
    cumulative_wedge_budget: int
    bootstrap_hang_reports: list[Path] = field(default_factory=list)
    codex_path_hang_reports: list[Path] = field(default_factory=list)
    invariant_violation: str = ""  # empty when invariant holds

    @property
    def invariant_holds(self) -> bool:
        return not self.invariant_violation


def analyze_run_dir_cumulative_wedge_budget(run_dir: Path) -> _CumulativeWedgeAnalysis:
    """Verify O.4.10: provider-routed Codex paths don't increment counter.

    Reads:

    * ``<run_dir>/.agent-team/STATE.json::_cumulative_wedge_budget``
    * ``<run_dir>/.agent-team/hang_reports/*.json::timeout_kind`` +
      ``payload.role`` + ``payload.provider``

    The O.4.10 invariant (Phase 5.7 §M.M4 + Blocker 2 scoping; plan
    §O.4.10 line 1752) has TWO halves and the analyzer FAILS CLOSED on
    either:

    1. **Provenance overlap.** Any hang report with
       ``provider==codex`` AND ``timeout_kind=="bootstrap"`` is a
       structural violation: Codex paths are bootstrap-EXEMPT per the
       Phase 5.7 ``bootstrap_eligible=False`` kwarg passed at the
       provider-routed dispatch site. A Codex-bootstrap overlap means
       the scoping is broken upstream.

    2. **Strict counter attribution.** Plan §O.4.10 line 1752:
       ``_cumulative_wedge_budget`` tracks Claude-SDK-only wedge
       events. Every Claude-SDK bootstrap-wedge respawn increments
       the counter by 1 and produces a hang report
       (``_write_hang_report`` writes one per wedge). The counter's
       value MUST equal the number of Claude-SDK bootstrap reports.
       Strict check:

       * ``cumulative > len(claude_bootstrap_reports)`` → **violation
         (under-attribution)**: more increments than legitimate
         Claude-SDK origins exist. The extra increment(s) must have
         come from a non-Claude-SDK path — exactly the failure the
         O.4.10 invariant exists to prevent. This includes the
         degenerate case of ``cumulative > 0`` with zero Claude
         reports.
       * ``cumulative == len(claude_bootstrap_reports)`` → holds
         (every increment has a matching Claude-SDK origin).
       * ``cumulative < len(claude_bootstrap_reports)`` → outside
         O.4.10's scope (would suggest the counter is
         under-incrementing — different invariant; surface as
         informational, not a hard violation).

    Returns analysis dict; empty ``invariant_violation`` means BOTH
    halves of the invariant hold.
    """

    state_path = run_dir / ".agent-team" / "STATE.json"
    hang_dir = run_dir / ".agent-team" / "hang_reports"

    cumulative = 0
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            cumulative = int(state.get("_cumulative_wedge_budget", 0) or 0)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError, TypeError):
            cumulative = 0

    bootstrap_reports: list[Path] = []
    codex_reports: list[Path] = []
    if hang_dir.is_dir():
        for path in sorted(hang_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            timeout_kind = str(payload.get("timeout_kind", ""))
            provider = str(payload.get("provider", "")).lower()
            if timeout_kind == "bootstrap":
                bootstrap_reports.append(path)
            if provider == "codex":
                codex_reports.append(path)

    # Half 1: Codex paths producing bootstrap-shaped hang reports is
    # a structural violation (bootstrap_eligible=False scoping).
    codex_bootstrap_overlap = [p for p in codex_reports if p in bootstrap_reports]
    # Half 2: counter attribution. The set of Claude-SDK bootstrap
    # reports is bootstrap reports MINUS Codex overlap.
    claude_bootstrap_reports = [
        p for p in bootstrap_reports if p not in codex_bootstrap_overlap
    ]

    violations: list[str] = []
    if codex_bootstrap_overlap:
        violations.append(
            f"O.4.10 violation (provenance): {len(codex_bootstrap_overlap)} "
            f"hang report(s) have provider=codex AND timeout_kind=bootstrap. "
            f"Codex paths must be bootstrap-EXEMPT per Phase 5.7 §M.M4 + "
            f"Blocker 2 scoping. Inspect: "
            f"{', '.join(str(p) for p in codex_bootstrap_overlap)}"
        )
    if cumulative > len(claude_bootstrap_reports):
        unattributed = cumulative - len(claude_bootstrap_reports)
        violations.append(
            f"O.4.10 violation (attribution): _cumulative_wedge_budget="
            f"{cumulative} exceeds the count of Claude-SDK bootstrap "
            f"hang reports ({len(claude_bootstrap_reports)}); "
            f"{unattributed} increment(s) cannot be attributed to a "
            f"Claude-SDK bootstrap-wedge respawn. Per plan §O.4.10 the "
            f"counter tracks Claude-SDK-only wedge events; extra "
            f"increment(s) must have come from a non-Claude-SDK path "
            f"(typically a Codex dispatch that should have been "
            f"bootstrap-EXEMPT). Fail closed."
        )
    violation = "\n".join(violations)

    return _CumulativeWedgeAnalysis(
        cumulative_wedge_budget=cumulative,
        bootstrap_hang_reports=bootstrap_reports,
        codex_path_hang_reports=codex_reports,
        invariant_violation=violation,
    )
