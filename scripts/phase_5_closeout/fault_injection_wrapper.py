"""Stage 2A fault-injection wrapper around ``agent_team_v15.cli.main()``.

Operator-facing entry-point that monkey-patches ``wave_executor._invoke``
to call :func:`scripts.phase_5_closeout.fault_injection.maybe_inject_delay`
BEFORE invoking the real callable. Injection state is configured via
environment variables so the bash launcher template can stay text-only.

This is the "operator's smoke wrapper" referenced in
``scripts/phase_5_closeout/fault_injection.py``'s module docstring. The
fault-injection helpers themselves stay default-off; this wrapper is
the explicit arming surface.

**Usage from the bash launcher template:**

.. code-block:: bash

    # Stage 2A.i — bootstrap-wedge respawn (one-shot Wave A delay):
    PHASE5_INJECT_MODE=first-call \\
    PHASE5_INJECT_ROLE=wave \\
    PHASE5_INJECT_WAVE=A \\
    PHASE5_INJECT_DELAY=70.0 \\
        python -m scripts.phase_5_closeout.fault_injection_wrapper \\
            --prd "${PRD_PATH}" \\
            --config "${CONFIG_PATH}" \\
            --depth exhaustive \\
            --cwd "${RUN_DIR}" \\
            --milestone-cost-cap-usd 20 \\
            --cumulative-wedge-cap 10

    # Stage 2A.ii — cumulative-cap halt (persistent every-dispatch delay
    # + tightened cap):
    PHASE5_INJECT_MODE=every \\
    PHASE5_INJECT_DELAY=70.0 \\
        python -m scripts.phase_5_closeout.fault_injection_wrapper \\
            --prd "${PRD_PATH}" \\
            --config "${CONFIG_PATH}" \\
            --depth exhaustive \\
            --cwd "${RUN_DIR}" \\
            --milestone-cost-cap-usd 20 \\
            --cumulative-wedge-cap 2

    # Phase 5 closeout Stage 2 §O.4.6 — productive-tool-idle wedge live:
    # one-shot delay AFTER the first item/completed commandExecution
    # reaches the wave_executor. 1230s = 1200s tier-3 threshold + 30s
    # margin. NO PHASE5_INJECT_MODE here (the post-cmdexec injection is
    # independent — composes with no-op SDK-callback path).
    PHASE5_INJECT_AFTER_CMDEXEC_DELAY=1230 \\
        python -m scripts.phase_5_closeout.fault_injection_wrapper \\
            --prd "${PRD_PATH}" \\
            --config "${CONFIG_PATH}" \\
            --depth exhaustive \\
            --cwd "${RUN_DIR}" \\
            --milestone-cost-cap-usd 20 \\
            --cumulative-wedge-cap 10

Env-var contract (all optional, but at least one of
``PHASE5_INJECT_MODE`` / ``PHASE5_INJECT_AFTER_CMDEXEC_DELAY`` is
required for the wrapper to do anything):

* ``PHASE5_INJECT_MODE`` — ``first-call`` (one-shot, self-disarms after
  first match) or ``every`` (persistent until process exit). Drives
  the SDK-callback injection (O.4.5 / O.4.7 / O.4.8 / O.4.9 / O.4.11).
* ``PHASE5_INJECT_ROLE`` — match filter for the dispatch's ``role``
  kwarg (e.g. ``wave``, ``compile_fix``, ``audit_fix``, ``audit``);
  empty string matches any role.
* ``PHASE5_INJECT_WAVE`` — match filter for the dispatch's ``wave``
  kwarg (e.g. ``A``, ``B``, ``C``, ``D``, ``E``, ``T``); empty string
  matches any wave letter.
* ``PHASE5_INJECT_DELAY`` — seconds to hold the SDK callback before
  invoking the real callable. Default 70.0 (10s above Phase 5.7's
  ``bootstrap_idle_timeout_seconds=60``).

* ``PHASE5_INJECT_AFTER_CMDEXEC_DELAY`` — seconds to sleep AFTER the
  first ``item/completed commandExecution`` event has been delivered
  to the wave_executor's ``_WaveWatchdogState.record_progress``. Drives
  Phase 5.7 tier-3 productive-tool-idle wedge live (Phase 5 closeout
  Stage 2 §O.4.6). One-shot self-disarming. Set to ``1230`` to fire
  tier 3 (1200s default) within the productive-tool-idle window with
  a 30s margin. Default-off — unset = pass-through. Hooks
  ``codex_appserver._emit_progress`` AFTER the original delivers the
  event, so ``pending_tool_starts`` is empty + ``last_tool_call_monotonic``
  refreshed + ``last_productive_tool_name="commandExecution"`` BEFORE
  the delay starts; tier 2 (orphan-tool) cannot fire because pending
  is empty post-event.

When neither ``PHASE5_INJECT_MODE`` nor
``PHASE5_INJECT_AFTER_CMDEXEC_DELAY`` is set, the wrapper falls through
to a plain ``cli.main()`` invocation — useful as a single entry-point
for both injected and non-injected smokes.
"""

from __future__ import annotations

import os
import sys

# Patch wave_executor BEFORE importing cli so the patched _invoke is
# what cli's pipeline references at call time. cli imports wave_executor
# at module load, but it goes through wave_executor.<name> lookup at
# call time (not via "from wave_executor import _invoke as ..."), so a
# late patch on the wave_executor module attribute is sufficient.
from agent_team_v15 import wave_executor  # noqa: E402
from agent_team_v15 import codex_appserver  # noqa: E402

from scripts.phase_5_closeout import fault_injection  # noqa: E402


_original_invoke = wave_executor._invoke
_original_emit_progress = codex_appserver._emit_progress
_original_process_streaming_event = codex_appserver._process_streaming_event
_original_next_notification = codex_appserver._CodexAppServerClient.next_notification


# A1b — side channel between _process_streaming_event (sync — observes
# the live ``item/completed commandExecution`` notification) and
# next_notification (async — awaits the post-cmdexec delay). The flag is
# set after the original sync ``_process_streaming_event`` has delivered
# the event to wave_executor's ``_WaveWatchdogState.record_progress``
# (which clears ``pending_tool_starts`` + refreshes
# ``last_tool_call_monotonic`` + sets
# ``last_productive_tool_name="commandExecution"``). The flag is consumed
# on the NEXT ``await client.next_notification()``, which awaits
# :func:`fault_injection.maybe_inject_post_cmdexec_delay` BEFORE returning
# the next real notification — stalling the codex_appserver drain loop
# while the wave_executor's watchdog poll loop runs concurrently and fires
# tier-3 productive-tool-idle within the configured window.
class _PendingCmdexecDelayState:
    """Single-flag side channel for the live-path injection."""

    pending: bool = False


_PENDING_CMDEXEC_DELAY = _PendingCmdexecDelayState()


async def _injected_invoke(func, **kwargs):
    """Wrap ``wave_executor._invoke`` with a maybe_inject_delay hook.

    Reads ``role`` + ``wave`` from kwargs (the central pinch-point's
    convention), gives :func:`maybe_inject_delay` first crack, then
    delegates to the original. When no injection is armed, the hook is
    a synchronous-cost no-op (one ``if not _INJECTION.armed: return``).
    """

    role = str(kwargs.get("role", "") or "")
    # ``_invoke``'s convention: caller passes ``wave="<letter>"``;
    # accept ``wave_letter=`` as a fallback for future-proofing.
    wave_letter = str(kwargs.get("wave", "") or kwargs.get("wave_letter", "") or "")
    await fault_injection.maybe_inject_delay(role=role, wave_letter=wave_letter)
    return await _original_invoke(func, **kwargs)


def _injected_process_streaming_event(
    event,
    watchdog,
    tokens,
    progress_callback,
    messages=None,
    capture_session=None,
):
    """A1b — wrap codex_appserver's sync ``_process_streaming_event`` to flag
    completed-commandExecution events for the next-notification delay hook.

    Order is load-bearing:

    1. Call the original sync ``_process_streaming_event`` first. The
       original fires ``_fire_progress_sync`` for ``item/started`` /
       ``item/completed`` / ``item/agentMessage/delta`` notifications,
       which dispatches to the progress_callback (wave_executor's
       ``_WaveWatchdogState.record_progress``). For
       ``item/completed commandExecution`` the wave_executor state is
       updated BEFORE step 2: ``last_tool_call_monotonic`` refreshed,
       ``last_productive_tool_name="commandExecution"``,
       ``tool_call_event_count += 1``, ``pending_tool_starts[id]``
       removed.
    2. Inspect the event payload. If the post-cmdexec injection is armed
       AND the event was an ``item/completed commandExecution``, set
       :data:`_PENDING_CMDEXEC_DELAY.pending = True`. The flag is consumed
       on the next ``await client.next_notification()`` call — which
       awaits :func:`fault_injection.maybe_inject_post_cmdexec_delay`
       BEFORE returning the next real notification, stalling the drain
       loop.

    Default-off: when no injection is armed, this wrapper is a thin
    pass-through that adds one boolean check.
    """

    _original_process_streaming_event(
        event, watchdog, tokens, progress_callback, messages, capture_session,
    )
    if not fault_injection._POST_CMDEXEC_INJECTION.armed:
        return
    method = ""
    params: dict = {}
    if isinstance(event, dict):
        method = str(event.get("method", "") or "")
        raw_params = event.get("params", {})
        if isinstance(raw_params, dict):
            params = raw_params
    if method not in ("item/completed", "item.completed"):
        return
    item = params.get("item", {}) if isinstance(params, dict) else {}
    tool_name = ""
    if isinstance(item, dict):
        tool_name = str(
            item.get("name") or item.get("tool") or item.get("type") or ""
        )
    if tool_name != "commandExecution":
        return
    _PENDING_CMDEXEC_DELAY.pending = True


async def _injected_next_notification(self):
    """A1b — wrap ``_CodexAppServerClient.next_notification`` to inject the
    post-cmdexec delay BEFORE awaiting the next real notification.

    When :data:`_PENDING_CMDEXEC_DELAY.pending` is True (flag set by a prior
    :func:`_injected_process_streaming_event` on an
    ``item/completed commandExecution``), awaits
    :func:`fault_injection.maybe_inject_post_cmdexec_delay` (which sleeps
    the configured ``delay_seconds`` + self-disarms the one-shot
    injection), resets the flag, and only then delegates to the original
    ``next_notification``. This stalls the codex_appserver drain loop
    while the wave_executor's separate poll-task continues running, so
    tier-3 productive-tool-idle (1200s default) fires inside the
    1230s sleep window.

    The hook fires regardless of whether the delivered event was the
    same item/completed commandExecution — the delay arms on the
    side-channel flag, not on the next notification's content.
    """

    if _PENDING_CMDEXEC_DELAY.pending:
        _PENDING_CMDEXEC_DELAY.pending = False
        # Forward to the central injection hook with the canonical match
        # signature so the existing fault_injection filter logic + log
        # emission still apply (`[FAULT-INJECTION-POST-CMDEXEC] holding…`).
        await fault_injection.maybe_inject_post_cmdexec_delay(
            message_type="item/completed",
            tool_name="commandExecution",
            event_kind="complete",
        )
    return await _original_next_notification(self)


async def _injected_emit_progress(
    progress_callback,
    *,
    message_type: str,
    tool_name: str = "",
    tool_id: str = "",
    event_kind: str = "other",
) -> None:
    """Phase 5 closeout Stage 2 §O.4.6 closure hook — wrap codex_appserver's
    progress emitter to inject a post-commandExecution stall.

    Order is load-bearing:

    1. Call the original ``_emit_progress`` first so the event reaches the
       wave_executor's ``_WaveWatchdogState.record_progress`` BEFORE the
       injected sleep. For ``item/completed commandExecution``, the
       original updates ``last_tool_call_monotonic`` (refreshed),
       ``last_productive_tool_name="commandExecution"``,
       ``tool_call_event_count += 1``, and clears the pending entry from
       ``pending_tool_starts``.
    2. Then call :func:`maybe_inject_post_cmdexec_delay`. When armed AND
       the event matches the narrow filter, sleeps the configured delay
       so the wave_executor's tier-3 productive-tool-idle predicate
       (1200s default) fires deterministically within the
       productive-tool-idle window — pending_tool_starts is empty
       (cleared in step 1), bootstrap_cleared True, last_tool_call > 0,
       so tier 3 is fire-eligible. Tier 2 (orphan-tool) cannot fire
       because pending is empty after step 1.

    Default-off: when ``PHASE5_INJECT_AFTER_CMDEXEC_DELAY`` is unset,
    :func:`maybe_inject_post_cmdexec_delay` is a synchronous-cost no-op
    (one ``if not _POST_CMDEXEC_INJECTION.armed: return``).
    """

    await _original_emit_progress(
        progress_callback,
        message_type=message_type,
        tool_name=tool_name,
        tool_id=tool_id,
        event_kind=event_kind,
    )
    await fault_injection.maybe_inject_post_cmdexec_delay(
        message_type=message_type,
        tool_name=tool_name,
        event_kind=event_kind,
    )


def _arm_from_env() -> bool:
    """Read PHASE5_INJECT_* env vars and arm the injection state.

    Returns True iff an injection was armed. Returns False (silently)
    when ``PHASE5_INJECT_MODE`` is unset — pass-through case.
    """

    mode = os.environ.get("PHASE5_INJECT_MODE", "").strip().lower()
    if not mode:
        return False
    if mode not in {"first-call", "every"}:
        raise SystemExit(
            f"PHASE5_INJECT_MODE must be 'first-call' or 'every'; got {mode!r}"
        )
    role = os.environ.get("PHASE5_INJECT_ROLE", "").strip()
    wave = os.environ.get("PHASE5_INJECT_WAVE", "").strip()
    try:
        delay = float(os.environ.get("PHASE5_INJECT_DELAY", "70.0"))
    except ValueError as exc:
        raise SystemExit(
            f"PHASE5_INJECT_DELAY must be a float; got "
            f"{os.environ.get('PHASE5_INJECT_DELAY')!r}: {exc}"
        ) from exc
    if delay < 0:
        raise SystemExit(f"PHASE5_INJECT_DELAY must be non-negative; got {delay}")

    # Arm directly. Single-arm is enforced by fault_injection's own
    # state machine (re-arm raises RuntimeError); but we're at process
    # boot, so this is always the first arm.
    if fault_injection._INJECTION.armed:
        raise SystemExit(
            "fault_injection already armed at wrapper entry — refusing to "
            "stack injections. Restart the process to clear state."
        )
    fault_injection._INJECTION.armed = True
    fault_injection._INJECTION.role = role
    fault_injection._INJECTION.wave_letter = wave
    fault_injection._INJECTION.delay_seconds = delay
    fault_injection._INJECTION.persistent = (mode == "every")
    fault_injection._INJECTION.matched_count = 0

    print(
        f"[FAULT-INJECTION-WRAPPER] armed mode={mode} role={role or '*'} "
        f"wave={wave or '*'} delay={delay}s persistent="
        f"{fault_injection._INJECTION.persistent}",
        file=sys.stderr,
        flush=True,
    )
    return True


def _arm_post_cmdexec_from_env() -> bool:
    """Read ``PHASE5_INJECT_AFTER_CMDEXEC_DELAY`` and arm the post-cmdexec
    injection.

    Phase 5 closeout Stage 2 §O.4.6 closure helper. Default-off; arm only
    when the env var is set to a positive float. Drives Phase 5.7 tier-3
    productive-tool-idle wedge live: the wrapper monkey-patches
    ``codex_appserver._emit_progress`` (already done at module import
    time), and ``maybe_inject_post_cmdexec_delay`` fires after the first
    ``item/completed commandExecution`` reaches the wave_executor.

    One-shot semantics by default — self-disarms after the first match —
    so the smoke produces a single deterministic tier-3 fire and
    subsequent events flow normally. Composes with the existing
    ``PHASE5_INJECT_MODE`` injection (the two states are independent;
    operators can arm both for combined exercises, but typical §O.4.6
    smokes use only this one).

    Returns True iff armed.
    """

    raw = os.environ.get("PHASE5_INJECT_AFTER_CMDEXEC_DELAY", "").strip()
    if not raw:
        return False
    try:
        delay = float(raw)
    except ValueError as exc:
        raise SystemExit(
            f"PHASE5_INJECT_AFTER_CMDEXEC_DELAY must be a float; got "
            f"{raw!r}: {exc}"
        ) from exc
    if delay <= 0:
        raise SystemExit(
            f"PHASE5_INJECT_AFTER_CMDEXEC_DELAY must be positive (>0); got {delay}"
        )

    if fault_injection._POST_CMDEXEC_INJECTION.armed:
        raise SystemExit(
            "fault_injection post-cmdexec injection already armed at wrapper "
            "entry — refusing to stack. Restart the process to clear state."
        )
    fault_injection._POST_CMDEXEC_INJECTION.armed = True
    fault_injection._POST_CMDEXEC_INJECTION.delay_seconds = delay
    fault_injection._POST_CMDEXEC_INJECTION.persistent = False
    fault_injection._POST_CMDEXEC_INJECTION.matched_count = 0

    print(
        f"[FAULT-INJECTION-WRAPPER] post-cmdexec armed delay={delay}s "
        f"(one-shot; fires after first item/completed commandExecution)",
        file=sys.stderr,
        flush=True,
    )
    return True


def main() -> None:
    """Wrapper entry-point. Arms (if env says so), patches, runs cli.main()."""

    armed = _arm_from_env()
    post_cmdexec_armed = _arm_post_cmdexec_from_env()
    if post_cmdexec_armed:
        # A1b — patch the LIVE event path so completed-commandExecution
        # notifications stall the drain loop AFTER the wave_executor's
        # ``_WaveWatchdogState.record_progress`` has updated state. The
        # live path is ``_process_streaming_event`` (sync — flag-setter)
        # + ``_CodexAppServerClient.next_notification`` (async —
        # delay-injector). The legacy ``_emit_progress`` patch is
        # retained as a defensive belt-and-suspenders — in practice
        # ``item/completed`` events do NOT flow through ``_emit_progress``
        # (that path is for ``turn/started`` and similar non-streaming
        # notifications), so the legacy hook never fires for the
        # post-cmdexec injection on the live path.
        codex_appserver._emit_progress = _injected_emit_progress
        codex_appserver._process_streaming_event = _injected_process_streaming_event
        codex_appserver._CodexAppServerClient.next_notification = _injected_next_notification
    if armed:
        # Apply the monkey-patch only when armed. Non-injected smokes
        # take the unpatched fast-path.
        wave_executor._invoke = _injected_invoke

    # Hand off to the real CLI. argv is unmodified — operator passes
    # only agent-team-v15 args (the wrapper has zero CLI args of its
    # own; everything is env-driven).
    from agent_team_v15 import cli  # noqa: E402

    cli.main()


if __name__ == "__main__":
    main()
