# Bug #12 Follow-Up: Wave T / SDK Watchdog Bypass

**Status:** superseded and corrected on `bug-12-followup-sdk-streaming-watchdog`

## Original intent

The original 2026-04-14 plan identified two real gaps:

1. Wave T and five SDK-driven fix sub-agents in `wave_executor.py` could hang forever.
2. Several top-level `ClaudeSDKClient` sessions in `cli.py` had no idle-stream watchdog.

Those remain the valid foundations for the follow-up fix.

## What Phase 1 verification changed

Independent verification against `baab6e9`, build-e telemetry, and targeted tests showed that two pieces of the original implementation should **not** be ported to `master`:

1. `wave_total_timeout_seconds` / per-wave wall-clock budget:
   The milestone-level `asyncio.wait_for(timeout=milestone_timeout_seconds * 1.5)` already fires first in the normal A+B+C -> D execution shape, so the per-wave outer timeout was dead weight.
2. `asyncio.wait_for(client.query(prompt), timeout=...)` in `cli.py`:
   `client.query()` submits the request; the stream is consumed later by `_process_response(...)`, so wrapping `query()` does not bound the real hang boundary.

## Corrected implementation shape

The follow-up branch keeps and extends only the pieces that survived verification:

1. Wrap the six audited `wave_executor.py` sub-agent SDK call sites with `_invoke_sdk_sub_agent_with_watchdog(...)`.
2. Add `_run_sdk_session_with_watchdog(...)` in `cli.py` so the idle timeout applies to streamed response consumption, not prompt submission.
3. Fix the milestone timeout log message so it prints the actual `milestone_timeout_seconds * 1.5` value.
4. Add per-wave heartbeat logging so "slow but productive" work is visible without forensic log review.

## Explicit non-goals for this follow-up

1. Do not reintroduce a per-wave total wall-clock timeout.
2. Do not tune Codex reasoning budgets or milestone sizing here.
3. Do not expand this PR into provider-router changes or the next-intl import scanner work.
