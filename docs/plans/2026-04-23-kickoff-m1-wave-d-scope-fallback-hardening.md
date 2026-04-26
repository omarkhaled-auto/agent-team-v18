# 2026-04-24 Kickoff: Milestone 1 whole-pipeline failure and performance audit continuation

Use this file as the next-session prompt and operating contract.

## Mission

Continue hardening `C:\Projects\agent-team-v18-codex` until a clean Milestone 1 run can complete without:

- Wave D prompt contamination,
- Wave D scope bleed into backend/root files,
- silent Codex-to-Claude fallback,
- legacy SDK-style repair paths,
- Context7-truth violations,
- low-fidelity pipeline degradation paths,
- hidden stage-to-stage poison that breaks later waves,
- poor-performance hotspots that make runs unreliable or too expensive,
- or fake/contaminated completion proof.

This is a continuation of a high-risk session, not a fresh diagnosis.

## Mandatory Read Order

Read these in this exact order before editing anything:

1. `docs/plans/2026-04-23-handoff-codex-wedge-and-calibration.md`
2. `docs/plans/2026-04-23-handoff-clean-build-context7-no-guessing.md`
3. `docs/plans/2026-04-23-handoff-m1-wave-d-scope-fallback-hardening.md`
4. This file

Then give a concise investigation-first status update before any edits.

## Non-Negotiable Rules

1. `CONTEXT7 IS THE TRUTH.`
2. DISCOVERY FIRST. READ BEFORE YOU WRITE.
3. ACCURACY over speed.
4. NO WORKAROUNDS. Fix root causes only.
5. DO NOT guess on protocol/framework behavior.
6. If Context7 is blocked or quota-limited, write `BLOCKED` and do not invent the rule.
7. Every important conclusion must be backed by either:
   - Context7 documentation, or
   - direct repo or live-artifact evidence with exact file paths and line numbers.
8. Do not trust prior summaries over real files and artifacts.
9. Do not start a new smoke run until the required investigation is complete and targeted verification is green.
10. Do not treat the old smoke run as completion proof. It is contaminated and forensic-only.
11. Codex in all waves must be app-server.
12. Claude in all waves must be Agent Teams.
13. No legacy SDK subagent behavior.
14. No silent fallback paths that violate that requirement.
15. Audit the **whole pipeline**, not only the last visible error.
16. Think step by step from pipeline entrypoint to clean completion and actively look for:
   - latent breakpoints,
   - low-fidelity degradation paths,
   - policy-breaking continue-anyway behavior,
   - and poor-performance hotspots.

Important distinction:
- The next agent's **own** source of truth for framework/provider/protocol claims is Context7.
- The old smoke run's **internal pipeline** Context7 quota exhaustion reflects the current account quota state and is **not** the product issue to investigate right now.
- Do not spend time diagnosing account quota, MCP availability, or quota-remediation workflow in this repo session.

## Current Proven State You Must Respect

Already true from prior continuations:

- Wave B.1 Docker/probe retry realism was fixed.
- Express 5 `req.query` prompt hardening plus validator was fixed.
- Windows OpenAPI launcher `WinError 193` resolution was fixed in repo.
- Hardcoded `8080` prompt drift removal was fixed.
- Broad targeted verification already passed:
  - `python -m pytest tests/test_agents.py tests/test_openapi_launcher_resolution.py tests/test_v18_phase2_wave_engine.py -q`
  - `406 passed`

Fixed in the most recent code continuation:

- Wave D prompt scaffold/task lists are filtered to frontend-only paths:
  - `src/agent_team_v15/agents.py:7328-7348`
  - `src/agent_team_v15/agents.py:8003-8018`
  - `src/agent_team_v15/agents.py:9682-9782`
- Post-wave scope validation now fails non-Wave-A waves on out-of-scope writes:
  - `src/agent_team_v15/wave_executor.py:179-225`
  - `src/agent_team_v15/wave_executor.py:6406-6411`
- `.env*` is now covered by forbidden-path matching:
  - `src/agent_team_v15/codex_observer_checks.py:30`
  - `src/agent_team_v15/codex_observer_checks.py:68`
- The scaffold RTL CSS comment defect was fixed:
  - `src/agent_team_v15/scaffold_runner.py:1957`
- Wave D recompile routing now preserves `provider_routing`:
  - `src/agent_team_v15/wave_executor.py:5040-5138`

Targeted verification already completed for those latest fixes:

```text
python -m pytest tests/test_wave_scope_filter.py tests/test_scaffold_rtl_baseline.py tests/test_compile_fix_codex.py tests/test_codex_observer_checks.py -q
39 passed in 1.31s
```

These are necessary fixes, not proof that the pipeline is now clean-run ready.

## Additional Pipeline Risks Already Visible In The Old Logs

These are forensic facts, not completion proof:

### 1. Known operator-context note: internal pipeline Context7 quota was exhausted in the old smoke

- `C:/smoke/clean-r1b1-postwedge-13/run.log:155-170`
- The research phase marked the work `BLOCKED` for monthly quota exceeded and the pipeline still moved to `Phase 2: Executing 5 milestones`.
- Relevant code:
  - `src/agent_team_v15/cli.py:3406-3460`
  - `src/agent_team_v15/cli.py:2439-2443`
  - `src/agent_team_v15/cli.py:4598-4605`
  - `src/agent_team_v15/cli.py:5265-5271`
- Treat this as forensic context only. Do **not** spend the session trying to solve the quota state itself.

### 2. Wave D modified backend/root files

- `C:/smoke/clean-r1b1-postwedge-13/.agent-team/artifacts/milestone-1-wave-D.json:8-23`
- The observer detected drift but only logged it:
  - `C:/smoke/clean-r1b1-postwedge-13/run.log:387-397`

### 3. The contaminated Wave D prompt itself handed backend/root files to the frontend wave

- `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-prompt.txt:168-177`
- `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-prompt.txt:208-224`

### 4. OpenAPI degraded to regex extraction in the old run

- `C:/smoke/clean-r1b1-postwedge-13/run.log:312-325`
- Relevant code:
  - `src/agent_team_v15/openapi_generator.py:63-71`
  - `src/agent_team_v15/openapi_generator.py:142-146`
  - `src/agent_team_v15/openapi_generator.py:236-246`
  - `src/agent_team_v15/openapi_generator.py:283-289`

### 5. The captured Wave D turn recorded Windows `spawn EPERM`

- `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-protocol.log:419-422`
- `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-protocol.log:797`

### 6. The contaminated workspace contains a deterministic malformed CSS comment

- `C:/smoke/clean-r1b1-postwedge-13/apps/web/src/styles/globals.css:5-6`

### 7. The old run already showed throughput / cost warning signs

- `C:/smoke/clean-r1b1-postwedge-13/run.log:303-304`
  - app-server turn `tokens_in=2965619`, `tokens_out=37887`, `cost=$1.8953`, `839.6s`
- `C:/smoke/clean-r1b1-postwedge-13/.agent-team/codex-captures/milestone-1-wave-D-protocol.log:1246`
  - Wave D turn `durationMs=670936`
- `src/agent_team_v15/codex_appserver.py:1690-1693`
  - cost/timing log site

## The Main Open Blockers

The pipeline is still **not** smoke-ready because of both correctness and whole-pipeline contract risk.

### Blocker A - fallback policy is still noncompliant

Main provider fallback surfaces still active:

- `src/agent_team_v15/provider_router.py:247-260`
- `src/agent_team_v15/provider_router.py:389-394`
- `src/agent_team_v15/provider_router.py:468-490`
- `src/agent_team_v15/provider_router.py:560-599`
- `src/agent_team_v15/provider_router.py:606-627`

Compile-fix and repair fallback surfaces still active:

- `src/agent_team_v15/wave_executor.py:4747-4761`
- `src/agent_team_v15/wave_executor.py:4844-4854`
- `src/agent_team_v15/wave_executor.py:4977-4982`

Observer is still `log_only` by default:

- `src/agent_team_v15/config.py:648-659`
- `src/agent_team_v15/codex_appserver.py:1439-1441`

### Blocker B - the pipeline may still contain continue-anyway or low-fidelity paths

You must audit for:

- regex-extraction degradation where real OpenAPI generation should exist
- any redispatch or compile-fix path that downgrades provider/runtime behavior
- any other stage that silently continues after degraded inputs
- performance hotspots that make clean runs slow or unstable

That means the latest continuation prevents contaminated success and reduces prompt poisoning, but it does **not** yet prove a fully clean end-to-end path.

## Mandatory Whole-Pipeline Investigation Before Any New Smoke

### 1. Re-establish the truth contract with Context7

Before any framework/provider/protocol fix:

- Resolve the official library in Context7.
- Query the exact behavior you need.
- State the library ID used.
- Apply the fix only after that.
- In your reasoning and final report, distinguish:
  - doc-backed fact
  - code-backed inference
  - still-unproven area

Already revalidated in the prior continuation:

- Codex library ID: `/openai/codex`
- Documented app-server startup command: `codex app-server --listen stdio://`
- Documented JSON-RPC operations: `thread/start`, `turn/start`
- Documented server-to-client approval requests: `applyPatchApproval`, `execCommandApproval`

If you touch Express, Next.js, pnpm, NestJS, or Prisma, resolve and query those libraries too.

### 2. Build a step-by-step pipeline map before editing

You must think through the pipeline as a sequence, not a pile of bugs. At minimum audit these stages:

1. CLI entrypoint / provider routing / transport mode / team mode
2. Phase 0.6 requirement generation and any fallback outputs
3. milestone planning / prompt assembly / scope shaping
4. Wave B backend / self-verify / runtime verification
5. OpenAPI generation / contract extraction / generated client handoff
6. Wave D frontend prompt assembly / observer / build / test / recompile
7. compile-fix / redispatch / repair loops
8. artifact finalization / scoring / smoke gating

For each stage, explicitly write down:

- expected inputs
- expected outputs
- possible silent degradation paths
- possible poor-performance points
- exact files / logs / tests that prove current behavior

### 3. Audit the OpenAPI / contract fidelity path

Questions to answer with code lines:

- Does a clean run now use the real OpenAPI launcher path on Windows?
- If not, where does it degrade to regex extraction?
- Is regex extraction acceptable for the current mission, or does it poison later waves?
- Which later prompts or generators consume that lower-fidelity output?

Inspect at minimum:

- `src/agent_team_v15/openapi_generator.py`
- `src/agent_team_v15/api_contract_extractor.py`
- downstream prompt construction that consumes contracts

### 4. Audit and resolve fallback policy

Before any smoke rerun, prove exactly how the remaining fallback branches should behave under the user's contract.

You must inspect at minimum:

- `src/agent_team_v15/provider_router.py`
- `src/agent_team_v15/wave_executor.py`
- `tests/test_provider_routing.py`
- any compile-fix routing tests tied to those branches

Questions to answer with code lines:

- Which branches still fall back to Claude?
- Which branches still use SDK-style repair calls?
- Which existing tests encode the old fallback contract?
- What exact policy change is needed so the production code matches the user's stated rules?

### 5. Keep EPERM investigation honest

Do not rewrite the handoff into "EPERM was solved." That is not proven.

What is proven:

- the scaffold CSS comment defect existed and is fixed in repo
- the old captured turn showed `spawn EPERM`

What is not proven:

- whether `spawn EPERM` persists after the scaffold fix
- whether it is environment-specific, generated-code-specific, or both

If you revisit it, use the contaminated smoke workspace only for forensic reproduction, not as completion proof.

### 6. Treat throughput as a first-class investigation axis

Questions to answer:

- Why did the app-server turn hit `2965619` input tokens and `839.6s`?
- Why did the Wave D turn take `670936ms`?
- Are observer log-only warnings causing repeated churn?
- Are prompts too large?
- Are retries / redispatch / compile-fix loops doing duplicate work?
- Are there avoidable health waits or subprocess patterns inflating runtime?

Do not optimize blindly. Prove the hotspot from logs and code first.

## Suggested First Commands

Run these before editing:

1. `git status --short`
2. `rg -n "fallback|fallback_used|regex extraction|log_only|Observer \\(log_only\\)|tokens_in=|cost=|durationMs|spawn EPERM" src tests`
3. `rg -n "Observer \\(log_only\\)|OpenAPI script generation unavailable|spawn EPERM|tokens_in=|cost=|durationMs" C:\smoke\clean-r1b1-postwedge-13\run.log C:\smoke\clean-r1b1-postwedge-13\.agent-team\codex-captures\milestone-1-wave-D-protocol.log`
4. Re-read the code and artifacts cited above
5. Write a stage-by-stage audit note for yourself before patching
6. Only then patch narrowly
7. Run only the targeted pytest slices for what you changed

Do **not** begin with a smoke rerun.

## When A Fresh Smoke Is Finally Allowed

Only after:

- the fallback-policy surfaces are brought into compliance with the user's contract,
- the OpenAPI / contract path is proven acceptable for a clean run,
- the targeted routing / gating / fidelity tests for those changes pass,
- and you can explain exactly why the old contaminated or degraded behaviors will now fail fast or no longer occur.

If that is not true, stop and report evidence instead of spending smoke budget.

## Stop Criteria For This Session

You are not done when "some tests pass."

You are done only when one of these is true:

1. The remaining contract and fallback gaps are fixed, the whole-pipeline audit found no unaddressed critical poison points, and targeted verification is green, making a fresh smoke justified.
2. You hit a real blocker and can prove it with code or artifact evidence.

If neither is true, keep investigating.

## Bottom Line

The latest continuation closed real root-cause gaps in:

- prompt contamination,
- weak post-wave scope enforcement,
- `.env` forbidden-path coverage,
- the scaffold CSS defect,
- and Wave D recompile routing.

That still does **not** make the pipeline clean-run ready.

The next session must start with a **whole-pipeline, Context7-first audit** focused on:

- OpenAPI / contract fidelity,
- provider and compile-fix fallback policy,
- observer behavior and scope enforcement,
- and performance hotspots visible in the old logs.

Start with the pipeline map, not with another smoke.
