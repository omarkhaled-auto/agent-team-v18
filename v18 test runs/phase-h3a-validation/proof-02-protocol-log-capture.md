# Proof 02 - Protocol Log Capture

Date: 2026-04-20

## Goal

Show that every app-server JSON-RPC request/notification is written to a rotating protocol log with the expected line format.

## Production call chain

- `src/agent_team_v15/codex_appserver.py:370-489`
  - `_CodexJSONRPCTransport.send_request(...)` logs outbound payloads before `stdin.write(...)`
  - `_CodexJSONRPCTransport._read_stdout(...)` logs inbound lines before message demux
- `src/agent_team_v15/codex_captures.py:173-236`
  - `ProtocolCaptureLogger` writes `<ISO> <DIR> <SIZE> <JSON>` lines and rotates at `10 MB` with `2` backups

## Evidence

- `tests/test_codex_dispatch_captures.py::test_provider_routed_codex_dispatch_writes_capture_files`
  - asserts the protocol file path is:
    - `<tmp>/.agent-team/codex-captures/milestone-1-wave-B-protocol.log`
  - asserts the log contains:
    - an outbound `initialize` request
    - an outbound `thread/start` request
    - an inbound `turn/completed` notification
- `tests/test_codex_dispatch_captures.py::test_protocol_capture_logger_rotates`
  - constructs `ProtocolCaptureLogger(..., max_bytes=160, backup_count=2)`
  - writes repeated outbound payloads
  - asserts both `protocol.log` and `protocol.log.1` exist
- `tests/test_codex_dispatch_captures.py::test_prompt_capture_failure_does_not_block_protocol_and_response_capture`
  - forces prompt capture failure
  - confirms protocol logging still succeeds

## Result

Protocol traffic is captured at the real stdio boundaries, rotation works, and protocol logging survives failures in sibling captures.
