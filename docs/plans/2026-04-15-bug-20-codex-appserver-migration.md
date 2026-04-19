# Bug #20 — Migrate codex transport from `codex exec` CLI to `codex app-server` RPC

**Status:** draft
**Severity:** HIGH — structural fix for the codex-path reliability class (supersedes Bug #18).
**Date:** 2026-04-15
**Supersedes:** `2026-04-15-bug-18-codex-orphan-tool-failfast.md` (do not implement Bug #18).
**Depends on:** PR #6 (merged) for orphan-tool telemetry; post-closeout master.
**Reference runs:** `v18 test runs/build-h-full-closeout-20260415/`,
`v18 test runs/build-i-full-closeout-retry-<date>/` (two-wedge run; M1 failed without Claude fallback).
**Upstream research:** context7 `/openai/codex` — see §2 and §7.

---

## 1. Why this supersedes Bug #18

Bug #18 proposed an orphan-tool detection shim on top of the current `codex exec` transport
(parse JSONL → detect `command_execution` with `item.started` and no `item.completed` → kill
subprocess → retry codex). That shim is ~150 LOC of throw-away code we'd delete the moment
Bug #20 lands. The `feedback_structural_vs_containment.md` rule applies: containment patches
on top of a broken transport are only acceptable as belt-and-suspenders on top of a real
fix. Bug #20 is the real fix; #18 is the containment. Skip the containment. Ship the fix.

Bug #18's *detection idea* (watch for orphan tool starts past a threshold) stays valid — we
just implement it inside the new transport using app-server primitives instead of wrapping
subprocess teardown.

## 2. What app-server mode actually gives us

Verified against `/openai/codex` docs via context7 on 2026-04-15:

### 2a. Primitives we gain

| Primitive | What it does | Solves |
|---|---|---|
| `thread/start` → `turn/start` | Agent-level turn API (equivalent to `codex exec`) | Same agent semantics, richer observability |
| `turn/interrupt` RPC | Gracefully cancel a turn in progress; server emits `turn/completed status=interrupted` | Replaces `taskkill /F /T`; keeps session recoverable for a re-prompt |
| `item/started` / `item/completed` streaming | Each tool call (`command_execution`, file edit, etc.) emits start + end events | First-class orphan detection; no JSONL parsing hacks |
| `item/agentMessage/delta` streaming | Chunked model reasoning output | Liveness signal *between* tool calls — today codex looks "idle" during reasoning |
| `command/exec/outputDelta` (if agent tool streams) | Chunked stdout/stderr from agent-invoked shell tools | Detect stdout-flushing tools as "alive" even before `item/completed` |
| `model/rerouted` | Backend-side model switch notification | Telemetry signal we miss today |
| `turn/diff/updated` | Aggregated unified diff after every file change | First-class file-change telemetry without our own diffing |
| `thread/tokenUsage/updated` | Streaming token usage deltas | Real-time cost signal vs end-of-run-only today |

### 2b. What app-server does NOT give us (honest non-goal)

- **Per-tool-timeout on the codex agent's internal shell tool calls.** The `command/exec`
  RPC with `timeoutMs` is a *client→server* primitive (for the TUI to run side commands).
  When the codex agent itself decides to run `npm install` as part of a turn, that shell
  call goes through the agent's internal tool-execution path, not through our client-side
  `command/exec`. We cannot pass `timeoutMs` into it from the client.
- **What this means:** the core "npm install wedges without flushing stdout → codex waits
  forever" scenario is NOT automatically fixed by the migration alone. We still need an
  orphan-tool watchdog. But — and this is the key — the watchdog in app-server mode uses
  `turn/interrupt` for recovery, which preserves the session instead of killing it.
- **Mitigation upstream:** if codex's config.toml ever exposes a per-tool timeout key, we
  set it. Today (codex 0.66.0) the documented config keys are `model`, `sandbox`,
  `approval_policy`, `model_reasoning_effort`, `analytics`, `mcp_servers`, `apps`,
  `features`, `notify` — no tool-timeout knob. File a codex CLI issue if worth pushing
  upstream; but don't gate on it.

### 2c. Net architectural win

Even accounting for 2b, the migration is worth it because:

1. **Turn-level cancellation without session death.** Today a watchdog fire means SIGKILL
   the whole codex process, lose the session, Claude fallback starts Wave B from zero. In
   app-server mode, a watchdog fire means `turn/interrupt`, the session stays alive, we
   send a new `turn/start` with a corrective prompt ("the previous turn's shell tool
   wedged on X — skip it and continue"). The session has all the context from the prior
   turn's work.
2. **Richer liveness signals.** `item/agentMessage/delta` and `outputDelta` let us
   distinguish "codex is reasoning (alive)" from "codex is wedged (dead)." Today we can't.
3. **Structured telemetry.** `turn/diff/updated` and `thread/tokenUsage/updated` replace
   several hundred lines of our own JSONL-parsing and diff-snap code.
4. **First-class tool lifecycle.** PR #6's orphan-tool detection becomes a trivial
   `item/started` tracker with no string-matching on event kinds.

## 3. Python SDK vs direct JSON-RPC over stdio

Two viable implementation paths. Recommendation below.

### 3a. Option A: Official Python SDK (`codex_app_server`)

```python
from codex_app_server import Codex, TextInput

with Codex() as codex:
    thread = codex.thread_start(model="gpt-5.4", config={"model_reasoning_effort": "high"})
    turn = thread.turn(TextInput(prompt))
    for event in turn.stream():
        if event.method == "item/started": ...
        elif event.method == "item/completed": ...
        elif event.method == "turn/completed": ...
```

- **Pros:** High-level, matches codex's own notebook examples. Fresh imports, session
  management, and event streaming all wrapped. Thread-safe against the one-consumer-per-
  client caveat.
- **Cons:** Experimental and not on PyPI (install from source: `cd sdk/python && pip
  install -e .`). Requires `codex-cli-bin` runtime package pin. Upstream calls it
  "unstable until the first public release" — interface may break between codex versions.
- **Versioning:** we'd pin codex CLI and the SDK commit together in `pyproject.toml`.

### 3b. Option B: Direct JSON-RPC over stdio

Spawn `codex app-server --listen stdio://` ourselves, write framed JSON-RPC to stdin,
consume JSON-RPC notifications from stdout.

- **Pros:** No dependency on the experimental Python SDK. Only uses Python stdlib (json,
  asyncio subprocess). Fully under our control — we can match the exact cancellation /
  teardown semantics we need. Stable against codex SDK churn as long as the wire protocol
  stays stable.
- **Cons:** More code (~300 LOC of RPC client plumbing, vs ~150 LOC using the SDK). We
  reimplement request/response correlation, notification dispatch, and error
  classification.

### 3c. Recommendation: **Option B (direct RPC).**

Rationale:
- Our current `codex_transport.py` is already async-subprocess-JSONL plumbing. Moving to
  async-subprocess-JSON-RPC is a smaller conceptual step than adding a new experimental
  dependency.
- The Python SDK's "experimental, unstable" labeling is a real risk in a pipeline that
  already has brittle codex behavior. We don't want a codex SDK update to silently change
  our teardown semantics.
- Direct RPC lets us fine-tune cancellation — we know exactly which requests are in flight
  and can cancel precisely.
- We retain the cost/pricing model code from the current transport unchanged; only the I/O
  layer changes.

## 4. Implementation steps

Branch from post-closeout `master`: `bug-20-codex-appserver-migration`.

### 4a. Scaffold the new transport alongside the old one

- Create `src/agent_team_v15/codex_app_server_transport.py` (new file).
- Expose the same public surface as `codex_transport.py`:
  - `@dataclass CodexConfig` (reuse).
  - `@dataclass CodexResult` (reuse).
  - `async def execute_codex(prompt, config, cwd, codex_home, progress_callback) -> CodexResult` (reuse signature).
  - `def is_codex_available() -> bool` (reuse).
- Implement `execute_codex` over `codex app-server --listen stdio://`:
  1. Spawn the server as an async subprocess with pipes.
  2. Write `initialize` (capabilities, protocolVersion) → await `initialize` response.
  3. Write `thread/start` with `{model, config: {model_reasoning_effort, sandbox, approval_policy}, cwd}`.
  4. Write `turn/start` with the Wave prompt.
  5. Stream JSON-RPC notifications in a task; forward to `progress_callback` with structured fields (`message_type=turn_started/item_started/item_completed/...`, `tool_id`, `event_kind`).
  6. Accumulate token usage from `thread/tokenUsage/updated`.
  7. Accumulate file changes from `turn/diff/updated` (single most recent diff = final turn diff).
  8. On `turn/completed`: build `CodexResult` with `success=(status=="completed")`,
     `final_message` from the last `item/agentMessage` completion, `duration_seconds`,
     `files_created`/`files_modified` parsed from the final diff, cost from token usage +
     existing pricing table.
  9. On our own watchdog/cancellation: send `turn/interrupt` + wait up to 15s for
     `turn/completed status=interrupted` → then tear down subprocess. Preserve the session
     (next `turn/start` can carry a corrective prompt).
  10. On process exit before `turn/completed`: drain stdout/stderr, mark `success=False`,
      surface stderr in `error_message`.

### 4b. Wire the orphan-tool watchdog at the transport layer

- Reuse `_WaveWatchdogState.pending_tool_starts` from PR #6 — keyed by
  `item.item.id` which becomes `tool_id`, valued with `{tool_name, started_monotonic}`.
- Record on `item/started` (tool-type items only — filter on item shape). Pop on
  `item/completed`.
- Every 60s inside the transport's streaming loop (or wire into the existing heartbeat
  observer), compute the oldest pending tool's age. If it crosses
  `config.v18.codex_orphan_tool_timeout_seconds` (default 300s), fire a
  `CodexOrphanToolError`.
- The watchdog catches the exception → calls `turn/interrupt` → waits for graceful turn
  close → returns a `CodexResult` tagged with `orphan_tool_events`.

### 4c. Wire provider_router to retry codex with a corrective prompt

- In `_execute_codex_wave`, on `CodexOrphanToolError`:
  1. Log `[Wave X] codex orphan tool <name> (<age>s) — turn/interrupt + retry (attempt N/2)`.
  2. Build a corrective prompt: prepend `"The previous turn's shell tool (tool_name=...)
     stalled for >Xs. Do not run that tool; continue the remaining work using alternative
     approaches (e.g., direct file writes instead of build/install commands)."` — this is
     the key advantage over Bug #18: we keep the session, codex retains context, we just
     nudge it past the wedged command.
  3. `turn/start` with the corrective prompt.
- Default `config.v18.codex_max_attempts = 2`. After 2 orphan events in one wave, THEN
  fall back to Claude via `_claude_fallback`.
- Non-orphan `WaveWatchdogTimeoutError` (session-level idle — rare after this fix) still
  triggers immediate Claude fallback.

### 4d. Fix the existing Claude-fallback-on-timeout gap observed in `build-i`

Observed in `build-i-full-closeout-retry-<date>`: when the wave-level watchdog fires on a
codex timeout, `WaveWatchdogTimeoutError` propagates up to `wave_executor` and marks M1
failed — `_claude_fallback` is never called. This is a pre-existing wiring bug independent
of Bug #20, but it's cheap to fix in the same PR:

- In `_execute_codex_wave` in `provider_router.py`, add a try/except around the codex call:
  catch `WaveWatchdogTimeoutError` (and `CodexOrphanToolError` past its retry budget) → log
  + call `_claude_fallback` → return with `fallback_used=True`, `fallback_reason="watchdog"`.

### 4e. Feature-flag the rollout

- Add `config.v18.codex_transport: Literal["exec", "app-server"] = "exec"`. Default stays
  `exec` so this can land without breaking anyone; flip to `app-server` after the stock
  smoke validates parity.
- Provider_router chooses `codex_app_server_transport` vs `codex_transport` based on the
  flag.
- After one clean validation smoke at `app-server`, flip default to `app-server` in a
  one-line follow-up PR.

### 4f. Deprecate the old transport (follow-up)

Once `app-server` is the default and has run clean smokes for ≥2 weeks, delete
`codex_transport.py` and the feature flag. Separate PR.

## 5. Tests (TDD)

File: `tests/test_codex_app_server_transport.py`. All tests use an in-process mock RPC
server (a coroutine that reads framed JSON-RPC from our client's stdin-like pipe and emits
JSON-RPC notifications). No real codex CLI involved.

### 5a. Happy path (mandatory)

1. **Single turn completes cleanly.** Mock emits `turn/started`, `item/started` (tool),
   `item/completed`, `item/agentMessage/delta` (×N), `item/completed` (final msg),
   `turn/completed status=completed`. Assert `result.success=True`,
   `result.exit_code=0`, cost computed correctly from `thread/tokenUsage/updated`.
2. **File changes extracted from `turn/diff/updated`.** Mock emits two diffs; assert
   `result.files_created` and `files_modified` parsed from the final diff.
3. **`progress_callback` receives structured events.** Assert callback called with
   `message_type`, `tool_name`, `tool_id`, `event_kind` for each item lifecycle event.

### 5b. Orphan tool detection + recovery (core of the bug)

4. **Orphan detected + `turn/interrupt` sent.** Mock emits `item/started` for a
   `command_execution` tool and never emits `item/completed`. Our transport's watchdog
   should fire at 300s (advance monotonic clock), send `turn/interrupt`, receive
   `turn/completed status=interrupted`, raise `CodexOrphanToolError`.
5. **Corrective retry sends a new `turn/start` on the same thread.** Mock first turn
   orphans; second turn completes cleanly. Assert `result.success=True`, `codex_attempts_used=2`,
   corrective prompt contains the wedged tool's name.
6. **`turn/interrupt` timeout → subprocess teardown.** Mock ignores `turn/interrupt`. Our
   transport waits 15s, then tears down subprocess (bounded `proc.kill()` + Windows
   `taskkill /F /T` fallback — carried over from PR #2's existing helper).

### 5c. Cancellation + fallback wiring

7. **Wave-level `WaveWatchdogTimeoutError` triggers Claude fallback.** Mock a
   session-level idle (no events at all). Watchdog at 1800s (session timeout, NOT orphan
   tool timeout). Assert `_claude_fallback` called, `fallback_used=True`,
   `fallback_reason="watchdog"`.
8. **Two orphan events exhaust codex retries → Claude fallback.** Mock orphans twice.
   Assert `codex_attempts_used=2`, `_claude_fallback` called after.

### 5d. Edge cases

9. **Non-zero `turn/completed status=failed` surfaces error_message.** Mock emits turn
   error; assert `result.success=False`, `result.error_message` contains server error text.
10. **Subprocess crashes mid-turn.** Mock process exits before `turn/completed`. Assert
    `result.success=False`, stderr captured.
11. **Feature flag picks the right transport.** `config.v18.codex_transport="exec"` calls
    `codex_transport.execute_codex`; `"app-server"` calls the new module.

### 5e. Existing-test preservation

- All `tests/test_codex_transport.py` tests stay green (they test the old transport,
  which we keep under the feature flag).
- `tests/test_provider_router.py` gets new cases for the two retry/fallback flows; existing
  cases stay green.

Target count: ~20 new tests, zero regressions in the existing suite.

## 6. Calibration plan

After TDD + unit suite green, run one stock smoke at `codex_transport: "app-server"` with
`codex_orphan_tool_timeout_seconds: 300`:

- Expected behavior: Wave B completes on codex without fallback. Any orphan events land in
  telemetry with the tool's name and age. If none fire, the threshold is fine.
- If an orphan fires on a legitimate slow command (e.g., fresh `npm install` on cold cache
  crossing 300s), bump threshold to 450s and re-smoke.
- If two orphan retries exhaust and Claude fallback kicks in: investigate the specific
  tool in the hang report, consider adding a per-tool allowlist with custom timeouts.

## 7. Upstream references (context7 /openai/codex, 2026-04-15)

- `sdk/python/docs/getting-started.md` — Python SDK install + synchronous turn example.
- `codex-rs/app-server/README.md` — full JSON-RPC protocol spec: `thread/start`,
  `turn/start`, `turn/interrupt`, `command/exec`, `command/exec/terminate`,
  streaming event types.
- `codex-rs/README.md` — config.toml keys (confirms no per-tool-timeout knob).
- `sdk/python/notebooks/sdk_walkthrough.ipynb` — full end-to-end example of driving the
  server from Python.
- `/ben-vargas/ai-sdk-provider-codex-cli` — Vercel AI SDK reference implementation,
  confirms the RPC protocol is production-usable.

## 8. Non-goals (explicit)

- **Do not patch codex CLI itself.** Not our code. If upstream ever adds per-tool timeouts
  to `command_execution` tool calls, we remove our orphan-detection layer and let codex
  handle it. Until then, we shim.
- **Do not attempt to kill individual grandchild shell processes from outside.** We can't
  reliably traverse codex's session's process tree cross-OS. `turn/interrupt` is the right
  abstraction.
- **Do not change provider_router's Claude-branch code path.** Claude waves stay exactly
  as they are.
- **Do not bump any timeouts in config.yaml.** 300s orphan threshold + 1800s session
  watchdog are the knobs; no milestone-level changes.
- **Do not delete `codex_transport.py` in this PR.** Feature flag stays; deletion is a
  follow-up after 2 weeks of clean app-server runs.
- **Do not couple this to Bug #17 / #18 / #19 plans.** They're superseded; delete or mark
  superseded as part of this PR's doc hygiene.

## 9. Memory-of-prior-mistakes hooks

- `feedback_structural_vs_containment.md`: this is the structural fix. PR #6's
  `pending_tool_starts` diagnostic is the observation layer; Bug #20 is the action layer.
  No per-wave outer timeouts added; no dead-code safety nets; detection and recovery both
  live in the transport where the blocking call actually sits.
- `feedback_verification_before_completion.md`: unit tests prove the mechanism. End-to-end
  proof is a stock smoke at `codex_transport: "app-server"` where Wave B clears with
  `provider=codex`, `fallback_used=False`, `codex_attempts_used ∈ {1, 2}`. Don't claim
  "codex is reliable now" until that telemetry is in hand.
- `project_v18_hardened_builder_state.md`'s line 27–28: deferred "fail-fast on orphan tool
  stalls" with threshold calibrated from one clean production run with PR #6's diagnostics
  — the `build-i` evidence supports 300s as the starting threshold (first wedge went to
  1800s; legitimate codex tool bursts completed in <120s in earlier runs).

## 10. Sequencing

1. This closeout merges to master (PRs #3–#9 as applicable, depending on Phase 3's
   strict grade).
2. Open `bug-20-codex-appserver-migration` branch from master.
3. Build (steps in §4), TDD (§5), unit suite green.
4. Calibration smoke (§6) — expect 2–3h wall clock, ~$10 budget.
5. If smoke clears with codex on Wave B, flip default + one-line follow-up PR.
6. Two weeks of clean runs → delete old `codex_transport.py` + feature flag.

Estimated cost to ship Bug #20: **1 week of focused work, ~$15 in validation smokes**.
Estimated cost NOT to ship (keep losing 30–60 min per run to wedges): same ~$15 every
2–3 runs.

---

## 11. Findings this migration resolves

Cross-reference with `docs/plans/2026-04-15-builder-reliability-tracker.md` (2026-04-15 triage
of build-j). Bug #20 is **not** a gate for M1 clearance — the tracker's Sessions 1–6 close all
6 Tier-1 blockers without touching the codex transport. Bug #20 is quality investment work for
post-closeout reliability.

**Materially resolved by Bug #20:**

1. **D-12 — Telemetry `last_sdk_tool_name` blank in final wave telemetry.** App-server mode
   emits `item/started` events with structured `tool_name` over a streaming channel, so the
   "last tool name" becomes a natural side effect of the transport layer. No need for D-12's
   finalize-timing fix on the codex path. (Claude path still needs it, but Claude doesn't
   have the orphan-tool issue that made D-12 visible.)

2. **Pre-existing Wave-level `WaveWatchdogTimeoutError` → claude fallback wiring gap.** §4d
   of this plan includes the try/except around `_execute_codex_wave`. PR #10 already shipped
   a narrower form of this fix (catches `WaveWatchdogTimeoutError` inside
   `provider_router._execute_codex_wave` → `_claude_fallback`). Bug #20 adds the app-server
   layer to that path; the wiring is already in place but will need a minor update to handle
   the new `CodexOrphanToolError` exception type past its retry budget.

**Indirectly helped by Bug #20 (reduced exposure, not structurally fixed):**

3. **A-10 — Wave D compile-fix budget exhaustion after fallback.** Bug #20's turn-level
   recovery (corrective prompt on same session) reduces how often Wave B/D fall back to
   Claude at all. When fallback fires less, compile-fix exhaustion exposure is proportionally
   lower. Does NOT fix the exhaustion scenario itself — Session 7 (A-10 + D-15 + D-16) is
   still needed.

4. **D-15 — Compile-fix loop lacks structural triage.** Same reasoning: less fallback ⇒ less
   compile-fix workload ⇒ less pressure on the triage gap. Still needs the fix; Bug #20
   shrinks the blast radius.

5. **D-16 — Post-fallback Claude output doesn't compile.** Same reasoning. Bug #20 doesn't
   change what Claude produces when it IS invoked; it just reduces how often that happens.

**Explicitly NOT resolved by Bug #20:**

- A-01 through A-08 (scaffold correctness: docker-compose, port 3001, vitest, `.gitignore`, etc.) — codex has nothing to do with scaffold template output.
- A-09 (Wave D/B over-build M2–M5 during M1) — scope enforcement lives in wave prompt construction, orthogonal to transport.
- C-01 (auditor milestone scope) — audit-layer, not codex.
- D-01 (Context7 quota) — environmental, not codex.
- D-02 through D-11, D-13, D-14, D-17, D-18, D-19, D-20 — orchestration, recovery, state, verification layers, all upstream or downstream of codex.

**Honest ROI:** Bug #20 resolves 1 tracker item materially (D-12, and only for codex path),
indirectly reduces pressure on 3 items (A-10, D-15, D-16) by lowering fallback frequency, and
is orthogonal to the remaining ~25 items. Its real value is at M2+ quality — by that point
the codex-path reliability class is paying dividends on every subsequent wave, and the
tracker's more structural fixes have already landed in M1. Do not run Bug #20 before Sessions
1–6 of the tracker; do run Bug #20 after Gate A smoke confirms M1 clears.
