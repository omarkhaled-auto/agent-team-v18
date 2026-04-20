# Proof 02: APP-SERVER-TEARDOWN-001

## Original Smoke Failure

Combined-smoke evidence:

- `codex-processes-final.txt`
  - `codex.exe                    36704 Console                    1     12,392 K`

This showed the Codex app-server parent surviving after the pipeline had already finished.

## Source Change

Primary source updates:

- `src/agent_team_v15/codex_transport.py:45, 49-50`
  - `CodexConfig` now carries `orphan_timeout_seconds`, `turn_interrupt_message_refined_enabled`, and `app_server_teardown_enabled`
- `src/agent_team_v15/codex_appserver.py:461-503`
  - `_perform_app_server_teardown(...)` added
- `src/agent_team_v15/codex_appserver.py:541-549`
  - transport start records `_use_shell` and tracked `_app_server_pid`
- `src/agent_team_v15/codex_appserver.py:566-585`
  - transport close is flag-gated: tracked teardown when on, legacy wait path when off
- `src/agent_team_v15/codex_appserver.py:714-719`
  - `app_server_teardown_enabled` is threaded into the app-server client transport
- `src/agent_team_v15/config.py:982-986, 2892-2898`
  - new flag: `codex_app_server_teardown_enabled`
- `src/agent_team_v15/cli.py:3597-3600`
  - CLI wiring threads the flag into `CodexConfig`

Diff excerpt:

```diff
+ if self._app_server_teardown_enabled:
+     await _perform_app_server_teardown(
+         self.process,
+         pid=self._app_server_pid,
+         use_shell=self._use_shell,
+     )
+ else:
+     await asyncio.wait_for(self.process.wait(), timeout=_PROCESS_TERMINATION_TIMEOUT_SECONDS)
```

## Production-Caller Proof

Invocation:

```text
pytest tests/test_h3h_app_server_teardown.py::test_transport_close_uses_tracked_teardown_when_flag_enabled tests/test_h3h_app_server_teardown.py::test_transport_close_preserves_legacy_path_when_flag_disabled tests/test_h3h_app_server_teardown.py::test_transport_close_terminates_real_subprocess_when_flag_enabled -v --tb=short
```

Output:

```text
tests/test_h3h_app_server_teardown.py::test_transport_close_uses_tracked_teardown_when_flag_enabled PASSED
tests/test_h3h_app_server_teardown.py::test_transport_close_preserves_legacy_path_when_flag_disabled PASSED
tests/test_h3h_app_server_teardown.py::test_transport_close_terminates_real_subprocess_when_flag_enabled PASSED
============================== 3 passed in 0.18s ==============================
```

What this proves:

- tracked PID teardown is used when the flag is on
- the old close path is still used when the flag is off
- a real spawned Python subprocess is terminated through the production transport close path

## Flag-Off Verification

`test_transport_close_preserves_legacy_path_when_flag_disabled` asserts `_perform_app_server_teardown(...)` is not called and the transport stays on the legacy `process.wait()` path.
