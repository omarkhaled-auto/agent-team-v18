# Phase H2a - Codex Config Schema + App-Server Transport - Final Report

**Branch:** `phase-h2a-codex-app-server-migration`
**Base SHA:** `b27825b` (`origin/integration-2026-04-15-closeout` current HEAD)
**Date:** 2026-04-20
**Orchestrator:** Codex GPT-5

## Implementation Summary

Phase H2a closes the two Codex hot-path failures identified in discovery:

1. **Bug #21 - invalid project `.codex/config.toml` schema.**
   The project snippet now emits top-level `project_doc_max_bytes = 65536` instead of the invalid `[features]` form, with shared helper wiring through `codex_cli.py` and `constitution_templates.py`.
2. **Bug #20 - broken app-server transport.**
   `src/agent_team_v15/codex_appserver.py` no longer assumes a nonexistent `codex_app_server` Python SDK. It now drives the canonical `codex app-server --listen stdio://` subprocess using JSON-RPC over stdio.

The public transport surface stays intact where callers expect it:
- `execute_codex(...)`
- `is_codex_available()`
- `CodexConfig`
- `CodexResult`
- orphan watchdog / `turn/interrupt` behavior

The internal SDK-shaped transport is gone.

## Coverage Matrix

| Item | Failure pattern | Implementation | Verification | Status |
|---|---|---|---|---|
| Bug #21 | `.codex/config.toml` emits invalid `[features] project_doc_max_bytes` for `codex-cli 0.121.0` | `constitution_templates.py` delegates to shared top-level-key renderer in `codex_cli.py` | `tests/test_codex_config_snippet.py`, `tests/test_constitution_writer.py`, `tests/test_constitution_templates.py` | PASS |
| Bug #21 review fix | existing `codex exec` path still resolves Windows-safe binary / version / prefixed errors through shared helper layer | `codex_transport.py` imports `resolve_codex_binary`, `log_codex_cli_version`, `prefix_codex_error_code` from `codex_cli.py` | targeted Bug #21 suite below | PASS |
| Bug #20 transport | nonexistent `codex_app_server` dependency breaks `app-server` route before dispatch | `codex_appserver.py` now spawns `codex app-server --listen stdio://` directly | `tests/test_bug20_codex_appserver.py::test_execute_codex_handles_real_protocol_shapes` | PASS |
| Bug #20 framing | wrong protocol framing would hang or stderr-fail app-server | newline-delimited JSON-RPC messages on stdio | `tests/test_bug20_codex_appserver.py::test_transport_serializes_newline_delimited_jsonrpc` plus live probe evidence | PASS |
| Bug #20 error surface | JSON-RPC error objects and subprocess death were previously unmodeled | request errors mapped to Python exceptions; mid-request process death surfaced with stderr/exit context | `test_transport_raises_jsonrpc_error_response`, `test_transport_surfaces_subprocess_death_mid_request` | PASS |
| Bug #20 auth | unclear whether a handshake was required | auth remains inherited from `CODEX_HOME` / environment; `initialize` sends only `clientInfo` + `capabilities` | `test_client_inherits_auth_from_environment_without_rpc_handshake` plus live initialize response | PASS |
| Bug #20 live dispatch | mocked SDK tests were not proof of the canonical path | new `@pytest.mark.codex_live` test runs a real app-server turn and archives the thread | `tests/test_codex_appserver_live.py` | PASS |

## Test Results

### Full suite

- Baseline before H2a: **11,192 passed, 35 skipped, 0 failed** (`phase-h1b` closeout).
- Current default H2a run: **11,176 passed, 35 skipped, 1 deselected, 0 failed**.
- Command: `pytest tests/ -q`

### Test-count reconciliation

- Old `integration-2026-04-15-closeout:tests/test_bug20_codex_appserver.py`: **21** tests.
- New `tests/test_bug20_codex_appserver.py`: **5** tests.
- New `tests/test_codex_appserver_live.py`: **1** test.
- Net collected-test delta in tree: `21 -> 6`, so **-15** tests.
- Default-run passed delta: `11,192 -> 11,176`, so **-16** passes.
- Reconciliation: **-15 collected tests** plus **1 new `codex_live` test that is deselected by default** equals **-16 passed**. This is expected, not a regression.

### Targeted Bug #21 verification

- Command: `pytest tests/test_codex_config_snippet.py tests/test_constitution_writer.py tests/test_constitution_templates.py -v`
- Result: **22 passed in 0.28s**

### Live app-server verification

- Command: `pytest tests/ -v -m codex_live --tb=short`
- Result: **1 passed, 1 skipped, 11210 deselected in 13.01s**
- Matching real transport cost: **$0.039506**

## Wiring Verification

- `cli.py` still selects `agent_team_v15.codex_appserver` when `codex_transport_mode == "app-server"` and `agent_team_v15.codex_transport` when mode is `exec`.
- No production caller imports the abandoned `codex_app_server` SDK shape.
- Provider-routed Codex dispatch, compile-fix dispatch, and A.5/T.5 dispatch all continue to call `execute_codex(...)`; no wave-dispatch rewiring was required.
- Claude fallback policy is unchanged. Transport failures surface from `codex_appserver.py`; fallback remains a caller-layer concern in existing routing code.
- Phase F orphan handling remains intact:
  - `_send_turn_interrupt` still exists and is async.
  - `_monitor_orphans` still exists and is async.
  - `_process_streaming_event` still avoids orphan registration regressions.

## Failure-Pattern Coverage

| Prior failure | Root cause | H2a closure |
|---|---|---|
| `codex-cli` rejects generated project config | `project_doc_max_bytes` emitted under `[features]` instead of as a top-level integer | Bug #21 moved emission to the canonical top-level key and locked it with 22 targeted tests |
| `app-server` route cannot run at all | `codex_appserver.py` imported a nonexistent Python SDK | Bug #20 replaced that with a subprocess JSON-RPC client over stdio |
| app-server tests were false proof | tests only monkeypatched a fake SDK module | Bug #20 replaced them with protocol-level subprocess tests and a real `codex_live` integration test |
| protocol assumptions were undocumented | framing/method/auth/error handling were guessed by prior code | H2a verified newline-delimited JSON-RPC, `initialize` / `thread/start` / `turn/start` / `turn/interrupt` / `thread/archive`, inherited auth, and JSON-RPC/subprocess error modes against real `codex-cli 0.121.0` |

## Branch Status Checklist

- [x] `codex_appserver.py` no longer imports `codex_app_server`
- [x] Fake-SDK tests removed from `tests/test_bug20_codex_appserver.py`
- [x] `tests/test_codex_appserver_live.py` added with `@pytest.mark.codex_live`
- [x] `pyproject.toml` registers `codex_live` and excludes it from default pytest runs
- [x] Full default pytest suite green: `11176 passed, 35 skipped, 1 deselected`
- [x] Live app-server pytest green: `1 passed, 1 skipped, 11210 deselected`
- [x] Live cost under both gates: `$0.039506 < $0.05 < $0.20`
- [x] Bug #21 targeted tests green: `22 passed`
- [x] No Bug #20 code changes in wave dispatch, Claude fallback logic, or Bug #21-owned source files
- [x] Current `HEAD` still equals integration base `b27825b`; all H2a changes are presently worktree edits, not new commits
- [ ] Stage and commit the H2a worktree
- [ ] Reviewer approval
- [ ] Merge to `integration-2026-04-15-closeout`

## Current Worktree Partition

### Bug #21 worker work

- `src/agent_team_v15/codex_cli.py` (new, untracked)
- `src/agent_team_v15/constitution_templates.py`
- `tests/test_codex_config_snippet.py`
- `tests/test_constitution_templates.py`
- `tests/test_constitution_writer.py`

### Review delegation fix

- `src/agent_team_v15/codex_transport.py`

This is the thin follow-up that routes the existing `codex exec` transport through the shared `codex_cli.py` helpers.

### Bug #20 worker work

- `src/agent_team_v15/codex_appserver.py`
- `tests/test_bug20_codex_appserver.py`
- `tests/test_codex_appserver_live.py` (new, untracked)
- `pyproject.toml`

### Anything else

- `docs/plans/phase-h2a-architecture-report.md`
- `docs/plans/phase-h2a-codex-config-schema.md`
- `docs/plans/phase-h2a-codex-sdk-decision.md`
- `docs/plans/phase-h2a-discovery-citations.md`
- `docs/plans/phase-h2a-report.md`
- `runs/phase-h2a-validation/proof-05-codex-live-integration-dispatch.md`
- `ProjectsArkanPM_Websitepublicimagesgenerated/`

These are outside the four-file Bug #20 implementation scope. They either ride intentionally as H2a discovery/support artifacts or should be stripped before merge.

## Handoff Notes for H2b

- Keep `codex_live` opt-in. The default pytest path should continue to run with `-m "not codex_live"` and the live gate should stay explicit.
- Treat app-server framing as newline-delimited JSON over stdio. Do not switch to LSP-style `Content-Length` framing unless upstream documentation changes and live probes confirm it.
- The validated JSON-RPC surface for current `codex-cli 0.121.0` is: `initialize`, `thread/start`, `turn/start`, `turn/interrupt`, `thread/archive`, plus streamed notifications such as `thread/started`, `turn/started`, `item/agentMessage/delta`, `thread/tokenUsage/updated`, `turn/completed`, and cleanup status changes.
- Auth is currently implicit via inherited `CODEX_HOME` / `~/.codex/auth.json` / environment. No explicit JSON-RPC auth handshake was required in H2a.
- Before merge, decide explicitly whether the untracked discovery docs and unrelated asset directory belong in the PR. They are visible in `git status` and are not part of the narrow Bug #20 code scope.
