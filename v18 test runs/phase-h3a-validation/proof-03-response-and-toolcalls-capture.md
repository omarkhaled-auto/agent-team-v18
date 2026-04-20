# Proof 03 - Response And Tool-Calls Capture

Date: 2026-04-20

## Goal

Show that H3a writes a triage-friendly response JSON containing the final assistant message, per-item tool lifecycle, and summary counts that distinguish write-like activity from shell-only activity.

## Production call chain

- `src/agent_team_v15/codex_appserver.py:711-830`
  - `_process_streaming_event(...)` now forwards each event into `CodexCaptureSession`
  - `_wait_for_turn_completion(...)` drains those events through the common demux
- `src/agent_team_v15/codex_captures.py:239-428`
  - `ResponseCaptureAccumulator` reconstructs the final agent message from `item/agentMessage/delta`
  - tracks non-message `item/started` / `item/completed`
  - classifies write-like vs read-like vs shell-like items
  - truncates per-item output summaries at `1 KB`

## Evidence

- `tests/test_codex_dispatch_captures.py::test_provider_routed_codex_dispatch_writes_capture_files`
  - asserts the response file path is:
    - `<tmp>/.agent-team/codex-captures/milestone-1-wave-B-response.json`
  - parses the JSON and asserts:
    - `metadata.milestone_id == "milestone-1"`
    - `metadata.wave_letter == "B"`
    - `final_agent_message == "OK"`
    - `cumulative_tool_summary.total_tool_calls == 1`
    - `cumulative_tool_summary.shell_tool_invocations == 1`
    - `cumulative_tool_summary.write_tool_invocations == 0`
    - the captured tool record is `commandExecution`
- `tests/test_codex_dispatch_captures.py::test_response_accumulator_counts_write_like_items_and_truncates_output`
  - feeds a synthetic `fileChange` item through the accumulator
  - asserts `write_tool_invocations == 1`
  - asserts oversized output is truncated with a `<truncated from ...>` marker
- `tests/test_codex_dispatch_captures.py::test_prompt_capture_failure_does_not_block_protocol_and_response_capture`
  - forces prompt capture failure
  - confirms response capture still persists

## Result

Response capture now records exactly what Codex said, what non-message items it executed, and whether any write-like items were attempted, which is the triage signal H3b/H3c need.
