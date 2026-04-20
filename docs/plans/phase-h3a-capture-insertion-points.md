# Phase H3a Capture Insertion Points

Date: 2026-04-20

## Capture 1: Prompt dump

### Required visibility

- full wrapped prompt after `wrap_prompt_for_codex(...)`
- milestone id
- wave letter
- orchestrator-passed cwd
- app-server spawn cwd
- model
- reasoning effort

### Exact hook

1. Derive metadata in `src/agent_team_v15/provider_router.py:319-325`, because that frame has:
   - `wave_letter`
   - `cwd`
   - `codex_config`
   - `codex_home`
   - `claude_callback_kwargs` containing the milestone object from the caller
2. Persist inside `src/agent_team_v15/codex_appserver.py:973-1012`, before the first `_execute_once(...)` attempt runs.

### Why split the hook

- `provider_router` knows milestone/wave.
- `codex_appserver` knows spawn metadata and still runs before subprocess spawn.

### Implementation note

Add optional capture kwargs to `codex_appserver.execute_codex(...)` and pass them from `provider_router` only when the selected transport accepts them.

## Capture 2: Protocol log

### Outbound boundary

- `src/agent_team_v15/codex_appserver.py:430-440`

Log the serialized JSON-RPC payload immediately before `stdin.write(payload)`.

### Inbound boundary

- `src/agent_team_v15/codex_appserver.py:459-464`

Log the raw line immediately after `stdout.readline()` succeeds and before/after parsing. Logging the raw UTF-8 line is sufficient because `_parse_jsonrpc_line(...)` already enforces JSON object shape.

### Lifecycle

- instantiate once per `execute_codex(...)` attempt;
- close in the enclosing `finally`;
- use rotation `10 MB + 2 backups`.

## Capture 3: Response + tool-call summary

### Agent message stream

- `src/agent_team_v15/codex_appserver.py:220-247`
- existing logic already reconstructs the final assistant message from:
  - `item/agentMessage/delta`
  - `item/completed` where `item.type == "agentMessage"`

### Tool/item lifecycle

- `src/agent_team_v15/codex_appserver.py:711-729`

This block already sees both:

- `item/started`
- `item/completed`

and already extracts:

- `item_id`
- a best-effort name via `name`, `tool`, or `type`

### Final persistence point

- `src/agent_team_v15/codex_appserver.py:952-970`

Persist from `_execute_once(...)` teardown so the capture survives success, failure, and exception paths.

## Path decision

Use:

- `<cwd>/.agent-team/codex-captures/<milestone_id>-wave-<wave_letter>-prompt.txt`
- `<cwd>/.agent-team/codex-captures/<milestone_id>-wave-<wave_letter>-protocol.log`
- `<cwd>/.agent-team/codex-captures/<milestone_id>-wave-<wave_letter>-response.json`

All paths must resolve from the `cwd` argument passed into the Codex transport, not process cwd and not repo root by accident.

## Non-goals for H3a

- no exec-mode transport instrumentation
- no fallback logic change
- no checkpoint diff change
- no prompt-content change
- no compile-fix / audit-fix call-site rewiring
