# Phase H3d Sandbox Schema Verification

Date: 2026-04-20

## Verification method

The brief requested `context7` and `sequential-thinking`. Those MCPs are not available in this Codex session, so this verification uses primary sources instead:

- OpenAI Developers app-server docs
- `openai/codex` app-server README
- `openai/codex` source snippets surfaced from `codex-rs/exec/src/lib.rs`
- `openai/codex` issue `#15310`

## Verified conclusions

### 1. `thread/start` accepts top-level `sandbox`

Verified by:

- OpenAI Developers app-server docs example:
  - `thread/start` includes `"sandbox": "workspaceWrite"`
- `openai/codex` app-server README example:
  - same top-level `sandbox` string
- `openai/codex` source:
  - `thread_start_params_from_config(...)` sets `sandbox: sandbox_mode_from_policy(...)`

Conclusion:

- H3d primary fix should send `params["sandbox"] = ...` on `thread/start`
- The docs/examples use camelCase in prose, but the installed Codex `0.121.0` app-server rejects camelCase on the wire and expects kebab-case enums

### 2. `turn/start` uses a different override surface

Verified by:

- app-server README lifecycle overview: `turn/start` allows sandbox policy overrides per turn
- `openai/codex` issue `#15310`: interactive flows can later send `turn/start { sandbox_policy: ... }`

Conclusion:

- `thread/start.sandbox` and `turn/start sandboxPolicy` are distinct protocol surfaces
- H3d does not need to redesign around `turn/start` unless a later smoke proves `thread/start.sandbox` is ignored in practice

### 3. Omission of `thread/start.sandbox` falls back to layered config / trust defaults

Verified by:

- `openai/codex` issue `#15310`
- H3c preserved protocol capture:
  - request omitted `sandbox`
  - response resolved `sandbox.type` to `readOnly`

Conclusion:

- The H3c smoke failure matches upstream behavior exactly
- The missing `sandbox` parameter is a real root cause, not an instrumentation artifact

### 4. Valid string values for H3d

Verified by:

- OpenAI app-server docs / README examples and surrounding prose
- current app-server naming convention in captured protocol and source

Config-facing values accepted by H3d:

- `readOnly`
- `workspaceWrite`
- `dangerFullAccess`
- their kebab-case aliases

Wire values actually accepted by the installed app-server:

- `read-only`
- `workspace-write`
- `danger-full-access`

Verified by live probe:

- the first live H3d dispatch failed with:
  - `unknown variant 'workspaceWrite', expected one of 'read-only', 'workspace-write', 'danger-full-access'`

Conclusion:

- H3d should keep the operator-facing config on the documented camelCase names for compatibility
- H3d must normalize those values to kebab-case before serializing the JSON-RPC payload
- object payloads still do not belong in `thread/start.sandbox`

### 5. Response observability is already sufficient

Verified by:

- H3c protocol capture line showing `thread/start` response with:
  - `"sandbox":{"type":"readOnly","access":{"type":"fullAccess"},"networkAccess":false}`
- existing protocol-shape unit test fixture in `tests/test_bug20_codex_appserver.py`

Conclusion:

- the effective sandbox is already visible in raw H3a protocol captures
- H3d does not require a capture schema change to prove whether the fix fired

## H3d implementation decision

Ship:

- `thread/start.params.sandbox` when `codex_sandbox_writable_enabled=True`
- runtime whitelist validation for `codex_sandbox_mode`
- router-level `BLOCKED:` failure interception before the success/no-diff gate

Do not ship in H3d:

- a `turn/start sandboxPolicy` redesign
- new capture schema fields
- `CodexResult` wrapper types or immutable-copy workarounds

## Smoke-time assertion checklist

The paid smoke should confirm:

1. `thread/start` request includes `"sandbox":"workspace-write"`
2. `thread/start` response resolves to non-read-only sandbox metadata
3. write-capable tool invocations occur
4. files land on disk in the target cwd

If the request includes `sandbox: "workspace-write"` but the response still resolves to `readOnly`, that is an H3d amendment case, not evidence that the local insertion point was wrong.
