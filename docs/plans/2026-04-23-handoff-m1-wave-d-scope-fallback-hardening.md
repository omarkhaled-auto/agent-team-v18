# HANDOFF - Milestone 1 whole-pipeline failure and performance audit continuation

**Original handoff date:** 2026-04-23
**Expanded on:** 2026-04-24
**Repo:** `C:/Projects/agent-team-v18-codex`
**Branch at handoff:** `master`
**HEAD at handoff:** `8a7f0e86a47bb63a32c8eafda1a1482cde1164ec fix(codex-appserver): add orphan-watchdog diagnostic logging (#74)`
**Platform:** Windows PowerShell, Codex CLI `0.123.0`, app-server transport available

---

## BIG WARNING TO THE NEXT AGENT - READ THIS FIRST

**NUMBER ONE RULE: CONTEXT7 IS THE TRUTH.**

If a framework, provider, protocol, or transport rule matters to the fix, resolve the official library in Context7 first, query the exact behavior, and only then act. If Context7 is unavailable, quota-limited, or does not answer the exact question, write `BLOCKED` and do not invent the rule.

**Important distinction for the next session:** the next agent itself must use Context7 as its source of truth for framework/provider/protocol claims. But the old smoke run's **internal pipeline** Context7 quota exhaustion reflects the current account quota state and is **not** the product issue to investigate right now. Do not spend time diagnosing account quota, MCP availability, or quota-remediation workflow in this repo session.

**This repo is still not smoke-ready. Do not call the old Milestone 1 run a pass. Do not start a fresh smoke until you have independently re-read the cited code and artifacts below and completed the broader whole-pipeline audit, not just the known Wave D scope/fallback defects.**

Concrete warnings:

1. **Known operator-context note: internal pipeline Context7 quota was exhausted in the old smoke.**
   - `C:/smoke/clean-r1b1-postwedge-13/run.log:155-170` shows all six technology lookups failed with monthly quota exceeded, `TECH_RESEARCH.md` was written as `BLOCKED`, and the pipeline still proceeded to `Phase 2: Executing 5 milestones`.
   - `src/agent_team_v15/cli.py:3406-3460` handles `source_unavailable` as a warning, not a hard stop.
   - `src/agent_team_v15/cli.py:2439-2443`, `src/agent_team_v15/cli.py:4598-4605`, and `src/agent_team_v15/cli.py:5265-5271` inject `"Use your best judgment"` notes when Context7 prefetch is empty.
   - Treat this as forensic context only. Do **not** spend the next session trying to solve the quota state itself unless a later proven repo defect depends on it.

2. **The old Milestone 1 run is contaminated, not promotable.**
   - Wave D edited backend/root files in `C:/smoke/clean-r1b1-postwedge-13/.agent-team/artifacts/milestone-1-wave-D.json:8-23`.
   - The observer detected the drift but only logged it in `C:/smoke/clean-r1b1-postwedge-13/run.log:387-397`.

3. **Wave D prompt contamination was real, and it was prompt-level before it was enforcement-level.**
   - The contaminated Wave D prompt explicitly handed backend/root files to the frontend wave in `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-prompt.txt:168-177` and `...wave-D-prompt.txt:208-224`.
   - Do not reduce this to "observer should have blocked it." The prompt itself was poisoned.

4. **The observer is still `log_only` by design unless config changes.**
   - `src/agent_team_v15/config.py:648-659` documents `log_only=True` as the default and says it never interrupts or steers.
   - `src/agent_team_v15/codex_appserver.py:1439-1441` shows the live behavior: steer only when `log_only` is false, otherwise log `Observer (log_only) would steer Codex`.
   - `C:/smoke/clean-r1b1-postwedge-13/run.log:387-397` and the longer repeated span in the same file show the observer firing many times without blocking the turn.

5. **OpenAPI degraded to regex extraction in the old smoke.**
   - `C:/smoke/clean-r1b1-postwedge-13/run.log:312-325` shows OpenAPI script generation was unavailable and the pipeline fell back to regex extraction.
   - `src/agent_team_v15/openapi_generator.py:63-71` makes this fallback explicit.
   - `src/agent_team_v15/openapi_generator.py:142-146`, `src/agent_team_v15/openapi_generator.py:236-246`, and `src/agent_team_v15/openapi_generator.py:283-289` are the key launcher/fallback surfaces.
   - The Windows `WinError 193` launcher fix already landed in repo, but the next session still needs to verify live behavior does not silently degrade to regex extraction in a clean run.

6. **`spawn EPERM` is still a real forensic signal, but it is not the only proven defect from that workspace.**
   - The captured Wave D turn shows `spawn EPERM` on `pnpm --filter web build` in `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-protocol.log:419-422`.
   - The same turn also shows `pnpm --filter api test` succeeding in `...wave-D-protocol.log:418-423`, which matters when separating frontend-specific failure from general process-launch failure.
   - The same contaminated workspace also contains a deterministic CSS comment terminator defect at `C:/smoke/clean-r1b1-postwedge-13/apps/web/src/styles/globals.css:5-6`.
   - The repo scaffold template for that comment has now been fixed, but do **not** claim Windows `spawn EPERM` is root-caused unless you reproduce and prove it again.

7. **Silent fallback policy is still wrong for the user's stated contract.**
   - Main provider routing still falls back from Codex to Claude in `src/agent_team_v15/provider_router.py:247-260`, `src/agent_team_v15/provider_router.py:389-394`, `src/agent_team_v15/provider_router.py:468-490`, and `src/agent_team_v15/provider_router.py:589-599`.
   - Compile-fix and repair paths still fall back to Claude or SDK-style sub-agents in `src/agent_team_v15/wave_executor.py:4747-4761`, `src/agent_team_v15/wave_executor.py:4844-4854`, and `src/agent_team_v15/wave_executor.py:4977-4982`.
   - Until this is resolved, you cannot honestly say "Codex in all waves must be app-server, Claude in all waves must be Agent Teams, no silent fallback paths" has been met.

8. **The logs already show pipeline throughput / prompt-bloat risk.**
   - `C:/smoke/clean-r1b1-postwedge-13/run.log:303-304` shows an app-server turn that consumed `tokens_in=2965619`, `tokens_out=37887`, cost `$1.8953`, and took `839.6s`.
   - `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-protocol.log:1246` shows a Wave D turn duration of `670936ms`.
   - `src/agent_team_v15/codex_appserver.py:1690-1693` is the cost/timing log site.
   - Do not assume the only remaining problem is correctness. The next session must inspect for prompt bloat, repeated observer churn, duplicate work, retry loops, or other poor-performance surfaces that can make a clean run unreliable or unaffordable.

9. **Use Context7 for protocol claims.**
   - Revalidated library ID in the prior continuation: `/openai/codex`.
   - Doc-backed facts already rechecked in Context7: `codex app-server --listen stdio://` is the documented app-server startup command; `thread/start` and `turn/start` are documented JSON-RPC operations; `applyPatchApproval` and `execCommandApproval` are documented server-to-client approval requests.
   - No `0.123.0`-specific protocol delta was proven from Context7 in the prior continuation. Treat version-specific behavior changes as still unproven unless you verify them.

---

## 1. Session narrative - what this continuation actually did

Starting point:
- The repo already had the earlier fixes from `docs/plans/2026-04-23-handoff-clean-build-context7-no-guessing.md`, including:
  - Wave B.1 Docker/probe retry realism
  - Express 5 `req.query` prompt hardening and validator
  - Windows OpenAPI launcher `WinError 193` fix
  - hardcoded `8080` prompt drift removal
- Broad targeted verification from the prior continuation had already passed:
  - `python -m pytest tests/test_agents.py tests/test_openapi_launcher_resolution.py tests/test_v18_phase2_wave_engine.py -q`
  - `406 passed`

What this continuation investigated:
- Re-read both 2026-04-23 handoff docs in order.
- Re-audited the contaminated Milestone 1 Wave D artifacts, including:
  - `run.log`
  - `milestone-1-wave-D.json`
  - `milestone-1-wave-D-prompt.txt`
  - `milestone-1-wave-D-protocol.log`
  - the contaminated `apps/web/src/styles/globals.css`
- Re-audited the live repo wiring for:
  - Wave D prompt construction
  - observer `log_only` behavior
  - milestone scope enforcement
  - compile-fix / repair routing
  - provider fallback behavior
  - OpenAPI regex-fallback surfaces
- Revalidated the Codex app-server baseline in Context7 under `/openai/codex`.

What this continuation changed:
- Sanitized Wave D prompt scaffold/task file lists to frontend-only paths.
- Added a real post-wave scope failure for non-Wave-A waves, covering both `files_created` and `files_modified`, and reusing the observer forbidden-path logic.
- Extended forbidden-path matching to include `.env*` files.
- Fixed the scaffolded RTL CSS comment that emitted an invalid `/* ... */` terminator sequence.
- Threaded `provider_routing` through the Wave D frontend hallucination guard's recompile path.
- Added targeted tests for each of the above.
- Expanded this handoff and the companion kickoff so the next session audits the **entire** pipeline for latent breakage and poor-performance points, not just the already-proven Wave D issues.

---

## 2. Current repo state at handoff

### Relevant source files changed in the prior code continuation

- `src/agent_team_v15/agents.py`
- `src/agent_team_v15/codex_observer_checks.py`
- `src/agent_team_v15/milestone_scope.py`
- `src/agent_team_v15/scaffold_runner.py`
- `src/agent_team_v15/wave_executor.py`
- `tests/test_wave_scope_filter.py`
- `tests/test_scaffold_rtl_baseline.py`
- `tests/test_compile_fix_codex.py`
- `tests/test_codex_observer_checks.py`

### Relevant docs changed in this continuation

- `docs/plans/2026-04-23-handoff-m1-wave-d-scope-fallback-hardening.md`
- `docs/plans/2026-04-23-kickoff-m1-wave-d-scope-fallback-hardening.md`

### Important worktree warning

The repo worktree is very dirty beyond the files above. `git status --short` at handoff showed many unrelated modified and untracked files, including temporary directories and prior-session artifacts. Do not "clean up" or normalize the tree blindly. Work only from the exact files you intend to touch.

---

## 3. What is now proven from code and artifacts

### A. Why Wave D was allowed to edit backend files

This is now proven as a combination of prompt contamination plus weak enforcement:

1. Prompt contamination:
   - The contaminated prompt told Wave D to build backend/root files in `...wave-D-prompt.txt:168-177` and `...wave-D-prompt.txt:208-224`.

2. Observer was log-only:
   - `src/agent_team_v15/config.py:648-659`
   - `src/agent_team_v15/codex_appserver.py:1439-1441`
   - `C:/smoke/clean-r1b1-postwedge-13/run.log:387-397`

3. Post-wave validation was too weak before the prior code continuation:
   - it only considered `files_created`
   - it did not hard-fail the wave
   - it did not use the observer forbidden-path patterns for modified files or root files like `.env.example`

4. Artifact proof of the bleed:
   - `C:/smoke/clean-r1b1-postwedge-13/.agent-team/artifacts/milestone-1-wave-D.json:8-23`

### B. What is now fixed for the Wave D scope gap

1. Frontend-only prompt filtering:
   - `src/agent_team_v15/agents.py:7328-7348`
   - `src/agent_team_v15/agents.py:8003-8018`
   - `src/agent_team_v15/agents.py:9682-9782`

2. Hard post-wave scope failure:
   - `src/agent_team_v15/wave_executor.py:179-225`
   - wired from `src/agent_team_v15/wave_executor.py:6406-6411`

3. `.env*` is now treated as forbidden for Wave D:
   - `src/agent_team_v15/codex_observer_checks.py:30`
   - `src/agent_team_v15/codex_observer_checks.py:68`

### C. Known operator-context only: the pipeline can continue after blocked internal Context7 research

This is now proven from both artifact and code:

1. Artifact evidence:
   - `C:/smoke/clean-r1b1-postwedge-13/run.log:155-170`
   - All six technology lookups failed with monthly quota exceeded, the research phase marked the work `BLOCKED`, and the run still advanced into milestone execution.

2. Code evidence:
   - `src/agent_team_v15/cli.py:3406-3460`
   - `source_unavailable` is surfaced as warning text and coverage reporting, not a hard execution stop.

3. Prompt-fallback risk:
   - `src/agent_team_v15/cli.py:2439-2443`
   - `src/agent_team_v15/cli.py:4598-4605`
   - `src/agent_team_v15/cli.py:5265-5271`
   - Those branches explicitly inject "Use your best judgment" notes when Context7 prefetch is empty.

This does **not** prove that the pipeline always violates the user's current contract. It proves the code and one contaminated run contain these surfaces. For the next session, treat this as known background context, not the main issue to chase.

### D. What is proven about the OpenAPI degradation path

1. Artifact evidence:
   - `C:/smoke/clean-r1b1-postwedge-13/run.log:312-325`
   - The old run degraded from script-based generation to regex extraction.

2. Code evidence:
   - `src/agent_team_v15/openapi_generator.py:63-71`
   - `src/agent_team_v15/openapi_generator.py:142-146`
   - `src/agent_team_v15/openapi_generator.py:236-246`
   - `src/agent_team_v15/openapi_generator.py:283-289`

3. Important nuance:
   - The repo already contains the Windows launcher fix that was intended to remove the earlier `WinError 193` degradation path.
   - The next session still must verify live behavior, because a clean run cannot rely on low-fidelity regex extraction if real OpenAPI generation is expected to be available.

### E. What is proven about the CSS defect

1. The contaminated workspace contains the malformed comment:
   - `C:/smoke/clean-r1b1-postwedge-13/apps/web/src/styles/globals.css:5-6`

2. The scaffold template emitted the bad text before the prior code continuation:
   - now fixed at `src/agent_team_v15/scaffold_runner.py:1957`

3. Regression coverage now exists:
   - `tests/test_scaffold_rtl_baseline.py:62`

### F. What is proven about the Wave D guard recompile path

1. The Wave D hallucination guard now accepts and forwards `provider_routing`:
   - `src/agent_team_v15/wave_executor.py:5040-5138`

2. Coverage exists:
   - `tests/test_compile_fix_codex.py:193`

### G. What is proven about top-level app-server / Agent Teams wiring

Code-backed:
- `src/agent_team_v15/cli.py:55-69` force-enables `agent_teams.enabled`, disables `fallback_to_cli`, enables provider routing, and forces `codex_transport_mode = "app-server"`.
- `src/agent_team_v15/cli.py:3778-3782` selects `codex_appserver` when transport mode is `app-server`.
- `src/agent_team_v15/cli.py:5186-5201` uses the Agent Teams backend when team mode is active.

Artifact-backed:
- `C:/smoke/clean-r1b1-postwedge-13/run.log:197-205` shows Codex CLI `0.123.0` app-server initialization and `workspace-write`.
- `C:/smoke/clean-r1b1-postwedge-13/run.log:39-47` from the earlier forensic read showed Agent Teams mode was active in the live run.

### H. What is proven about throughput / performance risk

1. Expensive turn evidence:
   - `C:/smoke/clean-r1b1-postwedge-13/run.log:303-304`
   - App-server turn OK with `tokens_in=2965619`, `tokens_out=37887`, cost `$1.8953`, duration `839.6s`.

2. Long Wave D turn evidence:
   - `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-protocol.log:1246`
   - `durationMs=670936`

3. Observer spam evidence:
   - `C:/smoke/clean-r1b1-postwedge-13/run.log:387-397`
   - the same log then repeats the same `Observer (log_only)` warning across a very large span.

This does **not** prove a single root cause for slow or costly runs. It proves the next session should explicitly audit throughput, not just correctness.

### I. What remains explicitly unproven

- Whether `spawn EPERM` is a persistent environment-specific Windows/esbuild issue after the scaffold CSS defect is removed.
- Whether prompt filtering alone is enough to prevent Wave D drift, since the observer is still `log_only` mid-turn.
- Whether live OpenAPI generation now succeeds end-to-end after the Windows launcher fix, or still silently degrades.
- Whether the large turn cost / duration is primarily prompt size, observer churn, duplicate validation, slow subprocesses, or another source.
- Whether Codex `0.123.0` changes any protocol detail relevant to this repo beyond the already revalidated app-server baseline.

---

## 4. Verification completed in the prior code continuation

Targeted tests run and passed:

```text
python -m pytest tests/test_wave_scope_filter.py tests/test_scaffold_rtl_baseline.py tests/test_compile_fix_codex.py tests/test_codex_observer_checks.py -q
39 passed in 1.31s
```

What those tests prove:
- Wave D prompt no longer includes backend/root scaffold paths for frontend work.
- Post-wave scope validation now fails on out-of-scope modified files.
- The scaffolded RTL CSS comment no longer embeds a premature comment terminator example.
- The Wave D recompile path preserves `provider_routing`.
- `.env*` forbidden-path collection is covered.

These tests do **not** prove whole-pipeline readiness.

---

## 5. The main blockers that still make a fresh smoke unjustified

There are now **two** top blockers, not one:

### Blocker A - Fallback-policy noncompliance

Provider-router fallback surfaces still active:
- `src/agent_team_v15/provider_router.py:247-260`
- `src/agent_team_v15/provider_router.py:389-394`
- `src/agent_team_v15/provider_router.py:468-490`
- `src/agent_team_v15/provider_router.py:560-599`
- `src/agent_team_v15/provider_router.py:606-627`

Compile-fix / repair fallback surfaces still active:
- Structural fix path falls back to SDK-style fix path:
  - `src/agent_team_v15/wave_executor.py:4747-4761`
- Main compile-fix path still falls back to Claude:
  - `src/agent_team_v15/wave_executor.py:4844-4854`
- Wave B DTO guard fix path still falls back to SDK-style fix path:
  - `src/agent_team_v15/wave_executor.py:4977-4982`

Tests still encode old fallback assumptions:
- `tests/test_provider_routing.py:1184-1205`
- `tests/test_provider_routing.py:1210-1258`
- `tests/test_provider_routing.py:2023-2046`
- `tests/test_provider_routing.py:2229-2258`
- `tests/test_phase_h3d_sandbox_fix.py:92`

### Blocker B - Whole-pipeline contract drift and low-fidelity degradation risk

The next session must explicitly audit whether the pipeline still contains any of these contract-breaking or reliability-breaking behaviors:
- silent degradation from real OpenAPI generation to regex extraction
- any redispatch or compile-fix path that downgrades provider/runtime behavior
- repeated observer churn or prompt bloat that makes clean runs too slow or too costly
- any other stage that can silently continue on a lower-fidelity path instead of failing clearly

Until both blockers are addressed, a fresh smoke is not justified.

---

## 6. Mandatory whole-pipeline investigation plan for the next session

**Do not run smoke first.**

### Step 1 - Re-read the three handoff docs in order

1. `docs/plans/2026-04-23-handoff-codex-wedge-and-calibration.md`
2. `docs/plans/2026-04-23-handoff-clean-build-context7-no-guessing.md`
3. `docs/plans/2026-04-23-handoff-m1-wave-d-scope-fallback-hardening.md`

### Step 2 - Re-establish the governing truth model

Before changing any framework/provider/protocol behavior:
- resolve the official library in Context7
- query the exact behavior you need
- record the library ID used
- separate:
  - doc-backed fact
  - code-backed inference
  - still-unproven area

Mandatory already-revalidated library:
- `/openai/codex`

Likely libraries you may need, depending on the branch you touch:
- Express 5
- Next.js
- pnpm
- Prisma
- NestJS

### Step 3 - Audit the pipeline stage by stage, end to end

Do this as a pipeline map, not as isolated bug hunting. For each stage, write down:
- what the stage is supposed to do
- what inputs/artifacts it consumes
- what lower-fidelity or fallback behavior exists
- what can silently continue when it should fail
- what can become a performance hotspot
- what exact files/tests/log lines prove the current behavior

Minimum stages to audit:

1. Entrypoint / global config / provider wiring
   - `src/agent_team_v15/cli.py`
   - `src/agent_team_v15/provider_router.py`
   - `src/agent_team_v15/codex_appserver.py`

2. Phase 0.6 / requirement generation / design fallback surfaces
   - inspect whether fallback generation can poison later waves

3. Milestone planning / scope shaping / prompt assembly
   - `src/agent_team_v15/agents.py`
   - milestone scope files under `.agent-team/`
   - look for hardcoded ports, ownership bleed, env drift, or prompt poisoning

4. Wave B backend / self-verify / runtime verification / OpenAPI
   - `src/agent_team_v15/wave_executor.py`
   - `src/agent_team_v15/openapi_generator.py`
   - `src/agent_team_v15/api_contract_extractor.py`
   - verify that real OpenAPI generation, not regex degradation, is what a clean run would use

5. Generated client / downstream prompt consumers
   - inspect whether low-fidelity contracts can poison later waves

6. Wave D frontend / observer / compile / test / recompile
   - `src/agent_team_v15/agents.py`
   - `src/agent_team_v15/codex_observer_checks.py`
   - `src/agent_team_v15/wave_executor.py`
   - `src/agent_team_v15/codex_appserver.py`

7. Compile-fix / redispatch / repair loops
   - `src/agent_team_v15/wave_executor.py`
   - `src/agent_team_v15/provider_router.py`
   - remove or hard-fail any policy-breaking downgrade path

8. Finalization / artifact scoring / smoke-readiness gate
   - verify that contaminated or degraded runs cannot be mistaken for passes

### Step 4 - Treat performance as a first-class investigation axis

Based on the old logs, the next session must explicitly ask:
- Why did the app-server turn hit `tokens_in=2965619` and `839.6s`?
- Why did the Wave D turn take `670936ms`?
- Are repeated observer messages inflating logs and turn payloads?
- Are prompt builders feeding unnecessary context into turns?
- Are compile-fix / retry / redispatch loops doing duplicate work?
- Are any subprocess invocations or health waits obviously oversized or repeated?

Do not optimize blindly. First prove the hotspot from code and logs.

### Step 5 - Patch only proven root causes

When you edit:
- patch narrowly
- preserve unrelated behavior
- remove policy-breaking fallback paths rather than hiding them
- avoid replacing one silent degradation with another

### Step 6 - Run only targeted verification for what changed

At minimum, expect to update targeted tests around:
- provider-routing policy
- compile-fix routing policy
- any research-phase gating or prompt-context behavior you change
- any OpenAPI degradation path you harden
- any performance guard or observer behavior you change

Do not rerun the broad `406 passed` slice unless your edits genuinely require it.

### Step 7 - Only then decide whether smoke is justified

A fresh smoke is justified only if:
- fallback-policy surfaces are removed, fail-hard, or otherwise brought into compliance with the user's contract,
- OpenAPI / contract extraction behavior is proven acceptable for a clean run,
- targeted tests for the changed areas pass,
- and you can explain why the old contaminated or degraded behaviors will now fail fast or no longer occur.

If that bar is not met, stop and hand back evidence instead of burning smoke budget.

---

## 7. Hard rules to restate in every next-session kickoff

- `CONTEXT7 IS THE TRUTH.`
- DISCOVERY FIRST. READ BEFORE YOU WRITE.
- ACCURACY over speed.
- NO WORKAROUNDS. Fix root causes only.
- DO NOT guess on protocol/framework behavior.
- If Context7 is blocked, write `BLOCKED` and do not invent the rule.
- Do not waste session time investigating the known internal pipeline Context7 quota state on this account.
- Do not treat the old smoke as completion proof.
- Do not start a new smoke until targeted verification is green and the remaining contamination, degradation, and fallback risks are addressed.
- Do not normalize or clean the dirty repo blindly.
- Do not claim the pipeline is fixed while fallback-policy violations or documentation-truth violations remain.
- Audit the **whole pipeline**, not only the last visible failure.
- Think stage by stage and assume there may be latent failure points after the currently known issue.

---

## 8. Critical file and artifact map for the next continuation

| Area | File / Artifact | Key lines |
|---|---|---|
| Known account-quota artifact only | `C:/smoke/clean-r1b1-postwedge-13/run.log` | `155-170` |
| Internal pipeline Context7 handling (for context only, not current priority) | `src/agent_team_v15/cli.py` | `3388-3465` |
| Prompt note: "use your best judgment" (for context only, not current priority) | `src/agent_team_v15/cli.py` | `2439-2443`, `4598-4605`, `5265-5271` |
| OpenAPI regex-fallback evidence | `C:/smoke/clean-r1b1-postwedge-13/run.log` | `312-325` |
| OpenAPI fallback implementation | `src/agent_team_v15/openapi_generator.py` | `63-71`, `142-146`, `236-246`, `283-289` |
| Wave D prompt contamination evidence | `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-prompt.txt` | `168-177`, `208-224` |
| Wave D artifact bleed evidence | `C:/smoke/clean-r1b1-postwedge-13/.agent-team/artifacts/milestone-1-wave-D.json` | `8-23` |
| Observer log-only evidence | `C:/smoke/clean-r1b1-postwedge-13/run.log` | `387-397` |
| Observer log site | `src/agent_team_v15/codex_appserver.py` | `1439-1441` |
| Turn cost / timing log evidence | `C:/smoke/clean-r1b1-postwedge-13/run.log` | `303-304` |
| Turn cost / timing log site | `src/agent_team_v15/codex_appserver.py` | `1690-1693` |
| Wave D turn duration evidence | `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-protocol.log` | `1246` |
| `spawn EPERM` evidence | `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-protocol.log` | `419-422`, `797` |
| Wave D prompt filtering | `src/agent_team_v15/agents.py` | `7328-7348`, `8003-8018`, `9682-9782` |
| Observer forbidden-path matcher | `src/agent_team_v15/codex_observer_checks.py` | `30`, `68` |
| Observer log-only contract | `src/agent_team_v15/config.py` | `648-659` |
| Post-wave hard scope failure | `src/agent_team_v15/wave_executor.py` | `179-225`, `6406-6411` |
| Wave D guard recompile routing | `src/agent_team_v15/wave_executor.py` | `5040-5138` |
| Remaining provider fallback policy | `src/agent_team_v15/provider_router.py` | `247-260`, `389-394`, `468-490`, `560-599`, `606-627` |
| Remaining compile-fix fallback policy | `src/agent_team_v15/wave_executor.py` | `4747-4761`, `4844-4854`, `4977-4982` |
| Fixed CSS scaffold template | `src/agent_team_v15/scaffold_runner.py` | `1957` |
| Scope tests added | `tests/test_wave_scope_filter.py` | `264`, `309`, `329` |
| CSS regression test added | `tests/test_scaffold_rtl_baseline.py` | `62` |
| Wave D recompile routing test added | `tests/test_compile_fix_codex.py` | `193` |
| Forbidden-path helper test added | `tests/test_codex_observer_checks.py` | `134` |

---

## 9. One-paragraph summary for the next agent's first action

**Read the two older 2026-04-23 handoffs first, then read this handoff, then audit the whole execution pipeline from provider routing through OpenAPI generation, Wave D prompt assembly, observer behavior, compile-fix routing, and final smoke gating before touching anything else. The prompt contamination, post-wave scope failure, `.env` forbidden-path coverage, CSS scaffold defect, and Wave D recompile routing are already fixed and covered by targeted tests. The pipeline is still not smoke-ready because silent fallback policy remains live and the old logs already show low-fidelity degradation and throughput risk. Treat the old internal pipeline Context7 quota state as known account context, not as the bug to focus on. Do not burn another clean Milestone 1 smoke until the broader pipeline risks are either fixed or disproven with evidence.**

---

_End of expanded handoff - 2026-04-24_
