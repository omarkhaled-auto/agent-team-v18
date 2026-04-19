# Phase H2a Architecture Report

## Summary

Two issues are real at current HEAD:

1. The project-root `.codex/config.toml` snippet is invalid for `codex-cli 0.121.0`.
2. The app-server transport is wired to a missing Python package instead of the documented JSON-RPC protocol.

Both are on the hot path for Codex-routed work.

## 1A. Config schema root cause

Current emission:
- `src/agent_team_v15/constitution_templates.py:162-172`
- emits `project_doc_max_bytes = 65536` under `[features]`

Why it fails:
- upstream schema defines `project_doc_max_bytes` as a top-level integer
- upstream schema defines `features.<name>` as boolean-only feature toggles

Rewrite:

```toml
project_doc_max_bytes = 65536
```

No source reader changes are needed because the repo-root snippet is write-only in this repo.

## 1B. Codex transport surface

### Current selector

- `src/agent_team_v15/cli.py:3457-3461`
- `app-server` imports `agent_team_v15.codex_appserver`
- otherwise imports `agent_team_v15.codex_transport`

### Current app-server failure surface

- `src/agent_team_v15/codex_appserver.py:328-334`
- imports `from codex_app_server import AppServerClient, AppServerConfig`
- no such dependency is declared in the repo
- the resulting exception is funneled into the generic Claude fallback path through `provider_router._execute_codex_wave(...)`

### Current exec path

- `src/agent_team_v15/codex_transport.py:549-684`
- spawns `codex exec --json --full-auto --skip-git-repo-check --cd <cwd> -m <model> -c model_reasoning_effort=<...> -`

## 1C. Canonical Bug #20 path

The official OpenAI-supported interface is direct `codex app-server` JSON-RPC over stdio.

Implementation shape for H2a:
- keep `src/agent_team_v15/codex_appserver.py`
- replace SDK assumptions with a thin async JSON-RPC subprocess client
- drive:
  - `initialize`
  - `thread/start`
  - `turn/start`
  - notification stream processing
  - `turn/interrupt` for orphan recovery

No new Python dependency is required.

## 1D. Dispatch sites H2a must cover

Distinct Codex call surfaces at current HEAD:
- provider-routed Wave B
- provider-routed Wave D only when merged-D override is off
- Wave A.5 main + rerun via `wave_a5_t5._dispatch_codex`
- Wave T.5 main + rerun via `wave_a5_t5._dispatch_codex`
- Codex compile-fix path in `_run_wave_compile(...)`
- Wave B DTO-guard compile-fix re-entry

Important behavioral split:
- B / provider-routed D / compile-fix already have Claude fallback
- A.5 and T.5 currently do not; they return failure without a Claude reroute

H2a should not broaden fallback policy. It should only make the selected Codex transport work.

## 1E. Test implications

Config tests currently lock in the broken `[features]` form and must be updated.

App-server tests currently prove only the local wrapper shape and mocked SDK behavior. They do not prove a real dependency install or a real app-server turn. H2a should replace these assumptions with:
- protocol/client tests for the local JSON-RPC transport wrapper
- one live `@pytest.mark.codex_live` integration test

## 1F. Live validation findings

Local app-server probes against `codex-cli 0.121.0` proved:
- `initialize`, `thread/start`, `turn/start`, and `turn/completed` all work over stdio JSON-RPC
- a request can fail cleanly at the API/model layer while transport stays healthy
- a successful turn emits `item/agentMessage/delta`, `item/completed`, and `thread/tokenUsage/updated`

Observed success-path token usage shape:
- `thread/tokenUsage/updated.params.tokenUsage.total.inputTokens`
- `...cachedInputTokens`
- `...outputTokens`
- `...reasoningOutputTokens`

Observed completion shape:
- `turn/completed.params.turn.status`
- `turn/completed.params.turn.error`

Observed final-answer shape:
- `item/completed.params.item.type == "agentMessage"`
- final text in `item.text`

## Recommended implementation order

1. Fix config snippet and add version-detection helper.
2. Rewrite `codex_appserver.py` around direct stdio JSON-RPC.
3. Preserve `execute_codex(...)` / `CodexOrphanToolError` / Claude fallback contracts.
4. Add protocol-focused tests plus a guarded live `codex_live` test.
5. Run targeted tests, then full `pytest tests/ -v`.
