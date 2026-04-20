# Proof 03 - Live Codex Write Test

## Goal

Prove end-to-end that the H3d transport fix allows real Codex app-server dispatches to write files into the workspace when the sandbox flag is enabled.

## Sources Under Test

- `src/agent_team_v15/codex_appserver.py:345-355`
- `src/agent_team_v15/codex_appserver.py:666-669`
- `tests/test_codex_appserver_live.py:87-150`

## Durable Artifacts

- Pytest output: [pytest-output-codex-live.txt](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/pytest-output-codex-live.txt)
- Live summary: [summary.json](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-03-live-run/summary.json)
- Protocol log: [phase-h3d-proof03-wave-B-protocol.log](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-03-live-run/.agent-team/codex-captures/phase-h3d-proof03-wave-B-protocol.log)
- Response capture: [phase-h3d-proof03-wave-B-response.json](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-03-live-run/.agent-team/codex-captures/phase-h3d-proof03-wave-B-response.json)
- Written file: [h3d_live_test.txt](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-03-live-run/h3d_live_test.txt)

## Pytest Result

```text
tests/test_codex_appserver_live.py::test_app_server_thread_start_real_codex PASSED [ 50%]
tests/test_codex_appserver_live.py::test_app_server_execute_codex_writes_file_with_workspace_write_sandbox PASSED [100%]

=============== 2 passed, 1 skipped, 11265 deselected in 35.59s ===============
```

## Stable Live Run Summary

```json
{
  "success": true,
  "duration_seconds": 24.17,
  "cost_usd": 0.01208,
  "final_message": "WROTE",
  "target_exists": true,
  "target_content": "hello"
}
```

## `thread/start` Request Proof

```text
2026-04-20T13:37:51.141Z OUT 260 {"jsonrpc":"2.0","id":2,"method":"thread/start","params":{"cwd":"C:\\Projects\\agent-team-v18-codex\\v18 test runs\\phase-h3d-validation\\proof-03-live-run","model":"gpt-5.4-mini","approvalPolicy":"never","personality":"pragmatic","sandbox":"workspace-write"}}
```

## `thread/started` Sandbox Echo

The same live capture returned a non-read-only sandbox in the app-server response:

```text
"sandbox":{"type":"workspaceWrite",...,"networkAccess":false,...}
```

## Write Evidence

The protocol log shows a real file-write event:

```text
2026-04-20T13:38:13.924Z IN ... "type":"fileChange" ... "path":"C:\\Projects\\agent-team-v18-codex\\v18 test runs\\phase-h3d-validation\\proof-03-live-run\\h3d_live_test.txt" ... "kind":{"type":"add"}
2026-04-20T13:38:13.958Z IN ... "delta":"Success. Updated the following files:\nA h3d_live_test.txt\n"
```

Resulting file content:

```text
hello
```

## Cost And Runtime

- Stable direct live proof: `24.17s`, `$0.01208`
- Guard rails requested by the H3d brief are satisfied:
  - runtime under `30s`
  - cost under `$0.05`

## Verdict

H3d's primary fix works end-to-end on the installed Codex `0.121.0` app-server. The request carries `sandbox:"workspace-write"`, the server resolves the sandbox to `workspaceWrite`, and Codex writes the file on disk.
