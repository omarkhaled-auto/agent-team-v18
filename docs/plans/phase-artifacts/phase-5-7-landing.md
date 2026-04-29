# Phase 5.7 — Bootstrap watchdog + productive-tool-idle + cumulative-wedge cap landing

**Plan:** `docs/plans/2026-04-28-phase-5-quality-milestone.md` §J + §M.M4 + §M.M6.
**Closes:** R-#41 (no bootstrap watchdog) + R-#45 (Codex productive-tool idle wedge) + §M.M4 (cumulative bootstrap-wedge circuit breaker).
**Landed:** 2026-04-29 direct-to-master commit `5b6580d` off baseline `25e5222` (Phase 5.6 reviewer corrections).
**Live smoke:** AC4 + AC10 deferred to closeout-smoke checklist (§O.4 rows below).

---

## Files touched (matches §J.1 + scope-check-in extensions)

| File | Change |
|---|---|
| `src/agent_team_v15/wave_executor.py` | `_WaveWatchdogState` extension (5 productive-tool fields + `bootstrap_cleared` + `stderr_tail` + `update_stderr_tail`); top-level `_is_productive_tool_event(message_type, tool_name, event_kind)` predicate; `record_progress` extension (productive vs non-productive split); `_build_wave_watchdog_timeout` rewritten as 4-tier evaluator (`bootstrap_eligible` + `idle_fallback_seconds` kwargs); new `_bootstrap_idle_timeout_seconds` / `_tool_call_idle_timeout_seconds` / `_bootstrap_respawn_max_per_wave` v18 lookup helpers; `_write_hang_report` extensions (`stderr_tail`, `cumulative_wedges_so_far`, `bootstrap_deadline_seconds`, `timeout_kind` discriminator + 5 tool-call-idle specific fields); bootstrap-respawn loops in `_invoke_wave_sdk_with_watchdog` / `_invoke_provider_wave_with_watchdog` / `_invoke_sdk_sub_agent_with_watchdog`; new `BuildEnvironmentUnstableError` + module-level `install_bootstrap_wedge_callback` / `get_bootstrap_wedge_callback` / `_get_cumulative_wedge_count`. |
| `src/agent_team_v15/agent_teams_backend.py` | `execute_prompt(stderr_observer=...)` kwarg threaded through to `_spawn_teammate(stderr_observer=...)`; new `_communicate_with_stderr_observer` helper replaces `proc.communicate()` ONLY when an observer is wired (default `None` preserves the existing path byte-identically); new `except asyncio.CancelledError` block kills the subprocess on watchdog-induced cancel + re-raises; adds `import contextlib`. |
| `src/agent_team_v15/config.py` | 4 new `V18Config` fields (`bootstrap_idle_timeout_seconds: int = 60` §M.M6; `tool_call_idle_timeout_seconds: int = 1200` §J.4; `bootstrap_respawn_max_per_wave: int = 3` §M.M6; `cumulative_wedge_cap: int = 10` §M.M4); YAML threading via `_coerce_int`; new `_validate_v18_phase57(cfg)` validator rejects `bootstrap_idle < 30`, `tool_call_idle < 300` / `> codex_timeout_seconds`, and negative respawn / wedge caps; invoked after the v18 YAML block. |
| `src/agent_team_v15/state.py` | `RunState._cumulative_wedge_budget: int = 0` field (preserved leading underscore per plan §J.3 / §M.M4); `load_state` `_expect` shim (default 0 for backward-compat); `update_milestone_progress` PRESERVE-on-skip patch — when the new entry doesn't include `_bootstrap_wedge_diagnostics`, copy from the existing entry. |
| `src/agent_team_v15/cli.py` | `--cumulative-wedge-cap N` argparse + override wiring (legacy-Namespace robust); `_make_bootstrap_wedge_callback` factory; `install_bootstrap_wedge_callback` install at start of `_run_prd_milestones` + `current_task.add_done_callback` cancellation-safe uninstall + explicit uninstall before natural return; `BuildEnvironmentUnstableError` catch in `cli_main` → `_finalize_milestone_with_quality_contract(override_status="FAILED", override_failure_reason="sdk_pipe_environment_unstable")` + `sys.exit(2)`; `_mark_bootstrap_cleared_on_watchdog_state` helper (Blocker 1 — opaque team-mode exemption); `_make_stderr_observer_from_progress_callback` helper; `_execute_single_wave_sdk` (cli.py:5419 team-mode branch) invokes both helpers before calling `execute_prompt`; cli.py:4720 first copy is direct-SDK only and untouched; **§M.M4 line 1515 audit + audit-fix coverage** — `_run_milestone_audit` accepts `cwd` kwarg and routes the Claude SDK dispatch through `_invoke_sdk_sub_agent_with_watchdog(role="audit", wave_letter="audit")` when cwd is supplied; `_run_audit_fix_unified` Claude fallback dispatch routes through `_invoke_sdk_sub_agent_with_watchdog(role="audit_fix", wave_letter="audit-fix")`; both audit + audit-fix env-var management (`AGENT_TEAM_AUDIT_*` / `AGENT_TEAM_FINDING_ID` / `AGENT_TEAM_ALLOWED_PATHS`) preserved verbatim around the wrapper; legacy callers without `cwd` continue using the pre-Phase-5.7 direct-SDK path; adds `import contextlib` + `from datetime import datetime, timezone`. |
| **NEW** `tests/test_pipeline_upgrade_phase5_7.py` | 26 fixtures (8 ACs + 18 supporting). |

**Net diff:** 6 files changed, 2031 insertions(+), 221 deletions(-).

---

## Risks closed

* **R-#41** (no bootstrap watchdog) — CLOSED for direct-SDK Claude paths AND provider-routed Claude paths. Bootstrap watchdog (60s) detects "no productive tool event in 60s" and respawns up to 3 times per wave; on the 4th attempt surfaces as wave-fail.
  * **Team-mode opaque claude --print path REVERTS to existing 400/600s `_sub_agent_idle_timeout_seconds`** per scope check-in Blocker 1: the opaque subprocess (claude --print --output-format json — single JSON dump at process END, no mid-run progress events) cannot satisfy the productive-event predicate without changing the output mode. Phase 5.7 ships explicit exemption (`_mark_bootstrap_cleared_on_watchdog_state` flips `state.bootstrap_cleared = True` BEFORE `execute_prompt`) so healthy >60s runs do NOT false-fire bootstrap. Future Phase 6+ option: switch team-mode to `--output-format stream-json` + parse JSONL chunks live (NOT shipped this phase).
* **R-#45** (Codex productive-tool idle wedge — M3 Wave B `commandExecution` idle 4920s) — CLOSED for ALL paths regardless of `bootstrap_eligible`. Tier 3 (productive-tool-idle, default 1200s) fires when no productive event lands within `tool_call_idle_timeout_seconds` AFTER bootstrap clearing AND with no pending orphan tool. Wave-fail signal (NOT respawn); Phase 4.5 cascade picks up. Provider-routed Codex (where `bootstrap_eligible=False`) STILL gets tier 3 — that's the M3 case.
* **§M.M4** (cumulative bootstrap-wedge circuit breaker) — CLOSED. `RunState._cumulative_wedge_budget` increments once per Claude SDK bootstrap-wedge respawn (NOT per orphan-tool / tool-call-idle / wave-idle event). At cap REACH (default 10), the callback raises `BuildEnvironmentUnstableError` → cli.py top-level catch routes through Phase 5.5 single-resolver to FAILED + `failure_reason="sdk_pipe_environment_unstable"` + EXIT_CODE=2. Operator override via `--cumulative-wedge-cap N` (0 disables).

---

## §M.M4 worst-case bootstrap-wedge budget table (per milestone)

§M.M4 line 1520 mandates this table identifies which subprocess classes use Claude SDK and thus contribute to the cumulative wedge counter. Worst case = "every Claude SDK subprocess wedges 3 times before respawn cap"; the in-build cap halts at 10 cumulative wedges across all sources, so no actual milestone reaches the worst case.

| # | Subprocess class | Worst-case count per milestone | Dispatch path | Claude SDK subprocess? | Counts toward §M.M4 cap? | Worst-case wedges if every dispatch wedges 3× |
|---|---|---|---|---|---|---|
| 1 | **Primary Claude waves** (Wave A, Scaffold, T, E for `full_stack`) | 4 dispatches | `_invoke_wave_sdk_with_watchdog` | YES (direct-SDK) — team-mode opaque path is bootstrap-EXEMPT (cli.py flips `bootstrap_cleared=True` before `execute_prompt`); direct-SDK path is bootstrap-eligible | YES for direct-SDK; NO for team-mode opaque (exempt) | up to 4 × 3 = **12** wedges (direct-SDK only; team-mode exempt produces 0) |
| 2 | **Primary Codex waves** (Wave B + Wave D when `provider_map_b/d="codex"`, the default) | 2 dispatches | `_invoke_provider_wave_with_watchdog` with `bootstrap_eligible=not codex_owned_route` → False | NO (Codex appserver/CLI is a long-running daemon / different subprocess class) | NO | **0** wedges |
| 3 | **Codex auxiliary waves** (A5, T5) | 2 dispatches | `_invoke_provider_wave_with_watchdog` with `bootstrap_eligible=False` | NO | NO | **0** wedges |
| 4 | **Wave C openapi generation** | 1 dispatch | scripted (`generate_openapi_contracts`) — no SDK | NO | NO | **0** wedges |
| 5 | **Compile-fix attempts (Codex routing for backend findings)** | up to 6 (max 3 per Wave B + 3 per Wave D) | `_dispatch_codex_compile_fix` (separate from `_invoke_sdk_sub_agent_with_watchdog`) | NO (Codex shell) | NO | **0** wedges (Codex compile-fix path) |
| 6 | **Compile-fix attempts (Claude SDK fallback)** | up to 6 worst-case | `_invoke_sdk_sub_agent_with_watchdog` (role=`compile_fix`) — bootstrap-eligible | YES | YES | up to 6 × 3 = **18** wedges (only when Codex routing isn't applicable AND Claude fallback is used) |
| 7 | **Audit-fix cycles** (cycle-1 dispatch lifted in Phase 5.4; max 3 cycles per `max_reaudit_cycles` default) | up to 3 | `_run_audit_fix_unified` → audit-fix sub-agent dispatch via Claude SDK | YES | YES | up to 3 × 3 = **9** wedges |
| 8 | **Re-audit sessions** (one per audit cycle that produces findings) | up to 3 | Claude SDK audit sub-agent dispatch | YES | YES | up to 3 × 3 = **9** wedges |

**Worst-case Claude SDK wedge count per milestone (sum of 1 + 6 + 7 + 8):** 12 + 18 + 9 + 9 = **48 wedges**.

**§M.M4 cap (default 10) interpretation:** the cap halts the build at the 10th cumulative wedge across the ENTIRE BUILD (all milestones, all subprocess classes that count). With the per-wave respawn cap of 3, even one pathologically-flaky Claude SDK source (e.g. compile-fix-fallback row 6) can saturate the budget if it wedges every attempt; this is the protection §M.M4 is designed to provide.

**Reading the table:** rows 2 / 3 / 4 / 5 produce **0 wedges** toward the cap regardless of how many subprocess wedges they experience — they're outside the §M.M4 scope (Codex paths or non-SDK scripts). Operators investigating a `sdk_pipe_environment_unstable` halt should look at row 1 / 6 / 7 / 8 BUILD_LOG entries (`bootstrap-wedge respawn N/3`) and the per-milestone `_bootstrap_wedge_diagnostics` field on `STATE.json::milestone_progress[<id>]`.

**Operator override:** `--cumulative-wedge-cap 0` disables the cap entirely (legacy unbounded behavior). Recommended only for known-flaky-environment data-collection runs where halting on environment instability would defeat the purpose of the run.

---

## `_WaveWatchdogState` extension shape

```python
# Phase 5.7 §J.4 — bootstrap + productive-tool idle tracking.
bootstrap_cleared: bool = False
last_tool_call_at: str = ""
last_tool_call_monotonic: float = 0.0
last_non_tool_progress_at: str = ""
last_productive_tool_name: str = ""
tool_call_event_count: int = 0
# Phase 5.7 §J.3 — stderr ring-buffer (last 4096 chars).
stderr_tail: str = ""
```

`update_stderr_tail(chunk: bytes | str)` appends + truncates to last 4096 chars; safe to call from concurrent stderr-drain task.

---

## `_is_productive_tool_event` predicate truth table

Centralised in `wave_executor._is_productive_tool_event`. Locked by `test_is_productive_tool_event_truth_table`.

| message_type | tool_name | event_kind | productive |
|---|---|---|---|
| `tool_use` | (any) | `start` | True |
| `tool_result` | `""` | `complete` | True |
| `item/started` | `commandExecution` | `start` | True |
| `item.started` | `commandExecution` | `start` | True |
| `item/completed` | `commandExecution` | `complete` | True |
| `item.completed` | `commandExecution` | `complete` | True |
| `item/started` | `agentMessage` / `reasoning` / `plan` | `start` | False |
| `item/agentMessage/delta` | `agentMessage` | `other` | False |
| `assistant_text` / `assistant_message` / `result_message` | `""` | `other` | False |
| `sdk_call_started` / `sdk_session_started` / `query_submitted` | `""` | (any) | False |
| `agent_teams_session_started` / `agent_teams_session_completed` | `""` | (any) | False |
| `codex_event` / `codex_stdout` / `turn/started` | (any) | (any) | False |

---

## Watchdog-tick precedence (4-tier per §J.4)

1. **Bootstrap** (gated by `bootstrap_eligible AND not state.bootstrap_cleared`): fires when `now - state.started_monotonic >= bootstrap_idle_timeout_seconds`. Caller-handled as a respawn (NOT wave-fail) up to `bootstrap_respawn_max_per_wave`. 4th attempt → wave-fail.
2. **Orphan-tool** (existing — `state.pending_tool_starts` non-empty AND oldest age `>= orphan_tool_idle_timeout_seconds`). More specific than tier 3 so AC8 holds: pending `commandExecution` older than orphan threshold fires `orphan-tool`, NOT `tool-call-idle`.
3. **Productive-tool-idle** (only if `state.bootstrap_cleared AND state.pending_tool_starts empty AND state.last_tool_call_monotonic > 0.0`): fires when `now - state.last_tool_call_monotonic >= tool_call_idle_timeout_seconds`. Wave-fail (NOT respawn).
4. **Idle fallback** (caller-supplied `idle_fallback_seconds`):
   * `_invoke_wave_sdk_with_watchdog` → `_wave_idle_timeout_seconds` (1800s).
   * `_invoke_provider_wave_with_watchdog` → `_wave_idle_timeout_seconds` (1800s).
   * `_invoke_sdk_sub_agent_with_watchdog` → `_sub_agent_idle_timeout_seconds` (400/600s — Blocker 3 fix).

---

## RunState `_cumulative_wedge_budget` round-trip

* `RunState._cumulative_wedge_budget: int = 0` field shipped with leading underscore per plan §J.3 / §M.M4 spec.
* `asdict(state)` includes the field in STATE.json output (dataclass fields with leading underscores ARE serialised).
* `load_state` `_expect` shim defaults to 0 for backward-compat — pre-Phase-5.7 STATE.json files load cleanly.
* Locked by `test_run_state_cumulative_wedge_budget_round_trip`: set=7 → save_state → load_state → 7; manual JSON delete → load_state → 0.

---

## `--cumulative-wedge-cap` argparse + halt-on-cap wiring

```python
parser.add_argument(
    "--cumulative-wedge-cap",
    type=int, default=None, metavar="N",
    help="Per-build cap on cumulative bootstrap-wedge respawns "
         "(default: config value, falls back to 10). When the counter "
         "reaches the cap, halt with failure_reason=sdk_pipe_environment_unstable "
         "and exit code 2. Pass 0 to disable. Phase 5.7 §M.M4.",
)
```

Override at args→config: `getattr(args, "cumulative_wedge_cap", None)` (legacy-Namespace robust). 0 disables; positive caps the count. Validation re-runs (`>= 0`) on override.

**§M.M4 cap-boundary lock** (per `test_cumulative_wedge_cap_halt_fires_exactly_at_cap_reached`): with `cap=3`, the 1st wedge → counter=1, no raise; 2nd → counter=2, no raise; 3rd → counter=3, raises `BuildEnvironmentUnstableError`. **"Count reaches cap" → halt** (NOT "count exceeds cap").

---

## Provider scoping (Blocker 2 fix)

`_invoke_provider_wave_with_watchdog(bootstrap_eligible=...)` kwarg. Caller at `wave_executor.py:_execute_wave_sdk` passes `bootstrap_eligible=not codex_owned_route`:

* Provider-routed **Codex** (Wave B/D default): `bootstrap_eligible=False`. Tier 1 NEVER fires; cumulative-wedge counter NEVER increments. Tier 3 (productive-tool-idle) STILL applies — that's R-#45.
* Provider-routed **Claude** (Wave B/D when operator overrides `provider_map_b/d='claude'`): `bootstrap_eligible=True`. Tier 1 + tier 3 + cumulative-wedge counter all apply.

Locked by:
* `test_provider_routed_codex_does_NOT_increment_cumulative_wedge_counter` (Codex with `bootstrap_eligible=False`, no tier-1 fire).
* `test_provider_routed_codex_productive_tool_idle_DOES_apply` (Codex productive-tool-idle still fires regardless of `bootstrap_eligible`).

---

## Team-mode opaque exemption (Blocker 1 fix)

`cli.py:_mark_bootstrap_cleared_on_watchdog_state(progress_callback)` mirrors `_set_watchdog_client` mechanics. Reaches into `progress_callback.__self__` (the `_WaveWatchdogState`) and flips `bootstrap_cleared = True`. Called from `_execute_single_wave_sdk` (cli.py:5419) team-mode branch BEFORE `execute_prompt`. **Tier 3 stays inert** because `last_tool_call_monotonic` remains 0.0 (no productive event ever fires through opaque subprocess); tier 2 / tier 4 preserve today's behaviour for the opaque path.

Locked by `test_team_mode_subprocess_with_no_tool_telemetry_does_NOT_bootstrap_fire`.

---

## Sub-agent idle fallback preservation (Blocker 3 fix)

`_build_wave_watchdog_timeout(idle_fallback_seconds=...)` kwarg. Each watchdog function passes its caller-appropriate fallback so sub-agents keep their 400/600s threshold instead of silently inheriting the 1800s wave-idle.

Locked by `test_sub_agent_idle_fallback_uses_sub_agent_timeout_not_wave_timeout`.

---

## Module-level callback install/uninstall + leak prevention

`wave_executor.install_bootstrap_wedge_callback(cb)` / `get_bootstrap_wedge_callback() -> cb`. cli.py installs at the start of `_run_prd_milestones`, registers `current_task.add_done_callback(lambda _t: install_bootstrap_wedge_callback(None))` for cancellation-safe uninstall, AND explicitly uninstalls at the natural return site. Idempotent.

Locked by `test_bootstrap_wedge_callback_uninstalls_in_finally_after_exception`.

---

## Hang-report writer extensions

Always emitted on every wedge-kind:

* `timeout_kind`: discriminator (`bootstrap` / `orphan-tool` / `tool-call-idle` / `wave-idle`).
* `stderr_tail`: last 4096 chars of subprocess stderr. **Non-empty only when the dispatch path goes through `agent_teams_backend.execute_prompt` AND a `stderr_observer` is wired** (today: cli.py:5419 team-mode branch wires `state.update_stderr_tail`). **Bootstrap-eligible paths are direct-SDK `ClaudeSDKClient` (in-process; no subprocess stderr to capture) — those hang reports surface `stderr_tail==""` by design.** Locked by O.4.7. Closeable in Phase 6+ via `--output-format stream-json` for team-mode + stream parsing (NOT shipped this phase).
* `role`: dispatch role from `WaveWatchdogTimeoutError.role` — supports O.4.11 grouping by Claude SDK subprocess class. Canonical values: `compile_fix` / `audit_fix` / `audit` / `wave`. Default `""` for legacy callers.

Bootstrap-wedge specific (when caller passes them):

* `cumulative_wedges_so_far`: read from `RunState._cumulative_wedge_budget` via `_get_cumulative_wedge_count()` at fire time.
* `bootstrap_deadline_seconds`: the configured deadline.

Tool-call-idle specific (when `timeout_kind == "tool-call-idle"`):

* `last_tool_call_at`: ISO timestamp of last productive event.
* `tool_call_idle_timeout_seconds`: equal to `timeout.timeout_seconds`.
* `last_non_tool_progress_at`: last non-productive event timestamp.
* `last_productive_tool_name`: e.g. `commandExecution`.
* `tool_call_event_count`: total productive events on this attempt.

---

## Phase 5.6 + 5.5 contract preservation (no edits made)

* Phase 5.6: `WaveBVerifyResult` / `WaveDVerifyResult` shape, `unified_build_gate.run_compile_profile_sync`, `_PHASE_5_6_INWAVE_TYPECHECK_HINT`, `_build_compile_fix_prompt(retry_payload=...)`, `build_codex_compile_fix_prompt(retry_payload=...)`, `_run_wave_compile` external contract — all untouched. HINT non-consumption lint still passes.
* Phase 5.5: `_evaluate_quality_contract`, `_finalize_milestone_with_quality_contract` (REUSED for the cumulative-cap halt; no signature change), `_quality.json` sidecar 6-field schema, `confirmation_status`, layer-2 `KNOWN_RULES`, §M.M13 dispatch-boundary suppression filter — all untouched.

---

## Verification gates passed

* **Targeted slice (§0.5 + Phase 5.{1,2,3,4,5,6,7} fixtures):** **955 passed** at HEAD post-Phase-5.7 (was 929 baseline + 26 new Phase 5.7 fixtures).
* **Wide-net sweep (§0.6):** **2235 passed**, 3 skipped, **4 pre-existing failures** matching plan §0.1.7 verbatim, 0 regressions vs Phase 5.6 baseline 2209 → +26 from new Phase 5.7 fixtures.
  * `test_cli.py::TestMain::test_interview_doc_scope_detected`
  * `test_cli.py::TestMain::test_complex_scope_forces_exhaustive`
  * `test_h3e_wave_redispatch.py::test_scaffold_port_failure_redispatches_back_to_wave_a_once`
  * `test_v18_phase4_throughput.py::test_run_prd_milestones_uses_git_isolation_path_even_when_parallel_limit_is_one`
* **Module import smoke (§0.7):** clean — `agent_team_v15.cli`, `audit_team`, `audit_models`, `fix_executor`, `wave_executor`, `state`, `agent_teams_backend`, `config`, `quality_contract`, `state_invariants`, `unified_build_gate` all import without warnings.
* **Backward-compat fixture spot-check:** Phase 1.6 / 4.{1-7} / 5.{1-6} all green byte-identical at HEAD post-Phase-5.7. `tests/test_agent_teams_backend.py` 154 fixtures green (legacy `proc.communicate()` path preserved when `stderr_observer is None`).
* **mcp__sequential-thinking + context7:** sequential-thinking used for the watchdog precedence + respawn-loop architecture lock-in. Context7 not needed in practice — Codex appserver / CLI event taxonomy was sourced from in-repo reading at `codex_appserver.py:1328-1357` + `codex_transport.py:356-385`.

---

## Smoke evidence (when applicable)

**No live AC4 + AC10 smoke executed this phase.** Per dispatch direction: AC4 (artificial bootstrap-wedge respawn) + AC10 (M3 replay against `codex_timeout_seconds=5400`) move to the closeout-smoke checklist (§O.4 rows below). Replay-fixture coverage + 26 synthetic AC + supporting fixtures + module import smoke + backward-compat slice are sufficient pre-merge evidence; the closeout smoke validates end-to-end on real Wave B/D execution.

---

## Open follow-ups (not blocking)

* AC4 live smoke (artificial bootstrap-wedge respawn) — closeout-smoke row.
* AC10 live smoke (M3 productive-tool-idle replay) — closeout-smoke row.
* `stderr_tail` populates on real bootstrap-wedge subprocess hang — closeout-smoke row.
* Cumulative-cap exit code 2 + `sdk_pipe_environment_unstable` — closeout-smoke row.
* No retry-budget increment on bootstrap respawn — closeout-smoke row.
* Provider-aware: no Codex bootstrap counting — closeout-smoke row.
* Sub-agent compile/audit/reaudit eligibility coverage — closeout-smoke row.
* §M.M11 calibration smoke for Phase 5.6 — separate operator-authorised activity (Phase 5.6 carry-over).
* `_run_wave_compile` shim removal — Phase 5.6 carry-over; follow-up commit after closeout-smoke validates.
* Phase 5.8 cross-package contract diagnostic-first (R-#42) — Wave 4. Consumes Phase 5.7's bootstrap-watchdog signal as the safety net for diagnostic M1+M2 sequential smokes.
* Phase 5.9 PRD decomposer cap (R-#43) — Wave 4.
* R-#41 closure for team-mode opaque subprocess at the 60s granularity — REVERTS to existing 400/600s sub-agent threshold per Blocker 1 fix. Phase 6+ option: switch team-mode to `--output-format stream-json` + parse JSONL chunks live.

---

## Out-of-scope items the plan flags but Phase 5.7 did NOT touch

* Phase 1 anchor primitive, Phase 2 test-surface lock, Phase 3 PreToolUse hook, Phase 3.5 ship-block, Phase 4.x cascade primitives, Phase 5.{1,2,3,4,5,6} primitives — preserved per §0.1 invariant 15.
* `score_healthy_threshold` default 90 — preserved (§M.M16).
* `_anchor/_complete/` directory name — preserved (§M.M16).
* `audit_fix_rounds` field name — preserved (§M.M16).
* Live AC4 + AC10 smoke — closeout-smoke checklist.
* Phase 5.6 `unified_build_gate` module + `WaveBVerifyResult` / `WaveDVerifyResult` + HINT + retry-payload threading — preserved.
* Phase 5.6 `_run_wave_compile` external contract — preserved.
* Phase 5.5 single-resolver / sidecar / state-invariants / dispatch-boundary suppression filter / strict §M.M13 schema validator — preserved.

---

## Surprises

1. **§J.3 says "from agent_teams_session_started event, deadline = bootstrap_idle_timeout_seconds" but the team-mode opaque path emits ONLY bookend events.** Resolved per scope check-in Blocker 1 approval option B: explicit exemption via `_mark_bootstrap_cleared_on_watchdog_state`. Tier 3 stays inert because `last_tool_call_monotonic` remains 0.0.
2. **Provider-routed Codex paths share the watchdog poll loop with provider-routed Claude paths.** Resolved via `bootstrap_eligible: bool` kwarg; caller passes `not codex_owned_route`.
3. **`update_milestone_progress` REPLACE semantic conflicts with mid-wave direct-mutation of `_bootstrap_wedge_diagnostics`.** Resolved with PRESERVE-on-skip 3-line patch.
4. **`_invoke_sdk_sub_agent_with_watchdog` previously used inline timeout logic at line 4396 (`_sub_agent_idle_timeout_seconds`, not `_wave_idle_timeout_seconds`).** Resolved via `idle_fallback_seconds` kwarg threading.
5. **Bootstrap respawn loop architecture: fresh `_WaveWatchdogState` per attempt** so stale `last_tool_call_*` from a prior wedged attempt cannot leak into the fresh attempt and cause tier 3 to fire on the new state.

---

## Note for Phase 5.8

Phase 5.8 (cross-package contract diagnostic-first per §M.M7 — R-#42) consumes Phase 5.7's bootstrap-watchdog signal as the safety net for the diagnostic M1+M2 sequential smokes:

* Phase 5.7's `_cumulative_wedge_budget` cap (default 10) protects Phase 5.8a's diagnostic-smoke loop from pathological pipe-instability days. Operators authorising Phase 5.8a smoke-batches should monitor the counter and consider `--cumulative-wedge-cap 0` only if the diagnostic phase requires unbounded environment-instability data collection (rare).
* Phase 5.7 watchdog tier-3 productive-tool-idle (1200s) is the new baseline for "model alive but not producing executable work" detection on Codex Wave C diagnostic dispatches. Phase 5.8a should expect faster failure on stale Codex turns than the pre-Phase-5.7 5400s hard Codex timeout.
* Phase 5.7's `state.stderr_tail` populates on subprocess paths automatically; Phase 5.8 cross-package contract code does NOT need to write into this field.

---

## Note for closeout smoke

The closeout-smoke checklist (§O.4 in the plan) accumulates AC4 + AC10 disk-shape verification AND the 7 carry-forward residual rows from this phase (§O.4.5 through §O.4.11 below). Phase 5.7 contributes:

* `state._cumulative_wedge_budget` non-zero on STATE.json IFF the smoke produced bootstrap-wedge respawns; zero on healthy runs.
* `<run-dir>/.agent-team/hang_reports/wave-<X>-<ts>.json::timeout_kind` populated on every wedge.
* `stderr_tail` field on bootstrap-wedge hang reports (subprocess paths) carries the last 4KB of subprocess stderr.
* `_bootstrap_wedge_diagnostics` per-milestone field on STATE.json populated when bootstrap respawn fires; per-wave dict-of-dicts shape.
* If the cumulative cap is reached during smoke, STATE.json shows current milestone FAILED with `failure_reason="sdk_pipe_environment_unstable"` and `EXIT_CODE.txt = 2`.
