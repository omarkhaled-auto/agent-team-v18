# Phase H3a Discovery Citations

Date: 2026-04-20

## Provider-routed Codex dispatch

| Concern | Citation | Notes |
|---|---|---|
| Provider router entry | `src/agent_team_v15/provider_router.py:153-208` | `execute_wave_with_provider(...)` routes Codex waves into `_execute_codex_wave(...)`. |
| Prompt wrapping | `src/agent_team_v15/provider_router.py:298-303` | `wrap_prompt_for_codex(...)` is called and stored in `codex_prompt`. |
| Final pre-dispatch call site | `src/agent_team_v15/provider_router.py:319-325` | `execute_codex(codex_prompt, cwd, codex_config, codex_home, progress_callback=...)`. |
| Wave executor carries milestone object into router | `src/agent_team_v15/wave_executor.py:1933-1960` | `claude_callback_kwargs` includes `"milestone": milestone`. |

## App-server transport boundaries

| Concern | Citation | Notes |
|---|---|---|
| Spawn helper | `src/agent_team_v15/codex_appserver.py:283-306` | Builds `cmd = [codex_bin, "app-server", "--listen", "stdio://"]` and passes `cwd=cwd` into subprocess creation. |
| Transport startup | `src/agent_team_v15/codex_appserver.py:388-394` | `start()` builds env, spawns process, starts stdout/stderr reader tasks. |
| JSON-RPC request serialization | `src/agent_team_v15/codex_appserver.py:250-258` | Returns newline-delimited UTF-8 JSON bytes. |
| JSON-RPC outbound write path | `src/agent_team_v15/codex_appserver.py:424-448` | `send_request(...)` writes serialized payload to stdin and drains it. |
| JSON-RPC inbound read path | `src/agent_team_v15/codex_appserver.py:453-493` | `_read_stdout(...)` reads one line, parses JSON, routes notifications vs replies. |
| stderr capture | `src/agent_team_v15/codex_appserver.py:494-509` | `_read_stderr(...)` accumulates stderr lines in a bounded deque. |

## Streaming-item demux and result accumulation

| Concern | Citation | Notes |
|---|---|---|
| Final assistant text accumulator | `src/agent_team_v15/codex_appserver.py:206-247` | `_MessageAccumulator.observe(...)` buffers `item/agentMessage/delta` and finalizes on `item/completed`. |
| Common event demux | `src/agent_team_v15/codex_appserver.py:683-748` | `_process_streaming_event(...)` handles `item/started`, `item/completed`, `item/agentMessage/delta`, and token updates. |
| Turn-completion loop | `src/agent_team_v15/codex_appserver.py:779-810` | `_wait_for_turn_completion(...)` drains notifications until matching `turn/completed`. |
| Session execution and final result | `src/agent_team_v15/codex_appserver.py:820-970` | `_execute_once(...)` starts client, runs turn, handles orphan recovery, archives thread, applies tokens. |
| Retry wrapper | `src/agent_team_v15/codex_appserver.py:973-1047` | `execute_codex(...)` owns attempt loop and aggregate result. |

## Existing `.agent-team` artifact conventions

| Concern | Citation | Notes |
|---|---|---|
| Wave artifacts path | `src/agent_team_v15/artifact_store.py:173-180` | Saves to `.agent-team/artifacts/<milestone_id>-wave-<wave>.json`. |
| Wave telemetry path | `src/agent_team_v15/wave_executor.py:632-697` | Saves to `.agent-team/telemetry/<milestone_id>-wave-<wave>.json`. |
| Shared-file scaffold path | `src/agent_team_v15/cli.py:525-552` | Uses `.agent-team/shared/`. |
| Wave state path | `src/agent_team_v15/cli.py:1735-1815` | Uses `.agent-team/` and `.agent-team/wave_state/...`. |

## Config-flag pattern

| Concern | Citation | Notes |
|---|---|---|
| V18 flag declaration neighborhood | `src/agent_team_v15/config.py:922-945` | Nearby default-off booleans include `ownership_contract_enabled`, `ownership_policy_required`, `spec_reconciliation_enabled`, `scaffold_verifier_enabled`. |
| Loader pattern | `src/agent_team_v15/config.py:2741-2775` | Existing `_coerce_bool(v18.get(...), default)` blocks. |
| Loader gap regression guard | `tests/test_config_v18_loader_gaps.py:29-104` | Parametrized round-trip plus structural guard. |

## Direct non-provider Codex app-server call sites

These are relevant to future follow-up, not required for H3a’s provider-routed Wave B/D proof:

| Call site | Citation | Notes |
|---|---|---|
| Wave A.5 / T.5 dispatch | `src/agent_team_v15/wave_a5_t5.py:450-485` | Calls `codex_transport_module.execute_codex(...)` directly. |
| Compile-fix dispatch | `src/agent_team_v15/wave_executor.py:2821-2845` | Calls `codex_mod.execute_codex(...)` directly. |
| Audit-fix Codex dispatch | `src/agent_team_v15/cli.py:6621-6639` | Calls `codex_mod.execute_codex(...)` directly. |

## External protocol schema references

Primary source used for schema verification:

- OpenAI Codex app-server README: `https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md`
  - message schema overview around lines `292-311`
  - `turn/start` / streaming lifecycle around lines `307-311`
  - `commandExecution` example around lines `632-646`
  - `fileChange` approval lifecycle around the "File change approvals" section in the same document

Key confirmation from the official docs:

- app-server streams `item/started`, item-specific deltas, and `item/completed`;
- `item/agentMessage/delta` must be concatenated by `itemId` to reconstruct the assistant reply;
- write-like activity is represented by `fileChange` items and shell-like activity by `commandExecution` items.
