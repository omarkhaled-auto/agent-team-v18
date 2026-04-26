# HANDOFF - M1 fast-forward real simulation before final smoke

**Date:** 2026-04-24
**Repo:** `C:/Projects/agent-team-v18-codex`
**Branch:** `master`
**Status:** planning handoff only. Do not treat this document as proof that M1 is clean.
**Goal:** build and run a no-workaround fast-forward pre-smoke harness that catches deterministic M1 failures quickly, then run one fresh full smoke for the only promotable proof.

---

## Read This First

The next session must investigate everything first. Do not start by coding the harness from this document as if it were already complete truth. This handoff is an implementation-grade plan, not a replacement for discovery.

The user wants speed, but not fake proof. The correct strategy is a proof ladder:

1. deterministic source and artifact checks,
2. a fresh generated scaffold in a disposable workspace,
3. exact Wave C canonical OpenAPI and client generation,
4. deterministic Wave D and Wave T gate simulations,
5. optional tiny real-agent canary if justified,
6. one final full M1 smoke only after the ladder is clean.

The full smoke remains the only promotable end-to-end result. The fast-forward harness is a blocker finder and confidence builder.

---

## Non-Negotiable Rules

- DISCOVERY FIRST. READ BEFORE YOU WRITE.
- Preserve unrelated dirty worktree files. Do not clean, reset, revert, or normalize unrelated changes.
- No workarounds:
  - do not patch a smoke run directory as proof,
  - do not edit generated output to make a run pass,
  - do not weaken gates,
  - do not hide findings,
  - do not skip failed artifacts,
  - do not relabel degraded output as success.
- Fix root causes only in builder/source, so future builds benefit.
- Fast-forward artifacts are diagnostic only. They cannot certify M1 complete.
- If Context7 is needed for a new framework/protocol claim and is blocked, say `BLOCKED` unless the user explicitly waives that exact known Context7 issue.
- The user has explicitly said the current Context7 monthly-quota issue is known and ignored for this M1 effort. Do not spend the session diagnosing account quota. That waiver does not waive OpenAPI/client degradation or invented framework rules.
- Do not invent provider, framework, pnpm, Docker, NestJS, Next.js, Prisma, OpenAPI, or Codex protocol behavior.
- If Docker is unavailable in the Codex shell but works in the user's normal PowerShell, ask the user to launch Docker-dependent proof commands rather than diagnosing Docker as a product blocker.

---

## Current Evidence To Carry Forward

Recent smoke that reached Wave C:

```text
C:/Projects/agent-team-v18-codex/v18 test runs/m1-hardening-smoke-20260424-202155
```

What it proved:

- Context7 monthly quota appeared in the internal research phase, but the user has waived that known issue.
- Stack-contract and scaffold port propagation looked coherent in `STACK_CONTRACT.json`:
  - `package_manager=pnpm`
  - `api_port=4000`
  - `web_port=3000`
  - `ports=[3000,4000,5432]`
  - `infrastructure_template.slots.api_port=4000`
  - `infrastructure_template.slots.web_port=3000`
- Wave B reached runtime health:
  - `GET http://localhost:4000/api/health` returned `200 OK`.
- Wave C failed correctly instead of treating degraded output as canonical.

Wave C failure evidence:

- `milestone-1-wave-C.json` had:
  - `contract_source: regex-extraction`
  - `contract_fidelity: degraded`
  - `client_generator: minimal-ts`
  - `client_fidelity: degraded`
- `BUILD_LOG.txt` showed:
  - `scripts/generate-openapi.ts` could not resolve `@nestjs/core` and `@nestjs/swagger` from the pnpm workspace,
  - `@hey-api/openapi-ts` required a client setting,
  - the milestone failed at Wave C.

Source-side fixes already applied before this handoff:

- `src/agent_team_v15/scaffold_runner.py`
  - generated `scripts/generate-openapi.ts` now uses `createRequire(join(apiRoot, 'package.json'))`,
  - loads root and API `.env.example` values,
  - calls `app.setGlobalPrefix(process.env.API_PREFIX || 'api')`,
  - avoids static imports from `@nestjs/core` and `@nestjs/swagger`,
  - writes web `openapi-ts.config.ts` with `@hey-api/client-fetch`.
- `src/agent_team_v15/openapi_generator.py`
  - `_generate_openapi_ts_client()` passes `-c @hey-api/client-fetch`.
- Related focused tests passed:
  - scaffold, stack-contract, OpenAPI launcher, routing, runtime, observer slices.

Do not blindly trust the above. Re-read the source and artifacts.

---

## Mandatory Discovery For The Next Session

Run first:

```powershell
Set-Location -LiteralPath 'C:\Projects\agent-team-v18-codex'
git status --short
git worktree list
```

Read these docs before edits:

- `docs/plans/2026-04-24-handoff-clean-milestone-success-context7-audit.md`
- `docs/plans/2026-04-23-handoff-m1-wave-d-scope-fallback-hardening.md`
- `docs/plans/2026-04-23-handoff-clean-build-context7-no-guessing.md`
- `docs/plans/2026-04-24-m1-pre-smoke-gate.md`
- this handoff

Inspect these source files before trusting this plan:

- `src/agent_team_v15/stack_contract.py`
- `src/agent_team_v15/milestone_spec_reconciler.py`
- `src/agent_team_v15/scaffold_runner.py`
- `src/agent_team_v15/openapi_generator.py`
- `src/agent_team_v15/wave_executor.py`
- `src/agent_team_v15/provider_router.py`
- `src/agent_team_v15/agents.py`
- `src/agent_team_v15/codex_observer_checks.py`
- `src/agent_team_v15/quality_checks.py`
- `src/agent_team_v15/replay_harness.py`
- `v18 test runs/start-m1-hardening-smoke.ps1`
- `v18 test runs/configs/taskflow-smoke-test-config.yaml`
- `v18 test runs/TASKFLOW_MINI_PRD.md`

Important source facts to verify:

- `WAVE_SEQUENCES["full_stack"]` contains `["A", "A5", "Scaffold", "B", "C", "D", "T", "T5", "E"]`, with feature flags removing disabled waves.
- `_CODEX_WAVES` is exactly `{"A5", "B", "D", "T5"}`.
- Wave T is Claude-only and bypasses provider routing.
- Wave C is Python-owned and fails if canonical generation or canonical client output degrades.
- Wave D is provider-routed Codex unless `wave_d_merged_enabled` changes the mode.
- `replay_harness.py` is currently observer-calibration only. It is not a full M1 stage simulator.

---

## What The Fast-Forward Setup Must Be

Build a new harness. Do not overload the old observer replay harness unless discovery proves that is the cleanest local pattern.

Preferred implementation shape:

- `src/agent_team_v15/m1_fast_forward.py`
  - reusable Python module with small functions for each stage,
  - returns structured results,
  - does not use network except package install/build commands required by the generated app,
  - never patches generated output after a failed stage.
- `scripts/run-m1-fast-forward.ps1`
  - user-facing runner that creates a timestamped disposable workspace under `v18 test runs/`.
- `tests/test_m1_fast_forward.py`
  - fast unit coverage for the harness with fixtures and failure cases.

If the repo already has a better script/test convention after discovery, follow the repo convention. Keep writes scoped.

Output contract:

```text
v18 test runs/m1-fast-forward-YYYYMMDD-HHMMSS/
  PRD.md
  config.yaml
  fast-forward-report.json
  fast-forward.log
  generated/
    .agent-team/
    apps/
    packages/
    contracts/
```

The report must include:

- `success: true | false`
- `failed_gate`
- `failed_reason`
- `workspace`
- `source_commit`
- `dirty_status_summary`
- `context7_waiver: "known monthly quota issue only"`
- per-gate timings
- commands run
- stdout/stderr tails for failed commands
- exact artifact paths checked
- `canonical_openapi: true | false`
- `canonical_client: true | false`
- `degraded_artifacts: []`
- `wave_d_gate: pass | fail | skipped`
- `wave_t_gate: pass | fail | skipped`
- `ready_for_full_smoke: true | false`

`ready_for_full_smoke=true` is allowed only when every deterministic gate passes. It still is not M1 completion proof.

---

## Gate 0 - Source And Config Baseline

Purpose: stop before spending time if the repo is obviously not in the intended state.

Checks:

1. `git status --short` and `git worktree list` recorded in the report.
2. Verify the current smoke config:
   - `v18.provider_routing: true`
   - `provider_map_b: codex`
   - `provider_map_d: codex`
   - `v18.scaffold_enabled: true`
   - `v18.openapi_generation: true`
   - `v18.wave_t_enabled: true`
   - `v18.live_endpoint_check: true`
3. Verify source constants:
   - `_CODEX_WAVES == {"A5", "B", "D", "T5"}`
   - full-stack sequence reaches D, T, and E when flags permit.
4. Verify no test helper or harness uses a patched smoke directory as input proof.

Fail if:

- provider routing is off,
- Wave T is disabled in the target config,
- the smoke script no longer points at `TASKFLOW_MINI_PRD.md` and `taskflow-smoke-test-config.yaml`,
- the harness would have to edit generated output to proceed.

Recommended targeted test slice:

```powershell
python -m pytest tests/test_stack_contract.py tests/test_scaffold_m1_correctness.py tests/test_openapi_launcher_resolution.py tests/test_wave_scope_filter.py
```

---

## Gate 1 - Exact Stack Contract And Scaffold Replay

Purpose: catch port/package/scaffold drift in seconds before any agent or Docker work.

Use the real source paths:

- `derive_stack_contract(...)` from `stack_contract.py`
- `scaffold_config_from_stack_contract(...)` from `scaffold_runner.py`
- `run_scaffolding(...)` from `scaffold_runner.py`
- `load_stack_contract(...)` from `stack_contract.py`

Input strategy:

1. Use `v18 test runs/TASKFLOW_MINI_PRD.md` as PRD input.
2. For M1 requirements, prefer a freshly generated current-builder `REQUIREMENTS.md` if discovery finds a safe non-agent preparation API.
3. If no safe planner-only API exists, use the latest real generated M1 `REQUIREMENTS.md` only as a diagnostic fixture, not proof. The final smoke will still validate planner output.
4. Do not edit the fixture requirements.

Checks:

- Resolved contract:
  - backend `nestjs`
  - frontend `nextjs`
  - ORM `prisma`
  - database `postgresql`
  - package manager `pnpm`
  - layout `apps`
  - API port `4000`
  - web port `3000`
  - postgres port `5432`
- `infrastructure_template.slots` exists after scaffold and matches contract.
- Generated files agree:
  - root `.env.example`
  - `apps/api/.env.example`
  - `apps/web/.env.example`
  - `docker-compose.yml`
  - `apps/api/Dockerfile`
  - `apps/web/Dockerfile`
  - root `package.json`
  - `apps/web/package.json`
  - `scripts/generate-openapi.ts`
  - `apps/web/openapi-ts.config.ts`
- `apps/web/Dockerfile` uses `next start -p 3000`.
- `docker-compose.yml` uses:
  - API `4000:4000`
  - web `3000:3000`
  - `NEXT_PUBLIC_API_URL=http://localhost:4000/api`
  - `INTERNAL_API_URL=http://api:4000/api`
  - healthcheck against `localhost:4000/api/health`
- Root and app scripts use pnpm, not npm.
- Port `5432` alone is never treated as API port.
- `reporter`, `description <= 2000`, and other non-port words/numbers do not become ports.

Fail if any surface disagrees. Do not patch the generated workspace.

Recommended tests:

```powershell
python -m pytest tests/templates/test_scaffold_integration.py tests/test_scaffold_m1_correctness.py tests/test_scaffold_root_package_json.py tests/test_stack_contract.py
```

---

## Gate 2 - Exact Wave C Canonical OpenAPI And Client Replay

Purpose: reproduce the last real blocker quickly with the same Wave C source path.

Use the real function:

```python
from agent_team_v15.openapi_generator import generate_openapi_contracts
```

Run it against the fresh generated workspace, not the failed smoke directory.

Required setup:

1. Install dependencies with the resolved package manager. For this scaffold that must be pnpm.
2. Do not use npm as a fallback.
3. Do not skip install scripts unless the smoke script also does so.
4. If install fails due network or registry, report an environment blocker with command evidence.

Expected command shape inside the harness:

```powershell
pnpm install
```

Then call `generate_openapi_contracts(cwd, milestone)` from Python. Do not manually write `contracts/openapi/current.json`.

Pass criteria:

- `ContractResult.success is True`
- `contract_source == "openapi-script"`
- `contract_fidelity == "canonical"`
- `degradation_reason == ""`
- `client_generator == "openapi-ts"`
- `client_fidelity == "canonical"`
- `client_degradation_reason == ""`
- `contracts/openapi/current.json` exists and is valid JSON.
- `packages/api-client/package.json` exists and names the generated package.
- `packages/api-client` contains TypeScript output from the canonical generator.
- OpenAPI paths include `/api/...`, not bare `/health` when the Nest global prefix is active.
- No generated client fallback files are accepted as canonical.

Negative fixture checks:

- A fixture with static `import { NestFactory } from '@nestjs/core'` in the root script must fail the harness.
- A fixture where `openapi-ts` is invoked without `-c @hey-api/client-fetch` must fail the harness.
- A fixture with `contract_fidelity=degraded` must fail even if client files exist.

Recommended tests:

```powershell
python -m pytest tests/test_openapi_launcher_resolution.py tests/test_scaffold_m1_correctness.py tests/test_scaffold_runner.py
```

---

## Gate 3 - Deterministic Wave D Readiness And Post-D Gate Simulation

Purpose: reduce the risk of discovering D-only failures during the expensive full smoke.

This gate cannot prove Codex will write the right frontend. It can prove the D prompt inputs and post-D enforcement are ready and strict.

Readiness checks before a real D dispatch:

- Wave C artifact is canonical.
- `packages/api-client` exists and has importable/generated exports.
- `apps/web` baseline compiles before D.
- Wave D prompt includes:
  - completed Wave C artifact summary,
  - generated-client-only rule,
  - immutable `packages/api-client/*` rule,
  - no instruction to edit backend/root files,
  - current stack and ports,
  - scope preamble if enabled.
- Provider metadata says D is Codex-owned unless `wave_d_merged_enabled` is intentionally enabled.

Synthetic post-D fixtures:

Create disposable fixture copies of the generated workspace and apply small deterministic changes to test gates. These are gate tests only, not product proof.

Positive D fixture:

- add a minimal frontend page/component that imports from `packages/api-client` or the generated package name,
- does not edit `packages/api-client`,
- does not create or modify backend/root files,
- uses no manual `/api` fetch or axios,
- preserves i18n/RTL baseline if applicable,
- compiles.

Negative D fixtures must fail:

- backend write in Wave D, for example `apps/api/src/main.ts`,
- root `.env.example` write in Wave D,
- `packages/api-client/index.ts` modification in Wave D,
- manual `fetch('/api/...')` or axios for generated-client-covered endpoints,
- zero generated-client imports in frontend source,
- client-gap-only page that renders an error shell instead of feature UI,
- invalid locale or Google font subset,
- Next build/typecheck failure.

Use existing source where possible:

- `build_wave_d_prompt(...)` in `agents.py`
- `_apply_post_wave_scope_validation(...)` in `wave_executor.py`
- `find_forbidden_paths(...)` in `codex_observer_checks.py`
- `run_frontend_hallucination_scan(...)` in `quality_checks.py`
- `scan_generated_client_import_usage(...)` in `quality_checks.py` for WIRING-CLIENT-001
- `_run_wave_compile(...)` or compile profile path if discovery shows it can be called cleanly.

Fail if:

- D readiness cannot see canonical client output,
- D prompt is missing the immutable/generated-client rules,
- a negative fixture passes,
- a positive fixture fails due harness bug.

Recommended tests:

```powershell
python -m pytest tests/test_wave_d_merged.py tests/test_wave_d_fallback_provider_neutral.py tests/test_wave_scope_filter.py tests/test_compile_fix_codex.py tests/test_quality_checks.py tests/test_codex_observer_checks.py
```

---

## Gate 4 - Deterministic Wave T And T.5 Gate Simulation

Purpose: avoid reaching T for the first time in the full smoke.

Wave T is Claude-owned. Do not pretend synthetic tests are equivalent to Claude writing correct tests. This gate verifies the orchestration, telemetry, summary, and audit bridge.

Readiness checks:

- Full-stack sequence includes T before E when `wave_t_enabled=True`.
- Wave T prompt includes:
  - completed B/C/D artifact summaries,
  - Wave C contract/client context,
  - Wave D frontend context,
  - acceptance criteria,
  - the locked "tests are the specification" principle,
  - backend and frontend test inventories for full-stack milestones,
  - required `wave-t-summary` JSON block instructions.
- Wave T is Claude-only in `WaveResult.provider`, regardless of provider map.
- Wave T timeout and watchdog telemetry are surfaced.

Synthetic Wave T execution fixtures:

- positive fixture: fake Claude writes backend and frontend test files, node test runners report pass, telemetry records `tests_written > 0`.
- persistent failure fixture: node test runners keep failing, Wave T records `TEST-FAIL` finding and `structural_findings_logged=1`.
- compile-break fixture: Wave T fix iteration writes broken app code, compile check fails, rollback removes the broken file and writes `WAVE-T-ROLLBACK`.
- timeout fixture: watchdog timeout marks `wave_timed_out=true` and writes a hang report path.

T.5 readiness if enabled:

- `collect_wave_t_test_files(...)` finds Wave T test files.
- `build_wave_t5_prompt(...)` includes tests, source, ACs, and JSON schema.
- invalid T.5 output does not become success.
- critical T.5 gaps block or loop back according to config.
- when T.5 is disabled, skip status is explicit and not confused with success.

Audit bridge checks:

- `persist_wave_findings_for_audit(...)` always writes structured `WAVE_FINDINGS.json`.
- If Wave D fails before T, `wave_t_status` is `skipped` and names Wave D.
- If Wave T runs and finds failures, findings are preserved for audit.
- If Wave T is disabled, status is `disabled`.
- Empty findings with no T marker are not acceptable.
- Investigate whether the code actually persists or parses the fenced `wave-t-summary` JSON block. Current source evidence may only show prompt/audit instructions plus WaveResult telemetry. If no parser/persistence exists, treat that as a proof gap to fix before claiming AC-level Wave T coverage is machine-checkable.

Recommended tests:

```powershell
python -m pytest tests/test_v18_wave_t.py tests/test_wave_t_findings.py tests/test_wave_t5.py tests/test_wave_e_t5_injection.py tests/test_test_auditor_t5_injection.py tests/test_sdk_sub_agent_watchdog.py
```

---

## Gate 5 - Run-Directory Artifact Auditor

Purpose: after any fast-forward, canary, or smoke, decide quickly whether the artifact set is coherent.

Implement or reuse a read-only run-dir auditor. It must never modify the run directory.

Inputs:

```text
RUN_DIR
BUILD_LOG.txt
BUILD_ERR.txt
EXIT_CODE.txt
.agent-team/STACK_CONTRACT.json
.agent-team/STATE.json
.agent-team/milestone_progress.json
.agent-team/milestones/milestone-1/REQUIREMENTS.md
.agent-team/artifacts/*milestone-1*
.agent-team/telemetry/*milestone-1*
.agent-team/milestones/milestone-1/WAVE_FINDINGS.json
.agent-team/AUDIT_INTERFACE.json
.agent-team/AUDIT_REPORT.json
WAVE_A_CONTRACT_CONFLICT.md
```

Fail conditions:

- missing final bookkeeping for a completed run,
- non-zero `EXIT_CODE.txt`,
- `STATE.json` says failed,
- `milestone_progress.json` has `interrupted_milestone`,
- any wave artifact or telemetry has `success=false`,
- any `wave_timed_out=true`,
- any `fallback_used=true` for Codex-owned waves,
- Claude fallback on Codex-owned Wave B/D/T5,
- `WAVE_A_CONTRACT_CONFLICT.md` exists,
- non-Wave-A `scope_violations` non-empty,
- Wave C degraded contract/client fields,
- OpenAPI/client output exists but is marked degraded,
- root bookkeeping files counted as wave outputs,
- package manager drift to npm,
- port drift across requirements, stack contract, env, compose, Dockerfiles, web scripts, or Wave B infra metadata,
- API port inferred as `5432`,
- audit artifacts contradict success,
- `WAVE_FINDINGS.json` says Wave T skipped when the sequence expected T and no upstream failure explains the skip.

Warn but do not fail by itself:

- Context7 monthly quota text, only if it is the known waived issue and no framework/protocol fabrication follows.
- Docker unavailable in the Codex shell, if the user's normal PowerShell Docker preflight succeeds.

---

## Gate 6 - Optional Tiny Real-Agent Canary

Purpose: exercise D/T transport and provider routing faster than full M1.

This is optional, not a substitute for M1. Run it only if deterministic gates pass and there is still concern that D/T transport will fail before full smoke.

Canary shape:

- one tiny PRD,
- same stack: NestJS, Next.js, Prisma, PostgreSQL, pnpm,
- one health or notes page,
- one API endpoint,
- generated client required,
- one frontend page using the client,
- Wave T enabled.

Rules:

- Use the same builder source and same no-workaround gates.
- Do not reduce or disable D/T checks.
- Do not use canary success as M1 completion proof.
- If canary fails due a real source bug, fix source and rerun deterministic gates before full M1.

Skip the canary if it would burn more time than going straight to M1 after deterministic gates are clean.

---

## Gate 7 - Final Full M1 Smoke

Only run after:

- Gate 0 through Gate 5 pass,
- optional canary either passes or is explicitly skipped with rationale,
- no unresolved deterministic blocker remains.

Start command:

```powershell
Set-Location -LiteralPath 'C:\Projects\agent-team-v18-codex'
& 'C:\Projects\agent-team-v18-codex\v18 test runs\start-m1-hardening-smoke.ps1'
```

If Codex shell cannot access Docker but normal PowerShell can, have the user run the command and provide:

```text
RUN_DIR=...
LOG=...
ERR=...
```

Monitor:

- `BUILD_LOG.txt`
- `BUILD_ERR.txt`
- `EXIT_CODE.txt`
- `.agent-team/STACK_CONTRACT.json`
- `.agent-team/STATE.json`
- `.agent-team/milestone_progress.json`
- `.agent-team/milestones/milestone-1/REQUIREMENTS.md`
- `.agent-team/artifacts/*milestone-1*`
- `.agent-team/telemetry/*milestone-1*`
- `.agent-team/milestones/milestone-1/WAVE_FINDINGS.json`
- `WAVE_A_CONTRACT_CONFLICT.md`
- `AUDIT_INTERFACE.json`
- `AUDIT_REPORT.json`

Clean success requires:

- `EXIT_CODE.txt` is `0`,
- M1 state is complete/successful,
- no interrupted milestone,
- all expected waves completed or have explicit disabled/skipped statuses matching config,
- no failed wave markers,
- no Wave A conflict,
- no fallback on Codex-owned waves,
- no degraded OpenAPI/client,
- runtime evidence exists where configured,
- Docker/build/runtime evidence exists where configured,
- stack contract, requirements, compose, env files, Dockerfiles, package scripts, and Wave B metadata agree on ports,
- audit artifacts do not contradict success,
- Wave T status is completed if expected,
- no high/critical deterministic findings remain unresolved.

Stop only when:

- M1 is fully successful and clean by evidence, or
- a real blocker is proven with code/log/artifact evidence.

---

## Exact Test Ladder Before Full Smoke

Run the focused source tests after implementing the fast-forward harness and before any smoke:

```powershell
python -m pytest tests/test_h3e_contract_guard.py tests/test_spec_reconciler_and_verifier.py tests/templates/test_scaffold_integration.py tests/test_stack_contract.py tests/test_scaffold_m1_correctness.py tests/test_scaffold_root_package_json.py tests/test_h1a_ownership_enforcer.py tests/templates/test_legacy_nonregression.py
```

```powershell
python -m pytest tests/test_checkpoint_walker_skip.py tests/test_stack_contract.py tests/test_wave_scope_filter.py tests/test_provider_routing.py tests/test_compile_fix_codex.py tests/test_a10_compile_fix.py tests/test_runtime_verification_block.py tests/test_openapi_launcher_resolution.py tests/test_v18_phase2_wave_engine.py tests/test_agents.py tests/test_codex_observer_checks.py
```

Add the D/T harness tests:

```powershell
python -m pytest tests/test_v18_wave_t.py tests/test_wave_t_findings.py tests/test_wave_t5.py tests/test_wave_e_t5_injection.py tests/test_test_auditor_t5_injection.py tests/test_sdk_sub_agent_watchdog.py tests/test_wave_d_merged.py tests/test_wave_d_fallback_provider_neutral.py
```

Then run the new fast-forward command, expected shape:

```powershell
& .\scripts\run-m1-fast-forward.ps1
```

If the harness is implemented as Python only, expected shape:

```powershell
python -m agent_team_v15.m1_fast_forward --repo 'C:\Projects\agent-team-v18-codex'
```

Pick one public command and document it in the harness report. Do not leave the next operator guessing.

---

## Design Constraints For The Harness

- The harness must be read-only against existing smoke run directories.
- It may create new disposable workspaces under `v18 test runs/`.
- It may delete only its own disposable workspace if explicitly requested. Default should preserve artifacts.
- It must use structured parsers for JSON/YAML where available.
- It must record exact commands and their exit codes.
- It must fail closed on missing artifacts.
- It must not silently continue after a failed gate.
- It must distinguish:
  - source-unit proof,
  - deterministic generated-workspace proof,
  - synthetic D/T gate proof,
  - real-agent canary proof,
  - full M1 smoke proof.
- It must not call a diagnostic fixture "promotable".

---

## Expected High-Value Failure Classes This Will Catch Fast

- stack-contract port drift,
- pnpm/npm package-manager drift,
- `5432` misclassified as API port,
- stale `STATE.json` stack-contract contradiction,
- generated scaffold and infra-template mismatch,
- root OpenAPI script unable to resolve API workspace dependencies,
- OpenAPI missing `/api` prefix,
- `openapi-ts` missing client selection,
- regex/minimal generated output treated as canonical,
- Wave D prompt missing immutable API-client rule,
- Wave D backend/root writes,
- Wave D manual HTTP layer,
- Wave D zero generated-client imports,
- invalid Next/i18n/font output,
- Wave T skipped without explicit upstream failure,
- Wave T failures lost before audit,
- T.5 critical gaps not enforcing the configured loop/block,
- audit artifacts contradicting success,
- build bookkeeping files counted as wave outputs.

---

## What Not To Do

- Do not rerun the full smoke repeatedly as the primary debugger.
- Do not patch `v18 test runs/m1-hardening-smoke-20260424-202155`.
- Do not use old failed run output as clean proof.
- Do not edit generated files in the fast-forward workspace to move a gate along.
- Do not disable Wave T just to reach E.
- Do not accept `minimal-ts` client output for M1.
- Do not accept `regex-extraction` OpenAPI output for M1.
- Do not downgrade Wave D scope violations to warnings.
- Do not ignore `WAVE_FINDINGS.json`.
- Do not conflate Docker Desktop/WSL shell integration issues with builder product blockers unless logs prove the builder is at fault.

---

## Final Reporting Template For The Next Session

When done, report:

```text
Fast-forward workspace:
Fast-forward report:
Gates passed:
Gates failed:
Source tests run:
Harness tests run:
Full smoke RUN_DIR:
Full smoke EXIT_CODE:
M1 state:
Wave summary:
OpenAPI/client fidelity:
D/T status:
Audit status:
Remaining blockers:
```

If clean:

- say M1 is clean only if the full smoke artifacts prove it.

If blocked:

- name the exact blocker,
- cite source/log/artifact evidence,
- say whether the blocker is deterministic harness-only, real canary, or full smoke.
