# 2026-04-23 Handoff: Clean Build Continuation, Context7-First, No Guessing

Use this file as the next-session prompt and operating contract.

## Mission

Continue hardening `C:\Projects\agent-team-v18-codex` until the pipeline can complete a clean milestone run without prompt drift, transport wedges, Docker/probe false recovery, Windows launcher mistakes, or scope bleed.

This is not a brainstorming session. This is a high-risk continuation on a repo that has already burned a lot of smoke budget.

## Non-Negotiable Rules

- DISCOVERY FIRST. READ BEFORE YOU WRITE.
- Do not trust prior summaries over live artifacts. Inspect the actual files listed below first.
- Do not guess. Every framework/protocol claim must be backed by:
  - Context7 official docs, or
  - direct code evidence with file paths and line numbers.
- Do not start a new smoke run until the mandatory investigation and targeted repo verification below are complete.
- Do not treat the old smoke run as completion proof. It is useful for evidence, but it is contaminated.
- No workaround fixes. Fix root causes only.
- If Context7 is unavailable or quota-blocked, write `BLOCKED` and do not fabricate a rule.

## Mandatory Read Order

Read these in this order before touching code:

1. `docs/plans/2026-04-23-handoff-codex-wedge-and-calibration.md`
2. This file.
3. Repo code touched in this session:
   - `src/agent_team_v15/wave_executor.py`
   - `src/agent_team_v15/agents.py`
   - `src/agent_team_v15/codex_prompts.py`
   - `src/agent_team_v15/quality_validators.py`
   - `src/agent_team_v15/openapi_generator.py`
   - `tests/test_runtime_verification_block.py`
   - `tests/test_n09_wave_b_prompt_hardeners.py`
   - `tests/test_quality_validators.py`
   - `tests/test_openapi_launcher_resolution.py`
   - `tests/test_agents.py`
4. Live smoke artifacts from the old run:
   - `C:\smoke\clean-r1b1-postwedge-13\run.log`
   - `C:\smoke\clean-r1b1-postwedge-13\.agent-team\STATE.json`
   - `C:\smoke\clean-r1b1-postwedge-13\.agent-team\artifacts\milestone-1-wave-B.json`
   - `C:\smoke\clean-r1b1-postwedge-13\.agent-team\artifacts\milestone-1-wave-C.json`
   - `C:\smoke\clean-r1b1-postwedge-13\.agent-team\artifacts\milestone-1-wave-D.json`
   - `C:\smoke\clean-r1b1-postwedge-13\.agent-team\codex-captures\milestone-1-wave-B-protocol.log`
   - `C:\smoke\clean-r1b1-postwedge-13\.agent-team\codex-captures\milestone-1-wave-D-protocol.log`
   - `C:\smoke\clean-r1b1-postwedge-13\.agent-team\codex-captures\milestone-1-wave-D-prompt.txt`

## What Was Fixed In This Session

### 1. Wave B.1 stale-container probe recovery was made real instead of partial

Problem:

- The old recovery path could apply a probe fix, but it did not fully rebuild the Docker/runtime state before retrying live probes.
- That created false confidence around fixes that were never exercised against a restarted stack.

Fix:

- `src/agent_team_v15/wave_executor.py:3654`
- `src/agent_team_v15/wave_executor.py:3669`
- `src/agent_team_v15/wave_executor.py:3680`

Behavior now:

- after successful probe-fix redispatch, the executor stops Docker services,
- restarts Docker services for probing,
- treats restart/startup failure as blocking,
- resets DB/seeds,
- then retries probing.

Guardrail:

- `tests/test_runtime_verification_block.py:744` asserts the repair path uses Codex routing and not the legacy SDK sub-agent path.

### 2. Wave B prompt hardening now forbids Express 5 `req.query` reassignment

Problem:

- Express 5 made `req.query` getter-backed.
- Generated middleware that did `req.query = normalize(...)` is invalid and was already showing up in generated output.

Fixes:

- Prompt hardener:
  - `src/agent_team_v15/codex_prompts.py:170`
  - `src/agent_team_v15/codex_prompts.py:177`
- Canonical Wave B instructions:
  - `src/agent_team_v15/agents.py:8893`

New rule:

- `AUD-025` explicitly forbids reassigning `req.query` and requires in-place normalization or a derived local copy.

Validator:

- `src/agent_team_v15/quality_validators.py:933`
- `src/agent_team_v15/quality_validators.py:1036`
- `src/agent_team_v15/quality_validators.py:1039`

Tests:

- `tests/test_n09_wave_b_prompt_hardeners.py:33`
- `tests/test_quality_validators.py:913`
- `tests/test_quality_validators.py:923`
- `tests/test_quality_validators.py:944`

### 3. OpenAPI script launcher resolution on Windows was fixed

Problem:

- In real scaffolded workspaces, `apps/api/node_modules/.bin` contains both:
  - extensionless POSIX shims like `ts-node`
  - Windows launchers like `ts-node.cmd`
- On Windows, returning the extensionless shim to `subprocess.run([path, ...])` causes:
  - `[WinError 193] %1 is not a valid Win32 application`

Root-cause code proof:

- `src/agent_team_v15/openapi_generator.py:233`
- `src/agent_team_v15/openapi_generator.py:287`
- `src/agent_team_v15/openapi_generator.py:289`
- `src/agent_team_v15/openapi_generator.py:312`
- `src/agent_team_v15/openapi_generator.py:314`

Fix:

- `_resolve_local_bin(...)` now skips extensionless shims on Windows and only returns native launchers (`.cmd`, `.exe`, `.bat`).

Tests:

- `tests/test_openapi_launcher_resolution.py:322`
- `tests/test_openapi_launcher_resolution.py:326`
- `tests/test_openapi_launcher_resolution.py:332`

### 4. Generic prompt drift that invented port 8080 was removed

Problem:

- The live Wave D prompt still said `Port: Listen on PORT env var, default 8080.`
- That is wrong for this scaffold and was actively poisoning later waves.

Live proof:

- `C:\smoke\clean-r1b1-postwedge-13\.agent-team\codex-captures\milestone-1-wave-D-prompt.txt:113`

Repo-side port contract proof:

- `src/agent_team_v15/scaffold_runner.py` already treats `PORT=4000` as canonical for this scaffold family.
- `docs/SCAFFOLD_OWNERSHIP.md` and scaffold integration tests also align to that contract.

Fixes:

- Orchestrator Dockerfile guidance:
  - `src/agent_team_v15/agents.py:1132`
- Python stack instructions:
  - `src/agent_team_v15/agents.py:1928`
- TypeScript backend instructions:
  - `src/agent_team_v15/agents.py:2063`

Tests:

- `tests/test_agents.py:79`
- `tests/test_agents.py:81`
- `tests/test_agents.py:1795`
- `tests/test_agents.py:1803`
- `tests/test_agents.py:1804`

## Targeted Verification Already Completed

These were run and passed in this session:

1. `python -m pytest tests/test_runtime_verification_block.py tests/test_n09_wave_b_prompt_hardeners.py tests/test_quality_validators.py -q`
   - `149 passed in 1.81s`

2. `python -m pytest tests/test_h1a_wiring.py tests/test_runtime_verification_block.py tests/test_v18_decoupling.py tests/test_v18_phase3_integration.py tests/test_v18_phase3_helpers.py tests/test_v18_phase3_verification.py tests/test_phase_h3c_wave_b_fixes.py tests/test_transport_selector.py tests/test_n09_wave_b_prompt_hardeners.py tests/test_quality_validators.py -q`
   - `266 passed in 6.02s`

3. `python -m pytest tests/test_openapi_launcher_resolution.py -q`
   - `19 passed in 0.58s`

4. `python -m pytest tests/test_agents.py tests/test_openapi_launcher_resolution.py tests/test_v18_phase2_wave_engine.py -q`
   - `406 passed in 89.20s (0:01:29)`

## Docker Cleanup Already Performed Safely

Safe cleanup already done before this handoff:

- `docker image prune -af` reclaimed `42.56MB`
- `docker builder prune -af` reclaimed `8.189GB`
- `docker volume prune -f` reclaimed `0B`
- `docker network prune -f` no material reclaim

No active process tied to `C:\smoke\clean-r1b1-postwedge-13` remained at handoff time.

## What The Old Smoke Run Proved

These are useful facts from the old run. Use them as evidence, not as completion proof.

### Codex really was app-server in the live run

- `C:\smoke\clean-r1b1-postwedge-13\run.log:197`
- `C:\smoke\clean-r1b1-postwedge-13\run.log:199`

Observed:

- `Detected Codex CLI v0.123.0`
- `App-server initialized`

Protocol proof:

- `C:\smoke\clean-r1b1-postwedge-13\.agent-team\codex-captures\milestone-1-wave-B-protocol.log:1`
- `...wave-B-protocol.log:3`
- `...wave-B-protocol.log:8`
- `...wave-B-protocol.log:1239`

Observed methods:

- `initialize`
- `thread/start`
- `turn/start`
- `thread/archive`

Also note:

- `thread/start` was sent with `"sandbox":"workspace-write"`.

### Claude really was Agent Teams in the live run

- `C:\smoke\clean-r1b1-postwedge-13\run.log:39`
- `C:\smoke\clean-r1b1-postwedge-13\run.log:47`

Observed:

- `Agent Teams enabled`
- `Mode: agent_teams`

### Research handled Context7 quota exhaustion correctly

- `C:\smoke\clean-r1b1-postwedge-13\run.log:148`
- `C:\smoke\clean-r1b1-postwedge-13\run.log:155`
- `C:\smoke\clean-r1b1-postwedge-13\run.log:159`
- `C:\smoke\clean-r1b1-postwedge-13\run.log:166`

Observed:

- monthly quota exhausted
- research recorded `BLOCKED`
- pipeline did not fabricate documentation

### The old Wave B transport wedge was fixed

- `C:\smoke\clean-r1b1-postwedge-13\run.log:303`
- `C:\smoke\clean-r1b1-postwedge-13\run.log:305`

Observed:

- Wave B app-server turn completed
- Wave B self-verify passed

### Wave C completed and generated the client

- `C:\smoke\clean-r1b1-postwedge-13\.agent-team\artifacts\milestone-1-wave-C.json:5`
- `...milestone-1-wave-C.json:6`
- `...milestone-1-wave-C.json:29`

Observed:

- cumulative OpenAPI spec exists
- generated client export `check` exists
- client files were created

## Why The Old Smoke Run Is Not Valid Completion Proof

This is the most important thing to understand before continuing.

### 1. Wave D prompt was contaminated by the hardcoded 8080 rule

- `C:\smoke\clean-r1b1-postwedge-13\.agent-team\codex-captures\milestone-1-wave-D-prompt.txt:113`

That prompt told the agent to default backend porting to `8080`. That is stale and wrong.

### 2. Wave D crossed scope and edited backend files during a frontend wave

Artifact proof:

- `C:\smoke\clean-r1b1-postwedge-13\.agent-team\artifacts\milestone-1-wave-D.json:8`

The Wave D artifact lists backend files modified during a frontend wave, including:

- `.env.example`
- `apps/api/.env.example`
- `apps/api/Dockerfile`
- `apps/api/src/config/env.validation.spec.ts`
- `apps/api/src/config/env.validation.ts`
- `apps/api/src/main.spec.ts`
- `apps/api/src/main.ts`

### 3. The log-only observer clearly detected the scope violation, but did not stop it

- `C:\smoke\clean-r1b1-postwedge-13\run.log:388`
- many repeated occurrences later in the same file

Observed:

- `Wave D is the frontend wave ... current step touches out-of-scope files`

This means the detection existed, but enforcement did not actually protect the wave.

### 4. Wave D also hit real Windows build/test failures

Protocol proof:

- `C:\smoke\clean-r1b1-postwedge-13\.agent-team\codex-captures\milestone-1-wave-D-protocol.log:422`
- `...wave-D-protocol.log:797`

Observed:

- `ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL`
- `Build error occurred`
- `spawn EPERM`

Do not paper over this. In the next session, prove whether this is:

- an environment-specific Windows child-process problem,
- a scaffold defect,
- or a Wave D-generated repo defect.

### 5. The run advanced into D5, so its later state is already downstream of bad inputs

- `C:\smoke\clean-r1b1-postwedge-13\run.log:2498`
- `C:\smoke\clean-r1b1-postwedge-13\run.log:2506`
- `C:\smoke\clean-r1b1-postwedge-13\.agent-team\STATE.json:147`
- `C:\smoke\clean-r1b1-postwedge-13\.agent-team\STATE.json:148`

Observed:

- D turn completed
- D5 became active
- `STATE.json` shows `current_wave: D5`

Conclusion:

- the old run is useful forensic evidence,
- but it must not be treated as a clean pass or used as final pipeline proof.

## Mandatory Investigation Before Any New Smoke

Do all of this before asking for or starting another full run.

### A. Re-audit Wave D scope enforcement

You must determine exactly why a frontend-only wave was still allowed to modify backend files.

Inspect at minimum:

- `src/agent_team_v15/agent_teams_backend.py`
- `src/agent_team_v15/wave_executor.py`
- `src/agent_team_v15/provider_router.py`
- any observer / scoping / ownership enforcement path used during Wave D

Questions to answer with code lines:

- Is the Wave D observer intentionally `log_only`?
- Where should hard blocking happen?
- Is there already a config gate that was disabled in the run config?
- Is the problem prompt-level, enforcement-level, or both?

Do not guess. Prove it from code and the run artifact.

### B. Reproduce `spawn EPERM` minimally before changing product code

Do not start with broad edits.

Use the contaminated smoke workspace only for forensic reproduction:

- `C:\smoke\clean-r1b1-postwedge-13`

Goal:

- find whether `pnpm --filter web build` / `pnpm --filter web test` fails because of:
  - generated code,
  - Windows/esbuild child-process behavior,
  - path/permission/antivirus interaction,
  - or something else.

If it is environmental, document it cleanly and do not mutate app code to hide it.

### C. Re-audit for any remaining prompt or template drift that can re-poison later waves

Run focused grep/read inspection for:

- hardcoded `8080`
- hardcoded `80`
- instructions that tell a wave to touch files outside its ownership
- instructions that silently allow port invention, env rewrites, or Docker rewrites

Do this across:

- prompt builders
- stack instructions
- Docker templates
- compile-fix prompts
- wave-specific prompt builders

### D. Reconfirm app-server and Agent Teams wiring is hardwired everywhere it matters

The user requirement is:

- Codex in all waves must use app-server
- Claude in all waves must use Agent Teams
- no stupid subagents

Do not assume that because the old run showed this in B and D, the entire routing surface is correct.

Audit:

- provider maps
- routing fallbacks
- compile-fix routing
- recovery-wave redispatch routing
- any path that can still fall back to SDK sub-agents

### E. Reconfirm Codex 0.123.0 implications before touching transport/config code again

Use Context7 first. Then inspect local code.

Focus:

- app-server startup contract
- stdio transport assumptions
- supported method names
- config rendering assumptions
- anything that changed between earlier local understanding and `v0.123.0`

## Context7 Usage Contract For The Next Session

This is mandatory. Follow it every time you touch framework- or provider-specific behavior.

### General Rule

Before making a protocol/framework fix:

1. Resolve the official library ID in Context7.
2. Query the relevant docs with the exact behavior you are validating.
3. Record the library ID and the returned rule in your notes/handoff.
4. Only then patch code.

If Context7 is blocked:

- record `BLOCKED`
- do not invent the rule
- fall back only to direct code evidence if the behavior is locally provable

### Known high-value Context7 targets for this repo

- Codex CLI / app-server:
  - resolve `OpenAI Codex`
  - preferred library: `/openai/codex`
- Express 5:
  - resolve `Express`
  - preferred library: `/expressjs/express/v5.1.0`
- NestJS:
  - resolve `NestJS`
- Next.js:
  - resolve `Next.js`
- pnpm:
  - resolve `pnpm`
- Prisma:
  - resolve `Prisma`

### Already confirmed via Context7 in this session

Codex:

- `/openai/codex` documents `codex app-server --listen stdio://`
- it documents JSON-RPC-style app-server thread operations and `thread/start` / `turn/start`
- that matches the live protocol capture in the smoke artifact

Express 5:

- `/expressjs/express/v5.1.0` documents `req.query` as a getter
- that matches the hardening/validator rule added here

## Suggested First Commands For The Next Session

Run these before editing:

1. `git status --short`
2. `rg -n "8080|EXPOSE 80|req\\.query =|log_only|agent_teams|app-server|sub-agent|subagent" src tests`
3. inspect the files/artifacts listed in the Mandatory Read Order
4. run only targeted pytest slices for any code you touch

Do not begin with a smoke rerun.

## When A New Smoke Is Finally Allowed

Only after:

- the mandatory investigation above is complete,
- any newly found root causes are fixed,
- the targeted tests for those fixes pass,
- and you can explain exactly why the previous contamination cannot recur.

Then start a fresh smoke in a new clean workspace, not in the old contaminated root.

## Bottom Line

This repo is much closer than before, but it is not done.

What is now solid:

- Codex app-server was live and real in smoke.
- Claude Agent Teams was live and real in smoke.
- the old Wave B wedge is fixed.
- Wave B.1 probe-fix restart logic is stronger.
- Express 5 `req.query` drift is now hardened and validated.
- the Windows `WinError 193` OpenAPI launcher bug is fixed.
- hardcoded `8080` drift was removed from prompt surfaces that were poisoning the run.

What is still open:

- Wave D scope enforcement must be audited and likely hardened.
- `spawn EPERM` must be diagnosed correctly, not guessed away.
- a fresh clean smoke has not been run after the latest prompt fixes.

Do not shortcut that last part.
