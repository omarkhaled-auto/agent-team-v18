# H3h Wiring Verification

## Scope

Read-only verification against the final H3h worktree in `C:/Projects/agent-team-v18-codex-h3h`.

Audited source files:

- `src/agent_team_v15/codex_appserver.py`
- `src/agent_team_v15/codex_transport.py`
- `src/agent_team_v15/cli.py`
- `src/agent_team_v15/state.py`
- `src/agent_team_v15/scaffold_runner.py`
- `src/agent_team_v15/config.py`

Smoke artifacts cross-checked from:

- `C:/Projects/agent-team-v18-codex-h2a-merge/v18 test runs/phase-combined-h3e-h3f-h3g-validation-20260421-002534/`

Verdict:

- `INTERRUPT-MSG-REFINE-001`: verified
- `APP-SERVER-TEARDOWN-001`: verified
- `STATE-FINALIZE-INVARIANT-001/-002`: verified
- `SCAFFOLD-CTX-001`: verified
- prior-phase diff audit: clean, additive only

## Pattern Execution Mapping

| Pattern ID | Source | Execution position | Result |
| --- | --- | --- | --- |
| `INTERRUPT-MSG-REFINE-001` | `codex_appserver.py:1044-1074`, `:1171-1183` | orphan detected, `turn/interrupt` sent, interrupted turn returns, corrective prompt chosen before next `turn/start` | verified |
| `APP-SERVER-TEARDOWN-001` | `codex_appserver.py:461-503`, `:541-585`, `:1222-1227` | tracked PID recorded at transport start; teardown runs inside transport close before `_execute_once()` returns a result | verified |
| `STATE-FINALIZE-INVARIANT-001` | `cli.py:1785-1792`, `:1831-1837`, `:5155-5164`, `:5180-5188`, `:5206-5215`, `:12442-12450`; `state.py:543-551` | finalize helper runs before intermediate saves when flag on; `save_state()` adds a second guard; final normal-completion save still calls `RunState.finalize()` directly | verified |
| `STATE-FINALIZE-INVARIANT-002` | `state.py:98-120`, `:543-551`; `cli.py:15588-15612` | existing `RunState.finalize()` remains behaviorally idempotent and is safe to call again on the final save path | verified |
| `SCAFFOLD-CTX-001` | `scaffold_runner.py:933-959`, `:1148-1219` | compose template switches to repo-root web build context only when flag on; legacy template remains default | verified |

## 4A. Interrupt Message Refinement

Verified call order:

1. `item/started` records the command summary into the orphan watchdog at `codex_appserver.py:922-934`.
2. `_monitor_orphans()` detects the stalled item and sends `turn/interrupt` at `codex_appserver.py:806-839`.
3. `_wait_for_turn_completion()` returns the interrupted turn at `codex_appserver.py:995-1033`.
4. `_execute_once()` branches on `turn_status == "interrupted"` at `codex_appserver.py:1171-1183`.
5. With `turn_interrupt_message_refined_enabled=True`, `_build_turn_interrupt_prompt(...)` is used at `codex_appserver.py:1180-1181`.
6. The retry loop restarts the turn via `client.turn_start(...)` at `codex_appserver.py:1126-1129`.

This is the correct placement: after orphan detection and before Turn 2 starts.

## 4B. App-Server Teardown

Verified execution position:

1. `_CodexJSONRPCTransport.start()` records the tracked PID and shell mode at `codex_appserver.py:541-549`.
2. `_execute_once()` always closes the client in `finally` at `codex_appserver.py:1222-1227`.
3. `client.close()` delegates into transport close at `codex_appserver.py:731-732`.
4. With `codex_app_server_teardown_enabled=True`, transport close calls `_perform_app_server_teardown(...)` at `codex_appserver.py:566-580`.
5. Only after that close path completes does `_execute_once()` finish result bookkeeping and return at `codex_appserver.py:1228-1240`.

Ordering note:

- there is no separate child-PID registry inside the app-server transport surface
- on Windows shell launches, the implementation uses `taskkill /T /F` against the tracked app-server PID at `codex_appserver.py:474-480`
- that collapses child cleanup plus parent cleanup into one coordinated tree teardown, rather than two explicit loops

The important contract is still met: teardown happens in the coordinated app-server close path before Wave B result persistence.

## 4C. Exit Path x Finalize Checklist

| Exit / write path | Source | Finalize present? | Notes |
| --- | --- | --- | --- |
| wave callback save | `cli.py:1785-1792` | yes, flag-gated | `_save_wave_state()` |
| isolated worktree wave save | `cli.py:1831-1837` | yes, flag-gated | `_save_isolated_wave_state()` |
| milestone timeout | `cli.py:5155-5164` | yes, flag-gated | runs before `save_state()` |
| milestone keyboard interrupt | `cli.py:5180-5188` | yes, flag-gated | also sets `interrupted = True` |
| milestone exception | `cli.py:5206-5215` | yes, flag-gated | original failure still surfaces |
| post-orchestration best-effort save | `cli.py:12442-12450` | yes, flag-gated | catches save exceptions |
| final normal completion save | `cli.py:15588-15612` | yes, unconditional legacy path | H3h preserved and kept loud logging |
| any flagged `save_state()` caller | `state.py:543-551` | yes, flag-gated | secondary safety net at persistence boundary |

Conclusion:

- every H3h-relevant non-final write path now has an explicit finalize call site
- `save_state()` adds a second guard when the flag is on
- the final completion write keeps the pre-existing direct `finalize()` path

## 4D. Scaffold Context Fix

Verified gating:

- `_scaffold_web_dockerfile_context_fix_enabled(...)` reads the new flag at `scaffold_runner.py:933-935`
- `_scaffold_docker_compose(...)` selects the fixed compose template only when that flag is on at `scaffold_runner.py:938-949`
- the fixed helper rewrites only the web build block at `scaffold_runner.py:1209-1219`
- the web Dockerfile template itself is unchanged and still references `packages/shared/package.json`, which is now valid because the fixed compose block uses repo-root context

## 4E. Config Gating

Each H3h feature is independently gated:

| Flag | Source | New branch only when enabled? | Result |
| --- | --- | --- | --- |
| `codex_turn_interrupt_message_refined_enabled` | `config.py:977-981`, `:2885-2891`; `cli.py:3586-3596`; `codex_appserver.py:1180-1183` | yes | verified |
| `codex_app_server_teardown_enabled` | `config.py:982-986`, `:2892-2898`; `cli.py:3597-3600`; `codex_appserver.py:567-585` | yes | verified |
| `state_finalize_invariant_enforcement_enabled` | `config.py:987-991`, `:2899-2905`; `cli.py:1840-1863`, `:5158-5164`, `:5182-5188`, `:5209-5215`, `:12445-12450`; `state.py:543-551` | yes | verified |
| `scaffold_web_dockerfile_context_fix_enabled` | `config.py:1011-1015`, `:3161-3167`; `scaffold_runner.py:933-949` | yes | verified |

When flags are off:

- legacy interrupt text is used
- legacy transport close path is used
- extra intermediate finalize calls do not run
- legacy compose template is emitted

## 4F. Crash Isolation

| Item | Isolation mechanism | Result |
| --- | --- | --- |
| `INTERRUPT-MSG-REFINE-001` | `_build_turn_interrupt_prompt(...)` catches failures and falls back to `_legacy_turn_interrupt_prompt(...)` at `codex_appserver.py:1052-1074` | verified |
| `APP-SERVER-TEARDOWN-001` | transport close catches teardown failures, logs warning, falls back to `_terminate_subprocess(...)` at `codex_appserver.py:567-580` | verified |
| `STATE-FINALIZE-INVARIANT-001/-002` | `_finalize_state_before_save(...)` logs and swallows finalize failures at `cli.py:1847-1863`; `save_state()` suppresses secondary finalize failures at `state.py:549-551`; final save logs without masking outer completion at `cli.py:15601-15612` | verified |
| `SCAFFOLD-CTX-001` | `_scaffold_docker_compose(...)` wraps fixed-template selection in `try/except` and falls back to the legacy template at `scaffold_runner.py:946-953` | verified |

## 4G. Persistence Fail-Silent

Verified:

- `save_state()` suppresses finalize exceptions at `state.py:549-551`
- CLI-side pre-save finalize logs a warning and returns at `cli.py:1855-1863`
- final save logs a warning if `finalize()` raises but continues to the save logic at `cli.py:15601-15612`

No persistence-layer failure in the H3h additions can crash the pipeline by itself.

## 4H. Prior-Phase Preservation

Diff audit:

```text
git diff --name-only -- src/agent_team_v15/wave_executor.py src/agent_team_v15/provider_router.py src/agent_team_v15/cli.py src/agent_team_v15/state.py src/agent_team_v15/codex_appserver.py src/agent_team_v15/scaffold_runner.py src/agent_team_v15/config.py src/agent_team_v15/codex_transport.py
src/agent_team_v15/cli.py
src/agent_team_v15/codex_appserver.py
src/agent_team_v15/codex_transport.py
src/agent_team_v15/config.py
src/agent_team_v15/scaffold_runner.py
src/agent_team_v15/state.py
```

Interpretation:

- `wave_executor.py` is untouched
- `provider_router.py` is untouched
- H3e redispatch and H3f ownership enforcement surfaces remain unchanged
- H3g bucket-D logic remains unchanged; H3h only adds new gated behavior in the Codex app-server transport / CLI / scaffold / state layers

Representative additive excerpts:

```diff
+ if bool(getattr(config, "turn_interrupt_message_refined_enabled", False)):
+     current_prompt = _build_turn_interrupt_prompt(watchdog, config)
+ else:
+     current_prompt = _legacy_turn_interrupt_prompt(watchdog)
```

```diff
+ if self._app_server_teardown_enabled:
+     await _perform_app_server_teardown(...)
+ else:
+     await asyncio.wait_for(self.process.wait(), timeout=_PROCESS_TERMINATION_TIMEOUT_SECONDS)
```

```diff
+ if _state_finalize_invariant_enabled(_current_state):
+     _finalize_state_before_save(...)
+ save_state(_current_state, directory=...)
```

```diff
+ if _scaffold_web_dockerfile_context_fix_enabled(config):
+     template = _docker_compose_template_with_web_root_context()
```

## 4I. Final Assessment

Execution positions, config gating, crash isolation, and persistence behavior are all wired correctly in the final H3h source.

The only nuance worth calling out is app-server teardown ordering on Windows: the implementation uses one tracked-PID tree kill rather than a separate child-first loop plus parent kill. That is still coordinated, flag-gated, and contained to the app-server close path.
