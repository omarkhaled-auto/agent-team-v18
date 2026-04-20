# Phase H3d Architecture Report

Date: 2026-04-20

## Summary

H3d is a narrow transport-and-router fix. The local code and the upstream app-server docs agree on the same implementation shape:

1. `thread/start` is built in `codex_appserver.py` and currently omits `sandbox`, which reproduces the H3c smoke failure.
2. The correct H3d primary fix is a top-level `sandbox` string on `thread/start`, not a `sandboxPolicy` object on `turn/start`.
3. The `BLOCKED:` defense-in-depth hook belongs in `provider_router.py` before the existing `if codex_result.success:` branch so existing rollback and Claude fallback code stays intact.
4. `CodexResult` is a mutable dataclass and the final assistant text lives in `final_message`, so no wrapper object or `dataclasses.replace(...)` detour is required.

Constraint note:

- The brief mandates `context7` and `sequential-thinking`, but those MCPs are not available in this Codex session. I verified the protocol shape against primary sources instead: the OpenAI app-server docs, `openai/codex` source, and `openai/codex` issue `#15310`.
- The installed Codex `0.121.0` runtime added one important empirical wrinkle: it accepts the `thread/start.sandbox` field, but the wire enum values are kebab-case (`workspace-write`) even though the published examples show camelCase (`workspaceWrite`).

## Insertion Map

### 1A. `thread/start` payload construction

- Exact site: `src/agent_team_v15/codex_appserver.py:637-644`
- Function: `_CodexAppServerClient.thread_start()`
- Current params:
  - `cwd`
  - `model`
  - `approvalPolicy`
  - `personality`
- H3d insertion point:
  - immediately after the existing base params dict in `thread_start()`
  - add a flag-gated `params["sandbox"] = sandbox_mode`

### 1B. `CodexConfig` plumbing path

- `config.v18` is loaded in `src/agent_team_v15/config.py:2791-2832`
- `CodexConfig(...)` is constructed in `src/agent_team_v15/cli.py:3537-3543`
- H3c already uses the non-invasive threading pattern we need:
  - `setattr(codex_config, "cwd_propagation_check_enabled", ...)` at `src/agent_team_v15/cli.py:3544-3548`
- H3d should mirror that pattern to avoid touching `codex_transport.py`:
  - `setattr(codex_config, "sandbox_writable_enabled", bool(...))`
  - `setattr(codex_config, "sandbox_mode", str(...))`

### 1C. `turn/start` payload reality

- Exact site: `src/agent_team_v15/codex_appserver.py:646-653`
- Function: `_CodexAppServerClient.turn_start()`
- Current params:
  - `threadId`
  - `input`
  - `cwd`
  - `effort`
- No `config` sub-object is currently sent.
- No sandbox override is currently sent on `turn/start`.
- H3d does not need to touch this function for the primary fix.

### 1D. `BLOCKED:` interception site

- Exact Codex dispatch call: `src/agent_team_v15/provider_router.py:342-352`
- Existing success gate starts at `src/agent_team_v15/provider_router.py:399`
- Existing zero-diff fallback branch is `src/agent_team_v15/provider_router.py:425-439`
- Existing failure rollback + Claude fallback is `src/agent_team_v15/provider_router.py:455-470`

Recommended H3d insertion point:

- between the `execute_codex(...)` await block and the `if getattr(codex_result, "success", False):` branch
- mutate `codex_result.success` to `False` when:
  - `v18.codex_blocked_prefix_as_failure_enabled` is on
  - `codex_result.success` is currently `True`
  - `codex_result.final_message.lstrip().startswith("BLOCKED:")`

This preserves:

- the zero-diff fallback branch byte-for-byte
- the `_claude_fallback(...)` implementation byte-for-byte
- the existing failure rollback path

### 1E. Result mutability

- `CodexResult` is declared in `src/agent_team_v15/codex_transport.py:65-85`
- It is a plain `@dataclass`, not frozen
- Final assistant text field: `final_message`
- Capture JSON field `final_agent_message` is produced separately by `codex_captures.py`; it is not the runtime `CodexResult` attribute

Practical implication:

- mutate in place; do not add wrappers and do not use `dataclasses.replace(...)`

### 1F. Sandbox metadata surfacing

- The H3a protocol capture already records the raw `thread/start` request and the `thread/start` response.
- The preserved H3c smoke log proves the response already contains the effective `sandbox` object.
- Existing protocol-shape test coverage already models this field in `tests/test_bug20_codex_appserver.py:263-276`.

Recommendation:

- do not add new capture/result plumbing in H3d
- rely on the existing H3a protocol capture for authoritative sandbox evidence
- optional runtime logging is possible, but not required for the fix and not required for smoke validation

### 1G. Flag inventory

Add to `V18Config`:

- `codex_sandbox_writable_enabled: bool = False`
- `codex_sandbox_mode: str = "workspace-write"`
- `codex_blocked_prefix_as_failure_enabled: bool = False`

Loader pattern:

- use `_coerce_bool(...)` for the two booleans
- use `_coerce_text(...)` for `codex_sandbox_mode`
- enforce the whitelist at runtime in `codex_appserver.py` so invalid values fail loudly before dispatch

Allowed values:

- `readOnly`
- `workspaceWrite`
- `dangerFullAccess`

Wire serialization:

- normalize the accepted config values above to:
  - `read-only`
  - `workspace-write`
  - `danger-full-access`

## Tests To Extend

- App-server transport/unit protocol tests:
  - `tests/test_bug20_codex_appserver.py`
- Provider fallback/result-shaping tests:
  - `tests/test_provider_routing.py`
- Config loader round-trip coverage:
  - `tests/test_config_v18_loader_gaps.py`
- Live app-server integration:
  - `tests/test_codex_appserver_live.py`

`tests/test_phase_h3d_sandbox_fix.py` is a reasonable new file for H3d-specific router assertions if keeping provider tests isolated is cleaner than extending `test_provider_routing.py`.

## Halt Review

No discovery halt condition fired.

- Upstream docs and source both point to `thread/start.params.sandbox` for the primary fix.
- The local live probe confirmed that `thread/start.params.sandbox` is the right field, while also proving the installed runtime expects kebab-case enum values on the wire.
- `turn/start` still supports richer per-turn sandbox overrides, but that is not required for the primary fix.
- The runtime result object is mutable.
- Existing captures already expose the resolved sandbox, so no H3d capture-schema change is required.
