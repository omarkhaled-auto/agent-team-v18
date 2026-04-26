# HANDOFF — Codex Wave B wedge + R1 calibration resumption

**Date of handoff:** 2026-04-23
**Repo:** `C:/Projects/agent-team-v18-codex`
**Master HEAD at handoff:** `8a7f0e8 fix(codex-appserver): add orphan-watchdog diagnostic logging (#74)`
**Platform:** Windows 11 + git-bash, Python 3.11, subscription-only auth (no `ANTHROPIC_API_KEY`), console script `agent-team-v15`.

---

## ⚠️ BIG WARNING TO THE NEXT AGENT — READ THIS FIRST

**Everything in this handoff is based on what we observed and what we reasoned from it. Before you act on any recommendation below, you MUST independently verify by (a) reading the actual source files at the cited paths and line numbers, (b) running the diagnostics listed, and (c) consulting context7 (`/openai/codex`) documentation for anything protocol-related.**

**Concrete warnings:**

1. **The Codex-side wedge pattern has NOT been root-caused.** Five+ preserved runs show it; three PRs this session targeted plausible hypotheses (#72, #73, #74) and landed cleanly, but none have been proven to prevent the wedge. Any next-step plan you build MUST treat the wedge as still-open and UNEXPLAINED.

2. **Logging is currently suppressed below WARNING for `agent_team_v15.*` loggers in the smoke CLI.** PR #74 added rich INFO-level diagnostic logs to the transport watchdog; **those logs did NOT appear in the preserved run.log**. If you build your next investigation on the assumption that PR #74's logs will surface, you will be wrong. Verify the CLI's `logging.basicConfig` / handler config before relying on any INFO-level diagnostic.

3. **PR #75 (protocol capture wiring) merged and passes unit tests, but `.agent-team/codex-captures/` did NOT appear on disk in the preserved run** despite the YAML flag being set and the test verifying wiring. Either (a) my tests test a narrower pattern than reality, (b) there's another layer that gates capture session creation, or (c) the dispatch path to `_execute_once` doesn't flow through the CodexConfig we populated. **Investigate before assuming protocol capture works.**

4. **Don't blame Codex 0.122.** Pin-bump was clean. The binary has been 0.122 for weeks. Preserved runs from `2026-04-21-build-0b-auth-fail` show the identical wedge pattern — predates the pin bump, predates #72, predates most fixes.

5. **When you reason about Codex protocol behavior, use context7.** The library ID is `/openai/codex`. Specifically verify anything about: item lifecycle for `plan` items (which is what we see flagged as `todo_list` in our orphan-watchdog), streaming event guarantees for long-running turns, and whether `turn/interrupt` produces a usable continuation path or requires a fresh `thread/start`.

---

## 1. Session narrative — what we did, in sequence

### Starting point (2026-04-22)
- Master was at `d2de1be` (PR #59) with Issues 1-14 landed from the prior session.
- Goal: run Round 1 calibration (Observer on CLIBackend, `observer.log_only=true`, `agent_teams.enabled=false`) — three smoke builds, merge observer logs, check calibration gate.
- R1B1 first-attempt failed at Wave B compile (TypeScript hoisting on Windows).

### Phase 1 — remediation team (7 issues)
Spawned 7 teammates in parallel, each as its own PR:
| PR | Branch | Fix |
|---|---|---|
| #61 | codex-cli-pin-bump-0.122 | Bump `LAST_VALIDATED_CODEX_CLI_VERSION` 0.121.0 → 0.122.0 (version canary; no runtime change) |
| #62 | observer-peek-prompt-truncation | `build_peek_prompt` now caps snippets at 4000 chars, cuts on last newline, labels truncation |
| #63 | scaffold-pnpm-detection-for-template-drop | Extend hotfix #59 with pnpm detection from `pnpm-workspace.yaml` + PRD/plan text → template drops all 5 files incl `.dockerignore` |
| #64 | replay-harness-min-waves-covered-2 | YAML-configurable `observer.min_waves_covered`, default 2 (was hard-coded 4) |
| #65 | contract-e2e-skip-when-mcp-unavailable | Post-orchestration contract-compliance E2E now writes a SKIPPED marker when Contract Engine MCP is unavailable |
| #66 | scaffold-root-typescript-devdep | Root `package.json` template now includes `typescript` devDep so `npx tsc` resolves on Windows |
| #68 | state-invariant-append-resolver | `update_milestone_progress` atomically reconciles `summary.success` with `failed_milestones`; `save_state` coerces stale True |

### Phase 2 — cleanup team (7 items)
Second wave, same pattern:
| PR | Item | Action |
|---|---|---|
| #60 | task-9 | Pushed Omar's local `3567ccf` (6 TestWrapPromptForCodex assertion updates) |
| #69 | observer-integration-test-fix | Added `peek_settle_seconds=0.0` to `tests/test_observer_integration.py` harness (test predated PR #46 default) |
| #70 | cli-exit-code-consult-failed-milestones | `_exit_code_for_state` now consults `failed_milestones` + `interrupted` directly (closes issue #67) |
| #71 | observer-codex-notification-plan-event | New integration test: `turn/plan/updated` → `source=plan_event` routing |
| — | stash-cleanup | 6 pre-existing stashes dropped; stash@{5} (1,426 LoC product-ir refactor) preserved to `save/product-ir-vendor-registry-20260414` branch |
| — | worktree-cleanup | 11 worktrees removed, 14 local + 10 remote branches deleted |
| — | wave-c-python-skip (closed NO-GO) | Teammate correctly identified the follow-up was already satisfied by PR #64's recalibration |

### Phase 3 — Codex wedge response (3 PRs)
After R1B1 failed again with a new signature (Codex silently wedged on `todo_list` item_1 for 620s during re-dispatch):

| PR | Branch | Fix | Outcome |
|---|---|---|---|
| #72 | codex-appserver-handle-server-to-client-requests | Transport now distinguishes JSON-RPC requests from notifications; auto-approves `applyPatchApproval` / `execCommandApproval`; responds -32601 on unknown methods | **Did NOT prevent the wedge in R1B1-full-fixes** — 0 `APP-SERVER-REQ` log lines in the preserved run, so Codex wasn't sending approval requests. Hypothesis ruled out. |
| #73 | wave-b-self-verify-skip-when-docker-unavailable | `run_wave_b_acceptance_test` checks `check_docker_available()` first; daemon-down → `env_unavailable=True`, no retry | **Correct but not relevant this run** — Docker was up, real `pnpm run build` failed on web service |
| #74 | transport-watchdog-diagnostic-logging | `_OrphanWatchdog.snapshot_pending()`, DEBUG on record_start/complete, INFO startup/cancel/exit on monitor, periodic INFO snapshot, WARNING on orphan detection now includes full pending list | **Logs DID NOT appear in run.log** — smoke's logging config filters INFO for `agent_team_v15.*`. The diagnostic we shipped is invisible to the smoke. |
| #75 | cli-wire-protocol-capture-config | `cli.py` now sets `CodexConfig.protocol_capture_enabled` from `v18.codex_protocol_capture_enabled` | **`.agent-team/codex-captures/` did NOT appear in the preserved run** despite YAML having the flag and `load_config` reading it True. Either wiring is incomplete OR another gate blocks it. **Needs investigation.** |

---

## 2. Current master state — all merged PRs this session

```
8a7f0e8 fix(codex-appserver): add orphan-watchdog diagnostic logging (#74)
ab551a3 fix(wave-b): skip self-verify when Docker daemon is unreachable (#73)
0ac105e fix(cli): wire v18.codex_protocol_capture_enabled to CodexConfig (#75)
fe6fb7b fix(codex-appserver): respond to server-to-client approval requests (#72)
948db4e test(observer): integration test for Codex turn/plan/updated → plan_event observer log routing (#71)
8a0b1eb (pin: 70) fix(cli): harden _exit_code_for_state to consult failed_milestones ... (#70)
cf0d230 test(observer): add peek_settle_seconds=0.0 to integration test harness (#69)
7d45ce2 fix(state): make update_milestone_progress single resolver for summary.success coherence (#68)
26723a7 fix(cli): skip contract compliance E2E when contract-engine MCP unavailable (#65)
e39d537 fix(scaffold): hoist typescript into root package.json so npx tsc resolves on Windows (#66)
d53402a fix(replay_harness): make min_waves_covered configurable, default 2, grounded in 61-entry corpus (#64)
fee221b fix(scaffold): detect pnpm from workspace file + PRD when IR omits the token (#63)
b3f3f46 fix(observer): prevent mid-directive prompt truncation in build_peek_prompt (#62)
14d0a3f chore(codex-cli): bump LAST_VALIDATED pin 0.121.0 -> 0.122.0 (#61)
98f534b test(provider-routing): update TestWrapPromptForCodex for directive prefix (#60)
```

Plus the preservation branch: `save/product-ir-vendor-registry-20260414` (not a merge candidate).
Plus filed issue: `#67` (harden `_exit_code_for_state`, closed by #70).

**Every single one of these PRs passed its own tests + regression tests. Zero are known-broken. Several are unproven against the real wedge pattern.**

---

## 3. R1B1-full-fixes run (2026-04-22 ~23:00-23:40 UTC) — concrete findings

**Command:** `agent-team-v15 --prd PRD.md --config config.yaml --depth exhaustive --cwd C:/smoke/clean-r1b1-full-fixes --reset-failed-milestones`

**Preserved run:** `C:/smoke/clean-r1b1-full-fixes/` (NOTE: `mv` to preserved-* failed with "Device or resource busy" — Docker has a handle. Rename after Docker releases.)

### ✅ What worked as designed
| Signal | Value | Proves |
|---|---|---|
| All 5 template files on disk | `.dockerignore`, `apps/api/Dockerfile`, `apps/web/Dockerfile`, `docker-compose.yml`, `pnpm-workspace.yaml` | PR #63 + #66 template drops working |
| `STACK_CONTRACT.json.package_manager` | `"pnpm"` | PR #63 pnpm detection working |
| Wave B first turn | 23 files, 117 progress events, cumulative SDK calls=1 | Codex native tool flow working, no approval-request wedge |
| Docker daemon | `server=29.2.0` (healthy when smoke launched) | Env was ready |
| `check_docker_available()` | Returned True (env_unavailable stayed False) | PR #73 correctly did NOT skip; real docker_build ran |
| STATE.json wave_progress | `current_wave=B, completed_waves=[A], failed_wave=B` | PR #68 state invariants logging correctly |

### ❌ What did not work
| Signal | Evidence |
|---|---|
| Wave B acceptance test 1st attempt | `WAVE_FINDINGS.json`: `service=web, error="target web: failed to solve: process \"/bin/sh -c pnpm run build\" did not complete successfully: exit code: 1"` — frontend compile error in Codex's first-attempt code |
| Wave B re-dispatch wedge | Line 333 of run.log: `[Wave B] orphan-tool wedge detected on todo_list (item_id=item_1), fail-fast at 611s idle (budget: 600s)` — **IDENTICAL to R1B1-server-req-fix (620s) and preserved-2026-04-22-build-1-dual-layer-10ok (615s)** |
| Fallback to Claude | Line 335: `Wave B: skipping Codex after wedge and routing retry directly to Claude fallback` |
| M1 failed | Line 464: `Warning: Milestone milestone-1 failed: Wave execution failed in B` |
| Diagnostic logs from #74 | **Zero** `ORPHAN-MONITOR` lines; **zero** `agent_team_v15.*` log lines; **zero** `Orphan tool detected` (pre-existing) lines; **zero** `App-server initialized` lines |
| Protocol captures from #75 | **`.agent-team/codex-captures/` directory was never created** |
| Observer log | 13 entries, 0 FPs, waves {B:11, A:2} — same shape as prior runs |

### Wedge pattern — cross-run evidence

| Run | Wave | Tool | item_id | Silence (s) |
|---|---|---|---|---|
| preserved-2026-04-21-build-0b-auth-fail | B | command_execution | item_73 | 610 |
| same run | D | command_execution | item_83 | 605 |
| preserved-2026-04-22-build-1-dual-layer-10ok | B | todo_list | item_1 | 615 |
| preserved-2026-04-22-build-1-peek-filter | B | command_execution | item_44 | 605 |
| preserved-2026-04-22-roundA-build1-FAILED-M1 | — | (Wave B compile failed first) | — | — |
| R1B1-server-req-fix (2026-04-22) | B | todo_list | item_1 | 620 (re-dispatch) |
| R1B1-full-fixes (2026-04-22) | B | todo_list | item_1 | 611 (re-dispatch) |

**Invariants:**
- Silence always 600-620s — that's our 600s wave-executor budget firing
- Tool type varies: `command_execution` AND `todo_list`
- item_id varies: 1, 44, 73, 83 — position-agnostic
- All occur on re-dispatch turns AFTER an initial successful turn (except dual-layer-10ok which wedged on first item)
- **Cumulative SDK calls stayed at 1 during the silence window** → Codex had ONE outstanding HTTP call to the model backend that never returned or never streamed. Our client was waiting on that stream.

### The functional issue revealed this run
The frontend `pnpm run build` fails on Codex's first-attempt code. Codex on re-dispatch SHOULD be able to fix it — but wedges. So the calibration pipeline is blocked on two independent bugs:
1. **Codex's first-attempt Wave B produces a broken Next.js build** (compile error in `apps/web`)
2. **Codex's re-dispatch to fix it wedges for 600s+ in silent streaming**

Either bug alone would be fixable; together they fail M1.

---

## 4. Remaining tasks + open investigations

### Task list state (from `~/.claude/tasks/`)
- ✅ `#1` R1B1 completed (as "ran, failed at M1 Wave B compile" — the original R1B1 outcome)
- 🔄 `#2` R1B2 — **BLOCKED** by the wedge (R1B1 has never produced a promotable observer log)
- ⏳ `#3` R1B3 — pending
- ⏳ `#4` R1 merged calibration report + gate check
- ⏳ `#5`-`#8` Round 2 (TeamBackend, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`)
- ✅ `#9` Tech-debt PR (closed via #60)
- 🔄 `#10` Worktree cleanup (completed by cleanup team; a few `fix/*` and `feat/*` locals remain)
- ⏳ `#11` Final deliverable: promotion verdict report
- Untracked in the task list: Docker-restart cleanup, postmortem of the `.LOCAL-WIP-20260422` divergent file in `docs/plans/`

### Open investigations needed BEFORE next R1B1 attempt

**INV-1. Why did PR #74's diagnostic logs NOT appear in run.log?**
- Hypotheses:
  - (a) The smoke CLI configures a root logger at WARNING and `agent_team_v15.codex_appserver` inherits that
  - (b) The CLI redirects stdout to run.log but logger goes to stderr, which also lands in run.log via `2>&1` — but with a level filter
  - (c) Some other log routing quirk
- How to verify: read `src/agent_team_v15/cli.py` near the top for `logging.basicConfig`, or find the top-level logger setup. Check what level gets set by default.
- Fix direction (if confirmed): either bump my new logs to WARNING, or fix the CLI's default to INFO for `agent_team_v15.*` loggers.

**INV-2. Why did `.agent-team/codex-captures/` NOT appear despite PR #75?**
- Hypotheses:
  - (a) PR #75 wires `CodexConfig.protocol_capture_enabled`, but the dispatch path to `_execute_once` is NOT through the `codex_config` object built in `cli.py:3601`. There may be a separate path (provider_router? wave_executor? wave_a5_t5.py:463 also builds a `_CodexConfig`?) that doesn't get the flag.
  - (b) `capture_session` is created but writes are gated on `capture_enabled=True` passed as a kwarg — which is set separately in provider_router.py:434 based on `v18.codex_capture_enabled` (NOT `codex_protocol_capture_enabled`). These are two different flags with two different paths (see config.py:1019 + 1026).
  - (c) The capture directory is created lazily on first write; if no capture-worthy events fire, no dir.
- How to verify: `grep -n "codex-captures" src/agent_team_v15/*.py` to find the actual write path. Trace the gate from YAML flag → capture-session-write.
- Fix direction: may require a THIRD wiring fix OR a rename to unify the two flags into one.

**INV-3. What is Codex actually doing during the 600s silence? (protocol-level)**
- Hypotheses:
  - (a) Model-side stream hang (OpenAI backend is slow / stalled on a long reasoning chain)
  - (b) Codex app-server is waiting for a stdin response we didn't send (similar to #72 but for a different request type)
  - (c) Codex's Guardian/Auto-Reviewer review lifecycle event (`item/autoApprovalReview/started`) blocks waiting for client response — we don't handle this method
  - (d) `thread/compact/*` events during long turns may block similarly
- How to verify: get protocol capture working (INV-2 first), then look at the EXACT last notifications before silence + the first after (if any). Context7 `/openai/codex` documents `item/autoApprovalReview/*` as `[UNSTABLE]` — could have changed shape between 0.121 and 0.122.
- Fix direction: TBD based on data.

**INV-4. Why did the transport-level 300s watchdog not fire?**
- We have `_OrphanWatchdog(timeout_seconds=300.0, max_orphan_events=2)` per-turn, and `_monitor_orphans` polls every 60s. It should fire `turn/interrupt` at ~300s if an item is pending. But NO `Orphan tool detected: ... sending turn/interrupt` log line appeared in any wedged run.
- Hypotheses:
  - (a) Transport watchdog's `pending_tool_starts` was empty when check_orphans polled (items never registered OR quickly completed and new ones replaced them)
  - (b) Monitor task was cancelled by a parent scope before hitting its first poll
  - (c) The log line is at WARNING but was being filtered (unlikely — ` wave-executor's own WARNING level logs DID appear)
  - (d) `_monitor_orphans` was never actually created in the path Codex took for the re-dispatched turn
- How to verify: after INV-1 is fixed (logs visible), observe ORPHAN-MONITOR startup + snapshot lines in the next run. They'll tell us which hypothesis is right.

**INV-5. Why does Codex's first-attempt Wave B produce a failing `pnpm run build` for `apps/web`?**
- Possibly stack-research gap, missing peer dep, TypeScript/ESLint config mismatch, or a Next.js 15.5.15 build constraint
- Not a blocker to calibration if we can get the re-dispatch wedge fixed — the retry would succeed. But if we lower retries to 0 (see recommendation below), we need this clean on first attempt.

---

## 5. Recommended plan for an absolute clean run

**⚠️ CAVEATS — READ BEFORE EXECUTING:**
- The recommendation below is **my reasoning from the observed evidence**, NOT a validated plan. **Do not treat any step as proven**.
- **Investigate INV-1 through INV-4 FIRST**. Do not jump to "apply these fixes and run". Every fix this session that looked right in theory failed to prevent the wedge in practice.
- **Use context7 `/openai/codex` aggressively** — whenever a step references Codex protocol behavior, verify the docs against your current Codex binary version (`codex --version`). Context7 has been useful for the JSON-RPC request/response methods and item-lifecycle events.
- **Every time you propose a fix, ASK: has this pattern been tried before this session?** If yes, understand WHY the prior attempt didn't work before proposing the same thing again.

### Step-by-step (with required verification gates)

**Step 1 — Restore full visibility (INV-1)**
- Read `src/agent_team_v15/cli.py` top-level for `logging` setup. Find the root logger level.
- Run: `grep -nE "logging\.(basicConfig|getLogger|setLevel)|LOG_LEVEL" src/agent_team_v15/cli.py | head -20`
- Choose between: (a) bump `agent_team_v15.*` logger to INFO by default for smoke runs, OR (b) bump PR #74's new log lines to WARNING so they pass whatever filter is in place.
- **Verification gate before proceeding**: run a dummy smoke that exits quickly and confirm `[ORPHAN-MONITOR] started` appears in run.log. If not, stop and re-investigate.

**Step 2 — Restore protocol capture (INV-2)**
- Trace the `capture_enabled=True` path in `provider_router.py:434-451`. It reads `v18.codex_capture_enabled` (different key from `codex_protocol_capture_enabled`).
- Read `config.py:1019-1026` for both flag definitions and their intended semantics.
- Check whether `wave_a5_t5.py:463` (second CodexConfig construction site I found) needs the same wiring fix.
- Confirm via context7 `/openai/codex` that the protocol capture format (newline-delimited JSON-RPC on a per-turn log file) is what we want.
- **Verification gate**: launch a 10-second Codex turn and assert `.agent-team/codex-captures/*-protocol.log` appears with at least `thread/start` request+response.

**Step 3 — Only once 1+2 are verified, relaunch R1B1 with the same config as R1B1-full-fixes**
- Config: preserved at `C:/smoke/clean-r1b1-full-fixes/config.yaml` (observer log_only=true, min_waves_covered=2, peek_settle_seconds=5.0, v18.codex_protocol_capture_enabled=true, agent_teams.enabled=false).
- Fresh cwd: `C:/smoke/clean-r1b1-postwedge/` (or similar — DON'T reuse `clean-r1b1-full-fixes` which is Docker-locked).
- Expected outcome IF wedge repros: we now have (a) ORPHAN-MONITOR log trail, (b) full protocol capture. Analyze those to root-cause INV-3 + INV-4.

**Step 4 — Depending on capture evidence, one of:**
- **4a. If protocol capture shows Codex sent a request method we don't handle:** extend `_AUTO_APPROVE_SERVER_REQUEST_METHODS` in `codex_appserver.py:377` with the new method. Example candidates per context7: `item/autoApprovalReview/started` (Guardian/Auto-Review), MCP elicitation methods.
- **4b. If protocol capture shows Codex emits NOTHING during silence (pure model hang):** add a structural escape — implement mid-turn `turn/interrupt` dispatch from wave-executor layer at, say, 400s of silence, followed by a NEW `turn/start` with "continue where you left off" context. Requires keeping the client/thread alive across the wave-executor and transport layers (non-trivial).
- **4c. If protocol capture shows Codex emits events but our parser drops them:** fix the parser. Look at `_process_streaming_event` at `codex_appserver.py:1015` and trace every branch.
- **DO NOT propose 4a/4b/4c without data from Step 3's capture.**

**Step 5 — ONCE Wave B retry path is viable, attempt three R1 builds in sequence**
- Preserve each as `C:/smoke/preserved-YYYY-MM-DD-roundA-buildN/`
- Merge observer logs per handoff §2 of the prior session's handoff (saved at `C:/Users/Omar Khaled/.claude/plans/handoff-session-2.md`)
- Run `generate_calibration_report` with `min_waves_covered=2` (the merged default)
- Round 1 gate: `build_count >= 3`, `false_positive_rate < 0.05`, `waves_covered >= 2`, `safe_to_promote == True`

**Step 6 — Round 2 (TeamBackend)**
- `export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- `agent_teams.enabled` defaults to True at `--depth exhaustive`
- 3 builds, verify `run.log` contains `select_backend: returning AgentTeamsBackend`
- Additional R2 gate: observer_log.jsonl must contain ≥1 `source=plan_event` AND ≥1 `source=diff_event`. If zero, the H-C probe described in the prior handoff is the follow-up.

**Step 7 — Final deliverable to user (per-build table, verbatim calibration stdout, promotion verdict, commit list, issues with VERIFIED lines, remaining risks, recommended next actions).**

### Alternative short-path (if investigations 1-2 take longer than an hour)
- Set `runtime_verification.wave_b_self_verify_max_retries: 0` in the smoke config. This ACCEPTS whatever Wave B authors on the first turn (no retries on build failure). Won't fix the pnpm build error but lets us at least measure the observer path end-to-end without the wedge path firing.
- **CAVEAT: this masks the retry wedge; the bug is still there. Use only to unblock calibration data collection, NOT as a permanent fix.** Re-open the wedge investigation when time permits.

---

## 6. Hard rules (restate in every agent dispatch)

- NO `ANTHROPIC_API_KEY`. Subscription only via `claude login`.
- NO wrapping `agent-team-v15` in `cmd.exe /c`.
- NO flipping `observer.log_only: false` until BOTH rounds genuinely pass (not at-boundary).
- NO edits to stock PRD / config in `v18 test runs/`.
- NO deletion of preserved run directories.
- NO `--no-verify`, `--amend` of pushed commits, force-push (even `--force-with-lease`).
- NO parallel calibration builds (ports 5432/5433/3080 + subscription quota collide).
- NO claiming "fixed" without empirical end-to-end repro.
- NO bundling unrelated fixes into one commit.
- NO timeouts/retries/kill-switches in place of root-cause fixes. If the wedge requires a 1200s budget to dodge the hang, that's a band-aid — find the structural cause.
- NO agent going idle on a scope question without timeout or explicit lead answer.

---

## 7. Critical files map (post-session-2)

| Area | File | Key lines |
|---|---|---|
| Transport: JSON-RPC request handling | `src/agent_team_v15/codex_appserver.py` | `_CodexJSONRPCTransport._read_stdout:789+`, `_handle_server_request:718`, `_AUTO_APPROVE_SERVER_REQUEST_METHODS:377` |
| Transport: orphan watchdog + diag logging | same file | `_OrphanWatchdog:160`, `snapshot_pending:~230`, `_monitor_orphans:1069` |
| Transport: capture session bootstrap | same file | `protocol_capture_enabled` gate at `~1628` |
| Transport: turn interrupt helper | same file | `_send_turn_interrupt:1044` |
| CLI: CodexConfig construction | `src/agent_team_v15/cli.py` | `~3601-3628` (setattr chain) — INV-2 check both this AND `wave_a5_t5.py:463` |
| Config: two capture flags | `src/agent_team_v15/config.py` | `codex_capture_enabled:1019` (provider_router gate) and `codex_protocol_capture_enabled:1026` (transport gate) — **TWO DIFFERENT FLAGS** |
| Provider router: codex dispatch + capture metadata | `src/agent_team_v15/provider_router.py` | `~434` (reads `codex_capture_enabled` NOT `codex_protocol_capture_enabled`) |
| Wave B self-verify + env-skip | `src/agent_team_v15/wave_b_self_verify.py` | `run_wave_b_acceptance_test`, `WaveBVerifyResult.env_unavailable` |
| Wave executor retry loop + env-skip handler | `src/agent_team_v15/wave_executor.py` | `~6485-6605` (self-verify retry loop with env_unavailable break) |
| Wave executor orphan-tool watchdog | same file | `_WaveWatchdogState`, `_orphan_tool_idle_timeout_seconds:2477` (default 600s), `_log_orphan_tool_wedge:2610` |
| State invariant resolver | `src/agent_team_v15/state.py` | `update_milestone_progress:~424` (atomic reconciliation), `save_state:~595-614` (coerce-stale-True) |
| CLI exit-code guard | `src/agent_team_v15/cli.py` | `_exit_code_for_state:1867` |
| Observer peek prompt | `src/agent_team_v15/observer_peek.py` | `build_peek_prompt:47-90` (cap 4000, newline-cut) |
| Replay harness gate | `src/agent_team_v15/replay_harness.py` | `_DEFAULT_MIN_WAVES_COVERED=2`, `_resolve_min_waves_covered` |
| Scaffold pnpm detection | `src/agent_team_v15/scaffold_runner.py` | `_resolve_package_manager_for_scaffold:~1138`, called from `run_scaffolding:~453` |
| Scaffold root TS devDep | same file | `_root_package_json_template` |
| pnpm-monorepo template | `src/agent_team_v15/templates/pnpm_monorepo/` | 5 files + manifest |

---

## 8. Budget estimate for the next session

- INV-1 + INV-2 (restore visibility): 1-2 hours with careful investigation
- Step 3 launch + 10-20 min smoke: 30 min
- INV-3 + INV-4 analysis based on capture data: 1-3 hours
- Step 4 fix: 1-4 hours depending on which branch
- Steps 5-7 (6 calibration smokes + report): 3-4 hours wall-clock
- Total: **7-13 hours if the wedge fix is structural**; could be shorter if the wedge turns out to be a one-line `AUTO_APPROVE_SERVER_REQUEST_METHODS` addition.

---

## 9. Things that were surfaced but NOT fully addressed this session

- `docs/plans/2026-04-14-bug-12-rootcause-postmortem.md.LOCAL-WIP-20260422` — parked file from a prior operator's divergent commit on bug-12-watchdog work. Content not reviewed. `diff`-able against master's canonical `2026-04-14-bug-12-rootcause-postmortem.md` — do we keep their WIP or discard?
- `save/product-ir-vendor-registry-20260414` branch — 1,426 LoC product-ir refactor (schema v2, vendor registry). Preserved but not merged. Decision needed.
- Cleanup-team left 9 local feature branches that ARE merged (via squash) but weren't in the approved delete set (see `worktree-cleanup-iso` Phase 2 report). Low-priority follow-up.
- `v18.codex_capture_enabled` vs `v18.codex_protocol_capture_enabled` — two independent flags with confusing names. If INV-2 turns out to be the flag mismatch, propose a unification PR.
- Docker Desktop on this Windows host is flaky — 500 errors require manual Quit/Relaunch + WSL --shutdown. Not a code issue but a documented environmental pain point.

---

## 10. One-paragraph summary for the next agent's first action

**Read this handoff end-to-end. Do NOT skip any section. Then, before touching any smoke config or opening any PR, run `grep -nE "logging\\.(basicConfig|getLogger|setLevel)" src/agent_team_v15/cli.py` and confirm what level the smoke's `agent_team_v15.*` loggers are at — if they're above INFO, PR #74's diagnostic work is invisible and your next run's data will be as blind as the last three. Every single proposed fix in this handoff has a "verify before acting" gate. Respect them.**

---

_End of handoff — 2026-04-23_
