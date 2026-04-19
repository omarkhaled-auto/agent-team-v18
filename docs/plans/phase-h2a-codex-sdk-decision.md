# Phase H2a Codex App-Server Decision

## Decision

Use the official `codex app-server` JSON-RPC protocol over stdio.

Do not add a `codex_app_server` Python SDK dependency.

## Why

### 1. The current repo has no SDK dependency

Local repo state:
- `pyproject.toml:16-30` declares only `claude-agent-sdk`, `pyyaml`, and `rich`
- there is no `requirements.txt`, `.gitmodules`, vendored SDK tree, or `sdk/python` directory
- `src/agent_team_v15/codex_appserver.py:328-334` imports `codex_app_server`, but that package is not installed in this environment

Verified locally:
- `import codex_app_server` fails
- `python -m pip index versions codex-app-server-sdk` returns no matching distribution
- `python -m pip index versions codex-python` returns no matching distribution

### 2. Official OpenAI docs are protocol-first, not Python-SDK-first

Official sources:
- OpenAI Codex app-server README: https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
- Raw app-server README: https://raw.githubusercontent.com/openai/codex/main/codex-rs/app-server/README.md

Verified upstream behavior:
- the supported transport is JSON-RPC 2.0-like messages over stdio (`--listen stdio://`)
- clients are expected to call `initialize`, `thread/start`, `turn/start`, then stream notifications
- upstream explicitly provides schema generation via `codex app-server generate-json-schema --out DIR`

No official OpenAI source found in this discovery pass documents a Python package named `codex_app_server`.

## Runtime proof on this machine

Using local `codex-cli 0.121.0`, direct stdio JSON-RPC succeeded:
- `initialize` response received
- `thread/start` response received
- `turn/start` response received
- `turn/completed` received for both a failure case and a successful turn

Observed success-path notifications included:
- `thread/started`
- `turn/started`
- `item/started`
- `item/agentMessage/delta`
- `item/completed`
- `thread/tokenUsage/updated`
- `turn/completed`

Observed failure-path proof:
- a turn failed cleanly with a structured API error when `effort="minimal"` conflicted with enabled tools
- transport remained healthy; failure was model/request-level, not protocol-level

## Required H2a changes

### Code

- Replace the current SDK-backed implementation in `src/agent_team_v15/codex_appserver.py`
  with a direct stdio JSON-RPC client that spawns `codex app-server --listen stdio://`
- Preserve the public surface:
  - `execute_codex(...)`
  - `is_codex_available()`
  - `CodexConfig`
  - `CodexResult`
  - orphan watchdog behavior and Claude fallback contracts

### Dependencies

- No new third-party Python dependency is required for app-server transport
- No `pyproject.toml` dependency addition is needed for Bug #20 once the transport is switched to direct JSON-RPC

## Scope consequence

H2a remains fully solvable.

This is not a "none available" halt:
- the canonical path is direct protocol
- the broken SDK import is replaced, not repaired
