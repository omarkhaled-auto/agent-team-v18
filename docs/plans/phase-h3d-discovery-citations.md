# Phase H3d Discovery Citations

## Local code citations

### App-server request construction

- `src/agent_team_v15/codex_appserver.py:637-644` builds the `thread/start` params dict.
- `src/agent_team_v15/codex_appserver.py:646-653` builds the `turn/start` params dict.
- `src/agent_team_v15/codex_appserver.py:947-955` receives the `thread/start` response before any turn begins.

### Config and plumbing

- `src/agent_team_v15/config.py:943-957` contains the current H3c flag block in `V18Config`.
- `src/agent_team_v15/config.py:2798-2832` shows the `_dict_to_config(...)` loader pattern for H3c flags.
- `src/agent_team_v15/cli.py:3537-3548` constructs `CodexConfig` and uses `setattr(...)` for H3c app-server flag threading.

### Provider routing / fallback

- `src/agent_team_v15/provider_router.py:342-352` awaits `execute_codex(...)`.
- `src/agent_team_v15/provider_router.py:399-453` is the success path and zero-diff fallback gate.
- `src/agent_team_v15/provider_router.py:455-470` is the failure rollback + `_claude_fallback(...)` path.

### Result type

- `src/agent_team_v15/codex_transport.py:65-85` defines mutable `CodexResult` fields, including `final_message` and `error`.

### Existing tests

- `tests/test_bug20_codex_appserver.py:245-426` exercises realistic app-server protocol shapes and already models `thread/start.result.sandbox`.
- `tests/test_bug20_codex_appserver.py:428-618` covers H3c cwd propagation behavior and the same request-capture style H3d can extend.
- `tests/test_provider_routing.py:1295-1334` covers the current success-with-no-changes fallback behavior.
- `tests/test_config_v18_loader_gaps.py:29-84` is the round-trip/defaults coverage surface for new v18 flags.
- `tests/test_codex_appserver_live.py:21-96` is the existing live app-server integration test surface.

## Preserved H3c evidence

- `v18 test runs/phase-h3c-validation-smoke-20260420-114825/H3C_SMOKE_ROOT_CAUSE.md`
- `v18 test runs/phase-h3c-validation-smoke-20260420-114825/codex-captures-at-kill/milestone-1-wave-B-protocol.log`
- `v18 test runs/phase-h3c-validation-smoke-20260420-114825/codex-captures-at-kill/milestone-1-wave-B-response.json`
- `docs/plans/phase-h3c-architecture-report.md`
- `docs/plans/phase-h3c-discovery-citations.md`

## External primary sources

### OpenAI app-server docs

- OpenAI Developers, App Server docs:
  - `https://developers.openai.com/codex/app-server`
  - thread/start example with top-level `sandbox: "workspaceWrite"` and `approvalPolicy`:
    - lines 426-433 in the current docs render

### openai/codex source and issue trail

- `openai/codex` app-server README:
  - `https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md`
  - thread/start example with top-level `sandbox: "workspaceWrite"`:
    - lines 426-433 in the current README render
  - turn/start overview saying sandbox policy can be overridden per turn:
    - lines 307-311

- `openai/codex` exec transport source:
  - `https://github.com/openai/codex/blob/main/codex-rs/exec/src/lib.rs`
  - `thread_start_params_from_config(...)` sets `sandbox: sandbox_mode_from_policy(...)`
  - `turn/start` is handled separately later in the file

- `openai/codex` issue `#15310`:
  - `https://github.com/openai/codex/issues/15310`
  - documents the exact failure mode caused by omitting `thread/start.params.sandbox`
  - explicitly contrasts `thread/start { sandbox: ... }` with later `turn/start { sandbox_policy: ... }`

## Empirical runtime citation

- Local live H3d probe via `tests/test_codex_appserver_live.py`:
  - first probe failed with:
    - `unknown variant 'workspaceWrite', expected one of 'read-only', 'workspace-write', 'danger-full-access'`
  - second probe, after normalizing the wire value to `workspace-write`, successfully wrote the target file under the app-server transport

## Discovery conclusion

The repo-local code and upstream primary sources agree on the same fix:

- add `sandbox` to `thread/start`
- do not replace that with a `turn/start sandboxPolicy` redesign
- treat `BLOCKED:` as a router-level failure signal before the existing success/no-diff gate
- normalize documented camelCase sandbox names to the runtime's kebab-case wire values before dispatch
