# Phase H3a - Codex Dispatch Observability - Final Report

Date: 2026-04-20

## Implementation Summary

- 3 captures added for provider-routed Codex app-server waves:
  - prompt dump
  - protocol log
  - response + tool-call summary
- Config flag added:
  - `v18.codex_capture_enabled` (default `False`)
- Pattern IDs added:
  - none
- LOC:
  - source: `+522 / -15`
  - tests: `+438`
  - docs (discovery artifacts only): `+212`

## Capture Coverage Matrix

| Capture | Addresses Hypothesis | File location |
|---|---|---|
| Prompt dump | (a) summary-only / prompt framing | `<cwd>/.agent-team/codex-captures/<milestone_id>-wave-<wave>-prompt.txt` |
| Protocol log | (b) cwd mismatch, (c) transport/race clues | `<cwd>/.agent-team/codex-captures/<milestone_id>-wave-<wave>-protocol.log` |
| Response + toolcalls | (a) direct triage signal via write-like item count | `<cwd>/.agent-team/codex-captures/<milestone_id>-wave-<wave>-response.json` |

## Code Changes

- `src/agent_team_v15/codex_captures.py`
  - new helper module for capture paths, prompt persistence, protocol rotation, response/tool-call accumulation, and masking
- `src/agent_team_v15/codex_appserver.py`
  - additive protocol hooks at the stdio JSON-RPC boundaries
  - additive event forwarding into the response/tool-call accumulator
  - optional `capture_enabled` / `capture_metadata` kwargs on `execute_codex(...)`
  - `_CLIENT_INFO` frozen to avoid mutable module-level state
- `src/agent_team_v15/provider_router.py`
  - reads `v18.codex_capture_enabled`
  - derives milestone/wave metadata for provider-routed Codex waves
  - signature-gates the extra kwargs so exec mode remains untouched
- `src/agent_team_v15/config.py`
  - declares and loads `v18.codex_capture_enabled`

## Test Results

- Focused H3a ring:
  - `pytest tests/test_codex_dispatch_captures.py tests/test_bug20_codex_appserver.py tests/test_provider_routing.py tests/test_provider_router_fallback.py tests/test_transport_selector.py tests/test_config_v18_loader_gaps.py -q`
  - result: `168 passed in 7.26s`
- Clean serial default suite:
  - `pytest tests/ -q`
  - saved at `v18 test runs/phase-h3a-validation/pytest-output-default.txt`
  - result: `11199 passed, 35 skipped, 1 deselected, 20 warnings in 506.95s (0:08:26)`
- Codex live suite:
  - `pytest tests/ -q -m codex_live`
  - saved at `v18 test runs/phase-h3a-validation/pytest-output-codex-live.txt`
  - result: `1 passed, 1 skipped, 11233 deselected in 18.03s`

## Wiring Verification

- Config gating: verified
  - `provider_router.py:320-349`
  - no capture directory is created when the flag is off
- Insertion points: verified
  - prompt capture created from `execute_codex(...)` before subprocess spawn (`codex_appserver.py:1028-1062`)
  - protocol capture attached to `send_request(...)` and `_read_stdout(...)` (`codex_appserver.py:437-479`)
  - response capture fed from `_process_streaming_event(...)` / `_wait_for_turn_completion(...)` (`codex_appserver.py:711-830`)
- H2a + H2bc dependency preservation: verified
  - no diff in:
    - `src/agent_team_v15/codex_transport.py`
    - `src/agent_team_v15/codex_cli.py`
    - `src/agent_team_v15/constitution_templates.py`
    - `src/agent_team_v15/ownership_enforcer.py`
    - `src/agent_team_v15/spec_reconciler.py`
    - `src/agent_team_v15/scaffold_verifier.py`
    - `src/agent_team_v15/scaffold_runner.py`
    - `docs/SCAFFOLD_OWNERSHIP.md`
- No mutable module globals: verified
  - `rg -n "^_[A-Z_]+\\s*=\\s*\\[\\]|^_[A-Z_]+\\s*=\\s*\\{|^_logger_instance\\s*=" src/agent_team_v15/codex_appserver.py src/agent_team_v15/codex_captures.py`
  - result: no matches
- Fallback path untouched: verified
  - the `checkpoint_diff -> "produced no tracked file changes" -> _claude_fallback(...)` branch remains unchanged in `provider_router.py:401-416`

## Production-Caller Proofs

- `v18 test runs/phase-h3a-validation/proof-01-prompt-dump-capture.md`
- `v18 test runs/phase-h3a-validation/proof-02-protocol-log-capture.md`
- `v18 test runs/phase-h3a-validation/proof-03-response-and-toolcalls-capture.md`

## Scope Notes

- H3a is implemented for the provider-routed Codex app-server wave path that caused the H2e fallback (`provider_router -> codex_appserver`).
- Direct app-server callers outside that path, such as A.5/T.5 and fix dispatch helpers, were not rewired in this phase because `wave_executor.py` / `cli.py` caller changes were explicitly out of scope.
- The lower transport now supports capture kwargs, so those caller sites can opt in later without refactoring the capture core.

## Handoff Notes For H3b

- Set `v18.codex_capture_enabled: true` in the H3b smoke config.
- Re-run the TaskFlow Mini PRD smoke that routes M1 Wave B through Codex app-server.
- Budget expectation: roughly `$2-5` for the Codex Wave B dispatch plus the existing fallback path.
- Expected captures:
  - Wave A remains on Claude and should not emit Codex captures.
  - Wave B should emit exactly 3 files under `<cwd>/.agent-team/codex-captures/`:
    - `<milestone_id>-wave-B-prompt.txt`
    - `<milestone_id>-wave-B-protocol.log`
    - `<milestone_id>-wave-B-response.json`
  - No Wave D capture is expected unless H3b drives execution past the current halt point.
- Inspect:
  - prompt dump for framing and cwd metadata
  - protocol log for actual streamed events
  - response JSON for `write_tool_invocations`
- Triage guidance:
  - `write_tool_invocations == 0` strongly points to hypothesis (a)
  - write-like items present but no filesystem change shifts attention to (b), (c), or (d)
- Post-H3b:
  - determine which of hypotheses `(a)`, `(b)`, `(c)`, or `(d)` the captures support
  - use that root-cause finding to scope H3c, which is the fix phase rather than another observability pass

## Verdict

SHIP IT
