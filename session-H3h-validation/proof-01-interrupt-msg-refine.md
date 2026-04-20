# Proof 01: INTERRUPT-MSG-REFINE-001

## Original Smoke Failure

Combined-smoke evidence:

- `milestone-1-wave-B-protocol.log:579`
  - Turn 2 was injected with the legacy blanket ban:
  - `The previous turn's tool (tool_name=commandExecution) stalled for >307s. Do not run that tool again; continue the remaining work using alternative approaches.`
- `milestone-1-wave-B-protocol.log:788`
  - Codex explicitly reported the consequence:
  - `I could not run dependency sync, build, or tests ... you instructed me not to use that tool again.`
- `milestone-1-wave-B-protocol.log:791`
  - the diff showed regressive workarounds, including removal of `supertest` / `@types/supertest` and root script changes from `turbo run ...` to `pnpm -r ...`

## Source Change

Primary source updates:

- `src/agent_team_v15/codex_appserver.py:848-858`
  - command summaries are derived and truncated from the interrupted item's `command`
- `src/agent_team_v15/codex_appserver.py:922-932`
  - `item/started` records the command summary in `_OrphanWatchdog`
- `src/agent_team_v15/codex_appserver.py:1044-1074`
  - legacy prompt preserved in `_legacy_turn_interrupt_prompt(...)`
  - refined prompt added in `_build_turn_interrupt_prompt(...)`
- `src/agent_team_v15/codex_appserver.py:1171-1183`
  - flag-gated branch chooses refined vs legacy prompt
- `src/agent_team_v15/config.py:977-981, 2885-2891`
  - new flag: `codex_turn_interrupt_message_refined_enabled`
- `src/agent_team_v15/cli.py:3586-3596`
  - CLI wiring threads the flag into `CodexConfig`

Diff excerpt:

```diff
+ if bool(getattr(config, "turn_interrupt_message_refined_enabled", False)):
+     current_prompt = _build_turn_interrupt_prompt(watchdog, config)
+ else:
+     current_prompt = _legacy_turn_interrupt_prompt(watchdog)
```

## Production-Caller Proof

Invocation:

```text
pytest tests/test_h3h_interrupt_msg.py::test_execute_once_retries_with_refined_interrupt_prompt tests/test_h3h_interrupt_msg.py::test_legacy_interrupt_prompt_is_byte_identical_when_flag_off -v --tb=short
```

Output:

```text
tests/test_h3h_interrupt_msg.py::test_execute_once_retries_with_refined_interrupt_prompt PASSED
tests/test_h3h_interrupt_msg.py::test_legacy_interrupt_prompt_is_byte_identical_when_flag_off PASSED
============================== 2 passed in 0.18s ==============================
```

What this proves:

- the real `_execute_once(...)` retry path now emits the refined message when the flag is on
- the exact legacy string remains byte-identical when the flag is off

## Flag-Off Verification

`test_legacy_interrupt_prompt_is_byte_identical_when_flag_off` asserts the old prompt text exactly:

```text
The previous turn's tool (tool_name=commandExecution) stalled for >307s. Do not run that tool again; continue the remaining work using alternative approaches.
```

That keeps backward compatibility reachable.
