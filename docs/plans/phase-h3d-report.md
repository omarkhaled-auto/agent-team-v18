# Phase H3d - Codex Sandbox Parameter Fix - Final Report (Pre-Smoke)

## Implementation Summary

- Primary fix: `thread/start` now sends `sandbox` when `codex_sandbox_writable_enabled=True`.
- Runtime compatibility fix: config-facing camelCase sandbox names are normalized to the installed Codex `0.121.0` wire enums (`workspace-write`, `read-only`, `danger-full-access`).
- Defense-in-depth: router-level `BLOCKED:` interception now flips `success=True` to failure when `codex_blocked_prefix_as_failure_enabled=True`.
- Config: added `codex_sandbox_writable_enabled`, `codex_sandbox_mode` (default `workspace-write`), and `codex_blocked_prefix_as_failure_enabled`.
- Pattern ID: added `CODEX-WAVE-B-BLOCKED-001`.
- Mechanical test maintenance: updated `tests/test_walker_sweep_complete.py` allow-list line number for the existing safe `.agent-team/` walker in `cli.py` after H3d shifted that file by 10 lines.

## Coverage Matrix

| Fix | Site | Flag | Pattern ID | Verification |
|---|---|---|---|---|
| Primary | `codex_appserver.py` `thread/start` params | `codex_sandbox_writable_enabled` | — | unit capture proof + live codex write test |
| Runtime enum normalization | `codex_appserver.py` sandbox helper | `codex_sandbox_writable_enabled` | — | invalid-value unit test + live probe |
| Defense | `provider_router.py` before success/no-diff gate | `codex_blocked_prefix_as_failure_enabled` | `CODEX-WAVE-B-BLOCKED-001` | mock-based router proof |

## Test Results

- Focused H3d unit ring: `43 passed`
- Provider routing regression ring: `4 passed`
- Walker-sweep invariant after line-drift correction: `3 passed`
- Full default suite: `11231 passed, 35 skipped, 2 deselected, 16 warnings`
- `codex_live`: `2 passed, 1 skipped, 11265 deselected`
- Stable direct live proof: success, `24.17s`, `$0.01208`, file written on disk

## Wiring Verification

- H2a/H2bc/H3a/H3c source files remain unchanged.
- `_claude_fallback(...)` remains untouched; H3d inserts before the existing success branch.
- No module-global cross-run state was added.
- Scope note: `tests/test_walker_sweep_complete.py` changed only to update the exact-line allow-list entry tied to the shifted `cli.py` safe walker.

## Production-Caller Proofs

- [proof-01-sandbox-param-in-thread-start.md](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-01-sandbox-param-in-thread-start.md)
- [proof-02-blocked-prefix-interception.md](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-02-blocked-prefix-interception.md)
- [proof-03-live-codex-write-test.md](/C:/Projects/agent-team-v18-codex/v18%20test%20runs/phase-h3d-validation/proof-03-live-codex-write-test.md)

## Pending

- paid validation smoke only

## Predicted Smoke Outcome

Wave B should send `sandbox: "workspace-write"` in `thread/start`, resolve to a non-read-only sandbox in `thread/started`, write files into the working directory, and advance to Wave C.
