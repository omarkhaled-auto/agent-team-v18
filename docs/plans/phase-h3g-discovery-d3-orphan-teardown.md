# Phase H3g Discovery - D3 Orphan Teardown

## Verdict

Proceed. No HALT.

## Landmarks

- `tests/test_codex_appserver_live.py:25-98`
- `src/agent_team_v15/codex_appserver.py:296-316`
- `src/agent_team_v15/codex_appserver.py:386-499`

## Current Shape

- The live tests start a real `_CodexAppServerClient` directly.
- `test_app_server_thread_start_real_codex` creates a client at `tests/test_codex_appserver_live.py:32`, calls `await client.start()`, and only archives the thread on the happy path at `:70`.
- Both live tests rely on `await client.close()` in `finally` for teardown at `:97` and `:151`.

## Root Cause

- The app-server transport launches through `_spawn_appserver_process()` in `codex_appserver.py:296-316`.
- On Windows, `.cmd` / `.bat` launchers use `asyncio.create_subprocess_shell()` (`codex_appserver.py:299-307`), which can leave a descendant `node.exe` / `codex.exe` alive after the parent shell exits.
- `close()` waits for the parent process and only escalates to `_terminate_subprocess()` on timeout (`codex_appserver.py:495-499`).
- `_terminate_subprocess()` does a tree-kill on Windows only after the wait path fails (`codex_appserver.py:414-438`).
- That means teardown can look successful from Python while a descendant `codex.exe` survives.

## Recommended Fix Shape

Prefer the smallest test-scoped cleanup for H3g:

1. Add a live-test fixture/helper that tracks spawned app-server PIDs.
2. Move `thread_archive()` into unconditional teardown when `thread_id` exists.
3. After `await client.close()`, do a Windows-only best-effort tree kill for any tracked PID that may still have descendants.

This closes the observed smoke nuisance without changing production behavior.

## Notes

- Discovery suggests the deeper weakness is in transport teardown, not pytest itself.
- H3g scope can still stay test-only by adding explicit cleanup in the live fixture rather than broadening `codex_appserver.py`.
