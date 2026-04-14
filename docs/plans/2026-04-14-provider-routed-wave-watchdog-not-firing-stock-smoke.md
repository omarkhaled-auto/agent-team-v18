# Provider-Routed Wave Watchdog Not Firing On Stock Smoke

**Date:** 2026-04-14
**Status:** open
**Source run:** `v18 test runs/build-f-pr2-validation-20260414/`
**Branch under test:** `bug-12-followup-sdk-streaming-watchdog`

## Summary

The stock-budget exhaustive smoke run did not clear milestone 1. Wave A
completed successfully, then provider-routed Wave B (Codex) emitted an initial
`command_execution` progress event and wrote backend files for a while, but the
provider-routed wave watchdog never fired even after the wave sat idle far past
`wave_idle_timeout_seconds=1800`.

## Observed facts

- `milestone-1-wave-A.json` landed and Wave A succeeded.
- No `milestone-1-wave-B.json` was written.
- No hang report was written for Wave B.
- `BUILD_LOG.txt` shows the last provider-routed Codex progress timestamp stayed
  fixed at `2026-04-14T15:39:55.924467+00:00`.
- Heartbeat logs continued past that point:
  - `last command_execution 1781s ago`
  - `last command_execution 2203s ago`
  - `last command_execution 3228s ago`
- Touched-file counts rose from `0 -> 76`, then flattened.
- The newest non-log file writes in the smoke workspace stopped at about
  `2026-04-14 19:58:02` local time.
- The run was manually terminated at `2026-04-14 20:34` local time after more
  than 30 minutes without new non-log writes and without any Wave B telemetry or
  watchdog timeout artifact.

## Why this matters

PR #2's primary structural claim is that provider-routed Codex waves now sit
under `_invoke_wave_sdk_with_watchdog`-equivalent coverage via
`_invoke_provider_wave_with_watchdog(...)`. This stock smoke suggests the wiring
is still incomplete in practice: progress metadata reached the log once, but the
wave-level idle timeout did not actually terminate the stalled provider-routed
wave.

## Investigation targets

1. Trace `_invoke_provider_wave_with_watchdog(...)` during a real stock run and
   verify the idle-timeout branch is reachable while `execute_wave_with_provider`
   is pending.
2. Confirm whether `state.last_progress_monotonic` is being updated anywhere
   other than real provider progress events.
3. Verify whether the heartbeat task can continue logging after the watchdog
   should have cancelled the provider task.
4. Determine whether the provider-routed Codex path can keep writing files after
   its last JSONL event, and whether that should count as watchdog progress.
5. Decide whether heartbeat-only log activity masks the operational kill rule,
   since the build was no longer silent but also was no longer making real
   progress.

## Merge impact

This run blocks PR #2 merge. The full suite is green, but the required stock
smoke did not demonstrate a healthy provider-routed Codex wave or a functioning
provider-routed watchdog timeout on the exact class of long silent Wave B work
this PR was supposed to make observable and bounded.
