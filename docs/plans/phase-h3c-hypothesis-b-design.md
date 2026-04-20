# Phase H3c Hypothesis (b) Design

## Goal

Verify that the cwd seen by the Codex app-server matches the cwd the orchestrator uses for checkpoints, and make mismatches obvious.

## Repo Reality

`codex_appserver.py` already passes cwd through every obvious transport layer:

- subprocess spawn: [`codex_appserver.py:284-303`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:284>)
- `thread/start`: [`codex_appserver.py:588-595`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:588>)
- `turn/start`: [`codex_appserver.py:597-604`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/codex_appserver.py:597>)

So the missing behavior is not "send cwd at all"; it is "resolve, validate, and compare what the server says back."

## Proposed Implementation

### 1. Add a transport flag to `CodexConfig`

Because `execute_codex()` receives a `CodexConfig`, not `config.v18`, the flag must be carried there:

- `cwd_propagation_check_enabled: bool = False`

This requires minimal shared plumbing:

- declaration on `CodexConfig`
- population from `config.v18.codex_cwd_propagation_check_enabled` at [`cli.py:3537-3543`](</C:/Projects/agent-team-v18-codex/src/agent_team_v15/cli.py:3537>)

### 2. Validate and normalize cwd in `execute_codex()`

When the flag is on:

- resolve `cwd` to an absolute path with `Path(cwd).resolve()`
- raise `CodexDispatchError` if it does not exist or is not a directory
- use the resolved path for subprocess spawn, JSON-RPC requests, and captures
- log the resolved path once at dispatch entry

### 3. Compare echoed cwd from `thread/start`

The app-server protocol already returns structured data from `thread/start`; the tests in [`tests/test_bug20_codex_appserver.py:262-275`](</C:/Projects/agent-team-v18-codex/tests/test_bug20_codex_appserver.py:262>) show a `"cwd"` field in that response.

Store the `thread/start` result and, when the flag is on:

- if the response includes `cwd`, resolve it
- compare it against the orchestrator-resolved cwd
- on mismatch, emit a warning containing `CODEX-CWD-MISMATCH-001`

This is preferable to probing OS process cwd because it is cross-platform and already present in the transport protocol surface.

## Tests

- relative cwd + flag on -> thread/start and turn/start receive the absolute resolved path
- nonexistent cwd + flag on -> `CodexDispatchError`
- file path instead of directory + flag on -> `CodexDispatchError`
- server returns a different cwd -> warning contains `CODEX-CWD-MISMATCH-001`
- flag off -> no validation enforcement and legacy call shape preserved

## Risks

- This is the one H3c hypothesis that cannot stay inside `codex_appserver.py` alone if it must remain flag-gated from YAML. `cli.py` and `CodexConfig` need a tiny amount of shared plumbing.
