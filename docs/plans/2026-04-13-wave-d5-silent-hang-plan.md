# Bug #10 - Wave D.5 SDK Silent Hang

> **Status:** New - surfaced during the 2026-04-13 smoke test clean-attempt-2. Not yet fixed at authoring time.
>
> **Severity:** HIGH - pipeline stops mid-wave indefinitely with no error, no timeout, and no telemetry write. Requires manual kill. Blocks Wave T, Wave E, and the per-milestone audit from ever running.

## Implementation Note (post-ratification)

The landed implementation is ratified for the smoke-test re-run. It does not
use a heartbeat file. Instead, `src/agent_team_v15/wave_executor.py` keeps an
in-memory `_WaveWatchdogState` with monotonic timestamps for the last observed
SDK progress event, and `src/agent_team_v15/cli.py` feeds that state via the
existing `progress_callback` hook on every SDK lifecycle/message event:
session start, query submit, assistant text, tool use, and result messages.

What shipped:

- Config defaults in `src/agent_team_v15/config.py`:
  `wave_idle_timeout_seconds=1800`, `wave_watchdog_poll_seconds=30`,
  `wave_watchdog_max_retries=1`
- Idle-time timeout enforcement in
  `src/agent_team_v15/wave_executor.py::_invoke_wave_sdk_with_watchdog()`
- Hang report emission to `<cwd>/.agent-team/hang_reports/` with recent SDK
  events, last message type/tool, timestamps, and a Python stack snapshot
- One retry on watchdog timeout before the wave fails
- Per-wave telemetry fields for `wave_timed_out`, `wave_watchdog_fired_at`,
  `last_sdk_message_type`, `last_sdk_tool_name`, and `hang_report_path`

Why this is acceptable in place of the heartbeat-file design:

- The original heartbeat file was only meant to represent recent SDK progress.
  Recording that state directly in memory is a tighter signal than mirroring
  it through filesystem writes.
- The callback is wired at the actual SDK stream-consumption layer
  (`_process_response`), so it observes real assistant/tool/result traffic
  rather than a coarser outer-loop timestamp.
- Avoiding per-message file writes removes extra I/O during long waves while
  still giving the watchdog a monotonic idle timer and enough context to write
  a useful hang report when it fires.

Evidence reviewed during ratification:

- `tests/test_v18_phase2_wave_engine.py::test_execute_milestone_waves_retries_sdk_timeout_once_and_writes_hang_report`
  proves the watchdog fires, retries once, and writes telemetry plus a hang
  report.
- `tests/test_v18_phase2_wave_engine.py::test_execute_milestone_waves_does_not_timeout_with_periodic_progress`
  proves periodic SDK progress keeps healthy waves alive under an aggressively
  low timeout.

Tradeoffs retained:

- There is no on-disk heartbeat file for external tailing/debugging during a
  live run.
- The implementation relies on task cancellation rather than an explicit
  PID-targeted subprocess kill path.

For the smoke-test re-run, those tradeoffs are acceptable because the watchdog
now bounds silent hangs, emits diagnostics, and retries once. If a future run
shows orphaned child processes surviving cancellation or hangs below the SDK
message layer, file a restoration follow-up specifically for explicit process
termination and/or external heartbeat artifacts.

## Note To The Implementing Agent

This is a hang bug, not a logic bug. Reproduce before assuming the root cause.
There are multiple plausible causes; start with instrumentation before patching
anything:

1. Reproduce. Run a TaskFlow-like smoke test with all other fixes in place.
   Observe whether Wave D.5 gets stuck after a long sequence of Edit-tool calls.
2. Instrument first, fix second. Add timing instrumentation around the
   `async with ClaudeSDKClient(...)` call that Wave D.5 makes. Capture:
   (a) when the call started, (b) wall-clock duration, (c) whether the SDK is
   in the query phase or `_process_response` phase when the hang begins,
   (d) the last stream message type received.
3. Capture an artifact. When the hang reproduces, take a stack dump
   (`py-spy dump --pid <python_pid>` or `faulthandler.dump_traceback()`) from
   the hung process. The stack shows whether we're blocked in the asyncio event
   loop, in the SDK's message reader, in Windows IPC, etc.
4. Do not add retries before understanding the cause. A retry over a hanging
   call may double the hang time. A watchdog timeout is the right instrument,
   but the threshold must be informed by what healthy Wave D.5 durations look
   like.

After understanding the problem, implement the watchdog plus one-retry policy
proposed below.

## Symptom

Wave D.5 (Claude-provided UI polish wave) on the 2026-04-13 clean-attempt-2:

- Wave D completed at 21:29:15 (telemetry written, `compile_passed: true`,
  43 files)
- Wave D.5 started immediately after - log shows a long sequence of `Read`
  actions followed by `Edit` actions across frontend files
- Last log line at 21:32:15: `Now polish the DataTable for compactness and
  better hover states` followed by more edits
- Then nothing. Python process alive, 117 MB working set. Zero file
  modifications for 80+ minutes. Zero new log lines. No exception, no timeout
  warning, and no telemetry write.
- Killed manually at about 22:13 (80+ minutes after the last log entry) to
  produce the final report

## Empirical Evidence

- `/c/smoke/clean/BUILD_LOG.txt` froze at line 711 from 21:32:15 until manual
  kill
- `/c/smoke/clean/.agent-team/telemetry/` contained
  `milestone-1-wave-{A,B,C,D}.json` but no `milestone-1-wave-D5.json`
- `/c/smoke/clean/.agent-team/STATE.json` last-modified at 21:29:20 (Wave D
  completion), never updated after that
- Two Python processes for the build remained alive:
  - `.venv/Scripts/python.exe` (3.6 MB) - parent orchestrator
  - `Python311/python.exe` (117 MB) - active SDK subprocess
- No native stack dump was taken - that was the first instrumentation gap to
  close

## Potential Root Causes (rank ordered)

1. `claude_agent_sdk` streaming message reader stuck on backpressure. The SDK
   uses asyncio to consume a message stream from the `claude-code` subprocess.
   If the subprocess produces a large burst of messages, the reader may block
   on a queue that was never drained properly.
2. Windows IPC buffer pressure. `asyncio.create_subprocess_exec` on Windows
   uses named pipes. If the subprocess writes a lot of stdout without the
   parent reading it fast enough, the pipe fills and the subprocess blocks on
   write.
3. Claude Code CLI process paused in a long thinking step. After a long edit
   sequence, the CLI might pause long enough that the parent sees no useful
   progress.
4. No timeout on `ClaudeSDKClient.__aexit__`. If the SDK client's context
   manager exit path waits for a final message that never arrives, the build
   hangs on exit.
5. Rate-limit or API throttle loop in `claude-code` itself. If the CLI
   silently retries after a 429, the parent sees nothing.

## Scope

Changes:

- Add a per-wave watchdog timer in `src/agent_team_v15/wave_executor.py` that
  kills and retries (or fails) a wave that has not emitted any SDK message for
  N minutes
- Add a "last heartbeat" timestamp to per-wave state that updates on every SDK
  message, tool use, or telemetry write
- Add config fields for idle timeout, watchdog poll interval, and retry budget
- Add instrumentation for future debugging: if a wave is killed by the
  watchdog, write a hang-report JSON with the last seen message/tool data
- Add telemetry fields for watchdog events

Not in scope:

- Rewriting `claude_agent_sdk` streaming internals
- Adding retry logic that masks a persistent hang
- Changing which waves run on which provider

## Proposed Implementation

### 1. Config

Add to `v18_config`:

```python
wave_timeout_seconds: int = 1800
wave_max_retries_on_hang: int = 1
wave_heartbeat_check_interval: int = 30
```

Users hitting the watchdog too aggressively can raise the timeout in config.

### 2. Wave executor integration

Wrap each wave call in a watchdog-aware coroutine that records the last
observed SDK progress, polls on a short interval, and raises a timeout when
idle time exceeds the configured threshold.

### 3. Heartbeat emission

Inside `_process_response()` (which consumes SDK stream messages), update the
watchdog state on every message before the existing handling continues.

### 4. Retry policy

If a wave times out, write a hang report and retry once with a fresh SDK
client. If the retry also times out, fail the milestone.

### 5. Hang report format

When the watchdog fires, write
`<cwd>/.agent-team/hang_reports/wave-<wave>-<timestamp>.json` with:

```json
{
  "wave": "D5",
  "milestone_id": "milestone-1",
  "started_at": "2026-04-13T21:29:20Z",
  "last_heartbeat": "2026-04-13T21:32:15Z",
  "hang_duration_seconds": 4800,
  "last_sdk_message_type": "tool_use",
  "last_sdk_tool_name": "Edit"
}
```

## Acceptance Criteria

- [ ] `wave_timeout_seconds` config field added with default 1800
- [ ] Watchdog runs per wave and checks progress every 30 seconds
- [ ] `_process_response` updates watchdog state on every SDK message
- [ ] On timeout: subprocess canceled, hang report written, wave marked failed
- [ ] One retry on hang (configurable)
- [ ] Per-wave telemetry includes `wave_timed_out: false` by default and
      `true` when the watchdog fires
- [ ] Test: simulate a long-hanging mock SDK call and verify the watchdog
      fires at the configured timeout
- [ ] Test: simulate a healthy wave with periodic progress and verify the
      watchdog does not fire
- [ ] Hang report JSON produced at `<cwd>/.agent-team/hang_reports/` when the
      watchdog fires
- [ ] Manual test: re-run the TaskFlow smoke test with a reproducing setup and
      verify the watchdog catches Wave D.5 if it hangs again

## Risk Notes

- Too-aggressive timeout could kill healthy long-running waves. Tune the idle
  timeout conservatively.
- Retry budget of 1 on hang is deliberate. If the retry also hangs, the issue
  is probably structural.
- Heartbeat updates on every SDK message may be chatty if persisted to disk.
  That is one reason the ratified implementation keeps the fast path in memory.
- Windows-specific IPC issues may still need a separate fix. The watchdog
  bounds the symptom even if it does not cure the underlying transport issue.

## Done When

- Any wave that hangs for more than the configured idle timeout produces a hang
  report and fails the wave instead of wedging the build indefinitely
- Hang reports accumulate at `<cwd>/.agent-team/hang_reports/`
- Healthy runs do not hit the watchdog
- A smoke-test re-run either completes through Wave D.5 or fails with a clear
  watchdog-fired message within the timeout window, not after an 80+ minute
  silent stall
