# M1 Clean-Run Blockers — Fixing Team Handoff

**Date:** 2026-05-04
**Source HEAD verified against:** `85da3bb` on branch `phase-5-closeout-stage-1-remediation`
**Investigation:** 6-investigator parallel swarm (codex-transport, claude-sdk, wave-output, build-gate-parity, audit-fix-loop, watchdog-halt) + adversarial reviewer + blocker synthesizer + cross-validation against an independent 2nd swarm
**Corpus inventoried:** 17+ Stage-2B reruns (`v18 test runs/phase-5-8a-stage-2b-rerun3..rerun14-*`) + 4 Stage-1 closeout runs + 10 Stage-2 originals + reference older fixtures (`m1-hardening-smoke-*`, `m1-fast-forward-*`, `m1-wave-1-closeout-*`, `build-{e..l}-*`)
**Goal of this handoff:** definitive ranked list of source/operational blockers that, when fixed, would GUARANTEE a clean M1 + clean full multi-milestone run on the TaskFlow MINI PRD. Each item carries enough detail (file:line, defect, evidence anchors, fix shape, tests) for a fixing team to implement WITHOUT re-investigating. Cross-investigator coherence already verified.

---

## 0. How to use this document

1. **Trust but verify line numbers.** Citations in this doc were captured at HEAD `85da3bb`. Source files in this codebase are large (`cli.py` ~17000 lines, `wave_executor.py` ~10200 lines) and line numbers can drift. The fixing team MUST `git diff` against `85da3bb` and re-locate symbols by name (function name + class context) before patching. Citations in `[BRACKETS]` indicate **direct line-read by team-lead**; citations without brackets are **agent-cited and cross-corroborated by the reviewer but not re-verified line-by-line by team-lead**.
2. **Land items in TIER order (0 → 1 → 2 → 3 → operational).** Within a tier, items are independent and can be parallelized.
3. **Do NOT skip the tests required.** Each item has a TDD lock specified. Land tests in the same commit as the fix.
4. **Containment is rejected.** All recommended fix shapes are STRUCTURAL. Do not propose timeouts/kill-thresholds/retry-budget bumps as fixes — operator memory `feedback_structural_vs_containment` makes this a hard rule.
5. **Probes (where flagged) come before patches.** Several items list a "probe before fixing" — that probe must complete and the result documented before the patch lands.
6. **End-to-end smoke is the only completion proof.** Per memory `feedback_verification_before_completion`, unit tests + targeted slices are NOT sufficient to mark an item complete. The minimum-fix-set must be exercised by a real M1 smoke before claiming the goal is achieved.

---

## 1. Minimum-fix-set summary

### For "GUARANTEE clean M1 on TaskFlow MINI PRD"

Six independent items — no dependency ordering required between them; can land in any order.

| # | Title | TIER | Confidence |
|---|---|---|---|
| **B1** | Reasoning items pollute `pending_tool_starts` in BOTH watchdogs | 0 | HIGH |
| **B2** | Phase 4.5 re-self-verify dispatcher mishandles non-B/D wave failures | 0 | HIGH |
| **B4** | PRISMA-DUP scaffold/wave_boundary contradiction | 1 | HIGH |
| **B5** | Wave D fails to finalize `apps/web/*` on TaskFlow MINI | 1 | HIGH (defect); MED (fix shape) |
| **B6** | Wave self-verify host 5.6c lacks Docker 5.6b's pre-step parity | 2 | HIGH |
| **B10** | `_cancel_sdk_client` calls `disconnect()` without first calling `interrupt()` | 0 | HIGH |

### For "GUARANTEE clean full multi-milestone build (M1 + M2 + ... + Mn)"

Above six PLUS three more:

| # | Title | TIER | Confidence |
|---|---|---|---|
| **B7** | Codex appserver silent-exit instrumentation gap (folds 2nd-swarm 1c) | 3 | HIGH on gap; MED on RUST_LOG cost |
| **B8** | Cumulative-wedge counter scope vs actual failure-mode distribution (reframed with 2nd-swarm 5b) | 3 | HIGH |
| **B11** | No protocol preflight before paid Codex turn dispatch | 3 | MED |

### Defer / probe-required / operational

- **B3** — Hang report filename collision (diagnostic only; sharpened with 2nd-swarm 2a+2b)
- **B9** — UserMessage branch missing in `cli._consume_response_stream` (currently inert)
- **2nd-swarm 2c** — `wave_executor.py:4771` "auto/UNKNOWN fallback" (probe required)
- **Operational items** — six items below at TIER OPERATIONAL.

### Already-implemented (NO fixing-team action required)

- **2nd-swarm 6c** — `_phase_4_5_terminal_transport_failure_reason` exists at `cli.py:8599` and is wired at `cli.py:9438-9468` to skip audit-fix on terminal Codex transport failures. **Verified by team-lead direct read.**

### Rejected (with empirical evidence)

- **2nd-swarm #3** — "no source change for Package/Client/Prisma; current HEAD passed local readiness proof at `agent3-package-gate-20260504-104720`". **Rejected.** Replay artifact is a static synthetic test, not a real smoke. Empirical evidence from rerun7+rerun8+rerun12 shows the source defects firing live. B4 + B6 source fixes ARE required. See §11 "Rejected items" below for the full justification.

---

## 2. TIER 0 — Single-line source defects (HIGHEST PRIORITY)

### B1 — Reasoning items pollute `pending_tool_starts` in BOTH watchdogs

**Severity:** BLOCKER
**Confidence:** HIGH
**Owner surface:** Codex transport / wave watchdog
**Cross-references:** Reduces priority of B8; resolves Stage 2 Gate 2 mystery (per memory `phase_5_closeout_stage_2_landing` gate 2)

**Source location(s):**

- **PRIMARY (method-level fix):**
  - `[src/agent_team_v15/wave_executor.py:638]` — `_WaveWatchdogState.record_progress` function definition
  - `[src/agent_team_v15/wave_executor.py:717-723]` — pending_tool_starts insert/pop logic (the actual defect site):
    ```python
    if tool_id:
        if event_kind == "start":
            self.pending_tool_starts[tool_id] = {
                "tool_name": self.last_tool_name,
                "started_at": now_iso,
                "started_monotonic": now_mono,
            }
        elif event_kind == "complete":
            self.pending_tool_starts.pop(tool_id, None)
    ```
  - `[src/agent_team_v15/codex_appserver.py:282]` — `_OrphanWatchdog.record_start` method body (the parallel pollution path; reviewer's missed-angle A1):
    ```python
    with self._lock:
        self.pending_tool_starts[item_id] = {
            "tool_name": tool_name,
            "command_summary": command_summary,
            "started_monotonic": time.monotonic(),
        }
    ```

- **ALTERNATIVE (call-site filter):** `[src/agent_team_v15/codex_appserver.py:1484]` — the `item/started` dispatcher inside `_handle_event` that invokes `record_start(item_id, tool_name, command_summary=...)`. Filtering at the call site is functionally equivalent to filtering inside `record_start` for this defect. Pick ONE site per call-stack — patching both is harmless but redundant.

**Defect description:**

Both watchdog state objects insert into `pending_tool_starts` indexed by `tool_id`/`item_id` UNCONDITIONALLY — no `tool_name` filter. Codex's `_progress_from_event` at `src/agent_team_v15/codex_transport.py:449-478` extracts `tool_name` via `item.name OR item.tool_name OR item.type`. So a Codex `item.started` event with `item.type == "reasoning"` and `item.id == "rs_..."` produces `tool_name="reasoning"` AND `tool_id="rs_..."`, which both watchdogs then track AS IF it were an orphanable tool call.

But Codex doesn't reliably emit `item.completed` for older `reasoning` items when the model pivots to a new turn. (`commandExecution` items get reliable lifecycle pairs because they are real tool calls; `reasoning` items are deltas + a single completion at end-of-turn at best.) So `reasoning` entries accumulate in `pending_tool_starts` and never get popped.

**Causal chain:**

1. Codex emits `item.started type=reasoning id=rs_<hash>` mid-turn.
2. Both `_WaveWatchdogState.record_progress` (via wave_executor's progress callback) AND `_OrphanWatchdog.record_start` (via codex_appserver's `_handle_event` at line 1484) insert the reasoning item into `pending_tool_starts`.
3. Model pivots to a new line of reasoning OR concludes the turn; no `item.completed` event for the abandoned reasoning id.
4. Reasoning entry remains permanently. Tier-2 orphan-tool watchdog (`_invoke_provider_wave_with_watchdog` polling loop) checks `oldest_pending_age >= orphan_tool_idle_timeout_seconds` (default 400s).
5. After 400s of no productive activity (or even concurrent productive activity that doesn't touch this entry's tool_id), the watchdog fires `orphan-tool` on the unmatched reasoning item.
6. Wave fails on a watchdog kill that never had a real tool to wait on.

**Fix shape (RECOMMENDED — adopt 2nd-swarm narrowing):**

At BOTH primary call sites, gate insertion on **`tool_name == "commandExecution"` only** (allowlist). Reasoning, agentMessage, userMessage, and fileChange are all "progress, not orphanable":
- `reasoning` — does not always emit `item.completed` (the defect site).
- `agentMessage` — these are incremental message-content blocks, not tool calls.
- `userMessage` — these are not Codex-emitted in the wave-execute path.
- `fileChange` — completes fast (subseconds) AND already has its own tier-3 gate at `[src/agent_team_v15/wave_executor.py:701-706]` via `last_file_mutation_monotonic` refresh, so a hypothetical hung fileChange would be caught by tier-3 productive-tool-idle (1200s).

**Why allowlist over denylist:** a future Codex item type we don't yet know about (e.g. `summary`, `audio`, custom) will not pollute by default. Adversarial reviewer recommended this discipline explicitly.

**Why partial fix is forbidden:** if we filter only one site, the unfiltered watchdog still pollutes. Reviewer's missed-angle A1 makes this explicit: "C2's fix MUST be applied symmetrically at BOTH call sites."

**Empirical evidence:**

- `v18 test runs/phase-5-8a-stage-2b-rerun13-20260504-7f59707-dirty-01-20260503-210240/.agent-team/hang_reports/wave-B-20260503T211940Z.json`: `pending_tool_starts: [{tool_id: "rs_01f15428acfc1ad30169f7ba5388448191b09bb655b2b58cab", tool_name: "reasoning", started_at: "2026-05-03T21:12:51.592579+00:00", idle_seconds: 409}]` + `orphan_tool_id: rs_01f15428..., orphan_tool_name: reasoning`. Single tier-2 fire on a reasoning item.
- Corpus tally (watchdog-halt-investigator's enumeration across 53 hang reports + reviewer-corrected total): 47 of 57 hang reports are tier-2 orphan-tool, only 7 are bootstrap-class. The dominant failure mode is mid-flight orphan-tool on items the watchdog should NOT have been tracking.
- Stage 2 Gate 2 forensic memo per memory `phase_5_closeout_stage_2_landing` documents: post-orphan-monitor wedge with no Phase 5.7 fire. The forensic claim was "Phase 5.7 watchdog wiring incomplete"; the actual cause (revealed by claude-sdk-investigator F5) is that the wedge wasn't on `commandExecution` (which Phase 5.7's productive-tool-idle predicate IS keyed on) — it was on `reasoning` (which Phase 5.7 correctly classifies as non-productive). The wedge happened at tier-2 on the unmatched reasoning, not at tier-3.

**Tests required (TDD lock):**

1. **Unit:** call `_WaveWatchdogState.record_progress(message_type="item/started", tool_name="reasoning", tool_id="rs_x", event_kind="start")`. Assert `state.pending_tool_starts == {}` (reasoning was rejected).
2. **Unit:** call `_OrphanWatchdog.record_start(item_id="rs_x", tool_name="reasoning")`. Assert `watchdog.pending_tool_starts == {}`.
3. **Unit:** same for `tool_name in {"agentMessage", "userMessage", "fileChange"}` — all rejected.
4. **Unit:** call with `tool_name == "commandExecution"`. Assert entry IS inserted.
5. **Behavioural (reproduces the rerun13 wedge):** synthesize a wave session that emits `item.started type=reasoning id=rs_a`, then `item.started type=commandExecution id=ce_b`, then `item.completed id=ce_b`, then NO `item.completed` for `rs_a`. After watchdog tick at `400s + epsilon`: `pending_tool_starts` is empty (commandExecution popped, reasoning never tracked); no tier-2 orphan-tool fire.
6. **Backward-compat lint:** grep the codebase for any other call site that inserts into `pending_tool_starts` — there should be exactly the two we filter (wave_executor + codex_appserver). Lock with a static-source test.

**Land in same commit:** all six tests + both source-site filters.

---

### B2 — Phase 4.5 re-self-verify dispatcher mishandles non-B/D wave failures

**Severity:** BLOCKER
**Confidence:** HIGH (defect); MEDIUM (fix shape — depends on probe outcome)
**Owner surface:** audit-fix loop / Phase 4.5 cascade
**Cross-references:** affects 3 of 10 `audit_fix_did_not_recover_build` reruns

**Source location(s):**

- `src/agent_team_v15/cli.py:10416-10446` — Phase 4.5 re-self-verify dispatcher (`audit-fix-loop-investigator` cited; reviewer corroborated). The dispatcher branches on:
  ```python
  if failed_letter == "B":
      _b_result = run_wave_b_acceptance_test(...)
      self_verify_passed = bool(getattr(_b_result, "passed", False))
  elif failed_letter == "D":
      _d_result = run_wave_d_acceptance_test(...)
      self_verify_passed = bool(getattr(_d_result, "passed", False))
  else:
      print_warning(
          f"[AUDIT-FIX] Phase 4.5 re-self-verify: unknown failed wave letter "
          f"{failed_letter!r}; skipping re-self-verify (recovery treated as failed)."
      )
  ```
- `src/agent_team_v15/cli.py:8670` — declares `_PHASE_4_5_RECOVERY_LATE_WAVE_LETTERS = frozenset({"D", "T"})`. The frozenset CLAIMS Wave T qualifies for FAILED→COMPLETE recovery, but the dispatcher only handles B and D.
- Modules present: `wave_b_self_verify.py`, `wave_d_self_verify.py`. **Missing:** `wave_t_self_verify.py`, `wave_a_self_verify.py`, `wave_c_self_verify.py`.

**Defect description:**

When a wave fails for any letter other than B or D, the Phase 4.5 dispatcher hits the "unknown failed wave letter" `print_warning` branch. `self_verify_passed` defaults to False; the cascade writes a misleading `failure_reason="audit_fix_did_not_recover_build"` even though no recovery was attempted. Operator-visible terminal claims recovery failed when in fact recovery was never run.

**Causal chain:**

1. A wave T or A or C fails (Codex output regression, test failure, network blip, anything).
2. Phase 4.5 cascade reaches the dispatcher; `failed_letter` is "T", "A", or "C".
3. Neither `B` nor `D` matches → fall through to "unknown failed wave letter" warn branch.
4. `self_verify_passed` stays False (default initialization).
5. Cascade writes `failure_reason="audit_fix_did_not_recover_build"` — implies recovery was attempted and didn't recover.
6. Operator triages a non-recovery as a recovery failure.

**Fix shape — Option A (RECOMMENDED if probe returns "no verifiable artifact for non-B/D waves"):**

Route non-B/D wave failures through the cascade with a precise failure_reason like `audit_fix_recovery_unsupported_for_wave_<letter>`. Concretely: replace the `print_warning(...)` in the `else` branch with:
```python
else:
    print_warning(
        f"[AUDIT-FIX] Phase 4.5 re-self-verify: wave letter {failed_letter!r} "
        f"has no recovery dispatcher; routing to cascade-FAILED."
    )
    _terminal_failure_reason = f"audit_fix_recovery_unsupported_for_wave_{failed_letter.lower()}"
    # ... thread _terminal_failure_reason into the existing cascade FAILED-mark path
```

ALSO: remove `T` from `_PHASE_4_5_RECOVERY_LATE_WAVE_LETTERS` at cli.py:8670 (if Wave T has no verifiable artifact, it shouldn't be flagged as recovery-eligible).

**Fix shape — Option B (if probe returns "Wave T DOES have a verifiable artifact"):**

Add `wave_t_self_verify.py` mirroring `wave_b_self_verify.py` / `wave_d_self_verify.py`. Then add the `elif failed_letter == "T":` branch alongside B and D.

**PROBE REQUIRED before deciding A vs B:**

Read `agents.py` for Wave T's responsibility (test wave) and check if there's a verifiable post-Wave-T artifact distinct from what Wave D's self-verify already covers. Same probe for Wave A and Wave C. If no distinct artifact → Option A. If distinct → Option B per wave (Wave T self-verify, then Wave A self-verify, then Wave C self-verify).

**Empirical evidence:**

- `v18 test runs/phase-5-8a-stage-2b-rerun3-fresh-20260501-01-20260501-104516/`: BUILD_LOG shows `failed_letter='T'` + "unknown failed wave letter 'T'".
- `v18 test runs/phase-5-8a-stage-2b-rerun5-20260502-1dc1180-01-20260502-143823/`: same — `failed_letter='T'`.
- `v18 test runs/phase-5-8a-stage-2b-rerun6-20260502-b6877d3-01-20260502-173503/`: `failed_letter='A'` — confirms the gap is broader than just T (reviewer's refinement to investigator's original claim).

**Tests required:**

1. **Static-source lock:** `cli.py:10442-10446` `else` branch's failure_reason synthesis call site MUST pass a `audit_fix_recovery_unsupported_for_wave_<letter>` string when failed_letter is non-B/D.
2. **Behavioural:** synthetic Phase 4.5 invocation with `failed_letter='T'` produces STATE.json `failure_reason="audit_fix_recovery_unsupported_for_wave_t"` (Option A) OR runs `wave_t_self_verify.run_wave_t_acceptance_test` (Option B).
3. **Backward-compat:** existing `failed_letter='B'` and `failed_letter='D'` paths produce byte-identical STATE.json contents to pre-fix.
4. **Documentation:** if Option A is chosen, update `cli.py:8670` `_PHASE_4_5_RECOVERY_LATE_WAVE_LETTERS` to remove T (or add a comment explaining why T stays despite no dispatcher).

**Land in same commit:** probe outcome documented in commit message + chosen-option patch + tests.

---

### B3 — Hang report filename collision via second-precision strftime

**Severity:** HIGH (DIAGNOSTIC — does NOT block M1 directly; loses inner-tier wedge evidence)
**Confidence:** HIGH
**Owner surface:** wave_executor watchdog instrumentation
**Cross-references:** Strengthened by 2nd-swarm 2a+2b (attempt/session metadata)

**Source location(s):**

- `[src/agent_team_v15/wave_executor.py:4097]` — `_write_hang_report` filename construction:
  ```python
  path = reports_dir / f"wave-{wave}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
  ```
  **Second-precision** timestamp.
- 4 outer-wrapper call sites that don't thread `cumulative_wedges_so_far` (claude-sdk-investigator F2, reviewer verified at 5791):
  - `src/agent_team_v15/wave_executor.py:5791` (Wave B probe-fix sub-agent timeout, in `_run_wave_b_pipeline`)
  - `src/agent_team_v15/wave_executor.py:5940` (Wave T pipeline timeout)
  - `src/agent_team_v15/wave_executor.py:6516` (`_execute_wave_sdk` provider path, after `_invoke_provider_wave_with_watchdog` re-raises)
  - `src/agent_team_v15/wave_executor.py:6592` (`_execute_wave_sdk` Claude path, after `_invoke_wave_sdk_with_watchdog` re-raises)
- 3 inner sites that DO thread the field (wave_executor.py:4986-4992, 5199-5205, 5320-5333).
- 2nd-swarm related sites:
  - `[src/agent_team_v15/codex_captures.py:204-208]` — `CodexCaptureMetadata` dataclass currently has `(milestone_id, wave_letter, fix_round)` — NO attempt/session fields.
  - `[src/agent_team_v15/provider_router.py:441]` — `capture_metadata` is built ONCE at line 447-450 BEFORE the EOF retry loop at 466-504. Both attempts share metadata.

**Defect description (combined with 2nd-swarm 2a+2b):**

Two distinct sub-defects compose into one diagnostic gap:

1. **Filename collision (claude-sdk F2):** `_write_hang_report` uses second-precision `strftime`. When the inner watchdog fires and writes a hang report, the outer wrapper's `except WaveWatchdogTimeoutError` catch can fire within the same UTC second and write again. Same filename → outer overwrites inner. Inner's `cumulative_wedges_so_far` is lost.

2. **Outer sites don't thread `cumulative_wedges_so_far` (claude-sdk F2 + watchdog-halt H3c):** even if the filename collision is fixed, the outer write still produces a hang report MISSING the field — operator can't audit the cumulative wedge count from the artifact.

3. **Codex capture metadata indistinguishability (2nd-swarm 2a+2b):** when EOF retry fires (provider_router.py:466-504), both attempts share the same `CodexCaptureMetadata`. The two terminal-diagnostic.json files written from the two attempts can collide on filename AND can't be distinguished by metadata. Operator cannot tell which attempt produced which artifact.

**Causal chain (filename collision):**

1. Inner `_invoke_provider_wave_with_watchdog` watchdog fires; `_write_hang_report` writes `wave-B-<TS>.json` with `cumulative_wedges_so_far=0`.
2. Within the same UTC second, `_execute_wave_sdk` outer `except WaveWatchdogTimeoutError` (cli.py:6516) catches the re-raised exception and calls `_write_hang_report` again.
3. Outer call site doesn't pass `cumulative_wedges_so_far` (kwarg defaults — field absent from payload).
4. Same filename `wave-B-<TS>.json` → outer overwrites inner. Counter field lost.

**Empirical evidence:**

- `v18 test runs/phase-5-8a-stage-2b-rerun13-20260504-7f59707-dirty-01-20260503-210240/BUILD_LOG.txt:198` — inner ERROR at `01:19:40,586` (`[Wave B] orphan-tool wedge detected on reasoning ... fail-fast at 18s idle (budget: 400s)`).
- Same BUILD_LOG `:199` — outer ERROR at `01:19:40,594` (`Wave B timed out for milestone-1: ...`). 8ms apart, same UTC second `211940Z`.
- `v18 test runs/phase-5-8a-stage-2b-rerun13-.../.agent-team/hang_reports/wave-B-20260503T211940Z.json`: file mtime matches outer; `cumulative_wedges_so_far` field MISSING.
- Reviewer-verified field-presence tally across 28 hang reports: 25 audit (single-write inner; field present) + 1 Wave B (outer overwrote; field missing) + 2 Wave T (outer-only; field missing).

**Fix shape (RECOMMENDED — combine all three sub-fixes):**

1. **Filename:** change `[wave_executor.py:4097]` strftime from `'%Y%m%dT%H%M%SZ'` to `'%Y%m%dT%H%M%S%fZ'` and slice `[:-3]` for millisecond precision. (Or: nanosecond suffix via `time.monotonic_ns()`.)

2. **Outer-write field threading:** at all 4 outer sites (5791, 5940, 6516, 6592), pass `cumulative_wedges_so_far=_get_cumulative_wedge_count()` to `_write_hang_report`. (Or, more structurally: attach `hang_report_path` to `WaveWatchdogTimeoutError`; outer recognizes the inner already wrote and skips the second write.)

3. **CodexCaptureMetadata extension (2nd-swarm 2a):** at `[codex_captures.py:204-208]`, extend the dataclass:
   ```python
   @dataclass(frozen=True)
   class CodexCaptureMetadata:
       milestone_id: str
       wave_letter: str
       fix_round: int | None = None
       attempt_id: int = 1     # NEW
       session_id: str = ""    # NEW
   ```

4. **Provider-router metadata threading (2nd-swarm 2b):** at `[provider_router.py:441]` and surrounding, increment `attempt_id` per EOF retry inside the loop (lines 466-504); generate a `session_id` once at the dispatch boundary. Path convention becomes `<stem>-attempt-<NN>-<session-id>-terminal-diagnostic.json` PLUS a stable `<stem>-terminal-diagnostic.json` symlink/copy for backcompat (latest attempt mirror), PLUS `<stem>-capture-index.json` listing all attempts.

**Why include the 2nd-swarm variant:** the 2nd swarm's path convention is STRONGER than my swarm's millisecond precision — it carries semantic information (which attempt) not just timestamp uniqueness, and survives clock skew / suspended-resumed laptops.

**Tests required:**

1. **Unit — filename precision:** call `_write_hang_report` 5 times in a tight loop. Assert all 5 produce distinct filenames.
2. **Unit — outer field threading:** synthesize an outer-wrapper catch path. Assert the written hang_report has non-empty `cumulative_wedges_so_far`.
3. **Unit — CodexCaptureMetadata extension:** construct with new fields; assert `_capture_stem(metadata)` produces the new path convention.
4. **Behavioural (reproduces the rerun13 collision):** trigger inner watchdog fire → outer catch within same UTC second. Assert BOTH hang_reports persist on disk with distinct filenames AND inner's `cumulative_wedges_so_far` is preserved.
5. **Backward-compat:** existing capture filename consumers (audit, K.2 evaluator, stage_2b driver) still find the canonical files via the latest-mirror symlink/copy.

**Why TIER 0 even though "diagnostic":** without B3, B7's instrumentation (silent-exit RUST_LOG output) is undermined — outer overwrites would erase the very stderr_tail B7 captures. B3 is a precondition for B7 being load-bearing.

---

### B10 — `_cancel_sdk_client` calls `disconnect()` without first calling `interrupt()`

**Severity:** HIGH
**Confidence:** HIGH (verified by team-lead direct read)
**Owner surface:** Claude SDK transport teardown
**Origin:** 2nd-swarm 5c

**Source location:**

- `[src/agent_team_v15/cli.py:1561-1565]`:
  ```python
  async def _cancel_sdk_client(client: ClaudeSDKClient) -> None:
      try:
          await client.disconnect()
      except Exception:
          pass
  ```
- `[src/agent_team_v15/cli.py:1568-1579]` — `_set_watchdog_client`:
  ```python
  def _set_watchdog_client(
      progress_callback: Callable[..., Any] | None,
      client: ClaudeSDKClient,
  ) -> None:
      """If *progress_callback* is a bound ``_WaveWatchdogState.record_progress``,
      inject the *client* reference so the watchdog can call ``client.interrupt()``
      for wedge recovery."""
      ...
  ```
  The docstring at line 1573 explicitly says the codebase ANTICIPATED `client.interrupt()` for wedge recovery — but `_cancel_sdk_client` doesn't use it.

**Verified:** `client.interrupt()` exists in the Claude SDK and is used elsewhere in this codebase:
- `[src/agent_team_v15/wave_executor.py:760]` in `_WaveWatchdogState.interrupt_oldest_orphan` — `await self.client.interrupt()`
- `[src/agent_team_v15/wave_executor.py:4693]` in observer-peek wedge recovery — `await state.client.interrupt()`
- `src/agent_team_v15/observer_peek.py:102` — comment confirming the pattern.
- `src/agent_team_v15/config.py:940` — comment about disabling interrupt on log_only mode.

**Defect description:**

When a Claude SDK wave-execute call wedges (e.g., the audit Task/Agent tool stalls on parallel sub-agents — claude-sdk F1 surface), the watchdog timeout cascade calls `_cancel_sdk_client` to tear down the wedged client. The current implementation calls only `client.disconnect()` — which closes the transport without first instructing the model to gracefully stop generating. Per the SDK contract (and per the watchdog's sibling pattern at `interrupt_oldest_orphan`), `client.interrupt()` should be called BEFORE `disconnect()` to give the model a clean cancellation signal.

**Causal chain:**

1. Claude SDK wave wedges (e.g., 398 pending Agent tool starts on rerun13/wave-audit per claude-sdk F1).
2. Watchdog timeout fires; `_cancel_sdk_client(client)` is called.
3. `client.disconnect()` runs without prior `interrupt()` — model isn't given a chance to gracefully cancel.
4. Outer client teardown happens but the underlying tool execution may continue / leak resources / send extra tokens before death. Wave-fail diagnostic is noisier than necessary.

**Fix shape:**

```python
async def _cancel_sdk_client(client: ClaudeSDKClient) -> None:
    try:
        await client.interrupt()
    except Exception:
        pass
    try:
        await client.disconnect()
    except Exception:
        pass
```

(Two separate `try/except` blocks so `interrupt()` failure doesn't prevent `disconnect()`. Both swallow exceptions because teardown should be best-effort.)

**Empirical evidence:**

Indirect: claude-sdk F1's 398-pending-Agent-tool wedge on rerun13/wave-audit shows the SDK wedged before clean shutdown. The codebase's intent (cli.py:1573 comment + sibling usage at wave_executor.py:760 and :4693) supports the recommendation.

**Tests required:**

1. **Static-source lock:** `_cancel_sdk_client` body MUST contain BOTH `await client.interrupt()` AND `await client.disconnect()`, with `interrupt` ordered first. Test scans the function body via `inspect.getsource`.
2. **Behavioural:** mock client with `interrupt()` and `disconnect()` recording call order. Call `_cancel_sdk_client` and assert order is `[interrupt, disconnect]`.
3. **Behavioural — interrupt failure isolation:** mock `interrupt()` to raise; assert `disconnect()` still runs.

---

## 3. TIER 1 — Codex output template / structure defects

### B4 — PRISMA-DUP scaffold/wave_boundary contradiction

**Severity:** BLOCKER
**Confidence:** HIGH
**Owner surface:** Wave B prompt scope / scaffold seeding
**Cross-references:** subsumes the originally-flagged Prisma sub-failure (rejected by reviewer as derivative)

**Source location(s):**

- `src/agent_team_v15/wave_boundary.py:65` — Wave B scope declaration includes root-level `prisma/**`:
  ```
  prisma/** (schema.prisma + migrations + generated client setup)
  ```
- `src/agent_team_v15/wave_boundary.py:167-168` — `_GLOB_WAVE_OWNERSHIP` declares ownership glob:
  ```python
  "prisma/**": "B",
  "prisma/*": "B",
  ```
- `src/agent_team_v15/scaffold_runner.py:1100, 1851, 1904, 1912-1915` — `_scaffold_prisma_schema_and_migrations` writes seed at `project_root / "apps" / "api" / "prisma" / "schema.prisma"` (workspace-level). Comment at line 1851 explicitly says "canonical location per /prisma/prisma context7 docs".

**Defect description:**

`wave_boundary.py` declares root-level `prisma/**` is Wave B's scope. `scaffold_runner.py` calls it "canonical" to seed at workspace-level `apps/api/prisma/schema.prisma`. **These two source-of-truth statements contradict each other.** Codex Wave B reads its scope from `wave_boundary` and may write to either or both locations. Result: duplicate prisma trees on disk; auditors flag both as a duplicate; downstream `prisma generate` runs against fragmented state.

**Causal chain:**

1. Scaffold seeds `apps/api/prisma/schema.prisma` (per scaffold_runner's stated "canonical" location).
2. Wave B prompt + boundary tells Codex root `prisma/**` is its scope.
3. Codex sees both locations → unpredictable choice. May write to root, may write to workspace, may write to both.
4. When Codex writes to root: a SECOND `prisma/schema.prisma` exists. Migrations get fragmented across two trees.
5. `_discover_prisma_schemas` at `compile_profiles.py:525-534` finds BOTH; `prisma generate` runs against each.
6. Auditor flags duplicate. Build (5.6b/5.6c) may compile against either schema → undefined behavior.

**Fix shape — Option 1 (RECOMMENDED, structural):**

Align `wave_boundary.py` with the scaffold's stated canonical layout:
- `wave_boundary.py:65` — change `prisma/**` declaration to `apps/api/prisma/**`.
- `wave_boundary.py:167-168` — change ownership glob:
  ```python
  "apps/api/prisma/**": "B",
  "apps/api/prisma/*": "B",
  ```
  Remove the root `prisma/**` and `prisma/*` entries.

Single-source-of-truth: scaffold seeds workspace-canonical, wave boundary points at workspace-canonical.

**Fix shape — Option 2 (more invasive):**

Delete the scaffold seed in `_scaffold_prisma_schema_and_migrations`. Let Wave B emit prisma from scratch via the root-level prompt. Riskier — removes a known-good seed; may regress Wave B if the model doesn't reliably reproduce the seed structure.

**Fix shape — Option 3 (REJECTED, containment):**

Add a post-Wave-B sanitizer in `wave_b_sanitizer.py` to delete whichever schema is non-canonical. Reject — this is containment, not root-cause fix. Operator memory `feedback_structural_vs_containment` makes this forbidden.

**Empirical evidence:**

- 4/4 reruns of the Phase 2 deep-corpus sample (wave-output-investigator's H1 verification): smoke1, daa0e90, 5d4655e, rerun8 — all surface PRISMA-DUP findings in audit JSON.
- Smoke1's preserved tree (`v18 test runs/phase-5-8a-stage-2b-rerun3-clean-20260501-205232-01-20260501-205249/`) has BOTH:
  - `prisma/schema.prisma` (root) — "well-thought infra-only, M1 declares NO models" version
  - `apps/api/prisma/schema.prisma` (workspace) — standard scaffold-style "datasource db, generator client"
- N1 forensic memo per memory `phase_5_closeout_stage_2_n1_landing` enumerates `duplicate-prisma-tree` as one of 3 CRITICAL groups.

**Tests required:**

1. **Static-source lock:** `wave_boundary.py:167-168` `_GLOB_WAVE_OWNERSHIP` MUST contain `"apps/api/prisma/**": "B"` and MUST NOT contain `"prisma/**": "B"` or `"prisma/*": "B"`.
2. **Static-source lock:** `wave_boundary.py:65` text scope description MUST reference `apps/api/prisma/**` and MUST NOT reference root-level `prisma/**` (regex-based test).
3. **Behavioural — A-09 wave scope:** synthesize a Wave B output that writes to root `prisma/schema.prisma`. Assert the A-09 scope filter (per memory `phase_5_7_landing` etc.) flags it as a SCOPE-VIOLATION.
4. **Backward-compat:** existing scaffold seed at `apps/api/prisma/schema.prisma` continues to be written + treated as canonical by `compile_profiles._workspace_has_package_prisma_ownership` at compile_profiles.py:545-549.

---

### B5 — Wave D fails to finalize `apps/web/*` on TaskFlow MINI

**Severity:** BLOCKER
**Confidence:** HIGH (defect); MEDIUM (fix shape — depends on root-cause probe)
**Owner surface:** Wave D dispatch / scaffold-stub finalization
**Cross-references:** vendor-treadmill-sensitive (see risk register §10)

**Source location(s):**

- `src/agent_team_v15/wave_boundary.py:89-91` — emits the marker line `// @scaffold-stub: finalized-by-wave-D` as a Wave-D-targeted scaffold instruction.
- `src/agent_team_v15/wave_d_self_verify.py` — runs Wave D acceptance test but doesn't check for residual scaffold markers post-Wave-D.

**Defect description:**

Scaffold seeds files in `apps/web/**` with `// @scaffold-stub: finalized-by-wave-D` markers. Wave D is supposed to remove these markers and replace stub content with real implementations. Empirically: across 5 reruns sampled by reviewer + smoke1's compile-recovered tree, **the markers persist post-Wave-D**. The file (e.g., `apps/web/src/app/layout.tsx`) is left as a partially-scaffolded stub. Strict compile / Wave T / E2E tests fail on the unfinished frontend.

**Causal chain:**

1. Scaffold writes `apps/web/src/app/layout.tsx` (and other apps/web files) with `// @scaffold-stub: finalized-by-wave-D` markers as Wave D handoff signals.
2. Wave D runs. Codex should remove markers + replace stub content with real implementations.
3. Wave D ends with markers still present + stub content largely unchanged. (Root cause UNKNOWN — needs probe.)
4. Wave D self-verify currently does NOT check for residual markers — passes if Docker compose build passes.
5. Strict compile / Wave T tests / downstream waves operate on partially-scaffolded frontend → failure.

**PROBE REQUIRED before deciding fix shape:**

1. Read `agents.py build_wave_d_prompt` (line cited but not directly verified; locate by function name). Assess scaffold-stub finalization language. Is the prompt clear about marker removal?
2. Search for any post-Wave-D mutation that could revert Wave D's edits:
   - Is there a `wave_d_sanitizer.py` that's overwriting Wave D output?
   - Does `cli.py` Phase 4.5 anchor restore wipe Wave D's edits? (Compare smoke1's anchor-restore tree to a known-good reference.)
   - Is the sandbox restriction for Codex Wave D scoped wrong (per memory `project_wave_d_sandbox_restriction_followup`)?
3. Compare 4 reruns' Wave D protocol logs to confirm the model output IS attempting marker removal but something downstream reverts it (vs the model never attempting removal at all).

**Fix shape — Option A (prompt-level, MEDIUM confidence; vendor-treadmill-vulnerable):**

Strengthen Wave D dispatch prompt at `agents.py build_wave_d_prompt` on scaffold-stub finalization. Probe FIRST to confirm prompt is the issue.

**Fix shape — Option B (RECOMMENDED, structural; model-treadmill-immune):**

Add post-Wave-D scaffold-stub sanity check in `src/agent_team_v15/wave_d_self_verify.py`. Concretely: after Wave D acceptance test passes, scan `apps/web/**` for any remaining `// @scaffold-stub: finalized-by-wave-D` markers. If any found → fail Wave D self-verify with `retry_payload` listing the unfinalized files. Combined with Phase 4.5 cascade re-dispatch, Wave D either completes OR the milestone fails with a precise actionable failure_reason like `wave_d_scaffold_stub_unfinalized`.

This is treadmill-immune: even if a future Codex model regresses on stub finalization, the structural check forces re-dispatch with explicit feedback.

**Fix shape — Option C (probe-first, may be load-bearing):**

If the probe reveals a hostile post-Wave-D mutation source (sanitizer, anchor-restore, sandbox), fix the mutation source instead. This may be the actual root cause and Options A/B are then symptoms.

**Recommended ordering:** Probe → Option C if probe finds a mutation source → otherwise Option B (post-Wave-D sanity check).

**Empirical evidence:**

- 5 reruns sampled by reviewer (smoke1 + 4 others): all show `// @scaffold-stub: finalized-by-wave-D` markers STILL PRESENT in `apps/web/src/app/layout.tsx`.
- 4/4 deep-corpus reruns (wave-output H1) show audit findings: FRONTEND-FOUNDATION (Wave D never finalized), I18N-MISSING, RTL-MISSING, TAILWIND-TOKENS, EMPTY-MODULES — all `apps/web/*`-rooted defect classes.

**Tests required (assuming Option B):**

1. **Unit:** synthesize a Wave D self-verify with an `apps/web/src/app/layout.tsx` containing the marker. Assert self-verify FAILS with a `wave_d_scaffold_stub_unfinalized` reason.
2. **Unit — backward-compat:** synthesize Wave D output WITHOUT markers. Assert self-verify PASSES.
3. **Unit — retry_payload:** verify the failure_reason carries the LIST of unfinalized files into the retry_payload via Phase 4.2 contract.
4. **Behavioural:** integration test mocking Phase 4.5 cascade — Wave D fails → re-dispatched with retry_payload → Wave D succeeds. Asserts re-dispatch includes the list of unfinalized files.

---

## 4. TIER 2 — Build-gate parity

### B6 — Wave self-verify host 5.6c lacks Docker 5.6b's pre-step parity

**Severity:** BLOCKER
**Confidence:** HIGH on defect; MEDIUM on long-term path choice
**Owner surface:** Phase 5.6 build gate
**Cross-references:** confirms operator's own `feedback_check_builder_parity_before_blaming_codex` rule in source

**Source location(s):**

- `src/agent_team_v15/wave_b_self_verify.py:286-500` (function body); reviewer cited specific defect window at lines 359-414, 402-404 — Wave B acceptance test orchestration. Goes from Wave write → `docker_build` (5.6b) → `run_compile_profile_sync` (5.6c) WITHOUT intervening `pnpm install`, `prisma generate`, or codegen.
- `src/agent_team_v15/wave_d_self_verify.py:251-475` (function body); reviewer cited 313-384, 367-369 — Wave D mirror of the same defect.
- `src/agent_team_v15/compile_profiles.py:958-1089` — `run_wave_compile_check` (the strict compile primitive); already has Prisma pre-step at lines 985-1023 per build-gate-parity, but no openapi-ts / pnpm install / GraphQL codegen pre-steps.
- `src/agent_team_v15/templates/pnpm_monorepo/apps/api/Dockerfile:50-51` — Docker DOES run prisma generate + tsc compile via `pnpm --filter <api> build`.
- `src/agent_team_v15/templates/pnpm_monorepo/apps/web/Dockerfile:40` — Docker runs `pnpm --filter web build` which triggers next build → runs codegen scripts.

**Defect description:**

Phase 5.6 unified build gate has 3 sub-gates:
- **5.6a:** wave-scope per-service `docker compose build` (diagnostic)
- **5.6b:** project-scope all-services `docker compose build --services=None` (authoritative)
- **5.6c:** host strict TypeScript compile via `compile_profiles.run_wave_compile_check`

Docker 5.6b runs `pnpm install --frozen-lockfile` in the deps stage AND runs all codegen pre-steps (prisma generate, openapi-ts, GraphQL codegen, etc.) via the Dockerfile's `RUN pnpm --filter X build` instructions. Host 5.6c runs strict tsc directly without ANY of these pre-steps. So if Codex Wave B writes a workspace `package.json` adding a dep, host 5.6c fails on TS2307 even when Docker 5.6b passes (Docker materialized the dep; host did not).

This was the operator's own observation in memory `feedback_check_builder_parity_before_blaming_codex`: "when 5.6b passes + 5.6c fails on same artifact, root cause is builder-side pre-step parity gap not Codex output". The defect is exactly this gap, in source.

**Causal chain:**

1. Codex Wave B writes a workspace `package.json` (e.g., adds `@hey-api/client-fetch` dep) + `apps/api/prisma/schema.prisma` + service files importing `@prisma/client`.
2. `wave_b_self_verify.run_wave_b_acceptance_test` runs.
3. 5.6a (wave-scope Docker build of `api` service) — passes (Docker copies new manifest, runs `pnpm install --frozen-lockfile`, runs prisma generate, runs tsc compile in Dockerfile).
4. 5.6b (project-scope Docker build of all services) — passes.
5. 5.6c (host strict TypeScript compile via `run_compile_profile_sync`) — runs `npx tsc --noEmit` against the workspace WITHOUT first running `pnpm install` or any codegen.
6. tsc fails with TS2307 (`Cannot find module '@hey-api/client-fetch'` in `client.gen.ts:4`) or TS2305+TS2339 (`PrismaClient export missing` in `prisma.service.ts`).
7. Wave self-verify reports failure → Phase 4.5 cascade picks up → audit-fix loop OR anchor restore.
8. If Phase 4.5 cascade also runs with the same defect, recovery fails too. STATE.json shows `failure_reason="audit_fix_did_not_recover_build"`.

**Fix shape — Option B (RECOMMENDED long-term, structural):**

Collapse host 5.6c into a Docker per-service build target. Compose CLI does not expose `docker compose build --target`; use a Compose service `build.target: build` (or an equivalent `docker build --target build` probe) and invoke `docker compose build <service>`. Eliminates the parity story entirely — host runs the same Dockerfile stages Docker does, by definition. Single source of truth for what compiles.

Concretely: in `wave_b_self_verify.py:402-404` and `wave_d_self_verify.py:367-369`, replace `run_compile_profile_sync` (host strict-tsc) with a Compose service configured for Dockerfile target `build` and invoked as `docker compose build <service>` (or use `docker build --target build` for direct probes). The build target stops at the build stage of the multi-stage Dockerfile (skipping the runtime stage), so it's faster than a full runtime image build — but it includes all pre-steps including pnpm install + codegen.

**Probe required before Option B:**
- Verify the Compose `build.target: build` / direct `docker build --target build` cold-cache time fits inside the wave self-verify timeout budget (~600s per `cli.py:10421`).
- Verify the failure-output parser in `unified_build_gate.py` handles `docker compose build` stderr output for `tsc_failures` extraction (Phase 4.2 retry payload structuring).
- Confirm tsc strict-mode flags inside Dockerfile are equivalent to current 5.6c invocation (or update Dockerfile if not).

**Fix shape — Option A (RECOMMENDED short-term, structural-but-additive):**

Thread Docker pre-step chain into `wave_b/d_self_verify.py` BEFORE `run_compile_profile_sync` is called:
1. Call `wave_executor._install_workspace_deps_if_needed(cwd)` (helper exists at `wave_executor.py:8683` per build-gate-parity citation).
2. Call `compile_profiles._run_prisma_generate_if_needed` (helper exists in compile_profiles.py).
3. NEW helper `_run_openapi_ts_generate_if_needed` mirroring `_run_prisma_generate_if_needed` for `apps/web/openapi-ts.config.ts`.
4. Future helpers per generator (GraphQL Code Generator, NestJS DI metadata reflection, etc.).

**Why short-term Option A is brittle:** every new code generator opens a new parity gap. Option B (collapse host 5.6c into Docker) is the only permanent solution.

**Recommended ordering:** Land Option A as a fast unblock (closes B6 for current generator inventory). Then schedule Option B as a follow-up that retires Option A's per-generator helpers.

**Empirical evidence:**

- `v18 test runs/phase-5-8a-stage-2b-rerun3-clean-20260501-231647-daa0e90-01-20260501-231704/`: Wave B 5.6b passes; 5.6c fails with TS2305 PrismaClient missing + TS2339 $connect on `prisma.service.ts:2,10`.
- `v18 test runs/phase-5-8a-stage-2b-rerun7-20260502-fbcbeea-01-20260502-181559/`: 5.6b passes; 5.6c fails with `PRISMA_GENERATE_FAILED prisma generate failed (exit 1) ... ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL`.
- `v18 test runs/phase-5-8a-stage-2b-rerun8-20260502-1b9ee72-01-20260502-200035/`: same signature as rerun7.
- `v18 test runs/phase-5-8a-stage-2b-rerun3-clean-20260502-042133-5d4655e-01-20260502-042156/` BUILD_LOG L573-603: `PRISMA_GENERATE_FAILED prisma generate failed (exit 1) ... pnpm add prisma@6.19.3 -D --silent ... ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL`.
- `v18 test runs/phase-5-8a-stage-2b-rerun12-20260503-7f59707-01-20260503-171458/` `wave_D_self_verify_error.txt`:
  ```
  TypeScript compile-profile failures (Phase 5.6c):
  - ../../packages/api-client/client.gen.ts:4 TS2307 Cannot find module '@hey-api/client-fetch'
  - ../../packages/api-client/sdk.gen.ts:3 TS2307 Cannot find module '@hey-api/client-fetch'
  ```
- Coverage of Class A reruns (audit-fix-loop H1' quantification): 6 of 10 `audit_fix_did_not_recover_build` reruns hit the 5.6b-PASS / 5.6c-FAIL pattern.

**Tests required (Option A short-term):**

1. **Static-source lock:** `wave_b_self_verify.run_wave_b_acceptance_test` MUST call `_install_workspace_deps_if_needed` BEFORE `run_compile_profile_sync`.
2. **Same lock for `wave_d_self_verify.run_wave_d_acceptance_test`.**
3. **Behavioural:** synthesize a Wave B that adds a new dep to `apps/api/package.json`. Without fix → 5.6c fails TS2307. With fix → 5.6c passes (pnpm install ran, dep is materialized).
4. **Behavioural — prisma:** synthesize Wave B that modifies `apps/api/prisma/schema.prisma`. With fix → 5.6c passes (prisma generate ran, `.d.ts` is current).
5. **Backward-compat:** if Wave B doesn't change package.json/schema, the extra pre-steps are no-ops (idempotent). Assert no log noise / no unexpected behavior.

**Tests required (Option B long-term):**

1. **Behavioural:** a Compose service with `build.target: build` (or direct `docker build --target build`) from a freshly-Wave-B-completed state produces tsc errors when there's a TS error in service code; passes when there isn't.
2. **Performance:** cold-cache invocation completes in < 600s.
3. **Failure-output parser:** `unified_build_gate.format_tsc_failures_as_stderr` correctly extracts canonical-shape errors from `docker compose build` stderr.

---

## 5. TIER 3 — Observability / structural correctness

### B7 — Codex appserver silent-exit instrumentation gap (folds 2nd-swarm 1c)

**Severity:** HIGH (DIAGNOSTIC; will surface NEW blocker classes once instrumented)
**Confidence:** HIGH on gap; MEDIUM on RUST_LOG cost
**Owner surface:** Codex appserver instrumentation

**Source location(s):**

- `[src/agent_team_v15/codex_appserver.py:782]` — `self._stderr_lines: deque[str] = deque(maxlen=40)`. Only 40 lines retained.
- `[src/agent_team_v15/codex_appserver.py:842-847]` — `close()` method calls `task.cancel()` on stderr task before drain completes:
  ```python
  for task in (self._stdout_task, self._stderr_task):
      if task is not None and not task.done():
          task.cancel()
  await asyncio.gather(...)
  ```
- `[src/agent_team_v15/codex_appserver.py:515-525]` — `_build_transport_env` only sets `CODEX_HOME`, `CODEX_QUIET_MODE`, `RIPGREP_CONFIG_PATH`. No `RUST_BACKTRACE` or `RUST_LOG`.
- `[src/agent_team_v15/codex_captures.py:168]` — `_diagnostic_classification` returns one of 5 classes: `natural_turn_completed`, `target_thread_archive_before_turn_completed`, `transport_stdout_eof_before_turn_completed`, `terminal_error_before_turn_completed`, `diagnostic_snapshot`. The 2nd swarm proposed 3 more granular EOF phases (`after_turn_started_no_items`, `after_completed_file_change`, `after_pending_command`).

**Defect description:**

When the Codex appserver subprocess crashes or exits silently (panic in Rust code, OOM, signal), the operator has zero visibility. Three contributing causes:

1. **40-line stderr ring buffer (`_stderr_lines = deque(maxlen=40)`)** is too small. Startup chatter fills it; actual error gets evicted.
2. **`close()` cancels stderr task before drain.** Whatever stderr was buffered but unread at cancellation time is lost.
3. **No `RUST_BACKTRACE` / `RUST_LOG` env.** Even if stderr captures something, panic frames + state-transition info aren't there.
4. **Coarse EOF classification (5 classes).** Operator can't tell which phase of the turn lifecycle the EOF occurred in — making correlation with Codex internal state impossible.

Result: 6 of 7 captured `terminal-diagnostic.json` files across 4 reruns have `stderr_tail=""`. Operator effectively blind to Codex appserver crashes.

**Causal chain:**

1. Codex appserver subprocess crashes mid-turn (e.g., Rust panic, OOM, signal).
2. The 40-line stderr ring buffer fills with unrelated startup chatter, evicting any actual error.
3. `close()` cancels the stderr task before drain completes, losing whatever was buffered.
4. No `RUST_BACKTRACE` / `RUST_LOG`, so even if a panic line is captured it lacks frames.
5. Hang report's `stderr_tail` field is empty.
6. `_diagnostic_classification` returns coarse `transport_stdout_eof_before_turn_completed` — operator can't correlate with what specifically went wrong.
7. Operator triages each crash blind. Same defect class persists across reruns.

**Fix shape (combine all four sub-fixes):**

1. **Increase deque maxlen 40 → 200** at `codex_appserver.py:782`. ~5x increase; negligible memory.
2. **Await stderr drain before cancel** at `codex_appserver.py:842-847`:
   ```python
   if self._stderr_task is not None and not self._stderr_task.done():
       try:
           await asyncio.wait_for(self._stderr_task, timeout=2.0)
       except asyncio.TimeoutError:
           self._stderr_task.cancel()
   ```
3. **Set `RUST_BACKTRACE=1` and `RUST_LOG=info`** in `_build_transport_env` at `codex_appserver.py:515-525`:
   ```python
   env["RUST_BACKTRACE"] = "1"
   env["RUST_LOG"] = "info"
   ```
   Trade-off: RUST_LOG=info increases stderr volume, but with maxlen=200 ring buffer this is bounded.
4. **Granular EOF classification** at `codex_captures.py:168` — extend `_diagnostic_classification` with the 2nd swarm's 3 sub-phases:
   - `after_turn_started_no_items`: turn/started observed, no item events before EOF.
   - `after_completed_file_change`: last item before EOF was `item.completed fileChange`.
   - `after_pending_command`: pending `commandExecution` items at EOF time.
   These are sub-types of `transport_stdout_eof_before_turn_completed`.

**Empirical evidence:**

- 6 of 7 captured `terminal-diagnostic.json` files show `stderr_tail=""`. Reviewer correction: the investigator's original "7 of 7" was off by 1; one rerun9 file has 332 chars (so 1 of 7 has SOME stderr).
- `v18 test runs/phase-5-8a-stage-2b-rerun9-20260503-20f2a37-01-20260502-220755/.agent-team/codex-captures/...terminal-diagnostic.json`: 5 diagnostics, all `transport_stdout_eof_before_turn_completed`, stderr_tail empty in 4 of them.
- `v18 test runs/phase-5-8a-stage-2b-rerun14-20260504-7f59707-dirty-01-20260503-215914/.agent-team/codex-captures/milestone-1-wave-B-terminal-diagnostic.json`: same signature, stderr_tail empty.

**Tests required:**

1. **Unit — deque size:** assert `_stderr_lines.maxlen == 200`.
2. **Unit — env:** assert `_build_transport_env` includes `RUST_BACKTRACE=1` and `RUST_LOG=info`.
3. **Unit — classification:** synthesize a turn with `turn/started` then nothing → assert `_diagnostic_classification` returns `after_turn_started_no_items`.
4. **Behavioural — drain ordering:** synthesize an appserver subprocess that writes to stderr THEN closes stdout. Assert close() captures the stderr in `_stderr_lines` BEFORE cancelling the drain task.
5. **Backward-compat:** existing 5-class classification consumers continue to work with new sub-classes.

---

### B8 — Cumulative-wedge counter scope vs actual failure-mode distribution (reframed with 2nd-swarm 5b)

**Severity:** MEDIUM (only matters if B1 incomplete OR if a new wedge class emerges)
**Confidence:** HIGH
**Owner surface:** Phase 5.7 §M.M4 cumulative cap + provider_router error class
**Cross-references:** B1 reduces this; reviewer's H1 corrected count

**Source location(s):**

- `src/agent_team_v15/wave_executor.py:5172-5174` — bootstrap-wedge callback invocation in `_invoke_provider_wave_with_watchdog` (gated on `bootstrap_eligible AND tier-1 fire`).
- `src/agent_team_v15/wave_executor.py:5299-5302` — same in `_invoke_sdk_sub_agent_with_watchdog`.
- Tier-2 (orphan-tool), tier-3 (productive-tool-idle), tier-4 (wave-idle) paths do NOT call the cumulative-wedge callback (e.g. `wave_executor.py:4985-4992`).
- Counter field: `src/agent_team_v15/state.py:129` — `_cumulative_wedge_budget: int = 0`.
- `[src/agent_team_v15/provider_router.py:482]` — EOF retry catch:
  ```python
  except _CodexTerminalTurnError as exc:
      if not _is_transport_stdout_eof(exc) or retry_budget <= 0:
          # Non-EOF terminal-turn failures retain the typed propagation
          # path expected by the wave watchdog/hang-report layer.
          raise
      ...
      retry_budget -= 1
  ```
  After retry exhausted, raises original `_CodexTerminalTurnError` — no distinct stability signal.

**Defect description:**

Phase 5.7 §M.M4 designed `_cumulative_wedge_budget` to fire on bootstrap-class wedges (60s deadline, 3-respawn cap, 10-cumulative-cap halt). Per memory `phase_5_7_landing`: "increments once per Claude SDK bootstrap-wedge respawn (NOT per orphan-tool / tool-call-idle / wave-idle event)."

Empirically: counter incremented correctly once at `phase-5-closeout-stage-2a-ii-rerun-20260501-090457` (counter=2, exit=2, `failure_reason=sdk_pipe_environment_unstable`). But **47 of 57 hang reports across the corpus are tier-2 orphan-tool wedges** (not bootstrap). Counter doesn't engage on the dominant failure mode → §M.M4 cap halt cannot fire → safety net inert.

ALSO (2nd-swarm 5b): when Codex EOF retry exhausts at `provider_router.py:482`, the original `_CodexTerminalTurnError` is re-raised. There's no distinct error class signaling "Codex appserver fundamentally unstable" — downstream can't differentiate single transient EOF from chronic instability.

**Fix shape — Option 1 (RECOMMENDED if B1 lands cleanly):**

Leave the counter scope as-is. After B1, reasoning-pollution-driven orphan-tool wedge mode disappears; counter's bootstrap-only scope becomes appropriate again.

**Fix shape — Option 2 (belt-and-suspenders — recommended ALONGSIDE Option 1):**

At `provider_router.py:482`, after retry exhausted, raise a NEW distinct error class `CodexAppserverUnstableError` (or extend `_CodexTerminalTurnError` with a `repeated_eof: bool = False` field). Downstream catches this distinctly:
```python
class CodexAppserverUnstableError(_CodexTerminalTurnError):
    """Repeated Codex appserver EOF after retry; treat as environmental instability."""
```
Wire it into the cumulative-cap halt path at `cli.py` so repeated Codex EOFs (≥N within a milestone) ALSO trigger `failure_reason="codex_appserver_unstable"` + exit 2.

**Fix shape — Option 3 (broader scope redefinition; risky):**

Redefine §M.M4 contract to include orphan-tool wedges. Requires re-reading the Phase 5.7 spec for invariants Phase 5.8a may have built on top. Not recommended without operator approval — the contract was load-bearing.

**Recommended:** Option 1 (no source change) + Option 2 (distinct error class). Skip Option 3.

**Empirical evidence:**

- `v18 test runs/phase-5-closeout-stage-2a-ii-rerun-20260501-090457/.agent-team/STATE.json`: `_cumulative_wedge_budget=2`, milestone-1 `failure_reason="sdk_pipe_environment_unstable"`, EXIT_CODE.txt=`2`. Counter fires correctly on bootstrap wedges.
- Across all 17 Stage-2B reruns: `_cumulative_wedge_budget=0` (counter never engages).
- Hang report tally (watchdog-halt with reviewer correction): 43 orphan-tool + 7 bootstrap + 2 wave-idle + 1 tool-call-idle = 53 hangs (or 47+7+2+1=57 per reviewer's broader corpus). Bootstrap is a minority class.

**Tests required (Option 2):**

1. **Unit — distinct error class:** synthesize repeated EOF; assert third raise is `CodexAppserverUnstableError` (or has the `repeated_eof=True` discriminator).
2. **Unit — propagation:** assert downstream cli.py catch routes the new error to `failure_reason="codex_appserver_unstable"` + exit 2.
3. **Backward-compat:** single transient EOF still raises plain `_CodexTerminalTurnError`; downstream behavior unchanged.
4. **Static-source lock:** `provider_router.py:482` retry catch site signature.

---

### B11 — No protocol preflight before paid Codex turn dispatch (origin: 2nd-swarm 1b)

**Severity:** MEDIUM (additive instrumentation; defends against silent-startup wedges)
**Confidence:** MEDIUM
**Owner surface:** Codex appserver / dispatch path

**Source location:**

- `[src/agent_team_v15/codex_appserver.py:1570]` — `_wait_for_turn_completion`. Currently no preflight; turn dispatch happens directly.

**Defect description:**

Codex appserver may be in a broken state at startup (missing dependencies, misconfiguration, prior-process residue) and we won't know until paid turn dispatch fails. A preflight that exercises `initialize → thread/start → minimal turn/start` would catch broken appservers before paid turn dispatch — saving Codex spend AND surfacing the instability earlier.

**Fix shape:**

Add a `_preflight_codex_appserver(client)` helper invoked once per session at the start of `_wait_for_turn_completion`'s outer dispatch (or earlier in `execute_codex` lifecycle). The helper sends a minimal `initialize` + `thread/start` + `turn/start` with a no-op prompt (e.g., `"Reply OK"`) and asserts a `turn/completed` arrives within a short timeout (e.g., 30s). If preflight fails → raise a typed `CodexAppserverPreflightError` that the orchestrator catches BEFORE paid turn dispatch.

**Empirical evidence:**

Indirect: 9 of 23 reruns show Codex EOF in BUILD_LOG (codex-transport investigator's H4 enumeration). If even a fraction of these were caught at preflight, paid Codex spend would drop.

**Tests required:**

1. **Unit:** mock client where `initialize` returns OK; preflight passes.
2. **Unit:** mock client where `turn/start` produces no `turn/completed` within timeout; preflight raises `CodexAppserverPreflightError`.
3. **Unit:** mock client where `initialize` errors; preflight surfaces the error distinctly.
4. **Behavioural:** integration test against fake-appserver fixture where appserver is broken at startup; orchestrator catches preflight error and surfaces a clear failure_reason like `codex_appserver_preflight_failed`.

---

## 6. OPERATIONAL — Test driver / cosmetic / opt-in (lower priority)

These are NOT source defects in the M1 critical path. Land after the TIER 0/1/2 minimum-fix-set if budget allows.

### OP1 — Codex CLI strict-version opt-in flag (origin: 2nd-swarm 1a, MODIFIED)

- **Source:** `[src/agent_team_v15/codex_cli.py:68-94]` — `log_codex_cli_version` already emits a warning when version > `LAST_VALIDATED_CODEX_CLI_VERSION`.
- **Proposed change:** ADD an opt-in `--strict-codex-cli-version` flag that converts the warning into a hard gate (raise on drift). Default: warning behavior (current).
- **Why MODIFIED from 2nd-swarm proposal:** the 2nd swarm proposed making the gate hard by default. That's too aggressive — it locks operators out of newer Codex CLIs without override. Opt-in flag preserves current permissive behavior while giving testers a way to enforce strict.
- **Tests:** unit test asserts flag default is False; unit test asserts flag True converts warning to raise.

### OP2 — Stage-2B driver: count terminal diagnostics separately from K.2 (origin: 2nd-swarm 2d)

- **Source:** `scripts/phase_5_closeout/sequential_batch_2b.py:447`.
- **Proposed change:** in batch records, count `terminal-diagnostic.json` files separately from `PHASE_5_8A_DIAGNOSTIC.json` (K.2 evaluator inputs). Currently they may be conflated.
- **Tests:** unit test on the driver's record-aggregation path.

### OP3 — Phase 5.9 split preflight gate before paid smoke (origin: 2nd-swarm #4)

- **Source:** new gate; touches `scripts/phase_5_closeout/sequential_batch_2b.py` and/or `cli.py` argparse.
- **Proposed change:** before any paid milestone dispatch, run a HEAD-N split-validation preflight. Acceptance: split exists with metadata + pre-final Wave C deferral, OR aborts with `SPLIT_VALIDATION_PRECONDITION_FAILED.json` artifact. Operational guard, not a source defect.
- **Tests:** integration test on driver path.

### OP4 — "Schema: CLEAN" rename to avoid run-clean confusion (origin: 2nd-swarm 6a)

- **Source:** `[src/agent_team_v15/cli.py:7393]` — `_final_validation_summary.append("Schema: CLEAN")`.
- **Proposed change:** rename to `"Schema validation: PASS"` or `"Static schema check: PASS"` to disambiguate from run-clean state (per memory `feedback_forensic_memo_self_consistency` on operator confusion risk).
- **Tests:** static-source lock on the new string.

### OP5 — SIGTERM handler that marks `interrupted=True`, saves state, exits 143 (origin: 2nd-swarm 6b)

- **Source:** `[src/agent_team_v15/cli.py:14693-14694]` — currently only `signal.signal(signal.SIGINT, _handle_interrupt)`.
- **Proposed change:** add `signal.signal(signal.SIGTERM, _handle_terminate)` where `_handle_terminate` marks `state.interrupted=True`, saves STATE.json, exits 143.
- **Why operational, not blocker:** per watchdog-halt's analysis, EXIT 143 from natural watcher SIGTERM is design behavior — milestone is already terminal. The handler just makes the EXIT cleaner for mid-flight kills (rare).
- **Tests:** unit test that SIGTERM produces clean STATE.json save + exit 143.

### OP6 — Stage-2B batch records `state_truth.clean_closeout=false` flag (origin: 2nd-swarm 6d)

- **Source:** `scripts/phase_5_closeout/sequential_batch_2b.py:740`.
- **Proposed change:** batch records must include `state_truth.clean_closeout=false` for rc 143, failed milestones, pending milestones, or Gate 7 findings.
- **Tests:** unit test on driver record shape.

---

## 7. PROBE REQUIRED before fixing

### PR1 — `wave_executor.py:4771` "auto/UNKNOWN fallback" (origin: 2nd-swarm 2c)

- **Source:** `src/agent_team_v15/wave_executor.py:4771` is `_dispatch_wrapped_codex_fix` — a thin wrapper that calls `wrap_fix_prompt_for_codex(prompt)` and then `_dispatch_codex_compile_fix`.
- **2nd-swarm claim:** "stop wrapped Codex fixes falling back to auto/UNKNOWN."
- **Verification status:** team-lead direct read of lines 4771-4785 + grep for `auto`/`UNKNOWN`/`unknown` in surrounding 100 lines → no markers found. The claim may refer to the upstream `_dispatch_codex_compile_fix` function or to metadata threading in some downstream path. **Could not locate the specific defect site.**
- **Probe:** ask 2nd swarm for the exact call-stack location OR read `_dispatch_codex_compile_fix` end-to-end + downstream metadata propagation to locate the fallback.
- **Resolution:** if probe confirms a real fallback site → file as a new B-item in TIER 0 or TIER 3. If probe finds nothing → reject as unverifiable.

---

## 8. DEFERRED — currently inert

### B9 — UserMessage branch missing in `cli._consume_response_stream` (currently inert)

**Severity:** LOW (forward-compat only)
**Confidence:** HIGH
**Origin:** claude-sdk-investigator F1 (originally HIGH/HIGH; reviewer correctly demoted)

**Source:**

- `src/agent_team_v15/cli.py:_consume_response_stream` (1796-1914) lacks `elif isinstance(msg, UserMessage):` branch. Reviewer note: function name was misreported by investigator as `_process_response`; correct name is `_consume_response_stream` (1917 is a thin wrapper).

**Why inert:**

- Per claude_agent_sdk's `client.py:374` docstring: `extra_args={"replay-user-messages": None}` is required to receive UserMessage objects with uuid via `receive_response()`. Codebase does NOT set this flag.
- The codebase ALREADY handles `ToolResultBlock` inside the AssistantMessage branch at `cli.py:1881-1886`. So the legacy "tool_result inside assistant" path is covered.
- Empirical zero `usermessage` events in 25 audit hang reports is consistent with SDK simply not delivering UserMessages without the flag.

**Fix shape (forward-compat):**

Add `elif isinstance(msg, UserMessage):` branch that explicitly handles or pass-throughs with debug log. For the day someone enables the SDK `replay-user-messages` flag.

**Why deferred:** zero current-day impact. Investigator F1 originally claimed this was the dominant blocker; reviewer correctly demoted because the codebase already covers the live tool_result path inside AssistantMessage.

---

## 9. ALREADY IMPLEMENTED — no fixing-team action

### AI1 — Scan nested wave EOF errors so terminal transport failures skip audit-fix (origin: 2nd-swarm 6c)

**Status:** DONE at HEAD `85da3bb`. Verified by team-lead direct read.

**Evidence:**

- `[src/agent_team_v15/cli.py:8599-8628]` — `_phase_4_5_terminal_transport_failure_reason(wave_result)` exists and scans:
  - Attributes: `error_message`, `fallback_reason`, `failure_reason`, `error`, `hang_report_path`
  - Findings list with `code` and `message` fields
  - For 4 EOF string patterns: `transport_stdout_eof_before_turn_completed`, `transport eof + turn/completed`, `stdout eof + turn/completed`, `app-server stdout eof`
- `[src/agent_team_v15/cli.py:9438-9468]` — wired:
  ```python
  _terminal_transport_failure_reason = (
      _phase_4_5_terminal_transport_failure_reason(wave_result)
  )
  if _terminal_transport_failure_reason:
      ...
      _update_progress_transport(state, str(milestone_id), "FAILED",
                                 failure_reason=_terminal_transport_failure_reason)
      ...
      print_warning(f"[AUDIT-FIX] Phase 4.5 skipped audit-fix for milestone {milestone_id}: "
                    f"terminal Codex transport failure ...")
      return 0.0
  ```

**Action for fixing team:** SKIP. Unless 2nd swarm provides specific evidence of an EOF case the existing scan misses, this is redundant.

---

## 10. REJECTED — with empirical evidence

### REJ1 — "No source change for Package/Client/Prisma; HEAD passed local readiness proof at agent3-package-gate" (origin: 2nd-swarm #3)

**Status:** REJECTED.

**The 2nd swarm's claim:** Package/Client/Prisma fixes are NOT needed in source. Current HEAD `85da3bb` allegedly passed a local readiness proof in `v18 test runs/agent3-package-gate-20260504-104720/`.

**Why rejected:**

1. The replay artifact is a **STATIC synthetic test**, not a real smoke. Verified by team-lead `ls`:
   - `fast-forward-report.json` (42KB)
   - `generated/` directory
   - `wave-d-fixtures/` directory
   - **NO `.agent-team/STATE.json`**
   - **NO `BUILD_LOG.txt` from a real smoke run**
   - **NO Codex protocol logs**
2. Per memory `feedback_verification_before_completion`: "unit tests aren't enough; end-to-end smoke must actually fire the fix."
3. **Empirical evidence from REAL smokes contradicts the 2nd swarm's claim:**
   - `v18 test runs/phase-5-8a-stage-2b-rerun12-20260503-7f59707-01-20260503-171458/wave_D_self_verify_error.txt`: live TS2307 on `@hey-api/client-fetch` from `packages/api-client/client.gen.ts:4` and `sdk.gen.ts:3`.
   - `v18 test runs/phase-5-8a-stage-2b-rerun7-20260502-fbcbeea-01-20260502-181559/BUILD_LOG.txt`: live `PRISMA_GENERATE_FAILED + ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL`.
   - `v18 test runs/phase-5-8a-stage-2b-rerun8-20260502-1b9ee72-01-20260502-200035/BUILD_LOG.txt`: same signature.
4. The 2nd swarm's "gate items" (forced post-Wave-C pnpm relink, package-local resolver, pnpm-aware Prisma generate) ARE materially equivalent to **B6 short-term Option A** — same fixes, just framed as a gate. The disagreement is about WHERE to place the fix (gate vs source), not whether a fix is needed. **B4 (PRISMA-DUP source contradiction) and B6 (host 5.6c parity) ARE required as source fixes.**

**Action for fixing team:** Do NOT skip B4 and B6. Implement them per their respective sections above.

---

## 11. Implementation order recommendation

The minimum-fix-set is 6 items for clean M1 (B1, B2, B4, B5, B6, B10). They are independent — can land in any order — but the suggested ordering optimizes for early-feedback + low-risk-of-regression:

1. **B10 first** (single-line addition; trivial; immediately improves wedge recovery hygiene).
2. **B1 second** (allowlist filter at 2 sites; high-leverage; closes the dominant tier-2 wedge mode). Run a paid M1 smoke after B1 lands to observe the new failure-mode distribution.
3. **B2 third** (Phase 4.5 dispatcher routing; closes 3 of 10 reruns' misclassifications).
4. **B4 fourth** (PRISMA-DUP alignment; 2-line edit + scope_violations test). Probe the scaffold path first.
5. **B6 short-term Option A fifth** (thread `_install_workspace_deps_if_needed` + prisma generate into wave_*_self_verify). Land Option A as the immediate unblock.
6. **B5 with Option B sixth** (post-Wave-D scaffold-stub sanity check). Probe required first to confirm B5's root cause is Wave D output (vs hostile post-Wave-D mutation).

After all 6 land: run M1 smoke. If clean, the minimum-fix-set worked. If not, the next failure mode revealed will be one of:
- Codex appserver instability (→ B7 + B8 + B11)
- Multi-milestone-specific pattern (→ B7 minimum)
- A new defect class (→ instrumented via B7 will be visible)

For full multi-milestone build clean run: land **B7, B8, B11** after the M1 smoke. Defer **B3** unless an M1 smoke specifically loses inner-tier wedge evidence due to filename collision.

For long-term hygiene: schedule **B6 long-term Option B** (collapse host 5.6c into Docker `--target build`) as a follow-up. Eliminates per-generator parity gaps permanently.

---

## 12. Cross-cutting concerns

### Risk register

| Risk | Operator-fixable? | Mitigation |
|---|---|---|
| **Codex model treadmill** (gpt-5.5 → gpt-5.6 regresses B5 again) | Partial — structural Option B for B5 (post-Wave-D sanity check + re-dispatch) is treadmill-immune. Prompt-only Option A is vulnerable. | **ALWAYS prefer Option B for B5.** |
| **TaskFlow MINI-specific evidence** | Yes | All 9 blockers are PRD-agnostic in source defect terms but evidence comes from TaskFlow runs only. Recommend running M1 against a 2nd PRD after the minimum-fix-set lands. |
| **Wave A planner output quality** | No (vendor) | B2 protects against terminal-FAILED but doesn't auto-retry. Operator can `--retry-milestone` after Wave A regressions. |
| **5.6c↔5.6b parity drift over time** | Yes | Long-term Option B for B6 eliminates the parity story. If short-term Option A chosen, add a unit test that asserts 5.6b and 5.6c run the same step list. |
| **B1 allowlist misses a new Codex item type** | Yes | Future Codex item types not in `{commandExecution}` will not pollute by default. If a new productive item type emerges, add it to the allowlist (single-line change). B8's distinct-error-class is the safety net for repeated EOF. |
| **B5 Option B sanity check loops indefinitely** | Yes | Combine with Phase 4.5 cascade re-dispatch budget — re-dispatch up to N times, then fail with `wave_d_scaffold_stub_unfinalized`. |
| **Probe outcomes change fix shape** | Yes | The B5 root-cause probe and B2 verifiable-artifact probe are pre-implementation gates. Document probe outcome in commit message before the patch lands. |

### Operator-fixable vs vendor classification

- **All B1-B11 (and operational items) are operator-fixable in source.**
- B9 is operator-deferred (depends on SDK flag the codebase doesn't enable).
- Codex model treadmill is partially mitigable via structural Option B fixes; the residual is vendor.

### Vendor-treadmill discipline

For B5: structural Option B (post-Wave-D sanity check + re-dispatch) is REQUIRED. Prompt-only Option A is acceptable as a same-day partial mitigation but MUST be replaced with Option B in a follow-up commit. Never ship Option A as the final fix.

### Reviewer-corrected counts (for synthesis self-consistency)

- Total hang reports across corpus: **57** (reviewer's full enumeration; investigator's earlier 53 was within an earlier sub-corpus).
- Tier-2 orphan-tool wedges: **47 of 57** (87% — dominant failure mode).
- Bootstrap-class wedges: **7 of 57** (counter fires correctly on these).
- Wave-idle: 2 of 57. Tool-call-idle: 1 of 57.
- `cumulative_wedges_so_far` field present on hang reports: **25 of 28 audit hangs** (single inner write); **2 of 6 non-audit hangs** (only when inner+outer don't collide).
- Reruns with `audit_fix_did_not_recover_build` failure_reason: **8** (audit-fix-loop's count) — sub-decomposed into 6 with 5.6c parity gap (build-gate-parity territory) + 3 with Wave T/A "unknown letter" silent-skip (B2 territory) + 1 Wave D 5.6b+5.6c failure. Sum 6+3+1=10 ≠ 8 — these counts are slightly inconsistent because the audit-fix-loop investigator scoped "Stage-2B" subset (10) while watchdog-halt scoped "phase-5-closeout-* + phase-5-8a-*" superset (8 in the failure_reason category). **For purposes of fix-prioritization, treat audit-fix-loop's 10-rerun sub-decomposition as canonical** (6 → B6, 3 → B2, 1 → B6+B5).

### Test verification matrix

After EACH fix lands (in any order), run:

1. **Targeted test slice** — pytest the new tests added with the fix.
2. **Phase X regression suite** — for any phase the fix touches, re-run that phase's full test suite (e.g., touching Phase 5.7 watchdog → run `tests/test_pipeline_upgrade_phase5_7.py`).
3. **Static source lock** — verify the fix is at the exact file:line claimed by lockfile-style fixture.
4. **No regressions** — full pytest sweep should match the baseline pre-fix counts (modulo the new tests).

After ALL of B1+B2+B4+B5+B6+B10 land, run a paid M1 smoke against TaskFlow MINI. **Acceptance:** STATE.json shows milestone-1 status COMPLETE OR DEGRADED; no `audit_fix_did_not_recover_build` failure_reason; no `post_anchor_restore_degraded_tree`; no `wave_fail_recovery_attempt` terminal; clean exit.

If the smoke fails on a different failure mode, instrument with B7 next and re-smoke.

---

## 13. Pointers

- **Memory:** `/home/omar/.claude/projects/-home-omar-projects-agent-team-v18-codex/memory/MEMORY.md` (index) — most relevant entries: `project_m1_clean_run_blocker_investigation_20260504.md`, `phase_5_7_landing.md`, `phase_5_6_landing.md`, `feedback_check_builder_parity_before_blaming_codex.md`, `feedback_structural_vs_containment.md`, `feedback_verification_before_completion.md`.
- **Investigation transcripts:** in-conversation Phase 2 reports from each of 6 investigators (codex-transport, claude-sdk, wave-output, build-gate-parity, audit-fix-loop, watchdog-halt) + adversarial reviewer + blocker synthesizer.
- **Corpus:** `v18 test runs/phase-5-8a-stage-2b-rerun{3..14}-*` (17+ Stage-2B reruns) + supporting older runs.
- **2nd swarm artifact reviewed:** `v18 test runs/agent3-package-gate-20260504-104720/` (rejected as substitute for end-to-end smoke).
- **Source HEAD reference for line numbers:** `git rev-parse 85da3bb` — re-locate symbols by name before patching.

---

## 14. Closing note for the fixing team

This handoff is the canonical M1 clean-run blocker analysis as of 2026-05-04. It synthesizes ~30+ minutes of cross-checked investigation across 6 parallel investigators + adversarial review + cross-validation against an independent 2nd swarm. The minimum-fix-set is 6 source items for clean M1 + 3 more for clean full build, with operational improvements stacking on top.

**The single highest-leverage fix is B1** — correcting the unconditional pending_tool_starts insertion in BOTH watchdogs. It's a 2-site allowlist filter that closes 47 of 57 hang reports' worth of failure mode. **Land this first** if you're going to start anywhere.

If you find yourself disagreeing with a finding here: re-run the relevant probe. If a probe contradicts a finding, update this document with the new evidence + commit-link + operator approval before patching anything else. Don't silently patch around findings — the investigation's value is in cross-investigator coherence; one drift unwinds it.

Welcome aboard. Every line in this document is grounded in either a direct line-read at HEAD `85da3bb` or an agent-cited finding cross-corroborated by the adversarial reviewer.

---

## 15. Status (Wave 1 closeout 2026-05-04 — outside-reviewer-corrected)

Wave 1 internal reviewer + tester PASS'd all 6 branches, but an outside-reviewer pass on the close report rejected the batch merge with 3 blocking findings (1 framing gap on B4, 2 source-level defects on B1 and B3-broad). This §15 reflects post-outside-reviewer state. See `2026-05-04-blocker-fix-wave-1.md` for full close memo + the corrective sequence in §16 below.

| Item | Status | Branch | Tip commit | Date | Notes |
|---|---|---|---|---|---|
| **B1** | MERGED (R4 corrective + outside-reviewer cleared) | parent | `1a6bcab` (rebased; chain spans `18581c2`→`088dc4e`→`20bfe46`→`19f71d6`→`1a6bcab`) | 2026-05-04 | Round 4 fixed stale-state read at `wave_executor.py:718-720`: gate now reads CURRENT event's `tool_name` parameter, not cached `self.last_tool_name`. Bug-reproduction proof verified via revert+rerun. |
| **B2** | MERGED | parent | `d3a7982` (rebased) | 2026-05-04 | Option A locked per probe-b2 — Wave T/A/C/A5/T5/D5/E all route to cascade-FAILED with `audit_fix_recovery_unsupported_for_wave_<X>`. T REMOVED from `_PHASE_4_5_RECOVERY_LATE_WAVE_LETTERS`. |
| **B3** | MERGED (R3+R4 corrective + outside-reviewer cleared) — bundled with B12 | parent | `5ccb417` (rebased; chain spans `7245105`→`acca730`→`9bc0adc`→`19e6615`→`5ccb417`) | 2026-05-04 | Round 3 fixed retry mirror/index sequencing (3 sub-defects: bump attempt_id at start of attempt, refresh mirror after every diagnostic write incl. success-after-retry, drop attempt-1 short-circuit). Round 4 added in-place legacy-stem mirror in `write_checkpoint_diff_capture` to fix the timing-induced regression discovered in tester R3. Bug-reproduction proofs verified for both rounds. |
| **B4** | MERGED (R2 corrective broadening + outside-reviewer cleared) | parent | `19f1764` (rebased; chain spans `419bd5b`→`19f1764`) | 2026-05-04 | Round 2 broadened B4 surface into `milestone_scope.py:155` per outside-reviewer reframe of "follow-up #3" as B4-incomplete. Narrative-PRD path (live M1 PRD path) now emits canonical `apps/api/prisma/**` instead of root `prisma/**`. Bug-reproduction proof verified. |
| **B5** | MERGED | parent | `2ac06ab` (rebased) | 2026-05-04 | Option B locked per probe-b5. Post-Wave-D scaffold-stub sanity check via `_scan_scaffold_stub_unfinalized` reusing `audit_models._SCAFFOLD_STUB_RE`. New WaveDVerifyResult field `scaffold_stub_unfinalized_files`. |
| **B6** | MERGED (Wave 2; outside-reviewer cleared) | parent | `fbbe2e2` (rebased/fast-forward; chain spans `363ac35`→`3b137a9`→`fbbe2e2`) | 2026-05-04 | Option B closed with 3 sub-fixes: B6a BuildKit stderr sanitizer, B6b Dockerfile lint stages using full-scope `tsconfig.json`, B6c self-verify via Compose `build.target: lint` and plain `docker compose build <service>`. Outside-reviewer NOT-FLAGGED; integrated sweep has zero new failure names vs Wave 1 baseline. |
| **B7** | MERGED (Wave 3; outside-reviewer cleared) | parent | `311e257` (fast-forward from `wave-3-b7`) | 2026-05-04 | Codex appserver stderr ring raised to 200, `RUST_BACKTRACE=1`/`RUST_LOG=info` enabled, `close()` drains stderr with bounded `asyncio.wait_for(..., timeout=2.0)`, and EOF diagnostics now classify `after_turn_started_no_items`, `after_completed_file_change`, and `after_pending_command` while parent-keyed consumers still map to `transport_stdout_eof_before_turn_completed`. Integrated sweep at `311e257`: 12680 passed / 34 failed / 46 skipped / 2 deselected; failure-name diff vs Wave 2 baseline: 0 new, 0 disappeared. |
| **B8** | MERGED (Wave 3; outside-reviewer cleared after R5) | parent | `ac97a71` (rebased/fast-forward from `wave-3-b8`) | 2026-05-04 | Repeated Codex appserver stdout EOF now raises `CodexAppserverUnstableError` (subclass of `CodexTerminalTurnError`, `repeated_eof=True`) on retry exhaustion, preserving thread/turn/milestone IDs and routing CLI top-level through Phase 5.5 to `failure_reason="codex_appserver_unstable"` + exit 2. Corrective rounds closed provider/wave-executor propagation, sequential and parallel catch-boundaries, and the R5 empty-parent-state halt chain via exception-carried `milestone_id`. Integrated sweep at `ac97a71`: 12696 passed / 34 failed / 46 skipped / 2 deselected; failure-name diff vs `7c1a85a`: 0 new, 0 disappeared. |
| **B9** | OPEN — Wave 4 | — | — | — | Forward-compat `UserMessage` branch reopened for final Wave 4 closure; lands last per locked order. |
| **B10** | MERGED | parent | `7bc5acf` | 2026-05-04 | 4-line addition. interrupt() before disconnect() in `_cancel_sdk_client` at cli.py:1561-1565. |
| **B11** | MERGED (Wave 3; outside-reviewer cleared) | parent | `806a7a3` (rebased/fast-forward from `wave-3-b11`) | 2026-05-04 | Codex appserver now preflights each client/session with bounded `initialize` → `thread/start` → no-op `turn/start` and requires `turn/completed` before real dispatch. Startup, initialize, dispatch, timeout, and preflight turn failures raise `CodexAppserverPreflightError`; provider/wave/CLI routing preserves `failure_reason="codex_appserver_preflight_failed"` + exit 2. Corrective rounds closed startup/`CodexDispatchError` typed-boundary gaps and preflight-aware fake-client regressions. Integrated sweep at `806a7a3`: 12707 passed / 34 failed / 46 skipped / 2 deselected; failure-name diff vs `7c1a85a`: 0 new, 0 disappeared. |
| **B12** | MERGED — bundled with B3 | parent | `5ccb417` (within B3-broad chain) | 2026-05-04 | NEW item filed from probe-pr1. Operator approved TIER 2 / MED. Two threading gaps fixed in B3 r1: `_dispatch_wrapped_codex_fix` wrapper + `execute_codex` self-default forensic stem. |
| **OP1** | MERGED (Wave 4; outside-reviewer cleared after R4) | parent | `a344d22` (fast-forward from `wave-4-op1`) | 2026-05-05 | Codex CLI version drift now has a default-off strict gate: absent flag preserves warning-only behavior, while `--strict-codex-cli-version` raises `CodexCliVersionDriftError` through the live PRD/provider path. R4 closed the outer orchestration catch boundary so typed strict drift is not converted into generic interruption. Post-merge sweep: 12743 passed / 34 failed / 46 skipped / 2 deselected; failure-nodeid diff vs OP5 integrated baseline: 0 new, 0 disappeared. |
| **OP2** | OPEN — Wave 4 | — | — | — | Stage-2B terminal diagnostics counted separately from K.2 diagnostics; next in locked Wave 4 order. |
| **OP3** | OPEN — Wave 4 | — | — | — | Phase 5.9 split preflight gate before paid smoke; pending after OP2. |
| **OP4** | MERGED (Wave 4; outside-reviewer cleared) | parent | `cb0ca1e` (fast-forward from `wave-4-op4`) | 2026-05-05 | Final schema validation pass summary now emits `Schema validation: PASS`; `_phase_4_5_terminal_transport_failure_reason` remained byte-identical and preflight-first. Post-merge sweep: 12711 passed / 34 failed / 46 skipped / 2 deselected; failure-name diff vs Wave 3 baseline: 0 new, 0 disappeared. |
| **OP5** | MERGED (Wave 4; outside-reviewer cleared) | parent | `2c78835` (fast-forward from `wave-4-op5`) | 2026-05-05 | SIGTERM now marks `interrupted=True`, saves `STATE.json`, and exits 143 via a re-entrant handler with no process-group kill path. Post-merge sweep: 12717 passed / 34 failed / 46 skipped / 2 deselected; failure-name diff vs OP4 integrated baseline: 0 new, 0 disappeared. |
| **OP6** | OPEN — Wave 4 | — | — | — | Stage-2B `state_truth.clean_closeout` truth-table flag; pending after OP3. |
| **PR1** | RESOLVED → became B12 | — | — | 2026-05-04 | Probe confirmed real defect; routed through normal flow as B12. |
| **AI1** | UNCHANGED — pre-existing at HEAD `85da3bb` | — | — | — | `_phase_4_5_terminal_transport_failure_reason` already implemented per handoff §9. No fixing-team action required. |
| **REJ1** | UNCHANGED — rejected per handoff §10 | — | — | — | B4 + B6 (and now B5) source fixes ARE required. The 2nd-swarm "agent3-package-gate" replay artifact is a static synthetic test, not a real smoke. |

### Wave 1 close summary
- **6 of 11 source items + 1 PR1-elevated item (B12) MERGED onto parent.** Final integrated HEAD `19f1764`. Linear history; 12 commits ahead of `85da3bb`.
- Integrated full-sweep: **12645 passed (+69 over 12576 baseline) / 40 failed (same set as baseline; ZERO NEW failures) / 46 skipped / 2 errors / 12667 collected.**
- 3 source items (B7, B8, B11) still OPEN, gated on Phase 5 closeout-track validation + Wave 3 (per §16.1 — no internal Gate 1/2 paid smokes). B6 is merged via Wave 2.
- Wave 4 operational status: OP4 MERGED at `cb0ca1e`; OP5 MERGED at `2c78835`; OP1 MERGED at `a344d22`; OP2, OP3, and OP6 remain OPEN in locked order.
- B9 remains pending for Wave 4 forward-compat closure per §16; AI1 + REJ1 unchanged.
- 3 corrective rounds executed (B1 R4 + B3 R3+R4 + B4 R2) per outside-reviewer flags. All 3 shipped bug-reproduction proofs (revert + rerun → demonstrably FAILS; reapply → PASS). Outside-reviewer template now locked into close-memo schema for Wave 2 onward (see §16.2).

### Wave 2 B6 close summary
- **B6 MERGED onto parent at source tip `fbbe2e2`.** Linear 3-commit chain: `363ac35` (B6a) → `3b137a9` (B6b) → `fbbe2e2` (B6c). No master merge and no paid smokes.
- Integrated full-sweep at `fbbe2e2`: **12669 passed / 34 failed / 46 skipped / 2 deselected / 20 warnings**; failure-name diff vs Wave 1 cleanup baseline: **0 new, 0 disappeared**.
- Outside-reviewer verdict: **NOT-FLAGGED**. Mandatory B6c integration proof exercises direct `docker compose build api` with Compose `build.target: lint`, `docker_build(..., parallel=False)`, and Wave B retry-payload `tsc_failures` from a spec-file strict-mode error.
- See close memo `2026-05-04-blocker-fix-wave-2.md` for reviewer iterations, tester deltas, and bug-reproduction proofs.

### Wave 3 close summary (B7+B8+B11)
- **B7 MERGED at `311e257`; B8 MERGED at `ac97a71`; B11 MERGED at `806a7a3`.** All three branches cleared internal reviewer, tester, and outside-reviewer gates. No paid smokes and no master merge.
- Integrated full-sweep after B11 at `806a7a3`: **12707 passed / 34 failed / 46 skipped / 2 deselected / 18 warnings**; failure-name diff vs immutable Wave 2 baseline `7c1a85a`: **0 new, 0 disappeared**.
- Wave 3 is source-closed. Remaining initiative scope is Wave 4 (OP1-6 + B9/UserMessage forward-compat per §6/§8) followed by operator final review. Master merge remains deferred until Wave 4 + operator final review.

### Wave 1 cleanup follow-ups status
1. **B3-broad #1 — LANDED cleanup #4 (`f096cde`):** 4 additional `_write_hang_report` outer sites at `wave_executor.py:6031, 7492, 7628, 7805` now thread `cumulative_wedges_so_far` (same gap shape as the enumerated 4).
2. **B5 #1 — LANDED cleanup #3 (`677c9a4`) + hardened in cleanup #5:** source-guard tests now cover wave-filter behavior (B/T marker ignore), per-file disk-error graceful skip, and rglob-level `OSError` graceful skip.
3. **B3-broad #2 — LANDED cleanup #2 (`eb25d7c`):** ripgrep-config fixture isolation in `tests/test_phase_h3c_wave_b_fixes.py::TestWaveBRouterFixes::test_all_four_flags_on_dispatches_cleanly` — `codex_home=tmp_path` leaked `ripgrep-config` into the cwd checkpoint diff (B3-broad round 4 unblocked the deeper assertion); now isolated structurally outside cwd.

> Note: B4 #3 ("tighten `milestone_scope._derive_surface_globs_from_requirements:155` to emit `apps/api/prisma/**` for narrative-style PRDs") was promoted to a blocker during outside-reviewer pass and merged via B4-r2 (commit `19f1764`).

### Harness limitation noted
> `Agent`'s `isolation: "worktree"` flag does NOT provide per-implementer isolation in this version of the harness. Sequential or manual-worktrees with absolute paths required for parallel implementers.

Wave 2/3/4 should plan accordingly. See close memo `2026-05-04-blocker-fix-wave-1.md` for full details.

---

## 16. Initiative orchestration update (2026-05-04 — supersedes §11 + §12 smoke-gate framing)

**Operator-locked decisions during Wave 1 close that change the originally-proposed orchestration in §11 + §12.**

### 16.1 No paid smokes inside this initiative

The original §12 "Test verification matrix" called for a paid M1 smoke (Gate 1) after the minimum-fix-set lands and a full-build smoke (Gate 2) after Wave 3. Both are **REMOVED** from this initiative.

**Replacement:** the Phase 5 closeout track (Stage 2 reapproval 2A/2B/2C smokes per `project_phase_5_closeout_smoke_plan` + Stage 2D enterprise mode smoke per `project_phase_5_stage_2d_enterprise_mode_decision` + Capstone smoke) resumes after master-merge and validates the integrated stack against real builder runs. The Phase 5 track has its own already-budgeted smoke spend ($240 floor / $1140 ceiling). Don't double-pay.

**Trade-off acknowledged:** if a defect slips through, it's discovered on a Phase 5 smoke (potentially the Capstone — most expensive) rather than on a cheaper M1-only Gate 1. **Mitigation:** outside-reviewer pass becomes the SOLE per-branch validation gate beyond internal review + tests. Brief outside-reviewer agents with full gravity — they are the last line of defense before master sees this code.

### 16.2 Outside-reviewer discipline locked for ALL waves + corrective rounds

Wave 1's internal reviewer + tester PASS missed two source-level defects (B1 stale-state, B3-broad retry sequencing) and one completeness gap (B4 narrative-PRD path). An outside-reviewer pass on the close report caught all three. Per memory `feedback_adversarial_review_catches_gaps_agent_team_misses`, the adversarial-review pass is the safety net for exactly this class of miss.

**Standing rule for Wave 2 onward AND Wave 1 corrective rounds (B1-r4, B3-r3, B4-r2):**

After internal reviewer + tester PASS each branch, spawn ONE fresh outside-reviewer agent (general-purpose, no team membership) with a brief that says: *"the internal team has reported these branches PASS; verify independently against source by reading each diff end-to-end, focusing on (a) state-vs-parameter reads, (b) sequencing in retry/recovery flows, (c) completeness vs the handoff's defined surface (test the LIVE path, not just the canonical-input path), (d) cross-branch overlap claims, (e) any net-new defect classes the correction might have introduced."*

Outside-reviewer's verdict is part of the close memo. Operator merge approval is gated on outside-reviewer NOT-FLAGGED.

### 16.3 Master merge — once, at initiative end

Master merge happens **ONCE** at the natural END of this initiative — defined as:

- Waves 1+2+3+4 closed (every B-item B1-B11 + every OP-item OP1-6 + PR1 resolved + B9 closed; **nothing deferred**).
- Each branch passed internal reviewer + outside reviewer + tester before merge to `phase-5-closeout-stage-1-remediation`.
- Full pytest sweep on integrated branch HEAD clean (no regressions vs pre-initiative baseline + all new tests passing).
- Operator final review approved.

**THEN** merge to master. **THEN** Phase 5 closeout track resumes on a fresh feature branch off new master HEAD.

Do NOT propose mid-initiative master-merge for any reason. The branch is the staging area; master is the destination, reached only at full initiative close.

### 16.4 Updated wave sequence (replaces §11)

1. **Wave 1 corrective rounds.** Land B2/B5/B10 NOW (outside-reviewer cleared). Re-iterate B1-r4 + B3-r3 + B4-r2 (each through internal reviewer + tester + outside-reviewer + merge). Then land THREE out-of-scope follow-ups bundled on `wave-1-cleanup`:
   1. **B3-broad #1:** 4 additional `_write_hang_report` outer sites at `wave_executor.py:6031, 7492, 7628, 7805` lacking `cumulative_wedges_so_far` threading.
   2. **B5 #1:** B5 source-guard regression tests (B/T marker filter, per-file disk-error graceful-skip, and rglob-level `OSError` graceful-skip hardening).
   3. **B3-broad #2:** ripgrep-config fixture isolation at `tests/test_phase_h3c_wave_b_fixes.py:593` (`codex_home=tmp_path` -> isolated codex home outside cwd).

   Note: original "follow-up #3" (B4 narrative-PRD path) was promoted to B4-r2 blocker per outside-reviewer and merged via commit `19f1764`.
2. **Wave 2.** B6 with sub-fixes B6a (BuildKit stderr sanitizer) + B6b (Dockerfile lint stage with `tsconfig.json` full-scope) + B6c (self-verify lint-target collapse via Compose `build.target` or direct `docker build --target`, not `docker compose build --target`). Single impl-b6 agent, three commits within one branch. Internal review + tester + outside-reviewer.
3. **Wave 3.** B7 + B8 + B11. Each through internal review + tester + outside-reviewer.
4. **Wave 4.** OP1-6 + B9 (forward-compat) + any remaining follow-ups. Each through internal review + tester + outside-reviewer.
5. **Operator final review** on integrated `phase-5-closeout-stage-1-remediation` HEAD. Diff vs master, full pytest sweep, scan integrated commit narrative.
6. **Master merge.**
7. **Phase 5 closeout track resumes** on fresh feature branch off new master:
   - Stage 2 reapproval (2A + 2B + 2C smokes — already-budgeted)
   - Stage 2D enterprise mode smoke (after pre-Stage-2D source hardening of `cli._execute_enterprise_role_session` watchdog if not already covered by Wave 1-3 fixes)
   - Capstone smoke
   - Final Phase 5 closeout

### 16.5 Wave-close memo template — REMOVE smoke-validation steps

For Waves 1-4, the wave-close memo does NOT include a "smoke validation" step. Wave 4 close memo is the FINAL close memo of this initiative; the next thing after it is operator-review + master-merge.

Each wave-close memo SHOULD include:
- Per-item branch + tip commit + status (CLOSE-READY-MERGED / RE-ITERATION-REQUIRED / etc.)
- Internal reviewer iteration counts per item
- Outside-reviewer verdict per branch
- Tester full-sweep delta vs prior baseline
- Any out-of-scope follow-ups filed
- Harness/coordination notes (per Wave 1's worktree-isolation lesson)

### 16.6 Why this orchestration is safer despite no internal smokes

- Per-branch outside-reviewer is calibrated to catch the exact failure mode that Wave 1's internal team missed (state-vs-parameter, retry-sequencing, live-path-vs-test-path).
- The Phase 5 closeout track's smoke battery is the canonical empirical validation path for this codebase. Running independent Gate 1 + Gate 2 inside this initiative would produce evidence the Phase 5 track will independently establish anyway.
- The fixes themselves close two of the three Phase 5 Stage 2 NOT-APPROVED gates from `phase_5_closeout_stage_2_landing` (gate 1 §O.4.8 cumulative-cap STATE.json subsumed by B7+B8; gate 2 Codex provider-routed post-orphan-monitor wedge subsumed by B1's reasoning-pollution fix). Stage 2 reapproval will validate THIS initiative's fixes by definition.
