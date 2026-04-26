# 2026-04-24 Kickoff: Clean Milestone 1 success with Context7-first audit

Use this as the next-session prompt.

## Mission

Continue in `C:\Projects\agent-team-v18-codex` and get **Milestone 1 fully successful, clean, unblocked, and honestly promotable**.

Start from this handoff:

```text
docs/plans/2026-04-24-handoff-clean-milestone-success-context7-audit.md
```

The job is not to run smoke blindly. The job is:

1. read the handoff,
2. audit and harden first,
3. use Context7 for framework/provider/protocol claims,
4. run targeted verification,
5. if the audit finds no blockers, run the fresh smoke,
6. monitor until Milestone 1 fully succeeds cleanly or a real blocker is proven.

If the audit finds nothing blocking, say that clearly and proceed to smoke. Do not invent more work.

## Mandatory Read Order

Read these before editing anything:

1. `docs/plans/2026-04-24-handoff-clean-milestone-success-context7-audit.md`
2. `docs/plans/2026-04-23-handoff-m1-wave-d-scope-fallback-hardening.md`
3. `docs/plans/2026-04-23-handoff-clean-build-context7-no-guessing.md`
4. `docs/plans/2026-04-24-m1-pre-smoke-gate.md` if present

Then give a concise status update with:

- what is already fixed,
- what still needs audit,
- whether a smoke is currently justified.

## Non-Negotiable Rules

- CONTEXT7 IS THE TRUTH.
- DISCOVERY FIRST. READ BEFORE YOU WRITE.
- AUDIT AND HARDENING FIRST.
- ACCURACY over speed.
- NO WORKAROUNDS. Fix root causes only.
- Do not guess on framework, provider, protocol, Docker, package-manager, Prisma, NestJS, Next.js, OpenAPI, Orval, or Codex app-server behavior.
- If Context7 is blocked or does not answer an exact question, write `BLOCKED` for that question and do not invent the rule.
- Do not diagnose account quota unless it is the proven product blocker.
- Do not use `C:\smoke\clean-r1b1-postwedge-13` as completion proof.
- Do not revert or clean unrelated dirty worktree files.
- Do not run a fresh smoke until the targeted audit and tests justify it.
- If the smoke reaches decisive failure evidence, stop it, preserve artifacts, and fix root cause.

## Current Known State

The previous session fixed and verified these source issues:

- blank-but-truthy stack contracts are no longer trusted,
- unresolved stack contracts are re-derived before waves,
- Wave A prompts no longer emit impossible `['(none)']` MUST rules,
- generated M1 requirements now produce scope globs,
- run bookkeeping files like `BUILD_LOG.txt` are excluded from wave checkpoints,
- `pnpm/npm workspace` is detected as `pnpm`,
- PostgreSQL-only `5432` no longer becomes `api_port=5432`.

Targeted verification passed:

```text
python -m pytest tests/test_checkpoint_walker_skip.py tests/test_stack_contract.py tests/test_wave_scope_filter.py
39 passed
```

Broader hardening slice passed:

```text
python -m pytest tests/test_provider_routing.py tests/test_compile_fix_codex.py tests/test_a10_compile_fix.py tests/test_runtime_verification_block.py tests/test_openapi_launcher_resolution.py tests/test_v18_phase2_wave_engine.py tests/test_agents.py tests/test_codex_observer_checks.py tests/test_stack_contract.py tests/test_wave_scope_filter.py tests/test_checkpoint_walker_skip.py
658 passed
```

The last fresh smoke was stopped intentionally:

```text
C:\Projects\agent-team-v18-codex\v18 test runs\m1-hardening-smoke-20260424-094340
```

It proved the old blank-contract blocker was gone, then exposed a false scope violation on `BUILD_LOG.txt`. That false violation has since been fixed in source and covered by tests, but not yet smoke-proven.

## Audit Before Smoke

Run or inspect the following before launching:

```powershell
git status --short
git worktree list
python -m pytest tests/test_checkpoint_walker_skip.py tests/test_stack_contract.py tests/test_wave_scope_filter.py
```

Inspect:

- `src/agent_team_v15/stack_contract.py`
- `src/agent_team_v15/cli.py`
- `src/agent_team_v15/milestone_scope.py`
- `src/agent_team_v15/wave_executor.py`
- `src/agent_team_v15/provider_router.py`
- `src/agent_team_v15/openapi_generator.py`

Confirm:

- `STACK_CONTRACT.json` cannot be blank-but-truthy,
- generated M1 requirements produce valid globs,
- `BUILD_LOG.txt` and other run bookkeeping files are not wave outputs,
- `pnpm/npm workspace` resolves to `pnpm`,
- `5432` alone is not treated as the API port,
- Codex-owned waves do not silently fall back to Claude,
- degraded OpenAPI/client output cannot be treated as clean canonical proof.

Use Context7 before changing any framework or protocol behavior.

## Fresh Smoke Command

If the audit finds no blocker and targeted tests pass, run:

```powershell
& "C:\Projects\agent-team-v18-codex\v18 test runs\start-m1-hardening-smoke.ps1"
```

If this Codex session cannot access Docker, ask the user to run that command in normal PowerShell and paste the `RUN_DIR`.

## Monitoring Requirements

Once a new `RUN_DIR` exists, monitor:

- `BUILD_LOG.txt`
- `EXIT_CODE.txt`
- `.agent-team/STACK_CONTRACT.json`
- `.agent-team/STATE.json`
- `.agent-team/milestone_progress.json`
- `.agent-team/milestones/milestone-1/REQUIREMENTS.md`
- `.agent-team/artifacts/*milestone-1*`
- `WAVE_A_CONTRACT_CONFLICT.md`
- `AUDIT_INTERFACE.json`
- `AUDIT_REPORT.json` if present

Do not stop at "looks good." Confirm clean success using artifacts.

## Clean Success Definition

Milestone 1 is clean only if:

- the process exits cleanly,
- the milestone has no failed/interrupted wave markers,
- no `WAVE_A_CONTRACT_CONFLICT.md` exists,
- no scope violations exist,
- no `fallback_used=true` appears for Codex-owned waves,
- no degraded contract/client metadata is treated as canonical,
- generated source files were not rolled back,
- build/runtime/Docker evidence exists where configured,
- audit artifacts do not contradict success.

If any of those fail, preserve the run and investigate root cause.

## Stop Criteria

You are done when one of these is true:

1. Milestone 1 is fully successful and clean by the definition above.
2. A real blocker is proven with code/log/artifact evidence and the next required fix is clear.

Do not end with an ambiguous "maybe pass."

