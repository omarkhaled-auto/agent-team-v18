# Phase H3h — Post-Smoke Remediation Architecture Report

## Executive Summary

The prompt-named smoke bundle `v18 test runs/phase-combined-h3e-h3f-h3g-validation-20260421-002534/` is not present in this checked-in worktree. There are also no checked-in `protocol.log`, `launch.log`, `STATE-final.json`, `milestone-1-wave-B-response.json`, or `milestone-1-wave-B-checkpoint-diff.json` files for that run. This report therefore separates:

- direct repo evidence from source, tests, and preserved proof docs
- inferences about the missing combined smoke

The actual H3h production surfaces are:

- `src/agent_team_v15/codex_appserver.py` for the Wave B orphan interrupt message and Codex app-server lifecycle
- `src/agent_team_v15/scaffold_runner.py` for the `docker-compose.yml` and `apps/web/Dockerfile` scaffold templates
- `src/agent_team_v15/cli.py` and `src/agent_team_v15/state.py` for finalize/write-path truthfulness
- `src/agent_team_v15/config.py` and `src/agent_team_v15/codex_transport.py` for flag/config threading

The prompt’s expected `wave_executor.py` insertion point for the interrupt message does not match repo reality. The corrective Turn 2 message is built in `codex_appserver.py`, not `wave_executor.py`.

## File Ownership

`orchestrator-fixer` owns:

- `src/agent_team_v15/codex_appserver.py`
- `src/agent_team_v15/cli.py`
- `src/agent_team_v15/state.py`
- `src/agent_team_v15/config.py`
- `src/agent_team_v15/codex_transport.py`

Function ownership within those files:

- `codex_appserver.py`
  - `_CodexJSONRPCTransport.start`
  - `_CodexJSONRPCTransport.close`
  - `_execute_once`
  - any new helper used for refined interrupt messaging or app-server teardown
- `cli.py`
  - provider-routing `CodexConfig` construction at `:3541-3562`
  - `_save_wave_state`
  - `_save_isolated_wave_state`
  - orchestration exception/save blocks at `:5096-5135`, `:12330-12367`
  - final save block at `:15502-15529`
- `state.py`
  - `RunState.finalize`
  - `save_state`
- `config.py`
  - `V18Config`
  - `_dict_to_config` v18 loader entries
- `codex_transport.py`
  - `CodexConfig` only, if new app-server flags must be threaded on the transport config object

`scaffold-template-fixer` owns:

- `src/agent_team_v15/scaffold_runner.py`

Function ownership within that file:

- `_docker_compose_template`
- `_web_dockerfile_template`
- `_scaffold_docker_compose` only if needed to wire the new flag

Off-limits unless the classifier audit later proves otherwise:

- `src/agent_team_v15/provider_router.py`
- `src/agent_team_v15/wave_executor.py`

`test-engineer` owns new/updated tests only after implementation lands.

`wiring-verifier` is read-only on source and may write verification docs/tests only.

## 1A. Current D3 Turn/Interrupt Injection Path

Direct repo evidence:

- app-server spawn and transport lifecycle: `src/agent_team_v15/codex_appserver.py:296-316`, `:441-500`
- orphan polling and `turn/interrupt`: `src/agent_team_v15/codex_appserver.py:694-747`
- corrective Turn 2 prompt construction: `src/agent_team_v15/codex_appserver.py:1028-1048`

Exact message site:

- file: `src/agent_team_v15/codex_appserver.py`
- lines: `1037-1040`
- current message:

```python
current_prompt = (
    f"The previous turn's tool (tool_name={watchdog.last_orphan_tool_name}) "
    f"stalled for >{watchdog.last_orphan_age:.0f}s. Do not run that tool again; "
    "continue the remaining work using alternative approaches."
)
```

Shape:

- f-string split across three string segments
- substituted values:
  - `watchdog.last_orphan_tool_name`
  - `watchdog.last_orphan_age`

Actual call path:

1. `_process_streaming_event()` records `item/started` and `item/completed` into `_OrphanWatchdog` at `codex_appserver.py:817-835`.
2. `_monitor_orphans()` polls the watchdog at `codex_appserver.py:719-747`.
3. On the first orphan, `_monitor_orphans()` calls `_send_turn_interrupt()` at `:746`.
4. `_wait_for_turn_completion()` returns the `turn/completed` payload at `:885-923`.
5. `_execute_once()` sees `turn_status == "interrupted"` at `:1028`.
6. `_execute_once()` rewrites `current_prompt` to the legacy blunt message at `:1037-1040`.
7. The `while True` loop re-enters `client.turn_start(thread_id, current_prompt)` at `:983-985`, which becomes Turn 2.

Timeout flag structure:

- `orphan_tool_idle_timeout_seconds` is defined in `config.py:810` and read by the generic wave watchdog helper in `wave_executor.py:2366-2371`, `:2455-2461`, `:2648-2650`
- `codex_orphan_tool_timeout_seconds` is defined in `config.py:829` and loaded in `config.py:3141-3147`
- direct repo finding: `codex_orphan_tool_timeout_seconds` is not currently threaded into `provider_router.execute_codex(...)` or `codex_appserver.execute_codex(...)`; the app-server path still uses the `execute_codex(..., orphan_timeout_seconds=300.0)` default from `codex_appserver.py:1107`

Insertion point for `INTERRUPT-MSG-REFINE-001`:

- primary change: `src/agent_team_v15/codex_appserver.py:1028-1041`
- likely companion helper placement: near `_format_turn_error()` / `_app_server_error_message()` or just above `_execute_once()`
- config threading needed so the message can branch on the new flag before constructing `current_prompt`

## 1B. Current codex.exe Process Lifecycle

Direct repo evidence:

- spawn helper: `src/agent_team_v15/codex_appserver.py:296-316`
- command builder: `src/agent_team_v15/codex_appserver.py:319-324`
- transport stores process handle: `src/agent_team_v15/codex_appserver.py:454`
- transport startup assigns process: `src/agent_team_v15/codex_appserver.py:472-478`
- transport close path: `src/agent_team_v15/codex_appserver.py:480-506`
- Windows tree kill helper: `src/agent_team_v15/codex_appserver.py:386-413`
- current H3g orphan-PID evidence: `v18 test runs/phase-h3g-validation/proof-02-fix-loop-cap-and-orphan-teardown.md:12-31`

Current production lifecycle:

- spawn occurs in `_spawn_appserver_process()` at `codex_appserver.py:296-316`
- the subprocess handle is stored on `_CodexJSONRPCTransport.process` at `:454`, assigned at `:476`
- no separate PID registry exists outside the transport object
- shutdown is `await client.close()` from `_execute_once()` finally block at `codex_appserver.py:1080-1084`
- `client.close()` delegates to `transport.close()` at `:644-645`
- `transport.close()`:
  - closes stdin at `:487-493`
  - waits on `self.process.wait()` at `:495-499`
  - only calls `_terminate_subprocess(self.process)` if that wait times out or errors

Why the app-server parent can survive:

- on Windows shell launches, `_build_appserver_command()` sets `use_shell=True` for `.cmd` / `.bat` binaries at `codex_appserver.py:323`
- `_spawn_appserver_process()` then uses `asyncio.create_subprocess_shell(...)` at `:299-307`
- when the wrapper shell exits cleanly, `self.process.wait()` can succeed at `:497` even if a descendant `codex.exe` remains alive
- the current tree-kill helper is only reached on timeout/error, not on a clean shell exit
- direct preserved evidence: H3g’s proof doc explicitly recorded a surviving `codex.exe` PID `36704`

Insertion point for `APP-SERVER-TEARDOWN-001`:

- primary lifecycle hook: `src/agent_team_v15/codex_appserver.py:472-500`
- best fit:
  - track `self.process.pid` and whether the command used `use_shell`
  - add a flag-gated post-close teardown branch after the normal `wait()` path, not only in the timeout path
- config threading:
  - `cli.py:3541-3562` currently threads H3c/H3d flags onto `CodexConfig` via `setattr(...)`
  - that is the narrowest consistent place to thread `codex_app_server_teardown_enabled`

## 1C. Current web Dockerfile + docker-compose Scaffold Path

Direct repo evidence:

- compose writer: `src/agent_team_v15/scaffold_runner.py:931-935`
- web foundation writer: `src/agent_team_v15/scaffold_runner.py:986-1021`
- compose template: `src/agent_team_v15/scaffold_runner.py:1124-1182`
- web Dockerfile template: `src/agent_team_v15/scaffold_runner.py:1832-1868`

Current emitted content:

- `docker-compose.yml` web build section from `_docker_compose_template()` at `scaffold_runner.py:1168-1170`:

```yaml
  web:
    build:
      context: ./apps/web
```

- `apps/web/Dockerfile` deps stage from `_web_dockerfile_template()` at `scaffold_runner.py:1846-1850`:

```dockerfile
FROM base AS deps
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/shared/package.json packages/shared/
RUN pnpm install --frozen-lockfile
```

Canonical fix:

- change the compose template, not the Dockerfile template
- recommended change:

```yaml
  web:
    build:
      context: .
      dockerfile: apps/web/Dockerfile
```

Reason:

- the Dockerfile already expects monorepo-root context because it copies root workspace files and `packages/shared/package.json`
- changing only the compose context is the minimum structural fix
- `services.api.build.context` should remain `./apps/api` for now; the current scaffolded API Dockerfile is Wave-B-owned, not scaffold-owned, and no scaffold template in this repo shows an out-of-tree copy requirement for `apps/api`

Insertion point for `SCAFFOLD-CTX-001`:

- primary: `src/agent_team_v15/scaffold_runner.py:1168-1170`
- flag gate can wrap the string branch inside `_docker_compose_template()`
- `apps/web/Dockerfile` should remain byte-identical when the new flag is on

## 1D. Current STATE finalize() Call Graph

Direct repo evidence:

- `RunState.finalize()`: `src/agent_team_v15/state.py:98-208`
- `save_state()` summary/invariant block: `src/agent_team_v15/state.py:576-613`
- final finalize+save block: `src/agent_team_v15/cli.py:15502-15529`
- state invariant tests: `tests/test_state.py:618-707`
- finalize tests: `tests/test_state_finalize.py:57-148`

Exact invariant:

- `save_state()` computes `_expected_success = (not state.interrupted) and len(state.failed_milestones) == 0` at `state.py:603`
- if `data["summary"]["success"] != _expected_success`, it raises `StateInvariantError` at `state.py:604-612`

Current handling when invariant fires:

- `save_state()` raises; it does not log-only
- the final `cli.py` block catches exceptions around the last save at `cli.py:15528-15529` and prints a warning

Current finalize call sites:

- only one explicit `finalize()` call exists in the repo:
  - `src/agent_team_v15/cli.py:15512-15514`

Relevant state-save exit paths:

| Exit path | Source | Calls `finalize()` now? | Writes `save_state()` now? | Gap |
|---|---|---|---|---|
| Early initial state persist | `cli.py:11244-11248` | No | Yes | acceptable bootstrap write, but flag-off legacy only |
| Orchestration exception catch | `cli.py:12330-12367` | No | Yes at `:12363-12365` | writes pre-finalized state after exceptions |
| Milestone timeout path | `cli.py:5096-5099` | No | Yes | failed milestone persisted without finalize |
| Milestone generic exception path | `cli.py:5132-5135` | No | Yes | failed milestone persisted without finalize |
| KeyboardInterrupt in milestone loop | `cli.py:5101-5115` | No | not directly in this block, but loop breaks before final normal-complete semantics | finalize skipped on interrupt path |
| Normal completion final write | `cli.py:15502-15529` | Yes | Yes | only explicit finalize site |
| `_save_wave_state` callback path | `cli.py:1735-1786` | No | Yes | wave progress writes can persist intermediate contradictory state if caller left poisoned `summary` |
| `_save_isolated_wave_state` | `cli.py:1789-1825` | No | Yes | same risk in isolated/worktree flow |

Important repo reality:

- `RunState.finalize()` is already idempotent by behavior; `tests/test_state_finalize.py:130-148` asserts identical output on a second call
- there is no explicit `_finalized` guard today
- the prompt’s `cli.py:13491-13498` reference is stale relative to this branch; the current final finalize block is at `cli.py:15502-15529`, while the invariant raise now lives in `state.py:603-612`

Insertion points for `STATE-FINALIZE-INVARIANT-001` / `-002`:

- add a flag-gated helper in `cli.py` and use it at:
  - `_save_wave_state()` before `save_state()` at `cli.py:1785-1786`
  - `_save_isolated_wave_state()` before `save_state()` at `cli.py:1825`
  - orchestration exception save at `cli.py:12361-12365`
  - milestone timeout/exception saves at `cli.py:5096-5099`, `:5132-5135`
  - retain existing final block at `cli.py:15502-15529`
- if an explicit idempotency guard is added, the narrowest site is `RunState.finalize()` in `state.py:98-208`

## 1E. Wave B Failure Classification Investigation

### Direct repo evidence

- blocked-prefix downgrade only fires on literal `BLOCKED:`:
  - `src/agent_team_v15/provider_router.py:399-414`
- Wave B output sanitization appends findings but does not set `wave_result.success = False`:
  - hook call: `src/agent_team_v15/wave_executor.py:4819-4826`
  - implementation: `src/agent_team_v15/wave_executor.py:2201-2299`
- Wave B requirements-deliverable check does set `wave_result.success = False`:
  - `src/agent_team_v15/wave_executor.py:4937-4951`
- Wave B live endpoint probing does set `wave_result.success = False`:
  - `src/agent_team_v15/wave_executor.py:4953-4983`
  - probe helper returns failure on manifest failures at `src/agent_team_v15/wave_executor.py:3258-3283`
- `failed_wave` is written from the wave’s final status:
  - `src/agent_team_v15/wave_executor.py:5040-5047`
  - `src/agent_team_v15/cli.py:1773-1786`
- audit-scope completeness runs later in the audit loop and cannot set `failed_wave: "B"`:
  - `src/agent_team_v15/cli.py:6442-6469`

### What can be concluded directly

- candidate mechanism 1 from the prompt, `codex_blocked_prefix_as_failure_enabled`, cannot explain the smoke outcome. In source it only triggers when the final Codex message begins with literal `BLOCKED:`:
  - `src/agent_team_v15/provider_router.py:399-410`
  - the recovered Wave B response artifact shows `metadata.codex_result_success = true` and the final message starts with `Implemented...` / `I could not run...`, not `BLOCKED:`:
    - `C:/Projects/agent-team-v18-codex-h2a-merge/v18 test runs/phase-combined-h3e-h3f-h3g-validation-20260421-002534/codex-captures/milestone-1-wave-B-response.json`
- candidate mechanism 2, Wave B output sanitization, cannot directly set `failed_wave: "B"` in the current repo because it only appends findings:
  - `src/agent_team_v15/wave_executor.py:2218-2301`
- candidate mechanism 4, audit-scope completeness, runs later in the audit loop and cannot directly set the Wave B failed marker in `STATE.json`:
  - `src/agent_team_v15/cli.py:6442-6469`
- the code paths that can directly turn a successful provider result into `failed_wave: "B"` are the Wave B post-verification checks in `wave_executor.py`, especially:
  - requirements-deliverable failure at `src/agent_team_v15/wave_executor.py:4937-4951`
  - live endpoint probe failure at `src/agent_team_v15/wave_executor.py:4953-4984`
  - final failed-wave persistence at `src/agent_team_v15/wave_executor.py:5040-5059`

### Smoke-artifact correlation

Recovered artifact evidence from the combined smoke:

- Wave B itself completed successfully at the Codex protocol layer:
  - `milestone-1-wave-B-protocol.log:793` shows `turn/completed ... "status":"completed"`
  - `milestone-1-wave-B-response.json` shows `metadata.codex_result_success = true`
- the first downstream failure recorded in the smoke bundle is the Docker-backed live probe startup failure:
  - `launch.log:620-622`
  - exact message:
    - `Docker build reported failures ... "/packages/shared/package.json": not found`
    - `Warning: Milestone milestone-1 failed: Wave execution failed in B: Docker build failed during live endpoint probing startup`
- `STATE-final.json` then records:
  - `wave_progress["milestone-1"]["failed_wave"] = "B"`
  - `wave_progress["milestone-1"]["completed_waves"] = ["A"]`

This matches the `wave_executor.py` control flow exactly:

- `_run_wave_b_probing(...)` returns a failed probe result when Docker startup does not produce a healthy API:
  - `src/agent_team_v15/wave_executor.py:3135-3172`
- the Wave B execution loop flips `wave_result.success = False` when probing fails:
  - `src/agent_team_v15/wave_executor.py:4953-4984`
- that failed wave status is then persisted as `failed_wave = "B"`:
  - `src/agent_team_v15/wave_executor.py:5040-5059`

### Finding

**Finding A: classifier correct**

Confidence: high.

Confirmed from source plus recovered smoke artifacts:

- blocked-prefix logic did not fire
- output sanitization did not own the failed-wave transition
- Wave B was classified failed only after Codex had already succeeded, when the post-wave live endpoint probing startup failed on the broken web Docker build context

No classifier code change is recommended. The correct fix is the scaffold-context remediation, not a classifier relaxation.

## 1F. Existing Patterns To Follow

### Flag pattern

Config dataclass:

- `src/agent_team_v15/config.py:789-1103`

Loader pattern:

- boolean flags use `_coerce_bool(v18.get("flag_name", cfg.v18.flag_name), cfg.v18.flag_name)`
- representative H3c/H3e/H3f flags:
  - `codex_cwd_propagation_check_enabled` at `config.py:981`, loader `:2865-2871`
  - `codex_flush_wait_enabled` at `:985`, loader `:2872-2878`
  - `codex_blocked_prefix_as_failure_enabled` at `:995`, loader `:2893-2899`
  - `recovery_wave_redispatch_enabled` at `:891`, loader `:3007-3013`

Config threading pattern for Codex app-server:

- `cli.py:3541-3562`
- fields beyond `CodexConfig` dataclass are currently threaded with `setattr(...)`

### Test pattern

- config round-trip / loader gaps:
  - `tests/test_config_v18_loader_gaps.py:29-134`
- scaffold emission surface:
  - `tests/test_scaffold_runner.py:37-108`
- finalize idempotence and reconciliation:
  - `tests/test_state_finalize.py:55-148`
- invariant behavior:
  - `tests/test_state.py:618-707`
- existing live Codex cleanup pattern:
  - `tests/test_codex_appserver_live.py:27-140`

### Conditional skip / fail-silent pattern

- flag-off early return pattern:
  - `wave_executor.py:2232-2233` for Wave B output sanitization
- best-effort try/except + warning:
  - `wave_executor.py:2221-2230`, `:2254-2264`, `:2272-2281`
  - `cli.py:15515-15529`
- these are the patterns H3h should match:
  - do nothing when flag off
  - on failure, log/warn and preserve legacy path

## 1G. File-Ownership Overlap

There is no required `provider_router.py` overlap for the four requested H3h fixes.

- the interrupt message and app-server lifecycle both live in `codex_appserver.py`
- the scaffold template bug lives in `scaffold_runner.py`
- the STATE finalize work lives in `cli.py` and `state.py`

The only shared file across Scope A and Scope B is `config.py`. To avoid merge collisions:

- `orchestrator-fixer` owns **all** `config.py` edits, including the scaffold flag addition
- `scaffold-template-fixer` must not edit `config.py`

That preserves parallel file ownership:

- `orchestrator-fixer`: `codex_appserver.py`, `cli.py`, `state.py`, `config.py`, `codex_transport.py`
- `scaffold-template-fixer`: `scaffold_runner.py`

## New Flags To Add

All default `False`:

- `codex_turn_interrupt_message_refined_enabled`
- `codex_app_server_teardown_enabled`
- `state_finalize_invariant_enforcement_enabled`
- `scaffold_web_dockerfile_context_fix_enabled`

Expected insertion sites:

- `src/agent_team_v15/config.py`
  - `V18Config` block near other H3* flags
  - `_dict_to_config` v18 loader block near the existing Codex/scaffold flags
- `src/agent_team_v15/cli.py:3541-3562`
  - thread the two Codex transport/runtime flags onto `CodexConfig`

## Final Recommendation

Proceed with:

1. `orchestrator-fixer` on `codex_appserver.py`, `cli.py`, `state.py`, `config.py`, `codex_transport.py`
2. `scaffold-template-fixer` on `scaffold_runner.py`
3. `test-engineer` only after both land
4. `wiring-verifier` in parallel with test engineering after implementation lands

Classifier result: **Finding A: classifier correct**
