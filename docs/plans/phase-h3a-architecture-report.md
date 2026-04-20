# Phase H3a Architecture Report

Date: 2026-04-20

## Scope

H3a is additive observability for the Codex app-server path. The behavior of dispatch, checkpoint diff, rollback, and Claude fallback must remain unchanged when the new flag is off.

## Dispatch blueprint

The provider-routed Wave B/D Codex path is:

1. `src/agent_team_v15/wave_executor.py:1933-1960`
   calls `provider_router.execute_wave_with_provider(...)` and already carries the milestone object inside `claude_callback_kwargs["milestone"]`.
2. `src/agent_team_v15/provider_router.py:298-325`
   wraps the prompt with `wrap_prompt_for_codex(...)`, stores the rendered string in `codex_prompt`, then calls `execute_codex(...)`.
3. `src/agent_team_v15/codex_appserver.py:820-1047`
   owns the app-server session: subprocess spawn, JSON-RPC writes, stdout/stderr readers, item demux, token accumulation, final message assembly, retry loop, and teardown.

## Capture insertion plan

### Capture 1: prompt dump

Hook at the Codex transport boundary, not in prompt-building helpers.

- Source prompt is finalized at `provider_router.py:301`.
- The last point before dispatch is `provider_router.py:319-325`.
- The app-server subprocess is not spawned until `codex_appserver.py:388-394`, so a prompt capture at `codex_appserver.execute_codex(...)` entry still satisfies "after wrap, before spawn".

Recommended wiring:

- Add a small optional capture context kwargs surface to `codex_appserver.execute_codex(...)`.
- In `provider_router._execute_codex_wave(...)`, derive:
  - `milestone_id` from `claude_callback_kwargs.get("milestone")`
  - `wave_letter` from the existing parameter
  - `capture_enabled` from `config.v18.codex_capture_enabled`
- Pass those kwargs only when the selected transport accepts them. This preserves exec-mode compatibility without touching `codex_transport.py`.

Reason for capturing inside `codex_appserver`, not `provider_router`:

- the app-server layer knows the exact spawn metadata (`cwd`, command argv, shell-vs-exec branch);
- the wrapped prompt text is already the `prompt` argument passed in from `provider_router`;
- the hook still runs before `client.start()` and before `_spawn_appserver_process(...)`.

### Capture 2: protocol log

Hook inside `_CodexJSONRPCTransport`:

- outbound JSON-RPC write point: `codex_appserver.py:424-448`, specifically `payload = _serialize_jsonrpc_request(...)` at `:430` and `stdin.write(payload)` at `:439`;
- inbound JSON-RPC read point: `codex_appserver.py:453-493`, specifically raw line read at `:459` and parsed message at `:462`.

This is the narrowest additive hook because all app-server traffic already passes through these two boundaries.

### Capture 3: response + tool-call summary

Hook into the existing item/message aggregation path:

- final agent text accumulation lives in `_MessageAccumulator.observe(...)` at `codex_appserver.py:214-247`;
- the common event demux lives in `_process_streaming_event(...)` at `codex_appserver.py:683-748`;
- turn completion is finalized in `_execute_once(...)` at `codex_appserver.py:894-900`, then the result object is returned through `execute_codex(...)`.

Recommended wiring:

- keep `_MessageAccumulator` unchanged for behavior neutrality;
- add a second additive accumulator for capture-only state;
- feed it from `_process_streaming_event(...)` alongside the existing watchdog/tokens/message flow;
- persist once per attempt in `_execute_once(...)` teardown so failed turns still emit a capture file.

## File location decision

Use `<cwd>/.agent-team/codex-captures/`.

This matches existing repo conventions:

- wave artifacts under `.agent-team/artifacts`: `src/agent_team_v15/artifact_store.py:173-180`
- wave telemetry under `.agent-team/telemetry`: `src/agent_team_v15/wave_executor.py:632-697`
- wave state under `.agent-team/wave_state`: `src/agent_team_v15/cli.py:1735-1815`

The capture files should persist. Existing telemetry/artifact writers persist under `.agent-team/` and do not clean up after success.

## Naming decision

For the provider-routed Wave B/D path, use:

- prompt: `<milestone_id>-wave-<wave_letter>-prompt.txt`
- protocol: `<milestone_id>-wave-<wave_letter>-protocol.log`
- response: `<milestone_id>-wave-<wave_letter>-response.json`

Do not prepend an extra literal `milestone-` because milestone ids in this codebase already carry that prefix in many real call sites (`wave_executor.py:595-602`, telemetry filenames at `wave_executor.py:697`).

If a future direct fix-path caller is instrumented, append `-fix-<round>` before the suffix. That suffix is not required for the provider-routed Wave B/D flow in H3a.

## Metadata header decision

The locked header is viable with one clarification:

- the subprocess working directory is not stored in the argv vector;
- the actual spawn code passes it as the `cwd=` argument to `asyncio.create_subprocess_shell/exec` at `codex_appserver.py:290-305`.

Implementation should therefore populate `# Cwd-codex-subprocess-argv:` with the actual spawn `cwd` value used by the app-server transport. That field name is slightly misleading, but it still answers hypothesis (b): did the orchestrator-passed cwd differ from the cwd used at subprocess spawn?

## Rotation decision

There is no reusable rotating-file helper in `src/agent_team_v15` for this use case. `rg` found no `RotatingFileHandler`, `logging.handlers`, `maxBytes`, or `backupCount` usage in the codebase.

Use `logging.handlers.RotatingFileHandler` with:

- `maxBytes=10 * 1024 * 1024`
- `backupCount=2`
- explicit `encoding="utf-8"`

This is additive and small enough that no refactor is needed.

## Config wiring

Follow the existing v18 flag pattern:

- dataclass declaration site near `ownership_policy_required`: `src/agent_team_v15/config.py:922-945`
- YAML loader pattern: `src/agent_team_v15/config.py:2748-2775`
- regression guard: `tests/test_config_v18_loader_gaps.py:29-104`

Add `codex_capture_enabled: bool = False` beside the other default-off v18 flags and thread it through the loader with `_coerce_bool(...)`.

## Tool-call classification notes

The local app-server code currently sees item lifecycle events, not legacy exec-mode shell tool names:

- tool-like items are handled by `item/started` and `item/completed` in `codex_appserver.py:711-729`;
- official app-server docs describe the lifecycle as `item/started -> deltas -> item/completed`, with examples for `commandExecution` and `fileChange`.

For H3a response classification on the app-server path:

- treat `commandExecution` as shell/bash-like;
- treat `fileChange` as write-like;
- treat `agentMessage` as non-tool output;
- keep unknown item types in the breakdown without forcing them into read/write buckets.

This is enough to distinguish hypothesis (a) from (b/c/d): a dispatch with zero write-like items did not attempt file changes.

## Risks

No HALT condition is triggered from the current source layout.

- The I/O points are already centralized in `_CodexJSONRPCTransport`.
- The streaming demux is already centralized in `_process_streaming_event`.
- The only notable design wrinkle is that the provider router does not currently thread milestone metadata into `execute_codex(...)`; that can be solved with optional kwargs and signature-gated passing, not a structural refactor.
