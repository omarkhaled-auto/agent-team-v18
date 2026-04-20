# Proof 01 - Sandbox Param In `thread/start`

## Goal

Prove that H3d adds the `sandbox` key to the `thread/start` JSON-RPC payload only when `codex_sandbox_writable_enabled=True`, and leaves the payload unchanged when the flag is off.

## Source Under Test

- `src/agent_team_v15/codex_appserver.py:345-355`
- `src/agent_team_v15/codex_appserver.py:666-669`
- `tests/test_bug20_codex_appserver.py:650-748`

## Repro Artifact

- JSON capture: [proof-01-sandbox-request.json](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-01-sandbox-request.json)
- Diff: [proof-01-sandbox-request.diff.txt](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-01-sandbox-request.diff.txt)

## Flag ON Request

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "thread/start",
  "params": {
    "cwd": "C:\\Projects\\agent-team-v18-codex\\v18 test runs\\phase-h3d-validation\\proof-01-temp\\on",
    "model": "gpt-5.4",
    "approvalPolicy": "never",
    "personality": "pragmatic",
    "sandbox": "workspace-write"
  }
}
```

## Flag OFF Request

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "thread/start",
  "params": {
    "cwd": "C:\\Projects\\agent-team-v18-codex\\v18 test runs\\phase-h3d-validation\\proof-01-temp\\off",
    "model": "gpt-5.4",
    "approvalPolicy": "never",
    "personality": "pragmatic"
  }
}
```

## Request Diff

```diff
--- flag_off
+++ flag_on
@@ -3,9 +3,10 @@
   "id": 2,
   "method": "thread/start",
   "params": {
-    "cwd": "C:\\Projects\\agent-team-v18-codex\\v18 test runs\\phase-h3d-validation\\proof-01-temp\\off",
+    "cwd": "C:\\Projects\\agent-team-v18-codex\\v18 test runs\\phase-h3d-validation\\proof-01-temp\\on",
     "model": "gpt-5.4",
     "approvalPolicy": "never",
-    "personality": "pragmatic"
+    "personality": "pragmatic",
+    "sandbox": "workspace-write"
   }
 }
```

## Verdict

The primary fix fires at the correct insertion point. With the flag on, `thread/start` carries the write-capable sandbox. With the flag off, the payload remains byte-identical except for the test cwd.
