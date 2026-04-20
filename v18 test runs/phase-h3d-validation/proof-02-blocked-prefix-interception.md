# Proof 02 - BLOCKED Prefix Interception

## Goal

Prove that H3d converts a `success=True` Codex result into a failure when the final assistant message begins with `BLOCKED:`, and that the legacy zero-diff fallback remains unchanged when the flag is off.

## Source Under Test

- `src/agent_team_v15/provider_router.py:400-413`
- `tests/test_phase_h3d_sandbox_fix.py:44-216`

## Repro Artifact

- JSON capture: [proof-02-blocked-interception.json](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-02-blocked-interception.json)
- Diff: [proof-02-blocked-interception.diff.txt](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-02-blocked-interception.diff.txt)

## Flag ON Result

```json
{
  "codex_result": {
    "success": false,
    "error": "BLOCKED: workspace read-only",
    "final_message": "BLOCKED: workspace read-only"
  },
  "router_result": {
    "cost": 0.13,
    "provider": "claude",
    "provider_model": "claude-sonnet-4-6",
    "fallback_used": true,
    "fallback_reason": "Codex failed: BLOCKED: workspace read-only",
    "retry_count": 0,
    "input_tokens": 400,
    "output_tokens": 120,
    "reasoning_tokens": 30
  }
}
```

## Flag OFF Result

```json
{
  "codex_result": {
    "success": true,
    "error": "",
    "final_message": "BLOCKED: workspace read-only"
  },
  "router_result": {
    "cost": 0.13,
    "provider": "claude",
    "provider_model": "claude-sonnet-4-6",
    "fallback_used": true,
    "fallback_reason": "Codex reported success but produced no tracked file changes",
    "retry_count": 0,
    "input_tokens": 400,
    "output_tokens": 120,
    "reasoning_tokens": 30
  }
}
```

## Behavioral Diff

```diff
--- flag_off
+++ flag_on
@@ -1,7 +1,7 @@
 {
   "codex_result": {
-    "success": true,
-    "error": "",
+    "success": false,
+    "error": "BLOCKED: workspace read-only",
     "final_message": "BLOCKED: workspace read-only"
   },
   "router_result": {
@@ -9,7 +9,7 @@
     "provider": "claude",
     "provider_model": "claude-sonnet-4-6",
     "fallback_used": true,
-    "fallback_reason": "Codex reported success but produced no tracked file changes",
+    "fallback_reason": "Codex failed: BLOCKED: workspace read-only",
     "retry_count": 0,
     "input_tokens": 400,
     "output_tokens": 120,
```

## Warning Emission

The interception path emits the new pattern ID:

```text
CODEX-WAVE-B-BLOCKED-001: Codex emitted BLOCKED signal; treating as failure despite success=true. Reason: BLOCKED: workspace read-only
```

## Verdict

The defense-in-depth hook works as designed. Flag on: `BLOCKED:` becomes a structured failure before the legacy success/no-diff gate. Flag off: legacy behavior is preserved.
