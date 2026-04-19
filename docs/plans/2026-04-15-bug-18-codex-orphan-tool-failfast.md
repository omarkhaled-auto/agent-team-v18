# Bug #18 — Codex orphan-tool fail-fast + codex-first retry

**Status:** SUPERSEDED on 2026-04-15 by
[`2026-04-15-bug-20-codex-appserver-migration.md`](./2026-04-15-bug-20-codex-appserver-migration.md).

> **Do not implement this plan.** After context7 research surfaced that codex's
> `app-server` mode exposes `turn/interrupt`, streaming item lifecycle events, and richer
> liveness primitives, the right structural fix is a transport migration, not a shim on
> top of `codex exec`. Bug #18's orphan-detection idea survives — it's reimplemented
> inside the new transport using RPC primitives (see Bug #20 §4b). The action layer
> (session-restart-on-orphan) is replaced by `turn/interrupt` + corrective retry that
> preserves session context.
>
> Kept here for historical context and to preserve the detection-logic sketch that fed
> into Bug #20 §4b.

**Original status:** draft (do not implement until after closeout integration smoke lands)
**Severity:** HIGH — root-cause for the majority of codex-path Wave B losses
**Date:** 2026-04-15
**Depends on:** PR #6 (merged) for the `pending_tool_starts` diagnostic; PR #9 (merged) for the
Docker-transient retry pattern; post-closeout master.
**Reference runs:** `v18 test runs/build-h-full-closeout-20260415/`,
`v18 test runs/build-i-full-closeout-retry-<date>/` (the run this bug was filed off of).
**Upstream research:** Context7-sourced codex RPC protocol docs — see §8 below.

---

## 1. Problem statement

The user's intended backend default is `provider_map_b: "codex"`. In practice, the codex path
loses Wave B in a reproducible shape: codex produces 30–80 files, then a single
`command_execution` tool call goes silent (no `item.completed` ever arrives). After 1800s of
idle, the wave watchdog fires and the wave falls back to Claude — which starts Wave B over
from zero.

The `build-i` smoke (2026-04-15) pinned this precisely. The hang report wrote:

```json
{
  "last_sdk_message_type": "item.completed",
  "last_sdk_tool_name": "command_execution",
  "observed_idle_seconds": 1814,
  "pending_tool_starts": [ ... one entry ... ]
}
```

That is PR #6's orphan-tool diagnostic showing exactly one open `command_execution` that
never emitted `item.completed`. The codex parent is blocked waiting for that tool to close.
The tool never closes because the grandchild subprocess (npm / tsc / prisma / a shell
script) didn't flush stdout in a way codex's session layer can observe. Codex can't see
the grandchild. We can.

**Consequences today:**

1. ~1800s burned before the watchdog even notices.
2. Wave B is thrown away entirely; Claude restarts from scratch (+10–20 min + duplicated
   token spend).
3. The backend ends up written by Claude, not codex, even though the user explicitly asked
   for codex.

## 2. Why the other options don't fit

Three options were considered:

1. **Per-tool orphan timeout + session-level recovery (this plan).** Structural fix at the
   layer where the blocking call sits — the codex transport. Detect the orphan fast, kill
   the session, restart codex with a fresh session. Only fall back to Claude after codex
   retries are exhausted.
2. **Codex-first retry on watchdog fire, no orphan detection.** Keeps the 1800s wait per
   attempt. The wedge is often deterministic for a given package.json/tsc setup, so blind
   retries hang at the same command. Doesn't address the root cause.
3. **PTY / line-buffered stdio patch in codex's command_execution path.** Correct in
   principle, but codex-transport runs the codex CLI as a subprocess — the grandchildren
   are spawned by codex's own shell-tool code, which is upstream and not ours to patch.

Option 1 is the only one that fits the "structural fix, at the layer where the blocking
call sits" principle from `feedback_structural_vs_containment.md`.

## 3. Proposed design

### 3a. Detection layer — in `wave_executor._WaveWatchdogState.record_progress`

PR #6 already tracks `pending_tool_starts: dict[tool_id, {tool_name, started_at,
started_monotonic}]`. Add a new method:

```python
def orphaned_tool(self, threshold_seconds: int) -> dict | None:
    """Return the oldest pending tool whose age > threshold, else None."""
    now = time.monotonic()
    oldest: tuple[str, dict] | None = None
    for tid, info in self.pending_tool_starts.items():
        age = now - info["started_monotonic"]
        if age > threshold_seconds:
            if oldest is None or info["started_monotonic"] < oldest[1]["started_monotonic"]:
                oldest = (tid, info)
    return {"tool_id": oldest[0], **oldest[1], "age_seconds": int(now - oldest[1]["started_monotonic"])} if oldest else None
```

Call `orphaned_tool(...)` from the existing watchdog heartbeat observer (already running at
60s cadence per PR #2's heartbeat work). When it returns non-None, raise a new exception
class `CodexOrphanToolError` (subclass of `WaveWatchdogTimeoutError` so existing handlers
keep working).

### 3b. Threshold — `codex_orphan_tool_timeout_seconds`

Default: **300s** (5 min). Justification:

- Legitimate slow commands this needs to allow: `npm install` on a fresh lockfile
  (commonly 60–180s for a Next.js + Prisma stack), `prisma generate` (~5–15s),
  `tsc --build` (30–90s on medium repos).
- The build-i orphan sat open for ~1800s — an order of magnitude above the legitimate
  upper bound.
- 300s leaves a 2× safety margin over realistic `npm install` worst-cases while cutting
  ~25 min (1500s) off today's wedge-to-fallback latency.

Config: `config.v18.codex_orphan_tool_timeout_seconds` with default 300. Set to 0 to
disable (debug only; not a production knob).

### 3c. Recovery layer — codex-first retry in `provider_router`

Current `execute_wave_with_provider` fails codex once → Claude fallback. Replace with:

```python
codex_attempts = config.v18.codex_max_attempts  # new, default 2
for attempt in range(1, codex_attempts + 1):
    try:
        result = await _execute_codex(...)
        if result["success"]:
            return result
    except CodexOrphanToolError as exc:
        logger.warning(
            "[Wave %s] codex orphan tool %s (%s) stalled %ds; restarting codex session (attempt %d/%d)",
            wave_letter, exc.tool_id, exc.tool_name, exc.age_seconds, attempt, codex_attempts,
        )
        if attempt >= codex_attempts:
            break
        # fresh codex session; kill prior subprocess was already done by transport teardown
        continue
    except WaveWatchdogTimeoutError:
        break  # non-orphan timeout — still fall back to Claude immediately
# only now fall back to Claude
return await _claude_fallback(...)
```

**On session kill:** the codex subprocess teardown from PR #2 already handles bounded
cancellation + Windows `taskkill /F /T`. No new kill logic needed.

**On retry:** a fresh codex session gets a fresh prompt — but the files already written to
disk by the prior attempt remain. Codex's second attempt sees the partial output and
usually moves forward from where it stopped. This matches the build-g run (post PR #2 fix)
where a restarted codex session successfully completed Wave B after the first hung.

### 3d. Telemetry

Add to `WaveResult`:

- `codex_attempts_used: int` — 1 if first attempt succeeded, N if needed retries.
- `orphan_tool_events: list[{tool_id, tool_name, age_seconds, attempt}]` — one per
  orphan detection event.

Existing `fallback_used` stays — it's set to `True` only if *all* codex attempts failed
and Claude was invoked.

### 3e. Non-goals

- **Don't try to cancel an individual grandchild.** We can't see codex's `command_execution`
  subprocess tree reliably across OSes, and even if we could, codex's session state after a
  partial tool kill is undefined. Whole-session restart is the right granularity.
- **Don't patch codex CLI itself.** Not our code. If upstream ever adds a per-tool timeout
  or PTY support, we can remove this shim — until then, this is the right layer.
- **Don't auto-bump `codex_attempts` above 2 by default.** One retry is enough to handle
  transient wedges; beyond that, the wedge is probably deterministic and we should fall
  back to Claude rather than spin.
- **Don't change `wave_watchdog_idle_timeout_seconds` (1800s).** It's still the
  belt-and-suspenders for a codex session that wedges *without* opening a tool (rare, but
  possible — e.g., codex reasoning loop without tool use). Orphan detection is the tight
  loop; the 1800s watchdog is the safety net.

## 4. Testing plan (TDD)

File: `tests/test_codex_orphan_failfast.py`

1. **`orphaned_tool` returns None when no tools pending.** Baseline.
2. **`orphaned_tool` returns None when all pending are younger than threshold.** State has
   a tool started 100s ago; threshold 300s; returns None.
3. **`orphaned_tool` returns the oldest when one is past threshold.** Two pending tools
   (100s and 500s); threshold 300s; returns the 500s one with `age_seconds >= 500`.
4. **`orphaned_tool` ignores tools completed by item.completed.** Record start then
   complete; threshold below age; returns None.
5. **Watchdog observer raises `CodexOrphanToolError` when orphan crosses threshold.**
   Drive `record_progress` with an `item.started`; advance monotonic clock (mock);
   assert `CodexOrphanToolError` raised with correct `tool_id` / `tool_name`.
6. **`execute_wave_with_provider` retries codex on `CodexOrphanToolError`.** Mock codex
   executor to raise `CodexOrphanToolError` once then succeed; assert final
   `result["fallback_used"] is False`, `codex_attempts_used == 2`, no Claude call.
7. **`execute_wave_with_provider` falls back to Claude only after attempts exhausted.**
   Codex raises `CodexOrphanToolError` on both attempts; assert Claude fallback invoked,
   `fallback_used: True`, `codex_attempts_used == 2`.
8. **Non-orphan `WaveWatchdogTimeoutError` still triggers immediate Claude fallback.**
   (Preserves today's behavior for reasoning-loop hangs that don't open tools.)
9. **Config: `codex_orphan_tool_timeout_seconds=0` disables detection.** Orphan past
   threshold never raises; watchdog still fires at 1800s.

## 5. Calibration plan

After merge, run one stock smoke with the default 300s threshold and verify:

- Legitimate slow commands (`npm install` on cold cache) complete within 300s — check
  build log for any `[Wave B] codex orphan tool ...` lines against command names that
  shouldn't be orphans.
- If `npm install` ever hits 300s legitimately, bump threshold to 450s and re-smoke.
- If no orphans fire in a clean run, the threshold is fine — ship it.

## 6. Disposition and sequencing

- **Do not merge until after the 2026-04-15 closeout lands on master.** Bug #18 is the
  correct structural next step *after* PRs #3–#9 are in.
- Branch from `master` post-merge: `bug-18-codex-orphan-failfast`.
- Single PR; ~150 LOC of code + ~250 LOC of tests.
- Expected cost to validate: one stock smoke (~$5–15, ~2h wall clock).

## 7. Memory-of-prior-mistakes hooks

- `feedback_structural_vs_containment.md`: this is the structural fix corresponding to
  PR #6's diagnostic. PR #6 was deliberately scoped to observation-only; Bug #18 is the
  action layer the diagnostic was built to enable.
- `feedback_verification_before_completion.md`: don't claim "codex is reliable now" after
  unit tests pass. Claim it after a stock smoke has Wave B clear on codex (not
  fallback) — `wave_result.fallback_used: False` + `codex_attempts_used ∈ {1, 2}`.
- `project_v18_hardened_builder_state.md`'s line 27–28 explicitly flags this as the
  deliberate follow-up ("threshold TBD from one clean production run with PR #6's
  diagnostics in place"). This run is that evidence.

---

## 8. Upstream research (context7 `/openai/codex` docs)

Before writing this plan the codex-cli documentation was queried to verify we weren't
re-inventing something upstream already provides. Findings materially shape the
recommended fix and the long-term roadmap.

### 8a. What codex already supports natively

The codex-rs **app-server** mode exposes a JSON-RPC protocol with exactly the knobs we
need for this bug:

| RPC method                 | What it gives us                                                                          |
|---------------------------|-------------------------------------------------------------------------------------------|
| `command/exec`            | Accepts `timeoutMs` (per-command wall-clock timeout) and `disableTimeout` (opt-out).      |
| `command/exec/terminate`  | Terminate a single running command by `processId` **without killing the session**.        |
| `turn/interrupt`          | Graceful turn-level cancel; server emits `turn/completed` with `status: "interrupted"`.   |
| `command/exec/outputDelta`| Incremental stdout/stderr deltas — we could treat as "still alive" even before complete.  |
| `tty: true` on exec       | PTY mode; forces line-buffering on grandchildren (fixes the root root cause of wedges).   |

If we were driving codex in app-server mode, this whole bug is a config change: pass
`timeoutMs: 300000` on every `command/exec` and codex itself will kill the stalled
grandchild and emit `item.completed` with a failure status. No wedge, no watchdog
needed at our layer for this class.

### 8b. Why our current transport can't use those knobs

`src/agent_team_v15/codex_transport.py` drives codex in **`codex exec`** mode
(non-interactive CLI with stdin prompt, stdout JSONL). We do not speak the JSON-RPC
protocol. The CLI mode's documented config.toml knobs (`model`, `sandbox`,
`approval_policy`, `model_reasoning_effort`) do not include a shell-tool timeout.

So at the `codex exec` boundary, we have only three levers:

1. Kill the codex subprocess from outside (what PR #2 already does at the wave-level
   1800s watchdog).
2. Generate a config.toml for codex's temp `CODEX_HOME` with every supported knob set
   (we already do this; no shell-timeout option exists to set).
3. Parse the JSONL event stream to detect orphan tools (PR #6 enabled this).

### 8c. How this reshapes the plan

- **Bug #18 (this plan) stays the right near-term fix.** Orphan detection at our layer
  + codex-first retry + Claude fallback. Tractable scope (~150 LOC + tests), no
  architectural rework.
- **Bug #20 (new) — migrate codex transport to app-server mode.** Structurally better:
  lets codex itself terminate stalled grandchildren via `command/exec` `timeoutMs`
  without killing the session, and lets us cancel individual tools with
  `command/exec/terminate` if we still need belt-and-suspenders. Drops Bug #18's
  session-restart-on-orphan behavior in favor of targeted tool kill. Estimated
  200–400 LOC of new transport + full re-validation smoke. File as the follow-up
  to Bug #18, not a replacement.
- **Bug #21 (new, smaller) — enable `tty: true` for shell tools.** If Bug #20 lands,
  pass `tty: true` on `command/exec` so npm/tsc/prisma flush stdout normally. Removes
  a significant fraction of wedges at their real root cause. Only reachable through
  app-server mode.

### 8d. Decision: ship Bug #18 first

Reason: Bug #18 is within reach of the current transport, delivers most of the
reliability improvement (cuts wedge-to-recovery from ~30 min to ~5 min + retains
codex as the Wave B provider in the common case), and doesn't require a transport
rewrite. Bug #20 is the architecturally correct long-term answer; file it
immediately but sequence behind Bug #18 so we're not gating this bug on a larger
rearchitecture.

### 8e. References

- `/openai/codex` — `codex-rs/app-server/README.md` (RPC protocol, timeoutMs,
  command/exec/terminate, turn/interrupt).
- `/openai/codex` — `codex-rs/README.md` (config.toml settings available to `codex
  exec` mode — confirms no per-tool-timeout knob at CLI level).
- Queried via MCP `context7` on 2026-04-15 while drafting this plan.
