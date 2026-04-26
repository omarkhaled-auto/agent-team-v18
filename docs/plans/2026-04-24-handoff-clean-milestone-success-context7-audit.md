# HANDOFF - Clean milestone success, Context7-first audit and hardening

**Date:** 2026-04-24
**Repo:** `C:/Projects/agent-team-v18-codex`
**Branch at handoff:** `master`
**Goal:** get one milestone fully successful, clean, unblocked, and honestly promotable
**Current status:** not yet smoke-proven after the latest source fixes

---

## Read This First

The next session's mission is not "run until something passes." The mission is:

1. audit the whole path needed for one milestone to finish cleanly,
2. harden any proven blockers first,
3. use Context7 for framework/provider/protocol claims,
4. run targeted verification,
5. then run a fresh smoke only if the audit finds no blockers or all found blockers are fixed,
6. stop only when Milestone 1 is either fully successful and clean, or a real blocker is proven with artifacts.

If the audit finds no blocking issue, that is possible. Do not invent work. In that case, document the audit evidence, run the smoke, and monitor it to completion.

---

## Non-Negotiable Rules

- CONTEXT7 IS THE TRUTH for framework, provider, protocol, package-manager, Docker, Prisma, NestJS, Next.js, pnpm, Orval/OpenAPI, and Codex app-server claims.
- DISCOVERY FIRST. READ BEFORE YOU WRITE.
- AUDIT AND HARDENING FIRST. Smoke only after the audit says it is justified.
- NO WORKAROUNDS. Fix root causes only.
- No fake passes, no contaminated completion proof, no "probably good enough."
- If Context7 is unavailable or does not answer a required framework/protocol question, write `BLOCKED` for that question and do not invent the rule.
- Do not spend the session diagnosing account quota unless that is the proven product blocker. Treat prior Context7 quota failures as pipeline evidence, not the user's current request.
- Do not use `C:/smoke/clean-r1b1-postwedge-13` as a completion workspace. It is forensic-only.
- Preserve the dirty worktree. Do not clean or revert unrelated files.
- If a smoke produces decisive failure evidence, stop it and preserve artifacts instead of spending more budget.

---

## What Was Done In The Previous Session

### Source hardening implemented and verified

The prior session fixed the first fresh M1 smoke blocker class:

- blank-but-truthy `STACK_CONTRACT.json` is no longer trusted as resolved,
- Phase 1.5 re-derives stack contracts when state/disk contracts are semantically empty,
- wave execution ignores unresolved stack contracts instead of passing them as authoritative,
- `format_stack_contract_for_prompt()` no longer emits impossible `['(none)']` MUST rules,
- M1 scope parsing now derives allowed globs from generated `In-Scope Deliverables` and `Merge Surfaces`,
- run bookkeeping files are excluded from wave checkpoint tracking,
- `pnpm/npm workspace` is detected as `pnpm`,
- PostgreSQL-only `5432` no longer becomes `api_port=5432`.

Relevant files:

- `src/agent_team_v15/stack_contract.py`
- `src/agent_team_v15/cli.py`
- `src/agent_team_v15/wave_executor.py`
- `src/agent_team_v15/milestone_scope.py`
- `tests/test_stack_contract.py`
- `tests/test_wave_scope_filter.py`
- `tests/test_checkpoint_walker_skip.py`

### Tests that passed after the latest fixes

Focused:

```text
python -m pytest tests/test_checkpoint_walker_skip.py tests/test_stack_contract.py tests/test_wave_scope_filter.py
39 passed
```

Broader targeted hardening slice:

```text
python -m pytest tests/test_provider_routing.py tests/test_compile_fix_codex.py tests/test_a10_compile_fix.py tests/test_runtime_verification_block.py tests/test_openapi_launcher_resolution.py tests/test_v18_phase2_wave_engine.py tests/test_agents.py tests/test_codex_observer_checks.py tests/test_stack_contract.py tests/test_wave_scope_filter.py tests/test_checkpoint_walker_skip.py
658 passed
```

### Fresh smoke run observed and stopped

Run directory:

```text
C:/Projects/agent-team-v18-codex/v18 test runs/m1-hardening-smoke-20260424-094340
```

Important evidence from that run:

- Docker preflight succeeded from the user's PowerShell.
- Agent Teams was active.
- Provider routing was active: `B=codex`, `D=codex`, model `gpt-5.4`.
- Context7 research inside the pipeline returned quota exceeded for all six libraries and correctly wrote `TECH_RESEARCH.md` as `BLOCKED` instead of fabricating docs.
- The old blank-contract blocker was gone.
- `STACK_CONTRACT.json` became explicit for `nestjs`, `nextjs`, `prisma`, `postgresql`, `apps/api/`, and `apps/web/`.
- M1 scope globs were populated.
- No `WAVE_A_CONTRACT_CONFLICT.md` was produced.
- Wave A created Prisma files, then false-failed because `BUILD_LOG.txt` was included in wave diff/scope validation.
- The run was killed intentionally after the false scope violation was decisive. `EXIT_CODE.txt` contains `-1`.

The false-failure evidence:

```text
2026-04-24 09:54:13,416 WARNING agent_team_v15.wave_executor:
Wave A for milestone-1 produced 1 out-of-scope file(s): ['BUILD_LOG.txt']

Rollback: deleted created file prisma/migrations/20260424094340_init/migration.sql
Rollback: deleted created file prisma/migrations/migration_lock.toml
Rollback: deleted created file prisma/schema.prisma
Rollback: deleted created file prisma/seed.ts
```

This is now fixed in source by excluding run-root bookkeeping files from checkpoint walking, but it has not yet been proven by a fresh smoke.

---

## Current Known Risks Before Another Smoke

The next session must audit these quickly before launching:

1. **Source fixes are targeted-test green, but not smoke-proven.**
   - The `BUILD_LOG.txt` false scope violation should be gone, but only a new smoke can prove it in the live path.

2. **Internal pipeline Context7 may still be quota-blocked.**
   - That is acceptable only if the pipeline preserves `BLOCKED` wording and does not fabricate docs or framework claims.

3. **OpenAPI / client fidelity still matters.**
   - A milestone is not clean if Wave C silently downgrades real OpenAPI generation to regex/minimal low-fidelity output and later waves treat it as canonical.

4. **Fallback policy must stay clean.**
   - Codex-owned waves must not silently route through Claude fallback.
   - Claude-owned waves must use Agent Teams, not legacy CLI fallback.
   - Repair paths must not hide failures through SDK-style fallback when provider-routed Codex repair is required.

5. **Completion proof must be artifact-backed.**
   - Do not rely on a summary field if milestone state, audit artifacts, logs, or wave artifacts disagree.

---

## Mandatory Audit Before Fresh Smoke

Do this before launching a fresh run. Keep it focused; the goal is to decide if smoke is justified, not to perform an endless audit.

### 1. Read the governing docs

Read:

- `docs/plans/2026-04-24-handoff-clean-milestone-success-context7-audit.md`
- `docs/plans/2026-04-23-handoff-m1-wave-d-scope-fallback-hardening.md`
- `docs/plans/2026-04-23-handoff-clean-build-context7-no-guessing.md`
- `docs/plans/2026-04-24-m1-pre-smoke-gate.md` if present

### 2. Re-check repo state and active source

Run:

```powershell
git status --short
git worktree list
```

Do not revert unrelated changes.

### 3. Verify the immediate fixes in code

Inspect these source surfaces:

- `src/agent_team_v15/stack_contract.py`
  - `is_resolved_stack_contract`
  - `format_stack_contract_for_prompt`
  - package-manager detection
  - port literal extraction

- `src/agent_team_v15/cli.py`
  - stack contract resolution before milestone execution
  - `_resolved_stack_contract_for_wave`

- `src/agent_team_v15/milestone_scope.py`
  - generated M1 requirements fallback globs

- `src/agent_team_v15/wave_executor.py`
  - `_DEFAULT_SKIP_ROOT_FILES`
  - `_checkpoint_file_iter`
  - post-wave scope validation
  - provider-routed repair behavior

- `src/agent_team_v15/provider_router.py`
  - hard failure metadata on Codex failure
  - rollback behavior
  - no silent Codex-to-Claude fallback for Codex-owned waves

### 4. Use Context7 for any framework/protocol claim

Before changing behavior involving these, verify with Context7:

- `/openai/codex` for Codex app-server protocol or approval behavior
- official NestJS docs if changing NestJS bootstrap, Swagger, or validation behavior
- official Prisma docs if changing schema/migration/seed behavior
- official Next.js docs if changing App Router or build behavior
- official pnpm docs if changing workspace/install/build behavior
- official OpenAPI/Orval/openapi-typescript docs if changing contract/client generation

If Context7 is blocked for a claim, do not invent the claim. Either avoid changing that area or mark it `BLOCKED`.

### 5. Run targeted tests

At minimum:

```powershell
python -m pytest tests/test_checkpoint_walker_skip.py tests/test_stack_contract.py tests/test_wave_scope_filter.py
```

If provider routing or repair paths changed, also run:

```powershell
python -m pytest tests/test_provider_routing.py tests/test_compile_fix_codex.py tests/test_a10_compile_fix.py
```

If OpenAPI/client paths changed, also run:

```powershell
python -m pytest tests/test_openapi_launcher_resolution.py tests/test_v18_phase2_wave_engine.py
```

### 6. If audit finds no blocker, run the smoke

If the audit finds no active blocker and targeted tests pass, run a fresh smoke. This is allowed.

Use the existing helper:

```powershell
& "C:\Projects\agent-team-v18-codex\v18 test runs\start-m1-hardening-smoke.ps1"
```

The user may need to launch it from normal PowerShell because this Codex sandbox may not have Docker pipe access.

---

## Fresh Smoke Monitoring Contract

When the smoke starts, record:

- `RUN_DIR`
- `LOG`
- `ERR`
- `EXIT_CODE.txt` when it appears
- Docker preflight result
- `STACK_CONTRACT.json`
- generated M1 `REQUIREMENTS.md`
- `STATE.json`
- `milestone_progress.json`
- wave artifacts under `.agent-team/artifacts`
- any `WAVE_A_CONTRACT_CONFLICT.md`
- any `scope_violations`
- `AUDIT_INTERFACE.json`
- `AUDIT_REPORT.json` if present

Monitor until one of these happens:

1. **Milestone 1 fully succeeds cleanly.**
   - all expected Wave A/B/C/D/T/E paths for M1 complete as configured,
   - no degraded contract metadata,
   - no fallback metadata,
   - no scope violations,
   - no failed wave markers,
   - no observer spam contaminating proof,
   - Docker/build/runtime proof is present where configured,
   - audit artifacts do not contradict success.

2. **A decisive blocker appears.**
   - stop the run,
   - preserve artifacts,
   - document the exact evidence,
   - patch root cause only after reading source and using Context7 where relevant.

---

## Clean Milestone Success Definition

A milestone is not "fully successful" unless all of this is true:

- `EXIT_CODE.txt` is `0` or the process completed without an error code and final artifacts confirm success.
- `STATE.json` has no failed milestone marker for the milestone.
- `milestone_progress.json` does not report an interrupted or failed wave.
- All wave artifacts for the milestone agree with success.
- There is no `WAVE_A_CONTRACT_CONFLICT.md`.
- No `fallback_used=true` for Codex-owned waves.
- No degraded OpenAPI/contract/client metadata is treated as canonical.
- No scope violations are present.
- No generated product files were rolled back.
- Audit score/status does not contradict success.
- Runtime/build/Docker evidence is present where the config requires it.

If any of those disagree, treat the run as failed or contaminated and investigate.

---

## Suggested First Action For The Next Agent

1. Read this handoff.
2. Run the targeted tests listed above.
3. Re-derive the contract from the last stopped smoke inputs and confirm:
   - package manager is `pnpm`,
   - API port is not `5432`,
   - only PostgreSQL port `5432` is retained as a DB port,
   - M1 globs are populated,
   - `BUILD_LOG.txt` is not tracked by `_checkpoint_file_iter`.
4. If all checks pass and no audit blocker is found, launch a fresh smoke.
5. Monitor until Milestone 1 either passes cleanly or fails with decisive evidence.

---

## Bottom Line

The previous session removed two real blockers: blank contract/scope poisoning and run-log false scope violations. The next session should not restart broad theoretical hardening unless it finds a real blocker. Audit first, use Context7 for claims, run targeted tests, then push for one fully clean Milestone 1 success.

