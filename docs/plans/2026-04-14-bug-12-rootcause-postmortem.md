# Bug #12 Post-Mortem: What Actually Happened, and Why the Fix Was Insufficient

**Status:** open, corrective investigation
**Severity:** HIGH — ratifies that the "silent hangs waste runs" problem is still not structurally fixed
**Date:** 2026-04-14
**Reference runs:** `v18 test runs/build-d-rerun-20260414/` (Wave T hang), `v18 test runs/build-e-bug12-20260414/` (post-fix smoke — M1 aborted at milestone-level timeout)

---

## 1. Honest summary

The Bug #12 fix shipped in PR #1 (`baab6e9`) was **mostly a fig leaf over the real issue**. Three of its four mechanisms are problematic:

| Fix component | Real behaviour | Net value |
|---|---|---|
| 6 sub-agent `_invoke_sdk_sub_agent_with_watchdog` wraps in `wave_executor.py` | ✅ Correct — does bound sub-agent SDK calls by a 600s idle watchdog | Real fix for yesterday's Wave T SDK-stream hang class |
| Per-wave `wave_total_timeout_seconds = 2700s` hard cap at `wave_executor.py:2218` | ❌ Architecturally redundant with the pre-existing milestone-level `asyncio.wait_for(timeout=_ms_timeout_s*1.5)` at `cli.py:3831`. Under any normal wave ordering (Wave A+B together take >1350s), the milestone timeout fires first and my per-wave timeout is dead code. | Near-zero |
| 8 `cli.py` `client.query(prompt)` wraps with `asyncio.wait_for(timeout=600s)` | ❌ Wraps the **wrong call**. `client.query()` is just the prompt submission (typically sub-second). The actual SDK streaming hang would occur in the subsequent `_process_response(client, ...)` loop, which is **not wrapped**. | Near-zero |
| `config.v18.sub_agent_idle_timeout_seconds` / `config.v18.wave_total_timeout_seconds` config fields | ✅ Fine by themselves | Neutral |

The today's build-e run "looked like" a validation of Bug #12 only because the pipeline exited cleanly after a timeout. It did, but **the timeout that fired was the pre-existing milestone-level wait_for, not anything introduced by PR #1**. The run proved that the pre-existing code does its job — not that the new code does.

---

## 2. What actually killed Wave D in build-e

### Timeline (all local times are UTC+4)

| Time (local) | Event |
|---|---|
| 12:32:12 | `python -m agent_team_v15` launched |
| 12:41:33 | Wave A starts (phases 0/1/1.5 done) |
| 12:44:01 | Wave A ends (147.6s, $0.52, claude) |
| 12:44:02 | Wave B starts |
| 13:17:17 | Wave B ends (1994.8s = 33.2 min, $6.63, codex) |
| 13:17:19 | Wave C starts (deterministic) |
| 13:17:25 | Wave C ends (5.8s) |
| 13:17:26 | Wave D starts |
| 13:30:15 | First Wave D frontend files written (13 min of silent codex reasoning first) |
| 13:31–13:47 | Bulk frontend work — ~30 files created |
| 13:49:03 | **Milestone-level wait_for cancels Wave D** at 4050s (= `_ms_timeout_s * 1.5`, where `_ms_timeout_s = 2700`). Log line: `Warning: Milestone milestone-1 timed out after 2700s. Marking as FAILED and continuing to next milestone.` |
| ~13:50–14:08 | Audit cycle 1 runs on the partial M1 output. 30 findings (3 CRITICAL, 9 HIGH, 13 MEDIUM, 5 LOW), score 656/1000 (YELLOW), 21/30 AC pass. |
| ~14:08 | Audit-fix cycle 1 writes two patch files (`badges.tsx`, `tasks/[taskId]/page.tsx`) — these are what I earlier mistook for late Wave D writes |
| ~14:19 | Pipeline exits cleanly, exit code 0 |

### What Wave D was doing for 31.5 minutes before cancellation

- First 13 min (13:17–13:30): no files written; codex was in reasoning (config sets `codex_reasoning_effort: "high"`, so single SDK turns can take 5–10+ minutes of reasoning before any tool call).
- 13:30–13:49: ~30 frontend files written over 19 minutes. This is legitimate Wave D output and matches the files the auditor later found. Normal-looking work.
- 13:49: cancellation.

Wave D was **not** in a retry loop. It was doing real work, but slowly. The bulk of the time loss is the reasoning-heavy codex profile, not a code logic bug.

### Why none of PR #1's safety nets fired

| Mechanism | Intended trigger | What actually happened |
|---|---|---|
| Sub-agent 600s idle watchdog (6 wrapped sites) | When any sub-agent SDK call goes 600s without a message | None of the 6 sub-agents were reached — Wave D's main SDK call hadn't yet returned, so neither compile-fix nor DTO nor frontend-hallucination guard had a chance to run. The sub-agents only fire *after* the main wave SDK call completes and a compile/scan guard finds something to fix. |
| Generic wave 1800s idle watchdog (pre-existing, `_invoke_wave_sdk_with_watchdog`) | Main wave SDK goes 1800s without a message | The main wave SDK was emitting tool calls regularly (files written continuously from 13:30 to 13:49). No 30-minute idle gap — watchdog never fired. |
| Per-wave `wave_total_timeout_seconds = 2700s` (new, via `_with_wave_budget`) | Wave runs 2700s wall-clock | Wave D only ran 1893s (31.5 min) before milestone-level cancellation. My per-wave timeout would have fired at 2700s (45 min), which is after the milestone-level one at 4050s cumulative — i.e., **the 2700s-per-wave safety net is unreachable in practice** because: milestone_timeout * 1.5 (4050s) − Wave A+B total (2148s) = 1902s remaining for Wave D, which is less than 2700s. |
| Milestone-level `asyncio.wait_for(timeout=_ms_timeout_s * 1.5)` (pre-existing, `cli.py:3831`) | Total milestone runtime exceeds 4050s | Fired at 4050s cumulative. **This is the cancellation that actually ran.** |
| 8 `cli.py` `client.query` wraps (new) | SDK prompt submission takes >600s | Bounded the wrong call — `client.query(prompt)` submits and returns quickly; the streaming is in the subsequent `_process_response`. None of these wraps would fire for a streaming hang anyway. |

**Net:** The only mechanism that saved this run from running indefinitely is **the milestone-level wait_for that was already in the code before PR #1**. PR #1 did not contribute to this outcome.

---

## 3. Where the PR #1 fix is actually correct and useful

The 6 sub-agent `_invoke_sdk_sub_agent_with_watchdog` wraps in `wave_executor.py` **are legitimate** and do add a real guarantee: if any of those specific sub-agents has a 600s idle stream, it raises `WaveWatchdogTimeoutError` and the wave writes a hang report.

For yesterday's Wave T hang, this is exactly the right shape: Wave T's initial SDK call had no idle bound, streamed nothing for >50 minutes, and the old code waited forever. With PR #1, the Wave T initial SDK call now has a 600s idle bound.

Caveats on these wraps:

- The 600s bound protects against **stream-silent** hangs only. A sub-agent that emits one empty tool-call every 500s would never trigger the watchdog — fine for Claude SDK behavior, but fragile in principle.
- The hang-report writing path (`_write_hang_report`) was added but I have not confirmed it writes to a directory the downstream code reads. Worth a targeted test.

---

## 4. What PR #1 did NOT fix

### 4a. The `wave_total_timeout_seconds` is dead code

Given the milestone-level wait_for at `cli.py:3831` uses `timeout=_ms_timeout_s * 1.5`, any Wave K (after Waves < K consumed cumulative time X) gets at most `_ms_timeout_s * 1.5 − X` wall-clock before the milestone-level wait_for cancels it. For the per-wave deadline to fire first, we'd need `2700 < _ms_timeout_s * 1.5 − X`, i.e. `X < 1350` at Wave K start.

With Wave A (~150s) and Wave B (~2000s), cumulative X before Wave D is ≈2150s — always above the 1350s threshold. The per-wave timeout can *only* fire in these corner cases:

- Wave A hangs longer than 2700s (extremely unusual, Wave A is small).
- A rare config where Wave B is near-empty and Wave D still goes long.

In the common case, **the per-wave timeout is a guard that never fires before a larger guard above it.** Adding it made the control flow harder to reason about without providing the protection we wanted.

### 4b. The `cli.py` `client.query` wraps bound the wrong thing

ClaudeSDKClient streaming behavior: `client.query(prompt)` submits the request and returns. The async iteration over messages happens inside `_process_response(...)`. Wrapping only `client.query` with `asyncio.wait_for(timeout=600)` protects against submission hanging, which is not the observed failure mode. The real hang class is a silent response stream — that's `_process_response`, and that's where the bound belongs.

The wrap is not harmful (timeout almost never fires on a submit), but it is not providing the protection PR #1 claimed.

### 4c. The confusing timeout log message

`cli.py:3868` prints:

```python
f"Milestone {milestone.id} timed out after {_ms_timeout_s}s. "
```

…but the actual `asyncio.wait_for` timeout is `_ms_timeout_s * 1.5`. So the log says "2700s" when the wait_for actually ran for 4050s. This has been a silent operator bug for a while, predates PR #1 — but should be fixed as part of the cleanup.

### 4d. The deeper root question: why is Wave D slow?

Today's Wave D ran for 31.5 min and wrote ~30 files before the milestone-level cancellation cut it off. Analysis:

- Config has `codex_reasoning_effort: "high"` and `codex_timeout_seconds: 5400` (90 min). Codex at high reasoning is genuinely slow — 5–15 min per SDK turn is typical.
- Wave D's initial silent phase was 13 min (13:17→13:30). That's a single codex reasoning pass before first tool use. Not a bug — just expensive per-turn.
- Subsequent work (13:30→13:49) was 19 min for 30 files, which is reasonable Claude-or-codex output speed.
- There is **no evidence of a retry loop**. The 30 files written appear to be distinct pages/components, not rewrites of the same files.

Conclusion: Wave D's 31.5-min runtime is *legitimate codex-high-reasoning work*, not a logic bug. The pipeline just budgets Wave D inside a milestone envelope that doesn't account for codex's reasoning-time profile.

---

## 5. The correct fix shape

### 5a. Decide whether the per-wave timeout should exist at all

Option A: **Remove** `wave_total_timeout_seconds` entirely. The milestone-level wait_for already covers the "total time" concern. Per-wave idle is covered by the existing generic wave watchdog + the 6 new sub-agent watchdogs.

Option B: **Make it tighter than the milestone bound** so it actually fires first. E.g., set default to `milestone_timeout_seconds * 0.6 = 1620s`. This only makes sense if we want "fail the wave, move on" as a behavior distinct from "fail the whole milestone" — which I don't think the current pipeline does; the milestone handler just marks FAILED and continues.

I recommend **Option A (remove)**. The per-wave wrapper adds complexity, ships no observed benefit, and confuses operators who assume the wave-level `_with_wave_budget` bounds are primary.

### 5b. Actually bound SDK streaming in `cli.py`

Replace the current pattern:

```python
await asyncio.wait_for(client.query(prompt), timeout=_sub_agent_idle_timeout_seconds(config))
cost = await _process_response(client, config, phase_costs)  # NOT bounded
```

with one of:

- Wrap the *whole* `_process_response` call instead. Simple but only catches total-time, not idle-time.
- Introduce an idle-timeout inside `_process_response` — iterate through `client.receive_response()` (or whatever the streaming primitive is) with a per-message timeout. This is the correct structural fix but touches more code.
- Cleaner: refactor so that all SDK session work goes through the same `_invoke_wave_sdk_with_watchdog` helper as the wave-level call. Today cli.py has several ad-hoc `ClaudeSDKClient(...)` blocks that bypass the watchdog primitives entirely.

I recommend the third: consolidate all SDK session use through the watchdog helper. It also makes the cli.py layer consistent with the wave_executor layer.

### 5c. Fix the timeout log message

`cli.py:3868` should print the actual wait_for timeout, not `_ms_timeout_s`. One-line correction.

### 5d. Instrument Wave D so we can tell "slow but productive" from "silently looping"

Add per-wave periodic progress heartbeats to the log:

- Every 60s: log `[Wave D] active — last tool use 12s ago, N files written so far, cumulative SDK calls: K`.
- Every 5 min: emit a delta summary.

This turns "is the 30-min wait reasonable or pathological?" from a forensic question into a direct observation, and lets us decide whether to bump the milestone budget for reasoning-heavy codex profiles or tighten the prompt scope.

### 5e. Reconsider the budget envelope when `codex_reasoning_effort=high`

If codex-high is the intended config for Wave D, the milestone timeout (2700s × 1.5 = 4050s) is too tight to let Wave D write anything substantial *and* reach Wave D5/T/E inside a single milestone run. Two concrete options:

1. Raise `milestone_timeout_seconds` to 3600s (6300s effective) when codex_reasoning_effort=high.
2. Scope Wave D smaller — don't include all pages/components/hooks/auth/i18n/api-contracts in one Wave D brief; split into D1 (auth+layout) and D2 (features).

Either is a scope/budget decision, not a code-level watchdog question. But this is the *actual* blocker to finishing M1 now, not Bug #12.

---

## 6. Disposition of PR #1

- **Do not merge PR #1 as-is.** It contains one genuinely-valuable change (the 6 sub-agent wraps in `wave_executor.py`), one dead-code change (the per-wave timeout), and ~8 ineffective wraps in `cli.py`.
- Recommended action: **narrow the PR** to just the 6 sub-agent wraps + their tests. Drop the per-wave timeout and drop the cli.py `client.query` wraps. File the cli.py streaming-bound work as its own plan (5b above), and file the milestone-budget tuning work as another plan (5e above).
- If you'd rather not re-work the PR, merge it and file the corrections — but the plan file for each correction must exist before merge so we don't forget.

---

## 7. What I should have done in my original investigation

In the Wave T hang analysis on 2026-04-14 morning, I:

- Found 6 unprotected `_invoke(execute_sdk_call, ...)` sites and correctly proposed wrapping them.
- Then added an "outer safety net" timeout **without first checking what timeouts already existed in the caller** — `cli.py:3831`'s `asyncio.wait_for(timeout=_ms_timeout_s * 1.5)` was already there and does essentially the same job. Reading the caller is basic due diligence I skipped.
- Added cli.py `client.query` wraps **without checking whether `client.query` is the actual blocking call.** A 60-second glance at `_process_response(...)` would have shown the streaming loop is elsewhere.
- Framed the sub-agent fix as "wrap, add belt-and-suspenders." The belt-and-suspenders turned out to be duplicated and the belt we added was on a cloth that wasn't the problem.

The correct first step, which I did not take, was:

> Before writing any new timeout, read every existing timeout/watchdog mechanism the request path crosses. Then add only what isn't already there, and add it at the layer where the blocking call actually sits.

I'm writing that commitment here so the next root-cause task reaches it before the fix task.

---

## 8. Follow-ups to file

1. **Bug #13:** `wave_total_timeout_seconds` is dead code — remove or retune (Section 5a).
2. **Bug #14:** `cli.py` streaming is not bounded — wraps target the wrong call (Section 5b).
3. **Bug #15:** milestone timeout log message prints wrong value (Section 5c).
4. **Bug #16:** add per-wave progress heartbeats (Section 5d).
5. **Bug #17:** codex-high milestone budget is too tight — bump or split scope (Section 5e).
6. **Separate plan** (Bug #11 class): `apps/web/src/i18n/navigation.ts` exported nothing, but pages imported `Link`, `usePathname`, `redirect`, `useRouter` from it. That's a Wave D scope-completion bug distinct from anything here — needs a post-Wave-D import-resolvability scanner.
---

## 9. Corrections (post-PR #2 stock rerun)

The analysis above is still incomplete in three important ways.

### 9a. The provider-routed Codex bypass was real

The first correction stands: the original investigation over-focused on the claude-only branch of
`_execute_wave_sdk`, the dead per-wave timeout, and the wrong-call `cli.py` wraps. The primary bug in
PR #2's target area was that provider-routed Codex waves could bypass the wave watchdog entirely.
That part of the diagnosis was correct and PR #2 fixed it by moving the watchdog wrapper above the
provider-routing split and threading `progress_callback` through `provider_router.py` into
`codex_transport.py`.

### 9b. The stock failure after that fix was not the heartbeat feeding the clock

The next hypothesis was that the new 60s heartbeat observer was accidentally resetting
`state.last_progress_monotonic`. The stock rerun and the code both refuted that:

- `_log_wave_heartbeats(...)` only logs `state.last_progress_at`, `state.last_message_type`, and
  touched-file counts. It does not call `record_progress(...)`.
- `codex_transport._drain_stream(...)` ignores empty and whitespace-only lines, and stderr is drained
  without a progress callback.
- In the failed stock run, the heartbeat summaries kept printing the same `last progress=` timestamp.
  If the heartbeat had been feeding the watchdog, that timestamp would have advanced.

So the observer heartbeat was noisy in the logs, but it was not the reason the idle clock stayed
"alive."

### 9c. The actual third layer was transport teardown after timeout

The real remaining bug was downstream of the timeout decision: once the watchdog decided a
provider-routed Codex wave had gone idle, the cancellation path inside `codex_transport.py` could
still wedge before control returned to `wave_executor.py`.

Specifically:

- `_communicate_with_progress(...)` waited on `asyncio.gather(stdout_task, stderr_task)` in `finally`
  without first canceling those drain tasks.
- `_execute_once(...)` used unbounded `proc.kill(); await proc.wait()` cleanup.
- If the Codex subprocess pipes never reached EOF, cancellation could hang in transport teardown even
  though the watchdog had already decided to fire.

That was the unlock. The fix that made the stock rerun behave correctly was:

- cancel the stdout/stderr drain tasks before awaiting them during teardown,
- bound subprocess termination with a short wait,
- and on Windows, fall back to `taskkill /F /T` if the local `proc.kill()` path does not complete.

After that change, the same stock scenario produced the missing artifacts:

- `milestone-1-wave-B.json` with `wave_timed_out: true`,
- non-empty `last_sdk_message_type` / `last_sdk_tool_name`,
- and a Wave B hang report written within the expected idle window.

### 9d. Refuting Sections 4a and 4b

Sections 4a and 4b are still directionally correct about the older PR #1 mistakes:

- the dead per-wave timeout should not have landed,
- and the old `asyncio.wait_for(client.query(...))` wraps targeted the wrong call.

But those were not the final blocker to closing the silent-hang class. The stock rerun proved the
last missing piece was bounded cancellation/teardown in the provider-routed Codex transport path.
